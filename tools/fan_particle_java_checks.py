#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Observe original-JAR Fan airflow in real, separately seeded clients."""

import argparse
import json
from pathlib import Path
import shutil
import tempfile
import time

from chain_drive_checks import Original, xyz
from common import PINS, ROOT
from native_check_session import NativeCheckSession, wait_loaded
from particle_checks import records
import reference_java


X, Y, Z = 1040, 190, 208
CASES = {
    'smoking': (0, 256, 'minecraft:campfire[lit=true]', 5, 'west'),
    'haunting': (4, -256, 'minecraft:soul_campfire[lit=true]', 5, 'west'),
    'splashing': (8, 256, 'minecraft:oak_fence[waterlogged=true]', 13, None),
    'blasting': (12, 256, 'minecraft:lava', 13, None),
    'blocked': (16, 256, 'minecraft:air', 1, None),
    'short': (20, 256, 'minecraft:air', 1, 'east'),
}
AREA = (X - 3, Y - 1, Z - 2, X + 15, Y + 4, Z + 23)
CAMERA = (X + 6.5, Y + 2, Z + 10.5)
TARGET = (X + 4.5, Y + .5, Z + 6.5)


def command_setup(command):
    command('fill ' + xyz(AREA) + ' minecraft:air')
    command(f'fill {X-3} {Y-1} {Z-2} {X+15} {Y-1} {Z+23} minecraft:smooth_stone')
    for name, (offset, rpm, catalyst, wall, trapdoor) in CASES.items():
        z = Z + offset
        if name == 'blasting':
            for x, y, dz in ((1, 1, 0), (1, 0, -1), (1, 0, 1), (1, -1, 0)):
                command(f'setblock {X+x} {Y+y} {z+dz} minecraft:glass')
            command(f'setblock {X+2} {Y} {z} minecraft:iron_bars')
        if name == 'splashing':
            for side in (z - 1, z + 1):
                command(f'fill {X+1} {Y} {side} {X+13} {Y} {side} minecraft:glass')
        if catalyst != 'minecraft:air':
            command(f'setblock {X+(3 if rpm < 0 else 1)} {Y} {z} {catalyst}')
        block = f'minecraft:oak_trapdoor[facing={trapdoor},open=true]' if trapdoor else 'minecraft:stone'
        command(f'setblock {X+wall} {Y} {z} {block}')
        command(f'setblock {X-1} {Y} {z} create:creative_motor[facing=east]{{ScrollValue:{rpm}}}')
        command(f'setblock {X} {Y} {z} create:encased_fan[facing=east]')
        if name in ('smoking', 'splashing'):
            command(f'setblock {X+3} {Y-1} {z} create:depot'
                    '{HeldItem:{Item:{id:"minecraft:stick",count:1}}}')


def color_matches(name, rgba):
    r, g, b, a = rgba
    epsilon = 1e-6
    if name == 'smoking':
        return r == g == b and 0 <= r <= 85 / 255 + epsilon and a == 1
    if name == 'haunting':
        return 0 <= r <= 18 / 255 + epsilon and 0 <= g <= 101 / 255 + epsilon \
            and 0 <= b <= 104 / 255 + epsilon and a == 1
    if name == 'splashing':
        return 34 / 255 - epsilon <= r <= 68 / 255 + epsilon \
            and 119 / 255 - epsilon <= g <= 153 / 255 + epsilon and b == 1 and a == 1
    if name == 'blasting':
        return r == 1 and 68 / 255 - epsilon <= g <= 136 / 255 + epsilon \
            and 0 <= b <= 85 / 255 + epsilon and a == .5
    return False


def check_motion(previous, position, velocity, bounds, distance, pushing):
    assert all(bounds[i] - .25 <= previous[i] < bounds[i + 3] + .25 for i in range(3)), (
        previous, bounds)
    offset = abs(previous[0] - (X + .5)) - .5
    direction = 1 if pushing else -1
    expected = (distance - (offset - 1)) * direction / 16
    assert abs(velocity[0] - expected) < 1e-10 and velocity[1:] == [0, 0], (velocity, expected)
    assert abs(position[0] - previous[0] - expected) < 1e-10 and position[1:] == previous[1:], (
        position, previous, expected)


