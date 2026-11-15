#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Compare item bounce on rotating slime and two controls with Create 6.0.10."""

import argparse
import json
from pathlib import Path
import shutil
import tempfile

from bearing_native_checks import Batch
from burner_heat_java_checks import number
from chain_drive_checks import Original, xyz
from common import PINS, ROOT
from native_check_session import NativeCheckSession
from plough_throw_checks import vector


Y = 100
Z = 212
CASES = {
    'slime': (1571, 'slime_block', 103.10, -0.80),
    'stone': (1575, 'stone', 103.10, -0.80),
    'slow_slime': (1579, 'slime_block', 102.17, -0.08),
}
TICKS = 4


def selector(name):
    return f'@e[type=minecraft:item,tag=rotary_bounce_{name},limit=1]'


def place(command):
    command('fill 1568 98 209 1583 106 215 minecraft:air')
    for x, block, _, _ in CASES.values():
        command(f'setblock {x} {Y} {Z} create:mechanical_bearing[facing=up]')
        command(f'setblock {x} {Y + 1} {Z} minecraft:{block}')
        command(f'setblock {x} {Y - 1} {Z} create:creative_motor[facing=up]{{ScrollValue:8}}')


def drop(command):
    for name, (x, _, height, speed) in CASES.items():
        command(f'summon minecraft:item {x + 0.5} {height} {Z + 0.5} '
                f'{{Tags:["rotary_bounce_{name}"],PickupDelay:32767,Motion:[0d,{speed}d,0d],'
                'Item:{id:"minecraft:iron_ingot",count:1}}')


def observe(command):
    for name in CASES:
        command(f'data get entity {selector(name)} Pos')
        command(f'data get entity {selector(name)} Motion')


def cleanup(command):
    for name in CASES:
        command(f'kill {selector(name)}')
    command('fill 1568 98 209 1583 106 215 minecraft:air')


def collect_java(path):
    host = Original()
    initial = host.call('state', {})
    assert initial['ready'] and initial['data_version'] == 3955, initial
    positions = [(x, Y, Z) for x, _, _, _ in CASES.values()]
    rows = []
    angles = []
    try:
        host.call('tick', {'frozen': True})
        host.command('gamemode creative')
        host.command('tp @s 1575.5 108 212.5')
        host.command('forceload add 1568 208 1583 223')
        host.snapshot(positions, 20)
        place(host.command)
        angles = [number(block, 'Angle', 0) for block in host.snapshot(positions, 8)]
        drop(host.command)
        for _ in range(TICKS):
            host.snapshot(positions, 1)
            observe(lambda command: rows.append(' '.join(host.command(command)['messages'])))
        return angles, rows
    finally:
        cleanup(host.command)
        host.command('forceload remove 1568 208 1583 223')
        host.call('tick', {'frozen': initial['server']['frozen']})
        (path / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')


def collect_native(session):
    batch = Batch()
    batch.load((1575, 107, Z))
    place(batch.command)
    batch.tick(8)
    for x, _, _, _ in CASES.values():
        batch.data((x, Y, Z))
    drop(batch.command)
    for _ in range(TICKS):
        batch.tick()
        observe(lambda command: batch.command(command, True))
    rows = batch.run(session, 'slime-item')
    return [number({'nbt': row}, 'Angle', 0) for row in rows[:len(CASES)]], rows[len(CASES):]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--java', action='store_true')
    for flag in ('game', 'resources', 'ctl', 'create-jar', 'reference'):
        parser.add_argument('--' + flag, type=Path)
    args = parser.parse_args()
    if args.java:
        scratch = Path(tempfile.mkdtemp(prefix='rotary-slime-item-java-', dir=ROOT / '.local'))
    elif all((args.game, args.resources, args.ctl, args.create_jar, args.reference)):
        session = NativeCheckSession(args.game, args.resources, args.ctl, args.create_jar,
                                     name='rotary-slime-item-native', graphics=False)
        scratch = session.scratch
    else:
        parser.error('Horizon comparison requires --game, --resources, --ctl, --create-jar and --reference')
    result = dict(passed=False, source=PINS['create_revision'])
    path = scratch / 'result.json'
    try:
        angles, rows = collect_java(scratch) if args.java else collect_native(session)
        result.update(angles=angles, raw=rows)
        assert all(angle != 0.0 for angle in angles), angles
        assert len(rows) == 2 * len(CASES) * TICKS, rows
        samples = {name: [] for name in CASES}
        for tick in range(TICKS):
            for index, name in enumerate(CASES):
                i = 2 * (tick * len(CASES) + index)
                samples[name].append(dict(pos=vector(rows[i]), motion=vector(rows[i + 1])))
        result['samples'] = samples
        assert samples['slime'][0]['motion'][1] > 0.4, samples
        assert samples['slime'][1]['pos'][1] > samples['slime'][0]['pos'][1], samples
        assert samples['stone'][0]['motion'][1] < 0, samples
        assert all(sample['motion'][1] <= 0 for sample in samples['slow_slime']), samples
        if not args.java:
            original = json.loads(args.reference.read_text())
            assert original['passed'] and original['source'] == result['source'], original
            # Once grounded, an idle item only moves every fourth tick, with
            # a phase derived from its runtime entity ID. Compare both control
            # impacts on tick one and the airborne slime rebound throughout.
            compared = [(samples['slime'], original['samples']['slime']),
                        *((samples[name][:1], original['samples'][name][:1])
                          for name in ('stone', 'slow_slime'))]
            error = max(abs(actual - expected)
                        for native, java in compared
                        for left, right in zip(native, java, strict=True)
                        for key in ('pos', 'motion')
                        for actual, expected in zip(left[key], right[key], strict=True))
            result['max_component_error'] = error
            assert error < 1.0e-5, (error, original['samples'], samples)
        result['passed'] = True
    finally:
        path.write_text(json.dumps(result, indent=2) + '\n')
        if not args.java:
            session.control_temp.cleanup()
            for name in ('resources', 'horizon-mods', '.horizon-cache'):
                disposable = session.scratch / name
                if disposable.is_dir():
                    shutil.rmtree(disposable)
        print(path)


if __name__ == '__main__':
    main()
