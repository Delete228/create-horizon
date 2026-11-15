#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Compare vanilla Hoppers feeding the top and side of a dry Smart Chute."""

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
from crafter_hopper_checks import inventory
from funnel_checks import put
from native_check_session import NativeCheckSession
import reference_java as java


X, Y, Z = 2486, 172, 1412
AREA = '2481 170 1409 2492 177 1422'
TICKET = '2480 1408 2495 1423'
CHUTE = 'create:smart_chute'
PAPER = 'minecraft:paper'
WRONG = 'minecraft:iron_ingot'
MARK = 'smart_chute_probe:11'
MARKED = PAPER + '[minecraft:custom_data={' + MARK + '}]'
LANES = ('top', 'side')
ENTRY = {f'entry_{tick}': pos for tick, pos in enumerate((1, .8, .6, .5, .5, .5), 1)}


def lane(name):
    if name == 'top':
        return (X, Y, Z), (X, Y + 1, Z), (X, Y - 1, Z), (X + 1, Y, Z), 'down'
    z = Z + 6
    return (X, Y, z), (X - 1, Y, z), (X, Y - 1, z), (X + 1, Y, z), 'east'


def setup(cmd):
    cmd(f'fill {AREA} minecraft:air')
    for name in LANES:
        chute, source, target, power, facing = lane(name)
        put(cmd, power, 'minecraft:redstone_block')
        put(cmd, target, 'minecraft:smooth_stone')
        put(cmd, chute, CHUTE + '{Filter:{id:"minecraft:paper",count:1},FilterAmount:64,UpTo:0b}')
        put(cmd, source, f'minecraft:hopper[facing={facing}]')
        cmd(f'item replace block {xyz(source)} container.0 with {WRONG} 2')
        cmd(f'item replace block {xyz(source)} container.1 with {MARKED} 3')


def park(cmd, scan):
    scan(24, 'powered')
    for name in LANES:
        put(cmd, lane(name)[3], 'minecraft:air')
    for phase in ENTRY:
        scan(1, phase)
    scan(18, 'parked')


def release(cmd, scan):
    scan(12, 'resumed')
    for name in LANES:
        put(cmd, lane(name)[2], 'minecraft:chest')
    scan(75, 'delivered')


def marked(raw):
    return MARK in re.sub(r'\s+', '', raw)


def observe(rows, phase):
    delivered = phase == 'delivered'
    stride = 3 if delivered else 2
    result = {}
    assert len(rows) == stride * len(LANES), rows
    for i, name in enumerate(LANES):
        chute, source, *target = rows[stride * i:stride * (i + 1)]
        has_item = bool(re.search(r'\bItem\s*:', chute))
        result[name] = dict(cargo=items(chute, 'Item') if has_item else {},
                            cargo_marked=has_item and marked(field(chute, 'Item')),
                            position=number({'nbt': chute}, 'ItemPosition', 0), source=inventory(source),
                            target=inventory(target[0]) if delivered else {},
                            target_marked=marked(target[0]) if delivered else False)
    return result


def verify(results):
    assert set(results) == {'powered', 'parked', 'resumed', 'delivered', *ENTRY}, results
    for phase, lanes in results.items():
        occupied = phase in ('parked', 'resumed') or phase in ENTRY
        source = {WRONG: 2}
        if phase != 'delivered':
            source[PAPER] = 2 if occupied else 3
        delivered = phase == 'delivered'
        want = dict(cargo={PAPER: 1} if occupied else {}, cargo_marked=occupied,
                    source=source, target={PAPER: 3} if delivered else {}, target_marked=delivered)
        for name, row in lanes.items():
            if occupied:
                assert row['position'] == ENTRY.get(phase, .5), (phase, name, row)
            assert {k: v for k, v in row.items() if k != 'position'} == want, (phase, name, row, want)


def java_run(work):
    host = Original()
    manifest = json.loads((java.BASE / 'manifest.json').read_text())
    initial = host.call('state', {})
    assert manifest['create_sha256'] == java.CREATE_SHA256
    assert initial['ready'] and initial['data_version'] == 3955, initial
    result = {}

    def scan(ticks, phase):
        stride = 3 if phase == 'delivered' else 2
        positions = [pos for name in LANES for pos in lane(name)[:stride]]
        rows = host.snapshot(positions, ticks)
        assert all((row['properties']['powered'] == 'true') == (phase == 'powered')
                   for row in rows[::stride]), rows
        result[phase] = observe([row['nbt'] for row in rows], phase)

    host.call('tick', {'frozen': True})
    try:
        host.command(f'forceload add {TICKET}')
        host.snapshot([lane('top')[0]], 20)
        setup(host.command)
        park(host.command, scan)
        release(host.command, scan)
        verify(result)
    finally:
        host.command(f'fill {AREA} minecraft:air')
        host.command(f'forceload remove {TICKET}')
        host.call('tick', {'frozen': initial['server']['frozen']})
        (work / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')
    return result


def native_run(session):
    phases = []

    def scan(ticks, phase):
        batch.tick(ticks)
        powered = str(phase == 'powered').lower()
        for name in LANES:
            batch.expect(lane(name)[0], f'{CHUTE}[powered={powered}]')
        stride = 3 if phase == 'delivered' else 2
        for name in LANES:
            for pos in lane(name)[:stride]:
                batch.data(pos)
        phases.append((phase, len(LANES) * stride))

    batch = Batch()
    batch.load((X, Y, Z + 3))
    setup(batch.command)
    park(batch.command, scan)
    rows = batch.run(session, 'smart-chute-hopper')
    batch = Batch()
    batch.load((X, Y, Z + 3))
    release(batch.command, scan)
    rows += batch.run(session, 'smart-chute-hopper-restart')
    result = {}
    for phase, count in phases:
        assert all('bearing_check' in row for row in rows[:len(LANES)]), (phase, rows[:len(LANES)])
        del rows[:len(LANES)]
        result[phase] = observe(rows[:count], phase)
        del rows[:count]
    assert not rows, rows
    verify(result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--java', action='store_true')
    for flag in ('game', 'resources', 'ctl', 'reference', 'create-jar'):
        parser.add_argument('--' + flag, type=Path)
    args = parser.parse_args()
    if args.java:
        work = Path(tempfile.mkdtemp(prefix='smart-chute-hopper-java-', dir=ROOT / '.local'))
        print(work, flush=True)
        result = java_run(work)
    else:
        if not all((args.game, args.resources, args.ctl, args.reference)):
            parser.error('Horizon requires --game, --resources, --ctl and --reference')
        reference = json.loads(args.reference.read_text())
        assert reference['create'] == PINS['create_revision'] and reference['passed'], reference
        session = NativeCheckSession(args.game, args.resources, args.ctl, args.create_jar,
                                     name='smart-chute-hopper-native', graphics=False, world='CreateSmartChuteHopper')
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
