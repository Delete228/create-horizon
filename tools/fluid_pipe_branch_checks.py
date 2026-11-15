#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Record pump pressure, fill fronts and delivery into unequal branches."""

import argparse
import json
from pathlib import Path
import shutil
import tempfile

from bearing_native_checks import Batch
from chain_drive_checks import Original, xyz
from common import PINS, ROOT
from fluid_pump_java_checks import PIPE, PUMP, TANK, amount, measure, seed
from funnel_checks import put
from native_check_session import NativeCheckSession


X, Y, Z = 2509, 169, 1206
AREA = '2506 167 1202 2514 171 1230'
LOAD = '2496 1200 2527 1231'
AIR = 'minecraft:air'
TICKS = 84
CASES = ('unequal', 'symmetric', 'partial-room')


def lane(name):
    z = Z + 8 * CASES.index(name)
    cells = [((X-1, Y, z), TANK, ()),
             ((X, Y, z), PUMP, ('west', 'east')),
             ((X+1, Y, z), PIPE, ('west', 'north', 'south'))]
    if name == 'symmetric':
        cells.append(((X+1, Y, z-1), PIPE, ('south', 'north')))
    cells.extend([((X+1, Y, z+1), PIPE, ('north', 'south')),
                  ((X+1, Y, z-(2 if name == 'symmetric' else 1)), TANK, ()),
                  ((X+1, Y, z+2), TANK, ())])
    return cells


CELLS = [cell for name in CASES for cell in lane(name)]
POSITIONS = [pos for pos, _, _ in CELLS]


def setup(cmd):
    cmd(f'fill {AREA} {AIR}')
    for pos, block, ports in CELLS:
        if block == PIPE:
            state = ','.join(f'{side}=true' for side in ports)
            block += f'[{state},waterlogged=false]'
        elif block == PUMP:
            block += '[facing=east,waterlogged=false]'
        put(cmd, pos, block)
    for name in CASES:
        cells = lane(name)
        put(cmd, (X, Y, cells[0][0][2]-1), 'create:cogwheel[axis=x]')


def activate(cmd):
    for name in CASES:
        cells = lane(name)
        source = cells[0][0]
        cmd(seed(source, 'water', 3000))
        if name == 'partial-room':
            cmd(seed(cells[-2][0], 'water', 7997))
        put(cmd, (source[0], source[1], source[2]-1), 'create:creative_motor[facing=east]{ScrollValue:32}')


def observations(rows):
    samples = {name: [] for name in CASES}
    for row in rows:
        assert len(row) == len(CELLS), row
        measured = [measure(block, cell[2]) for block, cell in zip(row, CELLS, strict=True)]
        offset = 0
        for name in CASES:
            cells = lane(name)
            views = measured[offset:offset+len(cells)]
            offset += len(cells)
            pressure = []
            flow = []
            for (_, _, ports), block in zip(cells[1:-2], views[1:-2], strict=True):
                for side in ports:
                    state = block['connections'][side]
                    pressure.append([round(value, 5) for value in state['pressure']])
                    sample = state['flow']
                    if sample:
                        assert sample['fluid'] == {'id': 'minecraft:water', 'amount': 1}, sample
                        flow.append([sample['inbound'], round(sample['progress'], 6)
                                     if sample['progress'] is not None else 1])
                    else:
                        flow.append(None)
            samples[name].append({'amounts': [amount(views[0]), amount(views[-2]), amount(views[-1])],
                                  'pressure': pressure, 'flow': flow})
    return samples


def verify(traces):
    for name, frames in traces.items():
        arrays = [frame['amounts'] for frame in frames]
        total = 10997 if name == 'partial-room' else 3000
        assert {sum(row) for row in arrays} == {total}, (name, arrays)
        pressure = [[32, 0], [0, 32], [16, 0], [0, 16], [0, 16]]
        if name == 'symmetric':
            pressure.extend([[10.66667, 0], [0, 10.66667]] * 2)
        else:
            pressure.extend([[32, 0], [0, 32]])
        assert frames[-1]['pressure'] == pressure, (name, frames[-1])
        delivery = [[b-a for a, b in zip(prev[1:], curr[1:])]
                    for prev, curr in zip(arrays, arrays[1:])]
        expected = {
            'unequal': {(0, 0), (16, 0), (8, 8)},
            'symmetric': {(0, 0), (8, 8)},
            'partial-room': {(0, 0), (3, 0), (0, 16)},
        }[name]
        assert set(map(tuple, delivery)) == expected, (name, delivery)


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
        return observations([row['blocks'] for row in rows])
    finally:
        host.command(f'fill {AREA} {AIR}')
        host.command(f'forceload remove {LOAD}')
        host.call('tick', {'frozen': initial['server']['frozen']})
        (work / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')


def native_run(session):
    batch = Batch()
    batch.load((X, Y+2, Z+8))
    setup(batch.command)
    batch.tick(40)
    activate(batch.command)
    for _ in range(TICKS):
        batch.tick()
        for pos in POSITIONS:
            batch.data(pos)
    raw = batch.run(session, 'pump-branch')
    size = len(CELLS)
    assert len(raw) == TICKS * size, raw
    return observations([[dict(id=cell[1], nbt=raw[offset+i], properties={})
                          for i, cell in enumerate(CELLS)] for offset in range(0, len(raw), size)])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--java', action='store_true')
    for flag in ('game', 'resources', 'ctl', 'create-jar', 'reference'):
        parser.add_argument('--' + flag, type=Path)
    args = parser.parse_args()
    if args.java:
        work = Path(tempfile.mkdtemp(prefix='fluid-branch-java-', dir=ROOT / '.local'))
        print(work, flush=True)
        traces = java_run(work)
    else:
        if not all((args.game, args.resources, args.ctl, args.create_jar, args.reference)):
            parser.error('Horizon requires --game, --resources, --ctl, --create-jar and --reference')
        session = NativeCheckSession(args.game, args.resources, args.ctl, args.create_jar,
                                     name='fluid-branch-native', world='CreateFluidBranch')
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
        expected = json.loads(args.reference.read_text())
        assert expected['passed'] and expected['create'] == PINS['create_revision']
        for name, rows in traces.items():
            for tick, (got, want) in enumerate(zip(rows, expected['traces'][name], strict=True), 1):
                assert got == want, (name, tick, got, want)
    result = work / 'result.json'
    result.write_text(json.dumps(dict(passed=True, create=PINS['create_revision'], traces=traces), indent=2) + '\n')
    print(result)


if __name__ == '__main__':
    main()
