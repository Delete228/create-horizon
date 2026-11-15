#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Compare ordinary waterlogged Chute transit and side Hopper input."""

import argparse
import json
from pathlib import Path
import shutil
import tempfile
import time

from bearing_native_checks import Batch
from burner_heat_java_checks import items, number
from chain_drive_checks import Native, Original, xyz
from common import PINS, ROOT
from fluid_tank_checks import click
from funnel_checks import block, put
from native_check_session import NativeCheckSession, wait_loaded
import reference_java as java
from reference_java import BASE, CREATE_SHA256


X, Y, Z = 1517, 195, 503
AREA = (X-4, Y-6, Z-2, X+4, Y+5, Z+24)
CAMERA = (X+2.5, Y+1, Z+10.5)
# Use separate columns and distinct Java block-entity map hash slots within
# each lane, so saved tag iteration order cannot vary their ticker order.
CASES = {'barrel': (Z+1, 'minecraft:iron_ingot', 23), 'hopper': (Z+21, 'minecraft:stick', 1)}
TICKS, RESTART = 35, 4


def positions(name):
    z = CASES[name][0]
    source = (X, Y+1, z) if name == 'barrel' else (X-1, Y, z)
    return (source, (X, Y, z), (X, Y-1, z), (X, Y-2, z))


POINTS = [pos for name in CASES for pos in positions(name)]
CHUTES = [pos for name in CASES for pos in positions(name)[1:3]]


def setup(command):
    command('fill ' + xyz(AREA) + ' minecraft:air')
    for name, (z, _, _) in CASES.items():
        source, upper, lower, out = positions(name)
        for dx, dz in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            command(f'fill {X+dx} {Y-2} {z+dz} {X+dx} {Y+1} {z+dz} minecraft:stone')
        put(command, source, 'minecraft:barrel' if name == 'barrel' else 'minecraft:hopper[facing=east]')
        put(command, out, 'minecraft:barrel')
        for pos in (upper, lower):
            put(command, pos, 'create:chute[facing=down,shape=window,waterlogged=true]')


def seed(command):
    for index, (name, (_, item, count)) in enumerate(CASES.items(), 1):
        command(f'item replace block {xyz(positions(name)[0])} container.0 with '
                f'{item}[minecraft:custom_data={{wet_chute:{index}}}] {count}')


def row(blocks):
    result = {}
    for index, (name, (_, item, count)) in enumerate(CASES.items(), 1):
        lane = blocks[4*(index-1):4*index]
        amounts = [items(block['nbt'], field).get(item, 0)
                   for block, field in zip(lane, ('Items', 'Item', 'Item', 'Items'), strict=True)]
        assert sum(amounts) == count, (name, amounts)
        offsets = []
        for i, (amount, block) in enumerate(zip(amounts, lane, strict=True)):
            if amount:
                assert number(block, 'wet_chute') == index, block
            if i in (1, 2):
                if 'properties' in block:
                    assert block['properties']['waterlogged'] == 'true', block
                offsets.append(number(block, 'ItemPosition') if amount else None)
        result[name] = dict(amounts=amounts, offsets=offsets)
    return result


