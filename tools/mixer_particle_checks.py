#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Compare the actual Mixer item and fluid particles with pinned Java Create."""

import argparse
from collections import Counter, defaultdict
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


X, Y, Z = 2504, 168, 1450
LANES = {'dry': (Z, 32), 'wet': (Z + 4, -32), 'idle': (Z + 8, 0)}
REGION = '2501 166 1448 2507 173 1460'
LOAD = '2496 1440 2511 1471'
CAMERA = (X + 4.5, Y + 2, Z + 4.5)
LOOK = (X + .5, Y + .75, Z + 4.5)
TRACE = 'Create mixer particle: '


def tank(fluid=None, amount=0):
    content = '{Fluid:{id:"%s",amount:%d}}' % (fluid, amount) if fluid else '{}'
    level = amount / 1000
    return ('{Level:{Force:1b,Value:%sf,Target:%sf,Speed:0.25f},TankContent:%s}'
            % (level, level, content))


def drive(cmd, z, rpm):
    block = f'create:creative_motor[facing=up]{{ScrollValue:{rpm}}}' if rpm else 'minecraft:air'
    cmd(f'setblock {X-1} {Y+1} {z} {block}')


def setup(cmd):
    cmd(f'fill {REGION} minecraft:air')
    for lane, (z, rpm) in LANES.items():
        items = ['create:wheat_flour'] if lane == 'wet' else ['minecraft:andesite', 'minecraft:iron_nugget']
        inputs = ','.join(f'{{Slot:{slot},id:"{item}",count:1}}' for slot, item in enumerate(items))
        fluids = (f',InputTanks:[{tank("minecraft:water", 1000)},{tank()}],'
                  f'OutputTanks:[{tank("create:honey", 500)},{tank()}]') if lane == 'wet' else ''
        cmd(f'setblock {X} {Y} {z} create:basin[facing=down]'
            + '{InputItems:{Size:9,Items:[' + inputs + ']}'+ fluids + '}')
        cmd(f'setblock {X} {Y+2} {z} create:mechanical_mixer')
        cmd(f'setblock {X-1} {Y+2} {z} create:cogwheel[axis=y]')
        drive(cmd, z, rpm)


def lane_at(at):
    if abs(at[0] - X - .5) > .3 or abs(at[1] - Y - .75) > 1e-5:
        return None
    return next((name for name, (z, _) in LANES.items() if abs(at[2] - z - .5) <= .3), None)


def vectors(lane, at, motion, fluid):
    z, rpm = LANES[lane]
    dx, dz = at[0] - X - .5, at[2] - z - .5
    assert abs(math.hypot(dx, dz) - .25) < 1e-4, at
    # The driving cog reverses the motor's direction at the mixer.
    assert (dz * motion[0] - dx * motion[2]) * rpm < 0, (lane, at, motion)
    if fluid:
        angle = math.radians(-25 if rpm > 0 else 25)
        expected = (dx * (math.cos(angle) - 1) + dz * math.sin(angle), .25,
                    dz * (math.cos(angle) - 1) - dx * math.sin(angle))
        assert all(abs(actual - target) <= 1 / 128 + 3e-5
                   for actual, target in zip(motion, expected, strict=True)), (at, motion, expected)


def java_run(work):
    host = Original()
    initial = host.call('state', {})
    manifest = json.loads((java.BASE / 'manifest.json').read_text())
    assert initial['data_version'] == 3955 and manifest['create_sha256'] == java.CREATE_SHA256
    grouped = defaultdict(dict)
    try:
        host.call('tick', {'frozen': True})
        host.command(f'forceload add {LOAD}')
        host.call('camera', {'position': CAMERA, 'target': LOOK})
        host.snapshot([(X, Y, z) for z, _ in LANES.values()], 25)
        setup(host.command)
        host.call('tick', {'frozen': False})
        first = None
        deadline = time.monotonic() + 12
        while time.monotonic() < deadline:
            sample = host.call('particles', {'limit': 384})
            tick = sample['level_animation_ticks']
            if first is None:
                first = tick
            for part in sample['samples']:
                if part['fields']['age'] == 0 and lane_at(part['position']) is not None:
                    grouped[tick][part['instance_id']] = part
            if tick >= first + 105:
                break
            time.sleep(.012)
        else:
            raise AssertionError('Java client did not reach the requested observation window')
    finally:
        host.call('tick', {'frozen': True})
        host.command(f'fill {REGION} minecraft:air')
        host.command(f'forceload remove {LOAD}')
        host.call('camera', {key: initial[key] for key in ('position', 'yaw', 'pitch')})
        host.call('tick', {'frozen': initial['server']['frozen']})
    (work / 'observed.json').write_text(json.dumps(grouped, indent=2) + '\n')
    return verify_java(grouped)


