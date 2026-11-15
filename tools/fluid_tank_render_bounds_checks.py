#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Compare visible water in tank windows when the controller is outside the view."""

import argparse
from itertools import batched
import json
from pathlib import Path
import shutil
import tempfile

from PIL import Image

from burner_heat_java_checks import number
from chain_drive_checks import Native, Original, xyz
from common import PINS, ROOT
from fluid_pump_java_checks import seed
from funnel_checks import block
from native_check_session import NativeCheckSession, wait_loaded


X, Y, Z = 2814, 174, 1677
LOAD = '2800 1664 2831 1695'
AREA = '2812 171 1674 2821 182 1692'
FOV = 30
CASES = {
    'top': ((X, Y, Z), 1, 6, 46_000,
            (X+.5, Y+5.29-1.62, Z+2.2), (X+.5, Y+5.29, Z+1)),
    'cross_chunk': ((X, Y, Z+8), 3, 4, 270_000,
                    (X+1.5, Y+3.32-1.62, Z+12), (X+1.5, Y+3.32, Z+11)),
}


def settle(host, ticks):
    if isinstance(host, Native):
        host.session.call('wait', ticks)
    else:
        host.call('observe_ticks', {'positions': [case[0] for case in CASES.values()], 'ticks': ticks})


def setup(host):
    host.command(f'fill {AREA} minecraft:air')
    for (x, y, z), width, height, _, _, _ in CASES.values():
        end = x+width-1, y+height-1, z+width-1
        host.command(f'fill {x} {y} {z} {xyz(end)} create:fluid_tank')
        host.command(f'fill {x} {y} {z-1} {end[0]} {end[1]} {z-1} minecraft:gray_concrete')
    settle(host, 24)
    for pos, width, height, _, _, _ in CASES.values():
        controller = block(host, pos)
        assert (number(controller, 'Size'), number(controller, 'Height')) == (width, height), controller


def capture(host, work, prefix):
    images = {}
    for name, (pos, _, _, volume, feet, target) in CASES.items():
        if isinstance(host, Native):
            host.command('tp @s ' + xyz(feet))
            host.session.call('look-at', *target)
        else:
            host.call('camera', {'position': feet, 'target': target, 'fov': FOV, 'hide_gui': True})
        files = []
        for state in ('empty', 'full'):
            if state == 'full':
                host.command(seed(pos, 'water', volume))
            settle(host, 24)
            path = work / f'{prefix}-{name}-{state}.png'
            if isinstance(host, Native):
                host.session.call('screenshot', path)
            else:
                frame = host.call('capture', {'name': f'{work.name}/{path.name}', 'frames': 12})
                shutil.copy2(frame['path'], path)
            files.append(path)
        images[name] = water_signal(*files)
    return images


def water_signal(empty, full):
    with Image.open(empty) as before, Image.open(full) as after:
        assert before.size == after.size
        w, h = after.size
        crop = (w//2-h//8, h//2-h//8, w//2+h//8, h//2+h//8)
        prior = batched(before.convert('RGB').crop(crop).tobytes(), 3)
        later = batched(after.convert('RGB').crop(crop).tobytes(), 3)
        changed = sum(b > r + 16 and b > g + 10 and (b-r)-(bb-br) > 16
                      for (br, _, bb), (r, g, b) in zip(prior, later, strict=True))
    return changed / ((crop[2]-crop[0]) * (crop[3]-crop[1]))


def java_run(work):
    host = Original()
    initial = host.call('state', {})
    assert initial['ready'] and initial['data_version'] == 3955, initial
    mode = next(mode for mode in ('creative', 'spectator', 'survival', 'adventure')
                if any('Test passed' in line for line in
                       host.command(f'execute if entity @s[gamemode={mode}]')['messages']))
    try:
        host.command('gamemode spectator')
        host.call('tick', {'frozen': True})
        host.command(f'forceload add {LOAD}')
        host.call('tick', {'step': 20})
        setup(host)
        return capture(host, work, 'java')
    finally:
        host.command(f'fill {AREA} minecraft:air')
        host.command(f'forceload remove {LOAD}')
        host.command(f'gamemode {mode}')
        host.call('camera', {key: initial[key] for key in ('position', 'yaw', 'pitch', 'fov')}
                  | {'hide_gui': False})
        host.call('tick', {'frozen': initial['server']['frozen']})
        (work / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')


def native_run(session):
    host = Native(session)
    with session:
        host.command('gamemode spectator')
        host.command(f'tp @s {X}.5 {Y+5} {Z+4}.5')
        wait_loaded(session.call, (case[0] for case in CASES.values()))
        session.call('options-set', 'fov', FOV)
        session.call('key', 'f1', 'tap')
        setup(host)
        return capture(host, session.scratch, 'native')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--java', action='store_true')
    for flag in ('game', 'resources', 'ctl', 'create-jar', 'reference'):
        parser.add_argument('--'+flag, type=Path)
    args = parser.parse_args()
    if args.java:
        work = Path(tempfile.mkdtemp(prefix='tank-bounds-java-', dir=ROOT / '.local'))
        print(work, flush=True)
        signal = java_run(work)
    else:
        if not all((args.game, args.resources, args.ctl, args.create_jar, args.reference)):
            parser.error('Horizon requires --game, --resources, --ctl, --create-jar and --reference')
        session = NativeCheckSession(args.game, args.resources, args.ctl, args.create_jar,
                                     name='tank-bounds-native', world='CreateTankBounds')
        work = session.scratch
        print(work, flush=True)
        try:
            signal = native_run(session)
        finally:
            for folder in (session.resources, work / '.horizon-cache', work / 'horizon-mods'):
                shutil.rmtree(folder, ignore_errors=True)

    visible = {name: value > .1 for name, value in signal.items()}
    (work / 'observed.json').write_text(json.dumps(signal, indent=2) + '\n')
    assert all(visible.values()), signal
    if not args.java:
        expected = json.loads(args.reference.read_text())
        assert expected['passed'] and expected['create'] == PINS['create_revision']
        assert visible == expected['visible'], (visible, expected)
    result = work / 'result.json'
    result.write_text(json.dumps(dict(passed=True, create=PINS['create_revision'],
                                     visible=visible, signal=signal), indent=2) + '\n')
    print(result)


if __name__ == '__main__':
    main()
