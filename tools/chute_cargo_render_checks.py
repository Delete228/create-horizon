#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Check whether Chute cargo is drawn below an offscreen block entity."""

import argparse
import json
from pathlib import Path
import shutil
import tempfile
import time

from burner_heat_java_checks import number
from chain_drive_checks import Original, xyz
from common import PINS, ROOT
from contraption_cargo_light_checks import red_ends
from native_check_session import NativeCheckSession, wait_loaded
from reference_java import BASE, CREATE_SHA256


X, Y, Z = 1450, 190, 477
POS = (X, Y, Z)
AREA = (X-2, Y-6, Z-2, X+5, Y+3, Z+3)
# Keep the original Chute and Horizon's previous default render bounds
# above both camera frustums, with the stationary cargo still centered.
OFFSET = -2.875
FOV = 40
CAMERA = (X+1.45, Y+OFFSET-1.62, Z+.5)
TARGET = (X+.5, Y+OFFSET, Z+.5)
CASES = {'windowless_suction': ('normal', 3), 'windowless_without_air': ('normal', 0),
         'window_always_visible': ('window', 0)}


def seed(command, shape, distance, native):
    item = 'id:"minecraft:red_concrete",count:1'
    slot = f',Items:[{{Slot:0b,{item}}}]' if native else ''
    command(f'setblock {xyz(POS)} create:chute[facing=down,shape={shape}]')
    command(f'data merge block {xyz(POS)} '
            f'{{Item:{{{item}}},ItemPosition:{OFFSET}f,BottomAirFlowDistance:{distance}.0f{slot}}}')


def verify_state(block, distance):
    assert number(block, 'BottomAirFlowDistance') == distance, block
    assert number(block, 'ItemPosition') == OFFSET, block
    assert 'minecraft:red_concrete' in block['nbt'], block


def java_run(work):
    host = Original()
    initial = host.call('state', {})
    assert initial['ready'] and initial['data_version'] == 3955
    assert json.loads((BASE / 'manifest.json').read_text())['create_sha256'] == CREATE_SHA256
    mode = next(mode for mode in ('creative', 'spectator', 'survival', 'adventure')
                if any('Test passed' in line for line in
                       host.command(f'execute if entity @s[gamemode={mode}]')['messages']))
    images = {}
    try:
        host.command('gamemode spectator')
        host.call('camera', {'position': CAMERA, 'target': TARGET, 'fov': FOV, 'hide_gui': True})
        host.call('tick', {'frozen': False})
        for _ in range(40):
            result = host.command(f'execute if loaded {xyz(POS)}')
            if 'Test passed' in result['messages']:
                break
            time.sleep(.15)
        else:
            raise AssertionError('Chute render fixture column did not load')
        host.call('tick', {'frozen': True})
        host.command('fill ' + xyz(AREA) + ' minecraft:air')
        for name, (shape, distance) in CASES.items():
            seed(host.command, shape, distance, False)
            verify_state(host.call('block', {'pos': POS}), distance)
            photo = host.call('capture', {'frames': 12, 'name': f'{work.name}/{name}.png'})
            images[name] = work / f'{name}.png'
            shutil.copy2(photo['path'], images[name])
        return images
    finally:
        host.command('fill ' + xyz(AREA) + ' minecraft:air')
        # Let the original client receive the removal before its camera leaves
        # the chunk. Create's first Chute tick otherwise races the unload.
        host.call('observe_ticks', {'positions': [POS], 'ticks': 2})
        time.sleep(.35)
        host.command('gamemode ' + mode)
        host.call('camera', {k: initial[k] for k in ('position', 'yaw', 'pitch', 'fov')} | {'hide_gui': False})
        host.call('tick', {'frozen': initial['server']['frozen']})
        (work / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')


def native_run(session):
    images = {}
    with session:
        call = session.call

        def command(text):
            return call('command', text)

        command('gamemode spectator')
        command('tp @s ' + xyz(CAMERA))
        wait_loaded(call, [POS])
        command('tick freeze')
        command('fill ' + xyz(AREA) + ' minecraft:air')
        call('options-set', 'fov', FOV)
        call('look-at', *TARGET)
        call('key', 'f1', 'tap')
        for name, (shape, distance) in CASES.items():
            seed(command, shape, distance, True)
            verify_state({'nbt': ' '.join(command('data get block ' + xyz(POS))['chat'])}, distance)
            call('wait', 15)
            images[name] = session.scratch / f'{name}.png'
            call('screenshot', images[name])
    return images


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('game', 'resources', 'ctl', 'create-jar', 'reference'):
        parser.add_argument('--' + name, type=Path)
    args = parser.parse_args()
    if args.game:
        if not all((args.resources, args.ctl, args.create_jar, args.reference)):
            parser.error('Horizon requires --resources, --ctl, --create-jar and --reference')
        reference = json.loads(args.reference.read_text())
        assert reference['passed'] and reference['create'] == PINS['create_revision']
        session = NativeCheckSession(args.game, args.resources, args.ctl, args.create_jar,
                                     name='chute-cargo-render-native', world='ChuteCargoRender')
        session.env.pop('CREATE_HORIZON_PARTICLE_TRACE', None)
        work = session.scratch
        try:
            images = native_run(session)
        finally:
            for folder in (session.resources, work / '.horizon-cache', work / 'horizon-mods'):
                shutil.rmtree(folder, ignore_errors=True)
    else:
        work = Path(tempfile.mkdtemp(prefix='chute-cargo-render-java-', dir=ROOT / '.local'))
        images = java_run(work)
    reds = {name: max(red_ends(path)) for name, path in images.items()}
    visible = {name: value > 24 for name, value in reds.items()}
    expected = dict(windowless_suction=True, windowless_without_air=False, window_always_visible=True)
    passed = visible == expected and (not args.game or visible == reference['visible'])
    receipt = work / 'result.json'
    receipt.write_text(json.dumps(dict(passed=passed, create=PINS['create_revision'], visible=visible,
                                       red_signal=reds), indent=2) + '\n')
    print(receipt)
    assert passed, (reds, visible)


if __name__ == '__main__':
    main()
