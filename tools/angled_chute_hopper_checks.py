#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Compare Hopper admission to occupied and empty ordinary angled Chutes."""

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


X, Y, Z = 1662, 200, 592
AREA = (X-5, Y-7, Z-3, X+4, Y+5, Z+23)
CAMERA = (X+2.5, Y+2, Z+10.5)
CASES = {'dry': (Z, False), 'wet': (Z+20, True)}
ITEMS = ('minecraft:stick', 'minecraft:cobblestone', 'minecraft:iron_ingot')
BLOCKED, RESUMED = 10, 32


def points(z):
    return [(X+1, Y+1, z), (X, Y+1, z), (X-1, Y, z), (X-1, Y-1, z)]


POINTS = [pos for z, _ in CASES.values() for pos in points(z)]


def stack(item, count, lane):
    return f'id:"{item}",count:{count},components:{{"minecraft:custom_data":{{angled_hopper:{lane}}}}}'


def setup(command, step, native=False):
    command('fill ' + xyz(AREA) + ' minecraft:air')
    command(f'fill {X-5} {Y-6} {Z-3} {X+4} {Y-6} {Z+23} minecraft:stone')
    for lane, (z, wet) in enumerate(CASES.values(), 1):
        source, angled, lower, barrel = points(z)
        state = f'waterlogged={str(wet).lower()}'
        full = ','.join(f'{{Slot:{i}b,id:"minecraft:stone",count:64}}' for i in range(27))
        put(command, barrel, f'minecraft:barrel{{Items:[{full}]}}')
        put(command, lower, f'create:chute[facing=down,shape=normal,{state}]')
        put(command, angled, f'create:chute[facing=east,shape=intersection,{state}]')
        put(command, source, 'minecraft:hopper[facing=west]')
    step(6)
    for lane, (z, _) in enumerate(CASES.values(), 1):
        source, angled, lower, _ = points(z)
        for pos, item, count in ((angled, ITEMS[1], 2), (lower, ITEMS[2], 3)):
            cargo = stack(item, count, lane)
            slot = f',Items:[{{Slot:0b,{cargo}}}]' if native else ''
            command(f'data merge block {xyz(pos)} {{Item:{{{cargo}}},ItemPosition:0.5f{slot}}}')
        command(f'item replace block {xyz(source)} container.0 with '
                f'{ITEMS[0]}[minecraft:custom_data={{angled_hopper:{lane}}}] 1')


def release(command):
    for z, _ in CASES.values():
        for slot in range(3):
            command(f'item replace block {xyz(points(z)[-1])} container.{slot} with minecraft:air')


def row(blocks):
    result = {}
    for lane, (name, (_, wet)) in enumerate(CASES.items(), 1):
        samples = blocks[4*(lane-1):4*lane]
        amounts = [{item: count for item, count in items(block['nbt'], field).items() if item in ITEMS}
                   for block, field in zip(samples, ('Items', 'Item', 'Item', 'Items'), strict=True)]
        assert [sum(point.get(item, 0) for point in amounts) for item in ITEMS] == [1, 2, 3], amounts
        for block, cargo in zip(samples, amounts, strict=True):
            if cargo:
                assert number(block, 'angled_hopper') == lane, block
        if 'properties' in samples[1]:
            assert samples[1]['properties']['facing'] == 'east', samples[1]
            assert samples[1]['properties']['waterlogged'] == str(wet).lower(), samples[1]
        offsets = [number(samples[i], 'ItemPosition') if amounts[i] else None for i in (1, 2)]
        result[name] = dict(amounts=amounts, offsets=offsets)
    return result


