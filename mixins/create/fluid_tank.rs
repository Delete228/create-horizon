// Copyright (c) The Create Team / The Creators of Create
// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT
// Ordinary FluidTankBlockEntity storage, topology and visual adapter.
use super::{
    Dim, Game, GameLevel,
    create_port_basin::{core_fluid, native_fluid},
    create_port_basin_recipes::emptying,
    create_port_block_entity_revision::EntityRevision as _,
    create_port_fluid_codec as fluids,
    native_block_entity_draw::BlockEntityDraw,
};
use crate::{
    containers::{BlockEntity, ModBlockEntity, ModRevision},
    world::World,
};
use create_engine::{
    basin as rules,
    fluid_tank::{self as geometry, Pos, Tank},
    fluid_transport::Fluid as FluidKind,
    transport::SessionCache,
};
use horizon_client::mod_api::{
    NativeFluidAction, NativeFluidDrain, NativeFluidRenderOptions, NativeFluidStack,
    NativeFluidTankView,
};
use horizon_core::random::RandomSource;
use horizon_world::{
    attachments::{AttachmentCodec, AttachmentError, AttachmentType, Holder},
    level::flags,
    nbt::{Compound, Tag},
};
use std::{
    cell::{Cell, RefCell},
    collections::{BTreeMap, BTreeSet, VecDeque},
    sync::{
        Arc, RwLock,
        atomic::{AtomicU32, Ordering},
    },
    thread::{self, ThreadId},
};

pub(in crate::game) const BLOCK: &str = "create:fluid_tank";
// The saved stack can exceed the current fill limit, for example after a
// capacity config change. Create still lets a pipe or bucket drain it.
pub(super) const SAVED_AMOUNT_LIMIT: u32 = i32::MAX as u32;
const CAPACITY_UPDATE: &str = "create_horizon_tank_capacity";
const BUCKET: i32 = 1000;
const LIGHT: &str = "create_light";
const CONNECTIONS: &str = "create_connections";
const VISUAL_UPDATE: i32 =
    flags::UPDATE_CLIENTS | flags::UPDATE_INVISIBLE | flags::UPDATE_KNOWN_SHAPE;

fn light_state(window: bool, luminosity: i32) -> &'static str {
    match (window, luminosity) {
        (true, 1) => "1",
        (true, 12) => "12",
        _ => "0",
    }
}
type Fluid = rules::Fluid<fluids::Key>;

#[derive(Clone, PartialEq)]
pub(super) struct Record {
    pub(super) tank: Tank,
    pub(super) part_capacity: u32,
    pub(super) window: bool,
    pub(super) fluid: Option<Fluid>,
}

impl Record {
    pub(super) fn capacity(&self) -> u32 {
        self.tank
            .volume()
            .saturating_mul(self.part_capacity)
            .min(SAVED_AMOUNT_LIMIT)
    }

    pub(super) fn fraction(&self) -> f32 {
        self.fluid
            .as_ref()
            .map_or(0.0, |f| f.amount as f32 / self.capacity() as f32)
    }

    fn luminosity(&self, pos: Pos) -> i32 {
        if self
            .fluid
            .as_ref()
            .is_none_or(|f| f.key.id != "minecraft:lava")
        {
            return 0;
        }
        let layer = pos[1] - self.tank.root[1];
        let lit = (self.fraction() * self.tank.height() as f32 + 1.0) as i32;
        if layer < lit { 12 } else { 1 }
    }
}

struct CapacityBinding {
    level: (usize, Dim),
    thread: ThreadId,
    pos: Pos,
    part: u32,
    config: Arc<AtomicU32>,
}

// Creation and connectivity bind capacity on the server. Update tags may
// be encoded by a worker, so use the stable entity identity across threads.
static CAPACITIES: RwLock<BTreeMap<u64, CapacityBinding>> = RwLock::new(BTreeMap::new());

fn configured_capacity() -> u32 {
    super::create_port_server_config::fluid_tank_capacity()
}

pub(super) fn read_capacity(value: Option<&Tag>) -> Option<u32> {
    match value {
        None => Some(geometry::BLOCK_CAPACITY),
        Some(Tag::Int(amount)) if *amount > 0 => Some(*amount as u32),
        _ => None,
    }
}

fn bound_capacity(entity: &ModBlockEntity) -> Option<u32> {
    CAPACITIES
        .read()
        .unwrap_or_else(|error| error.into_inner())
        .get(&entity.revision().create_entity_identity())
        .map(|binding| binding.part)
}

fn bind_capacity(game: &Game<'_>, pos: Pos, owner: ModRevision, part: u32) {
    CAPACITIES
        .write()
        .unwrap_or_else(|error| error.into_inner())
        .insert(
            owner.create_entity_identity(),
            CapacityBinding {
                level: (std::ptr::from_ref(&game.world) as usize, game.dim),
                thread: thread::current().id(),
                pos,
                part,
                config: super::create_port_server_config::fluid_tank_capacity_source(),
            },
        );
}

#[derive(Clone, Default, PartialEq)]
struct Break {
    removed: BTreeSet<Pos>,
    snapshot: Option<Record>,
}

type Breaks = BTreeMap<Pos, Break>;
const SAVED_BREAKS: AttachmentType<Breaks> = AttachmentType {
    namespace: "create",
    name: "fluid_tank_pending_splits",
    default: BTreeMap::new,
    codec: Some(AttachmentCodec {
        encode: write_breaks,
        decode: read_breaks,
    }),
    copy_on_death: false,
    sync: false,
};

fn write_breaks(breaks: &Breaks) -> Result<Compound, AttachmentError> {
    let pos_tag = |pos: Pos| Tag::IntArray(pos.to_vec());
    let rows = breaks
        .iter()
        .map(|(&root, entry)| {
            let mut row = Compound::from([
                ("Root".into(), pos_tag(root)),
                (
                    "Removed".into(),
                    Tag::List(entry.removed.iter().copied().map(pos_tag).collect()),
                ),
            ]);
            if let Some(record) = &entry.snapshot {
                let content = fluids::write_content(record.fluid.as_ref(), SAVED_AMOUNT_LIMIT)
                    .map_err(|_| AttachmentError::Encode)?;
                row.insert("Size".into(), Tag::Int(record.tank.width()));
                row.insert("Height".into(), Tag::Int(record.tank.height()));
                row.insert("Window".into(), Tag::Byte(i8::from(record.window)));
                if record.part_capacity != geometry::BLOCK_CAPACITY {
                    row.insert("PartCapacity".into(), Tag::Int(record.part_capacity as i32));
                }
                row.insert("TankContent".into(), content);
            }
            Ok(Tag::Compound(row))
        })
        .collect::<Result<Vec<_>, AttachmentError>>()?;
    Ok(Compound::from([("Splits".into(), Tag::List(rows))]))
}

