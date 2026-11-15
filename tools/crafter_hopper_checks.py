#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Compare real vanilla Hopper transfers into Java Create's linked Crafters."""

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
from crafter_java_checks import phase
from funnel_checks import block, put, step
from native_check_session import NativeCheckSession
import reference_java


X, Y, Z = 2469, 172, 1364
A, B, C = (X, Y, Z), (X + 1, Y, Z), (X, Y + 1, Z)
INLET, BELOW = (X + 2, Y, Z), (X, Y - 1, Z)
LOCK = (X + 3, Y, Z)
RECIPE_INLET, RECIPE_LOCK = (X - 1, Y, Z), (X - 2, Y, Z)
OUTPUT = (X + 1, Y, Z)
TICKET = '2464 1360 2479 1375'
AREA = '2466 169 1361 2475 177 1370'
OBSERVED = (A, B, C, INLET, BELOW)
PAPER = 'minecraft:paper'
MARK = 'create_hopper_probe'
MARKED = f'{PAPER}[minecraft:custom_data={{{MARK}:11}}]'
PLANK = 'minecraft:oak_planks'
CRAFT = 'create:mechanical_crafter[facing=south,pointing={}]'


def links(cmd, root, *members):
    # The real wrench path and the canonical offsets are covered separately
    # by crafter_link_checks. Here the transfer begins with authored links.
    def set_data(pos, controller, offsets):
        data = ','.join(f'{{X:{x},Y:{y},Z:{z}}}' for x, y, z in offsets)
        cmd(f'data merge block {xyz(pos)} '
            f'{{ConnectedInput:{{Controller:{int(controller)}b,Data:[{data}]}}}}')

    def delta(pos, origin):
        return tuple(p - r for p, r in zip(pos, origin, strict=True))

    set_data(root, True, [(0, 0, 0), *(delta(pos, root) for pos in members)])
    for pos in members:
        set_data(pos, False, [delta(root, pos)])


def setup(cmd):
    cmd(f'fill {AREA} minecraft:air')
    cmd('fill 2466 169 1361 2475 169 1370 minecraft:smooth_stone')
    for pos in (A, B, C):
        put(cmd, pos, CRAFT.format('up'))
    links(cmd, A, B, C)
    cmd(f'data merge block {xyz(C)} {{Cover:1b}}')
    cmd(f'data merge block {xyz(B)} '
        '{Inventory:{Size:1,Items:[{Slot:0,id:"minecraft:cobblestone",count:1}]}}')
    put(cmd, LOCK, 'minecraft:redstone_block')
    put(cmd, INLET, 'minecraft:hopper[facing=west]')
    put(cmd, BELOW, 'minecraft:hopper[facing=down]')
    cmd(f'item replace block {xyz(INLET)} container.0 with {MARKED} 3')


def set_recipe(cmd):
    cmd(f'fill {AREA} minecraft:air')
    put(cmd, A, CRAFT.format('right'))
    put(cmd, C, CRAFT.format('down'))
    links(cmd, A, C)
    put(cmd, OUTPUT, 'minecraft:barrel')
    put(cmd, (X - 1, Y + 1, Z), 'create:cogwheel[axis=z]')
    put(cmd, (X - 1, Y + 1, Z - 1), 'create:creative_motor[facing=south]{ScrollValue:128}')
    put(cmd, RECIPE_LOCK, 'minecraft:redstone_block')
    put(cmd, RECIPE_INLET, 'minecraft:hopper[facing=east]')
    cmd(f'item replace block {xyz(RECIPE_INLET)} container.0 with {PLANK} 2')


def inventory(raw):
    return items(raw, 'Items') if re.search(r'\bItems\s*:', raw) else {}


def observe(raws, cooldown=True):
    a, b, c, source, below = raws
    row = {
        'parts': [inventory(field(raw, 'Inventory')) for raw in (a, b, c)],
        'markers': [f'{MARK}:11' in raw.replace(' ', '') for raw in (a, b, c)],
        'source': inventory(source),
        'below': inventory(below),
    }
    if cooldown:
        row['cooldown'] = int(number({'nbt': source}, 'TransferCooldown'))
    return row


def observe_recipe(raws):
    output, source, sink = raws
    assert inventory(output) == {'minecraft:stick': 4}, output
    assert not inventory(source), source
    assert phase({'nbt': sink}) == ['IDLE', 0], sink
    return {'output': inventory(output), 'source': inventory(source)}


def expected(a, c, left, cooldown=None):
    row = {'parts': [{PAPER: 1} if a else {}, {'minecraft:cobblestone': 1},
                     {PAPER: 1} if c else {}],
           'markers': [a, False, c], 'source': {PAPER: left} if left else {}, 'below': {}}
    if cooldown is not None:
        row['cooldown'] = cooldown
    return row


def busy(cmd):
    cmd(f'data merge block {xyz(A)} {{Inventory:{{Size:1,Items:[]}}}}')
    cmd(f'data merge block {xyz(C)} {{Phase:"ACCEPTING",Inventory:{{Size:1,Items:[]}}}}')


