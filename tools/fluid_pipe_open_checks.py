#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Record water and lava moving between a tank and a pump's open end."""

import argparse
import json
from pathlib import Path
import re
import shutil
import tempfile
import time

from bearing_native_checks import Batch
from burner_heat_java_checks import field
from chain_drive_checks import Original, xyz
from common import PINS, ROOT
from fluid_pump_java_checks import PUMP, TANK, fluid, seed
from funnel_checks import put
from native_check_session import NativeCheckSession
import reference_java as java


X, Y, Z = 2583, 172, 1290
LOAD = '2576 1280 2591 1327'
AREA = '2579 170 1287 2587 175 1324'
AIR = 'minecraft:air'
TICKS = 90
NETHER = 'minecraft:the_nether'
OUTPUT_TICKS = 155
NO_PLACE = '[fluids]\npipesPlaceFluidSourceBlocks = false\n'
CASES = (
    ('finite-water', 'water', True),
    ('infinite-water', 'water', True),
    ('waterlogged-source', 'water', True),
    ('finite-lava', 'lava', True),
    ('place-water', 'water', False),
    ('place-lava', 'lava', False),
)


def lane(index):
    z = Z + index*6
    pull = CASES[index][2]
    return ((X-1 if pull else X+1, Y, z), (X, Y, z), (X+1 if pull else X-1, Y, z))


OVERWORLD_LANES = range(len(CASES))
OUTPUT_LANES = (4, 5)
POSITIONS = [pos for index in OVERWORLD_LANES for pos in lane(index)]


def setup(cmd, indices=OVERWORLD_LANES):
    cmd(f'fill {AREA} {AIR}')
    for i in indices:
        name, kind, pull = CASES[i]
        end, pump, tank = lane(i)
        z = pump[2]
        cmd(f'fill {X-3} {Y-1} {z-2} {X+3} {Y-1} {z+2} minecraft:smooth_stone')
        step = -1 if pull else 1
        for at in [(X+2*step, Y, z+d) for d in (-1, 0, 1)] + [(X+step, Y, z+d) for d in (-2, 2)]:
            put(cmd, at, 'minecraft:smooth_stone')
        for d in (-1, 1):
            at = (X+step, Y, z+d)
            put(cmd, at, 'minecraft:water' if name == 'infinite-water' else 'minecraft:smooth_stone')
            put(cmd, (X, Y, z+d), 'minecraft:smooth_stone')
        if name == 'infinite-water':
            for d in (-1, 0, 1):
                put(cmd, (X-1, Y+1, z+d), 'minecraft:sea_lantern')
        put(cmd, tank, TANK)
        put(cmd, pump, PUMP+'[facing=east,waterlogged=false]')
        put(cmd, (X, Y-1, z), 'create:cogwheel[axis=x]')
        if pull:
            source = ('minecraft:oak_slab[type=bottom,waterlogged=true]' if name == 'waterlogged-source'
                      else f'minecraft:{kind}')
            put(cmd, end, source)
        else:
            cmd(seed(tank, kind, 2000))


def activate(cmd, indices=OVERWORLD_LANES):
    for i in indices:
        _, pump, _ = lane(i)
        put(cmd, (X+1, Y-1, pump[2]), 'create:creative_motor[facing=west]{ScrollValue:32}')


def snapshot(row, pull):
    external, pump, tank = row
    side = 'west' if pull else 'east'
    face = field(pump['nbt'], side) if side + ':' in pump['nbt'] else '{}'
    saved = field(face, 'OpenEnd') if 'OpenEnd:' in face else None
    # Absolute positions in Location are fixture coordinates.
    opened = dict(fluid=fluid(saved), pulling='Pulling:1b' in saved.replace(' ', '')) if saved else None
    stored = fluid(field(tank['nbt'], 'TankContent'))
    return dict(end=external['id'], properties=external['properties'], open_end=opened, tank=stored)


def observations(rows, indices=OVERWORLD_LANES):
    return {name: [snapshot(row[3*i:3*i+3], pull) for row in rows]
            for i, (name, _, pull) in enumerate(CASES[index] for index in indices)}


