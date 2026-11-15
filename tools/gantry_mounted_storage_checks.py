#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Compare a Gantry carrying separate Chest and Barrel banks across restart."""

import argparse
import json
from pathlib import Path
import re
import shutil
import struct
import tempfile

from bearing_barrel_checks import check_blocks
from bearing_mounted_pair_checks import BANK_ITEMS, STORAGE, verify_inventory
from bearing_native_checks import Batch
from bearing_repeat_checks import POSES, SCENE
from chain_drive_checks import Original, xyz
from common import PINS, ROOT
from funnel_checks import step, text
from gantry_portable_storage_checks import AIR, CAMERA, CARRIAGE_STATE, COLUMN, END, MOTOR, ROOM, START
from native_check_session import NativeCheckSession
from pulley_portable_storage_checks import CHEST_STATE, java_restart, setblock
from saved_block_checks import read_saved_chunk_tag


LOCALS = ((0, 1, -1), (0, 2, 0))
STATES = (CHEST_STATE, 'minecraft:barrel[facing=east,open=false]')
TICKS = 27


def positions(origin):
    return tuple(tuple(a + b for a, b in zip(origin, local)) for local in LOCALS)


def setup(command):
    command(f'fill {ROOM} {AIR}')
    for x in range(START[0], END[0] + 1):
        setblock(command, (x, START[1] - 1, START[2]), 'create:gantry_shaft[facing=east]')
    setblock(command, START, CARRIAGE_STATE)
    setblock(command, (START[0], START[1] + 1, START[2]), 'minecraft:slime_block')
    for pos, state, items in zip(positions(START), STATES, BANK_ITEMS):
        setblock(command, pos, state)
        for slot, item, count, component in items:
            command(f'item replace block {xyz(pos)} container.{slot} with {item}{component} {count}')


def power(command):
    setblock(command, MOTOR, 'create:creative_motor[facing=east]{ScrollValue:-32}')


def original(work):
    host = Original()
    initial = host.call('state', {})
    assert initial['ready'] and initial['data_version'] == 3955, initial
    host.call('tick', {'frozen': True})
    try:
        host.command('tp @s ' + xyz(CAMERA))
        host.command(f'forceload add {COLUMN}')
        step(host, 20, START)
        setup(host.command)
        step(host, 8, START)
        power(host.command)
        captured = step(host, TICKS, START, *positions(START))
        assert all(row['id'] == AIR for row in captured), captured
        [carriage] = [entity for entity in host.call('entities', {'center': START, 'radius': 6})['entities']
                      if entity['type'] == 'create:gantry_contraption']
        offset = carriage['position'][0] - START[0]
        assert 0 < offset < END[0] - START[0], carriage
        x, y, z = START
        selector = f'@e[type=create:gantry_contraption,x={x},y={y},z={z},distance=..6,limit=1]'
        mounted = text(host, f'data get entity {selector} Contraption.items')
        local = re.findall(r'pos:\s*\[I;\s*(-?\d+),\s*(-?\d+),\s*(-?\d+)\]', mounted)
        order = [list(map(int, point)) for point in local]
        assert sorted(order) == sorted(map(list, LOCALS)), mounted
        assert mounted.count('size: 27') == 2 and 'first_bank: 31' in mounted, mounted
        java_restart(host)
        base, *banks = step(host, 85, END, *positions(END))
        assert base['id'] == 'create:gantry_carriage', base
        for row, state in zip(banks, STATES):
            block, props = state.split('[')
            expected = dict(pair.split('=') for pair in props[:-1].split(','))
            assert row['id'] == block, row
            assert {key: value.lower() for key, value in row['properties'].items()} == expected, row
        items = [verify_inventory(row['nbt'], i) for i, row in enumerate(banks)]
        return dict(offset=offset, order=order, items=items)
    finally:
        setblock(host.command, MOTOR, AIR)
        step(host, 5, START)
        host.command(f'fill {ROOM} {AIR}')
        host.command(f'forceload remove {COLUMN}')
        host.call('camera', {key: initial[key] for key in ('position', 'yaw', 'pitch')})
        host.call('tick', {'frozen': initial['server']['frozen']})
        (work / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')


def native(session, expected):
    def saved(keys):
        return read_saved_chunk_tag(session.scratch, START, keys, session.world)['nbt']

    batch = Batch()
    batch.load(CAMERA)
    setup(batch.command)
    batch.tick(8)
    power(batch.command)
    batch.tick(TICKS)
    for pos in (START, *positions(START)):
        batch.expect(pos, AIR)
    check_blocks(batch.run(session, 'gantry-mixed-bank-capture'))
    [pose] = saved(POSES)['value']['Entries']['value']
    bits = pose['value']['Stroke']['value']['Offset']['value']
    offset = struct.unpack('>f', struct.pack('>I', bits))[0]
    assert offset == expected['offset'], (offset, expected)
    storage = saved(STORAGE)['value']
    assert storage['Version']['value'] == 2, storage
    banks = [entry['value'] for entry in storage['Chests']['value']]
    assert [entry['Pos']['value'] for entry in banks] == expected['order'], banks
    assert all(entry['Controller']['value'] == list(START) for entry in banks), banks
    for entry in banks:
        index = LOCALS.index(tuple(entry['Pos']['value']))
        stacks = [stack['value'] for stack in entry['Items']['value']]
        assert [[stack[key]['value'] for key in ('Slot', 'id', 'count')]
                for stack in stacks] == expected['items'][index], stacks

    batch = Batch()
    batch.load(CAMERA)
    batch.tick(85)
    batch.expect(END, CARRIAGE_STATE)
    for pos, state in zip(positions(END), STATES):
        batch.expect(pos, state)
        batch.data(pos)
    rows = batch.run(session, 'gantry-mixed-bank-cold-landing')
    check_blocks((rows[0], rows[1], rows[3]))
    items = [verify_inventory(row, i) for i, row in enumerate(rows[2::2])]
    assert items == expected['items'] and saved(STORAGE) is None and saved(SCENE) is None
    return dict(offset=offset, order=expected['order'], items=items)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--java', action='store_true')
    for name in ('game', 'resources', 'ctl', 'create-jar', 'reference'):
        parser.add_argument('--' + name, type=Path)
    args = parser.parse_args()
    if args.java:
        work = Path(tempfile.mkdtemp(prefix='gantry-mixed-storage-java-', dir=ROOT / '.local'))
        print(work, flush=True)
        report = original(work)
    else:
        session = NativeCheckSession(args.game, args.resources, args.ctl, args.create_jar,
                                     name='gantry-mixed-storage-native', graphics=False, world='CreateGantryPair')
        work = session.scratch
        print(work, flush=True)
        expected = json.loads(args.reference.read_text())
        assert expected['create'] == PINS['create_revision']
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
