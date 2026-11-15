#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Observe water/lava flow collisions in a side tank between co-directed pumps."""

import argparse
import json
from pathlib import Path
import re
import shutil
import tempfile

from bearing_native_checks import Batch
from burner_heat_java_checks import field
from chain_drive_checks import Original, xyz
from common import PINS, ROOT
from fluid_pump_java_checks import PIPE, PUMP, TANK, measure, seed
from fluid_pump_overlap_checks import lane
from fluid_valve_java_checks import drive
from funnel_checks import put
from native_check_session import NativeCheckSession
from reference_java import BASE, CREATE_SHA256


CASES = {
    'east_water_lava': ('east', (16, 64), 'water', 'lava'),
    'west_lava_water': ('west', (-64, -16), 'lava', 'water'),
}
AMOUNTS = (8000, 2000)
COBBLESTONE = 'minecraft:cobblestone'
TICKS = 84
Z_OFFSET = 64


def layouts(split):
    result = {}
    for index, (name, (direction, _, _, _)) in enumerate(CASES.items()):
        layout = {key: ((x, y, z + Z_OFFSET), kind, faces)
                  for key, ((x, y, z), kind, faces) in lane(index, False).items()}
        if split:
            # This arm remains attached to the upstream pump after the
            # original junction breaks. It starts as an empty closed tank.
            junction = 'between_a' if direction == 'east' else 'between_b'
            (x, y, z), kind, faces = layout[junction]
            layout[junction] = ((x, y, z), kind, (*faces, 'north'))
            layout['other_arm'] = ((x, y, z-1), PIPE, ('north', 'south'))
            layout['other_tank'] = ((x, y, z-2), TANK, ())
        result[name] = layout
    return result


X, Y, Z = layouts(False)['east_water_lava']['left'][0]
AREA = f'{X-3} {Y-2} {Z-3} {X+11} {Y+4} {Z+11}'
LOAD = f'{X-3} {Z-3} {X+11} {Z+11}'


def item_selector(layout):
    x, y, z = layout['junction'][0]
    return f'@e[type=minecraft:item,x={x-6},y={y-1},z={z-3},dx=12,dy=5,dz=5]'


def item_query(layout):
    return f'execute as {item_selector(layout)} run data get entity @s Item'


def item_stacks(raw):
    stacks = []
    for start in re.finditer(r'has the following entity data:\s*', raw):
        payload = raw[start.end():]
        item = re.match(r'\{count:\s*(\d+),\s*id:\s*"([^"]+)"\}|'
                        r'\{id:\s*"([^"]+)",\s*count:\s*(\d+)\}', payload)
        assert item, payload
        before_count, after_id, before_id, after_count = item.groups()
        stacks.append([before_id or after_id, int(before_count or after_count)])
    return sorted(stacks)


def setup(command, lanes):
    command(f'fill {AREA} minecraft:air')
    command(f'fill {X-3} {Y-1} {Z-3} {X+11} {Y-1} {Z+11} minecraft:smooth_stone')
    for name, (direction, _, _, _) in CASES.items():
        layout = lanes[name]
        command(f'kill {item_selector(layout)}')
        for pos, kind, faces in layout.values():
            state = kind
            if kind == PIPE:
                state += '[' + ','.join(f'{face}=true' for face in faces) + ',waterlogged=false]'
            elif kind == PUMP:
                state += f'[facing={direction},waterlogged=false]'
            put(command, pos, state)
        for key, dy in (('first', -1), ('second', 1)):
            x, y, z = layout[key][0]
            put(command, (x, y+dy, z), 'create:cogwheel[axis=x]')


def seed_sources(command, lanes):
    for name, (direction, _, main, side) in CASES.items():
        layout = lanes[name]
        main_pos = layout['left' if direction == 'east' else 'right'][0]
        command(seed(main_pos, main, AMOUNTS[0]))
        command(seed(layout['side'][0], side, AMOUNTS[1]))


def power(command, lanes):
    for name, (_, speeds, _, _) in CASES.items():
        for key, dy, rpm in zip(('first', 'second'), (-1, 1), speeds, strict=True):
            x, y, z = lanes[name][key][0]
            command(drive((x-1, y+dy, z), rpm, 'east'))


