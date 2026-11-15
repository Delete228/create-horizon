#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Compare component-bearing Crushing Wheel recipe outputs at a blocked Depot."""

import argparse
import json
from pathlib import Path
import re
import shutil
import tempfile

from bearing_native_checks import Batch
from burner_heat_java_checks import field, items, number
from chain_drive_checks import Original, xyz
from common import PINS, ROOT
from crushing_wheel_checks import AIR, CHUTE, X, Y, put, seed_chute, wheels
from native_check_session import NativeCheckSession
import reference_java as java


Z = 1048
AREA = f'{X-2} {Y-2} {Z-2} {X+2} {Y+4} {Z+2}'
TICKET = '2128 1040 2143 1055'
CONTROL, DEPOT, FEED = (X, Y, Z), (X, Y - 1, Z), (X, Y + 1, Z)
RECIPES = 'data/create/recipe/crushing'
PACK = 'create-horizon-crusher-component-check'
INPUT = 'minecraft:nether_star'
INVALID = 'minecraft:netherite_ingot'
PAPER, DIAMOND = 'minecraft:paper', 'minecraft:diamond'
MARK = 'crusher_result_probe'


def recipe(item, results):
    return {'type': 'create:crushing', 'ingredients': [{'item': item}],
            'processing_time': 120, 'results': results}


def write_recipes(directory, malformed=False):
    rows = [{'id': PAPER, 'count': count, 'components': {'minecraft:custom_data': {MARK: mark}}}
            for count, mark in [(2, 101), (1, 202)]]
    (directory / 'zz_create_horizon_component_probe.json').write_text(
        json.dumps(recipe(INPUT, rows)) + '\n')
    if malformed:
        (directory / 'zz_create_horizon_malformed_component_probe.json').write_text(
            json.dumps(recipe(INVALID, [{'id': PAPER, 'components': [7]}])) + '\n')


def setup(cmd, wait):
    cmd(f'fill {AREA} {AIR}')
    put(cmd, DEPOT, 'create:depot{HeldItem:{Item:{id:"minecraft:diamond",count:1},'
        'Pos:0.5f,PrevPos:0.5f,Angle:180,InDirection:1}}')
    put(cmd, FEED, CHUTE)
    wheels(cmd, Z)
    wait(28)
    seed_chute(cmd, Z, INPUT, 1, 44)


def release(cmd, scan):
    scan(4, 'resumed')
    for phase in ('first', 'second'):
        cmd(f'data remove block {xyz(DEPOT)} HeldItem')
        scan(2, phase)


def normalized(rows):
    raw, depot = rows
    inventory = field(raw, 'Inventory')
    slots = re.findall(r'\bSlot\s*:\s*(\d+)', inventory)
    counts = re.findall(r'\bcount\s*:\s*(\d+)', inventory)
    markers = re.findall(r'\b' + MARK + r'\s*:\s*(\d+)', inventory)
    ids = re.findall(r'\bid\s*:\s*"([^"]+)"', inventory)
    queued = [[int(slot), item, int(count), int(mark)]
              for slot, item, count, mark in zip(slots, ids, counts, markers, strict=True)]
    held = field(depot, 'HeldItem')
    return dict(queued=queued, applied=bool(number({'nbt': inventory}, 'AppliedRecipe')),
                depot=items(held, 'Item'), marker=number({'nbt': held}, MARK, 0))


def verify(result):
    first, second = [1, PAPER, 2, 101], [2, PAPER, 1, 202]
    expected = {
        'blocked': dict(queued=[first, second], applied=True, depot={DIAMOND: 1}, marker=0),
        'resumed': dict(queued=[first, second], applied=True, depot={DIAMOND: 1}, marker=0),
        'first': dict(queued=[second], applied=True, depot={PAPER: 2}, marker=101),
        'second': dict(queued=[], applied=True, depot={PAPER: 1}, marker=202),
    }
    assert result == expected, (result, expected)


def java_run(work):
    host = Original()
    manifest = json.loads((java.BASE / 'manifest.json').read_text())
    initial = host.call('state', {})
    assert manifest['create_sha256'] == java.CREATE_SHA256
    assert initial['ready'] and initial['data_version'] == 3955, initial
    result = {}

    def wait(ticks):
        return host.snapshot([CONTROL, DEPOT], ticks)

    def scan(ticks, phase):
        result[phase] = normalized([row['nbt'] for row in wait(ticks)])

    host.call('tick', {'frozen': True})
    try:
        with java.fixture_datapack(host, manifest['world'], PACK, RECIPES, write_recipes):
            host.command(f'forceload add {TICKET}')
            wait(24)
            setup(host.command, wait)
            scan(40, 'blocked')
            release(host.command, scan)
            verify(result)
    finally:
        host.command(f'fill {AREA} {AIR}')
        host.command(f'forceload remove {TICKET}')
        host.call('tick', {'frozen': initial['server']['frozen']})
        (work / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')
    return result


def native_run(session):
    batch = Batch()
    batch.load(CONTROL)
    batch.run(session, 'materialize-datapack')
    write_recipes(session.scratch / 'horizon-mods/.create-native-content' / RECIPES, malformed=True)
    phases = []

    def scan(ticks, phase):
        batch.tick(ticks)
        batch.data(CONTROL)
        batch.data(DEPOT)
        phases.append(phase)

    batch = Batch()
    batch.load(CONTROL)
    setup(batch.command, batch.tick)
    scan(40, 'blocked')
    rows = batch.run(session, 'crusher-component-blocked')
    batch = Batch()
    batch.load(CONTROL)
    release(batch.command, scan)
    seed_chute(batch.command, Z, INVALID, 1, 55)
    batch.tick(24)
    batch.data(FEED)
    rows += batch.run(session, 'crusher-component-resumed')
    assert items(rows.pop(), 'Item') == {INVALID: 1}
    assert len(rows) == len(phases) * 2
    result = {phase: normalized(rows[2 * i:2 * i + 2]) for i, phase in enumerate(phases)}
    verify(result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--java', action='store_true')
    for flag in ('game', 'resources', 'ctl', 'reference', 'create-jar'):
        parser.add_argument('--' + flag, type=Path)
    args = parser.parse_args()
    if args.java:
        work = Path(tempfile.mkdtemp(prefix='crusher-component-java-', dir=ROOT / '.local'))
        print(work, flush=True)
        result = java_run(work)
    else:
        if not all((args.game, args.resources, args.ctl, args.reference)):
            parser.error('Horizon requires --game, --resources, --ctl and --reference')
        reference = json.loads(args.reference.read_text())
        assert reference['create'] == PINS['create_revision'] and reference['passed'], reference
        session = NativeCheckSession(args.game, args.resources, args.ctl, args.create_jar,
                                     name='crusher-component-native', graphics=False, world='CreateCrusherComponents')
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
