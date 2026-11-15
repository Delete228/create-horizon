#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Compare real Fluid Tank assembly, bucket use, windows, comparators and saves."""

import argparse
import json
from pathlib import Path
import re
import shutil
import tempfile
import time
from zipfile import ZipFile

from burner_heat_java_checks import field, number
from chain_drive_checks import Native, Original, xyz
from common import PINS, ROOT
from funnel_checks import block, put, text
from goggles_checks import component_spans, wait_trace
from native_check_session import NativeCheckSession, wait_loaded
import reference_java as java


TANK = 'create:fluid_tank'
POS = (2408, 168, 990)
COMPARATOR = (2408, 168, 989)
WIRE = (2408, 168, 988)
SPILL = (2408, 168, 991)
COLUMN = '2400 976 2431 991'
AREA = '2404 167 986 2419 173 993'
FEET = (2408.5, 168, 992.65)
AIM = (2408.5, 168.75, 991)
BUCKET = 'minecraft:bucket'
WATER = 'minecraft:water_bucket'
LAVA = 'minecraft:lava_bucket'
TOWER = (2405, 168, 990)
SQUARE = (2409, 168, 986)
WIDE = (2415, 168, 986)
MIXED = (2405, 168, 987)
SQUARE_COMPARATORS = (((2408, 168, 986), 'east'), ((2411, 168, 987), 'west'))
SQUARE_WIRES = ((2407, 168, 986), (2412, 168, 987))


def click(host, work, name, held, *, feet=FEET, aim=AIM, pos=POS, face='south', attack=False):
    host.command(f'item replace entity @s weapon.mainhand with {held}')
    if isinstance(host, Native):
        call = host.session.call
        host.command(f'tp @s {xyz(feet)}')
        call('look-at', *aim)
        call('wait', 4)
        hit = call('looking-at')['block']
        assert hit['pos'] == list(pos) and hit['face'] == face, hit
        call('mouse', 'left' if attack else 'right', 'click')
        call('wait', 6)
    else:
        host.call('camera', {'position': feet, 'target': aim})
        host.call('capture', {'name': f'{work.name}/{name}-aim.png', 'frames': 4})
        hit = host.call('state', {})['hit']
        assert hit['pos'] == list(pos) and hit['face'] == face, hit
        host.call('input', {'kind': 'tap', 'key': 'attack' if attack else 'use'})
        host.call('capture', {'name': f'{work.name}/{name}-after.png', 'frames': 6})


def snapshot(host):
    tank = block(host, POS)
    assert tank['id'] == TANK, tank
    content = field(tank['nbt'], 'TankContent')
    fluid = re.search(r'\bid\s*:\s*"([^"]+)"', content)
    hand = re.search(r'\bid\s*:\s*"([^"]+)"', text(host, 'data get entity @s SelectedItem'))
    known_pos = re.search(r'\bLastKnownPos:\s*\[I;\s*(-?\d+),\s*(-?\d+),\s*(-?\d+)\]', tank['nbt'])
    assert known_pos and tuple(map(int, known_pos.groups())) == POS, tank
    return dict(state={k: v.lower() for k, v in tank['properties'].items() if k not in ('create_light', 'create_connections')},
                fluid=fluid[1] if fluid else None, amount=int(number({'nbt': content}, 'amount', 0)),
                window=int(number(tank, 'Window')), size=int(number(tank, 'Size')),
                height=int(number(tank, 'Height')), luminosity=int(number(tank, 'Luminosity')),
                comparator=int(block(host, WIRE)['properties']['power']),
                held=hand[1] if hand else None, spill=block(host, SPILL)['id'])


def settle(host, ticks=5):
    if isinstance(host, Native):
        host.session.call('wait', ticks)
    else:
        host.call('observe_ticks', {'positions': [POS], 'ticks': ticks})


def setup(host, work):
    cmd = host.command
    cmd('gamemode creative')
    cmd('item replace entity @s weapon.mainhand with minecraft:air')
    cmd(f'fill {AREA} minecraft:air')
    cmd('fill 2404 167 986 2419 167 993 minecraft:smooth_stone')
    put(cmd, POS, TANK)
    put(cmd, COMPARATOR, 'minecraft:comparator[facing=south]')
    put(cmd, WIRE, 'minecraft:redstone_wire')
    settle(host, 8)
    raw = block(host, POS)['nbt']
    (work / 'initial-nbt.txt').write_text(raw + '\n')
    return raw


