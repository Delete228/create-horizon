#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Compare two-bank Piston landing through stone and custody at bedrock."""

import argparse
import json
from pathlib import Path
import re
import shutil
import tempfile

from bearing_barrel_checks import check_blocks
from bearing_mounted_pair_checks import STORAGE, verify_inventory
from bearing_native_checks import Batch
from bearing_repeat_checks import SCENE
from chain_drive_checks import Original, xyz
from common import PINS, ROOT
from funnel_checks import step, text
from native_check_session import NativeCheckSession
from piston_mounted_pair_checks import (
    CAMERA, COLD_AT, COLUMN, MOTOR, PISTON, ROOM, STATES, matches_java,
    positions, power, setup,
)
from pulley_capacity_checks import AIR, pose
from pulley_portable_storage_checks import setblock
from saved_block_checks import read_saved_chunk_tag


STOP = 1


def drops(item=None):
    x, y, z = positions(STOP)[0]
    tag = f',nbt={{Item:{{id:"{item}"}}}}' if item else ''
    return f'@e[type=minecraft:item,x={x},y={y},z={z},distance=..8{tag}]'


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
        step(host, 20, PISTON)
        cases = {}
        for case in ('stone', 'bedrock'):
            host.command(f'kill {drops()}')
            setup(host.command)
            step(host, 8, PISTON)
            power(host.command)
            moving = step(host, COLD_AT, PISTON)[0]
            assert pose(moving['nbt']) == (True, 1.625), moving
            chest_pos, barrel_pos = positions(STOP)
            setblock(host.command, chest_pos, f'minecraft:{case}')
            driver, chest, barrel = host.call('observe_ticks', {
                'ticks': 5, 'positions': (PISTON, chest_pos, barrel_pos),
                'commands': ['tick unfreeze', f'setblock {xyz(MOTOR)} {AIR}'],
            })['samples'][-1]['blocks']
            assert pose(driver['nbt']) == (False, STOP), driver
            assert matches_java(barrel, STATES[1]), barrel
            barrel_items = verify_inventory(barrel['nbt'], 1)
            if case == 'stone':
                assert matches_java(chest, STATES[0]), chest
                chest_items = verify_inventory(chest['nbt'], 0)
                item = 'minecraft:cobblestone'
            else:
                assert chest['id'] == 'minecraft:bedrock', chest
                chest_items = None
                item = 'minecraft:chest'
                for missing in ('minecraft:diamond', 'minecraft:stick'):
                    assert 'bank_lost' not in text(host, f'execute if entity {drops(missing)} run say bank_lost')
            selector = f'{drops(item)[:-1]},limit=1]'
            receipt = text(host, f'data get entity {selector} Item.count')
            assert re.search(r':\s*1\s*$', receipt), receipt
            cases[case] = dict(items=[chest_items, barrel_items], drop=item)
        return cases
    finally:
        setblock(host.command, MOTOR, AIR)
        step(host, 5, PISTON)
        host.command(f'fill {ROOM} {AIR}')
        host.command(f'kill {drops()}')
        host.command(f'forceload remove {COLUMN}')
        host.command(f'gamerule doTileDrops {"true" if "true" in rule else "false"}')
        host.call('camera', {key: initial[key] for key in ('position', 'yaw', 'pitch')})
        host.call('tick', {'frozen': initial['server']['frozen']})
        (work / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')


def native(session, expected, case):
    def saved(keys):
        return read_saved_chunk_tag(session.scratch, PISTON, keys, session.world)['nbt']

    batch = Batch()
    batch.load(CAMERA)
    batch.command(f'kill {drops()}')
    setup(batch.command)
    batch.tick(8)
    power(batch.command)
    batch.tick(COLD_AT)
    batch.data(PISTON)
    driver, = batch.run(session, f'{case}-piston-moving')
    assert pose(driver) == (True, 1.625), driver
    cargo = saved(STORAGE)
    assert cargo['value']['Version']['value'] == 2

    chest_pos, barrel_pos = positions(STOP)
    batch = Batch()
    batch.load(CAMERA)
    batch.put(chest_pos, f'minecraft:{case}')
    batch.put(MOTOR, AIR)
    if case == 'bedrock':
        batch.put(barrel_pos, 'minecraft:stone')
        batch.tick(5)
        batch.expect(chest_pos, 'minecraft:bedrock')
        batch.expect(barrel_pos, 'minecraft:stone')
        batch.command(f'execute if entity {drops()} run say loose_bank', True)
        rows = batch.run(session, 'piston-pair-blocked')
        check_blocks(rows[:2])
        assert 'loose_bank' not in rows[2]
        assert saved(STORAGE) == cargo and saved(SCENE) is not None
        batch = Batch()
        batch.load(CAMERA)
        batch.put(chest_pos, AIR)

    batch.tick(5)
    batch.data(PISTON)
    for pos, state in zip((chest_pos, barrel_pos), STATES, strict=True):
        batch.expect(pos, state)
        batch.data(pos)
    drop = expected['stone']['drop']
    selector = f'{drops(drop)[:-1]},limit=1]'
    batch.command(f'data get entity {selector} Item.count', True)
    batch.command(f'execute as {drops()} run say paired_drop', True)
    rows = batch.run(session, f'{case}-piston-landed')
    assert pose(rows[0]) == (False, STOP), rows[0]
    check_blocks((rows[1], rows[3]))
    items = [verify_inventory(rows[i], n) for n, i in enumerate((2, 4))]
    assert items == expected['stone']['items'] and saved(STORAGE) is None and saved(SCENE) is None
    assert re.search(r':\s*1\s*$', rows[-2]), rows[-2]
    assert rows[-1].count('paired_drop') == 1, rows[-1]
    if case == 'bedrock':
        return dict(items=items, drop_after_clear=drop)
    return dict(items=items, drop=drop)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--java', action='store_true')
    parser.add_argument('--case', choices=('stone', 'bedrock'), action='append')
    for name in ('game', 'resources', 'ctl', 'create-jar', 'reference'):
        parser.add_argument('--' + name, type=Path)
    args = parser.parse_args()
    if args.java:
        work = Path(tempfile.mkdtemp(prefix='piston-pair-obstruction-java-', dir=ROOT / '.local'))
        print(work, flush=True)
        cases = original(work)
    else:
        expected = json.loads(args.reference.read_text())
        assert expected['create'] == PINS['create_revision']
        session = NativeCheckSession(args.game, args.resources, args.ctl, args.create_jar,
                                     name='piston-pair-obstruction-native', graphics=False,
                                     world='CreatePistonObstruction')
        work = session.scratch
        print(work, flush=True)
        try:
            cases = {case: native(session, expected['cases'], case) for case in args.case or ('stone', 'bedrock')}
        finally:
            session.control_temp.cleanup()
            for folder in (session.resources, work / '.horizon-cache', work / 'horizon-mods'):
                shutil.rmtree(folder, ignore_errors=True)
    result = work / 'result.json'
    result.write_text(json.dumps(dict(create=PINS['create_revision'], cases=cases), indent=2) + '\n')
    print(result)


if __name__ == '__main__':
    main()