def java_run(work):
    host = Original()
    manifest = json.loads((reference_java.BASE / 'manifest.json').read_text())
    assert manifest['create_sha256'] == reference_java.CREATE_SHA256
    initial = host.call('state', {})
    if initial.get('screen') == 'PauseScreen':
        host.call('input', {'kind': 'escape'})
        initial = host.call('state', {})
    assert initial['ready'] and initial['data_version'] == 3955, initial
    host.call('tick', {'frozen': True})
    cmd = host.command

    def scan(ticks, *positions):
        return [row['nbt'] for row in step(host, ticks, *positions)]

    try:
        cmd(f'forceload add {TICKET}')
        cmd(f'tp @s {X}.5 {Y+3} {Z+4}.5')
        host.snapshot([A], 20)
        setup(cmd)
        warm = observe(scan(80, *OBSERVED))
        assert warm == expected(False, False, 3, 0), warm
        put(cmd, LOCK, 'minecraft:air')
        first = observe(scan(1, *OBSERVED))
        held = observe(scan(7, *OBSERVED))
        put(cmd, LOCK, 'minecraft:redstone_block')
        scan(3, *OBSERVED)
        cmd(f'data merge block {xyz(C)} {{Cover:0b}}')
        put(cmd, LOCK, 'minecraft:air')
        upper = observe(scan(1, *OBSERVED))
        busy(cmd)
        last = observe(scan(8, *OBSERVED))
        set_recipe(cmd)
        scan(20, OUTPUT, RECIPE_INLET, A)
        put(cmd, RECIPE_LOCK, 'minecraft:air')
        recipe = observe_recipe(scan(65, OUTPUT, RECIPE_INLET, A))
        return verify(first, held, upper, last, recipe)
    finally:
        cmd(f'fill {AREA} minecraft:air')
        cmd(f'forceload remove {TICKET}')
        host.call('camera', {'position': initial['position'], 'yaw': initial['yaw'], 'pitch': initial['pitch']})
        host.call('tick', {'frozen': initial['server']['frozen']})
        (work / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')


def verify(first, held, upper, last, recipe):
    assert first == expected(True, False, 2, 8), first
    assert held == expected(True, False, 2, 1), held
    assert upper == expected(True, True, 1, 8), upper
    assert last == expected(True, False, 0, 8), last
    return {'first': first, 'held': held, 'upper': upper, 'busy': last, 'recipe': recipe}


def native_run(session):
    def scan(batch, ticks, *positions):
        if ticks:
            batch.tick(ticks)
        for pos in positions:
            batch.data(pos)

    batch = Batch()
    batch.load((X, Y, Z + 4))
    setup(batch.command)
    scan(batch, 80, *OBSERVED)
    batch.put(LOCK, 'minecraft:air')
    scan(batch, 1, *OBSERVED)
    scan(batch, 7, *OBSERVED)
    batch.put(LOCK, 'minecraft:redstone_block')
    batch.tick(3)
    rows = batch.run(session, 'linked-hopper-first')
    warm, first, held = (observe(rows[i:i+5]) for i in (0, 5, 10))
    assert warm == expected(False, False, 3, 0), warm

    batch = Batch()
    batch.load((X, Y, Z + 4))
    scan(batch, 4, *OBSERVED)
    batch.command(f'data merge block {xyz(C)} {{Cover:0b}}')
    batch.put(LOCK, 'minecraft:air')
    scan(batch, 1, *OBSERVED)
    busy(batch.command)
    scan(batch, 8, *OBSERVED)
    set_recipe(batch.command)
    batch.tick(20)
    batch.put(RECIPE_LOCK, 'minecraft:air')
    scan(batch, 65, OUTPUT, RECIPE_INLET, A)
    rows = batch.run(session, 'linked-hopper-restart')
    assert observe(rows[:5], cooldown=False) == expected(True, False, 2), rows[:5]
    upper, last = (observe(rows[i:i+5]) for i in (5, 10))
    return verify(first, held, upper, last, observe_recipe(rows[15:]))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--java', action='store_true')
    for flag in ('game', 'resources', 'ctl', 'reference', 'create-jar'):
        parser.add_argument('--' + flag, type=Path)
    args = parser.parse_args()
    if args.java:
        work = Path(tempfile.mkdtemp(prefix='crafter-hopper-java-', dir=ROOT / '.local'))
        print(work, flush=True)
        cases = java_run(work)
    else:
        if not all((args.game, args.resources, args.ctl, args.reference)):
            parser.error('Horizon requires --game, --resources, --ctl and --reference')
        reference = json.loads(args.reference.read_text())
        assert reference['create'] == PINS['create_revision'] and reference['passed'], reference
        session = NativeCheckSession(args.game, args.resources, args.ctl, args.create_jar,
                                     name='crafter-hopper-native', graphics=False,
                                     world='CreateCrafterHopper')
        work = session.scratch
        print(work, flush=True)
        try:
            cases = native_run(session)
        finally:
            session.control_temp.cleanup()
            for folder in (session.resources, work / '.horizon-cache', work / 'horizon-mods'):
                shutil.rmtree(folder, ignore_errors=True)
        assert cases == reference['cases'], (cases, reference)
    path = work / 'result.json'
    path.write_text(json.dumps(dict(passed=True, create=PINS['create_revision'], cases=cases,
                                   native_cold_restart=not args.java), indent=2) + '\n')
    print(path)


if __name__ == '__main__':
    main()
