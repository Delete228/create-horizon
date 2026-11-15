#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Compare component-bearing transfers into linked Mechanical Crafters."""

import argparse
import json
from pathlib import Path
import re
import shutil
import tempfile

from bearing_native_checks import Batch
from burner_heat_java_checks import field, items, number
from chain_drive_checks import Original, xyz
from common import PINS, ROOT
from crafter_hopper_checks import inventory, links
from crafter_outlet_checks import craft_state, fed
from funnel_checks import block, click, put, step, text
from native_check_session import NativeCheckSession
import reference_java


X, Y, Z = 2470, 172, 1380
A, B, C = (X, Y, Z), (X + 1, Y, Z), (X, Y + 1, Z)
SINK, FEEDER = (X - 1, Y, Z), (X - 1, Y + 1, Z)
INLET, SOURCE = (X + 1, Y + 1, Z), (X + 1, Y + 2, Z)
AREA = '2467 169 1377 2476 177 1388'
TICKET = '2464 1376 2479 1391'
DROPS = '@e[type=minecraft:item,x=2467,y=169,z=1377,dx=9,dy=8,dz=11]'
PAPER = 'minecraft:paper'
PLANK = 'minecraft:oak_planks'
STICK = 'minecraft:stick'
MARK = 'create_machine_probe'
MARKED = f'{PAPER}[minecraft:custom_data={{{MARK}:31}}]'
PARTS = (A, B, C)


def crafter(facing='south', pointing='up'):
    return f'create:mechanical_crafter[facing={facing},pointing={pointing}]'


def cover(cmd, pos, value):
    cmd(f'data merge block {xyz(pos)} {{Cover:{int(value)}b}}')


def setup(cmd, kind):
    cmd(f'fill {AREA} minecraft:air')
    cmd(f'kill {DROPS}')
    cmd('fill 2467 170 1377 2476 170 1388 minecraft:smooth_stone')
    if kind == 'crafter':
        for pos in (A, C):
            put(cmd, pos, crafter('east'))
        links(cmd, A, C)
        put(cmd, SINK, crafter(pointing='right'))
        put(cmd, FEEDER, crafter(pointing='down'))
        put(cmd, (X - 2, Y + 1, Z), 'create:cogwheel[axis=z]')
        put(cmd, (X - 2, Y + 1, Z - 1), 'create:creative_motor[facing=south]{ScrollValue:128}')
        return

    for pos in PARTS:
        put(cmd, pos, crafter())
    links(cmd, A, B, C)
    cover(cmd, B, True)
    if kind == 'chute':
        put(cmd, INLET, 'create:chute[facing=down,shape=normal,waterlogged=false]')
        put(cmd, SOURCE, 'minecraft:barrel')
        cmd(f'item replace block {xyz(SOURCE)} container.0 with {MARKED} 3')
    elif kind == 'funnel':
        put(cmd, INLET, 'create:andesite_funnel[facing=up,extracting=false,waterlogged=false]')
        cmd(f'fill {X-1} {Y} {Z+2} {X+3} {Y} {Z+3} minecraft:smooth_stone')
    else:
        raise ValueError(kind)


def member(raw):
    return {'items': inventory(field(raw, 'Inventory')), 'marked': marked(raw)}


def marked(raw):
    return f'{MARK}:31' in re.sub(r'\s+', '', raw)


def remaining(raw):
    if PAPER not in raw:
        return 0
    assert marked(raw), raw
    return int(number({'nbt': raw}, 'count'))


def machine_snapshot(raws, expected_fill):
    parts, source = raws[:3], raws[3]
    assert [member(raw) for raw in parts] == [
        {'items': {PAPER: 1} if filled else {}, 'marked': filled}
        for filled in expected_fill
    ], raws
    expected_remaining = 3 - sum(expected_fill)
    assert remaining(source) == expected_remaining, source
    return {'parts': [member(raw) for raw in parts], 'remaining': expected_remaining}


def crafter_snapshot(raws, count):
    receivers = [member(raw) for raw in raws[:2]]
    assert receivers == [{'items': {STICK: 1}, 'marked': False}] * 2, raws
    sink = craft_state(raws[2])
    assert sink == {'phase': ['INSERTING', 0], 'group': {STICK: count}}, raws
    return {'parts': receivers, 'sink': sink}


def clear_member(cmd, pos):
    cmd(f'data merge block {xyz(pos)} {{Inventory:{{Size:1,Items:[]}}}}')


def run_cases(cmd, scan, use, read):
    setup(cmd, 'chute')
    scan(75, *PARTS, INLET)
    cover(cmd, B, False)
    scan(80, *PARTS, INLET)

    setup(cmd, 'funnel')
    scan(20)
    use('funnel', INLET, 'up', (X + 1.5, Y + 1, Z + 2.5),
        (X + 1.5, Y + 1.48, Z + .5), f'{MARKED} 3')
    scan(0, *PARTS)
    read('data get entity @s SelectedItem')

    setup(cmd, 'crafter')
    scan(20)
    for pos in (FEEDER, SINK):
        x, y, z = pos
        use(f'crafter-{y}', pos, 'south', (x + .5, Y - 1, z + 3.25),
            (x + .5, y + .5, z + .5), PLANK)
        scan(0, pos)
    scan(75, A, C, SINK)
    clear_member(cmd, C)
    scan(40, A, C, SINK)


