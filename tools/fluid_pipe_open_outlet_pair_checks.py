#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Compare two open outlets and conserve the supplying tank's contents."""

import argparse
import json
from pathlib import Path
import re
import shutil
import tempfile

from bearing_native_checks import Batch
from burner_heat_java_checks import field
from chain_drive_checks import Original
from common import PINS, ROOT
from fluid_pump_java_checks import PIPE, PUMP, TANK, fluid, seed
from funnel_checks import put
from native_check_session import NativeCheckSession


X, Y, Z = 2613, 173, 1439
AREA = '2609 171 1435 2618 177 1457'
LOAD = '2608 1424 2623 1457'
TICKS = 172
AIR, LAVA, WATER, OBSIDIAN = ('minecraft:'+name for name in ('air', 'lava', 'water', 'obsidian'))
CASES = dict(split=(AIR, AIR), one_reaction=(LAVA, AIR), two_reactions=(LAVA, LAVA))
CAULDRON = 'minecraft:water_cauldron'


def lane(name):
    z = Z + 7 * list(CASES).index(name)
    return ((X+1, Y, z-2), (X+1, Y, z+2), (X+1, Y, z-1), (X+1, Y, z+1), (X-1, Y, z))


def setup(cmd, world_source):
    cmd(f'fill {AREA} minecraft:air')
    for name, before in CASES.items():
        first, second, north, south, source = lane(name)
        z = source[2]
        cmd(f'fill {X-2} {Y-1} {z-3} {X+2} {Y-1} {z+3} minecraft:smooth_stone')
        for end, value in zip((first, second), before, strict=True):
            x, y, ez = end
            for sx, sz in ((x-1, ez), (x+1, ez), (x, ez-1 if ez < z else ez+1)):
                put(cmd, (sx, y, sz), 'minecraft:smooth_stone')
            put(cmd, (x, y+1, ez), 'minecraft:sea_lantern')
            if value != AIR:
                put(cmd, end, value+'[level=0]')
        if world_source:
            put(cmd, source, CAULDRON+'[level=3]')
        else:
            put(cmd, source, TANK)
            cmd(seed(source, 'water', 6000))
        put(cmd, (X, Y, z), PUMP+'[facing=east,waterlogged=false]')
        put(cmd, (X+1, Y, z), PIPE+'[west=true,north=true,south=true,waterlogged=false]')
        for pos in (north, south):
            put(cmd, pos, PIPE+'[north=true,south=true,waterlogged=false]')
        put(cmd, (X, Y-1, z), 'create:cogwheel[axis=x]')


def power(cmd):
    for name in CASES:
        put(cmd, (X+1, Y-1, lane(name)[-1][2]), 'create:creative_motor[facing=west]{ScrollValue:32}')


def buffer(block, side):
    raw = block['nbt']
    face = field(raw, side) if re.search(r'\b' + side + r'\s*:\s*\{', raw) else '{}'
    return fluid(field(face, 'OpenEnd')) if 'OpenEnd:' in face else None


def snapshot(blocks, world_source):
    first, second, north, south, source, *pump = blocks
    buffers = [buffer(north, 'north'), buffer(south, 'south')]
    if world_source:
        consumed = source['id'] != CAULDRON
        stored = buffer(pump[0], 'west') if consumed else dict(id=WATER, amount=1000)
        return dict(ends=[first['id'], second['id']], buffers=buffers, source=stored, consumed=consumed)
    return dict(ends=[first['id'], second['id']], buffers=buffers,
                source=fluid(field(source['nbt'], 'TankContent')))


def observed(name, world_source):
    cells = lane(name)
    return (*cells, (X, Y, cells[-1][2])) if world_source else cells


