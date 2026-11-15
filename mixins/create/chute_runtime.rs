// Copyright (c) The Create Team / The Creators of Create
// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT

use super::{
    Game, GameLevel,
    create_port_motor_value_world::{FilterDisplay, FilterLabel},
    native_block_entity_draw::BlockEntityDraw,
};
use crate::{
    containers::{BlockEntity, ModBlockEntity, ModContainer},
    items::{ItemStack, Items},
};
use create_engine::{
    chute::{self, ENTRY, Source, Step},
    kinetics::Pos,
};
use horizon_core::geometry::Direction;
use horizon_items::item_nbt::{item_from_nbt, item_to_nbt};
use horizon_world::{
    attachments::{AttachmentType, Holder},
    chunk::BlockState,
    level::{PlacementContext, flags},
    nbt::{Compound, Tag},
    registry::BlockStateId,
};
use std::{cell::RefCell, collections::HashMap, sync::OnceLock};

pub(super) const BLOCK: &str = "create:chute";
pub(super) const SMART: &str = "create:smart_chute";
const CASING: &str = "create:industrial_iron_block";
const DRAW_PREVIOUS: &str = "create:ChutePreviousPosition";
const HORIZONTAL: [Direction; 4] = [
    Direction::North,
    Direction::South,
    Direction::West,
    Direction::East,
];
const DIRECTION_NAMES: [&str; 6] = ["down", "up", "north", "south", "west", "east"];

const PREVIOUS: AttachmentType<f32> = AttachmentType {
    namespace: "create",
    name: "chute_previous_position",
    default: || 0.0,
    codec: None,
    copy_on_death: false,
    sync: false,
};

#[derive(Clone, Copy, PartialEq, Eq)]
struct Topology {
    inlet_sides: u8,
    vertical_above: bool,
    outlet_present: bool,
}

const TOPOLOGY: AttachmentType<Option<Topology>> = AttachmentType {
    namespace: "create",
    name: "chute_topology",
    default: || None,
    codec: None,
    copy_on_death: false,
    sync: false,
};

#[derive(Default)]
struct LiftCache {
    world: usize,
    dimension: String,
    tick: i64,
    air: HashMap<Pos, Option<Lift>>,
}
thread_local! { static LIFTS: RefCell<LiftCache> = RefCell::new(LiftCache::default()); }

#[derive(Clone, Copy, Default, PartialEq)]
struct Lift {
    push: f32,
    pull: f32,
}

impl Lift {
    fn read(entity: &ModBlockEntity) -> Self {
        Self {
            push: super::create_port::number(&entity.nbt, "Push"),
            pull: super::create_port::number(&entity.nbt, "Pull"),
        }
    }

    fn write(self, entity: &mut ModBlockEntity) {
        entity
            .nbt
            .insert("Push".into(), Tag::Float(self.push.to_bits()));
        entity
            .nbt
            .insert("Pull".into(), Tag::Float(self.pull.to_bits()));
    }

    fn motion(self) -> f32 {
        chute::motion(self.push, self.pull)
    }
}

#[derive(Clone, Copy, Default)]
struct SuctionTiming {
    air: Lift,
    below: Option<BlockStateId>,
    transport: Option<SuctionSource>,
    block_check: i32,
    entity_search: i32,
}

#[derive(Clone, Copy)]
enum SuctionSource {
    Belt(Pos),
    Depot(Pos),
}

const SUCTION_TIMING: AttachmentType<SuctionTiming> = AttachmentType {
    namespace: "create",
    name: "chute_suction_timing",
    default: SuctionTiming::default,
    codec: None,
    copy_on_death: false,
    sync: false,
};

pub(super) fn default_nbt() -> Compound {
    Compound::from([
        ("Item".into(), Tag::Compound(Compound::new())),
        ("ItemPosition".into(), Tag::Float(0)),
        ("Pull".into(), Tag::Float(0)),
        ("Push".into(), Tag::Float(0)),
        ("BottomAirFlowDistance".into(), Tag::Float(0)),
    ])
}

pub(super) fn smart_nbt() -> Compound {
    let mut nbt = default_nbt();
    nbt.insert("Filter".into(), Tag::Compound(Compound::new()));
    nbt.insert("FilterAmount".into(), Tag::Int(64));
    nbt.insert("UpTo".into(), Tag::Byte(1));
    nbt
}

pub(super) fn is_chute(block: &str) -> bool {
    matches!(block, BLOCK | SMART)
}

pub(super) fn container() -> ModContainer {
    ModContainer {
        slots: 1,
        faces: std::array::from_fn(|_| vec![0]),
        inputs: vec![0],
        outputs: vec![0],
        menu: None,
    }
}

fn direction(state: &BlockState) -> Option<Direction> {
    match state.name.as_str() {
        SMART => Some(Direction::Down),
        BLOCK => {
            let name = state.properties.get("facing")?;
            Direction::ALL
                .into_iter()
                .find(|face| DIRECTION_NAMES[*face as usize] == name)
        }
        _ => None,
    }
}

fn offset([x, y, z]: Pos, direction: Direction, height: i32) -> Pos {
    let [dx, _, dz] = direction.normal();
    [x + dx, y + height, z + dz]
}

fn topology<'a>(
    pos: Pos,
    face: Direction,
    read: impl Fn(Pos) -> Option<&'a BlockState>,
) -> Option<Topology> {
    let outlet_present =
        face == Direction::Down || is_chute(&read(offset(pos, face.opposite(), -1))?.name);
    let mut inlet_sides = 0;
    for (index, side) in HORIZONTAL.into_iter().enumerate() {
        if direction(read(offset(pos, side, 1))?) == Some(side) {
            inlet_sides |= 1 << index;
        }
    }
    let above = read(offset(pos, Direction::Up, 1))?;
    let vertical_above = direction(above) == Some(Direction::Down)
        || (funnel::is_funnel(&above.name)
            && above.properties.get("facing").is_some_and(|v| v == "down"));
    Some(Topology {
        inlet_sides,
        vertical_above,
        outlet_present,
    })
}

fn shape_for(face: Direction, old_shape: &str, topology: Topology) -> (Direction, &'static str) {
    if !topology.outlet_present {
        return (Direction::Down, "normal");
    }
    let shape = if face == Direction::Down {
        if topology.inlet_sides == 0 {
            match old_shape {
                "window" => "window",
                "encased" => "encased",
                _ => "normal",
            }
        } else {
            "intersection"
        }
    } else {
        let inlet = HORIZONTAL.iter().position(|&side| side == face);
        if inlet.is_some_and(|side| topology.inlet_sides == 1 << side) && !topology.vertical_above {
            if old_shape == "encased" {
                "encased"
            } else {
                "normal"
            }
        } else {
            "intersection"
        }
    };
    (face, shape)
}

pub(super) fn placement(
    game: &GameLevel<'_>,
    state: BlockStateId,
    ctx: &PlacementContext,
) -> Option<BlockStateId> {
    let pos = [ctx.pos.x, ctx.pos.y, ctx.pos.z];
    let read = |[x, y, z]: Pos| {
        game.registry
            .state(game.world.block(x, y, z))
            .filter(|_| game.world.loaded(x, z))
    };
    if read(offset(pos, Direction::Up, 1))
        .and_then(direction)
        .is_some_and(|face| face != Direction::Down)
    {
        return None;
    }
    let face = if HORIZONTAL.contains(&ctx.face) && !ctx.sneaking {
        ctx.face
    } else {
        Direction::Down
    };
    let (face, shape) = topology(pos, face, read).map_or((face, "normal"), |neighbors| {
        shape_for(face, "normal", neighbors)
    });
    let state = game.native_state_with_property(state, "facing", DIRECTION_NAMES[face as usize])?;
    game.native_state_with_property(state, "shape", shape)
}

pub(super) fn placed(game: &mut Game<'_>, [x, y, z]: Pos) {
    let registry = game.pack.assets.registry;
    let Some(face) = registry
        .state(game.world.block(x, y, z))
        .and_then(direction)
    else {
        return;
    };
    let [tx, ty, tz] = offset([x, y, z], face.opposite(), -1);
    if game.native_block([tx, ty, tz]) == BLOCK
        && let Some(map) = game.world.block_entities.attachments_mut((tx, ty, tz))
    {
        // Placement schedules the destination even before its first ticker.
        let _ = map.set(&TOPOLOGY, None);
    }
}

