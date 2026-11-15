#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Observe actual partial-tick rendering for a naturally lifted Chute item."""

import argparse
import json
from pathlib import Path
import shutil
import tempfile
import time

from burner_heat_java_checks import number
from chain_drive_checks import Original, xyz
from chute_suction_checks import fan_above
from common import PINS, ROOT
from funnel_checks import put
from native_check_session import NativeCheckSession, wait_loaded
from reference_java import BASE, CREATE_SHA256


X, Y, Z = 1589, 199, 551
POS = (X, Y, Z)
AREA = (X-3, Y-6, Z-3, X+5, Y+5, Z+3)
CAMERA = (X+3.5, Y-2.6, Z+.5)
TARGET = (X+.5, Y-1, Z+.5)
MARKER = 'chute_cargo_motion_probe'
TRACE = 'Create Chute cargo: '


def setup(command):
    command('fill ' + xyz(AREA) + ' minecraft:air')
    fan_above(command, POS)
    put(command, POS, 'create:chute[facing=down,shape=window]')


def seed(command):
    command(f'summon minecraft:item {X+.5} {Y-2.25} {Z+.5} '
            f'{{Tags:["{MARKER}"],NoGravity:1b,Motion:[0d,0d,0d],PickupDelay:32767s,'
            'Item:{id:"minecraft:red_concrete",count:1}}')


def verify_pose(rows):
    cargo = [row for row in rows if row['count'] == 1]
    assert cargo and min(row['previous'] for row in cargo) < -1.8, cargo[:4]
    moving = [row for row in cargo if row['previous'] != row['current']]
    intermediate = [row for row in moving if .02 < row['partial'] < .98]
    assert len(moving) >= 8 and len(intermediate) >= 5, (len(moving), len(intermediate))
    for row in cargo:
        previous, current, partial, observed = (row[key] for key in ('previous', 'current', 'partial', 'offset'))
        assert 0 <= partial <= 1, row
        assert abs(observed - (previous + partial * (current - previous))) < 3e-7, row
    assert all(row['previous'] == row['current'] == row['offset'] == .5 for row in cargo[-5:]), cargo[-5:]
    return dict(samples=len(cargo), moving=len(moving), intermediate=len(intermediate), parked=.5)


def java_run(work):
    host = Original()
    initial = host.call('state', {})
    assert initial['ready'] and initial['data_version'] == 3955
    assert json.loads((BASE / 'manifest.json').read_text())['create_sha256'] == CREATE_SHA256
    mode = next(mode for mode in ('creative', 'spectator', 'survival', 'adventure')
                if any('Test passed' in line for line in
                       host.command(f'execute if entity @s[gamemode={mode}]')['messages']))
    try:
        host.command('gamemode spectator')
        host.call('camera', {'position': CAMERA, 'target': TARGET, 'hide_gui': True})
        host.call('tick', {'frozen': False})
        for _ in range(35):
            reply = host.command(f'execute if loaded {xyz(POS)}')
            if 'Test passed' in reply['messages']:
                break
            time.sleep(.15)
        else:
            raise AssertionError('Chute cargo motion fixture column did not load')
        setup(host.command)
        time.sleep(.85)
        seed(host.command)
        end = time.monotonic() + 4.0
        rows = []
        while time.monotonic() < end:
            rows.append(host.call('chute_motion', {'pos': POS}))
            time.sleep(.012)
        raw = host.call('block', {'pos': POS})
        assert number(raw, 'ItemPosition') == .5, raw
        return rows
    finally:
        host.command(f'kill @e[type=minecraft:item,tag={MARKER}]')
        host.command('fill ' + xyz(AREA) + ' minecraft:air')
        time.sleep(.35)
        host.command('gamemode ' + mode)
        host.call('camera', {k: initial[k] for k in ('position', 'yaw', 'pitch')} | {'hide_gui': False})
        host.call('tick', {'frozen': initial['server']['frozen']})
        (work / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')


def native_run(session):
    session.env['CREATE_HORIZON_TRACE_CHUTE_CARGO'] = '1'
    with session:
        call = session.call

        def command(value):
            return call('command', value)

        command('gamemode spectator')
        command('tp @s ' + xyz(CAMERA))
        wait_loaded(call, [POS])
        call('look-at', *TARGET)
        setup(command)
        call('wait', 20)
        start = session.log.stat().st_size
        seed(command)
        call('wait', 85)
        raw = ' '.join(command('data get block ' + xyz(POS))['chat'])
        assert number({'nbt': raw}, 'ItemPosition') == .5, raw
        assert 'ChutePreviousPosition' not in raw, raw
        with session.log.open() as log:
            log.seek(start)
            rows = [json.loads(line.split(TRACE, 1)[1]) for line in log if TRACE in line]
        return [row for row in rows if row['pos'] == list(POS)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('game', 'resources', 'ctl', 'create-jar', 'reference'):
        parser.add_argument('--' + name, type=Path)
    args = parser.parse_args()
    if args.game:
        if not all((args.resources, args.ctl, args.create_jar, args.reference)):
            parser.error('Horizon requires --resources, --ctl, --create-jar and --reference')
        reference = json.loads(args.reference.read_text())
        assert reference['passed'] and reference['create'] == PINS['create_revision']
        session = NativeCheckSession(args.game, args.resources, args.ctl, args.create_jar,
                                     name='chute-cargo-motion-native', world='ChuteCargoMotion')
        session.env.pop('CREATE_HORIZON_PARTICLE_TRACE', None)
        session.env.pop('CREATE_HORIZON_TRACE_POSES', None)
        work = session.scratch
        try:
            rows = native_run(session)
        finally:
            for folder in (session.resources, work / '.horizon-cache', work / 'horizon-mods'):
                shutil.rmtree(folder, ignore_errors=True)
    else:
        work = Path(tempfile.mkdtemp(prefix='chute-cargo-motion-java-', dir=ROOT / '.local'))
        rows = java_run(work)
    (work / 'observed.json').write_text(json.dumps(rows, indent=2) + '\n')
    summary = verify_pose(rows)
    if args.game:
        assert summary['parked'] == reference['summary']['parked']
    receipt = work / 'result.json'
    receipt.write_text(json.dumps(dict(passed=True, create=PINS['create_revision'], summary=summary), indent=2) + '\n')
    print(receipt)


if __name__ == '__main__':
    main()
