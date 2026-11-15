#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Compare a Gantry Carriage docking and unloading a mounted chest."""

import argparse
import json
from pathlib import Path
import shutil
import struct
import tempfile

from bearing_native_checks import Batch
from bearing_repeat_checks import POSES
from burner_heat_java_checks import items, number
from chain_drive_checks import Original, xyz
from common import PINS, ROOT
from funnel_checks import step
from gantry_capacity_checks import CARRIAGE, CARRIAGE_STATE
from native_check_session import NativeCheckSession
from pulley_portable_storage_checks import (
    AIR, BLOCK, CHEST_STATE, RECEIVED, TRACE_TICKS, compare, java_restart, setblock,
)
from saved_block_checks import read_saved_chunk_tag


START = (2915, 165, 1819)
END = (2919, 165, 1819)
MOTOR = (2914, 164, 1819)
ORIGIN = (2915, 166, 1819)
MOVER = (2915, 166, 1820)
CHEST = (2915, 166, 1818)
STATION = (2917, 166, 1822)
HOPPER = (2917, 165, 1822)
OUTPUT = (2917, 164, 1822)
LANDED_MOVER = (2919, 166, 1820)
LANDED_CHEST = (2919, 166, 1818)
CAMERA = (2921, 171, 1822)
COLUMN = '2912 1808'
ROOM = '2913 162 1816 2922 169 1824'
MOVER_STATE = f'{BLOCK}[facing=south]'
POINTS = (STATION, HOPPER, OUTPUT, END)
COLD_AT = 40
DOCKS = ('horizon:attachments', 'create', 'gantry_item_docks', 'value')


def prepare(command):
    command(f'fill {ROOM} {AIR}')
    for x in range(START[0], END[0] + 1):
        setblock(command, (x, START[1] - 1, START[2]), 'create:gantry_shaft[facing=east]')
    setblock(command, START, CARRIAGE_STATE)
    setblock(command, ORIGIN, 'minecraft:slime_block')
    setblock(command, MOVER, MOVER_STATE)
    setblock(command, CHEST, CHEST_STATE)
    command(f'item replace block {xyz(CHEST)} container.5 with minecraft:wheat 3')
    command(f'item replace block {xyz(CHEST)} container.26 '
            'with minecraft:stick[minecraft:custom_data={psi_gantry_probe:153}] 2')
    setblock(command, STATION, f'{BLOCK}[facing=north]')
    setblock(command, HOPPER, 'minecraft:hopper[facing=down]')
    setblock(command, OUTPUT, CHEST_STATE)


def power(command):
    setblock(command, MOTOR, 'create:creative_motor[facing=east]{ScrollValue:-32}')


def snapshot(station, hopper, output, landed):
    return dict(timer=number({'nbt': station}, 'Timer', 0),
                distance=number({'nbt': station}, 'Distance', 0),
                hopper=items(hopper, 'Items'), output=items(output, 'Items'),
                marked='psi_gantry_probe:153' in output.replace(' ', ''), landed=landed)


def release(trace):
    start = next(i for i in range(COLD_AT, len(trace)) if trace[i]['timer'] == 4)
    end = next(i for i in range(start, len(trace)) if trace[i]['landed'])
    return trace[start:end + 1]


def verify(trace, landed, dock_x, cold):
    if cold:
        assert dock_x == STATION[0], dock_x
        saved = trace[COLD_AT - 1]
        assert 4 < saved['timer'] <= 64 and not saved['landed'], saved
        received = sum(saved['output'].values()) + sum(saved['hopper'].values())
        assert 0 < received < sum(RECEIVED.values()), saved
        release(trace)
    else:
        transfers = [i for i, row in enumerate(trace) if row['timer'] == 64]
        assert len(transfers) == 5 and all(b - a == 8 for a, b in zip(transfers, transfers[1:])), transfers
    assert trace[-1]['landed'] and trace[-1]['timer'] == 0, trace[-1]
    assert trace[-1]['output'] == RECEIVED and trace[-1]['marked'] and not trace[-1]['hopper'], trace[-1]
    assert landed == [True, {}], landed


def java_observe(host, count):
    rows = host.call('observe_ticks', {'ticks': count, 'positions': POINTS})['samples']
    return [snapshot(*(row.get('nbt', '') for row in sample['blocks'][:3]),
                     sample['blocks'][3]['id'] == CARRIAGE) for sample in rows]


