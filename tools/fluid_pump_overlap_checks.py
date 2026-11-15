#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Measure an active side tank in the overlap between two directed pumps."""

import argparse
import json
from pathlib import Path
import shutil
import tempfile

from bearing_native_checks import Batch
from chain_drive_checks import Original, xyz
from common import PINS, ROOT
from fluid_pump_java_checks import PIPE, PUMP, TANK, amount, measure, seed
from fluid_valve_java_checks import drive
from funnel_checks import put
from native_check_session import NativeCheckSession


X, Y, Z = 2819, 174, 1733
LOAD = '2816 1728 2831 1759'
AREA = '2816 172 1730 2830 178 1756'
CASES = {'push': (64, 16, (0,)), 'pull': (16, 64, (2000,)),
         'tie': (32, 32, (2000,)), 'empty_pull': (16, 64, (0,))}
PAIRED = {'push': (64, 16, (0, 0)), 'pull': (16, 64, (2000, 1000)),
          'tie': (32, 32, (2000, 0)), 'nearly_full': (64, 32, (7999, 0))}
PHASES = {'both': 88, 'upstream_only': 74, 'downstream_only': 74, 'restored': 74}
EW, NS = ('west', 'east'), ('north', 'south')
def lane(index, paired):
    z = Z + 6 * index
    cells = {
        'left': ((X, Y, z), TANK, ()),
        'inlet': ((X+1, Y, z), PIPE, EW),
        'first': ((X+2, Y, z), PUMP, EW),
        'between_a': ((X+3, Y, z), PIPE, EW),
        'junction': ((X+4, Y, z), PIPE, (*EW, *NS) if paired else (*EW, 'south')),
        'between_b': ((X+5, Y, z), PIPE, EW),
        'second': ((X+6, Y, z), PUMP, EW),
        'outlet': ((X+7, Y, z), PIPE, EW),
        'right': ((X+8, Y, z), TANK, ()),
        'arm': ((X+4, Y, z+1), PIPE, NS),
        'side': ((X+4, Y, z+2), TANK, ()),
    }
    if paired:
        cells['other_arm'] = ((X+4, Y, z-1), PIPE, NS)
        cells['other_tank'] = ((X+4, Y, z-2), TANK, ())
    return cells


class Fixture:
    def __init__(self, paired):
        self.cases = PAIRED if paired else CASES
        self.tanks = ('left', 'side', 'right', 'other_tank') if paired else ('left', 'side', 'right')
        self.tracked = (*self.tanks, 'junction', 'arm', 'other_arm') if paired else (
            *self.tanks, 'first', 'second', 'junction', 'arm')
        self.lanes = {name: lane(index, paired) for index, name in enumerate(self.cases)}
        self.cells = [layout[key] for layout in self.lanes.values() for key in self.tracked]
        self.positions = [pos for pos, _, _ in self.cells]


def setup(command, fixture):
    command(f'fill {AREA} minecraft:air')
    for lane in fixture.lanes.values():
        for pos, kind, faces in lane.values():
            state = kind
            if kind == PIPE:
                state += '[' + ','.join(f'{face}=true' for face in faces) + ']'
            elif kind == PUMP:
                state += '[facing=east]'
            put(command, pos, state)
        for key, offset in (('first', -1), ('second', 1)):
            x, y, z = lane[key][0]
            put(command, (x, y+offset, z), 'create:cogwheel[axis=x]')


def commands(phase, fixture):
    rows = []
    for name, (first, second, _) in fixture.cases.items():
        lane = fixture.lanes[name]
        for key, offset, rpm in (('first', -1, first), ('second', 1, second)):
            x, y, z = lane[key][0]
            pos = (x-1, y+offset, z)
            if (phase == 'both'
                    or (phase == 'restored' and key == 'first')
                    or (phase == 'downstream_only' and key == 'second')):
                rows.append(drive(pos, rpm, 'east'))
            elif (phase == 'upstream_only' and key == 'second') or (phase == 'downstream_only' and key == 'first'):
                rows.append(f'setblock {xyz(pos)} minecraft:air')
    return rows


