#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Compare stopped Deployer hand swaps, component fidelity and cold retrieval."""

import argparse
import json
from pathlib import Path
import re
import shutil
import tempfile
import time

from burner_heat_java_checks import field, number
from chain_drive_checks import Native, Original, xyz
from common import PINS, ROOT
from funnel_checks import block, text
from native_check_session import NativeCheckSession, wait_loaded
import reference_java as java


POS = (1246, 109, 101)
FEET = (1249.5, 108, 101.5)
AIM = (1246.98, 109.5, 101.5)
AREA = '1244 106 99 1251 112 103'
LOAD = '1232 96 1255 111'
AIR, OAK, IRON, TOOL, PAPER, WRENCH = ('minecraft:air', 'minecraft:oak_sapling', 'minecraft:iron_ingot',
                                      'minecraft:diamond_pickaxe', 'minecraft:paper', 'create:wrench')
MARK = 'deployer_hand_probe'


def marked(item, count, marker, extra=''):
    return f'{item}[minecraft:custom_data={{{MARK}:{marker}}}{extra}] {count}'


def stack(raw):
    item = re.search(r'\bid\s*:\s*"([^\"]+)"', raw)
    if item is None:
        return None
    damage = re.search(r'"minecraft:damage"\s*:\s*(\d+)', raw)
    glint = re.search(r'"minecraft:enchantment_glint_override"\s*:\s*(true|1b)', raw)
    return dict(id=item[1], count=int(number({'nbt': raw}, 'count')),
                marker=int(number({'nbt': raw}, MARK, 0)), damage=int(damage[1]) if damage else 0,
                glint=bool(glint))


def observe(host):
    raw = block(host, POS)['nbt']
    mode = re.search(r'\bMode\s*:\s*"(USE|PUNCH)"', raw)
    assert mode, raw
    selected = text(host, 'data get entity @s SelectedItem')
    return dict(player=stack(selected[selected.find('{'):]) if '{' in selected else None,
                held=stack(field(raw, 'HeldItem')) if re.search(r'\bHeldItem\s*:', raw) else None,
                filter=stack(field(raw, 'Filter')), mode=mode[1])


def setup(host):
    cmd = host.command
    cmd(f'fill {AREA} minecraft:air')
    cmd('fill 1245 107 100 1251 107 102 minecraft:smooth_stone')
    cmd(f'setblock {xyz(POS)} create:deployer[facing=east,axis_along_first=false]'
        '{Mode:"USE",State:"WAITING",Timer:0,Filter:{id:"minecraft:oak_sapling",count:1}}')
    host.snapshot([POS], 10)


def tap(host, work, name, mode, held):
    cmd = host.command
    cmd('gamemode ' + mode)
    cmd('item replace entity @s weapon.mainhand with ' + held)
    if isinstance(host, Native):
        call = host.session.call
        cmd('tp @s ' + xyz(FEET))
        call('look-at', *AIM)
        call('wait', 4)
        hit = call('looking-at')['block']
        assert hit and hit['pos'] == list(POS) and hit['face'] == 'east', hit
        call('mouse', 'right', 'click')
        call('wait', 6)
        if name in ('put-iron', 'swap-tool', 'toggle-punch'):
            call('key', 'f1', 'tap')
            call('wait', 2)
            call('screenshot', work / f'{name}.png')
            call('key', 'f1', 'tap')
    else:
        host.call('camera', {'position': FEET, 'target': AIM})
        host.call('capture', {'name': f'{work.name}/{name}-aim.png', 'frames': 8})
        hit = host.call('state', {})['hit']
        assert hit and hit['pos'] == list(POS) and hit['face'] == 'east', hit
        host.call('input', {'kind': 'tap', 'key': 'use'})
        captured = host.call('capture', {'name': f'{work.name}/{name}.png', 'frames': 8})
        if name in ('put-iron', 'swap-tool', 'toggle-punch'):
            shutil.copy2(captured['path'], work / f'{name}.png')
    return observe(host)


