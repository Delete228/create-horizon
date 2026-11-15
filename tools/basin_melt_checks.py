#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Compare stock honey and chocolate Basin melting and compaction recipes."""

import argparse
import json
from pathlib import Path
import re
import shutil
import tempfile

from basin_spout_checks import inventory
from bearing_native_checks import Batch
from burner_heat_java_checks import field, items, number
from chain_drive_checks import Original
from common import PINS, ROOT
from funnel_checks import put
from native_check_session import NativeCheckSession
import reference_java as java


X, Y, Z = 2455, 172, 1459
AREA = '2451 169 1455 2461 177 1471'
TICKET = '2448 1456 2463 1471'
AIR = 'minecraft:air'
BASIN = 'create:basin'
MIXER = 'create:mechanical_mixer'
HEATER = 'create:blaze_burner'
PRESS = 'create:mechanical_press[facing=east]'
MOTOR = 'create:creative_motor[facing={}]{{ScrollValue:64}}'
LANES = {'honey': (Z, 'minecraft:honey_block', 1000),
         'chocolate': (Z + 6, 'create:bar_of_chocolate', 250)}
POSITIONS = [pos for z, *_ in LANES.values() for pos in ((X, Y, z), (X + 1, Y - 1, z))]


def setup(cmd):
    cmd(f'fill {AREA} minecraft:air')
    cmd('fill 2451 169 1455 2461 169 1471 minecraft:smooth_stone')
    for z, item, _ in LANES.values():
        put(cmd, (X, Y, z), BASIN)
        put(cmd, (X + 1, Y - 1, z), BASIN)
        put(cmd, (X, Y - 1, z), HEATER + '[blaze=smouldering]')
        put(cmd, (X, Y + 2, z), MIXER)
        put(cmd, (X, Y + 2, z - 1), 'create:cogwheel[axis=y]')
        put(cmd, (X, Y + 1, z - 1), MOTOR.format('up'))
        put(cmd, (X + 1, Y + 1, z), PRESS)
        inventory(cmd, (X, Y, z), [(item, 1)])


def melt(cmd, scan, wait):
    scan(100, 'cold')
    for z, _, _ in LANES.values():
        put(cmd, (X, Y + 1, z - 1), 'minecraft:air')
        put(cmd, (X, Y - 1, z), HEATER + '[blaze=kindled]{fuelLevel:1,burnTimeRemaining:3000}')
    wait(15)
    for z, _, _ in LANES.values():
        put(cmd, (X, Y + 1, z - 1), MOTOR.format('up'))
    scan(135, 'melted')


def compact(cmd, scan):
    scan(8, 'resumed')
    for z, _, _ in LANES.values():
        put(cmd, (X + 2, Y + 1, z), MOTOR.format('west'))
    scan(100, 'compacted')


def contents(raw, tag):
    fluids = re.findall(r'\bid\s*:\s*"(create:(?:honey|chocolate))"', field(raw, tag))
    amounts = re.findall(r'\bamount\s*:\s*(\d+)', field(raw, tag))
    return [[kind, int(amount)] for kind, amount in zip(fluids, amounts, strict=True)]


def snapshot(rows):
    result = {}
    for i, kind in enumerate(LANES):
        source, target = rows[2 * i:2 * i + 2]
        assert not contents(source, 'OutputTanks') and not contents(source, 'FluidOverflow'), source
        assert not contents(target, 'OutputTanks') and not contents(target, 'FluidOverflow'), target
        result[kind] = dict(ingredient=items(source, 'InputItems'), fluid=contents(target, 'InputTanks'),
                            output=items(target, 'OutputItems'))
    return result


def verify(result):
    assert set(result) == {'cold', 'melted', 'resumed', 'compacted'}, result
    for kind, (_, item, amount) in LANES.items():
        assert result['cold'][kind] == dict(ingredient={item: 1}, fluid=[], output={}), result
        fluid = dict(ingredient={}, fluid=[['create:' + kind, amount]], output={})
        assert result['melted'][kind] == result['resumed'][kind] == fluid, result
        assert result['compacted'][kind] == dict(ingredient={}, fluid=[], output={item: 1}), result


def java_run(work):
    host = Original()
    manifest = json.loads((java.BASE / 'manifest.json').read_text())
    initial = host.call('state', {})
    assert manifest['create_sha256'] == java.CREATE_SHA256
    assert initial['ready'] and initial['data_version'] == 3955, initial
    result = {}

    def wait(ticks):
        return host.snapshot(POSITIONS, ticks)

    def scan(ticks, phase):
        result[phase] = snapshot([row['nbt'] for row in wait(ticks)])

    host.call('tick', {'frozen': True})
    try:
        host.command(f'forceload add {TICKET}')
        wait(22)
        setup(host.command)
        melt(host.command, scan, wait)
        compact(host.command, scan)
        verify(result)
    finally:
        host.command(f'fill {AREA} {AIR}')
        host.command(f'forceload remove {TICKET}')
        host.call('tick', {'frozen': initial['server']['frozen']})
        (work / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')
    return result


def native_run(session):
    phases = []

    def scan(ticks, phase):
        batch.tick(ticks)
        for pos in POSITIONS:
            batch.data(pos)
        phases.append(phase)

    batch = Batch()
    batch.load((X, Y, Z + 4))
    setup(batch.command)
    melt(batch.command, scan, batch.tick)
    rows = batch.run(session, 'basin-melt')
    batch = Batch()
    batch.load((X, Y, Z + 4))
    compact(batch.command, scan)
    rows += batch.run(session, 'basin-compact-restart')
    assert len(rows) == len(phases) * 4
    result = {phase: snapshot(rows[4 * i:4 * i + 4]) for i, phase in enumerate(phases)}
    verify(result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--java', action='store_true')
    for flag in ('game', 'resources', 'ctl', 'reference', 'create-jar'):
        parser.add_argument('--' + flag, type=Path)
    args = parser.parse_args()
    if args.java:
        work = Path(tempfile.mkdtemp(prefix='basin-melt-java-', dir=ROOT / '.local'))
        print(work, flush=True)
        result = java_run(work)
    else:
        if not all((args.game, args.resources, args.ctl, args.reference)):
            parser.error('Horizon requires --game, --resources, --ctl and --reference')
        reference = json.loads(args.reference.read_text())
        assert reference['create'] == PINS['create_revision'] and reference['passed'], reference
        session = NativeCheckSession(args.game, args.resources, args.ctl, args.create_jar,
                                     name='basin-melt-native', graphics=False, world='CreateBasinMelt')
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
