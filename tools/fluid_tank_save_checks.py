#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Break a tank with half its footprint unloaded, then reopen the actual save."""

import argparse
import gzip
import json
from pathlib import Path
import shutil

from chain_drive_checks import Native, xyz
from fluid_tank_checks import TANK, offset, set_fluid, part_snapshot
from native_check_session import NativeCheckSession, wait_loaded


WORLD = 'CreateDeferredTankSplit'
ROOT = (1039, 168, 1025)
PARTS = [offset(ROOT, dx=dx, dz=dz) for dx in range(2) for dz in range(2)]
LEFT, RIGHT = PARTS[0], PARTS[-1]
FAR = (1800, 170, 1800)
MARKERS = {pos: offset(pos, dz=6) for pos in (LEFT, RIGHT)}
PENDING = b'fluid_tank_pending_splits'


def loaded(session, pos):
    marker = MARKERS[pos]
    reply = session.call('command', f'execute if block {xyz(marker)} minecraft:barrel run say fixture_loaded')
    return any('fixture_loaded' in line for line in reply.get('chat', ()))


def wait_residency(session, expected):
    for _ in range(120):
        observed = {pos: loaded(session, pos) for pos in expected}
        if observed == expected:
            return
        session.call('wait', 5)
    raise AssertionError((expected, observed))


def attachment(session):
    candidates = list((session.scratch / 'saves' / WORLD).rglob('attachments.dat'))
    if not candidates:
        return b''
    assert len(candidates) == 1, candidates
    return gzip.decompress(candidates[0].read_bytes())


def run_case(session, *, root_break):
    host = Native(session)
    cmd = host.command
    cmd('forceload remove all')
    cmd('tp @s 1040 168 1027')
    wait_loaded(session.call, (LEFT, RIGHT))
    cmd(f'fill {xyz(LEFT)} {xyz(RIGHT)} minecraft:air')
    cmd(f'fill {xyz(LEFT)} {xyz(RIGHT)} {TANK}')
    session.call('wait', 12)
    assert part_snapshot(host, ROOT)['size'] == 2
    set_fluid(host, ROOT, 19_000)
    for marker in MARKERS.values():
        cmd(f'setblock {xyz(marker)} minecraft:barrel')
    session.call('save-all')

    # Keep the already generated column at the edge of a forced range.
    # The vanilla loaded predicate checks entity ticking, so probe the
    # marker blocks instead. That uses the same residency check as setblock.
    retained_x = (LEFT[0] >> 4) - 4 if root_break else (RIGHT[0] >> 4) + 4
    cmd(f'forceload add {retained_x << 4} {LEFT[2]}')
    cmd(f'tp @s {xyz(FAR)}')
    expected = {LEFT: root_break, RIGHT: not root_break}
    wait_residency(session, expected)
    removed = ROOT if root_break else RIGHT
    cmd(f'setblock {xyz(removed)} minecraft:air')
    session.call('save-all')
    session.restart()
    wait_residency(session, expected)
    assert PENDING in attachment(session), 'The pending split was missing after cold restart'

    cmd('tp @s 1040 168 1027')
    wait_loaded(session.call, (LEFT, RIGHT))
    session.call('wait', 12)
    survivors = [pos for pos in PARTS if pos != removed]
    result = [part_snapshot(host, pos) for pos in survivors]
    assert all(r['size'] == 1 and r['height'] == 1 and 'controller' not in r for r in result), result
    assert [r['amount'] for r in result] == [8000, 8000, 3000], result
    assert all(r['fluid'] == 'minecraft:water' for r in result), result
    session.call('save-all')
    assert PENDING not in attachment(session), 'The applied split was still pending'
    session.restart()
    wait_loaded(session.call, (LEFT, RIGHT))
    assert [part_snapshot(host, pos) for pos in survivors] == result
    return dict(removed=removed, survivors=survivors, volumes=[r['amount'] for r in result])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in ('game', 'resources', 'ctl', 'create-jar'):
        parser.add_argument('--' + flag, type=Path, required=flag != 'create-jar')
    args = parser.parse_args()
    session = NativeCheckSession(args.game, args.resources, args.ctl, args.create_jar,
                                 name='fluid-tank-save', graphics=False, world=WORLD)
    work = session.scratch
    print(work, flush=True)
    try:
        with session:
            report = {name: run_case(session, root_break=root) for name, root in
                      (('unloaded_member', True), ('unloaded_controller', False))}
    finally:
        for folder in (session.resources, work / '.horizon-cache', work / 'horizon-mods'):
            shutil.rmtree(folder, ignore_errors=True)
    path = work / 'result.json'
    path.write_text(json.dumps({'passed': True, **report}, indent=2) + '\n')
    print(path)


if __name__ == '__main__':
    main()
