#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Compare dry vertical piston capacity, both directions and sticky return."""

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
import re
import shutil
import tempfile

from bearing_barrel_checks import check_blocks
from bearing_native_checks import Batch
from bearing_repeat_checks import SCENE
from chain_drive_checks import Original, xyz
from common import PINS, ROOT
from funnel_checks import step
from native_check_session import NativeCheckSession
from pulley_capacity_checks import AIR, SLIME, assert_count, pose
from saved_block_checks import read_saved_chunk_tag


@dataclass(frozen=True)
class Rig:
    x: int
    sign: int
    sticky: bool

    @property
    def base(self):
        return self.x, 140, 311

    @property
    def motor(self):
        return self.x - 1, 140, 311

    @property
    def facing(self):
        return 'up' if self.sign > 0 else 'down'

    def at(self, distance):
        return self.x, 140 + self.sign * distance, 311

    def volume(self, low, high):
        y1, y2 = sorted((self.at(low)[1], self.at(high)[1]))
        return f'{self.x - 7} {y1} 304 {self.x + 8} {y2} 319'

    def clear(self, command):
        command(f'fill {self.volume(-6, 14)} {AIR}')

    def power(self, command, reverse=False):
        rpm = self.sign * (128 if reverse else -128)
        command(f'setblock {xyz(self.motor)} create:creative_motor[facing=east]{{ScrollValue:{rpm}}}')

    def setup(self, command, oversized=False):
        self.clear(command)
        piston = 'sticky_mechanical_piston' if self.sticky else 'mechanical_piston'
        command(f'setblock {xyz(self.base)} create:{piston}[facing={self.facing},axis_along_first=true]')
        for i in range(1, 5):
            command(f'setblock {xyz(self.at(-i))} create:piston_extension_pole[facing={self.facing}]')
        command(f'fill {self.volume(1, 8)} {SLIME}')
        # Keep the Slime face over the motor empty so the drive is outside
        # the moving structure.
        command(f'setblock {self.x - 1} {self.at(1)[1]} 311 {AIR}')
        y = self.at(8)[1]
        end = self.x - (5 if oversized else 4)
        command(f'fill {self.x - 7} {y} 304 {end} {y} 304 {AIR}')
        self.power(command)

    def count(self, offset):
        return f'fill {self.volume(1 + offset, 8 + offset)} minecraft:stone replace {SLIME}'


UP = Rig(1223, 1, False)
DOWN = Rig(1239, -1, True)
RIGS = (UP, DOWN)
FORCE = '1216 304 1247 319'
CAMERA = (1230, 154, 311)