def verify_java(grouped):
    ticks = defaultdict(dict)
    colors = {}
    for tick, parts in grouped.items():
        for part in parts.values():
            at = part['position']
            lane = lane_at(at)
            fluid = part['class'].endswith('.FluidStackParticle')
            assert fluid or part['class'].endswith('.BreakingItemParticle'), part
            motion = [part['fields'][key] for key in ('xd', 'yd', 'zd')]
            vectors(lane, at, motion, fluid)
            ticks[lane].setdefault(tick, []).append(part['sprite'])
            if fluid:
                rgba = [part['fields'][key] for key in ('rCol', 'gCol', 'bCol', 'alpha')]
                assert colors.setdefault(part['sprite'], rgba) == rgba, part
    cases = summarize(ticks)
    cases['wet']['fluid_colors'] = colors
    return cases


def summarize(ticks):
    assert not ticks['idle'], ticks['idle']
    result = {}
    for lane, count in [('dry', 2), ('wet', 3)]:
        common = Counter(tuple(sorted(sprites)) for sprites in ticks[lane].values())
        assert len(common) == 1, (lane, common)
        [(sprites, samples)] = common.items()
        assert len(sprites) == count and samples >= 20, (lane, common)
        times = sorted(map(int, ticks[lane]))
        assert times == list(range(times[0], times[-1] + 1)), (lane, times)
        if lane == 'wet':
            assert 'minecraft:block/water_still' in sprites and 'create:fluid/honey_still' in sprites, sprites
        result[lane] = {'sprites': sprites, 'full_ticks': samples}
    return result


def native_run(session, expected):
    with session:
        call = session.call
        cmd = lambda text: call('command', text)
        cmd('gamemode spectator')
        cmd('tp @s ' + xyz(CAMERA))
        call('look-at', *LOOK)
        wait_loaded(call, [(X, Y, z) for z, _ in LANES.values()])
        cmd('tick freeze')
        setup(cmd)
        start = session.log.stat().st_size
        cmd('tick unfreeze')
        call('wait', 35)
        cmd('tick freeze')
        call('wait', 4)
        frozen = session.log.stat().st_size
        assert TRACE in session.log.read_bytes()[start:frozen].decode(errors='replace')
        call('wait', 8)
        assert TRACE not in session.log.read_bytes()[frozen:].decode(errors='replace')
        cmd('tick unfreeze')
        call('wait', 75)
        end = session.log.stat().st_size
    ticks = defaultdict(dict)
    lines = session.log.read_bytes()[start:end].decode(errors='replace').splitlines()
    for line in lines:
        if TRACE not in line:
            continue
        row = json.loads(line.split(TRACE, 1)[1])
        lane = lane_at(row['position'])
        assert lane and row['accepted'], row
        vectors(lane, row['position'], row['velocity'], row['fluid'])
        sprite = row['sprite']
        if ':' not in sprite:
            sprite = 'minecraft:' + sprite
        if row['fluid']:
            color = expected['wet']['fluid_colors'][sprite]
            assert all(abs(a - b) < 1e-6 for a, b in zip(row['rgba'], color, strict=True)), row
        ticks[lane].setdefault(row['tick'], []).append(sprite)
    return summarize(ticks)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--java', action='store_true')
    for flag in ('game', 'resources', 'ctl', 'reference', 'create-jar'):
        parser.add_argument('--' + flag, type=Path)
    args = parser.parse_args()
    if args.java:
        work = Path(tempfile.mkdtemp(prefix='mixer-particle-java-', dir=ROOT / '.local'))
        print(work, flush=True)
        cases = java_run(work)
    else:
        if not all((args.game, args.resources, args.ctl, args.reference, args.create_jar)):
            parser.error('Horizon requires --game, --resources, --ctl, --reference and --create-jar')
        reference = json.loads(args.reference.read_text())
        assert reference['passed'] and reference['create'] == PINS['create_revision'], reference
        session = NativeCheckSession(args.game, args.resources, args.ctl, args.create_jar,
                                     name='mixer-particle-native', world='MixerParticle')
        work = session.scratch
        print(work, flush=True)
        try:
            cases = native_run(session, reference['cases'])
        finally:
            for folder in (session.resources, work / '.horizon-cache', work / 'horizon-mods'):
                shutil.rmtree(folder, ignore_errors=True)
        for lane, case in cases.items():
            expected = reference['cases'][lane]
            assert list(case['sprites']) == expected['sprites'] and case['full_ticks'] == expected['full_ticks'], (
                cases, reference)
    path = work / 'result.json'
    path.write_text(json.dumps(dict(passed=True, create=PINS['create_revision'], cases=cases), indent=2) + '\n')
    print(path)


if __name__ == '__main__':
    main()