def java_run(work):
    host = Original()
    initial = host.call('state', {})
    assert initial['ready'] and initial['data_version'] == 3955
    manifest = json.loads((reference_java.BASE / 'manifest.json').read_text())
    assert manifest['create_sha256'] == reference_java.CREATE_SHA256
    samples = []
    try:
        host.call('camera', {'position': CAMERA, 'target': TARGET})
        host.call('tick', {'frozen': False})
        for x in (AREA[0], AREA[3]):
            for z in (AREA[2], AREA[5]):
                for _ in range(20):
                    check = host.command(f'execute if loaded {x} {Y} {z}')
                    if any('Test passed' in line for line in check['messages']):
                        break
                    time.sleep(.15)
                else:
                    raise AssertionError(('Fan fixture column did not load', x, z))
        command_setup(host.command)
        host.call('camera', {'position': CAMERA, 'target': TARGET})
        time.sleep(3)
        for _ in range(14):
            samples.extend(host.call('particles', {'limit': 1024, 'partial': .5})['samples'])
            time.sleep(.3)
        photo = host.call('capture', {'frames': 2, 'name': 'fan-particle-lanes.png'})
        shutil.move(photo['path'], work / 'fan-particles.png')
        return summarize_java(samples)
    finally:
        host.command('fill ' + xyz(AREA) + ' minecraft:air')
        host.call('camera', {k: initial[k] for k in ('position', 'yaw', 'pitch')})
        host.call('tick', {'frozen': initial['server']['frozen']})
        (work / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')


def summarize_java(samples):
    report = {}
    for name, (offset, rpm, _, _, _) in CASES.items():
        z = Z + offset
        air = [p for p in samples if p.get('air_current', {}).get('origin') == [X, Y, z]]
        assert air, (name, 'no actual Java airflow samples')
        current = air[-1]['air_current']
        assert current['pushing'] == (rpm > 0)
        distance, bounds = current['max_distance'], current['bounds']
        live = [p for p in air if p['fields']['age'] > 0]
        colored = []
        for p in live:
            f = p['fields']
            assert f['lifetime'] == 40 and p['render_type'] == 'PARTICLE_SHEET_TRANSLUCENT', p
            assert not f['hasPhysics'] and .075 <= p['base_quad_size'] <= .15, p
            check_motion([f['xo'], f['yo'], f['zo']], p['position'], [f['xd'], f['yd'], f['zd']],
                         bounds, distance, current['pushing'])
            if f['alpha'] != .25:
                assert color_matches(name, [f['rCol'], f['gCol'], f['bCol'], f['alpha']]), p
                assert p['sprite'].endswith(('generic_7', 'generic_6')), p
                colored.append(p)
        if name not in ('blocked', 'short'):
            assert colored, (name, 'no morphed particles')
        if distance < .25:
            assert not live, (name, 'subquarter current still had live particles')
        report[name] = dict(distance=distance, bounds=bounds, pushing=current['pushing'],
                            samples=len(air), live=len(live), colored=len(colored))
    return report


def native_run(session, reference):
    with session:
        call = session.call

        def command(text):
            return call('command', text)

        command('tp @s ' + xyz(CAMERA))
        wait_loaded(call, [(x, Y, z) for x in (X-3, X+15) for z in (Z-2, Z+23)])
        command_setup(command)
        command('tp @s ' + xyz(CAMERA))
        call('look-at', *TARGET)
        call('wait', 55)
        start = session.log.stat().st_size
        call('wait', 140)
        report = {}
        particles = records(session.log, start)
        for name, (offset, _, _, _, _) in CASES.items():
            rows = [p for p in particles if p['kind'] == 'air_flow' and p['origin'] == [X, Y, Z+offset]]
            spawn = [p for p in rows if p['event'] == 'spawn']
            live = [p for p in rows if p['event'] == 'tick' and not p['removed']]
            assert spawn, (name, 'no actual Horizon airflow samples')
            original = reference[name]
            distance, bounds, pushing = (original[k] for k in ('distance', 'bounds', 'pushing'))
            expected_x = X + 1 + (0 if pushing else distance)
            for p in spawn:
                assert abs(p['position'][0] - expected_x) <= .25, (name, p)
                assert p['quad']['sprite'].endswith('generic_1') and p['lifetime'] == 40, p
            colored = []
            for p in live:
                check_motion(p['previous'], p['position'], p['velocity'], bounds, distance, pushing)
                if p['rgba'][3] != .25:
                    assert color_matches(name, p['rgba']) and p['frame'] in (0, 1), (name, p)
                    colored.append(p)
            assert bool(colored) == bool(original['colored']) and bool(live) == bool(original['live']), (
                name, original, len(colored), len(live))
            report[name] = dict(spawns=len(spawn), live=len(live), colored=len(colored))
        call('screenshot', session.scratch / 'fan-particles.png')
        return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--java', action='store_true')
    for name in ('game', 'resources', 'ctl', 'create-jar', 'reference'):
        parser.add_argument('--' + name, type=Path)
    args = parser.parse_args()
    if args.java:
        work = Path(tempfile.mkdtemp(prefix='fan-particles-java-', dir=ROOT / '.local'))
        result = java_run(work)
    else:
        if not all((args.game, args.resources, args.ctl, args.create_jar, args.reference)):
            parser.error('Horizon checks require --game, --resources, --ctl, --create-jar and --reference')
        reference = json.loads(args.reference.read_text())
        assert reference['passed'] and reference['create'] == PINS['create_revision']
        session = NativeCheckSession(args.game, args.resources, args.ctl, args.create_jar,
                                     name='fan-particles-native', world='CreateFanParticles')
        session.env.pop('CREATE_HORIZON_TRACE_POSES', None)
        work = session.scratch
        try:
            result = native_run(session, reference['cases'])
        finally:
            for folder in (session.resources, work / '.horizon-cache', work / 'horizon-mods'):
                shutil.rmtree(folder, ignore_errors=True)
    receipt = work / 'result.json'
    receipt.write_text(json.dumps(dict(passed=True, create=PINS['create_revision'], cases=result), indent=2) + '\n')
    print(receipt)


if __name__ == '__main__':
    main()
