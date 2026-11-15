#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Compare Tank light propagation, layer changes and Wrench windows in both clients."""

import argparse
import json
from pathlib import Path
import shutil
import tempfile
import time

from chain_drive_checks import Native, Original, xyz
from common import PINS, ROOT as REPO
from fluid_tank_checks import LAVA, click, offset, set_fluid
from native_check_session import NativeCheckSession, wait_loaded
import reference_java as java
from saved_block_checks import read_saved_chunk_tag


WORLD = 'CreateTankEffects'
ROOT = (2432, 168, 1043)
MEMBER = offset(ROOT, dy=1)
OUTSIDE = (2428, 167, 1039, 2436, 174, 1048)
INSIDE = (2429, 168, 1040, 2435, 173, 1047)
COLUMN = '2416 1024 2447 1055'
FEET = (2432.5, 168, 1046.65)
AIM = (2432.5, 169.75, 1044)
PROBES = [offset(ROOT, dx=-1, dy=y) for y in range(3)]


def settle(host, ticks):
    if isinstance(host, Native):
        host.session.call('wait', ticks)
    else:
        time.sleep(ticks / 20)


def light_levels(scratch, world, probes):
    first = probes[0]
    rows = read_saved_chunk_tag(scratch, first, ['sections'], world)['nbt']['value']
    section = next(row['value'] for row in rows if row['value']['Y']['value'] == first[1] // 16)
    block = section.get('BlockLight', {}).get('value', [0] * 2048)
    indices = [(y % 16) * 256 + (z % 16) * 16 + (x % 16) for x, y, z in probes]
    return [(block[index // 2] >> ((index % 2) * 4)) & 15 for index in indices]


def scenarios(host, work):
    cmd = host.command
    cmd('gamemode creative')
    cmd(f'fill {xyz(OUTSIDE)} minecraft:smooth_stone')
    cmd(f'fill {xyz(INSIDE)} minecraft:air')
    for dy in range(3):
        cmd(f'setblock {xyz(offset(ROOT, dy=dy))} create:fluid_tank')
    settle(host, 12)
    steps = [
        ('low-lava', LAVA, [11, 10, 9]),
        ('high-lava', LAVA, [11, 11, 10]),
        ('hidden-lava', 'create:wrench', [0, 0, 0]),
        ('shown-lava', 'create:wrench', [11, 11, 10]),
    ]
    results = {}
    for name, item, expected in steps:
        if name == 'high-lava':
            set_fluid(host, ROOT, 8000, 'lava')
        click(host, work, name, item, feet=FEET, aim=AIM, pos=MEMBER)
        settle(host, 30)
        if isinstance(host, Native):
            host.session.call('save-all')

            def read(probes):
                return light_levels(work, WORLD, probes)
        else:
            host.call('capture', {'name': f'{work.name}/{name}-settled.png', 'frames': 18})

            def read(probes):
                return [host.call('block_light', {'pos': p})['block_light'] for p in probes]

        for dx in (0, 1):
            probes = [offset(ROOT, dx=dx, dy=dy) for dy in range(3)]
            results[f'{name}-dx{dx}'] = read(probes)
        observed = read(PROBES)
        assert observed == expected, (name, observed, expected)
        results[name] = observed
        (work / 'observed.json').write_text(json.dumps(results, indent=2) + '\n')
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--java', action='store_true')
    for flag in ('game', 'resources', 'ctl', 'create-jar', 'reference'):
        parser.add_argument('--' + flag, type=Path)
    args = parser.parse_args()
    if args.java:
        work = Path(tempfile.mkdtemp(prefix='fluid-tank-effects-java-', dir=REPO / '.local'))
        print(work, flush=True)
        host = Original()
        initial = host.call('state', {})
        try:
            host.call('tick', {'frozen': False})
            host.command(f'forceload add {COLUMN}')
            settle(host, 20)
            result = scenarios(host, work)
        finally:
            host.command(f'fill {xyz(OUTSIDE)} minecraft:air')
            host.command(f'forceload remove {COLUMN}')
            host.command(f'item replace entity @s weapon.mainhand with minecraft:air')
            host.call('camera', {'position': initial['position'], 'yaw': initial['yaw'], 'pitch': initial['pitch']})
            host.call('tick', {'frozen': initial['server']['frozen']})
            (work / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')
    else:
        if not all((args.game, args.resources, args.ctl, args.create_jar, args.reference)):
            parser.error('Horizon comparison needs --game, --resources, --ctl, --create-jar and --reference')
        session = NativeCheckSession(args.game, args.resources, args.ctl, args.create_jar,
                                     name='fluid-tank-effects-native', world=WORLD)
        work = session.scratch
        print(work, flush=True)
        try:
            with session:
                session.call('command', f'tp @s {xyz(FEET)}')
                wait_loaded(session.call, (ROOT, PROBES[0]))
                result = scenarios(Native(session), work)
        finally:
            for folder in (session.resources, work / '.horizon-cache', work / 'horizon-mods'):
                shutil.rmtree(folder, ignore_errors=True)
        reference = json.loads(args.reference.read_text())
        assert reference == {'passed': True, 'create': PINS['create_revision'], 'cases': result}
    output = work / 'result.json'
    output.write_text(json.dumps({'passed': True, 'create': PINS['create_revision'], 'cases': result}, indent=2) + '\n')
    print(output)


if __name__ == '__main__':
    main()
