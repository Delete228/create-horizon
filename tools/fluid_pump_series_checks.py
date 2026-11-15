#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Observe both pressure contributions in a line with two pumps."""

import argparse
import json
from pathlib import Path
import shutil
import tempfile

from bearing_native_checks import Batch
from chain_drive_checks import Original, xyz
from common import PINS, ROOT
from fluid_pump_java_checks import PIPE, PUMP, TANK, amount, measure, seed
from fluid_valve_java_checks import drive
from funnel_checks import put
from native_check_session import NativeCheckSession


X, Y, Z = 2707, 173, 1335
LOAD = '2704 1328 2735 1359'
AREA = '2704 170 1332 2720 176 1354'
CASES = dict(adjacent=(0, 32, 64), equal=(3, 32, 32), unequal=(3, 16, 64))
PHASES = dict(first=54, both=90, stopped_second=34, restarted=34)


def lane(name):
    index = list(CASES).index(name)
    middle, _, _ = CASES[name]
    z = Z + 6 * index
    blocks = [TANK, PIPE, PUMP, *([PIPE] * middle), PUMP, PIPE, TANK]
    return [((X + x, Y, z), kind) for x, kind in enumerate(blocks)]


def branch(name):
    if name == 'adjacent':
        return []
    z = lane(name)[0][0][2]
    return [((X+4, Y, z+offset), PIPE) for offset in (1, 2)]


def cells(capped_branch):
    return [cell for name in CASES for cell in lane(name) + (branch(name) if capped_branch else [])]


def setup(command, capped_branch):
    command(f'fill {AREA} minecraft:air')
    for name in CASES:
        cells = lane(name)
        for pos, kind in cells:
            state = {
                PIPE: '[east=true,west=true,waterlogged=false]',
                PUMP: '[facing=east,waterlogged=false]',
            }.get(kind, '')
            put(command, pos, kind + state)
        for ((x, y, z), _), offset in zip((cells[2], cells[-3]), (-1, 1), strict=True):
            put(command, (x, y+offset, z), 'create:cogwheel[axis=x]')
        arms = branch(name) if capped_branch else []
        if arms:
            x, y, z = arms[-1][0]
            put(command, (x, y, z+1), 'minecraft:stone')
            for pos, kind in reversed(arms):
                put(command, pos, kind+'[north=true,south=true,waterlogged=false]')
            put(command, (x, y, z-2), PIPE+'[east=true,west=true,south=true,waterlogged=false]')


def commands(phase):
    actions = []
    for name, (_, first, second) in CASES.items():
        cells = lane(name)
        (x, y, z), _ = cells[2 if phase == 'first' else -3]
        if phase == 'first':
            actions.extend((seed(cells[0][0], 'water', 8000), drive((x-1, y-1, z), first, 'east')))
        elif phase == 'stopped_second':
            actions.append(f'setblock {xyz((x-1, y+1, z))} minecraft:air')
        else:
            actions.append(drive((x-1, y+1, z), second, 'east'))
    return actions


def observe(blocks, capped_branch):
    lanes = {}
    offset = 0
    for name in CASES:
        count = len(lane(name))
        physical = ('west', 'east', 'south') if capped_branch and branch(name) else ('west', 'east')
        row = [measure(block, physical if index == 4 else ('west', 'east'))
               for index, block in enumerate(blocks[offset:offset+count])]
        offset += count
        lanes[name] = dict(tanks=[amount(row[0]), amount(row[-1])],
                           devices=[{face: [value['pressure'] or [0, 0],
                                             value['flow'] is not None]
                                     for face, value in block['connections'].items()}
                                    for block in row[1:-1]])
        if capped_branch and branch(name):
            dead = [measure(block, ('north', 'south'))['connections']
                    for block in blocks[offset:offset+len(branch(name))]]
            assert all(not face['pressure'] and face['flow'] is None
                       for device in dead for face in device.values()), (name, dead)
            offset += len(dead)
    assert offset == len(blocks)
    return lanes


