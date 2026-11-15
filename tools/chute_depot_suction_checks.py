#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Compare a reverse Fan with and without a Chute above a marked Depot."""

import argparse
import json
from pathlib import Path
import shutil
import tempfile

from bearing_native_checks import Batch
from burner_heat_java_checks import items, number
from chain_drive_checks import Original, xyz
from chute_suction_checks import fan_above
from common import PINS, ROOT
from native_check_session import NativeCheckSession
import reference_java as java


X, Y, Z = 2774, 178, 1714
CAMERA = (X + 3, Y + 1, Z + 7)
LOAD = '2768 1712 2783 1727'
AREA = (X - 2, Y - 4, Z - 1, X + 4, Y + 4, Z + 13)
LANES = {'bare': (Z, 2), 'direct': (Z + 4, 1), 'gap': (Z + 8, 2), 'blocked': (Z + 12, 2)}
POINTS = [pos for z, depth in LANES.values() for pos in [(X, Y - depth, z), (X, Y, z)]]
CARGO = 'minecraft:stick'
BUFFER = 'minecraft:iron_ingot'
TICKS = 12


def setup(command):
    command('fill ' + xyz(AREA) + ' minecraft:air')
    for lane, (z, depth) in LANES.items():
        fan_above(command, (X, Y, z))
        command(f'setblock {X} {Y-depth} {z} create:depot')
        if lane != 'bare':
            command(f'setblock {X} {Y} {z} create:chute[facing=down,shape=window]')
        if lane == 'blocked':
            command(f'setblock {X} {Y-1} {z} minecraft:stone')


def seed(command):
    for marker, (z, depth) in enumerate(LANES.values(), 1):
        payload = (f'{{id:"{CARGO}",count:23,components:{{"minecraft:custom_data":'
                   f'{{depot_suction:{marker}}}}}}}')
        command(f'data merge block {X} {Y-depth} {z} '
                f'{{HeldItem:{{Item:{payload},Pos:0.5f,PrevPos:0.5f,InDirection:1}},'
                f'OutputBuffer:{{Size:8,Items:[{{Slot:0,id:"{BUFFER}",count:4}}]}}}}')


def snapshot(raw):
    rows = {}
    for marker, (lane, depot, chute) in enumerate(zip(LANES, raw[::2], raw[1::2], strict=True), 1):
        assert 'create:depot' in depot, depot
        held = items(depot, 'HeldItem').get(CARGO, 0) if 'HeldItem:' in depot else 0
        buffer = items(depot, 'OutputBuffer')
        cargo = items(chute, 'Item').get(CARGO, 0) if lane != 'bare' else 0
        if held:
            assert number({'nbt': depot}, 'depot_suction') == marker, depot
        if cargo:
            assert number({'nbt': chute}, 'depot_suction') == marker, chute
        rows[lane] = dict(held=held, buffer=buffer, cargo=cargo,
                          offset=number({'nbt': chute}, 'ItemPosition') if cargo else None,
                          pull=number({'nbt': chute}, 'Pull', 0) if lane != 'bare' else None,
                          reach=number({'nbt': chute}, 'BottomAirFlowDistance', 0) if lane != 'bare' else None)
    return rows


def java_run(work):
    host = Original()
    initial = host.call('state', {})
    assert initial['ready'] and initial['data_version'] == 3955
    assert json.loads((java.BASE / 'manifest.json').read_text())['create_sha256'] == java.CREATE_SHA256

    def observe(ticks):
        return host.call('observe_ticks', {'positions': POINTS, 'ticks': ticks})['samples']

    host.call('tick', {'frozen': True})
    try:
        host.command('forceload add ' + LOAD)
        host.command('tp @s ' + xyz(CAMERA))
        observe(24)
        setup(host.command)
        observe(24)
        seed(host.command)
        return [snapshot([block.get('nbt', '') for block in frame['blocks']]) for frame in observe(TICKS)]
    finally:
        host.command('fill ' + xyz(AREA) + ' minecraft:air')
        host.command('forceload remove ' + LOAD)
        host.call('camera', {k: initial[k] for k in ('position', 'yaw', 'pitch')})
        host.call('tick', {'frozen': initial['server']['frozen']})
        (work / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')


def native_run(session):
    batch = Batch()
    batch.load(CAMERA)
    setup(batch.command)
    batch.tick(24)
    seed(batch.command)
    for _ in range(TICKS):
        batch.tick()
        for pos in POINTS:
            batch.data(pos)
    raw = batch.run(session, 'depot-suction')
    width = len(POINTS)
    assert len(raw) == width * TICKS, len(raw)
    return [snapshot(raw[i:i + width]) for i in range(0, len(raw), width)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--java', action='store_true')
    parser.add_argument('--baseline', action='store_true')
    for flag in ('game', 'resources', 'ctl', 'create-jar', 'reference'):
        parser.add_argument('--' + flag, type=Path)
    args = parser.parse_args()
    if args.java:
        work = Path(tempfile.mkdtemp(prefix='chute-depot-suction-java-', dir=ROOT / '.local'))
        print(work, flush=True)
        trace = java_run(work)
        for lane in ('bare', 'blocked'):
            assert all(row[lane]['held'] == 23 and row[lane]['cargo'] == 0 for row in trace), trace
        for lane in ('direct', 'gap'):
            assert all(row[lane]['held'] == 0 and row[lane]['cargo'] == 23 for row in trace), trace
        assert all(lane['buffer'] == {BUFFER: 4} for row in trace for lane in row.values()), trace
        matches = True
    else:
        if not all((args.game, args.resources, args.ctl, args.create_jar, args.reference)):
            parser.error('Horizon requires --game, --resources, --ctl, --create-jar and --reference')
        reference = json.loads(args.reference.read_text())
        assert reference['passed'] and reference['create'] == PINS['create_revision']
        session = NativeCheckSession(args.game, args.resources, args.ctl, args.create_jar,
                                     name='chute-depot-suction-native', world='ChuteDepotSuction', graphics=False)
        work = session.scratch
        print(work, flush=True)
        try:
            trace = native_run(session)
        finally:
            session.control_temp.cleanup()
            for folder in (session.resources, work / '.horizon-cache', work / 'horizon-mods'):
                shutil.rmtree(folder, ignore_errors=True)
        matches = trace == reference['trace']
    result = work / 'result.json'
    result.write_text(json.dumps(dict(passed=matches, create=PINS['create_revision'], trace=trace), indent=2) + '\n')
    print(result, trace[0], trace[-1])
    assert matches != args.baseline, (result, matches)


if __name__ == '__main__':
    main()
