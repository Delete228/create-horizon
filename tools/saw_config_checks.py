#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Compare bulk Saw input and the original stonecutting server option."""

import argparse
import json
from pathlib import Path
import re
import shutil
import tempfile
import time

from bearing_native_checks import Batch
from burner_heat_java_checks import field, items, number
from chain_drive_checks import Native, Original, xyz
from common import PINS, ROOT
from fan_config_checks import configure_java
from native_check_session import NativeCheckSession, wait_loaded
import reference_java as java


X, Y = 2252, 126
AREA = '2248 124 1380 2255 129 1396'
TICKET = '2240 1376 2255 1407'
SETTINGS = {'bulkCutting': 'true', 'allowStonecuttingOnSaw': 'false'}
RELOADED = {'bulkCutting': 'false', 'allowStonecuttingOnSaw': 'true'}
LOG, STRIPPED, STONE = 'minecraft:oak_log', 'minecraft:stripped_oak_log', 'minecraft:stone'
MARK = 'saw_config_marker'
LANES = {'belt': (1382, LOG, 11), 'chute': (1386, LOG, 22), 'stone': (1390, STONE, 33),
         'drop': (1394, LOG, 44)}


def probes(name):
    z = LANES[name][0]
    inlet = (X - 3, Y, z) if name == 'belt' else (X - 1, Y, z) if name == 'drop' else (X, Y + 1, z)
    return inlet, (X, Y, z), (X + 1, Y - 1, z)


POINTS = [pos for lane in LANES for pos in probes(lane)]
HOT_POINTS = [(X, Y, z) for z in (1382, 1386, 1390, 1394)]


def stack(item, marker, count=12):
    return f'id:"{item}",count:{count},components:{{"minecraft:custom_data":{{{MARK}:{marker}}}}}'


def setup(cmd, tick, *, native=False):
    cmd(f'fill {AREA} minecraft:air')
    for name, (z, _, _) in LANES.items():
        cmd(f'setblock {X + 1} {Y - 1} {z} minecraft:chest')
        cmd(f'setblock {X + 1} {Y} {z} create:chute[facing=down,shape=window]')
        cmd(f'setblock {X} {Y} {z} create:mechanical_saw[facing=up,axis_along_first=false]')
        if name == 'belt':
            for index, part in enumerate(('start', 'middle', 'end')):
                cmd(f'setblock {X - 3 + index} {Y} {z} create:belt[facing=east,slope=horizontal,part={part}]')
            cmd(f'setblock {X - 3} {Y} {z - 1} create:creative_motor[facing=south]{{ScrollValue:-32}}')
        elif name == 'drop':
            cmd(f'setblock {X - 1} {Y} {z} minecraft:barrel')
        else:
            cmd(f'setblock {X} {Y + 1} {z} create:chute[facing=down,shape=window]')
    tick(24)
    for name, (z, item, marker) in LANES.items():
        inlet, _, _ = probes(name)
        item = stack(item, marker)
        if name == 'belt':
            cmd(f'data merge block {xyz(inlet)} {{Inventory:{{PositiveOrder:1b,Items:[{{Item:{{{item}}},'
                'Pos:2.65f,PrevPos:2.65f,InDirection:5,InSegment:2,Angle:180}]}}')
        elif name != 'drop':
            live = f',Items:[{{Slot:0b,{item}}}]' if native else ''
            cmd(f'data merge block {xyz(inlet)} {{Item:{{{item}}},ItemPosition:1f{live}}}')


def power(cmd):
    for z, _, _ in LANES.values():
        cmd(f'setblock {X} {Y} {z - 1} create:creative_motor[facing=south]{{ScrollValue:128}}')
    z, item, marker = LANES['drop']
    cmd(f'summon minecraft:item {X + .5} {Y + 2.4} {z + .5} '
        f'{{Item:{{{stack(item, marker)}}},PickupDelay:32767s}}')


