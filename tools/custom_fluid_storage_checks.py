#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Compare closed Honey and Chocolate pump routes, with native cold restart."""

import argparse
import json
from pathlib import Path
import re
import shutil
from statistics import median
import tempfile
import time

from bearing_native_checks import Batch
from burner_heat_java_checks import field, number
from chain_drive_checks import Native, Original, xyz
from common import PINS, ROOT
from fluid_pump_java_checks import PIPE, PUMP, TANK
from funnel_checks import put
from native_check_session import NativeCheckSession, wait_loaded


X, Y, Z = 2520, 166, 1254
LOAD = '2512 1248 2527 1279'
AREA = '2516 164 1251 2524 169 1277'
TICKS = 70
CASES = (
    ('honey-direct', 'create:honey', 0, None),
    ('chocolate-pipe', 'create:chocolate', 1, None),
    ('different-fluid', 'create:honey', 0, ('create:chocolate', 500)),
    ('small-room', 'create:chocolate', 0, ('create:chocolate', 7997)),
)
DISPLAY = (X, Y, Z)
CAMERA = (X+0.5, Y-1.0, Z+3.3)
TARGET = (X+0.5, Y+0.62, Z+0.5)


def lane(i):
    count = CASES[i][2]
    z = Z+6*i
    return tuple((x, Y, z) for x in range(X-1, X+count+2))


POSITIONS = [pos for i in range(len(CASES)) for pos in lane(i)]


def set_fluid(cmd, pos, fluid, amount):
    cmd(f'data merge block {xyz(pos)} {{TankContent:{{Fluid:{{id:"{fluid}",amount:{amount}}}}}}}')


def prepare(cmd):
    cmd(f'fill {AREA} minecraft:air')
    for i, (_, fluid, _, initial) in enumerate(CASES):
        source, pump, *outlet = lane(i)
        target = outlet[-1]
        put(cmd, source, TANK)
        put(cmd, target, TANK)
        if initial:
            set_fluid(cmd, target, *initial)
        for pos in outlet[:-1]:
            put(cmd, pos, PIPE+'[east=true,west=true,waterlogged=false]')
        put(cmd, pump, PUMP+'[facing=east,waterlogged=false]')
        put(cmd, (X, Y-1, pump[2]), 'create:cogwheel[axis=x]')
        set_fluid(cmd, source, fluid, 3000)


def activate(cmd):
    for i in range(len(CASES)):
        z = lane(i)[0][2]
        put(cmd, (X+1, Y-1, z), 'create:creative_motor[facing=west]{ScrollValue:32}')


def fluid(nbt):
    identifier = re.search(r'\bid:\s*"(create:(?:honey|chocolate))"', nbt)
    return [identifier[1], int(number({'nbt': nbt}, 'amount'))] if identifier else None


def measure(row):
    def content(block):
        return fluid(field(block, 'TankContent'))

    def face(block, side):
        fields = field(block, side) if side + ':' in block else '{}'
        return fluid(field(field(fields, 'Flow'), 'Fluid')) if 'Flow:' in fields else None

    return dict(source=content(row[0]), target=content(row[-1]),
                faces=[[face(block, side) for side in ('west', 'east')] for block in row[1:-1]])


def observations(rows):
    traces = {name: [] for name, *_ in CASES}
    for row in rows:
        offset = 0
        for i, (name, *_) in enumerate(CASES):
            end = offset+len(lane(i))
            traces[name].append(measure(row[offset:end]))
            offset = end
        assert len(row) == offset
    return traces


