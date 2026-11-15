#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Compare Encased Fan server config, airflow and processing in real clients."""

import argparse
import json
from pathlib import Path
import re
import shutil
import tempfile
import time

from burner_heat_java_checks import items, number
from chain_drive_checks import Native, Original, xyz
from common import PINS, ROOT
from fan_hazard_checks import advance
from funnel_checks import put
from native_check_session import NativeCheckSession, wait_loaded
from particle_checks import records
from reference_java import BASE, CREATE_SHA256


X, Y, Z = 1144, 188, 248
AREA = (X - 32, Y - 3, Z - 2, X + 32, Y + 3, Z + 28)
CAMERA = (X + .5, Y, Z + 10.5)
RANGES = {
    'east_push': (0, 'east', 64, 29, True),
    'east_pull': (4, 'east', -64, 7, False),
    'west_pull': (8, 'west', 64, 29, False),
    'west_push': (12, 'west', -32, 5, True),
}
SETTINGS = dict(fanPushDistance=29, fanPullDistance=7, fanBlockCheckRate=10,
                fanRotationArgmax=64, fanProcessingTime=4)
DEPOTS = [(X-5, Y, Z+21), (X, Y, Z+21), (X+5, Y-1, Z+25)]
TIMED_FANS = [(X-5, Y-1, Z+21), (X, Y-1, Z+21), (X, Y, Z+25)]
WALL = (X+3, Y, Z+25)


def power(command, pos, face, rpm):
    x, y, z = pos
    dx, dy, sign = {'east': (1, 0, 1), 'west': (-1, 0, -1), 'up': (0, 1, 1)}[face]
    put(command, (x-dx, y-dy, z), f'create:creative_motor[facing={face}]{{ScrollValue:{rpm*sign}}}')
    put(command, pos, f'create:encased_fan[facing={face}]')


def setup_ranges(command):
    command('fill ' + xyz(AREA) + ' minecraft:air')
    command(f'fill {X-32} {Y-1} {Z-2} {X+32} {Y-1} {Z+28} minecraft:smooth_stone')
    for offset, face, rpm, _, _ in RANGES.values():
        power(command, (X, Y, Z+offset), face, rpm)


def input_items(command, stations):
    for index, pos in enumerate(stations):
        name, count = [('create:wheat_flour', 1), ('create:wheat_flour', 17), ('minecraft:beef', 1)][index]
        command('data remove block ' + xyz(pos) + ' HeldItem')
        command('data merge block ' + xyz(pos) +
                f' {{HeldItem:{{Item:{{id:"{name}",count:{count}}},Pos:0.5f,PrevPos:0.5f}}}}')


def settings_text(settings):
    return '[kinetics.encasedFan]\n' + ''.join(f'{key} = {value}\n' for key, value in settings.items())


def configure_java(path, base, settings):
    data = base
    for key, value in settings.items():
        expression = rb'(?m)^([ \t]*' + key.encode() + rb'[ \t]*=[ \t]*)[^\r\n]+$'
        data, count = re.subn(expression, rb'\g<1>' + str(value).encode(), data)
        assert count == 1, (path, key, count)
    path.write_bytes(data)


def read_timed(host, ticks, depots):
    if isinstance(host, Native):
        raw = [advance(host, 1, *depots) for _ in range(ticks)]
    else:
        reply = host.call('observe_ticks', {'ticks': ticks, 'positions': depots})
        raw = [sample['blocks'] for sample in reply['samples']]
    return [[dict(items=items(block['nbt'], 'HeldItem'),
                  timer=number(block, 'FanProcessingTime', -2)) for block in tick] for tick in raw]


def timed(host, configure):
    command = host.command
    command('tick freeze')
    put(command, (X+1, Y, Z+25), 'minecraft:campfire[lit=true]')
    put(command, WALL, 'minecraft:stone')
    for pos, fan, face in zip(DEPOTS, TIMED_FANS, ('up', 'up', 'east'), strict=True):
        put(command, pos, f'create:depot[waterlogged={str(face == "up").lower()}]')
        power(command, fan, face, 64)
    observed = advance(host, 2, *TIMED_FANS)
    assert all(number(block, 'Speed') == 64 for block in observed), observed
    put(command, WALL, 'minecraft:air')
    input_items(command, DEPOTS)
    configured = read_timed(host, 17, DEPOTS)
    configure(SETTINGS | dict(fanProcessingTime=0))
    # The normal watcher reloads this independent server's config file.
    time.sleep(2)
    input_items(command, DEPOTS[:2])
    reloaded = read_timed(host, 4, DEPOTS[:2])
    return dict(configured=configured, reloaded=reloaded)


