// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT

use super::create_port_block_entity_revision::EntityRevision as _;
use super::{
    Game, GameLevel, create_port_contraption as contraption,
    create_port_contraption_storage as storage, native_block_entity_draw::BlockEntityDraw,
};
use crate::{
    containers::{BlockEntity, ModBlockEntity, ModRevision},
    items::ItemStack,
};
use create_engine::{
    contraption::portable_storage::{
        Actor, DEFAULT_TIMEOUT, Endpoint, MovingHead, PowerUpdate, Probe, Station, TickUpdate,
        stationary_extension,
    },
    kinetics::{Axis, Pos},
    placement::Direction,
    transport::SessionCache,
};
use glam::DVec3;
use horizon_client_render::create_contraption_scene::{
    MAX_BLOCKS, RECORDS, Record, StrokeKind, read,
};
use horizon_core::{geometry::Direction as Face, position::BlockPos};
use horizon_world::{
    attachments::{AttachmentType, Holder},
    chunk::BlockState,
    nbt::{Compound, Tag},
    registry::BlockStateId,
};
use std::{cell::RefCell, collections::BTreeMap, ops::ControlFlow};

pub(super) const BLOCK: &str = "create:portable_storage_interface";
const STALLED_DOCK: &str = "create_horizon:StalledItemDock";

#[derive(Clone, Default)]
struct Runtime {
    docks: BTreeMap<Pos, Station>,
    movers: BTreeMap<Pos, Moving>,
}

#[derive(Clone, Default)]
struct Moving {
    actor: Actor,
    previous: Option<Probe>,
    motion: [f64; 3],
    visited: bool,
    refresh: bool,
    advanced_at: Option<i64>,
}

const LINKS: AttachmentType<Runtime> = AttachmentType {
    namespace: "create",
    name: "portable_storage_links",
    default: Runtime::default,
    codec: None,
    copy_on_death: false,
    sync: false,
};

fn load(game: &mut Game<'_>, key: [i32; 2]) -> Option<Runtime> {
    let map = game.attachment_map_quiet(Holder::Chunk(key)).ok()?;
    Some(map.get_existing(&LINKS).ok()?.unwrap_or_default())
}

fn save(game: &mut Game<'_>, key: [i32; 2], runtime: Runtime) {
    if let Ok(map) = game.attachment_map_quiet(Holder::Chunk(key)) {
        if runtime.docks.is_empty() && runtime.movers.is_empty() {
            let _ = map.remove(&LINKS);
        } else {
            let _ = map.set(&LINKS, runtime);
        }
    }
}

fn read_nbt(nbt: &Compound) -> Station {
    let timer = u32::try_from(super::create_port::integer(nbt, "Timer")).unwrap_or(0);
    let distance = super::create_port::number(nbt, "Distance");
    let powered = super::create_port::integer(nbt, "Powered") != 0;
    Station::from_saved(timer, distance, powered).unwrap_or_default()
}

fn write_nbt(entity: &mut ModBlockEntity, station: Station) {
    entity
        .nbt
        .insert("Timer".into(), Tag::Int(station.timer() as i32));
    entity
        .nbt
        .insert("Distance".into(), Tag::Float(station.distance().to_bits()));
    entity
        .nbt
        .insert("Powered".into(), Tag::Byte(i8::from(station.powered())));
}

fn remember(runtime: &mut Runtime, pos: Pos, station: Station) {
    if station.owner().is_some() || station.timer() != 0 {
        runtime.docks.insert(pos, station);
    } else {
        runtime.docks.remove(&pos);
    }
}

fn powered(game: &mut Game<'_>, pos: Pos) -> bool {
    game.native_neighbor_signal(game.dim.id(), pos) > 0
}

fn endpoint(game: &mut Game<'_>, key: [i32; 2], pos: Pos) -> Option<Endpoint> {
    if contraption::column(pos) != key || game.native_block(pos) != BLOCK {
        return None;
    }
    station_entity(game, pos)?;
    Some(Endpoint {
        facing: contraption::facing(game, pos)?,
        powered: powered(game, pos),
    })
}