def java_run(work, world_source):
    host = Original()
    initial = host.call('state', {})
    assert initial['ready'] and initial['data_version'] == 3955, initial
    host.call('tick', {'frozen': True})
    count = len(observed(next(iter(CASES)), world_source))
    positions = [pos for name in CASES for pos in observed(name, world_source)]
    try:
        host.command(f'forceload add {LOAD}')
        host.call('observe_ticks', {'positions': positions, 'ticks': 14})
        setup(host.command, world_source)
        host.call('observe_ticks', {'positions': positions, 'ticks': 40})
        commands = []
        power(commands.append)
        rows = host.call('observe_ticks', {'positions': positions, 'ticks': TICKS,
                                           'commands': commands})['samples']
        return {name: [snapshot(row['blocks'][count*i:count*(i+1)], world_source) for row in rows]
                for i, name in enumerate(CASES)}
    finally:
        host.command(f'fill {AREA} minecraft:air')
        host.command(f'forceload remove {LOAD}')
        host.call('tick', {'frozen': initial['server']['frozen']})
        (work / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')


def after(value):
    return WATER if value == AIR else OBSIDIAN


def native_start(world_source):
    batch = Batch()
    batch.load((X, Y+2, Z+7))
    setup(batch.command, world_source)
    batch.tick(40)
    power(batch.command)
    return batch


def record(batch, world_source):
    for name, initial in CASES.items():
        first, second, north, south, source, *pump = observed(name, world_source)
        for pos, value in zip((first, second), initial, strict=True):
            batch.expect(pos, after(value))
        for pos in (north, south):
            batch.data(pos)
        if world_source:
            batch.expect(source, CAULDRON+'[level=3]')
            batch.data(pump[0])
        else:
            batch.data(source)


def read(raw, world_source):
    rows = {}
    for name, initial in CASES.items():
        ends = [dict(id=after(value) if 'bearing_check' in next(raw) else value) for value in initial]
        devices = [dict(nbt=next(raw)) for _ in range(2)]
        if world_source:
            devices.extend((dict(id=CAULDRON if 'bearing_check' in next(raw) else 'minecraft:cauldron'),
                            dict(nbt=next(raw))))
        else:
            devices.append(dict(nbt=next(raw)))
        rows[name] = snapshot(ends + devices, world_source)
    return rows


def native_run(session, world_source):
    batch = native_start(world_source)
    for _ in range(TICKS):
        batch.tick()
        record(batch, world_source)
    raw = iter(batch.run(session, 'open-outlet-pair'))
    traces = {name: [] for name in CASES}
    for _ in range(TICKS):
        for name, row in read(raw, world_source).items():
            traces[name].append(row)
    assert next(raw, None) is None
    return traces


def cold_run(session, traces):
    cut = 60
    batch = native_start(True)
    batch.tick(cut)
    record(batch, True)
    raw = iter(batch.run(session, 'open-outlet-pair-before-restart'))
    before = read(raw, True)
    assert next(raw, None) is None
    assert before == {name: rows[cut-1] for name, rows in traces.items()}, before
    assert before['split']['consumed'] and all(before['split']['buffers']), before

    batch = Batch()
    batch.load((X, Y+2, Z+7))
    batch.tick(TICKS)
    record(batch, True)
    raw = iter(batch.run(session, 'open-outlet-pair-after-restart'))
    after_restart = read(raw, True)
    assert next(raw, None) is None
    assert after_restart == {name: rows[-1] for name, rows in traces.items()}, after_restart
    return dict(cut=cut, before=before, after=after_restart)


def verify(traces, world_source, *, java=False):
    temporarily_hidden = []
    total = 1000 if world_source else 6000
    for name, initial in CASES.items():
        rows = traces[name]
        if world_source and name == 'split':
            assert rows[-1]['ends'] == [AIR, AIR], rows[-1]
            assert rows[-1]['buffers'] == [dict(id=WATER, amount=500)] * 2, rows[-1]
        else:
            assert rows[-1]['ends'] == list(map(after, initial)) and rows[-1]['buffers'] == [None, None], (name, rows[-1])
        for index, row in enumerate(rows):
            amount = (row['source'] or {}).get('amount', 0)
            amount += sum((buffer or {}).get('amount', 0) for buffer in row['buffers'])
            accounted = amount + 1000 * row['ends'].count(WATER)
            if accounted == total:
                continue
            # Java briefly omits the live buffer from NBT during the pressure
            # wipe. Identical snapshots either side prove that it survives.
            assert java and 0 < index < len(rows) - 1, (name, index+1, row)
            assert rows[index-1] == rows[index+1] == (row | {key: rows[index-1][key] for key in ('source', 'buffers')}), (name, index+1, row)
            temporarily_hidden.append([name, index+1])
    return temporarily_hidden


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--java', action='store_true')
    parser.add_argument('--world-source', action='store_true', help='draw water from a cauldron instead of a tank')
    parser.add_argument('--cold', action='store_true', help='reopen the Horizon save with all three open buffers occupied')
    for flag in ('game', 'resources', 'ctl', 'create-jar', 'reference'):
        parser.add_argument('--'+flag, type=Path)
    args = parser.parse_args()
    if args.cold and (args.java or not args.world_source):
        parser.error('--cold requires Horizon and --world-source')
    cold = None
    if args.java:
        work = Path(tempfile.mkdtemp(prefix='open-outlet-pair-java-', dir=ROOT / '.local'))
        print(work, flush=True)
        traces = java_run(work, args.world_source)
    else:
        if not all((args.game, args.resources, args.ctl, args.create_jar, args.reference)):
            parser.error('Horizon requires --game, --resources, --ctl, --create-jar and --reference')
        session = NativeCheckSession(args.game, args.resources, args.ctl, args.create_jar,
                                     name='open-outlet-pair-native', world='CreateOpenOutletPair')
        work = session.scratch
        print(work, flush=True)
        try:
            traces = native_run(session, args.world_source)
            if args.cold:
                cold = cold_run(session, traces)
        finally:
            session.control_temp.cleanup()
            for folder in (session.resources, work / '.horizon-cache', work / 'horizon-mods'):
                shutil.rmtree(folder, ignore_errors=True)
    (work / 'observed.json').write_text(json.dumps(traces, indent=2) + '\n')
    temporarily_hidden = verify(traces, args.world_source, java=args.java)
    if not args.java:
        expected = json.loads(args.reference.read_text())
        assert expected['passed'] and expected['create'] == PINS['create_revision'] and expected.get('world_source', False) == args.world_source
        for name, rows in traces.items():
            for tick, (got, want) in enumerate(zip(rows, expected['traces'][name], strict=True), 1):
                if [name, tick] in expected['temporarily_hidden']:
                    want = want | {key: expected['traces'][name][tick-2][key] for key in ('source', 'buffers')}
                assert got == want, (name, tick, got, want)
    result = work / 'result.json'
    result.write_text(json.dumps(dict(passed=True, create=PINS['create_revision'], traces=traces, cold=cold,
                                     world_source=args.world_source,
                                     temporarily_hidden=temporarily_hidden), indent=2) + '\n')
    print(result)


if __name__ == '__main__':
    main()
