#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Compare open pump outlets colliding with a different world fluid."""

import argparse
import json
from pathlib import Path
import shutil
import tempfile

from bearing_native_checks import Batch
from burner_heat_java_checks import field
from chain_drive_checks import Original, xyz
from common import PINS, ROOT
from fluid_pump_java_checks import PUMP, TANK, fluid, seed
from funnel_checks import put
from native_check_session import NativeCheckSession


X, Y, Z = 2583, 172, 1290
LOAD = '2576 1280 2591 1327'
AREA = '2579 170 1287 2587 175 1324'
TICKS = 50
WARMUP = 70
CASES = (
    ('water-lava-source', 'water', 'lava', 'source', 'obsidian'),
    ('lava-water-source', 'lava', 'water', 'source', 'stone'),
    ('water-flowing-lava', 'water', 'lava', 'flowing', 'cobblestone'),
    ('lava-flowing-water', 'lava', 'water', 'flowing', 'cobblestone'),
    ('lava-waterlogged', 'lava', 'water', 'slab', 'stone'),
)


def lane(index):
    z = Z + index*6
    return (X+1, Y, z), (X-1, Y, z)


POSITIONS = [pos for index in range(len(CASES)) for pos in lane(index)]


def prepare(cmd):
    cmd(f'fill {AREA} minecraft:air')
    for index, (_, kind, external, shape, _) in enumerate(CASES):
        (x, y, z), tank = lane(index)
        cmd(f'fill {X-2} {Y-1} {z-1} {X+3} {Y-1} {z+1} minecraft:smooth_stone')
        for wall_z in (z-1, z+1):
            cmd(f'fill {X} {Y} {wall_z} {X+3} {Y} {wall_z} minecraft:smooth_stone')
        put(cmd, (x, y+1, z), 'minecraft:sea_lantern')
        put(cmd, (x+1, y+1, z), 'minecraft:sea_lantern')
        put(cmd, (x+2, y, z), 'minecraft:smooth_stone')
        put(cmd, tank, TANK)
        cmd(seed(tank, kind, 2000))
        put(cmd, (X, Y, z), PUMP+'[facing=east,waterlogged=false]')
        put(cmd, (X, Y-1, z), 'create:cogwheel[axis=x]')
        if shape == 'slab':
            put(cmd, (x, y, z), 'minecraft:oak_slab[type=bottom,waterlogged=true]')
            put(cmd, (x+1, y, z), 'minecraft:smooth_stone')
        else:
            put(cmd, (x+(shape == 'flowing'), y, z), f'minecraft:{external}')
            if shape == 'source':
                put(cmd, (x+1, y, z), 'minecraft:smooth_stone')


def activate(cmd):
    for index in range(len(CASES)):
        z = lane(index)[0][2]
        put(cmd, (X+1, Y-1, z), 'create:creative_motor[facing=west]{ScrollValue:32}')


def measure(block, tank):
    state = block['id']
    if state in ('minecraft:water', 'minecraft:lava'):
        state += '[source]' if block['properties']['level'] == '0' else '[flowing]'
    if state == 'minecraft:oak_slab':
        assert block['properties']['waterlogged'] == 'true', block
    return dict(end=state, tank=fluid(field(tank['nbt'], 'TankContent')))


