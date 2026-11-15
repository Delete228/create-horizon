#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Compare the read behavior of tanks containing more than their capacity."""

import argparse
import json
from pathlib import Path
import shutil
import tempfile

from bearing_native_checks import Batch
from burner_heat_java_checks import field, number
from chain_drive_checks import Original, xyz
from common import PINS, ROOT
from fluid_pump_java_checks import PUMP, TANK, fluid
from native_check_session import NativeCheckSession


X, Y, Z = 2639, 175, 1462
AREA = '2636 174 1459 2644 180 1478'
LOAD = '2624 1456 2655 1487'
CASES = (
    ((X, Y, Z), 1, 1, 'minecraft:water', 8001),
    ((X, Y, Z+5), 1, 2, 'minecraft:lava', 19000),
    ((X, Y, Z+10), 2, 2, 'create:honey', 64250),
)
POSITIONS = [pos for pos, *_ in CASES]
DESTINATIONS = [(x+width+1, y, z) for (x,y,z), width, *_ in CASES]


def setup(cmd):
    cmd(f'fill {AREA} minecraft:air')
    for (x, y, z), width, height, _, _ in CASES:
        cmd(f'fill {x} {y} {z} {x+width-1} {y+height-1} {z+width-1} {TANK}')
        cmd(f'setblock {x+width+1} {y} {z} {TANK}')
        cmd(f'setblock {x+width} {y} {z} {PUMP}[facing=east,waterlogged=false]')
        cmd(f'setblock {x+width} {y-1} {z} create:cogwheel[axis=x]')


def fill(cmd):
    for pos, _, _, kind, amount in CASES:
        cmd(f'data merge block {xyz(pos)} {{TankContent:{{Fluid:{{id:"{kind}",amount:{amount}}}}}}}')


def power(cmd):
    for x, y, z in DESTINATIONS:
        cmd(f'setblock {x} {y-1} {z} create:creative_motor[facing=west]{{ScrollValue:32}}')


def snapshot(rows):
    return [dict(size=number({'nbt': raw}, 'Size'), height=number({'nbt': raw}, 'Height'),
                 fluid=fluid(field(raw, 'TankContent'))) for raw in rows]


def verify(rows):
    for i, (_, width, height, kind, amount) in enumerate(CASES):
        assert rows['loaded'][i] == dict(size=width, height=height, fluid=dict(id=kind, amount=amount)), rows
        source, target = rows['drained'][i], rows['received'][i]
        assert target['fluid'] and source['fluid'] and target['fluid']['id'] == source['fluid']['id'] == kind, rows
        assert 0 < target['fluid']['amount'] and source['fluid']['amount'] + target['fluid']['amount'] == amount, rows
        if amount > 9000:
            assert source['fluid']['amount'] > 8000*width*width*height, source


def java_run(work):
    host = Original()
    initial = host.call('state', {})
    assert initial['ready'] and initial['data_version'] == 3955, initial
    host.call('tick', {'frozen': True})
    try:
        host.command(f'forceload add {LOAD}')
        host.call('observe_ticks', {'positions': POSITIONS, 'ticks': 14})
        setup(host.command)
        host.call('observe_ticks', {'positions': POSITIONS, 'ticks': 40})
        commands = []
        fill(commands.append)
        observed = host.call('observe_ticks', {'positions': POSITIONS, 'ticks': 1,
                                               'commands': commands})['samples'][0]['blocks']
        loaded = snapshot([block['nbt'] for block in observed])
        commands.clear()
        power(commands.append)
        observed = host.call('observe_ticks', {'positions': POSITIONS+DESTINATIONS, 'ticks': 18,
                                               'commands': commands})['samples'][-1]['blocks']
        transferred = snapshot([block['nbt'] for block in observed])
        return dict(loaded=loaded, drained=transferred[:len(CASES)], received=transferred[len(CASES):])
    finally:
        host.command(f'fill {AREA} minecraft:air')
        host.command(f'forceload remove {LOAD}')
        host.call('tick', {'frozen': initial['server']['frozen']})
        (work / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')


def native_run(session):
    batch = Batch()
    batch.load((X, Y+2, Z+5))
    setup(batch.command)
    batch.tick(40)
    fill(batch.command)
    batch.tick()
    for pos in POSITIONS:
        batch.data(pos)
    power(batch.command)
    batch.tick(18)
    for pos in POSITIONS+DESTINATIONS:
        batch.data(pos)
    rows = snapshot(batch.run(session, 'overflowing-tanks'))
    return dict(loaded=rows[:len(CASES)], drained=rows[len(CASES):2*len(CASES)], received=rows[2*len(CASES):])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--java', action='store_true')
    for flag in ('game', 'resources', 'ctl', 'create-jar', 'reference'):
        parser.add_argument('--'+flag, type=Path)
    args = parser.parse_args()
    if args.java:
        work = Path(tempfile.mkdtemp(prefix='tank-overflow-java-', dir=ROOT / '.local'))
        print(work, flush=True)
        observed = java_run(work)
    else:
        if not all((args.game, args.resources, args.ctl, args.create_jar, args.reference)):
            parser.error('Horizon requires --game, --resources, --ctl, --create-jar and --reference')
        session = NativeCheckSession(args.game, args.resources, args.ctl, args.create_jar,
                                     name='tank-overflow-native', world='CreateTankOverflow')
        work = session.scratch
        print(work, flush=True)
        try:
            observed = native_run(session)
        finally:
            session.control_temp.cleanup()
            for folder in (session.resources, work / '.horizon-cache', work / 'horizon-mods'):
                shutil.rmtree(folder, ignore_errors=True)
    (work / 'observed.json').write_text(json.dumps(observed, indent=2) + '\n')
    verify(observed)
    if not args.java:
        expected = json.loads(args.reference.read_text())
        assert expected['passed'] and expected['create'] == PINS['create_revision']
        assert observed == expected['observed'], (observed, expected['observed'])
    result = work / 'result.json'
    result.write_text(json.dumps(dict(passed=True, create=PINS['create_revision'], observed=observed), indent=2) + '\n')
    print(result)


if __name__ == '__main__':
    main()
