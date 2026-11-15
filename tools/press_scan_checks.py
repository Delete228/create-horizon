#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Compare loose-item Press scans on natural server ticks."""

import argparse
import json
from pathlib import Path
import shutil
import tempfile
import time

from bearing_native_checks import Batch
from burner_heat_java_checks import number
from chain_drive_checks import Original, xyz
from common import PINS, ROOT
from native_check_session import NativeCheckSession
import reference_java as java


PRESS = (2662, 180, 1602)
MOTOR = (2661, 180, 1602)
STABLE_MOTOR = (2660, 180, 1602)
CLUTCH_LOCK = (2661, 181, 1602)
CAMERA = (2665, 182, 1605)
LOAD = '2656 1600 2671 1615'
AREA = '2660 178 1600 2667 184 1606'
DROPS = '@e[type=minecraft:item,x=2662,y=179,z=1602,distance=..3]'
POWER = f'setblock {xyz(MOTOR)} create:creative_motor[facing=east]{{ScrollValue:64}}'
STOP = f'setblock {xyz(MOTOR)} minecraft:air'
DROP = ('summon minecraft:item 2662.5 179 1602.5 '
        '{PickupDelay:32767s,Motion:[0d,0d,0d],Item:{id:"minecraft:copper_ingot",count:2}}')
PRIME = DROP.replace('count:2', 'count:1')
CLUTCH_ON = f'setblock {xyz(CLUTCH_LOCK)} minecraft:air'
CLUTCH_OFF = f'setblock {xyz(CLUTCH_LOCK)} minecraft:redstone_block'
FRESH_CASES = {
    'arrive_between_scans': ((3, POWER), (14, DROP)),
    'arrive_during_power_stop': ((3, POWER), (6, STOP), (5, DROP), (14, POWER)),
    'hit_resets_scan': ((6, DROP), (50, POWER)),
    'miss_keeps_scan': ((6, DROP), (26, POWER), (1, 'kill ' + DROPS), (54, DROP)),
}
FRESH_JAVA_STARTS = {
    'arrive_between_scans': [11],
    'arrive_during_power_stop': [23],
    'hit_resets_scan': [17, 50],
    'miss_keeps_scan': [17, 59],
}


def phase_cases(fresh, first_hit):
    if first_hit:
        return {'first_hit_after_long_stop': ((72, PRIME), (48, POWER if fresh else CLUTCH_ON))}
    if fresh:
        return FRESH_CASES
    signals = {POWER: CLUTCH_ON, STOP: CLUTCH_OFF}
    timings = dict(FRESH_CASES)
    timings['miss_keeps_scan'] = ((6, DROP), (14, POWER), (16, 'kill ' + DROPS), (54, DROP))
    return {name: [(ticks, signals.get(command, command)) for ticks, command in phases]
            for name, phases in timings.items()}


def setup(command, fresh):
    command('kill ' + DROPS)
    command('fill ' + AREA + ' minecraft:air')
    command('setblock 2662 178 1602 minecraft:smooth_stone')
    if not fresh:
        command(f'setblock {xyz(CLUTCH_LOCK)} minecraft:redstone_block')
        command(f'setblock {xyz(MOTOR)} create:clutch[axis=x,powered=true]')
        command(f'setblock {xyz(STABLE_MOTOR)} create:creative_motor[facing=east]{{ScrollValue:64}}')
    command(f'setblock {xyz(PRESS)} create:mechanical_press[facing=east]')


def before_cold_start(fresh):
    return ((3, POWER if fresh else CLUTCH_ON), (12, STOP if fresh else CLUTCH_OFF))


def restart_java(host):
    host.command(f'forceload remove {LOAD}')
    host.call('camera', {'position': (CAMERA[0] + 256, CAMERA[1], CAMERA[2])})
    host.call('quit', {})
    deadline = time.monotonic() + 60
    while java.process_alive(java.BASE):
        assert time.monotonic() < deadline, 'Private Java did not save and exit'
        time.sleep(.2)
    assert java.launch(java.BASE)['ready']
    host.call('tick', {'frozen': True})
    host.command(f'forceload add {LOAD}')
    host.command('tp @s ' + xyz(CAMERA))


def state(nbt):
    record = {'nbt': nbt}
    return dict(rpm=int(number(record, 'Speed', 0)), running=bool(number(record, 'Running', 0)),
                ticks=int(number(record, 'Ticks', 0)), finished=bool(number(record, 'Finished', 0)))