fn update_shape(game: &mut Game<'_>, pos: Pos) -> Option<Direction> {
    let registry = game.pack.assets.registry;
    let [x, y, z] = pos;
    let state = game.world.block(x, y, z);
    let block = registry.state(state)?;
    let face = direction(block)?;
    if block.name != BLOCK {
        return Some(face);
    }
    let read = |[x, y, z]: Pos| {
        registry
            .state(game.world.block(x, y, z))
            .filter(|_| game.world.loaded(x, z))
    };
    let Some(neighbors) = topology(pos, face, read) else {
        return Some(face);
    };
    let (facing, shape) = shape_for(face, block.properties.get("shape")?, neighbors);
    let settled = if face == facing {
        neighbors
    } else {
        topology(pos, facing, read)?
    };
    let changed = game
        .world
        .block_entities
        .attachments_mut((x, y, z))
        .is_some_and(|map| {
            let old = map.get_existing(&TOPOLOGY).ok().flatten();
            if old != Some(Some(settled)) {
                let _ = map.set(&TOPOLOGY, Some(settled));
            }
            old.is_some_and(|old| old != Some(neighbors))
        });
    // Java recomputes on neighbor events. On load, an existing shape is
    // authoritative until a neighbor changes, including a detached chute
    // that just became a vertical normal chute with an inlet still above.
    if !changed && neighbors.outlet_present {
        return Some(face);
    }
    if face == facing
        && block
            .properties
            .get("shape")
            .is_some_and(|current| current == shape)
    {
        return Some(face);
    }
    let mut next = block.clone();
    next.properties
        .insert("facing".into(), DIRECTION_NAMES[facing as usize].into());
    next.properties.insert("shape".into(), shape.into());
    let next = registry.id(&next)?;
    if next != state && !game.native_set_block(game.dim.id(), pos, next, flags::UPDATE_ALL) {
        return Some(face);
    }
    Some(facing)
}

fn empty(entity: &ModBlockEntity) -> bool {
    entity
        .items
        .first()
        .is_none_or(|slot| slot.as_ref().is_none_or(|stack| stack.count == 0))
}

fn still_air(entity: &ModBlockEntity) -> bool {
    Lift::read(entity) == Lift::default()
}

pub(super) fn visual_air(entity: &ModBlockEntity) -> Option<(f32, f32)> {
    let air = Lift::read(entity);
    let motion = air.motion();
    let distance = super::create_port::number(&entity.nbt, "BottomAirFlowDistance");
    (air != Lift::default() && motion.is_finite() && distance.is_finite())
        .then_some((motion, distance))
}

// Java checks the block directly above, then walks North, South, West, East
// and looks back toward the parent from each diagonal above it.
fn input_candidates(pos: Pos) -> [(Pos, Direction); 5] {
    let [north, south, west, east] = HORIZONTAL;
    [
        Direction::Down,
        north.opposite(),
        south.opposite(),
        west.opposite(),
        east.opposite(),
    ]
    .map(|face| (offset(pos, face, 1), face))
}

fn loaded_state<'a>(game: &'a Game<'_>, [x, y, z]: Pos) -> Option<&'a BlockState> {
    game.world.loaded(x, z).then_some(())?;
    game.pack.assets.registry.state(game.world.block(x, y, z))
}

fn ordinary_facing(state: &BlockState) -> Option<Direction> {
    if state.name != BLOCK {
        return None;
    }
    direction(state)
}

fn is_fan(state: &BlockState, facing: Direction) -> bool {
    state.name == "create:encased_fan"
        && state
            .properties
            .get("facing")
            .is_some_and(|value| value == DIRECTION_NAMES[facing as usize])
}

/// One ordinary network with one end Fan. A bottom Fan can feed a single
/// angled edge and fork, while a top Fan is restricted to a straight run.
fn lift_run(game: &Game<'_>, seed: Pos) -> Option<(Vec<(Pos, f32)>, Lift)> {
    let mut root = seed;
    let below = loop {
        let facing = ordinary_facing(loaded_state(game, root)?)?;
        let target = offset(root, facing.opposite(), -1);
        let state = loaded_state(game, target)?;
        if !is_chute(&state.name) {
            if facing != Direction::Down {
                return None;
            }
            break target;
        }
        root = target;
    };
    let bottom = is_fan(loaded_state(game, below)?, Direction::Up).then_some(below);
    let mut top = None;
    let mut angled = false;
    let mut run = vec![(root, 1.0)];
    let mut current = 0;
    while let Some(&(pos, share)) = run.get(current) {
        current += 1;
        if pos != root
            && is_fan(
                loaded_state(game, offset(pos, Direction::Down, -1))?,
                Direction::Up,
            )
        {
            return None;
        }
        let above = offset(pos, Direction::Up, 1);
        if is_fan(loaded_state(game, above)?, Direction::Down) {
            if bottom.is_some() || top.replace(above).is_some() {
                return None;
            }
        }

        let start = run.len();
        for (child, facing) in input_candidates(pos) {
            let state = loaded_state(game, child)?;
            if direction(state) != Some(facing) {
                continue;
            }
            ordinary_facing(state)?;
            if facing != Direction::Down {
                if angled || bottom.is_none() {
                    return None;
                }
                angled = true;
            }
            run.push((child, share));
        }
        if run.len() - start == 2 {
            // Java gives each input the parent's push divided by the number of inputs.
            run[start..].iter_mut().for_each(|(_, share)| *share /= 2.0);
        }
    }

    let speed = |p: Pos| match game.world.block_entities.get(&(p[0], p[1], p[2])) {
        Some(BlockEntity::Mod(entity)) if entity.id == "create:encased_fan" => {
            super::create_port::running_speed(game, &entity.nbt)
        }
        _ => 0.0,
    };
    let air = Lift {
        push: bottom.map_or(0.0, speed),
        pull: top.map_or(0.0, speed),
    };
    (air.push.is_finite() && air.pull.is_finite()).then_some((run, air))
}

fn cache_lifts(game: &Game<'_>, seed: Pos, changed_fan: Option<(Direction, f32)>) -> Option<Lift> {
    LIFTS.with(|cache| {
        let mut cache = cache.borrow_mut();
        let world = std::ptr::from_ref(&game.world) as usize;
        if cache.world != world
            || cache.dimension != game.dim.id()
            || cache.tick != game.world.game_time
        {
            cache.world = world;
            game.dim.id().clone_into(&mut cache.dimension);
            cache.tick = game.world.game_time;
            cache.air.clear();
        }
        if changed_fan.is_none()
            && let Some(air) = cache.air.get(&seed)
        {
            return *air;
        }
        let Some((run, mut air)) = lift_run(game, seed) else {
            cache.air.insert(seed, None);
            return None;
        };
        if let Some((facing, speed)) = changed_fan {
            match facing {
                Direction::Up => air.push = speed,
                Direction::Down => air.pull = speed,
                _ => return None,
            }
        }
        cache.air.extend(run.into_iter().map(|(pos, share)| {
            (
                pos,
                Some(Lift {
                    push: air.push * share,
                    pull: air.pull,
                }),
            )
        }));
        cache.air.get(&seed).copied().flatten()
    })
}

fn lift_air(game: &Game<'_>, pos: Pos) -> Option<Lift> {
    cache_lifts(game, pos, None)
}

/// EncasedFanBlockEntity.onSpeedChanged updates nearby Chute data immediately,
/// even when those Chutes have already taken their item movement turn.
pub(super) fn publish_fan_air(game: &mut Game<'_>, fan: Pos, speed: f32) {
    if !speed.is_finite() {
        return;
    }
    let facing = match game.native_block_property(fan, "facing").as_deref() {
        Some("up") => Direction::Up,
        Some("down") => Direction::Down,
        _ => return,
    };
    let seed = offset(fan, facing, facing.normal()[1]);
    if cache_lifts(game, seed, Some((facing, speed))).is_none() {
        return;
    }
    let mut pending = vec![seed];
    while let Some(pos) = pending.pop() {
        let Some(air) = lift_air(game, pos) else {
            continue;
        };
        let changed = entity_at(game, pos).is_some_and(|entity| Lift::read(entity) != air);
        if changed {
            game.native_with_mod_block_entity(pos, |entity| air.write(entity));
            game.native_block_entity_sync(pos);
        }
        if facing == Direction::Up {
            pending.extend(
                input_candidates(pos)
                    .into_iter()
                    .filter_map(|(child, face)| {
                        (loaded_state(game, child).and_then(ordinary_facing) == Some(face))
                            .then_some(child)
                    }),
            );
        } else {
            let below = offset(pos, Direction::Down, -1);
            if loaded_state(game, below).and_then(ordinary_facing) == Some(Direction::Down) {
                pending.push(below);
            }
        }
    }
}

fn entry_position(game: &Game<'_>, pos: Pos) -> f32 {
    if lift_air(game, pos).is_some_and(|air| air.motion() > 0.0) {
        0.0
    } else {
        ENTRY
    }
}

fn set_position(entity: &mut ModBlockEntity, value: f32) {
    entity
        .nbt
        .insert("ItemPosition".into(), Tag::Float(value.to_bits()));
}

fn item_data(entity: &ModBlockEntity) -> Tag {
    entity
        .items
        .first()
        .and_then(Option::as_ref)
        .filter(|stack| stack.count > 0)
        .map_or_else(|| Tag::Compound(Compound::new()), item_to_nbt)
}

fn set_item(entity: &mut ModBlockEntity, stack: Option<ItemStack>, position: f32) {
    entity.clear_client_update_fields();
    if entity.items.is_empty() {
        entity.items.push(stack);
    } else {
        entity.items[0] = stack;
    }
    let item = item_data(entity);
    entity.nbt.insert("Item".into(), item);
    set_position(entity, position);
}

fn remember(game: &mut Game<'_>, pos: Pos, previous: Option<f32>) {
    if let Ok(map) = game.attachment_map_quiet(Holder::BlockEntity(pos)) {
        if let Some(previous) = previous {
            let _ = map.set(&PREVIOUS, previous);
        } else {
            let _ = map.remove(&PREVIOUS);
        }
    }
}