fn station_entity<'g>(game: &'g Game<'_>, pos: Pos) -> Option<&'g ModBlockEntity> {
    match game.world.block_entities.get(&(pos[0], pos[1], pos[2]))? {
        BlockEntity::Mod(entity) if entity.id == BLOCK => Some(entity),
        _ => None,
    }
}

fn station_at(game: &Game<'_>, runtime: &Runtime, pos: Pos) -> Option<Station> {
    Some(reconcile(
        runtime.docks.get(&pos).copied(),
        read_nbt(&station_entity(game, pos)?.nbt),
    ))
}

fn reconcile(live: Option<Station>, saved: Station) -> Station {
    live.filter(|live| {
        live.timer() == saved.timer()
            && live.distance() == saved.distance()
            && live.powered() == saved.powered()
    })
    .unwrap_or(saved)
}

pub(super) fn block_state(state: &BlockState) -> bool {
    state.name == BLOCK && state.properties.len() == 1 && local_facing(state).is_some()
}

pub(super) fn has_multiple(blocks: &[(Pos, BlockState)]) -> bool {
    blocks
        .iter()
        .filter(|(_, state)| state.name == BLOCK)
        .nth(1)
        .is_some()
}

fn local_facing(state: &BlockState) -> Option<Direction> {
    let facing = state.properties.get("facing")?;
    Direction::ALL
        .into_iter()
        .find(|direction| direction.name() == facing)
}

pub(super) fn can_capture(game: &Game<'_>, pos: Pos, state: &BlockState) -> bool {
    let key = (pos[0], pos[1], pos[2]);
    if !block_state(state)
        || !station_entity(game, pos).is_some_and(|entity| {
            entity.items.iter().all(Option::is_none)
                && entity.nbt.iter().all(|(key, value)| {
                    clean_field(key.to_string().as_deref().unwrap_or_default(), value)
                })
        })
        || game.world.block_names.contains_key(&key)
        || game.world.block_lock(key).is_some()
    {
        return false;
    }
    let [x, z] = contraption::column(pos);
    if game
        .world
        .block_entities
        .chunk_attachments(x, z)
        .iter()
        .any(|(p, _)| *p == key)
    {
        return false;
    }
    game.world
        .chunks
        .get(&(x, z))
        .and_then(|chunk| chunk.saved.as_ref())
        .is_none_or(|saved| {
            !saved.rolled_loot.iter().any(|loot| loot.pos == key)
                && !saved
                    .block_entity_attachments
                    .iter()
                    .any(|(p, _)| *p == key)
                && saved
                    .block_entity_sources
                    .iter()
                    .find(|(p, _)| *p == key)
                    .is_none_or(|(_, tag)| clean_source(tag))
        })
}

fn clean_field(name: &str, value: &Tag) -> bool {
    match name {
        "Timer" => *value == Tag::Int(0),
        "Distance" => {
            matches!(value, Tag::Float(bits) if (0.0..=2.0).contains(&f32::from_bits(*bits)))
        }
        "Powered" => matches!(value, Tag::Byte(0 | 1)),
        _ => false,
    }
}

fn clean_source(source: &Tag) -> bool {
    let Tag::Compound(fields) = source else {
        return false;
    };
    fields
        .iter()
        .all(|(key, value)| match key.to_string().as_deref() {
            Ok("id") => *value == Tag::String(BLOCK.into()),
            Ok("x" | "y" | "z") => matches!(value, Tag::Int(_)),
            Ok("keepPacked") => *value == Tag::Byte(0),
            Ok("components") => matches!(value, Tag::Compound(fields) if fields.is_empty()),
            Ok("Items") => matches!(value, Tag::List(items) if items.is_empty()),
            Ok(name) => clean_field(name, value),
            Err(_) => false,
        })
}

