#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Compare closed straight lines with opposing Mechanical Pumps."""

import argparse
import json
from pathlib import Path
import shutil
import tempfile

from bearing_native_checks import Batch
from chain_drive_checks import Original, xyz
from common import PINS, ROOT
from fluid_pump_java_checks import PIPE, PUMP, TANK, measure, seed
from fluid_valve_java_checks import drive
from funnel_checks import put
from native_check_session import NativeCheckSession
from reference_java import BASE, CREATE_SHA256


X, Y = 2707, 173
LOAD = '2704 1408 2719 1423'
AREA = '2705 170 1410 2717 177 1420'
CASES = {'push_inward': (1412, 'east', 'west'), 'pull_outward': (1418, 'west', 'east')}
KINDS = (TANK, PIPE, PUMP, PIPE, PIPE, PIPE, PUMP, PIPE, TANK)
CELLS = [((X + i, Y, z), kind) for z, _, _ in CASES.values() for i, kind in enumerate(KINDS)]
TICKS = 80
TOGGLE_TICKS = {'both': 40, 'right_off': 20, 'right_again': 30}
TANKS = [{'id': 'minecraft:water', 'amount': amount} for amount in (6000, 2000)]


def setup(command):
    command(f'fill {AREA} minecraft:air')
    for z, left, right in CASES.values():
        for index, kind in enumerate(KINDS):
            state = kind
            if kind == PIPE:
                state += '[east=true,west=true,waterlogged=false]'
            elif kind == PUMP:
                state += f'[facing={left if index == 2 else right},waterlogged=false]'
            put(command, (X + index, Y, z), state)
        put(command, (X + 2, Y - 1, z), 'create:cogwheel[axis=x]')
        put(command, (X + 6, Y + 1, z), 'create:cogwheel[axis=x]')


def start(command):
    for z, _, _ in CASES.values():
        command(seed((X, Y, z), 'water', 6000))
        command(seed((X + 8, Y, z), 'water', 2000))
        command(drive((X + 1, Y - 1, z), 32, 'east'))
        command(drive((X + 5, Y + 1, z), 64, 'east'))


def run_phase(command, phase):
    if phase == 'both':
        start(command)
        return
    for z, _, _ in CASES.values():
        pos = (X + 5, Y + 1, z)
        command(f'setblock {xyz(pos)} minecraft:air' if phase == 'right_off' else drive(pos, 64, 'east'))


def observe(blocks):
    assert len(blocks) == len(CELLS)
    rows = {}
    for index, name in enumerate(CASES):
        row = [measure(block) for block in blocks[index * len(KINDS):(index + 1) * len(KINDS)]]
        for device in row[1:-1]:
            for face in device['connections'].values():
                face['pressure'] = face['pressure'] or [0, 0]
                if face['flow'] and face['flow']['progress'] is not None:
                    face['flow']['progress'] = round(face['flow']['progress'], 6)
        rows[name] = dict(tanks=[row[0]['tank'], row[-1]['tank']],
                          devices=[{key: value for key, value in device.items() if key != 'props'}
                                   for device in row[1:-1]])
    return rows


