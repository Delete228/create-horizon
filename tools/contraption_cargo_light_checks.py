#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Swap a lamp near stationary rotating cargo and verify both end blocks respond."""

import argparse
import json
from pathlib import Path
import shutil
import subprocess
import tempfile

from bearing_barrel_checks import pose
from chain_drive_checks import Native, Original, xyz
from common import PINS, ROOT
from native_check_session import NativeCheckSession, wait_loaded


X, Y, Z = 1752, 112, 1112
PIVOT, MOTOR = (X, Y, Z), (X, Y - 1, Z)
ENDS = ((X - 6, Y + 1, Z), (X + 6, Y + 1, Z))
LAMPS = ((X - 6, Y + 3, Z + 2), (X + 6, Y + 3, Z + 2))
ROOM = f'{X - 8} {Y - 3} {Z - 8} {X + 7} {Y + 10} {Z + 7}'
FORCE = f'{X - 8} {Z - 8} {X + 7} {Z + 7}'
CAMERA, TARGET = (X + .5, Y + 1.75, Z + 6.5), (X + .5, Y + 1.5, Z + .5)
AIR = 'minecraft:air'


def setblock(command, pos, state):
    command(f'setblock {xyz(pos)} {state}')


def rig(command):
    command(f'fill {ROOM} minecraft:stone hollow')
    command(f'fill {X - 5} {Y + 1} {Z} {X + 5} {Y + 1} {Z} minecraft:slime_block')
    for pos in ENDS:
        setblock(command, pos, 'minecraft:red_concrete')
    setblock(command, PIVOT, 'create:mechanical_bearing[facing=up]{ScrollValue:2}')
    setblock(command, MOTOR, 'create:creative_motor[facing=up]{ScrollValue:1}')


def light_images(command, step, capture):
    step(4)
    setblock(command, MOTOR, AIR)
    step(4)
    paths = []
    for i, pos in enumerate(LAMPS):
        setblock(command, LAMPS[1 - i], AIR)
        setblock(command, pos, 'minecraft:sea_lantern')
        step(30)
        paths.append(capture('west' if i == 0 else 'east'))
    return paths


def java_run(work):
    host = Original()
    initial = host.call('state', {})
    if initial.get('screen') == 'PauseScreen':
        host.call('input', {'kind': 'escape'})
        initial = host.call('state', {})
    assert initial['ready'] and initial['data_version'] == 3955, initial

    def capture(name):
        result = host.call('capture', {'name': f'{work.name}/{name}.png', 'frames': 24})
        assert result['client']['screen'] == 'playing', result
        return Path(result['path'])

    try:
        host.call('tick', {'frozen': True})
        host.command('gamemode spectator')
        host.command(f'tp @s {xyz(CAMERA)}')
        host.command(f'forceload add {FORCE}')
        host.snapshot([PIVOT], 24)
        rig(host.command)
        host.call('camera', {'position': CAMERA, 'target': TARGET, 'hide_gui': True})
        paths = light_images(host.command, lambda n: host.snapshot([PIVOT], n), capture)
        verify_cargo(host)
        return paths
    finally:
        host.command(f'kill @e[type=create:stationary_contraption,x={X},y={Y + 1},z={Z},distance=..8]')
        host.command(f'fill {ROOM} {AIR}')
        host.command(f'forceload remove {FORCE}')
        host.command('gamemode creative')
        host.call('camera', {'position': initial['position'], 'yaw': initial['yaw'],
                             'pitch': initial['pitch'], 'hide_gui': False})
        host.call('tick', {'frozen': initial['server']['frozen']})
        (work / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')


def verify_cargo(host):
    controller, *ends = host.snapshot((PIVOT, *ENDS), 2)
    running, angle = pose(controller['nbt'])
    assert running and 0 <= angle < 3 and all(b['block'] == AIR for b in ends), (controller, ends)


def native_run(session):
    host = Native(session)
    call = session.call

    def step(n):
        host.command(f'tick step {n}')
        call('wait', n + 4)

    def capture(name):
        path = session.scratch / f'{name}.png'
        call('look-at', *TARGET)
        call('wait', 24)
        call('screenshot', path)
        return path

    with session:
        host.command('gamemode spectator')
        host.command(f'tp @s {xyz(CAMERA)}')
        wait_loaded(call, [PIVOT, *ENDS, *LAMPS])
        host.command('tick freeze')
        rig(host.command)
        call('key', 'f1', 'tap')
        paths = light_images(host.command, step, capture)
        verify_cargo(host)
        return paths


def red_ends(path):
    # The two cargo blocks are red concrete. The room, slime, lights and
    # controller are different colours. Rank each half independently so the
    # check remains valid with different lightmaps and framebuffer scales.
    width, height = 640, 360
    data = subprocess.check_output([
        'ffmpeg', '-v', 'error', '-i', str(path), '-vf', f'scale={width}:{height}',
        '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-threads', '1', 'pipe:1',
    ])
    assert len(data) == width * height * 3, path
    reds = [[], []]
    for y in range(height // 4, height * 3 // 4):
        for x in range(width):
            i = (y * width + x) * 3
            r, g, b = data[i:i+3]
            if r > max(g, b) * 1.5:
                reds[x >= width // 2].append(r)
    return [sorted(side)[len(side) * 3 // 4] if len(side) > 16 else 0 for side in reds]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--java', action='store_true')
    for name in ('game', 'resources', 'ctl', 'create-jar'):
        parser.add_argument('--' + name, type=Path)
    args = parser.parse_args()
    if args.java:
        work = Path(tempfile.mkdtemp(prefix='contraption-cargo-light-java-', dir=ROOT / '.local'))
        print(work, flush=True)
        paths = java_run(work)
    else:
        if not all((args.game, args.resources, args.ctl, args.create_jar)):
            parser.error('Horizon runs require --game, --resources, --ctl and --create-jar')
        session = NativeCheckSession(args.game, args.resources, args.ctl, args.create_jar,
                                     name='contraption-cargo-light-native', world='CargoLight')
        work = session.scratch
        print(work, flush=True)
        try:
            paths = native_run(session)
        finally:
            session.control_temp.cleanup()
            for folder in (session.resources, work / '.horizon-cache', work / 'horizon-mods'):
                shutil.rmtree(folder, ignore_errors=True)
    west, east = [red_ends(path) for path in paths]
    # From the south looking north, west appears on the left.
    passed = west[0] > east[0] + 8 and east[1] > west[1] + 8
    report = {'passed': passed, 'create': PINS['create_revision'],
              'lamp_west': west, 'lamp_east': east, 'images': list(map(str, paths))}
    result = work / 'result.json'
    result.write_text(json.dumps(report, indent=2) + '\n')
    print(result)
    assert passed, report


if __name__ == '__main__':
    main()