fn probe(record: &Record, local: Pos, facing: Direction) -> Option<Probe> {
    let rotation = record.orientation(record.angle);
    let center = DVec3::splat(0.5);
    let local = DVec3::from_array(Probe::local_center(local, facing)) - center;
    let point = DVec3::from_array(record.origin_at(1.0)) + center + rotation * local;
    let direction = rotation * DVec3::from_array(facing.vector().map(f64::from));
    Probe::new(point.to_array(), direction.to_array())
}

pub(super) fn mover(record: &Record) -> Option<(Pos, Direction)> {
    if (record.axis != Axis::Y.index() && record.stroke_kind() != Some(StrokeKind::Gantry))
        || record.clock_hand.is_some()
        || record.return_home
        || record.blocks.len() > MAX_BLOCKS
    {
        return None;
    }
    let (local, state) = record
        .blocks
        .iter()
        .find(|(_, state)| state.name == BLOCK)?;
    Some((*local, local_facing(state)?))
}

pub(super) fn saved_dock(entity: &ModBlockEntity) -> Option<Pos> {
    match entity.nbt.get(&STALLED_DOCK.into()) {
        Some(Tag::IntArray(pos)) => Pos::try_from(pos.as_slice()).ok(),
        _ => None,
    }
}

pub(super) fn save_dock(entity: &mut ModBlockEntity, dock: Option<Pos>) {
    if let Some(pos) = dock {
        if saved_dock(entity) != dock {
            entity
                .nbt
                .insert(STALLED_DOCK.into(), Tag::IntArray(pos.to_vec()));
        }
    } else {
        entity.nbt.remove(&STALLED_DOCK.into());
    }
}

fn publish(game: &mut Game<'_>, pos: Pos, station: Station, sync: bool, compare: bool) {
    if game
        .native_with_mod_block_entity(pos, |entity| write_nbt(entity, station))
        .is_none()
    {
        return;
    }
    if sync {
        game.native_block_entity_sync(pos);
    }
    if compare {
        game.native_update_output_neighbors(game.dim.id(), pos);
    }
}

/// The original controlled entity visits its dock before the stationary
/// block entity ticks, regardless of the order in which they were loaded.
pub(super) fn tick_piston_docks(game: &mut Game<'_>) {
    let ticking = game.block_ticking_area();
    let mut active = Vec::new();
    for chunk in game.world.chunks.values() {
        let Ok(records) = read(chunk) else {
            continue;
        };
        for record in records.iter() {
            let [x, y, z] = record.controller;
            if record.stroke_kind() != Some(StrokeKind::Piston)
                || !ticking(x, z)
                || !game.border.contains(f64::from(x), f64::from(z))
                || mover(record).is_none()
                || !contraption::controller_present(game, record)
            {
                continue;
            }
            if let Some(BlockEntity::Mod(entity)) = game.world.block_entities.get(&(x, y, z)) {
                active.push((record.clone(), saved_dock(entity)));
            }
        }
    }
    active.sort_unstable_by_key(|(record, _)| record.controller);
    for (record, saved) in active {
        advance(game, &record, saved);
    }
}

