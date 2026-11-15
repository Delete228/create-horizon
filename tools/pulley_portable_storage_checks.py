#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Compare a Rope Pulley docking, unloading and landing an item interface."""

import argparse
import json
from pathlib import Path
import shutil
import tempfile
import time

from bearing_native_checks import Batch
from burner_heat_java_checks import items, number
from chain_drive_checks import Original, xyz
from common import PINS, ROOT
from funnel_checks import step
from native_check_session import NativeCheckSession
from portable_storage_reference_checks import BLOCK
from pulley_capacity_checks import AIR, pose
import reference_java as java


PULLEY = (2853, 164, 1818)
MOTOR = (2854, 164, 1818)
STATION = (2856, 160, 1818)
HOPPER = (2856, 159, 1818)
OUTPUT = (2856, 158, 1818)
CAMERA = (2857, 170, 1820)
COLUMN = '2848 1808'
ROOM = '2850 155 1815 2858 166 1822'
CHEST_STATE = 'minecraft:chest[facing=north,type=single,waterlogged=false]'
MOVER_STATE = f'{BLOCK}[facing=east]'
RECEIVED = {'minecraft:wheat': 3, 'minecraft:stick': 2}
POINTS = (PULLEY, STATION, HOPPER, OUTPUT)
TRACE_TICKS = 200
COLD_AT = 38


def setblock(command, pos, state):
    command(f'setblock {xyz(pos)} {state}')


def cargo(offset):
    x, y, z = PULLEY
    return tuple((x + dx, y - 1 - offset, z) for dx in (0, 1, -1))


def prepare(command, case):
    command(f'fill {ROOM} {AIR}')
    initial_offset = 1 if case == 'down' else 5
    origin, mover, chest = cargo(initial_offset)
    setblock(command, PULLEY, f'create:rope_pulley[axis=x]{{Offset:{initial_offset}f}}')
    if case == 'down':
        setblock(command, (2853, 157, 1818), 'minecraft:obsidian')
    else:
        command('fill 2853 160 1818 2853 163 1818 create:rope[waterlogged=false]')
    setblock(command, (2853, origin[1] + 1, 1818), 'create:pulley_magnet[waterlogged=false]')
    setblock(command, origin, 'minecraft:slime_block')
    setblock(command, mover, MOVER_STATE)
    setblock(command, chest, CHEST_STATE)
    command(f'item replace block {xyz(chest)} container.5 with minecraft:wheat 3')
    command(f'item replace block {xyz(chest)} container.26 '
            'with minecraft:stick[minecraft:custom_data={psi_pulley_probe:153}] 2')
    setblock(command, STATION, f'{BLOCK}[facing=west]')
    setblock(command, HOPPER, 'minecraft:hopper[facing=down]')
    setblock(command, OUTPUT, CHEST_STATE)


def power(command, case):
    rpm = -32 if case == 'down' else 32
    setblock(command, MOTOR, f'create:creative_motor[facing=west]{{ScrollValue:{rpm}}}')


def snapshot(controller, station, hopper, output):
    running, offset = pose(controller)
    return dict(running=running, offset=offset, timer=number({'nbt': station}, 'Timer', 0),
                distance=number({'nbt': station}, 'Distance', 0),
                hopper=items(hopper, 'Items'), output=items(output, 'Items'),
                marked='psi_pulley_probe:153' in output.replace(' ', ''))


def verify(trace, landed, case='up'):
    starting = next((row for row in trace if row['running']), None)
    assert starting and starting['offset'] == (1 if case == 'down' else 5), starting
    transfers = [i for i, row in enumerate(trace) if row['timer'] == 64]
    if case == 'restart':
        saved = trace[COLD_AT - 1]
        assert saved['running'] and saved['offset'] == 3 and 4 < saved['timer'] < 64, saved
        assert saved['hopper'] == saved['output'] == {'minecraft:wheat': 1}, saved
        resumed = restart_release(trace)
        assert resumed[0]['offset'] == 3 and resumed[0]['timer'] == 4, resumed[0]
    else:
        assert len(transfers) == 5 and all(b - a == 8 for a, b in zip(transfers, transfers[1:])), transfers
        stalled = trace[transfers[1]:transfers[-1] + 61]
        assert all(row['running'] and row['offset'] == 3 for row in stalled), stalled
        assert stalled[-1]['timer'] == 4, stalled[-1]
        resumed = trace[transfers[-1] + 61]['offset']
        assert (resumed > 3 if case == 'down' else resumed < 3), resumed
    landing_offset = 5 if case == 'down' else 0
    assert not trace[-1]['running'] and trace[-1]['offset'] == landing_offset and trace[-1]['timer'] == 0, trace[-1]
    assert trace[-1]['output'] == RECEIVED and trace[-1]['marked'] and not trace[-1]['hopper'], trace[-1]
    assert landed == [True, {}], landed


def restart_release(trace):
    # The launchers can take a different number of live ticks to expose their
    # control bridge. Check the held pose and compare from the release event.
    moved = next(i for i in range(COLD_AT, len(trace)) if trace[i]['offset'] < 3)
    assert moved > COLD_AT, trace[COLD_AT]
    assert all(row['running'] and row['offset'] == 3 for row in trace[COLD_AT:moved])
    landed = next(i for i in range(moved, len(trace)) if not trace[i]['running'])
    return trace[moved - 1:landed + 1]