def snapshot(rows):
    sample = {}
    for name, inlet, saw, chest in zip(LANES, rows[::3], rows[1::3], rows[2::3], strict=True):
        inlet_key = 'Inventory' if name == 'belt' else 'Item'
        saw_items = field(saw, 'Inventory')
        chest_items = field(chest, 'Items') if re.search(r'\bItems\s*:', chest) else ''
        sample[name] = dict(
            inlet=items(inlet, inlet_key) if re.search(r'\b' + inlet_key + r'\s*:', inlet) else {},
            saw=items(saw, 'Inventory'), chest=items(chest, 'Items') if chest_items else {},
            saw_marker=int(number({'nbt': saw_items}, MARK, 0)),
            chest_marker=int(number({'nbt': chest_items}, MARK, 0)),
            duration=number({'nbt': saw_items}, 'RecipeTime', 0),
        )
    return sample


def verify(result):
    for name, (_, item, marker) in LANES.items():
        warm = result['warm'][name]
        assert warm['saw'] == ({} if name == 'drop' else {item: 12}), (name, warm)
        assert not warm['inlet'] and not warm['chest'], (name, warm)
        assert warm['saw_marker'] == (0 if name == 'drop' else marker), (name, warm)
        assert warm['duration'] == (0 if name == 'drop' else 10 if name == 'stone' else 100), (name, warm)
        end = result['finished'][name]
        assert end['chest'] == {STONE if name == 'stone' else STRIPPED: 12}, (name, end)
        assert end['chest_marker'] == (marker if name == 'stone' else 0), (name, end)
        assert not end['inlet'] and not end['saw'], (name, end)
    if 'cold' in result:
        assert result['cold'] == result['warm'], result


def verify_hot(result):
    assert result == {
        'initial_policy': {'count': 1, 'inlet': 0, 'duration': 10.0},
        'existing_saw': {'count': 12, 'inlet': 0, 'duration': 100.0},
        'new_saw': {'count': 1, 'inlet': 11, 'duration': 50.0},
        'cached_stonecutting': {'count': 1, 'inlet': 0, 'duration': 10.0},
        'after_data_reload': {'count': 1, 'inlet': 0, 'duration': 50.0},
    }, result


def hot_scenario(host, write_config):
    cmd = host.command
    existing, new, initial, cached = HOT_POINTS
    native = isinstance(host, Native)

    def install(pos):
        cmd(f'setblock {xyz(pos)} create:mechanical_saw[facing=up,axis_along_first=false]')
        x, y, z = pos
        inlet = x, y + 1, z
        cmd(f'setblock {xyz(inlet)} create:chute[facing=down,shape=window]')
        return inlet

    def feed(pos, inlet, item, count):
        payload = stack(item, 55, count)
        bridge = f',Items:[{{Slot:0b,{payload}}}]' if native else ''
        cmd(f'data merge block {xyz(inlet)} {{Item:{{{payload}}},ItemPosition:1f{bridge}}}')
        saw, chute = [row['nbt'] for row in host.snapshot([pos, inlet], 18)]
        contents = items(saw, 'Inventory')
        assert contents.keys() == {item} and int(number({'nbt': saw}, MARK)) == 55, saw
        remainder = items(chute, 'Item') if re.search(r'\bItem\s*:', chute) else {}
        return dict(count=contents[item], inlet=remainder.get(item, 0),
                    duration=number({'nbt': saw}, 'RecipeTime'))

    cmd(f'fill {AREA} minecraft:air')
    existing_inlet = install(existing)
    initial_inlet = install(initial)
    host.snapshot([existing, initial], 18)
    result = {'initial_policy': feed(initial, initial_inlet, STONE, 1)}
    write_config(RELOADED)
    time.sleep(2)
    new_inlet, cached_inlet = install(new), install(cached)
    host.snapshot([existing, new, cached], 18)
    result['existing_saw'] = feed(existing, existing_inlet, LOG, 12)
    result['new_saw'] = feed(new, new_inlet, LOG, 12)
    result['cached_stonecutting'] = feed(cached, cached_inlet, STONE, 1)
    cmd('reload')
    time.sleep(2)
    cmd(f'setblock {xyz(cached)} minecraft:air')
    cmd(f'setblock {xyz(cached_inlet)} minecraft:air')
    fresh_inlet = install(cached)
    host.snapshot([cached, fresh_inlet], 18)
    result['after_data_reload'] = feed(cached, fresh_inlet, STONE, 1)
    return result