/// Sample the previously published pose before the controller moves it again,
/// in the same order as the original contraption entity and controller ticks.
pub(super) fn advance(
    game: &mut Game<'_>,
    record: &Record,
    saved_dock: Option<Pos>,
) -> Option<Pos> {
    let (local, facing) = mover(record)?;
    let key = contraption::column(record.controller);
    let mut runtime = load(game, key)?;
    let time = game.world.game_time;
    if let Some(moving) = runtime.movers.get(&record.controller)
        && moving.advanced_at == Some(time)
    {
        return moving.actor.working().filter(|_| moving.actor.stalled());
    }
    let current = probe(record, local, facing);
    let mut moving = runtime
        .movers
        .remove(&record.controller)
        .unwrap_or_else(|| {
            let Some((saved, current)) = saved_dock.zip(current).filter(|_| record.stalled) else {
                return Moving::default();
            };
            let dock = current.find(|pos| {
                if pos == saved {
                    endpoint(game, key, pos)
                } else {
                    None
                }
            });
            if dock.is_none() {
                return Moving::default();
            }
            Moving {
                actor: Actor::resume_stall(saved),
                visited: true,
                ..Moving::default()
            }
        });
    let visit = if let Some((old, current)) = moving.previous.zip(current)
        && !moving.actor.stalled()
    {
        moving.motion = std::array::from_fn(|i| current.position()[i] - old.position()[i]);
        !moving.visited || old.grid() != current.grid()
    } else {
        false
    };
    if (visit || moving.refresh)
        && let Some(dock) = moving.actor.visit(current, |pos| endpoint(game, key, pos))
        && let Some(mut station) = station_at(game, &runtime, dock.position)
    {
        let _ = station.set_powered(false);
        if station.start(record.controller, dock.distance) {
            remember(&mut runtime, dock.position, station);
            publish(game, dock.position, station, true, true);
        }
    }
    moving.visited |= visit;
    moving.refresh = false;
    moving.previous = current;
    moving.advanced_at = Some(time);
    if let Some((pos, end, mut station)) = moving.actor.working().and_then(|pos| {
        Some((
            pos,
            endpoint(game, key, pos)?,
            station_at(game, &runtime, pos)?,
        ))
    }) {
        let started = moving.actor.tick(
            record.controller,
            current,
            moving.motion,
            Some((end, &mut station)),
        );
        remember(&mut runtime, pos, station);
        if started {
            publish(game, pos, station, true, true);
        }
    } else {
        moving.actor.reset();
    }
    let stalled = moving.actor.working().filter(|_| moving.actor.stalled());
    runtime.movers.insert(record.controller, moving);
    save(game, key, runtime);
    stalled
}

pub(super) fn remove(game: &mut Game<'_>, owner: Pos) {
    let key = contraption::column(owner);
    let Some(mut runtime) = load(game, key) else {
        return;
    };
    runtime.movers.remove(&owner);
    for station in runtime.docks.values_mut() {
        if station.owner() == Some(owner) {
            station.disconnect();
        }
    }
    save(game, key, runtime);
}

pub(super) fn stop_motion(game: &mut Game<'_>, owner: Pos) {
    let key = contraption::column(owner);
    let Some(mut runtime) = load(game, key) else {
        return;
    };
    if let Some(moving) = runtime.movers.get_mut(&owner) {
        // Contraption.stop clears pose and motion; the PSI keeps its dock.
        moving.previous = None;
        moving.motion = [0.0; 3];
        save(game, key, runtime);
    }
}

pub(super) fn tick(game: &mut Game<'_>, pos: Pos, entity: &mut ModBlockEntity) {
    let key = contraption::column(pos);
    let Some(mut runtime) = load(game, key) else {
        return;
    };
    let old = read_nbt(&entity.nbt);
    let mut station = reconcile(runtime.docks.remove(&pos), old);
    let power = station.set_powered(powered(game, pos));
    if power == PowerUpdate::RefreshActors
        || (!station.powered() && !entity.nbt.contains_key(&"Timer".into()))
    {
        for moving in runtime.movers.values_mut() {
            moving.refresh = true;
        }
    }
    let update = station.tick(DEFAULT_TIMEOUT);
    remember(&mut runtime, pos, station);
    save(game, key, runtime);
    write_nbt(entity, station);
    if power != PowerUpdate::Unchanged
        || matches!(
            update,
            TickUpdate::Sync | TickUpdate::Disconnect { sync: true }
        )
        || (old.timer() <= 4 && old.timer() != station.timer())
    {
        game.native_block_entity_sync(pos);
    }
    // A powered station notifies neighbours on each ordinary countdown
    // decrement. The keepalive expiry writes its retract timer after the
    // notification, so the first off-state query comes on the next tick.
    let powered_stop = station.powered()
        && !station.connected(DEFAULT_TIMEOUT)
        && matches!(update, TickUpdate::Disconnect { sync: false });
    if old.timer() != 0 && (station.timer() == 0 || powered_stop) {
        game.native_update_output_neighbors(game.dim.id(), pos);
    }
}

