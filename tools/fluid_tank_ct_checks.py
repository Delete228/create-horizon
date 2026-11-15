#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Capture original and native connected tank models and audit controller masks."""

import argparse
import json
from pathlib import Path
import shutil
import tempfile

from chain_drive_checks import Native, Original, xyz
from common import PINS, ROOT
from fluid_tank_checks import TANK, offset, part_snapshot, set_fluid, settle, tank_parts
from funnel_checks import block, put
from native_check_session import NativeCheckSession, wait_loaded
import reference_java as java


ROOF = (2415, 168, 986)
TOWER = (2423, 168, 986)
WATER = (2415, 168, 996)
LAVA = (2417, 168, 996)
GROUPS = ((ROOF, 3, 2), (TOWER, 1, 3), (WATER, 2, 1), (LAVA, 2, 1))
CAMERAS = {
    'roof': ((2419.5, 172, 992.5), (2416.5, 169.7, 987.5)),
    'tower': ((2425.5, 169, 991.5), (2423.5, 169.35, 986.5)),
    'touching': ((2417.5, 172, 1002.5), (2417, 168.7, 997)),
}
AREA = '2412 167 984 2427 172 1003'
COLUMNS = '2400 976 2431 1007'
CONNECTIONS = 'create_connections'
FOV = 52


def setup(host):
    cmd = host.command
    cmd('gamemode creative')
    cmd('item replace entity @s weapon.mainhand with minecraft:air')
    cmd('item replace entity @s weapon.offhand with minecraft:air')
    cmd(f'fill {AREA} minecraft:air')
    cmd('fill 2412 167 984 2427 167 1003 minecraft:smooth_stone')
    cmd('time set 6000')
    cmd('weather clear')
    for feet, _ in CAMERAS.values():
        put(cmd, (int(feet[0]), feet[1] - 1, int(feet[2])), 'minecraft:smooth_stone')
    for origin, width, height in GROUPS:
        cmd(f'fill {xyz(origin)} {xyz(offset(origin, width - 1, height - 1, width - 1))} {TANK}')
        settle(host, 10)
    set_fluid(host, WATER, 22000)
    set_fluid(host, LAVA, 22000, fluid='lava')
    settle(host, 10)


def mask_at(pos, origin, width):
    x = pos[0] - origin[0]
    z = pos[2] - origin[2]
    return int(x > 0) + 2 * int(x < width - 1) + 4 * int(z > 0) + 8 * int(z < width - 1)


def snapshot(host, groups, mode):
    rows = {}
    masks = {}
    for origin, width, height in groups:
        for pos in tank_parts(origin, width, height):
            key = xyz(pos)
            raw = block(host, pos)
            part = part_snapshot(host, pos)
            if pos == origin:
                assert (part['size'], part['height']) == (width, height), (pos, part)
            else:
                assert part['controller'] == list(origin), (pos, part)
            if mode == 'native':
                actual = int(raw['properties'][CONNECTIONS])
                assert actual == mask_at(pos, origin, width), (pos, actual, part)
                masks[key] = actual
            else:
                assert CONNECTIONS not in raw['properties'], (pos, raw)
            for internal in (CONNECTIONS, 'create_light'):
                part['state'].pop(internal, None)
            rows[key] = part
    return dict(parts=rows, masks=masks)


def capture(host, work):
    images = {}
    for name, (feet, target) in CAMERAS.items():
        if isinstance(host, Native):
            call = host.session.call
            host.command(f'tp @s {xyz(feet)}')
            call('look-at', *target)
            call('wait', 16)
            path = work / f'{name}.png'
            call('screenshot', path)
        else:
            host.call('camera', dict(position=feet, target=target, fov=FOV, hide_gui=True))
            reply = host.call('capture', dict(name=f'{work.name}/{name}.png', frames=16))
            source = Path(reply['path'])
            path = work / f'{name}.png'
            shutil.copy2(source, path)
        images[name] = path.name
    return images


