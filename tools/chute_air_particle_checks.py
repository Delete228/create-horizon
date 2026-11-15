#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Observe the original Chute air billboards in both game clients."""

import argparse
import json
from pathlib import Path
import shutil
import tempfile
import time

from chain_drive_checks import Original, xyz
from chute_suction_checks import fan_above
from common import PINS, ROOT
from native_check_session import NativeCheckSession, wait_loaded
from particle_checks import records
from reference_java import BASE, CREATE_SHA256


X, Y, Z = 1405, 181, 445
CASES = {'blower': Z, 'suction': Z+4, 'blocked': Z+8, 'reversed': Z+12, 'idle': Z+16}
AREA = (X-3, Y-6, Z-2, X+11, Y+5, Z+18)
CAMERA = (X+9.5, Y-1, Z+8.5)
TARGET = (X+.5, Y+.3, Z+8.5)
VERTICAL = {'blower': (0, 2), 'suction': (-3, 1), 'blocked': (0, 1), 'reversed': (-1, 1)}


def frame(age, lifetime):
    return 6 if age == 0 else age * 7 // lifetime


def verify_position(case, pos, previous, velocity):
    lo, hi = VERTICAL[case]
    assert Y+lo-1/6-.0002 <= pos[1] <= Y+hi+1/6+.0002, (case, pos)
    assert all(abs(at-old-delta) < 1e-9 for at, old, delta in zip(pos, previous, velocity, strict=True)), (
        case, pos, previous, velocity)


def setup(command):
    command('fill ' + xyz(AREA) + ' minecraft:air')
    command(f'fill {X+8} {Y-2} {Z+7} {X+10} {Y-2} {Z+9} minecraft:smooth_stone')
    for name, z in CASES.items():
        if name == 'blower':
            command(f'setblock {X} {Y-2} {z} create:creative_motor[facing=up]{{ScrollValue:128}}')
            command(f'setblock {X} {Y-1} {z} create:encased_fan[facing=up]')
        elif name != 'idle':
            fan_above(command, (X, Y, z), -128 if name == 'reversed' else 128)
        command(f'setblock {X} {Y} {z} create:chute[facing=down,shape=window]')
        if name == 'blocked':
            command(f'setblock {X} {Y-1} {z} minecraft:stone')


def signature(at, lifetime, origin_y=None):
    if lifetime >= 25:
        return 'draw-in'
    if origin_y is not None:
        if origin_y == 1 and lifetime > 5:
            return 'blow-out'
        if origin_y == 0 and lifetime < 5:
            return 'exhaust'
        return 'window'
    if lifetime > 5 and at > 1.2:
        return 'blow-out'
    if lifetime < 5 and at < -.2:
        return 'exhaust'
    return 'window'


def verify_cases(cases):
    expected = {'blower': {'window', 'blow-out'}, 'suction': {'window', 'draw-in'},
                'blocked': {'window'}, 'reversed': {'window', 'exhaust'}, 'idle': set()}
    assert {lane: set(samples['paths']) for lane, samples in cases.items()} == expected, cases


