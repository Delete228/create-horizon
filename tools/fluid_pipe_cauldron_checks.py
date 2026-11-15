#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Compare open-end pumps drawing from cauldrons, bee nests and beehives."""

import argparse
import json
from pathlib import Path
import shutil
import tempfile

from bearing_native_checks import Batch
from chain_drive_checks import Original, xyz
from common import PINS, ROOT
from fluid_pipe_open_checks import AIR, AREA, CASES, LOAD, TICKS, X, Y, Z, compare, lane, setup, snapshot
from funnel_checks import put
from native_check_session import NativeCheckSession


PROFILES = (
    (0, 'full-water', 'minecraft:water_cauldron[level=3]', 'minecraft:cauldron', {'id': 'minecraft:water', 'amount': 1000}),
    (1, 'full-lava', 'minecraft:lava_cauldron', 'minecraft:cauldron', {'id': 'minecraft:lava', 'amount': 1000}),
    (2, 'partial-water', 'minecraft:water_cauldron[level=2]', 'minecraft:water_cauldron[level=2]', None),
    (4, 'fill-refused', 'minecraft:cauldron', 'minecraft:cauldron', {'id': 'minecraft:water', 'amount': 2000}),
)
HIVES = (
    (0, 'full-nest', 'minecraft:bee_nest[facing=north,honey_level=5]', 'minecraft:bee_nest[facing=north,honey_level=0]',
     {'id': 'create:honey', 'amount': 250}),
    (1, 'full-hive', 'minecraft:beehive[facing=north,honey_level=5]', 'minecraft:beehive[facing=north,honey_level=0]',
     {'id': 'create:honey', 'amount': 250}),
    (2, 'partial-hive', 'minecraft:beehive[facing=north,honey_level=4]',
     'minecraft:beehive[facing=north,honey_level=4]', None),
    (4, 'fill-refused', 'minecraft:beehive[facing=north,honey_level=0]', 'minecraft:beehive[facing=north,honey_level=0]',
     {'id': 'create:honey', 'amount': 2000}),
)


def prepare(cmd, profiles):
    setup(cmd)
    for index, _, block, _, tank in profiles:
        put(cmd, lane(index)[0], block)
        if not CASES[index][2] and tank['id'] == 'create:honey':
            cmd(f'data merge block {xyz(lane(index)[2])} {{TankContent:{{Fluid:{{id:"create:honey",amount:2000}}}}}}')


def motors(cmd, profiles):
    for index, *_ in profiles:
        put(cmd, (X+1, Y-1, lane(index)[1][2]), 'create:creative_motor[facing=west]{ScrollValue:32}')


def block_state(value):
    identifier, _, properties = value.partition('[')
    fields = dict(pair.split('=') for pair in properties.rstrip(']').split(',')) if properties else {}
    return dict(id=identifier, properties=fields)