def original(work):
    host = Original()
    assert json.loads((java.BASE / 'manifest.json').read_text())['create_sha256'] == java.CREATE_SHA256
    initial = host.call('state', {})
    assert initial['ready'] and initial['data_version'] == 3955, initial
    host.call('tick', {'frozen': True})
    try:
        host.command(f'forceload add {COLUMNS}')
        settle(host, 20)
        setup(host)
        rows = snapshot(host, GROUPS, 'java')
        images = capture(host, work)
        return dict(initial=rows, images=images)
    finally:
        host.command(f'fill {AREA} minecraft:air')
        host.command(f'forceload remove {COLUMNS}')
        host.call('camera', dict(position=initial['position'], yaw=initial['yaw'], pitch=initial['pitch'],
                                 fov=initial['fov'], hide_gui=initial.get('hide_gui', False)))
        host.call('tick', {'frozen': initial['server']['frozen']})
        (work / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')


def native(args, work, session, reference):
    mode = 'baseline' if args.baseline else 'native'
    host = Native(session)
    call = session.call
    for key, value in [('fov', FOV), ('bobView', 'false'), ('chatVisibility', 2), ('tutorialStep', 'none')]:
        call('options-set', key, value)
    host.command(f'tp @s {xyz(CAMERAS["roof"][0])}')
    wait_loaded(call, [ROOF, TOWER, WATER, LAVA])
    setup(host)
    state = snapshot(host, GROUPS, mode)
    assert state['parts'] == reference['initial']['parts'], 'Java and Horizon tank topology differ'
    call('key', 'f1', 'tap')
    images = capture(host, work)
    report = dict(initial=state, images=images)
    if args.baseline:
        return report

    # The remaining L-shaped footprint cannot be one tank. The touching
    # independent group must keep both its controller and its own boundaries.
    put(host.command, WATER, 'minecraft:air')
    settle(host, 12)
    surviving = [(pos, 1, 1) for pos in tank_parts(WATER, 2, 1) if pos != WATER]
    report['split'] = snapshot(host, [*surviving, (LAVA, 2, 1)], mode)
    put(host.command, WATER, TANK)
    settle(host, 12)
    report['reformed'] = snapshot(host, GROUPS, mode)
    assert report['reformed']['masks'] == state['masks'], report['reformed']
    session.restart()
    wait_loaded(call, [ROOF, TOWER, WATER, LAVA])
    assert snapshot(host, GROUPS, mode) == report['reformed']
    report['cold'] = True

    roots = list((work / '.horizon-cache/create-assets/overlay').glob('*/assets/create/blockstates/fluid_tank.json'))
    assert len(roots) == 1 and 'create_connections=15' in roots[0].read_text(), roots
    report['active_overlay'] = True
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--java', action='store_true')
    parser.add_argument('--baseline', action='store_true')
    for flag in ('game', 'resources', 'ctl', 'reference', 'create-jar'):
        parser.add_argument('--' + flag, type=Path)
    args = parser.parse_args()
    if args.java:
        work = Path(tempfile.mkdtemp(prefix='tank-ct-java-', dir=ROOT / '.local'))
        print(work, flush=True)
        report = original(work)
    else:
        if not all((args.game, args.resources, args.ctl, args.reference, args.create_jar)):
            parser.error('Horizon requires --game, --resources, --ctl, --reference and --create-jar')
        reference = json.loads(args.reference.read_text())
        assert reference['passed'] and reference['create'] == PINS['create_revision']
        session = NativeCheckSession(args.game, args.resources, args.ctl, args.create_jar,
                                     name='tank-ct-baseline' if args.baseline else 'tank-ct-native',
                                     world='CreateTankCT')
        work = session.scratch
        print(work, flush=True)
        try:
            with session:
                report = native(args, work, session, reference)
        finally:
            for folder in (session.resources, work / '.horizon-cache', work / 'horizon-mods'):
                shutil.rmtree(folder, ignore_errors=True)
    out = work / 'result.json'
    out.write_text(json.dumps(dict(passed=True, create=PINS['create_revision'], **report), indent=2) + '\n')
    print(out)


if __name__ == '__main__':
    main()
