#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Compare real pump transfers with the Basin and Item Drain capabilities."""

import argparse
import json
from pathlib import Path
import re
import shutil
import tempfile

from bearing_native_checks import Batch
from burner_heat_java_checks import field
from chain_drive_checks import Original, xyz
from common import PINS, ROOT
from fluid_pump_java_checks import PIPE, PUMP, TANK, fluid, seed
from native_check_session import NativeCheckSession
import reference_java as java


X, Y, Z = 2453, 168, 1090
BASIN = 'create:basin'
DRAIN = 'create:item_drain'
AIR = 'minecraft:air'
AREA = (2449, 166, 1088, 2457, 173, 1120)
FORCE = '2448 1088 2463 1135'
TICKS = 70
CASES = (
    ('tank-to-basin', TANK, BASIN, 'water'),
    ('basin-to-tank', BASIN, TANK, 'lava'),
    ('basin-to-basin', BASIN, BASIN, 'water'),
    ('full-basin', TANK, BASIN, 'water'),
    ('drain-side', DRAIN, TANK, 'water'),
    ('drain-bottom', DRAIN, TANK, 'lava'),
    ('drain-top', DRAIN, TANK, 'water'),
    ('drain-denies-fill', TANK, DRAIN, 'water'),
)


def lane(index):
    z = Z + 4 * index
    side = {'drain-bottom': 'up', 'drain-top': 'down'}.get(CASES[index][0])
    height = 1 if side == 'up' else -1 if side == 'down' else 0
    pipes = [((X - 1, Y, z), 'east,west'), ((X + 1, Y, z), 'east,west')]
    if side:
        pipes.insert(0, ((X - 2, Y, z), f'east,{side}'))
    return dict(source=(X - 2, Y + height, z), target=(X + 2, Y, z),
                motor=(X - 1, Y, z - 1), cog=(X, Y, z - 1), pipes=pipes, pump=(X, Y, z))


def setup(cmd):
    cmd(f'fill {xyz(AREA)} {AIR}')
    for index, (_, source, target, _) in enumerate(CASES):
        rig = lane(index)
        for key, block in [('source', source), ('target', target),
                           ('pump', PUMP + '[facing=east,waterlogged=false]'),
                           ('cog', 'create:cogwheel[axis=x]')]:
            cmd(f'setblock {xyz(rig[key])} {block}')
        for pos, ports in rig['pipes']:
            properties = ','.join(f'{port}=true' for port in ports.split(','))
            cmd(f'setblock {xyz(pos)} {PIPE}[{properties},waterlogged=false]')


def seed_basin(pos, half, kind, amount):
    return (f'data modify block {xyz(pos)} {half}[0].TankContent set value '
            f'{{Fluid:{{id:"minecraft:{kind}",amount:{amount}}}}}')


def seed_tanks(cmd):
    for index, (name, source, _, kind) in enumerate(CASES):
        rig = lane(index)
        if source == TANK:
            cmd(seed(rig['source'], kind, 1000))
        elif source == DRAIN:
            cmd(seed_basin(rig['source'], 'Tanks', kind, 220))
        else:
            cmd(seed_basin(rig['source'], 'OutputTanks', kind, 1000))
            if name == 'basin-to-tank':
                cmd(seed_basin(rig['source'], 'InputTanks', 'water', 200))
        if name == 'full-basin':
            cmd(seed_basin(rig['target'], 'InputTanks', kind, 1000))


def power(cmd):
    for index in range(len(CASES)):
        rig = lane(index)
        cmd(f'setblock {xyz(rig["motor"])} create:creative_motor[facing=east]{{ScrollValue:32}}')


def reservoir(raw, block):
    if block == TANK:
        return fluid(field(raw, 'TankContent'))
    if block == DRAIN:
        return fluid(field(field(raw, 'Tanks'), 'TankContent'))
    return {half: [fluid(value) for value in
                   re.findall(r'TankContent:\s*(\{(?:[^{}]|\{[^{}]*\})*\})', field(raw, half))]
            for half in ('InputTanks', 'OutputTanks')}


def frame(raw):
    return {
        name: [reservoir(raw[2 * index], source), reservoir(raw[2 * index + 1], target)]
        for index, (name, source, target, _) in enumerate(CASES)
    }


def count(stack):
    if not stack:
        return 0
    if 'amount' in stack:
        return stack['amount']
    return sum(count(cell) for half in stack.values() for cell in half)


