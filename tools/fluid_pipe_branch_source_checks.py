#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Compare a single open pump inlet supplying multiple closed outlets."""

import argparse
import json
from pathlib import Path
import shutil
import tempfile

from bearing_native_checks import Batch
from burner_heat_java_checks import field
from chain_drive_checks import Original, xyz
from common import PINS, ROOT
from fluid_pipe_open_checks import compare, snapshot
from fluid_pump_java_checks import PIPE, PUMP, TANK, fluid, seed
from funnel_checks import put
from native_check_session import NativeCheckSession


X, Y, Z = 2583, 172, 1290
LOAD = '2576 1280 2591 1311'
AREA = '2579 170 1287 2587 175 1310'
TICKS = 130
PROFILES = (
    ('finite-water', 'water', 'minecraft:water[level=0]'),
    ('renewable-water', 'water', 'minecraft:water[level=0]'),
    ('lava-cauldron', 'lava', 'minecraft:lava_cauldron'),
    ('nearly-full-outlet', 'water', 'minecraft:oak_slab[type=bottom,waterlogged=true]'),
)


def lane(i):
    z = Z+6*i
    return (X-1, Y, z), (X, Y, z), (X+1, Y, z-1), (X+1, Y, z+1)


POSITIONS = [pos for i in range(len(PROFILES)) for pos in lane(i)]


def setup(cmd):
    cmd(f'fill {AREA} minecraft:air')
    for i, (name, _, initial) in enumerate(PROFILES):
        source, pump, north, south = lane(i)
        z = pump[2]
        cmd(f'fill {X-3} {Y-1} {z-2} {X+2} {Y-1} {z+2} minecraft:smooth_stone')
        for d in (-1, 0, 1):
            put(cmd, (X-2, Y, z+d), 'minecraft:smooth_stone')
            put(cmd, (X-1, Y+1, z+d), 'minecraft:sea_lantern')
        for d in (-2, 2):
            put(cmd, (X-1, Y, z+d), 'minecraft:smooth_stone')
        for d in (-1, 1):
            block = 'minecraft:water' if name == 'renewable-water' else 'minecraft:smooth_stone'
            put(cmd, (X-1, Y, z+d), block)
            put(cmd, (X, Y, z+d), 'minecraft:smooth_stone')
        put(cmd, source, initial)
        put(cmd, north, TANK)
        put(cmd, south, TANK)
        if name == 'nearly-full-outlet':
            cmd(seed(north, 'water', 7997))
        put(cmd, (X+1, Y, z), PIPE+'[west=true,north=true,south=true,waterlogged=false]')
        put(cmd, pump, PUMP+'[facing=east,waterlogged=false]')
        put(cmd, (X, Y-1, z), 'create:cogwheel[axis=x]')


def activate(cmd):
    for i in range(len(PROFILES)):
        z = lane(i)[1][2]
        put(cmd, (X+1, Y-1, z), 'create:creative_motor[facing=west]{ScrollValue:32}')


def measure(blocks):
    first = snapshot(blocks[:3], pull=True)
    first['north'] = first.pop('tank')
    first['south'] = fluid(field(blocks[3]['nbt'], 'TankContent'))
    return first


def java_run(work):
    host = Original()
    initial = host.call('state', {})
    assert initial['ready'] and initial['data_version'] == 3955, initial
    host.call('tick', {'frozen': True})
    try:
        host.command(f'forceload add {LOAD}')
        host.call('observe_ticks', {'positions': POSITIONS, 'ticks': 14})
        setup(host.command)
        host.call('observe_ticks', {'positions': POSITIONS, 'ticks': 40})
        commands = []
        activate(commands.append)
        rows = host.call('observe_ticks', {'positions': POSITIONS, 'ticks': TICKS,
                                           'commands': commands})['samples']
        return {name: [measure(row['blocks'][4*i:4*i+4]) for row in rows]
                for i, (name, _, _) in enumerate(PROFILES)}
    finally:
        host.command(f'fill {AREA} minecraft:air')
        host.command(f'forceload remove {LOAD}')
        host.call('tick', {'frozen': initial['server']['frozen']})
        (work / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')


def possible_states(initial):
    if initial == 'minecraft:lava_cauldron':
        return (initial, 'minecraft:cauldron')
    if initial.startswith('minecraft:oak_slab'):
        return (initial, initial.replace('true', 'false'))
    return (initial, 'minecraft:water[level=14]', 'minecraft:air')


def native_run(session):
    batch = Batch()
    batch.load((X, Y+2, Z+9))
    setup(batch.command)
    batch.tick(40)
    activate(batch.command)
    for _ in range(TICKS):
        batch.tick()
        for i, (_, _, initial) in enumerate(PROFILES):
            source, *others = lane(i)
            for value in possible_states(initial):
                batch.command(f'execute if block {xyz(source)} {value} run say {value}', True)
            for pos in others:
                batch.data(pos)
    raw = iter(batch.run(session, 'open-source-branches'))
    traces = {name: [] for name, _, _ in PROFILES}
    for tick in range(1, TICKS+1):
        for name, _, initial in PROFILES:
            values = [value for value in possible_states(initial) if value in next(raw)]
            assert len(values) == 1, (name, tick, values)
            block, _, props = values[0].partition('[')
            props = dict(pair.split('=') for pair in props.rstrip(']').split(',')) if props else {}
            traces[name].append(measure([dict(id=block, properties=props)] +
                                        [dict(nbt=next(raw)) for _ in range(3)]))
    assert next(raw, None) is None
    return traces


def verify(traces):
    for name, kind, _ in PROFILES:
        final = traces[name][-1]
        amounts = [stack['amount'] if stack else 0 for stack in (final['north'], final['south'])]
        if name == 'renewable-water':
            assert amounts[0] == amounts[1] and sum(amounts) > 1000, final
        elif name == 'nearly-full-outlet':
            assert amounts == [8000, 997], final
        else:
            assert amounts == [500, 500], final
        assert {final[side]['id'] for side in ('north', 'south')} == {f'minecraft:{kind}'}, final


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--java', action='store_true')
    for flag in ('game', 'resources', 'ctl', 'create-jar', 'reference'):
        parser.add_argument('--' + flag, type=Path)
    args = parser.parse_args()
    if args.java:
        work = Path(tempfile.mkdtemp(prefix='fluid-branch-source-java-', dir=ROOT / '.local'))
        print(work, flush=True)
        traces = java_run(work)
    else:
        if not all((args.game, args.resources, args.ctl, args.create_jar, args.reference)):
            parser.error('Horizon requires --game, --resources, --ctl, --create-jar and --reference')
        session = NativeCheckSession(args.game, args.resources, args.ctl, args.create_jar,
                                     name='fluid-branch-source-native', world='CreateFluidBranchSource')
        work = session.scratch
        print(work, flush=True)
        try:
            traces = native_run(session)
        finally:
            session.control_temp.cleanup()
            for folder in (session.resources, work / '.horizon-cache', work / 'horizon-mods'):
                shutil.rmtree(folder, ignore_errors=True)
    (work / 'observed.json').write_text(json.dumps(traces, indent=2) + '\n')
    verify(traces)
    if not args.java:
        reference = json.loads(args.reference.read_text())
        assert reference['passed'] and reference['create'] == PINS['create_revision']
        compare(traces, reference['traces'])
    result = work / 'result.json'
    result.write_text(json.dumps(dict(passed=True, create=PINS['create_revision'], traces=traces), indent=2) + '\n')
    print(result)


if __name__ == '__main__':
    main()