def java_run(work):
    host = Original()
    initial = host.call('state', {})
    assert initial['ready'] and initial['data_version'] == 3955
    assert json.loads((BASE / 'manifest.json').read_text())['create_sha256'] == CREATE_SHA256
    config = BASE / 'game/config/create-server.toml'
    previous = config.read_bytes()

    def configure(settings):
        configure_java(config, previous, settings)

    try:
        configure(SETTINGS)
        host.call('camera', {'position': CAMERA})
        host.call('tick', {'frozen': False})
        for x in (AREA[0], AREA[3]):
            for z in (AREA[2], AREA[5]):
                for _ in range(25):
                    check = host.command(f'execute if loaded {x} {Y} {z}')
                    if any('Test passed' in line for line in check['messages']):
                        break
                    time.sleep(.15)
                else:
                    raise AssertionError(('Fan config fixture column did not load', x, z))
        setup_ranges(host.command)
        host.call('camera', {'position': CAMERA, 'target': (X+.5, Y+.5, Z)})
        time.sleep(2)
        ranges = {}
        for _ in range(6):
            response = host.call('particles', {'class_contains': 'AirFlowParticle', 'limit': 512})
            for particle in response['samples']:
                current = particle['air_current']
                for name, (offset, face, rpm, distance, pushing) in RANGES.items():
                    if current['origin'] == [X, Y, Z+offset]:
                        assert (current['origin_side'], current['speed'], current['max_distance'],
                                current['pushing']) == (face, rpm, distance, pushing), current
                        ranges[name] = current['max_distance']
            if len(ranges) == len(RANGES):
                break
            time.sleep(.25)
        assert len(ranges) == len(RANGES), ranges
        return dict(ranges=ranges, **timed(host, configure))
    finally:
        config.write_bytes(previous)
        host.command('fill ' + xyz(AREA) + ' minecraft:air')
        host.call('camera', {k: initial[k] for k in ('position', 'yaw', 'pitch')})
        host.call('tick', {'frozen': initial['server']['frozen']})
        (work / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')


def native_run(session):
    config = session.scratch / 'config/create-server.toml'
    config.parent.mkdir(exist_ok=True)

    def configure(settings):
        config.write_text(settings_text(settings))

    configure(SETTINGS)
    host = Native(session)
    with session:
        host.command('tp @s ' + xyz(CAMERA))
        wait_loaded(session.call, [(x, Y, z) for x in (AREA[0], AREA[3]) for z in (AREA[2], AREA[5])])
        setup_ranges(host.command)
        host.command('tp @s ' + xyz(CAMERA))
        session.call('wait', 55)
        start = session.log.stat().st_size
        session.call('wait', 55)
        particles = records(session.log, start)
        ranges = {}
        for name, (offset, face, _, distance, pushing) in RANGES.items():
            direction = 1 if face == 'east' else -1
            rows = [p for p in particles if p['kind'] == 'air_flow' and p['event'] == 'tick'
                    and p['origin'] == [X, Y, Z+offset] and not p['removed']]
            assert rows, (name, 'no client airflow over this configured range')
            for row in rows:
                previous_offset = abs(row['previous'][0] - (X + .5)) - .5
                observed_distance = row['velocity'][0] * 16 * direction * (1 if pushing else -1) + previous_offset - 1
                assert abs(observed_distance - distance) < 1e-10, (name, observed_distance, distance)
            ranges[name] = distance
        return dict(ranges=ranges, **timed(host, configure))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--java', action='store_true')
    for name in ('game', 'resources', 'ctl', 'create-jar', 'reference'):
        parser.add_argument('--' + name, type=Path)
    args = parser.parse_args()
    if args.java:
        work = Path(tempfile.mkdtemp(prefix='fan-config-java-', dir=ROOT / '.local'))
        result = java_run(work)
    else:
        if not all((args.game, args.resources, args.ctl, args.create_jar, args.reference)):
            parser.error('Horizon checks require --game, --resources, --ctl, --create-jar and --reference')
        reference = json.loads(args.reference.read_text())
        assert reference['passed'] and reference['create'] == PINS['create_revision']
        session = NativeCheckSession(args.game, args.resources, args.ctl, args.create_jar,
                                     name='fan-config-native', world='CreateFanConfig')
        session.env.pop('CREATE_HORIZON_TRACE_POSES', None)
        work = session.scratch
        try:
            result = native_run(session)
        finally:
            for folder in (session.resources, work / '.horizon-cache', work / 'horizon-mods'):
                shutil.rmtree(folder, ignore_errors=True)
        (work / 'observed.json').write_text(json.dumps(result, indent=2) + '\n')
        assert result == reference['observed'], (result, reference['observed'])
    assert [result['configured'][0][i]['timer'] for i in range(3)] == [5, 9, -2], result
    assert [row[2]['timer'] for row in result['configured']].count(5) == 1, result
    assert [result['reloaded'][0][i]['timer'] for i in range(2)] == [1, 1], result
    receipt = work / 'result.json'
    receipt.write_text(json.dumps(dict(passed=True, create=PINS['create_revision'], observed=result), indent=2) + '\n')
    print(receipt)


if __name__ == '__main__':
    main()