fn previous(game: &mut Game<'_>, pos: Pos, current: f32) -> f32 {
    game.attachment_map_quiet(Holder::BlockEntity(pos))
        .ok()
        .and_then(|map| map.get_existing(&PREVIOUS).ok().flatten())
        .unwrap_or(current)
}

fn entity_at<'g>(game: &'g Game<'_>, [x, y, z]: Pos) -> Option<&'g ModBlockEntity> {
    match game.world.block_entities.get(&(x, y, z))? {
        BlockEntity::Mod(entity) if is_chute(&entity.id) => Some(entity),
        _ => None,
    }
}

fn enter_at(game: &mut Game<'_>, pos: Pos, stack: ItemStack, start: f32) -> bool {
    if !can_enter(game, pos, &stack) {
        return false;
    }
    let accepted = game.native_with_mod_block_entity(pos, |entity| {
        if !is_chute(&entity.id) || !empty(entity) {
            return false;
        }
        set_item(entity, Some(stack), start);
        true
    }) == Some(true);
    if accepted {
        remember(game, pos, None);
        game.native_block_entity_sync(pos);
    }
    accepted
}

fn can_enter(game: &Game<'_>, pos: Pos, stack: &ItemStack) -> bool {
    is_chute(&game.native_block(pos))
        && entity_at(game, pos).is_some_and(|entity| {
            entity.items.len() <= 1
                && (still_air(entity) || lift_air(game, pos).is_some())
                && empty(entity)
                && (entity.id != SMART
                    || (!powered(game, pos) && accepts_filter(game.items(), entity, stack)))
        })
}

pub(super) fn automation_accepts(
    items: &Items,
    entity: &ModBlockEntity,
    slot: usize,
    stack: &ItemStack,
) -> bool {
    // ChuteItemHandler.insertItem rejects an occupied Chute even when a
    // matching stack could merge. Vanilla still owns its transfer and rollback.
    slot == 0
        && stack.count > 0
        && entity.items.len() <= 1
        && still_air(entity)
        && empty(entity)
        && accepts_filter(items, entity, stack)
}

pub(super) fn external_change(game: &mut Game<'_>, (x, y, z): (i32, i32, i32)) {
    let pos = [x, y, z];
    let Some(entity) = entity_at(game, pos) else {
        return;
    };
    let item = item_data(entity);
    if entity.nbt.get(&"Item".into()) == Some(&item) {
        return;
    }
    let start = entry_position(game, pos);
    if let Some(BlockEntity::Mod(entity)) = game.world.block_entities.get_mut(&(x, y, z)) {
        entity.clear_client_update_fields();
        entity.nbt.insert("Item".into(), item);
        set_position(entity, start);
    }
    remember(game, pos, None);
    game.native_block_entity_sync(pos);
}

fn suction_source(game: &Game<'_>, pos: Pos, distance: f32) -> Option<SuctionSource> {
    // Java chooses the first transported-item handler, including one in the
    // block immediately beyond the unobstructed reach. A Depot or sloped
    // Belt still takes precedence over a more distant horizontal Belt.
    for depth in 1..=(distance as i32 + 1) {
        let source = offset(pos, Direction::Down, -depth);
        let state = loaded_state(game, source)?;
        match state.name.as_str() {
            "create:depot" => return Some(SuctionSource::Depot(source)),
            "create:belt" => {
                return state
                    .properties
                    .get("slope")
                    .is_some_and(|slope| slope == "horizontal")
                    .then_some(SuctionSource::Belt(source));
            }
            _ => {}
        }
    }
    None
}

fn extract_from_belt(game: &mut Game<'_>, pos: Pos) -> Option<ItemStack> {
    use super::create_port_belt as belt;
    let mut captured = None;
    let removed = belt::apply_to_each_within(game, pos, 0.5, |_, item| {
        if captured.is_some() || item.stack.count == 0 {
            return None;
        }
        captured = Some(belt::game_stack(&item.stack));
        Some(create_engine::transport::TransportedResult::Convert {
            outputs: Vec::new(),
            held: None,
        })
    });
    if removed == 1 { captured } else { None }
}

fn capture_transport(
    game: &mut Game<'_>,
    pos: Pos,
    chute: &mut ModBlockEntity,
    source: SuctionSource,
) -> bool {
    let location = match source {
        SuctionSource::Belt(location) | SuctionSource::Depot(location) => location,
    };
    let start = (location[1] + 1 - pos[1]) as f32;
    match source {
        SuctionSource::Belt(_) => extract_from_belt(game, location).is_some_and(|stack| {
            set_item(chute, Some(stack), start);
            true
        }),
        SuctionSource::Depot(_) => {
            let moved = game
                .native_with_mod_block_entity(location, |depot| {
                    if depot.id != "create:depot" || !super::create_port::inventory_supported(depot)
                    {
                        return None;
                    }
                    let Tag::Compound(held) = depot.nbt.get(&"HeldItem".into())? else {
                        return None;
                    };
                    // DepotBehaviour compares the one-sided distance to centre.
                    if 0.5 - super::create_port::number(held, "Pos") > 0.5 {
                        return None;
                    }
                    let slot = depot.items.first_mut()?;
                    let stack = slot.as_ref().filter(|stack| stack.count > 0)?;
                    set_item(chute, Some(stack.clone()), start);
                    *slot = None;
                    super::create_port::depot_data(depot);
                    Some(())
                })
                .flatten()
                .is_some();
            if moved {
                game.native_block_entity_sync(location);
            }
            moved
        }
    }
}

fn suction_tick(game: &mut Game<'_>, pos: Pos, entity: &mut ModBlockEntity, air: Lift) {
    let below = offset(pos, Direction::Down, -1);
    let below_state = game.world.block(below[0], below[1], below[2]);
    let key = (pos[0], pos[1], pos[2]);
    let Some(map) = game.world.block_entities.attachments_mut(key) else {
        return;
    };
    let mut timing = map
        .get_existing(&SUCTION_TIMING)
        .ok()
        .flatten()
        .unwrap_or_default();
    let block_due = timing.block_check <= 0;
    let search_due = timing.entity_search <= 0 && empty(entity);
    let rebuild = block_due || timing.air != air || timing.below != Some(below_state);
    timing.block_check = if block_due {
        super::create_port_server_config::fan().block_check_rate
    } else {
        timing.block_check - 1
    };
    timing.entity_search = if search_due {
        5
    } else {
        timing.entity_search.wrapping_sub(1)
    };
    timing.below = Some(below_state);
    timing.air = air;

    let upwards = air.motion() > 0.0;
    let mut distance = super::create_port::number(&entity.nbt, "BottomAirFlowDistance");
    if upwards && rebuild {
        let limit = chute::suction_range(air.pull - air.push);
        let next = if limit > 0.0 && !is_chute(&game.native_block(below)) {
            super::create_port_fan::flow_limit(
                game,
                pos,
                create_engine::placement::Direction::Down,
                limit,
            )
        } else {
            0.0
        };
        timing.transport = if air.pull >= air.push {
            suction_source(game, pos, next)
        } else {
            None
        };
        if distance != next {
            distance = next;
            entity
                .nbt
                .insert("BottomAirFlowDistance".into(), Tag::Float(next.to_bits()));
            game.native_block_entity_sync(pos);
        }
    }
    if let Some(map) = game.world.block_entities.attachments_mut(key) {
        let _ = map.set(&SUCTION_TIMING, timing);
    }

    if !upwards || !empty(entity) || !distance.is_finite() {
        return;
    }
    let mut captured = None;
    if search_due {
        let [x, y, z] = pos.map(f64::from);
        let margin = f64::from(0.45_f32);
        let min = [
            x + 0.5 - margin,
            y - f64::from(distance) - margin,
            z + 0.5 - margin,
        ];
        let max = [x + 0.5 + margin, y + margin, z + 0.5 + margin];
        let dim = game.dim.id();
        if let Some(item) = game.native_item_entities(dim, min, max).into_iter().next()
            && game.native_set_item_entity(dim, item.id, ItemStack::new("minecraft:air", 0))
        {
            captured = Some((item.stack, (item.position[1] + 0.125 - y) as f32));
        }
    }
    if let Some((stack, start)) = captured {
        set_item(entity, Some(stack), start);
    } else if !timing
        .transport
        .is_some_and(|source| capture_transport(game, pos, entity, source))
    {
        return;
    }
    remember(game, pos, None);
    game.native_block_entity_sync(pos);
}

fn pull(
    game: &mut Game<'_>,
    [x, y, z]: Pos,
    source_face: Direction,
    smart: Option<&ModBlockEntity>,
) -> Option<ItemStack> {
    let source = [x, y + source_face.normal()[1], z];
    if !game.chute_source_available((source[0], source[1], source[2])) {
        return None;
    }
    let dim = game.dim.id();
    let side = source_face.opposite();
    let slots = game.native_container_slots(dim, source, side)?;
    let filter = match smart {
        Some(entity) => read_filter(game, entity)?,
        None => None,
    };
    let slots = slots
        .iter()
        .filter(|slot| slot.can_take)
        .filter_map(|slot| {
            let stack = slot.stack.as_ref()?;
            if filter
                .as_ref()
                .is_some_and(|filter| filter.item != stack.item)
            {
                return None;
            }
            Some(Source {
                slot: slot.slot,
                stack,
                count: stack.count,
                maximum: super::create_port::stack_maximum(game, stack),
            })
        });
    let plan = if let Some(entity) = smart {
        let maximum = filter_maximum(game, filter.as_ref());
        let (amount, exact) = if maximum > 1 && smart_extracting(game, [x, y, z]) {
            extraction_amount(entity, maximum)?
        } else {
            (64, false)
        };
        grouped_pull_plan(&slots.collect::<Vec<_>>(), amount, exact)
    } else {
        chute::pull_plan(slots, ItemStack::same_item_same_components)
    };
    take_from(game, source, side, plan)
}

