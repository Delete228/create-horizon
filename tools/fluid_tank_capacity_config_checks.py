#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Compare configured Fluid Tank capacity before and after a hot reload."""

import argparse
import json
from pathlib import Path
import shutil
import tempfile
import time

from burner_heat_java_checks import field
from chain_drive_checks import Native, Original, xyz
from common import PINS, ROOT
from fan_config_checks import configure_java
from fluid_pump_java_checks import PUMP, TANK, fluid, seed
from fluid_tank_checks import goggles_snapshot, goggles_translations
from funnel_checks import put
from native_check_session import NativeCheckSession, wait_loaded
import reference_java as java


X, Y, Z = 2671, 173, 1525
LOAD = '2656 1520 2687 1551'
AREA = '2666 171 1521 2676 176 1547'
LANES = dict(old_single=(0, 1, 1), old_wide=(7, 2, 1), new_single=(14, 1, 1))
CAMERA = (X+.5, Y+3, Z+7.5)


def lane(name):
    offset, _, _ = LANES[name]
    z = Z+offset
    return (X-2, Y, z), (X-1, Y, z), (X, Y, z)


def setup(command, names):
    for name in names:
        source, pump, (x,y,z) = lane(name)
        _, width, height = LANES[name]
        command(f'fill {x} {y} {z} {x+width-1} {y+height-1} {z+width-1} {TANK}')
        put(command, source, TANK)
        put(command, pump, PUMP+'[facing=east,waterlogged=false]')
        put(command, (pump[0], Y-1, z), 'create:cogwheel[axis=x]')
        put(command, (x, Y-1, z+width+1), 'minecraft:smooth_stone')


def power(command):
    for name in LANES:
        source, _, _ = lane(name)
        command(seed(source, 'water', 24000))
        put(command, (source[0], Y-1, source[2]), 'create:creative_motor[facing=east]{ScrollValue:256}')


def snapshot(blocks):
    return {name: (fluid(field(raw, 'TankContent')) or {}).get('amount', 0)
            for name, raw in zip(LANES, blocks, strict=True)}


def visual_state(host, work, prefix):
    translations = goggles_translations()
    rows = {}
    for name, (_, width, _) in LANES.items():
        x, y, z = lane(name)[2]
        rows[name] = goggles_snapshot(host, work, prefix+'-'+name, (x,y,z+width-1),
                                      translations, floor_y=Y)
    return rows


def cold_java(host):
    host.call('quit', {})
    deadline = time.monotonic() + 60
    while java.process_alive(java.BASE):
        if time.monotonic() >= deadline:
            raise RuntimeError('The private Java client did not save and exit')
        time.sleep(.2)
    assert java.launch(java.BASE)['ready']
    host.call('tick', {'frozen': True})


