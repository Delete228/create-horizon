#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Compare complete ordinary Tanks carried by a vertical Rope Pulley."""

import argparse
import json
from pathlib import Path
import re
import shutil
import tempfile

from bearing_barrel_checks import check_blocks
from bearing_native_checks import Batch
from bearing_repeat_checks import SCENE
from bearing_tank_checks import STORAGE, snapshot
from burner_heat_java_checks import field
from chain_drive_checks import Original, xyz
from common import PINS, ROOT
from fluid_tank_checks import TANK, expected_tank, offset, tank_parts
from funnel_checks import step, text
from native_check_session import NativeCheckSession
from pulley_capacity_checks import AIR, pose
from saved_block_checks import read_saved_block, read_saved_chunk_tag


PULLEY = (2853, 164, 1785)
MOTOR = offset(PULLEY, dx=1)
SOURCE = offset(PULLEY, dy=-6)
PARTS = tank_parts(SOURCE, 2, 2)
CAMERA = (2856, 170, 1790)
ROOM = '2850 153 1782 2857 168 1790'
COLUMN = '2848 1776'
ENTITY = '@e[type=create:stationary_contraption,x=2853,y=159,z=1785,distance=..7,limit=1]'
CASES = (('empty', None, 0, 128), ('water', 'minecraft:water', 19000, 128),
         ('honey', 'create:honey', 2375, 128), ('chocolate', 'create:chocolate', 3125, -128))


def prepare(command):
    command(f'fill {ROOM} {AIR}')
    command(f'setblock {xyz(PULLEY)} create:rope_pulley[axis=x]{{Offset:4f}}')
    command('fill 2853 161 1785 2853 163 1785 create:rope[waterlogged=false]')
    command('setblock 2853 160 1785 create:pulley_magnet[waterlogged=false]')
    command(f'fill {xyz(SOURCE)} {xyz(offset(SOURCE, 1, 1, 1))} {TANK}')


def fill(command, fluid, amount):
    if fluid:
        command(f'data merge block {xyz(SOURCE)} '
                f'{{TankContent:{{Fluid:{{id:"{fluid}",amount:{amount}}}}}}}')


def power(command, rpm):
    command(f'setblock {xyz(MOTOR)} create:creative_motor[facing=west]{{ScrollValue:{rpm}}}')


def tank_at(origin, fluid, amount):
    expected = expected_tank(origin, 2, 2, amount)
    expected[xyz(origin)]['fluid'] = fluid
    return expected


