#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Compare actual pump range, fringe pressure and a nearby branch."""

import argparse
import json
from pathlib import Path
import shutil
import tempfile
import time

from bearing_native_checks import Batch
from chain_drive_checks import Original, xyz
from common import PINS, ROOT
from fan_config_checks import configure_java
from fluid_pump_java_checks import PIPE, PUMP, TANK, amount, measure, seed
from fluid_valve_java_checks import drive
from funnel_checks import put
from native_check_session import NativeCheckSession
from reference_java import BASE


X, Y, Z = 2603, 172, 1330
LOAD = '2592 1328 2639 1359'
AREA = '2599 170 1328 2623 176 1356'
TICKS = 72
LANES = dict(short=3, nearby=4, far=15, beyond=16, branched=16)


def lane_z(name):
    return Z + 5 * list(LANES).index(name)


def rig(command):
    command(f'fill {AREA} minecraft:air')
    for name, length in LANES.items():
        z = lane_z(name)
        put(command, (X-1, Y, z), TANK)
        put(command, (X, Y, z), PUMP+'[facing=east,waterlogged=false]')
        for index in range(1, length+1):
            branch = ',south=true' if index == 1 and name == 'branched' else ''
            put(command, (X+index, Y, z), PIPE+f'[east=true,west=true,waterlogged=false{branch}]')
        put(command, (X+length+1, Y, z), TANK)
        if name == 'branched':
            put(command, (X+1, Y, z+1), TANK)
        put(command, (X, Y, z-1), 'create:cogwheel[axis=x]')


def start():
    return [command for z in map(lane_z, LANES)
            for command in (seed((X-1, Y, z), 'water', 8000), drive((X-1, Y, z-1), 128, 'east'))]


def observed_cells(limit):
    cells = []
    for name, length in LANES.items():
        z = lane_z(name)
        cells.extend((name, (x, Y, z), TANK, ()) for x in (X-1, X+length+1))
        if name == 'branched':
            cells.append((name, (X+1, Y, z+1), TANK, ()))
        for index in sorted({1, min(length, limit-1), min(length, limit)} - {0}):
            sides = ('west', 'east', 'south') if name == 'branched' and index == 1 else ('west', 'east')
            cells.append((name, (X+index, Y, z), PIPE, sides))
    return cells


def observe(raw, cells):
    lanes = {name: dict(tanks=[], pipes={}) for name in LANES}
    for block, (name, pos, kind, faces) in zip(raw, cells, strict=True):
        measured = measure(block, faces)
        if kind == TANK:
            lanes[name]['tanks'].append(amount(measured))
        else:
            lanes[name]['pipes'][str(pos[0]-X)] = {
                face: [data['pressure'] or [0, 0], data['flow'] is not None]
                for face, data in measured['connections'].items()}
    return lanes


def java_run(work, limit, cells):
    host = Original()
    initial = host.call('state', {})
    assert initial['ready'] and initial['data_version'] == 3955, initial
    path = BASE / 'game/config/create-server.toml'
    original = path.read_bytes()
    host.call('tick', {'frozen': True})
    try:
        configure_java(path, original, dict(mechanicalPumpRange=limit))
        time.sleep(2)
        positions = [cell[1] for cell in cells]
        host.command(f'forceload add {LOAD}')
        host.call('observe_ticks', {'positions': positions[:1], 'ticks': 16})
        rig(host.command)
        host.call('observe_ticks', {'positions': positions[:1], 'ticks': 40})
        rows = host.call('observe_ticks', {'positions': positions, 'ticks': TICKS,
                                           'commands': start()})['samples']
        return [observe(row['blocks'], cells) for row in rows]
    finally:
        path.write_bytes(original)
        host.command(f'fill {AREA} minecraft:air')
        host.command(f'forceload remove {LOAD}')
        host.call('tick', {'frozen': initial['server']['frozen']})
        (work / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')


def native_run(session, limit, cells):
    config = session.scratch / 'config/create-server.toml'
    config.parent.mkdir(exist_ok=True)
    config.write_text(f'[fluids]\nmechanicalPumpRange = {limit}\n')
    batch = Batch()
    batch.load((X+7, Y+2, Z+10))
    rig(batch.command)
    batch.tick(40)
    for command in start():
        batch.command(command)
    for _ in range(TICKS):
        batch.tick()
        for _, pos, _, _ in cells:
            batch.data(pos)
    raw = iter(batch.run(session, 'pump-range'))
    rows = [observe([dict(id=cell[2], nbt=next(raw), properties={}) for cell in cells], cells)
            for _ in range(TICKS)]
    assert next(raw, None) is None
    return rows


def verify(rows, limit):
    for name, length in LANES.items():
        assert all(sum(row[name]['tanks']) == 8000 for row in rows), name
        final = rows[-1][name]
        assert (final['tanks'][1] > 0) == (length < limit), (name, final)
        if name == 'branched':
            assert final['tanks'][2] > 0, final
        if length >= limit:
            assert final['pipes'][str(limit-1)]['east'][0][1] > 0, (name, final)
            assert final['pipes'][str(limit)]['west'][0] == [0, 0], (name, final)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--java', action='store_true')
    parser.add_argument('--limit', type=int, choices=(4, 16), required=True)
    for flag in ('game', 'resources', 'ctl', 'create-jar', 'reference'):
        parser.add_argument('--'+flag, type=Path)
    args = parser.parse_args()
    cells = observed_cells(args.limit)
    if args.java:
        work = Path(tempfile.mkdtemp(prefix='pump-range-java-', dir=ROOT / '.local'))
        print(work, flush=True)
        rows = java_run(work, args.limit, cells)
    else:
        if not all((args.game, args.resources, args.ctl, args.create_jar, args.reference)):
            parser.error('Horizon requires --game, --resources, --ctl, --create-jar and --reference')
        session = NativeCheckSession(args.game, args.resources, args.ctl, args.create_jar,
                                     name='pump-range-native', world='CreatePumpRange')
        work = session.scratch
        print(work, flush=True)
        try:
            rows = native_run(session, args.limit, cells)
        finally:
            session.control_temp.cleanup()
            for folder in (session.resources, work / '.horizon-cache', work / 'horizon-mods'):
                shutil.rmtree(folder, ignore_errors=True)
    (work / 'observed.json').write_text(json.dumps(rows, indent=2) + '\n')
    verify(rows, args.limit)
    if not args.java:
        expected = json.loads(args.reference.read_text())
        assert expected['passed'] and expected['create'] == PINS['create_revision'] and expected['limit'] == args.limit
        for tick, (got, want) in enumerate(zip(rows, expected['rows'], strict=True), 1):
            for name in LANES:
                assert got[name] == want[name], (tick, name, got[name], want[name])
    result = work / 'result.json'
    result.write_text(json.dumps(dict(passed=True, create=PINS['create_revision'], limit=args.limit, rows=rows), indent=2) + '\n')
    print(result)


if __name__ == '__main__':
    main()