fn read_breaks(nbt: &Compound) -> Result<Breaks, AttachmentError> {
    let invalid = AttachmentError::Decode;
    let pos = |tag: &Tag| match tag {
        Tag::IntArray(pos) => <Pos>::try_from(pos.as_slice()).ok(),
        _ => None,
    };
    let Some(Tag::List(rows)) = nbt.get(&"Splits".into()) else {
        return Err(invalid);
    };
    let mut breaks = Breaks::new();
    for row in rows {
        let root = pos(row.get("Root").ok_or(invalid)?).ok_or(invalid)?;
        let Some(Tag::List(removed)) = row.get("Removed") else {
            return Err(invalid);
        };
        let removed = removed
            .iter()
            .map(pos)
            .collect::<Option<BTreeSet<_>>>()
            .ok_or(invalid)?;
        let snapshot = match (row.get("Size"), row.get("Height"), row.get("Window")) {
            (None, None, None) if row.get("TankContent").is_none() => None,
            (Some(Tag::Int(width)), Some(Tag::Int(height)), Some(Tag::Byte(window @ (0 | 1)))) => {
                let tank = Tank::new(root, *width, *height)
                    .filter(|tank| {
                        tank.volume() > 1 && removed.iter().all(|&pos| tank.contains(pos))
                    })
                    .ok_or(invalid)?;
                Some(Record {
                    tank,
                    part_capacity: read_capacity(row.get("PartCapacity")).ok_or(invalid)?,
                    window: *window != 0,
                    fluid: fluids::read_content(row.get("TankContent"), SAVED_AMOUNT_LIMIT)
                        .map_err(|_| invalid)?,
                })
            }
            _ => return Err(invalid),
        };
        if removed.is_empty() || breaks.insert(root, Break { removed, snapshot }).is_some() {
            return Err(invalid);
        }
    }
    Ok(breaks)
}

fn merge_breaks(old: &mut Breaks, new: Breaks) {
    for (root, new) in new {
        let old = old.entry(root).or_default();
        if old.snapshot.is_none() {
            old.snapshot = new.snapshot;
        }
        old.removed.extend(new.removed);
    }
}

#[derive(Default)]
struct Pending {
    placed: Vec<Pos>,
    broken: Breaks,
    visual_states: BTreeSet<Pos>,
}

#[derive(Default)]
struct RenderLevel {
    tank: Option<Tank>,
    owner: Option<ModRevision>,
    tick: Option<i64>,
    chase: rules::FluidLevel,
}

thread_local! {
    static PENDING: RefCell<SessionCache<Pending>> = RefCell::new(SessionCache::default());
    static RENDER: RefCell<SessionCache<BTreeMap<Pos, RenderLevel>>> = RefCell::new(SessionCache::default());
}

pub(super) fn reset() {
    RENDER.with(|cache| cache.borrow_mut().clear());
    PENDING.with(|cache| cache.borrow_mut().clear());
    let current = thread::current().id();
    CAPACITIES
        .write()
        .unwrap_or_else(|error| error.into_inner())
        .retain(|_, binding| binding.thread != current);
}

pub(in crate::game) fn default_nbt() -> Compound {
    Compound::from([
        (
            "Boiler".into(),
            Tag::Compound(Compound::from([
                ("ActiveHeat".into(), Tag::Int(0)),
                ("Engines".into(), Tag::Int(0)),
                ("PassiveHeat".into(), Tag::Byte(0)),
                ("Supply".into(), Tag::Float(0)),
                ("Update".into(), Tag::Byte(0)),
                ("Whistles".into(), Tag::Int(0)),
            ])),
        ),
        ("Height".into(), Tag::Int(1)),
        ("Size".into(), Tag::Int(1)),
        ("Luminosity".into(), Tag::Int(0)),
        ("Window".into(), Tag::Byte(1)),
        ("TankContent".into(), Tag::Compound(Compound::new())),
    ])
}

fn ordinary(entity: &ModBlockEntity) -> bool {
    let Some(Tag::Compound(boiler)) = entity.nbt.get(&"Boiler".into()) else {
        return false;
    };
    entity.id == BLOCK
        && ["Engines", "Whistles"]
            .iter()
            .all(|key| matches!(boiler.get(&(*key).into()), Some(Tag::Int(0))))
}

fn root_of(entity: &ModBlockEntity, pos: Pos) -> Option<Pos> {
    if !ordinary(entity) {
        return None;
    }
    match entity.nbt.get(&"Controller".into()) {
        None => Some(pos),
        Some(Tag::IntArray(root))
            if !["Size", "Height", "Window", "TankContent"]
                .iter()
                .any(|key| entity.nbt.contains_key(&(*key).into())) =>
        {
            let root: Pos = root.as_slice().try_into().ok()?;
            (root != pos).then_some(root)
        }
        _ => None,
    }
}

fn client_root_of(entity: &ModBlockEntity, pos: Pos) -> Option<Pos> {
    if !ordinary(entity) {
        return None;
    }
    match entity.nbt.get(&"Controller".into()) {
        None => Some(pos),
        Some(Tag::IntArray(root)) if root.is_empty() => Some(pos),
        Some(Tag::IntArray(root)) => root.as_slice().try_into().ok(),
        _ => None,
    }
}

fn read(entity: &ModBlockEntity, pos: Pos) -> Option<Record> {
    (root_of(entity, pos)? == pos).then(|| {
        read_controller(
            entity,
            pos,
            bound_capacity(entity).unwrap_or_else(configured_capacity),
        )
    })?
}

fn read_client(entity: &ModBlockEntity, pos: Pos) -> Option<Record> {
    let capacity = read_capacity(entity.nbt.get(&CAPACITY_UPDATE.into()))?;
    (client_root_of(entity, pos)? == pos).then(|| read_controller(entity, pos, capacity))?
}

fn tank_geometry(nbt: &Compound, pos: Pos) -> Option<Tank> {
    let Some(Tag::Int(width)) = nbt.get(&"Size".into()) else {
        return None;
    };
    let Some(Tag::Int(height)) = nbt.get(&"Height".into()) else {
        return None;
    };
    Tank::new(pos, *width, *height)
}

