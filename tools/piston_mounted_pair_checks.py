#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Compare two mounted banks on an extending vertical Mechanical Piston."""

import argparse
import json
from pathlib import Path
import re
import shutil
import tempfile

from bearing_mounted_pair_checks import BANK_ITEMS, STORAGE, verify_inventory
from bearing_native_checks import Batch
from bearing_repeat_checks import SCENE
from chain_drive_checks import Original, xyz
from common import PINS, ROOT
from funnel_checks import step, text
from native_check_session import NativeCheckSession
from piston_portable_storage_checks import CAMERA, COLUMN, MOTOR, ORIGIN, PISTON, ROOM, power
from pulley_capacity_checks import AIR, pose
from pulley_portable_storage_checks import CHEST_STATE, compare, java_restart, setblock
from saved_block_checks import read_saved_chunk_tag


LOCALS = ((-1, 0, 0), (0, 0, 1))
STATES = (CHEST_STATE, 'minecraft:barrel[facing=east,open=false]')
COLD_AT = 28
TRACE_TICKS = 80


def positions(stroke):
    x, y, z = ORIGIN
    return tuple((x + dx, y + dy + stroke, z + dz) for dx, dy, dz in LOCALS)


def setup(command):
    command(f'fill {ROOM} {AIR}')
    setblock(command, PISTON, 'create:mechanical_piston[facing=up,axis_along_first=true]')
    command('fill 2885 160 1818 2885 163 1818 create:piston_extension_pole[facing=up]')
    setblock(command, ORIGIN, 'minecraft:slime_block')
    for pos, state, items in zip(positions(0), STATES, BANK_ITEMS, strict=True):
        setblock(command, pos, state)
        for slot, item, count, component in items:
            command(f'item replace block {xyz(pos)} container.{slot} with {item}{component} {count}')


def snapshot(driver, matches):
    running, offset = pose(driver)
    return dict(running=running, offset=offset, sources=matches[:2], targets=matches[2:])


def matches_java(row, state):
    block, props = state.split('[')
    expected = dict(pair.split('=') for pair in props[:-1].split(','))
    return row['id'] == block and {
        key: value.lower() for key, value in row['properties'].items()
    } == expected


def java_observe(host, count):
    points = (PISTON, *positions(0), *positions(4))
    receipt = host.call('observe_ticks', {'ticks': count, 'positions': points})
    trace = []
    for sample in receipt['samples']:
        driver, *banks = sample['blocks']
        matches = [matches_java(row, state) for row, state in zip(banks, STATES * 2, strict=True)]
        trace.append(snapshot(driver['nbt'], matches))
    return trace


def java_inventory(host):
    banks = [host.call('block', {'pos': pos}) for pos in positions(4)]
    assert all(matches_java(row, state) for row, state in zip(banks, STATES, strict=True)), banks
    return [verify_inventory(row['nbt'], i) for i, row in enumerate(banks)]


def verify(trace):
    assert trace[0]['sources'] == [True, True], trace[0]
    assert trace[COLD_AT - 1]['running'] and 0 < trace[COLD_AT - 1]['offset'] < 4, trace[COLD_AT - 1]
    assert trace[COLD_AT - 1]['sources'] == trace[COLD_AT - 1]['targets'] == [False, False]
    assert trace[-1] == dict(running=False, offset=4, sources=[False, False], targets=[True, True]), trace[-1]


def original(work):
    host = Original()
    initial = host.call('state', {})
    assert initial['ready'] and initial['data_version'] == 3955, initial
    host.call('tick', {'frozen': True})
    try:
        host.command('tp @s ' + xyz(CAMERA))
        host.command(f'forceload add {COLUMN}')
        step(host, 20, PISTON)
        setup(host.command)
        step(host, 8, PISTON)
        power(host.command)
        trace = java_observe(host, TRACE_TICKS)
        verify(trace)
        items = java_inventory(host)

        setup(host.command)
        step(host, 8, PISTON)
        power(host.command)
        assert java_observe(host, COLD_AT) == trace[:COLD_AT]
        x, y, z = ORIGIN
        selector = f'@e[type=create:stationary_contraption,x={x},y={y},z={z},distance=..6,limit=1]'
        mounted = text(host, f'data get entity {selector} Contraption.items')
        order = [list(map(int, point)) for point in re.findall(
            r'pos:\s*\[I;\s*(-?\d+),\s*(-?\d+),\s*(-?\d+)\]', mounted)]
        assert sorted(order) == sorted(map(list, LOCALS)), mounted
        assert mounted.count('size: 27') == 2 and 'first_bank: 31' in mounted, mounted
        java_restart(host)
        assert java_observe(host, TRACE_TICKS)[-1] == trace[-1]
        assert java_inventory(host) == items
        return dict(trace=trace, order=order, items=items)
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
        batch.data(PISTON)
        for pos, state in zip((*positions(0), *positions(4)), STATES * 2, strict=True):
            batch.expect(pos, state)


