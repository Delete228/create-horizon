#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Compare hand-built elbows and a pumped route crossing two chunk columns."""

import argparse
import json
from pathlib import Path
import shutil
import tempfile

from bearing_native_checks import Batch
from chain_drive_checks import Native, Original, xyz
from common import PINS, ROOT
from fluid_pump_java_checks import PIPE, PUMP, TANK, amount, measure, model_startup, seed
from fluid_tank_checks import click
from funnel_checks import block, put
from native_check_session import NativeCheckSession, wait_loaded


X, Y, Z = 2479, 168, 1136
AREA = '2473 166 1134 2485 175 1146'
LOAD = '2464 1120 2495 1151'
AIR = 'minecraft:air'
POSITIONS = [
    (X-3, Y, Z), (X-2, Y, Z), (X-2, Y, Z+1), (X-1, Y, Z+1),
    (X, Y, Z+1), (X+1, Y, Z+1), (X+1, Y+1, Z+1), (X+2, Y+1, Z+1),
]
FACES = [('west', 'south'), ('north', 'east'), ('west', 'east'),
         ('west', 'east'), ('west', 'up'), ('down', 'east')]
MOTOR = (X-1, Y, Z+2)
COG = (X, Y, Z+2)
TICKS = 65


def settle(host, ticks):
    if isinstance(host, Native):
        host.session.call('wait', ticks)
    else:
        host.call('observe_ticks', {'positions': [POSITIONS[0]], 'ticks': ticks})


def setup(cmd, wet):
    cmd(f'fill {AREA} {AIR}')
    for i, pos in enumerate(POSITIONS):
        if i in (0, len(POSITIONS)-1):
            state = TANK
        elif i == 4:
            state = PUMP + '[facing=east,waterlogged=false]'
        else:
            inlet, outlet = FACES[i-1]
            waterlogged = str(wet and i == 5).lower()
            state = f'{PIPE}[{inlet}=true,{outlet}=true,waterlogged={waterlogged}]'
        put(cmd, pos, state)
    put(cmd, COG, 'create:cogwheel[axis=x]')


def activate(cmd, kind):
    cmd(seed(POSITIONS[0], kind, 3000))
    put(cmd, MOTOR, 'create:creative_motor[facing=east]{ScrollValue:32}')


def measure_row(raw):
    return [measure(block, FACES[i-1] if 0 < i < len(raw)-1 else ())
            for i, block in enumerate(raw)]


def verify(rows, kind):
    observations = []
    for tick, row in enumerate(rows, 1):
        assert amount(row[0]) + amount(row[-1]) == 3000, row
        flows = []
        for pair, device in zip(FACES, row[1:-1], strict=True):
            states = [device['connections'][side] for side in pair]
            pressure = [[], []] if tick == 1 else [[32, 0], [0, 32]]
            assert [state['pressure'] for state in states] == pressure, (tick, states)
            values = []
            for i, state in enumerate(states):
                active = state['flow']
                if active:
                    assert active['fluid'] == {'id': f'minecraft:{kind}', 'amount': 1}, active
                    assert active['inbound'] == (i == 0), active
                values.append(None if not active else 1 if active['progress'] is None else active['progress'])
            flows.append(values)
        observations.append([flows, amount(row[-1])])
    return observations


def placement(host, work, wet):
    at, back, right = (X, Y, Z+7), (X-1, Y, Z+7), (X, Y, Z+8)
    below = (at[0], at[1]-1, at[2])
    host.command(f'fill {X} {Y-1} {Z+4} {xyz(below)} minecraft:smooth_stone')
    put(host.command, back, TANK)
    put(host.command, right, TANK)
    if wet:
        put(host.command, at, 'minecraft:water')
    click(host, work, 'place-elbow', PIPE, pos=below, face='up',
          feet=(X+.5, Y, Z+4.5), aim=(X+.5, Y, Z+7.5))

    def read():
        record = block(host, at)
        assert record['id'] == PIPE, record
        assert record['properties']['waterlogged'] == str(wet).lower(), record
        return sorted(side for side, value in record['properties'].items() if side != 'waterlogged' and value == 'true')

    settle(host, 8)
    initial = read()
    put(host.command, right, AIR)
    settle(host, 8)
    opened = read()
    put(host.command, right, TANK)
    settle(host, 8)
    joined = read()
    assert [initial, opened, joined] == [['south', 'west'], ['east', 'west'], ['south', 'west']]
    return [initial, opened, joined]