def seed_tanks(command, fixture):
    for name, (_, _, volumes) in fixture.cases.items():
        lane = fixture.lanes[name]
        command(seed(lane['left'][0], 'water', 8000))
        for key, volume in zip(('side', 'other_tank'), volumes):
            if volume:
                command(seed(lane[key][0], 'water', volume))


def observe(blocks, fixture):
    observed = iter(blocks)
    rows = {}
    for name, lane in fixture.lanes.items():
        devices = {key: measure(next(observed), lane[key][2]) for key in fixture.tracked}
        pressure = {key: {side: [round(x, 6) for x in v['pressure']]
                          for side, v in device['connections'].items()}
                    for key, device in devices.items() if device['block'] != TANK}
        flow = {key: {side: ([v['flow']['inbound'],
                            round(v['flow']['progress'], 6) if v['flow']['progress'] is not None else 1.0]
                           if v['flow'] else None)
                      for side, v in device['connections'].items()}
                for key, device in devices.items() if device['block'] != TANK}
        rows[name] = dict(tanks=[amount(devices[key]) for key in fixture.tanks], pressure=pressure, flow=flow)
    assert next(observed, None) is None
    return rows


def java_run(work, fixture):
    host = Original()
    initial = host.call('state', {})
    assert initial['ready'] and initial['data_version'] == 3955, initial
    host.call('tick', {'frozen': True})
    try:
        host.command(f'forceload add {LOAD}')
        host.call('tick', {'step': 20})
        setup(host.command, fixture)
        host.call('observe_ticks', {'positions': fixture.positions[:1], 'ticks': 40})
        seed_tanks(host.command, fixture)
        return {phase: [observe(row['blocks'], fixture) for row in host.call('observe_ticks', {
            'positions': fixture.positions, 'ticks': ticks,
            'commands': ['tick unfreeze', *commands(phase, fixture)]})['samples']]
                for phase, ticks in PHASES.items()}
    finally:
        host.command(f'fill {AREA} minecraft:air')
        host.command(f'forceload remove {LOAD}')
        host.call('tick', {'frozen': initial['server']['frozen']})
        (work / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')


def native_run(session, fixture):
    batch = Batch()
    batch.load((X+4, Y+2, Z+9))
    setup(batch.command, fixture)
    batch.tick(40)
    seed_tanks(batch.command, fixture)
    for phase, ticks in PHASES.items():
        for value in commands(phase, fixture):
            batch.command(value)
        for _ in range(ticks):
            batch.tick()
            record(batch, fixture)
    raw = iter(batch.run(session, 'pump-overlap'))
    rows = {phase: [observe((dict(id=kind, nbt=next(raw), properties={})
                             for _, kind, _ in fixture.cells), fixture)
                    for _ in range(ticks)] for phase, ticks in PHASES.items()}
    assert next(raw, None) is None
    return rows


def record(batch, fixture):
    for pos in fixture.positions:
        batch.data(pos)


def recorded_snapshot(batch, session, label, fixture):
    raw = iter(batch.run(session, label))
    frame = observe((dict(id=kind, nbt=next(raw), properties={})
                     for _, kind, _ in fixture.cells), fixture)
    assert next(raw, None) is None
    return frame


def cold_run(session, warm, fixture):
    cut = 70
    batch = Batch()
    batch.load((X+4, Y+2, Z+9))
    setup(batch.command, fixture)
    batch.tick(40)
    seed_tanks(batch.command, fixture)
    for value in commands('both', fixture):
        batch.command(value)
    batch.tick(cut)
    record(batch, fixture)
    before = recorded_snapshot(batch, session, 'pump-overlap-before-restart', fixture)
    assert before == warm['both'][cut-1], before

    batch = Batch()
    batch.load((X+4, Y+2, Z+9))
    batch.tick(88)
    record(batch, fixture)
    after = recorded_snapshot(batch, session, 'pump-overlap-after-restart', fixture)
    for name, row in after.items():
        assert sum(row['tanks']) == sum(before[name]['tanks']), (name, row)
        assert row['tanks'][2] > before[name]['tanks'][2], (name, row)
        assert row['pressure'] == before[name]['pressure'], (name, row)
    assert after['push']['tanks'][1] > before['push']['tanks'][1]
    assert after['pull']['tanks'][1] < before['pull']['tanks'][1]
    if len(fixture.tanks) == 4:
        assert after['push']['tanks'][3] > before['push']['tanks'][3]
        assert after['pull']['tanks'][3] < before['pull']['tanks'][3]
    return dict(cut=cut, before={name: row['tanks'] for name, row in before.items()},
                after={name: row['tanks'] for name, row in after.items()})


def verify(traces, fixture):
    totals = {name: 8000 + sum(volumes) for name, (_, _, volumes) in fixture.cases.items()}
    for rows in traces.values():
        for row in rows:
            assert all(sum(state['tanks']) == totals[name] for name, state in row.items()), row
    assert traces['both'][-1]['push']['tanks'][1] > 0
    assert traces['both'][-1]['pull']['tanks'][1] < 2000
    if len(fixture.tanks) == 4:
        assert traces['both'][-1]['push']['tanks'][3] > 0
        assert traces['both'][-1]['pull']['tanks'][3] < 1000


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--java', action='store_true')
    parser.add_argument('--paired', action='store_true', help='exercise two closed side tanks in the overlap')
    parser.add_argument('--cold', action='store_true', help='reopen the Horizon save with pressure on both sides of the branch')
    for flag in ('game', 'resources', 'ctl', 'create-jar', 'reference'):
        parser.add_argument('--'+flag, type=Path)
    args = parser.parse_args()
    if args.cold and args.java:
        parser.error('--cold is the native persistence check')
    fixture = Fixture(args.paired)
    cold = None
    if args.java:
        work = Path(tempfile.mkdtemp(prefix='pump-overlap-java-', dir=ROOT / '.local'))
        print(work, flush=True)
        traces = java_run(work, fixture)
    else:
        if not all((args.game, args.resources, args.ctl, args.create_jar, args.reference)):
            parser.error('Horizon requires --game, --resources, --ctl, --create-jar and --reference')
        session = NativeCheckSession(args.game, args.resources, args.ctl, args.create_jar,
                                     name='pump-overlap-native', world='CreatePumpOverlap')
        work = session.scratch
        print(work, flush=True)
        try:
            traces = native_run(session, fixture)
            if args.cold:
                cold = cold_run(session, traces, fixture)
        finally:
            session.control_temp.cleanup()
            for folder in (session.resources, work / '.horizon-cache', work / 'horizon-mods'):
                shutil.rmtree(folder, ignore_errors=True)

    (work / 'observed.json').write_text(json.dumps(traces, indent=2) + '\n')
    verify(traces, fixture)
    if not args.java:
        expected = json.loads(args.reference.read_text())
        assert expected['passed'] and expected['create'] == PINS['create_revision']
        assert expected.get('paired', False) == args.paired
        expected_traces = json.loads(args.reference.with_name('observed.json').read_text())
        for phase, rows in traces.items():
            for tick, (got, want) in enumerate(zip(rows, expected_traces[phase], strict=True), 1):
                for name in fixture.cases:
                    for field, value in got[name].items():
                        assert value == want[name][field], (phase, tick, name, field, value, want[name][field])
    result = work / 'result.json'
    result.write_text(json.dumps(dict(passed=True, create=PINS['create_revision'], cold=cold, paired=args.paired,
        final={phase: {name: row['tanks'] for name, row in rows[-1].items()}
               for phase, rows in traces.items()}), indent=2) + '\n')
    print(result)


if __name__ == '__main__':
    main()
