#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Compare single-click Fluid Tank layer placement and item consumption."""

import argparse
import json
from pathlib import Path
import shutil
import tempfile

from burner_heat_java_checks import number
from chain_drive_checks import Native, Original, xyz
from common import PINS, ROOT
from fluid_tank_checks import TANK, click, offset, part_snapshot, settle, tank_parts
from funnel_checks import block, put, text
from native_check_session import NativeCheckSession, wait_loaded
import reference_java as java


BASE = (2431, 168, 1018)
AREA = '2428 163 1015 2435 173 1022'
COLUMNS = '2416 1008 2447 1023'
TOP_FEET = (2431.5, 170, 1016.5)
BOTTOM_FEET = (2431.5, 165, 1018.5)
SIDE_FEET = (2431.5, 167, 1016.5)


def setup(host, width):
    cmd = host.command
    cmd('gamemode creative')
    cmd(f'fill {AREA} minecraft:air')
    cmd('fill 2428 164 1015 2435 164 1022 minecraft:smooth_stone')
    put(cmd, (2431, 169, 1016), 'minecraft:smooth_stone')
    put(cmd, (2431, 166, 1016), 'minecraft:smooth_stone')
    for pos in tank_parts(BASE, width, 1):
        put(cmd, pos, TANK)
    settle(host, 12)
    controller = part_snapshot(host, BASE)
    assert controller['size'] == width and controller['height'] == 1, controller


def use(host, work, name, mode, count, face, sneak):
    cmd = host.command
    cmd(f'gamemode {mode}')
    aim = {
        'up': (2431.5, 169, 1018.5),
        'down': (2431.5, 168, 1018.5),
        'north': (2431.5, 168.5, 1018),
    }
    feet = {'up': TOP_FEET, 'down': BOTTOM_FEET, 'north': SIDE_FEET}
    if sneak:
        if isinstance(host, Native):
            host.session.call('key', 'shift', 'down')
        else:
            host.call('input', {'key': 'shift', 'down': True})
    try:
        click(host, work, name, f'{TANK} {count}', feet=feet[face], aim=aim[face], pos=BASE, face=face)
    finally:
        if sneak:
            if isinstance(host, Native):
                host.session.call('key', 'shift', 'up')
            else:
                host.call('input', {'key': 'shift', 'down': False})
    settle(host, 12)


def observe(host, width):
    positions = [p for dy in (-1, 0, 1) for p in tank_parts(offset(BASE, dy=dy), width, 1)]
    positions.append(offset(BASE, dz=-1))
    blocks = {}
    for pos in positions:
        state = block(host, pos)
        if state['id'] == TANK:
            part = part_snapshot(host, pos)
            blocks[xyz(pos)] = part
        elif state['id'] != 'minecraft:air':
            blocks[xyz(pos)] = state['id']
    held = text(host, 'data get entity @s SelectedItem')
    return dict(blocks=blocks, held=int(number({'nbt': held}, 'count', 0)))


def cases(host, work):
    rows = {}
    for name, width, mode, count, face, sneak, preset, remaining in [
        ('creative-top', 2, 'creative', 1, 'up', False, None, 1),
        ('creative-bottom', 2, 'creative', 1, 'down', False, None, 1),
        ('survival-insufficient', 2, 'survival', 3, 'up', False, None, 2),
        ('survival-obstructed', 2, 'survival', 4, 'up', False, 'minecraft:stone', 3),
        ('survival-sneak', 2, 'survival', 4, 'up', True, None, 3),
        ('survival-side', 2, 'survival', 4, 'north', False, None, 3),
        ('survival-width-three', 3, 'survival', 9, 'up', False, None, 0),
        ('survival-existing-member', 3, 'survival', 8, 'up', False, TANK, 0),
    ]:
        setup(host, width)
        if preset is not None:
            put(host.command, offset(BASE, width-1, 1, width-1), preset)
            settle(host, 4)
        use(host, work, name, mode, count, face, sneak)
        row = observe(host, width)
        assert row['held'] == remaining, (name, row)
        positions = [p for p, state in row['blocks'].items() if isinstance(state, dict)]
        complete = name in {'creative-top', 'creative-bottom', 'survival-width-three',
                            'survival-existing-member'}
        expected_count = 2 * width * width if complete else width * width + 1
        assert len(positions) == expected_count, (name, row)
        root = offset(BASE, dy=-1) if face == 'down' else BASE
        state = row['blocks'][xyz(root)]
        assert state['height'] == (2 if complete else 1) and state['size'] == width, (name, state)
        rows[name] = row
    return rows


def original(work):
    host = Original()
    assert json.loads((java.BASE / 'manifest.json').read_text())['create_sha256'] == java.CREATE_SHA256
    initial = host.call('state', {})
    assert initial['ready'] and initial['data_version'] == 3955, initial
    host.call('tick', {'frozen': True})
    try:
        host.command(f'forceload add {COLUMNS}')
        settle(host, 20)
        return cases(host, work)
    finally:
        host.command('gamemode creative')
        host.command('item replace entity @s weapon.mainhand with minecraft:air')
        host.command(f'fill {AREA} minecraft:air')
        host.command(f'forceload remove {COLUMNS}')
        host.call('camera', {'position': initial['position'], 'yaw': initial['yaw'], 'pitch': initial['pitch']})
        host.call('tick', {'frozen': initial['server']['frozen']})
        (work / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--java', action='store_true')
    for flag in ('game', 'resources', 'ctl', 'reference', 'create-jar'):
        parser.add_argument('--' + flag, type=Path)
    args = parser.parse_args()
    if args.java:
        work = Path(tempfile.mkdtemp(prefix='fluid-layer-java-', dir=ROOT / '.local'))
        print(work, flush=True)
        rows = original(work)
        cold = False
    else:
        if not all((args.game, args.resources, args.ctl, args.reference)):
            parser.error('Horizon requires --game, --resources, --ctl and --reference')
        reference = json.loads(args.reference.read_text())
        assert reference['passed'] and reference['create'] == PINS['create_revision'], reference
        session = NativeCheckSession(args.game, args.resources, args.ctl, args.create_jar,
                                     name='fluid-layer-native', world='CreateFluidLayers')
        work = session.scratch
        print(work, flush=True)
        try:
            with session:
                host = Native(session)
                host.command(f'tp @s {xyz(TOP_FEET)}')
                wait_loaded(session.call, [BASE, offset(BASE, dx=2, dz=2)])
                rows = cases(host, work)
                session.restart()
                wait_loaded(session.call, [BASE, offset(BASE, dx=2, dz=2)])
                assert observe(host, 3) == rows['survival-existing-member']
                cold = True
        finally:
            for folder in (session.resources, work / '.horizon-cache', work / 'horizon-mods'):
                shutil.rmtree(folder, ignore_errors=True)
        for name, row in rows.items():
            assert row == reference['cases'][name], (name, row, reference['cases'][name])
    out = work / 'result.json'
    out.write_text(json.dumps(dict(passed=True, create=PINS['create_revision'], cold=cold, cases=rows),
                              indent=2) + '\n')
    print(out)


if __name__ == '__main__':
    main()