def scenarios(host, work):
    setup(host, work)
    phases = {}

    def take(name):
        settle(host)
        phases[name] = snapshot(host)
        (work / 'observed.json').write_text(json.dumps(phases, indent=2) + '\n')
        if isinstance(host, Native) and name in ('lava', 'hide', 'show', 'almost-full'):
            host.session.call('key', 'f1', 'tap')
            host.session.call('wait', 3)
            host.session.call('screenshot', work / f'{name}.png')
            host.session.call('key', 'f1', 'tap')

    take('empty')
    for name, item in [('water', WATER), ('incompatible', LAVA), ('drain-water', BUCKET),
                       ('lava', LAVA), ('hide', 'create:wrench'), ('show', 'create:wrench')]:
        click(host, work, name, item)
        take(name)
    (work / 'lava-nbt.txt').write_text(block(host, POS)['nbt'] + '\n')
    host.command('gamemode survival')
    click(host, work, 'survival-empty', BUCKET)
    take('survival-empty')
    click(host, work, 'survival-water', WATER)
    take('survival-water')
    put(host.command, SPILL, 'minecraft:air')
    host.command('gamemode creative')
    click(host, work, 'drain-lava', BUCKET)
    take('drain-lava')
    # Horizon's generic data command does not notify comparators. Exercise
    # the normal bucket action on both sides after seeding the fractional fill.
    host.command(f'data merge block {xyz(POS)} {{TankContent:{{Fluid:{{id:"minecraft:water",amount:6500}}}}}}')
    click(host, work, 'finish-pour', WATER)
    take('almost-full')
    click(host, work, 'would-overflow', WATER)
    take('would-overflow')
    return phases


def verify(phases):
    expected = {
        'empty': (None, 0, 0, 0, 1),
        'water': ('water', 1000, 2, 0, 1),
        'incompatible': ('water', 1000, 2, 0, 1),
        'drain-water': (None, 0, 0, 0, 1),
        'lava': ('lava', 1000, 2, 12, 1),
        'hide': ('lava', 1000, 2, 12, 0),
        'show': ('lava', 1000, 2, 12, 1),
        'survival-empty': ('lava', 1000, 2, 12, 1),
        'survival-water': ('lava', 1000, 2, 12, 1),
        'drain-lava': (None, 0, 0, 0, 1),
        'almost-full': ('water', 7500, 14, 0, 1),
        'would-overflow': ('water', 7500, 14, 0, 1),
    }
    for name, row in phases.items():
        fluid, amount, comparator, luminosity, window = expected[name]
        assert row['state'] == dict(top='true', bottom='true', shape='window' if window else 'plain'), (name, row)
        assert (row['fluid'], row['amount'], row['comparator'], row['luminosity'], row['window']) == (
            f'minecraft:{fluid}' if fluid else None, amount, comparator, luminosity, window), (name, row)
        assert row['size'] == row['height'] == 1, (name, row)
    assert phases['water']['held'] == WATER and phases['incompatible']['held'] == LAVA, phases
    assert phases['drain-water']['held'] == phases['drain-lava']['held'] == BUCKET, phases
    assert phases['survival-empty']['held'] == phases['survival-water']['held'] == BUCKET, phases
    assert phases['survival-water']['spill'] == 'minecraft:water', phases


def offset(pos, dx=0, dy=0, dz=0):
    return pos[0] + dx, pos[1] + dy, pos[2] + dz


def tank_parts(origin, width, height):
    return [offset(origin, x, y, z)
            for y in range(height) for x in range(width) for z in range(width)]


