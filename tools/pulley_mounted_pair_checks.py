#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Compare two Rope Pulley cargo banks, blocked landing and terrain drops."""

import argparse
import json
from pathlib import Path
import re
import shutil
import tempfile

from actor_native_checks import matched
from bearing_barrel_checks import check_blocks
from bearing_mounted_pair_checks import BANK_ITEMS, STORAGE, verify_inventory
from bearing_native_checks import Batch
from bearing_repeat_checks import SCENE
from chain_drive_checks import Original, xyz
from common import PINS, ROOT
from funnel_checks import step, text
from native_check_session import NativeCheckSession
from pulley_capacity_checks import AIR, pose
from pulley_portable_storage_checks import CHEST_STATE, java_restart, setblock
from saved_block_checks import read_saved_chunk_tag


PULLEY = (2934, 164, 1819)
MOTOR = (2935, 164, 1819)
CAMERA = (2939, 174, 1823)
COLUMN = '2928 1808'
ROOM = '2930 154 1815 2940 167 1824'
LOCALS = ((-1, 0, 0), (0, 0, 1))
STATES = (CHEST_STATE, 'minecraft:barrel[facing=east,open=false]')
TICKS = 28
STOP_OFFSET = 3


def positions(offset):
    x, y, z = PULLEY
    return tuple((x + dx, y - 1 - offset + dy, z + dz) for dx, dy, dz in LOCALS)


def drops(item=None):
    tag = f',nbt={{Item:{{id:"{item}"}}}}' if item else ''
    x, y, z = positions(STOP_OFFSET)[0]
    return f'@e[type=minecraft:item,x={x},y={y},z={z},distance=..8{tag}]'


def setup(command):
    command(f'kill {drops()}')
    command(f'fill {ROOM} {AIR}')
    setblock(command, PULLEY, 'create:rope_pulley[axis=x]{Offset:5f}')
    command('fill 2934 160 1819 2934 163 1819 create:rope[waterlogged=false]')
    setblock(command, (2934, 159, 1819), 'create:pulley_magnet[waterlogged=false]')
    setblock(command, (2934, 158, 1819), 'minecraft:slime_block')
    for pos, state, items in zip(positions(5), STATES, BANK_ITEMS, strict=True):
        setblock(command, pos, state)
        for slot, item, count, component in items:
            command(f'item replace block {xyz(pos)} container.{slot} with {item}{component} {count}')


def power(command):
    setblock(command, MOTOR, 'create:creative_motor[facing=west]{ScrollValue:32}')


def verify_blocks(rows, obstruction=None):
    result = []
    for i, (row, state) in enumerate(zip(rows, STATES, strict=True)):
        if i == 0 and obstruction == 'bedrock':
            assert row['id'] == 'minecraft:bedrock', row
            result.append(None)
            continue
        block, props = state.split('[')
        expected = dict(pair.split('=') for pair in props[:-1].split(','))
        assert row['id'] == block, row
        assert {key: value.lower() for key, value in row['properties'].items()} == expected, row
        result.append(verify_inventory(row['nbt'], i))
    return result