fn read_controller(entity: &ModBlockEntity, pos: Pos, part_capacity: u32) -> Option<Record> {
    let nbt = &entity.nbt;
    let tank = tank_geometry(nbt, pos)?;
    let window = match nbt.get(&"Window".into())? {
        Tag::Byte(value @ (0 | 1)) => *value != 0,
        _ => return None,
    };
    let fluid = fluids::read_content(nbt.get(&"TankContent".into()), SAVED_AMOUNT_LIMIT).ok()?;
    Some(Record {
        tank,
        part_capacity,
        window,
        fluid,
    })
}

fn entity_at(world: &World, [x, y, z]: Pos) -> Option<&ModBlockEntity> {
    match world.block_entities.get(&(x, y, z))? {
        BlockEntity::Mod(entity) => Some(entity),
        _ => None,
    }
}

fn root_at(world: &World, pos: Pos) -> Option<Pos> {
    root_of(entity_at(world, pos)?, pos)
}

fn loaded(world: &World, tank: Tank) -> bool {
    tank.columns_loaded(|x, z| world.loaded(x, z))
}

fn resolve(
    world: &World,
    registry: &horizon_world::registry::BlockRegistry,
    pos: Pos,
    client: bool,
) -> Option<Record> {
    let is_tank = |[x, y, z]: Pos| {
        registry
            .state(world.block(x, y, z))
            .is_some_and(|s| s.name == BLOCK)
    };
    if !is_tank(pos) {
        return None;
    }
    let root_of = if client { client_root_of } else { root_of };
    let root = root_of(entity_at(world, pos)?, pos)?;
    if !is_tank(root) {
        return None;
    }
    let root_entity = entity_at(world, root)?;
    let record = if client {
        read_client(root_entity, root)?
    } else {
        read(root_entity, root)?
    };
    (record.tank.contains(pos) && loaded(world, record.tank)).then_some(record)
}

fn current(game: &Game<'_>, pos: Pos) -> Option<Record> {
    if game.options.execution_role.is_client() || !game.native_on("create") {
        return None;
    }
    resolve(&game.world, game.pack.assets.registry, pos, false)
}

fn complete(game: &Game<'_>, tank: Tank) -> bool {
    tank.parts()
        .all(|pos| game.native_block(pos) == BLOCK && root_at(&game.world, pos) == Some(tank.root))
}

fn remember_removal(world: &World, dimension: &str, pos: Pos) {
    let Some(root) = root_at(world, pos) else {
        return;
    };
    let snapshot = entity_at(world, root).and_then(|entity| read(entity, root));
    if snapshot
        .as_ref()
        .is_some_and(|record| record.tank.volume() == 1 || !record.tank.contains(pos))
        || (snapshot.is_none() && world.loaded(root[0], root[2]))
    {
        return;
    }
    PENDING.with(|cache| {
        let mut cache = cache.borrow_mut();
        let pending = cache.dimension(std::ptr::from_ref(world) as usize, dimension);
        let entry = pending.broken.entry(root).or_default();
        if entry.snapshot.is_none() {
            entry.snapshot = snapshot;
        }
        entry.removed.insert(pos);
    });
}

pub(super) fn changed(
    level: &GameLevel<'_>,
    dimension: &str,
    pos: Pos,
    was_tank: bool,
    is_tank: bool,
) {
    if was_tank && !is_tank {
        // LevelChunk writes the state before removing its block entity.
        remember_removal(level.world, dimension, pos);
    } else if !was_tank && is_tank {
        PENDING.with(|cache| {
            cache
                .borrow_mut()
                .dimension(std::ptr::from_ref(&*level.world) as usize, dimension)
                .placed
                .push(pos);
        });
    }
}

pub(super) fn before_command_replacement(
    game: &Game<'_>,
    pos: Pos,
    state: horizon_world::registry::BlockStateId,
) {
    if game.native_block(pos) == BLOCK
        && game
            .pack
            .assets
            .registry
            .state(state)
            .is_some_and(|state| state.name != BLOCK)
    {
        remember_removal(&game.world, game.dim.id(), pos);
    }
}

thread_local! {
    static LAYER_CLICK: Cell<Option<(Pos, i32)>> = const { Cell::new(None) };
}

pub(super) fn remember_layer_click(game: &Game<'_>, clicked: Pos, face: Pos) {
    let vertical = matches!(face, [0, 1 | -1, 0]);
    let tank = game
        .held()
        .is_some_and(|stack| stack.item.as_ref() == BLOCK);
    LAYER_CLICK.set(
        (vertical && tank && game.native_on("create") && !game.native_sneaking())
            .then_some((clicked, face[1])),
    );
}

/// FluidTankItem.tryMultiPlace after the first block is placed. Horizon's
/// place_block hook runs before the first shrink, so reserve that item.
pub(super) fn place_layer(game: &mut Game<'_>, first: Pos, item: &crate::items::ItemStack) {
    use horizon_core::{
        geometry::{Direction, Vec3},
        position::BlockPos,
    };
    use horizon_world::level::PlaceContext;

    let Some(([cx, cy, cz], dy)) = LAYER_CLICK.take() else {
        return;
    };
    if item.item.as_ref() != BLOCK
        || (first != [cx, cy, cz] && first != [cx, cy + dy, cz])
        || game.native_block(first) != BLOCK
    {
        return;
    }
    let Some(count) = game
        .held()
        .filter(|stack| stack.item.as_ref() == BLOCK)
        .map(|stack| stack.count)
    else {
        return;
    };
    if game
        .inventory
        .iter()
        .take(9)
        .flatten()
        .any(|stack| stack.item.as_ref() == "create:wand_of_symmetry")
    {
        return;
    }
    let [x, y, z] = first;
    let Some(Record { tank, .. }) = current(game, [x, y - dy, z]) else {
        return;
    };
    let [root_x, root_y, root_z] = tank.root;
    let layer_y = if dy == 1 {
        root_y + tank.height()
    } else {
        root_y - 1
    };
    if tank.width() == 1 || y != layer_y || !complete(game, tank) {
        return;
    }
    let Some(layer) = Tank::new([root_x, layer_y, root_z], tank.width(), 1) else {
        return;
    };
    let missing: Vec<_> = layer
        .parts()
        .filter(|&pos| game.native_block(pos) != BLOCK)
        .collect();
    if (!game.creative && count <= missing.len() as u32)
        || missing
            .iter()
            .any(|&pos| !super::create_port_generators::replaceable(game, pos))
    {
        return;
    }
    let face = if dy == 1 {
        Direction::Up
    } else {
        Direction::Down
    };
    for [x, y, z] in missing {
        let ctx = PlaceContext {
            clicked_pos: BlockPos::new(x, y, z),
            face,
            hit: Vec3::new(
                f64::from(x) + 0.5,
                f64::from(y) + (f64::from(dy) + 1.0) / 2.0,
                f64::from(z) + 0.5,
            ),
            inside: false,
            yaw: game.yaw,
            pitch: game.pitch,
            sneaking: false,
            item: BLOCK.into(),
            can_use_game_master_blocks: game.can_use_game_master_blocks(),
        };
        place_layer_part(game, &ctx, [x, y, z]);
    }
}

