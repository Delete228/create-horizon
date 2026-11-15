#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Compare hopper-fed milling, legacy result components and recipe remainders."""

import argparse
import json
from pathlib import Path
import re
import shutil
import tempfile

from bearing_native_checks import Batch
from burner_heat_java_checks import field, number
from chain_drive_checks import Original, xyz
from common import PINS, ROOT
from native_check_session import NativeCheckSession
import reference_java as java


MILL = (2140, 168, 1048)
HOPPER = (2140, 169, 1048)
MOTOR = (2140, 167, 1048)
AREA = '2139 167 1047 2141 170 1049'
TICKET = '2128 1040 2143 1055'
INPUT, PAPER, GLASS, DIAMOND = ('minecraft:honey_bottle', 'minecraft:paper',
                                'minecraft:glass_bottle', 'minecraft:diamond')
MARKER = 'millstone_codec_probe'
RECIPES = 'data/create/recipe/milling'
PACK = 'create-horizon-millstone-codec-check'


def write_recipe(folder):
    data = {
        'type': 'create:milling',
        'ingredients': [{'item': INPUT}],
        'processing_time': 8,
        'results': [
            {'item': {'id': PAPER, 'components': {'minecraft:custom_data': {MARKER: 11}}}, 'count': 2},
            {'id': PAPER, 'components': {'minecraft:custom_data': {MARKER: 22}}},
        ],
    }
    (folder / 'zz_create_horizon_millstone_codec_probe.json').write_text(json.dumps(data) + '\n')


def setup(cmd, tick):
    cmd(f'fill {AREA} minecraft:air')
    cmd(f'setblock {xyz(MILL)} create:millstone')
    cmd(f'setblock {xyz(HOPPER)} minecraft:hopper[facing=down]')
    cmd(f'data merge block {xyz(MILL)} {{OutputInventory:{{Size:9,Items:[{{Slot:8,id:"{DIAMOND}",count:99,'
        'components:{"minecraft:max_stack_size":99}}]}}')
    cmd(f'setblock {xyz(MOTOR)} create:creative_motor[facing=up]{{ScrollValue:64}}')
    tick(24)
    cmd(f'item replace block {xyz(HOPPER)} container.0 with {INPUT}[minecraft:custom_data={{{MARKER}:33}}] 2')


def release(cmd, scan):
    # A data merge invokes Java's complete kinetic read. Reconnect the source
    # after the administrative edit to preserve an equivalent powered setup.
    cmd(f'setblock {xyz(MOTOR)} minecraft:air')
    cmd(f'data merge block {xyz(MILL)} {{OutputInventory:{{Size:9,Items:[{{Slot:8,id:"{DIAMOND}",count:64}}]}}}}')
    cmd(f'setblock {xyz(MOTOR)} create:creative_motor[facing=up]{{ScrollValue:64}}')
    for tick in range(9):
        scan(1, f'resume_{tick}')


def stacks(items):
    rows = []
    for item in re.split(r'(?<=\}),\s*(?=\{)', items[1:-1]) if items != '[]' else []:
        slot = re.search(r'\bSlot\s*:\s*(\d+)', item)
        stack_id = re.search(r'\bid\s*:\s*"([^"]+)"', item)
        count = re.search(r'\bcount\s*:\s*(\d+)', item)
        assert slot and stack_id and count, item
        rows.append([int(slot.group(1)), stack_id.group(1), int(count.group(1)),
                     int(number({'nbt': item}, MARKER, 0))])
    return rows


def sample(mill, hopper):
    return dict(input=stacks(field(field(mill, 'InputInventory'), 'Items')),
                output=stacks(field(field(mill, 'OutputInventory'), 'Items')),
                timer=int(number({'nbt': mill}, 'Timer', 0)),
                hopper=stacks(field(hopper, 'Items')) if re.search(r'\bItems\s*:', hopper) else [])


def after_power(result):
    # The command sequence reconnects kinetics. Compare all six processing
    # ticks starting at the first recipe arm, independent of connection latency.
    trace = [result.pop(f'resume_{tick}') for tick in range(9)]
    first = next((tick for tick, row in enumerate(trace) if row['timer'] == 8), None)
    assert first is not None, trace
    processing = trace[first:first + 6]
    assert [row['timer'] for row in processing] == [8, 4, 0, 8, 4, 0], trace
    result.update(armed=processing[0], one=processing[2], two=processing[5])
    return result


