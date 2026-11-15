#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Observe competing closed sources feeding one pump through a T junction."""

import argparse
import json
from pathlib import Path
import re
import shutil
import tempfile

from bearing_native_checks import Batch
from burner_heat_java_checks import field
from chain_drive_checks import Original
from common import PINS, ROOT
from fluid_pump_java_checks import PIPE, PUMP, TANK, measure, seed
from funnel_checks import put
from native_check_session import NativeCheckSession
from reference_java import BASE, CREATE_SHA256

X, Y, Z = 2260, 171, 1942
AREA = '2256 169 1938 2263 174 1976'
LOAD = '2256 1936 2271 1983'
TICKS = 84
COBBLESTONE = 'minecraft:cobblestone'
COLLISIONS = ('mixed', 'mixed_unequal')
CASES = {
    'equal': ('water', 2000, 'water', 2000, False),
    'nearly_empty': ('water', 3, 'water', 2000, False),
    'empty': ('water', 0, 'water', 2000, False),
    'mixed': ('water', 2000, 'lava', 2000, False),
    'unequal': ('water', 2000, 'water', 2000, True),
    'mixed_unequal': ('water', 2000, 'lava', 2000, True),
}


def cells(name):
    z = Z + 6 * list(CASES).index(name)
    longer = CASES[name][4]
    layout = {
        'north': ((X-1, Y, z - (2 if longer else 1)), TANK, ()),
        'south': ((X-1, Y, z+1), TANK, ()),
        'sink': ((X+1, Y, z), TANK, ()),
        'junction': ((X-1, Y, z), PIPE, ('east', 'north', 'south')),
        'pump': ((X, Y, z), PUMP, ('west', 'east')),
    }
    if longer:
        layout['long_pipe'] = ((X-1, Y, z-1), PIPE, ('north', 'south'))
    return layout


LAYOUTS = {name: cells(name) for name in CASES}
POSITIONS = [pos for layout in LAYOUTS.values() for pos, _, _ in layout.values()]


def dropped_pipe(name):
    x, y, z = LAYOUTS[name]['junction'][0]
    return (f'@e[type=minecraft:item,x={x-3},y={y-2},z={z-3},dx=7,dy=5,dz=6,'
            'nbt={Item:{id:"create:fluid_pipe",count:1}}]')


def drop_query(name):
    return f'execute as {dropped_pipe(name)} run data get entity @s Item'


def drop_count(text):
    return text.count('"create:fluid_pipe"')


def setup(command):
    for name in COLLISIONS:
        command(f'kill {dropped_pipe(name)}')
    command(f'fill {AREA} minecraft:air')
    command('fill 2256 169 1938 2263 169 1976 minecraft:smooth_stone')
    for name in COLLISIONS:
        x, y, z = LAYOUTS[name]['junction'][0]
        for wall_x in (x-3, x+4):
            command(f'fill {wall_x} {y-1} {z-3} {wall_x} {y+2} {z+3} minecraft:smooth_stone')
        for wall_z in (z-3, z+3):
            command(f'fill {x-3} {y-1} {wall_z} {x+4} {y+2} {wall_z} minecraft:smooth_stone')
    for layout in LAYOUTS.values():
        for pos, block, ports in layout.values():
            if block == PIPE:
                mask = ','.join(f'{side}=true' for side in ports)
                block += f'[{mask},waterlogged=false]'
            elif block == PUMP:
                block += '[facing=east,waterlogged=false]'
            put(command, pos, block)
        z = layout['pump'][0][2]
        put(command, (X, Y-1, z), 'create:cogwheel[axis=x]')


def seed_sources(command):
    for name, (first, a, second, b, _) in CASES.items():
        layout = LAYOUTS[name]
        for medium, size, key in ((first, a, 'north'), (second, b, 'south')):
            if size:
                command(seed(layout[key][0], medium, size))


def power(command):
    for layout in LAYOUTS.values():
        z = layout['pump'][0][2]
        put(command, (X+1, Y-1, z), 'create:creative_motor[facing=west]{ScrollValue:32}')