fn place_layer_part(game: &mut Game<'_>, ctx: &horizon_world::level::PlaceContext, pos: Pos) {
    use horizon_world::level::{LevelEvent, PlaceOutcome};

    let Some(stack) = game
        .held()
        .filter(|stack| stack.item.as_ref() == BLOCK && stack.count > 0)
        .cloned()
    else {
        return;
    };
    if game
        .lan_acting_spawn_protection
        .is_some_and(|radius| game.spawn_protects(radius, game.dim.id(), pos))
        || game.block_place_canceled(&stack, ctx)
    {
        return;
    }
    let events_before = game.level_events.len();
    let outcome = game.with_level(|behaviour, level, ticks| {
        if behaviour.directional_can_place(level, ticks, ctx) {
            behaviour.place_block(level, ticks, ctx)
        } else {
            PlaceOutcome::Failed
        }
    });
    if let PlaceOutcome::Placed {
        pos: placed,
        mut state,
    } = outcome
    {
        debug_assert_eq!(placed, ctx.clicked_pos);
        // FluidTankBlock's extra placements use SILENCED_METAL. Keep normal
        // placement game events and let the server deliver this sound.
        for event in game.level_events[events_before..].iter_mut().rev() {
            if let LevelEvent::Sound {
                pos: at,
                sound,
                volume,
                pitch,
            } = event
                && *at == placed
            {
                *sound = "minecraft:block.metal.place".into();
                *volume = 0.55;
                *pitch = 1.2;
                break;
            }
        }
        match game.apply_item_block_state(pos, state, &stack) {
            Ok(updated) => state = updated,
            Err(error) => log::warn!("Fluid Tank layer block state: {error}"),
        }
        if !game.world.block_entities.stateful_entity(state.0)
            && let Some(entity) = game.new_block_entity_for_state(state)
        {
            game.world
                .block_entities
                .insert((pos[0], pos[1], pos[2]), entity);
        }
        let game_master = game.can_use_game_master_blocks();
        game.apply_placed_item(pos, &stack, game_master);
        game.trigger_block("minecraft:placed_block", pos, &stack);
        game.native_place_block(&stack, pos, state);
        game.consume_held();
    }
    if let Err(error) = game.process_level_events() {
        log::warn!("Fluid Tank layer placement: {error}");
    }
}

pub(super) fn tick(game: &mut Game<'_>, pos: Pos, entity: &mut ModBlockEntity) {
    if !ordinary(entity) {
        return;
    }
    if root_of(entity, pos) == Some(pos) && bound_capacity(entity).is_none() {
        let part = configured_capacity();
        bind_capacity(game, pos, entity.revision(), part);
        if part != geometry::BLOCK_CAPACITY {
            game.native_block_entity_sync(pos);
        }
    }
    if let Some(root) = root_of(entity, pos)
        && let Some(owner) = if root == pos {
            Some(&*entity)
        } else {
            entity_at(&game.world, root)
        }
        && let Some(Tag::Int(luminosity)) = entity.nbt.get(&"Luminosity".into())
        && let Some(Tag::Byte(window)) = owner.nbt.get(&"Window".into())
        && let Some(Tag::Int(width)) = owner.nbt.get(&"Size".into())
        && let Some(Tag::Int(height)) = owner.nbt.get(&"Height".into())
        && let Some(tank) = Tank::new(root, *width, *height)
        && tank.contains(pos)
        && (state_property_differs(game, pos, LIGHT, light_state(*window != 0, *luminosity))
            || state_property_differs(game, pos, CONNECTIONS, connection_state(tank, pos)))
    {
        // Legacy saves need render-state migration. The block entity is
        // temporarily out of the map while this callback runs.
        PENDING.with(|cache| {
            cache
                .borrow_mut()
                .dimension(std::ptr::from_ref(&game.world) as usize, game.dim.id())
                .visual_states
                .insert(root)
        });
    }
    let initial = !entity.nbt.contains_key(&"LastKnownPos".into());
    let dirty = entity.nbt.remove(&"Uninitialized".into()).is_some();
    if initial {
        entity
            .nbt
            .insert("LastKnownPos".into(), Tag::IntArray(pos.to_vec()));
    }
    if initial || dirty {
        game.world.modified.insert((pos[0] >> 4, pos[2] >> 4));
        if root_of(entity, pos) == Some(pos) {
            PENDING.with(|cache| {
                cache
                    .borrow_mut()
                    .dimension(std::ptr::from_ref(&game.world) as usize, game.dim.id())
                    .placed
                    .push(pos);
            });
        }
    }
}

fn state_for(
    game: &Game<'_>,
    record: &Record,
    pos: Pos,
) -> Option<horizon_world::registry::BlockStateId> {
    let registry = game.pack.assets.registry;
    let state = game.world.block(pos[0], pos[1], pos[2]);
    tank_state(registry, state, record, pos)
}

fn tank_state(
    registry: &horizon_world::registry::BlockRegistry,
    base: horizon_world::registry::BlockStateId,
    record: &Record,
    pos: Pos,
) -> Option<horizon_world::registry::BlockStateId> {
    let mut state = registry.state(base)?.clone();
    if state.name != BLOCK {
        return None;
    }
    state
        .properties
        .insert("top".into(), record.tank.top(pos).to_string());
    state
        .properties
        .insert("bottom".into(), record.tank.bottom(pos).to_string());
    state
        .properties
        .insert("shape".into(), record.tank.shape(pos, record.window).into());
    state.properties.insert(
        LIGHT.into(),
        light_state(record.window, record.luminosity(pos)).into(),
    );
    state.properties.insert(
        CONNECTIONS.into(),
        connection_state(record.tank, pos).into(),
    );
    registry.id(&state)
}

pub(super) fn mounted_state(
    game: &Game<'_>,
    record: &Record,
    pos: Pos,
) -> Option<horizon_world::registry::BlockStateId> {
    let registry = game.pack.assets.registry;
    tank_state(registry, registry.default_state(BLOCK)?, record, pos)
}

