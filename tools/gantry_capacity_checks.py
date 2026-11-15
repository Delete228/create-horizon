#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Compare a full Gantry load, powered stop, resume, and oversize refusal."""

import argparse
import json
from pathlib import Path
import re
import shutil
import struct
import tempfile

from bearing_barrel_checks import check_blocks
from bearing_native_checks import Batch
from bearing_repeat_checks import POSES, SCENE
from chain_drive_checks import Original, xyz
from common import PINS, ROOT
from funnel_checks import step
from native_check_session import NativeCheckSession
from pulley_capacity_checks import AIR, SLIME, assert_count
from saved_block_checks import read_saved_chunk_tag


START = (1249, 141, 327)
STOP = (1250, 141, 327)
END = (1251, 141, 327)
MOTOR = (1248, 140, 327)
BRAKE = (1250, 140, 328)
CAMERA = (1255, 154, 327)
AREA = '1248 138 320 1263 153 335'
COLUMN = '1248 320'
CARRIAGE = 'create:gantry_carriage'
CARRIAGE_STATE = CARRIAGE + '[facing=up,axis_along_first=false]'
ENTITY = '@e[type=create:gantry_contraption,x=1250,y=141,z=327,distance=..4,limit=1]'


def cargo(pos):
    return pos[0], pos[1] + 1, pos[2]


def count(offset):
    return (f'fill {1249 + offset} 142 320 {1261 + offset} 151 335 '
            f'minecraft:stone replace {SLIME}')


def setup(command, oversized=False):
    command(f'fill {AREA} {AIR}')
    for x in range(1249, 1252):
        command(f'setblock {x} 140 327 create:gantry_shaft[facing=east]')
    command(f'setblock {xyz(START)} {CARRIAGE_STATE}')
    command(f'fill 1249 142 320 1261 151 335 {SLIME}')
    command(f'fill 1249 151 320 1261 151 321 {AIR}')
    command(f'fill 1249 151 322 {1254 if oversized else 1255} 151 322 {AIR}')
    command(f'setblock {xyz(MOTOR)} create:creative_motor[facing=east]{{ScrollValue:-128}}')


