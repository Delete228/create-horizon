#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Compare a Fluid Valve on one of two outlets while the other stays open."""

import argparse
import json
from pathlib import Path
import shutil
import tempfile

from bearing_native_checks import Batch
from burner_heat_java_checks import field, number
from chain_drive_checks import Original, xyz
from common import PINS, ROOT
from fluid_pump_java_checks import PIPE, PUMP, TANK, fluid, seed
from fluid_valve_java_checks import VALVE, drive
from funnel_checks import put
from native_check_session import NativeCheckSession


X, Y, Z = 2583, 172, 1290
LOAD = '2576 1280 2591 1295'
AREA = '2579 170 1286 2587 176 1294'
SOURCE = (X-1, Y, Z)
JUNCTION = (X+1, Y, Z)
VALVE_POS = (X+1, Y, Z+1)
PLAIN = (X+1, Y, Z-1)
GATED = (X+1, Y, Z+2)
PUMP_POS = (X, Y, Z)
POSITIONS = (SOURCE, PLAIN, GATED, VALVE_POS)
MOTOR = (X-1, Y, Z+1)
REDSTONE = (X, Y+1, Z+1)
SECOND_VALVE = (X+1, Y, Z-1)
SECOND_TANK = (X+1, Y, Z-2)
BYPASS = (X+2, Y, Z)
SECOND_MOTOR = (X+3, Y, Z-1)
SECOND_SIGNAL = (X+2, Y+1, Z-1)
PHASES = (
    ('closed', 48, ()),
    ('opening', 46, (drive(MOTOR, 32, 'east'),)),
    ('closing', 42, (f'setblock {xyz(REDSTONE)} minecraft:redstone_block',)),
    ('reopening', 42, (f'setblock {xyz(REDSTONE)} minecraft:air',)),
)
DOUBLE_PHASES = (
    ('closed', 32, ()),
    ('open-south', 46, (drive(MOTOR, 32, 'east'),)),
    ('open-both', 46, (drive(SECOND_MOTOR, -32, 'west'),)),
    ('close-south', 42, (f'setblock {xyz(REDSTONE)} minecraft:redstone_block',)),
    ('close-both', 42, (f'setblock {xyz(SECOND_SIGNAL)} minecraft:redstone_block',)),
    ('open-north', 42, (f'setblock {xyz(SECOND_SIGNAL)} minecraft:air',)),
)


def setup(cmd, double):
    cmd(f'fill {AREA} minecraft:air')
    for pos in (SOURCE, BYPASS if double else PLAIN, GATED):
        put(cmd, pos, TANK)
    put(cmd, PUMP_POS, PUMP+'[facing=east,waterlogged=false]')
    junction = '[west=true,north=true,south=true,waterlogged=false'
    put(cmd, JUNCTION, PIPE + junction + (',east=true]' if double else ']'))
    valve = VALVE+'[facing=up,axis_along_first=true,enabled=false,waterlogged=false]'
    put(cmd, VALVE_POS, valve)
    put(cmd, (X, Y, Z+1), 'create:gearshift[axis=x,powered=false]')
    put(cmd, (X, Y-1, Z), 'create:cogwheel[axis=x]')
    if double:
        put(cmd, SECOND_TANK, TANK)
        put(cmd, SECOND_VALVE, valve)
        put(cmd, (X+2, Y, Z-1), 'create:gearshift[axis=x,powered=false]')


def activate(cmd):
    cmd(seed(SOURCE, 'water', 7000))
    cmd(drive((X+1, Y-1, Z), 32, 'west'))


def snapshot(nbts, enabled, valve_count):
    def amount(raw):
        saved = fluid(field(raw, 'TankContent'))
        return saved['amount'] if saved else 0

    def pointer(raw):
        nbt = field(raw, 'Pointer')
        return [round(number({'nbt': nbt}, key), 6) for key in ('Value', 'Target', 'Speed')]

    values = [amount(raw) for raw in nbts[:-valve_count]]
    pointers = [pointer(raw) for raw in nbts[-valve_count:]]
    return dict(tanks=values, enabled=enabled if valve_count > 1 else enabled[0],
                pointer=pointers if valve_count > 1 else pointers[0])