pub(super) fn mounted_nbt(record: &Record, pos: Pos) -> Option<Compound> {
    let tank = record.tank;
    let mut data = default_nbt();
    data.insert("LastKnownPos".into(), Tag::IntArray(pos.to_vec()));
    data.insert("Luminosity".into(), Tag::Int(record.luminosity(pos)));
    if pos == tank.root {
        data.insert("Size".into(), Tag::Int(tank.width()));
        data.insert("Height".into(), Tag::Int(tank.height()));
        data.insert("Window".into(), Tag::Byte(i8::from(record.window)));
        data.insert(
            "TankContent".into(),
            fluids::write_content(record.fluid.as_ref(), SAVED_AMOUNT_LIMIT).ok()?,
        );
    } else {
        for key in ["Size", "Height", "Window", "TankContent"] {
            data.remove(&key.into());
        }
        data.insert("Controller".into(), Tag::IntArray(tank.root.to_vec()));
    }
    Some(data)
}

pub(super) fn canonical_mount(game: &Game<'_>, record: &Record) -> bool {
    let tank = record.tank;
    complete(game, tank)
        && tank.parts().all(|pos| {
            let key = (pos[0], pos[1], pos[2]);
            let Some(block_entity @ BlockEntity::Mod(entity)) = game.world.block_entities.get(&key)
            else {
                return false;
            };
            if !entity.items.is_empty()
                || !entity.data.is_empty()
                || game.world.block_names.contains_key(&key)
                || game.world.block_lock(key).is_some()
                || state_for(game, record, pos) != Some(game.world.block(pos[0], pos[1], pos[2]))
            {
                return false;
            }
            if mounted_nbt(record, pos).as_ref() != Some(&entity.nbt) {
                return false;
            }
            let (cx, cz) = (pos[0] >> 4, pos[2] >> 4);
            if game
                .world
                .block_entities
                .chunk_attachments(cx, cz)
                .iter()
                .any(|(at, _)| *at == key)
            {
                return false;
            }
            game.world
                .chunks
                .get(&(cx, cz))
                .and_then(|chunk| chunk.saved.as_ref())
                .is_none_or(|saved| {
                    !saved.rolled_loot.iter().any(|loot| loot.pos == key)
                        && !saved
                            .block_entity_attachments
                            .iter()
                            .any(|(at, _)| *at == key)
                        && saved
                            .block_entity_sources
                            .iter()
                            .find(|(at, _)| *at == key)
                            .is_none_or(|(_, source)| {
                                *source
                                    == horizon_client::save::encode_block_entity(
                                        key,
                                        block_entity,
                                        BLOCK,
                                    )
                            })
                })
        })
}

fn apply(game: &mut Game<'_>, record: &Record) -> bool {
    let tank = record.tank;
    let Ok(content) = fluids::write_content(record.fluid.as_ref(), SAVED_AMOUNT_LIMIT) else {
        return false;
    };
    let Some(states) = tank
        .parts()
        .map(|pos| {
            ordinary(entity_at(&game.world, pos)?).then_some(())?;
            Some((pos, state_for(game, record, pos)?))
        })
        .collect::<Option<Vec<_>>>()
    else {
        return false;
    };
    for &(pos, _) in &states {
        game.native_with_mod_block_entity(pos, |entity| {
            let nbt = &mut entity.nbt;
            nbt.remove(&"Uninitialized".into());
            nbt.insert("LastKnownPos".into(), Tag::IntArray(pos.to_vec()));
            if pos == tank.root {
                nbt.remove(&"Controller".into());
                nbt.insert("Size".into(), Tag::Int(tank.width()));
                nbt.insert("Height".into(), Tag::Int(tank.height()));
                nbt.insert("Window".into(), Tag::Byte(i8::from(record.window)));
                nbt.insert("TankContent".into(), content.clone());
            } else {
                for key in ["Size", "Height", "Window", "TankContent"] {
                    nbt.remove(&key.into());
                }
                nbt.insert("Controller".into(), Tag::IntArray(tank.root.to_vec()));
            }
        });
    }
    for (pos, state) in states {
        if game.world.block(pos[0], pos[1], pos[2]) != state {
            game.native_set_block(game.dim.id(), pos, state, VISUAL_UPDATE);
        }
        game.native_block_entity_sync(pos);
    }
    if let Some(entity) = entity_at(&game.world, tank.root) {
        bind_capacity(game, tank.root, entity.revision(), record.part_capacity);
    }
    notify(game, record);
    true
}

fn split(game: &mut Game<'_>, old: &Record, placed: &mut Vec<Pos>) {
    let tank = old.tank;
    let part_capacity = configured_capacity();
    let surviving = tank.split(
        old.fluid.as_ref().map_or(0, |f| f.amount),
        part_capacity,
        |pos| {
            game.native_block(pos) == BLOCK
                && root_at(&game.world, pos) == Some(tank.root)
                && (pos != tank.root
                    || entity_at(&game.world, pos)
                        .and_then(|entity| read(entity, pos))
                        .is_some_and(|current| current.tank == old.tank))
        },
    );
    for (pos, amount) in surviving {
        let fluid = old
            .fluid
            .as_ref()
            .filter(|_| amount != 0)
            .map(|fluid| Fluid {
                key: fluid.key.clone(),
                amount,
            });
        if apply(
            game,
            &Record {
                tank: Tank::single(pos),
                part_capacity,
                window: old.window,
                fluid,
            },
        ) {
            placed.push(pos);
        }
    }
}

fn candidate(game: &Game<'_>, root: Pos) -> Option<(Tank, BTreeMap<Pos, Record>)> {
    let mut sources = BTreeMap::<Pos, Option<Record>>::new();
    let max_height = super::create_port_server_config::fluid_tank_max_height()
        .min(game.dimension_type().height.height);
    let tank = geometry::largest(root, max_height, |pos| {
        let source = root_at(&game.world, pos)?;
        let record = sources
            .entry(source)
            .or_insert_with(|| current(game, source).filter(|record| complete(game, record.tank)))
            .as_ref()?;
        if !record.tank.contains(pos) {
            return None;
        }
        Some((record.tank, record.fluid.as_ref().map(|f| f.key.clone())))
    })?;
    let sources = sources
        .into_values()
        .flatten()
        .filter(|record| tank.contains(record.tank.root))
        .map(|record| (record.tank.root, record))
        .collect::<BTreeMap<_, _>>();
    let base = sources.get(&root)?;
    (tank != base.tank).then_some((tank, sources))
}

