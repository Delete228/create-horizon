#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Compare a complete ordinary Fluid Tank on a vertical Mechanical Bearing."""

import argparse
import json
from pathlib import Path
import re
import shutil
import tempfile
import time

from bearing_barrel_checks import pose
from bearing_native_checks import Batch
from burner_heat_java_checks import field
from chain_drive_checks import Native, Original, xyz
from common import PINS, ROOT
from fluid_tank_checks import TANK, expected_tank, offset, part_snapshot, set_fluid, tank_parts
from funnel_checks import block, put, step, text
from native_check_session import NativeCheckSession, wait_loaded
from reference_java import BASE, CREATE_SHA256
from saved_block_checks import read_saved_chunk_tag


AIR = 'minecraft:air'
BEDROCK = 'minecraft:bedrock'
PIVOT = (2810, 160, 1770)
ANCHOR = offset(PIVOT, dy=1)
MOTOR = offset(PIVOT, dy=-1)
SOURCE = offset(ANCHOR, 1, 0, -1)
LANDED = offset(ANCHOR, -1, 0, -2)
NEIGHBOR = offset(ANCHOR, 3, 0, 0)
SOURCE_PARTS = tank_parts(SOURCE, 2, 2)
TARGET_PARTS = tank_parts(LANDED, 2, 2)
CAMERA = (2816.5, 163, 1775.5)
CAMERA_FLOOR = (2816, 162, 1775)
LOOK = (2810.5, 162, 1769)
ROOM = '2805 159 1764 2815 164 1775'
COLUMNS = '2800 1760 2831 1791'
ENTITY = f'@e[type=create:stationary_contraption,x={ANCHOR[0]},y={ANCHOR[1]},z={ANCHOR[2]},distance=..3,limit=1]'
DRIVE = 'create:creative_motor[facing=up]{ScrollValue:32}'
STORAGE = ('horizon:attachments', 'create', 'mounted_empty_tanks', 'value')
CASES = (('empty', 0), ('water', 19000), ('lava', 19000))
SOURCE_LIGHT = offset(SOURCE, dx=-1)
TARGET_LIGHT = offset(LANDED, dx=-1)


def snapshot(host, positions):
    return {xyz(pos): part_snapshot(host, pos) for pos in positions}


def prepare(host, amount, fluid='water'):
    command = host.command
    command(f'fill {ROOM} {AIR}')
    put(command, PIVOT, 'create:mechanical_bearing[facing=up]')
    put(command, ANCHOR, 'minecraft:slime_block')
    command(f'fill {xyz(SOURCE)} {xyz(offset(SOURCE, 1, 1, 1))} {TANK}')
    step(host, 6, PIVOT)
    put(command, NEIGHBOR, TANK)
    if amount:
        set_fluid(host, SOURCE, amount, fluid)
    if amount and fluid == 'lava':
        # Set the static source's known canonical emission explicitly since
        # /data merge does not run FluidTankBlockEntity.onFluidStackChanged.
        for pos in SOURCE_PARTS:
            luminosity = 12 if pos[1] == SOURCE[1] else 1
            command(f'data merge block {xyz(pos)} {{Luminosity:{luminosity}}}')
    step(host, 6, PIVOT)
    assert snapshot(host, SOURCE_PARTS) == expected_tank(SOURCE, 2, 2, amount, fluid=fluid)
    assert snapshot(host, [NEIGHBOR]) == expected_tank(NEIGHBOR, 1, 1)


def verify_mounted_tag(host, amount, fluid):
    raw = text(host, f'data get entity {ENTITY} Contraption')
    mounted = field(raw, 'fluids')
    assert re.search(r'\bpos:\s*\[I;\s*1,\s*0,\s*-1\]', mounted), mounted
    assert re.search(r'\bcapacity:\s*64000\b', mounted), mounted
    assert mounted.count('create:fluid_tank') == 1, mounted
    if amount:
        assert f'minecraft:{fluid}' in mounted and re.search(rf'\bamount:\s*{amount}\b', mounted), mounted
    members = field(raw, 'CapturedMultiblocks')
    assert re.search(r'\bController:\s*\[I;\s*1,\s*0,\s*-1\]', members), members
    assert len(re.findall(r'\bPos:\s*\[I;', members)) == 8, members
    return raw