def original(work):
    host = Original()
    initial = host.call('state', {})
    assert initial['ready'] and initial['data_version'] == 3955, initial
    host.call('tick', {'frozen': True})
    rule = text(host, 'gamerule doTileDrops').lower()
    assert 'true' in rule or 'false' in rule, rule
    try:
        host.command('gamerule doTileDrops true')
        host.command('tp @s ' + xyz(CAMERA))
        host.command(f'forceload add {COLUMN}')
        step(host, 20, PULLEY)
        cases = {}
        for case in ('cold', 'stone', 'bedrock'):
            setup(host.command)
            step(host, 8, PULLEY)
            power(host.command)
            driver, *empty = step(host, TICKS, PULLEY, *positions(5))
            running, offset = pose(driver['nbt'])
            assert running and 3 < offset < 3.5, driver
            assert all(row['id'] == AIR for row in empty), empty
            if case == 'cold':
                java_restart(host)
                driver, *banks = step(host, 85, PULLEY, *positions(0))
                assert pose(driver['nbt']) == (False, 0), driver
                cases[case] = dict(offset=offset, items=verify_blocks(banks))
                continue
            target = positions(STOP_OFFSET)[0]
            setblock(host.command, target, f'minecraft:{case}')
            observed = host.call('observe_ticks', {
                'ticks': 5, 'positions': (PULLEY, *positions(STOP_OFFSET)),
                'commands': ['tick unfreeze', f'setblock {xyz(MOTOR)} {AIR}'],
            })['samples'][-1]['blocks']
            assert pose(observed[0]['nbt']) == (False, STOP_OFFSET), observed
            item = 'minecraft:cobblestone' if case == 'stone' else 'minecraft:chest'
            dropped = f'{drops(item)[:-1]},limit=1]'
            receipt = text(host, f'data get entity {dropped} Item.count')
            assert re.search(r':\s*1\s*$', receipt), receipt
            assert text(host, f'execute as {drops(item)} run say paired_drop').count('paired_drop') == 1
            if case == 'bedrock':
                for missing in ('minecraft:diamond', 'minecraft:stick'):
                    assert 'loose_bank' not in text(host, f'execute if entity {drops(missing)} run say loose_bank')
            cases[case] = dict(offset=offset, items=verify_blocks(observed[1:], case), drop=item)
        return cases
    finally:
        setblock(host.command, MOTOR, AIR)
        step(host, 5, PULLEY)
        host.command(f'fill {ROOM} {AIR}')
        host.command(f'kill {drops()}')
        host.command(f'forceload remove {COLUMN}')
        host.command(f'gamerule doTileDrops {"true" if "true" in rule else "false"}')
        host.call('camera', {key: initial[key] for key in ('position', 'yaw', 'pitch')})
        host.call('tick', {'frozen': initial['server']['frozen']})
        (work / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')


def native(session, expected):
    def saved(keys):
        return read_saved_chunk_tag(session.scratch, PULLEY, keys, session.world)['nbt']

    def capture(case):
        batch = Batch()
        batch.load(CAMERA)
        setup(batch.command)
        batch.tick(8)
        power(batch.command)
        batch.tick(TICKS)
        batch.data(PULLEY)
        for pos in positions(5):
            batch.expect(pos, AIR)
        driver, *empty = batch.run(session, f'{case}-moving-pair')
        assert pose(driver) == (True, expected[case]['offset']), driver
        check_blocks(empty)
        cargo = saved(STORAGE)
        assert cargo['value']['Version']['value'] == 2
        assert [entry['value']['Pos']['value'] for entry in cargo['value']['Chests']['value']] == list(map(list, LOCALS))
        return cargo

    def landing(case, offset, drop=None, obstruction=None, clear=False):
        batch = Batch()
        batch.load(CAMERA)
        if obstruction:
            batch.put(positions(offset)[0], obstruction)
            batch.put(MOTOR, AIR)
        if clear:
            batch.put(positions(offset)[0], AIR)
        batch.tick(85 if case == 'cold' else 5)
        batch.data(PULLEY)
        for pos, state in zip(positions(offset), STATES, strict=True):
            batch.expect(pos, state)
            batch.data(pos)
        if drop:
            query = f'{drops(drop)[:-1]},limit=1]'
            batch.command(f'data get entity {query} Item.count', True)
            batch.command(f'execute as {drops()} run say paired_drop', True)
        else:
            batch.command(f'execute if entity {drops()} run say loose_bank', True)
        rows = batch.run(session, f'{case}-landed-pair')
        assert pose(rows[0]) == (False, offset), rows[0]
        check_blocks((rows[1], rows[3]))
        if drop:
            assert re.search(r':\s*1\s*$', rows[-2]), rows[-2]
            assert rows[-1].count('paired_drop') == 1, rows[-1]
        else:
            assert 'loose_bank' not in rows[-1], rows[-1]
        assert saved(STORAGE) is None and saved(SCENE) is None
        return [verify_inventory(rows[i], n) for n, i in enumerate((2, 4))]

    capture('cold')
    cold = landing('cold', 0)
    assert cold == expected['cold']['items']
    cases = dict(cold=dict(items=cold))
    capture('stone')
    stone_drop = expected['stone']['drop']
    stone = landing('stone', STOP_OFFSET, stone_drop, obstruction='minecraft:stone')
    assert stone == expected['stone']['items']
    cases['stone'] = dict(items=stone, drop=stone_drop)

    cargo = capture('bedrock')
    batch = Batch()
    batch.load(CAMERA)
    batch.put(positions(STOP_OFFSET)[0], 'minecraft:bedrock')
    batch.put(positions(STOP_OFFSET)[1], 'minecraft:stone')
    batch.put(MOTOR, AIR)
    batch.tick(5)
    batch.expect(positions(STOP_OFFSET)[0], 'minecraft:bedrock')
    batch.expect(positions(STOP_OFFSET)[1], 'minecraft:stone')
    batch.command(f'execute if entity {drops()} run say loose_bank', True)
    rows = batch.run(session, 'bedrock-obstructed-pair')
    check_blocks(rows[:2])
    assert 'loose_bank' not in rows[2]
    assert saved(STORAGE) == cargo and saved(SCENE) is not None
    # Java discards the bank at that cell. Horizon replays the landing
    # with both inventories intact after the obstruction is removed.
    bedrock = landing('bedrock', STOP_OFFSET, stone_drop, clear=True)
    assert bedrock == expected['cold']['items']
    cases['bedrock'] = dict(items=bedrock, drop_after_clear=stone_drop)
    return cases


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--java', action='store_true')
    for name in ('game', 'resources', 'ctl', 'create-jar', 'reference'):
        parser.add_argument('--' + name, type=Path)
    args = parser.parse_args()
    if args.java:
        work = Path(tempfile.mkdtemp(prefix='pulley-mixed-pair-java-', dir=ROOT / '.local'))
        print(work, flush=True)
        cases = original(work)
    else:
        reference = json.loads(args.reference.read_text())
        assert reference['create'] == PINS['create_revision']
        session = NativeCheckSession(args.game, args.resources, args.ctl, args.create_jar,
                                     name='pulley-mixed-pair-native', graphics=False, world='CreatePulleyPair')
        work = session.scratch
        print(work, flush=True)
        try:
            cases = native(session, reference['cases'])
        finally:
            session.control_temp.cleanup()
            for folder in (session.resources, work / '.horizon-cache', work / 'horizon-mods'):
                shutil.rmtree(folder, ignore_errors=True)
    result = work / 'result.json'
    result.write_text(json.dumps(dict(create=PINS['create_revision'], cases=cases), indent=2) + '\n')
    print(result)


if __name__ == '__main__':
    main()