pub(super) fn analog(game: &GameLevel<'_>, pos: BlockPos, state: BlockStateId, output: &mut i32) {
    if game.native_state_block(state) != Some(BLOCK) {
        return;
    }
    *output = match game.world.block_entities.get(&(pos.x, pos.y, pos.z)) {
        Some(BlockEntity::Mod(entity)) => i32::from(read_nbt(&entity.nbt).signal(DEFAULT_TIMEOUT)),
        _ => 0,
    };
}

fn draw_parts(
    game: &Game<'_>,
    draw: &mut BlockEntityDraw,
    facing: Direction,
    extension: f32,
    lit: bool,
) {
    draw.push();
    match facing {
        Direction::Up => {}
        Direction::Down => draw.rotate_about([1.0, 0.0, 0.0], 180.0, [0.5; 3]),
        _ => {
            super::create_port::face_south(draw, facing);
            draw.rotate_about([1.0, 0.0, 0.0], 90.0, [0.5; 3]);
        }
    }
    draw.push();
    draw.translate([0.0, extension / 2.0 + 0.375, 0.0]);
    let middle = if lit {
        "create:block/portable_storage_interface/block_middle_powered"
    } else {
        "create:block/portable_storage_interface/block_middle"
    };
    game.native_draw_model(draw, middle, 0xFFFFFF);
    draw.pop();
    draw.translate([0.0, extension, 0.0]);
    game.native_draw_model(
        draw,
        "create:block/portable_storage_interface/block_top",
        0xFFFFFF,
    );
    draw.pop();
}

struct StationFrame {
    owner: ModRevision,
    previous: f32,
    progress: f32,
    tick: i64,
}

struct MovingFrame {
    anchor: Pos,
    local: Pos,
    facing: Direction,
    head: MovingHead,
    tick: i64,
}

#[derive(Default)]
struct ClientVisuals {
    tick: Option<i64>,
    stations: BTreeMap<Pos, StationFrame>,
    moving: BTreeMap<Pos, MovingFrame>,
}

thread_local! {
    static VISUALS: RefCell<SessionCache<ClientVisuals>> = RefCell::new(SessionCache::default());
}

fn with_visuals<R>(game: &Game<'_>, f: impl FnOnce(&mut ClientVisuals) -> R) -> R {
    VISUALS.with_borrow_mut(|cache| {
        f(cache.dimension(std::ptr::from_ref(&game.world) as usize, game.dim.id()))
    })
}