def original(work):
    host = Original()
    initial = host.call('state', {})
    if initial['screen'] == 'PauseScreen':
        host.call('input', {'kind': 'escape'})
        initial = host.call('state', {})
    assert initial['ready'] and initial['data_version'] == 3955, initial
    assert json.loads((BASE / 'manifest.json').read_text())['create_sha256'] == CREATE_SHA256
    host.call('tick', {'frozen': True})
    try:
        host.command('gamemode creative')
        host.command(f'forceload add {COLUMNS}')
        host.call('camera', {'position': CAMERA, 'target': LOOK, 'fov': 52, 'hide_gui': True})
        step(host, 24, PIVOT)
        put(host.command, CAMERA_FLOOR, 'minecraft:smooth_stone')
        results = {}
        for name, amount in CASES:
            prepare(host, amount, name)
            put(host.command, MOTOR, DRIVE)
            captured = step(host, 10, PIVOT, ANCHOR, *SOURCE_PARTS, NEIGHBOR)
            assert pose(captured[0]['nbt']) == [1, 86.399994], captured
            assert all(row['id'] == AIR for row in captured[1:-1]), captured
            assert captured[-1]['id'] == TANK, captured
            raw = verify_mounted_tag(host, amount, name)
            (work / f'{name}-contraption.snbt').write_text(raw + '\n')
            host.call('camera', {'position': CAMERA, 'target': LOOK})
            result = host.call('capture', {'name': f'{work.name}/{name}.png', 'frames': 16})
            shutil.copy2(Path(result['path']), work / f'{name}.png')
            moving_light = host.call('block_light', {'pos': SOURCE_LIGHT})['block_light']
            assert moving_light == 0, moving_light

            moving = step(host, 1, PIVOT)[0]
            assert pose(moving['nbt']) == [1, 95.99999], moving
            put(host.command, MOTOR, AIR)
            landed = step(host, 5, PIVOT)[0]
            assert pose(landed['nbt']) == [0, 0], landed
            observed = snapshot(host, TARGET_PARTS + [NEIGHBOR])
            assert observed == (expected_tank(LANDED, 2, 2, amount, fluid=name) | expected_tank(NEIGHBOR, 1, 1)), observed
            assert all(block(host, pos)['id'] == AIR for pos in SOURCE_PARTS)
            results[name] = dict(captured=pose(captured[0]['nbt']), moving=pose(moving['nbt']),
                                 landed=observed, moving_light=moving_light, image=f'{name}.png')
        return results
    finally:
        put(host.command, MOTOR, AIR)
        step(host, 2, PIVOT)
        host.command(f'kill {ENTITY}')
        host.command(f'fill {ROOM} {AIR}')
        put(host.command, CAMERA_FLOOR, AIR)
        host.command(f'forceload remove {COLUMNS}')
        host.call('camera', {key: initial[key] for key in ('position', 'yaw', 'pitch', 'fov')}
                  | {'hide_gui': initial.get('hide_gui', False)})
        host.call('tick', {'frozen': initial['server']['frozen']})
        (work / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')


def native(session, expected, name, amount):
    host = Native(session)
    command, call = host.command, session.call
    points = [PIVOT, ANCHOR, *SOURCE_PARTS, *TARGET_PARTS, NEIGHBOR]
    image = session.scratch / f'{name}.png'
    cold_image = session.scratch / f'{name}-cold.png'

    def game_time():
        values = re.findall(r'\b\d+\b', text(host, 'time query gametime'))
        assert len(values) == 1, values
        return int(values[0])

    def advance(count, *positions):
        # A genuinely frozen tick supplies zero effective RPM. Observe a
        # fixed number of ordinary server ticks before freezing for capture.
        command('tick rate 4')
        start = game_time()
        command('tick unfreeze')
        try:
            deadline = time.monotonic() + 12
            while game_time() < start + count - 1:
                assert time.monotonic() < deadline, ('simulation stalled', start, count)
                time.sleep(.035)
        finally:
            command('tick freeze')
            command('tick rate 20')
        elapsed = game_time() - start
        assert count - 1 <= elapsed <= count + 1, (elapsed, count)
        return [block(host, pos) for pos in positions]

    def align_camera():
        put(command, CAMERA_FLOOR, 'minecraft:smooth_stone')
        command(f'tp @s {xyz(CAMERA)}')
        call('look-at', *LOOK)
        call('wait', 8)

    def verify_parked():
        assert pose(block(host, PIVOT)['nbt'])[0] == 1
        assert all(block(host, pos)['id'] == AIR for pos in [ANCHOR, *SOURCE_PARTS])
        assert all(block(host, pos)['id'] == (BEDROCK if pos == LANDED else AIR) for pos in TARGET_PARTS)

    def saved_mount():
        tag = read_saved_chunk_tag(session.scratch, PIVOT, STORAGE, session.world)['nbt']
        if tag is None:
            return None
        [entry] = tag['value']['Tanks']['value']
        data = {key: field['value'] for key, field in entry['value'].items()}
        if 'TankContent' in data:
            fluid = data.pop('TankContent')['Fluid']['value']
            data['fluid'] = {key: field['value'] for key, field in fluid.items()}
        return data

    def block_light(pos):
        return int(call('light', *pos, *pos)['block'], 16)

    session.start()
    try:
        command(f'tp @s {xyz(CAMERA)}')
        wait_loaded(call, points)
        command('tick freeze')
        for key, value in [('fov', 52), ('bobView', 'false'), ('chatVisibility', 2), ('tutorialStep', 'none')]:
            call('options-set', key, value)
        call('key', 'f1', 'tap')
        prepare(host, amount, name)
        put(command, MOTOR, DRIVE)
        captured = advance(10, PIVOT, ANCHOR, *SOURCE_PARTS, NEIGHBOR)
        captured_pose = pose(captured[0]['nbt'])
        assert captured_pose[0] == 1 and abs(captured_pose[1] - expected['captured'][1]) < 10, captured
        assert all(row['id'] == AIR for row in captured[1:-1]) and captured[-1]['id'] == TANK, captured
        align_camera()
        call('screenshot', image)
        moving_light = block_light(SOURCE_LIGHT)
        assert moving_light == expected['moving_light'], (name, moving_light)
        moving = advance(1, PIVOT)[0]
        moving_pose = pose(moving['nbt'])
        assert moving_pose[0] == 1 and 70 < moving_pose[1] < 120, moving

        # Keep the tank mounted when the snapped destination is occupied.
        put(command, LANDED, BEDROCK)
        put(command, MOTOR, AIR)
        step(host, 4, PIVOT)
        verify_parked()
        session.stop()
        mounted = saved_mount()
        expected_mount = {'Bearing': list(PIVOT), 'Controller': [1, 0, -1], 'Size': 2, 'Height': 2, 'Window': 1}
        if amount:
            expected_mount['fluid'] = dict(id=f'minecraft:{name}', amount=amount)
        assert mounted == expected_mount, mounted
        session.start()
        wait_loaded(call, points)
        command('tick freeze')
        verify_parked()
        if amount:
            call('key', 'f1', 'tap')
            align_camera()
            call('screenshot', cold_image)
        put(command, LANDED, AIR)
        landed = step(host, 5, PIVOT)[0]
        assert pose(landed['nbt']) == [0, 0], landed
        actual = snapshot(host, TARGET_PARTS + [NEIGHBOR])
        assert actual == expected['landed'], actual
        assert all(block(host, pos)['id'] == AIR for pos in SOURCE_PARTS)
        call('wait', 12)
        landed_light = block_light(TARGET_LIGHT)
        assert (landed_light > 0) == (name == 'lava'), (name, landed_light)
        session.stop()
        assert saved_mount() is None
        session.start()
        wait_loaded(call, points)
        command('tick freeze')
        assert snapshot(host, TARGET_PARTS + [NEIGHBOR]) == actual

        second = offset(ANCHOR, -2, 0, 0)
        put(command, MOTOR, DRIVE)
        second_pose = pose(advance(11, PIVOT)[0]['nbt'])
        assert second_pose[0] == 1 and 70 < second_pose[1] < 120, second_pose
        assert all(block(host, pos)['id'] == AIR for pos in TARGET_PARTS)
        put(command, MOTOR, AIR)
        assert pose(step(host, 5, PIVOT)[0]['nbt']) == [0, 0]
        assert snapshot(host, tank_parts(second, 2, 2)) == expected_tank(second, 2, 2, amount, fluid=name)

        result = dict(captured=captured_pose, moving=moving_pose, landed=actual, attachment=mounted,
                      moving_light=moving_light, landed_light=landed_light, cold_restart=True,
                      second_assembly=True, refusals=['bedrock'], image=image.name)
        if amount:
            result['cold_image'] = cold_image.name
            return result

        prepare(host, 19000)
        command(f'data merge block {xyz(SOURCE)} {{TankContent:{{Fluid:{{components:{{"minecraft:custom_data":{{opaque:1}}}}}}}}}}')
        put(command, MOTOR, DRIVE)
        assert pose(step(host, 11, PIVOT)[0]['nbt']) == [0, 0]
        assert snapshot(host, SOURCE_PARTS) == expected_tank(SOURCE, 2, 2, 19000)
        assert 'opaque' in block(host, SOURCE)['nbt']
        put(command, MOTOR, AIR)

        prepare(host, 0)
        command(f'data merge block {xyz(SOURCE)} {{Foreign:42}}')
        put(command, MOTOR, DRIVE)
        assert pose(step(host, 11, PIVOT)[0]['nbt']) == [0, 0]
        assert 'Foreign: 42' in block(host, SOURCE)['nbt']
        assert snapshot(host, SOURCE_PARTS) == expected_tank(SOURCE, 2, 2)
        put(command, MOTOR, AIR)

        prepare(host, 0)
        command(f'data merge block {xyz(SOURCE)} {{Size:3}}')
        put(command, MOTOR, DRIVE)
        assert pose(step(host, 11, PIVOT)[0]['nbt']) == [0, 0]
        assert all(block(host, pos)['id'] == TANK for pos in SOURCE_PARTS)
        assert 'Size: 3' in block(host, SOURCE)['nbt']
        put(command, MOTOR, AIR)

        command('fill 2805 159 1764 2817 164 1774 minecraft:air')
        pivot = offset(PIVOT, dx=4)
        anchor = offset(pivot, dy=1)
        motor = offset(pivot, dy=-1)
        root = offset(anchor, 1, 0, -1)
        parts = tank_parts(root, 2, 2)
        wait_loaded(call, parts)
        put(command, pivot, 'create:mechanical_bearing[facing=up]')
        put(command, anchor, 'minecraft:slime_block')
        command(f'fill {xyz(root)} {xyz(offset(root, 1, 1, 1))} {TANK}')
        step(host, 6, pivot)
        put(command, motor, DRIVE)
        assert pose(step(host, 11, pivot)[0]['nbt']) == [0, 0]
        assert snapshot(host, parts) == expected_tank(root, 2, 2)
        assert (parts[0][0] >> 4) != (parts[-1][0] >> 4)
        put(command, motor, AIR)
        command(f'fill {xyz(root)} {xyz(offset(root, 1, 1, 1))} {AIR}')
    finally:
        session.stop()

    result['refusals'] += ['fluid_components', 'foreign_nbt', 'partial', 'cross_column']
    return result


def native_timing(session, expected):
    # The official headless command harness advances exactly one normal
    # simulation tick per script action. Keep the visual world separate.
    world = session.world
    session.world = 'CreateBearingTankTiming'
    try:
        batch = Batch()
        batch.load(PIVOT)
        batch.command(f'fill {ROOM} {AIR}')
        batch.put(PIVOT, 'create:mechanical_bearing[facing=up]')
        batch.put(ANCHOR, 'minecraft:slime_block')
        batch.command(f'fill {xyz(SOURCE)} {xyz(offset(SOURCE, 1, 1, 1))} {TANK}')
        batch.tick(6)
        batch.put(NEIGHBOR, TANK)
        batch.tick(6)
        batch.put(MOTOR, DRIVE)
        batch.tick(10)
        batch.data(PIVOT)
        batch.tick()
        batch.data(PIVOT)
        captured, moving = map(pose, batch.run(session, 'exact-tick-timing'))
        assert captured == expected['captured'] and moving == expected['moving'], (captured, moving)
        return {'captured': captured, 'moving': moving}
    finally:
        session.world = world


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ('game', 'resources', 'ctl', 'reference', 'create-jar'):
        parser.add_argument('--' + key, type=Path)
    args = parser.parse_args()
    session = None
    if args.game:
        if not all((args.resources, args.ctl, args.reference, args.create_jar)):
            parser.error('Horizon requires --resources, --ctl, --reference and --create-jar')
        reference = json.loads(args.reference.read_text())
        assert reference['passed'] and reference['create'] == PINS['create_revision']
        session = NativeCheckSession(args.game, args.resources, args.ctl, args.create_jar,
                                     name='bearing-tank-native', world='CreateBearingTank')
        work = session.scratch
    else:
        work = Path(tempfile.mkdtemp(prefix='bearing-tank-java-', dir=ROOT / '.local'))
    print(work, flush=True)
    report = dict(passed=False, create=PINS['create_revision'])
    try:
        if session:
            cases = {name: native(session, reference['cases'][name], name, amount) for name, amount in CASES}
            cases['empty']['exact_tick_timing'] = native_timing(session, reference['cases']['empty'])
        else:
            cases = original(work)
        report.update(cases=cases, passed=True)
    finally:
        if session:
            session.control_temp.cleanup()
            for folder in (session.resources, work / '.horizon-cache', work / 'horizon-mods'):
                shutil.rmtree(folder, ignore_errors=True)
        (work / 'result.json').write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    main()