def check_cases(observations):
    rows = iter(observations)

    def chute(expected):
        parts = [next(rows) for _ in PARTS]
        return machine_snapshot([*parts, field(next(rows), 'Item')], expected)

    before = chute((True, False, True))
    after = chute((True, True, True))
    funnel = machine_snapshot([next(rows) for _ in range(4)], (True, False, True))
    for pos in (FEEDER, SINK):
        fed('crafter', pos, next(rows))
    crafts_before = crafter_snapshot([next(rows) for _ in range(3)], 2)
    crafts_after = crafter_snapshot([next(rows) for _ in range(3)], 1)
    assert next(rows, None) is None, observations
    return {'chute': {'before': before, 'after': after}, 'funnel': funnel,
            'crafter': {'before': crafts_before, 'after': crafts_after}}


def java_run(work):
    host = Original()
    manifest = json.loads((reference_java.BASE / 'manifest.json').read_text())
    assert manifest['create_sha256'] == reference_java.CREATE_SHA256
    initial = host.call('state', {})
    if initial.get('screen') == 'PauseScreen':
        host.call('input', {'kind': 'escape'})
        initial = host.call('state', {})
    assert initial['ready'] and initial['data_version'] == 3955, initial
    cmd = host.command
    observations = []

    def scan(ticks, *positions):
        if not positions:
            step(host, ticks, A)
        else:
            rows = step(host, ticks, *positions) if ticks else (block(host, p) for p in positions)
            observations.extend(row['nbt'] for row in rows)

    host.call('tick', {'frozen': True})
    try:
        cmd(f'forceload add {TICKET}')
        cmd(f'tp @s {X}.5 {Y+3} {Z+4}.5')
        host.snapshot([A], 20)
        cmd('gamemode survival')
        run_cases(cmd, scan, lambda *args: click(host, work, *args),
                  lambda query: observations.append(text(host, query)))
        return check_cases(observations)
    finally:
        cmd('gamemode creative')
        cmd('item replace entity @s weapon.mainhand with minecraft:air')
        cmd(f'fill {AREA} minecraft:air')
        cmd(f'kill {DROPS}')
        cmd(f'forceload remove {TICKET}')
        host.call('camera', {'position': initial['position'], 'yaw': initial['yaw'], 'pitch': initial['pitch']})
        host.call('tick', {'frozen': initial['server']['frozen']})
        (work / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')


def native_run(session):
    batch = Batch()
    batch.load((X, Y, Z + 4))
    batch.command('gamemode survival')

    def scan(ticks, *positions):
        if ticks:
            batch.tick(ticks)
        for pos in positions:
            batch.data(pos)

    def use(_name, pos, face, feet, _aim, item):
        batch.command(f'tp @s {xyz(feet)}')
        batch.command(f'item replace entity @s weapon.mainhand with {item}')
        batch.ops.append(dict(op='use_block', pos=pos, face={'up': 1, 'south': 3}[face],
                              sequence=len(batch.ops)))

    run_cases(batch.command, scan, use, lambda query: batch.command(query, True))
    return check_cases(batch.run(session, 'crafter-machine-inputs'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--java', action='store_true')
    for flag in ('game', 'resources', 'ctl', 'reference', 'create-jar'):
        parser.add_argument('--' + flag, type=Path)
    args = parser.parse_args()
    if args.java:
        work = Path(tempfile.mkdtemp(prefix='crafter-machine-java-', dir=ROOT / '.local'))
        print(work, flush=True)
        result = java_run(work)
    else:
        if not all((args.game, args.resources, args.ctl, args.reference)):
            parser.error('Horizon requires --game, --resources, --ctl and --reference')
        reference = json.loads(args.reference.read_text())
        assert reference['create'] == PINS['create_revision'] and reference['passed'], reference
        session = NativeCheckSession(args.game, args.resources, args.ctl, args.create_jar,
                                     name='crafter-machine-native', graphics=False,
                                     world='CreateCrafterMachine')
        work = session.scratch
        print(work, flush=True)
        try:
            result = native_run(session)
        finally:
            session.control_temp.cleanup()
            for folder in (session.resources, work / '.horizon-cache', work / 'horizon-mods'):
                shutil.rmtree(folder, ignore_errors=True)
        assert result == reference['cases'], (result, reference)
    path = work / 'result.json'
    path.write_text(json.dumps(dict(passed=True, create=PINS['create_revision'], cases=result), indent=2) + '\n')
    print(path)


if __name__ == '__main__':
    main()