def native_trace(rows):
    return [snapshot(rows[i], ['bearing_check' in row for row in rows[i + 1:i + 5]])
            for i in range(0, len(rows), 5)]


def native(session, expected):
    def saved(keys):
        return read_saved_chunk_tag(session.scratch, PISTON, keys, session.world)['nbt']

    def active():
        batch = Batch()
        batch.load(CAMERA)
        setup(batch.command)
        batch.tick(8)
        power(batch.command)
        return batch

    def observe_inventory(batch):
        for pos in positions(4):
            batch.data(pos)

    batch = active()
    native_observe(batch, TRACE_TICKS)
    observe_inventory(batch)
    rows = batch.run(session, 'piston-pair-warm')
    trace = native_trace(rows[:-2])
    verify(trace)
    differences = compare(trace, expected['trace'])
    assert not differences, differences[:5]
    items = [verify_inventory(row, i) for i, row in enumerate(rows[-2:])]
    assert items == expected['items'] and saved(STORAGE) is None and saved(SCENE) is None

    batch = active()
    native_observe(batch, COLD_AT)
    captured = native_trace(batch.run(session, 'piston-pair-before-restart'))
    assert captured == expected['trace'][:COLD_AT], compare(captured, expected['trace'][:COLD_AT])[:5]
    storage = saved(STORAGE)['value']
    assert storage['Version']['value'] == 2, storage
    banks = [entry['value'] for entry in storage['Chests']['value']]
    assert [entry['Pos']['value'] for entry in banks] == expected['order'], banks
    assert all(entry['Controller']['value'] == list(PISTON) for entry in banks), banks
    for entry in banks:
        index = LOCALS.index(tuple(entry['Pos']['value']))
        slots = [stack['value'] for stack in entry['Items']['value']]
        assert [[stack[key]['value'] for key in ('Slot', 'id', 'count')]
                for stack in slots] == expected['items'][index], slots

    batch = Batch()
    batch.load(CAMERA)
    batch.tick(TRACE_TICKS - 1)
    native_observe(batch, 1)
    observe_inventory(batch)
    rows = batch.run(session, 'piston-pair-cold-landing')
    assert native_trace(rows[:-2]) == [expected['trace'][-1]], rows
    assert [verify_inventory(row, i) for i, row in enumerate(rows[-2:])] == items
    assert saved(STORAGE) is None and saved(SCENE) is None
    return dict(trace=trace, order=expected['order'], items=items)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--java', action='store_true')
    for name in ('game', 'resources', 'ctl', 'create-jar', 'reference'):
        parser.add_argument('--' + name, type=Path)
    args = parser.parse_args()
    if args.java:
        work = Path(tempfile.mkdtemp(prefix='piston-mixed-pair-java-', dir=ROOT / '.local'))
        print(work, flush=True)
        report = original(work)
    else:
        expected = json.loads(args.reference.read_text())
        assert expected['create'] == PINS['create_revision']
        session = NativeCheckSession(args.game, args.resources, args.ctl, args.create_jar,
                                     name='piston-mixed-pair-native', graphics=False, world='CreatePistonPair')
        work = session.scratch
        print(work, flush=True)
        try:
            report = native(session, expected)
        finally:
            session.control_temp.cleanup()
            for folder in (session.resources, work / '.horizon-cache', work / 'horizon-mods'):
                shutil.rmtree(folder, ignore_errors=True)
    result = work / 'result.json'
    result.write_text(json.dumps(dict(create=PINS['create_revision'], **report), indent=2) + '\n')
    print(result)


if __name__ == '__main__':
    main()
