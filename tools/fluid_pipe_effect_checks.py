#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Check water/lava outlet effects without placing a fluid source block."""

import argparse
import json
from pathlib import Path
import re
import shutil
import tempfile

from bearing_native_checks import Batch
from burner_heat_java_checks import field, number
from chain_drive_checks import Original
from common import PINS, ROOT
from fluid_pump_java_checks import PIPE, PUMP, TANK, fluid, seed
from funnel_checks import put, text
from native_check_session import NativeCheckSession
from reference_java import BASE, CREATE_SHA256

X, Y, Z = 2140, 169, 1840
LOAD = '2128 1824 2159 1887'
AREA = '2137 164 1838 2145 172 1873'
AIR = 'minecraft:air'
AMOUNT = 450
TICKS = 26
CASES = {
    'water_sheep': ('water', 'sheep', 'east'),
    'water_blaze': ('water', 'blaze', 'east'),
    'lava_sheep': ('lava', 'sheep', 'east'),
    'lava_blaze': ('lava', 'blaze', 'east'),
    'resistant_sheep': ('lava', 'sheep', 'east'),
    'down_sheep': ('lava', 'sheep', 'down'),
    'blocked_sheep': ('lava', 'sheep', 'east'),
}


def lane(name):
    z = Z + 5 * list(CASES).index(name)
    if CASES[name][2] == 'down':
        return dict(tank=(X, Y+2, z), pump=(X, Y+1, z), pipe=(X, Y, z),
                    motor=(X, Y, z-1), cog=(X, Y+1, z-1), out=(X, Y-1, z))
    return dict(tank=(X-1, Y, z), pump=(X, Y, z), pipe=(X+1, Y, z),
                motor=(X-1, Y, z-1), cog=(X, Y, z-1), out=(X+2, Y, z))


def selector(name):
    return f'@e[tag=pipe_effect_{name},limit=1]'


def setup(command):
    command(f'fill {AREA} {AIR}')
    command('fill 2137 164 1838 2145 164 1873 minecraft:smooth_stone')
    for name, (_, _, side) in CASES.items():
        at = lane(name)
        put(command, at['tank'], TANK)
        opposite, axis = ('up', 'y') if side == 'down' else ('west', 'x')
        put(command, at['pump'], f'{PUMP}[facing={side},waterlogged=false]')
        put(command, at['pipe'], f'{PIPE}[{opposite}=true,{side}=true,waterlogged=false]')
        put(command, at['cog'], f'create:cogwheel[axis={axis}]')
        if name == 'blocked_sheep':
            put(command, at['out'], 'minecraft:stone')


def load_entities(command):
    def summon(name, species, x, y, z, fire):
        command(f'summon minecraft:{species} {x} {y} {z} '
                f'{{Tags:["pipe_effect_probe","pipe_effect_{name}"],'
                f'NoAI:1b,NoGravity:1b,PersistenceRequired:1b,Silent:1b,Fire:{fire}s}}')

    for name, (medium, species, side) in CASES.items():
        at = lane(name)
        command(seed(at['tank'], medium, AMOUNT))
        x, y, z = at['out']
        lower = 2.6 if side == 'down' else 2.05 if name == 'blocked_sheep' else .4
        summon(name, species, x+.5, y-lower, z+.5, 258 if name == 'water_sheep' else 0)
        if name == 'lava_sheep':
            summon('below_side', 'sheep', x+.5, y-2.6, z+.5, 0)
        if name in ('resistant_sheep', 'water_sheep'):
            command(f'effect give {selector(name)} minecraft:fire_resistance 60 0 true')


def power(command):
    for name, (_, _, side) in CASES.items():
        face = 'up' if side == 'down' else 'east'
        put(command, lane(name)['motor'], f'create:creative_motor[facing={face}]{{ScrollValue:32}}')


def values(raw):
    assert 'Fire:' in raw and 'Health:' in raw, raw
    nbt = {'nbt': raw}
    return dict(fire=int(number(nbt, 'Fire')), health=number(nbt, 'Health'))