def original(work, cold):
    host = Original()
    initial = host.call('state', {})
    assert initial['ready'] and initial['data_version'] == 3955, initial
    host.call('tick', {'frozen': True})
    dock_x = None
    try:
        host.command('tp @s ' + xyz(CAMERA))
        host.command(f'forceload add {COLUMN}')
        step(host, 20, START)
        prepare(host.command)
        step(host, 8, START)
        power(host.command)
        if cold:
            trace = java_observe(host, COLD_AT)
            [entity] = [row for row in host.call('entities', {'center': STATION, 'radius': 6})['entities']
                        if row['type'] == 'create:gantry_contraption']
            dock_x = entity['position'][0]
            java_restart(host)
            trace.extend(java_observe(host, TRACE_TICKS - COLD_AT))
        else:
            trace = java_observe(host, TRACE_TICKS)
        mover = host.call('block', {'pos': LANDED_MOVER})
        chest = host.call('block', {'pos': LANDED_CHEST})
        landed = [mover['id'] == BLOCK and mover['properties']['facing'] == 'south',
                  items(chest.get('nbt', ''), 'Items') if chest['id'] != AIR else None]
        return trace, landed, dock_x
    finally:
        setblock(host.command, MOTOR, AIR)
        step(host, 5, START)
        host.command(f'fill {ROOM} {AIR}')
        host.command(f'forceload remove {COLUMN}')
        host.call('camera', {key: initial[key] for key in ('position', 'yaw', 'pitch')})
        host.call('tick', {'frozen': initial['server']['frozen']})
        (work / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')


def native_observe(batch, count):
    for _ in range(count):
        batch.tick()
        for pos in POINTS[:3]:
            batch.data(pos)
        batch.expect(END, CARRIAGE_STATE)


def native(args):
    session = NativeCheckSession(args.game, args.resources, args.ctl, args.create_jar,
                                 name='gantry-psi-native', graphics=False, world='CreateGantryPSI')
    try:
        batch = Batch()
        batch.load(CAMERA)
        prepare(batch.command)
        batch.tick(8)
        power(batch.command)
        rows = []
        remaining = TRACE_TICKS
        dock_x = None
        if args.cold:
            native_observe(batch, COLD_AT)
            rows = batch.run(session, 'gantry-psi-before-restart')
            poses = read_saved_chunk_tag(session.scratch, START, POSES, session.world)['nbt']
            [pose] = poses['value']['Entries']['value']
            bits = pose['value']['Stroke']['value']['Offset']['value']
            dock_x = START[0] + struct.unpack('>f', struct.pack('>I', bits))[0]
            docks = read_saved_chunk_tag(session.scratch, START, DOCKS, session.world)['nbt']
            assert [entry['value'] for entry in docks['value']['Entries']['value']] == [list(START + STATION)]
            batch = Batch()
            batch.load(CAMERA)
            remaining -= COLD_AT
        native_observe(batch, remaining)
        batch.expect(LANDED_MOVER, MOVER_STATE)
        batch.data(LANDED_CHEST)
        rows.extend(batch.run(session, 'gantry-psi'))
        assert read_saved_chunk_tag(session.scratch, START, DOCKS, session.world)['nbt'] is None
        trace = [snapshot(*rows[i:i + 3], 'bearing_check' in rows[i + 3])
                 for i in range(0, len(rows) - 2, len(POINTS))]
        landed = ['bearing_check' in rows[-2], items(rows[-1], 'Items') if 'Items' in rows[-1] else None]
        return session.scratch, trace, landed, dock_x
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
        work = Path(tempfile.mkdtemp(prefix='gantry-psi-java-', dir=ROOT / '.local'))
        trace, landed, dock_x = original(work, args.cold)
    else:
        work, trace, landed, dock_x = native(args)
    result = work / 'result.json'
    report = dict(create=PINS['create_revision'], cold=args.cold, trace=trace, landed=landed, dock_x=dock_x)
    result.write_text(json.dumps(report, indent=2) + '\n')
    print(result, flush=True)
    verify(trace, landed, dock_x, args.cold)
    if args.reference:
        expected = json.loads(args.reference.read_text())
        assert expected['create'] == PINS['create_revision'] and args.cold == expected['cold']
        comparable = COLD_AT if args.cold else TRACE_TICKS
        differences = compare(trace[:comparable], expected['trace'][:comparable])
        if args.cold:
            differences.extend(compare(release(trace), release(expected['trace'])))
        report['differences'] = differences
        result.write_text(json.dumps(report, indent=2) + '\n')
        assert not differences and landed == expected['landed'] and dock_x == expected['dock_x'], differences[:4]


if __name__ == '__main__':
    main()
