#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Compare a local rider falling on rotating Slime and Stone."""

import argparse
import json
from pathlib import Path
import shutil
import tempfile

from belt_rider_checks import wait_for
from chain_drive_checks import Original, xyz
from common import PINS, ROOT
from native_check_session import NativeCheckSession, wait_loaded


AREA = '1567 95 248 1585 108 256'
FORCE = '1568 240 1583 271'
SLIME = (1571, 101, 252)
STONE = (1579, 101, 252)
TICKS = 18


def setup(command):
    command(f'fill {AREA} minecraft:air')
    command('fill 1567 95 248 1585 95 256 minecraft:stone')
    for anchor, block in ((SLIME, 'slime_block'), (STONE, 'stone')):
        x, y, z = anchor
        command(f'setblock {x} {y - 1} {z} create:mechanical_bearing[facing=up]')
        command(f'setblock {x} {y} {z} minecraft:{block}')
        command(f'setblock {x} {y - 2} {z} create:creative_motor[facing=up]{{ScrollValue:8}}')
    command('gamemode survival')


def measure(aim, read, key, pause_pose=None):
    results = {}
    cases = [
        ('slime', SLIME, 104.9, False),
        ('stone', STONE, 104.9, False),
        ('slow_slime', SLIME, 102.04, False),
        ('crouched_slime', SLIME, 104.9, True),
    ]
    if pause_pose:
        cases.append(('slime_pose_gap', SLIME, 104.9, False))
    for name, anchor, height, crouch in cases:
        x, _, z = anchor
        with_gap = name == 'slime_pose_gap'
        paused_at = None
        paused = False
        key(crouch)
        try:
            aim((x + .5, height, z + .5))
            sample = lambda: read(anchor)
            first = wait_for(sample, lambda row: abs(row['position'][0] - x - .5) < 1e-5
                             and abs(row['position'][1] - height) < .08)
            rows = [dict(first, elapsed=0)]
            while rows[-1]['elapsed'] < TICKS:
                row = wait_for(sample, lambda row: row['tick'] > rows[-1]['tick'])
                rows.append(dict(row, elapsed=row['tick'] - first['tick'], pose_gap=paused))
                if paused and row['tick'] - paused_at >= 3:
                    pause_pose(False)
                    paused = False
                if with_gap and paused_at is None and row['velocity'][1] < -.43:
                    pause_pose(True)
                    paused = True
                    paused_at = row['tick']
            results[name] = rows
        finally:
            if paused:
                pause_pose(False)
            key(False)
    return results


def original(work):
    host = Original()
    state = host.call('state', {})
    if state.get('screen') == 'PauseScreen':
        host.call('input', {'kind': 'escape'})
        state = host.call('state', {})
    assert state['ready'] and state['data_version'] == 3955, state

    def read(anchor):
        row = host.call('rider_pose', {'pos': anchor})
        return dict(row, tick=row['player_tick'])

    try:
        host.call('tick', {'frozen': True})
        host.command('gamemode creative')
        host.command('tp @s ' + xyz((1575.5, 108, 252.5)))
        host.command('forceload add ' + FORCE)
        host.snapshot([(1571, 100, 252), (1579, 100, 252)], 16)
        setup(host.command)
        host.snapshot([(1571, 100, 252), (1579, 100, 252)], 12)
        host.command('tick rate 8')
        host.call('tick', {'frozen': False})
        return measure(lambda feet: host.call('camera', {'position': feet}), read,
                       lambda down: host.call('input', {'key': 'shift', 'down': down}))
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

    def read(_):
        state = session.call('state')
        return dict(tick=state['ticks'], position=state['player']['position'],
                    velocity=state['player']['velocity'], grounded=state['player']['on_ground'])

    with session:
        command('tp @s ' + xyz((1575.5, 108, 252.5)))
        wait_loaded(session.call, [SLIME, STONE])
        command('tick freeze')
        setup(command)
        command('tick rate 8')
        command('tick unfreeze')
        session.call('wait', 12)
        return measure(lambda feet: command('tp @s ' + xyz(feet)), read,
                       lambda down: session.call('key', 'shift', 'down' if down else 'up'),
                       lambda held: session.call('server-hold', 'on' if held else 'off'))


def compare_contact(expected, actual, contact_tick):
    def aligned(rows):
        contact = contact_tick(rows)['elapsed']
        return {row['elapsed'] - contact: row for row in rows}

    source, native = aligned(expected), aligned(actual)
    shared = source.keys() & native.keys() & set(range(7))
    assert 0 in shared and len(shared) >= 5, shared
    assert all(native[tick]['grounded'] == source[tick]['grounded'] for tick in shared), shared
    return max(abs(native[tick][field][1] - source[tick][field][1])
               for tick in shared for field in ('position', 'velocity'))


def rebound(rows):
    return max(rows, key=lambda row: row['velocity'][1])


def settled_on_slime(rows):
    return next(row for row in rows if row['grounded'] and abs(row['position'][1] - 102) < .01)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--java', action='store_true')
    for flag in ('game', 'resources', 'ctl', 'create-jar', 'reference'):
        parser.add_argument('--' + flag, type=Path)
    args = parser.parse_args()
    report = dict(passed=False, create=PINS['create_revision'])
    session = None
    if args.java:
        work = Path(tempfile.mkdtemp(prefix='rotary-slime-player-java-', dir=ROOT / '.local'))
    elif all((args.game, args.resources, args.ctl, args.create_jar, args.reference)):
        session = NativeCheckSession(args.game, args.resources, args.ctl, args.create_jar,
                                     name='rotary-slime-player-native', world='RotarySlimePlayer')
        work = session.scratch
    else:
        parser.error('Horizon requires --game, --resources, --ctl, --create-jar and --reference')
    output = work / 'result.json'
    print(output, flush=True)
    try:
        report['cases'] = native(session) if session else original(work)
        peaks = report['peaks'] = {name: max(row['velocity'][1] for row in rows)
                                   for name, rows in report['cases'].items()}
        assert peaks['slime'] > .15, peaks
        assert all(peaks[name] <= .01 for name in ('stone', 'slow_slime', 'crouched_slime')), peaks
        if session:
            source = json.loads(args.reference.read_text())
            assert source['passed'] and source['create'] == report['create'], source
            comparisons = (
                ('slime', 'slime', rebound),
                ('slime_pose_gap', 'slime', rebound),
                ('slow_slime', 'slow_slime', settled_on_slime),
                ('crouched_slime', 'crouched_slime', settled_on_slime),
            )
            errors = report['max_vertical_errors'] = {
                name: compare_contact(source['cases'][expected], report['cases'][name], align)
                for name, expected, align in comparisons
            }
            assert max(errors.values()) < 1e-5, errors
            gap = report['cases']['slime_pose_gap']
            impulses = [row for previous, row in zip(gap, gap[1:])
                        if previous['velocity'][1] <= 0 < row['velocity'][1]]
            assert len(impulses) == 1 and impulses[0]['pose_gap'], gap
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