fn form(game: &mut Game<'_>, start: Pos) {
    let mut frontier = VecDeque::from([start]);
    let mut visited = BTreeSet::new();
    let mut choices = Vec::new();
    while let Some(pos) = frontier.pop_front() {
        if !visited.insert(pos) || game.native_block(pos) != BLOCK {
            continue;
        }
        if let Some((tank, _)) = candidate(game, pos) {
            choices.push(tank);
        }
        for axis in 0..3 {
            let mut next = pos;
            next[axis] -= 1;
            if axis == 1 || next[axis] > start[axis] - geometry::MAX_WIDTH {
                frontier.push_back(next);
            }
        }
    }
    choices.sort_by_key(|tank| std::cmp::Reverse(tank.volume()));
    for choice in choices {
        let Some((tank, mut sources)) = candidate(game, choice.root) else {
            continue;
        };
        let Some(mut record) = sources.remove(&tank.root) else {
            continue;
        };
        record.tank = tank;
        record.part_capacity = configured_capacity();
        let capacity = record.capacity();
        if let Some(fluid) = &mut record.fluid {
            fluid.amount = fluid.amount.min(capacity);
        }
        for source in sources.into_values() {
            if let Some(mut fluid) = source.fluid {
                match &mut record.fluid {
                    Some(stored) => {
                        stored.amount = stored.amount.saturating_add(fluid.amount).min(capacity);
                    }
                    None => {
                        fluid.amount = fluid.amount.min(capacity);
                        record.fluid = Some(fluid);
                    }
                }
            }
        }
        apply(game, &record);
    }
}

fn write_saved_breaks(game: &mut Game<'_>, breaks: Breaks) -> Result<(), AttachmentError> {
    if breaks.is_empty() {
        game.native_attachments(Holder::Level)?
            .remove(&SAVED_BREAKS)?;
    } else {
        game.native_attachments(Holder::Level)?
            .set(&SAVED_BREAKS, breaks)?;
    }
    Ok(())
}

pub(super) fn before_save(game: &mut Game<'_>) {
    if game.options.execution_role.is_client() || !game.native_on("create") {
        return;
    }
    let pending = PENDING.with(|cache| {
        cache
            .borrow_mut()
            .dimension(std::ptr::from_ref(&game.world) as usize, game.dim.id())
            .broken
            .clone()
    });
    if pending.is_empty() {
        return;
    }
    let result = game
        .native_attachments(Holder::Level)
        .and_then(|map| map.get_existing(&SAVED_BREAKS))
        .and_then(|stored| {
            let mut stored = stored.unwrap_or_default();
            merge_breaks(&mut stored, pending);
            write_saved_breaks(game, stored)
        });
    if let Err(error) = result {
        log::warn!("Create fluid tank splits could not be saved: {error:?}");
    }
}

pub(super) fn maintenance(game: &mut Game<'_>) {
    let session = std::ptr::from_ref(&game.world) as usize;
    let dimension = game.dim.id();
    if !game.clock.frozen() && game.world.game_time % 200 == 0 {
        CAPACITIES
            .write()
            .unwrap_or_else(|error| error.into_inner())
            .retain(|id, binding| {
                binding.level != (session, game.dim)
                    || entity_at(&game.world, binding.pos)
                        .is_some_and(|entity| entity.revision().create_entity_identity() == *id)
            });
    }
    let Pending {
        mut placed,
        mut broken,
        visual_states,
    } = PENDING.with(|cache| std::mem::take(cache.borrow_mut().dimension(session, dimension)));
    let stored = game
        .native_attachments(Holder::Level)
        .and_then(|map| map.get_existing(&SAVED_BREAKS));
    if let Ok(Some(saved)) = &stored {
        let new = broken;
        broken = saved.clone();
        merge_breaks(&mut broken, new);
    }
    let mut deferred = BTreeMap::new();
    for (root, mut entry) in broken {
        if entry.snapshot.is_none() {
            if !game.world.loaded(root[0], root[2]) {
                deferred.insert(root, entry);
                continue;
            }
            entry.snapshot = entity_at(&game.world, root).and_then(|entity| read(entity, root));
        }
        let Some(record) = &entry.snapshot else {
            continue;
        };
        if record.tank.volume() == 1 || !entry.removed.iter().any(|&pos| record.tank.contains(pos))
        {
            continue;
        }
        if !loaded(&game.world, record.tank) {
            entry.removed.retain(|&pos| record.tank.contains(pos));
            deferred.insert(root, entry);
        } else if !complete(game, record.tank) {
            split(game, record, &mut placed);
        }
    }
    match stored {
        Ok(saved)
            if saved.as_ref() == Some(&deferred) || (saved.is_none() && deferred.is_empty()) => {}
        Ok(_) => {
            if let Err(error) = write_saved_breaks(game, deferred.clone()) {
                log::warn!("Create fluid tank splits could not be saved: {error:?}");
                PENDING.with(|cache| {
                    cache
                        .borrow_mut()
                        .dimension(session, dimension)
                        .broken
                        .extend(deferred)
                });
            }
        }
        Err(_) => {
            // Keep the unknown saved attachment intact and retry new work in memory.
            PENDING.with(|cache| {
                cache
                    .borrow_mut()
                    .dimension(session, dimension)
                    .broken
                    .extend(deferred)
            });
        }
    }
    for root in visual_states {
        let Some(record) = current(game, root).filter(|record| complete(game, record.tank)) else {
            continue;
        };
        for pos in record.tank.parts() {
            if let Some(state) = state_for(game, &record, pos)
                && state != game.world.block(pos[0], pos[1], pos[2])
            {
                game.native_set_block(game.dim.id(), pos, state, VISUAL_UPDATE);
            }
        }
    }
    let mut visited = BTreeSet::new();
    for pos in placed {
        if visited.insert(pos) {
            form(game, pos);
        }
    }
}

pub(super) fn comparator(game: &GameLevel<'_>, pos: Pos) -> i32 {
    resolve(game.world, game.registry, pos, false).map_or(0, |record| {
        let fraction = f64::from(record.fraction());
        (fraction * 14.0 + f64::from(u8::from(fraction > 0.0)))
            .clamp(0.0, 15.0)
            .floor() as i32
    })
}

pub(super) fn tooltip(game: &Game<'_>, pos: Pos) -> Vec<horizon_client::text::Text> {
    let Some(record) = resolve(&game.world, game.pack.assets.registry, pos, true) else {
        return Vec::new();
    };
    let fluid = record.fluid.as_ref().map(|f| (f.key.id.as_str(), f.amount));
    super::create_port_goggles::fluid_container(game, record.capacity(), fluid)
}

