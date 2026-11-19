#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Compare the 2048/2049 block bearing boundary on Java and Horizon."""

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
import shutil
import tempfile

from bearing_barrel_checks import check_blocks, pose
from bearing_native_checks import Batch
from bearing_repeat_checks import SCENE
from chain_drive_checks import Original, xyz
from common import PINS, ROOT
from funnel_checks import step
from native_check_session import NativeCheckSession
from saved_block_checks import read_saved_chunk_tag

PIVOT = (1256, 130, 263)
CAMERA = (1256, 146, 263)
MOTOR = (1256, 129, 263)
ANCHOR = (1256, 131, 263)
COLUMN = '1248 256'
AIR = 'minecraft:air'
SLIME = 'minecraft:slime_block'
ENTITY = '@e[type=create:stationary_contraption,x=1256,y=131,z=263,distance=..3,limit=1]'


@dataclass(frozen=True)
class Cargo:
    camera: tuple
    area: str
    fills: tuple
    tail: tuple
    turned_tail: tuple
    extra: tuple

    def observed(self):
        return [PIVOT, ANCHOR, self.tail, self.turned_tail, self.extra]


STANDARD = Cargo(CAMERA, '1248 129 256 1263 145 271',
                 ('1250 131 257 1262 142 269', '1258 143 258 1262 143 261'),
                 (1260, 143, 260), (1253, 143, 259), (1262, 143, 262))
TALL = Cargo((1256, 199, 263), '1248 129 256 1263 195 271',
             ('1254 131 259 1257 194 266',),
             (1254, 194, 259), (1252, 194, 265), (1258, 194, 259))


def setup(command, count, cargo=STANDARD):
    command(f'fill {cargo.area} {AIR}')
    command(f'setblock {xyz(PIVOT)} create:mechanical_bearing[facing=up]')
    for volume in cargo.fills:
        command(f'fill {volume} {SLIME}')
    if count == 2049:
        command(f'setblock {xyz(cargo.extra)} {SLIME}')
    command(f'setblock {xyz(MOTOR)} create:creative_motor[facing=up]{{ScrollValue:16}}')


def original(work, cargo):
    observed = cargo.observed()
    host = Original()
    initial = host.call('state', {})
    assert initial['ready'] and initial['data_version'] == 3955, initial
    host.call('tick', {'frozen': True})
    try:
        x, y, z = cargo.camera
        host.command(f'tp @s {x}.5 {y+1} {z}.5')
        host.command(f'forceload add {COLUMN}')
        step(host, 25, PIVOT)
        setup(host.command, 2048, cargo)
        moving, *cells = step(host, 20, *observed)
        moving_pose = pose(moving['nbt'])
        assert moving_pose[0] == 1 and 85 < moving_pose[1] < 105, moving
        assert all(cell['id'] == AIR for cell in cells), cells
        first = host.command(f'data get entity {ENTITY} Contraption.Blocks.BlockList[-2048].State')
        before_first = host.command(f'data get entity {ENTITY} Contraption.Blocks.BlockList[-2049].State')
        assert any(message.endswith(': 0') for message in first['messages']), first
        assert not any(message.endswith(': 0') for message in before_first['messages']), before_first
        host.command(f'setblock {xyz(MOTOR)} {AIR}')
        landed, *cells = step(host, 4, *observed)
        assert pose(landed['nbt']) == [0, 0], landed
        assert [cell['id'] for cell in cells] == [SLIME, AIR, SLIME, AIR], cells
        setup(host.command, 2049, cargo)
        blocked, *cells = step(host, 20, *observed)
        assert pose(blocked['nbt']) == [0, 0], blocked
        assert [cell['id'] for cell in cells] == [SLIME, SLIME, AIR, SLIME], cells
        return dict(captured=2048, refused=2049, angle=moving_pose[1])
    finally:
        host.command(f'setblock {xyz(MOTOR)} {AIR}')
        step(host, 4, PIVOT)
        host.command(f'fill {cargo.area} {AIR}')
        host.command(f'forceload remove {COLUMN}')
        host.call('camera', {key: initial[key] for key in ('position', 'yaw', 'pitch')})
        host.call('tick', {'frozen': initial['server']['frozen']})
        (work / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')


def native(session, reference, cargo):
    observed = cargo.observed()
    def saved():
        return read_saved_chunk_tag(session.scratch, PIVOT, SCENE, session.world)['nbt']

    batch = Batch()
    batch.load(cargo.camera)
    setup(batch.command, 2048, cargo)
    batch.tick(20)
    batch.data(PIVOT)
    for pos in observed[1:]:
        batch.expect(pos, AIR)
    moving, *cells = batch.run(session, 'large-bearing-capture')
    moving_pose = pose(moving)
    assert moving_pose[0] == 1 and abs(moving_pose[1] - reference['angle']) < 0.0001, moving
    check_blocks(cells)
    [record] = saved()['value']['Entries']['value']
    geometry = record['value']
    assert len(geometry['Palette']['value']) == 1 and len(geometry['Blocks']['value']) == 2048 * 4

    batch = Batch()
    batch.load(cargo.camera)
    batch.put(MOTOR, AIR)
    batch.tick(4)
    batch.data(PIVOT)
    for pos, block in zip(observed[1:], [SLIME, AIR, SLIME, AIR], strict=True):
        batch.expect(pos, block)
    landed, *cells = batch.run(session, 'large-bearing-cold-landing')
    assert pose(landed) == [0, 0] and saved() is None, landed
    check_blocks(cells)

    batch = Batch()
    batch.load(cargo.camera)
    setup(batch.command, 2049, cargo)
    batch.tick(20)
    batch.data(PIVOT)
    for pos, block in zip(observed[1:], [SLIME, SLIME, AIR, SLIME], strict=True):
        batch.expect(pos, block)
    blocked, *cells = batch.run(session, 'oversized-bearing-refused')
    assert pose(blocked) == [0, 0] and saved() is None, blocked
    check_blocks(cells)
    return dict(captured=2048, refused=2049, angle=moving_pose[1])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--java', action='store_true')
    parser.add_argument('--tall', action='store_true', help='Use a 64-block-tall payload')
    for name in ('game', 'resources', 'ctl', 'reference'):
        parser.add_argument('--' + name, type=Path)
    args = parser.parse_args()
    cargo = TALL if args.tall else STANDARD
    if args.java:
        work = Path(tempfile.mkdtemp(prefix='bearing-capacity-java-', dir=ROOT / '.local'))
        observation = original(work, cargo)
    else:
        if not all((args.game, args.resources, args.ctl, args.reference)):
            parser.error('Horizon needs --game, --resources, --ctl and --reference')
        source = json.loads(args.reference.read_text())
        assert source['passed'] and source['create'] == PINS['create_revision'], source
        assert source.get('tall', False) == args.tall, source
        session = NativeCheckSession(args.game, args.resources, args.ctl, None,
                                     name='bearing-capacity-native', world='BearingCapacity', graphics=False)
        work = session.scratch
        try:
            observation = native(session, source, cargo)
        finally:
            session.control_temp.cleanup()
            for folder in (session.resources, session.scratch / '.horizon-cache', session.scratch / 'horizon-mods'):
                shutil.rmtree(folder, ignore_errors=True)
    output = work / 'result.json'
    output.write_text(json.dumps(dict(passed=True, create=PINS['create_revision'], tall=args.tall,
                                      **observation), indent=2) + '\n')
    print(output)


if __name__ == '__main__':
    main()
