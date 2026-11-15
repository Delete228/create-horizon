#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Check creative paste of ordinary Fluid Tank schematics in both games."""

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import tempfile

from burner_heat_java_checks import field, number
from chain_drive_checks import Native, Original, xyz
from common import PINS, ROOT
from fluid_tank_checks import expected_tank, offset, part_snapshot, set_fluid, tank_parts
from native_check_session import NativeCheckSession, wait_loaded
from reference_java import BASE, CREATE_SHA256, stage_schematic
from schematic_checks import _json_reply
from schematic_chute_checks import CASES
from schematic_rotation_checks import ROTATIONS, fixture


TANK = 'create:fluid_tank'
AIR = 'minecraft:air'
GOLD = 'minecraft:gold_block'
ANCHOR = (2711, 146, 1719)
ROOM = '2707 144 1715 2715 151 1723'
FORCE = '2704 1712 2719 1727'
SIZE = (3, 1, 1)
BOILER = dict.fromkeys(('ActiveHeat', 'Engines', 'PassiveHeat', 'Supply', 'Update', 'Whistles'), 0)
BLOCKS = [((2 * window, 0, 0), TANK,
           dict(top='true', bottom='true', shape='window' if window else 'plain'),
           {'id': (8, TANK), 'Window': (1, window), 'Height': (3, 1), 'Size': (3, 1)})
          for window in (0, 1)]
EXPORT_ORIGIN = (2731, 146, 1720)
EXPORT_SIZE = (9, 3, 8)
MULTI_ANCHOR = (2767, 146, 1727)
MULTI_ROOM = '2758 146 1718 2776 149 1736'
MULTI_COLUMNS = '2720 1712 2783 1743'
OBSTRUCTION = offset(MULTI_ANCHOR, 2, 1, 7)
BEDROCK = 'minecraft:bedrock'
GROUPS = (((0, 0, 0), 2, 2, True), ((5, 0, 1), 2, 2, False),
          ((1, 0, 5), 3, 2, True), ((7, 0, 5), 1, 3, False))


def multiblock_placements(mirror, turns):
    for local, width, height, window in GROUPS:
        members = []
        for x, y, z in tank_parts(local, width, height):
            x = -x if mirror == 'front_back' else x
            z = -z if mirror == 'left_right' else z
            dx, dz = ((x, z), (-z, x), (-x, -z), (z, -x))[turns]
            members.append(offset(MULTI_ANCHOR, dx, y, dz))
        yield tuple(map(min, zip(*members))), width, height, window


def transformed_expected(mirror, turns):
    return {key: row for origin, width, height, window in multiblock_placements(mirror, turns)
            for key, row in expected_tank(origin, width, height, window=window).items()}


def multiblock_snapshot(host, expected):
    return {key: part_snapshot(host, tuple(map(int, key.split()))) for key in expected}


