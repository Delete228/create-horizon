#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Compare a Basin's item spout, blocked recipe buffer and Wrench routing."""

import argparse
import json
from pathlib import Path
import re
import shutil
import tempfile

from bearing_native_checks import Batch
from burner_heat_java_checks import field, items
from chain_drive_checks import Original, xyz
from common import PINS, ROOT
from funnel_checks import put, step
from native_check_session import NativeCheckSession
import reference_java


X, Y, Z = 2455, 172, 1400
SOURCE, EAST, WEST = (X, Y, Z), (X + 1, Y - 1, Z), (X - 1, Y - 1, Z)
EAST_OPEN = (X + 1, Y, Z)
MIXER, MOTOR = (X, Y + 2, Z), (X, Y + 1, Z - 1)
AREA = '2451 169 1396 2461 177 1406'
TICKET = '2448 1392 2463 1407'
BASIN = 'create:basin'
BRASS, COPPER, ZINC = 'create:brass_ingot', 'minecraft:copper_ingot', 'create:zinc_ingot'
FILLER = [f'minecraft:{name}' for name in ('stone', 'dirt', 'gravel', 'sand', 'paper', 'stick', 'diamond', 'emerald')]


def inventory(cmd, pos, stacks):
    slots = ','.join(f'{{Slot:{i}b,id:"{item}",count:{count}}}' for i, (item, count) in enumerate(stacks))
    cmd(f'data merge block {xyz(pos)} {{InputItems:{{Size:9,Items:[{slots}]}}}}')


def fill_target(cmd, count):
    inventory(cmd, EAST, [(BRASS, count), *((item, 64) for item in FILLER)])


def setup(cmd):
    cmd(f'fill {AREA} minecraft:air')
    cmd('fill 2451 169 1396 2461 169 1406 minecraft:smooth_stone')
    cmd(f'fill {X+2} {Y-1} {Z} {X+4} {Y-1} {Z} minecraft:smooth_stone')
    put(cmd, SOURCE, BASIN)
    put(cmd, EAST, BASIN)
    fill_target(cmd, 64)
    inventory(cmd, SOURCE, [(COPPER, 1), (ZINC, 1)])
    put(cmd, (X, Y - 1, Z), 'create:blaze_burner[blaze=kindled]{fuelLevel:1,burnTimeRemaining:3000}')
    put(cmd, MIXER, 'create:mechanical_mixer')
    put(cmd, (X, Y + 2, Z - 1), 'create:cogwheel[axis=y]')
    put(cmd, MOTOR, 'create:creative_motor[facing=up]{ScrollValue:64}')


def blocked(cmd, scan, wait):
    wait(140)
    inventory(cmd, SOURCE, [(COPPER, 1), (ZINC, 1)])
    scan(140, 'east')


def release(cmd, scan, wrench):
    scan(4, 'east')
    fill_target(cmd, 63)
    scan(1, 'east')
    fill_target(cmd, 62)
    scan(1, 'east')
    put(cmd, MIXER, 'minecraft:air')
    put(cmd, WEST, BASIN)
    wrench()
    scan(12, 'west')
    wrench()
    scan(12, 'east')
    put(cmd, EAST_OPEN, 'minecraft:smooth_stone')
    scan(22, 'west')
    put(cmd, EAST_OPEN, 'minecraft:air')
    scan(22, 'east')


def directions(raw):
    preferred = re.search(r'\bPreferredSpoutput\s*:\s*"([A-Z]+)"', raw)
    disabled = re.findall(r'"([A-Z]+)"', field(raw, 'DisabledSpoutput'))
    return (preferred[1] if preferred else None), disabled


def parse(rows):
    names = ('blocked', 'reload', 'partial', 'released', 'disabled', 'preferred', 'occluded', 'reopened')
    assert len(rows) == 3 * len(names), rows
    result = {}
    for index, name in enumerate(names):
        facing, source, target = rows[3 * index:3 * index + 3]
        assert items(source, 'OutputItems') == {}, (name, source)
        preferred, disabled = directions(source)
        result[name] = dict(facing=facing, input=items(source, 'InputItems'),
                            buffered=items(source, 'Overflow'), target=items(target, 'InputItems')[BRASS],
                            preferred=preferred, disabled=disabled)
    expected = [
        ('east', 2, 64, None, []), ('east', 2, 64, None, []),
        ('east', 1, 64, None, []), ('east', 0, 63, None, []),
        ('west', 0, 63, None, ['EAST']), ('east', 0, 63, 'EAST', []),
        ('west', 0, 63, 'EAST', []), ('east', 0, 63, 'EAST', []),
    ]
    for name, (facing, buffered, target, preferred, disabled) in zip(names, expected, strict=True):
        want = dict(facing=facing, input={COPPER: 1, ZINC: 1},
                    buffered={BRASS: buffered} if buffered else {}, target=target,
                    preferred=preferred, disabled=disabled)
        assert result[name] == want, (name, result[name], want)
    return result


