#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Compare marked sapling and bone meal use by a stationary Deployer."""

import argparse
import json
from pathlib import Path
import re
import shutil
import tempfile

from burner_heat_java_checks import field
from chain_drive_checks import Native, Original, xyz
from common import PINS, ROOT
from deployer_hand_exchange_checks import MARK, marked, stack
from funnel_checks import text
from native_check_session import NativeCheckSession, wait_loaded
import reference_java as java


DEPLOYER = (1278, 122, 118)
MOTOR = (1277, 122, 118)
TARGET = (1278, 120, 118)
SOIL = (1278, 119, 118)
BACKUP = (1275, 121, 117)
AREA = '1275 118 115 1282 124 122'
LOAD = '1264 112 1295 127'
FRONT_FEET = (1278.5, 120.0, 118.5)
FRONT_AIM = (1278.5, 122.0, 118.5)
WATCH_FEET = (1275.5, 124, 118.5)
AIR = 'minecraft:air'
SAPLING = 'minecraft:oak_sapling'
MEAL = 'minecraft:bone_meal'
WHEAT = 'minecraft:wheat'
MARKER = 734
CASES = {
    'plant': (SAPLING, 'minecraft:dirt', AIR, SAPLING, {'stage': '0'}),
    'fertilize': (MEAL, 'minecraft:farmland[moisture=7]', WHEAT + '[age=6]', WHEAT, {'age': '7'}),
}


def put(host, position, block):
    host.command(f'setblock {xyz(position)} {block}')


def observe(host, ticks):
    deployer, target = host.snapshot([DEPLOYER, TARGET], ticks)
    nbt = deployer['nbt']
    return dict(target=target['block'], properties=target['properties'],
                held=stack(field(nbt, 'HeldItem')) if re.search(r'\bHeldItem\s*:', nbt) else None)


def remainder(item, count):
    return dict(id=item, count=count, marker=MARKER, damage=0, glint=True)


def power(host):
    put(host, MOTOR, 'create:creative_motor[facing=east]{ScrollValue:32}')


def run_case(host, case, restart):
    item, soil, target, result, properties = case
    host.command(f'fill {AREA} minecraft:air')
    put(host, SOIL, soil)
    put(host, TARGET, target)
    item_nbt = (f'{{Slot:0b,id:"{item}",count:3,components:{{'
                f'"minecraft:custom_data":{{{MARK}:{MARKER}}},'
                '"minecraft:enchantment_glint_override":true}}')
    put(host, DEPLOYER, 'create:deployer[facing=down,axis_along_first=true]'
        + '{Mode:"USE",State:"WAITING",Timer:0,Inventory:[' + item_nbt + ']}')
    initial = observe(host, 4)
    power(host)
    first = observe(host, 65)
    put(host, MOTOR, AIR)
    stopped = observe(host, 4)
    restart()
    cold = observe(host, 4)
    put(host, TARGET, target)
    power(host)
    repeated = observe(host, 65)

    assert initial['held'] == remainder(item, 3), initial
    assert first == dict(target=result, properties=properties, held=remainder(item, 2)), first
    assert stopped == cold == first, (stopped, cold, first)
    assert repeated == dict(target=result, properties=properties, held=remainder(item, 1)), repeated
    return dict(initial=initial, first=first, stopped=stopped, cold=cold, repeated=repeated)


def selected(host):
    raw = text(host, 'data get entity @s SelectedItem')
    return stack(raw[raw.find('{'):]) if '{' in raw else None


def run_running(host, work):
    host.command(f'fill {AREA} minecraft:air')
    previous = selected(host)
    put(host, BACKUP, 'minecraft:barrel')
    host.command(f'item replace block {xyz(BACKUP)} container.0 from entity @s weapon.mainhand')
    try:
        return running_stroke(host, work)
    finally:
        host.command(f'item replace entity @s weapon.mainhand from block {xyz(BACKUP)} container.0')
        assert selected(host) == previous, 'The fixture must restore the player hand'


