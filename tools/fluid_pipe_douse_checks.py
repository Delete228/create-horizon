#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Compare open pipe water on blocks and open water/lava on a real player."""

import argparse
import json
from pathlib import Path
import re
import shutil
import tempfile

from burner_heat_java_checks import number
from chain_drive_checks import Native, Original
from common import PINS, ROOT
from fan_hazard_checks import advance
from fluid_pipe_effect_checks import AIR, AREA, LOAD, X, Y, Z, amount, lane, setup
from fluid_pump_java_checks import seed
from funnel_checks import block, put, step, text
from native_check_session import NativeCheckSession, wait_loaded
from reference_java import BASE, CREATE_SHA256

WATER = lane('water_sheep')
LAVA = lane('lava_sheep')
OUTLETS = {'water': WATER, 'lava': LAVA}
XW, YW, ZW = WATER['out']
BLOCKS = {
    'fire': ((XW, YW-1, ZW+1), 'minecraft:fire'),
    'candle': ((XW+1, YW, ZW), 'minecraft:candle[lit=true]'),
    'campfire': ((XW+1, YW-1, ZW+1), 'minecraft:campfire[lit=true]'),
    'outside_fire': ((XW+2, YW-1, ZW+1), 'minecraft:fire'),
}
AMOUNT = 400
POSITIONS = [WATER['tank'], WATER['out'], LAVA['out'], *(pos for pos, _ in BLOCKS.values())]


def game_time(host):
    matches = re.findall(r'\b\d+\b', text(host, 'time query gametime'))
    assert len(matches) == 1, matches
    return int(matches[0])


def fire(host):
    raw = text(host, 'data get entity @s')
    return int(number({'nbt': raw}, 'Fire'))


def stand(host, rig):
    x, y, z = rig['out']
    host.command(f'tp @s {x+.5} {y-1} {z+.5}')


def states(rows):
    output = {}
    for (name, _), row in zip(BLOCKS.items(), rows, strict=True):
        output[name] = row['id'] if name in ('fire', 'outside_fire') else row['properties']['lit'].lower()
    return output


def scenario(host):
    command = host.command
    setup(command)
    advance(host, 28, WATER['tank'])
    for (x, y, z), kind in BLOCKS.values():
        put(command, (x, y-1, z), 'minecraft:netherrack' if kind == 'minecraft:fire' else 'minecraft:stone')
        put(command, (x, y, z), kind)
    for kind, rig in OUTLETS.items():
        x, y, z = rig['out']
        put(command, (x, y-2, z), 'minecraft:smooth_stone')
        command(seed(rig['tank'], kind, AMOUNT))
        put(command, rig['motor'], 'create:creative_motor[facing=east]{ScrollValue:32}')
    command('gamemode survival')
    command('effect give @s minecraft:fire_resistance 60 0 true')
    stand(host, LAVA)
    assert fire(host) <= 0
    before = dict(fire='minecraft:fire', candle='true', campfire='true', outside_fire='minecraft:fire')
    assert states([block(host, p) for p, _ in BLOCKS.values()]) == before
    rows = []
    advance(host, 16, WATER['tank'])
    for _ in range(10):
        observed = advance(host, 1, *POSITIONS)
        tank, water, lava, *targets = observed
        assert water['id'] == lava['id'] == AIR, (water, lava)
        state = states(targets)
        rows.append(dict(time=game_time(host), tank=amount(tank['nbt']), blocks=state))
        if state != before:
            break
    expected = before | dict(fire=AIR, candle='false', campfire='false')
    assert len(rows) >= 2 and all(row['blocks'] == before for row in rows[:-1]), rows
    assert rows[-1]['blocks'] == expected and rows[-1]['time'] % 5 == 0, rows
    assert rows[-1]['tank'] < rows[-2]['tank'], rows

    # Reacquire the outlet's five-tick pulse just before reading the player,
    # avoiding the extra real player ticks taken by the block queries above.
    advance(host, 5, LAVA['out'])
    hot = fire(host)
    assert 0 < hot <= 60, hot
    stand(host, WATER)
    advance(host, 5, WATER['out'])
    wet = fire(host)
    assert wet <= 0, (hot, wet)
    assert all(block(host, rig['out'])['id'] == AIR for rig in OUTLETS.values())
    return dict(blocks=expected, hot=hot, wet=wet, trace=rows)


def java(work):
    host = Original()
    initial = host.call('state', {})
    if initial['screen'] == 'PauseScreen':
        host.call('input', {'kind': 'escape'})
        initial = host.call('state', {})
    assert initial['ready'] and initial['data_version'] == 3955, initial
    assert json.loads((BASE / 'manifest.json').read_text())['create_sha256'] == CREATE_SHA256
    mode = next((mode for mode in ('creative', 'survival', 'adventure', 'spectator')
                 if 'Test passed' in text(host, f'execute if entity @s[gamemode={mode}]')), None)
    assert mode and 'minecraft:fire_resistance' not in text(host, 'data get entity @s active_effects')
    host.call('tick', {'frozen': True})
    try:
        host.command(f'forceload add {LOAD}')
        host.command(f'tp @s {X}.5 {Y+5} {Z+5}.5')
        step(host, 40, WATER['tank'])
        return scenario(host)
    finally:
        host.command(f'gamemode {mode}')
        host.command('effect clear @s minecraft:fire_resistance')
        host.command(f'fill {AREA} {AIR}')
        host.command(f'forceload remove {LOAD}')
        host.call('camera', {key: initial[key] for key in ('position', 'yaw', 'pitch')})
        host.call('tick', {'frozen': initial['server']['frozen']})
        (work / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')


def native(session):
    with session:
        host = Native(session)
        host.command(f'tp @s {X}.5 {Y+5} {Z+5}.5')
        wait_loaded(session.call, POSITIONS)
        host.command('tick freeze')
        return scenario(host)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--java', action='store_true')
    for key in ('game', 'resources', 'ctl', 'create-jar', 'reference'):
        parser.add_argument('--' + key, type=Path)
    args = parser.parse_args()
    session = None
    if args.java:
        work = Path(tempfile.mkdtemp(prefix='pipe-douse-java-', dir=ROOT / '.local'))
    else:
        if not all((args.game, args.resources, args.ctl, args.create_jar, args.reference)):
            parser.error('Horizon requires --game, --resources, --ctl, --create-jar and --reference')
        reference = json.loads(args.reference.read_text())
        assert reference['passed'] and reference['create'] == PINS['create_revision']
        session = NativeCheckSession(args.game, args.resources, args.ctl, args.create_jar,
                                     name='pipe-douse-native', graphics=False, world='CreatePipeDouse')
        session.env.pop('CREATE_HORIZON_PARTICLE_TRACE', None)
        work = session.scratch
    print(work, flush=True)
    report = dict(passed=False, create=PINS['create_revision'])
    try:
        report['case'] = native(session) if session else java(work)
        if session:
            assert report['case']['blocks'] == reference['case']['blocks']
        report['passed'] = True
    finally:
        if session:
            session.control_temp.cleanup()
            for folder in (session.resources, work / '.horizon-cache', work / 'horizon-mods'):
                shutil.rmtree(folder, ignore_errors=True)
        (work / 'result.json').write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    main()