def java_run(work, hot=False):
    host = Original()
    manifest = json.loads((java.BASE / 'manifest.json').read_text())
    initial = host.call('state', {})
    assert manifest['create_sha256'] == java.CREATE_SHA256 and initial['data_version'] == 3955
    config = java.BASE / 'game/config/create-server.toml'
    previous = config.read_bytes()

    def tick(ticks):
        return host.snapshot(POINTS, ticks)

    host.call('tick', {'frozen': True})
    try:
        configure_java(config, previous, SETTINGS)
        time.sleep(2)
        host.command('reload')
        time.sleep(2)
        host.command(f'forceload add {TICKET}')
        tick(24)
        if hot:
            return hot_scenario(host, lambda settings: configure_java(config, previous, settings))
        setup(host.command, tick)
        warm = snapshot([row['nbt'] for row in tick(24)])
        power(host.command)
        for _ in range(3):
            end = tick(48)
        return dict(warm=warm, finished=snapshot([row['nbt'] for row in end]))
    finally:
        config.write_bytes(previous)
        host.command(f'fill {AREA} minecraft:air')
        host.command(f'forceload remove {TICKET}')
        host.command('reload')
        host.call('tick', {'frozen': initial['server']['frozen']})
        (work / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')


def native_run(session, hot=False):
    config = session.scratch / 'config/create-server.toml'
    config.parent.mkdir(exist_ok=True)

    def write_config(settings):
        config.write_text('[recipes]\n' + ''.join(f'{key} = {value}\n' for key, value in settings.items()))

    write_config(SETTINGS)
    if hot:
        host = Native(session)
        with session:
            host.command(f'tp @s {X + .5} {Y + 3} 1388.5')
            wait_loaded(session.call, HOT_POINTS)
            return hot_scenario(host, write_config)

    def probe(batch):
        for pos in POINTS:
            batch.data(pos)

    batch = Batch()
    batch.load((X, Y + 3, 1388))
    setup(batch.command, batch.tick, native=True)
    batch.tick(24)
    probe(batch)
    warm = snapshot(batch.run(session, 'bulk-saw-buffered'))
    batch = Batch()
    batch.load((X, Y + 3, 1388))
    probe(batch)
    power(batch.command)
    batch.tick(144)
    probe(batch)
    rows = batch.run(session, 'bulk-saw-resumed')
    return dict(warm=warm, cold=snapshot(rows[:len(POINTS)]), finished=snapshot(rows[len(POINTS):]))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--java', action='store_true')
    parser.add_argument('--hot-toggle', action='store_true')
    for flag in ('game', 'resources', 'ctl', 'reference', 'create-jar'):
        parser.add_argument('--' + flag, type=Path)
    args = parser.parse_args()
    label = 'saw-config-hot' if args.hot_toggle else 'saw-config'
    if args.java:
        work = Path(tempfile.mkdtemp(prefix=f'{label}-java-', dir=ROOT / '.local'))
        print(work, flush=True)
        result = java_run(work, args.hot_toggle)
    else:
        if not all((args.game, args.resources, args.ctl, args.reference, args.create_jar)):
            parser.error('Horizon requires --game, --resources, --ctl, --reference and --create-jar')
        reference = json.loads(args.reference.read_text())
        assert reference['create'] == PINS['create_revision'] and reference['passed'], reference
        assert reference.get('hot_toggle', False) == args.hot_toggle, reference
        session = NativeCheckSession(args.game, args.resources, args.ctl, args.create_jar,
                                     name=f'{label}-native', graphics=args.hot_toggle, world='CreateSawConfig')
        work = session.scratch
        print(work, flush=True)
        try:
            result = native_run(session, args.hot_toggle)
        finally:
            session.control_temp.cleanup()
            for folder in (session.resources, work / '.horizon-cache', work / 'horizon-mods'):
                shutil.rmtree(folder, ignore_errors=True)
        assert {phase: result[phase] for phase in reference['cases']} == reference['cases'], (result, reference)
    (verify_hot if args.hot_toggle else verify)(result)
    path = work / 'result.json'
    path.write_text(json.dumps(dict(passed=True, create=PINS['create_revision'], hot_toggle=args.hot_toggle,
                                    cases=result), indent=2) + '\n')
    print(path)


if __name__ == '__main__':
    main()
