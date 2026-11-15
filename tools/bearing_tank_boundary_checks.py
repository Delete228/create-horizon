#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Compare filled Bearing Tanks at a real chunk and Anvil region boundary."""

import argparse
import json
from pathlib import Path
import re
import shutil
import tempfile

from bearing_barrel_checks import pose
from bearing_repeat_checks import SCENE
from bearing_tank_checks import AIR, BEDROCK, DRIVE, STORAGE
from burner_heat_java_checks import field
from chain_drive_checks import Native, Original, xyz
from common import PINS, ROOT
from fluid_tank_checks import TANK, expected_tank, offset, part_snapshot, set_fluid, tank_parts
from funnel_checks import block, put, step, text
from native_check_session import NativeCheckSession, wait_loaded
from saved_block_checks import read_saved_chunk_tag

# x=1024 begins a new chunk column and a new Anvil region.
X, Y = 1023, 160
LOAD = '1008 576 1039 623'
CASES = {
    'crossing_source': (582, (0, -2), (-2, -1), False),
    'crossing_destination': (598, (-1, 1), (1, 0), False),
    'blocked_destination': (614, (-1, 1), (1, 0), True),
}
AMOUNT = 19000


def room(z):
    return f'{X-3} {Y-1} {z-3} {X+3} {Y+3} {z+3}'


def layout(z, source, destination):
    pivot = (X, Y, z)
    anchor = offset(pivot, dy=1)
    source = offset(anchor, source[0], 0, source[1])
    destination = offset(anchor, destination[0], 0, destination[1])
    return pivot, anchor, source, destination


def tank_at(host, root):
    return {xyz(pos): part_snapshot(host, pos) for pos in tank_parts(root, 2, 2)}


def prepare(host, pivot, anchor, source, destination, blocked):
    command = host.command
    command(f'fill {room(pivot[2])} {AIR}')
    put(command, pivot, 'create:mechanical_bearing[facing=up]')
    put(command, anchor, 'minecraft:slime_block')
    command(f'fill {xyz(source)} {xyz(offset(source, 1, 1, 1))} {TANK}')
    step(host, 8, pivot)
    set_fluid(host, source, AMOUNT)
    assert tank_at(host, source) == expected_tank(source, 2, 2, AMOUNT)
    if blocked:
        put(command, offset(destination, 1, 1, 1), BEDROCK)
    put(command, offset(pivot, dy=-1), DRIVE)


def loaded(host, pos):
    if isinstance(host, Native):
        command = f'execute if loaded {xyz(pos)} run say create_tank_boundary_loaded'
        return 'create_tank_boundary_loaded' in text(host, command)
    return 'Test passed' in text(host, f'execute if loaded {xyz(pos)}')


def java_case(host, pivot, anchor, source, destination, blocked):
    source_cells = set(tank_parts(source, 2, 2))
    destination_cells = set(tank_parts(destination, 2, 2))
    assert all(loaded(host, pos) for pos in (pivot, source, offset(source, dx=1),
                                             destination, offset(destination, dx=1)))
    prepare(host, pivot, anchor, source, destination, blocked)
    rows = step(host, 11, pivot, *sorted(source_cells))
    assert pose(rows[0]['nbt']) == [1, 95.99999], rows[0]
    assert all(row['id'] == AIR for row in rows[1:]), rows
    selector = f'@e[type=create:stationary_contraption,x={X},y={Y+1},z={pivot[2]},distance=..3,limit=1]'
    mounted = field(text(host, f'data get entity {selector} Contraption'), 'fluids')
    assert mounted.count('create:fluid_tank') == 1 and re.search(r'\bamount:\s*19000\b', mounted), mounted
    put(host.command, offset(pivot, dy=-1), AIR)
    stopped = step(host, 8, pivot)[0]
    assert pose(stopped['nbt']) == [0, 0], stopped
    assert all(block(host, pos)['id'] == AIR for pos in source_cells - destination_cells)
    placed = {xyz(pos): block(host, pos) for pos in sorted(destination_cells)}
    if blocked:
        assert placed[xyz(offset(destination, 1, 1, 1))]['id'] == BEDROCK, placed
        assert sum(row['id'] == TANK for row in placed.values()) == 7, placed
        assert part_snapshot(host, destination)['amount'] == AMOUNT, placed
    else:
        assert tank_at(host, destination) == expected_tank(destination, 2, 2, AMOUNT)
    return dict(captured=True, landed=sum(row['id'] == TANK for row in placed.values()),
                placed=placed, mounted=mounted)


