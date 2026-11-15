#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Check the visible tip of a loaded rotor beyond the old render cutoffs."""

import argparse
import json
from pathlib import Path
import shutil
import tempfile

from bearing_barrel_checks import pose
from chain_drive_checks import Native, Original, xyz
from common import PINS, ROOT
from contraption_cargo_light_checks import red_ends, setblock
from native_check_session import NativeCheckSession, wait_loaded


X, Y, Z = 1832, 240, 1208
PIVOT, MOTOR, TIP = (X, Y, Z), (X, Y - 1, Z), (X, Y + 16, Z)
ROOM = f'{X - 4} {Y - 2} {Z - 4} {X + 4} {Y + 17} {Z + 4}'
FORCE = f'{X - 4} {Z - 4} {X + 4} {Z + 4}'
ABOVE = (X + .5, Y + 69.0, Z + .5)
FAR = (X + .5, Y + 33.0, Z + 88.5)
TARGET = (X + .5, Y + 16.5, Z + .5)
AWAY = (X + .5, Y + 90.0, Z + .5)
AIR = 'minecraft:air'
FRAME_MARKER = 'Create contraption frame: '


def rig(command, step):
    command(f'fill {ROOM} {AIR}')
    command(f'fill {X} {Y + 1} {Z} {X} {Y + 14} {Z} minecraft:slime_block')
    command(f'fill {X - 2} {Y + 15} {Z - 2} {X + 2} {Y + 15} {Z + 2} minecraft:slime_block')
    command(f'fill {X - 2} {Y + 16} {Z - 2} {X + 2} {Y + 16} {Z + 2} minecraft:red_concrete')
    setblock(command, PIVOT, 'create:mechanical_bearing[facing=up]{ScrollValue:2}')
    setblock(command, MOTOR, 'create:creative_motor[facing=up]{ScrollValue:1}')
    step(4)
    setblock(command, MOTOR, AIR)
    step(4)


def verify_cargo(host):
    bearing, tip = host.snapshot((PIVOT, TIP), 2)
    running, angle = pose(bearing['nbt'])
    assert running and 0 <= angle < 3 and tip['block'] == AIR, (bearing, tip)


def java_run(work):
    host = Original()
    initial = host.call('state', {})
    if initial.get('screen') == 'PauseScreen':
        host.call('input', {'kind': 'escape'})
        initial = host.call('state', {})
    assert initial['ready'] and initial['data_version'] == 3955, initial
    paths = {}
    try:
        host.call('tick', {'frozen': True})
        host.command('gamemode spectator')
        host.command(f'tp @s {xyz(ABOVE)}')
        host.command(f'forceload add {FORCE}')
        host.snapshot([PIVOT], 24)
        host.command('time set 6000')
        rig(host.command, lambda ticks: host.snapshot([PIVOT], ticks))
        verify_cargo(host)
        for name, target in [('above', TARGET), ('away', AWAY)]:
            host.call('camera', {'position': ABOVE, 'target': target, 'hide_gui': True})
            result = host.call('capture', {'name': f'{work.name}/{name}.png', 'frames': 24})
            assert result['client']['screen'] == 'playing', result
            paths[name] = Path(result['path'])
        return paths
    finally:
        host.command(f'kill @e[type=create:stationary_contraption,x={X},y={Y + 1},z={Z},distance=..8]')
        host.command(f'fill {ROOM} {AIR}')
        host.command(f'forceload remove {FORCE}')
        host.command('gamemode creative')
        host.command(f'time set {initial["server"]["day_time"]}')
        host.call('camera', {'position': initial['position'], 'yaw': initial['yaw'],
                             'pitch': initial['pitch'], 'hide_gui': False})
        host.call('tick', {'frozen': initial['server']['frozen']})
        (work / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')


def native_run(session):
    host = Native(session)
    call = session.call

    def step(ticks):
        host.command(f'tick step {ticks}')
        call('wait', ticks + 4)

    paths, rendered = {}, {}
    with session:
        call('render-distance', 8)
        host.command('gamemode spectator')
        host.command(f'tp @s {xyz(ABOVE)}')
        wait_loaded(call, [PIVOT, TIP])
        host.command('tick freeze')
        host.command('time set 6000')
        rig(host.command, step)
        verify_cargo(host)
        call('key', 'f1', 'tap')
        for name, camera, target in [('above', ABOVE, TARGET), ('away', ABOVE, AWAY),
                                     ('far', FAR, TARGET)]:
            host.command(f'tp @s {xyz(camera)}')
            call('look-at', *target)
            wait_loaded(call, [PIVOT, TIP])
            call('wait', 32)
            assert call('block', *PIVOT)['block'] == 'create:mechanical_bearing', name
            start = session.log.stat().st_size
            paths[name] = session.scratch / f'{name}.png'
            call('screenshot', paths[name])
            call('wait', 12)
            with session.log.open() as file:
                file.seek(start)
                rendered[name] = sum(json.loads(line.split(FRAME_MARKER, 1)[1])['controller'] == list(PIVOT)
                                     for line in file if FRAME_MARKER in line)
    return paths, rendered


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--java', action='store_true')
    for name in ('game', 'resources', 'ctl', 'create-jar'):
        parser.add_argument('--' + name, type=Path)
    args = parser.parse_args()
    if args.java:
        work = Path(tempfile.mkdtemp(prefix='contraption-culling-java-', dir=ROOT / '.local'))
        print(work, flush=True)
        paths = java_run(work)
        rendered = None
    else:
        if not all((args.game, args.resources, args.ctl, args.create_jar)):
            parser.error('Horizon runs require --game, --resources, --ctl and --create-jar')
        session = NativeCheckSession(args.game, args.resources, args.ctl, args.create_jar,
                                     name='contraption-culling-native', world='CargoCulling')
        session.env['CREATE_TRACE_CONTRAPTION_FRAMES'] = '1'
        work = session.scratch
        print(work, flush=True)
        try:
            paths, rendered = native_run(session)
        finally:
            session.control_temp.cleanup()
            for folder in (session.resources, work / '.horizon-cache', work / 'horizon-mods'):
                shutil.rmtree(folder, ignore_errors=True)
    red = {name: max(red_ends(path)) for name, path in paths.items()}
    passed = red['above'] > 24 and red['away'] == 0
    if rendered is not None:
        passed = (passed and red['far'] > 24 and rendered['above'] > 0
                  and rendered['far'] > 0 and rendered['away'] == 0)
    report = {'passed': passed, 'create': PINS['create_revision'], 'cargo_red': red,
              'rendered_frames': rendered, 'images': {name: str(path) for name, path in paths.items()}}
    result = work / 'result.json'
    result.write_text(json.dumps(report, indent=2) + '\n')
    print(result)
    assert passed, report


if __name__ == '__main__':
    main()