def java_run(work):
    host = Original()
    manifest = json.loads((reference_java.BASE / 'manifest.json').read_text())
    assert manifest['create_sha256'] == reference_java.CREATE_SHA256
    initial = host.call('state', {})
    if initial.get('screen') == 'PauseScreen':
        host.call('input', {'kind': 'escape'})
        initial = host.call('state', {})
    assert initial['ready'] and initial['data_version'] == 3955, initial
    cmd = host.command
    rows = []

    def scan(ticks, facing):
        source, target = step(host, ticks, SOURCE, EAST)
        assert source['properties']['facing'].lower() == facing, source
        rows.extend([facing, source['nbt'], target['nbt']])

    def wrench():
        cmd('item replace entity @s weapon.mainhand with create:wrench')
        host.call('camera', {'position': (X + 3.25, Y, Z + .14), 'target': (X + .8, Y + .32, Z + .14)})
        host.snapshot([SOURCE], 2)
        hit = host.call('state', {})['hit']
        assert hit['pos'] == list(SOURCE) and hit['face'] == 'east', hit
        host.call('input', {'key': 'use'})
        try:
            host.snapshot([SOURCE], 2)
        finally:
            host.call('input', {'key': 'use', 'down': False})

    host.call('tick', {'frozen': True})
    try:
        cmd(f'forceload add {TICKET}')
        cmd(f'tp @s {X}.5 {Y+3} {Z+4}.5')
        host.snapshot([SOURCE], 20)
        cmd('gamemode creative')
        setup(cmd)
        blocked(cmd, scan, lambda ticks: host.snapshot([SOURCE], ticks))
        release(cmd, scan, wrench)
        return parse(rows)
    finally:
        cmd('item replace entity @s weapon.mainhand with minecraft:air')
        cmd(f'fill {AREA} minecraft:air')
        cmd(f'forceload remove {TICKET}')
        host.call('camera', {'position': initial['position'], 'yaw': initial['yaw'], 'pitch': initial['pitch']})
        host.call('tick', {'frozen': initial['server']['frozen']})
        (work / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')


def native_run(session):
    expected_directions = []

    def scan(ticks, facing):
        batch.tick(ticks)
        batch.expect(SOURCE, f'{BASIN}[facing={facing}]')
        expected_directions.append(facing)
        batch.data(SOURCE)
        batch.data(EAST)

    def wrench():
        batch.command(f'tp @s {X+3.25} {Y} {Z+.5}')
        batch.command('item replace entity @s weapon.mainhand with create:wrench')
        batch.ops.append(dict(op='use_block', pos=SOURCE, face=5, sequence=len(batch.ops)))

    batch = Batch()
    batch.load((X, Y, Z + 4))
    setup(batch.command)
    blocked(batch.command, scan, batch.tick)
    rows = batch.run(session, 'basin-spout-first')
    batch = Batch()
    batch.load((X, Y, Z + 4))
    release(batch.command, scan, wrench)
    rows += batch.run(session, 'basin-spout-restart')
    for i, facing in enumerate(expected_directions):
        assert 'bearing_check' in rows[3 * i], (i, facing, rows[3 * i:3 * i + 3])
        rows[3 * i] = facing
    return parse(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--java', action='store_true')
    for flag in ('game', 'resources', 'ctl', 'reference', 'create-jar'):
        parser.add_argument('--' + flag, type=Path)
    args = parser.parse_args()
    if args.java:
        work = Path(tempfile.mkdtemp(prefix='basin-spout-java-', dir=ROOT / '.local'))
        print(work, flush=True)
        result = java_run(work)
    else:
        if not all((args.game, args.resources, args.ctl, args.reference)):
            parser.error('Horizon requires --game, --resources, --ctl and --reference')
        reference = json.loads(args.reference.read_text())
        assert reference['create'] == PINS['create_revision'] and reference['passed'], reference
        session = NativeCheckSession(args.game, args.resources, args.ctl, args.create_jar,
                                     name='basin-spout-native', graphics=False, world='CreateBasinSpout')
        work = session.scratch
        print(work, flush=True)
        try:
            result = native_run(session)
        finally:
            session.control_temp.cleanup()
            for folder in (session.resources, work / '.horizon-cache', work / 'horizon-mods'):
                shutil.rmtree(folder, ignore_errors=True)
        assert result == reference['cases'], (result, reference)
    path = work / 'result.json'
    path.write_text(json.dumps(dict(passed=True, create=PINS['create_revision'], cases=result), indent=2) + '\n')
    print(path)


if __name__ == '__main__':
    main()