def java_run(work):
    host = Original()
    initial = host.call('state', {})
    assert initial['ready'] and initial['data_version'] == 3955, initial
    host.call('tick', {'frozen': True})
    try:
        host.command(f'forceload add {LOAD}')
        host.call('observe_ticks', {'positions': POSITIONS, 'ticks': 14})
        prepare(host.command)
        host.call('observe_ticks', {'positions': POSITIONS, 'ticks': 40})
        commands = []
        activate(commands.append)
        rows = host.call('observe_ticks', {'positions': POSITIONS, 'ticks': TICKS,
                                           'commands': commands})['samples']
        return observations([[block['nbt'] for block in row['blocks']] for row in rows])
    finally:
        host.command(f'fill {AREA} minecraft:air')
        host.command(f'forceload remove {LOAD}')
        host.call('tick', {'frozen': initial['server']['frozen']})
        (work / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')


def observe(batch):
    for pos in POSITIONS:
        batch.data(pos)


def native_run(session):
    batch = Batch()
    batch.load((X, Y+2, Z+9))
    prepare(batch.command)
    batch.tick(40)
    activate(batch.command)
    for _ in range(TICKS):
        batch.tick()
        observe(batch)
    width = len(POSITIONS)
    raw = batch.run(session, 'closed-custom-fluids')
    assert len(raw) == TICKS*width
    traces = observations([raw[i:i+width] for i in range(0, len(raw), width)])

    batch = Batch()
    batch.load((X, Y+2, Z+9))
    batch.tick(28)
    observe(batch)
    cold = observations([batch.run(session, 'after-cold-custom-fluids')])
    for name, frames in traces.items():
        if name in ('honey-direct', 'chocolate-pipe'):
            assert cold[name][0]['target'][1] > frames[-1]['target'][1]
    return traces, cold


def verify(traces):
    for name, kind, _, initial in CASES:
        supply = 3000+(initial[1] if initial else 0)
        for row in traces[name]:
            assert row['source'][0] == kind, (name, row)
            assert row['source'][1]+(row['target'][1] if row['target'] else 0) == supply, (name, row)
        final = traces[name][-1]
        assert all(port == [kind, 1] for faces in final['faces'] for port in faces), (name, final)
        if name == 'different-fluid':
            assert final['source'][1] == 3000 and final['target'] == list(initial), final
        elif name == 'small-room':
            assert final['source'][1] == 2997 and final['target'] == [kind, 8000], final
        else:
            assert final['target'][0] == kind and final['target'][1] > 0, final


def visual(host, work):
    from PIL import Image

    native = isinstance(host, Native)
    cmd = host.command
    cmd('gamemode creative')
    cmd(f'fill {AREA} minecraft:air')
    put(cmd, (X, Y-2, Z+3), 'minecraft:smooth_stone')
    put(cmd, DISPLAY, TANK+'[shape=window]')
    cmd('time set 6000')
    if native:
        cmd(f'tp @s {xyz(CAMERA)}')
        host.session.call('look-at', *TARGET)
        host.session.call('key', 'f1', 'tap')
    else:
        host.call('camera', dict(position=CAMERA, target=TARGET, hide_gui=True))
    images = {}
    for kind in ('empty', 'honey', 'chocolate'):
        if kind != 'empty':
            set_fluid(cmd, DISPLAY, f'create:{kind}', 7600)
        path = work / f'{kind}.png'
        if native:
            host.session.call('wait', 35)
            host.session.call('screenshot', path)
        else:
            time.sleep(1.8)
            capture = host.call('capture', dict(name=f'{work.name}/{kind}.png', frames=14))
            shutil.copy2(capture['path'], path)
        with Image.open(path) as image:
            x = image.width//2
            patch = image.convert('RGB').crop((x-10, int(image.height*0.49),
                                                x+10, int(image.height*0.68)))
            images[kind] = [patch.getpixel((px, py))
                            for py in range(patch.height) for px in range(patch.width)]
    changed = {}
    ratios = {}
    for kind in ('honey', 'chocolate'):
        rendered = [b for a, b in zip(images['empty'], images[kind], strict=True)
                    if sum(abs(c-d) for c, d in zip(a, b)) >= 20]
        changed[kind] = len(rendered)
        warm = [blue/red for red, green, blue in rendered if red > max(green, blue)]
        assert len(warm) >= 100, (kind, changed)
        ratios[kind] = median(warm)
    changed['honey-to-chocolate'] = sum(sum(abs(c-d) for c, d in zip(a, b)) >= 20
                                       for a, b in zip(images['honey'], images['chocolate'], strict=True))
    assert changed['honey-to-chocolate'] >= 100, changed
    return {'changed_pixels': changed, 'blue_red_ratio': ratios}


def visual_run(session, work):
    if session:
        with session:
            session.call('command', f'tp @s {xyz(CAMERA)}')
            wait_loaded(session.call, (DISPLAY,))
            return visual(Native(session), work)
    host = Original()
    initial = host.call('state', {})
    try:
        host.call('tick', {'frozen': False})
        host.command(f'forceload add {LOAD}')
        time.sleep(0.8)
        return visual(host, work)
    finally:
        host.command(f'fill {AREA} minecraft:air')
        host.command(f'forceload remove {LOAD}')
        host.call('camera', dict(position=initial['position'], yaw=initial['yaw'], pitch=initial['pitch']))
        host.call('tick', {'frozen': initial['server']['frozen']})
        (work / 'visual-transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--java', action='store_true')
    parser.add_argument('--visual', action='store_true', help='Also capture an empty tank and both liquids')
    for flag in ('game', 'resources', 'ctl', 'create-jar', 'reference'):
        parser.add_argument('--' + flag, type=Path)
    args = parser.parse_args()
    cold = None
    rendered = None
    if args.java:
        work = Path(tempfile.mkdtemp(prefix='custom-fluid-java-', dir=ROOT / '.local'))
        print(work, flush=True)
        traces = java_run(work)
        if args.visual:
            rendered = visual_run(None, work)
    else:
        if not all((args.game, args.resources, args.ctl, args.reference)):
            parser.error('Horizon requires --game, --resources, --ctl and --reference')
        session = NativeCheckSession(args.game, args.resources, args.ctl, args.create_jar,
                                     name='custom-fluid-native', world='CreateCustomFluid')
        work = session.scratch
        print(work, flush=True)
        try:
            traces, cold = native_run(session)
            if args.visual:
                rendered = visual_run(session, work)
        finally:
            session.control_temp.cleanup()
            for folder in (session.resources, work / '.horizon-cache', work / 'horizon-mods'):
                shutil.rmtree(folder, ignore_errors=True)
    (work / 'observed.json').write_text(json.dumps(traces, indent=2) + '\n')
    verify(traces)
    if cold:
        verify(cold)
    if not args.java:
        reference = json.loads(args.reference.read_text())
        assert reference['passed'] and reference['create'] == PINS['create_revision']
        if args.visual and args.create_jar:
            expected = reference['rendered']['blue_red_ratio']
            for kind, ratio in rendered['blue_red_ratio'].items():
                assert abs(ratio-expected[kind]) < 0.07, (kind, ratio, expected[kind])
        for name, rows in traces.items():
            for tick, (got, want) in enumerate(zip(rows, reference['traces'][name], strict=True), 1):
                assert got == want, (name, tick, got, want)
    result = work / 'result.json'
    result.write_text(json.dumps(dict(passed=True, create=PINS['create_revision'], traces=traces,
                                      cold=cold, rendered=rendered), indent=2) + '\n')
    print(result)


if __name__ == '__main__':
    main()
