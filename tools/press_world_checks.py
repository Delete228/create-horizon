#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Check the loose-item Press start box and first grounded strike target."""

import argparse
import json
from pathlib import Path
import re
import shutil
import tempfile

from burner_heat_java_checks import number
from chain_drive_checks import Native, Original, xyz
from common import PINS, ROOT
from funnel_checks import text
from native_check_session import NativeCheckSession, wait_loaded
import reference_java as java


PRESS = (2580, 172, 1530)
EDGE = (2580, 172, 1534)
CAMERA = (2583.5, 175, 1532.5)
REGION = '2577 169 1528 2584 176 1536'
LOAD = '2576 1520 2591 1535'
DROPS = '@e[type=minecraft:item,x=2580,y=171,z=1532,distance=..4]'
COPPER = 'minecraft:copper_ingot'
SHEET = 'create:copper_sheet'
TRACE = 'Create press world split: '


def drive(host, pos, rpm=64):
    x, y, z = pos
    state = f'create:creative_motor[facing=east]{{ScrollValue:{rpm}}}' if rpm else 'minecraft:air'
    host.command(f'setblock {x-1} {y} {z} {state}')


def drop(host, pos, item, count, tag):
    marker = ',components:{"minecraft:custom_data":{press_world_probe:7}}' if item == COPPER else ''
    host.command(f'summon minecraft:item {xyz(pos)} {{Tags:["{tag}"],PickupDelay:32767s,'
                 f'Motion:[0d,0d,0d],Item:{{id:"{item}",count:{count}{marker}}}}}')


def setup(host):
    host.command(f'kill {DROPS}')
    host.command(f'fill {REGION} minecraft:air')
    host.command('fill 2578 170 1529 2581 170 1535 minecraft:smooth_stone')
    for x, y, z in (PRESS, EDGE):
        host.command(f'setblock {x} {y} {z} create:mechanical_press[facing=east]')
    drop(host, (2580.40, 171, 1530.5), 'minecraft:stone', 1, 'create_press_blocker')
    drop(host, (2580.62, 171, 1530.5), COPPER, 4, 'create_press_stock')
    drop(host, (2579.90, 171, 1534.5), COPPER, 1, 'create_press_edge')
    host.snapshot([PRESS, EDGE], 18)
    drive(host, PRESS)
    drive(host, EDGE)


def strike(host, pos, next_cycle=False):
    before_impact = not next_cycle
    for _ in range(64):
        [press] = host.snapshot([pos], 1)
        ticks = number(press, 'Ticks', 0)
        if not number(press, 'Running', 0):
            continue
        if ticks <= 120:
            before_impact = True
        elif before_impact:
            return ticks
    raise AssertionError(('No Press impact', pos, press))


def selected(host, selector, field):
    return text(host, f'data get entity {selector} {field}')


def report_stock(host):
    raw = selected(host, '@e[type=minecraft:item,tag=create_press_stock,limit=1]', 'Item')
    return dict(count=int(number({'nbt': raw}, 'count')), marker=int(number({'nbt': raw}, 'press_world_probe')))


