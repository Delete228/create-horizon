#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Build and verify an isolated Create review world with the original JAR."""

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import shlex
import shutil

from burner_heat_java_checks import field, items, number
from chain_drive_checks import Native, xyz
from common import PINS
from fluid_pump_java_checks import amount, measure, seed
from fluid_pump_overlap_collision_checks import item_stacks
from funnel_checks import block
from mixer_particle_checks import tank as basin_segment
from native_check_session import NativeCheckSession, wait_loaded
from reference_java import CREATE_SHA256


WORLD = 'CreateParityReview09'
NAME = 'CreateReview'
FLOOR = 127
SPAWN = (23.5, 128, 28.5)
AIR = 'minecraft:air'
WATER = 'minecraft:water'
TANK = 'create:fluid_tank'
PIPE_X = 'create:fluid_pipe[east=true,west=true]'
PIPE_Z = 'create:fluid_pipe[north=true,south=true]'
PUMP = 'create:mechanical_pump[facing=east]'
DEPLOYER = (36, 131, 9)
PRESS = (42, 130, 9)
DEPOT = (42, 128, 9)
CHUTE = (39, 132, 23)
BELT = (38, 130, 23)
GANTRY = (19, 130, 23)
GANTRY_END = (23, 130, 23)
GANTRY_OUT = (21, 129, 26)
GANTRY_BANKS = (19, 130, 17)
PISTON = (33, 132, 23)
PISTON_OUT = (36, 133, 23)
PISTON_BANKS = (29, 132, 12)
ROPE = (12, 135, 22)
WET_IN = (44, 131, 24)
WET_OUT = (44, 128, 24)
SUCTION_DEPOT = (46, 128, 29)
DEPOT_CHUTE = (46, 130, 29)
TOWER = (4, 128, 4)
WIDE_TANK = (14, 128, 5)
SOURCE = (19, 129, 8)
TARGET = (27, 129, 8)
CAULDRON = (6, 129, 23)
ENDS = ((8, 129, 21), (8, 129, 25))
VALVE = (26, 129, 8)
BASIN = (44, 128, 16)
OVERLAP_TANKS = ((3, 129, 13), (7, 129, 15), (11, 129, 13))
COLLISION_TANKS = ((35, 130, 5), (39, 130, 7), (43, 130, 5))
COLLISION_JUNCTION = (39, 130, 5)
GAP = {
    'pump one': ((20, 129, 7), 'east', 32),
    'pump two': ((23, 129, 7), 'east', 64),
    'valve': ((26, 129, 6), 'south', 32),
    'side pump A': ((4, 129, 12), 'east', 64),
    'side pump B': ((8, 129, 12), 'east', 16),
    'mixed pump A': ((36, 129, 5), 'east', 16),
    'mixed pump B': ((40, 131, 5), 'east', 64),
    'cauldron pump': ((6, 129, 24), 'east', 32),
    'gantry': ((18, 129, 23), 'east', -32),
    'mixed gantry': ((18, 129, 17), 'east', -1),
    'piston': ((32, 132, 23), 'east', -32),
    'rope': ((13, 135, 22), 'west', 32),
    'mixed piston': ((28, 132, 12), 'east', -1),
    'chute fan': ((39, 134, 23), 'down', -128),
    'depot fan': ((46, 132, 29), 'down', -128),
    'deployer': ((35, 131, 9), 'east', 32),
    'press': ((41, 130, 9), 'east', 32),
    'mixer': ((43, 129, 16), 'up', 32),
}
CHEST = 'minecraft:chest[facing=north,type=single]'
CARRIAGE = 'create:gantry_carriage[facing=up]'
DOCK = 'create:portable_storage_interface'
CARGO = {'minecraft:wheat': 3, 'minecraft:stick': 2}


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


