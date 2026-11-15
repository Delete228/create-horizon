#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Observe ordinary vertical Chutes powered from below by an Encased Fan."""

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
from fan_hazard_checks import advance
from funnel_checks import put
from native_check_session import NativeCheckSession
from reference_java import BASE, CREATE_SHA256


X, Y, Z = 1190, 172, 314
AREA = (X-3, Y-4, Z-3, X+4, Y+6, Z+13)
CAMERA = (X+3.5, Y+1, Z+4.5)
CASES = {'hopper': Z, 'blocked': Z+4, 'reverse': Z+8}
CARGO = 'minecraft:stick'
POINTS = [(X, Y+dy, z) for z in CASES.values() for dy in range(4)]


def payload(count, probe):
    return f'id:"{CARGO}",count:{count},components:{{"minecraft:custom_data":{{chute_lift:{probe}}}}}'


def motor(command, z, rpm):
    put(command, (X, Y-2, z), 'minecraft:air')
    put(command, (X, Y-2, z), f'create:creative_motor[facing=up]{{ScrollValue:{rpm}}}')


def setup(command, tick, *, native=False, wet=False):
    command('fill ' + xyz(AREA) + ' minecraft:air')
    command(f'fill {X-3} {Y-3} {Z-3} {X+4} {Y-3} {Z+13} minecraft:smooth_stone')
    for name, z in CASES.items():
        motor(command, z, 128)
        put(command, (X, Y-1, z), 'create:encased_fan[facing=up]')
        for dy in (0, 1, 2):
            put(command, (X, Y+dy, z),
                f'create:chute[facing=down,shape=window,waterlogged={str(wet).lower()}]')
        full = ('{Items:[' + ','.join(f'{{Slot:{i}b,id:"minecraft:stone",count:64}}'
                                       for i in range(27)) + ']}') if name == 'blocked' else ''
        put(command, (X, Y+3, z), 'minecraft:barrel' + full)
    tick(6)
    for i, (name, z) in enumerate(CASES.items(), 1):
        stack = payload(1 if name == 'hopper' else 7, i)
        if name == 'hopper':
            put(command, (X+1, Y, z), 'minecraft:hopper[facing=west]'
                f'{{Items:[{{Slot:0b,{stack}}}]}}')
        else:
            live = f',Items:[{{Slot:0b,{stack}}}]' if native else ''
            command(f'data merge block {X} {Y} {z} {{Item:{{{stack}}},ItemPosition:0.0f{live}}}')


def row(blocks):
    lanes = {}
    for i, name in enumerate(CASES, 1):
        chute_a, chute_b, chute_c, barrel = [b['nbt'] for b in blocks[4*(i-1):4*i]]
        chutes = [chute_a, chute_b, chute_c]
        counts = [items(raw, 'Item').get(CARGO, 0) for raw in chutes] + [items(barrel, 'Items').get(CARGO, 0)]
        for raw, count in zip([*chutes, barrel], counts, strict=True):
            if count:
                assert number({'nbt': raw}, 'chute_lift') == i, raw
        lanes[name] = dict(counts=counts,
                           offsets=[number({'nbt': raw}, 'ItemPosition') if count else None
                                    for raw, count in zip(chutes, counts[:3], strict=True)],
                           push=[number({'nbt': raw}, 'Push') for raw in chutes],
                           pull=[number({'nbt': raw}, 'Pull') for raw in chutes])
    return lanes


def phase(host, count, wet):
    result = host.call('observe_ticks', {'positions': POINTS, 'ticks': count})
    if wet:
        assert all(block['properties']['waterlogged'] == 'true' for sample in result['samples']
                   for index, block in enumerate(sample['blocks']) if index % 4 != 3)
    return [row(sample['blocks']) for sample in result['samples']]


def release(command):
    command(f'item replace block {X} {Y+3} {CASES["blocked"]} container.0 with minecraft:air')