def running_stroke(host, work):
    put(host, SOIL, 'minecraft:dirt')
    put(host, DEPLOYER, 'create:deployer[facing=down,axis_along_first=true]'
        f'{{Mode:"USE",State:"WAITING",Timer:0,Filter:{{id:"{SAPLING}",count:1}}}}')
    host.snapshot([DEPLOYER], 4)
    power(host)
    [active] = host.snapshot([DEPLOYER], 4)
    assert active['speed'] == 32 and re.search(r'\bState\s*:\s*"EXPANDING"', active['nbt']), active
    host.command('item replace entity @s weapon.mainhand with '
                 + marked(SAPLING, 3, MARKER, ',minecraft:enchantment_glint_override=true'))
    if isinstance(host, Native):
        call = host.session.call
        host.command('tp @s ' + xyz(FRONT_FEET))
        call('look-at', *FRONT_AIM)
        hit = call('looking-at')['block']
        assert hit and hit['pos'] == list(DEPLOYER) and hit['face'] == 'down', hit
        call('mouse', 'right', 'click')
        call('wait', 2)
    else:
        host.call('camera', {'position': FRONT_FEET, 'target': FRONT_AIM})
        host.call('capture', {'name': f'{work.name}/active-aim.png', 'frames': 8})
        hit = host.call('state', {})['hit']
        assert hit and hit['pos'] == list(DEPLOYER) and hit['face'] == 'down', hit
        host.call('input', {'kind': 'tap', 'key': 'use'})
        host.call('capture', {'name': f'{work.name}/active-click.png', 'frames': 8})
    host.command('tp @s ' + xyz(WATCH_FEET))
    clicked = observe(host, 4)
    assert clicked['held'] == remainder(SAPLING, 3) and selected(host) is None, clicked
    final = observe(host, 65)
    assert final == dict(target=SAPLING, properties={'stage': '0'}, held=remainder(SAPLING, 2)), final
    return dict(clicked=clicked, final=final)


def java_run(work, running):
    host = Original()
    manifest = json.loads((java.BASE / 'manifest.json').read_text())
    initial = host.call('state', {})
    assert manifest['create_sha256'] == java.CREATE_SHA256 and initial['data_version'] == 3955
    rule = ' '.join(host.command('gamerule randomTickSpeed')['messages'])
    speed = int(re.search(r'\b(\d+)\.?$', rule)[1])
    host.call('tick', {'frozen': True})
    try:
        host.command(f'forceload add {LOAD}')
        host.command('tp @s ' + xyz(WATCH_FEET))
        host.snapshot([DEPLOYER], 24)
        host.command('gamerule randomTickSpeed 0')
        if running:
            return {'running': run_running(host, work)}
        return {label: run_case(host, case, lambda: None) for label, case in CASES.items()}
    finally:
        host.command(f'fill {AREA} minecraft:air')
        host.command(f'forceload remove {LOAD}')
        host.command(f'gamerule randomTickSpeed {speed}')
        host.call('camera', {key: initial[key] for key in ('position', 'yaw', 'pitch')})
        host.call('tick', {'frozen': initial['server']['frozen']})
        (work / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')


def native_run(session, running):
    host = Native(session)

    def restart():
        session.restart()
        wait_loaded(session.call, [DEPLOYER, TARGET])

    with session:
        host.command('tp @s ' + xyz(WATCH_FEET))
        wait_loaded(session.call, [DEPLOYER, TARGET])
        host.command('gamerule minecraft:random_tick_speed 0')
        if running:
            return {'running': run_running(host, session.scratch)}
        return {label: run_case(host, case, restart) for label, case in CASES.items()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--java', action='store_true')
    parser.add_argument('--running', action='store_true', help='Check a front click during a powered stroke')
    for flag in ('game', 'resources', 'ctl', 'reference', 'create-jar'):
        parser.add_argument('--' + flag, type=Path)
    args = parser.parse_args()
    if args.java:
        work = Path(tempfile.mkdtemp(prefix='deployer-components-java-', dir=ROOT / '.local'))
        print(work, flush=True)
        cases = java_run(work, args.running)
    else:
        if not all((args.game, args.resources, args.ctl, args.reference, args.create_jar)):
            parser.error('Horizon requires --game, --resources, --ctl, --reference and --create-jar')
        reference = json.loads(args.reference.read_text())
        assert reference['passed'] and reference['create'] == PINS['create_revision'], reference
        session = NativeCheckSession(args.game, args.resources, args.ctl, args.create_jar,
                                     name='deployer-components-native', world='DeployerComponents',
                                     graphics=args.running)
        work = session.scratch
        print(work, flush=True)
        try:
            cases = native_run(session, args.running)
        finally:
            for folder in (session.resources, work / '.horizon-cache', work / 'horizon-mods'):
                shutil.rmtree(folder, ignore_errors=True)
        assert cases == reference['cases'], (cases, reference)
    path = work / 'result.json'
    path.write_text(json.dumps(dict(passed=True, create=PINS['create_revision'], cases=cases), indent=2) + '\n')
    print(path)


if __name__ == '__main__':
    main()