def decode_frame(observed):
    readings = iter(observed)
    out = {}
    for name, layout in LAYOUTS.items():
        state = {key: next(readings) for key in layout}
        devices = {}
        for key, value in state.items():
            kind = value['id']
            if kind not in (PIPE, PUMP):
                continue
            raw = value['nbt']
            # The native kinetic Ports contain scalar cardinal names. They
            # are separate from Create's compound fluid connections.
            if re.search(r'\bcreate_horizon\s*:', raw):
                diagnostic = field(raw, 'create_horizon')
                raw = re.sub(r'\bcreate_horizon\s*:\s*' + re.escape(diagnostic), '', raw, count=1)
            values = measure(value | {'nbt': raw}, layout[key][2])
            for face in values['connections'].values():
                face['pressure'] = [round(p, 5) for p in face['pressure']]
                if (flow := face['flow']) and flow['progress'] is not None:
                    flow['progress'] = round(flow['progress'], 6)
            devices[key] = dict(speed=values['speed'], faces=values['connections'])
        out[name] = {
            'tanks': {key: measure(state[key])['tank'] for key in ('north', 'south', 'sink')},
            'junction': state['junction']['id'],
            'devices': devices,
        }
    assert next(readings, None) is None
    return out


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
        host.command(f'tp @s {X}.5 {Y+6} {Z+12}.5')
        host.call('observe_ticks', {'ticks': 30, 'positions': POSITIONS})
        setup(host.command)
        host.call('observe_ticks', {'ticks': 40, 'positions': POSITIONS})
        commands = []
        seed_sources(host.command)
        power(commands.append)
        frames = host.call('observe_ticks', {'ticks': TICKS, 'positions': POSITIONS,
                                             'commands': commands})['samples']
        rows = [decode_frame(frame['blocks']) for frame in frames]
        drops = {name: drop_count(' '.join(host.command(drop_query(name))['messages']))
                 for name in COLLISIONS}
        return rows, drops
    finally:
        for name in COLLISIONS:
            host.command(f'kill {dropped_pipe(name)}')
        host.command(f'fill {AREA} minecraft:air')
        host.command(f'forceload remove {LOAD}')
        host.call('camera', {key: initial[key] for key in ('position', 'yaw', 'pitch')})
        host.call('tick', {'frozen': initial['server']['frozen']})
        (work / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')


def observe_native(batch, ticks, session, label):
    for _ in range(ticks):
        batch.tick()
        for layout in LAYOUTS.values():
            for key, (pos, _, _) in layout.items():
                if key == 'junction':
                    batch.expect(pos, PIPE)
                    batch.expect(pos, COBBLESTONE)
                batch.data(pos)
    for name in COLLISIONS:
        batch.command(drop_query(name), True)
    readings = iter(batch.run(session, label))
    rows = []
    for _ in range(ticks):
        observed = []
        for layout in LAYOUTS.values():
            for key, (_, kind, _) in layout.items():
                if key == 'junction':
                    is_pipe, is_cobble = ('bearing_check' in next(readings) for _ in range(2))
                    assert is_pipe != is_cobble, (key, is_pipe, is_cobble)
                    if is_cobble:
                        kind = COBBLESTONE
                observed.append(dict(id=kind, nbt=next(readings), properties={}))
        rows.append(decode_frame(observed))
    drops = {name: drop_count(next(readings)) for name in COLLISIONS}
    assert next(readings, None) is None
    return rows, drops


def native(session, cold):
    batch = Batch()
    batch.load((X, Y+4, Z+12))
    setup(batch.command)
    batch.tick(40)
    seed_sources(batch.command)
    power(batch.command)
    rows, drops = observe_native(batch, TICKS, session, 'inlet-branch')
    restored = None
    if cold:
        batch = Batch()
        batch.load((X, Y+4, Z+12))
        batch.tick(34)
        after, persisted_drops = observe_native(batch, 1, session, 'inlet-branch-after-restart')
        restored = after[0]
        assert persisted_drops == drops, (persisted_drops, drops)
        for name, row in restored.items():
            before = rows[-1][name]
            assert sum(totals(row)) == sum(totals(before)), (name, row)
            if name in COLLISIONS:
                assert row['junction'] == COBBLESTONE and row['tanks'] == before['tanks'], (name, row)
            else:
                assert totals(row)[2] > totals(before)[2], (name, row)
    return rows, drops, restored


def totals(frame):
    return [stack['amount'] if stack else 0 for stack in frame['tanks'].values()]


def summarize(rows):
    report = {}
    for name, (_, start_north, _, start_south, _) in CASES.items():
        track = [row[name] for row in rows]
        amounts = [totals(frame) for frame in track]
        assert all(sum(counts) == start_north + start_south for counts in amounts), (name, amounts)
        assert amounts[0] == [start_north, start_south, 0], (name, amounts[0])
        changed = [(i, [before[0] - after[0], before[1] - after[1], after[2] - before[2]])
                   for i, (before, after) in enumerate(zip(amounts, amounts[1:]), 2) if before != after]
        collision = next((i for i, frame in enumerate(track, 1) if frame['junction'] == COBBLESTONE), None)
        flow_starts = {}
        for i, frame in enumerate(track, 1):
            for key, device in frame['devices'].items():
                for direction, face in device['faces'].items():
                    if face['flow']:
                        flow_starts.setdefault(f'{key}/{direction}', (i, face['flow']))
        report[name] = dict(final_amounts=amounts[-1], first_transfers=changed[:8],
                            distinct_rates=sorted({tuple(delta) for _, delta in changed}),
                            collision_tick=collision, initial_flows=flow_starts,
                            final_pressures={key: {face: values['pressure'] for face, values in device['faces'].items()}
                                             for key, device in track[-1]['devices'].items()})
    return report


def verify_reference(summary):
    expected = {
        'equal': (25, [(8, 8, 16)]),
        'nearly_empty': (25, [(3, 8, 11), (0, 8, 8)]),
        'empty': (25, [(0, 8, 8)]),
        'unequal': (24, [(16, 0, 16), (16, 8, 24)]),
    }
    for name, (start, rates) in expected.items():
        lane = summary[name]
        assert lane['collision_tick'] is None, (name, lane)
        assert lane['first_transfers'][0] == (start, list(rates[0])), (name, lane)
        assert lane['distinct_rates'] == sorted(rates), (name, lane)
        assert lane['final_pressures']['junction'] == {
            'east': [0, 16], 'north': [16, 0], 'south': [16, 0],
        }, (name, lane)
    assert summary['unequal']['final_pressures']['long_pipe'] == {'north': [32, 0], 'south': [0, 32]}
    for name, collision in (('mixed', 11), ('mixed_unequal', 19)):
        lane = summary[name]
        assert lane['collision_tick'] == collision and not lane['first_transfers'], (name, lane)
    short = summary['mixed_unequal']['initial_flows']['pump/west']
    assert short[0] == 17 and short[1]['fluid']['id'] == 'minecraft:lava', short


def verify_baseline(summary):
    for name, lane in summary.items():
        assert not lane['first_transfers'] and lane['collision_tick'] is None, (name, lane)
        assert all(not faces for device in lane['final_pressures'].values() for faces in device.values()), (name, lane)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--java', action='store_true')
    parser.add_argument('--baseline', action='store_true', help='Check safe refusal by the current adapter')
    for key in ('game', 'resources', 'ctl', 'create-jar', 'reference'):
        parser.add_argument('--' + key, type=Path)
    args = parser.parse_args()
    session = None
    if args.java:
        work = Path(tempfile.mkdtemp(prefix='pipe-inlet-branch-java-', dir=ROOT / '.local'))
    else:
        if not all((args.game, args.resources, args.ctl, args.create_jar, args.reference)):
            parser.error('Horizon requires --game, --resources, --ctl, --create-jar and --reference')
        reference = json.loads(args.reference.read_text())
        assert reference['passed'] and reference['create'] == PINS['create_revision']
        session = NativeCheckSession(args.game, args.resources, args.ctl, args.create_jar,
                                     name='pipe-inlet-branch-native', graphics=False, world='CreatePipeInletBranch')
        session.env.pop('CREATE_HORIZON_PARTICLE_TRACE', None)
        work = session.scratch
    print(work, flush=True)
    report = dict(passed=False, create=PINS['create_revision'])
    try:
        if session:
            rows, drops, cold = native(session, not args.baseline)
            report['cold'] = cold
        else:
            rows, drops = java(work)
        report['rows'] = rows
        report['drops'] = drops
        assert drops == dict.fromkeys(COLLISIONS, 0 if args.baseline else 1), drops
        summary = summarize(rows)
        report['summary'] = summary
        if not session:
            verify_reference(summary)
        elif args.baseline:
            verify_baseline(summary)
        else:
            for tick, (actual, expected) in enumerate(zip(rows, reference['rows'], strict=True), 1):
                assert actual == expected, (tick, actual, expected)
        report['passed'] = True
    finally:
        if session:
            session.control_temp.cleanup()
            for folder in (session.resources, work / '.horizon-cache', work / 'horizon-mods'):
                shutil.rmtree(folder, ignore_errors=True)
        (work / 'result.json').write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    main()
