#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Compare direct bottle use on a Basin and a standard Fluid Tank."""

import argparse
import json
from pathlib import Path
import re
import shutil
import tempfile

from burner_heat_java_checks import field
from chain_drive_checks import Native, Original, xyz
from common import PINS, ROOT
from funnel_checks import block, put, text
from item_drain_hand_checks import AIM, FEET, LOAD, POS, REGION, capture_click, held
from item_drain_checks import POTION_CONTENTS, WATER_BOTTLE, WATER_CONTENTS
from native_check_session import NativeCheckSession, wait_loaded
import reference_java as java


BASIN, TANK = 'create:basin', 'create:fluid_tank'
HONEY, GLASS = 'minecraft:honey_bottle', 'minecraft:glass_bottle'
CASES = (
    ('basin_survival', BASIN, 'survival', HONEY, GLASS, 250),
    ('basin_glass', BASIN, 'survival', GLASS, GLASS, 250),
    ('tank_survival', TANK, 'survival', HONEY, HONEY, 0),
    ('tank_creative', TANK, 'creative', HONEY, HONEY, 250),
    ('tank_glass', TANK, 'creative', GLASS, GLASS, 250),
)


def read_fluid(raw, kind):
    if kind == BASIN:
        assert 'create:honey' not in field(raw, 'OutputTanks'), raw
        raw = field(raw, 'InputTanks')
    else:
        raw = field(raw, 'TankContent')
    values = re.findall(r'\bid\s*:\s*"([^"]+)"', raw)
    amounts = re.findall(r'\bamount\s*:\s*(\d+)', raw)
    return [(fluid, int(amount)) for fluid, amount in zip(values, amounts, strict=True)]


def prepare(host):
    host.command(f'fill {REGION} minecraft:air')
    host.command('fill 2187 167 978 2191 167 984 minecraft:smooth_stone')


def scenario(host, work):
    cmd = host.command
    prepare(host)
    result = {}
    last = None
    for name, kind, mode, source, container, amount in CASES:
        if kind != last:
            put(cmd, POS, kind)
            last = kind
        cmd('gamemode ' + mode)
        cmd(f'item replace entity @s weapon.mainhand with {source}[minecraft:custom_data={{drain_hand:21}}]')
        aim = (POS[0], POS[1] + .38, POS[2] + .2) if kind == BASIN else AIM
        capture_click(host, work, name, aim)
        state = block(host, POS)
        assert state['id'] == kind, state
        if kind == BASIN and re.search(r'\bFilter\s*:', state['nbt']):
            assert field(state['nbt'], 'Filter') == '{}', state
        item, fluid = held(host), read_fluid(state['nbt'], kind)
        assert item == dict(item=container, count=1, marker=21 if container == source else 0), item
        assert fluid == ([('create:honey', amount)] if amount else []), fluid
        result[name] = dict(held=item, tank=[[fluid_id, volume] for fluid_id, volume in fluid])
    return result


