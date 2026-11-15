#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Observe a top Fan's vertical Chute suction, clearance, and cargo custody."""

import argparse
import json
from pathlib import Path
import shutil
import tempfile
import time

from bearing_native_checks import Batch
from burner_heat_java_checks import items, number
from chain_drive_checks import Original, xyz
from common import PINS, ROOT
from funnel_checks import put
from native_check_session import NativeCheckSession
from reference_java import BASE, CREATE_SHA256


X, Y, Z = 1240, 176, 362
AREA = (X-3, Y-7, Z-3, X+5, Y+7, Z+15)
CAMERA = (X+4.5, Y+1, Z+6.5)
OPEN = (X, Y, Z)
SHALLOW = (X, Y, Z+4)
LOWER = (X, Y, Z+8)
UPPER = (X, Y+1, Z+8)
BARREL = (X, Y-1, Z+8)
SPLIT = [(X, Y, Z+12), (X, Y+1, Z+12), (X+1, Y+1, Z+12), (X+1, Y+2, Z+12)]
POINTS = [OPEN, SHALLOW, LOWER, UPPER, BARREL, *SPLIT]
ITEMS = {'open': ('chute_suction_open', OPEN, -2.25, 3),
         'near': ('chute_suction_near', SHALLOW, -1.625, 2),
         'far': ('chute_suction_far', SHALLOW, -2.75, 5)}
CARGO = 'minecraft:stick'


def fan_above(command, chute, rpm=128):
    x, y, z = chute
    put(command, (x, y+2, z), f'create:creative_motor[facing=down]{{ScrollValue:{-rpm}}}')
    put(command, (x, y+1, z), 'create:encased_fan[facing=down]')


def setup(command, wet=False):
    command('fill ' + xyz(AREA) + ' minecraft:air')
    command(f'fill {X-3} {Y-6} {Z-3} {X+5} {Y-6} {Z+15} minecraft:smooth_stone')
    chute = f'create:chute[facing=down,shape=window,waterlogged={str(wet).lower()}]'
    for pos in (OPEN, SHALLOW, UPPER):
        fan_above(command, pos)
        put(command, pos, chute)
    put(command, LOWER, chute)
    put(command, BARREL, 'minecraft:barrel')
    put(command, (X, Y-2, Z+4), 'minecraft:oak_trapdoor[half=bottom,open=false]')

    put(command, (X, Y-2, Z+12), 'create:creative_motor[facing=up]{ScrollValue:128}')
    put(command, (X, Y-1, Z+12), 'create:encased_fan[facing=up]')
    for index, pos in enumerate(SPLIT):
        face = 'east' if index == 2 else 'down'
        put(command, pos, f'create:chute[facing={face},shape=normal]')


def seed(command, wet):
    # In the wet comparison, use the contained Barrel stack. Open-water
    # motion of loose item entities is a separate vanilla physics boundary.
    loose = () if wet else ITEMS.values()
    for index, (tag, (x, y, z), dy, count) in enumerate(loose, 1):
        command(f'summon minecraft:item {x+.5} {y+dy} {z+.5} '
                f'{{Tags:["{tag}"],NoGravity:1b,Motion:[0d,0d,0d],PickupDelay:32767s,'
                f'Item:{{id:"{CARGO}",count:{count},components:{{"minecraft:custom_data":'
                f'{{suction_probe:{index}}}' + '}}}')
    command(f'item replace block {xyz(BARREL)} container.0 with '
            f'{CARGO}[minecraft:custom_data={{suction_probe:4}}] 7')


def entity_query(tag):
    return f'data get entity @e[type=minecraft:item,tag={tag},limit=1]'


def row(blocks, entities):
    chutes = []
    for block in blocks[:4]:
        count = items(block['nbt'], 'Item').get(CARGO, 0)
        chutes.append(dict(count=count, offset=number(block, 'ItemPosition') if count else None,
                           pull=number(block, 'Pull'), push=number(block, 'Push'),
                           distance=number(block, 'BottomAirFlowDistance'),
                           probe=number(block, 'suction_probe') if count else None))
    barrel = blocks[4]
    count = items(barrel['nbt'], 'Items').get(CARGO, 0)
    split = [{'push': number(block, 'Push'), 'pull': number(block, 'Pull'),
              'facing': block['properties']['facing']} for block in blocks[5:]]
    return dict(chutes=chutes, barrel=dict(count=count, probe=number(barrel, 'suction_probe') if count else None),
                entities={name: items(raw, 'Item').get(CARGO, 0) if 'Item:' in raw else 0
                          for name, raw in zip(ITEMS, entities, strict=True)}, split=split)