def decode(blocks, lanes):
    values = iter(blocks)
    rows = {}
    for name, layout in lanes.items():
        row = dict(blocks={}, tanks={}, devices={})
        for key, (_, _, ports) in layout.items():
            block = next(values)
            kind = block['id']
            row['blocks'][key] = kind
            if kind == TANK:
                row['tanks'][key] = measure(block)['tank']
            elif kind in (PIPE, PUMP):
                raw = block['nbt']
                if 'create_horizon:' in raw:
                    # Ignore native kinetic Ports unrelated to the fluid faces.
                    diagnostic = field(raw, 'create_horizon')
                    raw = raw.replace(diagnostic, '{}', 1)
                state = measure(block | {'nbt': raw}, ports)
                for face in state['connections'].values():
                    face['pressure'] = [round(p, 6) for p in face['pressure']]
                    flow = face['flow']
                    if flow and flow['progress'] is not None:
                        flow['progress'] = round(flow['progress'], 6)
                row['devices'][key] = dict(speed=state['speed'], faces=state['connections'])
        rows[name] = row
    assert next(values, None) is None
    return rows


def java(work, lanes):
    positions = [pos for layout in lanes.values() for pos, _, _ in layout.values()]
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
        host.command(f'tp @s {X+4}.5 {Y+6} {Z+3}.5')
        host.call('tick', {'step': 35})
        setup(host.command, lanes)
        host.call('observe_ticks', {'ticks': 40, 'positions': positions[:1]})
        seed_sources(host.command, lanes)
        commands = []
        power(commands.append, lanes)
        samples = host.call('observe_ticks', {'ticks': TICKS, 'positions': positions,
                                              'ticker_order': True, 'commands': commands})['samples']
        drops = {name: item_stacks(' '.join(host.command(item_query(layout))['messages']))
                 for name, layout in lanes.items()}
        return [decode(frame['blocks'], lanes) for frame in samples], drops
    finally:
        for layout in lanes.values():
            host.command(f'kill {item_selector(layout)}')
        host.command(f'fill {AREA} minecraft:air')
        host.command(f'forceload remove {LOAD}')
        host.call('camera', {key: initial[key] for key in ('position', 'yaw', 'pitch')})
        host.call('tick', {'frozen': initial['server']['frozen']})
        (work / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')


def native_setup(lanes):
    batch = Batch()
    batch.load((X+4, Y+6, Z+3))
    setup(batch.command, lanes)
    batch.tick(40)
    seed_sources(batch.command, lanes)
    power(batch.command, lanes)
    return batch


def native_samples(session, batch, lanes, name, intervals):
    for ticks in intervals:
        batch.tick(ticks)
        for layout in lanes.values():
            for pos, kind, _ in layout.values():
                if kind != TANK:
                    for variant in (kind, COBBLESTONE, 'minecraft:air'):
                        batch.expect(pos, variant)
                batch.data(pos)
    for layout in lanes.values():
        batch.command(item_query(layout), True)

    readings = iter(batch.run(session, name))
    rows = []
    for _ in intervals:
        blocks = []
        for layout in lanes.values():
            for pos, kind, _ in layout.values():
                if kind != TANK:
                    matched = [variant for variant in (kind, COBBLESTONE, 'minecraft:air')
                               if 'bearing_check' in next(readings)]
                    assert len(matched) == 1, (pos, matched)
                    kind = matched[0]
                blocks.append(dict(id=kind, nbt=next(readings), properties={}))
        rows.append(decode(blocks, lanes))
    drops = {name: item_stacks(next(readings)) for name in CASES}
    assert next(readings, None) is None
    return rows, drops


def native_cold(session, lanes, warm):
    cut = 47
    (before,), drops = native_samples(session, native_setup(lanes), lanes, 'split-before-restart', (cut,))
    assert before == warm[cut-1], before
    assert drops == {name: [[PIPE, 1]] for name in CASES}, drops
    batch = Batch()
    batch.load((X+4, Y+6, Z+3))
    (after,), later_drops = native_samples(session, batch, lanes, 'split-after-restart', (90,))
    assert later_drops == drops, later_drops
    for name, (direction, _, main, _) in CASES.items():
        source, sink = ('left', 'right') if direction == 'east' else ('right', 'left')
        initial, final = before[name]['tanks'], after[name]['tanks']
        assert before[name]['blocks'] == after[name]['blocks'], name
        assert final['side'] == initial['side'] and final[sink] == initial[sink], (name, final)
        moved = final['other_tank']
        assert moved['id'] == 'minecraft:'+main and moved['amount'] > 0, (name, final)
        assert final[source]['amount'] + moved['amount'] == AMOUNTS[0], (name, final)
    return dict(cut=cut, before={k: v['tanks'] for k, v in before.items()},
                after={k: v['tanks'] for k, v in after.items()}, drops=later_drops)


def summarize(rows, drops):
    result = {}
    for name, (direction, _, main, side) in CASES.items():
        track = [row[name] for row in rows]
        collision = next((i for i, row in enumerate(track, 1) if COBBLESTONE in row['blocks'].values()), None)
        windows = {str(tick): track[tick-1] for tick in range(collision-1, collision+4)} if collision else {}
        final = track[-1]
        start = track[0]['tanks']
        assert start['left' if direction == 'east' else 'right'] == dict(id='minecraft:'+main, amount=AMOUNTS[0])
        assert start['side'] == dict(id='minecraft:'+side, amount=AMOUNTS[1])
        assert all(sum((tank or {}).get('amount', 0) for tank in row['tanks'].values()) == sum(AMOUNTS)
                   for row in track), name
        result[name] = dict(collision_tick=collision, collision_window=windows, final=final, drops=drops[name])
    return result


def compare(actual, reference):
    result = {}
    for name in CASES:
        delta = {}
        for tick, (got, wanted) in enumerate(zip(actual['rows'], reference['rows'], strict=True), 1):
            for key in ('blocks', 'tanks', 'devices'):
                if key not in delta and got[name][key] != wanted[name][key]:
                    delta[key] = dict(tick=tick, horizon=got[name][key], java=wanted[name][key])
        if actual['drops'][name] != reference['drops'][name]:
            delta['drops'] = dict(horizon=actual['drops'][name], java=reference['drops'][name])
        result[name] = delta
    return result


def verify_original(report, split=False):
    expected = {'east_water_lava': (43, 192), 'west_lava_water': (46, 168)} if split else {
        'east_water_lava': (40, 0), 'west_lava_water': (43, 0)}
    sink_amount = 72 if split else 90
    for name, (tick, surviving_amount) in expected.items():
        row = report['summary'][name]
        assert row['collision_tick'] == tick and row['drops'] == [[PIPE, 1]], (name, row)
        assert row['final']['blocks']['junction'] == COBBLESTONE, (name, row)
        direction, _, main, side = CASES[name]
        tanks = row['final']['tanks']
        sink = 'right' if direction == 'east' else 'left'
        assert tanks[sink] == dict(id='minecraft:'+side, amount=sink_amount), tanks
        assert tanks['side'] == dict(id='minecraft:'+side, amount=AMOUNTS[1]-sink_amount), tanks
        if split:
            assert tanks['other_tank'] == dict(id='minecraft:'+main, amount=surviving_amount), tanks


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--java', action='store_true')
    parser.add_argument('--baseline', action='store_true', help='report mismatches without failing')
    parser.add_argument('--cold', action='store_true', help='reopen the native split during recovery')
    parser.add_argument('--split', action='store_true', help='leave a second side tank on the surviving route')
    for key in ('game', 'resources', 'ctl', 'create-jar', 'reference'):
        parser.add_argument('--'+key, type=Path)
    args = parser.parse_args()
    if args.cold and (args.java or not args.split):
        parser.error('--cold requires a native --split run')
    lanes = layouts(args.split)
    cold = None
    if args.java:
        work = Path(tempfile.mkdtemp(prefix='pump-overlap-collision-java-', dir=ROOT / '.local'))
        print(work, flush=True)
        rows, drops = java(work, lanes)
    else:
        if not all((args.game, args.resources, args.ctl, args.create_jar, args.reference)):
            parser.error('Horizon requires --game, --resources, --ctl, --create-jar and --reference')
        reference = json.loads(args.reference.read_text())
        assert reference['passed'] and reference['create'] == PINS['create_revision']
        assert reference.get('split', False) == args.split
        session = NativeCheckSession(args.game, args.resources, args.ctl, args.create_jar,
                                     name='pump-overlap-collision-native', graphics=False,
                                     world='CreatePumpOverlapCollision')
        work = session.scratch
        print(work, flush=True)
        try:
            rows, drops = native_samples(session, native_setup(lanes), lanes, 'overlap-collision', (1,)*TICKS)
            if args.cold:
                cold = native_cold(session, lanes, rows)
        finally:
            session.control_temp.cleanup()
            for folder in (session.resources, work / '.horizon-cache', work / 'horizon-mods'):
                shutil.rmtree(folder, ignore_errors=True)

    report = dict(passed=False, create=PINS['create_revision'], split=args.split, rows=rows, drops=drops,
                  cold=cold)
    report['summary'] = summarize(rows, drops)
    if args.java:
        (work / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
        verify_original(report, args.split)
        report['passed'] = True
    else:
        report['first_differences'] = compare(report, reference)
        report['passed'] = not any(report['first_differences'].values())
    (work / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(dict(passed=report['passed'], collision_ticks={
        name: row['collision_tick'] for name, row in report['summary'].items()}, drops=drops,
        result=str(work / 'result.json'))))
    if not args.baseline:
        differences = {name: {key: delta.get('tick', 'final') for key, delta in fields.items()}
                       for name, fields in report.get('first_differences', {}).items() if fields}
        assert report['passed'], (differences, work / 'result.json')


if __name__ == '__main__':
    main()
