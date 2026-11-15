#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Compare the 2048-block plain Rope Pulley lift and its refusal boundary."""

import argparse
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
from saved_block_checks import read_saved_chunk_tag


PULLEY = (1207, 140, 311)
MOTOR = (1208, 140, 311)
CAMERA = (1207, 145, 311)
AREA = '1200 122 304 1215 142 319'
COLUMN = '1200 304'
AIR = 'minecraft:air'
SLIME = 'minecraft:slime_block'
EXTRA = (1207, 123, 311)
SOURCE = ((1200, 124, 304), (1215, 131, 319), (1207, 131, 311))
LANDED = tuple((x, y + 8, z) for x, y, z in SOURCE)
ENTITY = '@e[type=create:stationary_contraption,x=1207,y=131,z=311,distance=..15,limit=1]'
COUNT_LANDED = f'fill 1200 132 304 1215 139 319 minecraft:stone replace {SLIME}'
COUNT_REFUSED = f'fill 1200 123 304 1215 131 319 minecraft:stone replace {SLIME}'


def setup(command, count):
    command(f'fill {AREA} {AIR}')
    command(f'setblock {xyz(PULLEY)} create:rope_pulley[axis=x]{{Offset:8f}}')
    command('fill 1207 133 311 1207 139 311 create:rope[waterlogged=false]')
    command('setblock 1207 132 311 create:pulley_magnet[waterlogged=false]')
    command(f'fill 1200 124 304 1215 131 319 {SLIME}')
    if count == 2049:
        command(f'setblock {xyz(EXTRA)} {SLIME}')
    command(f'setblock {xyz(MOTOR)} create:creative_motor[facing=west]{{ScrollValue:128}}')


def pose(nbt):
    running = re.search(r'\bRunning:\s*(0b|1b|true|false)', nbt)
    offset = re.search(r'\bOffset:\s*(-?[0-9.]+)f', nbt)
    return (bool(running and running[1] in ('1b', 'true')),
            float(offset[1]) if offset else 0.0)


def assert_count(message, count):
    assert re.search(rf'\b{count}\b', message), message


def original(work):
    host = Original()
    initial = host.call('state', {})
    assert initial['ready'] and initial['data_version'] == 3955, initial
    host.call('tick', {'frozen': True})
    try:
        host.command('tp @s ' + xyz(CAMERA))
        host.command(f'forceload add {COLUMN}')
        step(host, 20, PULLEY)
        setup(host.command, 2048)
        moving, *cells = step(host, 12, PULLEY, *SOURCE)
        moving_pose = pose(moving['nbt'])
        assert moving_pose[0] and 0 < moving_pose[1] < 8, moving
        assert all(cell['id'] == AIR for cell in cells), cells
        first = host.command(f'data get entity {ENTITY} Contraption.Blocks.BlockList[-2048].State')
        before_first = host.command(f'data get entity {ENTITY} Contraption.Blocks.BlockList[-2049].State')
        assert any(message.endswith(': 0') for message in first['messages']), first
        assert not any(message.endswith(': 0') for message in before_first['messages']), before_first
        landed, *cells = step(host, 40, PULLEY, *LANDED, SOURCE[0])
        assert pose(landed['nbt']) == (False, 0.0), landed
        assert [cell['id'] for cell in cells] == [SLIME, SLIME, SLIME, AIR], cells
        assert_count(' '.join(host.command(COUNT_LANDED)['messages']), 2048)
        setup(host.command, 2049)
        blocked, *cells = step(host, 16, PULLEY, *SOURCE, EXTRA)
        assert pose(blocked['nbt']) == (False, 8.0), blocked
        assert all(cell['id'] == SLIME for cell in cells), cells
        assert_count(' '.join(host.command(COUNT_REFUSED)['messages']), 2049)
        return dict(captured=2048, refused=2049, moving_offset=moving_pose[1])
    finally:
        host.command(f'setblock {xyz(MOTOR)} {AIR}')
        step(host, 4, PULLEY)
        host.command(f'fill {AREA} {AIR}')
        host.command(f'forceload remove {COLUMN}')
        host.call('camera', {key: initial[key] for key in ('position', 'yaw', 'pitch')})
        host.call('tick', {'frozen': initial['server']['frozen']})
        (work / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')


def native(session, reference):
    def saved():
        return read_saved_chunk_tag(session.scratch, PULLEY, SCENE, session.world)['nbt']

    batch = Batch()
    batch.load(CAMERA)
    setup(batch.command, 2048)
    batch.tick(12)
    batch.data(PULLEY)
    for pos in SOURCE:
        batch.expect(pos, AIR)
    moving, *cells = batch.run(session, 'large-pulley-capture')
    moving_pose = pose(moving)
    assert moving_pose[0] and abs(moving_pose[1] - reference['moving_offset']) < 1e-5, moving
    check_blocks(cells)
    geometry = saved()['value']
    assert geometry['Version']['value'] == 3, geometry.keys()
    [record] = geometry['Entries']['value']
    assert len(record['value']['Palette']['value']) == 1
    assert len(record['value']['Blocks']['value']) == 2048 * 4

    batch = Batch()
    batch.load(CAMERA)
    batch.tick(40)
    batch.data(PULLEY)
    for pos in LANDED:
        batch.expect(pos, SLIME)
    batch.expect(SOURCE[0], AIR)
    batch.command(COUNT_LANDED, True)
    landed, *cells = batch.run(session, 'large-pulley-cold-landing')
    assert pose(landed) == (False, 0.0) and saved() is None, landed
    check_blocks(cells[:-1])
    assert_count(cells[-1], 2048)

    batch = Batch()
    batch.load(CAMERA)
    setup(batch.command, 2049)
    batch.tick(16)
    batch.data(PULLEY)
    for pos in (*SOURCE, EXTRA):
        batch.expect(pos, SLIME)
    batch.command(COUNT_REFUSED, True)
    blocked, *cells = batch.run(session, 'oversized-pulley-refused')
    assert pose(blocked) == (False, 8.0) and saved() is None, blocked
    check_blocks(cells[:-1])
    assert_count(cells[-1], 2049)
    return dict(captured=2048, refused=2049, moving_offset=moving_pose[1])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--java', action='store_true')
    for flag in ('game', 'resources', 'ctl', 'create-jar', 'reference'):
        parser.add_argument('--' + flag, type=Path)
    args = parser.parse_args()
    if args.java:
        work = Path(tempfile.mkdtemp(prefix='pulley-capacity-java-', dir=ROOT / '.local'))
        observations = original(work)
    else:
        if not all((args.game, args.resources, args.ctl, args.reference)):
            parser.error('Horizon needs --game, --resources, --ctl and --reference')
        reference = json.loads(args.reference.read_text())
        assert reference['passed'] and reference['create'] == PINS['create_revision'], reference
        session = NativeCheckSession(args.game, args.resources, args.ctl, args.create_jar,
                                     name='pulley-capacity-native', world='PulleyCapacity', graphics=False)
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