def java_run(work, wet):
    host = Original()
    initial = host.call('state', {})
    assert initial['ready'] and initial['data_version'] == 3955
    assert json.loads((BASE / 'manifest.json').read_text())['create_sha256'] == CREATE_SHA256

    def advance(ticks):
        return host.call('observe_ticks', {'positions': POINTS, 'ticks': ticks})['samples'][-1]['blocks']

    def sample():
        blocks = advance(1)
        if wet:
            assert all(block['properties']['waterlogged'] == 'true' for block in blocks[:4])
        entities = [' '.join(host.command(entity_query(tag))['messages']) for tag, *_ in ITEMS.values()]
        return row(blocks, entities)

    try:
        host.call('camera', {'position': CAMERA})
        host.call('tick', {'frozen': False})
        for _ in range(25):
            result = host.command(f'execute if loaded {X} {Y} {Z+12}')
            if any('Test passed' in line for line in result['messages']):
                break
            time.sleep(.15)
        else:
            raise AssertionError('Chute suction fixture column did not load')
        host.command('tick freeze')
        setup(host.command, wet)
        advance(6)
        seed(host.command, wet)
        suction = [sample() for _ in range(18)]
        put(host.command, (X, Y+3, Z+8), 'minecraft:air')
        release = [sample() for _ in range(12)]
        return suction + release
    finally:
        for tag, *_ in ITEMS.values():
            host.command(f'kill @e[type=minecraft:item,tag={tag}]')
        host.command('fill ' + xyz(AREA) + ' minecraft:air')
        host.call('camera', {k: initial[k] for k in ('position', 'yaw', 'pitch')})
        host.call('tick', {'frozen': initial['server']['frozen']})
        (work / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')


def native_run(session, cold, wet):
    positions = POINTS[:5]
    width = len(positions) + len(ITEMS)

    def sample(batch):
        for pos in positions:
            batch.data(pos)
        for tag, *_ in ITEMS.values():
            batch.command(entity_query(tag), True)

    def record(batch, ticks):
        for _ in range(ticks):
            batch.tick()
            sample(batch)

    def run(batch, name):
        chutes = positions[:4] if wet else []
        for pos in chutes:
            batch.expect(pos, 'create:chute[waterlogged=true]')
        raw = batch.run(session, name)
        if chutes:
            assert all('bearing_check' in reply for reply in raw[-len(chutes):])
            raw = raw[:-len(chutes)]
        assert len(raw) % width == 0, raw
        return [row([{'nbt': nbt} for nbt in raw[i:i+len(positions)]], raw[i+len(positions):i+width])
                for i in range(0, len(raw), width)]

    batch = Batch()
    batch.load((X+4, Y, Z+6))
    setup(batch.command, wet)
    batch.tick(6)
    seed(batch.command, wet)
    record(batch, 18)
    first = []
    if cold:
        first = run(batch, 'held-before-restart')
        batch = Batch()
        batch.load((X+4, Y, Z+6))
        sample(batch)
    put(batch.command, (X, Y+3, Z+8), 'minecraft:air')
    record(batch, 12)
    final = run(batch, 'suction')
    if cold:
        assert first[-1] == final[0], (first[-1], final[0])
        final = final[1:]
    return first + final


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cold', action='store_true')
    parser.add_argument('--wet', action='store_true')
    for name in ('game', 'resources', 'ctl', 'create-jar', 'reference'):
        parser.add_argument('--' + name, type=Path)
    args = parser.parse_args()
    if args.game:
        if not all((args.resources, args.ctl, args.create_jar, args.reference)):
            parser.error('Horizon requires --resources, --ctl, --create-jar and --reference')
        reference = json.loads(args.reference.read_text())
        assert reference['passed'] and reference['create'] == PINS['create_revision']
        assert reference.get('wet', False) == args.wet
        session = NativeCheckSession(args.game, args.resources, args.ctl, args.create_jar,
                                     name='chute-suction-native', world='ChuteSuction', graphics=False)
        session.env.pop('CREATE_HORIZON_PARTICLE_TRACE', None)
        session.env.pop('CREATE_HORIZON_TRACE_POSES', None)
        work = session.scratch
        try:
            trace = native_run(session, args.cold, args.wet)
        finally:
            session.control_temp.cleanup()
            for folder in (session.resources, work / '.horizon-cache', work / 'horizon-mods'):
                shutil.rmtree(folder, ignore_errors=True)
        (work / 'observed.json').write_text(json.dumps(trace, indent=2) + '\n')
        for i, (got, expected) in enumerate(zip(trace, reference['trace'], strict=True), 1):
            # The branch is a Java topology observation outside straight lift coverage.
            assert got == (expected | {'split': []}), (i, got, expected)
    else:
        if args.cold:
            parser.error('--cold restarts the native client')
        work = Path(tempfile.mkdtemp(prefix='chute-suction-java-', dir=ROOT / '.local'))
        trace = java_run(work, args.wet)
        assert [part['push'] for part in trace[0]['split']] == [128, 64, 64, 64], trace[0]
    assert [chute['distance'] for chute in trace[0]['chutes']] == [3, 1.84375, 0, 0], trace[0]
    assert [chute['offset'] for chute in trace[0]['chutes']] == [
        None if args.wet else -2.025, None if args.wet else -1.4, 0, None], trace[0]
    assert all(state['entities'] == dict(open=0, near=0, far=0 if args.wet else 5) for state in trace), trace
    assert trace[17]['chutes'][3]['count'] == 7 and trace[17]['chutes'][3]['offset'] == .5, trace[17]
    assert trace[-1]['barrel'] == dict(count=7, probe=4), trace[-1]
    receipt = work / 'result.json'
    receipt.write_text(json.dumps(dict(passed=True, create=PINS['create_revision'],
                                       cold=args.cold, wet=args.wet, trace=trace), indent=2) + '\n')
    print(receipt)


if __name__ == '__main__':
    main()
