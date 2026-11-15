#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Check the original fluid valve pointer's slope from opposing faces."""

import argparse
import json
import math
from pathlib import Path
import shutil
import tempfile

from PIL import Image

from chain_drive_checks import Native, Original, xyz
from common import PINS, ROOT
from fluid_valve_java_checks import VALVE
from funnel_checks import put
from native_check_session import NativeCheckSession, wait_loaded


X, Y, Z = 2725, 177, 1544
AREA = '2718 175 1538 2732 182 1570'
LOAD = '2704 1536 2735 1583'
CASES = {'east': (1,0), 'west': (-1,0), 'north': (0,-1)}


def position(name):
    return (X,Y,Z+8*list(CASES).index(name))


def valve(name):
    return VALVE+f'[facing={name},axis_along_first=true,enabled=false,waterlogged=false]'


def setup(command):
    command(f'fill {AREA} minecraft:air')
    command('fill 2718 175 1538 2732 175 1570 minecraft:smooth_stone')
    for name in CASES:
        put(command, position(name), valve(name))


def angles(host, work, native):
    output = {}
    for name, (dx,dz) in CASES.items():
        x, y, z = position(name)
        feet = (x+.5+dx*3.1, y-1, z+.5+dz*3.1)
        target = (x+.5, y+.5, z+.5)
        if native:
            host.command('tp @s '+xyz(feet))
            host.session.call('look-at', *target)
        else:
            host.call('camera', {'position': feet, 'target': target, 'hide_gui': True})
        paths = []
        for label, value in (('flat', 0), ('half', .5)):
            path = work / f'{name}-{label}.png'
            # Recreate the block entity so both clients initialize the visual
            # from this value instead of keeping a settled interpolation.
            put(host.command, position(name), 'minecraft:air')
            if native:
                host.session.call('wait', 3)
            else:
                host.call('observe_ticks', {'positions': [position(name)], 'ticks': 3})
            put(host.command, position(name), valve(name)+f'{{Pointer:{{Value:{value}f,Target:0f,Speed:0f}}}}')
            if native:
                host.session.call('wait', 12)
                host.session.call('screenshot', path)
            else:
                host.call('observe_ticks', {'positions': [position(name)], 'ticks': 4})
                capture = host.call('capture', {'name': f'{work.name}/{path.name}', 'frames': 16})
                shutil.copy2(capture['path'], path)
            paths.append(path)
        output[name] = slope(*paths)
    return output


def slope(before, after):
    with Image.open(before) as first, Image.open(after) as second:
        a, b = first.convert('RGB'), second.convert('RGB')
    assert a.size == b.size
    cx, cy = a.width//2, a.height//2
    radius = int(a.height*.105)
    pixels = []
    for y in range(cy-radius, cy+radius):
        for x in range(cx-radius, cx+radius):
            earlier, later = a.getpixel((x,y)), b.getpixel((x,y))
            if max(later) < 106 and sum(earlier)-sum(later) > 82:
                pixels.append((x,y))
    assert len(pixels) > 10, (before, after, len(pixels))
    px = sum(x for x,_ in pixels)/len(pixels)
    py = sum(y for _,y in pixels)/len(pixels)
    dx = [x-px for x,_ in pixels]
    dy = [y-py for _,y in pixels]
    correlation = sum(x*y for x,y in zip(dx,dy,strict=True)) / math.sqrt(sum(x*x for x in dx)*sum(y*y for y in dy))
    assert abs(correlation) > .45, (before, after, correlation)
    return dict(samples=len(pixels), slope=round(correlation,6), sign=1 if correlation>0 else -1)


def java_run(work):
    host = Original()
    initial = host.call('state', {})
    assert initial['ready'] and initial['data_version'] == 3955, initial
    host.call('tick', {'frozen': True})
    try:
        host.command(f'forceload add {LOAD}')
        host.call('observe_ticks', {'positions': list(map(position, CASES)), 'ticks': 20})
        setup(host.command)
        host.call('observe_ticks', {'positions': list(map(position, CASES)), 'ticks': 16})
        return angles(host, work, False)
    finally:
        host.command(f'fill {AREA} minecraft:air')
        host.command(f'forceload remove {LOAD}')
        host.call('camera', {**{key: initial[key] for key in ('position','yaw','pitch')}, 'hide_gui': False})
        host.call('tick', {'frozen': initial['server']['frozen']})
        (work / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')


def native_run(session):
    host = Native(session)
    with session:
        host.command(f'tp @s {X}.5 {Y+2} {Z+8}.5')
        wait_loaded(session.call, list(map(position, CASES)))
        setup(host.command)
        session.call('wait', 16)
        session.call('key', 'f1', 'tap')
        host.command('tick freeze')
        return angles(host, session.scratch, True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--java', action='store_true')
    for flag in ('game', 'resources', 'ctl', 'create-jar', 'reference'):
        parser.add_argument('--'+flag, type=Path)
    args = parser.parse_args()
    if args.java:
        work = Path(tempfile.mkdtemp(prefix='valve-pose-java-', dir=ROOT / '.local'))
        print(work, flush=True)
        views = java_run(work)
    else:
        if not all((args.game, args.resources, args.ctl, args.create_jar, args.reference)):
            parser.error('Horizon requires --game, --resources, --ctl, --create-jar and --reference')
        session = NativeCheckSession(args.game, args.resources, args.ctl, args.create_jar,
                                     name='valve-pose-native', world='CreateValvePose', size=(1440,900))
        work = session.scratch
        print(work, flush=True)
        try:
            views = native_run(session)
        finally:
            session.control_temp.cleanup()
            for folder in (session.resources, work / '.horizon-cache', work / 'horizon-mods'):
                shutil.rmtree(folder, ignore_errors=True)
    (work / 'observed.json').write_text(json.dumps(views, indent=2) + '\n')
    if not args.java:
        expected = json.loads(args.reference.read_text())
        assert expected['passed'] and expected['create'] == PINS['create_revision']
        for name, view in views.items():
            assert view['sign'] == expected['views'][name]['sign'], (name, view, expected['views'][name])
    result = work / 'result.json'
    result.write_text(json.dumps(dict(passed=True, create=PINS['create_revision'], views=views), indent=2) + '\n')
    print(result)


if __name__ == '__main__':
    main()
