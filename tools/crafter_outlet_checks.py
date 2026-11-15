#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Compare Mechanical Crafter output away from its downward face in both games."""

import argparse
import json
from pathlib import Path
import shutil
import tempfile

from bearing_native_checks import Batch
from burner_heat_java_checks import field, items, number
from chain_drive_checks import Original, xyz
from common import PINS, ROOT
from crafter_java_checks import phase
from funnel_checks import block, click, put, step, text
from native_check_session import NativeCheckSession
import reference_java


X, Y, Z = 2471, 172, 1348
BOTTOM = (X, Y, Z)
TOP = (X, Y + 1, Z)
SIDE = (X + 1, Y, Z)
ABOVE = (X, Y + 2, Z)
BELT_ROOT = (X + 1, Y, Z - 2)
BELT_MOTOR = (X + 2, Y, Z - 2)
TICKET = '2464 1344 2479 1359'
AREA = '2467 170 1345 2478 176 1355'
DROPS = '@e[type=minecraft:item,x=2467,y=170,z=1345,dx=11,dy=6,dz=10]'
INGREDIENT = 'minecraft:oak_planks'
PRODUCT = 'minecraft:stick'
CASES = ('chest', 'above', 'wall', 'belt')
IDLE = {'phase': ['IDLE', 0], 'group': {}}
BLOCKED = {'phase': ['INSERTING', 0], 'group': {PRODUCT: 4}}


def setup(cmd, kind):
    cmd(f'fill {AREA} minecraft:air')
    cmd(f'kill {DROPS}')
    cmd('fill 2467 170 1345 2478 170 1355 minecraft:smooth_stone')
    bottom, top = ('up', 'up') if kind == 'above' else ('right', 'down')
    for pos, pointing in ((BOTTOM, bottom), (TOP, top)):
        put(cmd, pos, f'create:mechanical_crafter[facing=south,pointing={pointing}]')
    put(cmd, (X - 1, Y + 1, Z), 'create:cogwheel[axis=z]')
    put(cmd, (X - 1, Y + 1, Z - 1), 'create:creative_motor[facing=south]{ScrollValue:128}')
    match kind:
        case 'chest':
            put(cmd, SIDE, 'minecraft:chest')
            cmd(f'item replace block {xyz(SIDE)} container.4 with {PRODUCT} 63')
        case 'above':
            put(cmd, ABOVE, 'minecraft:barrel')
        case 'wall':
            put(cmd, SIDE, 'minecraft:smooth_stone')
        case 'belt':
            parts = ('start', 'middle', 'middle', 'middle', 'end')
            for i, part in enumerate(parts):
                put(cmd, (BELT_ROOT[0], Y, BELT_ROOT[2] + i),
                    f'create:belt[facing=south,slope=horizontal,part={part}]')
        case _:
            raise ValueError(kind)


def fed(kind, pos, raw):
    assert (items(field(raw, 'Inventory'), 'Items') == {INGREDIENT: 1}
            or items(raw, 'Grid') == {INGREDIENT: 1}), (kind, pos, raw)


def slot_query(pos, index):
    return f'data get block {xyz(pos)} Items[{{Slot:{index}b}}]'


def expected_product(raw, count):
    assert PRODUCT in raw and number({'nbt': raw}, 'count') == count, raw
    return count


def craft_state(raw):
    return {'phase': phase({'nbt': raw}), 'group': items(raw, 'Grid')}


def belt_delivery(raw, destination):
    assert craft_state(raw) == IDLE, raw
    inv = field(destination, 'Inventory')
    assert items(inv, 'Items') == {PRODUCT: 4}, inv
    observed = {'nbt': inv}
    entry = [number(observed, key) for key in ('InSegment', 'InDirection')]
    assert entry == [2, 5], inv  # The travel direction into the Belt is east.
    side = number(observed, 'PrevOffset')
    assert abs(side + .675) < 1e-5, inv
    return {'blocked': BLOCKED, 'delivered': items(inv, 'Items'),
            'entry': entry, 'previous_side_offset': round(side, 3)}


def container_queries(kind):
    if kind == 'chest':
        return [('slot4', slot_query(SIDE, 4), 64), ('slot0', slot_query(SIDE, 0), 3)]
    if kind == 'above':
        return [('slot0', slot_query(ABOVE, 0), 4)]
    if kind == 'wall':
        return [('dropped', f'data get entity {DROPS[:-1]},limit=1] Item', 4)]
    return []


