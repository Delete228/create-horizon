#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Observe live Millstone particles, including the gap between retry cycles."""

import argparse
from collections import defaultdict
import json
import math
from pathlib import Path
import shutil
import tempfile
import time

from chain_drive_checks import Original, xyz
from common import PINS, ROOT
from native_check_session import NativeCheckSession, wait_loaded
import reference_java as java


X, Y = 2140, 168
LANES = {1098: 256, 1102: -256, 1106: 256}
BLOCKED = 1106
REGION = '2138 166 1096 2142 171 1108'
LOAD = '2128 1088 2143 1119'
CAMERA = (X + .5, Y + 2, 1103.5)
TARGET = (X + .5, Y + .5, 1102.5)
TRACE = 'Create millstone particle: '


def drive(command, z, rpm=None):
    block = 'minecraft:air' if rpm is None else f'create:creative_motor[facing=up]{{ScrollValue:{rpm}}}'
    command(f'setblock {X} {Y - 1} {z} {block}')


def setup(command):
    command(f'fill {REGION} minecraft:air')
    for z, rpm in LANES.items():
        blocked = (',OutputInventory:{Size:9,Items:[{Slot:8,id:"minecraft:diamond",count:99,'
                   'components:{"minecraft:max_stack_size":99}}]}') if z == BLOCKED else ''
        command(f'setblock {X} {Y} {z} create:millstone'
                '{InputInventory:{Size:1,Items:[{Slot:0,id:"minecraft:diamond",count:1}]}' + blocked + '}')
        drive(command, z, rpm)


def lane_of(pos):
    x, y, z = pos
    if abs(x - X - .5) <= .6 and abs(y - Y - .5) <= .4:
        return next((lane for lane in LANES if abs(z - lane - .5) <= .6), None)
    return None


def java_particles(host, duration, wait_for_emission=False):
    ticks = defaultdict(dict)
    first = None
    deadline = time.monotonic() + 14
    while time.monotonic() < deadline:
        report = host.call('particles', {'limit': 128, 'class_contains': 'BreakingItemParticle'})
        tick = report['level_animation_ticks']
        at_tick = ticks[tick]
        for part in report['samples']:
            lane = lane_of(part['position'])
            if lane is not None and part['fields']['age'] == 0:
                at_tick[part['instance_id']] = part
        if first is None and (at_tick or not wait_for_emission):
            first = tick
        if first is not None and tick >= first + duration:
            break
        time.sleep(.01)
    else:
        raise AssertionError(f'No {duration}-tick Java client particle window')
    return {tick: list(parts.values()) for tick, parts in ticks.items()}