def java_run(work, profiles):
    host = Original()
    positions = [pos for index, *_ in profiles for pos in lane(index)]
    initial = host.call('state', {})
    assert initial['ready'] and initial['data_version'] == 3955, initial
    host.call('tick', {'frozen': True})
    try:
        host.command(f'forceload add {LOAD}')
        host.call('observe_ticks', {'positions': positions, 'ticks': 14})
        prepare(host.command, profiles)
        host.call('observe_ticks', {'positions': positions, 'ticks': 40})
        commands = []
        motors(commands.append, profiles)
        rows = host.call('observe_ticks', {'positions': positions, 'ticks': TICKS,
                                           'commands': commands})['samples']
        return {name: [snapshot(row['blocks'][3*i:3*i+3], CASES[index][2]) for row in rows]
                for i, (index, name, *_) in enumerate(profiles)}
    finally:
        host.command(f'fill {AREA} {AIR}')
        host.command(f'forceload remove {LOAD}')
        host.call('tick', {'frozen': initial['server']['frozen']})
        (work / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')


def native_run(session, profiles):
    batch = Batch()
    batch.load((X, Y+2, Z+14))
    prepare(batch.command, profiles)
    batch.tick(40)
    motors(batch.command, profiles)
    for _ in range(TICKS):
        batch.tick()
        for index, _, block, after, _ in profiles:
            end, pump, tank = lane(index)
            batch.command(f'execute if block {xyz(end)} {block} run say fixture_initial', True)
            batch.command(f'execute if block {xyz(end)} {after} run say fixture_empty', True)
            batch.data(pump)
            batch.data(tank)
    raw = iter(batch.run(session, 'open-cauldron'))
    result = {name: [] for _, name, *_ in profiles}
    for _ in range(TICKS):
        for index, name, block, after, _ in profiles:
            initial = 'fixture_initial' in next(raw)
            empty = 'fixture_empty' in next(raw)
            assert initial or empty, (name, len(result[name])+1)
            current = block if initial else after
            external = block_state(current)
            result[name].append(snapshot([external, dict(nbt=next(raw)), dict(nbt=next(raw))], CASES[index][2]))
    assert next(raw, None) is None
    return result


def restart_hives(session):
    full = HIVES[:2]

    def observe(batch, ticks, label):
        batch.tick(ticks)
        for index, _, _, after, _ in full:
            _, pump, tank = lane(index)
            batch.data(pump)
            batch.data(tank)
        raw = iter(batch.run(session, label))
        result = {name: snapshot([block_state(after), dict(nbt=next(raw)), dict(nbt=next(raw))], True)
                  for _, name, _, after, _ in full}
        assert next(raw, None) is None
        return result

    batch = Batch()
    batch.load((X, Y+2, Z+14))
    prepare(batch.command, HIVES)
    batch.tick(40)
    motors(batch.command, HIVES)
    before = observe(batch, 20, 'hive-before-restart')
    batch = Batch()
    batch.load((X, Y+2, Z+14))
    after = observe(batch, 70, 'hive-after-restart')
    for _, name, _, _, tank in full:
        first = before[name]
        assert first['tank']['amount'] == 80 and first['open_end']['fluid']['amount'] == 170, first
        assert after[name]['tank'] == tank and after[name]['open_end']['fluid'] is None, after[name]
    return {'before': before, 'after': after}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--java', action='store_true')
    parser.add_argument('--hives', action='store_true', help='Measure honey extraction and refusal to fill a hive')
    for flag in ('game', 'resources', 'ctl', 'create-jar', 'reference'):
        parser.add_argument('--' + flag, type=Path)
    args = parser.parse_args()
    profiles = HIVES if args.hives else PROFILES
    cold = None
    if args.java:
        work = Path(tempfile.mkdtemp(prefix='fluid-cauldron-java-', dir=ROOT / '.local'))
        print(work, flush=True)
        traces = java_run(work, profiles)
    else:
        if not all((args.game, args.resources, args.ctl, args.create_jar, args.reference)):
            parser.error('Horizon requires --game, --resources, --ctl, --create-jar and --reference')
        session = NativeCheckSession(args.game, args.resources, args.ctl, args.create_jar,
                                     name='fluid-cauldron-native', world='CreateFluidCauldron')
        work = session.scratch
        print(work, flush=True)
        try:
            traces = native_run(session, profiles)
            if args.hives:
                cold = restart_hives(session)
        finally:
            session.control_temp.cleanup()
            for folder in (session.resources, work / '.horizon-cache', work / 'horizon-mods'):
                shutil.rmtree(folder, ignore_errors=True)
        reference = json.loads(args.reference.read_text())
        assert reference['passed'] and reference['create'] == PINS['create_revision']
        compare(traces, reference['traces'])
    for _, name, _, after, tank in profiles:
        final = traces[name][-1]
        assert final['tank'] == tank and final['open_end']['fluid'] is None, (name, final)
        expected = block_state(after)
        assert final['end'] == expected['id'] and final['properties'] == expected['properties'], (name, final)
    result = work / 'result.json'
    result.write_text(json.dumps(dict(passed=True, create=PINS['create_revision'], traces=traces, cold=cold),
                                 indent=2) + '\n')
    print(result)


if __name__ == '__main__':
    main()