pub(super) fn view(game: &Game<'_>, pos: Pos) -> Option<Vec<NativeFluidTankView>> {
    let record = current(game, pos)?;
    if !complete(game, record.tank) {
        return None;
    }
    Some(vec![NativeFluidTankView {
        tank: 0,
        content: record.fluid.as_ref().map(native_fluid),
        capacity: record.capacity() as i32,
        can_fill: true,
        can_drain: true,
    }])
}

pub(super) fn set_content(game: &mut Game<'_>, pos: Pos, content: Tag) {
    game.native_with_mod_block_entity(pos, |entity| {
        entity.nbt.insert("TankContent".into(), content);
    });
}

fn connection_state(tank: Tank, pos: Pos) -> &'static str {
    const MASKS: [&str; 16] = [
        "0", "1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "11", "12", "13", "14", "15",
    ];
    MASKS[usize::from(tank.horizontal_mask(pos))]
}

fn state_property_differs(game: &Game<'_>, pos: Pos, key: &str, value: &str) -> bool {
    let state = game.world.block(pos[0], pos[1], pos[2]);
    game.pack
        .assets
        .registry
        .state(state)
        .and_then(|state| state.properties.get(key))
        .is_some_and(|current| current != value)
}

fn update_light(game: &mut Game<'_>, record: &Record, pos: Pos) {
    let value = light_state(record.window, record.luminosity(pos));
    if state_property_differs(game, pos, LIGHT, value) {
        game.native_set_block_property_with(pos, LIGHT, value, VISUAL_UPDATE);
    }
}

pub(super) fn notify(game: &mut Game<'_>, record: &Record) {
    game.native_block_entity_sync(record.tank.root);
    for pos in record.tank.parts() {
        let luminosity = Tag::Int(record.luminosity(pos));
        if entity_at(&game.world, pos)
            .is_some_and(|entity| entity.nbt.get(&"Luminosity".into()) != Some(&luminosity))
        {
            game.native_with_mod_block_entity(pos, |entity| {
                entity.nbt.insert("Luminosity".into(), luminosity);
            });
            game.native_block_entity_sync(pos);
        }
        update_light(game, record, pos);
        game.native_update_output_neighbors(game.dim.id(), pos);
    }
}

pub(super) fn prepare_content(game: &Game<'_>, record: &Record) -> Option<Tag> {
    if !complete(game, record.tank) {
        return None;
    }
    fluids::write_content(record.fluid.as_ref(), SAVED_AMOUNT_LIMIT).ok()
}

fn commit(game: &mut Game<'_>, record: &Record) -> bool {
    let Some(content) = prepare_content(game, record) else {
        return false;
    };
    set_content(game, record.tank.root, content);
    notify(game, record);
    true
}

pub(super) fn endpoint(game: &Game<'_>, pos: Pos) -> Option<Record> {
    current(game, pos).filter(|record| {
        record
            .fluid
            .as_ref()
            .is_none_or(|fluid| fluid.key.components.is_empty())
    })
}

pub(super) fn fill(
    game: &mut Game<'_>,
    pos: Pos,
    resource: &NativeFluidStack,
    action: NativeFluidAction,
) -> Option<i32> {
    let mut record = current(game, pos)?;
    if !complete(game, record.tank) {
        return None;
    }
    let Some(mut fluid) = core_fluid(resource) else {
        return Some(0);
    };
    let stored = match record.fluid.as_ref() {
        Some(current) if current.key == fluid.key => current.amount,
        Some(_) => return Some(0),
        None => 0,
    };
    let accepted = fluid.amount.min(record.capacity().saturating_sub(stored));
    #[allow(unreachable_patterns)]
    match action {
        NativeFluidAction::Simulate => {}
        NativeFluidAction::Execute => {
            fluid.amount = stored + accepted;
            record.fluid = Some(fluid);
            if accepted != 0 && !commit(game, &record) {
                return Some(0);
            }
        }
        _ => return Some(0),
    }
    Some(accepted as i32)
}

pub(super) fn drain(
    game: &mut Game<'_>,
    pos: Pos,
    request: &NativeFluidDrain,
    action: NativeFluidAction,
) -> Option<NativeFluidStack> {
    let mut record = current(game, pos)?;
    if !complete(game, record.tank) {
        return None;
    }
    let mut fluid = record.fluid.take()?;
    let maximum = match request {
        NativeFluidDrain::Any(maximum) => *maximum,
        NativeFluidDrain::Exact(wanted)
            if wanted.fluid == fluid.key.id && wanted.components == fluid.key.components =>
        {
            wanted.amount
        }
        _ => return None,
    };
    if maximum <= 0 {
        return None;
    }
    let drained = fluid.amount.min(maximum as u32);
    #[allow(unreachable_patterns)]
    match action {
        NativeFluidAction::Simulate => {}
        NativeFluidAction::Execute => {
            fluid.amount -= drained;
            record.fluid = (fluid.amount > 0).then(|| fluid.clone());
            if !commit(game, &record) {
                return None;
            }
        }
        _ => return None,
    }
    fluid.amount = drained;
    Some(native_fluid(&fluid))
}

pub(in crate::game) fn predicts_use(game: &Game<'_>, pos: Pos) -> bool {
    game.native_on("create")
        && game.native_block(pos) == BLOCK
        && !game.native_sneaking()
        && game
            .held()
            .filter(|held| held.count > 0)
            .is_some_and(|held| {
                game.may_build() && crate::game::create_port_chassis::wrench(game, held)
                    || game.creative
                        && (held.item.as_ref() == "minecraft:bucket"
                            || held.item.as_ref() == emptying::GLASS_BOTTLE
                            || emptying::can_empty(game, held))
            })
}

