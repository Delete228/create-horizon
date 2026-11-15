#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Compare simultaneous inlet and outlet branches on a single pump."""

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


X, Y, Z = 2757, 173, 1589
LOAD = '2752 1584 2767 1615'
AREA = '2753 171 1586 2762 178 1611'
TICKS = 116
CASES = {
    'equal': ((2000, 2000, 0, 0), False, False),
    'long_paths': ((2000, 2000, 0, 0), True, True),
    'low_inlet': ((3, 2000, 0, 0), False, True),
    'low_headroom': ((2000, 2000, 7997, 0), True, False),
}
STORAGE = ('north_in', 'south_in', 'north_out', 'south_out')
EW, NS = ('west', 'east'), ('north', 'south')


def cells(name):
    z = Z + 6 * list(CASES).index(name)
    _, long_in, long_out = CASES[name]
    devices = dict(
        north_in=((X-1, Y, z-1-int(long_in)), TANK, ()),
        south_in=((X-1, Y, z+1), TANK, ()),
        north_out=((X+1, Y, z-1), TANK, ()),
        south_out=((X+1, Y, z+1+int(long_out)), TANK, ()),
        inlet=((X-1, Y, z), PIPE, ('east', *NS)),
        pump=((X, Y, z), PUMP, EW),
        outlet=((X+1, Y, z), PIPE, ('west', *NS)),
    )
    if long_in:
        devices['in_extension'] = ((X-1, Y, z-1), PIPE, NS)
    if long_out:
        devices['out_extension'] = ((X+1, Y, z+1), PIPE, NS)
    return devices


LANES = {name: cells(name) for name in CASES}
CELLS = [device for lane in LANES.values() for device in lane.values()]
POSITIONS = [pos for pos, _, _ in CELLS]


def setup(command):
    command(f'fill {AREA} minecraft:air')
    for name, lane in LANES.items():
        for pos, kind, ports in lane.values():
            state = kind
            if kind == PIPE:
                state += '[' + ','.join(f'{port}=true' for port in ports) + ']'
            elif kind == PUMP:
                state += '[facing=east]'
            put(command, pos, state)
        for key, volume in zip(STORAGE, CASES[name][0], strict=True):
            if volume:
                command(seed(lane[key][0], 'water', volume))
        _, _, z = lane['pump'][0]
        put(command, (X, Y-1, z), 'create:cogwheel[axis=x]')


def power(command):
    for lane in LANES.values():
        x, y, z = lane['pump'][0]
        put(command, (x-1, y-1, z), 'create:creative_motor[facing=east]{ScrollValue:32}')


def observe(blocks):
    observed = iter(blocks)
    frame = {}
    for name, lane in LANES.items():
        tanks, pipes = {}, {}
        for key, (_, _, ports) in lane.items():
            state = measure(next(observed), ports)
            if not ports:
                tanks[key] = amount(state)
                continue
            for connection in state['connections'].values():
                connection['pressure'] = [round(value, 5) for value in connection['pressure']]
                if connection['flow'] and connection['flow']['progress'] is not None:
                    connection['flow']['progress'] = round(connection['flow']['progress'], 6)
            pipes[key] = state['connections']
        frame[name] = dict(tanks=tanks, pipes=pipes)
    assert next(observed, None) is None
    return frame


def java_run(work):
    host = Original()
    initial = host.call('state', {})
    assert initial['ready'] and initial['data_version'] == 3955, initial
    host.call('tick', {'frozen': True})
    try:
        host.command(f'forceload add {LOAD}')
        host.call('observe_ticks', {'positions': POSITIONS[:1], 'ticks': 20})
        setup(host.command)
        host.call('observe_ticks', {'positions': POSITIONS[:1], 'ticks': 40})
        commands = []
        power(commands.append)
        rows = host.call('observe_ticks', {'positions': POSITIONS, 'ticks': TICKS,
                                           'commands': commands})['samples']
        return [observe(row['blocks']) for row in rows]
    finally:
        host.command(f'fill {AREA} minecraft:air')
        host.command(f'forceload remove {LOAD}')
        host.call('tick', {'frozen': initial['server']['frozen']})
        (work / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')


def native_run(session):
    batch = Batch()
    batch.load((X, Y+2, Z+8))
    setup(batch.command)
    batch.tick(40)
    power(batch.command)
    for _ in range(TICKS):
        batch.tick()
        for pos in POSITIONS:
            batch.data(pos)
    raw = iter(batch.run(session, 'pipe-cross-branch'))
    frames = [observe(dict(id=kind, nbt=next(raw), properties={}) for _, kind, _ in CELLS)
              for _ in range(TICKS)]
    assert next(raw, None) is None
    return frames


def verify(frames):
    summary = {}
    for name, (volumes, _, _) in CASES.items():
        sequence = [[row[name]['tanks'][key] for key in STORAGE] for row in frames]
        assert sequence[0] == list(volumes), (name, sequence[0])
        assert all(sum(row) == sum(volumes) for row in sequence), (name, sequence)
        assert sequence[-1][2] > volumes[2] and sequence[-1][3] > volumes[3], (name, sequence[-1])
        summary[name] = {'initial': sequence[0], 'final': sequence[-1]}
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--java', action='store_true')
    for flag in ('game', 'resources', 'ctl', 'create-jar', 'reference'):
        parser.add_argument('--'+flag, type=Path)
    args = parser.parse_args()
    if args.java:
        work = Path(tempfile.mkdtemp(prefix='pipe-cross-branch-java-', dir=ROOT / '.local'))
        print(work, flush=True)
        frames = java_run(work)
    else:
        if not all((args.game, args.resources, args.ctl, args.create_jar, args.reference)):
            parser.error('Horizon requires --game, --resources, --ctl, --create-jar and --reference')
        session = NativeCheckSession(args.game, args.resources, args.ctl, args.create_jar,
                                     name='pipe-cross-branch-native', world='CreatePipeCrossBranch')
        work = session.scratch
        print(work, flush=True)
        try:
            frames = native_run(session)
        finally:
            session.control_temp.cleanup()
            for folder in (session.resources, work / '.horizon-cache', work / 'horizon-mods'):
                shutil.rmtree(folder, ignore_errors=True)

    (work / 'observed.json').write_text(json.dumps(frames, indent=2) + '\n')
    summary = verify(frames)
    if not args.java:
        reference = json.loads(args.reference.read_text())
        assert reference['passed'] and reference['create'] == PINS['create_revision']
        expected = json.loads(args.reference.with_name('observed.json').read_text())
        for tick, (got, want) in enumerate(zip(frames, expected, strict=True), 1):
            for name in CASES:
                assert got[name] == want[name], (name, tick, got[name], want[name])
    result = work / 'result.json'
    result.write_text(json.dumps(dict(passed=True, create=PINS['create_revision'],
                                     lane_frames=TICKS * len(CASES), summary=summary), indent=2) + '\n')
    print(result)


if __name__ == '__main__':
    main()