def part_snapshot(host, pos):
    tank = block(host, pos)
    assert tank['id'] == TANK, (pos, tank)
    nbt = tank['nbt']
    controller = re.search(r'\bController:\s*\[I;\s*(-?\d+),\s*(-?\d+),\s*(-?\d+)\]', nbt)
    known = re.search(r'\bLastKnownPos:\s*\[I;\s*(-?\d+),\s*(-?\d+),\s*(-?\d+)\]', nbt)
    assert known and tuple(map(int, known.groups())) == pos, (pos, tank)
    row = dict(state={key: value.lower() for key, value in tank['properties'].items() if key not in ('create_light', 'create_connections')},
               luminosity=int(number(tank, 'Luminosity')))
    if controller:
        assert not re.search(r'\b(?:TankContent|Window|Size|Height)\s*:', nbt), (pos, tank)
        row['controller'] = list(map(int, controller.groups()))
    else:
        content = field(nbt, 'TankContent')
        fluid = re.search(r'\bid\s*:\s*"([^"]+)"', content)
        row.update(fluid=fluid[1] if fluid else None, amount=int(number({'nbt': content}, 'amount', 0)),
                   window=int(number(tank, 'Window')), size=int(number(tank, 'Size')),
                   height=int(number(tank, 'Height')))
    return row


def parts_snapshot(host, expected):
    return {pos: part_snapshot(host, tuple(map(int, pos.split()))) for pos in expected}


def expected_tank(origin, width, height, amount=0, *, window=True, fluid='water'):
    rows = {}
    for pos in tank_parts(origin, width, height):
        x, y, z = (p - start for p, start in zip(pos, origin))
        shape = 'plain'
        if window:
            if width == 2:
                shape = f'window_{"s" if z else "n"}{"e" if x else "w"}'
            elif width == 1 or abs(x - z) == 1:
                shape = 'window'
        luminosity = 0
        if amount and fluid == 'lava':
            luminosity = 12 if y < int(amount / (8000 * width * width) + 1) else 1
        row = dict(state=dict(bottom=str(y == 0).lower(), top=str(y == height - 1).lower(),
                              shape=shape), luminosity=luminosity)
        if pos == origin:
            row.update(fluid=f'minecraft:{fluid}' if amount else None, amount=amount,
                       window=int(window), size=width, height=height)
        else:
            row['controller'] = list(origin)
        rows[xyz(pos)] = row
    return rows


def set_fluid(host, pos, amount, fluid='water'):
    host.command(f'data merge block {xyz(pos)} '
                 f'{{TankContent:{{Fluid:{{id:"minecraft:{fluid}",amount:{amount}}}}}}}')


def use_south(host, work, name, item, pos, *, attack=False):
    x, y, z = pos
    click(host, work, name, item, feet=(x + .5, 168, z + 2.65),
          aim=(x + .5, y + .75, z + 1), pos=pos, attack=attack)


def goggles_snapshot(host, work, name, pos, translations, *, floor_y=168):
    x, y, z = pos
    feet = (x + .5, floor_y, z + 2.65)
    aim = (x + .5, y + .75, z + 1)
    host.command('item replace entity @s armor.head with create:goggles')
    try:
        if isinstance(host, Native):
            session = host.session
            call = session.call
            host.command(f'tp @s {xyz(feet)}')
            call('look', 0, -80)
            call('wait', 5)
            start = session.log.stat().st_size
            call('look-at', *aim)
            overlay = wait_trace(call, session.log, 'Create visual: ',
                                 lambda row: row.get('event') == 'goggles_hud'
                                 and row.get('pos') == list(pos), start)
            call('screenshot', work / f'goggles-{name}.png')
        else:
            host.call('camera', {'position': feet, 'target': aim, 'hide_gui': False})
            host.call('capture', {'name': f'{work.name}/goggles-{name}.png', 'frames': 40})
            ui = host.call('ui', {})
            assert ui['hit']['pos'] == list(pos) and ui['goggles']['wearing'], ui
            overlay = ui['goggles']
        lines = overlay['lines']
        assert lines, overlay
        return [dict(text=line['text'], width=line['width'],
                     spans=component_spans(line['component'], translations)) for line in lines]
    finally:
        host.command('item replace entity @s armor.head with minecraft:air')


def goggles_translations():
    from basin_tooltip_reference import languages

    source = languages(java.BASE)['en_us']
    keys = ('block.minecraft.water', 'create.generic.unit.millibuckets',
            'create.gui.goggles.fluid_container', 'create.gui.goggles.fluid_container.capacity')
    return {key: source[key] for key in keys}


