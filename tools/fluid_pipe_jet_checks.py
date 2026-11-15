#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Compare the open pipe intake and outlet liquid particles with Java."""

import argparse
import json
from pathlib import Path
import shutil
import tempfile

from chain_drive_checks import Native, Original, xyz
from common import PINS, ROOT
from fluid_pipe_open_checks import AIR, AREA, CASES, LOAD, POSITIONS, X, Y, Z, lane, setup
from funnel_checks import put
from native_check_session import NativeCheckSession, wait_loaded


def view(index):
    return (X+.5, Y, lane(index)[1][2]+2.5)


def start(cmd, index):
    _, pump, _ = lane(index)
    put(cmd, (X+1, Y-1, pump[2]), 'create:creative_motor[facing=west]{ScrollValue:32}')


def java_run(work):
    host = Original()
    initial = host.call('state', {})
    assert initial['ready'] and initial['data_version'] == 3955, initial
    host.call('tick', {'frozen': False})
    try:
        host.command(f'forceload add {LOAD}')
        host.call('capture', {'name': f'{work.name}/loaded.png', 'frames': 20})
        report = {}
        for i in (0, 5):
            name, kind, _ = CASES[i]
            end, pump, _ = lane(i)
            setup(host.command)
            host.call('camera', {'position': view(i), 'target': pump})
            host.call('capture', {'name': f'{work.name}/{kind}-before.png', 'frames': 12})
            start(host.command, i)
            for frame in range(12):
                host.call('capture', {'name': f'{work.name}/{kind}-{frame}.png', 'frames': 5})
                samples = host.call('particles', {'class_contains': 'FluidStackParticle', 'limit': 256})['samples']
                candidates = [p for p in samples if p['fields']['age'] <= 2 and
                              sum((a-b)**2 for a, b in zip(p['position'], end)) < 5]
                if candidates:
                    report[name] = candidates
                    break
            assert name in report, (kind, samples)
        return report
    finally:
        host.command(f'fill {AREA} {AIR}')
        host.command(f'forceload remove {LOAD}')
        host.call('camera', {key: initial[key] for key in ('position', 'yaw', 'pitch')})
        host.call('tick', {'frozen': initial['server']['frozen']})
        (work / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')


def native_run(session, reference):
    session.env['CREATE_HORIZON_PARTICLE_TRACE'] = '1'
    report = {}
    with session:
        host = Native(session)
        host.command(f'tp @s {X+.5} {Y+2} {Z+14.5}')
        wait_loaded(session.call, POSITIONS)
        for i in (0, 5):
            name, kind, inbound = CASES[i]
            _, pump, _ = lane(i)
            setup(host.command)
            host.command(f'tp @s {xyz(view(i))}')
            session.call('look-at', *pump)
            session.call('wait', 10)
            start(host.command, i)
            session.call('wait', 18)
            token = 'Create pipe jet: '
            lines = [json.loads(line.split(token, 1)[1]) for line in session.log.read_text().splitlines() if token in line]
            samples = [p for p in lines if p['pos'] == list(pump) and p['fluid'] == f'minecraft:{kind}']
            assert len(samples) >= 7, (name, samples)
            side = -1 if inbound else 1
            java = reference[name][0]
            for p in samples:
                assert p['inbound'] == inbound and p['side'] == ('west' if inbound else 'east'), p
                assert p['sprite'] and p['sprite'].endswith(java['sprite'].split(':', 1)[-1]), p
                assert all(abs(a-java['fields'][k]) < 1e-7 for a, k in zip(p['color'], ('rCol', 'gCol', 'bCol'))), p
                axial = (p['at'][0] - X - .5) * side
                low, high = (.625, .9375) if inbound else (.5, .75)
                assert low <= axial <= high, p
                v = (0.5 - axial) / 16 if inbound else axial / 4
                assert abs(p['motion'][0] - v * side) < 1e-10, p
                if kind == 'lava':
                    assert p['light'] & 0xf0 == java['light'] & 0xf0 == 0xf0, p
            report[name] = samples
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--java', action='store_true')
    for flag in ('game', 'resources', 'ctl', 'create-jar', 'reference'):
        parser.add_argument('--' + flag, type=Path)
    args = parser.parse_args()
    if args.java:
        work = Path(tempfile.mkdtemp(prefix='fluid-jet-java-', dir=ROOT / '.local'))
        print(work, flush=True)
        samples = java_run(work)
    else:
        if not all((args.game, args.resources, args.ctl, args.create_jar, args.reference)):
            parser.error('Horizon requires --game, --resources, --ctl, --create-jar and --reference')
        ref = json.loads(args.reference.read_text())
        assert ref['passed'] and ref['create'] == PINS['create_revision']
        session = NativeCheckSession(args.game, args.resources, args.ctl, args.create_jar,
                                     name='fluid-jet-native', world='CreateFluidJet')
        work = session.scratch
        print(work, flush=True)
        try:
            samples = native_run(session, ref['samples'])
        finally:
            session.control_temp.cleanup()
            for folder in (session.resources, work / '.horizon-cache', work / 'horizon-mods'):
                shutil.rmtree(folder, ignore_errors=True)
    result = work / 'result.json'
    result.write_text(json.dumps(dict(passed=True, create=PINS['create_revision'], samples=samples), indent=2) + '\n')
    print(result)


if __name__ == '__main__':
    main()