def java_unloaded(host, *, source_unloaded):
    # The bearing ticket also loads nearby columns. A long Java slime arm
    # lets the tank source or destination unload while the bearing ticks.
    z = 630 if source_unloaded else 710
    pivot = (X, Y, z)
    anchor = offset(pivot, dy=1)
    source = offset(anchor, dx=65)
    destination = offset(anchor, dz=-66)
    source_columns = f'1008 {z} 1103 {z}'
    target_columns = f'1008 {destination[2]} 1039 {z}'
    source_room = f'{X} {Y-1} {z} 1089 {Y+2} {z+1}'
    target_room = f'{X} {Y+1} {destination[2]} {X+1} {Y+2} {z-1}'
    try:
        host.command(f'forceload add {source_columns}')
        step(host, 50, pivot)
        assert loaded(host, source), source
        host.command(f'fill {source_room} {AIR}')
        put(host.command, pivot, 'create:mechanical_bearing[facing=up]')
        host.command(f'fill {xyz(anchor)} {xyz(offset(source, dx=-1))} minecraft:slime_block')
        host.command(f'fill {xyz(source)} {xyz(offset(source, 1, 1, 1))} {TANK}')
        step(host, 8, pivot)
        set_fluid(host, source, AMOUNT)
        assert tank_at(host, source) == expected_tank(source, 2, 2, AMOUNT)
        if source_unloaded:
            host.command(f'forceload remove 1024 {z} 1103 {z}')
        host.command(f'tp @s 800.5 180 {z}.5')
        absent = source if source_unloaded else destination
        for _ in range(8):
            step(host, 50, pivot)
            if not loaded(host, absent):
                break
        assert loaded(host, pivot) and not loaded(host, absent), (pivot, absent)
        put(host.command, offset(pivot, dy=-1), DRIVE)
        captured = step(host, 4 if source_unloaded else 11, pivot, anchor)
        assert pose(captured[0]['nbt']) == [1, 28.800001 if source_unloaded else 95.99999], captured
        assert captured[1]['id'] == AIR, captured
        selector = f'@e[type=create:stationary_contraption,x={X},y={Y+1},z={z},distance=..3,limit=1]'
        mounted = field(text(host, f'data get entity {selector} Contraption'), 'fluids')
        assert re.search(r'pos:\s*\[I;\s*65,\s*0,\s*0\]', mounted), mounted
        assert mounted.count('create:fluid_tank') == 1 and re.search(r'\bamount:\s*19000\b', mounted), mounted
        loaded_at_stop = loaded(host, absent)
        if not source_unloaded:
            assert not loaded_at_stop, absent
        put(host.command, offset(pivot, dy=-1), AIR)
        stopped = step(host, 8, pivot)[0]
        assert pose(stopped['nbt']) == [0, 0], stopped
        landed = source if source_unloaded else destination
        host.command(f'forceload add {source_columns if source_unloaded else target_columns}')
        step(host, 50, pivot)
        assert loaded(host, landed), landed
        assert tank_at(host, landed) == expected_tank(landed, 2, 2, AMOUNT)
        return dict(captured=True, loaded_before_start=False, loaded_at_stop=loaded_at_stop,
                    restored_amount=AMOUNT, mounted=mounted, landed_root=landed)
    finally:
        put(host.command, offset(pivot, dy=-1), AIR)
        host.command(f'forceload add {source_columns}')
        if not source_unloaded:
            host.command(f'forceload add {target_columns}')
        step(host, 25, pivot)
        host.command(f'fill {source_room} {AIR}')
        if not source_unloaded:
            for block_id in ('minecraft:slime_block', TANK):
                host.command(f'fill {target_room} {AIR} replace {block_id}')
            # The target and source force ranges overlap in the owner's column.
            host.command(f'forceload remove {target_columns}')
        host.command(f'forceload remove {source_columns}')


