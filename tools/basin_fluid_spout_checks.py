#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Compare water and lava Basin side output queues with the pinned Java game."""

import argparse
import json
from pathlib import Path
import re
import shutil
import tempfile

from basin_spout_checks import inventory
from bearing_native_checks import Batch
from burner_heat_java_checks import field, items
from chain_drive_checks import Original, xyz
from common import PINS, ROOT
from fluid_pump_basin_checks import reservoir
from fluid_pump_java_checks import fluid
from funnel_checks import put
from native_check_session import NativeCheckSession
import reference_java as java


BASIN = 'create:basin'
X, Y, Z = 2455, 172, 1412
AREA = '2451 169 1409 2461 177 1423'
TICKET = '2448 1408 2463 1423'
RECIPES = 'data/create/recipe/mixing'
DATAPACK = 'create-horizon-fluid-spout-check'
LANES = {'water': (Z, 'minecraft:paper'), 'lava': (Z + 6, 'minecraft:stick')}
POSITIONS = [pos for z, _ in LANES.values() for pos in ((X, Y, z), (X + 1, Y - 1, z))]


def stack(kind, amount):
    return {'id': 'minecraft:' + kind, 'amount': amount}


def tanks(cmd, pos, half, values):
    segments = []
    for value in values:
        nbt = '{Fluid:{id:"%s",amount:%d}}' % (value['id'], value['amount']) if value else '{}'
        segments.append('{Level:{Value:0.0f,Target:0.0f,Speed:0.25f,Force:1b},TankContent:' + nbt + '}')
    cmd(f'data merge block {xyz(pos)} {{{half}:[{",".join(segments)}]}}')


def fill_receivers(cmd, amount):
    for kind, (z, _) in LANES.items():
        other = 'water' if kind == 'lava' else 'lava'
        tanks(cmd, (X + 1, Y - 1, z), 'InputTanks', [stack(kind, amount), stack(other, 1000)])


def feed(cmd):
    for z, item in LANES.values():
        inventory(cmd, (X, Y, z), [(item, 1)])


def setup(cmd):
    cmd(f'fill {AREA} minecraft:air')
    cmd('fill 2451 169 1409 2461 169 1423 minecraft:smooth_stone')
    for z, _ in LANES.values():
        put(cmd, (X, Y, z), BASIN)
        put(cmd, (X + 1, Y - 1, z), BASIN)
        put(cmd, (X, Y + 2, z), 'create:mechanical_mixer')
        put(cmd, (X, Y + 2, z - 1), 'create:cogwheel[axis=y]')
        put(cmd, (X, Y + 1, z - 1), 'create:creative_motor[facing=up]{ScrollValue:64}')


def block(cmd, scan):
    fill_receivers(cmd, 900)
    feed(cmd)
    scan(140, 'first_batch')
    feed(cmd)
    scan(140, 'blocked')


def release(cmd, scan):
    scan(4, 'resumed')
    fill_receivers(cmd, 750)
    scan(1, 'released')
    scan(140, 'next_batch')


def reroute(cmd, scan):
    for z, _ in LANES.values():
        put(cmd, (X, Y + 2, z), 'minecraft:air')
        put(cmd, (X + 1, Y, z), 'minecraft:smooth_stone')
    scan(24, 'occluded', facing='down')
    for kind, (z, _) in LANES.items():
        tanks(cmd, (X, Y, z), 'OutputTanks', [stack(kind, 250), None])
    fill_receivers(cmd, 900)
    for z, _ in LANES.values():
        put(cmd, (X + 1, Y, z), 'minecraft:air')
    scan(24, 'migrated')
    fill_receivers(cmd, 750)
    scan(1, 'migration_released')


def parse(raw):
    result = {}
    for i, kind in enumerate(LANES):
        source, receiver = raw[2 * i:2 * i + 2]
        queued = [fluid(nbt) for nbt in re.findall(r'\{[^{}]*\}', field(source, 'FluidOverflow'))]
        result[kind] = dict(input=items(source, 'InputItems'), queued=queued,
                            local=reservoir(source, BASIN)['OutputTanks'],
                            receiver=reservoir(receiver, BASIN))
    return result


