#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Check Create's bulkPressing setting in world, Depot and Belt modes."""

import argparse
from collections import Counter
import json
from pathlib import Path
import re
import shutil
import tempfile
import time

from burner_heat_java_checks import items, number
from chain_drive_checks import Native, Original, xyz
from common import PINS, ROOT
from fan_config_checks import configure_java
from native_check_session import NativeCheckSession, wait_loaded
from press_world_checks import drive, selected
import reference_java as java


X, Y, Z = 2628, 175, 1558
LANES = {name: Z + 5 * i for i, name in enumerate(('world', 'depot', 'belt', 'reload'))}
PRESS = [(X, Y + 2, z) for z in LANES.values()]
AREA = '2624 173 1556 2632 180 1575'
LOAD = '2624 1552 2639 1583'
CAMERA = (X + .5, Y + 4, Z + 5.5)
DROPS = f'@e[type=minecraft:item,x={X},y={Y},z={Z+7},distance=..12]'
COPPER, IRON = 'minecraft:copper_ingot', 'minecraft:iron_ingot'
SHEET = 'create:copper_sheet'


def setblock(host, pos, state):
    host.command(f'setblock {xyz(pos)} {state}')


def stack(item, count):
    return f'{{id:"{item}",count:{count},components:{{"minecraft:custom_data":{{press_bulk_probe:17}}}}}}'


def drop(host, z, offset, item, count, tag):
    host.command(f'summon minecraft:item {X+offset} {Y+1} {z+.5} '
                 f'{{Tags:["{tag}"],PickupDelay:32767s,Motion:[0d,0d,0d],Item:{stack(item, count)}}}')


def stocks(host, z, prefix):
    drop(host, z, .25, 'minecraft:stone', 1, prefix + '_stone')
    drop(host, z, .50, COPPER, 4, prefix + '_copper')
    if prefix == 'bulk':
        drop(host, z, .75, IRON, 6, prefix + '_iron')


def setup(host):
    host.command(f'kill {DROPS}')
    host.command(f'fill {AREA} minecraft:air')
    host.command('fill 2625 174 1557 2631 174 1574 minecraft:smooth_stone')
    for pos in PRESS:
        setblock(host, pos, 'create:mechanical_press[facing=east]')
    for lane in ('world', 'reload'):
        setblock(host, (X, Y, LANES[lane]), 'minecraft:smooth_stone')
    setblock(host, (X, Y, LANES['depot']), 'create:depot')
    z = LANES['belt']
    for index, part in enumerate(('start', 'middle', 'middle', 'middle', 'end')):
        setblock(host, (X-2+index, Y, z), f'create:belt[facing=east,slope=horizontal,part={part}]')
    setblock(host, (X+3, Y, z), 'create:depot')
    setblock(host, (X-2, Y, z-1), 'create:creative_motor[facing=south]{ScrollValue:-16}')
    host.snapshot(PRESS, 24)
    host.command(f'data merge block {X} {Y} {LANES["depot"]} '
                 + '{HeldItem:{Item:' + stack(COPPER, 7)
                 + ',Pos:.5f,PrevPos:.5f,InDirection:5,Angle:180}}')
    stocks(host, LANES['world'], 'bulk')
    for pos in PRESS[:3]:
        drive(host, pos)
    host.snapshot(PRESS, 6)
    host.command(f'data merge block {X-2} {Y} {z} '
                 + '{Inventory:{PositiveOrder:1b,Items:[{Item:' + stack(COPPER, 9)
                 + ',Pos:2.25f,PrevPos:2.25f,InDirection:5,InSegment:2,Angle:180}]}}')


def stock(host, tag):
    data = selected(host, f'@e[type=minecraft:item,tag={tag},limit=1]', 'Item')
    match = re.search(r'\bid\s*:\s*"([^"]+)"', data)
    assert match, data
    return dict(item=match[1], count=int(number({'nbt': data}, 'count')),
                marker=int(number({'nbt': data}, 'press_bulk_probe', 0)))


def total(rows):
    found = Counter()
    for row in rows:
        for key in ('Inventory', 'HeldItem', 'OutputBuffer'):
            if re.search(r'\b' + key + r'\s*:', row['nbt']):
                found.update(items(row['nbt'], key))
    return dict(found)


