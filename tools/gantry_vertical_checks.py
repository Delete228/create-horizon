#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Compare upward and downward Gantry travel on dry vertical rails."""

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
import shutil
import struct
import tempfile

from bearing_barrel_checks import check_blocks
from bearing_mounted_pair_checks import BANK_ITEMS, STORAGE, verify_inventory
from bearing_native_checks import Batch
from bearing_repeat_checks import POSES, SCENE
from chain_drive_checks import Original, xyz
from common import PINS, ROOT
from funnel_checks import step
from native_check_session import NativeCheckSession
from piston_mounted_pair_checks import STATES, matches_java
from pulley_capacity_checks import AIR
from pulley_portable_storage_checks import setblock
from saved_block_checks import read_saved_chunk_tag


CARRIAGE = 'create:gantry_carriage[facing=east,axis_along_first=false]'
CAMERA = (2967, 172, 1821)
COLUMN = '2960 1808'
ROOM = '2961 157 1816 2973 167 1822'
TICKS = 27


@dataclass(frozen=True)
class Rig:
    x: int
    sign: int

    @property
    def direction(self):
        return 'up' if self.sign > 0 else 'down'

    def carriage(self, end=False):
        at_upper_end = end if self.sign > 0 else not end
        return self.x + 1, (164 if at_upper_end else 160), 1819

    def banks(self, end=False):
        x, y, z = self.carriage(end)
        return (x + 1, y, z - 1), (x + 1, y, z + 1)

    @property
    def motor(self):
        return self.x, self.carriage()[1] - self.sign, 1819

    def setup(self, command):
        for y in range(160, 165):
            setblock(command, (self.x, y, 1819), f'create:gantry_shaft[facing={self.direction}]')
        setblock(command, self.carriage(), CARRIAGE)
        x, y, z = self.carriage()
        setblock(command, (x + 1, y, z), 'minecraft:slime_block')
        for pos, state, items in zip(self.banks(), STATES, BANK_ITEMS, strict=True):
            setblock(command, pos, state)
            for slot, item, count, component in items:
                command(f'item replace block {xyz(pos)} container.{slot} with {item}{component} {count}')

    def power(self, command):
        setblock(command, self.motor,
                 f'create:creative_motor[facing={self.direction}]{{ScrollValue:{-32 * self.sign}}}')


RIGS = (Rig(2963, 1), Rig(2969, -1))


def original(work):
    host = Original()
    initial = host.call('state', {})
    assert initial['ready'] and initial['data_version'] == 3955, initial
    host.call('tick', {'frozen': True})
    try:
        host.command('tp @s ' + xyz(CAMERA))
        host.command(f'forceload add {COLUMN}')
        step(host, 20, RIGS[0].carriage())
        host.command(f'fill {ROOM} {AIR}')
        for rig in RIGS:
            rig.setup(host.command)
        step(host, 8, RIGS[0].carriage())
        for rig in RIGS:
            rig.power(host.command)
        points = [pos for rig in RIGS for pos in (rig.carriage(), *rig.banks())]
        moving = step(host, TICKS, *points)
        assert all(row['id'] == AIR for row in moving), moving
        cases = {}
        for rig in RIGS:
            center = rig.carriage()
            [entity] = [entity for entity in host.call('entities', {'center': center, 'radius': 5})['entities']
                        if entity['type'] == 'create:gantry_contraption' and entity['position'][0] == center[0]]
            y = entity['position'][1]
            assert 160 < y < 164, entity
            cases[rig.direction] = dict(y=y)
        points = [pos for rig in RIGS for pos in (rig.carriage(True), *rig.banks(True))]
        landed = step(host, 65, *points)
        for i, rig in enumerate(RIGS):
            carriage, *banks = landed[i * 3:i * 3 + 3]
            assert matches_java(carriage, CARRIAGE), carriage
            assert all(matches_java(row, state) for row, state in zip(banks, STATES, strict=True)), banks
            cases[rig.direction]['items'] = [verify_inventory(row['nbt'], n) for n, row in enumerate(banks)]
        return cases
    finally:
        for rig in RIGS:
            setblock(host.command, rig.motor, AIR)
        step(host, 5, RIGS[0].carriage())
        host.command(f'fill {ROOM} {AIR}')
        host.command(f'forceload remove {COLUMN}')
        host.call('camera', {key: initial[key] for key in ('position', 'yaw', 'pitch')})
        host.call('tick', {'frozen': initial['server']['frozen']})
        (work / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')


def native(session, expected):
    def saved(keys):
        return read_saved_chunk_tag(session.scratch, RIGS[0].carriage(), keys, session.world)['nbt']

    batch = Batch()
    batch.load(CAMERA)
    batch.command(f'fill {ROOM} {AIR}')
    for rig in RIGS:
        rig.setup(batch.command)
    batch.tick(8)
    for rig in RIGS:
        rig.power(batch.command)
    batch.tick(TICKS)
    for rig in RIGS:
        for pos in (rig.carriage(), *rig.banks()):
            batch.expect(pos, AIR)
    check_blocks(batch.run(session, 'vertical-gantry-pair-capture'))
    poses = saved(POSES)['value']['Entries']['value']
    assert len(poses) == 2, poses
    cases = {}
    for pose in poses:
        fields = pose['value']
        owner = tuple(fields['Controller']['value'])
        rig = next(rig for rig in RIGS if owner == rig.carriage())
        bits = fields['Stroke']['value']['Offset']['value']
        y = 160 + struct.unpack('>f', struct.pack('>I', bits))[0]
        assert y == expected[rig.direction]['y'], (rig, y, expected)
        cases[rig.direction] = dict(y=y)

    batch = Batch()
    batch.load(CAMERA)
    batch.tick(70)
    for rig in RIGS:
        batch.expect(rig.carriage(True), CARRIAGE)
        for pos, state in zip(rig.banks(True), STATES, strict=True):
            batch.expect(pos, state)
            batch.data(pos)
    rows = batch.run(session, 'vertical-gantry-pair-cold-landing')
    for index, rig in enumerate(RIGS):
        carriage, chest, chest_nbt, barrel, barrel_nbt = rows[index * 5:index * 5 + 5]
        check_blocks((carriage, chest, barrel))
        cases[rig.direction]['items'] = [verify_inventory(chest_nbt, 0), verify_inventory(barrel_nbt, 1)]
    assert cases == expected and saved(STORAGE) is None and saved(SCENE) is None
    return cases


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--java', action='store_true')
    for name in ('game', 'resources', 'ctl', 'create-jar', 'reference'):
        parser.add_argument('--' + name, type=Path)
    args = parser.parse_args()
    if args.java:
        work = Path(tempfile.mkdtemp(prefix='gantry-vertical-java-', dir=ROOT / '.local'))
        print(work, flush=True)
        cases = original(work)
    else:
        expected = json.loads(args.reference.read_text())
        assert expected['create'] == PINS['create_revision']
        session = NativeCheckSession(args.game, args.resources, args.ctl, args.create_jar,
                                     name='gantry-vertical-native', graphics=False, world='CreateVerticalGantry')
        work = session.scratch
        print(work, flush=True)
        try:
            cases = native(session, expected['cases'])
        finally:
            session.control_temp.cleanup()
            for folder in (session.resources, work / '.horizon-cache', work / 'horizon-mods'):
                shutil.rmtree(folder, ignore_errors=True)
    result = work / 'result.json'
    result.write_text(json.dumps(dict(create=PINS['create_revision'], cases=cases), indent=2) + '\n')
    print(result)


if __name__ == '__main__':
    main()