fn take_from(
    game: &mut Game<'_>,
    source: Pos,
    side: Direction,
    plan: Vec<(usize, u32)>,
) -> Option<ItemStack> {
    let dim = game.dim.id();
    let mut result: Option<ItemStack> = None;
    for (slot, count) in plan {
        let Some(item) = game.native_extract_item(dim, source, side, slot, count) else {
            continue;
        };
        if let Some(stack) = &mut result {
            stack.count += item.count;
        } else {
            result = Some(item);
        }
    }
    result
}

fn grouped_pull_plan(
    slots: &[Source<'_, ItemStack>],
    amount: u32,
    exact: bool,
) -> Vec<(usize, u32)> {
    // ItemHelper.extract(EXACTLY) retries using the next component identity
    // when the first does not have enough. Test each whole group before writes.
    for (index, first) in slots.iter().enumerate() {
        if first.count == 0
            || first.maximum == 0
            || slots[..index].iter().any(|slot| {
                slot.count != 0
                    && slot.maximum != 0
                    && first.stack.same_item_same_components(slot.stack)
            })
        {
            continue;
        }
        let mut plan = Vec::new();
        let mut total = 0;
        for slot in &slots[index..] {
            let count = slot.count.min(slot.maximum).min(amount - total);
            if count == 0
                || total + count > slot.maximum
                || !first.stack.same_item_same_components(slot.stack)
            {
                continue;
            }
            plan.push((slot.slot, count));
            total += count;
            if total == amount {
                return plan;
            }
        }
        if !exact {
            return plan;
        }
    }
    Vec::new()
}

#[derive(Clone, Copy)]
enum Route {
    Blocked,
    Chute { target: Pos, start: f32 },
    Inventory(BelowInventory),
    UpperInventory,
    Drop,
}

#[derive(Clone, Copy)]
enum BelowInventory {
    Belt,
    Depot,
    Container,
    PortableStorage,
    Crusher,
    Saw,
    Millstone,
    Crafter,
}

impl BelowInventory {
    fn insert(
        self,
        game: &mut Game<'_>,
        pos: Pos,
        below: Pos,
        stack: &ItemStack,
        simulate: bool,
    ) -> Option<u32> {
        Some(match self {
            Self::Belt => {
                super::create_port_belt::insert_from_container(game, below, stack, simulate)
            }
            Self::Depot => {
                super::create_port_belt::insert_depot_from_chute(game, below, stack, simulate)
            }
            Self::Container => {
                return game.insert_stacked_from_side(
                    (below[0], below[1], below[2]),
                    Direction::Up,
                    stack,
                    simulate,
                );
            }
            Self::PortableStorage => {
                super::create_port_portable_storage::push_chute(game, below, pos, stack, simulate)
            }
            Self::Crusher => {
                super::create_port_saw_processing::crushing::insert(game, below, stack, simulate)
            }
            Self::Saw => super::create_port_saw_processing::insert_from_transport(
                game, below, stack, simulate,
            ),
            Self::Millstone => {
                super::create_port_millstone::insert_from_transport(game, below, stack, simulate)
            }
            Self::Crafter => super::create_port_saw_processing::crafter::insert_linked(
                game, below, stack, simulate,
            ),
        })
    }
}

fn route_below(
    game: &mut Game<'_>,
    pos: Pos,
    below: Pos,
    stack: &ItemStack,
    vertical: bool,
) -> Route {
    if !super::create_port_contraption::resident(game, below) {
        return Route::Blocked;
    }
    let block = game.native_block(below);
    if is_chute(&block) {
        // The source can tick before the receiving Smart Chute refreshes its state.
        if block == SMART && refresh_power(game, below) {
            return Route::Blocked;
        }
        return if (vertical || block == SMART) && can_enter(game, below, stack) {
            Route::Chute {
                target: below,
                start: ENTRY,
            }
        } else {
            Route::Blocked
        };
    }
    let inventory = match block.as_str() {
        "create:belt" => BelowInventory::Belt,
        "create:depot" => BelowInventory::Depot,
        super::create_port_portable_storage::BLOCK => BelowInventory::PortableStorage,
        super::create_port_saw_processing::crushing::CONTROLLER => BelowInventory::Crusher,
        super::create_port_drill::SAW => BelowInventory::Saw,
        super::create_port_millstone::ID => BelowInventory::Millstone,
        super::create_port_saw_processing::crafter::BLOCK => BelowInventory::Crafter,
        _ => BelowInventory::Container,
    };
    if let Some(moved) = inventory.insert(game, pos, below, stack, true) {
        return if moved > 0 {
            Route::Inventory(inventory)
        } else {
            Route::Blocked
        };
    }
    let state = game.world.block(below[0], below[1], below[2]);
    if !vertical
        || game
            .res
            .behaviours()
            .is_face_sturdy_rigid(state, Direction::Up)
    {
        Route::Blocked
    } else {
        Route::Drop
    }
}

fn route(game: &mut Game<'_>, pos: Pos, below: Pos, stack: &ItemStack, facing: Direction) -> Route {
    let vertical = facing == Direction::Down;
    let direct = route_below(game, pos, below, stack, vertical);
    if vertical || !matches!(direct, Route::Blocked) {
        return direct;
    }
    let target = offset(pos, facing.opposite(), -1);
    if super::create_port_contraption::resident(game, target) && can_enter(game, target, stack) {
        Route::Chute {
            target,
            start: 0.51,
        }
    } else {
        Route::Blocked
    }
}

fn route_above(game: &mut Game<'_>, pos: Pos, facing: Direction, stack: &ItemStack) -> Route {
    let above = offset(pos, Direction::Up, 1);
    if !super::create_port_contraption::resident(game, above) {
        return Route::Blocked;
    }
    let block = game.native_block(above);
    if open_chute(game, pos, facing)
        && !is_chute(&block)
        && let Some(count) = game.insert_stacked_from_side(
            (above[0], above[1], above[2]),
            Direction::Down,
            stack,
            true,
        )
    {
        return if count > 0 {
            Route::UpperInventory
        } else {
            Route::Blocked
        };
    }

    let mut has_input = false;
    let mut best = None;
    for (target, face) in input_candidates(pos) {
        let Some(state) = loaded_state(game, target) else {
            return Route::Blocked;
        };
        if direction(state) != Some(face) {
            continue;
        }
        has_input = true;
        if can_enter(game, target, stack)
            && let Some(air) = lift_air(game, target)
        {
            let motion = air.motion();
            if motion >= 0.0 && best.is_none_or(|(_, faster)| motion > faster) {
                best = Some((target, motion));
            }
        }
    }
    if let Some((target, _)) = best {
        return Route::Chute { target, start: 0.0 };
    }
    let state = game.world.block(above[0], above[1], above[2]);
    if has_input
        || (funnel::is_funnel(&block)
            && game.native_block_property(above, "facing").as_deref() == Some("up"))
        || game.res.behaviours().is_face_sturdy(state, Direction::Down)
    {
        Route::Blocked
    } else {
        Route::Drop
    }
}

pub(super) fn tick(game: &mut Game<'_>, pos: Pos, entity: &mut ModBlockEntity) {
    if entity.id == SMART {
        restore_filter_amount(game, pos, entity);
    }
    if !is_chute(&game.native_block(pos)) || !is_chute(&entity.id) || entity.items.len() > 1 {
        return;
    }
    let air = lift_air(game, pos);
    if let Some(next) = air {
        if next != Lift::read(entity) {
            next.write(entity);
            game.native_block_entity_sync(pos);
        }
    } else if !still_air(entity) {
        return;
    }
    let Some(facing) = update_shape(game, pos) else {
        return;
    };
    let smart = entity.id == SMART;
    let powered = smart && refresh_power(game, pos);
    let motion = air.unwrap_or_default().motion();
    if let Some(air) = air {
        suction_tick(game, pos, entity, air);
    }
    let Some(stack) = entity
        .items
        .first()
        .and_then(Option::as_ref)
        .filter(|stack| stack.count > 0)
    else {
        if powered || motion == 0.0 {
            return;
        }
        let above = [pos[0], pos[1] + 1, pos[2]];
        let pulled = if motion > 0.0 {
            if let Some(item) = pull(game, pos, Direction::Down, None) {
                set_item(entity, Some(item), 0.0);
                true
            } else {
                false
            }
        } else if !smart && game.native_block(above) == super::create_port_portable_storage::BLOCK {
            super::create_port_portable_storage::pull_chute(game, above, |_, item| {
                set_item(entity, Some(item.clone()), ENTRY);
                true
            })
        } else if let Some(item) = pull(game, pos, Direction::Up, smart.then_some(&*entity)) {
            set_item(entity, Some(item), ENTRY);
            true
        } else {
            false
        };
        if pulled {
            remember(game, pos, None);
            game.native_block_entity_sync(pos);
        }
        return;
    };
    let offset = super::create_port::number(&entity.nbt, "ItemPosition");
    if !offset.is_finite() {
        return;
    }
    let below = [pos[0], pos[1] - 1, pos[2]];
    let above = [pos[0], pos[1] + 1, pos[2]];
    let mut output = Route::Blocked;
    match chute::step(offset, motion, || {
        if !powered {
            output = if motion > 0.0 {
                route_above(game, pos, facing, stack)
            } else {
                route(game, pos, below, stack, facing)
            };
        }
        !matches!(output, Route::Blocked)
    }) {
        Step::Position(next) => {
            let moved = next != offset;
            let stopped = !moved && previous(game, pos, offset) != offset;
            remember(game, pos, Some(offset));
            if moved {
                set_position(entity, next);
            }
            if (moved || stopped)
                && (smart
                    || game.native_block_property(pos, "shape").as_deref() == Some("window")
                    || shows_suction_cargo(entity, offset.min(next)))
            {
                // Send the previous render endpoint on movement and reset it
                // on the first stationary tick. The authoritative NBT remains
                // the same Java ItemPosition field in both cases.
                entity.set_client_update_fields(Compound::from([(
                    DRAW_PREVIOUS.into(),
                    Tag::Float(offset.to_bits()),
                )]));
                game.native_block_entity_sync(pos);
            }
        }
        Step::Output => {
            let stack = stack.clone();
            match output {
                Route::Chute { target, start } => {
                    if !enter_at(game, target, stack, start) {
                        return;
                    }
                    set_item(entity, None, if motion > 0.0 { 0.0 } else { ENTRY });
                }
                Route::Inventory(inventory) => {
                    let mut rest = stack;
                    let moved = inventory
                        .insert(game, pos, below, &rest, false)
                        .unwrap_or(0);
                    rest.count -= moved;
                    let previous = previous(game, pos, offset);
                    set_item(entity, (rest.count != 0).then_some(rest), previous);
                }
                Route::UpperInventory => {
                    let mut rest = stack;
                    let moved = game
                        .insert_stacked_from_side(
                            (above[0], above[1], above[2]),
                            Direction::Down,
                            &rest,
                            false,
                        )
                        .unwrap_or(0);
                    rest.count -= moved;
                    set_item(entity, (rest.count != 0).then_some(rest), offset);
                }
                Route::Drop => {
                    let (height, velocity, start) = if motion > 0.0 {
                        (1.0, f64::from(motion * 2.0), 0.0)
                    } else {
                        (-0.25, -0.25, ENTRY)
                    };
                    game.spawn_item(
                        stack,
                        [
                            f64::from(pos[0]) + 0.5,
                            f64::from(pos[1]) + height,
                            f64::from(pos[2]) + 0.5,
                        ],
                        [0.0, velocity, 0.0],
                        10,
                    );
                    set_item(entity, None, start);
                }
                Route::Blocked => return,
            }
            remember(game, pos, None);
            game.native_block_entity_sync(pos);
        }
    }
}

fn open_chute(game: &Game<'_>, pos: Pos, facing: Direction) -> bool {
    facing == Direction::Down
        || game.native_block_property(pos, "shape").as_deref() == Some("intersection")
}

pub(super) fn accepts_direct_input(game: &Game<'_>, pos: Pos) -> bool {
    let above = offset(pos, Direction::Up, 1);
    is_chute(&game.native_block(pos))
        && loaded_state(game, above).and_then(direction) != Some(Direction::Down)
        && loaded_state(game, pos)
            .and_then(direction)
            .is_some_and(|facing| open_chute(game, pos, facing))
        && (!lift_air(game, pos).is_some_and(|air| air.motion() > 0.0)
            || input_candidates(pos)
                .into_iter()
                .any(|(child, face)| loaded_state(game, child).and_then(direction) == Some(face)))
}

pub(super) fn insert_from_transport(game: &mut Game<'_>, pos: Pos, stack: &ItemStack) -> u32 {
    if !accepts_direct_input(game, pos) {
        return 0;
    }
    insert_from_inventory(game, pos, stack)
}

/// ChuteItemHandler remains available when the direct Belt entrance is closed.
pub(super) fn insert_from_inventory(game: &mut Game<'_>, pos: Pos, stack: &ItemStack) -> u32 {
    if !game.native_on("create") || stack.count == 0 {
        return 0;
    }
    // Insertion can run before the Chute's block-entity tick. Observe
    // the current neighbor signal just as SmartChuteBlock does on change.
    if game.native_block(pos) == SMART && refresh_power(game, pos) {
        return 0;
    }
    let count = stack
        .count
        .min(super::create_port::stack_maximum(game, stack));
    let start = entry_position(game, pos);
    if count == 0
        || !enter_at(
            game,
            pos,
            ItemStack {
                count,
                ..stack.clone()
            },
            start,
        )
    {
        return 0;
    }
    count
}

pub(super) fn landed(game: &mut Game<'_>, pos: Pos, stack: &mut ItemStack) -> bool {
    let moved = insert_from_transport(game, pos, stack);
    stack.count -= moved;
    moved > 0
}

fn powered(game: &Game<'_>, pos: Pos) -> bool {
    game.native_block_property(pos, "powered").as_deref() == Some("true")
}

pub(super) fn refresh_power(game: &mut Game<'_>, pos: Pos) -> bool {
    let signal = game.native_neighbor_signal(game.dim.id(), pos) != 0;
    if signal != powered(game, pos) {
        game.native_set_block_property_with(
            pos,
            "powered",
            if signal { "true" } else { "false" },
            horizon_world::level::flags::UPDATE_CLIENTS,
        );
    }
    signal
}

fn smart_extracting(game: &Game<'_>, [x, y, z]: Pos) -> bool {
    // In the supported downward flow, the count board describes the source
    // above the Smart Chute, even when the outlet below is open.
    let source_y = y + 1;
    !is_chute(&game.native_block([x, source_y, z]))
        && !game
            .res
            .behaviours()
            .is_replaceable(game.world.block(x, source_y, z))
}

fn filter_maximum(game: &Game<'_>, sample: Option<&ItemStack>) -> u32 {
    sample.map_or(64, |stack| super::create_port::stack_maximum(game, stack))
}

fn has_legacy_filter_amount(entity: &ModBlockEntity) -> bool {
    super::create_port::integer(&entity.nbt, "FilterAmount") == 0
}

fn write_legacy_filter_amount(entity: &mut ModBlockEntity, amount: u32) {
    // FilteringBehaviour.read migrates a legacy zero using the filter that
    // was saved with it. A later filter replacement must keep this amount.
    entity
        .nbt
        .insert("FilterAmount".into(), Tag::Int(amount as i32));
    entity.nbt.insert("UpTo".into(), Tag::Byte(1));
}

fn restore_filter_amount(game: &mut Game<'_>, pos: Pos, entity: &mut ModBlockEntity) {
    if has_legacy_filter_amount(entity)
        && let Some(filter) = read_filter(game, entity)
    {
        let amount = filter_maximum(game, filter.as_ref());
        write_legacy_filter_amount(entity, amount);
        game.native_block_entity_sync(pos);
    }
}

fn extraction_amount(entity: &ModBlockEntity, maximum: u32) -> Option<(u32, bool)> {
    match super::create_port::integer(&entity.nbt, "FilterAmount") {
        0 => Some((maximum, false)),
        amount @ 1..=99 => Some((amount as u32, exact_amount(entity))),
        _ => None,
    }
}

fn exact_amount(entity: &ModBlockEntity) -> bool {
    matches!(entity.nbt.get(&"UpTo".into()), Some(Tag::Byte(0)))
}

fn read_filter(game: &Game<'_>, entity: &ModBlockEntity) -> Option<Option<ItemStack>> {
    super::create_port_saw_processing::read_filter(game.items(), entity)
}

fn accepts_filter(items: &Items, entity: &ModBlockEntity, stack: &ItemStack) -> bool {
    super::create_port_saw_processing::read_filter(items, entity)
        .is_some_and(|filter| filter.is_none_or(|filter| filter.item == stack.item))
}

fn filter_center(face: Pos, height: f32) -> [f32; 3] {
    [
        0.5 + face[0] as f32 * 7.5 / 16.0,
        height,
        0.5 + face[2] as f32 * 7.5 / 16.0,
    ]
}

fn filter_hit(game: &Game<'_>, pos: Pos, height: f32) -> bool {
    if !game.may_build()
        || game.native_sneaking()
        || game
            .inventory
            .get(game.selected)
            .and_then(Option::as_ref)
            .is_some_and(|stack| stack.item.as_ref() == "create:clipboard")
    {
        return false;
    }
    let Some(hit) = game.pick().filter(|hit| hit.pos == pos && hit.face[1] == 0) else {
        return false;
    };
    hits_filter(hit.point, pos, filter_center(hit.face, height))
}

fn hits_filter(point: [f64; 3], pos: Pos, center: [f32; 3]) -> bool {
    point
        .into_iter()
        .zip(pos)
        .zip(center)
        .map(|((at, block), center)| (at - f64::from(block) - f64::from(center)).powi(2))
        .sum::<f64>()
        < 0.25 * 0.25
}

#[derive(Clone, Copy)]
struct FilterSlot {
    entity: &'static str,
    height: f32,
    extracting: bool,
}

fn filter_slot(game: &Game<'_>, pos: Pos, block: &str) -> Option<FilterSlot> {
    match block {
        SMART => Some(FilterSlot {
            entity: SMART,
            height: 11.0 / 16.0,
            extracting: smart_extracting(game, pos),
        }),
        funnel::BRASS
            if game.native_block_property(pos, "waterlogged").as_deref() == Some("false") =>
        {
            Some(FilterSlot {
                entity: funnel::ENTITY,
                height: funnel::filter_height(game, pos)?,
                extracting: game.native_block_property(pos, "extracting").as_deref()
                    == Some("true"),
            })
        }
        _ => None,
    }
}

#[derive(Clone, Copy)]
pub(super) struct FilterAmount {
    pub maximum: i32,
    pub value: i32,
    pub up_to: bool,
}

fn visible_amount(
    game: &Game<'_>,
    slot: FilterSlot,
    entity: &ModBlockEntity,
    sample: Option<&ItemStack>,
) -> Option<FilterAmount> {
    let maximum = filter_maximum(game, sample);
    if !slot.extracting || maximum <= 1 {
        return None;
    }
    let (value, exact) = extraction_amount(entity, maximum)?;
    Some(FilterAmount {
        maximum: maximum as i32,
        value: value as i32,
        up_to: !exact,
    })
}

fn slot_amount(game: &Game<'_>, pos: Pos, slot: FilterSlot) -> Option<FilterAmount> {
    let entity = filter_entity(game, pos, slot.entity)?;
    let sample = read_filter(game, entity)?;
    visible_amount(game, slot, entity, sample.as_ref())
}

pub(super) fn amount_board(game: &Game<'_>, pos: Pos) -> Option<FilterAmount> {
    slot_amount(game, pos, filter_slot(game, pos, &game.native_block(pos))?)
}

pub(super) fn amount_board_hit(
    game: &Game<'_>,
    hit: &super::Hit,
    block: &str,
) -> Option<FilterAmount> {
    let slot = filter_slot(game, hit.pos, block)?;
    if hit.face[1] != 0 || !hits_filter(hit.point, hit.pos, filter_center(hit.face, slot.height)) {
        return None;
    }
    slot_amount(game, hit.pos, slot)
}

pub(super) fn set_filter_amount(game: &mut Game<'_>, pos: Pos, row: i32, raw: i32) -> bool {
    let Some(old) = amount_board(game, pos) else {
        return false;
    };
    let up_to = row == 0;
    if old.up_to == up_to && old.value == raw {
        return false;
    }
    let value = raw.clamp(1, old.maximum);
    if game
        .native_with_mod_block_entity(pos, |entity| {
            entity.nbt.insert("FilterAmount".into(), Tag::Int(value));
            entity.nbt.insert("UpTo".into(), Tag::Byte(i8::from(up_to)));
        })
        .is_none()
    {
        return false;
    }
    game.native_block_entity_sync(pos);
    true
}

pub(super) fn filter_tap(
    game: &mut Game<'_>,
    pos: Pos,
    face: Pos,
    offset: [f32; 3],
    sample: Option<&ItemStack>,
) {
    let Some(slot) = filter_slot(game, pos, &game.native_block(pos)) else {
        return;
    };
    let point = std::array::from_fn(|axis| f64::from(pos[axis]) + f64::from(offset[axis]));
    if !hits_filter(point, pos, filter_center(face, slot.height))
        || slot_amount(game, pos, slot).is_none()
    {
        return;
    }
    change_filter(game, pos, slot.entity, sample);
}

pub(super) fn filter_display(
    game: &Game<'_>,
    hit: &super::Hit,
    block: &str,
) -> Option<FilterDisplay> {
    if hit.face[1] != 0 {
        return None;
    }
    let slot = filter_slot(game, hit.pos, block)?;
    let entity = filter_entity(game, hit.pos, slot.entity)?;
    let filter = read_filter(game, entity)?;
    let center = filter_center(hit.face, slot.height);
    let count =
        visible_amount(game, slot, entity, filter.as_ref()).map_or_else(String::new, |amount| {
            if amount.up_to && amount.value == amount.maximum {
                "*".into()
            } else {
                amount.value.to_string()
            }
        });
    let solid_item = !count.is_empty()
        && filter.as_ref().is_some_and(|stack| {
            game.resolve_item(
                stack,
                horizon_assets::item_model::DisplayContext::Fixed,
                None,
                0,
            )
            .uses_block_light()
        });
    Some(FilterDisplay {
        center,
        rotation: None,
        label: FilterLabel::Item,
        hit: hits_filter(hit.point, hit.pos, center),
        filled: filter.is_some(),
        solid_item,
        count,
    })
}

fn change_filter(game: &mut Game<'_>, pos: Pos, id: &str, sample: Option<&ItemStack>) -> bool {
    if sample.is_some_and(|stack| {
        matches!(
            stack.item.as_ref(),
            "create:wrench" | "create:mechanical_arm" | "create:clipboard"
        ) || !super::create_port_saw_processing::ordinary_filter_item(game.items(), stack)
    }) {
        return true;
    }
    let Some(entity) = filter_entity(game, pos, id) else {
        return true;
    };
    let Some(current) = read_filter(game, entity) else {
        return true;
    };
    let legacy = has_legacy_filter_amount(entity).then(|| filter_maximum(game, current.as_ref()));
    let maximum = sample.map(|stack| filter_maximum(game, Some(stack)) as i32);
    let sample = sample.map_or_else(|| Tag::Compound(Compound::new()), item_to_nbt);
    if game
        .native_with_mod_block_entity(pos, |entity| {
            if let Some(amount) = legacy {
                write_legacy_filter_amount(entity, amount);
            }
            entity.nbt.insert("Filter".into(), sample);
            if matches!(entity.nbt.get(&"UpTo".into()), Some(Tag::Byte(0)))
                && let (Some(max), Some(Tag::Int(count))) =
                    (maximum, entity.nbt.get_mut(&"FilterAmount".into()))
            {
                *count = (*count).min(max);
            }
        })
        .is_none()
    {
        return false;
    }
    game.native_block_entity_sync(pos);
    game.native_play_sound_in_place(
        "minecraft:entity.item_frame.add_item",
        pos.map(|coordinate| f64::from(coordinate) + 0.5),
        4,
        0.25,
        0.1,
    );
    true
}

fn filter_entity<'g>(game: &'g Game<'_>, [x, y, z]: Pos, id: &str) -> Option<&'g ModBlockEntity> {
    match game.world.block_entities.get(&(x, y, z))? {
        BlockEntity::Mod(entity) if entity.id == id => Some(entity),
        _ => None,
    }
}

fn shape_change(game: &Game<'_>, pos: Pos, item: &ItemStack) -> Option<(String, &'static str)> {
    if game.spectator() || game.native_sneaking() {
        return None;
    }
    let shape = game.native_block_property(pos, "shape")?;
    let next = if item.item.as_ref() == CASING {
        match shape.as_str() {
            "normal" | "window" => "encased",
            _ => return None,
        }
    } else {
        if !super::create_port_chassis::wrench(game, item) || !game.may_build() {
            return None;
        }
        let vertical = game.native_block_property(pos, "facing").as_deref() == Some("down");
        match shape.as_str() {
            "normal" if vertical => "window",
            "window" | "encased" => "normal",
            "normal" => "normal",
            _ => return None,
        }
    };
    Some((shape, next))
}

pub(super) fn predicts_use(game: &Game<'_>, pos: Pos) -> bool {
    game.native_on("create")
        && is_chute(&game.native_block(pos))
        && (game.native_block(pos) == SMART && filter_hit(game, pos, 11.0 / 16.0)
            || game
                .held()
                .is_some_and(|item| shape_change(game, pos, item).is_some()))
}

pub(super) fn right_click(game: &mut Game<'_>, pos: Pos) -> bool {
    if !game.native_on("create") || !is_chute(&game.native_block(pos)) {
        return false;
    }
    if game.native_block(pos) == SMART && filter_hit(game, pos, 11.0 / 16.0) {
        let sample = game.held().cloned();
        return change_filter(game, pos, SMART, sample.as_ref());
    }
    if let Some(item) = game.held() {
        let Some((shape, next)) = shape_change(game, pos, item) else {
            return false;
        };
        if shape == next {
            return true;
        }
        if !game.native_set_block_property(pos, "shape", next) {
            return false;
        }
        if next == "encased" {
            let center = pos.map(|v| f64::from(v) + 0.5);
            game.native_play_sound_in_place(
                "minecraft:block.netherite_block.hit",
                center,
                4,
                0.5,
                1.05,
            );
        } else if shape == "encased"
            && let Some(state) = game.pack.assets.registry.default_state(CASING)
        {
            game.level_event_at(2001, pos, state.0 as i32);
        }
        return true;
    }
    let item = game
        .native_with_mod_block_entity(pos, |entity| {
            let item = entity.items.first_mut()?.take()?;
            set_item(entity, None, ENTRY);
            Some(item)
        })
        .flatten();
    if let Some(item) = item {
        game.give_or_drop(item);
        remember(game, pos, None);
        game.native_block_entity_sync(pos);
        true
    } else {
        false
    }
}

fn shows_suction_cargo(entity: &ModBlockEntity, offset: f32) -> bool {
    offset <= 0.5 && super::create_port::number(&entity.nbt, "BottomAirFlowDistance") != 0.0
}

pub(super) fn update_render_tag(entity: &ModBlockEntity, tag: &mut Compound) {
    let current = tag
        .get(&"ItemPosition".into())
        .cloned()
        .unwrap_or(Tag::Float(0));
    tag.insert(DRAW_PREVIOUS.into(), current);
    tag.extend(entity.take_client_update_fields());
}

pub(super) fn draw(game: &Game<'_>, pos: Pos, entity: &ModBlockEntity, draw: &mut BlockEntityDraw) {
    if !is_chute(&game.native_block(pos)) {
        return;
    }
    let current = super::create_port::number(&entity.nbt, "ItemPosition");
    let previous = match entity.nbt.get(&DRAW_PREVIOUS.into()) {
        Some(Tag::Float(bits)) if f32::from_bits(*bits).is_finite() => f32::from_bits(*bits),
        _ => current,
    };
    let offset = previous + draw.partial * (current - previous);
    if entity.id == SMART {
        draw_filter(game, entity, draw, 11.0 / 16.0);
        if offset > 0.0 {
            return;
        }
    } else if game.native_block_property(pos, "facing").as_deref() != Some("down")
        || (game.native_block_property(pos, "shape").as_deref() != Some("window")
            && !shows_suction_cargo(entity, offset))
    {
        return;
    }
    let Some(stack) = entity.nbt.get(&"Item".into()).and_then(item_from_nbt) else {
        return;
    };
    if !offset.is_finite() {
        return;
    }
    static TRACE: OnceLock<bool> = OnceLock::new();
    if *TRACE.get_or_init(|| std::env::var_os("CREATE_HORIZON_TRACE_CHUTE_CARGO").is_some()) {
        log::info!(
            "Create Chute cargo: {}",
            serde_json::json!({"pos": pos, "time": draw.game_time, "count": stack.count,
                "previous": previous, "current": current, "partial": draw.partial, "offset": offset})
        );
    }
    draw.push();
    draw.translate([0.5, offset, 0.5]);
    draw.scale([0.5; 3]);
    draw.rotate_about([1.0, 0.0, 0.0], offset * 180.0, [0.0; 3]);
    draw.rotate_about([0.0, 1.0, 0.0], offset * 180.0, [0.0; 3]);
    game.native_draw_item(
        draw,
        &stack,
        horizon_assets::item_model::DisplayContext::Fixed,
        None,
        0,
    );
    draw.pop();
}

fn draw_filter(game: &Game<'_>, entity: &ModBlockEntity, draw: &mut BlockEntityDraw, height: f32) {
    let Some(Some(stack)) = read_filter(game, entity) else {
        return;
    };
    let rendered = game.resolve_item(
        &stack,
        horizon_assets::item_model::DisplayContext::Fixed,
        None,
        0,
    );
    if rendered.is_empty() {
        return;
    }
    let solid = rendered.uses_block_light();
    let scale = 0.5 * ((if solid { 1.0 } else { 0.5 }) + 1.0 / 64.0);
    for (face, yaw) in [
        ([0, 0, 1], 180.),
        ([0, 0, -1], 0.),
        ([1, 0, 0], -90.),
        ([-1, 0, 0], 90.),
    ] {
        draw.push();
        draw.translate(filter_center(face, height));
        draw.rotate_about([0., 1., 0.], yaw, [0.; 3]);
        draw.scale([scale; 3]);
        draw.translate([0., 0., if solid { 0.0 } else { -0.15 }]);
        game.submit_item_world(&rendered, draw.pose(), draw.light, draw.vertices_mut());
        draw.pop();
    }
}

pub(in crate::game) mod funnel {
    use super::{
        BlockEntityDraw, Source, accepts_filter, change_filter, draw_filter, extraction_amount,
        filter_entity, filter_hit, filter_maximum, grouped_pull_plan, read_filter,
        restore_filter_amount, take_from,
    };
    use crate::game::{Game, GameLevel, create_port_belt::world_direction};
    use crate::{containers::ModBlockEntity, items::ItemStack};
    use create_engine::{kinetics::Pos, placement::Direction};
    use horizon_core::{geometry::Vec3, position::BlockPos, random::RandomSource};
    use horizon_world::{
        fluid::FluidKind,
        level::{PlaceContext, PlaceOutcome, PlacementContext, flags},
        nbt::{Compound, Tag},
        registry::BlockStateId,
    };

    pub(in crate::game) const BLOCK: &str = "create:andesite_funnel";
    pub(in crate::game) const BRASS: &str = "create:brass_funnel";
    pub(in crate::game) const ENTITY: &str = "create:funnel";
    // CLogistics.defaultExtractionTimer in Create 6.0.10.
    const EXTRACTION_COOLDOWN: i32 = 8;

    pub(in crate::game) fn is_funnel(block: &str) -> bool {
        matches!(block, BLOCK | BRASS)
    }

    pub(in crate::game) fn default_nbt() -> Compound {
        Compound::from([
            ("TransferCooldown".into(), Tag::Int(0)),
            ("Filter".into(), Tag::Compound(Compound::new())),
            ("FilterAmount".into(), Tag::Int(64)),
            ("UpTo".into(), Tag::Byte(1)),
        ])
    }

    fn property(game: &Game<'_>, pos: Pos, name: &str) -> bool {
        game.native_block_property(pos, name).as_deref() == Some("true")
    }

    fn direction(game: &Game<'_>, pos: Pos) -> Option<Direction> {
        let name = game.native_block_property(pos, "facing")?;
        Direction::ALL.into_iter().find(|d| d.name() == name)
    }

    pub(in crate::game) fn placement(
        game: &GameLevel<'_>,
        state: BlockStateId,
        context: &PlacementContext,
        face: Direction,
    ) -> Option<BlockStateId> {
        let facing = if context.replace_clicked {
            crate::game::create_port::nearest(context.yaw, context.pitch).opposite()
        } else {
            face
        };
        let at = context.pos;
        let existing = game.world.block(at.x, at.y, at.z);
        // This release implements the dry vertical forms. A horizontal
        // placement may also resolve to a separate Belt Funnel in Java.
        if !matches!(facing, Direction::Up | Direction::Down)
            || game.behaviours.fluid_kind(existing) != FluidKind::Empty
        {
            return None;
        }
        let [dx, dy, dz] = facing.vector();
        let behind = game.world.block(at.x - dx, at.y - dy, at.z - dz);
        if game.native_state_block(behind).is_some_and(is_funnel) {
            return None;
        }
        let state = game.native_state_with_property(state, "facing", facing.name())?;
        game.native_state_with_property(
            state,
            "extracting",
            if context.sneaking { "false" } else { "true" },
        )
    }

    pub(in crate::game) fn refresh_power(game: &mut Game<'_>, pos: Pos) -> bool {
        let powered = game.native_neighbor_signal(game.dim.id(), pos) != 0;
        if powered != property(game, pos, "powered") {
            game.native_set_block_property_with(
                pos,
                "powered",
                if powered { "true" } else { "false" },
                flags::UPDATE_CLIENTS,
            );
        }
        powered
    }

    pub(in crate::game) fn tick(game: &mut Game<'_>, pos: Pos, entity: &mut ModBlockEntity) {
        if entity.id != ENTITY {
            return;
        }
        restore_filter_amount(game, pos, entity);
        if property(game, pos, "waterlogged") {
            return;
        }
        let cooldown = crate::game::create_port::integer(&entity.nbt, "TransferCooldown");
        let next = if refresh_power(game, pos) {
            0
        } else if cooldown > 0 {
            cooldown - 1
        } else if property(game, pos, "extracting") && extract(game, pos, entity) {
            EXTRACTION_COOLDOWN
        } else {
            0
        };
        if next != cooldown {
            entity.nbt.insert("TransferCooldown".into(), Tag::Int(next));
        }
    }

    fn extract(game: &mut Game<'_>, pos: Pos, entity: &ModBlockEntity) -> bool {
        let Some(facing @ (Direction::Up | Direction::Down)) = direction(game, pos) else {
            return false;
        };
        let dim = game.dim.id();
        let source = [pos[0], pos[1] - facing.vector()[1], pos[2]];
        let side = world_direction(facing);
        let Some(slots) = game.native_container_slots(dim, source, side) else {
            return false;
        };
        let plan = if game.native_block(pos) == BRASS {
            let Some(filter) = read_filter(game, entity) else {
                return false;
            };
            let Some((amount, exact)) =
                extraction_amount(entity, filter_maximum(game, filter.as_ref()))
            else {
                return false;
            };
            let sources = slots
                .iter()
                .filter(|slot| slot.can_take)
                .filter_map(|slot| {
                    let stack = slot.stack.as_ref()?;
                    if filter
                        .as_ref()
                        .is_some_and(|sample| sample.item != stack.item)
                    {
                        return None;
                    }
                    Some(Source {
                        slot: slot.slot,
                        stack,
                        count: stack.count,
                        maximum: crate::game::create_port::stack_maximum(game, stack),
                    })
                })
                .collect::<Vec<_>>();
            grouped_pull_plan(&sources, amount, exact)
        } else {
            slots
                .into_iter()
                .find(|slot| slot.can_take)
                .map_or_else(Vec::new, |slot| vec![(slot.slot, 1)])
        };
        if plan.is_empty() {
            return false;
        }
        let up = facing == Direction::Up;
        let origin = pos.map(f64::from);
        let mut scan_min = origin;
        if !up {
            scan_min[1] -= 1.0;
        }
        if !game
            .native_item_entities(dim, scan_min, origin.map(|v| v + 1.0))
            .is_empty()
        {
            return false;
        }
        let Some(stack) = take_from(game, source, side, plan) else {
            return false;
        };
        let mut spawn = origin.map(|v| v + 0.5);
        spawn[1] = if up {
            spawn[1] + f64::from(0.15_f32)
        } else {
            origin[1]
        };
        game.spawn_item(stack, spawn, [0.0, if up { 0.25 } else { 0.0 }, 0.0], 10);
        let at = origin.map(|v| v + 0.5);
        game.native_play_sound_in_place(
            "minecraft:entity.item_frame.rotate_item",
            at,
            4,
            0.125,
            1.5,
        );
        game.native_play_sound_in_place("minecraft:block.wool.break", at, 4, 0.0425, 0.75);
        true
    }

    fn collecting(game: &Game<'_>, pos: Pos, face: Pos, stack: &ItemStack) -> bool {
        face == [0, 1, 0]
            && direction(game, pos) == Some(Direction::Up)
            && !property(game, pos, "powered")
            && !property(game, pos, "extracting")
            && stack.item.as_ref() != "create:mechanical_arm"
    }

    fn insert_into(game: &mut Game<'_>, pos: Pos, block: &str, stack: &ItemStack) -> u32 {
        if block == BRASS
            && !filter_entity(game, pos, ENTITY)
                .is_some_and(|entity| accepts_filter(game.items(), entity, stack))
        {
            return 0;
        }
        let below @ [x, y, z] = [pos[0], pos[1] - 1, pos[2]];
        use crate::game::create_port_saw_processing::crafter;
        if game.native_block(below) == crafter::BLOCK {
            return crafter::insert_linked(game, below, stack, false);
        }
        game.insert_stacked_from_side((x, y, z), world_direction(Direction::Up), stack, false)
            .unwrap_or(0)
    }

    pub(in crate::game) fn insert_from_transport(
        game: &mut Game<'_>,
        pos: Pos,
        block: &str,
        stack: &ItemStack,
    ) -> u32 {
        // FunnelBlockEntity only exposes direct input on a collecting
        // Funnel facing up. Check redstone before its own ticker can run.
        if direction(game, pos) != Some(Direction::Up)
            || property(game, pos, "extracting")
            || property(game, pos, "waterlogged")
            || refresh_power(game, pos)
        {
            return 0;
        }
        insert_into(game, pos, block, stack)
    }

    enum Use {
        Attach,
        Wrench,
        Pickup,
        Filter,
        Collect,
    }

    pub(super) fn filter_height(game: &Game<'_>, pos: Pos) -> Option<f32> {
        match direction(game, pos)? {
            Direction::Down => Some(14.0 / 16.0),
            Direction::Up => Some(2.0 / 16.0),
            _ => None,
        }
    }

    pub(in crate::game) fn draw(
        game: &Game<'_>,
        pos: Pos,
        entity: &ModBlockEntity,
        draw: &mut BlockEntityDraw,
    ) {
        if entity.id == ENTITY
            && let Some(height) = filter_height(game, pos)
        {
            draw_filter(game, entity, draw, height);
        }
    }

    fn action(game: &Game<'_>, pos: Pos, face: Pos, held: Option<&ItemStack>) -> Option<Use> {
        if !game.native_on("create") || game.spectator() {
            return None;
        }
        let sneaking = game.native_sneaking();
        let block = game.native_block(pos);
        if held.is_some_and(|stack| is_funnel(&stack.item)) {
            return (!sneaking
                && matches!(face, [0, -1, 0] | [0, 1, 0])
                && matches!(
                    block.as_str(),
                    "minecraft:chest" | "minecraft:trapped_chest" | "minecraft:barrel"
                ))
            .then_some(Use::Attach);
        }
        if !is_funnel(&block) || property(game, pos, "waterlogged") {
            return None;
        }
        if block == BRASS
            && filter_height(game, pos).is_some_and(|height| filter_hit(game, pos, height))
        {
            return Some(Use::Filter);
        }
        let stack = held?;
        if game.may_build() && crate::game::create_port_chassis::wrench(game, stack) {
            return Some(if sneaking { Use::Pickup } else { Use::Wrench });
        }
        (!sneaking && collecting(game, pos, face, stack)).then_some(Use::Collect)
    }

    pub(in crate::game) fn predicts_use(game: &Game<'_>, pos: Pos, face: Pos) -> bool {
        action(game, pos, face, game.held()).is_some()
    }

    pub(in crate::game) fn right_click(game: &mut Game<'_>, pos: Pos, face: Pos) -> bool {
        let Some(action) = action(game, pos, face, game.held()) else {
            return false;
        };
        match (action, game.held().cloned()) {
            (Use::Filter, sample) => return change_filter(game, pos, ENTITY, sample.as_ref()),
            (Use::Attach, Some(stack)) => attach(game, pos, face, &stack),
            (Use::Pickup, Some(stack)) => pickup(game, pos, &stack),
            (Use::Wrench, _) => {
                let extracting = property(game, pos, "extracting");
                game.native_set_block_property(
                    pos,
                    "extracting",
                    if extracting { "false" } else { "true" },
                );
            }
            (Use::Collect, Some(stack)) => {
                let block = game.native_block(pos);
                let inserted = insert_into(game, pos, &block, &stack);
                if inserted > 0 {
                    let count = stack.count - inserted;
                    *game.held_mut() = (count > 0).then_some(ItemStack { count, ..stack });
                }
            }
            _ => return false,
        }
        true
    }

    fn pickup(game: &mut Game<'_>, pos: Pos, wrench: &ItemStack) {
        let [x, y, z] = pos;
        let state = game.world.block(x, y, z);
        let mut canceled = false;
        game.native_destroy_block(pos, state, &mut canceled);
        if canceled || game.world.block(x, y, z) != state {
            return;
        }
        let drops = if game.creative {
            Vec::new()
        } else {
            let block = game.native_block(pos);
            let entity = game.loot_block_entity(pos, &block);
            game.block_loot_at(pos, state, Some(wrench), entity)
        };
        if game.with_level(|b, level, ticks| {
            b.destroy_block(level, ticks, BlockPos::new(x, y, z), false)
        }) {
            let _ = game.process_level_events();
            for stack in drops {
                game.give_or_drop(stack);
            }
            let pitch = 0.5 + game.world.random.next_float() * 0.5;
            crate::game::create_port_sounds::wrench_remove(game, pos, pitch);
        }
    }

    fn attach(game: &mut Game<'_>, pos: Pos, face: Pos, stack: &ItemStack) {
        // FunnelItem bypasses the clicked container's own menu before running
        // BlockItem.place. Keep its ordinary validation and placed-item effects.
        if !game.may_build() && !game.can_place_on_in_adventure(pos) {
            game.use_failed = true;
            return;
        }
        let ctx = PlaceContext {
            clicked_pos: BlockPos::new(pos[0], pos[1], pos[2]),
            face: world_direction(if face[1] > 0 {
                Direction::Up
            } else {
                Direction::Down
            }),
            hit: Vec3::new(
                f64::from(pos[0]) + 0.5,
                f64::from(pos[1]) + if face[1] > 0 { 1.0 } else { 0.0 },
                f64::from(pos[2]) + 0.5,
            ),
            inside: false,
            yaw: game.yaw,
            pitch: game.pitch,
            sneaking: false,
            item: stack.item.to_string(),
            can_use_game_master_blocks: game.can_use_game_master_blocks(),
        };
        if game.block_place_canceled(stack, &ctx) {
            game.use_failed = true;
            game.guest_inventory_resend = true;
            return;
        }
        let outcome = game.with_level(|b, level, ticks| b.place_block(level, ticks, &ctx));
        if let PlaceOutcome::Placed { pos, state } = outcome {
            let target = [pos.x, pos.y, pos.z];
            let state = game
                .apply_item_block_state(target, state, stack)
                .unwrap_or(state);
            if !game.world.block_entities.stateful_entity(state.0)
                && let Some(entity) = game.new_block_entity_for_state(state)
            {
                game.world
                    .block_entities
                    .insert((pos.x, pos.y, pos.z), entity);
            }
            game.apply_placed_item(target, stack, ctx.can_use_game_master_blocks);
            game.award_stat("used", &stack.item, 1);
            game.trigger_block("minecraft:placed_block", target, stack);
            game.native_place_block(stack, target, state);
            game.consume_held();
        } else {
            game.use_failed = true;
        }
        if let Err(error) = game.process_level_events() {
            log::warn!("Create Funnel placement: {error}");
        }
    }
}
