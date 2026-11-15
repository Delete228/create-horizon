#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Compare loose, recipe-less items in a powered downward Crushing Wheel pair."""

import argparse
import json
from pathlib import Path
import shutil
import tempfile

from bearing_native_checks import Batch
from chain_drive_checks import Original
from common import PINS, ROOT
from crusher_drop_checks import compare, state
from crushing_wheel_checks import AIR, CONTROLLER, X, Y, wheels
from native_check_session import NativeCheckSession
import reference_java


LANES = ((1030, 'minecraft:paper', 1), (1037, 'minecraft:stick', 4))
UNPORTED = 'minecraft:netherrack'
POINTS = [(X, Y, z) for z, *_ in LANES]
REGION = f'{X-2} {Y-2} 1028 {X+2} {Y+4} 1039'
LOAD = '2128 1024 2143 1039'
CAMERA = (X, Y + 4, 1034)
DROPS = f'@e[type=minecraft:item,x={X-2},y={Y-2},z=1028,dx=4,dy=6,dz=11]'
TICKS = 110


def setup(command, advance):
    command(f'fill {REGION} {AIR}')
    command(f'fill {X-2} {Y-2} 1028 {X+2} {Y-2} 1039 minecraft:smooth_stone')
    command(f'kill {DROPS}')
    for z, *_ in LANES:
        wheels(command, z)
    advance(28)
    for z, item, count in LANES:
        command(f'summon minecraft:item {X+.5} {Y+2.25} {z+.5} '
                f'{{Motion:[0d,0d,0d],PickupDelay:32767s,Item:{{id:"{item}",count:{count},'
                f'components:{{"minecraft:custom_data":{{crusher_probe:{z}}}}}}}}}')


def verify(trace, drops):
    assert not drops, drops
    result = []
    for index, (z, item, count) in enumerate(LANES):
        rows = [row[index] for row in trace]
        assert all(row['speed'] == 1.28 for row in rows), rows[:4]
        entered = next(tick for tick, row in enumerate(rows, 1) if row['entity'])
        stored = next(tick for tick, row in enumerate(rows, 1) if row['items'])
        cleared = next(tick for tick, row in enumerate(rows, 1) if row['applied'])
        assert entered < stored < cleared, (entered, stored, cleared)
        assert rows[stored - 1]['items'] == {item: count}, rows[stored - 1]
        assert rows[stored - 1]['remaining'] == 100 and rows[stored - 1]['marker'] == z, rows[stored - 1]
        assert all(row['applied'] and not row['items'] and not row['entity'] and row['remaining'] == 0
                   for row in rows[cleared - 1:]), rows[cleared - 1:]
        result.append(dict(item=item, count=count, captured_tick=entered,
                           stored_tick=stored, cleared_tick=cleared))
    return result


def java(work):
    host = Original()
    manifest = json.loads((reference_java.BASE / 'manifest.json').read_text())
    assert manifest['create_sha256'] == reference_java.CREATE_SHA256
    initial = host.call('state', {})
    if initial.get('screen') == 'PauseScreen':
        host.call('input', {'kind': 'escape'})
        initial = host.call('state', {})
    assert initial['ready'] and initial['data_version'] == 3955, initial
    host.call('tick', {'frozen': True})
    command = host.command

    def observe(ticks):
        return host.call('observe_ticks', {'positions': POINTS, 'ticks': ticks})['samples']

    try:
        command(f'tp @s {CAMERA[0]}.5 {CAMERA[1]} {CAMERA[2]}.5')
        command(f'forceload add {LOAD}')
        observe(30)
        setup(command, observe)
        trace = []
        while len(trace) < TICKS:
            for tick in observe(min(TICKS - len(trace), 60)):
                assert all(block['id'] == CONTROLLER for block in tick['blocks']), tick
                trace.append([state(block['nbt']) for block in tick['blocks']])
        entities = host.call('entities', {'center': [X+.5, Y, CAMERA[2]+.5], 'radius': 7})['entities']
        drops = [entity for entity in entities if entity['type'] == 'minecraft:item']
        return trace, drops
    finally:
        command(f'kill {DROPS}')
        command(f'fill {REGION} {AIR}')
        command(f'forceload remove {LOAD}')
        host.call('camera', {key: initial[key] for key in ('position', 'yaw', 'pitch')})
        host.call('tick', {'frozen': initial['server']['frozen']})
        (work / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')


def native(session):
    batch = Batch()
    batch.load(CAMERA)
    setup(batch.command, batch.tick)
    for _ in range(TICKS):
        batch.tick()
        for pos in POINTS:
            batch.data(pos)
    batch.command(f'data get entity {DROPS[:-1]},limit=1] Item', True)
    z = LANES[0][0]
    batch.command(f'summon minecraft:item {X+.5} {Y+2.25} {z+.5} '
                  f'{{Motion:[0d,0d,0d],PickupDelay:32767s,Item:{{id:"{UNPORTED}",count:1}}}}')
    batch.tick(45)
    batch.data(POINTS[0])
    batch.command(f'data get entity {DROPS[:-1]},nbt={{Item:{{id:"{UNPORTED}"}}}},limit=1] Item', True)
    rows = batch.run(session, 'crusher-no-recipe')
    observations = TICKS * len(LANES)
    assert len(rows) == observations + 3, len(rows)
    trace = [[state(raw) for raw in rows[i:i+len(LANES)]]
             for i in range(0, observations, len(LANES))]
    drops, controller, preserved = rows[observations:]
    status = state(controller)
    assert not status['items'] and not status['entity'], status
    assert UNPORTED in preserved, preserved
    return trace, [drops] if 'id:' in drops else []


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--java', action='store_true')
    for flag in ('game', 'resources', 'ctl', 'reference', 'create-jar'):
        parser.add_argument('--' + flag, type=Path)
    args = parser.parse_args()
    if args.java:
        work = Path(tempfile.mkdtemp(prefix='crusher-no-recipe-java-', dir=ROOT / '.local'))
        print(work, flush=True)
        trace, drops = java(work)
    else:
        if not all((args.game, args.resources, args.ctl, args.reference)):
            parser.error('Horizon requires --game, --resources, --ctl and --reference')
        reference = json.loads(args.reference.read_text())
        assert reference['create'] == PINS['create_revision'] and reference['passed'], reference
        session = NativeCheckSession(args.game, args.resources, args.ctl, args.create_jar,
                                     name='crusher-no-recipe-native', graphics=False,
                                     world='CrusherNoRecipe')
        work = session.scratch
        print(work, flush=True)
        try:
            trace, drops = native(session)
        finally:
            session.control_temp.cleanup()
            for folder in (session.resources, work / '.horizon-cache', work / 'horizon-mods'):
                shutil.rmtree(folder, ignore_errors=True)
        compare(trace, reference['trace'])
    cases = verify(trace, drops)
    path = work / 'result.json'
    path.write_text(json.dumps(dict(passed=True, create=PINS['create_revision'],
                                    trace=trace, cases=cases), indent=2) + '\n')
    print(path)


if __name__ == '__main__':
    main()