def java_run(work, visual, cold):
    host = Original()
    initial = host.call('state', {})
    assert initial['ready'] and initial['data_version'] == 3955, initial
    config = java.BASE / 'game/config/create-server.toml'
    original = config.read_bytes()
    positions = [lane(name)[2] for name in LANES]

    def configure(buckets):
        configure_java(config, original, dict(fluidTankCapacity=buckets))
        time.sleep(2)

    host.call('tick', {'frozen': True})
    try:
        if visual and initial['language'] != 'en_us':
            host.call('language', {'language': 'en_us'})
        configure(4)
        host.command(f'forceload add {LOAD}')
        host.call('observe_ticks', {'positions': positions, 'ticks': 16})
        host.command(f'fill {AREA} minecraft:air')
        setup(host.command, ('old_single', 'old_wide'))
        host.call('observe_ticks', {'positions': positions, 'ticks': 40})
        configure(2)
        host.call('observe_ticks', {'positions': positions, 'ticks': 16})
        setup(host.command, ('new_single',))
        host.call('observe_ticks', {'positions': positions, 'ticks': 40})
        commands = []
        power(commands.append)
        rows = host.call('observe_ticks', {'positions': positions, 'ticks': 168,
                                           'commands': commands})['samples']
        values = snapshot([row['nbt'] for row in rows[-1]['blocks']])
        extras = {'visual': visual_state(host, work, 'hot') if visual else None}
        if cold:
            cold_java(host)
            extras['cold'] = snapshot([host.call('block', {'pos': pos})['nbt'] for pos in positions])
            if visual:
                extras['cold_visual'] = visual_state(host, work, 'cold')
            commands = [seed(pos, 'water', 1000) for pos in positions]
            rows = host.call('observe_ticks', {'positions': positions, 'ticks': 168,
                                               'commands': commands})['samples']
            extras['cold_refill'] = snapshot([row['nbt'] for row in rows[-1]['blocks']])
        return values, extras
    finally:
        config.write_bytes(original)
        host.command(f'fill {AREA} minecraft:air')
        host.command(f'forceload remove {LOAD}')
        if visual:
            host.command(f'item replace entity @s armor.head with {initial["head"]}')
            if initial['language'] != 'en_us':
                host.call('language', {'language': initial['language']})
            host.call('camera', {key: initial[key] for key in ('position','yaw','pitch')})
        host.call('tick', {'frozen': initial['server']['frozen']})
        (work / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')


def native_run(session, visual, cold):
    config = session.scratch / 'config/create-server.toml'
    config.parent.mkdir(exist_ok=True)

    def configure(buckets):
        config.write_text(f'[fluids]\nfluidTankCapacity = {buckets}\n')

    configure(4)
    host = Native(session)
    positions = [lane(name)[2] for name in LANES]

    def read():
        return snapshot([' '.join(host.command('data get block '+xyz(pos))['chat']) for pos in positions])

    with session:
        host.command('tp @s ' + xyz(CAMERA))
        wait_loaded(session.call, positions)
        host.command(f'fill {AREA} minecraft:air')
        setup(host.command, ('old_single', 'old_wide'))
        session.call('wait', 40)
        configure(2)
        time.sleep(2)
        setup(host.command, ('new_single',))
        session.call('wait', 40)
        power(host.command)
        session.call('wait', 168)
        values = read()
        extras = {'visual': visual_state(host, session.scratch, 'hot') if visual else None}
        if cold:
            session.restart()
            wait_loaded(session.call, positions)
            extras['cold'] = read()
            if visual:
                extras['cold_visual'] = visual_state(host, session.scratch, 'cold')
            for pos in positions:
                host.command(seed(pos, 'water', 1000))
            session.call('wait', 168)
            extras['cold_refill'] = read()
    return values, extras


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--java', action='store_true')
    parser.add_argument('--visual', action='store_true', help='compare original-JAR Goggles text')
    parser.add_argument('--cold', action='store_true', help='reopen the same game with the new configuration')
    for flag in ('game', 'resources', 'ctl', 'create-jar', 'reference'):
        parser.add_argument('--'+flag, type=Path)
    args = parser.parse_args()
    if args.java:
        work = Path(tempfile.mkdtemp(prefix='tank-capacity-java-', dir=ROOT / '.local'))
        print(work, flush=True)
        values, extras = java_run(work, args.visual, args.cold)
    else:
        if not all((args.game, args.resources, args.ctl, args.create_jar, args.reference)):
            parser.error('Horizon requires --game, --resources, --ctl, --create-jar and --reference')
        session = NativeCheckSession(args.game, args.resources, args.ctl, args.create_jar,
                                     name='tank-capacity-native', world='CreateTankCapacity')
        work = session.scratch
        print(work, flush=True)
        try:
            values, extras = native_run(session, args.visual, args.cold)
        finally:
            session.control_temp.cleanup()
            for folder in (session.resources, work / '.horizon-cache', work / 'horizon-mods'):
                shutil.rmtree(folder, ignore_errors=True)
    (work / 'observed.json').write_text(json.dumps(dict(values=values, **extras), indent=2) + '\n')
    assert values == dict(old_single=4000, old_wide=16000, new_single=2000), values
    if args.cold:
        assert extras['cold'] == values, extras
        assert extras['cold_refill'] == dict(old_single=2000, old_wide=8000, new_single=2000), extras
    if not args.java:
        expected = json.loads(args.reference.read_text())
        assert expected['passed'] and expected['create'] == PINS['create_revision'] and values == expected['values']
        for key, value in extras.items():
            assert value == expected.get(key), (key, value, expected.get(key))
    result = work / 'result.json'
    result.write_text(json.dumps(dict(passed=True, create=PINS['create_revision'], values=values, **extras), indent=2) + '\n')
    print(result)


if __name__ == '__main__':
    main()