def java_run(work):
    host = Original()
    initial = host.call('state', {})
    assert initial['ready'] and initial['data_version'] == 3955
    assert json.loads((BASE / 'manifest.json').read_text())['create_sha256'] == CREATE_SHA256

    def advance(ticks):
        response = host.call('observe_ticks', {'positions': POINTS, 'ticks': ticks})
        return [row(sample['blocks']) for sample in response['samples']]

    try:
        host.call('camera', {'position': CAMERA})
        host.call('tick', {'frozen': False})
        for _ in range(35):
            probes = [host.command(f'execute if loaded {xyz(pos)}') for pos in (POINTS[0], POINTS[-1])]
            if all('Test passed' in probe['messages'] for probe in probes):
                break
            time.sleep(.15)
        else:
            raise AssertionError('Angled Hopper fixture columns did not load')
        host.call('tick', {'frozen': True})
        # The settle phase has no cargo yet, so only advance the clock.
        setup(host.command, lambda ticks: host.call('observe_ticks', {'positions': POINTS, 'ticks': ticks}))
        before = advance(BLOCKED)
        release(host.command)
        return before + advance(RESUMED)
    finally:
        host.command('fill ' + xyz(AREA) + ' minecraft:air')
        time.sleep(.35)
        host.call('camera', {k: initial[k] for k in ('position', 'yaw', 'pitch')})
        host.call('tick', {'frozen': initial['server']['frozen']})
        (work / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')


def native_run(session):
    def record(batch, ticks):
        for _ in range(ticks):
            batch.tick()
            for pos in POINTS:
                batch.data(pos)

    batch = Batch()
    batch.load((X+2, Y+2, Z+10))
    setup(batch.command, batch.tick, True)
    record(batch, BLOCKED)
    release(batch.command)
    record(batch, RESUMED)
    for z, wet in CASES.values():
        batch.expect(points(z)[1], f'create:chute[facing=east,waterlogged={str(wet).lower()}]')
    raw = batch.run(session, 'angled-chute-hopper')
    end = (BLOCKED+RESUMED)*len(POINTS)
    assert len(raw) == end + len(CASES), len(raw)
    assert all('bearing_check' in value for value in raw[end:]), raw[end:]
    return [row([{'nbt': value} for value in raw[i:i+len(POINTS)]]) for i in range(0, end, len(POINTS))]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('game', 'resources', 'ctl', 'create-jar', 'reference'):
        parser.add_argument('--' + name, type=Path)
    args = parser.parse_args()
    if args.game:
        if not all((args.resources, args.ctl, args.create_jar, args.reference)):
            parser.error('Horizon requires --resources, --ctl, --create-jar and --reference')
        reference = json.loads(args.reference.read_text())
        assert reference['passed'] and reference['create'] == PINS['create_revision']
        session = NativeCheckSession(args.game, args.resources, args.ctl, args.create_jar,
                                     name='angled-chute-hopper-native', world='AngledHopper', graphics=False)
        session.env.pop('CREATE_HORIZON_PARTICLE_TRACE', None)
        session.env.pop('CREATE_HORIZON_TRACE_POSES', None)
        work = session.scratch
        try:
            trace = native_run(session)
        finally:
            session.control_temp.cleanup()
            for folder in (session.resources, work / '.horizon-cache', work / 'horizon-mods'):
                shutil.rmtree(folder, ignore_errors=True)
        (work / 'observed.json').write_text(json.dumps(trace, indent=2) + '\n')
        for tick, (got, expected) in enumerate(zip(trace, reference['trace'], strict=True), 1):
            assert got == expected, (tick, got, expected)
    else:
        work = Path(tempfile.mkdtemp(prefix='angled-chute-hopper-java-', dir=ROOT / '.local'))
        trace = java_run(work)
    for name in CASES:
        assert all(sample[name]['amounts'][0] == {ITEMS[0]: 1} for sample in trace[:BLOCKED]), trace[0]
        assert trace[-1][name]['amounts'] == [{}, {}, {}, dict(zip(ITEMS, (1, 2, 3)))], trace[-1]
    receipt = work / 'result.json'
    receipt.write_text(json.dumps(dict(passed=True, create=PINS['create_revision'], trace=trace), indent=2) + '\n')
    print(receipt)


if __name__ == '__main__':
    main()