pub(super) fn client_tick(game: &Game<'_>) {
    if game.remote.is_none() {
        VISUALS.with_borrow_mut(SessionCache::clear);
        return;
    }
    let tick = game.world.game_time;
    with_visuals(game, |visuals| {
        if visuals.tick == Some(tick) {
            return;
        }
        if visuals.tick.is_some_and(|old| old > tick) {
            *visuals = ClientVisuals::default();
        }
        visuals.tick = Some(tick);
        for (&(x, y, z), block) in game.world.block_entities.iter() {
            let BlockEntity::Mod(entity) = block else {
                continue;
            };
            if entity.id != BLOCK {
                continue;
            }
            let station = read_nbt(&entity.nbt);
            let progress = station.animation_progress(DEFAULT_TIMEOUT);
            let pos = [x, y, z];
            let owner = entity.revision();
            let previous = visuals
                .stations
                .get(&pos)
                .filter(|frame| frame.owner.is_same_create_entity(owner))
                .map_or(0.0, |frame| frame.progress);
            if previous != 0.0 || progress != 0.0 {
                visuals.stations.insert(
                    pos,
                    StationFrame {
                        owner,
                        previous,
                        progress,
                        tick,
                    },
                );
            }
        }
        visuals.stations.retain(|_, frame| frame.tick == tick);
        for chunk in game.world.chunks.values().filter(|chunk| {
            chunk
                .saved
                .as_ref()
                .is_some_and(|saved| saved.attachments.has(&RECORDS))
        }) {
            let Ok(records) = read(chunk) else { continue };
            for record in records.iter() {
                let Some((local, facing)) = mover(record) else {
                    continue;
                };
                let mut frame = MovingFrame {
                    anchor: record.anchor,
                    local,
                    facing,
                    head: MovingHead::default(),
                    tick,
                };
                if let Some(old) = visuals.moving.get(&record.controller)
                    && old.anchor == frame.anchor
                    && old.local == local
                    && old.facing == facing
                {
                    frame.head = old.head;
                }
                let dock = probe(record, local, facing).and_then(|probe| {
                    probe.find(|pos| {
                        if contraption::column(pos) != contraption::column(record.controller) {
                            return None;
                        }
                        let station = read_nbt(&station_entity(game, pos)?.nbt);
                        Some(Endpoint {
                            facing: contraption::facing(game, pos)?,
                            powered: station.powered(),
                        })
                    })
                });
                let stationary = record.stalled
                    || record
                        .stroke
                        .map_or(record.angle == record.previous_angle, |stroke| {
                            stroke.offset == stroke.previous
                        });
                let target = match dock {
                    Some(dock) if stationary => station_entity(game, dock.position)
                        .map(|entity| read_nbt(&entity.nbt).distance() / 2.0),
                    Some(_) => None,
                    None => Some(0.0),
                };
                frame.head.tick(target);
                visuals.moving.insert(record.controller, frame);
            }
        }
        visuals.moving.retain(|_, frame| frame.tick == tick);
    });
}

pub(super) fn draw_station(
    game: &Game<'_>,
    pos: Pos,
    entity: &ModBlockEntity,
    draw: &mut BlockEntityDraw,
) {
    if let Some(facing) = contraption::facing(game, pos) {
        let station = read_nbt(&entity.nbt);
        let progress = with_visuals(game, |visuals| {
            visuals
                .stations
                .get(&pos)
                .filter(|frame| frame.owner.is_same_create_entity(entity.revision()))
                .map_or(0.0, |frame| {
                    frame.previous + (frame.progress - frame.previous) * draw.partial
                })
        });
        let extension = stationary_extension(progress, station.distance());
        trace_head(
            game,
            pos,
            false,
            extension,
            station.connected(DEFAULT_TIMEOUT),
            station.timer(),
        );
        draw_parts(
            game,
            draw,
            facing,
            extension,
            station.connected(DEFAULT_TIMEOUT),
        );
    }
}

pub(super) fn draw_moving(
    game: &Game<'_>,
    draw: &mut BlockEntityDraw,
    record: &Record,
    local: Pos,
    state: &BlockState,
) {
    let Some(facing) = local_facing(state) else {
        return;
    };
    let head = with_visuals(game, |visuals| {
        visuals
            .moving
            .get(&record.controller)
            .filter(|frame| {
                frame.anchor == record.anchor && frame.local == local && frame.facing == facing
            })
            .map_or_else(MovingHead::default, |frame| frame.head)
    });
    let extension = head.extension(draw.partial);
    trace_head(game, record.controller, true, extension, head.settled(), 0);
    draw_parts(game, draw, facing, extension, head.settled());
}

fn trace_head(game: &Game<'_>, pos: Pos, moving: bool, extension: f32, lit: bool, timer: u32) {
    static TRACE: std::sync::OnceLock<bool> = std::sync::OnceLock::new();
    if *TRACE.get_or_init(|| std::env::var_os("CREATE_HORIZON_TRACE_DOCK").is_some()) {
        log::info!(
            "Create dock head: {}",
            serde_json::json!({
                "pos": pos, "moving": moving, "extension": extension, "lit": lit,
                "timer": timer, "tick": game.world.game_time,
            })
        );
    }
}

