#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Compare real main-hand use on Item Drain in the pinned Java and Horizon clients."""

import argparse
import json
from pathlib import Path
import re
import shutil
import tempfile

from burner_heat_java_checks import field, number
from chain_drive_checks import Native, Original, xyz
from common import PINS, ROOT
from funnel_checks import block, text
from item_drain_checks import DRAIN, LIQUIDS, WATER_BOTTLE
from native_check_session import NativeCheckSession, wait_loaded
import reference_java


POS = (2191, 168, 981)
LOAD = '2176 976 2191 991'
REGION = '2187 166 977 2191 171 985'
FEET = (2188.95, 168.0, 981.5)
AIM = (2191.0, 168.56, 981.5)


def capture_click(host, work, label, aim=AIM):
    if isinstance(host, Native):
        call = host.session.call
        host.command(f'tp @s {xyz(FEET)}')
        call('look-at', *aim)
        call('wait', 4)
        hit = call('looking-at')['block']
        assert hit['pos'] == list(POS) and hit['face'] == 'west', hit
        call('mouse', 'right', 'click')
        call('wait', 4)
        return
    host.call('camera', {'position': FEET, 'target': aim})
    host.call('capture', {'name': f'{work.name}/{label}-aim.png', 'frames': 10})
    hit = host.call('state', {})['hit']
    assert hit['pos'] == list(POS) and hit['face'] == 'west', hit
    host.call('input', {'kind': 'tap', 'key': 'use'})
    host.call('capture', {'name': f'{work.name}/{label}-settled.png', 'frames': 10})


def held(host):
    value = text(host, 'data get entity @s SelectedItem')
    id = re.search(r'id:\s*"(minecraft:\w+)"', value)
    assert id, value
    if id.group(1) == WATER_BOTTLE:
        assert re.search(r'\bpotion\s*:\s*"minecraft:water"', value), value
    return dict(item=id.group(1), count=int(number({'nbt': value}, 'count')),
                marker=int(number({'nbt': value}, 'drain_hand', 0)))


def tank(host, fluid_id):
    saved = block(host, POS)
    fluid = field(field(saved['nbt'], 'Tanks'), 'TankContent')
    amount = int(number({'nbt': fluid}, 'amount', 0))
    assert not amount or fluid_id in fluid, saved
    assert int(number(saved, 'ProcessingTicks')) == 0, saved
    west = block(host, (POS[0] - 1, POS[1], POS[2]))
    assert west['id'] == 'minecraft:air', west
    return amount


def scenario(host, work, liquid=LIQUIDS['water']):
    command = host.command
    command(f'fill {REGION} minecraft:air')
    command('fill 2187 167 978 2191 167 984 minecraft:smooth_stone')
    command(f'setblock {xyz(POS)} {DRAIN}')
    result = {}
    cases = [
        ('survival', 'survival', 61, liquid.container, 0),
        ('refused', 'survival', 62, liquid.source, 62),
        ('creative', 'creative', 63, liquid.source, 63),
    ]
    bottle = liquid.container == 'minecraft:glass_bottle'
    if bottle:
        cases.insert(2, ('incompatible', 'survival', 65, liquid.source, 65))
    for name, mode, marker, item, kept_marker in cases:
        fluid_id, amount = liquid.fluid, liquid.amount
        if bottle and name in ('refused', 'incompatible'):
            if name == 'refused':
                fluid_id, amount = liquid.blocked_fluid, liquid.blocked_amount
            else:
                fluid_id, amount = ('minecraft:lava' if liquid.fluid == 'minecraft:water' else 'minecraft:water'), 100
            command(f'data merge block {xyz(POS)} {{Tanks:[{{Level:{{Value:0f,Target:0f,Speed:.25f}},'
                    f'TankContent:{{Fluid:{{id:"{fluid_id}",amount:{amount}}}}}}}]}}')
        if mode == 'creative':
            command(f'setblock {xyz(POS)} minecraft:air')
            command(f'setblock {xyz(POS)} {DRAIN}')
        command(f'gamemode {mode}')
        patch = ','.join(f'{key}={value}' for key, value in liquid.marked('drain_hand', marker).items())
        command(f'item replace entity @s weapon.mainhand with {liquid.source}[{patch}]')
        capture_click(host, work, name)
        sample = dict(held=held(host), tank=tank(host, fluid_id))
        assert sample == dict(held=dict(item=item, count=1, marker=kept_marker), tank=amount), sample
        result[name] = sample
    command('gamemode survival')
    command('item replace entity @s weapon.mainhand with minecraft:air')
    patch = ','.join(f'"{key}":{value}' for key, value in liquid.marked('drain_hand', 64).items())
    command(f'data merge block {xyz(POS)} {{HeldItem:{{Item:{{id:"{liquid.source}",count:1,'
            f'components:{{{patch}}}}},'
            'Pos:.5f,PrevPos:.5f,InDirection:5,Angle:180}}')
    capture_click(host, work, 'recover')
    assert 'HeldItem:' not in block(host, POS)['nbt'], block(host, POS)
    inventory = text(host, 'data get entity @s Inventory')
    assert 'drain_hand:64' in re.sub(r'\s+', '', inventory), inventory
    if liquid.source == WATER_BOTTLE:
        assert re.search(r'\bpotion\s*:\s*"minecraft:water"', inventory), inventory
    result['recover'] = dict(cargo_marker=64, tank=tank(host, liquid.fluid))
    return result