def verify(traces, mode='overworld'):
    indices = OVERWORLD_LANES if mode == 'overworld' else OUTPUT_LANES
    assert traces.keys() == {CASES[i][0] for i in indices}, traces.keys()
    for name, kind, pull in CASES:
        if name not in traces:
            continue
        frames = traces[name]
        assert any(frame['open_end'] is not None for frame in frames), (name, frames[-1])
        amounts = [0 if frame['tank'] is None else frame['tank']['amount'] for frame in frames]
        if pull:
            assert amounts[0] == 0 and amounts[-1] >= 1000, (name, amounts)
            if name == 'infinite-water':
                assert amounts[-1] > 1000 and all(frame['end'] == 'minecraft:water' for frame in frames)
            else:
                assert amounts[-1] == 1000, (name, amounts)
            if name == 'waterlogged-source':
                assert frames[-1]['properties']['waterlogged'] == 'false'
        elif mode == 'no-place' or (mode == 'nether' and kind == 'water'):
            assert amounts[0] == 2000 and amounts[-1] == 0, (name, amounts)
            assert all(frame['end'] == AIR for frame in frames), (name, frames[-1])
            assert frames[-1]['open_end']['fluid'] is None, frames[-1]
        else:
            assert amounts[0] == 2000 and amounts[-1] == 1000, (name, amounts)
            assert frames[-1]['end'] == f'minecraft:{kind}' and frames[-1]['properties']['level'] == '0'
        assert {frame['tank']['id'] for frame in frames if frame['tank']} == {f'minecraft:{kind}'}


