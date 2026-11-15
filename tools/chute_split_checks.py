#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Compare an ordinary Chute split and its angled outlet with Java Create."""

import argparse
import json
from pathlib import Path
import shutil
import tempfile
import time

from bearing_native_checks import Batch
from burner_heat_java_checks import items, number
from chain_drive_checks import Original, xyz
from common import PINS, ROOT
from funnel_checks import put
from native_check_session import NativeCheckSession
import reference_java as java


Y = 181
CASES = {'straight': (1293, 394), 'angled': (1295, 398)}
AREA = (1290, Y-4, 391, 1300, Y+6, 402)
CAMERA = (1296.5, Y+3, 397.5)
CARGO = 'minecraft:stick'
BLOCKED = 'minecraft:iron_ingot'
TICKS, RESTART = 62, 13


def lane(name):
    x, z = CASES[name]
    return [(x, Y, z), (x, Y+1, z), (x+1, Y+1, z), (x+1, Y+2, z),
            (x, Y+2, z), (x+1, Y+3, z)]


POINTS = [pos for name in CASES for pos in lane(name)]


def payload(item, count, tag):
    return f'id:"{item}",count:{count},components:{{"minecraft:custom_data":{{chute_split:{tag}}}}}'


def setup(command, wet=False):
    command('fill ' + xyz(AREA) + ' minecraft:air')
    for name, (x, z) in CASES.items():
        put(command, (x, Y-2, z), 'create:creative_motor[facing=up]{ScrollValue:128}')
        put(command, (x, Y-1, z), 'create:encased_fan[facing=up]')
        for i, pos in enumerate(lane(name)[:4]):
            face = 'east' if i == 2 else 'down'
            put(command, pos, f'create:chute[facing={face},shape=window,waterlogged={str(wet).lower()}]')
        full = ('{Items:[' + ','.join(f'{{Slot:{i}b,id:"minecraft:stone",count:64}}'
                                       for i in range(27)) + ']}') if name == 'angled' else ''
        put(command, lane(name)[4], 'minecraft:barrel' + full)
        put(command, lane(name)[5], 'minecraft:barrel')


def seed(command, *, native=False):
    x, z = CASES['angled']
    blocker = payload(BLOCKED, 3, 91)
    live = f',Items:[{{Slot:0b,{blocker}}}]' if native else ''
    command(f'data merge block {x} {Y+1} {z} {{Item:{{{blocker}}},ItemPosition:0.5f{live}}}')
    for i, (x, z) in enumerate(CASES.values(), 1):
        cargo = payload(CARGO, 1, i)
        put(command, (x-1, Y, z), f'minecraft:hopper[facing=east]{{Items:[{{Slot:0b,{cargo}}}]}}')


def row(blocks):
    report = {}
    for i, name in enumerate(CASES, 1):
        states = blocks[6*(i-1):6*i]
        chutes, barrels = states[:4], states[4:]
        stacks = [items(block['nbt'], 'Item') for block in chutes]
        counts = [stack.get(CARGO, 0) for stack in stacks]
        counts += [items(block['nbt'], 'Items').get(CARGO, 0) for block in barrels]
        for block, count in zip(states, counts, strict=True):
            if count:
                assert number(block, 'chute_split') == i, block
        parked = stacks[1].get(BLOCKED, 0)
        if parked:
            assert number(chutes[1], 'chute_split') == 91, chutes[1]
        report[name] = dict(counts=counts,
                            offsets=[number(block, 'ItemPosition') if count else None
                                     for block, count in zip(chutes, counts[:4], strict=True)],
                            push=[number(block, 'Push') for block in chutes], parked=parked)
    return report


class JavaShutdownTimeout(RuntimeError):
    pass


def stop_java(host, timeout):
    host.call('quit', {})
    deadline = time.monotonic() + timeout
    while java.process_alive(java.BASE):
        if time.monotonic() >= deadline:
            raise JavaShutdownTimeout('Isolated Java client failed to save and exit')
        time.sleep(.15)


