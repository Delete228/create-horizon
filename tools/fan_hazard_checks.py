#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Compare hot/wet air against actual Java mobs and the integrated player."""

import argparse
import json
from pathlib import Path
import re
import shutil
import tempfile
import time

from burner_heat_java_checks import number
from chain_drive_checks import Native, Original
from common import PINS, ROOT
from funnel_checks import block, put, step, text
from native_check_session import NativeCheckSession, wait_loaded
from reference_java import BASE, CREATE_SHA256

X, Y = 2000, 170
AREA = '1998 169 1748 2007 174 1773'
LOAD = '1984 1744 2015 1775'
LANES = {
    'lava_sheep': (1750, 'lava', 'sheep'),
    'smoke_sheep': (1754, 'smoke', 'sheep'),
    'lava_blaze': (1758, 'lava', 'blaze'),
    'water_blaze': (1762, 'water', 'blaze'),
    'resistant_sheep': (1766, 'lava', 'sheep'),
    'player': (1770, 'lava', None),
}
FAN = 'create:encased_fan[facing=east]'
MOTOR = 'create:creative_motor[facing=east]{ScrollValue:256}'
AIR = 'minecraft:air'


def selector(name):
    return '@s' if name == 'player' else f'@e[tag=fan_hazard_{name},limit=1]'


def position(dx, z, dy=0):
    return X + dx, Y + dy, z


def setup(host):
    command = host.command
    command(f'fill {AREA} {AIR}')
    command('fill 1998 169 1748 2007 169 1773 minecraft:smooth_stone')
    for name, (z, medium, entity) in LANES.items():
        command(f'fill {X+5} {Y} {z-1} {X+5} {Y+2} {z+1} minecraft:stone')
        if name == 'player':
            for wall in (z - 1, z + 1):
                command(f'fill {X+3} {Y} {wall} {X+5} {Y+2} {wall} minecraft:stone')
        if medium == 'smoke':
            put(command, position(1, z), 'minecraft:campfire[lit=true]')
        else:
            for pos in (position(1, z-1), position(1, z+1), position(1, z, 1)):
                put(command, pos, 'minecraft:glass')
            put(command, position(2, z), 'minecraft:iron_bars')
            put(command, position(1, z), f'minecraft:{medium}')
        if entity:
            command(f'summon minecraft:{entity} {X+3.5} {Y} {z+.5} '
                    f'{{Tags:["fan_hazard_probe","fan_hazard_{name}"],'
                    'NoAI:1b,NoGravity:1b,Silent:1b}')
        if name == 'resistant_sheep':
            command(f'effect give {selector(name)} minecraft:fire_resistance 60 0 true')
        put(command, position(-1, z), MOTOR)


def read(host, name):
    data = text(host, f'data get entity {selector(name)}')
    assert 'Health:' in data and 'Fire:' in data, (name, data)
    return {key.lower(): int(number({'nbt': data}, key)) for key in ('Health', 'Fire', 'HurtTime')}


def samples(host):
    return {name: read(host, name) for name in ('player', *(name for name in LANES if name != 'player'))}


def advance(host, count, *positions):
    if not isinstance(host, Native):
        return step(host, count, *positions)

    def game_time():
        values = re.findall(r'\b\d+\b', text(host, 'time query gametime'))
        assert len(values) == 1, values
        return int(values[0])

    # The public sprint command temporarily restores normal simulation, then
    # refreezes after the exact number of ticks. Frozen stepping supplies
    # zero effective RPM to the fan.
    start = game_time()
    host.command(f'tick sprint {count}')
    deadline = time.monotonic() + 12
    while game_time() < start + count:
        assert time.monotonic() < deadline, ('simulation stalled', start, count)
        time.sleep(.035)
    assert game_time() - start == count, (start, game_time(), count)
    assert 'frozen' in text(host, 'tick query').lower()
    return [block(host, pos) for pos in positions]