def compare(trace, expected):
    assert len(trace) == len(expected)
    differences = []
    for tick, (actual, reference) in enumerate(zip(trace, expected), 1):
        fields = [key for key in actual if actual[key] != reference[key]]
        if fields:
            differences.append(dict(tick=tick, fields=fields, actual=actual, expected=reference))
    return differences


def java_trace(host, count):
    samples = host.call('observe_ticks', {'ticks': count, 'positions': POINTS})['samples']
    return [snapshot(*(row.get('nbt', '') for row in sample['blocks'])) for sample in samples]


def java_restart(host):
    host.call('quit', {})
    deadline = time.monotonic() + 60
    while java.process_alive(java.BASE):
        if time.monotonic() >= deadline:
            raise RuntimeError('The isolated Java client did not finish saving')
        time.sleep(.2)
    assert java.launch(java.BASE)['ready']
    host.call('tick', {'frozen': True})


def original(work, case):
    host = Original()
    initial = host.call('state', {})
    assert initial['ready'] and initial['data_version'] == 3955, initial
    host.call('tick', {'frozen': True})
    try:
        host.command('tp @s ' + xyz(CAMERA))
        host.command(f'forceload add {COLUMN}')
        step(host, 20, PULLEY)
        prepare(host.command, case)
        step(host, 8, PULLEY)
        power(host.command, case)
        if case == 'restart':
            trace = java_trace(host, COLD_AT)
            java_restart(host)
            trace.extend(java_trace(host, TRACE_TICKS - COLD_AT))
        else:
            trace = java_trace(host, TRACE_TICKS)
        _, mover, chest = cargo(5 if case == 'down' else 0)
        mover = host.call('block', {'pos': mover})
        chest = host.call('block', {'pos': chest})
        return trace, [mover['id'] == BLOCK and mover['properties']['facing'] == 'east',
                       items(chest.get('nbt', ''), 'Items')]
    finally:
        setblock(host.command, MOTOR, AIR)
        step(host, 5, PULLEY)
        host.command(f'fill {ROOM} {AIR}')
        host.command(f'forceload remove {COLUMN}')
        host.call('camera', {key: initial[key] for key in ('position', 'yaw', 'pitch')})
        host.call('tick', {'frozen': initial['server']['frozen']})
        (work / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')


def native_observe(batch, count):
    for _ in range(count):
        batch.tick()
        for pos in POINTS:
            batch.data(pos)


def native(args):
    session = NativeCheckSession(args.game, args.resources, args.ctl, args.create_jar,
                                 name='pulley-psi-native', graphics=False, world='CreatePulleyPSI')
    try:
        batch = Batch()
        batch.load(CAMERA)
        prepare(batch.command, args.case)
        batch.tick(8)
        power(batch.command, args.case)
        rows = []
        remaining = TRACE_TICKS
        if args.case == 'restart':
            native_observe(batch, COLD_AT)
            rows = batch.run(session, 'pulley-psi-before-restart')
            batch = Batch()
            batch.load(CAMERA)
            remaining -= COLD_AT
        native_observe(batch, remaining)
        _, mover, chest = cargo(5 if args.case == 'down' else 0)
        batch.expect(mover, MOVER_STATE)
        batch.data(chest)
        rows.extend(batch.run(session, 'pulley-psi'))
        trace = [snapshot(*rows[i:i + len(POINTS)]) for i in range(0, len(rows) - 2, len(POINTS))]
        landed = ['bearing_check' in rows[-2], items(rows[-1], 'Items') if 'Items' in rows[-1] else None]
        return session.scratch, trace, landed
    finally:
        session.control_temp.cleanup()
        for folder in (session.resources, session.scratch / '.horizon-cache',
                       session.scratch / 'horizon-mods'):
            shutil.rmtree(folder, ignore_errors=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--java', action='store_true')
    parser.add_argument('--case', choices=('up', 'down', 'restart'), default='up')
    for name in ('game', 'resources', 'ctl', 'create-jar', 'reference'):
        parser.add_argument('--' + name, type=Path)
    args = parser.parse_args()
    if args.java:
        work = Path(tempfile.mkdtemp(prefix='pulley-psi-java-', dir=ROOT / '.local'))
        trace, landed = original(work, args.case)
    else:
        work, trace, landed = native(args)
    differences = []
    if args.reference:
        expected = json.loads(args.reference.read_text())
        assert expected['create'] == PINS['create_revision']
        assert expected.get('case', 'up') == args.case
        comparable = COLD_AT if args.case == 'restart' else len(trace)
        differences = compare(trace[:comparable], expected['trace'][:comparable])
        if args.case == 'restart':
            differences.extend(compare(restart_release(trace), restart_release(expected['trace'])))
        if landed != expected['landed']:
            differences.append(dict(actual_landing=landed, expected_landing=expected['landed']))
    result = work / 'result.json'
    result.write_text(json.dumps(dict(create=PINS['create_revision'], case=args.case, trace=trace, landed=landed,
                                      differences=differences), indent=2) + '\n')
    print(result, flush=True)
    verify(trace, landed, args.case)
    assert not differences, differences[:5]


if __name__ == '__main__':
    main()