def cases(host):
    setup(host)
    strike(host, PRESS)
    assert report_stock(host) == {'count': 4, 'marker': 7}, report_stock(host)
    host.command('kill @e[type=minecraft:item,tag=create_press_blocker]')
    strike(host, PRESS, next_cycle=True)
    drive(host, PRESS, 0)
    assert report_stock(host) == {'count': 3, 'marker': 7}, report_stock(host)
    selector = f'@e[type=minecraft:item,x=2580.5,y=171,z=1530.5,distance=..1,nbt={{Item:{{id:"{SHEET}"}}}},limit=1]'
    sheet = selected(host, selector, 'Item')
    assert SHEET in sheet and number({'nbt': sheet}, 'count') == 1, sheet
    if isinstance(host, Original):
        velocity = selected(host, selector, 'Motion')
        vector = list(map(float, re.findall(r'(-?[\d.]+(?:[eE][+-]?\d+)?)d', velocity)))
        assert len(vector) == 3 and all(abs(value) <= .050001 for value in vector), velocity
        delay = selected(host, selector, 'PickupDelay')
        assert re.search(r':\s*10s\b', delay), delay
    [edge] = host.snapshot([EDGE], 12)
    assert edge['speed'] != 0 and number(edge, 'Ticks', 0) == 0, edge
    edge_item = '@e[type=minecraft:item,tag=create_press_edge,limit=1]'
    still_edge = selected(host, edge_item, 'Item')
    assert COPPER in still_edge and number({'nbt': still_edge}, 'count') == 1, still_edge
    # A centered stack starts a new stroke, whose larger hit box reaches the
    # first item at the edge without consuming the centered trigger stack.
    drop(host, (2580.60, 171, 1534.5), 'minecraft:iron_ingot', 2, 'create_press_trigger')
    strike(host, EDGE)
    drive(host, EDGE, 0)
    edge_output = selected(host, edge_item, 'Item')
    assert SHEET in edge_output and number({'nbt': edge_output}, 'count') == 1, edge_output
    center = selected(host, '@e[type=minecraft:item,tag=create_press_trigger,limit=1]', 'Item')
    assert 'minecraft:iron_ingot' in center and number({'nbt': center}, 'count') == 2, center
    return dict(blocked_count=4, pressed_count=3, edge_count=1, output=SHEET, edge_output=SHEET, trigger_count=2)


def java_run(work):
    host = Original()
    initial = host.call('state', {})
    manifest = json.loads((java.BASE / 'manifest.json').read_text())
    assert initial['data_version'] == 3955 and manifest['create_sha256'] == java.CREATE_SHA256
    host.call('tick', {'frozen': True})
    try:
        host.command(f'forceload add {LOAD}')
        host.command('tp @s ' + xyz(CAMERA))
        host.snapshot([PRESS, EDGE], 24)
        return cases(host)
    finally:
        host.command(f'kill {DROPS}')
        host.command(f'fill {REGION} minecraft:air')
        host.command(f'forceload remove {LOAD}')
        host.call('camera', {key: initial[key] for key in ('position', 'yaw', 'pitch')})
        host.call('tick', {'frozen': initial['server']['frozen']})
        (work / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')


def native_run(session):
    with session:
        host = Native(session)
        host.command('tp @s ' + xyz(CAMERA))
        wait_loaded(session.call, [PRESS, EDGE])
        result = cases(host)
    lines = session.log.read_text().splitlines()
    splits = [json.loads(line.split(TRACE, 1)[1]) for line in lines if TRACE in line]
    assert len(splits) == 1 and splits[0]['pickup_delay'] == 10, splits
    assert all(abs(v) <= .050001 for v in splits[0]['motion']), splits
    prefix = 'Create press client: '
    packets = [json.loads(line.split(prefix, 1)[1]) for line in lines if prefix in line]
    bursts = [row for row in packets if row['event'] == 'packet' and row['particle_requests']]
    assert [(row['pos'], row['particle_requests']) for row in bursts] == [(list(PRESS), 15), (list(EDGE), 15)], bursts
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--java', action='store_true')
    for flag in ('game', 'resources', 'ctl', 'reference', 'create-jar'):
        parser.add_argument('--' + flag, type=Path)
    args = parser.parse_args()
    if args.java:
        work = Path(tempfile.mkdtemp(prefix='press-world-java-', dir=ROOT / '.local'))
        print(work, flush=True)
        result = java_run(work)
    else:
        if not all((args.game, args.resources, args.ctl, args.reference, args.create_jar)):
            parser.error('Horizon requires --game, --resources, --ctl, --reference and --create-jar')
        reference = json.loads(args.reference.read_text())
        assert reference['passed'] and reference['create'] == PINS['create_revision'], reference
        session = NativeCheckSession(args.game, args.resources, args.ctl, args.create_jar,
                                     name='press-world-native', world='PressWorld', graphics=False)
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
