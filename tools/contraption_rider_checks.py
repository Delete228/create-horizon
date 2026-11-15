#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Observe the camera on a horizontal rotor and rider contact on a rising blade."""

import argparse
import json
import math
from pathlib import Path
import shutil
import tempfile
import time

from burner_heat_java_checks import number
from chain_drive_checks import Original, xyz
from common import PINS, ROOT
from contraption_frame_checks import MARKER
from native_check_session import NativeCheckSession, wait_loaded

HORIZONTAL = (1509, 100, 280)
VERTICAL = (1509, 100, 296)
FEET = (1510.5, 101.0, 298.5)
MOTOR = 'setblock 1508 100 296 create:creative_motor[facing=east]{ScrollValue:-8}'
VERTICAL_SPACE = '1506 99 291 1514 107 302'
VERTICAL_LOAD = '1504 288 1519 303'


def setup_vertical(command):
    command(f'fill {VERTICAL_SPACE} minecraft:air')
    command('fill 1506 99 291 1514 99 302 minecraft:stone')
    command('setblock 1509 100 296 create:mechanical_bearing[facing=east]')
    command('fill 1510 100 295 1510 100 297 minecraft:slime_block')
    command('setblock 1510 100 298 minecraft:oak_planks')
    command('gamemode survival')


def observe_vertical(read, pause):
    trace = []
    for _ in range(230):
        row = read()
        if not trace or row['angle'] != trace[-1]['angle']:
            trace.append(row)
        if abs(row['angle']) >= 125.0:
            return trace
        pause()
    raise AssertionError(('No complete sweep', trace))


def java_vertical(work):
    host = Original()
    state = host.call('state', {})
    if state['screen'] == 'PauseScreen':
        host.call('input', {'kind': 'escape'})
        state = host.call('state', {})
    assert state['ready'] and state['data_version'] == 3955, state

    def read():
        return host.call('rider_pose', {'pos': [VERTICAL[0] + 1, *VERTICAL[1:]]})

    try:
        host.call('tick', {'frozen': True})
        host.command('forceload add ' + VERTICAL_LOAD)
        host.command('tp @s 1509.5 105 296.5')
        host.snapshot([VERTICAL], 24)
        setup_vertical(host.command)
        host.call('camera', {'position': FEET, 'target': [1510.5, 101.0, 296.5]})
        host.snapshot([VERTICAL], 8)
        before = host.call('state', {})['position']
        host.command('tick rate 8')
        host.command(MOTOR)
        host.call('tick', {'frozen': False})
        return before, observe_vertical(read, lambda: time.sleep(.025))
    finally:
        host.call('tick', {'frozen': True})
        host.command('tick rate 20')
        host.command(f'fill {VERTICAL_SPACE} minecraft:air')
        host.command('forceload remove ' + VERTICAL_LOAD)
        host.call('camera', {'position': state['position'], 'yaw': state['yaw'], 'pitch': state['pitch']})
        host.call('tick', {'frozen': state['server']['frozen']})
        (work / 'java-transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')


def native_vertical(call, interrupt=False):
    def command(text):
        return call('command', text)['chat']

    def read():
        block = {'nbt': ' '.join(command('data get block ' + xyz(VERTICAL)))}
        return dict(angle=number(block, 'Angle', 0), position=call('state')['player']['position'])

    interruptions = {}

    def poll():
        row = read()
        if not interrupt or interruptions or row['angle'] > -55.0:
            return row
        call('server-hold', 'on')
        try:
            hold_start = read()
            client_tick = call('state')['ticks']
            call('wait', 3)
            hold_end = read()
            interruptions['hold'] = dict(start=hold_start, end=hold_end,
                                         client_ticks=call('state')['ticks'] - client_tick)
        finally:
            call('server-hold', 'off')
        stall_start = read()
        call('stall', 375)
        interruptions['stall'] = dict(start=stall_start, end=read())
        return row

    command('tp @s 1509.5 105 296.5')
    wait_loaded(call, [VERTICAL])
    setup_vertical(command)
    command('tp @s ' + xyz(FEET))
    call('wait', 10)
    player = call('state')['player']
    assert player['on_ground'], player
    command('tick freeze')
    command('tick rate 8')
    command(MOTOR)
    command('tick unfreeze')
    trace = observe_vertical(poll, lambda: call('wait', 1))
    command('tick rate 20')
    return player['position'], trace, interruptions