def starts(rows):
    return [i + 1 for i, row in enumerate(rows) if row['running'] and (i == 0 or not rows[i-1]['running'])]


SETTLED = {
    'arrive_between_scans': (17, {3: DROP}),
    'arrive_during_power_stop': (28, {3: CLUTCH_OFF, 9: DROP, 14: CLUTCH_ON}),
}
SETTLED_JAVA_STARTS = {'arrive_between_scans': [11], 'arrive_during_power_stop': [22]}


def java_settled(host, observe):
    result = {}
    for name, (length, actions) in SETTLED.items():
        setup(host.command, False)
        observe(12)
        host.command(PRIME)
        observe(6)
        host.command(CLUTCH_ON)
        for _ in range(50):
            [row] = observe(1)
            if row['finished'] and not row['running']:
                break
        else:
            raise AssertionError('Initial loose-item cycle never finished')
        rows = []
        for index, action in sorted(actions.items()):
            rows.extend(observe(index - len(rows)))
            host.command(action)
        rows.extend(observe(length - len(rows)))
        result[name] = rows
    return result


def java_run(work, fresh, settled, first_hit, cold):
    host = Original()
    initial = host.call('state', {})
    manifest = json.loads((java.BASE / 'manifest.json').read_text())
    assert initial['data_version'] == 3955 and manifest['create_sha256'] == java.CREATE_SHA256

    def observe(ticks):
        positions = [PRESS, MOTOR] if fresh else [PRESS, MOTOR, STABLE_MOTOR]
        result = host.call('observe_ticks', {'ticks': ticks, 'positions': positions, 'ticker_order': True})
        return [state(row['blocks'][0].get('nbt', '')) for row in result['samples']]

    host.call('tick', {'frozen': True})
    try:
        host.command(f'forceload add {LOAD}')
        host.command('tp @s ' + xyz(CAMERA))
        observe(24)
        if settled:
            return java_settled(host, observe)
        result = {}
        for name, phases in phase_cases(fresh, first_hit).items():
            setup(host.command, fresh)
            observe(12)
            if cold:
                rows = []
                for ticks, command in before_cold_start(fresh):
                    host.command(command)
                    rows.extend(observe(ticks))
                result['before_restart'] = rows
                restart_java(host)
                observe(24)
            rows = []
            for ticks, command in phases:
                host.command(command)
                rows.extend(observe(ticks))
            result[name] = rows
        return result
    finally:
        host.command('kill ' + DROPS)
        host.command('fill ' + AREA + ' minecraft:air')
        host.command(f'forceload remove {LOAD}')
        host.call('camera', {key: initial[key] for key in ('position', 'yaw', 'pitch')})
        host.call('tick', {'frozen': initial['server']['frozen']})
        (work / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')


def native_settled(session):
    batch = Batch()
    batch.load(CAMERA)
    batch.command('scoreboard objectives add press_scan dummy')
    frames = 80
    for _, actions in SETTLED.values():
        setup(batch.command, False)
        batch.tick(12)
        batch.command(PRIME)
        batch.tick(6)
        batch.command(CLUTCH_ON)
        batch.command('scoreboard players set #clock press_scan -1')
        for _ in range(frames):
            batch.command(f'execute if score #clock press_scan matches -1 if data block {xyz(PRESS)} '
                          '{Running:0b,Finished:1b} run scoreboard players set #clock press_scan 0')
            for index, action in actions.items():
                batch.command(f'execute if score #clock press_scan matches {index} run {action}')
            batch.tick()
            batch.data(PRESS)
            batch.command('execute if score #clock press_scan matches 0.. run scoreboard players add #clock press_scan 1')
    rows = list(map(state, batch.run(session, 'press-scan-settled')))
    assert len(rows) == frames * len(SETTLED), len(rows)
    result = {}
    for i, (name, (length, _)) in enumerate(SETTLED.items()):
        window = rows[i*frames:(i+1)*frames]
        anchor = next(n for n, row in enumerate(window) if row['finished'] and not row['running'])
        result[name] = window[anchor+1:anchor+1+length]
        assert len(result[name]) == length, (name, anchor)
    return result


def append_phases(batch, phases):
    for ticks, command in phases:
        batch.command(command)
        for _ in range(ticks):
            batch.tick()
            batch.data(PRESS)


def native_run(session, fresh, settled, first_hit, cold):
    if settled:
        return native_settled(session)
    batch = Batch()
    batch.load(CAMERA)
    result = {}
    plan = phase_cases(fresh, first_hit)
    for phases in plan.values():
        setup(batch.command, fresh)
        batch.tick(12)
        if cold:
            append_phases(batch, before_cold_start(fresh))
            result['before_restart'] = list(map(state, batch.run(session, 'press-scan-before-restart')))
            batch = Batch()
            batch.load(CAMERA)
            batch.tick(24)
        append_phases(batch, phases)
    rows = batch.run(session, 'press-scan')
    index = 0
    for name, phases in plan.items():
        count = sum(ticks for ticks, _ in phases)
        result[name] = list(map(state, rows[index:index+count]))
        index += count
    assert len(rows) == index, (len(rows), index)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--java', action='store_true')
    rigs = parser.add_mutually_exclusive_group()
    rigs.add_argument('--fresh-motor', action='store_true', help='Track new-motor publication timing separately')
    rigs.add_argument('--settled', action='store_true', help='Anchor the comparison at an observed completed strike')
    parser.add_argument('--first-hit', action='store_true', help='Observe the first hit after 72 unpowered ticks')
    parser.add_argument('--cold', action='store_true', help='Restart while stopped after three ticks of drive')
    parser.add_argument('--baseline', action='store_true', help='Record a native mismatch before the fix')
    for flag in ('game', 'resources', 'ctl', 'reference', 'create-jar'):
        parser.add_argument('--' + flag, type=Path)
    args = parser.parse_args()
    if args.settled and args.first_hit:
        parser.error('--settled and --first-hit are mutually exclusive')
    if args.cold and not args.first_hit:
        parser.error('--cold requires --first-hit')
    fresh = args.fresh_motor
    drive = 'settled' if args.settled else 'fresh' if fresh else 'clutch'
    if args.first_hit:
        drive += '-first-hit'
    if args.cold:
        drive += '-cold'
    if args.java:
        work = Path(tempfile.mkdtemp(prefix='press-scan-java-', dir=ROOT / '.local'))
        print(work, flush=True)
        cases = java_run(work, fresh, args.settled, args.first_hit, args.cold)
        matches = True
    else:
        if not all((args.game, args.resources, args.ctl, args.reference, args.create_jar)):
            parser.error('Horizon requires --game, --resources, --ctl, --reference and --create-jar')
        reference = json.loads(args.reference.read_text())
        assert reference['passed'] and reference['create'] == PINS['create_revision'], reference
        assert reference.get('drive', 'fresh') == drive, reference
        session = NativeCheckSession(args.game, args.resources, args.ctl, args.create_jar,
                                     name='press-scan-native', world='PressScan', graphics=False)
        work = session.scratch
        print(work, flush=True)
        try:
            cases = native_run(session, fresh, args.settled, args.first_hit, args.cold)
        finally:
            session.control_temp.cleanup()
            for folder in (session.resources, work / '.horizon-cache', work / 'horizon-mods'):
                shutil.rmtree(folder, ignore_errors=True)
        matches = cases == reference['cases']
    edges = {name: starts(rows) for name, rows in cases.items()}
    if args.java and args.first_hit:
        rows = cases['first_hit_after_long_stop']
        powered_early = [index for index, row in enumerate(rows[:72], 1) if row['rpm'] or row['running']]
        assert not powered_early, powered_early
        assert edges['first_hit_after_long_stop'] == [83 if fresh else 82] and rows[-1]['finished'], (edges, rows[-1])
        if args.cold:
            before = cases['before_restart']
            assert before[2]['rpm'] == 64 and before[-1]['rpm'] == 0 and not starts(before), before
    elif args.java and fresh:
        assert edges == FRESH_JAVA_STARTS and cases['miss_keeps_scan'][31]['ticks'] == 120, edges
    if args.java and args.settled:
        assert edges == SETTLED_JAVA_STARTS, edges
    path = work / 'result.json'
    path.write_text(json.dumps(dict(passed=matches, create=PINS['create_revision'], drive=drive,
                                    starts=edges, cases=cases), indent=2) + '\n')
    print(path, edges)
    if args.baseline:
        assert not matches, 'The baseline already matched Java'
    elif not args.java:
        assert matches, (edges, reference['starts'])


if __name__ == '__main__':
    main()