def amount(raw):
    stack = fluid(field(raw, 'TankContent'))
    return stack['amount'] if stack else 0


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
    positions = [lane(name)[key] for name in CASES for key in ('tank', 'out')]
    host.call('tick', {'frozen': True})
    try:
        host.command(f'forceload add {LOAD}')
        host.command(f'tp @s {X}.5 {Y+5} {Z+15}.5')
        host.call('observe_ticks', {'ticks': 40, 'positions': positions})
        setup(host.command)
        host.call('observe_ticks', {'ticks': 28, 'positions': positions})
        host.command('difficulty normal')
        put(host.command, (X, Y+4, Z+15), 'minecraft:smooth_stone')
        host.command('gamemode survival')
        load_entities(host.command)
        power(host.command)
        rows = []
        for _ in range(TICKS):
            frame, = host.call('observe_ticks', {'ticks': 1, 'positions': positions})['samples']
            batch = host.call('entities', {'center': (X, Y, Z+15), 'radius': 23})
            entities = {}
            for entity in batch['entities']:
                tag = re.search(r'"pipe_effect_(?!probe\b)(\w+)"', entity['nbt'])
                if tag:
                    entities[tag[1]] = values(entity['nbt'])
            assert entities.keys() == {*CASES, 'below_side'}, (frame, batch)
            tanks = {name: amount(frame['blocks'][2*i]['nbt']) for i, name in enumerate(CASES)}
            assert all(frame['blocks'][2*i+1]['id'] == ('minecraft:stone' if name == 'blocked_sheep' else AIR)
                       for i, name in enumerate(CASES)), frame
            rows.append(dict(time=frame['game_time'], tanks=tanks, entities=entities))
        return rows
    finally:
        host.command('kill @e[tag=pipe_effect_probe]')
        host.command(f'fill {AREA} {AIR}')
        put(host.command, (X, Y+4, Z+15), AIR)
        host.command(f'gamemode {mode}')
        host.command(f'forceload remove {LOAD}')
        host.command(f'difficulty {difficulty}')
        host.call('camera', {key: initial[key] for key in ('position', 'yaw', 'pitch')})
        host.call('tick', {'frozen': initial['server']['frozen']})
        (work / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')


def native(session):
    batch = Batch()
    batch.load((X, Y+3, Z+15))
    setup(batch.command)
    batch.tick(28)
    batch.command('difficulty normal')
    load_entities(batch.command)
    power(batch.command)
    for _ in range(TICKS):
        batch.tick(1)
        batch.command('time query gametime', True)
        for name in CASES:
            batch.data(lane(name)['tank'])
            batch.expect(lane(name)['out'], 'minecraft:stone' if name == 'blocked_sheep' else AIR)
        for name in (*CASES, 'below_side'):
            batch.command(f'data get entity {selector(name)}', True)
    outputs = iter(batch.run(session, 'pipe-effects'))
    rows = []
    for _ in range(TICKS):
        time_text = next(outputs)
        time = re.findall(r'\b\d+\b', time_text)
        assert len(time) == 1, time_text
        tanks = {}
        for name in CASES:
            tanks[name] = amount(next(outputs))
            assert 'bearing_check' in next(outputs), name
        entities = {name: values(next(outputs)) for name in (*CASES, 'below_side')}
        rows.append(dict(time=int(time[0]), tanks=tanks, entities=entities))
    assert next(outputs, None) is None
    return rows


def verify(rows):
    assert all(r['tanks']['blocked_sheep'] == AMOUNT for r in rows)
    for name in ('lava_blaze', 'water_blaze', 'below_side', 'blocked_sheep'):
        initial = rows[0]['entities'][name]
        assert initial['fire'] == 0
        assert all(row['entities'][name] == initial for row in rows), name
    events = {}
    for name in ('water_sheep', 'lava_sheep', 'resistant_sheep', 'down_sheep'):
        water = name == 'water_sheep'
        effect = [row['entities'][name]['fire'] == 0 if water else row['entities'][name]['fire'] > 0
                  for row in rows]
        assert not effect[0] and any(effect), (name, rows)
        i = effect.index(True)
        previous, current = rows[i-1:i+1]
        assert current['time'] % 5 == 0 and current['tanks'][name] < previous['tanks'][name], (name, rows)
        state = current['entities'][name]
        assert state == {'fire': 0 if water else 60, 'health': 8}, (name, state)
        if name in ('lava_sheep', 'down_sheep'):
            assert rows[i+1]['entities'][name] == {'fire': 59, 'health': 7}, (name, rows)
        else:
            assert all(row['entities'][name]['health'] == 8 for row in rows), (name, rows)
        events[name] = state
    return events


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--java', action='store_true')
    for key in ('game', 'resources', 'ctl', 'create-jar', 'reference'):
        parser.add_argument('--' + key, type=Path)
    args = parser.parse_args()
    session = None
    if args.java:
        work = Path(tempfile.mkdtemp(prefix='pipe-effects-java-', dir=ROOT / '.local'))
    else:
        if not all((args.game, args.resources, args.ctl, args.create_jar, args.reference)):
            parser.error('Horizon requires --game, --resources, --ctl, --create-jar and --reference')
        reference = json.loads(args.reference.read_text())
        assert reference['passed'] and reference['create'] == PINS['create_revision']
        session = NativeCheckSession(args.game, args.resources, args.ctl, args.create_jar,
                                     name='pipe-effects-native', graphics=False, world='CreatePipeEffects')
        session.env.pop('CREATE_HORIZON_PARTICLE_TRACE', None)
        work = session.scratch
    print(work, flush=True)
    report = dict(passed=False, create=PINS['create_revision'])
    try:
        report['rows'] = native(session) if session else java(work)
        events = verify(report['rows'])
        if session:
            assert events == reference['events'], (events, reference['events'])
        report.update(events=events, passed=True)
    finally:
        if session:
            session.control_temp.cleanup()
            for folder in (session.resources, work / '.horizon-cache', work / 'horizon-mods'):
                shutil.rmtree(folder, ignore_errors=True)
        (work / 'result.json').write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    main()