def native_horizontal(call):
    def command(text):
        return call('command', text)

    command('gamemode creative')
    command('tp @s 1510.9 105 280.5')
    wait_loaded(call, [HORIZONTAL])
    command('fill 1504 99 275 1514 107 285 minecraft:air')
    command('fill 1504 99 275 1514 99 285 minecraft:stone')
    command('setblock 1509 100 280 create:mechanical_bearing[facing=up]')
    command('fill 1506 101 277 1512 101 283 minecraft:slime_block')
    command('tp @s 1510.9 102.1 280.5')
    command('gamemode survival')
    call('look-at', 1509.5, 103.6, 280.5)
    call('wait', 8)
    command('setblock 1509 99 280 create:creative_motor[facing=up]{ScrollValue:12}')
    call('wait', 18)
    standing = call('state')
    call('key', 'w', 'down')
    try:
        call('wait', 8)
    finally:
        call('key', 'w', 'up')
    walking = call('state')
    call('wait', 8)
    return standing, walking


def camera_metrics(rows, standing, walking):
    rotor = [row for row in rows if row['controller'] == list(HORIZONTAL)]
    last_standing = standing['ticks'] - 1
    still = [row for row in rotor if last_standing - 10 <= row['tick'] <= last_standing]
    walking = [row for row in rotor if last_standing + 2 <= row['tick'] < walking['ticks']]

    def metrics(frames):
        assert len(frames) > 12, len(frames)
        steps = [math.dist(a['camera'], b['camera']) for a, b in zip(frames, frames[1:])]
        short_steps = [step for step, a, b in zip(steps, frames, frames[1:])
                       if 0 < b['tick'] - a['tick'] + b['camera_partial'] - a['camera_partial'] < 0.35]
        assert short_steps, len(frames)
        return dict(frames=len(frames), distance=sum(steps), largest_short_frame=max(short_steps))

    return dict(standing=metrics(still), walking=metrics(walking))


def delivery_metrics(rows):
    poses = {row['tick']: row['current_angle'] for row in rows
             if row['controller'] == list(VERTICAL) and -125.0 <= row['current_angle'] < 0.0}
    adjacent = [(poses[tick - 1], angle) for tick, angle in poses.items() if tick - 1 in poses]
    nominal_step = 2.4
    return dict(adjacent_samples=len(adjacent),
                unchanged=sum(abs(after - before) < .001 for before, after in adjacent),
                burst=sum(abs(after - before) > nominal_step + .001 for before, after in adjacent))