def water_scenario(host, work):
    prepare(host)
    cmd = host.command
    result = {}
    water = 'minecraft:water'
    potion = f'{WATER_BOTTLE}[{POTION_CONTENTS}={WATER_CONTENTS}]'
    water_field = r'\bpotion\s*:\s*"minecraft:water"'

    def seed(kind, *amounts):
        entries = [f'{{Fluid:{{id:"{water}",amount:{amount}}}}}' for amount in amounts]
        if kind == BASIN:
            segments = [f'{{TankContent:{entry},Level:{{Value:0f,Target:0f,Speed:.25f}}}}'
                        for entry in (entries + ['{}'])[:2]]
            nbt = f'InputTanks:[{",".join(segments)}]'
        else:
            nbt = f'TankContent:{entries[0]}'
        cmd(f'data merge block {xyz(POS)} {{{nbt}}}')

    def click(name, kind, mode, source, remaining, amounts, *, count=1, returned=False):
        cmd('gamemode ' + mode)
        patch = 'minecraft:custom_data={drain_hand:21}'
        if source == WATER_BOTTLE:
            patch += f',{POTION_CONTENTS}={WATER_CONTENTS}'
        cmd(f'item replace entity @s weapon.mainhand with {source}[{patch}] {count}')
        aim = (POS[0], POS[1] + .38, POS[2] + .2) if kind == BASIN else AIM
        capture_click(host, work, name, aim)
        sample = held(host)
        selected = text(host, 'data get entity @s SelectedItem')
        assert bool(re.search(water_field, selected)) == (remaining == WATER_BOTTLE), selected
        expected = dict(item=remaining, count=count - int(returned), marker=21 if remaining == source else 0)
        assert sample == expected, (name, sample, expected)
        tank = read_fluid(block(host, POS)['nbt'], kind)
        assert tank == [(water, amount) for amount in amounts], (name, tank, amounts)
        inventory = text(host, 'data get entity @s Inventory')
        assert len(re.findall(water_field, inventory)) == int(returned) + int(remaining == WATER_BOTTLE), inventory
        if returned:
            cmd(f'clear @s {potion} 1')
        result[name] = dict(held=sample, tank=[list(entry) for entry in tank], returned=returned)

    put(cmd, POS, BASIN)
    click('basin_pour', BASIN, 'survival', WATER_BOTTLE, GLASS, [250])
    click('basin_stacked_fill', BASIN, 'survival', GLASS, GLASS, [], count=2, returned=True)
    seed(BASIN, 200)
    click('basin_insufficient_water', BASIN, 'survival', GLASS, GLASS, [200])
    seed(BASIN, 950, 900)
    click('basin_insufficient_room', BASIN, 'survival', WATER_BOTTLE, WATER_BOTTLE, [950, 900])
    seed(BASIN, 250)
    click('basin_creative_fill', BASIN, 'creative', GLASS, GLASS, [])

    put(cmd, POS, TANK)
    click('tank_survival_pour', TANK, 'survival', WATER_BOTTLE, WATER_BOTTLE, [])
    click('tank_creative_pour', TANK, 'creative', WATER_BOTTLE, WATER_BOTTLE, [250])
    click('tank_creative_fill', TANK, 'creative', GLASS, GLASS, [])
    seed(TANK, 200)
    click('tank_insufficient_water', TANK, 'creative', GLASS, GLASS, [200])
    seed(TANK, 7900)
    click('tank_insufficient_room', TANK, 'creative', WATER_BOTTLE, WATER_BOTTLE, [7900])
    return result


def java_run(work, run):
    host = Original()
    assert json.loads((java.BASE / 'manifest.json').read_text())['create_sha256'] == java.CREATE_SHA256
    initial = host.call('state', {})
    assert initial['ready'] and initial['data_version'] == 3955, initial
    host.call('tick', {'frozen': True})
    try:
        host.command(f'forceload add {LOAD}')
        host.snapshot([POS], 20)
        return run(host, work)
    finally:
        host.command('gamemode creative')
        host.command('item replace entity @s weapon.mainhand with minecraft:air')
        host.command(f'fill {REGION} minecraft:air')
        host.command(f'forceload remove {LOAD}')
        host.call('camera', {key: initial[key] for key in ('position', 'yaw', 'pitch')})
        host.call('tick', {'frozen': initial['server']['frozen']})
        (work / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--java', action='store_true')
    parser.add_argument('--water-bottle', action='store_true')
    for flag in ('game', 'resources', 'ctl', 'reference', 'create-jar'):
        parser.add_argument('--' + flag, type=Path)
    args = parser.parse_args()
    kind = 'water' if args.water_bottle else 'honey'
    run = water_scenario if args.water_bottle else scenario
    if args.java:
        work = Path(tempfile.mkdtemp(prefix=f'basin-tank-{kind}-java-', dir=ROOT / '.local'))
        print(work, flush=True)
        result = java_run(work, run)
    else:
        if not all((args.game, args.resources, args.ctl, args.reference)):
            parser.error('Horizon requires --game, --resources, --ctl and --reference')
        reference = json.loads(args.reference.read_text())
        assert reference['create'] == PINS['create_revision'] and reference['passed'], reference
        assert reference.get('liquid', 'honey') == kind, reference
        session = NativeCheckSession(args.game, args.resources, args.ctl, args.create_jar,
                                     name=f'basin-tank-{kind}-native', world=f'CreateBasinTank{kind.title()}')
        work = session.scratch
        print(work, flush=True)
        try:
            with session:
                session.call('command', f'tp @s {xyz(FEET)}')
                wait_loaded(session.call, [POS])
                session.call('command', 'tick freeze')
                result = run(Native(session), work)
        finally:
            for folder in (session.resources, work / '.horizon-cache', work / 'horizon-mods'):
                shutil.rmtree(folder, ignore_errors=True)
        assert result == reference['cases'], (result, reference)
    path = work / 'result.json'
    path.write_text(json.dumps(dict(passed=True, create=PINS['create_revision'], liquid=kind, cases=result), indent=2) + '\n')
    print(path)


if __name__ == '__main__':
    main()
