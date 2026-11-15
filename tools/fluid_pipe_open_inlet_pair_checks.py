#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Compare two open pipe inlets filling the same closed tank."""

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
from fluid_pipe_cauldron_checks import block_state
from fluid_pump_java_checks import PIPE, PUMP, TANK, fluid, measure
from funnel_checks import put
from native_check_session import NativeCheckSession


X, Y, Z = 2613, 173, 1403
AREA = '2609 171 1399 2618 177 1418'
LOAD = '2608 1392 2623 1423'
TICKS = 166
WATER = ('minecraft:water_cauldron[level=3]', 'minecraft:cauldron')
NEST = ('minecraft:bee_nest[facing=north,honey_level=5]', 'minecraft:bee_nest[facing=north,honey_level=0]')
HIVE = ('minecraft:beehive[facing=north,honey_level=5]', 'minecraft:beehive[facing=north,honey_level=0]')
CASES = dict(water=(WATER, WATER, 'minecraft:water', 2000),
             honey=(NEST, HIVE, 'create:honey', 500))


def lane(name):
    z = Z + 7 * list(CASES).index(name)
    return (X-1, Y, z-1), (X-1, Y, z+1), (X-1, Y, z), (X+1, Y, z)


def setup(cmd):
    cmd(f'fill {AREA} minecraft:air')
    for name, (north, south, _, _) in CASES.items():
        first, second, junction, tank = lane(name)
        z = junction[2]
        put(cmd, first, north[0])
        put(cmd, second, south[0])
        put(cmd, junction, PIPE+'[east=true,north=true,south=true,waterlogged=false]')
        put(cmd, (X, Y, z), PUMP+'[facing=east,waterlogged=false]')
        put(cmd, tank, TANK)
        put(cmd, (X, Y-1, z), 'create:cogwheel[axis=x]')


def power(cmd):
    for name in CASES:
        put(cmd, (X+1, Y-1, lane(name)[2][2]), 'create:creative_motor[facing=west]{ScrollValue:32}')


def matches(block, value):
    state = block_state(value)
    return block['id'] == state['id'] and block['properties'].items() >= state['properties'].items()


def snapshot(blocks, name):
    north, south, junction, tank = blocks
    raw = junction['nbt']
    faces = measure(junction, ('north', 'south', 'east'))['connections']
    for side, data in faces.items():
        saved = field(raw, side) if re.search(r'\b' + side + r'\s*:\s*\{', raw) else '{}'
        buffer = field(saved, 'OpenEnd') if 'OpenEnd:' in saved else None
        data['buffer'] = dict(fluid=fluid(buffer), pulling='Pulling:1b' in buffer.replace(' ', '')) if buffer else None
        if (flow := data['flow']) and flow['progress'] is not None:
            flow['progress'] = round(flow['progress'], 6)
    first, second, _, _ = CASES[name]
    consumed = [matches(north, first[1]), matches(south, second[1])]
    return dict(consumed=consumed, faces=faces, tank=measure(tank)['tank'])