def multiblock_scenarios(host, work, goggles=None):
    cmd = host.command
    phases = {}

    def take(name, expected, *, wires=None):
        settle(host, 8)
        rows = parts_snapshot(host, expected)
        assert rows == expected, (name, rows, expected)
        phases[name] = dict(parts=rows)
        if wires is not None:
            actual = [int(block(host, pos)['properties']['power']) for pos in SQUARE_WIRES]
            assert actual == wires, (name, actual, wires)
            phases[name]['comparators'] = actual
        (work / 'multiblock-observed.json').write_text(json.dumps(phases, indent=2) + '\n')

    x, y, z = TOWER
    middle, top = offset(TOWER, dy=1), offset(TOWER, dy=2)
    put(cmd, TOWER, TANK)
    settle(host)
    click(host, work, 'tower-place', TANK, pos=TOWER, face='up',
          feet=(x + .5, y, z + 2.65), aim=(x + .5, y + 1, z + .5))
    take('tower-two', expected_tank(TOWER, 1, 2))
    put(cmd, top, TANK)
    take('tower-three', expected_tank(TOWER, 1, 3))
    set_fluid(host, TOWER, 16000)
    use_south(host, work, 'tower-pour-into-member', WATER, top)
    take('tower-member-pour', expected_tank(TOWER, 1, 3, 17000))
    put(cmd, middle, 'minecraft:air')
    take('tower-split-middle', expected_tank(TOWER, 1, 1, 8000) | expected_tank(top, 1, 1, 8000))
    put(cmd, middle, TANK)
    take('tower-rejoin', expected_tank(TOWER, 1, 3, 16000))
    put(cmd, TOWER, 'minecraft:air')
    take('tower-split-controller', expected_tank(middle, 1, 2, 16000))
    set_fluid(host, middle, 6000, 'lava')
    use_south(host, work, 'tower-lava-low', LAVA, top)
    take('tower-lava-below-layer', expected_tank(middle, 1, 2, 7000, fluid='lava'))
    use_south(host, work, 'tower-lava-threshold', LAVA, top)
    take('tower-lava-at-layer', expected_tank(middle, 1, 2, 8000, fluid='lava'))

    mixed_middle, mixed_top = offset(MIXED, dy=1), offset(MIXED, dy=2)
    for pos in (MIXED, mixed_top):
        put(cmd, pos, TANK)
    settle(host)
    set_fluid(host, MIXED, 1000)
    use_south(host, work, 'mixed-lava-in-separated-member', LAVA, mixed_top)
    put(cmd, mixed_middle, TANK)
    take('incompatible-merge', expected_tank(MIXED, 1, 1, 1000)
         | expected_tank(mixed_middle, 1, 2, 1000, fluid='lava'))

    square = tank_parts(SQUARE, 2, 1)
    for pos in square[:-1]:
        put(cmd, pos, TANK)
    take('square-partial', {key: row for pos in square[:-1]
                            for key, row in expected_tank(pos, 1, 1).items()})
    put(cmd, square[-1], TANK)
    for pos, facing in SQUARE_COMPARATORS:
        put(cmd, pos, f'minecraft:comparator[facing={facing}]')
    for pos in SQUARE_WIRES:
        put(cmd, pos, 'minecraft:redstone_wire')
    take('square-empty', expected_tank(SQUARE, 2, 1), wires=[0, 0])
    if goggles is not None:
        goggles['cases']['empty-member'] = goggles_snapshot(
            host, work, 'empty-member', square[-1], goggles['translations'])
    set_fluid(host, SQUARE, 30000)
    use_south(host, work, 'square-pour-into-member', LAVA, square[-1])
    take('square-incompatible-pour', expected_tank(SQUARE, 2, 1, 30000))
    use_south(host, work, 'square-pour-compatible', WATER, square[-1])
    take('square-member-pour', expected_tank(SQUARE, 2, 1, 31000), wires=[14, 14])
    if goggles is not None:
        goggles['cases']['filled-member'] = goggles_snapshot(
            host, work, 'filled-member', square[-1], goggles['translations'])
    use_south(host, work, 'square-member-wrench-hide', 'create:wrench', square[-1])
    take('square-windows-hidden', expected_tank(SQUARE, 2, 1, 31000, window=False), wires=[14, 14])
    use_south(host, work, 'square-member-wrench-show', 'create:wrench', square[-1])
    use_south(host, work, 'square-drain-from-member', BUCKET, square[-1])
    take('square-member-drain', expected_tank(SQUARE, 2, 1, 30000), wires=[14, 14])
    use_south(host, work, 'square-break-corner', 'minecraft:air', square[1], attack=True)
    take('square-split-corner', {key: row for pos in (square[0], *square[2:])
                                 for key, row in expected_tank(pos, 1, 1, 8000).items()}, wires=[15, 15])
    if goggles is not None:
        goggles['cases']['promoted-member'] = goggles_snapshot(
            host, work, 'promoted-member', square[-1], goggles['translations'])

    inner = tank_parts(WIDE, 2, 1)
    outer = [pos for pos in tank_parts(WIDE, 3, 1) if pos not in inner]
    for pos in inner + outer:
        put(cmd, pos, TANK)
    take('wide-cross-chunk', expected_tank(WIDE, 3, 1))
    use_south(host, work, 'wide-pour-into-member', WATER, offset(WIDE, dx=1, dz=2))
    take('wide-member-pour', expected_tank(WIDE, 3, 1, 1000))
    upper = tank_parts(offset(WIDE, dy=1), 3, 1)
    put(cmd, upper[0], TANK)
    take('wide-partial-layer', expected_tank(WIDE, 3, 1, 1000) | expected_tank(upper[0], 1, 1))
    for pos in upper[1:]:
        put(cmd, pos, TANK)
    take('wide-completed-layer', expected_tank(WIDE, 3, 2, 1000))
    return phases