def scenario(host, work):
    report = {}
    for kind in CASES:
        setup(host.command, kind)
        step(host, 20, BOTTOM, TOP)
        for pos in (TOP, BOTTOM):
            x, y, z = pos
            click(host, work, f'{kind}-{y}', pos, 'south', (x + .5, Y - 1, z + 3.25),
                  (x + .5, y + .5, z + .5), INGREDIENT)
            fed(kind, pos, block(host, pos)['nbt'])
        if kind == 'wall':
            # Do not let the observer pick up the dropped result.
            host.command(f'tp @s {X-3}.5 {Y-1} {Z+6}.5')
        sink = TOP if kind == 'above' else BOTTOM
        step(host, 68, sink)
        final = craft_state(block(host, sink)['nbt'])
        if kind != 'belt':
            assert final == IDLE, (kind, final, block(host, sink))
            report[kind] = {key: expected_product(text(host, query), count)
                            for key, query, count in container_queries(kind)}
            continue
        assert final == BLOCKED, final
        assert not items(field(block(host, BELT_ROOT)['nbt'], 'Inventory'), 'Items')
        put(host.command, BELT_MOTOR, 'create:creative_motor[facing=west]{ScrollValue:32}')
        for _ in range(8):
            raw, destination = (node['nbt'] for node in step(host, 1, sink, BELT_ROOT))
            if items(field(destination, 'Inventory'), 'Items'):
                report[kind] = belt_delivery(raw, destination)
                break
        else:
            raise AssertionError((raw, destination))
    return report


def native_run(session):
    batch = Batch()
    batch.load((X, Y, Z + 4))
    batch.command('gamemode survival')
    for case, kind in enumerate(CASES):
        setup(batch.command, kind)
        batch.tick(20)
        for seq, pos in enumerate((TOP, BOTTOM), 1):
            x, y, z = pos
            batch.command(f'tp @s {x + .5} {Y - 1} {z + 3.25}')
            batch.command(f'item replace entity @s weapon.mainhand with {INGREDIENT}')
            batch.ops.append(dict(op='use_block', pos=pos, face=3, sequence=2 * case + seq))
            batch.data(pos)
        if kind == 'wall':
            batch.command(f'tp @s {X-3}.5 {Y-1} {Z+6}.5')
        sink = TOP if kind == 'above' else BOTTOM
        batch.tick(68)
        batch.data(sink)
        for _, query, _ in container_queries(kind):
            batch.command(query, True)
        if kind == 'belt':
            batch.data(BELT_ROOT)
            batch.put(BELT_MOTOR, 'create:creative_motor[facing=west]{ScrollValue:32}')
            for _ in range(8):
                batch.tick()
                batch.data(sink)
                batch.data(BELT_ROOT)

    rows = iter(batch.run(session, 'crafter-outlets'))
    report = {}
    for kind in CASES:
        for pos in (TOP, BOTTOM):
            fed(kind, pos, next(rows))
        final = craft_state(next(rows))
        if kind != 'belt':
            assert final == IDLE, (kind, final)
            report[kind] = {key: expected_product(next(rows), count)
                            for key, _, count in container_queries(kind)}
            continue
        assert final == BLOCKED, final
        assert not items(field(next(rows), 'Inventory'), 'Items')
        delivered = None
        for _ in range(8):
            raw, destination = next(rows), next(rows)
            if delivered is None and items(field(destination, 'Inventory'), 'Items'):
                delivered = belt_delivery(raw, destination)
        assert delivered is not None, (raw, destination)
        report[kind] = delivered
    assert next(rows, None) is None
    return report


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
    try:
        host.command(f'forceload add {TICKET}')
        host.snapshot([BOTTOM], 20)
        host.command('gamemode survival')
        return scenario(host, work)
    finally:
        host.command('gamemode creative')
        host.command('item replace entity @s weapon.mainhand with minecraft:air')
        host.command(f'fill {AREA} minecraft:air')
        host.command(f'kill {DROPS}')
        host.command(f'forceload remove {TICKET}')
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
        work = Path(tempfile.mkdtemp(prefix='crafter-outlet-java-', dir=ROOT / '.local'))
        print(work, flush=True)
        result = java_run(work)
    else:
        if not all((args.game, args.resources, args.ctl, args.reference)):
            parser.error('Horizon requires --game, --resources, --ctl and --reference')
        reference = json.loads(args.reference.read_text())
        assert reference['create'] == PINS['create_revision'] and reference['passed'], reference
        session = NativeCheckSession(args.game, args.resources, args.ctl, args.create_jar,
                                     name='crafter-outlet-native', graphics=False,
                                     world='CreateCrafterOutlet')
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