def java_run(work, liquid=LIQUIDS['water']):
    host = Original()
    pinned = json.loads((reference_java.BASE / 'manifest.json').read_text())
    assert pinned['create_sha256'] == reference_java.CREATE_SHA256
    previous = host.call('state', {})
    assert previous['ready'] and previous['data_version'] == 3955, previous
    host.call('tick', {'frozen': True})
    try:
        host.command(f'forceload add {LOAD}')
        host.snapshot([POS], 20)
        return scenario(host, work, liquid)
    finally:
        host.command('gamemode creative')
        host.command('item replace entity @s weapon.mainhand with minecraft:air')
        host.command(f'clear @s {liquid.source}[minecraft:custom_data={{drain_hand:64}}]')
        host.command(f'fill {REGION} minecraft:air')
        host.command(f'forceload remove {LOAD}')
        host.call('camera', {'position': previous['position'], 'yaw': previous['yaw'], 'pitch': previous['pitch']})
        host.call('tick', {'frozen': previous['server']['frozen']})
        (work / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--java', action='store_true')
    fluids = parser.add_mutually_exclusive_group()
    fluids.add_argument('--lava', action='store_true')
    fluids.add_argument('--honey', action='store_true')
    fluids.add_argument('--water-bottle', action='store_true')
    for flag in ('game', 'resources', 'ctl', 'reference', 'create-jar'):
        parser.add_argument('--' + flag, type=Path)
    args = parser.parse_args()
    kind = 'water-bottle' if args.water_bottle else 'honey' if args.honey else 'lava' if args.lava else 'water'
    liquid = LIQUIDS[kind]
    if args.java:
        work = Path(tempfile.mkdtemp(prefix='drain-hand-java-', dir=ROOT / '.local'))
        result = java_run(work, liquid)
    else:
        if not all((args.game, args.resources, args.ctl, args.reference)):
            parser.error('Horizon check requires --game, --resources, --ctl and --reference')
        reference = json.loads(args.reference.read_text())
        assert reference['create'] == PINS['create_revision'] and reference['passed']
        assert reference.get('fluid', 'lava' if reference.get('lava', False) else 'water') == kind
        session = NativeCheckSession(args.game, args.resources, args.ctl, args.create_jar, name='drain-hand-native',
                                     world='CreateItemDrainHand')
        work = session.scratch
        try:
            with session:
                session.call('command', f'tp @s {xyz(FEET)}')
                wait_loaded(session.call, [POS])
                session.call('command', 'tick freeze')
                result = scenario(Native(session), work, liquid)
        finally:
            for folder in (session.resources, work / '.horizon-cache', work / 'horizon-mods'):
                shutil.rmtree(folder, ignore_errors=True)
        assert result == reference['scenarios'], (result, reference)
    path = work / 'result.json'
    path.write_text(json.dumps(dict(passed=True, create=PINS['create_revision'], fluid=kind, scenarios=result), indent=2) + '\n')
    print(path)


if __name__ == '__main__':
    main()