def cases(host, setting):
    setup(host)
    z = LANES['belt']
    probes = [(X, Y, LANES['depot']), (X-2, Y, z), (X+3, Y, z)]
    depot, *belt = host.snapshot(probes, 40)
    bulk = dict(world={item: stock(host, 'bulk_' + item) for item in ('stone', 'copper', 'iron')},
                depot=total([depot]), belt=total(belt))
    assert bulk['world'] == {
        'stone': {'item': 'minecraft:stone', 'count': 1, 'marker': 17},
        'copper': {'item': SHEET, 'count': 4, 'marker': 0},
        'iron': {'item': 'create:iron_sheet', 'count': 6, 'marker': 0},
    }, bulk
    assert bulk['depot'] == {SHEET: 7} and bulk['belt'] == {SHEET: 9}, bulk
    setting(False)
    stocks(host, LANES['reload'], 'reloaded')
    drive(host, PRESS[-1])
    [press] = host.snapshot([PRESS[-1]], 40)
    assert abs(press['speed']) == 64 and (number(press, 'Ticks', 0) > 120
                                         or number(press, 'Finished', 0)), press
    reloaded = stock(host, 'reloaded_copper')
    assert reloaded == {'item': COPPER, 'count': 4, 'marker': 17}, reloaded
    return dict(bulk=bulk, hot_nonbulk=reloaded)


def java_run(work):
    host = Original()
    initial = host.call('state', {})
    manifest = json.loads((java.BASE / 'manifest.json').read_text())
    assert initial['data_version'] == 3955 and manifest['create_sha256'] == java.CREATE_SHA256
    config = java.BASE / 'game/config/create-server.toml'
    previous = config.read_bytes()

    def setting(enabled):
        configure_java(config, previous, {'bulkPressing': str(enabled).lower()})
        time.sleep(2)
        host.command('reload')
        time.sleep(2)

    host.call('tick', {'frozen': True})
    try:
        setting(True)
        host.command(f'forceload add {LOAD}')
        host.command('tp @s ' + xyz(CAMERA))
        host.snapshot(PRESS, 24)
        return cases(host, setting)
    finally:
        config.write_bytes(previous)
        host.command('reload')
        host.command(f'kill {DROPS}')
        host.command(f'fill {AREA} minecraft:air')
        host.command(f'forceload remove {LOAD}')
        host.call('camera', {key: initial[key] for key in ('position', 'yaw', 'pitch')})
        host.call('tick', {'frozen': initial['server']['frozen']})
        (work / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')


def native_run(session):
    config = session.scratch / 'config/create-server.toml'
    config.parent.mkdir(exist_ok=True)
    config.write_text('[recipes]\nbulkPressing = true\n')
    with session:
        host = Native(session)
        host.command('tp @s ' + xyz(CAMERA))
        wait_loaded(session.call, PRESS)

        def setting(enabled):
            config.write_text('[recipes]\nbulkPressing = ' + str(enabled).lower() + '\n')
            host.command('reload')
            host.snapshot(PRESS, 20)

        result = cases(host, setting)
    prefix = 'Create press client: '
    packets = [json.loads(line.split(prefix, 1)[1]) for line in session.log.read_text().splitlines()
               if prefix in line]
    bursts = Counter((tuple(row['pos']), row['particle_requests']) for row in packets
                     if row['event'] == 'packet' and row['particle_requests'])
    assert bursts == Counter({(PRESS[0], 30): 1, (PRESS[1], 15): 1, (PRESS[2], 15): 1}), bursts
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--java', action='store_true')
    for flag in ('game', 'resources', 'ctl', 'reference', 'create-jar'):
        parser.add_argument('--' + flag, type=Path)
    args = parser.parse_args()
    if args.java:
        work = Path(tempfile.mkdtemp(prefix='press-bulk-java-', dir=ROOT / '.local'))
        print(work, flush=True)
        result = java_run(work)
    else:
        if not all((args.game, args.resources, args.ctl, args.reference, args.create_jar)):
            parser.error('Horizon requires --game, --resources, --ctl, --reference and --create-jar')
        reference = json.loads(args.reference.read_text())
        assert reference['passed'] and reference['create'] == PINS['create_revision'], reference
        session = NativeCheckSession(args.game, args.resources, args.ctl, args.create_jar,
                                     name='press-bulk-native', world='PressBulk', graphics=False)
        work = session.scratch
        print(work, flush=True)
        try:
            result = native_run(session)
        finally:
            for folder in (session.resources, work / '.horizon-cache', work / 'horizon-mods'):
                shutil.rmtree(folder, ignore_errors=True)
        assert result == reference['cases'], (result, reference)
    path = work / 'result.json'
    path.write_text(json.dumps(dict(passed=True, create=PINS['create_revision'], cases=result), indent=2) + '\n')
    print(path)


if __name__ == '__main__':
    main()