def java_multiblock(work):
    host = Original()
    initial = host.call('state', {})
    assert initial['ready'] and initial['data_version'] == 3955, initial
    assert json.loads((BASE / 'manifest.json').read_text())['create_sha256'] == CREATE_SHA256
    last = offset(EXPORT_ORIGIN, *(side - 1 for side in EXPORT_SIZE))
    source_room = f'{xyz(EXPORT_ORIGIN)} {xyz(last)}'
    source_name = f'{work.name}.nbt'
    path = None
    host.call('tick', {'frozen': True})
    try:
        host.command('gamemode creative')
        host.command(f'forceload add {MULTI_COLUMNS}')
        host.command(f'tp @s {MULTI_ANCHOR[0]}.5 {MULTI_ANCHOR[1] + 4} {MULTI_ANCHOR[2]}.5')
        host.snapshot([EXPORT_ORIGIN, MULTI_ANCHOR], 24)
        host.command(f'fill {source_room} {AIR}')
        expected_source = {}
        for index, (local, width, height, window) in enumerate(GROUPS):
            origin = offset(EXPORT_ORIGIN, *local)
            end = offset(origin, width - 1, height - 1, width - 1)
            host.command(f'fill {xyz(origin)} {xyz(end)} {TANK}')
            host.snapshot([origin], 6)
            if not window:
                host.command(f'data merge block {xyz(origin)} {{Window:0b}}')
                for pos in tank_parts(origin, width, height):
                    # Vanilla /setblock preserves the BE when only its shape changes.
                    top = str(pos[1] == end[1]).lower()
                    bottom = str(pos[1] == origin[1]).lower()
                    host.command(f'setblock {xyz(pos)} {TANK}[shape=plain,top={top},bottom={bottom}]')
            amount = 19000 if index == 0 else 0
            if amount:
                set_fluid(host, origin, amount)
            expected_source.update(expected_tank(origin, width, height, amount, window=window))
        host.snapshot([EXPORT_ORIGIN], 6)
        assert multiblock_snapshot(host, expected_source) == expected_source
        exported = host.call('schematic_export', {'file': source_name, 'first': EXPORT_ORIGIN, 'second': last})
        path = Path(exported['path'])
        saved = work / 'fluid-tanks-exported.nbt'
        shutil.copy2(path, saved)

        results = {}
        for mirror, turns in CASES:
            host.command(f'fill {MULTI_ROOM} {AIR}')
            reply = host.call('schematic', {'file': path.name, 'origin': MULTI_ANCHOR,
                                            'rotation': ROTATIONS[turns], 'mirror': mirror.upper()})
            assert reply['placed'], (mirror, turns, reply)
            expected = transformed_expected(mirror, turns)
            host.snapshot([MULTI_ANCHOR], 8)
            results[f'{mirror}:{turns}'] = multiblock_snapshot(host, expected)
            (work / 'observed-multiblocks.json').write_text(json.dumps(results, indent=2) + '\n')
        exact = [f'{mirror}:{turns}' for mirror, turns in CASES
                 if results[f'{mirror}:{turns}'] == transformed_expected(mirror, turns)]
        assert exact == ['none:0', 'left_right:1', 'front_back:3'], exact
        assert all(row.get('amount', 0) == 0 for rows in results.values() for row in rows.values())
        host.command(f'fill {MULTI_ROOM} {AIR}')
        host.command(f'setblock {xyz(MULTI_ANCHOR)} {GOLD}')
        host.command(f'setblock {xyz(OBSTRUCTION)} {BEDROCK}')
        host.call('schematic', {'file': path.name, 'origin': MULTI_ANCHOR})
        blocked = {xyz(pos): host.call('block', {'pos': pos})['id'] for pos in (MULTI_ANCHOR, OBSTRUCTION)}
        assert blocked == {xyz(MULTI_ANCHOR): TANK, xyz(OBSTRUCTION): BEDROCK}, blocked
        return dict(export=saved.name, sha256=hashlib.sha256(saved.read_bytes()).hexdigest(),
                    placements=results, exact=exact, blocked=blocked)
    finally:
        host.command(f'fill {source_room} {AIR}')
        host.command(f'fill {MULTI_ROOM} {AIR}')
        host.command(f'forceload remove {MULTI_COLUMNS}')
        host.call('camera', {key: initial[key] for key in ('position', 'yaw', 'pitch')})
        host.call('tick', {'frozen': initial['server']['frozen']})
        if path is not None:
            path.unlink(missing_ok=True)
            (BASE / 'game/schematics/uploaded/reference' / path.name).unlink(missing_ok=True)
        (work / 'transcript-multiblocks.json').write_text(json.dumps(host.trace, indent=2) + '\n')


def placements(mirror, turns):
    for (x, _, _), _, props, _ in BLOCKS:
        x = -x if mirror == 'front_back' else x
        dx, dz = ((x, 0), (0, x), (-x, 0), (0, -x))[turns]
        yield (ANCHOR[0] + dx, ANCHOR[1], ANCHOR[2] + dz), props