def original(work):
    host = Original()
    initial = host.call('state', {})
    assert initial['ready'] and initial['data_version'] == 3955, initial
    host.call('tick', {'frozen': True})
    try:
        host.command('tp @s ' + xyz(CAMERA))
        host.command(f'forceload add {COLUMN}')
        step(host, 20, START)
        setup(host.command)
        moving = step(host, 6, START, cargo(START))
        assert all(row['id'] == AIR for row in moving), moving
        entities = [row for row in host.call('entities', {'center': STOP, 'radius': 4})['entities']
                    if row['type'] == 'create:gantry_contraption']
        [entity] = entities
        offset = entity['position'][0] - START[0]
        assert 0 < offset < 2, entity
        queries = [f'data get entity {ENTITY} Contraption.Blocks.BlockList[-{index}].State'
                   for index in (2048, 2049)]
        messages = [' '.join(host.command(query)['messages']) for query in queries]
        assert re.search(r': \d+$', messages[0]) and not re.search(r': \d+$', messages[1]), messages

        host.command(f'setblock {xyz(BRAKE)} minecraft:redstone_block')
        stopped = step(host, 8, START, STOP, END, cargo(STOP))
        assert [row['id'] for row in stopped] == [AIR, CARRIAGE, AIR, SLIME], stopped
        host.command(f'setblock {xyz(BRAKE)} {AIR}')
        landed = step(host, 16, START, STOP, END, cargo(END))
        assert [row['id'] for row in landed] == [AIR, AIR, CARRIAGE, SLIME], landed
        assert_count(' '.join(host.command(count(2))['messages']), 2047)

        setup(host.command, oversized=True)
        refused = step(host, 16, START, STOP, END, cargo(START))
        assert [row['id'] for row in refused] == [CARRIAGE, AIR, AIR, SLIME], refused
        assert_count(' '.join(host.command(count(0))['messages']), 2048)
        return dict(captured_total=2048, refused_total=2049, moving_offset=offset)
    finally:
        host.command(f'setblock {xyz(MOTOR)} {AIR}')
        step(host, 4, START, STOP, END)
        host.command(f'fill {AREA} {AIR}')
        host.command(f'forceload remove {COLUMN}')
        host.call('camera', {key: initial[key] for key in ('position', 'yaw', 'pitch')})
        host.call('tick', {'frozen': initial['server']['frozen']})
        (work / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')


def native(session, reference):
    def saved(keys):
        return read_saved_chunk_tag(session.scratch, START, keys, session.world)['nbt']

    batch = Batch()
    batch.load(CAMERA)
    setup(batch.command)
    batch.tick(6)
    batch.expect(START, AIR)
    batch.expect(cargo(START), AIR)
    check_blocks(batch.run(session, 'large-gantry-capture'))
    geometry = saved(SCENE)['value']
    assert geometry['Version']['value'] == 3
    [record] = geometry['Entries']['value']
    assert len(record['value']['Palette']['value']) == 2
    assert len(record['value']['Blocks']['value']) == 2048 * 4
    [pose] = saved(POSES)['value']['Entries']['value']
    bits = pose['value']['Stroke']['value']['Offset']['value']
    offset = struct.unpack('>f', struct.pack('>I', bits))[0]
    assert abs(offset - reference['moving_offset']) < 1e-6, (offset, reference)

    batch = Batch()
    batch.load(CAMERA)
    batch.put(BRAKE, 'minecraft:redstone_block')
    batch.tick(8)
    for position, state in ((START, AIR), (STOP, CARRIAGE_STATE), (END, AIR), (cargo(STOP), SLIME)):
        batch.expect(position, state)
    check_blocks(batch.run(session, 'large-gantry-cold-brake'))
    assert saved(SCENE) is None and saved(POSES) is None

    batch = Batch()
    batch.load(CAMERA)
    batch.put(BRAKE, AIR)
    batch.tick(16)
    for position, state in ((START, AIR), (STOP, AIR), (END, CARRIAGE_STATE), (cargo(END), SLIME)):
        batch.expect(position, state)
    batch.command(count(2), True)
    rows = batch.run(session, 'large-gantry-resume')
    check_blocks(rows[:-1])
    assert_count(rows[-1], 2047)
    assert saved(SCENE) is None and saved(POSES) is None

    batch = Batch()
    batch.load(CAMERA)
    setup(batch.command, oversized=True)
    batch.tick(16)
    for position, state in ((START, CARRIAGE_STATE), (STOP, AIR), (END, AIR), (cargo(START), SLIME)):
        batch.expect(position, state)
    batch.command(count(0), True)
    rows = batch.run(session, 'oversized-gantry-refused')
    check_blocks(rows[:-1])
    assert_count(rows[-1], 2048)
    assert saved(SCENE) is None and saved(POSES) is None
    return dict(captured_total=2048, refused_total=2049, moving_offset=offset)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--java', action='store_true')
    for flag in ('game', 'resources', 'ctl', 'create-jar', 'reference'):
        parser.add_argument('--' + flag, type=Path)
    args = parser.parse_args()
    if args.java:
        work = Path(tempfile.mkdtemp(prefix='gantry-capacity-java-', dir=ROOT / '.local'))
        observations = original(work)
    else:
        if not all((args.game, args.resources, args.ctl, args.reference)):
            parser.error('Horizon needs --game, --resources, --ctl and --reference')
        reference = json.loads(args.reference.read_text())
        assert reference['passed'] and reference['create'] == PINS['create_revision'], reference
        session = NativeCheckSession(args.game, args.resources, args.ctl, args.create_jar,
                                     name='gantry-capacity-native', world='GantryCapacity', graphics=False)
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
