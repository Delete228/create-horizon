#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Compare Fluid Tank controller grouping under a configured height limit."""

import argparse
import json
from pathlib import Path
import re
import shutil
import tempfile
import time

from bearing_native_checks import Batch
from burner_heat_java_checks import number
from chain_drive_checks import Original, xyz
from common import PINS, ROOT
from fan_config_checks import configure_java
from fluid_pump_java_checks import TANK
from native_check_session import NativeCheckSession
from reference_java import BASE


AREA = '2630 167 1488 2645 210 1512'
LOAD = '2624 1488 2655 1519'


def groups(limit):
    return (((2634,168,1491), 1, limit+2), ((2639,168,1497), 2, 3), ((2639,168,1505), 3, 3))


def parts(root, width, height):
    x, y, z = root
    return [(x+dx, y+dy, z+dz) for dy in range(height) for dx in range(width) for dz in range(width)]


def setup(cmd, limit):
    cmd(f'fill {AREA} minecraft:air')
    for root, width, height in groups(limit):
        end = tuple(a+b for a,b in zip(root, (width-1,height-1,width-1), strict=True))
        cmd(f'fill {xyz(root)} {xyz(end)} {TANK}')


def decode(pos, raw):
    parent = re.search(r'\bController:\s*\[I;\s*(-?\d+),\s*(-?\d+),\s*(-?\d+)\]', raw)
    if parent:
        return dict(controller=list(map(int, parent.groups())))
    return dict(controller=list(pos), width=int(number({'nbt': raw}, 'Size')),
                height=int(number({'nbt': raw}, 'Height')))


def java_run(work, limit, positions):
    host = Original()
    initial = host.call('state', {})
    assert initial['ready'] and initial['data_version'] == 3955, initial
    config = BASE / 'game/config/create-server.toml'
    original = config.read_bytes()
    host.call('tick', {'frozen': True})
    try:
        configure_java(config, original, dict(fluidTankMaxHeight=limit))
        time.sleep(2)
        host.command(f'forceload add {LOAD}')
        host.call('observe_ticks', {'positions': positions[:1], 'ticks': 14})
        setup(host.command, limit)
        host.call('observe_ticks', {'positions': positions[:1], 'ticks': 40})
        return {xyz(pos): decode(pos, host.call('block', {'pos': pos})['nbt']) for pos in positions}
    finally:
        config.write_bytes(original)
        host.command(f'fill {AREA} minecraft:air')
        host.command(f'forceload remove {LOAD}')
        host.call('tick', {'frozen': initial['server']['frozen']})
        (work / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')


def native_run(session, limit, positions):
    config = session.scratch / 'config/create-server.toml'
    config.parent.mkdir(exist_ok=True)
    config.write_text(f'[fluids]\nfluidTankMaxHeight = {limit}\n')
    batch = Batch()
    batch.load((2639,171,1498))
    setup(batch.command, limit)
    batch.tick(40)
    for pos in positions:
        batch.data(pos)
    return {xyz(pos): decode(pos, raw) for pos, raw in zip(positions, batch.run(session, 'tank-height'), strict=True)}


def verify(rows, limit):
    for root, width, height in groups(limit):
        observed = {xyz(pos): rows[xyz(pos)] for pos in parts(root, width, height)}
        assert max(row.get('height', 0) for row in observed.values()) == min(height, limit), observed
        for key, row in observed.items():
            at = xyz(row['controller'])
            controller = observed[at]
            assert at == xyz(controller['controller']) and controller['height'] <= limit, (key, row)
            assert key in {xyz(pos) for pos in parts(row['controller'], controller['width'], controller['height'])}, (key, row)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--java', action='store_true')
    parser.add_argument('--limit', type=int, choices=(2,36), required=True)
    for flag in ('game', 'resources', 'ctl', 'create-jar', 'reference'):
        parser.add_argument('--'+flag, type=Path)
    args = parser.parse_args()
    positions = [pos for root, width, height in groups(args.limit) for pos in parts(root, width, height)]
    if args.java:
        work = Path(tempfile.mkdtemp(prefix='tank-height-java-', dir=ROOT / '.local'))
        print(work, flush=True)
        rows = java_run(work, args.limit, positions)
    else:
        if not all((args.game, args.resources, args.ctl, args.create_jar, args.reference)):
            parser.error('Horizon requires --game, --resources, --ctl, --create-jar and --reference')
        session = NativeCheckSession(args.game, args.resources, args.ctl, args.create_jar,
                                     name='tank-height-native', world='CreateTankHeight')
        work = session.scratch
        print(work, flush=True)
        try:
            rows = native_run(session, args.limit, positions)
        finally:
            session.control_temp.cleanup()
            for folder in (session.resources, work / '.horizon-cache', work / 'horizon-mods'):
                shutil.rmtree(folder, ignore_errors=True)
    (work / 'observed.json').write_text(json.dumps(rows, indent=2) + '\n')
    verify(rows, args.limit)
    if not args.java:
        expected = json.loads(args.reference.read_text())
        assert expected['passed'] and expected['create'] == PINS['create_revision'] and expected['limit'] == args.limit
        for pos, row in rows.items():
            assert row == expected['rows'][pos], (pos, row, expected['rows'][pos])
    result = work / 'result.json'
    result.write_text(json.dumps(dict(passed=True, create=PINS['create_revision'], limit=args.limit, rows=rows), indent=2) + '\n')
    print(result)


if __name__ == '__main__':
    main()
