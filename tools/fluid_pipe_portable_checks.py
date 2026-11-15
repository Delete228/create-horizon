#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Compare dropped item and arrow fire timers at actual open pipe outlets."""

import argparse
import json
from pathlib import Path
import re
import shutil
import tempfile

from bearing_native_checks import Batch
from burner_heat_java_checks import number
from chain_drive_checks import Original
from common import PINS, ROOT
from fluid_pipe_douse_checks import LAVA, WATER
from fluid_pipe_effect_checks import AIR, AMOUNT, AREA, LOAD, X, Y, Z, amount, setup
from fluid_pump_java_checks import seed
from funnel_checks import put
from native_check_session import NativeCheckSession
from reference_java import BASE, CREATE_SHA256

TICKS = 27
ITEMS = {
    'lava_item': ('lava', 'minecraft:stick', 0),
    'lava_prototype': ('lava', 'minecraft:netherite_ingot', 0),
    'lava_override': ('lava', 'minecraft:apple', 0),
    'water_item': ('water', 'minecraft:stick', 299),
}
ARROWS = {
    'lava_arrow': ('lava', 'minecraft:arrow', 0),
    'lava_spectral': ('lava', 'minecraft:spectral_arrow', 0),
    'water_arrow': ('water', 'minecraft:arrow', 299),
}
RIGS = dict(lava=LAVA, water=WATER)
CASES = (*ITEMS, *ARROWS)
POSITIONS = [rig[key] for rig in RIGS.values() for key in ('tank', 'out')]


def power(command, original):
    for medium, rig in RIGS.items():
        command(seed(rig['tank'], medium, AMOUNT))
    for name, (medium, item, fire) in ITEMS.items():
        x, y, z = RIGS[medium]['out']
        data = ''
        if name == 'lava_override':
            data = (',components:{"minecraft:fire_resistant":{}}' if original else
                    ',components:{"minecraft:damage_resistant":{types:"#minecraft:is_fire"}}')
        command(f'summon minecraft:item {x+.3} {y-.4} {z+.5} '
                f'{{Tags:["pipe_portable_{name}"],NoGravity:1b,Motion:[0d,0d,0d],'
                f'Fire:{fire}s,Health:5s,PickupDelay:32767s,Item:{{id:"{item}",count:1{data}}}}}')
    for name, (medium, kind, fire) in ARROWS.items():
        x, y, z = RIGS[medium]['out']
        command(f'summon {kind} {x+.7} {y-.5} {z+.5} '
                f'{{Tags:["pipe_portable_{name}"],NoGravity:1b,Motion:[0d,0d,0d],Fire:{fire}s}}')
    for rig in RIGS.values():
        put(command, rig['motor'], 'create:creative_motor[facing=east]{ScrollValue:32}')


def read(raw, name):
    record = {'nbt': raw}
    row = dict(fire=int(number(record, 'Fire')))
    if name in ITEMS:
        row['health'] = int(number(record, 'Health'))
    return row