def verify(results):
    expected = {
        'first_batch': (0, 250, 900), 'blocked': (1, 250, 900), 'resumed': (1, 250, 900),
        'released': (1, 0, 1000), 'next_batch': (0, 250, 1000),
        'occluded': (0, 0, 1000), 'migrated': (0, 250, 900), 'migration_released': (0, 0, 1000),
    }
    assert set(results) == expected.keys(), results
    for phase, (count, queued, amount) in expected.items():
        for kind, (_, item) in LANES.items():
            other = 'water' if kind == 'lava' else 'lava'
            want = dict(input={item: count} if count else {},
                        queued=[stack(kind, queued)] if queued else [], local=[None, None],
                        receiver={'InputTanks': [stack(kind, amount), stack(other, 1000)],
                                  'OutputTanks': [None, None]})
            got = results[phase][kind]
            assert got == want, (phase, kind, got, want)


def write_recipes(directory):
    for kind, (_, item) in LANES.items():
        (directory / f'zz_create_horizon_spout_{kind}.json').write_text(json.dumps({
            'type': 'create:mixing', 'ingredients': [{'item': item}], 'results': [stack(kind, 250)],
        }) + '\n')


def java_run(work):
    host = Original()
    manifest = json.loads((java.BASE / 'manifest.json').read_text())
    initial = host.call('state', {})
    assert manifest['create_sha256'] == java.CREATE_SHA256
    assert initial['ready'] and initial['data_version'] == 3955, initial
    results = {}

    def scan(ticks, phase, facing='east'):
        rows = host.snapshot(POSITIONS, ticks)
        assert all(row['properties']['facing'] == facing for row in rows[::2]), rows
        results[phase] = parse([row['nbt'] for row in rows])

    host.call('tick', {'frozen': True})
    try:
        with java.fixture_datapack(host, manifest['world'], DATAPACK, RECIPES, write_recipes):
            host.command(f'forceload add {TICKET}')
            host.snapshot(POSITIONS, 20)
            setup(host.command)
            block(host.command, scan)
            release(host.command, scan)
            reroute(host.command, scan)
            verify(results)
    finally:
        host.command(f'fill {AREA} minecraft:air')
        host.command(f'forceload remove {TICKET}')
        host.call('tick', {'frozen': initial['server']['frozen']})
        (work / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')
    return results


def native_run(session):
    prime = Batch()
    prime.load((X, Y, Z))
    prime.run(session, 'materialize-datapack')
    write_recipes(session.scratch / 'horizon-mods/.create-native-content' / RECIPES)
    phases = []

    def scan(ticks, phase, facing='east'):
        batch.tick(ticks)
        for pos in POSITIONS[::2]:
            batch.expect(pos, f'{BASIN}[facing={facing}]')
        for pos in POSITIONS:
            batch.data(pos)
        phases.append(phase)

    batch = Batch()
    batch.load((X, Y, Z))
    setup(batch.command)
    block(batch.command, scan)
    rows = batch.run(session, 'fluid-spout-blocked')
    batch = Batch()
    batch.load((X, Y, Z))
    release(batch.command, scan)
    reroute(batch.command, scan)
    batch.command(f'data merge block {xyz(POSITIONS[0])} '
                  '{FluidOverflow:[{id:"create:tea",amount:250}]}')
    batch.tick(8)
    batch.data(POSITIONS[0])
    rows += batch.run(session, 'fluid-spout-release')
    unsupported = rows.pop()
    assert re.search(r'\bid:\s*"create:tea"', field(unsupported, 'FluidOverflow')), unsupported
    assert 'unsupported basin fluid id' in unsupported, unsupported
    results = {}
    for phase in phases:
        assert all('bearing_check' in row for row in rows[:2]), (phase, rows[:2])
        del rows[:2]
        results[phase] = parse(rows[:4])
        del rows[:4]
    assert not rows, rows
    verify(results)
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--java', action='store_true')
    for flag in ('game', 'resources', 'ctl', 'reference', 'create-jar'):
        parser.add_argument('--' + flag, type=Path)
    args = parser.parse_args()
    if args.java:
        work = Path(tempfile.mkdtemp(prefix='basin-fluid-spout-java-', dir=ROOT / '.local'))
        print(work, flush=True)
        result = java_run(work)
    else:
        if not all((args.game, args.resources, args.ctl, args.reference)):
            parser.error('Horizon requires --game, --resources, --ctl and --reference')
        reference = json.loads(args.reference.read_text())
        assert reference['create'] == PINS['create_revision'] and reference['passed'], reference
        session = NativeCheckSession(args.game, args.resources, args.ctl, args.create_jar,
                                     name='basin-fluid-spout-native', graphics=False, world='CreateBasinFluidSpout')
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