def verify(result):
    diamond = [8, DIAMOND, 64, 0]
    expected = {
        'blocked': dict(input=[[0, INPUT, 2, 33]], output=[[8, DIAMOND, 99, 0]], timer=0, hopper=[]),
        'armed': dict(input=[[0, INPUT, 2, 33]], output=[diamond], timer=8, hopper=[]),
        'one': dict(input=[[0, INPUT, 1, 33]], output=[[0, PAPER, 2, 11], [1, PAPER, 1, 22], [2, GLASS, 1, 0], diamond],
                    timer=0, hopper=[]),
        'two': dict(input=[], output=[[0, PAPER, 4, 11], [1, PAPER, 2, 22], [2, GLASS, 2, 0], diamond], timer=0, hopper=[]),
    }
    assert {phase: result[phase] for phase in expected} == expected, (result, expected)
    if 'cold' in result:
        assert result['cold'] == result['blocked'], result


def java_run(work):
    host = Original()
    manifest = json.loads((java.BASE / 'manifest.json').read_text())
    initial = host.call('state', {})
    assert manifest['create_sha256'] == java.CREATE_SHA256
    assert initial['ready'] and initial['data_version'] == 3955, initial
    result = {}

    def tick(ticks):
        return host.snapshot([MILL, HOPPER], ticks)

    def scan(ticks, phase):
        result[phase] = sample(*(block['nbt'] for block in tick(ticks)))

    host.call('tick', {'frozen': True})
    try:
        with java.fixture_datapack(host, manifest['world'], PACK, RECIPES, write_recipe):
            host.command(f'forceload add {TICKET}')
            tick(24)
            setup(host.command, tick)
            scan(24, 'blocked')
            release(host.command, scan)
    finally:
        host.command(f'fill {AREA} minecraft:air')
        host.command(f'forceload remove {TICKET}')
        host.call('tick', {'frozen': initial['server']['frozen']})
        (work / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')
    return after_power(result)


def native_run(session):
    batch = Batch()
    batch.load(MILL)
    batch.run(session, 'materialize-datapack')
    write_recipe(session.scratch / 'horizon-mods/.create-native-content' / RECIPES)
    phases = []

    def scan(ticks, phase):
        if ticks:
            batch.tick(ticks)
        batch.data(MILL)
        batch.data(HOPPER)
        phases.append(phase)

    batch = Batch()
    batch.load(MILL)
    setup(batch.command, batch.tick)
    scan(24, 'blocked')
    rows = batch.run(session, 'millstone-codec-blocked')
    batch = Batch()
    batch.load(MILL)
    scan(0, 'cold')
    release(batch.command, scan)
    rows += batch.run(session, 'millstone-codec-resumed')
    result = {phase: sample(*values) for phase, values in zip(phases, zip(rows[::2], rows[1::2], strict=True), strict=True)}
    return after_power(result)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--java', action='store_true')
    for flag in ('game', 'resources', 'ctl', 'reference', 'create-jar'):
        parser.add_argument('--' + flag, type=Path)
    args = parser.parse_args()
    if args.java:
        work = Path(tempfile.mkdtemp(prefix='millstone-codec-java-', dir=ROOT / '.local'))
        print(work, flush=True)
        result = java_run(work)
    else:
        if not all((args.game, args.resources, args.ctl, args.reference)):
            parser.error('Horizon requires --game, --resources, --ctl and --reference')
        reference = json.loads(args.reference.read_text())
        assert reference['create'] == PINS['create_revision'] and reference['passed'], reference
        session = NativeCheckSession(args.game, args.resources, args.ctl, args.create_jar,
                                     name='millstone-codec-native', graphics=False, world='CreateMillstoneCodec')
        work = session.scratch
        print(work, flush=True)
        try:
            result = native_run(session)
        finally:
            session.control_temp.cleanup()
            for folder in (session.resources, work / '.horizon-cache', work / 'horizon-mods'):
                shutil.rmtree(folder, ignore_errors=True)
        assert {key: result[key] for key in reference['cases']} == reference['cases'], (result, reference)
    verify(result)
    path = work / 'result.json'
    path.write_text(json.dumps(dict(passed=True, create=PINS['create_revision'], cases=result), indent=2) + '\n')
    print(path)


if __name__ == '__main__':
    main()
