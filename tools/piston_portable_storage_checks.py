#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Compare a vertical Mechanical Piston carrying a portable item dock."""

import argparse
import json
from pathlib import Path
import shutil
import tempfile

from bearing_native_checks import Batch
from burner_heat_java_checks import items
from chain_drive_checks import Original, xyz
from common import PINS, ROOT
from funnel_checks import step
from native_check_session import NativeCheckSession
from pulley_portable_storage_checks import (
    AIR, BLOCK, CHEST_STATE, MOVER_STATE, RECEIVED, TRACE_TICKS, compare,
    java_restart, setblock, snapshot,
)


PISTON = (2885, 164, 1818)
MOTOR = (2884, 164, 1818)
ORIGIN = (2885, 165, 1818)
MOVER = (2886, 165, 1818)
CHEST = (2884, 165, 1818)
STATION = (2888, 167, 1818)
HOPPER = (2888, 166, 1818)
OUTPUT = (2888, 165, 1818)
LANDED_MOVER = (2886, 169, 1818)
LANDED_CHEST = (2884, 169, 1818)
CAMERA = (2889, 174, 1820)
COLUMN = '2880 1808'
ROOM = '2882 157 1815 2891 171 1822'
POINTS = (PISTON, STATION, HOPPER, OUTPUT)
COLD_AT = 38
DOCK_OFFSET = 2


def prepare(command):
    command(f'fill {ROOM} {AIR}')
    setblock(command, PISTON, 'create:mechanical_piston[facing=up,axis_along_first=true]')
    command('fill 2885 160 1818 2885 163 1818 create:piston_extension_pole[facing=up]')
    setblock(command, ORIGIN, 'minecraft:slime_block')
    setblock(command, MOVER, MOVER_STATE)
    setblock(command, CHEST, CHEST_STATE)
    command(f'item replace block {xyz(CHEST)} container.5 with minecraft:wheat 3')
    command(f'item replace block {xyz(CHEST)} container.26 '
            'with minecraft:stick[minecraft:custom_data={psi_pulley_probe:153}] 2')
    setblock(command, STATION, f'{BLOCK}[facing=west]')
    setblock(command, HOPPER, 'minecraft:hopper[facing=down]')
    setblock(command, OUTPUT, CHEST_STATE)


def power(command):
    setblock(command, MOTOR, 'create:creative_motor[facing=east]{ScrollValue:-32}')


def release(trace):
    moved = next(i for i in range(COLD_AT, len(trace)) if trace[i]['offset'] > DOCK_OFFSET)
    assert moved > COLD_AT, trace[COLD_AT]
    assert all(row['running'] and row['offset'] == DOCK_OFFSET for row in trace[COLD_AT:moved])
    assert trace[moved - 1]['timer'] == 4, trace[moved - 1]
    end = next(i for i in range(moved, len(trace)) if not trace[i]['running'])
    return trace[moved - 1:end + 1]


def verify(trace, landed, cold):
    started = next((row for row in trace if row['running']), None)
    assert started and started['offset'] == 0, started
    if cold:
        saved = trace[COLD_AT - 1]
        assert saved['running'] and saved['offset'] == DOCK_OFFSET and 4 < saved['timer'] < 64, saved
        assert saved['hopper'] == saved['output'] == {'minecraft:wheat': 1}, saved
        release(trace)
    else:
        transfers = [i for i, row in enumerate(trace) if row['timer'] == 64]
        assert len(transfers) == 5 and all(b - a == 8 for a, b in zip(transfers, transfers[1:])), transfers
        held = trace[transfers[1]:transfers[-1] + 61]
        assert all(row['running'] and row['offset'] == DOCK_OFFSET for row in held), held
        assert held[-1]['timer'] == 4 and trace[transfers[-1] + 61]['offset'] > DOCK_OFFSET
    assert not trace[-1]['running'] and trace[-1]['offset'] == 4 and trace[-1]['timer'] == 0, trace[-1]
    assert trace[-1]['output'] == RECEIVED and trace[-1]['marked'] and not trace[-1]['hopper'], trace[-1]
    assert landed == [True, {}], landed


def java_observe(host, count):
    rows = host.call('observe_ticks', {'ticks': count, 'positions': POINTS})['samples']
    return [snapshot(*(row.get('nbt', '') for row in sample['blocks'])) for sample in rows]


def original(work, cold):
    host = Original()
    initial = host.call('state', {})
    assert initial['ready'] and initial['data_version'] == 3955, initial
    host.call('tick', {'frozen': True})
    try:
        host.command('tp @s ' + xyz(CAMERA))
        host.command(f'forceload add {COLUMN}')
        step(host, 20, PISTON)
        prepare(host.command)
        step(host, 8, PISTON)
        power(host.command)
        if cold:
            trace = java_observe(host, COLD_AT)
            java_restart(host)
            trace.extend(java_observe(host, TRACE_TICKS - COLD_AT))
        else:
            trace = java_observe(host, TRACE_TICKS)
        mover = host.call('block', {'pos': LANDED_MOVER})
        chest = host.call('block', {'pos': LANDED_CHEST})
        landed = [mover['id'] == BLOCK and mover['properties']['facing'] == 'east',
                  items(chest.get('nbt', ''), 'Items') if chest['id'] != AIR else None]
        return trace, landed
    finally:
        setblock(host.command, MOTOR, AIR)
        step(host, 5, PISTON)
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
                                 name='piston-psi-native', graphics=False, world='CreatePistonPSI')
    try:
        batch = Batch()
        batch.load(CAMERA)
        prepare(batch.command)
        batch.tick(8)
        power(batch.command)
        rows = []
        remaining = TRACE_TICKS
        if args.cold:
            native_observe(batch, COLD_AT)
            rows = batch.run(session, 'piston-psi-before-restart')
            batch = Batch()
            batch.load(CAMERA)
            remaining -= COLD_AT
        native_observe(batch, remaining)
        batch.expect(LANDED_MOVER, MOVER_STATE)
        batch.data(LANDED_CHEST)
        rows.extend(batch.run(session, 'piston-psi'))
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
    parser.add_argument('--cold', action='store_true')
    for name in ('game', 'resources', 'ctl', 'create-jar', 'reference'):
        parser.add_argument('--' + name, type=Path)
    args = parser.parse_args()
    if args.java:
        work = Path(tempfile.mkdtemp(prefix='piston-psi-java-', dir=ROOT / '.local'))
        trace, landed = original(work, args.cold)
    else:
        work, trace, landed = native(args)
    result = work / 'result.json'
    report = dict(create=PINS['create_revision'], cold=args.cold, trace=trace, landed=landed)
    result.write_text(json.dumps(report, indent=2) + '\n')
    print(result, flush=True)
    verify(trace, landed, args.cold)
    if args.reference:
        expected = json.loads(args.reference.read_text())
        assert expected['create'] == PINS['create_revision'] and args.cold == expected['cold']
        comparable = COLD_AT if args.cold else TRACE_TICKS
        differences = compare(trace[:comparable], expected['trace'][:comparable])
        if args.cold:
            differences.extend(compare(release(trace), release(expected['trace'])))
        report['differences'] = differences
        result.write_text(json.dumps(report, indent=2) + '\n')
        assert not differences and landed == expected['landed'], differences[:4]


if __name__ == '__main__':
    main()