fn connected_mount(game: &mut Game<'_>, pos: Pos) -> Option<(Runtime, Station, storage::Mount)> {
    let key = contraption::column(pos);
    if !game.native_on("create") || game.native_block(pos) != BLOCK || powered(game, pos) {
        return None;
    }
    let runtime = load(game, key)?;
    let station = station_at(game, &runtime, pos).filter(|s| s.can_transfer(DEFAULT_TIMEOUT))?;
    let owner = station
        .owner()
        .filter(|owner| contraption::column(*owner) == key)?;
    let records = contraption::entries(game, key).ok()?;
    let record = records.iter().find(|record| record.controller == owner)?;
    let controller = game.native_block(owner);
    let drives_mover = match record.stroke_kind() {
        None => controller == contraption::BLOCK,
        Some(StrokeKind::RopePulley) => controller == super::create_port_pulley::BLOCK,
        Some(StrokeKind::Piston) => {
            super::create_port_piston::is_piston(&controller)
                && game.native_block_property(owner, "state").as_deref() == Some("moving")
        }
        Some(StrokeKind::Gantry) => record.stroke.is_some_and(|stroke| !stroke.waiting),
    };
    if !drives_mover || mover(record).is_none() {
        return None;
    }
    Some((runtime, station, storage::mounted_chest(record)?))
}

fn finish_transfer(
    game: &mut Game<'_>,
    pos: Pos,
    mut runtime: Runtime,
    mut station: Station,
    count: u32,
) {
    if station.transferred(DEFAULT_TIMEOUT, count, false) {
        remember(&mut runtime, pos, station);
        save(game, contraption::column(pos), runtime);
        publish(game, pos, station, true, false);
    }
}

fn withdraw(
    game: &mut Game<'_>,
    pos: Pos,
    take: impl FnOnce(&mut Game<'_>, storage::Mount) -> Option<ItemStack>,
) -> Option<ItemStack> {
    let (runtime, station, mount) = connected_mount(game, pos)?;
    let item = take(game, mount)?;
    finish_transfer(game, pos, runtime, station, item.count);
    Some(item)
}

pub(super) fn push_chute(
    game: &mut Game<'_>,
    station_pos: Pos,
    source: Pos,
    stack: &ItemStack,
    simulate: bool,
) -> u32 {
    let Some((runtime, station, mount)) = connected_mount(game, station_pos) else {
        return 0;
    };
    let inserted = storage::insert_from_chute(game, mount, source, stack, simulate);
    if !simulate && inserted != 0 {
        finish_transfer(game, station_pos, runtime, station, inserted);
    }
    inserted
}

pub(super) fn pull_chute(
    game: &mut Game<'_>,
    station: Pos,
    receive: impl FnOnce(&mut Game<'_>, &ItemStack) -> bool,
) -> bool {
    withdraw(game, station, |game, mount| {
        storage::withdraw_for_chute(game, mount, receive)
    })
    .is_some()
}

pub(super) fn hopper_suck(game: &mut Game<'_>, hopper: Pos) -> ControlFlow<bool> {
    let pos = [hopper[0], hopper[1] + 1, hopper[2]];
    let pulled = withdraw(game, pos, |game, mount| {
        let slots = game.native_container_slots(game.dim.id(), hopper, Face::Up)?;
        let limits: Vec<_> = slots
            .into_iter()
            .map(|slot| {
                slot.stack.map(|stack| {
                    let limit = super::create_port::stack_maximum(game, &stack);
                    (stack, limit)
                })
            })
            .collect();
        storage::withdraw_one(
            game,
            mount,
            |candidate| {
                limits.iter().any(|slot| match slot {
                    None => true,
                    Some((stack, limit)) => {
                        stack.count == 0
                            || (stack.count < *limit && stack.same_item_same_components(candidate))
                    }
                })
            },
            |game, item| {
                game.native_insert_item(hopper, Face::Up, item.clone())
                    .is_none()
            },
        )
    })
    .is_some();
    if pulled {
        ControlFlow::Break(true)
    } else {
        ControlFlow::Continue(())
    }
}