def java_run(work):
    host = Original()
    manifest = json.loads((java.BASE / 'manifest.json').read_text())
    initial = host.call('state', {})
    assert manifest['create_sha256'] == java.CREATE_SHA256
    assert initial['ready'] and initial['data_version'] == 3955, initial
    try:
        host.call('tick', {'frozen': True})
        host.command('gamemode spectator')
        host.command(f'forceload add {LOAD}')
        host.call('observe_ticks', {'ticks': 32, 'positions': [[X, Y, z] for z in LANES]})
        host.call('camera', {'position': CAMERA, 'target': TARGET})
        setup(host.command)
        host.call('tick', {'frozen': False})
        observations = java_particles(host, 64, wait_for_emission=True)
        for lane in LANES:
            drive(host.command, lane)
        stopped = java_particles(host, 16)
        assert not any(parts for tick, parts in stopped.items() if tick >= min(stopped) + 3), stopped
        for lane, rpm in LANES.items():
            drive(host.command, lane, rpm)
        restarted = java_particles(host, 18, wait_for_emission=True)
        resumed = {lane_of(part['position']) for parts in restarted.values() for part in parts}
        assert resumed == set(LANES) - {BLOCKED}, restarted
    finally:
        host.call('tick', {'frozen': True})
        host.command(f'fill {REGION} minecraft:air')
        host.command(f'forceload remove {LOAD}')
        host.command('gamemode creative')
        host.call('camera', {key: initial[key] for key in ('position', 'yaw', 'pitch')})
        host.call('tick', {'frozen': initial['server']['frozen']})
        (work / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')
    (work / 'observed.json').write_text(json.dumps(observations, indent=2) + '\n')
    (work / 'motor-edges.json').write_text(json.dumps(dict(stopped=stopped, restarted=restarted), indent=2) + '\n')
    return verify_java(observations)


def verify_java(observations):
    result = {}
    for lane, rpm in LANES.items():
        found = {tick: [part for part in parts if lane_of(part['position']) == lane]
                 for tick, parts in observations.items()}
        emitted = [tick for tick, parts in found.items() if parts]
        if lane == BLOCKED:
            assert not emitted, emitted
            result[str(lane)] = {'active': False}
            continue
        assert len(emitted) >= 24, (lane, emitted)
        assert all(len(found[tick]) == 1 for tick in emitted), (lane, found)
        gaps = [tick for tick in range(emitted[0] + 1, emitted[-1])
                if tick in found and not found[tick] and found.get(tick - 1) and found.get(tick + 1)]
        assert sum(right - left == 8 for left, right in zip(gaps, gaps[1:])) >= 3, (lane, emitted, gaps)
        for tick in emitted:
            [part] = found[tick]
            assert part['sprite'] == 'minecraft:item/diamond', part
            x, y, z = part['position']
            dx, dz = x - X - .5, z - lane - .5
            # Minecraft's table indices for sine/cosine can differ by one.
            assert abs(y - Y - .5) < 1e-6 and abs(math.hypot(dx, dz) - .5) < 1e-4, part
            vx, vz = part['fields']['xd'], part['fields']['zd']
            assert (dz * vx - dx * vz) * rpm > 0, part
        result[str(lane)] = {'active': True, 'rpm': rpm, 'observed_emissions': len(emitted), 'gaps': gaps}
    return result


def native_run(session):
    with session:
        call = session.call
        command = lambda value: call('command', value)
        command('gamemode spectator')
        command('tp @s ' + xyz(CAMERA))
        call('look-at', *TARGET)
        wait_loaded(call, [(X, Y, z) for z in LANES])
        command('tick freeze')
        setup(command)
        start = session.log.stat().st_size
        command('tick unfreeze')
        call('wait', 82)
        end = session.log.stat().st_size
        command('tick freeze')
        call('wait', 4)
        frozen_start = session.log.stat().st_size
        call('wait', 15)
        frozen = session.log.read_bytes()[frozen_start:].decode(errors='replace')
        assert TRACE not in frozen, frozen[-2000:]
        command('tick unfreeze')
        for lane in LANES:
            drive(command, lane)
        call('wait', 6)
        stopped_start = session.log.stat().st_size
        call('wait', 15)
        stopped_end = session.log.stat().st_size
        assert not trace_rows(session, stopped_start, stopped_end), session.log.read_text()[-2000:]
        for lane, rpm in LANES.items():
            drive(command, lane, rpm)
        call('wait', 24)
        restarted = trace_rows(session, stopped_end, session.log.stat().st_size)
        resumed = {row['pos'][2] for row in restarted if row['event'] == 'spawn'}
        assert resumed == set(LANES) - {BLOCKED}, restarted
        (session.scratch / 'motor-edges.json').write_text(json.dumps(restarted, indent=2) + '\n')
    return trace_rows(session, start, end)


def trace_rows(session, start, end):
    lines = session.log.read_bytes()[start:end].decode(errors='replace').splitlines()
    return [json.loads(line.split(TRACE, 1)[1]) for line in lines if TRACE in line]


def verify_native(rows, reference):
    result = {}
    for lane, rpm in LANES.items():
        relevant = [row for row in rows if row['pos'][2] == lane]
        expected = reference[str(lane)]
        if not expected['active']:
            assert not relevant, relevant
            result[str(lane)] = {'active': False}
            continue
        emissions = [row for row in relevant if row['event'] == 'spawn']
        armed = [index for index, row in enumerate(relevant) if row['event'] == 'armed']
        assert len(emissions) >= 42 and len(armed) >= 6, (lane, relevant)
        for left, right in zip(armed[1:-1], armed[2:]):
            assert [row['timer'] for row in relevant[left + 1:right]] == [100, 84, 68, 52, 36, 20, 4], relevant
        for row in emissions:
            assert row['rpm'] == rpm and row['item'] == 'minecraft:diamond' and row['accepted'] == 1, row
            x, y, z = row['position']
            vx, vy, vz = row['velocity']
            dx, dz = x - X - .5, z - lane - .5
            assert abs(y - Y - .5) < 1e-6 and abs(math.hypot(dx, dz) - .5) < 1e-4, row
            assert abs(vy) <= 1 / 128 and (dz * vx - dx * vz) * rpm > 0, row
        result[str(lane)] = {'active': True, 'rpm': rpm, 'emissions': len(emissions), 'arms': len(armed)}
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--java', action='store_true')
    for flag in ('game', 'resources', 'ctl', 'reference', 'create-jar'):
        parser.add_argument('--' + flag, type=Path)
    args = parser.parse_args()
    if args.java:
        work = Path(tempfile.mkdtemp(prefix='millstone-particle-java-', dir=ROOT / '.local'))
        print(work, flush=True)
        result = java_run(work)
    else:
        if not all((args.game, args.resources, args.ctl, args.reference, args.create_jar)):
            parser.error('Horizon requires --game, --resources, --ctl, --reference and --create-jar')
        reference = json.loads(args.reference.read_text())
        assert reference['create'] == PINS['create_revision'] and reference['passed'], reference
        session = NativeCheckSession(args.game, args.resources, args.ctl, args.create_jar,
                                     name='millstone-particle-native', world='CreateMillstoneParticle')
        work = session.scratch
        print(work, flush=True)
        try:
            rows = native_run(session)
            (work / 'observed.json').write_text(json.dumps(rows, indent=2) + '\n')
            result = verify_native(rows, reference['lanes'])
        finally:
            for folder in (session.resources, work / '.horizon-cache', work / 'horizon-mods'):
                shutil.rmtree(folder, ignore_errors=True)
    path = work / 'result.json'
    path.write_text(json.dumps(dict(passed=True, create=PINS['create_revision'], lanes=result), indent=2) + '\n')
    print(path)


if __name__ == '__main__':
    main()