def java(work):
    host = Original()
    initial = host.call('state', {})
    if initial['screen'] == 'PauseScreen':
        host.call('input', {'kind': 'escape'})
        initial = host.call('state', {})
    assert initial['ready'] and initial['data_version'] == 3955, initial
    assert json.loads((BASE / 'manifest.json').read_text())['create_sha256'] == CREATE_SHA256
    host.call('tick', {'frozen': True})
    try:
        host.command(f'forceload add {LOAD}')
        host.command(f'tp @s {X}.5 {Y+5} {Z+5}.5')
        host.call('observe_ticks', {'ticks': 40, 'positions': POSITIONS})
        setup(host.command)
        host.call('observe_ticks', {'ticks': 28, 'positions': POSITIONS})
        power(host.command, original=True)
        rows = []
        for _ in range(TICKS):
            frame, = host.call('observe_ticks', {'ticks': 1, 'positions': POSITIONS})['samples']
            entities = host.call('entities', {'center': (X, Y, Z+5), 'radius': 11})['entities']
            sample = {}
            for entity in entities:
                tag = re.search(r'"pipe_portable_(\w+)"', entity['nbt'])
                if tag:
                    sample[tag[1]] = read(entity['nbt'], tag[1])
            assert sample.keys() == set(CASES), entities
            tanks = {kind: amount(frame['blocks'][2*i]['nbt']) for i, kind in enumerate(RIGS)}
            assert all(frame['blocks'][i]['id'] == AIR for i in (1, 3)), frame
            rows.append(dict(time=frame['game_time'], tanks=tanks, portable=sample))
        return rows
    finally:
        for name in CASES:
            host.command(f'kill @e[tag=pipe_portable_{name}]')
        host.command(f'fill {AREA} {AIR}')
        host.command(f'forceload remove {LOAD}')
        host.call('camera', {key: initial[key] for key in ('position', 'yaw', 'pitch')})
        host.call('tick', {'frozen': initial['server']['frozen']})
        (work / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')


def native(session):
    batch = Batch()
    batch.load((X, Y+3, Z+5))
    setup(batch.command)
    batch.tick(28)
    power(batch.command, original=False)
    for _ in range(TICKS):
        batch.tick(1)
        batch.command('time query gametime', True)
        for rig in RIGS.values():
            batch.data(rig['tank'])
            batch.expect(rig['out'], AIR)
        for name in CASES:
            batch.command(f'data get entity @e[tag=pipe_portable_{name},limit=1]', True)
    outputs = iter(batch.run(session, 'pipe-portable'))
    rows = []
    for _ in range(TICKS):
        raw = next(outputs)
        times = re.findall(r'\b\d+\b', raw)
        assert len(times) == 1, raw
        tanks = {}
        for kind in RIGS:
            tanks[kind] = amount(next(outputs))
            assert 'bearing_check' in next(outputs), kind
        sample = {name: read(next(outputs), name) for name in CASES}
        rows.append(dict(time=int(times[0]), tanks=tanks, portable=sample))
    assert next(outputs, None) is None
    return rows


def verify(rows):
    events = {}
    for name in ('lava_item', 'lava_arrow', 'lava_spectral', 'water_item', 'water_arrow'):
        wet = name.startswith('water_')
        medium = 'water' if wet else 'lava'
        actual = [row['portable'][name]['fire'] <= 0 if wet else row['portable'][name]['fire'] > 0
                  for row in rows]
        assert not actual[0] and any(actual), (name, rows[0], rows[-1])
        index = actual.index(True)
        before, now, after = rows[index-1:index+2]
        assert now['time'] % 5 == 0 and now['tanks'][medium] < before['tanks'][medium], (name, before, now)
        state = now['portable'][name]
        assert state['fire'] == (0 if wet else 60), (name, state)
        next_fire = after['portable'][name]['fire']
        assert (next_fire <= 0 if wet else next_fire == 59), (name, after)
        if name == 'lava_item':
            assert state['health'] == 5 and after['portable'][name]['health'] == 4, (name, state, after)
        events[name] = state['fire']
    for name in ('lava_prototype', 'lava_override'):
        assert all(row['portable'][name]['fire'] <= 0 and row['portable'][name]['health'] == 5
                   for row in rows), name
        events[name] = 0
    return events


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--java', action='store_true')
    for key in ('game', 'resources', 'ctl', 'create-jar', 'reference'):
        parser.add_argument('--' + key, type=Path)
    args = parser.parse_args()
    session = None
    if args.java:
        work = Path(tempfile.mkdtemp(prefix='pipe-portable-java-', dir=ROOT / '.local'))
    else:
        if not all((args.game, args.resources, args.ctl, args.create_jar, args.reference)):
            parser.error('Horizon requires --game, --resources, --ctl, --create-jar and --reference')
        reference = json.loads(args.reference.read_text())
        assert reference['passed'] and reference['create'] == PINS['create_revision']
        session = NativeCheckSession(args.game, args.resources, args.ctl, args.create_jar,
                                     name='pipe-portable-native', graphics=False, world='CreatePipePortable')
        session.env.pop('CREATE_HORIZON_PARTICLE_TRACE', None)
        work = session.scratch
    print(work, flush=True)
    report = dict(passed=False, create=PINS['create_revision'])
    try:
        report['rows'] = native(session) if session else java(work)
        events = verify(report['rows'])
        if session:
            assert events == reference['events']
        report.update(events=events, passed=True)
    finally:
        if session:
            session.control_temp.cleanup()
            for folder in (session.resources, work / '.horizon-cache', work / 'horizon-mods'):
                shutil.rmtree(folder, ignore_errors=True)
        (work / 'result.json').write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    main()