def java_run(work, cold):
    host = Original()
    initial = host.call('state', {})
    assert initial['ready'] and initial['data_version'] == 3955
    assert json.loads((BASE / 'manifest.json').read_text())['create_sha256'] == CREATE_SHA256

    def wait_for_columns():
        for _ in range(35):
            probes = [host.command(f'execute if loaded {xyz(pos)}') for pos in (POINTS[0], POINTS[-1])]
            if all('Test passed' in reply['messages'] for reply in probes):
                return
            time.sleep(.15)
        raise AssertionError('Wet Chute fixture columns did not load')

    def advance(ticks):
        response = host.call('observe_ticks', {'positions': POINTS, 'ticks': ticks})
        return [row(sample['blocks']) for sample in response['samples']]

    try:
        host.call('camera', {'position': CAMERA})
        host.call('tick', {'frozen': False})
        wait_for_columns()
        host.call('tick', {'frozen': True})
        setup(host.command)
        host.call('observe_ticks', {'positions': POINTS, 'ticks': 6})
        seed(host.command)
        if not cold:
            return advance(TICKS)

        before = advance(RESTART)
        assert before[-1]['barrel']['amounts'][1] == 16 and before[-1]['hopper']['amounts'][1] == 1
        # Keep the fixture outside the spawning player's ticking distance until
        # the restarted private Java world is frozen and ready for the replay.
        host.call('camera', {'position': (CAMERA[0]+256, CAMERA[1], CAMERA[2])})
        host.call('quit', {})
        deadline = time.monotonic() + 55
        while java.process_alive(BASE):
            assert time.monotonic() < deadline, 'Isolated Java client failed to save and exit'
            time.sleep(.15)
        assert java.launch(BASE)['ready']
        host.call('tick', {'frozen': True})
        host.call('camera', {'position': CAMERA})
        wait_for_columns()
        saved = row([host.call('block', {'pos': pos}) for pos in POINTS])
        assert saved == before[-1], (saved, before[-1])
        return before + advance(TICKS - RESTART)
    finally:
        host.command('fill ' + xyz(AREA) + ' minecraft:air')
        host.call('camera', {k: initial[k] for k in ('position', 'yaw', 'pitch')})
        host.call('tick', {'frozen': initial['server']['frozen']})
        (work / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')


def native_run(session, cold):
    camera = (X+2, Y+1, Z+10)

    def sample(batch):
        for pos in POINTS:
            batch.data(pos)

    def record(batch, ticks):
        for _ in range(ticks):
            batch.tick()
            sample(batch)

    def run(batch, label, observations):
        for pos in CHUTES:
            batch.expect(pos, 'create:chute[waterlogged=true]')
        raw = batch.run(session, label)
        end = len(POINTS) * observations
        assert len(raw) == end + len(CHUTES), len(raw)
        assert all('bearing_check' in state for state in raw[end:]), raw[end:]
        return [row([{'nbt': text} for text in raw[i:i+len(POINTS)]])
                for i in range(0, end, len(POINTS))]

    batch = Batch()
    batch.load(camera)
    setup(batch.command)
    batch.tick(6)
    seed(batch.command)
    before = []
    if cold:
        record(batch, RESTART)
        before = run(batch, 'wet-chutes-before-restart', RESTART)
        assert before[-1]['barrel']['amounts'][1] == 16 and before[-1]['hopper']['amounts'][1] == 1
        batch = Batch()
        batch.load(camera)
        sample(batch)
    rest = TICKS - RESTART if cold else TICKS
    record(batch, rest)
    after = run(batch, 'wet-chutes', rest + int(cold))
    if cold:
        assert after[0] == before[-1], (after[0], before[-1])
        after = after[1:]
    return before + after


def placement_cases(host, work):
    target = (X, Y, Z+1)
    support = (X, Y, Z)
    backup = (X+3, Y-1, Z+1)
    command = host.command
    command('fill ' + xyz(AREA) + ' minecraft:air')
    command(f'fill {X-2} {Y-2} {Z} {X+2} {Y-2} {Z+6} minecraft:stone')
    put(command, support, 'minecraft:stone')
    put(command, backup, 'minecraft:barrel')
    command(f'item replace block {xyz(backup)} container.0 from entity @s weapon.mainhand')
    result = {}
    try:
        for wet in (False, True):
            name = 'source' if wet else 'dry'
            put(command, target, 'minecraft:water[level=0]' if wet else 'minecraft:air')
            click(host, work, name, 'create:chute', feet=(X+.5, Y-1, Z+3.25),
                  aim=(X+.5, Y+.25, Z+1), pos=support, face='south')
            placed = block(host, target)
            result[name] = dict(id=placed['id'],
                                properties={key: value.lower() for key, value in placed['properties'].items()})
    finally:
        command(f'item replace entity @s weapon.mainhand from block {xyz(backup)} container.0')
    return result


def java_placement(work):
    host = Original()
    initial = host.call('state', {})
    assert initial['ready'] and initial['data_version'] == 3955
    assert json.loads((BASE / 'manifest.json').read_text())['create_sha256'] == CREATE_SHA256
    mode = next(mode for mode in ('creative', 'spectator', 'survival', 'adventure')
                if any('Test passed' in line for line in
                       host.command(f'execute if entity @s[gamemode={mode}]')['messages']))
    host.call('tick', {'frozen': True})
    try:
        host.command('gamemode creative')
        host.call('camera', {'position': CAMERA})
        host.call('observe_ticks', {'positions': [(X, Y, Z)], 'ticks': 24})
        return placement_cases(host, work)
    finally:
        host.command('fill ' + xyz(AREA) + ' minecraft:air')
        host.call('observe_ticks', {'positions': [(X, Y, Z+1)], 'ticks': 2})
        time.sleep(.35)
        host.command('gamemode ' + mode)
        host.call('camera', {k: initial[k] for k in ('position', 'yaw', 'pitch')})
        host.call('tick', {'frozen': initial['server']['frozen']})
        (work / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')


def native_placement(session):
    with session:
        host = Native(session)
        host.command(f'tp @s {xyz(CAMERA)}')
        wait_loaded(session.call, [(X, Y, Z)])
        host.command('tick freeze')
        return placement_cases(host, session.scratch)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--placement', action='store_true')
    mode.add_argument('--cold', action='store_true')
    for name in ('game', 'resources', 'ctl', 'create-jar', 'reference'):
        parser.add_argument('--' + name, type=Path)
    args = parser.parse_args()
    if args.game:
        if not all((args.resources, args.ctl, args.create_jar, args.reference)):
            parser.error('Horizon requires --resources, --ctl, --create-jar and --reference')
        reference = json.loads(args.reference.read_text())
        assert reference['passed'] and reference['create'] == PINS['create_revision']
        assert reference.get('placement', False) == args.placement
        assert reference.get('cold', False) == args.cold
        session = NativeCheckSession(args.game, args.resources, args.ctl, args.create_jar,
                                     name='wet-chute-native', world='WetChute', graphics=args.placement)
        session.env.pop('CREATE_HORIZON_PARTICLE_TRACE', None)
        work = session.scratch
        try:
            trace = native_placement(session) if args.placement else native_run(session, args.cold)
        finally:
            session.control_temp.cleanup()
            for folder in (session.resources, work / '.horizon-cache', work / 'horizon-mods'):
                shutil.rmtree(folder, ignore_errors=True)
        (work / 'observed.json').write_text(json.dumps(trace, indent=2) + '\n')
        if args.placement:
            assert trace == reference['trace'], (trace, reference['trace'])
        else:
            for i, (got, expected) in enumerate(zip(trace, reference['trace'], strict=True), 1):
                assert got == expected, (i, got, expected)
    else:
        work = Path(tempfile.mkdtemp(prefix='wet-chute-java-', dir=ROOT / '.local'))
        trace = java_placement(work) if args.placement else java_run(work, args.cold)
    if args.placement:
        expected = {name: dict(id='create:chute', properties=dict(facing='down', shape='normal', waterlogged=wet))
                    for name, wet in (('dry', 'false'), ('source', 'true'))}
        assert trace == expected, trace
    else:
        assert all(trace[-1][name]['amounts'] == [0, 0, 0, count]
                   for name, (_, _, count) in CASES.items()), trace[-1]
    receipt = work / 'result.json'
    receipt.write_text(json.dumps(dict(passed=True, create=PINS['create_revision'], placement=args.placement,
                                       cold=args.cold, trace=trace), indent=2) + '\n')
    print(receipt)


if __name__ == '__main__':
    main()
