#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Compare finished Crafter output into a busy or powered Chute."""

import argparse
import json
from pathlib import Path
import re
import shutil
import tempfile

from bearing_native_checks import Batch
from burner_heat_java_checks import field, number
from chain_drive_checks import Original, xyz
from common import PINS, ROOT
from crafter_outlet_checks import (
    AREA, BLOCKED, BOTTOM, DROPS, IDLE, INGREDIENT, PRODUCT, SIDE, TICKET, TOP,
    X, Y, Z, craft_state, fed, setup as setup_crafter,
)
from funnel_checks import block, click, put, step
from native_check_session import NativeCheckSession
import reference_java


CASES = ('open', 'stacked', 'smart')
ABOVE_CHUTE = (SIDE[0], SIDE[1] + 1, SIDE[2])
BELOW_CHUTE = (SIDE[0], SIDE[1] - 1, SIDE[2])
REDSTONE = (SIDE[0] + 1, SIDE[1], SIDE[2])
CHUTE = 'create:chute[facing=down,shape=normal,waterlogged=false]'
DUMMY = 'minecraft:paper'


def setup(cmd, kind):
    setup_crafter(cmd, 'wall')
    put(cmd, BELOW_CHUTE, 'minecraft:smooth_stone')
    if kind == 'smart':
        put(cmd, SIDE, 'create:smart_chute[powered=false]')
        put(cmd, REDSTONE, 'minecraft:redstone_block')
    else:
        put(cmd, SIDE, CHUTE)
        if kind == 'stacked':
            put(cmd, ABOVE_CHUTE, CHUTE)
        # Horizon also stores the Chute's slot in the host container list.
        cmd(f'data merge block {xyz(SIDE)} '
            f'{{Item:{{id:"{DUMMY}",count:1}},ItemPosition:0.5f,'
            f'Items:[{{Slot:0b,id:"{DUMMY}",count:1}}]}}')


def cases(cmd, scan, use):
    for kind in CASES:
        setup(cmd, kind)
        scan(20)
        for pos in (TOP, BOTTOM):
            use(kind, pos)
            scan(0, pos)
        scan(68, BOTTOM, SIDE)
        if kind == 'smart':
            put(cmd, REDSTONE, 'minecraft:air')
        else:
            cmd(f'data remove block {xyz(SIDE)} Item')
            cmd(f'data remove block {xyz(SIDE)} Items')
        for _ in range(21):
            scan(1, BOTTOM, SIDE)
        scan(15, SIDE)


def cargo(raw):
    if not re.search(r'\bItem\s*:', raw):
        return {}
    item = field(raw, 'Item')
    for item_id in (PRODUCT, DUMMY):
        if item_id in item:
            return {item_id: int(number({'nbt': item}, 'count'))}
    assert item == '{}', raw
    return {}


def check_cases(observations):
    rows = iter(observations)
    result = {}
    for kind in CASES:
        for pos in (TOP, BOTTOM):
            fed(kind, pos, next(rows))
        before, occupied = craft_state(next(rows)), cargo(next(rows))
        assert before == BLOCKED and occupied == ({} if kind == 'smart' else {DUMMY: 1}), (
            kind, before, occupied)
        delivery_tick = None
        for tick in range(1, 22):
            sink, target = next(rows), next(rows)
            delivered = cargo(target)
            if delivered:
                assert delivered == {PRODUCT: 4} and craft_state(sink) == IDLE, (kind, tick, sink, target)
                if delivery_tick is None:
                    delivery_tick = tick
            else:
                assert delivery_tick is None and craft_state(sink) == BLOCKED, (kind, tick, sink, target)
        assert delivery_tick is not None, kind
        if kind == 'stacked':
            assert delivery_tick > 1, delivery_tick
        else:
            assert delivery_tick == 1, (kind, delivery_tick)
        settled = next(rows)
        assert cargo(settled) == {PRODUCT: 4}, settled
        assert number({'nbt': settled}, 'ItemPosition') == .5, settled
        result[kind] = {'blocked': before, 'release_tick': delivery_tick, 'cargo': cargo(settled),
                        'settled_position': .5}
    assert next(rows, None) is None, observations
    return result


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
            step(host, ticks, BOTTOM)
        else:
            seen = step(host, ticks, *positions) if ticks else (block(host, p) for p in positions)
            observations.extend(row['nbt'] for row in seen)

    def use(kind, pos):
        x, y, z = pos
        click(host, work, f'{kind}-{y}', pos, 'south', (x + .5, Y - 1, z + 3.25),
              (x + .5, y + .5, z + .5), INGREDIENT)

    host.call('tick', {'frozen': True})
    try:
        cmd(f'forceload add {TICKET}')
        cmd(f'tp @s {X}.5 {Y+3} {Z+4}.5')
        host.snapshot([BOTTOM], 20)
        cmd('gamemode survival')
        cases(cmd, scan, use)
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

    def use(_kind, pos):
        x, _, z = pos
        batch.command(f'tp @s {x + .5} {Y - 1} {z + 3.25}')
        batch.command(f'item replace entity @s weapon.mainhand with {INGREDIENT}')
        batch.ops.append(dict(op='use_block', pos=pos, face=3, sequence=len(batch.ops)))

    cases(batch.command, scan, use)
    return check_cases(batch.run(session, 'crafter-chute-outlets'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--java', action='store_true')
    for flag in ('game', 'resources', 'ctl', 'reference', 'create-jar'):
        parser.add_argument('--' + flag, type=Path)
    args = parser.parse_args()
    if args.java:
        work = Path(tempfile.mkdtemp(prefix='crafter-chute-java-', dir=ROOT / '.local'))
        print(work, flush=True)
        result = java_run(work)
    else:
        if not all((args.game, args.resources, args.ctl, args.reference)):
            parser.error('Horizon requires --game, --resources, --ctl and --reference')
        reference = json.loads(args.reference.read_text())
        assert reference['create'] == PINS['create_revision'] and reference['passed'], reference
        session = NativeCheckSession(args.game, args.resources, args.ctl, args.create_jar,
                                     name='crafter-chute-native', graphics=False,
                                     world='CreateCrafterChute')
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
