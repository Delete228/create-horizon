#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Compare a top Fan extracting marked cargo from stopped horizontal Belts."""

import argparse
import json
from pathlib import Path
import shutil
import tempfile
import time

from bearing_native_checks import Batch
from burner_heat_java_checks import items, number
from chain_drive_checks import Original, xyz
from chute_suction_checks import fan_above
from common import PINS, ROOT
from funnel_checks import put
from native_check_session import NativeCheckSession
from reference_java import BASE, CREATE_SHA256


X, Y, Z = 1333, 182, 429
AREA = (X-4, Y-6, Z-2, X+5, Y+5, Z+10)
CAMERA = (X+2.5, Y+1, Z+4.5)
CASES = {'direct': (Z, 1), 'gap': (Z+4, 3), 'blocked': (Z+8, 2)}
POINTS = [pos for z, depth in CASES.values() for pos in [(X-1, Y-depth, z), (X, Y, z)]]
CARGO = 'minecraft:stick'
EDGE = 'minecraft:iron_ingot'
TICKS = 10


def setup(command):
    command('fill ' + xyz(AREA) + ' minecraft:air')
    for name, (z, depth) in CASES.items():
        fan_above(command, (X, Y, z))
        put(command, (X, Y, z), 'create:chute[facing=down,shape=window]')
        for i, part in enumerate(('start', 'middle', 'middle', 'end')):
            put(command, (X-1+i, Y-depth, z), f'create:belt[facing=east,slope=horizontal,part={part}]')
        if name == 'blocked':
            put(command, (X, Y-1, z), 'minecraft:stone')


def seed(command):
    for index, (z, depth) in enumerate(CASES.values(), 1):
        def record(item, count, pos, tag):
            return (f'{{Item:{{id:"{item}",count:{count},components:{{"minecraft:custom_data":'
                    f'{{chute_belt_suction:{tag}}}}}}},Pos:{pos}f,PrevPos:{pos}f,InSegment:1,InDirection:5,Angle:180}}')

        records = ','.join((record(CARGO, 7, 1.5, index), record(EDGE, 3, 2.0, index)))
        command(f'data merge block {X-1} {Y-depth} {z} {{Inventory:{{PositiveOrder:1b,Items:[{records}]}}}}')


def row(blocks):
    result = {}
    for i, name in enumerate(CASES, 1):
        belt, chute = blocks[2*(i-1):2*i]
        in_belt = items(belt['nbt'], 'Inventory')
        in_chute = items(chute['nbt'], 'Item')
        if in_chute:
            assert number(chute, 'chute_belt_suction') == i, chute
        assert in_belt.get(EDGE) == 3 and number(belt, 'chute_belt_suction') == i, belt
        result[name] = dict(belt=in_belt, chute=in_chute,
                            offset=number(chute, 'ItemPosition') if in_chute else None,
                            distance=number(chute, 'BottomAirFlowDistance'), pull=number(chute, 'Pull'))
    return result


def java_run(work):
    host = Original()
    initial = host.call('state', {})
    assert initial['ready'] and initial['data_version'] == 3955
    assert json.loads((BASE / 'manifest.json').read_text())['create_sha256'] == CREATE_SHA256
    try:
        host.call('camera', {'position': CAMERA})
        host.call('tick', {'frozen': False})
        for _ in range(25):
            reply = host.command(f'execute if loaded {X} {Y} {Z+8}')
            if any('Test passed' in line for line in reply['messages']):
                break
            time.sleep(.15)
        else:
            raise AssertionError('Belt suction fixture column did not load')
        host.call('tick', {'frozen': True})
        setup(host.command)
        host.call('observe_ticks', {'positions': POINTS, 'ticks': 24})
        seed(host.command)
        response = host.call('observe_ticks', {'positions': POINTS, 'ticks': TICKS})
        return [row(sample['blocks']) for sample in response['samples']]
    finally:
        host.command('fill ' + xyz(AREA) + ' minecraft:air')
        host.call('camera', {k: initial[k] for k in ('position', 'yaw', 'pitch')})
        host.call('tick', {'frozen': initial['server']['frozen']})
        (work / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')


def native_run(session, cold):
    def sample(batch):
        for pos in POINTS:
            batch.data(pos)

    def record(batch, ticks):
        for _ in range(ticks):
            batch.tick()
            sample(batch)

    def run(batch, name):
        raw = batch.run(session, name)
        assert len(raw) % len(POINTS) == 0, len(raw)
        return [row([{'nbt': nbt} for nbt in raw[i:i+len(POINTS)]])
                for i in range(0, len(raw), len(POINTS))]

    batch = Batch()
    batch.load((X+2, Y+1, Z+4))
    setup(batch.command)
    batch.tick(24)
    seed(batch.command)
    before = []
    if cold:
        record(batch, 3)
        before = run(batch, 'belt-suction-before-restart')
        batch = Batch()
        batch.load((X+2, Y+1, Z+4))
        sample(batch)
    record(batch, TICKS - 3 if cold else TICKS)
    after = run(batch, 'belt-suction')
    if cold:
        assert before[-1] == after[0], (before[-1], after[0])
        after = after[1:]
    return before + after


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cold', action='store_true')
    for name in ('game', 'resources', 'ctl', 'create-jar', 'reference'):
        parser.add_argument('--' + name, type=Path)
    args = parser.parse_args()
    if args.game:
        if not all((args.resources, args.ctl, args.create_jar, args.reference)):
            parser.error('Horizon requires --resources, --ctl, --create-jar and --reference')
        reference = json.loads(args.reference.read_text())
        assert reference['passed'] and reference['create'] == PINS['create_revision']
        session = NativeCheckSession(args.game, args.resources, args.ctl, args.create_jar,
                                     name='chute-belt-suction-native', world='ChuteBeltSuction', graphics=False)
        session.env.pop('CREATE_HORIZON_PARTICLE_TRACE', None)
        work = session.scratch
        try:
            trace = native_run(session, args.cold)
        finally:
            session.control_temp.cleanup()
            for folder in (session.resources, work / '.horizon-cache', work / 'horizon-mods'):
                shutil.rmtree(folder, ignore_errors=True)
        (work / 'observed.json').write_text(json.dumps(trace, indent=2) + '\n')
        for i, (got, expected) in enumerate(zip(trace, reference['trace'], strict=True), 1):
            assert got == expected, (i, got, expected)
    else:
        if args.cold:
            parser.error('--cold restarts the native client in flight')
        work = Path(tempfile.mkdtemp(prefix='chute-belt-suction-java-', dir=ROOT / '.local'))
        trace = java_run(work)
    (work / 'observed.json').write_text(json.dumps(trace, indent=2) + '\n')
    for sample in trace:
        for case in ('direct', 'gap'):
            assert sample[case]['chute'] == {CARGO: 7} and sample[case]['belt'] == {EDGE: 3}, sample
        assert sample['blocked']['chute'] == {} and sample['blocked']['belt'] == {EDGE: 3, CARGO: 7}, sample
    assert trace[0]['direct']['offset'] == .1 and trace[0]['gap']['offset'] == -1.9, trace[0]
    receipt = work / 'result.json'
    receipt.write_text(json.dumps(dict(passed=True, create=PINS['create_revision'], cold=args.cold,
                                       trace=trace), indent=2) + '\n')
    print(receipt)


if __name__ == '__main__':
    main()
