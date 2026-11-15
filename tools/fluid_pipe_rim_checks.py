#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Check the water and lava drips emitted on a pump's first active faces."""

import argparse
import json
from pathlib import Path
import shutil
import tempfile

from chain_drive_checks import Native, Original, xyz
from common import PINS, ROOT
from fluid_pump_java_checks import PUMP, TANK, seed
from funnel_checks import put
from native_check_session import NativeCheckSession, wait_loaded


PUMP_POS = (2559, 172, 1253)
X, Y, Z = PUMP_POS
VIEW = (X+.5, Y, Z+4.5)
FAR = (X+.5, Y, Z+24.5)
SOURCE, TARGET = (X-1, Y, Z), (X+1, Y, Z)
MOTOR = (X-1, Y, Z-1)
AREA = '2556 170 1249 2563 175 1279'
COLUMNS = '2544 1248 2575 1279'
AIR = 'minecraft:air'


def setup(cmd, kind):
    cmd(f'fill {AREA} {AIR}')
    cmd(f'fill {X-2} {Y-1} {Z-2} {X+2} {Y-1} {Z+25} minecraft:smooth_stone')
    put(cmd, SOURCE, TANK)
    put(cmd, TARGET, TANK)
    put(cmd, PUMP_POS, PUMP+'[facing=east,waterlogged=false]')
    put(cmd, (X, Y, Z-1), 'create:cogwheel[axis=x]')
    cmd(seed(SOURCE, kind, 2000))


def start(cmd):
    put(cmd, MOTOR, 'create:creative_motor[facing=east]{ScrollValue:32}')


def rim_side(at):
    dx, dy, dz = [v - p - .5 for v, p in zip(at, PUMP_POS)]
    if .44 <= abs(dx) <= .52 and -.34 <= dy <= .21 and abs(dz) <= .27:
        return 'east' if dx > 0 else 'west'
    return None


def original(work):
    host = Original()
    initial = host.call('state', {})
    assert initial['ready'] and initial['data_version'] == 3955, initial
    observed = {}
    host.call('tick', {'frozen': False})
    try:
        host.command(f'forceload add {COLUMNS}')
        host.call('camera', {'position': VIEW, 'target': PUMP_POS})
        host.call('capture', {'name': f'{work.name}/loaded.png', 'frames': 20})
        for kind in ('water', 'lava'):
            setup(host.command, kind)
            host.call('camera', {'position': VIEW, 'target': PUMP_POS})
            host.call('capture', {'name': f'{work.name}/{kind}-before.png', 'frames': 20})
            before = host.call('particles', {'class_contains': 'DripParticle', 'limit': 512})['samples']
            ids = {p['instance_id'] for p in before}
            start(host.command)
            sides = {}
            for frame in range(6):
                host.call('capture', {'name': f'{work.name}/{kind}-{frame}.png', 'frames': 8})
                samples = host.call('particles', {'class_contains': 'DripParticle', 'limit': 512})['samples']
                for p in samples:
                    side = rim_side(p['position'])
                    if side and p['instance_id'] not in ids:
                        sides.setdefault(side, p)
                if set(sides) == {'east', 'west'}:
                    break
            assert set(sides) == {'east', 'west'}, (kind, sides)
            observed[kind] = sides
        return observed
    finally:
        host.command(f'fill {AREA} {AIR}')
        host.command(f'forceload remove {COLUMNS}')
        host.call('camera', {key: initial[key] for key in ('position', 'yaw', 'pitch')})
        host.call('tick', {'frozen': initial['server']['frozen']})
        (work / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')


def native(session):
    session.env['CREATE_HORIZON_PARTICLE_TRACE'] = '1'

    def events(kind):
        token = 'Create pipe rim: '
        return [p for line in session.log.read_text().splitlines() if token in line
                if (p := json.loads(line.split(token, 1)[1]))['pos'] == list(PUMP_POS)
                and p['fluid'] == f'minecraft:{kind}' and p['splash']]

    observed = {}
    with session:
        host = Native(session)
        host.command(f'tp @s {xyz(VIEW)}')
        wait_loaded(session.call, [SOURCE, TARGET])
        for kind in ('water', 'lava'):
            setup(host.command, kind)
            host.command(f'tp @s {xyz(VIEW)}')
            session.call('wait', 12)
            start(host.command)
            session.call('wait', 18)
            rows = events(kind)
            assert len(rows) == 2 and {row['side'] for row in rows} == {'east', 'west'}, (kind, rows)
            assert all(rim_side(row['at']) == row['side'] for row in rows), rows
            observed[kind] = rows
        setup(host.command, 'water')
        host.command(f'tp @s {xyz(FAR)}')
        session.call('wait', 12)
        start(host.command)
        session.call('wait', 18)
        assert events('water') == observed['water'], 'Started outside the 20-block particle range'
        host.command(f'tp @s {xyz(VIEW)}')
        session.call('wait', 12)
        assert events('water') == observed['water'], 'Returning to an active flow added a false splash'
    return observed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--java', action='store_true')
    for flag in ('game', 'resources', 'ctl', 'create-jar', 'reference'):
        parser.add_argument('--' + flag, type=Path)
    args = parser.parse_args()
    if args.java:
        work = Path(tempfile.mkdtemp(prefix='fluid-rim-java-', dir=ROOT / '.local'))
        print(work, flush=True)
        rows = original(work)
    else:
        if not all((args.game, args.resources, args.ctl, args.create_jar, args.reference)):
            parser.error('Horizon requires --game, --resources, --ctl, --create-jar and --reference')
        session = NativeCheckSession(args.game, args.resources, args.ctl, args.create_jar,
                                     name='fluid-rim-native', world='CreateFluidRim')
        work = session.scratch
        print(work, flush=True)
        try:
            rows = native(session)
        finally:
            session.control_temp.cleanup()
            for folder in (session.resources, work / '.horizon-cache', work / 'horizon-mods'):
                shutil.rmtree(folder, ignore_errors=True)
        expected = json.loads(args.reference.read_text())
        assert expected['passed'] and expected['create'] == PINS['create_revision']
        assert {kind: {p['side'] for p in samples} for kind, samples in rows.items()} == {
            kind: set(sides) for kind, sides in expected['samples'].items()
        }
    result = work / 'result.json'
    result.write_text(json.dumps(dict(passed=True, create=PINS['create_revision'], samples=rows), indent=2) + '\n')
    print(result)


if __name__ == '__main__':
    main()