def java_run(work):
    host = Original()
    initial = host.call('state', {})
    assert initial['ready'] and initial['data_version'] == 3955
    assert json.loads((BASE / 'manifest.json').read_text())['create_sha256'] == CREATE_SHA256
    samples = []
    try:
        host.call('camera', {'position': CAMERA, 'target': TARGET})
        host.call('tick', {'frozen': False})
        for pos in ((X-3, Y, Z-2), (X+11, Y, Z+18)):
            for _ in range(40):
                result = host.command(f'execute if loaded {xyz(pos)}')
                if any('Test passed' in line for line in result['messages']):
                    break
                time.sleep(.15)
            else:
                raise AssertionError(('Chute air fixture column did not load', pos))
        setup(host.command)
        host.call('camera', {'position': CAMERA, 'target': TARGET})
        time.sleep(1.5)
        for _ in range(30):
            response = host.call('particles', {'limit': 1024, 'partial': .5,
                                              'class_contains': 'foundation.particle.AirParticle'})
            samples.extend(response['samples'])
            time.sleep(.14)
        photo = host.call('capture', {'frames': 2, 'name': 'chute-air-lanes.png'})
        shutil.move(photo['path'], work / 'chute-air.png')
    finally:
        host.command('fill ' + xyz(AREA) + ' minecraft:air')
        host.call('camera', {k: initial[k] for k in ('position', 'yaw', 'pitch')})
        host.call('tick', {'frozen': initial['server']['frozen']})
        (work / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')

    result = {}
    for name, z in CASES.items():
        found = [p for p in samples if X <= p['position'][0] < X+1 and z <= p['position'][2] < z+1]
        paths = set()
        for p in found:
            fields = p['fields']
            assert p['render_type'] == 'PARTICLE_SHEET_TRANSLUCENT' and fields['alpha'] == .25, p
            assert not fields['hasPhysics'] and .075 <= p['base_quad_size'] <= .15, p
            assert p['sprite'].endswith(f'generic_{7-frame(fields["age"], fields["lifetime"])}'), p
            if fields['age'] > 0:
                verify_position(name, p['position'], [fields[k] for k in ('xo', 'yo', 'zo')],
                                [fields[k] for k in ('xd', 'yd', 'zd')])
            paths.add(signature(p['position'][1] - Y, fields['lifetime']))
        result[name] = dict(paths=sorted(paths), samples=len(found),
                            colors=sorted({tuple(p['fields'][k] for k in ('rCol', 'gCol', 'bCol')) for p in found}),
                            lifetimes=sorted({p['fields']['lifetime'] for p in found}))
    return result


def native_run(session, reference):
    with session:
        call = session.call
        call('command', 'tp @s ' + xyz(CAMERA))
        wait_loaded(call, [(X-3, Y, Z-2), (X+11, Y, Z+18)])
        setup(lambda command: call('command', command))
        call('command', 'tp @s ' + xyz(CAMERA))
        call('look-at', *TARGET)
        call('wait', 35)
        start = session.log.stat().st_size
        call('wait', 160)
        samples = records(session.log, start)
        result = {}
        for name, z in CASES.items():
            air = [p for p in samples if p['kind'] == 'chute_air' and p['origin'] == [X, Y, z]]
            births = [p for p in air if p['event'] == 'spawn']
            paths = set()
            for p in births:
                assert p['quad']['sprite'].endswith('generic_1'), p
                assert all(.075 <= size <= .15 for size in p['quad']['size']), p
                assert p['quad']['rgba'][3] == .25, p
                assert tuple(p['quad']['rgba'][:3]) in map(tuple, reference[name]['colors']), p
                assert p['lifetime'] in reference[name]['lifetimes'], p
                assert X+.25 <= p['position'][0] < X+.75 and z+.25 <= p['position'][2] < z+.75, p
                paths.add(signature(0, p['lifetime'], p['position'][1] - Y))
            for p in air:
                if p['event'] == 'tick' and not p['removed']:
                    assert p['frame'] == frame(p['age'], p['lifetime']), p
                    verify_position(name, p['position'], p['previous'], p['velocity'])
            result[name] = dict(paths=sorted(paths), samples=len(air), spawns=len(births))
        call('screenshot', session.scratch / 'chute-air.png')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fallback', action='store_true')
    for name in ('game', 'resources', 'ctl', 'create-jar', 'reference'):
        parser.add_argument('--' + name, type=Path)
    args = parser.parse_args()
    if args.game:
        if not all((args.resources, args.ctl, args.reference)) or bool(args.create_jar) == args.fallback:
            parser.error('Horizon requires --resources, --ctl, --reference and either --create-jar or --fallback')
        reference = json.loads(args.reference.read_text())
        assert reference['passed'] and reference['create'] == PINS['create_revision']
        session = NativeCheckSession(args.game, args.resources, args.ctl, args.create_jar,
                                     name='chute-air-native', world='ChuteAir')
        session.env.pop('CREATE_HORIZON_TRACE_POSES', None)
        work = session.scratch
        try:
            result = native_run(session, reference['cases'])
        finally:
            for folder in (session.resources, work / '.horizon-cache', work / 'horizon-mods'):
                shutil.rmtree(folder, ignore_errors=True)
    else:
        if args.fallback:
            parser.error('--fallback is only for the native run')
        work = Path(tempfile.mkdtemp(prefix='chute-air-java-', dir=ROOT / '.local'))
        result = java_run(work)
    verify_cases(result)
    receipt = work / 'result.json'
    receipt.write_text(json.dumps(dict(passed=True, create=PINS['create_revision'], fallback=args.fallback,
                                       cases=result), indent=2) + '\n')
    print(receipt)


if __name__ == '__main__':
    main()
