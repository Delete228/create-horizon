#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Compare a moving Fluid Valve when the game steps through a frozen tick."""

import argparse
import json
from pathlib import Path
import shutil
import tempfile

from chain_drive_checks import Native, Original, xyz
from common import PINS, ROOT
from fluid_valve_java_checks import AREA, LOAD, VALVE_MOTOR, VALVE_POS, X, Y, Z, drive, setup, valve_state
from funnel_checks import block
from native_check_session import NativeCheckSession, wait_loaded


AIR = 'minecraft:air'


def native_steps(host, count):
    host.command(f'tick step {count}')
    host.session.call('wait', count+4)


def run(host):
    if isinstance(host, Native):
        call = host.session.call
        command = host.command
        command('tp @s ' + xyz((X+.5, Y+4, Z+2.5)))
        wait_loaded(call, (VALVE_POS, VALVE_MOTOR))
        command('tick freeze')
        setup(host)
        native_steps(host, 12)
        command(drive(VALVE_MOTOR, 32, 'south'))
        command('tick unfreeze')
        call('wait', 3)
        command('tick freeze')
        step = lambda n: native_steps(host, n)
    else:
        command = host.command
        host.call('tick', {'frozen': True})
        command(f'forceload add {LOAD}')
        step = lambda n: host.call('tick', {'step': n})
        step(16)
        setup(host)
        step(12)
        host.call('observe_ticks', {'positions': [VALVE_POS], 'ticks': 4,
                                    'commands': ['tick unfreeze', drive(VALVE_MOTOR, 32, 'south')]})

    before = valve_state(block(host, VALVE_POS))['pointer']
    assert 0 < before['value'] < .61 and before['target'] == 1, before
    samples = []
    for _ in range(4):
        step(1)
        samples.append(valve_state(block(host, VALVE_POS))['pointer'])
    increments = [round(curr['value'] - prev['value'], 6)
                  for prev, curr in zip([before, *samples[:-1]], samples, strict=True)]
    return dict(before=before, samples=samples, increments=increments)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--java', action='store_true')
    for flag in ('game', 'resources', 'ctl', 'create-jar', 'reference'):
        parser.add_argument('--'+flag, type=Path)
    args = parser.parse_args()
    if args.java:
        work = Path(tempfile.mkdtemp(prefix='valve-step-java-', dir=ROOT / '.local'))
        print(work, flush=True)
        host = Original()
        initial = host.call('state', {})
        assert initial['ready'] and initial['data_version'] == 3955, initial
        try:
            result = run(host)
        finally:
            host.command(f'fill {AREA} {AIR}')
            host.command(f'forceload remove {LOAD}')
            host.call('tick', {'frozen': initial['server']['frozen']})
            (work / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')
    else:
        if not all((args.game, args.resources, args.ctl, args.create_jar, args.reference)):
            parser.error('Horizon requires --game, --resources, --ctl, --create-jar and --reference')
        session = NativeCheckSession(args.game, args.resources, args.ctl, args.create_jar,
                                     name='valve-step-native', world='CreateValveStep')
        work = session.scratch
        print(work, flush=True)
        try:
            with session:
                result = run(Native(session))
        finally:
            for folder in (session.resources, work / '.horizon-cache', work / 'horizon-mods'):
                shutil.rmtree(folder, ignore_errors=True)

    (work / 'observed.json').write_text(json.dumps(result, indent=2) + '\n')
    assert result['increments'] == [.1]*4, result
    if not args.java:
        expected = json.loads(args.reference.read_text())
        assert expected['passed'] and expected['create'] == PINS['create_revision']
        assert result['increments'] == expected['increments']
        assert [sample['speed'] for sample in result['samples']] == [sample['speed'] for sample in expected['samples']]
        assert [sample['target'] for sample in result['samples']] == [sample['target'] for sample in expected['samples']]
    output = work / 'result.json'
    output.write_text(json.dumps(dict(passed=True, create=PINS['create_revision'], **result), indent=2) + '\n')
    print(output)


if __name__ == '__main__':
    main()