class Review:
    def __init__(self, session):
        self.session = session
        self.call = session.call
        self.host = Native(session)

    def command(self, value):
        reply = self.host.command(value)
        errors = ('not loaded', 'Unknown block', 'Unknown item', 'Unknown command', 'Incorrect argument')
        assert not any(error in message for error in errors for message in reply['chat']), (value, reply)
        return reply

    def put(self, pos, state):
        self.command(f'setblock {xyz(pos)} {state}')

    def fill(self, start, end, state):
        self.command(f'fill {xyz(start)} {xyz(end)} {state}')

    def get(self, pos):
        return block(self.host, pos)

    def sign(self, pos, *lines):
        self.put(pos, 'minecraft:oak_sign[rotation=0]')
        self.command(f'data merge block {xyz(pos)} {{front_text:{{messages:{json.dumps(lines)},'
                     'color:"black"},is_waxed:1b}')

    def tick(self, count):
        self.command(f'tick step {count}')
        self.call('wait', count + 3)

    def player(self, pos, aim):
        self.command(f'tp @s {xyz(pos)}')
        self.call('look-at', *aim)

    def stock(self, pos, slot, stack):
        self.command(f'item replace block {xyz(pos)} container.{slot} with {stack}')

    def size(self, pos):
        record = self.get(pos)
        return number(record, 'Size'), number(record, 'Height')

    def fluid(self, pos):
        return amount(measure(self.get(pos)))

    def start_verification_motors(self):
        for name, (pos, face, speed) in GAP.items():
            if name in ('mixed gantry', 'mixed piston'):
                # The review signs give players a slow menu-testing pass.
                speed = -32
            self.put(pos, f'create:creative_motor[facing={face}]{{ScrollValue:{speed}}}')

    def mark_motors(self):
        for name, (pos, face, speed) in GAP.items():
            x, y, z = pos
            self.put((x, FLOOR, z), 'minecraft:yellow_concrete')
            self.sign((x, 128, z+1), name.upper(), f'({x}, {y}, {z})', f'{face} / {speed} RPM')

    def prepare_floor(self):
        self.command('tick unfreeze')
        self.command('gamemode spectator')
        self.command('gamerule minecraft:spawn_mobs false')
        self.command('gamerule minecraft:random_tick_speed 0')
        self.command('time set noon')
        self.command('forceload add 0 0 47 31')
        for x in (0, 16, 32):
            for z in (0, 16):
                self.command(f'tp @s {x+8}.5 144 {z+8}.5')
                wait_loaded(self.call, [(x, 128, z), (x+15, 128, z+15)])
                self.fill((x, FLOOR, z), (x+15, FLOOR, z+15), 'minecraft:smooth_stone')
                self.fill((x, 128, z), (x+15, 140, z+15), AIR)
        self.command('kill @e[type=minecraft:item,x=0,y=128,z=0,dx=47,dy=24,dz=31]')
        self.command('tick freeze')

    def place_tanks(self):
        self.fill(TOWER, (4, 130, 4), TANK)
        self.fill(WIDE_TANK, (16, 129, 7), TANK)
        self.fill((4, 127, 9), (15, 127, 9), 'minecraft:polished_andesite')
        self.sign((4, 128, 7), '01 / WATER', 'Tower: 3 blocks', '15,000 / 24,000', 'Try the wrench')
        self.sign((15, 128, 8), '01 / LAVA', '3 x 3 x 2 tank', '84,000 / 144,000', 'Across chunk edge')

    def place_series(self):
        junction = 'create:fluid_pipe[east=true,west=true,south=true]'
        for x, state in enumerate((TANK, PIPE_X, PUMP, junction, PIPE_X, PUMP, PIPE_X,
                                   'create:fluid_valve[facing=up,axis_along_first=false,enabled=false]',
                                   TANK), 19):
            self.put((x, 129, 8), state)
        self.put((22, 129, 11), 'minecraft:stone')
        for z in (10, 9):
            self.put((22, 129, z), PIPE_Z)
        for x in (21, 24):
            self.put((x, 129, 7), 'create:cogwheel[axis=x]')
        self.put((26, 129, 7), 'create:gearshift[axis=z,powered=false]')
        self.sign((22, 128, 11), '02 / TWO PUMPS', '32 + 64 RPM', 'Open valve first', 'Wrench to reverse')

        for x, state in enumerate((TANK, PIPE_X, PUMP, PIPE_X, junction, PIPE_X, PUMP, PIPE_X, TANK), 3):
            self.put((x, 129, 13), state)
        self.put((7, 129, 14), PIPE_Z)
        self.put(OVERLAP_TANKS[1], TANK)
        for x in (5, 9):
            self.put((x, 129, 12), 'create:cogwheel[axis=x]')
        self.sign((7, 128, 17), '02B / SIDE TANK', '64 pushes / 16 pulls', 'Break the left motor', 'Watch the side tank')

    def place_collision(self):
        junction = 'create:fluid_pipe[east=true,west=true,south=true]'
        for x, state in enumerate((TANK, PIPE_X, PUMP, PIPE_X, junction, PIPE_X, PUMP, PIPE_X, TANK), 35):
            self.put((x, 130, 5), state)
        self.put((39, 130, 6), PIPE_Z)
        self.put(COLLISION_TANKS[1], TANK)
        self.put((37, 129, 5), 'create:cogwheel[axis=x]')
        self.put((41, 131, 5), 'create:cogwheel[axis=x]')
        self.sign((38, 128, 8), '02C / WATER + LAVA', 'Start both together', 'One pipe drops', 'See the checklist')

    def place_open(self):
        self.put(CAULDRON, 'minecraft:water_cauldron[level=3]')
        self.put((7, 129, 23), PUMP)
        self.put((8, 129, 23), 'create:fluid_pipe[west=true,north=true,south=true]')
        self.put((8, 129, 22), PIPE_Z)
        self.put((8, 129, 24), PIPE_Z)
        self.put((7, 129, 24), 'create:cogwheel[axis=x]')
        for x, y, z in ENDS:
            self.put((x, y-1, z), 'minecraft:glass')
            self.put((x, y+1, z), 'minecraft:sea_lantern')
            self.put((x-1, y, z), 'minecraft:glass')
            self.put((x+1, y, z), 'minecraft:glass')
            self.put((x, y, z + (-1 if z < 23 else 1)), 'minecraft:glass')
        self.sign((10, 128, 27), '03 / OPEN ENDS', 'One water cauldron', '500 mB each end', 'Try lava at one')

    def place_docks(self):
        self.fill((19, 129, 23), (23, 129, 23), 'create:gantry_shaft[facing=east]')
        self.put(GANTRY, CARRIAGE)
        self.put((19, 131, 23), 'minecraft:slime_block')
        self.put((19, 131, 24), f'{DOCK}[facing=south]')
        self.put((19, 131, 22), CHEST)
        self.stock((19, 131, 22), 5, 'minecraft:wheat 3')
        self.stock((19, 131, 22), 26, 'minecraft:stick[minecraft:custom_data={review_dock:153}] 2')
        self.put((21, 131, 26), f'{DOCK}[facing=north]')
        self.put((21, 130, 26), 'minecraft:hopper[facing=down]')
        self.put(GANTRY_OUT, CHEST)
        self.sign((22, 128, 28), '04 / GANTRY', 'Watch the dock', '3 wheat + 2 sticks', 'Then lands east')

        self.fill((19, 129, 17), (23, 129, 17), 'create:gantry_shaft[facing=east]')
        self.put(GANTRY_BANKS, CARRIAGE)
        self.put((19, 131, 17), 'minecraft:slime_block')
        self.put((19, 131, 16), CHEST)
        self.stock((19, 131, 16), 2, 'minecraft:iron_ingot[minecraft:custom_data={review_chest:31}] 3')
        self.put((19, 132, 17), 'minecraft:barrel[facing=east]')
        self.stock((19, 132, 17), 6, 'minecraft:iron_pickaxe[minecraft:damage=17]')
        self.sign((22, 128, 20), '04B / TWO BANKS', 'Chest and Barrel', 'Try at -1 RPM', 'Open while moving')

        self.put(PISTON, 'create:mechanical_piston[facing=up,axis_along_first=true]')
        self.fill((33, 128, 23), (33, 131, 23), 'create:piston_extension_pole[facing=up]')
        self.put((33, 133, 23), 'minecraft:slime_block')
        self.put((34, 133, 23), f'{DOCK}[facing=east]')
        self.put((32, 133, 23), CHEST)
        self.stock((32, 133, 23), 5, 'minecraft:wheat 3')
        self.stock((32, 133, 23), 26, 'minecraft:stick[minecraft:custom_data={review_dock:153}] 2')
        self.put((36, 135, 23), f'{DOCK}[facing=west]')
        self.put((36, 134, 23), 'minecraft:hopper[facing=down]')
        self.put(PISTON_OUT, CHEST)
        self.sign((33, 128, 27), '05 / PISTON', 'Watch the dock', '3 wheat + 2 sticks', 'Then lands up')

        self.put(ROPE, 'create:rope_pulley[axis=x]{Offset:5f}')
        self.fill((12, 131, 22), (12, 134, 22), 'create:rope[waterlogged=false]')
        self.put((12, 130, 22), 'create:pulley_magnet[waterlogged=false]')
        self.put((12, 129, 22), 'minecraft:slime_block')
        self.put((11, 129, 22), CHEST)
        self.stock((11, 129, 22), 0, 'minecraft:diamond 7')
        self.put((12, 129, 23), 'minecraft:barrel[facing=east]')
        self.stock((12, 129, 23), 3, 'minecraft:iron_ingot[minecraft:custom_data={review_rope:31}] 23')
        self.sign((12, 128, 25), '05B / ROPE', 'Two inventories', 'Lift both together', 'Stop to land')

        self.put(PISTON_BANKS, 'create:mechanical_piston[facing=up,axis_along_first=true]')
        self.fill((29, 128, 12), (29, 131, 12), 'create:piston_extension_pole[facing=up]')
        self.put((29, 133, 12), 'minecraft:slime_block')
        self.put((28, 133, 12), CHEST)
        self.stock((28, 133, 12), 0, 'minecraft:copper_ingot[minecraft:custom_data={review_piston:31}] 7')
        self.put((29, 133, 13), 'minecraft:barrel[facing=east]')
        self.stock((29, 133, 13), 3, 'minecraft:iron_pickaxe[minecraft:damage=17]')
        self.sign((30, 128, 15), '05C / TWO BANKS', 'Try at -1 RPM', 'Open either bank', 'Both land up')

    def place_workshop(self):
        self.put((39, 133, 23), 'create:encased_fan[facing=down]')
        self.put(CHUTE, 'create:chute[facing=down,shape=window]')
        for x, part in enumerate(('start', 'middle', 'middle', 'end'), 38):
            self.put((x, 130, 23), f'create:belt[facing=east,slope=horizontal,part={part}]')
        self.sign((40, 128, 26), '06 / CHUTE', 'Fan draws from', 'the stopped Belt', 'Watch the window')
        self.put(WET_IN, 'minecraft:hopper[facing=down]')
        self.put(WET_OUT, 'minecraft:barrel')
        self.fill((44, 129, 24), (44, 130, 24), 'create:chute[facing=down,shape=window,waterlogged=true]')
        self.sign((44, 128, 26), '06B / WET CHUTE', 'Fill top hopper', 'Two wet Chutes', 'Check the barrel')
        self.put(SUCTION_DEPOT, 'create:depot')
        self.put(DEPOT_CHUTE, 'create:chute[facing=down,shape=window]')
        self.put((46, 131, 29), 'create:encased_fan[facing=down]')
        self.command(f'data merge block {xyz(SUCTION_DEPOT)} '
                     '{HeldItem:{Item:{id:"minecraft:stick",count:23,components:{'
                     '"minecraft:custom_data":{review_depot_suction:23},"minecraft:enchantment_glint_override":true}},'
                     'Pos:.5f,PrevPos:.5f,InDirection:1},OutputBuffer:{Size:8,Items:[{Slot:0,id:"minecraft:iron_ingot",'
                     'count:4,components:{"minecraft:custom_data":{review_depot_buffer:4}}}]}}')
        self.sign((44, 128, 29), '06C / DEPOT', 'Lift 23 sticks', 'Across the gap', 'Iron stays below')
        self.put((36, 128, 9), 'minecraft:dirt')
        self.put(DEPLOYER, 'create:deployer[facing=down,axis_along_first=true]'
                 '{Mode:"USE",State:"WAITING",Timer:0,Inventory:[{Slot:0b,id:"minecraft:oak_sapling",count:3,'
                 'components:{"minecraft:custom_data":{review_sapling:734},"minecraft:enchantment_glint_override":true}}]}')
        self.sign((37, 128, 12), '07 / DEPLOYER', 'Marked saplings', 'Right click hand', 'Clear soil to repeat')
        self.put(PRESS, 'create:mechanical_press[facing=west]')
        self.put(DEPOT, 'create:depot')
        self.command(f'data merge block {xyz(DEPOT)} '
                     '{HeldItem:{Item:{id:"minecraft:copper_ingot",count:8},Pos:.25f,PrevPos:.25f,'
                     'Offset:0f,PrevOffset:0f,InSegment:0,Angle:0,InDirection:3}}')
        self.sign((42, 128, 12), '08 / PRESS', '8 copper ingots', 'Run at 32 RPM', 'Take sheets')
        self.put(BASIN, 'create:basin[facing=down]'
                 '{InputItems:{Size:9,Items:[{Slot:0,id:"create:wheat_flour",count:1}]},'
                 f'InputTanks:[{basin_segment("minecraft:water", 1000)},{basin_segment()}],'
                 f'OutputTanks:[{basin_segment("create:honey", 500)},{basin_segment()}]}}')
        self.put((44, 130, 16), 'create:mechanical_mixer')
        self.put((43, 130, 16), 'create:cogwheel[axis=y]')
        self.sign((44, 128, 19), '09 / MIXER', 'Water and honey', 'Watch the whisk', 'Makes dough')

    def build(self):
        self.prepare_floor()
        self.place_tanks()
        self.place_series()
        self.place_collision()
        self.place_open()
        self.place_docks()
        self.place_workshop()
        self.mark_motors()
        self.sign((23, 128, 27), 'CREATE REVIEW', '01-03: fluids', '04-06: transport', '07-09: workshop')
        self.tick(24)
        for pos, dims in ((TOWER, (1, 3)), (WIDE_TANK, (3, 2))):
            assert self.size(pos) == dims, (pos, self.get(pos))
        for pos, fluid, volume in ((TOWER, 'water', 15_000), (WIDE_TANK, 'lava', 84_000),
                                   (SOURCE, 'water', 8_000), (OVERLAP_TANKS[0], 'water', 8_000),
                                   (COLLISION_TANKS[0], 'water', 8_000), (COLLISION_TANKS[1], 'lava', 2_000)):
            self.command(seed(pos, fluid, volume))
        self.command(f'data merge block {xyz(BELT)} '
                     '{Inventory:{PositiveOrder:1b,Items:[{Item:{id:"minecraft:stick",count:7,'
                     'components:{"minecraft:custom_data":{review_chute:1}}},Pos:1.5f,'
                     'PrevPos:1.5f,InSegment:1,InDirection:5,Angle:180}]}}')
        self.tick(2)
        self.command('gamemode creative')
        self.command('item replace entity @s armor.head with create:goggles')
        for slot, item in enumerate(('create:wrench', 'create:creative_motor 16', 'minecraft:water_bucket',
                                     'minecraft:bucket', 'create:fluid_tank 64', 'create:fluid_pipe 64',
                                     'create:super_glue', 'minecraft:copper_ingot 16')):
            self.command(f'item replace entity @s hotbar.{slot} with {item}')
        self.command(f'spawnpoint @s {int(SPAWN[0])} {int(SPAWN[1])} {int(SPAWN[2])}')
        self.player(SPAWN, (23.5, 128.8, 25))
        self.tick(4)

    def initial(self):
        volumes = {name: self.fluid(pos) for name, pos in
                   (('tower', TOWER), ('wide', WIDE_TANK), ('source', SOURCE), ('target', TARGET))}
        assert volumes == dict(tower=15_000, wide=84_000, source=8000, target=0), volumes
        assert [self.fluid(pos) for pos in OVERLAP_TANKS] == [8_000, 0, 0]
        assert [measure(self.get(pos))['tank'] for pos in COLLISION_TANKS] == [
            dict(id=WATER, amount=8_000), dict(id='minecraft:lava', amount=2_000), None]
        assert self.get(COLLISION_JUNCTION)['id'] == 'create:fluid_pipe'
        assert self.get(GANTRY)['id'] == 'create:gantry_carriage'
        assert self.get(PISTON)['id'] == 'create:mechanical_piston'
        assert items(self.get(BELT)['nbt'], 'Inventory') == {'minecraft:stick': 7}
        self.check_depot_suction(False)
        assert all(self.get(pos)['id'] == AIR for pos, _, _ in GAP.values())
        return volumes

    def check_depot_suction(self, transferred):
        depot = self.get(SUCTION_DEPOT)
        chute = self.get(DEPOT_CHUTE)
        assert depot['id'] == 'create:depot' and chute['id'] == 'create:chute', (depot, chute)
        depot_nbt, chute_nbt = depot['nbt'], chute['nbt']
        held = items(depot_nbt, 'HeldItem') if 'HeldItem:' in depot_nbt else {}
        buffer = items(depot_nbt, 'OutputBuffer')
        cargo = items(chute_nbt, 'Item')
        expected = {'minecraft:stick': 23}
        assert buffer == {'minecraft:iron_ingot': 4} and number(depot, 'review_depot_buffer') == 4, depot
        if transferred:
            assert held == {} and cargo == expected and number(chute, 'review_depot_suction') == 23, (depot, chute)
            assert number(chute, 'ItemPosition') == .5, chute
        else:
            assert held == expected and cargo == {} and number(depot, 'review_depot_suction') == 23, (depot, chute)
        return dict(held=held, buffer=buffer, chute=cargo)

    def verify(self):
        initial = self.initial()
        self.start_verification_motors()
        self.stock(WET_IN, 0, 'minecraft:wheat[minecraft:custom_data={review_wet:17}] 7')
        self.command('tick unfreeze')
        self.call('wait', 42)
        self.command('tick freeze')
        assert self.get(VALVE)['properties']['enabled'] == 'true', self.get(VALVE)
        self.check_depot_suction(True)
        gantry = self.get((21, 131, 26))
        assert 4 < number(gantry, 'Timer', 0) <= 64, gantry
        original_pid = self.session.process.pid
        self.session.restart()
        assert self.session.process.pid != original_pid
        wait_loaded(self.call, (TOWER, WIDE_TANK, SOURCE, TARGET, CHUTE, DEPOT_CHUTE, GANTRY, PISTON))
        self.command('tick unfreeze')
        self.call('wait', 475)
        self.command('tick freeze')
        volumes = [self.fluid(SOURCE), self.fluid(TARGET)]
        assert sum(volumes) == 8_000 and volumes[1] > 0, volumes
        overlap = [self.fluid(pos) for pos in OVERLAP_TANKS]
        assert sum(overlap) == 8_000 and overlap[1] > 0 and overlap[2] > 0, overlap
        collision = self.get(COLLISION_JUNCTION)['id']
        assert collision == 'minecraft:cobblestone', collision
        collision_tanks = [measure(self.get(pos))['tank'] for pos in COLLISION_TANKS]
        assert collision_tanks == [dict(id=WATER, amount=8_000), dict(id='minecraft:lava', amount=1_910),
                                   dict(id='minecraft:lava', amount=90)], collision_tanks
        drops = self.command('execute as @e[type=minecraft:item,x=34,y=128,z=2,dx=10,dy=6,dz=6] '
                             'run data get entity @s Item')
        collision_drops = item_stacks(' '.join(drops['chat']))
        assert collision_drops == [['create:fluid_pipe', 1]], collision_drops
        cauldron = self.get(CAULDRON)
        assert cauldron['id'] == 'minecraft:cauldron', cauldron
        open_buffers = [number({'nbt': field(field(self.get(pos)['nbt'], side), 'OpenEnd')}, 'amount')
                        for pos, side in (((8, 129, 22), 'north'), ((8, 129, 24), 'south'))]
        assert open_buffers == [500, 500], open_buffers
        for pos in (GANTRY_OUT, PISTON_OUT):
            nbt = self.get(pos)['nbt']
            assert items(nbt, 'Items') == CARGO and 'review_dock:153' in nbt.replace(' ', ''), nbt
        assert self.get(GANTRY_END)['id'] == 'create:gantry_carriage'
        chest = self.get((23, 131, 16))
        barrel = self.get((23, 132, 17))
        assert chest['properties']['facing'] == 'north' and 'review_chest:31' in chest['nbt'].replace(' ', '')
        assert barrel['properties']['facing'] == 'east' and '"minecraft:damage":17' in barrel['nbt'].replace(' ', '')
        assert self.get((32, 137, 23))['id'] == 'minecraft:chest'
        assert items(self.get((11, 134, 22))['nbt'], 'Items') == {'minecraft:diamond': 7}
        rope_barrel = self.get((12, 134, 23))['nbt']
        assert items(rope_barrel, 'Items') == {'minecraft:iron_ingot': 23}
        assert 'review_rope:31' in rope_barrel.replace(' ', '')
        piston_chest = self.get((28, 137, 12))['nbt']
        piston_barrel = self.get((29, 137, 13))['nbt']
        assert 'review_piston:31' in piston_chest.replace(' ', '')
        assert '"minecraft:damage":17' in piston_barrel.replace(' ', '')
        assert self.get((36, 129, 9))['id'] == 'minecraft:oak_sapling'
        deployer = self.get(DEPLOYER)['nbt']
        assert items(deployer, 'HeldItem') == {'minecraft:oak_sapling': 2}, deployer
        assert 'review_sapling:734' in field(deployer, 'HeldItem').replace(' ', ''), deployer
        depot = self.get(DEPOT)['nbt']
        sheets = Counter(items(depot, 'HeldItem')) + Counter(items(depot, 'OutputBuffer'))
        assert sheets == {'create:copper_sheet': 8}, depot
        assert items(self.get(BASIN)['nbt'], 'OutputItems') == {'create:dough': 1}
        assert not items(self.get(BELT)['nbt'], 'Inventory'), self.get(BELT)
        wet = self.get(WET_OUT)['nbt']
        assert items(wet, 'Items') == {'minecraft:wheat': 7} and 'review_wet:17' in wet.replace(' ', '')
        assert all(self.get((44, y, 24))['properties']['waterlogged'] == 'true' for y in (129, 130))
        depot_suction = self.check_depot_suction(True)
        return dict(initial=initial, series=volumes, side_tank_series=overlap,
                    mixed_pump_collision=dict(junction=collision, tanks=collision_tanks, drops=collision_drops),
                    outlet_buffers=open_buffers, dock_cargo=CARGO,
                    deployer='planted with two marked saplings remaining', press='eight sheets',
                    chute='seven items removed from the stopped Belt', mixer='one dough',
                    depot_suction=depot_suction,
                    mixed_gantry='separate chest and barrel retain their components',
                    mixed_rope='both inventories and components landed', wet_chute='seven marked wheat',
                    mixed_piston='both inventories and components landed',
                    restart=True)

    def captures(self, work):
        cameras = {
            'overview': ((23.5, 152, 28.5), (23.5, 128, 15.5)),
            'fluids': ((17.5, 134, 15.5), (17.5, 129, 7)),
            'side-tank': ((7.5, 134, 19.5), (7.5, 129, 13.5)),
            'pump-collision': ((38.5, 135, 10.5), (39.5, 130, 5.5)),
            'moving-docks': ((27.5, 137, 30.5), (27.5, 131, 23)),
            'workshop': ((39.5, 135, 16), (39.5, 130, 9)),
        }
        self.call('key', 'f1', 'tap')
        for name, (pos, aim) in cameras.items():
            self.player(pos, aim)
            self.call('wait', 8)
            self.call('screenshot', work / f'{name}.png')
        self.call('key', 'f1', 'tap')
        return [f'{name}.png' for name in cameras]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in ('game', 'resources', 'ctl', 'create-jar'):
        parser.add_argument('--' + flag, type=Path, required=True)
    args = parser.parse_args()
    if sha(args.create_jar) != CREATE_SHA256:
        parser.error('the private resource input must be the pinned Create 6.0.10 JAR')

    session = NativeCheckSession(args.game, args.resources, args.ctl, args.create_jar,
                                 name='parity-review09', world=WORLD, username=NAME,
                                 size=(1440, 900))
    session.env.update(HORIZON_API_DISCOVERY='http://127.0.0.1:9/', HORIZON_NO_DISCORD='1')
    work = session.scratch
    print(work, flush=True)
    try:
        with session:
            review = Review(session)
            review.build()
            result = review.verify()
            review.build()
            review.initial()
            images = review.captures(work)
            review.player(SPAWN, (23.5, 128.8, 25))
            review.command('tick unfreeze')
            review.command('save-all flush')
            session.restart()
            wait_loaded(session.call, (TOWER, WIDE_TANK, SOURCE, TARGET, CHUTE, DEPOT_CHUTE, GANTRY, PISTON))
            review.initial()
        assert 'local resources from Create 6.0.10' in session.log.read_text()
    except BaseException:
        for folder in (session.resources, work / '.horizon-cache', work / 'horizon-mods'):
            shutil.rmtree(folder, ignore_errors=True)
        raise

    play = work / 'Play.command'
    base_resources = shlex.quote(str(args.resources.resolve()))
    play.write_text('#!/bin/bash\nset -euo pipefail\ncd "$(dirname "$0")"\n'
                    'export HORIZON_HOME="$PWD/home" HORIZON_LAUNCHER_HOME="$PWD/launcher"\n'
                    'export HORIZON_LAUNCHER_NO_SELF_UPDATE=1 HORIZON_NO_DISCORD=1\n'
                    'export XDG_CONFIG_HOME="$PWD/config" XDG_DATA_HOME="$PWD/data"\n'
                    f'exec {shlex.quote(str(session.game))} --resources {base_resources} '
                    f'--world {WORLD} --creative --name {NAME} --render-distance 4 "$@"\n')
    play.chmod(0o755)
    shutil.copyfile(Path(__file__).resolve().parents[1] / 'docs/reviews/0.9-parity-world.md',
                    work / 'CHECKLIST.md')
    shutil.rmtree(session.resources)
    (work / 'result.json').write_text(json.dumps(dict(passed=True, horizon=PINS['horizon_revision'],
        create=PINS['create_revision'], executable_sha256=sha(session.game), verification=result,
        delivery_restart=True, images=images), indent=2) + '\n')
    print(work / 'result.json', flush=True)


if __name__ == '__main__':
    main()
