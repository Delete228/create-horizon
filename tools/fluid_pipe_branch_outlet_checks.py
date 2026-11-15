#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Compare one exposed outlet alongside a closed tank branch."""

import argparse
import json
from pathlib import Path
import shutil
import tempfile

from bearing_native_checks import Batch
from burner_heat_java_checks import field
from chain_drive_checks import Original, xyz
from common import PINS, ROOT
from fluid_pump_java_checks import PIPE, PUMP, TANK, fluid, seed
from funnel_checks import put
from native_check_session import NativeCheckSession


X, Y, Z = 2583, 172, 1290
LOAD = '2576 1280 2591 1327'
AREA = '2579 170 1287 2587 175 1318'
TICKS = 185
CASES = (
    ('split', 'minecraft:air', 'minecraft:water[level=0]', 0),
    ('partial-room', 'minecraft:air', 'minecraft:water[level=0]', 7997),
    ('react', 'minecraft:lava[level=0]', 'minecraft:obsidian', 0),
    ('blocked', 'minecraft:smooth_stone', 'minecraft:smooth_stone', 0),
)


def lane(i):
    z = Z+7*i
    return (X+1, Y, z+2), (X+1, Y, z+1), (X-1, Y, z), (X+1, Y, z-1)


POSITIONS = [pos for i in range(len(CASES)) for pos in lane(i)]


def setup(cmd):
    cmd(f'fill {AREA} minecraft:air')
    for i, (_, before, _, filled) in enumerate(CASES):
        end, outlet, source, tank = lane(i)
        z = source[2]
        cmd(f'fill {X-2} {Y-1} {z-2} {X+3} {Y-1} {z+4} minecraft:smooth_stone')
        for pos in ((X, Y, z+1), (X+2, Y, z+1), (X, Y, z+2), (X+2, Y, z+2), (X+1, Y, z+3)):
            put(cmd, pos, 'minecraft:smooth_stone')
        put(cmd, (end[0], end[1]+1, end[2]), 'minecraft:sea_lantern')
        if before != 'minecraft:air':
            put(cmd, end, before)
        put(cmd, source, TANK)
        cmd(seed(source, 'water', 6000))
        put(cmd, tank, TANK)
        if filled:
            cmd(seed(tank, 'water', filled))
        put(cmd, (X, Y, z), PUMP+'[facing=east,waterlogged=false]')
        put(cmd, (X+1, Y, z), PIPE+'[west=true,north=true,south=true,waterlogged=false]')
        put(cmd, outlet, PIPE+'[north=true,south=true,waterlogged=false]')
        put(cmd, (X, Y-1, z), 'create:cogwheel[axis=x]')


def activate(cmd):
    for i in range(len(CASES)):
        z = lane(i)[2][2]
        put(cmd, (X+1, Y-1, z), 'create:creative_motor[facing=west]{ScrollValue:32}')


def measure(blocks):
    external, outlet, source, tank = blocks
    face = field(outlet['nbt'], 'south') if 'south:' in outlet['nbt'] else '{}'
    saved = field(face, 'OpenEnd') if 'OpenEnd:' in face else None
    source, tank = (fluid(field(block['nbt'], 'TankContent')) for block in (source, tank))
    # Include the retained amount. An empty stale tag has no storage or effect.
    buffer = fluid(saved) if saved else None
    return dict(end=external['id'], source=source, tank=tank, open_end=buffer)


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
                for i, (name, *_) in enumerate(CASES)}
    finally:
        host.command(f'fill {AREA} minecraft:air')
        host.command(f'forceload remove {LOAD}')
        host.call('tick', {'frozen': initial['server']['frozen']})
        (work / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')


def block_options(before, after):
    return (before,) if before == after else (before, after)


def native_run(session):
    batch = Batch()
    batch.load((X, Y+2, Z+10))
    setup(batch.command)
    batch.tick(40)
    activate(batch.command)
    for _ in range(TICKS):
        batch.tick()
        for i, (_, before, after, _) in enumerate(CASES):
            end, *devices = lane(i)
            for value in block_options(before, after):
                batch.command(f'execute if block {xyz(end)} {value} run say {value}', True)
            for pos in devices:
                batch.data(pos)
    raw = iter(batch.run(session, 'open-outlet-branches'))
    traces = {name: [] for name, *_ in CASES}
    for tick in range(1, TICKS+1):
        for name, before, after, _ in CASES:
            found = [value for value in block_options(before, after) if value in next(raw)]
            assert len(found) == 1, (name, tick, found)
            traces[name].append(measure([dict(id=found[0].split('[')[0])] +
                                        [dict(nbt=next(raw)) for _ in range(3)]))
    assert next(raw, None) is None
    return traces


def verify(traces):
    for name, _, after, filled in CASES:
        rows = traces[name]
        final = rows[-1]
        assert final['end'] == after.split('[')[0], (name, final)
        assert final['open_end'] is None and final['tank']['amount'] > filled, (name, final)
        for row in rows:
            stored = sum((row[key] or {}).get('amount', 0) for key in ('source', 'tank', 'open_end'))
            assert stored + (1000 if row['end'] == 'minecraft:water' else 0) == 6000+filled, (name, row)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--java', action='store_true')
    for flag in ('game', 'resources', 'ctl', 'create-jar', 'reference'):
        parser.add_argument('--' + flag, type=Path)
    args = parser.parse_args()
    if args.java:
        work = Path(tempfile.mkdtemp(prefix='fluid-branch-outlet-java-', dir=ROOT / '.local'))
        print(work, flush=True)
        traces = java_run(work)
    else:
        if not all((args.game, args.resources, args.ctl, args.create_jar, args.reference)):
            parser.error('Horizon requires --game, --resources, --ctl, --create-jar and --reference')
        session = NativeCheckSession(args.game, args.resources, args.ctl, args.create_jar,
                                     name='fluid-branch-outlet-native', world='CreateFluidBranchOutlet')
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
        for name, rows in traces.items():
            for tick, (got, want) in enumerate(zip(rows, reference['traces'][name], strict=True), 1):
                assert got == want, (name, tick, got, want)
    result = work / 'result.json'
    result.write_text(json.dumps(dict(passed=True, create=PINS['create_revision'], traces=traces), indent=2) + '\n')
    print(result)


if __name__ == '__main__':
    main()