def java_run(work, wet):
    host = Original()
    initial = host.call('state', {})
    assert initial['ready'] and initial['data_version'] == 3955
    assert json.loads((BASE / 'manifest.json').read_text())['create_sha256'] == CREATE_SHA256
    try:
        host.call('camera', {'position': CAMERA})
        host.call('tick', {'frozen': False})
        for _ in range(25):
            probe = host.command(f'execute if loaded {X} {Y} {Z+8}')
            if any('Test passed' in line for line in probe['messages']):
                break
            time.sleep(.15)
        else:
            raise AssertionError('Chute lift fixture column did not load')
        host.command('tick freeze')
        setup(host.command, lambda count: advance(host, count, *POINTS), wet=wet)
        first = phase(host, 15, wet)
        motor(host.command, CASES['reverse'], -128)
        second = phase(host, 25, wet)
        release(host.command)
        return first + second + phase(host, 15, wet)
    finally:
        host.command('fill ' + xyz(AREA) + ' minecraft:air')
        host.call('camera', {k: initial[k] for k in ('position', 'yaw', 'pitch')})
        host.call('tick', {'frozen': initial['server']['frozen']})
        (work / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')


def native_run(session, cold, wet):
    def sample(batch):
        for pos in POINTS:
            batch.data(pos)

    def record(batch, ticks):
        for _ in range(ticks):
            batch.tick()
            sample(batch)

    def run(batch, name):
        chutes = [pos for i, pos in enumerate(POINTS) if i % 4 != 3] if wet else []
        for pos in chutes:
            batch.expect(pos, 'create:chute[waterlogged=true]')
        rows = batch.run(session, name)
        if chutes:
            assert all('bearing_check' in reply for reply in rows[-len(chutes):])
            rows = rows[:-len(chutes)]
        assert len(rows) % len(POINTS) == 0, rows
        return [row([{'nbt': raw} for raw in rows[i:i+len(POINTS)]])
                for i in range(0, len(rows), len(POINTS))]

    batch = Batch()
    batch.load((X+3, Y, Z+4))
    setup(batch.command, batch.tick, native=True, wet=wet)
    record(batch, 15)
    motor(batch.command, CASES['reverse'], -128)
    record(batch, 25)
    first = []
    if cold:
        first = run(batch, 'blocked-before-restart')
        assert first[-1]['blocked']['offsets'] == [None, None, .5], first[-1]
        batch = Batch()
        batch.load((X+3, Y, Z+4))
        sample(batch)
    release(batch.command)
    record(batch, 15)
    after = run(batch, 'chute-fan')
    if cold:
        assert after[0] == first[-1], (after[0], first[-1])
        after = after[1:]
    return first + after


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--java', action='store_true')
    parser.add_argument('--cold', action='store_true')
    parser.add_argument('--wet', action='store_true')
    for name in ('game', 'resources', 'ctl', 'reference', 'create-jar'):
        parser.add_argument('--' + name, type=Path)
    args = parser.parse_args()
    if args.java and args.cold:
        parser.error('--cold restarts the native client after the blocked stack stops')
    if args.java:
        work = Path(tempfile.mkdtemp(prefix='chute-fan-java-', dir=ROOT / '.local'))
        trace = java_run(work, args.wet)
    else:
        if not all((args.game, args.resources, args.ctl, args.reference)):
            parser.error('Horizon checks require --game, --resources, --ctl and --reference')
        reference = json.loads(args.reference.read_text())
        assert reference['passed'] and reference['create'] == PINS['create_revision']
        assert reference.get('wet', False) == args.wet
        session = NativeCheckSession(args.game, args.resources, args.ctl, args.create_jar, graphics=False,
                                     name='chute-fan-native', world='CreateChuteLift')
        session.env.pop('CREATE_HORIZON_TRACE_POSES', None)
        session.env.pop('CREATE_HORIZON_PARTICLE_TRACE', None)
        work = session.scratch
        try:
            trace = native_run(session, args.cold, args.wet)
        finally:
            session.control_temp.cleanup()
            for folder in (session.resources, work / '.horizon-cache', work / 'horizon-mods'):
                shutil.rmtree(folder, ignore_errors=True)
        (work / 'observed.json').write_text(json.dumps(trace, indent=2) + '\n')
        for i, (got, want) in enumerate(zip(trace, reference['trace'], strict=True), 1):
            for name, sample in got.items():
                assert sample == want[name], (i, name, sample, want[name])
    assert all(sum(lane['counts']) == (1 if name == 'hopper' else 7)
               for sample in trace for name, lane in sample.items()), trace
    assert trace[28]['hopper']['counts'] == [0, 0, 0, 1], trace[28]
    assert trace[39]['blocked']['offsets'] == [None, None, .5], trace[39]
    assert trace[44]['blocked']['counts'] == [0, 0, 0, 7], trace[44]
    assert trace[-1]['reverse']['offsets'] == [.5, None, None], trace[-1]
    receipt = work / 'result.json'
    receipt.write_text(json.dumps(dict(passed=True, create=PINS['create_revision'],
                                       cold=args.cold, wet=args.wet, trace=trace), indent=2) + '\n')
    print(receipt)


if __name__ == '__main__':
    main()