def java_run(work, cold, wet, shutdown_timeout):
    host = Original()
    initial = host.call('state', {})
    assert initial['ready'] and initial['data_version'] == 3955
    assert json.loads((java.BASE / 'manifest.json').read_text())['create_sha256'] == java.CREATE_SHA256
    ready = True

    def wait_loaded(*positions):
        for _ in range(40):
            probes = [host.command(f'execute if loaded {xyz(pos)}') for pos in positions]
            if all(any('Test passed' in line for line in probe['messages']) for probe in probes):
                return
            time.sleep(.15)
        raise AssertionError('Chute split fixture columns did not load')

    def advance(ticks):
        response = host.call('observe_ticks', {'positions': POINTS, 'ticks': ticks, 'ticker_order': True})
        if wet:
            assert all(block['properties']['waterlogged'] == 'true' for sample in response['samples']
                       for index, block in enumerate(sample['blocks']) if index % 6 < 4)
        return [row(sample['blocks']) for sample in response['samples']]

    try:
        if cold:
            options = dict(line.split(':', 1) for line in (java.BASE / 'game/options.txt').read_text().splitlines()
                           if ':' in line)
            distance = max(int(options.get(key, 4)) for key in ('renderDistance', 'simulationDistance'))
            park = (CAMERA[0] + (distance + 7) * 16, CAMERA[1], CAMERA[2])
            park_block = tuple(map(int, park))
            # Warm the parking chunks before the wet fixture exists. Quitting
            # after a frozen teleport into new chunks can stall Java's unload.
            host.call('camera', {'position': park})
            host.call('tick', {'frozen': False})
            wait_loaded(park_block)
            host.call('tick', {'frozen': True})
            host.call('observe_ticks', {'positions': [park_block], 'ticks': 50})
        host.call('camera', {'position': CAMERA})
        if not cold:
            host.call('tick', {'frozen': False})
        wait_loaded(POINTS[0], POINTS[-1])
        if not cold:
            host.call('tick', {'frozen': True})
        setup(host.command, wet)
        host.call('observe_ticks', {'positions': POINTS, 'ticks': 6})
        seed(host.command)
        if not cold:
            return advance(TICKS)

        before = advance(RESTART)
        assert before[-1]['angled']['counts'] == [0, 0, 1, 0, 0, 0], before[-1]
        # Start the private JVM outside ticking distance of the fixture. Freeze
        # it before bringing the existing blocks and saved cargo back into view.
        host.call('camera', {'position': park})
        wait_loaded(park_block)
        ready = False
        stop_java(host, shutdown_timeout)
        restarted = java.launch(java.BASE)
        assert restarted['ready'] and restarted['position'][0] >= park[0] - 1, restarted
        ready = True
        host.call('tick', {'frozen': True})
        host.call('camera', {'position': CAMERA})
        wait_loaded(POINTS[0], POINTS[-1])
        checkpoint = row([host.call('block', {'pos': pos}) for pos in POINTS])
        assert before[-1] == checkpoint, (before[-1], checkpoint)
        return before + advance(TICKS - RESTART)
    finally:
        try:
            if ready:
                host.command('fill ' + xyz(AREA) + ' minecraft:air')
                host.call('camera', {k: initial[k] for k in ('position', 'yaw', 'pitch')})
                host.call('tick', {'frozen': initial['server']['frozen']})
        finally:
            (work / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')


def native_run(session, cold, wet):
    def sample(batch):
        for pos in POINTS:
            batch.data(pos)

    def record(batch, ticks):
        for _ in range(ticks):
            batch.tick()
            sample(batch)

    def run(batch, name):
        chutes = [pos for i, pos in enumerate(POINTS) if i % 6 < 4] if wet else []
        for pos in chutes:
            batch.expect(pos, 'create:chute[waterlogged=true]')
        raw = batch.run(session, name)
        if chutes:
            assert all('bearing_check' in reply for reply in raw[-len(chutes):])
            raw = raw[:-len(chutes)]
        assert len(raw) % len(POINTS) == 0, len(raw)
        return [row([{'nbt': nbt} for nbt in raw[i:i+len(POINTS)]])
                for i in range(0, len(raw), len(POINTS))]

    batch = Batch()
    camera = (1296, Y+2, 397)
    batch.load(camera)
    setup(batch.command, wet)
    batch.tick(6)
    seed(batch.command, native=True)
    before = []
    if cold:
        record(batch, RESTART)
        before = run(batch, 'chute-split-before-restart')
        assert before[-1]['angled']['counts'] == [0, 0, 1, 0, 0, 0], before[-1]
        batch = Batch()
        batch.load(camera)
        sample(batch)
    record(batch, TICKS - RESTART if cold else TICKS)
    after = run(batch, 'chute-split')
    if cold:
        assert before[-1] == after[0], (before[-1], after[0])
        after = after[1:]
    return before + after


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--java', action='store_true', help='capture the original Java trace (default without --game)')
    parser.add_argument('--java-root', type=Path, help='run in a separately prepared Java reference root')
    parser.add_argument('--cold', action='store_true')
    parser.add_argument('--wet', action='store_true')
    for name in ('game', 'resources', 'ctl', 'create-jar', 'reference'):
        parser.add_argument('--' + name, type=Path)
    args = parser.parse_args()
    if args.game:
        if args.java or args.java_root:
            parser.error('Select either the Java reference or a Horizon build')
        if not all((args.resources, args.ctl, args.create_jar, args.reference)):
            parser.error('Horizon requires --resources, --ctl, --create-jar and --reference')
        reference = json.loads(args.reference.read_text())
        assert reference['passed'] and reference['create'] == PINS['create_revision']
        assert reference.get('cold', False) == args.cold and reference.get('wet', False) == args.wet, (
            'Use a matching Java reference mode')
        session = NativeCheckSession(args.game, args.resources, args.ctl, args.create_jar,
                                     name='chute-split-native', world='ChuteSplit', graphics=False)
        session.env.pop('CREATE_HORIZON_PARTICLE_TRACE', None)
        work = session.scratch
        try:
            trace = native_run(session, args.cold, args.wet)
        finally:
            session.control_temp.cleanup()
            for folder in (session.resources, work / '.horizon-cache', work / 'horizon-mods'):
                shutil.rmtree(folder, ignore_errors=True)
        (work / 'observed.json').write_text(json.dumps(trace, indent=2) + '\n')
        for i, (got, expected) in enumerate(zip(trace, reference['trace'], strict=True), 1):
            assert got == expected, (i, got, expected)
    else:
        work = Path(tempfile.mkdtemp(prefix='chute-split-java-', dir=ROOT / '.local'))
        owned = False
        if args.java_root:
            base = args.java_root.resolve()
            if not base.is_relative_to(ROOT / '.local') or base == java.BASE:
                parser.error('--java-root must be a separately prepared directory under .local')
            java.BASE = base
            owned = not java.process_alive(base)
            if owned:
                java.launch(base)
        try:
            trace = java_run(work, args.cold, args.wet, 45 if args.java_root else 180)
        except JavaShutdownTimeout:
            # The first quit already started saving. A second command can
            # wait on the same stuck integrated server thread.
            owned = False
            raise
        finally:
            if owned and java.process_alive(java.BASE):
                stop_java(Original(), 45)
    assert all(sample['push'] == [128, 64, 64, 64] for row in trace for sample in row.values()), trace[0]
    assert all(sum(sample['counts']) == 1 for row in trace for sample in row.values()), trace
    assert trace[-1]['straight']['counts'] == [0, 0, 0, 0, 1, 0], trace[-1]
    assert trace[-1]['angled']['counts'] == [0, 0, 0, 0, 0, 1], trace[-1]
    assert all(row['angled']['parked'] == 3 for row in trace), trace
    receipt = work / 'result.json'
    receipt.write_text(json.dumps(dict(passed=True, create=PINS['create_revision'], cold=args.cold, wet=args.wet,
                                       trace=trace), indent=2) + '\n')
    print(receipt)


if __name__ == '__main__':
    main()