def java_run(work, double, positions, valves, phases):
    host = Original()
    initial = host.call('state', {})
    assert initial['ready'] and initial['data_version'] == 3955, initial
    host.call('tick', {'frozen': True})
    traces = {}
    try:
        host.command(f'forceload add {LOAD}')
        host.call('observe_ticks', {'positions': positions, 'ticks': 16})
        setup(host.command, double)
        host.call('observe_ticks', {'positions': positions, 'ticks': 40})
        first = []
        activate(first.append)
        for name, ticks, commands in phases:
            rows = host.call('observe_ticks', {'positions': positions, 'ticks': ticks,
                                               'commands': first + list(commands)})['samples']
            first.clear()
            traces[name] = [snapshot([block['nbt'] for block in row['blocks']],
                                     [block['properties']['enabled'] == 'true'
                                      for block in row['blocks'][-len(valves):]], len(valves)) for row in rows]
    finally:
        host.command(f'fill {AREA} minecraft:air')
        host.command(f'forceload remove {LOAD}')
        host.call('tick', {'frozen': initial['server']['frozen']})
        (work / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')
    return traces


def native_run(session, double, positions, valves, phases, cold):
    def record(batch):
        for pos in positions:
            batch.data(pos)
        for pos in valves:
            batch.expect(pos, VALVE+'[enabled=true]')

    def read(raw):
        return snapshot([next(raw) for _ in positions],
                        ['bearing_check' in next(raw) for _ in valves], len(valves))

    batch = Batch()
    batch.load((X, Y+2, Z))
    setup(batch.command, double)
    batch.tick(40)
    activate(batch.command)
    for _, ticks, commands in phases:
        for command in commands:
            batch.command(command)
        for _ in range(ticks):
            batch.tick()
            record(batch)
    if cold:
        batch.command(f'setblock {X+1} {Y-1} {Z} minecraft:air')
        batch.tick(12)
        record(batch)
    raw = iter(batch.run(session, 'branch-valve'))
    traces = {name: [read(raw) for _ in range(ticks)] for name, ticks, _ in phases}
    restart = None
    if cold:
        parked = read(raw)
        batch = Batch()
        batch.load((X, Y+2, Z))
        record(batch)
        batch.command(drive((X+1, Y-1, Z), 32, 'west'))
        batch.tick(50)
        record(batch)
        resumed = iter(batch.run(session, 'branch-valve-restart'))
        after, running = read(resumed), read(resumed)
        assert next(resumed, None) is None
        assert parked == after, (parked, after)
        assert sum(running['tanks']) == 7000 and running['enabled'] == [False, True], running
        assert running['tanks'][1] > after['tanks'][1] and running['tanks'][3] > after['tanks'][3], running
        assert running['tanks'][2] == after['tanks'][2], running
        restart = dict(before=parked, after=after, resumed=running)
    assert next(raw, None) is None
    return traces, restart


def verify(traces, double):
    for name, rows in traces.items():
        assert all(sum(row['tanks']) == 7000 for row in rows), name
        assert rows[-1]['tanks'][1] > rows[0]['tanks'][1], name
    if double:
        expected = ([False, False], [True, False], [True, True], [False, True],
                    [False, False], [False, True])
        for (name, rows), enabled in zip(traces.items(), expected, strict=True):
            assert rows[-1]['enabled'] == enabled, (name, rows[-1])
            for index, state in enumerate(enabled, 2):
                changed = rows[-1]['tanks'][index] > rows[-6]['tanks'][index]
                assert changed == state, (name, index, rows[-1])
        return
    assert all(not row['enabled'] and not row['tanks'][2] for row in traces['closed'])
    assert traces['opening'][-1]['enabled'] and traces['opening'][-1]['tanks'][2] > 0
    parked = traces['closing'][-1]
    assert not parked['enabled'] and all(row['tanks'][2] == parked['tanks'][2] for row in traces['closing'][-8:])
    assert traces['reopening'][-1]['enabled'] and traces['reopening'][-1]['tanks'][2] > parked['tanks'][2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--java', action='store_true')
    parser.add_argument('--double', action='store_true', help='gate both branches independently')
    parser.add_argument('--cold', action='store_true', help='reopen the Horizon save with two parked valves')
    for flag in ('game', 'resources', 'ctl', 'create-jar', 'reference'):
        parser.add_argument('--' + flag, type=Path)
    args = parser.parse_args()
    if args.cold and (args.java or not args.double):
        parser.error('--cold applies to the two-valve Horizon fixture')
    valves = (VALVE_POS, SECOND_VALVE) if args.double else (VALVE_POS,)
    positions = (SOURCE, BYPASS, GATED, SECOND_TANK, *valves) if args.double else POSITIONS
    phases = DOUBLE_PHASES if args.double else PHASES
    restart = None
    if args.java:
        work = Path(tempfile.mkdtemp(prefix='valve-branch-java-', dir=ROOT / '.local'))
        print(work, flush=True)
        traces = java_run(work, args.double, positions, valves, phases)
    else:
        if not all((args.game, args.resources, args.ctl, args.create_jar, args.reference)):
            parser.error('Horizon requires --game, --resources, --ctl, --create-jar and --reference')
        session = NativeCheckSession(args.game, args.resources, args.ctl, args.create_jar,
                                     name='valve-branch-native', world='CreateBranchValve')
        work = session.scratch
        print(work, flush=True)
        try:
            traces, restart = native_run(session, args.double, positions, valves, phases, args.cold)
        finally:
            session.control_temp.cleanup()
            for folder in (session.resources, work / '.horizon-cache', work / 'horizon-mods'):
                shutil.rmtree(folder, ignore_errors=True)
    (work / 'observed.json').write_text(json.dumps(traces, indent=2) + '\n')
    verify(traces, args.double)
    if not args.java:
        reference = json.loads(args.reference.read_text())
        assert reference['passed'] and reference['create'] == PINS['create_revision']
        for name, rows in traces.items():
            for tick, (got, want) in enumerate(zip(rows, reference['traces'][name], strict=True), 1):
                assert got == want, (name, tick, got, want)
    result = work / 'result.json'
    result.write_text(json.dumps(dict(passed=True, create=PINS['create_revision'],
                                     traces=traces, restart=restart), indent=2) + '\n')
    print(result)


if __name__ == '__main__':
    main()