def original(work, wet):
    host = Original()
    start = host.call('state', {})
    assert start['ready'] and start['data_version'] == 3955, start
    host.call('tick', {'frozen': True})
    try:
        host.command(f'forceload add {LOAD}')
        settle(host, 14)
        setup(host.command, wet)
        host.call('observe_ticks', {'positions': POSITIONS, 'ticks': 40})
        host.call('camera', {'position': (X+.5, Y+2, Z+3.5), 'yaw': 0, 'pitch': 0})
        commands = []
        kind = 'lava' if wet else 'water'
        activate(commands.append, kind)
        rows = host.call('observe_ticks', {'positions': POSITIONS, 'ticks': TICKS,
                                           'commands': commands, 'ticker_order': True})['samples']
        if wet:
            assert all(row['blocks'][5]['properties']['waterlogged'] == 'true' for row in rows)
        observations = verify([measure_row(row['blocks']) for row in rows], kind)
        order = [POSITIONS[1:-1].index(pos) for ticker in rows[0]['ticker_order']['blockEntityTickers']
                 if (pos := tuple(ticker['pos'])) in POSITIONS[1:-1]]
        assert sorted(order) == list(range(len(FACES))), order
        assert observations[-1][1] > 0, observations[-1]
        startup = [([[None, None] for _ in FACES], 0)] * 3
        startup.extend(model_startup(len(FACES), order, 32, TICKS-3))
        for tick, ((flows, volume), (expected, delivered)) in enumerate(zip(
            observations, startup, strict=True
        ), 1):
            assert volume == delivered, (tick, volume, delivered)
            for got, want in zip((v for pair in flows for v in pair),
                                 (v for pair in expected for v in pair), strict=True):
                assert got is want or (got is not None and want is not None and abs(got-want) < 1e-7)
        return observations, placement(host, work, wet)
    finally:
        host.command(f'fill {AREA} {AIR}')
        host.command(f'forceload remove {LOAD}')
        host.command(f'item replace entity @s weapon.mainhand with {AIR}')
        host.call('camera', {'position': start['position'], 'yaw': start['yaw'], 'pitch': start['pitch']})
        host.call('tick', {'frozen': start['server']['frozen']})
        (work / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')


def native(session, wet):
    batch = Batch()
    batch.load((X, Y+2, Z+3))
    setup(batch.command, wet)
    batch.tick(40)
    kind = 'lava' if wet else 'water'
    activate(batch.command, kind)
    for _ in range(TICKS):
        batch.tick()
        for pos in POSITIONS:
            batch.data(pos)
    raw = batch.run(session, 'bend')
    assert len(raw) == TICKS * len(POSITIONS), raw
    rows = []
    for offset in range(0, len(raw), len(POSITIONS)):
        rows.append(measure_row([dict(id=kind, nbt=raw[offset+i], properties={})
                                 for i, kind in enumerate([TANK, PIPE, PIPE, PIPE, PUMP, PIPE, PIPE, TANK])]))
    observations = verify(rows, kind)
    with session:
        host = Native(session)
        host.command(f'tp @s {X+.5} {Y+2} {Z+4.5}')
        wait_loaded(session.call, [POSITIONS[0], POSITIONS[-1]])
        if wet:
            assert block(host, POSITIONS[5])['properties']['waterlogged'] == 'true'
        shapes = placement(host, session.scratch, wet)
    return observations, shapes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--java', action='store_true')
    parser.add_argument('--wet', action='store_true', help='Pump lava through a waterlogged elbow')
    for flag in ('game', 'resources', 'ctl', 'create-jar', 'reference'):
        parser.add_argument('--' + flag, type=Path)
    args = parser.parse_args()
    if args.java:
        work = Path(tempfile.mkdtemp(prefix='fluid-bend-java-', dir=ROOT / '.local'))
        print(work, flush=True)
        trace, shapes = original(work, args.wet)
    else:
        if not all((args.game, args.resources, args.ctl, args.create_jar, args.reference)):
            parser.error('Horizon requires --game, --resources, --ctl, --create-jar and --reference')
        session = NativeCheckSession(args.game, args.resources, args.ctl, args.create_jar,
                                     name='fluid-bend-native', world='CreateFluidBend')
        work = session.scratch
        print(work, flush=True)
        try:
            trace, shapes = native(session, args.wet)
        finally:
            session.control_temp.cleanup()
            for folder in (session.resources, work / '.horizon-cache', work / 'horizon-mods'):
                shutil.rmtree(folder, ignore_errors=True)
    report = {'create': PINS['create_revision'], 'trace': trace, 'shapes': shapes}
    if args.wet:
        report['waterlogged'] = True
    (work / 'observed.json').write_text(json.dumps(report, indent=2) + '\n')
    if not args.java:
        expected = json.loads(args.reference.read_text())
        assert expected.pop('passed') and report == expected
    result = work / 'result.json'
    result.write_text(json.dumps({'passed': True, **report}, indent=2) + '\n')
    print(result)


if __name__ == '__main__':
    main()