def original(work):
    host = Original()
    initial = host.call('state', {})
    assert initial['ready'] and initial['data_version'] == 3955, initial
    host.call('tick', {'frozen': True})
    try:
        host.command('tp @s ' + xyz(CAMERA))
        host.command(f'forceload add {FORCE}')
        bases = [rig.base for rig in RIGS]
        step(host, 20, *bases)
        for rig in RIGS:
            rig.setup(host.command)
        rows = step(host, 12, *bases, *(rig.at(1) for rig in RIGS))
        offsets = [pose(row['nbt'])[1] for row in rows[:2]]
        assert all(pose(row['nbt'])[0] and 0 < pose(row['nbt'])[1] < 4 for row in rows[:2]), rows
        assert all(row['id'] == AIR for row in rows[2:]), rows
        for rig in RIGS:
            selector = f'@e[type=create:stationary_contraption,x={rig.x},y=140,z=311,distance=..10,limit=1]'
            commands = [f'data get entity {selector} Contraption.Blocks.BlockList[-{index}].State'
                        for index in (2048, 2049)]
            messages = [' '.join(host.command(command)['messages']) for command in commands]
            assert re.search(r': \d+$', messages[0]) and not re.search(r': \d+$', messages[1]), messages

        rows = step(host, 24, *bases, *(rig.at(5) for rig in RIGS))
        assert all(row['properties']['state'].lower() == 'extended' for row in rows[:2]), rows
        assert all(row['id'] == SLIME for row in rows[2:]), rows
        for rig in RIGS:
            host.command(f'setblock {xyz(rig.motor)} {AIR}')
        step(host, 2, *bases)
        for rig in RIGS:
            rig.power(host.command, reverse=True)
        rows = step(host, 26, *bases, UP.at(5), DOWN.at(1))
        assert all(row['properties']['state'].lower() == 'retracted' for row in rows[:2]), rows
        assert all(row['id'] == SLIME for row in rows[2:]), rows
        for rig, offset in ((UP, 4), (DOWN, 0)):
            assert_count(' '.join(host.command(rig.count(offset))['messages']), 2043)

        UP.setup(host.command, oversized=True)
        blocked, centre = step(host, 18, UP.base, UP.at(1))
        assert blocked['properties']['state'].lower() == 'retracted' and centre['id'] == SLIME, (blocked, centre)
        assert_count(' '.join(host.command(UP.count(0))['messages']), 2044)
        return dict(captured_total=2048, refused_total=2049, offsets=offsets)
    finally:
        for rig in RIGS:
            host.command(f'setblock {xyz(rig.motor)} {AIR}')
        step(host, 4, UP.base, DOWN.base)
        for rig in RIGS:
            rig.clear(host.command)
        host.command(f'forceload remove {FORCE}')
        host.call('camera', {key: initial[key] for key in ('position', 'yaw', 'pitch')})
        host.call('tick', {'frozen': initial['server']['frozen']})
        (work / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')


def native(session, reference):
    def saved(rig):
        return read_saved_chunk_tag(session.scratch, rig.base, SCENE, session.world)['nbt']

    batch = Batch()
    batch.load(CAMERA)
    for rig in RIGS:
        rig.setup(batch.command)
    batch.tick(12)
    for rig in RIGS:
        batch.data(rig.base)
        batch.expect(rig.at(1), AIR)
    observations = batch.run(session, 'large-vertical-pistons-capture')
    offsets = []
    for i, rig in enumerate(RIGS):
        running, offset = pose(observations[i * 2])
        assert running and abs(offset - reference['offsets'][i]) < 1e-5, observations
        offsets.append(offset)
        geometry = saved(rig)['value']
        assert geometry['Version']['value'] == 3
        [record] = geometry['Entries']['value']
        assert len(record['value']['Palette']['value']) == 3
        assert len(record['value']['Blocks']['value']) == 2048 * 4
    check_blocks(observations[1::2])

    batch = Batch()
    batch.load(CAMERA)
    batch.tick(24)
    for rig in RIGS:
        piston = 'sticky_mechanical_piston' if rig.sticky else 'mechanical_piston'
        batch.expect(rig.base, f'create:{piston}[state=extended]')
        batch.expect(rig.at(5), SLIME)
    check_blocks(batch.run(session, 'large-vertical-pistons-cold-land'))
    assert all(saved(rig) is None for rig in RIGS)

    batch = Batch()
    batch.load(CAMERA)
    for rig in RIGS:
        batch.put(rig.motor, AIR)
    batch.tick(2)
    for rig in RIGS:
        rig.power(batch.command, reverse=True)
    batch.tick(26)
    for rig, offset in ((UP, 4), (DOWN, 0)):
        piston = 'sticky_mechanical_piston' if rig.sticky else 'mechanical_piston'
        batch.expect(rig.base, f'create:{piston}[state=retracted]')
        batch.command(rig.count(offset), True)
    observations = batch.run(session, 'large-vertical-pistons-return')
    check_blocks(observations[::2])
    for row in observations[1::2]:
        assert_count(row, 2043)
    assert all(saved(rig) is None for rig in RIGS)

    batch = Batch()
    batch.load(CAMERA)
    UP.setup(batch.command, oversized=True)
    batch.tick(18)
    batch.expect(UP.base, 'create:mechanical_piston[state=retracted]')
    batch.command(UP.count(0), True)
    observation, count = batch.run(session, 'oversized-vertical-piston-refused')
    check_blocks([observation])
    assert_count(count, 2044)
    assert saved(UP) is None
    return dict(captured_total=2048, refused_total=2049, offsets=offsets)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--java', action='store_true')
    for flag in ('game', 'resources', 'ctl', 'create-jar', 'reference'):
        parser.add_argument('--' + flag, type=Path)
    args = parser.parse_args()
    if args.java:
        work = Path(tempfile.mkdtemp(prefix='piston-capacity-java-', dir=ROOT / '.local'))
        observations = original(work)
    else:
        if not all((args.game, args.resources, args.ctl, args.reference)):
            parser.error('Horizon needs --game, --resources, --ctl and --reference')
        reference = json.loads(args.reference.read_text())
        assert reference['passed'] and reference['create'] == PINS['create_revision'], reference
        session = NativeCheckSession(args.game, args.resources, args.ctl, args.create_jar,
                                     name='piston-capacity-native', world='PistonCapacity', graphics=False)
        work = session.scratch
        try:
            observations = native(session, reference)
        finally:
            session.control_temp.cleanup()
            for folder in (session.resources, work / '.horizon-cache', work / 'horizon-mods'):
                shutil.rmtree(folder, ignore_errors=True)
    output = work / 'result.json'
    output.write_text(json.dumps(dict(passed=True, create=PINS['create_revision'], **observations), indent=2) + '\n')
    print(output)


if __name__ == '__main__':
    main()