def compare_at_angles(native, original):
    # The Java client chases server angle updates, so its real contact angle
    # does not generally land on the native 2.4-degree samples.
    source = sorted(original, key=lambda row: row['angle'])
    intervals = list(zip(source, source[1:]))
    pairs = []
    for row in native:
        angle = row['angle']
        for lower, upper in intervals:
            if not lower['angle'] <= angle <= upper['angle']:
                continue
            span = upper['angle'] - lower['angle']
            if span > 6.0:
                break
            progress = (angle - lower['angle']) / span
            target = [a + (b - a) * progress
                      for a, b in zip(lower['position'], upper['position'], strict=True)]
            pairs.append((angle, row['position'], target))
            break
    descending = [(angle, abs(native[1] - java[1]))
                  for angle, native, java in pairs if -125.0 <= angle <= -95.0]
    assert pairs and descending, (len(pairs), len(descending))
    distances = [math.dist(native, java) for _, native, java in pairs]
    return dict(matched_angles=len(pairs), max_distance=max(distances),
                mean_distance=sum(distances) / len(distances),
                max_height_difference=max(abs(native[1] - java[1]) for _, native, java in pairs),
                descending_samples=len(descending),
                descending_angles=[min(angle for angle, _ in descending),
                                   max(angle for angle, _ in descending)],
                max_descending_height_difference=max(error for _, error in descending))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--java', action='store_true')
    parser.add_argument('--observe-only', action='store_true')
    parser.add_argument('--pose-load', action='store_true',
                        help='Keep verbose particle and block-entity diagnostics enabled during native delivery')
    parser.add_argument('--pose-interrupt', action='store_true',
                        help='Hold server ticks, then stall the native window while transport continues')
    for name in ('game', 'resources', 'ctl', 'reference', 'create-jar'):
        parser.add_argument('--' + name, type=Path)
    args = parser.parse_args()
    if args.java and (args.pose_load or args.pose_interrupt):
        parser.error('Pose delivery controls require a native run')
    report = {'create': PINS['create_revision']}
    if args.java:
        work = Path(tempfile.mkdtemp(prefix='vertical-rider-java-', dir=ROOT / '.local'))
        before, vertical = java_vertical(work)
    else:
        if not all((args.game, args.resources, args.ctl)):
            parser.error('Native test requires --game, --resources and --ctl')
        session = NativeCheckSession(args.game, args.resources, args.ctl, args.create_jar,
                                     name='contraption-rider', world='CreateMotionChecks',
                                     size=(640, 360), username='BearingReview')
        if not args.pose_load:
            session.env.pop('CREATE_HORIZON_PARTICLE_TRACE', None)
            session.env.pop('CREATE_HORIZON_TRACE_POSES', None)
        session.env['CREATE_TRACE_CONTRAPTION_FRAMES'] = '1'
        work = session.scratch
        print(work, flush=True)
        try:
            with session:
                standing, walking = native_horizontal(session.call)
                before, vertical, interruptions = native_vertical(session.call, args.pose_interrupt)
            rows = [json.loads(line.split(MARKER, 1)[1]) for line in session.log.read_text().splitlines()
                    if MARKER in line]
            if rows and 'camera' in rows[0]:
                report['camera'] = camera_metrics(rows, standing, walking)
                report['pose_delivery'] = delivery_metrics(rows)
            if interruptions:
                report['interruptions'] = interruptions
        finally:
            session.control_temp.cleanup()
            for path in (session.resources, work / '.horizon-cache', work / 'horizon-mods'):
                shutil.rmtree(path, ignore_errors=True)
    report.update(before=before, vertical=vertical)
    if args.reference:
        original = json.loads(args.reference.read_text())
        assert original['create'] == PINS['create_revision'], original
        assert 'previous_angle' in original['vertical'][-1], 'Collect the atomic Java client angle with --java'
        report['java_comparison'] = compare_at_angles(vertical, original['vertical'])
    (work / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
    print(work)
    print('Vertical max height:', max(row['position'][1] for row in vertical), report.get('camera'))
    if not args.observe_only:
        rising = [row['position'][1] for row in vertical if 25 <= abs(row['angle']) <= 50]
        assert rising and min(rising) > before[1] + 0.6, rising
        assert vertical[-1]['position'][1] < max(rising), vertical[-1]
        if not args.java:
            assert report['camera']['standing']['largest_short_frame'] < 0.05, report['camera']
            assert report['camera']['walking']['largest_short_frame'] < 0.15, report['camera']
        if args.pose_interrupt:
            hold = report['interruptions']['hold']
            stall = report['interruptions']['stall']
            assert hold['client_ticks'] >= 3 and hold['start']['angle'] == hold['end']['angle'], hold
            assert abs(hold['end']['position'][2] - hold['start']['position'][2]) < .01, hold
            assert abs(stall['end']['angle'] - stall['start']['angle']) >= 4.79, stall
        if args.reference:
            comparison = report['java_comparison']
            assert comparison['matched_angles'] >= 26, comparison
            assert comparison['max_distance'] < .12, comparison
            assert comparison['descending_samples'] >= 6, comparison
            assert comparison['descending_angles'][0] <= -120.0, comparison
            assert comparison['descending_angles'][1] >= -100.0, comparison
            assert comparison['max_descending_height_difference'] < .03, comparison


if __name__ == '__main__':
    main()