def record(block, pos, props):
    state = {key: value.lower() for key, value in block['properties'].items()}
    nbt = block['nbt']
    assert block['id'] == TANK and state == props, (block, props)
    assert re.search(r'\bid:\s*"create:fluid_tank"', nbt), nbt
    assert field(nbt, 'TankContent') == '{}', nbt
    assert not re.search(r'\b(Controller|Uninitialized)\s*:', nbt), nbt
    boiler = field(nbt, 'Boiler')
    assert set(re.findall(r'[,{]\s*(\w+)\s*:', boiler)) == BOILER.keys(), boiler
    assert {key: number({'nbt': boiler}, key) for key in BOILER} == BOILER, boiler
    window = int(props['shape'] == 'window')
    assert tuple(number(block, key) for key in ('Window', 'Size', 'Height', 'Luminosity')) == (window, 1, 1, 0), nbt
    assert [number(block, axis) for axis in 'xyz'] == list(pos), nbt
    location = re.search(r'\bLastKnownPos:\s*\[I;\s*(-?\d+),\s*(-?\d+),\s*(-?\d+)\]', nbt)
    if location:
        assert tuple(map(int, location.groups())) == pos, nbt
    return dict(properties=props, last_known_pos=bool(location))


def java(work, path):
    host = Original()
    initial = host.call('state', {})
    if initial.get('screen') == 'PauseScreen':
        host.call('input', {'kind': 'escape'})
        initial = host.call('state', {})
    assert initial['ready'] and initial['data_version'] == 3955, initial
    assert json.loads((BASE / 'manifest.json').read_text())['create_sha256'] == CREATE_SHA256
    staged = Path(stage_schematic(BASE, path)['staged'])
    results, raw = [], []
    host.call('tick', {'frozen': True})
    try:
        host.command('gamemode creative')
        host.command(f'forceload add {FORCE}')
        host.command(f'tp @s {ANCHOR[0]}.5 {ANCHOR[1]+4} {ANCHOR[2]}.5')
        host.snapshot([ANCHOR], 24)
        for mirror, turns in CASES:
            host.command(f'fill {ROOM} {AIR}')
            reply = host.call('schematic', {'file': staged.name, 'origin': ANCHOR,
                                            'rotation': ROTATIONS[turns], 'mirror': mirror.upper()})
            assert reply['placed'], (mirror, turns, reply)
            states = list(placements(mirror, turns))
            positions = [pos for pos, _ in states]
            before = [host.call('block', {'pos': pos}) for pos in positions]
            first = host.call('observe_ticks', {'ticks': 1, 'positions': positions})['samples'][0]['blocks']
            frames = [before, first]
            rows = [[record(row, pos, props) for row, (pos, props) in zip(frame, states, strict=True)] for frame in frames]
            assert [row['last_known_pos'] for frame in rows for row in frame] == [False, False, True, True], rows
            results.append(rows)
            raw.append([[row['nbt'] for row in frame] for frame in frames])
        (work / 'java-raw-nbt.json').write_text(json.dumps(raw, indent=2) + '\n')
        return results
    finally:
        host.command(f'fill {ROOM} {AIR}')
        host.command(f'forceload remove {FORCE}')
        host.call('camera', {key: initial[key] for key in ('position', 'yaw', 'pitch')})
        host.call('tick', {'frozen': initial['server']['frozen']})
        staged.unlink()
        (work / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')


def native(session, path):
    directory = session.scratch / 'schematics'
    directory.mkdir()
    shutil.copy2(path, directory / path.name)
    call = session.call

    def command(text):
        return call('command', text)

    def paste(name, mirror='none', turns=0):
        return _json_reply(command(f'create schematic paste {name} {xyz(ANCHOR)} {turns} {mirror}'))

    def server_record(pos, props):
        state = TANK + '[' + ','.join(f'{key}={value}' for key, value in props.items()) + ']'
        reply = command(f'execute if block {xyz(pos)} {state} run data get block {xyz(pos)}')
        return record(dict(id=TANK, properties=props, nbt=' '.join(reply['chat'])), pos, props)

    command(f'tp @s {ANCHOR[0]}.5 {ANCHOR[1]+4} {ANCHOR[2]}.5')
    wait_loaded(call, [ANCHOR])
    command('tick freeze')
    results, refusals = [], {}
    for mirror, turns in CASES:
        command(f'fill {ROOM} {AIR}')
        reply = paste(path.name, mirror, turns)
        assert reply['ok'] and reply['placed'] == len(BLOCKS), (mirror, turns, reply)
        states = list(placements(mirror, turns))
        before = [server_record(pos, props) for pos, props in states]
        command('tick step 1')
        call('wait', 4)
        after = [server_record(pos, props) for pos, props in states]
        for pos, props in states:
            client = call('block', *pos)
            state = dict(re.findall(r'(\w+)=(\w+)', client['state']))
            assert client['block'] == TANK and {k: state[k] for k in props} == props, client
        results.append([before, after])

    command(f'fill {ROOM} {AIR}')
    command(f'setblock {xyz(ANCHOR)} {GOLD}')
    for key, blocks in {
        'adjacent': [BLOCKS[0], ((1, 0, 0), *BLOCKS[1][1:])],
        'malformed_content': [BLOCKS[0], (*BLOCKS[1][:3], BLOCKS[1][3] | {'TankContent': (3, 1000)})],
    }.items():
        bad = fixture(directory, blocks=blocks, size=SIZE, prefix=key)
        reply = paste(bad.name)
        assert not reply['ok'] and reply['issues'], (key, reply)
        for dx, block in enumerate((GOLD, AIR, AIR)):
            pos = (ANCHOR[0] + dx, ANCHOR[1], ANCHOR[2])
            check = command(f'execute if block {xyz(pos)} {block} run say tank_unchanged')
            assert any('tank_unchanged' in message for message in check['chat']), (key, pos, check)
        refusals[key] = reply['issues']
    return dict(placements=results, refusals=refusals)


def native_multiblock(session, path, reference):
    host = Native(session)
    call = session.call
    directory = session.scratch / 'schematics'
    directory.mkdir()
    shutil.copy2(path, directory / path.name)
    host.command(f'tp @s {MULTI_ANCHOR[0]}.5 {MULTI_ANCHOR[1] + 4} {MULTI_ANCHOR[2]}.5')
    positions = {tuple(map(int, key.split())) for mirror, turns in CASES
                 for key in transformed_expected(mirror, turns)}
    columns = {((x + dx) >> 4, (z + dz) >> 4) for x, _, z in positions
               for dx, dz in ((-1, 0), (1, 0), (0, -1), (0, 1), (0, 0))}
    loaded = [(x << 4, MULTI_ANCHOR[1], z << 4) for x, z in sorted(columns)]
    wait_loaded(call, loaded)

    def paste(file=path, mirror='none', turns=0):
        return _json_reply(host.command(f'create schematic paste {file.name} {xyz(MULTI_ANCHOR)} {turns} {mirror}'))

    def assert_block(pos, block):
        reply = host.command(f'execute if block {xyz(pos)} {block} run say tank_schematic_expected')
        assert any('tank_schematic_expected' in line for line in reply['chat']), (pos, block, reply)

    report = dict(placements={}, refusals={})
    for mirror, turns in CASES:
        host.command(f'fill {MULTI_ROOM} {AIR}')
        call('wait', 5)
        expected = transformed_expected(mirror, turns)
        key = f'{mirror}:{turns}'
        reply = paste(mirror=mirror, turns=turns)
        assert reply['ok'] and reply['placed'] == len(expected), (key, reply)
        assert any(note['field'] == 'TankContent' for note in reply['notes']), reply
        call('wait', 8)
        observed = multiblock_snapshot(host, expected)
        assert observed == expected, (key, observed)
        if key in reference['exact']:
            assert observed == reference['placements'][key]
        report['placements'][key] = observed
    session.restart()
    wait_loaded(call, loaded)
    last = report['placements'][key]
    assert multiblock_snapshot(host, last) == last
    report['cold'] = True

    host.command(f'fill {MULTI_ROOM} {AIR}')
    call('wait', 8)
    host.command(f'setblock {xyz(MULTI_ANCHOR)} {GOLD}')
    host.command(f'setblock {xyz(OBSTRUCTION)} {BEDROCK}')
    reply = paste()
    assert not reply['ok'] and any('unbreakable' in issue['message'] for issue in reply['issues']), reply
    assert_block(MULTI_ANCHOR, GOLD)
    assert_block(OBSTRUCTION, BEDROCK)
    assert_block(offset(MULTI_ANCHOR, 1, 0, 0), AIR)
    report['refusals']['blocked'] = reply['issues']
    host.command(f'setblock {xyz(OBSTRUCTION)} {AIR}')

    external = offset(MULTI_ANCHOR, -1, 0, 0)
    host.command(f'setblock {xyz(external)} {TANK}')
    call('wait', 5)
    reply = paste()
    assert not reply['ok'] and any('existing tanks' in issue['message'] for issue in reply['issues']), reply
    assert_block(MULTI_ANCHOR, GOLD)
    assert_block(external, TANK)
    report['refusals']['external_tank'] = reply['issues']
    host.command(f'setblock {xyz(external)} {AIR}')

    first = dict(top='false', bottom='true', shape='window_nw')
    missing = fixture(directory, size=(2, 2, 2), prefix='partial', blocks=[
        ((0, 0, 0), TANK, first, {'id': (8, TANK), 'Window': (1, 1), 'Size': (3, 2), 'Height': (3, 2)}),
        ((1, 0, 0), TANK, first | {'shape': 'window_ne'}, {'id': (8, TANK)}),
    ])
    reply = paste(missing)
    assert not reply['ok'] and any('complete footprint' in issue['message'] for issue in reply['issues']), reply
    assert_block(MULTI_ANCHOR, GOLD)
    assert_block(offset(MULTI_ANCHOR, 1, 0, 0), AIR)
    report['refusals']['partial'] = reply['issues']
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--multiblock', action='store_true')
    for name in ('game', 'resources', 'ctl', 'reference', 'create-jar'):
        parser.add_argument('--' + name, type=Path)
    args = parser.parse_args()
    work = Path(tempfile.mkdtemp(prefix='schematic-tank-', dir=ROOT / '.local'))
    if args.multiblock:
        report = dict(passed=False, create=PINS['create_revision'])
        try:
            if args.game:
                if not all((args.resources, args.ctl, args.reference, args.create_jar)):
                    parser.error('Horizon multiblock check requires --resources, --ctl, --reference and --create-jar')
                source = json.loads(args.reference.read_text())
                path = args.reference.parent / source['export']
                assert source['passed'] and source['create'] == report['create']
                assert hashlib.sha256(path.read_bytes()).hexdigest() == source['sha256']
                session = NativeCheckSession(args.game, args.resources, args.ctl, args.create_jar, graphics=False,
                                             world='SchematicTankMultiblock', name='schematic-tank-multi-native')
                report.update(session=str(session.scratch), sha256=source['sha256'])
                try:
                    with session:
                        report.update(native_multiblock(session, path, source))
                finally:
                    session.control_temp.cleanup()
                    for folder in (session.resources, session.scratch / '.horizon-cache', session.scratch / 'horizon-mods'):
                        shutil.rmtree(folder, ignore_errors=True)
            else:
                report.update(java_multiblock(work))
            report['passed'] = True
        finally:
            result = work / 'result.json'
            result.write_text(json.dumps(report, indent=2) + '\n')
            print(result, flush=True)
        return
    path = fixture(work, blocks=BLOCKS, size=SIZE, prefix='empty-fluid-tanks')
    report = dict(passed=False, create=PINS['create_revision'], sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    try:
        if args.game:
            if not all((args.resources, args.ctl, args.reference)):
                parser.error('Horizon requires --game, --resources, --ctl and --reference')
            source = json.loads(args.reference.read_text())
            assert source['passed'] and source['create'] == report['create'] and source['sha256'] == report['sha256']
            session = NativeCheckSession(args.game, args.resources, args.ctl, None, graphics=False,
                                         world='SchematicTank', name='schematic-tank-native')
            try:
                with session:
                    report.update(native(session, path))
                assert report['placements'] == source['placements']
            finally:
                session.control_temp.cleanup()
                for folder in (session.resources, session.scratch / '.horizon-cache', session.scratch / 'horizon-mods'):
                    shutil.rmtree(folder, ignore_errors=True)
        else:
            report['placements'] = java(work, path)
        report['passed'] = True
    finally:
        result = work / 'result.json'
        result.write_text(json.dumps(report, indent=2) + '\n')
        print(result, flush=True)


if __name__ == '__main__':
    main()