def java_run(work, capped_branch):
    host = Original()
    initial = host.call('state', {})
    assert initial['ready'] and initial['data_version'] == 3955, initial
    host.call('tick', {'frozen': True})
    positions = [cell[0] for cell in cells(capped_branch)]
    try:
        host.command(f'forceload add {LOAD}')
        host.call('observe_ticks', {'positions': positions[:1], 'ticks': 20})
        setup(host.command, capped_branch)
        host.call('observe_ticks', {'positions': positions[:1], 'ticks': 40})
        # Speed-change callbacks must see the actual previous RPM when
        # removing a source. The bridge runs these commands before sampling.
        return {phase: [observe(row['blocks'], capped_branch) for row in host.call('observe_ticks', {
            'positions': positions, 'ticks': ticks,
            'commands': ['tick unfreeze', *commands(phase)]})['samples']]
                for phase, ticks in PHASES.items()}
    finally:
        host.command(f'fill {AREA} minecraft:air')
        host.command(f'forceload remove {LOAD}')
        host.call('tick', {'frozen': initial['server']['frozen']})
        (work / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')


def native_run(session, capped_branch):
    batch = Batch()
    batch.load((X+5, Y+2, Z+6))
    setup(batch.command, capped_branch)
    all_cells = cells(capped_branch)
    batch.tick(40)
    for phase, ticks in PHASES.items():
        for command in commands(phase):
            batch.command(command)
        for _ in range(ticks):
            batch.tick()
            for pos, _ in all_cells:
                batch.data(pos)
    raw = iter(batch.run(session, 'pump-series'))
    traces = {phase: [observe([dict(id=kind, nbt=next(raw), properties={}) for _, kind in all_cells], capped_branch)
                      for _ in range(ticks)] for phase, ticks in PHASES.items()}
    assert next(raw, None) is None
    return traces


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--java', action='store_true')
    parser.add_argument('--capped-branch', action='store_true', help='add a short blind branch between pumps')
    for flag in ('game', 'resources', 'ctl', 'create-jar', 'reference'):
        parser.add_argument('--'+flag, type=Path)
    args = parser.parse_args()
    if args.java:
        work = Path(tempfile.mkdtemp(prefix='pump-series-java-', dir=ROOT / '.local'))
        print(work, flush=True)
        traces = java_run(work, args.capped_branch)
    else:
        if not all((args.game, args.resources, args.ctl, args.create_jar, args.reference)):
            parser.error('Horizon requires --game, --resources, --ctl, --create-jar and --reference')
        session = NativeCheckSession(args.game, args.resources, args.ctl, args.create_jar,
                                     name='pump-series-native', world='CreatePumpSeries')
        work = session.scratch
        print(work, flush=True)
        try:
            traces = native_run(session, args.capped_branch)
        finally:
            session.control_temp.cleanup()
            for folder in (session.resources, work / '.horizon-cache', work / 'horizon-mods'):
                shutil.rmtree(folder, ignore_errors=True)
    (work / 'observed.json').write_text(json.dumps(traces, indent=2) + '\n')
    for phase, rows in traces.items():
        assert all(sum(lane['tanks']) == 8000 for row in rows for lane in row.values()), phase
    if not args.java:
        expected = json.loads(args.reference.read_text())
        assert expected['passed'] and expected['create'] == PINS['create_revision']
        assert expected.get('capped_branch', False) == args.capped_branch, expected.keys()
        for phase, rows in traces.items():
            for tick, (got, want) in enumerate(zip(rows, expected['traces'][phase], strict=True), 1):
                for name in CASES:
                    assert got[name] == want[name], (phase, tick, name, got[name], want[name])
    result = work / 'result.json'
    result.write_text(json.dumps(dict(passed=True, create=PINS['create_revision'], traces=traces,
                                     capped_branch=args.capped_branch), indent=2) + '\n')
    print(result)


if __name__ == '__main__':
    main()