def original(work, mode='overworld'):
    host = Original()
    start = host.call('state', {})
    assert start['ready'] and start['data_version'] == 3955, start
    indices = OVERWORLD_LANES if mode == 'overworld' else OUTPUT_LANES
    positions = POSITIONS if mode == 'overworld' else [pos for i in indices for pos in lane(i)]
    ticks = TICKS if mode == 'overworld' else OUTPUT_TICKS
    config = java.BASE / 'game/config/create-server.toml'
    previous_config = None
    host.call('tick', {'frozen': True})
    try:
        if mode == 'no-place':
            previous_config = config.read_bytes()
            updated, count = re.subn(rb'(?m)^([ \t]*pipesPlaceFluidSourceBlocks[ \t]*=[ \t]*)true[ \t]*$',
                                     rb'\g<1>false', previous_config)
            assert count == 1, config
            config.write_bytes(updated)
            time.sleep(2)
        if mode == 'nether':
            host.command(f'execute in {NETHER} run tp @s {X}.5 {Y+5} {Z+27}.5')
        host.command(f'forceload add {LOAD}')
        if mode == 'nether':
            deadline = time.monotonic() + 20
            while True:
                current = host.call('state', {})
                if current['ready'] and current['dimension'] == NETHER:
                    break
                assert time.monotonic() < deadline, current
                time.sleep(0.15)
        host.call('observe_ticks', {'positions': positions, 'ticks': 14})
        setup(host.command, indices)
        host.call('observe_ticks', {'positions': positions, 'ticks': 40})
        commands = []
        activate(commands.append, indices)
        rows = host.call('observe_ticks', {'positions': positions, 'ticks': ticks,
                                           'commands': commands})['samples']
        return observations([row['blocks'] for row in rows], indices)
    finally:
        try:
            host.command(f'fill {AREA} {AIR}')
            host.command(f'forceload remove {LOAD}')
            if mode == 'nether':
                x, y, z = start['position']
                host.command(f"execute in {start['dimension']} run tp @s {x} {y} {z} {start['yaw']} {start['pitch']}")
        finally:
            if previous_config is not None:
                config.write_bytes(previous_config)
                time.sleep(2)
            host.call('tick', {'frozen': start['server']['frozen']})
            (work / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')


def states(name, kind):
    if name == 'waterlogged-source':
        return ('minecraft:oak_slab[type=bottom,waterlogged=true]',
                'minecraft:oak_slab[type=bottom,waterlogged=false]')
    return (f'minecraft:{kind}[level=0]', f'minecraft:{kind}[level=14]', AIR)


def observe(batch, indices=OVERWORLD_LANES):
    for i in indices:
        name, kind, _ = CASES[i]
        end, pump, tank = lane(i)
        for state in states(name, kind):
            batch.command(f'execute if block {xyz(end)} {state} run say {state}', True)
        batch.data(pump)
        batch.data(tank)


def decode(raw, ticks, indices=OVERWORLD_LANES):
    raw = iter(raw)
    rows = []
    for tick in range(1, ticks+1):
        row = []
        for i in indices:
            name, kind, _ = CASES[i]
            found = [state for state in states(name, kind) if state in next(raw)]
            assert len(found) == 1, (tick, name, found)
            name, _, props = found[0].partition('[')
            properties = dict(pair.split('=') for pair in props.rstrip(']').split(',')) if props else {}
            row.extend([dict(id=name, properties=properties), dict(nbt=next(raw)), dict(nbt=next(raw))])
        rows.append(row)
    assert next(raw, None) is None
    return observations(rows, indices)


def native_run(session, mode='overworld'):
    batch = Batch()
    indices = OVERWORLD_LANES if mode == 'overworld' else OUTPUT_LANES
    ticks = TICKS if mode == 'overworld' else OUTPUT_TICKS
    if mode == 'no-place':
        config = session.scratch / 'config/create-server.toml'
        config.parent.mkdir(exist_ok=True)
        config.write_text(NO_PLACE)
    if mode == 'nether':
        batch.command(f'execute in {NETHER} run tp @s {X}.5 {Y+5} {Z+27}.5')
        batch.load((X, Y+2, Z+27))
    else:
        batch.load((X, Y+2, Z+14))
    setup(batch.command, indices)
    batch.tick(40)
    activate(batch.command, indices)
    for _ in range(ticks):
        batch.tick()
        observe(batch, indices)
    return decode(batch.run(session, 'open-pump'), ticks, indices)


def cold_run(session):
    batch = Batch()
    batch.load((X, Y+2, Z+14))
    setup(batch.command)
    batch.tick(40)
    activate(batch.command)
    batch.tick(30)
    observe(batch)
    before = decode(batch.run(session, 'before-cold-open-pump'), 1)

    batch = Batch()
    batch.load((X, Y+2, Z+14))
    batch.tick(100)
    observe(batch)
    after = decode(batch.run(session, 'after-cold-open-pump'), 1)
    for name, kind, pull in CASES:
        first, final = before[name][0], after[name][0]
        assert first['open_end']['fluid']['amount'] > 0, (name, first)
        if name == 'infinite-water':
            assert final['tank']['amount'] > 1000, final
        else:
            assert final['tank'] == {'id': f'minecraft:{kind}', 'amount': 1000}, (name, final)
        if not pull:
            assert final['end'] == f'minecraft:{kind}' and final['properties']['level'] == '0', final
    return {'before': before, 'after': after}


def compare(traces, expected):
    for name, rows in traces.items():
        for tick, (got, want) in enumerate(zip(rows, expected[name], strict=True), 1):
            previous = expected[name][tick-2] if tick > 1 else None
            if previous and want['open_end'] is None and previous['open_end']:
                # Horizon retains the still-owned buffer through the
                # transient phase in which Java's write omits it.
                assert got['open_end'] == previous['open_end'], (tick, got)
                got = {**got, 'open_end': None}
            assert got == want, (name, tick, got, want)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--java', action='store_true')
    parser.add_argument('--cold', action='store_true', help='Also restart with fluid in all six buffers')
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument('--nether', action='store_const', dest='mode', const='nether',
                       help='Compare water evaporation and lava placement')
    modes.add_argument('--no-place', action='store_const', dest='mode', const='no-place',
                       help='Compare outlets with source block placement disabled')
    parser.set_defaults(mode='overworld')
    for flag in ('game', 'resources', 'ctl', 'create-jar', 'reference'):
        parser.add_argument('--' + flag, type=Path)
    args = parser.parse_args()
    if args.cold and args.mode != 'overworld':
        parser.error('--cold applies to the standard Overworld cases')
    cold = None
    if args.java:
        work = Path(tempfile.mkdtemp(prefix='fluid-open-java-', dir=ROOT / '.local'))
        print(work, flush=True)
        traces = original(work, args.mode)
    else:
        if not all((args.game, args.resources, args.ctl, args.create_jar, args.reference)):
            parser.error('Horizon requires --game, --resources, --ctl, --create-jar and --reference')
        session = NativeCheckSession(args.game, args.resources, args.ctl, args.create_jar,
                                     name='fluid-open-native', world='CreateFluidOpen')
        work = session.scratch
        print(work, flush=True)
        try:
            traces = native_run(session, args.mode)
            if args.cold:
                cold = cold_run(session)
        finally:
            session.control_temp.cleanup()
            for folder in (session.resources, work / '.horizon-cache', work / 'horizon-mods'):
                shutil.rmtree(folder, ignore_errors=True)
    (work / 'observed.json').write_text(json.dumps(traces, indent=2) + '\n')
    verify(traces, args.mode)
    if not args.java:
        expected = json.loads(args.reference.read_text())
        assert expected['passed'] and expected['create'] == PINS['create_revision']
        compare(traces, expected['traces'])
    result = work / 'result.json'
    result.write_text(json.dumps(dict(passed=True, create=PINS['create_revision'], traces=traces, cold=cold), indent=2) + '\n')
    print(result)


if __name__ == '__main__':
    main()
