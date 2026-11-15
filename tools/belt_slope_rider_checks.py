#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Observe player motion on a dry rising Belt in both travel directions."""

import argparse
import json
import math
from pathlib import Path
import shutil
import tempfile

from belt_rider_checks import wait_for
from chain_drive_checks import Original, xyz
from common import PINS, ROOT
from native_check_session import NativeCheckSession, wait_loaded


BASE = (2578, 165, 1611)
AREA = '2568 148 1603 2588 170 1626'
FORCE = '2560 1600 2591 1631'
LANES = (
    ('east', (2572, 151, 1606), 0, 2576, -32),
    ('south', (2584, 151, 1608), 2, 1616, 32),
)
TICKS = 14


def offset(pos, axis, amount):
    return tuple(value + (amount if i == axis else 0) for i, value in enumerate(pos))


def setup(command):
    command(f'fill {AREA} minecraft:air')
    for direction, origin, axis, _, _ in LANES:
        for index in range(12):
            part = 'start' if index == 0 else 'end' if index == 11 else 'middle'
            pos = offset(offset(origin, axis, index), 1, index)
            command(f'setblock {xyz(pos)} create:belt[facing={direction},slope=upward,part={part}]')
    command('gamemode survival')


def measure(command, aim, read):
    cases = {}
    for direction, origin, axis, boundary, uphill_rpm in LANES:
        cross = 2 if axis == 0 else 0
        motor = xyz(offset(origin, cross, -1))
        face = 'south' if axis == 0 else 'east'
        for label, sign in (('up', 1), ('down', -1)):
            longitudinal = boundary - .55 * sign
            index = math.floor(longitudinal - origin[axis])
            start = list(offset(offset(origin, cross, .5), 1, index + 1.65))
            start[axis] = longitudinal
            aim(start)
            rest = wait_for(read, lambda row: row['grounded']
                            and abs(row['position'][axis] - longitudinal) < 1e-6
                            and abs(row['position'][cross] - start[cross]) < 1e-6
                            and row['position'][1] < start[1] - .1)
            command(f'setblock {motor} create:creative_motor[facing={face}]{{ScrollValue:{uphill_rpm * sign}}}')
            rows = []
            try:
                row = wait_for(read, lambda row: (row['position'][axis] - longitudinal) * sign > .025)
                initial_tick = row['tick']
                while row['tick'] - initial_tick < TICKS:
                    rows.append(dict(row, elapsed=row['tick'] - initial_tick))
                    row = wait_for(read, lambda sample: sample['tick'] > rows[-1]['tick'])
                authority = command('data get entity @s Motion')
            finally:
                command(f'setblock {motor} minecraft:air')
            cases[f'{direction}_{label}'] = dict(rest=rest, rows=rows, axis=axis, sign=sign,
                                                   boundary=boundary,
                                                   authority_motion=authority.get('messages', authority.get('chat', [])))
            stopped_at = read()['tick']
            wait_for(read, lambda row: row['tick'] >= stopped_at + 6)
    return cases


def original(work):
    host = Original()
    state = host.call('state', {})
    if state.get('screen') == 'PauseScreen':
        host.call('input', {'kind': 'escape'})
        state = host.call('state', {})
    assert state['ready'] and state['data_version'] == 3955, state

    def read():
        row = host.call('rider_pose', {'pos': BASE})
        return dict(tick=row['player_tick'], position=row['position'], velocity=row['velocity'],
                    grounded=row['grounded'], before_player_tick=row.get('before_player_tick'),
                    after_player_tick=row.get('after_player_tick'))

    try:
        host.call('tick', {'frozen': True})
        host.command('gamemode creative')
        host.command('tp @s ' + xyz(BASE))
        host.command('forceload add ' + FORCE)
        host.snapshot([BASE, *(lane[1] for lane in LANES)], 24)
        setup(host.command)
        host.command('tick rate 8')
        host.call('tick', {'frozen': False})
        return measure(host.command, lambda feet: host.call('camera', {'position': feet}), read)
    finally:
        host.call('tick', {'frozen': True})
        host.command('gamemode creative')
        host.command(f'fill {AREA} minecraft:air')
        host.command('forceload remove ' + FORCE)
        host.command('tick rate 20')
        host.call('camera', {key: state[key] for key in ('position', 'yaw', 'pitch')})
        host.call('tick', {'frozen': state['server']['frozen']})
        (work / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')


def native(session):
    def command(value):
        return session.call('command', value)

    def read():
        state = session.call('state')
        return dict(tick=state['ticks'], position=state['player']['position'],
                    velocity=state['player']['velocity'],
                    grounded=state['player']['on_ground'])

    with session:
        command('tp @s ' + xyz(BASE))
        wait_loaded(session.call, [BASE, *(lane[1] for lane in LANES), (2584, 161, 1618)])
        command('tick freeze')
        setup(command)
        command('tick rate 8')
        command('tick unfreeze')
        return measure(command, lambda feet: command('tp @s ' + xyz(feet)), read)


def verify(cases):
    for name, case in cases.items():
        axis, sign, boundary = (case[key] for key in ('axis', 'sign', 'boundary'))
        before, after = case['rest']['position'], case['rows'][-1]['position']
        assert (after[axis] - boundary) * sign > 0.0, (name, case)
        assert (after[1] - before[1]) * sign > .4, (name, case)
        assert math.floor(before[axis]) >> 4 != math.floor(after[axis]) >> 4, (name, case)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--java', action='store_true')
    for flag in ('game', 'resources', 'ctl', 'create-jar', 'reference'):
        parser.add_argument('--' + flag, type=Path)
    args = parser.parse_args()
    report = dict(passed=False, create=PINS['create_revision'])
    session = None
    if args.java:
        work = Path(tempfile.mkdtemp(prefix='belt-slope-rider-java-', dir=ROOT / '.local'))
    elif all((args.game, args.resources, args.ctl, args.reference)):
        session = NativeCheckSession(args.game, args.resources, args.ctl, args.create_jar,
                                     name='belt-slope-rider-native', world='BeltSlopeRider')
        work = session.scratch
    else:
        parser.error('Horizon comparison requires --game, --resources, --ctl and --reference')
    output = work / 'result.json'
    print(output, flush=True)
    try:
        report['cases'] = native(session) if session else original(work)
        verify(report['cases'])
        if session:
            reference = json.loads(args.reference.read_text())
            assert reference['passed'] and reference['create'] == report['create'], reference
            comparison = report['comparison'] = {}
            for name, case in report['cases'].items():
                expected = reference['cases'][name]
                source = {row['elapsed']: row['position'] for row in expected['rows']}
                errors = [math.dist(row['position'], source[row['elapsed']]) for row in case['rows']
                          if row['elapsed'] in source]
                comparison[name] = dict(samples=len(errors), max_distance=max(errors),
                                        mean_distance=sum(errors) / len(errors),
                                        rest=math.dist(case['rest']['position'], expected['rest']['position']))
                assert len(errors) >= 7 and comparison[name]['rest'] < 1e-6, comparison
            # Client/authority packet phase can shift an observation by one
            # sample. A different steady carry speed accumulates beyond it.
            assert all(row['max_distance'] < .17 and row['mean_distance'] < .08
                       for row in comparison.values()), comparison
        report['passed'] = True
    except BaseException as error:
        report['error'] = repr(error)
        raise
    finally:
        if session:
            session.control_temp.cleanup()
            for path in (session.resources, work / '.horizon-cache', work / 'horizon-mods'):
                shutil.rmtree(path, ignore_errors=True)
        output.write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    main()