def java(work):
    host = Original()
    initial = host.call('state', {})
    if initial['screen'] == 'PauseScreen':
        host.call('input', {'kind': 'escape'})
        initial = host.call('state', {})
    assert initial['ready'] and initial['data_version'] == 3955, initial
    host.call('tick', {'frozen': True})
    host.command(f'forceload add {LOAD}')
    try:
        host.command('tp @s 1022.5 180 600.5')
        step(host, 50, (X, Y, 598))
        results = {name: java_case(host, *layout(z, source, destination), blocked)
                   for name, (z, source, destination, blocked) in CASES.items()}
        results['unloaded_source'] = java_unloaded(host, source_unloaded=True)
        results['unloaded_destination'] = java_unloaded(host, source_unloaded=False)
        return results
    finally:
        for z, *_ in CASES.values():
            host.command(f'fill {room(z)} {AIR}')
        host.command(f'forceload remove {LOAD}')
        host.call('camera', {key: initial[key] for key in ('position', 'yaw', 'pitch')})
        host.call('tick', {'frozen': initial['server']['frozen']})
        (work / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')


def native(session):
    host = Native(session)
    points = [(x, Y, z) for z, *_ in CASES.values() for x in (X, X + 1)]

    def arrive():
        host.command('tp @s 1022.5 180 600.5')
        wait_loaded(session.call, points)
        host.command('tick freeze')

    def unload_one(side):
        z = CASES['crossing_source'][0]
        expected = (side == -1, side == 1)
        attempts = []
        for distance in range(1, 9):
            x = ((X >> 4) + side * distance) * 16 + 8.5
            host.command(f'tp @s {x} 180 {z}.5')
            step(host, 45)
            present = tuple(loaded(host, (x, Y, z)) for x in (X, X + 1))
            if present == expected:
                return present
            attempts.append(present)
        raise AssertionError(('could not unload one region independently', side, attempts))

    def verify():
        rows = {}
        for name, (z, source, destination, blocked) in CASES.items():
            pivot, anchor, source, destination = layout(z, source, destination)
            assert pose(block(host, pivot)['nbt']) == [0, 0]
            assert block(host, anchor)['id'] == 'minecraft:slime_block'
            assert tank_at(host, source) == expected_tank(source, 2, 2, AMOUNT)
            source_cells = set(tank_parts(source, 2, 2))
            for pos in set(tank_parts(destination, 2, 2)) - source_cells:
                assert block(host, pos)['id'] == (BEDROCK if blocked and
                                                  pos == offset(destination, 1, 1, 1) else AIR)
            rows[name] = dict(captured=False, intact_source=True, retained_amount=AMOUNT)
        return rows

    try:
        session.start()
        arrive()
        for z, source, destination, blocked in CASES.values():
            prepare(host, *layout(z, source, destination), blocked)
            step(host, 12, (X, Y, z))
        before = verify()
        availability = [unload_one(side) for side in (-1, 1)]
        arrive()
        assert verify() == before
        session.restart()
        arrive()
        step(host, 12, (X, Y, 598))
        assert verify() == before
        session.stop()
        for pos in points:
            for path in (SCENE, STORAGE):
                tag = read_saved_chunk_tag(session.scratch, pos, path, session.world)
                assert tag['nbt'] is None, (pos, path, tag)
        return ({name: row | {'cold_restart': True} for name, row in before.items()}
                | {'adjacent_unload': dict(loaded_columns=availability, intact_source=True)})
    finally:
        session.stop()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--java', action='store_true')
    for key in ('game', 'resources', 'ctl', 'create-jar'):
        parser.add_argument('--' + key, type=Path)
    args = parser.parse_args()
    session = None
    if args.java:
        work = Path(tempfile.mkdtemp(prefix='bearing-tank-boundary-java-', dir=ROOT / '.local'))
    else:
        if not all((args.game, args.resources, args.ctl, args.create_jar)):
            parser.error('Horizon requires --game, --resources, --ctl and --create-jar')
        session = NativeCheckSession(args.game, args.resources, args.ctl, args.create_jar,
                                     name='bearing-tank-boundary', graphics=False,
                                     world='CreateBearingTankBoundary')
        work = session.scratch
    print(work, flush=True)
    report = dict(passed=False, create=PINS['create_revision'])
    try:
        report.update(cases=native(session) if session else java(work), passed=True)
    finally:
        if session:
            session.control_temp.cleanup()
            for folder in (session.resources, work / '.horizon-cache', work / 'horizon-mods'):
                shutil.rmtree(folder, ignore_errors=True)
        (work / 'result.json').write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    main()
