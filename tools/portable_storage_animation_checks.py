#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Check the rendered stationary and moving PSI heads on a real client."""

import argparse
import json
from pathlib import Path
import shutil

from burner_heat_java_checks import items
from chain_drive_checks import xyz
from gantry_portable_storage_checks import OUTPUT, RECEIVED, START, STATION, power, prepare
from native_check_session import NativeCheckSession, wait_loaded


def run(session):
    call = session.call

    def command(text):
        return call('command', text)['chat']

    with session:
        command('gamemode spectator')
        command('tp @s 2922.5 168.5 1825')
        wait_loaded(call, (START, STATION, OUTPUT))
        prepare(command)
        call('look-at', 2917.5, 166.5, 1821.5)
        call('key', 'f1', 'tap')
        call('wait', 12)
        call('screenshot', session.scratch / 'before.png')
        command('tick rate 10')
        power(command)
        call('wait', 55)
        call('screenshot', session.scratch / 'connected.png')
        call('wait', 225)
        cargo = ' '.join(command(f'data get block {xyz(OUTPUT)}'))
        assert items(cargo, 'Items') == RECEIVED and 'psi_gantry_probe:153' in cargo.replace(' ', ''), cargo
        call('screenshot', session.scratch / 'after.png')

    log = session.log.read_text()
    assert 'local resources from Create 6.0.10' in log
    prefix = 'Create dock head: '
    frames = [json.loads(line.split(prefix, 1)[1]) for line in log.splitlines() if prefix in line]
    stationary = [row for row in frames if not row['moving'] and row['pos'] == list(STATION)]
    moving = [row for row in frames if row['moving'] and row['pos'][1:] == list(START[1:])]
    assert stationary and moving, (len(stationary), len(moving))
    for label, side in (('stationary', stationary), ('moving', moving)):
        peak = max(row['extension'] for row in side)
        assert peak > .45, peak
        at = next(i for i, row in enumerate(side) if row['extension'] >= peak - .01)
        assert any(.03 < row['extension'] < peak - .03 for row in side[:at]), ('no extension', label)
        assert any(row['extension'] < peak - .1 for row in side[at+1:]), ('no retraction', label)
    assert any(row['lit'] and row['extension'] > .45 for row in moving)
    assert any(row['lit'] and row['timer'] >= 4 for row in stationary)
    assert any(row['timer'] in (1, 2, 3) and not row['lit'] for row in stationary)
    return dict(passed=True, stationary=stationary, moving=moving)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in ('game', 'resources', 'ctl', 'create-jar'):
        parser.add_argument('--' + flag, type=Path, required=True)
    args = parser.parse_args()
    session = NativeCheckSession(args.game, args.resources, args.ctl, args.create_jar,
                                 name='portable-storage-visual', world='PortableStorageVisual')
    session.env['CREATE_HORIZON_TRACE_DOCK'] = '1'
    session.env.pop('CREATE_HORIZON_TRACE_POSES', None)
    session.env.pop('CREATE_HORIZON_PARTICLE_TRACE', None)
    print(session.scratch, flush=True)
    try:
        result = run(session)
        path = session.scratch / 'result.json'
        path.write_text(json.dumps(result, indent=2) + '\n')
        print(path)
    finally:
        session.control_temp.cleanup()
        for folder in (session.resources, session.scratch / '.horizon-cache', session.scratch / 'horizon-mods'):
            shutil.rmtree(folder, ignore_errors=True)


if __name__ == '__main__':
    main()