def java_run(work):
    host = Original()
    initial = host.call('state', {})
    assert initial['ready'] and initial['data_version'] == 3955, initial
    host.call('tick', {'frozen': True})
    positions = [pos for name in CASES for pos in lane(name)]
    try:
        host.command(f'forceload add {LOAD}')
        host.call('observe_ticks', {'positions': positions, 'ticks': 14})
        setup(host.command)
        host.call('observe_ticks', {'positions': positions, 'ticks': 40})
        commands = []
        power(commands.append)
        rows = host.call('observe_ticks', {'positions': positions, 'ticks': TICKS,
                                           'commands': commands})['samples']
        return {name: [snapshot(row['blocks'][4*i:4*i+4], name) for row in rows]
                for i, name in enumerate(CASES)}
    finally:
        host.command(f'fill {AREA} minecraft:air')
        host.command(f'forceload remove {LOAD}')
        host.call('tick', {'frozen': initial['server']['frozen']})
        (work / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')


def native_start():
    batch = Batch()
    batch.load((X, Y+2, Z+3))
    setup(batch.command)
    batch.tick(40)
    power(batch.command)
    return batch


def record(batch):
    for name, (north, south, _, _) in CASES.items():
        first, second, junction, tank = lane(name)
        batch.expect(first, north[1])
        batch.expect(second, south[1])
        batch.data(junction)
        batch.data(tank)


def read(raw):
    rows = {}
    for name, (north, south, _, _) in CASES.items():
        first, second = [block_state(states['bearing_check' in next(raw)]) for states in (north, south)]
        junction, tank = [dict(nbt=next(raw), id=kind, properties={}) for kind in (PIPE, TANK)]
        rows[name] = snapshot((first, second, junction, tank), name)
    return rows


def native_run(session):
    batch = native_start()
    for _ in range(TICKS):
        batch.tick()
        record(batch)
    raw = iter(batch.run(session, 'open-inlet-pair'))
    traces = {name: [] for name in CASES}
    for _ in range(TICKS):
        for name, row in read(raw).items():
            traces[name].append(row)
    assert next(raw, None) is None
    return traces


def cold_run(session, traces):
    batch = native_start()
    batch.tick(28)
    record(batch)
    raw = iter(batch.run(session, 'open-inlet-before-restart'))
    before = read(raw)
    assert next(raw, None) is None
    assert before == {name: rows[27] for name, rows in traces.items()}, before
    for name, row in before.items():
        assert row['consumed'] == [True, True] and all(row['faces'][side]['buffer']['fluid'] for side in ('north', 'south')), (name, row)
    batch = Batch()
    batch.load((X, Y+2, Z+3))
    batch.tick(TICKS)
    record(batch)
    raw = iter(batch.run(session, 'open-inlet-after-restart'))
    after = read(raw)
    assert next(raw, None) is None
    assert after == {name: rows[-1] for name, rows in traces.items()}, after
    return dict(before=before, after=after)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--java', action='store_true')
    parser.add_argument('--cold', action='store_true', help='reopen the Horizon save with both inlet buffers occupied')
    for flag in ('game', 'resources', 'ctl', 'create-jar', 'reference'):
        parser.add_argument('--'+flag, type=Path)
    args = parser.parse_args()
    if args.java and args.cold:
        parser.error('--cold applies to Horizon')
    restart = None
    if args.java:
        work = Path(tempfile.mkdtemp(prefix='open-inlet-pair-java-', dir=ROOT / '.local'))
        print(work, flush=True)
        traces = java_run(work)
    else:
        if not all((args.game, args.resources, args.ctl, args.create_jar, args.reference)):
            parser.error('Horizon requires --game, --resources, --ctl, --create-jar and --reference')
        session = NativeCheckSession(args.game, args.resources, args.ctl, args.create_jar,
                                     name='open-inlet-pair-native', world='CreateOpenInletPair')
        work = session.scratch
        print(work, flush=True)
        try:
            traces = native_run(session)
            if args.cold:
                restart = cold_run(session, traces)
        finally:
            session.control_temp.cleanup()
            for folder in (session.resources, work / '.horizon-cache', work / 'horizon-mods'):
                shutil.rmtree(folder, ignore_errors=True)
    (work / 'observed.json').write_text(json.dumps(traces, indent=2) + '\n')
    for name, (_, _, kind, volume) in CASES.items():
        final = traces[name][-1]
        assert final['consumed'] == [True, True] and final['tank'] == dict(id=kind, amount=volume), (name, final)
    if not args.java:
        expected = json.loads(args.reference.read_text())
        assert expected['passed'] and expected['create'] == PINS['create_revision']
        for name, rows in traces.items():
            for tick, (got, want) in enumerate(zip(rows, expected['traces'][name], strict=True), 1):
                assert got == want, (name, tick, got, want)
    result = work / 'result.json'
    result.write_text(json.dumps(dict(passed=True, create=PINS['create_revision'], traces=traces,
                                     restart=restart), indent=2) + '\n')
    print(result)


if __name__ == '__main__':
    main()