pub(in crate::game) fn right_click(game: &mut Game<'_>, pos: Pos) -> bool {
    if !predicts_use(game, pos) {
        return false;
    }
    let Some(mut record) = current(game, pos) else {
        return true;
    };
    let Some(held) = game.held().cloned() else {
        return false;
    };
    if crate::game::create_port_chassis::wrench(game, &held) {
        if complete(game, record.tank) {
            record.window = !record.window;
            apply(game, &record);
        }
        return true;
    }
    let before = &record.fluid;
    let bottle = held.item.as_ref() == emptying::GLASS_BOTTLE;
    let (fluid, amount, emptying) = if bottle || held.item.as_ref() == "minecraft:bucket" {
        let Some(mut resource) = before
            .as_ref()
            .map(native_fluid)
            .filter(|f| f.components.is_empty())
        else {
            return true;
        };
        let required = if bottle {
            emptying::BOTTLE_AMOUNT
        } else {
            BUCKET
        };
        let matches = if bottle {
            resource.fluid == FluidKind::Water.id()
        } else {
            game.native_item_fluid_fill(&held, &resource.fluid, required)
                .is_some_and(|(amount, _)| amount == required)
        };
        if resource.amount < required || !matches {
            return true;
        }
        let remaining = resource.amount - required;
        resource.amount = required;
        let request = NativeFluidDrain::Exact(resource);
        let mut drained = None;
        game.native_custom_fluid_drain(
            pos,
            None,
            &request,
            NativeFluidAction::Execute,
            &mut drained,
        );
        let Some(drained) = drained else {
            return true;
        };
        (drained.fluid, remaining, false)
    } else {
        let Some((fluid, amount, _)) = emptying::empty(game, &held) else {
            return true;
        };
        let resource = NativeFluidStack {
            fluid: fluid.to_owned(),
            amount,
            components: Compound::new(),
        };
        let mut accepted = None;
        game.native_custom_fluid_fill(
            pos,
            None,
            &resource,
            NativeFluidAction::Simulate,
            &mut accepted,
        );
        if accepted != Some(amount) {
            return true;
        }
        accepted = None;
        game.native_custom_fluid_fill(
            pos,
            None,
            &resource,
            NativeFluidAction::Execute,
            &mut accepted,
        );
        if accepted != Some(amount) {
            return true;
        }
        (
            resource.fluid,
            before.as_ref().map_or(0, |f| f.amount as i32) + amount,
            true,
        )
    };
    play_bucket(game, pos, &fluid, amount, emptying);
    true
}

fn play_bucket(game: &mut Game<'_>, pos: Pos, fluid: &str, amount: i32, emptying: bool) {
    let event = match (emptying, fluid) {
        (true, "minecraft:lava") => "minecraft:item.bucket.empty_lava",
        (false, "minecraft:lava") => "minecraft:item.bucket.fill_lava",
        (true, _) => "minecraft:item.bucket.empty",
        (false, _) => "minecraft:item.bucket.fill",
    };
    game.with_level(|_, level, _| {
        let Some(random) = level.native_level_random() else {
            return;
        };
        let pitch = (1.0 - amount as f32 / (configured_capacity() as f32 * 16.0)).clamp(0.0, 1.0)
            / 1.5
            + 0.5
            + (random.next_float() - 0.5) / 4.0;
        level.native_play_sound(
            event,
            pos.map(|coordinate| f64::from(coordinate) + 0.5),
            4,
            0.5,
            pitch,
        );
    });
}

pub(super) fn update_tag(entity: &ModBlockEntity) -> Compound {
    let mut snapshot = entity.nbt.clone();
    // Java's client re-reads its tank using the active config. The server
    // keeps the original fill limit until this controller is rebuilt.
    let display_capacity = CAPACITIES
        .read()
        .unwrap_or_else(|error| error.into_inner())
        .get(&entity.revision().create_entity_identity())
        .map(|binding| binding.config.load(Ordering::Relaxed))
        .unwrap_or_else(configured_capacity);
    snapshot.insert(CAPACITY_UPDATE.into(), Tag::Int(display_capacity as i32));
    // Horizon merges client update tags. On promotion the new controller
    // must explicitly replace the previous member's pointer on the wire.
    snapshot
        .entry("Controller".into())
        .or_insert_with(|| Tag::IntArray(Vec::new()));
    snapshot
}

pub(super) fn client_tick(
    session: usize,
    dimension: &str,
    time: i64,
    entries: &[(Pos, &ModBlockEntity)],
) {
    RENDER.with(|cache| {
        let mut cache = cache.borrow_mut();
        let cache = cache.dimension(session, dimension);
        let mut live = std::collections::BTreeSet::new();
        for &(pos, entity) in entries.iter().filter(|(_, e)| e.id == BLOCK) {
            let Some(record) = read_client(entity, pos) else {
                continue;
            };
            live.insert(pos);
            let owner = entity.revision();
            let target = record.fraction();
            let motion = cache.entry(pos).or_default();
            if motion.tank != Some(record.tank)
                || motion.tick.is_some_and(|old| old > time)
                || motion
                    .owner
                    .is_none_or(|old| !old.is_same_create_entity(owner))
            {
                *motion = RenderLevel {
                    tank: Some(record.tank),
                    owner: Some(owner),
                    tick: None,
                    chase: rules::FluidLevel {
                        previous: target,
                        value: target,
                        target,
                        speed: 0.5,
                    },
                };
            }
            motion.chase.target = target;
            if motion.tick != Some(time) {
                motion.chase.tick();
                motion.tick = Some(time);
            }
        }
        cache.retain(|pos, _| live.contains(pos));
    });
}

pub(in crate::game) fn draw(
    game: &Game<'_>,
    pos: Pos,
    entity: &ModBlockEntity,
    draw: &mut BlockEntityDraw,
) {
    let Some(record) = read_client(entity, pos).filter(|record| record.window) else {
        return;
    };
    let level = RENDER.with(|cache| {
        cache
            .borrow_mut()
            .dimension(std::ptr::from_ref(&game.world) as usize, game.dim.id())
            .get(&pos)
            .filter(|motion| {
                motion.tank == Some(record.tank)
                    && motion
                        .owner
                        .is_some_and(|old| old.is_same_create_entity(entity.revision()))
            })
            .map_or_else(|| record.fraction(), |motion| motion.chase.at(draw.partial))
    });
    draw_fluid(game, &record, level, draw);
}

pub(super) fn render_bounds(pos: Pos, entity: &ModBlockEntity, bounds: &mut [f32; 6]) {
    if client_root_of(entity, pos) == Some(pos)
        && let Some(tank) = tank_geometry(&entity.nbt, pos)
    {
        bounds[3] = bounds[3].max(tank.width() as f32);
        bounds[4] = bounds[4].max(tank.height() as f32);
        bounds[5] = bounds[5].max(tank.width() as f32);
    }
}

pub(super) fn draw_fluid(game: &Game<'_>, record: &Record, level: f32, draw: &mut BlockEntityDraw) {
    let Some(fluid) = record.fluid.as_ref().filter(|_| record.window) else {
        return;
    };
    let Some(bounds) = record.tank.liquid_bounds(level) else {
        return;
    };
    super::create_port_fluid_render::draw(
        game,
        draw,
        &native_fluid(fluid),
        bounds,
        NativeFluidRenderOptions {
            argb: None,
            render_bottom: false,
            uv_shrink_ratio: 4.0 / 2048.0,
        },
    );
}