def original(work):
    host = Original()
    initial = host.call('state', {})
    assert initial['ready'] and initial['data_version'] == 3955, initial
    host.call('tick', {'frozen': True})
    try:
        host.command('tp @s ' + xyz(CAMERA))
        host.command(f'forceload add {COLUMN}')
        step(host, 20, PULLEY)
        results = {}
        for name, fluid, amount, rpm in CASES:
            prepare(host.command)
            step(host, 6, PULLEY)
            fill(host.command, fluid, amount)
            step(host, 6, PULLEY)
            assert snapshot(host, PARTS) == tank_at(SOURCE, fluid, amount)
            power(host.command, rpm)
            driver, *empty = step(host, 8, PULLEY, *PARTS)
            running, moving_offset = pose(driver['nbt'])
            assert running and (moving_offset < 4 if rpm > 0 else moving_offset > 4), driver
            assert all(row['id'] == AIR for row in empty), empty
            raw = text(host, f'data get entity {ENTITY} Contraption')
            mounted = field(raw, 'fluids')
            assert re.search(r'\bcapacity:\s*64000\b', mounted), mounted
            if fluid:
                assert fluid in mounted and re.search(rf'\bamount:\s*{amount}\b', mounted), mounted
            if rpm < 0:
                # A frozen Java removal reports zero effective RPM before the
                # source changes, skipping the regular sign-change snap.
                landed = host.call('observe_ticks', {
                    'ticks': 24, 'positions': [PULLEY],
                    'commands': ['tick unfreeze', f'setblock {xyz(MOTOR)} {AIR}'],
                })['samples'][-1]['blocks'][0]
            else:
                landed = step(host, 24, PULLEY)[0]
            running, landing_offset = pose(landed['nbt'])
            assert not running and (landing_offset == 0 if rpm > 0 else landing_offset > 4), landed
            target = offset(SOURCE, dy=4 - int(landing_offset))
            landed_parts = snapshot(host, tank_parts(target, 2, 2))
            assert landed_parts == tank_at(target, fluid, amount), landed_parts
            results[name] = dict(moving_offset=moving_offset, landing_offset=landing_offset,
                                 landed=landed_parts)
        return results
    finally:
        host.command(f'setblock {xyz(MOTOR)} {AIR}')
        step(host, 5, PULLEY)
        host.command(f'fill {ROOM} {AIR}')
        host.command(f'forceload remove {COLUMN}')
        host.call('camera', {key: initial[key] for key in ('position', 'yaw', 'pitch')})
        host.call('tick', {'frozen': initial['server']['frozen']})
        (work / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')


def check_fluid(data, fluid, amount):
    if fluid:
        content = data['TankContent']['value']['Fluid']['value']
        assert content['id']['value'] == fluid and content['amount']['value'] == amount, content
    elif 'TankContent' in data:
        assert 'Fluid' not in data['TankContent']['value'], data


def native(session, expected):
    def saved(keys):
        return read_saved_chunk_tag(session.scratch, PULLEY, keys, session.world)['nbt']

    results = {}
    for name, fluid, amount, rpm in CASES:
        batch = Batch()
        batch.load(CAMERA)
        prepare(batch.command)
        batch.tick(6)
        fill(batch.command, fluid, amount)
        batch.tick(6)
        power(batch.command, rpm)
        batch.tick(8)
        batch.data(PULLEY)
        for pos in PARTS:
            batch.expect(pos, AIR)
        moving, *cells = batch.run(session, name + '-tank-capture')
        assert pose(moving) == (True, expected[name]['moving_offset']), moving
        check_blocks(cells)
        assert saved(SCENE) is not None
        [entry] = saved(STORAGE)['value']['Tanks']['value']
        data = entry['value']
        assert data['Bearing']['value'] == list(PULLEY)
        assert data['Controller']['value'] == [0, -1, 0]
        assert data['Size']['value'] == data['Height']['value'] == 2
        check_fluid(data, fluid, amount)

        batch = Batch()
        batch.load(CAMERA)
        if rpm < 0:
            batch.put(MOTOR, AIR)
        batch.tick(24)
        batch.data(PULLEY)
        landing_offset = expected[name]['landing_offset']
        target = offset(SOURCE, dy=4 - int(landing_offset))
        parts = tank_at(target, fluid, amount)
        assert parts == expected[name]['landed']
        for position, part in parts.items():
            props = ','.join(f'{key}={value}' for key, value in part['state'].items())
            batch.expect(tuple(map(int, position.split())), f'{TANK}[{props}]')
        landed, *cells = batch.run(session, name + '-tank-cold-landing')
        assert pose(landed) == (False, landing_offset), landed
        check_blocks(cells)
        assert saved(SCENE) is None and saved(STORAGE) is None
        for pos in tank_parts(target, 2, 2):
            tag = read_saved_block(session.scratch, pos, session.world)['nbt']['value']
            if pos == target:
                assert tag['Size']['value'] == tag['Height']['value'] == 2
                check_fluid(tag, fluid, amount)
            else:
                assert tag['Controller']['value'] == list(target), tag
        results[name] = expected[name]
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--java', action='store_true')
    for flag in ('game', 'resources', 'ctl', 'create-jar', 'reference'):
        parser.add_argument('--' + flag, type=Path)
    args = parser.parse_args()
    if args.java:
        work = Path(tempfile.mkdtemp(prefix='pulley-tank-java-', dir=ROOT / '.local'))
        cases = original(work)
    else:
        if not all((args.game, args.resources, args.ctl, args.reference)):
            parser.error('Horizon needs --game, --resources, --ctl and --reference')
        reference = json.loads(args.reference.read_text())
        assert reference['passed'] and reference['create'] == PINS['create_revision'], reference
        session = NativeCheckSession(args.game, args.resources, args.ctl, args.create_jar,
                                     name='pulley-tank-native', world='PulleyTank', graphics=False)
        work = session.scratch
        try:
            cases = native(session, reference['cases'])
        finally:
            session.control_temp.cleanup()
            for folder in (session.resources, work / '.horizon-cache', work / 'horizon-mods'):
                shutil.rmtree(folder, ignore_errors=True)
    output = work / 'result.json'
    output.write_text(json.dumps(dict(passed=True, create=PINS['create_revision'], cases=cases), indent=2) + '\n')
    print(output)


if __name__ == '__main__':
    main()
