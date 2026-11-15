#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Check local player ground contact under a weak upward Fan in both clients."""

import argparse
import json
from pathlib import Path
import shutil
import tempfile
import time

from burner_heat_java_checks import number
from chain_drive_checks import Original, xyz
from common import PINS, ROOT
from native_check_session import NativeCheckSession, wait_loaded
import reference_java


X, Y, Z = 1058, 192, 212
FAN = (X, Y - 2, Z)
PLAYER = (X + .5, Y, Z + .5)
CAMERA = (X + 3.5, Y, Z + .5)
AREA = (X - 1, Y - 3, Z - 1, X + 4, Y + 2, Z + 1)


def setup(command):
    command('fill ' + xyz(AREA) + ' minecraft:air')
    command(f'fill {X-1} {Y-1} {Z-1} {X+4} {Y-1} {Z+1} minecraft:stone')
    command(f'setblock {X} {Y-1} {Z} minecraft:iron_bars')
    command(f'setblock {X} {Y-2} {Z} create:encased_fan[facing=up]')


def power(command):
    command(f'setblock {X} {Y-3} {Z} create:creative_motor[facing=up]{{ScrollValue:1}}')


def collect(read, wait):
    wait()
    rows = []
    for _ in range(10):
        rows.append(read())
        wait()
    return rows


def java_run(work):
    host = Original()
    initial = host.call('state', {})
    assert initial['ready'] and initial['data_version'] == 3955
    manifest = json.loads((reference_java.BASE / 'manifest.json').read_text())
    assert manifest['create_sha256'] == reference_java.CREATE_SHA256

    def read():
        row = host.call('rider_pose', {'pos': FAN})
        return {k: row[k] for k in ('position', 'velocity', 'grounded')}

    def wait():
        time.sleep(.15)

    try:
        host.call('camera', {'position': CAMERA})
        host.call('tick', {'frozen': False})
        for _ in range(20):
            check = host.command('execute if loaded ' + xyz(FAN))
            if any('Test passed' in line for line in check['messages']):
                break
            wait()
        else:
            raise AssertionError('Fan ground fixture column did not load')
        setup(host.command)
        host.call('camera', {'position': PLAYER})
        time.sleep(.5)
        idle = collect(read, wait)
        power(host.command)
        time.sleep(.7)
        active = collect(read, wait)
        assert number(host.call('block', {'pos': FAN}), 'Speed') == 1
        return dict(idle=idle, active=active)
    finally:
        host.command('fill ' + xyz(AREA) + ' minecraft:air')
        host.call('camera', {k: initial[k] for k in ('position', 'yaw', 'pitch')})
        host.call('tick', {'frozen': initial['server']['frozen']})
        (work / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')


def native_run(session):
    with session:
        call = session.call

        def command(text):
            return call('command', text)

        def read():
            row = call('status')['player']
            return dict(position=row['position'], velocity=row['velocity'], grounded=row['on_ground'])

        def wait():
            call('wait', 3)

        command('tp @s ' + xyz(CAMERA))
        wait_loaded(call, [FAN])
        setup(command)
        command('tp @s ' + xyz(PLAYER))
        call('wait', 12)
        idle = collect(read, wait)
        power(command)
        call('wait', 18)
        active = collect(read, wait)
        nbt = ' '.join(command('data get block ' + xyz(FAN))['chat'])
        assert number({'nbt': nbt}, 'Speed') == 1, nbt
        return dict(idle=idle, active=active)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--java', action='store_true')
    parser.add_argument('--baseline', action='store_true')
    for name in ('game', 'resources', 'ctl', 'reference'):
        parser.add_argument('--' + name, type=Path)
    args = parser.parse_args()
    if args.java and args.baseline:
        parser.error('--baseline applies to the old Horizon build')
    if args.java:
        work = Path(tempfile.mkdtemp(prefix='fan-ground-java-', dir=ROOT / '.local'))
        result = java_run(work)
        reference = None
    else:
        if not all((args.game, args.resources, args.ctl, args.reference)):
            parser.error('Horizon checks require --game, --resources, --ctl and --reference')
        reference = json.loads(args.reference.read_text())
        assert reference['passed'] and reference['create'] == PINS['create_revision']
        session = NativeCheckSession(args.game, args.resources, args.ctl, None,
                                     name='fan-ground-native', world='CreateFanGround')
        session.env.pop('CREATE_HORIZON_TRACE_POSES', None)
        session.env.pop('CREATE_HORIZON_PARTICLE_TRACE', None)
        work = session.scratch
        try:
            result = native_run(session)
        finally:
            for folder in (session.resources, work / '.horizon-cache', work / 'horizon-mods'):
                shutil.rmtree(folder, ignore_errors=True)
    (work / 'observed.json').write_text(json.dumps(result, indent=2) + '\n')
    idle, active = result['idle'], result['active']
    assert all(row['position'] == list(PLAYER) for row in idle + active), result
    assert all(row['grounded'] for row in idle), idle
    assert all(row['grounded'] == (not args.baseline) for row in active), active
    if reference and args.baseline:
        expected = reference['rows']['active'][0]['velocity'][1]
        assert all(abs(row['velocity'][1] - expected) < 1e-7 for row in active), (active, expected)
    elif reference:
        assert result == reference['rows'], (result, reference['rows'])
    receipt = work / 'result.json'
    receipt.write_text(json.dumps(dict(passed=True, create=PINS['create_revision'], rows=result), indent=2) + '\n')
    print(receipt)


if __name__ == '__main__':
    main()