def verify_multiblock_restart(host, phases):
    for phase in ('tower-lava-at-layer', 'incompatible-merge', 'square-split-corner', 'wide-completed-layer'):
        expected = phases[phase]['parts']
        observed = parts_snapshot(host, expected)
        assert observed == expected, (phase, observed, expected)


def original(work, cold, goggles):
    host = Original()
    assert json.loads((java.BASE / 'manifest.json').read_text())['create_sha256'] == java.CREATE_SHA256
    initial = host.call('state', {})
    assert initial['ready'] and initial['data_version'] == 3955, initial
    if goggles is not None and initial['language'] != 'en_us':
        host.call('language', {'language': 'en_us'})
    host.call('tick', {'frozen': True})
    try:
        host.command(f'forceload add {COLUMN}')
        settle(host, 20)
        phases = scenarios(host, work)
        multiblock = multiblock_scenarios(host, work, goggles)
        if cold:
            host.call('quit', {})
            deadline = time.monotonic() + 60
            while java.process_alive(java.BASE):
                if time.monotonic() >= deadline:
                    raise RuntimeError('The private Java client did not save and exit')
                time.sleep(.2)
            after = java.launch(java.BASE)
            assert after['ready'], after
            host.call('tick', {'frozen': True})
            settle(host, 8)
            assert snapshot(host) == phases['would-overflow']
            verify_multiblock_restart(host, multiblock)
        return phases, multiblock
    finally:
        host.command('gamemode creative')
        host.command('item replace entity @s weapon.mainhand with minecraft:air')
        host.command(f'fill {AREA} minecraft:air')
        host.command(f'forceload remove {COLUMN}')
        if goggles is not None:
            host.command(f'item replace entity @s armor.head with {initial["head"]}')
            if initial['language'] != 'en_us':
                host.call('language', {'language': initial['language']})
        host.call('camera', {'position': initial['position'], 'yaw': initial['yaw'], 'pitch': initial['pitch']})
        host.call('tick', {'frozen': initial['server']['frozen']})
        (work / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')


def verify_native_opaque_save(host, work):
    host.command(f'data merge block {xyz(POS)} {{Size:2,Controller:[I;2407,168,990],FutureData:{{keep:37}}}}')
    before = block(host, POS)
    for name, held in [('opaque-pour', WATER), ('opaque-extract', BUCKET), ('opaque-window', 'create:wrench')]:
        click(host, work, name, held)
        assert block(host, POS) == before, (name, before, block(host, POS))


def native_resources(session, jar):
    receipts = list((session.scratch / '.horizon-cache/create-assets/imports').glob('*/import.json'))
    if jar is None:
        assert not receipts, receipts
        bundle = session.scratch / 'horizon-mods/.create-native-content'
        content = ROOT / 'content'
        for name in ('block_single', 'block_single_window'):
            model = Path(f'assets/create/models/block/fluid_tank/{name}.json')
            assert (bundle / model).read_bytes() == (content / model).read_bytes(), model
        for name in ('fluid_tank', 'tank_glass'):
            texture = Path(f'assets/create/textures/block/fallback/{name}.png')
            assert (bundle / texture).read_bytes() == (content / texture).read_bytes(), texture
        return {'fallback': True}
    assert len(receipts) == 1, receipts
    pack = receipts[0].parent / 'pack'
    states = 'assets/create/blockstates/fluid_tank.json'
    paths = {states, 'assets/create/models/item/fluid_tank.json'}
    with ZipFile(jar) as archive:
        variants = json.loads(archive.read(states))['variants']
        models = {f'assets/create/models/{v["model"].removeprefix("create:")}.json' for v in variants.values()}
        paths.update(models)
        for model in models:
            for texture in json.loads(archive.read(model))['textures'].values():
                if texture.startswith('create:'):
                    paths.add('assets/create/textures/' + texture.removeprefix('create:') + '.png')
        for path in paths:
            assert (pack / path).read_bytes() == archive.read(path), path
    return {'original_files': sorted(paths)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--java', action='store_true')
    parser.add_argument('--cold', action='store_true', help='Also restart the private Java reference')
    parser.add_argument('--goggles', action='store_true', help='Compare original-asset HUD text on tank members')
    for flag in ('game', 'resources', 'ctl', 'reference', 'create-jar'):
        parser.add_argument('--' + flag, type=Path)
    args = parser.parse_args()
    report = dict(passed=True, create=PINS['create_revision'])
    goggles = None
    if args.java:
        work = Path(tempfile.mkdtemp(prefix='fluid-tank-java-', dir=ROOT / '.local'))
        print(work, flush=True)
        if args.goggles:
            goggles = dict(translations=goggles_translations(), cases={})
        phases, multiblock = original(work, args.cold, goggles)
        report['cold'] = args.cold
    else:
        if not all((args.game, args.resources, args.ctl, args.reference)):
            parser.error('Horizon requires --game, --resources, --ctl and --reference')
        reference = json.loads(args.reference.read_text())
        assert reference['passed'] and reference['create'] == PINS['create_revision'], reference
        if args.goggles:
            if args.create_jar is None:
                parser.error('--goggles requires --create-jar for the native client')
            goggles = dict(translations=reference['goggles']['translations'], cases={})
        session = NativeCheckSession(args.game, args.resources, args.ctl, args.create_jar,
                                     name='fluid-tank-native', world='CreateFluidTank')
        work = session.scratch
        print(work, flush=True)
        try:
            with session:
                session.call('options-set', 'chatVisibility', 2)
                session.call('options-set', 'tutorialStep', 'none')
                session.call('command', f'tp @s {xyz(FEET)}')
                wait_loaded(session.call, [POS, (2408, 168, 993), offset(WIDE, dx=2)])
                phases = scenarios(Native(session), work)
                multiblock = multiblock_scenarios(Native(session), work, goggles)
                report['assets'] = native_resources(session, args.create_jar)
                session.restart()
                wait_loaded(session.call, [POS, offset(WIDE, dx=2)])
                assert snapshot(Native(session)) == phases['would-overflow']
                verify_multiblock_restart(Native(session), multiblock)
                report['cold'] = True
                verify_native_opaque_save(Native(session), work)
                report['admission'] = ['opaque-save-preserved']
        finally:
            for folder in (session.resources, work / '.horizon-cache', work / 'horizon-mods'):
                shutil.rmtree(folder, ignore_errors=True)
        for phase, observed in phases.items():
            expected = reference['phases'][phase]
            assert observed == expected, (phase, observed, expected)
        assert multiblock == reference['multiblock'], (multiblock, reference['multiblock'])
        if goggles is not None:
            assert goggles == reference['goggles'], (goggles, reference['goggles'])
    verify(phases)
    if goggles is not None:
        report['goggles'] = goggles
    path = work / 'result.json'
    path.write_text(json.dumps(dict(report, phases=phases, multiblock=multiblock), indent=2) + '\n')
    print(path)


if __name__ == '__main__':
    main()