def java_run(work):
    host = Original()
    initial = host.call('state', {})
    assert initial['ready'] and initial['data_version'] == 3955, initial
    host.call('tick', {'frozen': True})
    try:
        host.command(f'forceload add {LOAD}')
        host.call('observe_ticks', {'positions': POSITIONS, 'ticks': 14})
        prepare(host.command)
        warm = host.call('observe_ticks', {'positions': POSITIONS, 'ticks': WARMUP})['samples'][-1:]
        commands = []
        activate(commands.append)
        rows = warm + host.call('observe_ticks', {'positions': POSITIONS, 'ticks': TICKS,
                                                  'commands': commands})['samples']
        return {name: [measure(*row['blocks'][2*i:2*i+2]) for row in rows]
                for i, (name, *_) in enumerate(CASES)}
    finally:
        host.command(f'fill {AREA} minecraft:air')
        host.command(f'forceload remove {LOAD}')
        host.call('tick', {'frozen': initial['server']['frozen']})
        (work / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')


def before_state(external, shape):
    return ('minecraft:oak_slab' if shape == 'slab' else f'minecraft:{external}[{shape}]')


def native_run(session):
    batch = Batch()
    batch.load((X, Y+2, Z+12))
    prepare(batch.command)
    batch.tick(WARMUP)

    def observe():
        for i, (_, _, external, shape, solid) in enumerate(CASES):
            end, tank = lane(i)
            initial = ('minecraft:oak_slab[type=bottom,waterlogged=true]' if shape == 'slab'
                       else f'minecraft:{external}')
            batch.command(f'execute if block {xyz(end)} {initial} run say fixture_liquid', True)
            batch.command(f'execute if block {xyz(end)} minecraft:{external}[level=0] run say fixture_source', True)
            batch.command(f'execute if block {xyz(end)} minecraft:{solid} run say fixture_solid', True)
            batch.data(tank)

    observe()
    activate(batch.command)
    for _ in range(TICKS):
        batch.tick()
        observe()
    raw = iter(batch.run(session, 'open-spill'))
    result = {name: [] for name, *_ in CASES}
    for tick in range(TICKS+1):
        for name, _, external, shape, solid in CASES:
            liquid = 'fixture_liquid' in next(raw)
            source = 'fixture_source' in next(raw)
            reacted = 'fixture_solid' in next(raw)
            assert liquid != reacted, (name, tick, liquid, reacted)
            if liquid and shape != 'slab':
                assert source == (shape == 'source'), (name, tick, source)
            state = before_state(external, shape) if liquid else f'minecraft:{solid}'
            result[name].append(dict(end=state, tank=fluid(field(next(raw), 'TankContent'))))
    assert next(raw, None) is None
    return result


def verify(traces):
    for name, kind, external, shape, solid in CASES:
        rows = traces[name]
        initial = before_state(external, shape)
        after = f'minecraft:{solid}'
        assert rows[0]['end'] == initial and rows[-1]['end'] == after, (name, rows[0], rows[-1])
        changes = [i for i, row in enumerate(rows) if row['end'] == after]
        assert changes == list(range(changes[0], TICKS+1)), (name, changes)
        assert all(row['tank'] == {'id': f'minecraft:{kind}', 'amount': 2000} for row in rows), name


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--java', action='store_true')
    for flag in ('game', 'resources', 'ctl', 'create-jar', 'reference'):
        parser.add_argument('--' + flag, type=Path)
    args = parser.parse_args()
    if args.java:
        work = Path(tempfile.mkdtemp(prefix='fluid-spill-java-', dir=ROOT / '.local'))
        print(work, flush=True)
        traces = java_run(work)
    else:
        if not all((args.game, args.resources, args.ctl, args.create_jar, args.reference)):
            parser.error('Horizon requires --game, --resources, --ctl, --create-jar and --reference')
        session = NativeCheckSession(args.game, args.resources, args.ctl, args.create_jar,
                                     name='fluid-spill-native', world='CreateFluidSpill')
        work = session.scratch
        print(work, flush=True)
        try:
            traces = native_run(session)
        finally:
            session.control_temp.cleanup()
            for folder in (session.resources, work / '.horizon-cache', work / 'horizon-mods'):
                shutil.rmtree(folder, ignore_errors=True)
        reference = json.loads(args.reference.read_text())
        assert reference['passed'] and reference['create'] == PINS['create_revision']
        for name, rows in traces.items():
            for tick, (got, want) in enumerate(zip(rows, reference['traces'][name], strict=True)):
                assert got == want, (name, tick, got, want)
    verify(traces)
    result = work / 'result.json'
    result.write_text(json.dumps(dict(passed=True, create=PINS['create_revision'], traces=traces), indent=2) + '\n')
    print(result)


if __name__ == '__main__':
    main()