def java_run(work, phases, toggle):
    host = Original()
    initial = host.call('state', {})
    assert initial['ready'] and initial['data_version'] == 3955, initial
    assert json.loads((BASE / 'manifest.json').read_text())['create_sha256'] == CREATE_SHA256
    positions = [pos for pos, _ in CELLS]
    host.call('tick', {'frozen': True})
    try:
        host.command(f'forceload add {LOAD}')
        host.call('observe_ticks', {'positions': positions[:1], 'ticks': 20})
        setup(host.command)
        host.call('observe_ticks', {'positions': positions[:1], 'ticks': 40})
        traces = {}
        for phase, ticks in phases.items():
            # The motor removal callback needs the previously running speed.
            commands = ['tick unfreeze'] if toggle else []
            run_phase(commands.append, phase)
            result = host.call('observe_ticks', {'positions': positions, 'ticks': ticks,
                                                 'commands': commands, 'ticker_order': True})
            traces[phase] = [observe(sample['blocks']) for sample in result['samples']]
        return traces
    finally:
        host.command(f'fill {AREA} minecraft:air')
        host.command(f'forceload remove {LOAD}')
        host.call('tick', {'frozen': initial['server']['frozen']})
        (work / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')


def native_run(session, phases):
    batch = Batch()
    batch.load((X + 4, Y + 3, 1415))
    setup(batch.command)
    batch.tick(40)
    for phase, ticks in phases.items():
        run_phase(batch.command, phase)
        for _ in range(ticks):
            batch.tick()
            for pos, _ in CELLS:
                batch.data(pos)
    readings = iter(batch.run(session, 'opposed-pumps'))
    traces = {phase: [observe([dict(id=kind, nbt=next(readings), properties={}) for _, kind in CELLS])
                      for _ in range(ticks)] for phase, ticks in phases.items()}
    assert next(readings, None) is None
    return traces


def verify_reference(traces, phases):
    for phase, ticks in phases.items():
        rows = traces[phase]
        assert len(rows) == ticks
        for frame in rows:
            for lane in frame.values():
                assert lane['tanks'] == TANKS, lane
                for pipe in lane['devices'][2:5]:
                    assert all(face == {'pressure': [0, 0], 'flow': None}
                               for face in pipe['connections'].values()), lane
        for lane in rows[-1].values():
            for outer, active in ((lane['devices'][0], True), (lane['devices'][-1], phase != 'right_off')):
                assert all(any(face['pressure']) == active for face in outer['connections'].values()), lane


def compare(rows, reference):
    first = {}
    differing_samples = {name: 0 for name in CASES}
    for tick, (actual, expected) in enumerate(zip(rows, reference, strict=True), 1):
        for name in CASES:
            if actual[name] != expected[name]:
                differing_samples[name] += 1
                first.setdefault(name, dict(tick=tick, horizon=actual[name], java=expected[name]))
    return dict(first=first, differing_samples=differing_samples)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--java', action='store_true')
    parser.add_argument('--toggle', action='store_true', help='stop and restart the right drive in both lanes')
    parser.add_argument('--baseline', action='store_true', help='record differences without a failing exit code')
    for flag in ('game', 'resources', 'ctl', 'create-jar', 'reference'):
        parser.add_argument('--' + flag, type=Path)
    args = parser.parse_args()
    phases = TOGGLE_TICKS if args.toggle else {'both': TICKS}
    name = 'pump-opposed-toggle' if args.toggle else 'pump-opposed'
    differences = None
    passed = True
    if args.java:
        work = Path(tempfile.mkdtemp(prefix=name + '-java-', dir=ROOT / '.local'))
        print(work, flush=True)
        traces = java_run(work, phases, args.toggle)
        verify_reference(traces, phases)
    else:
        if not all((args.game, args.resources, args.ctl, args.create_jar, args.reference)):
            parser.error('Horizon requires --game, --resources, --ctl, --create-jar and --reference')
        reference = json.loads(args.reference.read_text())
        assert reference['passed'] and reference['create'] == PINS['create_revision']
        if reference.get('toggle', False) != args.toggle:
            parser.error('the reference must use the same --toggle setting')
        expected = reference['rows'] if args.toggle else {'both': reference['rows']}
        session = NativeCheckSession(args.game, args.resources, args.ctl, args.create_jar,
                                     name=name + '-native', world='CreatePumpOpposed')
        work = session.scratch
        print(work, flush=True)
        try:
            traces = native_run(session, phases)
        finally:
            session.control_temp.cleanup()
            for folder in (session.resources, work / '.horizon-cache', work / 'horizon-mods'):
                shutil.rmtree(folder, ignore_errors=True)
        comparisons = {phase: compare(rows, expected[phase]) for phase, rows in traces.items()}
        passed = all(not comparison['first'] for comparison in comparisons.values())
        differences = comparisons if args.toggle else comparisons['both']
    path = work / 'result.json'
    result = dict(passed=passed, create=PINS['create_revision'],
                  rows=traces if args.toggle else traces['both'], differences=differences)
    if args.toggle:
        result['toggle'] = True
    path.write_text(json.dumps(result, indent=2) + '\n')
    print(path, flush=True)
    assert passed or args.baseline, differences


if __name__ == '__main__':
    main()