def scenario(host, work, restart):
    setup(host)
    result = {}
    result['put_iron'] = tap(host, work, 'put-iron', 'creative',
                             marked(IRON, 17, 111, ',minecraft:enchantment_glint_override=true'))
    result['swap_tool'] = tap(host, work, 'swap-tool', 'survival', marked(TOOL, 1, 222, ',minecraft:damage=37'))
    restart()
    result['cold'] = observe(host)
    result['toggle_punch'] = tap(host, work, 'toggle-punch', 'survival', WRENCH)
    result['toggle_use'] = tap(host, work, 'toggle-use', 'survival', WRENCH)
    result['take_tool'] = tap(host, work, 'take-tool', 'survival', AIR)
    result['put_saplings'] = tap(host, work, 'put-saplings', 'survival', marked(OAK, 6, 333))
    result['swap_adventure'] = tap(host, work, 'swap-adventure', 'adventure', marked(PAPER, 3, 444))
    result['take_adventure'] = tap(host, work, 'take-adventure', 'adventure', AIR)
    return result


def verify(result):
    def item(id, count=1, marker=0, damage=0, glint=False):
        return dict(id=id, count=count, marker=marker, damage=damage, glint=glint)

    filter = item(OAK)
    iron, tool = item(IRON, 17, 111, glint=True), item(TOOL, 1, 222, damage=37)
    oak, paper, wrench = item(OAK, 6, 333), item(PAPER, 3, 444), item(WRENCH)

    def row(player, held, mode='USE'):
        return dict(player=player, held=held, filter=filter, mode=mode)

    assert result == {
        'put_iron': row(None, iron), 'swap_tool': row(iron, tool), 'cold': row(iron, tool),
        'toggle_punch': row(wrench, tool, 'PUNCH'), 'toggle_use': row(wrench, tool),
        'take_tool': row(tool, None), 'put_saplings': row(None, oak),
        'swap_adventure': row(oak, paper), 'take_adventure': row(paper, None),
    }, result


def java_run(work):
    host = Original()
    manifest = json.loads((java.BASE / 'manifest.json').read_text())
    initial = host.call('state', {})
    assert manifest['create_sha256'] == java.CREATE_SHA256 and initial['data_version'] == 3955

    def restart():
        host.call('quit', {})
        deadline = time.monotonic() + 55
        while java.process_alive(java.BASE):
            assert time.monotonic() < deadline, 'Isolated Java client failed to save and exit'
            time.sleep(.15)
        assert java.launch(java.BASE)['ready']
        host.call('tick', {'frozen': True})
        host.snapshot([POS], 18)

    host.call('tick', {'frozen': True})
    try:
        host.command('gamemode creative')
        host.command(f'forceload add {LOAD}')
        host.snapshot([POS], 22)
        return scenario(host, work, restart)
    finally:
        host.command('gamemode creative')
        host.command('item replace entity @s weapon.mainhand with minecraft:air')
        host.command(f'fill {AREA} minecraft:air')
        host.command(f'forceload remove {LOAD}')
        host.call('camera', {key: initial[key] for key in ('position', 'yaw', 'pitch')})
        host.call('tick', {'frozen': initial['server']['frozen']})
        (work / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')


def native_run(session):
    host = Native(session)

    def restart():
        session.restart()
        wait_loaded(session.call, [POS])

    with session:
        host.command('tp @s ' + xyz(FEET))
        wait_loaded(session.call, [POS])
        return scenario(host, session.scratch, restart)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--java', action='store_true')
    for flag in ('game', 'resources', 'ctl', 'reference', 'create-jar'):
        parser.add_argument('--' + flag, type=Path)
    args = parser.parse_args()
    if args.java:
        work = Path(tempfile.mkdtemp(prefix='deployer-hand-java-', dir=ROOT / '.local'))
        print(work, flush=True)
        result = java_run(work)
    else:
        if not all((args.game, args.resources, args.ctl, args.reference, args.create_jar)):
            parser.error('Horizon requires --game, --resources, --ctl, --reference and --create-jar')
        reference = json.loads(args.reference.read_text())
        assert reference['create'] == PINS['create_revision'] and reference['passed'], reference
        session = NativeCheckSession(args.game, args.resources, args.ctl, args.create_jar,
                                     name='deployer-hand-native', world='CreateDeployerHand')
        work = session.scratch
        print(work, flush=True)
        try:
            result = native_run(session)
        finally:
            for folder in (session.resources, work / '.horizon-cache', work / 'horizon-mods'):
                shutil.rmtree(folder, ignore_errors=True)
        assert result == reference['cases'], (result, reference)
    verify(result)
    path = work / 'result.json'
    path.write_text(json.dumps(dict(passed=True, create=PINS['create_revision'], cases=result), indent=2) + '\n')
    print(path)


if __name__ == '__main__':
    main()