def verify(rows):
    for name, source, target, _ in CASES:
        trace = [row[name] for row in rows]
        assert len({sum(map(count, pair)) for pair in trace}) == 1, (name, trace)
        amounts = [count(pair[1]) for pair in trace]
        if name == 'full-basin':
            assert set(amounts) == {1000}, (name, trace)
            continue
        if name in ('drain-top', 'drain-denies-fill'):
            assert set(amounts) == {0}, (name, trace)
            continue
        assert amounts[0] == 0 and amounts[-1] >= 16, (name, trace)
        increments = {b - a for a, b in zip(amounts, amounts[1:])}
        if source == DRAIN:
            assert increments == {0, 12, 16} and amounts[-1] == 220, (name, trace)
            assert trace[-1][0] is None, (name, trace)
        else:
            assert increments == {0, 16}, (name, trace)
        if target == BASIN:
            assert trace[-1][1]['InputTanks'][0]['amount'] == amounts[-1]
            assert trace[-1][1]['OutputTanks'] == [None, None]
        if name == 'basin-to-tank':
            assert trace[-1][0]['InputTanks'][0] == {'id': 'minecraft:water', 'amount': 200}
            assert trace[-1][1]['id'] == 'minecraft:lava'


def java_run(work):
    host = Original()
    initial = host.call('state', {})
    assert initial['ready'] and initial['data_version'] == 3955, initial
    host.call('tick', {'frozen': True})
    positions = [lane(i)[key] for i in range(len(CASES)) for key in ('source', 'target')]
    try:
        host.command(f'forceload add {FORCE}')
        host.call('observe_ticks', {'positions': positions, 'ticks': 14})
        setup(host.command)
        host.call('observe_ticks', {'positions': positions, 'ticks': 40})
        seed_tanks(host.command)
        commands = []
        power(commands.append)
        samples = host.call('observe_ticks', {'positions': positions, 'ticks': TICKS,
                                             'commands': commands})['samples']
        return [frame([block['nbt'] for block in row['blocks']]) for row in samples]
    finally:
        host.command(f'fill {xyz(AREA)} {AIR}')
        host.command(f'forceload remove {FORCE}')
        host.call('tick', {'frozen': initial['server']['frozen']})
        (work / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')


def native_run(session):
    batch = Batch()
    batch.load((X, Y + 2, Z + 4 * (len(CASES) // 2)))
    setup(batch.command)
    batch.tick(40)
    seed_tanks(batch.command)
    power(batch.command)
    for _ in range(TICKS):
        batch.tick()
        for index in range(len(CASES)):
            for key in ('source', 'target'):
                batch.data(lane(index)[key])
    rows = batch.run(session, 'pump-basin')
    count = 2 * len(CASES)
    assert len(rows) == TICKS * count, rows
    return [frame(rows[i:i+count]) for i in range(0, len(rows), count)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--java', action='store_true')
    for flag in ('game', 'resources', 'ctl', 'create-jar', 'reference'):
        parser.add_argument('--' + flag, type=Path)
    args = parser.parse_args()
    if args.java:
        work = Path(tempfile.mkdtemp(prefix='pump-basin-java-', dir=ROOT / '.local'))
        print(work, flush=True)
        rows = java_run(work)
    else:
        if not all((args.game, args.resources, args.ctl, args.create_jar, args.reference)):
            parser.error('Horizon requires --game, --resources, --ctl, --create-jar and --reference')
        session = NativeCheckSession(args.game, args.resources, args.ctl, args.create_jar,
                                     name='pump-basin-native', world='CreatePumpBasin')
        work = session.scratch
        print(work, flush=True)
        try:
            rows = native_run(session)
        finally:
            session.control_temp.cleanup()
            for folder in (session.resources, work / '.horizon-cache', work / 'horizon-mods'):
                shutil.rmtree(folder, ignore_errors=True)
    (work / 'observed.json').write_text(json.dumps(rows, indent=2) + '\n')
    verify(rows)
    report = {'passed': True, 'create': PINS['create_revision'], 'ticks': rows}
    if not args.java:
        reference = json.loads(args.reference.read_text())
        for i, (observed, wanted) in enumerate(zip(rows, reference['ticks'], strict=True)):
            assert observed == wanted, (i + 1, observed, wanted)
    output = work / 'result.json'
    output.write_text(json.dumps(report, indent=2) + '\n')
    print(output)


if __name__ == '__main__':
    main()