def scenario(host):
    native = isinstance(host, Native)
    command = host.command
    fanz = [position(0, z) for z, _, _ in LANES.values()]
    command('gamemode survival')
    player_z = LANES['player'][0]
    setup(host)
    command(f'tp @s {X+3.5} {Y} {player_z+.5}')
    result = {'initial': samples(host)}
    assert result['initial']['player']['health'] == 20, result['initial']['player']
    for pos in fanz:
        put(command, pos, FAN)
    for age, elapsed in ((1, 1), (2, 1), (6, 4), (9, 3)):
        blocks = advance(host, elapsed, *fanz)
        assert all(number(b, 'Speed') == 256 for b in blocks), blocks
        result[f'hot_{age}'] = samples(host)
        if age == 1:
            # The native player keeps taking ordinary on-fire ticks between
            # control queries. Preserve its burning state without risking a
            # death before the water phase. The first unprotected hit is above.
            command('effect give @s minecraft:fire_resistance 6 0 true')
    for name in ('lava_sheep', 'resistant_sheep', 'player'):
        put(command, position(1, LANES[name][0]), 'minecraft:water')
    for age, elapsed in ((1, 1), (2, 1), (6, 4)):
        advance(host, elapsed, fanz[-1])
        result[f'water_{age}'] = samples(host)
    if native:
        result['native_fan_hits'] = [hit for player in host.session.call('hurtlog')['players']
                                     for hit in player['hurts']
                                     if hit['hurt'] and hit['source'] == 'create:fan_lava']
    return result


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
    assert mode, initial
    difficulty = text(host, 'difficulty').split()[-1].lower()
    assert difficulty in ('peaceful', 'easy', 'normal', 'hard'), difficulty
    natural_regeneration = 'true' if 'true' in text(host, 'gamerule naturalRegeneration') else 'false'
    assert 'minecraft:fire_resistance' not in text(host, 'data get entity @s active_effects')
    host.call('tick', {'frozen': True})
    host.command(f'forceload add {LOAD}')
    try:
        host.command(f'tp @s {X+3.5} {Y+4} 1760.5')
        step(host, 50, (X, Y, 1760))
        host.command('gamerule naturalRegeneration false')
        host.command('difficulty normal')
        return scenario(host)
    finally:
        host.command('gamemode ' + mode)
        host.command('effect clear @s minecraft:fire_resistance')
        host.command('effect give @s minecraft:instant_health 1 6 true')
        host.command('gamerule naturalRegeneration ' + natural_regeneration)
        host.command('difficulty ' + difficulty)
        host.command('kill @e[tag=fan_hazard_probe]')
        host.command(f'fill {AREA} {AIR}')
        host.command(f'forceload remove {LOAD}')
        host.call('camera', {key: initial[key] for key in ('position', 'yaw', 'pitch')})
        host.call('tick', {'frozen': initial['server']['frozen']})
        (work / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')


def native(session):
    with session:
        host = Native(session)
        host.command(f'tp @s {X+3.5} {Y+4} 1760.5')
        wait_loaded(session.call, [position(0, z) for z, _, _ in LANES.values()])
        host.command('tick freeze')
        host.command('gamerule minecraft:natural_health_regeneration false')
        host.command('difficulty normal')
        return scenario(host)


def verify(rows, reference):
    assert all(0 < rows[f'hot_{age}']['player']['fire'] <= 200 for age in (1, 2, 6, 9)), rows
    assert all(rows[f'water_{age}']['player']['fire'] <= 0 for age in (1, 2, 6)), rows
    assert rows['water_6']['player']['health'] == rows['water_1']['player']['health'], rows
    if reference is None:
        assert rows['hot_1']['player'] == dict(health=16, fire=199, hurttime=9), rows['hot_1']
        assert rows['hot_1']['lava_sheep'] == dict(health=4, fire=200, hurttime=10), rows['hot_1']
        assert rows['hot_1']['smoke_sheep'] == dict(health=6, fire=40, hurttime=10), rows['hot_1']
        assert rows['hot_1']['lava_blaze'] == dict(health=20, fire=0, hurttime=0), rows['hot_1']
        assert rows['hot_1']['water_blaze'] == dict(health=18, fire=0, hurttime=10), rows['hot_1']
        assert rows['hot_1']['resistant_sheep'] == dict(health=8, fire=200, hurttime=0), rows['hot_1']
        assert rows['water_1']['lava_sheep']['fire'] == rows['water_1']['resistant_sheep']['fire'] == 0, rows
        return

    for phase, expected in reference['rows'].items():
        for name in LANES:
            if name != 'player':
                assert rows[phase][name] == expected[name], (phase, name, rows[phase][name], expected[name])
    # A client player keeps simulating between native control queries while
    # world time is frozen. Compare the real first hit, fire state and the
    # first wet tick without equating its inter-query vanilla fire countdown.
    first, *_ = rows['native_fan_hits']
    assert first['taken'] == 4 and first['health'] == 16, first


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--java', action='store_true')
    for key in ('game', 'resources', 'ctl', 'create-jar', 'reference'):
        parser.add_argument('--' + key, type=Path)
    args = parser.parse_args()
    session = None
    reference = None
    if args.java:
        work = Path(tempfile.mkdtemp(prefix='fan-hazard-java-', dir=ROOT / '.local'))
    else:
        if not all((args.game, args.resources, args.ctl, args.create_jar, args.reference)):
            parser.error('Horizon requires --game, --resources, --ctl, --create-jar and --reference')
        reference = json.loads(args.reference.read_text())
        assert reference['passed'] and reference['create'] == PINS['create_revision'], reference
        session = NativeCheckSession(args.game, args.resources, args.ctl, args.create_jar,
                                     name='fan-hazard-native', graphics=False, world='CreateFanHazard')
        session.env.pop('CREATE_HORIZON_PARTICLE_TRACE', None)
        work = session.scratch
    print(work, flush=True)
    report = dict(passed=False, create=PINS['create_revision'])
    try:
        rows = native(session) if session else java(work)
        report['rows'] = rows
        verify(rows, reference)
        report['passed'] = True
    finally:
        if session:
            session.control_temp.cleanup()
            for folder in (session.resources, work / '.horizon-cache', work / 'horizon-mods'):
                shutil.rmtree(folder, ignore_errors=True)
        (work / 'result.json').write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    main()
