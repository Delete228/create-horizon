// Copyright (c) The Create Team / The Creators of Create
// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT
// Create 6.0.10 BasinBlockEntity/BasinInventory/BasinRenderer adapter.
// Heat-aware Basin with canonical fluid tanks and side output queues.
use super::create_port_block_entity_revision::EntityRevision as _;
use super::{
    Game, GameLevel,
    create_port_basin_recipes::{emptying, item_drain},
    create_port_fluid_codec as fluids, create_port_fluid_tank as tank,
    native_block_entity_draw::BlockEntityDraw,
};
use crate::{
    containers::{BlockEntity, ModBlockEntity, ModContainer, ModRevision},
    items::ItemStack,
};
use create_engine::{basin as rules, fluid_transport::Fluid, transport::SessionCache};
use horizon_client::mod_api::{
    NativeFluidAction, NativeFluidDrain, NativeFluidRenderOptions, NativeFluidStack,
    NativeFluidTankView,
};
use horizon_core::random::{LegacyRandom, RandomSource};
use horizon_world::nbt::{Compound, Tag};
use std::{cell::RefCell, collections::BTreeMap};

pub(super) const ID: &str = "create:basin";
type Pos = [i32; 3];

#[derive(Clone, Debug)]
pub(super) struct Key(pub ItemStack);
impl PartialEq for Key {
    fn eq(&self, other: &Self) -> bool {
        self.0.same_item_same_components(&other.0)
    }
}
impl Eq for Key {}
pub(super) type Basin = rules::Basin<Key, fluids::Key>;
type FluidBasin = rules::Basin<(), fluids::Key>;

#[derive(Default)]
struct Motion {
    owner: Option<ModRevision>,
    tick: Option<i64>,
    previous: f32,
    angle: f32,
    speed: f32,
    lazy: i32,
    moving: bool,
    fluid_levels: [rules::FluidLevel; 4],
    received_fluids: [Option<fluids::Level>; 4],
    rendered_fluids: [Option<rules::Fluid<fluids::Key>>; 4],
}
struct Server {
    owner: Option<ModRevision>,
    initialized: bool,
    contents_changed: bool,
    tick: Option<i64>,
    lazy: i32,
    backup: i32,
    heat: rules::HeatCache,
}
impl Default for Server {
    fn default() -> Self {
        Self {
            owner: None,
            initialized: false,
            contents_changed: false,
            tick: None,
            lazy: 10,
            backup: 20,
            heat: rules::HeatCache::default(),
        }
    }
}
impl Server {
    fn bind(&mut self, owner: ModRevision) {
        if self
            .owner
            .is_some_and(|old| !old.is_same_create_entity(owner))
        {
            *self = Self::default();
        }
        self.owner = Some(owner);
    }
}
thread_local! {
    static MOTION: RefCell<SessionCache<BTreeMap<Pos, Motion>>> = RefCell::new(SessionCache::default());
    static SERVER: RefCell<SessionCache<BTreeMap<Pos, Server>>> = RefCell::new(SessionCache::default());
}

pub(super) fn reset(reload: bool) {
    if !reload {
        MOTION.with(|m| m.borrow_mut().clear());
        SERVER.with(|m| m.borrow_mut().clear());
        tank::reset();
        pump::reset();
    }
}

/// BasinInventory.whenContentsChanged/notifyChangeOfContents only raises a
/// flag. The next ordinary Basin tick schedules its operator checker.
pub(super) fn notify_contents(game: &Game<'_>, pos: Pos) {
    let Some(BlockEntity::Mod(entity)) = game.world.block_entities.get(&(pos[0], pos[1], pos[2]))
    else {
        return;
    };
    if entity.id != ID || !crate::game::create_port::inventory_supported(entity) {
        return;
    }
    SERVER.with(|cache| {
        let mut cache = cache.borrow_mut();
        let server = cache
            .dimension(std::ptr::from_ref(&game.world) as usize, game.dim.id())
            .entry(pos)
            .or_default();
        server.bind(entity.revision());
        server.contents_changed = true;
    });
}

pub(super) fn container(block: &str, container: &mut Option<ModContainer>) {
    if block == ID && container.is_none() {
        *container = Some(ModContainer {
            slots: 18,
            faces: std::array::from_fn(|_| (0..18).collect()),
            inputs: (0..9).collect(),
            // CombinedInvWrapper exposes BOTH input and output to extraction.
            outputs: (0..18).collect(),
            menu: None,
        });
    }
}

fn inventory(slots: &[Option<ItemStack>]) -> Tag {
    Tag::Compound(Compound::from([
        ("Size".into(), Tag::Int(9)),
        (
            "Items".into(),
            Tag::List(
                slots
                    .iter()
                    .enumerate()
                    .filter_map(|(i, s)| {
                        let stack = s.as_ref().filter(|s| s.count > 0)?;
                        let Tag::Compound(mut nbt) = horizon_items::item_nbt::item_to_nbt(stack)
                        else {
                            return None;
                        };
                        nbt.insert("Slot".into(), Tag::Int(i as i32));
                        Some(Tag::Compound(nbt))
                    })
                    .collect(),
            ),
        ),
    ]))
}
fn restore(entity: &mut ModBlockEntity) {
    // Canonical inventory is decoded before publication. Never re-read an old
    // bridge snapshot after ordinary automation has already changed live slots.
    if crate::game::create_port::inventory_supported(entity) {
        entity.items.resize(18, None);
    }
}
pub(super) fn data(entity: &mut ModBlockEntity) -> bool {
    if entity.id != ID || !crate::game::create_port::inventory_supported(entity) {
        return false;
    }
    entity.items.resize(18, None);
    let mut changed = false;
    for (key, range) in [("InputItems", 0..9), ("OutputItems", 9..18)] {
        let Tag::Compound(updated) = inventory(&entity.items[range]) else {
            unreachable!();
        };
        let mut value = match entity.nbt.get(&key.into()) {
            Some(Tag::Compound(existing)) => existing.clone(),
            _ => Compound::new(),
        };
        value.extend(updated);
        let value = Tag::Compound(value);
        changed |= entity.nbt.get(&key.into()) != Some(&value);
        entity.nbt.insert(key.into(), value.clone());
    }
    changed
}
fn empty_tanks() -> Tag {
    let segment = Tag::Compound(Compound::from([
        (
            "Level".into(),
            Tag::Compound(Compound::from([
                ("Force".into(), Tag::Byte(1)),
                ("Speed".into(), Tag::Float(0.25f32.to_bits())),
                ("Target".into(), Tag::Float(0.0f32.to_bits())),
                ("Value".into(), Tag::Float(0.0f32.to_bits())),
            ])),
        ),
        ("TankContent".into(), Tag::Compound(Compound::new())),
    ]));
    Tag::List(vec![segment.clone(), segment])
}
pub(super) fn initialize(entity: &mut ModBlockEntity) {
    if entity.id != ID || !crate::game::create_port::inventory_supported(entity) {
        return;
    }
    restore(entity);
    for key in ["InputTanks", "OutputTanks"] {
        entity.nbt.entry(key.into()).or_insert_with(empty_tanks);
    }
    for key in ["DisabledSpoutput", "Overflow", "FluidOverflow"] {
        entity
            .nbt
            .entry(key.into())
            .or_insert_with(|| Tag::List(Vec::new()));
    }
    entity
        .nbt
        .entry("Filter".into())
        .or_insert_with(|| Tag::Compound(Compound::new()));
    entity
        .nbt
        .entry("FilterAmount".into())
        .or_insert(Tag::Int(64));
    entity.nbt.entry("UpTo".into()).or_insert(Tag::Byte(1));
    data(entity);
}

pub(super) fn unsupported(
    game: &Game<'_>,
    pos: Pos,
    entity: &ModBlockEntity,
) -> Option<&'static str> {
    if !crate::game::create_port::inventory_supported(entity) {
        return Some("basin inventory sizes are not supported");
    }
    if spout::facing(game, pos).is_none() {
        return Some("basin spout direction is not supported");
    }
    if super::create_port_basin_filter::read(game, entity).is_none() {
        return Some("basin recipe filter data is not supported");
    }
    for key in ["InputTanks", "OutputTanks"] {
        if let Err(fluids::Unsupported(reason)) = read_tanks(entity, key) {
            return Some(reason);
        }
    }
    if let Err(fluids::Unsupported(reason)) = spout::fluid_buffer(entity) {
        return Some(reason);
    }
    if spout::Settings::read(entity).is_none() || spout::buffer(entity).is_none() {
        return Some("basin item spout data is not supported");
    }
    None
}
fn component_maximum(stack: &ItemStack) -> Option<u32> {
    super::create_port::stack_maximum_override(stack)
}
pub(super) fn max_stack(game: &Game<'_>, stack: &ItemStack) -> u32 {
    super::create_port::stack_maximum(game, stack)
}
pub(super) fn has_analog(
    game: &GameLevel<'_>,
    state: horizon_world::registry::BlockStateId,
    output: &mut bool,
) {
    if matches!(
        game.facts.get(state).name.as_ref(),
        ID | item_drain::BLOCK | tank::BLOCK
    ) {
        *output = true;
    }
}
pub(super) fn analog(
    game: &GameLevel<'_>,
    pos: horizon_core::position::BlockPos,
    state: horizon_world::registry::BlockStateId,
    output: &mut i32,
) {
    let block = game.facts.get(state).name.as_ref();
    if !matches!(block, ID | item_drain::BLOCK | tank::BLOCK) {
        return;
    }
    *output = 0;
    let Some(BlockEntity::Mod(e)) = game.world.block_entities.get(&(pos.x, pos.y, pos.z)) else {
        return;
    };
    if block == item_drain::BLOCK {
        *output = item_drain::comparator(e);
        return;
    }
    if block == tank::BLOCK {
        *output = tank::comparator(game, [pos.x, pos.y, pos.z]);
        return;
    }
    // Unsupported native-created inventories may not have canonical slots yet.
    // Keep their payload opaque and fail closed before any comparator indexing.
    if !crate::game::create_port::inventory_supported(e) {
        return;
    }
    let mut fullness = 0.0f32;
    let mut occupied = false;
    for stack in e.items.iter().take(9).flatten().filter(|s| s.count > 0) {
        let maximum = component_maximum(stack)
            .unwrap_or_else(|| game.items.get(&stack.item).map_or(64, |i| i.max_stack))
            .min(64);
        fullness += stack.count as f32 / maximum as f32;
        occupied = true;
    }
    *output = (fullness / 9.0 * 14.0).floor() as i32 + i32::from(occupied);
}
pub(super) fn can_survive(
    game: &GameLevel<'_>,
    pos: horizon_core::position::BlockPos,
    state: horizon_world::registry::BlockStateId,
    survives: &mut Option<bool>,
) {
    let block = game.facts.get(state).name.as_ref();
    if block == "create:mechanical_mixer" {
        *survives = Some(
            !matches!(game.world.block_entities.get(&(pos.x,pos.y-1,pos.z)),Some(BlockEntity::Mod(e)) if e.id == ID),
        );
        return;
    }
    if block != ID {
        return;
    }
    *survives = Some(
        !matches!(game.world.block_entities.get(&(pos.x,pos.y+1,pos.z)),Some(BlockEntity::Mod(e)) if matches!(e.id.as_str(),"create:mechanical_mixer"|"create:mechanical_press")),
    );
}
pub(super) fn core_stack(game: &Game<'_>, stack: &ItemStack) -> rules::Item<Key> {
    let mut key = stack.clone();
    key.count = 1;
    rules::Item {
        key: Key(key),
        count: stack.count,
        maximum: max_stack(game, stack),
    }
}
pub(super) fn native_stack(item: &rules::Item<Key>) -> ItemStack {
    ItemStack {
        count: item.count,
        ..item.key.0.clone()
    }
}
pub(super) fn read(game: &Game<'_>, pos: Pos) -> Option<Basin> {
    let BlockEntity::Mod(entity) = game.world.block_entities.get(&(pos[0], pos[1], pos[2]))? else {
        return None;
    };
    if entity.id != ID || unsupported(game, pos, entity).is_some() {
        return None;
    }
    Some(Basin {
        input: std::array::from_fn(|i| {
            entity
                .items
                .get(i)
                .and_then(Option::as_ref)
                .filter(|s| s.count > 0)
                .map(|s| core_stack(game, s))
        }),
        output: std::array::from_fn(|i| {
            entity
                .items
                .get(9 + i)
                .and_then(Option::as_ref)
                .filter(|s| s.count > 0)
                .map(|s| core_stack(game, s))
        }),
        input_fluids: read_tanks(entity, "InputTanks").ok()?,
        output_fluids: read_tanks(entity, "OutputTanks").ok()?,
        mode: spout::output_mode(game, pos),
        overflow: spout::buffer(entity)?
            .iter()
            .map(|stack| core_stack(game, stack))
            .collect(),
        fluid_overflow: spout::fluid_buffer(entity).ok()?,
        ..Basin::default()
    })
}
pub(super) fn heat(game: &Game<'_>, pos: Pos) -> rules::Heat {
    let Some(BlockEntity::Mod(entity)) = game.world.block_entities.get(&(pos[0], pos[1], pos[2]))
    else {
        return rules::Heat::None;
    };
    if entity.id != ID {
        return rules::Heat::None;
    }
    SERVER.with(|cache| {
        let mut cache = cache.borrow_mut();
        let server = cache
            .dimension(std::ptr::from_ref(&game.world) as usize, game.dim.id())
            .entry(pos)
            .or_default();
        server.bind(entity.revision());
        server.heat.get_or_read(|| {
            let state = game.world.block(pos[0], pos[1] - 1, pos[2]);
            let Some(state) = game.pack.assets.registry.state(state) else {
                return Some(rules::Heat::None);
            };
            let blaze = state
                .properties
                .get("blaze")
                .map(|value| match value.as_str() {
                    "smouldering" => rules::Heat::Smouldering,
                    "fading" => rules::Heat::Fading,
                    "kindled" => rules::Heat::Kindled,
                    "seething" => rules::Heat::Seething,
                    _ => rules::Heat::None,
                });
            // Same source priority and short-circuit: a real blaze level
            // wins before passive tags or campfire lit state are tested.
            if let Some(blaze) = blaze {
                return Some(blaze);
            }
            let passive = game
                .native_server_block_in_tag(state, "create:passive_boiler_heaters")
                .unwrap_or(false);
            let campfire = passive
                && game
                    .native_server_block_in_tag(state, "minecraft:campfires")
                    .unwrap_or(false);
            let lit = state.properties.get("lit").map(|v| v == "true");
            Some(rules::heat_for_block(blaze, passive, campfire, lit))
        })
    })
}
pub(super) fn write(game: &mut Game<'_>, pos: Pos, basin: &Basin) -> bool {
    let Some(changed) = game.native_with_mod_block_entity(pos, |entity| {
        if entity.id != ID || !crate::game::create_port::inventory_supported(entity) {
            return false;
        }
        // Preflight both canonical halves before any item/fluid write. Unsupported
        // original data is retained; it cannot become an empty tank by accident.
        let Ok((input, output)) = replacement_tanks(entity, basin) else {
            return false;
        };
        let Ok(pending_fluids) = spout::encode_fluid_buffer(&basin.fluid_overflow) else {
            return false;
        };
        let fluid_changed = set_tanks(entity, input, output);
        let spout_changed = spout::set_buffer(entity, basin.overflow.iter().map(native_stack))
            | spout::set_fluid_buffer(entity, pending_fluids);
        entity.items = basin
            .input
            .iter()
            .chain(&basin.output)
            .map(|s| s.as_ref().map(native_stack))
            .collect();
        data(entity) || fluid_changed || spout_changed
    }) else {
        return false;
    };
    if changed {
        game.native_block_entity_sync(pos);
        notify_contents(game, pos);
    }
    changed
}

fn read_tanks(entity: &ModBlockEntity, key: &str) -> Result<fluids::Tanks, fluids::Unsupported> {
    // A fresh factory-created entity has not yet had its first initialization
    // tick. Reading/simulating that default must not write or dirty the entity.
    let empty = empty_tanks();
    fluids::read_half(Some(entity.nbt.get(&key.into()).unwrap_or(&empty)))
}
fn replacement_tanks<I>(
    entity: &ModBlockEntity,
    basin: &rules::Basin<I, fluids::Key>,
) -> Result<(Tag, Tag), fluids::Unsupported> {
    let empty = empty_tanks();
    Ok((
        fluids::write_half(
            Some(entity.nbt.get(&"InputTanks".into()).unwrap_or(&empty)),
            &basin.input_fluids,
        )?,
        fluids::write_half(
            Some(entity.nbt.get(&"OutputTanks".into()).unwrap_or(&empty)),
            &basin.output_fluids,
        )?,
    ))
}
fn set_tanks(entity: &mut ModBlockEntity, input: Tag, output: Tag) -> bool {
    let changed = entity.nbt.get(&"InputTanks".into()) != Some(&input)
        || entity.nbt.get(&"OutputTanks".into()) != Some(&output);
    if changed {
        entity.nbt.insert("InputTanks".into(), input);
        entity.nbt.insert("OutputTanks".into(), output);
    }
    changed
}
fn fluid_state(game: &Game<'_>, pos: Pos) -> Option<FluidBasin> {
    if game.options.execution_role.is_client() {
        return None;
    }
    let BlockEntity::Mod(entity) = game.world.block_entities.get(&(pos[0], pos[1], pos[2]))? else {
        return None;
    };
    if entity.id != ID || !crate::game::create_port::inventory_supported(entity) {
        return None;
    }
    Some(FluidBasin {
        input_fluids: read_tanks(entity, "InputTanks").ok()?,
        output_fluids: read_tanks(entity, "OutputTanks").ok()?,
        ..FluidBasin::default()
    })
}
fn commit_fluids(game: &mut Game<'_>, pos: Pos, state: &FluidBasin) {
    let changed = game
        .native_with_mod_block_entity(pos, |entity| {
            if entity.id != ID || !crate::game::create_port::inventory_supported(entity) {
                return false;
            }
            let Ok((input, output)) = replacement_tanks(entity, state) else {
                return false;
            };
            set_tanks(entity, input, output)
        })
        .unwrap_or(false);
    if changed {
        game.native_block_entity_sync(pos);
        notify_contents(game, pos);
    }
}
pub(super) fn core_fluid(stack: &NativeFluidStack) -> Option<rules::Fluid<fluids::Key>> {
    (stack.amount > 0 && create_engine::fluid_transport::Fluid::from_id(&stack.fluid).is_some())
        .then(|| rules::Fluid {
            key: fluids::Key {
                id: stack.fluid.clone(),
                components: stack.components.clone(),
            },
            amount: stack.amount as u32,
        })
}
pub(super) fn native_fluid(stack: &rules::Fluid<fluids::Key>) -> NativeFluidStack {
    NativeFluidStack {
        fluid: stack.key.id.clone(),
        amount: stack.amount as i32,
        components: stack.key.components.clone(),
    }
}
/// Use the shared Horizon fluid helpers for sided automation.
pub(super) fn custom_fluids(block: &str, custom: &mut bool) {
    if matches!(block, ID | tank::BLOCK | item_drain::BLOCK) {
        *custom = true;
    }
}
pub(super) fn fluid_tanks(
    game: &Game<'_>,
    pos: Pos,
    side: Option<horizon_core::geometry::Direction>,
    out: &mut Option<Vec<NativeFluidTankView>>,
) {
    match game.native_block(pos).as_str() {
        tank::BLOCK => {
            *out = tank::view(game, pos);
            return;
        }
        item_drain::BLOCK => {
            if side != Some(horizon_core::geometry::Direction::Up) {
                *out = item_drain::fluid_view(game, pos);
            }
            return;
        }
        _ => {}
    }
    let Some(state) = fluid_state(game, pos) else {
        return;
    };
    *out = Some(
        (0..4)
            .map(|tank| NativeFluidTankView {
                tank,
                content: state.fluid(tank).map(native_fluid),
                capacity: rules::TANK_CAPACITY as i32,
                can_fill: tank >= 2,
                can_drain: true,
            })
            .collect(),
    );
}
pub(super) fn fluid_fill(
    game: &mut Game<'_>,
    pos: Pos,
    _side: Option<horizon_core::geometry::Direction>,
    resource: &NativeFluidStack,
    action: NativeFluidAction,
    out: &mut Option<i32>,
) {
    if game.native_block(pos) == tank::BLOCK {
        *out = tank::fill(game, pos, resource, action);
        return;
    }
    let Some(mut state) = fluid_state(game, pos) else {
        return;
    };
    *out = Some(0);
    let Some(resource) = core_fluid(resource) else {
        return;
    };
    // Injected into the defining crate today; reject future external variants.
    #[allow(unreachable_patterns)]
    let simulate = match action {
        NativeFluidAction::Simulate => true,
        NativeFluidAction::Execute => false,
        _ => return,
    };
    *out = Some(fill_input(game, pos, &mut state, &resource, simulate) as i32);
}
fn fill_input(
    game: &mut Game<'_>,
    pos: Pos,
    state: &mut FluidBasin,
    resource: &rules::Fluid<fluids::Key>,
    simulate: bool,
) -> u32 {
    let amount = state.fill_input_fluid(resource, simulate);
    if !simulate && amount > 0 {
        commit_fluids(game, pos, state);
    }
    amount
}
pub(super) fn fluid_drain(
    game: &mut Game<'_>,
    pos: Pos,
    side: Option<horizon_core::geometry::Direction>,
    request: &NativeFluidDrain,
    action: NativeFluidAction,
    out: &mut Option<NativeFluidStack>,
) {
    match game.native_block(pos).as_str() {
        tank::BLOCK => {
            *out = tank::drain(game, pos, request, action);
            return;
        }
        item_drain::BLOCK => {
            if side != Some(horizon_core::geometry::Direction::Up) {
                *out = item_drain::fluid_drain(game, pos, request, action);
            }
            return;
        }
        _ => {}
    }
    let Some(mut state) = fluid_state(game, pos) else {
        return;
    };
    let selected;
    let request = match request {
        NativeFluidDrain::Any(maximum) if *maximum > 0 => rules::FluidRequest::Any(*maximum as u32),
        NativeFluidDrain::Exact(stack) => {
            let Some(stack) = core_fluid(stack) else {
                return;
            };
            selected = stack;
            rules::FluidRequest::Exact(&selected)
        }
        _ => return,
    };
    // Injected into the defining crate today; reject future external variants.
    #[allow(unreachable_patterns)]
    let simulate = match action {
        NativeFluidAction::Simulate => true,
        NativeFluidAction::Execute => false,
        _ => return,
    };
    *out = drain(game, pos, &mut state, request, simulate)
        .as_ref()
        .map(native_fluid);
}
fn drain(
    game: &mut Game<'_>,
    pos: Pos,
    state: &mut FluidBasin,
    request: rules::FluidRequest<'_, fluids::Key>,
    simulate: bool,
) -> Option<rules::Fluid<fluids::Key>> {
    let report = state.drain_fluid(request, simulate);
    if !simulate && report.consumed > 0 {
        commit_fluids(game, pos, state);
    }
    report.returned
}
/// `BasinInventory.insertItem`: unique component-bearing stack per half and
/// only its first empty slot. Normal hopper transfers are one item at a time.
pub(super) fn can_place(
    slots: &[Option<ItemStack>],
    local: usize,
    stack: &ItemStack,
    maximum: u32,
) -> bool {
    let maximum = component_maximum(stack).unwrap_or(maximum);
    if local >= 9 || slots.len() < 9 || stack.count == 0 {
        return false;
    }
    let input = &slots[..9];
    if input.iter().enumerate().any(|(i, s)| {
        i != local
            && s.as_ref()
                .is_some_and(|s| s.count > 0 && s.same_item_same_components(stack))
    }) {
        return false;
    }
    match input[local].as_ref().filter(|s| s.count > 0) {
        Some(held) => held.count < maximum.min(64) && held.same_item_same_components(stack),
        None => {
            input
                .iter()
                .position(|s| s.as_ref().is_none_or(|s| s.count == 0))
                == Some(local)
        }
    }
}

pub(super) fn tick(game: &mut Game<'_>, pos: Pos, entity: &mut ModBlockEntity) -> bool {
    if entity.id != ID || !crate::game::create_port::inventory_supported(entity) {
        return false;
    }
    restore(entity);
    let changed = data(entity);
    initialize(entity);
    let owner = entity.revision();
    let already_ticked = SERVER.with(|cache| {
        let mut cache = cache.borrow_mut();
        let server = cache
            .dimension(std::ptr::from_ref(&game.world) as usize, game.dim.id())
            .entry(pos)
            .or_default();
        server.bind(owner);
        server.tick == Some(game.world.game_time)
    });
    if already_ticked {
        return changed;
    }
    SERVER.with(|cache| {
        cache
            .borrow_mut()
            .dimension(std::ptr::from_ref(&game.world) as usize, game.dim.id())
            .entry(pos)
            .or_default()
            .heat
            .reset()
    });
    for key in ["InputTanks", "OutputTanks"] {
        if let Some(tanks) = entity.nbt.get_mut(&key.into()) {
            let _ = fluids::tick_half(tanks);
        }
    }
    let (scheduled, refresh_spout) = SERVER.with(|cache| {
        let mut cache = cache.borrow_mut();
        let s = cache
            .dimension(std::ptr::from_ref(&game.world) as usize, game.dim.id())
            .entry(pos)
            .or_default();
        if s.tick == Some(game.world.game_time) {
            return (false, false);
        }
        if s.tick.is_some_and(|t| t > game.world.game_time) {
            *s = Server {
                owner: Some(owner),
                ..Server::default()
            };
        }
        // The duplicate-tick return above deliberately leaves this flag set.
        let mut scheduled = std::mem::take(&mut s.contents_changed) || !s.initialized;
        let refresh_spout = !s.initialized || s.lazy <= 0;
        if !s.initialized {
            s.initialized = true;
            s.backup -= 1;
        }
        if s.lazy <= 0 {
            s.lazy = 10;
            if s.backup <= 0 {
                s.backup = 20;
                scheduled |= entity.items.iter().flatten().any(|s| s.count > 0)
                    || ["InputTanks", "OutputTanks"].into_iter().any(|key| {
                        read_tanks(entity, key)
                            .is_ok_and(|tanks| tanks.iter().flatten().any(|f| f.amount > 0))
                    });
            } else {
                s.backup -= 1;
            }
        } else {
            s.lazy -= 1;
        }
        s.tick = Some(game.world.game_time);
        (scheduled, refresh_spout)
    });
    let reason = unsupported(game, pos, entity);
    let spout_changed = reason.is_none() && spout::tick(game, pos, entity, refresh_spout);
    // Canonical serialization may normalize a supported loaded inventory's
    // order/numeric tags. Basin.read does not notify contents: only genuine
    // inventory/fluid events, initialization and the lazy backup wake it.
    if scheduled || spout_changed {
        crate::game::create_port_mixer::schedule(game, [pos[0], pos[1] + 2, pos[2]]);
        crate::game::create_port_press_basin::schedule(game, [pos[0], pos[1] + 2, pos[2]]);
    }
    if changed {
        let dim = game.dim.id().to_owned();
        game.native_update_output_neighbors(&dim, pos);
    }
    match reason {
        Some(reason) => {
            entity.nbt.insert(
                "create_horizon:Unsupported".into(),
                Tag::String(reason.into()),
            );
        }
        None => {
            entity.nbt.remove(&"create_horizon:Unsupported".into());
        }
    }
    // Falling-item intake deliberately waits for the entity-sensitive basin
    // collision API; no guessed contact height or direct teleport is used.
    changed || spout_changed
}

pub(super) fn predicts_wrench(game: &Game<'_>, pos: Pos) -> bool {
    spout::wrench_held(game, pos)
}

pub(super) fn wrench(game: &mut Game<'_>, pos: Pos, face: Pos) -> bool {
    spout::wrench(game, pos, face)
}
pub(super) fn reacts(game: &Game<'_>, pos: Pos) -> bool {
    game.native_on("create")
        && game.native_block(pos) == ID
        && game.held().is_none_or(|s| {
            s.count == 0
                || matches!(
                    s.item.as_ref(),
                    "minecraft:air"
                        | "minecraft:bucket"
                        | "minecraft:sponge"
                        | emptying::GLASS_BOTTLE
                )
                || emptying::can_empty(game, s)
        })
}
pub(super) fn give_container(game: &mut Game<'_>, pos: Pos, stack: ItemStack) {
    let player = game.native_acting_id();
    if let Some(rest) = game.native_give_stack(player, stack) {
        if let Some(eye) = game.eye_position() {
            game.throw_from_eyes(rest, eye, false);
        } else {
            game.spawn_item(rest, pos.map(|v| f64::from(v) + 0.5), [0.0, 0.2, 0.0], 10);
        }
    }
}
fn fluid_container_click(game: &mut Game<'_>, pos: Pos, held: &ItemStack) -> bool {
    match held.item.as_ref() {
        _ if emptying::can_empty(game, held) => {
            let Some((fluid, amount, remainder)) = emptying::empty(game, held) else {
                return true;
            };
            let Some(mut state) = fluid_state(game, pos) else {
                return true;
            };
            let fluid = rules::Fluid {
                key: fluids::Key {
                    id: fluid.to_owned(),
                    components: Compound::new(),
                },
                amount: amount as u32,
            };
            if fill_input(game, pos, &mut state, &fluid, true) != fluid.amount {
                return true;
            }
            fill_input(game, pos, &mut state, &fluid, false);
            if !game.creative {
                if held.count == 1 {
                    *game.held_mut() = Some(remainder);
                } else {
                    if let Some(s) = game.held_mut() {
                        s.count -= 1;
                    }
                    give_container(game, pos, remainder);
                }
            }
            true
        }
        "minecraft:bucket" | emptying::GLASS_BOTTLE => {
            let bottle = held.item.as_ref() == emptying::GLASS_BOTTLE;
            let required = if bottle {
                emptying::BOTTLE_AMOUNT
            } else {
                1000
            };
            let Some(mut state) = fluid_state(game, pos) else {
                return true;
            };
            for tank in 0..4 {
                let Some(mut fluid) = state.fluid(tank).cloned() else {
                    continue;
                };
                // API item containers cannot carry an opaque fluid component
                // patch. Refuse it explicitly rather than flattening it.
                if !fluid.key.components.is_empty() || fluid.amount < required as u32 {
                    continue;
                }
                let filled = if bottle {
                    if fluid.key.id != Fluid::Water.id() {
                        continue;
                    }
                    ItemStack::new("minecraft:potion", 1).with_potion(Fluid::Water.id())
                } else {
                    let Some((_, filled)) = game
                        .native_item_fluid_fill(held, &fluid.key.id, required)
                        .filter(|(amount, _)| *amount == required)
                    else {
                        continue;
                    };
                    filled
                };
                fluid.amount = required as u32;
                drain(
                    game,
                    pos,
                    &mut state,
                    rules::FluidRequest::Exact(&fluid),
                    false,
                );
                if !game.creative {
                    game.consume_held();
                    give_container(game, pos, filled);
                }
                return true;
            }
            true // GenericItemFilling claims even a refused/insufficient container.
        }
        "minecraft:sponge" => fluid_state(game, pos).is_some_and(|mut state| {
            drain(
                game,
                pos,
                &mut state,
                rules::FluidRequest::Any(i32::MAX as u32),
                false,
            )
            .is_some()
        }),
        _ => false,
    }
}
pub(super) fn right_click(game: &mut Game<'_>, pos: Pos) -> bool {
    if crate::game::create_port::inventory_blocked(game, pos) {
        return true;
    }
    if !reacts(game, pos) {
        return false;
    }
    if let Some(held) = game
        .held()
        .filter(|s| s.count > 0 && s.item.as_ref() != "minecraft:air")
        .cloned()
    {
        return fluid_container_click(game, pos, &held);
    }
    let stacks = game
        .native_with_mod_block_entity(pos, |entity| {
            restore(entity);
            let stacks = entity
                .items
                .iter_mut()
                .filter_map(Option::take)
                .collect::<Vec<_>>();
            data(entity);
            stacks
        })
        .unwrap_or_default();
    let player = game.native_acting_id();
    let success = !stacks.is_empty();
    for stack in stacks {
        if let Some(rest) = game.native_give_stack(player, stack) {
            if let Some(eye) = game.eye_position() {
                game.throw_from_eyes(rest, eye, false);
            } else {
                game.spawn_item(rest, pos.map(|v| f64::from(v) + 0.5), [0.0, 0.2, 0.0], 10);
            }
        }
    }
    if success {
        let pitch = 1.0 + game.world.random.next_float();
        game.with_level(|_, level, _| {
            level.native_play_sound(
                "minecraft:entity.item.pickup",
                pos.map(|v| f64::from(v) + 0.5),
                7,
                0.2,
                pitch,
            );
        });
    }
    game.native_block_entity_sync(pos);
    crate::game::create_port_mixer::basin_removed(game, [pos[0], pos[1] + 2, pos[2]]);
    crate::game::create_port_press_basin::basin_removed(game, [pos[0], pos[1] + 2, pos[2]]);
    true
}

pub(super) fn removed(game: &mut Game<'_>, pos: Pos) {
    spout::drop_items(game, pos);
    SERVER.with(|cache| {
        cache
            .borrow_mut()
            .dimension(std::ptr::from_ref(&game.world) as usize, game.dim.id())
            .remove(&pos);
    });
    crate::game::create_port_mixer::basin_removed(game, [pos[0], pos[1] + 2, pos[2]]);
    crate::game::create_port_press_basin::basin_removed(game, [pos[0], pos[1] + 2, pos[2]]);
}
pub(super) fn maintenance(game: &mut Game<'_>) {
    SERVER.with(|cache| {
        cache
            .borrow_mut()
            .dimension(std::ptr::from_ref(&game.world) as usize, game.dim.id())
            .retain(|p, _| game.world.loaded(p[0], p[2]) && game.native_block(*p) == ID);
    });
}
/// Item spouts between Basins.
mod spout {
    use super::{
        BlockEntity, Game, ID, ItemStack, ModBlockEntity, Pos, Tag, core_stack, data, fluids,
        notify_contents, read, read_tanks, restore, rules, unsupported, write,
    };
    use create_engine::placement::Direction;
    use horizon_items::item_nbt::{item_from_nbt, item_to_nbt};

    const PREFERRED: &str = "PreferredSpoutput";
    const DISABLED: &str = "DisabledSpoutput";
    const OVERFLOW: &str = "Overflow";
    const FLUID_OVERFLOW: &str = "FluidOverflow";
    const FLUID_STACK_CAPACITY: u32 = i32::MAX as u32;
    type Fluid = rules::Fluid<fluids::Key>;
    // Catnip Iterate.getHorizontals uses Direction.from2DDataValue. Java
    // keeps the last eligible side, so search in reverse order.
    const PRIORITY: [Direction; 4] = [
        Direction::East,
        Direction::North,
        Direction::West,
        Direction::South,
    ];

    pub(super) struct Settings {
        preferred: Option<Direction>,
        disabled: Vec<Direction>,
    }

    fn direction_tag(direction: Direction) -> Tag {
        Tag::String(direction.name().to_ascii_uppercase().as_str().into())
    }

    fn read_direction(tag: &Tag) -> Option<Direction> {
        let Tag::String(name) = tag else { return None };
        let name = name.to_string().ok()?;
        Direction::ALL
            .into_iter()
            .find(|direction| direction.name().eq_ignore_ascii_case(&name))
    }

    impl Settings {
        pub(super) fn read(entity: &ModBlockEntity) -> Option<Self> {
            let preferred = match entity.nbt.get(&PREFERRED.into()) {
                Some(value) => Some(read_direction(value)?),
                None => None,
            };
            let disabled = match entity.nbt.get(&DISABLED.into()) {
                None => Vec::new(),
                Some(Tag::List(rows)) if rows.len() <= Direction::ALL.len() => rows
                    .iter()
                    .map(read_direction)
                    .collect::<Option<Vec<_>>>()?,
                _ => return None,
            };
            Some(Self {
                preferred,
                disabled,
            })
        }

        fn write(&self, entity: &mut ModBlockEntity) {
            if let Some(direction) = self.preferred {
                entity
                    .nbt
                    .insert(PREFERRED.into(), direction_tag(direction));
            } else {
                entity.nbt.remove(&PREFERRED.into());
            }
            entity.nbt.insert(
                DISABLED.into(),
                Tag::List(self.disabled.iter().copied().map(direction_tag).collect()),
            );
        }
    }

    pub(super) fn buffer(entity: &ModBlockEntity) -> Option<Vec<ItemStack>> {
        match entity.nbt.get(&OVERFLOW.into()) {
            None => Some(Vec::new()),
            Some(Tag::List(stacks)) => stacks
                .iter()
                .map(|tag| item_from_nbt(tag).filter(|stack| stack.count > 0))
                .collect(),
            _ => None,
        }
    }

    pub(super) fn set_buffer(
        entity: &mut ModBlockEntity,
        stacks: impl IntoIterator<Item = ItemStack>,
    ) -> bool {
        let value = Tag::List(
            stacks
                .into_iter()
                .map(|stack| item_to_nbt(&stack))
                .collect(),
        );
        let changed = entity.nbt.get(&OVERFLOW.into()) != Some(&value);
        if changed {
            entity.nbt.insert(OVERFLOW.into(), value);
        }
        changed
    }

    pub(super) fn fluid_buffer(entity: &ModBlockEntity) -> Result<Vec<Fluid>, fluids::Unsupported> {
        match entity.nbt.get(&FLUID_OVERFLOW.into()) {
            None => Ok(Vec::new()),
            Some(Tag::List(stacks)) => stacks
                .iter()
                .map(|tag| fluids::read_stack(Some(tag), FLUID_STACK_CAPACITY))
                .collect(),
            _ => Err(fluids::Unsupported("noncanonical basin fluid spout buffer")),
        }
    }

    pub(super) fn encode_fluid_buffer(stacks: &[Fluid]) -> Result<Tag, fluids::Unsupported> {
        stacks
            .iter()
            .map(|fluid| fluids::write_stack(fluid, FLUID_STACK_CAPACITY))
            .collect::<Result<Vec<_>, _>>()
            .map(Tag::List)
    }

    pub(super) fn set_fluid_buffer(entity: &mut ModBlockEntity, value: Tag) -> bool {
        let changed = entity.nbt.get(&FLUID_OVERFLOW.into()) != Some(&value);
        if changed {
            entity.nbt.insert(FLUID_OVERFLOW.into(), value);
        }
        changed
    }

    pub(super) fn facing(game: &Game<'_>, pos: Pos) -> Option<Direction> {
        let name = game.native_block_property(pos, "facing")?;
        Direction::ALL
            .into_iter()
            .find(|direction| direction.name() == name)
    }

    fn neighbor(pos: Pos, direction: Direction) -> Pos {
        let offset = direction.vector();
        std::array::from_fn(|axis| pos[axis] + offset[axis])
    }

    fn target(pos: Pos, direction: Direction) -> Pos {
        let [x, y, z] = neighbor(pos, direction);
        [x, y - 1, z]
    }

    fn has_receiver(game: &Game<'_>, pos: Pos, direction: Direction) -> bool {
        let [x, y, z] = target(pos, direction);
        game.world.loaded(x, z)
            && game.native_block([x, y, z]) == ID
            && matches!(game.world.block_entities.get(&(x, y, z)), Some(BlockEntity::Mod(entity))
                if entity.id == ID && unsupported(game, [x, y, z], entity).is_none())
    }

    fn can_output_to(game: &Game<'_>, pos: Pos, direction: Direction) -> bool {
        has_receiver(game, pos, direction)
            && game
                .block_collision_shape(neighbor(pos, direction))
                .is_empty()
    }

    pub(super) fn output_mode(game: &Game<'_>, pos: Pos) -> rules::OutputMode {
        match facing(game, pos) {
            Some(direction) if direction != Direction::Down => {
                let has_receiver = has_receiver(game, pos, direction);
                rules::OutputMode::Spout {
                    item_destination: has_receiver,
                    fluid_destination: has_receiver,
                }
            }
            _ => rules::OutputMode::Internal,
        }
    }

    fn next_facing(
        game: &Game<'_>,
        pos: Pos,
        settings: &Settings,
        current: Direction,
    ) -> Direction {
        if current != Direction::Down {
            let [x, y, z] = target(pos, current);
            if !game.world.loaded(x, z) {
                return current;
            }
            let block = game.native_block([x, y, z]);
            if block.starts_with("create:") && !has_receiver(game, pos, current) {
                // Keep a saved route to a mod machine whose intake isn't wired yet.
                return current;
            }
        }
        settings
            .preferred
            .filter(|&direction| direction != Direction::Up && can_output_to(game, pos, direction))
            .or_else(|| {
                PRIORITY.into_iter().find(|direction| {
                    !settings.disabled.contains(direction) && can_output_to(game, pos, *direction)
                })
            })
            .unwrap_or(Direction::Down)
    }

    fn migrate(entity: &mut ModBlockEntity, next: Direction) {
        if next == Direction::Down {
            return;
        }
        let Some(mut pending) = buffer(entity) else {
            return;
        };
        if let Ok(output) = read_tanks(entity, "OutputTanks")
            && output.iter().any(Option::is_some)
            && let Ok(mut fluids) = fluid_buffer(entity)
        {
            fluids.extend(output.into_iter().flatten());
            if let (Ok(buffer), Ok(half)) = (
                encode_fluid_buffer(&fluids),
                fluids::write_half(entity.nbt.get(&"OutputTanks".into()), &[None, None]),
            ) {
                set_fluid_buffer(entity, buffer);
                entity.nbt.insert("OutputTanks".into(), half);
            }
        }
        restore(entity);
        for slot in entity.items.iter_mut().skip(9).take(9) {
            if let Some(stack) = slot.take() {
                pending.push(stack);
            }
        }
        set_buffer(entity, pending);
        data(entity);
    }

    fn flush(game: &mut Game<'_>, pos: Pos, entity: &mut ModBlockEntity) -> bool {
        let (Some(mut pending), Ok(mut pending_fluids)) = (buffer(entity), fluid_buffer(entity))
        else {
            return false;
        };
        if pending.is_empty() && pending_fluids.is_empty() {
            return false;
        }
        let Some(direction) = facing(game, pos) else {
            return false;
        };
        if direction == Direction::Down {
            for stack in pending {
                game.pop_resource(pos, stack);
            }
            return set_buffer(entity, []) | set_fluid_buffer(entity, Tag::List(Vec::new()));
        }
        if !has_receiver(game, pos, direction) {
            return false;
        }
        let receiver = target(pos, direction);
        let Some(mut state) = read(game, receiver) else {
            return false;
        };
        let mut moved = false;
        pending.retain_mut(|stack| {
            let mut remainder = core_stack(game, stack);
            for slot in 0..9 {
                remainder = state.insert_input(slot, remainder, false);
                if remainder.count == 0 {
                    break;
                }
            }
            moved |= stack.count != remainder.count;
            stack.count = remainder.count;
            stack.count > 0
        });
        pending_fluids.retain(|fluid| {
            if state.fill_input_fluid(fluid, true) != fluid.amount {
                return true;
            }
            state.fill_input_fluid(fluid, false);
            moved = true;
            false
        });
        if !moved {
            return false;
        }
        let Ok(pending_fluids) = encode_fluid_buffer(&pending_fluids) else {
            return false;
        };
        write(game, receiver, &state)
            && (set_buffer(entity, pending) | set_fluid_buffer(entity, pending_fluids))
    }

    pub(super) fn tick(
        game: &mut Game<'_>,
        pos: Pos,
        entity: &mut ModBlockEntity,
        refresh: bool,
    ) -> bool {
        let mut changed = false;
        if refresh
            && let Some(current) = facing(game, pos)
            && let Some(settings) = Settings::read(entity)
        {
            let next = next_facing(game, pos, &settings, current);
            if next != current && game.native_set_block_property(pos, "facing", next.name()) {
                migrate(entity, next);
                changed = true;
            }
        }
        flush(game, pos, entity) || changed
    }

    pub(super) fn wrench_held(game: &Game<'_>, pos: Pos) -> bool {
        game.native_on("create")
            && game.native_block(pos) == ID
            && !game.native_sneaking()
            && !game.spectator()
            && game
                .held()
                .is_some_and(|stack| super::super::create_port_chassis::wrench(game, stack))
    }

    pub(super) fn wrench(game: &mut Game<'_>, pos: Pos, face: Pos) -> bool {
        if !wrench_held(game, pos) {
            return false;
        }
        let Some(clicked) = Direction::from_vector(face) else {
            return false;
        };
        let Some(current) = facing(game, pos) else {
            return true;
        };
        let Some(BlockEntity::Mod(entity)) =
            game.world.block_entities.get(&(pos[0], pos[1], pos[2]))
        else {
            return true;
        };
        if unsupported(game, pos, entity).is_some() {
            return true;
        }
        let Some(mut settings) = Settings::read(entity) else {
            return true;
        };
        settings.disabled.retain(|&direction| direction != clicked);
        if clicked == current {
            if settings.preferred == Some(clicked) {
                settings.preferred = None;
            }
            settings.disabled.push(clicked);
        } else {
            settings.preferred = Some(clicked);
        }
        let next = next_facing(game, pos, &settings, current);
        let changed = next != current && game.native_set_block_property(pos, "facing", next.name());
        game.native_with_mod_block_entity(pos, |entity| {
            settings.write(entity);
            if changed {
                migrate(entity, next);
            }
        });
        game.native_block_entity_sync(pos);
        if changed {
            notify_contents(game, pos);
        }
        true
    }

    pub(super) fn drop_items(game: &mut Game<'_>, pos: Pos) {
        let Some(BlockEntity::Mod(entity)) =
            game.world.block_entities.get(&(pos[0], pos[1], pos[2]))
        else {
            return;
        };
        let Some(stacks) = buffer(entity) else { return };
        for stack in stacks {
            game.pop_resource(pos, stack);
        }
    }
}

/// FluidTransportBehaviour adapter for directed pipe networks.
pub(super) mod pump {
    use super::*;
    use crate::game::create_port_fluid_open_effects as open_effects;
    use crate::game::create_port_fluid_open_end as open;
    use create_engine::{fluid_transport as flow, placement::Direction};
    use horizon_world::{
        chunk::BlockState,
        level::{BlockId, PlacementContext},
        registry::BlockStateId,
    };
    use std::{
        collections::{BTreeSet, VecDeque},
        rc::Rc,
    };

    pub(in crate::game) const PUMP: &str = "create:mechanical_pump";
    pub(in crate::game) const PIPE: &str = "create:fluid_pipe";
    pub(in crate::game) const VALVE: &str = "create:fluid_valve";
    const PRESSURE_REBUILD_TICKS: u8 = 2;

    struct Line {
        pump: Pos,
        front: Direction,
        sources: Rc<[End]>,
        source_faces: BTreeMap<(Pos, u8), End>,
        open_sources: Box<[End]>,
        source_surfaces: RefCell<Option<Rc<[BlockId]>>>,
        targets: Vec<Target>,
        devices: Vec<Hop>,
        by_pos: BTreeMap<Pos, usize>,
        pump_count: usize,
        opposing: Vec<Pos>,
        overlap: bool,
        valves: Rc<[(Pos, bool)]>,
    }

    impl Line {
        fn source(&self, pos: Pos, side: Direction) -> Option<End> {
            self.source_faces.get(&(pos, side as u8)).copied()
        }
    }

    #[derive(Clone, Copy, PartialEq, Eq)]
    struct End {
        pos: Pos,
        face: Direction,
        open: bool,
    }

    impl End {
        fn anchor(self) -> Pos {
            relative(self.pos, self.face, 1)
        }

        fn port(self) -> Direction {
            self.face.opposite()
        }
    }

    #[derive(Clone, Copy)]
    struct Target {
        end: End,
        device: usize,
    }

    #[derive(Clone, Copy)]
    struct Hop {
        pos: Pos,
        ports: u8,
        inlets: u8,
        outlets: u8,
        pump: Pos,
        other: Option<PressureContribution>,
        divisor: usize,
    }

    #[derive(Clone, Copy)]
    struct PressureContribution {
        pump: Pos,
        inlets: u8,
        outlets: u8,
        divisor: usize,
    }

    impl Hop {
        fn new(pos: Pos, inlets: u8, outlets: u8, pump: Pos) -> Self {
            Self {
                pos,
                ports: inlets | outlets,
                inlets,
                outlets,
                pump,
                other: None,
                divisor: 1,
            }
        }

        fn inlets(self) -> impl Iterator<Item = Direction> {
            Direction::ALL
                .into_iter()
                .filter(move |&side| self.inlets & bit(side) != 0)
        }

        fn outlets(self) -> impl Iterator<Item = Direction> {
            Direction::ALL
                .into_iter()
                .filter(move |&side| self.outlets & bit(side) != 0)
        }

        fn matches(self, state: &BlockState) -> bool {
            port_mask(state) == self.ports
        }
    }

    fn bit(side: Direction) -> u8 {
        1 << side as usize
    }

    type Fluid = rules::Fluid<fluids::Key>;

    enum Endpoint {
        Tank(tank::Record),
        Basin {
            pos: Pos,
            tanks: Box<FluidBasin>,
        },
        Drain(Pos, item_drain::Tank),
        Open {
            end: End,
            space: open::Space,
            buffer: open::Buffer,
            world: Option<open::WorldWrite>,
        },
    }

    enum FluidWrite {
        Tank(tank::Record, Tag),
        Basin(Pos, Tag, Tag),
        Drain(Pos, item_drain::Tank),
        Open(End, Tag, Option<open::WorldWrite>),
    }

    impl Endpoint {
        fn storage(game: &Game<'_>, pos: Pos, side: Direction) -> Option<Self> {
            match game.native_block(pos).as_str() {
                tank::BLOCK => Some(Self::Tank(tank::endpoint(game, pos)?)),
                ID => Some(Self::Basin {
                    pos,
                    tanks: Box::new(fluid_state(game, pos)?),
                }),
                item_drain::BLOCK if side != Direction::Up => {
                    Some(Self::Drain(pos, item_drain::fluid_tank(game, pos)?))
                }
                _ => None,
            }
        }

        fn at(game: &Game<'_>, end: End, current: (Pos, &ModBlockEntity)) -> Option<Self> {
            if !end.open {
                return Self::storage(game, end.pos, end.face);
            }
            let space = open::Space::read(game, end.pos, end.face)?;
            let at = end.anchor();
            let entity = if at == current.0 {
                current.1
            } else {
                device_at(game, at)?
            };
            let buffer = open::Buffer::read(open_data(entity, end.port()), end.port())?;
            Some(Self::Open {
                end,
                space,
                buffer,
                world: None,
            })
        }

        fn owner(&self) -> Pos {
            match self {
                Self::Tank(record) => record.tank.root,
                Self::Basin { pos, .. } | Self::Drain(pos, _) => *pos,
                Self::Open { end, .. } => end.pos,
            }
        }

        fn amount(&self) -> u32 {
            match self {
                Self::Tank(record) => record.fluid.as_ref().map_or(0, |fluid| fluid.amount),
                Self::Basin { tanks, .. } => (0..4)
                    .filter_map(|index| tanks.fluid(index))
                    .map(|fluid| fluid.amount)
                    .sum(),
                Self::Drain(_, tank) => tank.amount as u32,
                Self::Open { buffer, .. } => buffer.fluid.as_ref().map_or(0, |fluid| fluid.amount),
            }
        }

        fn sample(&mut self) -> Option<flow::Fluid> {
            let sampled;
            let fluid = match self {
                Self::Tank(record) => record.fluid.as_ref()?,
                Self::Basin { tanks, .. } => {
                    sampled = tanks
                        .drain_fluid(rules::FluidRequest::Any(1), true)
                        .returned?;
                    &sampled
                }
                Self::Drain(_, tank) => {
                    return (tank.amount > 0)
                        .then(|| flow::Fluid::from_id(tank.fluid))
                        .flatten();
                }
                Self::Open { buffer, space, .. } => {
                    return buffer
                        .fluid
                        .as_ref()
                        .and_then(|stack| flow::Fluid::from_id(&stack.key.id))
                        .or_else(|| space.source().map(|(kind, _)| kind));
                }
            };
            if !fluid.key.components.is_empty() {
                return None;
            }
            flow::Fluid::from_id(&fluid.key.id)
        }

        fn drain(&mut self, game: &Game<'_>, request: &Fluid, simulate: bool) -> u32 {
            match self {
                Self::Tank(record) => {
                    let Some(stored) = record.fluid.as_mut().filter(|f| f.key == request.key)
                    else {
                        return 0;
                    };
                    let drained = request.amount.min(stored.amount);
                    if !simulate {
                        stored.amount -= drained;
                        if stored.amount == 0 {
                            record.fluid = None;
                        }
                    }
                    drained
                }
                Self::Basin { tanks, .. } => {
                    let result = tanks.drain_fluid(rules::FluidRequest::Exact(request), simulate);
                    if result.source_discarded > 0 {
                        return 0;
                    }
                    result.returned.map_or(0, |fluid| fluid.amount)
                }
                Self::Drain(_, tank) => {
                    if request.key.id != tank.fluid || !request.key.components.is_empty() {
                        return 0;
                    }
                    let drained = request.amount.min(tank.amount as u32);
                    if !simulate {
                        tank.set_amount(tank.amount - drained as i32);
                    }
                    drained
                }
                Self::Open {
                    buffer,
                    space,
                    world,
                    ..
                } => {
                    let (amount, change) = buffer.drain(game, space, request, simulate);
                    *world = change;
                    amount
                }
            }
        }

        fn fill(&mut self, game: &Game<'_>, resource: &Fluid) -> u32 {
            match self {
                Self::Tank(record) => {
                    let capacity = record.capacity();
                    match &mut record.fluid {
                        Some(stored) if stored.key == resource.key => {
                            let accepted =
                                resource.amount.min(capacity.saturating_sub(stored.amount));
                            stored.amount += accepted;
                            accepted
                        }
                        None => {
                            let mut stored = resource.clone();
                            stored.amount = stored.amount.min(capacity);
                            let accepted = stored.amount;
                            record.fluid = Some(stored);
                            accepted
                        }
                        Some(_) => 0,
                    }
                }
                Self::Basin { tanks, .. } => tanks.fill_input_fluid(resource, false),
                Self::Drain(..) => 0,
                Self::Open {
                    buffer,
                    space,
                    world,
                    ..
                } => {
                    if world.is_some() {
                        return 0;
                    }
                    let (amount, change) = buffer.fill(game, space, resource);
                    *world = change;
                    amount
                }
            }
        }

        fn prepare(self, game: &Game<'_>) -> Option<FluidWrite> {
            match self {
                Self::Tank(record) => {
                    let content = tank::prepare_content(game, &record)?;
                    Some(FluidWrite::Tank(record, content))
                }
                Self::Basin {
                    pos: [x, y, z],
                    tanks,
                } => {
                    let BlockEntity::Mod(entity) = game.world.block_entities.get(&(x, y, z))?
                    else {
                        return None;
                    };
                    let (input, output) = replacement_tanks(entity, &tanks).ok()?;
                    Some(FluidWrite::Basin([x, y, z], input, output))
                }
                Self::Drain(pos, tank) => Some(FluidWrite::Drain(pos, tank)),
                Self::Open {
                    end, buffer, world, ..
                } => Some(FluidWrite::Open(
                    end,
                    buffer.write(end.anchor(), end.port())?,
                    world,
                )),
            }
        }
    }

    impl FluidWrite {
        fn apply_world(&mut self, game: &mut Game<'_>) -> Option<bool> {
            if let Self::Open(_, _, world) = self
                && let Some(change) = world.take()
            {
                return change.apply(game);
            }
            Some(false)
        }

        fn set(self, game: &mut Game<'_>, pos: Pos, entity: &mut ModBlockEntity) -> Notification {
            match self {
                Self::Tank(record, content) => {
                    tank::set_content(game, record.tank.root, content);
                    Notification::Tank(record)
                }
                Self::Basin(pos, input, output) => {
                    game.native_with_mod_block_entity(pos, |entity| {
                        set_tanks(entity, input, output)
                    });
                    Notification::Basin(pos)
                }
                Self::Drain(pos, tank) => {
                    item_drain::set_fluid(game, pos, &tank);
                    Notification::Drain(pos)
                }
                Self::Open(end, tag, _) => {
                    let at = end.anchor();
                    if at == pos {
                        save_open(entity, end.port(), tag);
                    } else {
                        game.native_with_mod_block_entity(at, |entity| {
                            save_open(entity, end.port(), tag)
                        });
                    }
                    Notification::Open(at)
                }
            }
        }
    }

    enum Notification {
        Tank(tank::Record),
        Basin(Pos),
        Drain(Pos),
        Open(Pos),
    }

    impl Notification {
        fn send(self, game: &mut Game<'_>) {
            match self {
                Self::Tank(record) => tank::notify(game, &record),
                Self::Basin(pos) => {
                    game.native_block_entity_sync(pos);
                    notify_contents(game, pos);
                }
                Self::Drain(pos) => item_drain::notify_fluid(game, pos),
                Self::Open(pos) => game.native_block_entity_sync(pos),
            }
        }
    }

    fn transfer(
        game: &mut Game<'_>,
        pos: Pos,
        entity: &mut ModBlockEntity,
        source: End,
        targets: &[End],
        kind: flow::Fluid,
        rate: i32,
    ) -> (bool, bool) {
        if targets.is_empty() || rate <= 0 {
            return (false, false);
        }
        let source_end = source;
        let Some(mut source) = Endpoint::at(game, source_end, (pos, entity)) else {
            return (false, false);
        };
        let mut resource = Fluid {
            key: fluids::Key {
                id: kind.id().into(),
                components: Compound::new(),
            },
            amount: rate as u32,
        };
        let available = source.drain(game, &resource, true);
        if available == 0 {
            return (false, false);
        }
        let mut by_owner = BTreeMap::new();
        let mut stores = Vec::new();
        let destinations: Vec<_> = targets
            .iter()
            .map(|target| {
                let target = Endpoint::at(game, *target, (pos, entity))?;
                let owner = target.owner();
                if owner == source.owner() {
                    return None;
                }
                Some(*by_owner.entry(owner).or_insert_with(|| {
                    let index = stores.len();
                    stores.push((target, 0));
                    index
                }))
            })
            .collect();
        flow::distribute(available, destinations.len(), |i, quota| {
            let Some(index) = destinations[i] else {
                return 0;
            };
            resource.amount = quota;
            let (target, filled) = &mut stores[index];
            let accepted = target.fill(game, &resource);
            *filled += accepted;
            accepted
        });
        let mut reactions = Vec::new();
        let mut writes = Vec::new();
        for (mut target, filled) in stores {
            if let Endpoint::Open { world, .. } = &mut target
                && world.as_ref().is_some_and(open::WorldWrite::is_reaction)
            {
                reactions.extend(world.take());
            }
            if filled != 0 {
                let Some(write) = target.prepare(game) else {
                    return (false, false);
                };
                writes.push((filled, write));
            }
        }
        let mut refresh = false;
        for reaction in reactions {
            refresh |= reaction.apply(game).unwrap_or(false);
        }
        // An open source has to claim its world fluid first. Retain any
        // unused part of that claim in the inlet's existing buffer.
        let prepaid = if source_end.open {
            resource.amount = writes.iter().map(|(filled, _)| filled).sum();
            if resource.amount == 0 || source.drain(game, &resource, false) != resource.amount {
                return (false, refresh);
            }
            let Endpoint::Open { world, .. } = &mut source else {
                return (false, refresh);
            };
            if let Some(change) = world.take() {
                let Some(rebuild) = change.apply(game) else {
                    return (false, refresh);
                };
                refresh |= rebuild && open_source_rebuilds(game, source_end);
            }
            resource.amount
        } else {
            0
        };
        // A surface changed by an earlier outlet can invalidate a later
        // one. Charge the source only for destinations that accepted fluid.
        writes.retain_mut(|(_, write)| match write.apply_world(game) {
            Some(rebuild) => {
                refresh |= rebuild;
                true
            }
            None => false,
        });
        resource.amount = writes.iter().map(|(filled, _)| filled).sum();
        if let Endpoint::Open { buffer, .. } = &mut source {
            if prepaid > resource.amount {
                let mut returned = resource.clone();
                returned.amount = prepaid - resource.amount;
                buffer.refund(returned);
            }
        } else if resource.amount == 0 || source.drain(game, &resource, false) != resource.amount {
            return (false, refresh);
        }
        let Some(source_write) = source.prepare(game) else {
            return (false, refresh);
        };
        let exposed: Vec<_> = writes
            .iter()
            .filter_map(|(_, write)| match write {
                FluidWrite::Open(end, ..) => Some(*end),
                _ => None,
            })
            .collect();
        // Contents are committed before any dependent notification.
        let updates: Vec<_> = std::iter::once(source_write)
            .chain(writes.into_iter().map(|(_, write)| write))
            .map(|write| write.set(game, pos, entity))
            .collect();
        let mut current = false;
        for update in updates {
            if matches!(update, Notification::Open(at) if at == pos) {
                current = true;
            } else {
                update.send(game);
            }
        }
        for end in exposed {
            open_effects::apply(game, end.pos, end.port(), kind);
        }
        (current, refresh)
    }

    fn is_endpoint(name: &str, face: Direction) -> bool {
        matches!(name, tank::BLOCK | ID) || (name == item_drain::BLOCK && face != Direction::Up)
    }

    fn endpoint(game: &Game<'_>, pos: Pos, block: &BlockState, face: Direction) -> Option<End> {
        if is_endpoint(&block.name, face) {
            Endpoint::storage(game, pos, face)?;
            return Some(End {
                pos,
                face,
                open: false,
            });
        }
        if matches!(block.name.as_str(), PIPE | PUMP | VALVE) {
            return None;
        }
        open::Space::read(game, pos, face)?;
        Some(End {
            pos,
            face,
            open: true,
        })
    }

    #[derive(Default)]
    struct TickState {
        owner: Option<ModRevision>,
        line: Option<PressureRoute>,
        source_surfaces: Option<Rc<[BlockId]>>,
        refresh_surface: bool,
        collision: Option<CollisionRecovery>,
        valves: Option<Rc<[(Pos, bool)]>>,
        pressure: [f32; 2],
        phase: u8,
        source_ticks: [u8; 6],
        overlap_targets: BTreeMap<u8, Vec<End>>,
        last_turn: Option<i64>,
    }

    #[derive(Clone, Copy)]
    enum CollisionRecovery {
        Junction {
            resume_at: i64,
        },
        Split {
            broken: Pos,
            resume_at: i64,
            role: SplitRole,
        },
    }

    #[derive(Clone, Copy)]
    enum SplitRole {
        Pipe,
        Pump,
        Unchanged,
    }

    impl CollisionRecovery {
        fn current(self, game: &Game<'_>) -> bool {
            match self {
                Self::Junction { .. } => true,
                Self::Split {
                    broken, resume_at, ..
                } => {
                    game.world.game_time <= resume_at
                        && game.native_block(broken) == "minecraft:cobblestone"
                }
            }
        }
    }

    #[derive(PartialEq, Eq)]
    struct PressureRoute {
        pump: Pos,
        front: Direction,
        sources: Rc<[End]>,
        inlets: u8,
        outlets: u8,
    }

    #[derive(Default)]
    struct Lines {
        tick: Option<i64>,
        by_device: BTreeMap<Pos, Option<(Rc<Line>, usize)>>,
        live: BTreeMap<Pos, TickState>,
        stopped_pumps: BTreeMap<Pos, i64>,
        reset_overlap_inlets: BTreeMap<Pos, i64>,
    }

    thread_local! {
        static NETWORKS: RefCell<SessionCache<Lines>> = RefCell::new(SessionCache::default());
        static POINTERS: RefCell<SessionCache<BTreeMap<Pos, PointerFrame>>> = RefCell::new(SessionCache::default());
        static RIMS: RefCell<SessionCache<RimHistory>> = RefCell::new(SessionCache::default());
    }

    pub(super) fn reset() {
        NETWORKS.with(|networks| networks.borrow_mut().clear());
        POINTERS.with(|pointers| pointers.borrow_mut().clear());
        RIMS.with(|rims| rims.borrow_mut().clear());
    }

    #[derive(Default)]
    struct RimHistory {
        time: Option<i64>,
        active: BTreeMap<Pos, (ModRevision, u8)>,
    }

    type FluidParticle = (Pos, Direction, flow::Fluid, bool, Option<bool>);

    pub(super) fn rim_events(
        game: &Game<'_>,
        session: usize,
        dimension: &str,
        time: i64,
        entries: &[(Pos, &ModBlockEntity)],
    ) -> Vec<FluidParticle> {
        let view = game
            .camera_mob()
            .map(|m| [m.position.x, m.position.y, m.position.z])
            .or_else(|| {
                game.player
                    .as_ref()
                    .map(|p| [p.position.x, p.position.y, p.position.z])
            });
        RIMS.with(|cache| {
            let mut cache = cache.borrow_mut();
            let history = cache.dimension(session, dimension);
            if history.time == Some(time) {
                return Vec::new();
            }
            if history.time.is_some_and(|previous| previous > time) {
                history.active.clear();
            }
            history.time = Some(time);
            history
                .active
                .retain(|pos, _| device_at(game, *pos).is_some());
            let mut events = Vec::new();
            for &(pos, entity) in entries
                .iter()
                .filter(|(_, e)| matches!(e.id.as_str(), PIPE | PUMP | VALVE))
            {
                let mask = state(game, pos).map_or(0, port_mask);
                let owner = entity.revision();
                let previous = history
                    .active
                    .get(&pos)
                    .filter(|(old, _)| old.is_same_create_entity(owner))
                    .map_or(0, |(_, mask)| *mask);
                let visible = view.is_some_and(|view| {
                    (0..3)
                        .map(|i| {
                            let distance = view[i] - (f64::from(pos[i]) + 0.5);
                            distance * distance
                        })
                        .sum::<f64>()
                        <= 20.0 * 20.0
                });
                let mut current = 0;
                for side in Direction::ALL
                    .into_iter()
                    .filter(|&side| mask & bit(side) != 0)
                {
                    if let Some(Some((flow, inbound))) = stored(entity, side) {
                        current |= bit(side);
                        if visible {
                            let adjacent = relative(pos, side, 1);
                            let jet = (open_data(entity, side).is_some()
                                && state(game, adjacent)
                                    .and_then(|block| {
                                        endpoint(game, adjacent, block, side.opposite())
                                    })
                                    .is_some_and(|end| end.open))
                            .then_some(inbound);
                            events.push((pos, side, flow.fluid, previous & bit(side) == 0, jet));
                        }
                    }
                }
                if current == 0 {
                    history.active.remove(&pos);
                } else {
                    history.active.insert(pos, (owner, current));
                }
            }
            events
        })
    }

    fn relative(pos: Pos, direction: Direction, distance: i32) -> Pos {
        let offset = direction.vector();
        std::array::from_fn(|i| pos[i] + offset[i] * distance)
    }

    fn front(state: &BlockState) -> Option<Direction> {
        let name = state.properties.get("facing")?;
        Direction::ALL.into_iter().find(|side| side.name() == name)
    }

    fn pipe_open(state: &BlockState, side: Direction) -> bool {
        state
            .properties
            .get(side.name())
            .is_some_and(|v| v == "true")
    }

    fn connects(state: &BlockState, toward: Direction) -> bool {
        matches!(
            state.name.as_str(),
            PIPE | "minecraft:cauldron" | "minecraft:lava_cauldron" | "minecraft:water_cauldron"
        ) || state.properties.contains_key("honey_level")
            || is_endpoint(&state.name, toward.opposite())
            || device_ports(state).is_some_and(|ports| ports.contains(&toward.opposite()))
    }

    fn enabled(state: &BlockState) -> bool {
        state
            .properties
            .get("enabled")
            .is_some_and(|value| value == "true")
    }

    fn valve_axis(state: &BlockState, shaft: bool) -> Option<create_engine::kinetics::Axis> {
        let first = state.properties.get("axis_along_first")? == "true";
        Some(create_engine::placement::gauge_axis(
            front(state)?,
            first == shaft,
        ))
    }

    fn state<'a>(game: &'a Game<'_>, pos: Pos) -> Option<&'a BlockState> {
        let [x, y, z] = pos;
        if !game.world.loaded(x, z) {
            return None;
        }
        game.pack.assets.registry.state(game.world.block(x, y, z))
    }

    fn port_mask(state: &BlockState) -> u8 {
        let direction = match state.name.as_str() {
            PIPE => {
                return Direction::ALL
                    .into_iter()
                    .filter(|&side| pipe_open(state, side))
                    .fold(0, |mask, side| mask | bit(side));
            }
            PUMP => front(state),
            VALVE => valve_axis(state, false)
                .map(|axis| [Direction::East, Direction::Up, Direction::South][axis.index()]),
            _ => None,
        };
        direction.map_or(0, |side| bit(side) | bit(side.opposite()))
    }

    fn device_ports(state: &BlockState) -> Option<[Direction; 2]> {
        let mask = port_mask(state);
        let mut sides = Direction::ALL
            .into_iter()
            .filter(|&side| mask & bit(side) != 0);
        let pair = [sides.next()?, sides.next()?];
        sides.next().is_none().then_some(pair)
    }

    fn straight_axis(state: &BlockState) -> Option<create_engine::kinetics::Axis> {
        let [first, second] = device_ports(state)?;
        (first.opposite() == second).then_some(first.axis())
    }

    fn pump_at(game: &Game<'_>, pos: Pos, origin: &BlockState, limit: usize) -> Option<Pos> {
        if origin.name == PUMP {
            return Some(pos);
        }
        let mut visited = BTreeSet::from([pos]);
        let mut queue = VecDeque::from([(pos, port_mask(origin), 0)]);
        while let Some((pos, mask, depth)) = queue.pop_front() {
            for side in Direction::ALL
                .into_iter()
                .filter(|&side| mask & bit(side) != 0)
            {
                let at = relative(pos, side, 1);
                let Some(block) = state(game, at) else {
                    continue;
                };
                let ports = port_mask(block);
                if ports & bit(side.opposite()) == 0 || !visited.insert(at) {
                    continue;
                }
                if block.name == PUMP {
                    return Some(at);
                }
                if depth + 1 < limit {
                    queue.push_back((at, ports, depth + 1));
                }
            }
        }
        None
    }

    struct HalfHop {
        hop: Hop,
        toward_pump: Direction,
        parent: usize,
        depth: usize,
        terminal_faces: u8,
        valve: Option<bool>,
    }

    struct Half {
        devices: Vec<HalfHop>,
        ends: Vec<End>,
        link: Option<Pos>,
        opposing: Vec<Pos>,
    }

    impl Half {
        fn valves(&self) -> impl Iterator<Item = (Pos, bool)> + '_ {
            self.devices
                .iter()
                .filter(|device| device.hop.outlets != 0)
                .filter_map(|device| Some((device.hop.pos, device.valve?)))
        }
    }

    /// Pressure fans out from the pump on both sides, including the side
    /// where actual liquid will travel back toward the pump.
    fn scan_half(
        game: &Game<'_>,
        pump: Pos,
        side: Direction,
        pulling: bool,
        limit: usize,
        visited: &mut BTreeSet<Pos>,
    ) -> Option<Half> {
        let mut devices = vec![HalfHop {
            hop: Hop::new(pump, bit(side.opposite()), bit(side), pump),
            toward_pump: side.opposite(),
            parent: 0,
            depth: 0,
            terminal_faces: 0,
            valve: None,
        }];
        let mut targets = Vec::new();
        let mut link = None;
        let mut opposing = Vec::new();
        let mut index = 0;
        while index < devices.len() {
            let HalfHop { hop, depth, .. } = devices[index];
            for side in hop.outlets() {
                let at = relative(hop.pos, side, 1);
                let Some(block) = state(game, at) else {
                    continue;
                };
                let face = side.opposite();
                if let Some(end) = endpoint(game, at, block, face) {
                    targets.push(end);
                    devices[index].terminal_faces |= bit(side);
                    continue;
                }
                let ports = port_mask(block);
                let outlets = ports & !bit(face);
                if block.name == PUMP && ports & bit(face) != 0 {
                    let required = if pulling { face } else { side };
                    if front(block) != Some(required) {
                        // Pumps using the same side of their transfer
                        // behavior do not form a pressure endpoint.
                        opposing.push(at);
                        continue;
                    }
                    if link.replace(at).is_some() {
                        return None;
                    }
                    devices[index].terminal_faces |= bit(side);
                    continue;
                }
                if !matches!(block.name.as_str(), PIPE | VALVE)
                    || ports & bit(face) == 0
                    || outlets == 0
                {
                    continue;
                }
                if visited.contains(&at) {
                    return None;
                }
                if depth == limit {
                    // At the limit pressure reaches this face, but there is
                    // no storage endpoint through which to transfer fluid.
                    devices[index].terminal_faces |= bit(side);
                    continue;
                }
                visited.insert(at);
                devices.push(HalfHop {
                    hop: Hop::new(at, bit(face), outlets, pump),
                    toward_pump: face,
                    parent: index,
                    depth: depth + 1,
                    terminal_faces: 0,
                    valve: (block.name == VALVE).then(|| enabled(block)),
                });
            }
            index += 1;
        }
        // An outlet or inlet between opposing pumps can see both pressure
        // sources. Leave that layout to a combined pressure route.
        if !opposing.is_empty() && !targets.is_empty() {
            return None;
        }
        // A dead branch keeps its physical ports but contributes no pressure.
        let mut face_counts = vec![0; devices.last()?.depth + 1];
        for device in &mut devices {
            device.hop.outlets = device.terminal_faces;
        }
        for i in (1..devices.len()).rev() {
            let HalfHop {
                hop,
                depth,
                toward_pump,
                parent,
                ..
            } = devices[i];
            if hop.outlets != 0 {
                face_counts[depth] += 1 + hop.outlets.count_ones() as usize;
                devices[parent].hop.outlets |= bit(toward_pump.opposite());
            }
        }
        for device in devices.iter_mut().skip(1) {
            device.hop.divisor = flow::pressure_divisor(face_counts[device.depth]);
        }
        Some(Half {
            devices,
            ends: targets,
            link,
            opposing,
        })
    }

    struct PumpSection {
        pos: Pos,
        front: Direction,
        inlet: Half,
        outlet: Half,
    }

    fn section(game: &Game<'_>, pump: Pos, limit: usize) -> Option<PumpSection> {
        let front = front_of_pump(state(game, pump)?)?;
        let mut visited = BTreeSet::from([pump]);
        Some(PumpSection {
            pos: pump,
            front,
            inlet: scan_half(game, pump, front.opposite(), true, limit, &mut visited)?,
            outlet: scan_half(game, pump, front, false, limit, &mut visited)?,
        })
    }

    fn find_line(game: &Game<'_>, pos: Pos, origin: &BlockState) -> Option<Line> {
        // Java always inspects the first neighboring pipe, even at range 1.
        let limit = (crate::game::create_port_server_config::pump_range() - 1).max(1) as usize;
        let nearest = pump_at(game, pos, origin, limit)?;
        let mut current = section(game, nearest, limit)?;
        let mut later = BTreeMap::new();
        while let Some(previous) = current.inlet.link {
            if previous == current.pos || later.contains_key(&previous) {
                return None;
            }
            let earlier = section(game, previous, limit)?;
            if earlier.outlet.link != Some(current.pos) {
                return None;
            }
            later.insert(current.pos, current);
            current = earlier;
        }
        let pump = current.pos;
        let direction = current.front;
        let opposing = current
            .inlet
            .opposing
            .iter()
            .chain(&current.outlet.opposing)
            .copied()
            .collect();
        let mut sources = std::mem::take(&mut current.inlet.ends);
        let mut valves: Vec<_> = current.inlet.valves().collect();
        let mut devices: Vec<_> = std::mem::take(&mut current.inlet.devices)
            .into_iter()
            .skip(1)
            .rev()
            .map(|mut device| {
                std::mem::swap(&mut device.hop.inlets, &mut device.hop.outlets);
                device.hop
            })
            .collect();
        let mut pumps = BTreeSet::new();
        let mut side_tanks = Vec::new();
        let mut ends = loop {
            if !pumps.insert(current.pos) {
                return None;
            }
            devices.push(Hop::new(
                current.pos,
                bit(current.front.opposite()),
                bit(current.front),
                current.pos,
            ));
            valves.extend(current.outlet.valves());
            let Some(next) = current.outlet.link else {
                devices.extend(
                    current
                        .outlet
                        .devices
                        .into_iter()
                        .skip(1)
                        .map(|device| device.hop),
                );
                break current.outlet.ends;
            };
            let following = match later.remove(&next) {
                Some(section) => section,
                None => section(game, next, limit)?,
            };
            let side_ends = &current.outlet.ends;
            if following.inlet.link != Some(current.pos)
                || side_ends.len() != following.inlet.ends.len()
                || side_ends
                    .iter()
                    .any(|end| !following.inlet.ends.contains(end))
            {
                return None;
            }
            if (1..=2).contains(&side_ends.len())
                && side_tanks.is_empty()
                && side_ends.iter().all(|end| {
                    !end.open && state(game, end.pos).is_some_and(|block| block.name == tank::BLOCK)
                })
            {
                side_tanks.extend(side_ends.iter().copied());
                let mut reverse: BTreeMap<_, _> = following
                    .inlet
                    .devices
                    .iter()
                    .skip(1)
                    .filter(|device| device.hop.outlets != 0)
                    .map(|device| (device.hop.pos, device.hop))
                    .collect();
                for mut device in current.outlet.devices.into_iter().skip(1) {
                    if device.hop.outlets != 0 {
                        let other = reverse.remove(&device.hop.pos)?;
                        device.hop.other = Some(PressureContribution {
                            pump: next,
                            inlets: other.outlets,
                            outlets: other.inlets,
                            divisor: other.divisor,
                        });
                    }
                    devices.push(device.hop);
                }
                if !reverse.is_empty() {
                    return None;
                }
                current = following;
                continue;
            }
            if !current.outlet.ends.is_empty() {
                return None;
            }
            // On the path between co-directed pumps, suction and output
            // contribute pressure to the same face polarity. Compare only
            // the pressure-carrying path. A capped arm can be visited in a
            // different order from either pump and carries no pressure.
            let mut reverse = following
                .inlet
                .devices
                .iter()
                .skip(1)
                .filter(|device| device.hop.outlets != 0)
                .rev();
            for mut device in current.outlet.devices.into_iter().skip(1) {
                if device.hop.outlets == 0 {
                    devices.push(device.hop);
                    continue;
                }
                let other = reverse.next()?.hop;
                if device.hop.pos != other.pos
                    || device.hop.inlets != other.outlets
                    || device.hop.outlets != other.inlets
                    || device.hop.outlets.count_ones() != 1
                {
                    return None;
                }
                device.hop.other = Some(PressureContribution {
                    pump: next,
                    inlets: other.outlets,
                    outlets: other.inlets,
                    divisor: other.divisor,
                });
                devices.push(device.hop);
            }
            if reverse.next().is_some() {
                return None;
            }
            current = following;
        };
        let overlap = !side_tanks.is_empty();
        if overlap {
            // Both pumps can contribute pressure at the side tanks. These
            // ends can act as inlets or outlets according to the flow.
            if pumps.len() != 2
                || sources.len() != 1
                || ends.len() != 1
                || sources[0].open
                || ends[0].open
                || !valves.is_empty()
            {
                return None;
            }
            sources.extend(side_tanks.iter().copied());
            ends.extend(side_tanks);
        }
        let open_sources: Box<[End]> = sources.iter().filter(|end| end.open).copied().collect();
        let mut outlet_surfaces = BTreeSet::new();
        if ends
            .iter()
            .filter(|end| end.open)
            .any(|end| !outlet_surfaces.insert(end.pos))
            || open_sources
                .iter()
                .any(|end| outlet_surfaces.contains(&end.pos))
        {
            return None;
        }
        let by_pos: BTreeMap<_, _> = devices
            .iter()
            .enumerate()
            .map(|(i, hop)| (hop.pos, i))
            .collect();
        if by_pos.len() != devices.len() {
            return None;
        }
        let targets = ends
            .into_iter()
            .map(|end| {
                Some(Target {
                    device: *by_pos.get(&end.anchor())?,
                    end,
                })
            })
            .collect::<Option<Vec<_>>>()?;
        let source_faces = sources
            .iter()
            .map(|end| ((end.anchor(), end.port() as u8), *end))
            .collect();
        let source_surfaces = RefCell::new(source_surfaces(game, &open_sources));
        Some(Line {
            pump,
            front: direction,
            open_sources,
            source_surfaces,
            sources: sources.into(),
            source_faces,
            targets,
            devices,
            by_pos,
            pump_count: pumps.len(),
            opposing,
            overlap,
            valves: valves.into(),
        })
    }

    fn line(game: &Game<'_>, pos: Pos, origin: &BlockState) -> Option<(Rc<Line>, usize)> {
        NETWORKS.with(|cache| {
            let mut cache = cache.borrow_mut();
            let index = cache.dimension(std::ptr::from_ref(&game.world) as usize, game.dim.id());
            let now = game.world.game_time;
            if index.tick != Some(now) {
                index.by_device.clear();
                index.tick = Some(now);
                index.stopped_pumps.retain(|_, tick| *tick >= now);
                index.reset_overlap_inlets.retain(|_, tick| *tick >= now);
                if now % 20 == 0 {
                    index.live.retain(|p, _| {
                        state(game, *p)
                            .is_some_and(|s| matches!(s.name.as_str(), PIPE | PUMP | VALVE))
                    });
                }
            }
            if let Some(line) = index.by_device.get(&pos) {
                return line.clone();
            }
            let found = find_line(game, pos, origin).map(Rc::new);
            if let Some(line) = &found {
                for (i, device) in line.devices.iter().enumerate() {
                    index.by_device.insert(
                        device.pos,
                        (device.inlets != 0 && device.outlets != 0).then(|| (line.clone(), i)),
                    );
                }
            } else {
                index.by_device.insert(pos, None);
            }
            index.by_device.get(&pos).cloned().flatten()
        })
    }

    fn open_data(entity: &ModBlockEntity, side: Direction) -> Option<&Tag> {
        entity.nbt.get(&side.name().into())?.get("OpenEnd")
    }

    fn save_open(entity: &mut ModBlockEntity, side: Direction, tag: Tag) -> bool {
        let connection = entity
            .nbt
            .entry(side.name().into())
            .or_insert_with(|| Tag::Compound(Compound::new()));
        let Tag::Compound(fields) = connection else {
            return false;
        };
        let key = "OpenEnd".into();
        if fields.get(&key) == Some(&tag) {
            return false;
        }
        fields.insert(key, tag);
        true
    }

    fn maintain_open(
        pos: Pos,
        entity: &mut ModBlockEntity,
        line: &Line,
        phase: u8,
        active: bool,
    ) -> bool {
        if !active || phase == 2 {
            return false;
        }
        let mut changed = false;
        for (end, pulling) in line
            .open_sources
            .iter()
            .copied()
            .map(|end| (end, phase == 0))
            .chain(line.targets.iter().map(|target| (target.end, false)))
            .filter(|(end, _)| end.open && end.anchor() == pos)
        {
            let side = end.port();
            let Some(mut buffer) = open::Buffer::read(open_data(entity, side), side) else {
                continue;
            };
            buffer.pulling |= pulling;
            if let Some(tag) = buffer.write(pos, side) {
                changed |= save_open(entity, side, tag);
            }
        }
        changed
    }

    fn stored(entity: &ModBlockEntity, side: Direction) -> Option<Option<(flow::Flow, bool)>> {
        let Some(tag) = entity.nbt.get(&side.name().into()) else {
            return Some(None);
        };
        let Tag::Compound(connection) = tag else {
            return None;
        };
        if connection.keys().any(|key| {
            !matches!(
                key.to_string_lossy().as_str(),
                "Pressure" | "Flow" | "OpenEnd"
            )
        }) {
            return None;
        }
        if let Some(pressure) = connection.get(&"Pressure".into()) {
            let Tag::List(values) = pressure else {
                return None;
            };
            let [Tag::Float(inward), Tag::Float(outward)] = values.as_slice() else {
                return None;
            };
            let inward = f32::from_bits(*inward);
            let outward = f32::from_bits(*outward);
            if !inward.is_finite() || !outward.is_finite() || inward < 0.0 || outward < 0.0 {
                return None;
            }
        }
        let Some(tag) = connection.get(&"Flow".into()) else {
            return Some(None);
        };
        let Tag::Compound(data) = tag else {
            return None;
        };
        if data
            .keys()
            .any(|key| !matches!(key.to_string_lossy().as_str(), "Fluid" | "In" | "Progress"))
        {
            return None;
        }
        let Tag::Compound(fluid) = data.get(&"Fluid".into())? else {
            return None;
        };
        if fluid.len() != 2 || !matches!(fluid.get(&"amount".into()), Some(Tag::Int(1))) {
            return None;
        }
        let Tag::String(id) = fluid.get(&"id".into())? else {
            return None;
        };
        let Tag::Byte(inbound @ (0 | 1)) = data.get(&"In".into())? else {
            return None;
        };
        let progress = match data.get(&"Progress".into()) {
            None => 1.0,
            Some(Tag::Compound(fields))
                if fields.keys().all(|key| {
                    matches!(
                        key.to_string_lossy().as_str(),
                        "Value" | "Target" | "Speed" | "Force"
                    )
                }) =>
            {
                if !matches!(fields.get(&"Target".into()), Some(Tag::Float(0)))
                    || !matches!(fields.get(&"Speed".into()), Some(Tag::Float(0)))
                {
                    return None;
                }
                if fields
                    .get(&"Force".into())
                    .is_some_and(|tag| !matches!(tag, Tag::Byte(1)))
                {
                    return None;
                }
                let Tag::Float(value) = fields.get(&"Value".into())? else {
                    return None;
                };
                let value = f32::from_bits(*value);
                if !(0.0..1.0).contains(&value) {
                    return None;
                }
                value
            }
            _ => return None,
        };
        Some(Some((
            flow::Flow {
                fluid: flow::Fluid::from_id(&id.to_string_lossy())?,
                progress,
            },
            *inbound != 0,
        )))
    }

    type FaceFlows = [Option<flow::Flow>; 6];

    fn internal_fluid(
        hop: Hop,
        before: FaceFlows,
    ) -> Result<Option<flow::Fluid>, (flow::Fluid, flow::Fluid)> {
        let mut complete = hop
            .inlets()
            .filter_map(|side| before[side as usize].and_then(flow::Flow::complete));
        let first = complete.next();
        if let Some(first) = first
            && let Some(other) = complete.find(|&fluid| fluid != first)
        {
            return Err((first, other));
        }
        Ok(first)
    }

    fn face(entity: &ModBlockEntity, side: Direction, inbound: bool) -> Option<Option<flow::Flow>> {
        Some(stored(entity, side)?.and_then(|(flow, old_inbound)| {
            (old_inbound == inbound || flow.complete().is_some()).then_some(flow)
        }))
    }

    fn faces(entity: &ModBlockEntity, hop: Hop) -> Option<FaceFlows> {
        let mut flows = [None; 6];
        for side in hop.inlets() {
            flows[side as usize] = face(entity, side, true)?;
        }
        for side in hop.outlets() {
            flows[side as usize] = face(entity, side, false)?;
        }
        Some(flows)
    }

    fn tag_number(n: f32) -> Tag {
        Tag::Float(n.to_bits())
    }

    #[derive(Clone, Copy, Default, PartialEq)]
    struct Pointer {
        value: f32,
        target: f32,
        speed: f32,
    }

    struct PointerFrame {
        owner: ModRevision,
        time: i64,
        previous: f32,
        value: f32,
    }

    pub(super) fn client_tick(
        session: usize,
        dimension: &str,
        time: i64,
        entries: &[(Pos, &ModBlockEntity)],
    ) {
        POINTERS.with(|cache| {
            let mut cache = cache.borrow_mut();
            let pointers = cache.dimension(session, dimension);
            let mut live = std::collections::BTreeSet::new();
            for &(pos, entity) in entries.iter().filter(|(_, e)| e.id == VALVE) {
                let Some(pointer) = Pointer::read(&entity.nbt) else {
                    continue;
                };
                live.insert(pos);
                let owner = entity.revision();
                let frame = pointers.entry(pos).or_insert(PointerFrame {
                    owner,
                    time,
                    previous: pointer.value,
                    value: pointer.value,
                });
                if frame.time != time || !frame.owner.is_same_create_entity(owner) {
                    let continuous =
                        frame.time + 1 == time && frame.owner.is_same_create_entity(owner);
                    *frame = PointerFrame {
                        owner,
                        time,
                        previous: if continuous {
                            frame.value
                        } else {
                            pointer.value
                        },
                        value: pointer.value,
                    };
                } else {
                    frame.value = pointer.value;
                }
            }
            pointers.retain(|pos, _| live.contains(pos));
        });
    }

    fn pointer_angle(game: &Game<'_>, pos: Pos, entity: &ModBlockEntity, partial: f32) -> f32 {
        let value = Pointer::read(&entity.nbt).unwrap_or_default().value;
        POINTERS.with(|cache| {
            let mut cache = cache.borrow_mut();
            let pointers = cache.dimension(std::ptr::from_ref(&game.world) as usize, game.dim.id());
            let value = pointers
                .get(&pos)
                .filter(|frame| frame.owner.is_same_create_entity(entity.revision()))
                .map_or(value, |frame| {
                    frame.previous + (frame.value - frame.previous) * partial
                });
            value * -90.0
        })
    }

    impl Pointer {
        fn read(nbt: &Compound) -> Option<Self> {
            let Some(tag) = nbt.get(&"Pointer".into()) else {
                return Some(Self::default());
            };
            let Tag::Compound(fields) = tag else {
                return None;
            };
            let number = |key: &str| match fields.get(&key.into()) {
                Some(Tag::Float(bits)) => Some(f32::from_bits(*bits)),
                _ => None,
            };
            let value = number("Value")?;
            let target = number("Target")?;
            let speed = number("Speed")?;
            ((0.0..=1.0).contains(&value)
                && matches!(target, 0.0 | 1.0)
                && (0.0..=1.0).contains(&speed))
            .then_some(Self {
                value,
                target,
                speed,
            })
        }

        fn set_speed(&mut self, rpm: f32) {
            self.target = if rpm > 0.0 { 1.0 } else { 0.0 };
            self.speed = (rpm.abs() / 16.0 / 20.0).clamp(0.0, 1.0);
        }

        fn tick(&mut self) {
            if self.value < self.target {
                self.value = (self.value + self.speed).min(self.target);
            } else if self.value > self.target {
                self.value = (self.value - self.speed).max(self.target);
            }
        }

        fn save(self, nbt: &mut Compound) {
            if nbt.get(&"Pointer".into()).is_none() {
                nbt.insert("Pointer".into(), Tag::Compound(Compound::new()));
            }
            if let Some(Tag::Compound(fields)) = nbt.get_mut(&"Pointer".into()) {
                fields.insert("Value".into(), tag_number(self.value));
                fields.insert("Target".into(), tag_number(self.target));
                fields.insert("Speed".into(), tag_number(self.speed));
            }
        }
    }

    pub(in crate::game) fn valve_nbt() -> Compound {
        let mut nbt = Compound::new();
        Pointer::default().save(&mut nbt);
        nbt
    }

    pub(in crate::game) fn valve_speed_changed(entity: &mut ModBlockEntity, rpm: f32) {
        if let Some(mut pointer) = Pointer::read(&entity.nbt) {
            pointer.set_speed(rpm);
            pointer.save(&mut entity.nbt);
        }
    }

    pub(in crate::game) fn tick_valve(
        game: &mut Game<'_>,
        pos: Pos,
        entity: &mut ModBlockEntity,
        rpm: f32,
    ) -> bool {
        let mut changed = tick(game, pos, entity, rpm);
        let Some(mut pointer) = Pointer::read(&entity.nbt) else {
            return changed;
        };
        let previous = pointer;
        pointer.tick();
        if pointer != previous || entity.nbt.get(&"Pointer".into()).is_none() {
            pointer.save(&mut entity.nbt);
            changed = true;
        }
        let value = match pointer.value {
            0.0 => Some("false"),
            1.0 => Some("true"),
            _ => None,
        };
        if let Some(value) = value {
            changed |= game.native_set_block_property(pos, "enabled", value);
        }
        if trace_enabled() {
            log::info!(
                "Create fluid valve: {}",
                serde_json::json!({
                    "time": game.world.game_time, "pos": pos, "rpm": rpm,
                    "enabled": state(game, pos).is_some_and(enabled),
                    "pointer": [pointer.value, pointer.target, pointer.speed],
                })
            );
        }
        changed
    }

    fn save_face(
        entity: &mut ModBlockEntity,
        side: Direction,
        pressure: flow::Pressure,
        fluid: Option<flow::DirectedFlow>,
        force: bool,
    ) -> bool {
        let mut connection = Compound::new();
        if let Some(open) = open_data(entity, side) {
            connection.insert("OpenEnd".into(), open.clone());
        }
        if pressure != flow::Pressure::default() {
            let values = [pressure.inbound, pressure.outward];
            connection.insert("Pressure".into(), Tag::List(values.map(tag_number).into()));
        }
        if let Some(flow::DirectedFlow { flow, inbound }) = fluid {
            let mut data = Compound::from([
                (
                    "Fluid".into(),
                    Tag::Compound(Compound::from([
                        ("id".into(), Tag::String(flow.fluid.id().into())),
                        ("amount".into(), Tag::Int(1)),
                    ])),
                ),
                ("In".into(), Tag::Byte(i8::from(inbound))),
            ]);
            if flow.progress != 1.0 {
                let mut progress = Compound::from([
                    ("Value".into(), tag_number(flow.progress)),
                    ("Target".into(), tag_number(0.0)),
                    ("Speed".into(), tag_number(0.0)),
                ]);
                if force {
                    progress.insert("Force".into(), Tag::Byte(1));
                }
                data.insert("Progress".into(), Tag::Compound(progress));
            }
            connection.insert("Flow".into(), Tag::Compound(data));
        }
        let value = Tag::Compound(connection);
        let key = side.name().into();
        if entity.nbt.get(&key) == Some(&value) {
            return false;
        }
        entity.nbt.insert(key, value);
        true
    }

    fn save(
        entity: &mut ModBlockEntity,
        hop: Hop,
        pressure: f32,
        before: FaceFlows,
        after: FaceFlows,
    ) -> bool {
        let mut changed = false;
        for side in Direction::ALL {
            let inbound = hop.inlets & bit(side) != 0;
            if inbound || hop.outlets & bit(side) != 0 {
                changed |= save_face(
                    entity,
                    side,
                    if inbound {
                        flow::Pressure {
                            inbound: pressure,
                            outward: 0.0,
                        }
                    } else {
                        flow::Pressure {
                            inbound: 0.0,
                            outward: pressure,
                        }
                    },
                    after[side as usize].map(|flow| flow::DirectedFlow { flow, inbound }),
                    before[side as usize].is_none(),
                );
            } else if stored(entity, side).is_some() {
                if open_data(entity, side).is_some() {
                    changed |= save_face(entity, side, flow::Pressure::default(), None, false);
                } else {
                    changed |= entity.nbt.remove(&side.name().into()).is_some();
                }
            }
        }
        changed
    }

    fn device_at<'a>(game: &'a Game<'_>, [x, y, z]: Pos) -> Option<&'a ModBlockEntity> {
        let BlockEntity::Mod(entity) = game.world.block_entities.get(&(x, y, z))? else {
            return None;
        };
        matches!(entity.id.as_str(), PIPE | PUMP | VALVE).then_some(entity.as_ref())
    }

    fn clear_connections(entity: &mut ModBlockEntity, clear_flow: bool) -> bool {
        let mut changed = false;
        for side in Direction::ALL {
            if stored(entity, side).is_none() {
                continue;
            }
            if let Some(Tag::Compound(connection)) = entity.nbt.get_mut(&side.name().into()) {
                changed |= connection.remove(&"Pressure".into()).is_some();
                if clear_flow {
                    changed |= connection.remove(&"Flow".into()).is_some();
                }
            }
        }
        changed
    }

    fn wipe_pressure(game: &mut Game<'_>, pos: Pos) {
        if game
            .native_with_mod_block_entity(pos, |entity| clear_connections(entity, false))
            .unwrap_or(false)
        {
            game.native_block_entity_sync(pos);
        }
    }

    /// A kinetic publication wipes pressure through each adjacent pipe up to
    /// the next pump. An immediately adjacent pump is also a starting node,
    /// so its other side is part of this rebuild.
    pub(in crate::game) fn drive_changed(game: &mut Game<'_>, pos: Pos, rpm: f32) {
        let Some((line, index)) = state(game, pos).and_then(|block| line(game, pos, block)) else {
            return;
        };
        if line.pump_count < 2 {
            // Even a pressureless connection reaches the other pump on a
            // speed change. That pump rebuilds its own faces, while its
            // exterior pipes retain their pressure and flow.
            for &peer in &line.opposing {
                let Some(owner) = device_at(game, peer)
                    .filter(|entity| entity.id == PUMP)
                    .map(ModBlockEntity::revision)
                else {
                    continue;
                };
                NETWORKS.with(|cache| {
                    let mut cache = cache.borrow_mut();
                    let state =
                        cache.dimension(std::ptr::from_ref(&game.world) as usize, game.dim.id());
                    if let Some(entry) = state.live.get_mut(&peer)
                        && entry
                            .owner
                            .is_some_and(|old| old.is_same_create_entity(owner))
                    {
                        entry.phase = PRESSURE_REBUILD_TICKS;
                        entry.source_ticks = [0; 6];
                    }
                });
                wipe_pressure(game, peer);
            }
            return;
        }
        let now = game.world.game_time;
        let mut wiped = BTreeSet::from([pos]);
        let mut redistribute = BTreeSet::new();
        if line.overlap {
            redistribute.insert(pos);
        }
        let mut pending: VecDeque<_> = Direction::ALL
            .into_iter()
            .filter(|&side| line.devices[index].ports & bit(side) != 0)
            .map(|side| (relative(pos, side, 1), side.opposite(), true))
            .collect();
        while let Some((at, entered, start)) = pending.pop_front() {
            let Some(&index) = line.by_pos.get(&at) else {
                continue;
            };
            if !wiped.insert(at) {
                continue;
            }
            let hop = line.devices[index];
            if line.overlap && at == hop.pump && hop.outlets & bit(entered) != 0 {
                redistribute.insert(at);
            }
            if start || hop.pos != hop.pump {
                pending.extend(
                    Direction::ALL
                        .into_iter()
                        .filter(|&side| hop.ports & bit(side) != 0)
                        .map(|side| (relative(at, side, 1), side.opposite(), false)),
                );
            }
        }
        NETWORKS.with(|cache| {
            let mut cache = cache.borrow_mut();
            let state = cache.dimension(std::ptr::from_ref(&game.world) as usize, game.dim.id());
            if rpm == 0.0 {
                let turned = state
                    .live
                    .get(&pos)
                    .is_some_and(|entry| entry.last_turn == Some(now));
                state
                    .stopped_pumps
                    .insert(pos, if turned { now + 1 } else { now });
            } else {
                state.stopped_pumps.remove(&pos);
            }
            if line.overlap {
                state
                    .reset_overlap_inlets
                    .extend(redistribute.into_iter().map(|pos| (pos, now + 1)));
            }
            for at in &wiped {
                if let Some(entry) = state.live.get_mut(at) {
                    entry.phase = PRESSURE_REBUILD_TICKS;
                    entry.source_ticks = [0; 6];
                    entry.overlap_targets.clear();
                }
            }
        });
        for at in wiped {
            wipe_pressure(game, at);
        }
    }

    fn ready_targets(
        game: &Game<'_>,
        line: &Line,
        source_device: usize,
        source_side: Direction,
        start: FaceFlows,
        kind: flow::Fluid,
    ) -> Vec<End> {
        let mut reachable = vec![0; line.devices.len()];
        for (i, &hop) in line.devices.iter().enumerate().skip(source_device) {
            let supplied = |side| {
                if i == source_device {
                    return side == source_side;
                }
                line.by_pos
                    .get(&relative(hop.pos, side, 1))
                    .is_some_and(|&parent| reachable[parent] & bit(side.opposite()) != 0)
            };
            if !hop.inlets().any(supplied) {
                continue;
            }
            let valid = state(game, hop.pos).is_some_and(|block| {
                if hop.pos == hop.pump {
                    front_of_pump(block).is_some_and(|front| hop.outlets & bit(front) != 0)
                        && (line.pump_count == 1
                            || i == source_device
                            || pump_supplies(game, hop.pos))
                } else {
                    (block.name == PIPE || (block.name == VALVE && enabled(block)))
                        && hop.matches(block)
                }
            });
            let flows = if i == source_device {
                Some(start)
            } else {
                device_at(game, hop.pos).and_then(|entity| faces(entity, hop))
            };
            if valid
                && let Some(flows) = flows
                && internal_fluid(hop, flows) == Ok(Some(kind))
                && hop.inlets().any(|side| {
                    supplied(side)
                        && flows[side as usize].and_then(flow::Flow::complete) == Some(kind)
                })
            {
                reachable[i] = hop
                    .outlets()
                    .filter(|&side| {
                        flows[side as usize].and_then(flow::Flow::complete) == Some(kind)
                    })
                    .fold(0, |mask, side| mask | bit(side));
            }
        }
        line.targets
            .iter()
            .filter_map(|target| {
                (reachable[target.device] & bit(target.end.face.opposite()) != 0)
                    .then_some(target.end)
            })
            .collect()
    }

    fn open_source_rebuilds(game: &Game<'_>, end: End) -> bool {
        // Create's neighbor-change validation only propagates pressure
        // from a straight pipe. Bends and junctions skip this rebuild.
        state(game, end.anchor()).and_then(straight_axis).is_some()
    }

    fn source_surfaces(game: &Game<'_>, sources: &[End]) -> Option<Rc<[BlockId]>> {
        if sources.is_empty() {
            return None;
        }
        let surfaces: Rc<[_]> = sources
            .iter()
            .filter(|&&end| open_source_rebuilds(game, end))
            .map(|end| {
                let [x, y, z] = end.pos;
                game.res.behaviours().block(game.world.block(x, y, z))
            })
            .collect();
        (!surfaces.is_empty()).then_some(surfaces)
    }

    fn controls(
        game: &Game<'_>,
        pos: Pos,
        owner: ModRevision,
        route: Option<(&Line, Hop)>,
        pressure: [f32; 2],
        source_flow: u8,
    ) -> (u8, u8) {
        let valves = route.map(|(line, _)| line.valves.clone());
        let source_surfaces = route.and_then(|(line, _)| line.source_surfaces.borrow().clone());
        let line = route.map(|(line, hop)| PressureRoute {
            pump: line.pump,
            front: line.front,
            sources: line.sources.clone(),
            inlets: hop.inlets,
            outlets: hop.outlets,
        });
        NETWORKS.with(|cache| {
            let mut cache = cache.borrow_mut();
            let state = cache
                .dimension(std::ptr::from_ref(&game.world) as usize, game.dim.id())
                .live
                .entry(pos)
                .or_default();
            let same_owner = state
                .owner
                .is_some_and(|old| old.is_same_create_entity(owner));
            let rebuilt = state.collision.take().is_some_and(|recovery| {
                if !same_owner || !recovery.current(game) {
                    return false;
                }
                if matches!(
                    recovery,
                    CollisionRecovery::Split {
                        role: SplitRole::Unchanged,
                        ..
                    }
                ) {
                    // Only the line ownership changed outside the split.
                    // A new drive or connection still starts a rebuild.
                    return state.pressure == pressure
                        && state.valves == valves
                        && state
                            .line
                            .as_ref()
                            .zip(line.as_ref())
                            .is_some_and(|(old, new)| {
                                old.front == new.front
                                    && old.inlets == new.inlets
                                    && old.outlets == new.outlets
                            });
                }
                true
            });
            if !same_owner
                || state.line != line
                || state.valves != valves
                || state.pressure != pressure
            {
                *state = TickState {
                    owner: Some(owner),
                    line,
                    source_surfaces,
                    refresh_surface: false,
                    collision: None,
                    valves,
                    pressure,
                    phase: if rebuilt { 0 } else { PRESSURE_REBUILD_TICKS },
                    source_ticks: [0; 6],
                    overlap_targets: BTreeMap::new(),
                    last_turn: Some(game.world.game_time),
                };
            } else {
                // Scheduled fluid changes complete their current transfer.
                // The neighbor update rebuilds pressure on the next tick.
                if state.refresh_surface {
                    state.phase = PRESSURE_REBUILD_TICKS;
                    state.source_ticks = [0; 6];
                }
                state.refresh_surface = state.source_surfaces != source_surfaces;
                state.source_surfaces = source_surfaces;
                state.last_turn = Some(game.world.game_time);
            }
            if state.phase != 0 {
                let phase = state.phase;
                state.phase -= 1;
                return (phase, 0);
            }
            state
                .overlap_targets
                .retain(|&side, _| source_flow & (1 << side) != 0);
            let mut ready = 0;
            for side in Direction::ALL {
                let ticks = &mut state.source_ticks[side as usize];
                *ticks = if source_flow & bit(side) != 0 {
                    (*ticks + 1).min(3)
                } else {
                    0
                };
                if *ticks == 3 {
                    ready |= bit(side);
                }
            }
            (0, ready)
        })
    }

    fn hold_after_collision(game: &mut Game<'_>, line: &Line, collision: Pos) {
        let resume_at = game.world.game_time + 1 + i64::from(PRESSURE_REBUILD_TICKS);
        // Pipe removal clears pressure on this side of the pump immediately.
        // The two rebuild phases retain existing fluid animation progress.
        for &hop in &line.devices {
            if hop.pos != collision
                && let Some(entity) = device_at(game, hop.pos)
            {
                let owner = entity.revision();
                NETWORKS.with(|cache| {
                    let mut cache = cache.borrow_mut();
                    let live = &mut cache
                        .dimension(std::ptr::from_ref(&game.world) as usize, game.dim.id())
                        .live;
                    let state = live.entry(hop.pos).or_default();
                    if state
                        .owner
                        .is_some_and(|old| old.is_same_create_entity(owner))
                    {
                        state.collision = Some(CollisionRecovery::Junction { resume_at });
                    }
                });
                if hop.pos != line.pump
                    && game
                        .native_with_mod_block_entity(hop.pos, |entity| {
                            clear_connections(entity, false)
                        })
                        .unwrap_or(false)
                {
                    game.native_block_entity_sync(hop.pos);
                }
            }
            if hop.pos == line.pump {
                break;
            }
        }
    }

    fn hold_after_overlap_collision(game: &mut Game<'_>, line: &Line, collision: Pos) {
        // Removing the pipe propagates to both pumps without crossing them.
        // The neighbor update repeats the pressure rebuild on the next tick.
        let resume_at = game.world.game_time + 1 + i64::from(PRESSURE_REBUILD_TICKS);
        NETWORKS.with(|cache| {
            let mut cache = cache.borrow_mut();
            let state = cache.dimension(std::ptr::from_ref(&game.world) as usize, game.dim.id());
            state.live.remove(&collision);
            for hop in &line.devices {
                state.by_device.remove(&hop.pos);
                if let Some(entry) = state.live.get_mut(&hop.pos) {
                    let role = if hop.pos == hop.pump {
                        SplitRole::Pump
                    } else if hop.other.is_some() {
                        SplitRole::Pipe
                    } else {
                        // The pump stopped the wipe. Rebind this outer
                        // section to its new line without restarting flow.
                        SplitRole::Unchanged
                    };
                    entry.collision = Some(CollisionRecovery::Split {
                        broken: collision,
                        resume_at,
                        role,
                    });
                    entry.overlap_targets.clear();
                }
            }
        });
        for hop in line
            .devices
            .iter()
            .filter(|hop| hop.pos != collision && (hop.pos == hop.pump || hop.other.is_some()))
        {
            wipe_pressure(game, hop.pos);
        }
    }

    fn republish_split_pressure(game: &mut Game<'_>, pos: Pos, rpm: f32) {
        let Some((line, _)) = state(game, pos).and_then(|origin| line(game, pos, origin)) else {
            return;
        };
        for &hop in line
            .devices
            .iter()
            .filter(|hop| hop.pos != pos && hop.pump == pos && hop.inlets != 0 && hop.outlets != 0)
        {
            let Some(entity) = device_at(game, hop.pos) else {
                continue;
            };
            if !matches!(
                collision_recovery(game, hop.pos, entity),
                Some(CollisionRecovery::Split {
                    role: SplitRole::Pipe,
                    ..
                })
            ) {
                continue;
            }
            let magnitude = rpm.abs() / hop.divisor as f32;
            if game
                .native_with_mod_block_entity(hop.pos, |entity| {
                    let mut changed = false;
                    for side in hop.inlets().chain(hop.outlets()) {
                        let Some(saved) = stored(entity, side) else {
                            continue;
                        };
                        let pressure = if hop.inlets & bit(side) != 0 {
                            flow::Pressure {
                                inbound: magnitude,
                                outward: 0.0,
                            }
                        } else {
                            flow::Pressure {
                                inbound: 0.0,
                                outward: magnitude,
                            }
                        };
                        let saved =
                            saved.map(|(flow, inbound)| flow::DirectedFlow { flow, inbound });
                        changed |= save_face(entity, side, pressure, saved, false);
                    }
                    changed
                })
                .unwrap_or(false)
            {
                game.native_block_entity_sync(hop.pos);
            }
        }
    }

    fn collision_recovery(
        game: &Game<'_>,
        pos: Pos,
        entity: &ModBlockEntity,
    ) -> Option<CollisionRecovery> {
        NETWORKS.with(|cache| {
            cache
                .borrow_mut()
                .dimension(std::ptr::from_ref(&game.world) as usize, game.dim.id())
                .live
                .get(&pos)
                .filter(|state| {
                    state
                        .owner
                        .is_some_and(|owner| owner.is_same_create_entity(entity.revision()))
                })
                .and_then(|state| state.collision)
                .filter(|recovery| recovery.current(game))
        })
    }

    fn react_to_flow_collision(
        game: &mut Game<'_>,
        line: &Line,
        pos: Pos,
        entity: &ModBlockEntity,
        first: flow::Fluid,
        other: flow::Fluid,
    ) {
        if entity.id != PIPE || !first.has_world_state() || !other.has_world_state() {
            return;
        }
        let Some(cobble) = game.native_default_state("minecraft:cobblestone") else {
            return;
        };
        if game
            .native_machine_destroy_block(pos, None, false)
            .is_none()
            || game.native_block(pos) == PIPE
        {
            return;
        }
        let _ = game.native_set_block(
            game.dim.id(),
            pos,
            cobble,
            horizon_world::level::flags::UPDATE_ALL,
        );
        if line.overlap {
            hold_after_overlap_collision(game, line, pos);
        } else {
            hold_after_collision(game, line, pos);
        }
    }

    fn pump_speed(game: &Game<'_>, pump: Pos, pos: Pos, rpm: f32) -> f32 {
        if pump == pos {
            return rpm.abs();
        }
        saved_pump_speed(game, pump)
    }

    fn saved_pump_speed(game: &Game<'_>, pump: Pos) -> f32 {
        device_at(game, pump)
            .filter(|entity| entity.id == PUMP)
            .map_or(0.0, |entity| {
                crate::game::create_port::running_speed(game, &entity.nbt).abs()
            })
    }

    fn pump_supplies(game: &Game<'_>, pos: Pos) -> bool {
        saved_pump_speed(game, pos) != 0.0
            || NETWORKS.with(|cache| {
                let mut cache = cache.borrow_mut();
                let state =
                    cache.dimension(std::ptr::from_ref(&game.world) as usize, game.dim.id());
                // A source outside the wiped region can still use its old
                // destinations until that pressure rebuild reaches it.
                state.stopped_pumps.get(&pos) == Some(&game.world.game_time)
            })
    }

    type DirectedFaces = [Option<flow::DirectedFlow>; 6];

    fn directed_faces(entity: &ModBlockEntity, hop: Hop) -> Option<DirectedFaces> {
        let mut faces = [None; 6];
        for side in Direction::ALL
            .into_iter()
            .filter(|&side| hop.ports & bit(side) != 0)
        {
            faces[side as usize] =
                stored(entity, side)?.map(|(flow, inbound)| flow::DirectedFlow { flow, inbound });
        }
        Some(faces)
    }

    fn complete_face(face: Option<flow::DirectedFlow>, inbound: bool) -> Option<flow::Fluid> {
        face.filter(|face| face.inbound == inbound)?.flow.complete()
    }

    fn overlap_targets(
        game: &Game<'_>,
        line: &Line,
        source: usize,
        port: Direction,
        start: DirectedFaces,
        kind: flow::Fluid,
    ) -> Vec<End> {
        let mut pending = VecDeque::from([(source, port, start)]);
        let mut visited = BTreeSet::from([source]);
        let mut targets = Vec::new();
        while let Some((index, inlet, faces)) = pending.pop_front() {
            if complete_face(faces[inlet as usize], true) != Some(kind) {
                continue;
            }
            let hop = line.devices[index];
            for side in Direction::ALL
                .into_iter()
                .filter(|&side| complete_face(faces[side as usize], false) == Some(kind))
            {
                if let Some(target) = line
                    .targets
                    .iter()
                    .find(|target| target.device == index && target.end.port() == side)
                {
                    targets.push(target.end);
                    continue;
                }
                let next = relative(hop.pos, side, 1);
                let Some(&neighbor) = line.by_pos.get(&next) else {
                    continue;
                };
                let device = line.devices[neighbor];
                if (next != device.pump || pump_supplies(game, next))
                    && visited.insert(neighbor)
                    && let Some(faces) =
                        device_at(game, next).and_then(|entity| directed_faces(entity, device))
                {
                    pending.push_back((neighbor, side.opposite(), faces));
                }
            }
        }
        targets
    }

    fn retain_overlap_targets(
        game: &Game<'_>,
        pos: Pos,
        side: Direction,
        found: Vec<End>,
    ) -> Vec<End> {
        NETWORKS.with(|cache| {
            let mut cache = cache.borrow_mut();
            let dimension =
                cache.dimension(std::ptr::from_ref(&game.world) as usize, game.dim.id());
            let targets = dimension
                .live
                .entry(pos)
                .or_default()
                .overlap_targets
                .entry(side as u8)
                .or_default();
            for end in found {
                if !targets.contains(&end) {
                    targets.push(end);
                }
            }
            targets.clone()
        })
    }

    /// Follow inbound flows back to the FluidNetwork that owns each source.
    /// A direction change can leave an already discovered destination in the
    /// network when this search cannot reach the source.
    fn reset_overlap_sources(
        game: &Game<'_>,
        line: &Line,
        index: usize,
        side: Direction,
        start: DirectedFaces,
    ) {
        let mut pending = VecDeque::from([(index, bit(side), start)]);
        let mut visited = BTreeSet::from([index]);
        let mut sources = Vec::new();
        while let Some((device, mask, faces)) = pending.pop_front() {
            let hop = line.devices[device];
            for side in Direction::ALL.into_iter().filter(|&side| {
                mask & bit(side) != 0 && faces[side as usize].is_some_and(|face| face.inbound)
            }) {
                if line.source(hop.pos, side).is_some() {
                    sources.push((hop.pos, side));
                }
                let next = relative(hop.pos, side, 1);
                if let Some(&next) = line.by_pos.get(&next)
                    && visited.insert(next)
                    && let Some(faces) = device_at(game, line.devices[next].pos)
                        .and_then(|entity| directed_faces(entity, line.devices[next]))
                {
                    pending.push_back((next, line.devices[next].ports, faces));
                }
            }
        }
        NETWORKS.with(|cache| {
            let mut cache = cache.borrow_mut();
            let dimension =
                cache.dimension(std::ptr::from_ref(&game.world) as usize, game.dim.id());
            for (pos, side) in sources {
                if let Some(state) = dimension.live.get_mut(&pos) {
                    state.source_ticks[side as usize] = 0;
                    state.overlap_targets.remove(&(side as u8));
                }
            }
        });
    }

    fn tick_overlap(
        game: &mut Game<'_>,
        entity: &mut ModBlockEntity,
        line: &Line,
        index: usize,
        rpm: f32,
    ) -> bool {
        let hop = line.devices[index];
        let Some(saved) = directed_faces(entity, hop) else {
            return false;
        };
        let primary = pump_speed(game, hop.pump, hop.pos, rpm) / hop.divisor as f32;
        let secondary = hop.other.map_or(0.0, |other| {
            pump_speed(game, other.pump, hop.pos, rpm) / other.divisor as f32
        });
        let pressures = Direction::ALL.map(|side| {
            let pressure = |main, alt| {
                let first = if main & bit(side) != 0 { primary } else { 0.0 };
                let second = if alt & bit(side) != 0 { secondary } else { 0.0 };
                first + second
            };
            flow::Pressure {
                inbound: pressure(hop.inlets, hop.other.map_or(0, |other| other.inlets)),
                outward: pressure(hop.outlets, hop.other.map_or(0, |other| other.outlets)),
            }
        });
        let inputs = Direction::ALL.map(|side| {
            if pressures[side as usize].inbound == 0.0 {
                return None;
            }
            if let Some(source) = line.source(hop.pos, side) {
                return Endpoint::at(game, source, (hop.pos, entity))?.sample();
            }
            let entity = device_at(game, relative(hop.pos, side, 1))?;
            let (flow, inbound) = stored(entity, side.opposite())??;
            if inbound { None } else { flow.complete() }
        });
        let source_flow = Direction::ALL
            .into_iter()
            .filter(|&side| {
                let i = side as usize;
                line.source(hop.pos, side).is_some()
                    && inputs[i].is_some_and(|input| {
                        saved[i].is_some_and(|face| face.inbound && face.flow.fluid == input)
                    })
            })
            .fold(0, |mask, side| mask | bit(side));
        let (phase, ready) = controls(
            game,
            hop.pos,
            entity.revision(),
            Some((line, hop)),
            [primary, secondary],
            source_flow,
        );
        let before = std::array::from_fn(|i| {
            if phase == PRESSURE_REBUILD_TICKS {
                saved[i]
            } else {
                pressures[i].flip(saved[i]?)
            }
        });
        let mut after = before;
        if phase == 0 {
            let mut internal = None;
            let mut inbound_count = 0;
            for face in before {
                if let Some(fluid) = complete_face(face, true) {
                    if let Some(inside) = internal.filter(|&inside| inside != fluid) {
                        react_to_flow_collision(game, line, hop.pos, entity, inside, fluid);
                        return false;
                    }
                    internal = Some(fluid);
                    inbound_count += 1;
                }
            }
            after = std::array::from_fn(|i| {
                let from_self = inbound_count == 1 && complete_face(before[i], true).is_some();
                pressures[i].tick(
                    before[i],
                    inputs[i],
                    if from_self { None } else { internal },
                )
            });
            for side in Direction::ALL.into_iter().filter(|&side| {
                ready & bit(side) != 0 && after[side as usize].is_some_and(|face| face.inbound)
            }) {
                let i = side as usize;
                let (Some(source), Some(kind)) = (line.source(hop.pos, side), inputs[i]) else {
                    continue;
                };
                let found = overlap_targets(game, line, index, side, before, kind);
                let targets = retain_overlap_targets(game, hop.pos, side, found);
                transfer(
                    game,
                    hop.pos,
                    entity,
                    source,
                    &targets,
                    kind,
                    flow::transfer_rate(pressures[i].inbound),
                );
            }
            for side in Direction::ALL {
                let i = side as usize;
                if before[i].is_some_and(|face| face.inbound)
                    && after[i].is_some_and(|face| !face.inbound)
                {
                    reset_overlap_sources(game, line, index, side, before);
                }
            }
        }
        if entity.id == PUMP {
            let reset = NETWORKS.with(|cache| {
                cache
                    .borrow_mut()
                    .dimension(std::ptr::from_ref(&game.world) as usize, game.dim.id())
                    .reset_overlap_inlets
                    .remove(&hop.pos)
                    .is_some()
            });
            if reset
                && primary > 0.0
                && let Some(inlet) = hop.inlets().next()
            {
                reset_overlap_sources(game, line, index, inlet, after);
            }
        }
        let mut changed = false;
        for side in Direction::ALL
            .into_iter()
            .filter(|&side| hop.ports & bit(side) != 0)
        {
            let i = side as usize;
            let force = saved[i].map(|face| face.inbound) != after[i].map(|face| face.inbound);
            changed |= save_face(entity, side, pressures[i], after[i], force);
        }
        changed
    }

    pub(in crate::game) fn tick(
        game: &mut Game<'_>,
        pos: Pos,
        entity: &mut ModBlockEntity,
        rpm: f32,
    ) -> bool {
        if !matches!(entity.id.as_str(), PIPE | PUMP | VALVE) {
            return false;
        }
        let Some(origin) = state(game, pos) else {
            return false;
        };
        if port_mask(origin) == 0 {
            return false;
        }
        let recovery = collision_recovery(game, pos, entity);
        let now = game.world.game_time;
        match recovery {
            Some(CollisionRecovery::Junction { resume_at }) if now < resume_at => return false,
            Some(CollisionRecovery::Split {
                resume_at,
                role: SplitRole::Pipe,
                ..
            }) if now < resume_at => {
                if now + i64::from(PRESSURE_REBUILD_TICKS) == resume_at {
                    // The neighbor tick drops faces that no longer connect.
                    return Direction::ALL
                        .into_iter()
                        .filter(|&side| port_mask(origin) & bit(side) == 0)
                        .fold(false, |changed, side| {
                            entity.nbt.remove(&side.name().into()).is_some() || changed
                        });
                }
                return false;
            }
            Some(CollisionRecovery::Split {
                resume_at,
                role: SplitRole::Pump,
                ..
            }) if now < resume_at => {
                if let Some(front) = front_of_pump(origin) {
                    let hop = Hop::new(pos, bit(front.opposite()), bit(front), pos);
                    republish_split_pressure(game, pos, rpm);
                    return faces(entity, hop)
                        .is_some_and(|before| save(entity, hop, rpm.abs(), before, before));
                }
            }
            _ => {}
        }
        let Some((line, index)) = line(game, pos, origin) else {
            let managed = NETWORKS.with(|cache| {
                let mut cache = cache.borrow_mut();
                cache
                    .dimension(std::ptr::from_ref(&game.world) as usize, game.dim.id())
                    .live
                    .get(&pos)
                    .is_some_and(|state| {
                        state.line.is_some()
                            && state
                                .owner
                                .is_some_and(|owner| owner.is_same_create_entity(entity.revision()))
                    })
            });
            // An unsupported or unloaded path has no authority to drain
            // storage. End visual flow only on a connection we managed.
            controls(game, pos, entity.revision(), None, [0.0; 2], 0);
            return managed && clear_connections(entity, true);
        };
        let hop = line.devices[index];
        if !hop.matches(origin) {
            return false;
        }
        if line.overlap {
            return tick_overlap(game, entity, &line, index, rpm);
        }
        let Some(before) = faces(entity, hop) else {
            return false;
        };
        let pressure = pump_speed(game, hop.pump, pos, rpm) / hop.divisor as f32
            + hop.other.map_or(0.0, |other| {
                pump_speed(game, other.pump, pos, rpm) / other.divisor as f32
            });
        let valve_closed_here = origin.name == VALVE && !enabled(origin);
        let mut inputs = [None; 6];
        let mut sources = [None; 6];
        let mut source_flow = 0;
        if pressure > 0.0 && !valve_closed_here {
            for side in hop.inlets() {
                let i = side as usize;
                let source = line.source(pos, side);
                sources[i] = source;
                inputs[i] = match source {
                    Some(end) => Endpoint::at(game, end, (pos, entity))
                        .and_then(|mut endpoint| endpoint.sample()),
                    None => device_at(game, relative(pos, side, 1)).and_then(|entity| {
                        face(entity, side.opposite(), false)?.and_then(flow::Flow::complete)
                    }),
                };
                if source.is_some()
                    && inputs[i]
                        .is_some_and(|fluid| before[i].is_some_and(|inlet| inlet.fluid == fluid))
                {
                    source_flow |= bit(side);
                }
            }
        }
        let (phase, ready) = controls(
            game,
            pos,
            entity.revision(),
            Some((&line, hop)),
            [pressure, 0.0],
            source_flow,
        );
        let mut changed = maintain_open(pos, entity, &line, phase, pressure > 0.0);
        if phase != 0 {
            // Pressure is visible while the network waits to advance flow.
            return save(entity, hop, pressure, before, before) || changed;
        }
        let internal = match internal_fluid(hop, before) {
            Ok(fluid) => fluid,
            Err((first, other)) if pressure > 0.0 => {
                react_to_flow_collision(game, &line, pos, entity, first, other);
                return changed;
            }
            Err(_) => None,
        };
        if ready != 0 {
            for side in hop.inlets().filter(|&side| ready & bit(side) != 0) {
                let i = side as usize;
                let (Some(source), Some(fluid)) = (sources[i], inputs[i]) else {
                    continue;
                };
                let destinations = ready_targets(game, &line, index, side, before, fluid);
                let (transferred, refresh) = transfer(
                    game,
                    pos,
                    entity,
                    source,
                    &destinations,
                    fluid,
                    flow::transfer_rate(pressure),
                );
                changed |= transferred;
                if refresh {
                    // Keep existing flow through both pressure rebuild phases.
                    let surfaces = source_surfaces(game, &line.open_sources);
                    *line.source_surfaces.borrow_mut() = surfaces.clone();
                    NETWORKS.with(|cache| {
                        let mut cache = cache.borrow_mut();
                        let live = &mut cache
                            .dimension(std::ptr::from_ref(&game.world) as usize, game.dim.id())
                            .live;
                        for hop in &line.devices {
                            if let Some(state) = live.get_mut(&hop.pos) {
                                state.phase = PRESSURE_REBUILD_TICKS;
                                state.source_ticks = [0; 6];
                                state.source_surfaces = surfaces.clone();
                                state.refresh_surface = false;
                            }
                        }
                    });
                    break;
                }
            }
        }
        let mut after = [None; 6];
        if pressure > 0.0 {
            for side in hop.inlets() {
                let i = side as usize;
                after[i] = flow::advance_face(before[i], inputs[i], pressure);
            }
            for side in hop.outlets() {
                after[side as usize] =
                    flow::advance_face(before[side as usize], internal, pressure);
            }
        }
        trace(game, hop, &line, pressure, after, entity);
        let resumed_pipe = matches!(
            recovery,
            Some(CollisionRecovery::Split {
                role: SplitRole::Pipe,
                ..
            })
        );
        changed | ((before != after || resumed_pipe) && save(entity, hop, pressure, before, after))
    }

    fn trace(
        game: &Game<'_>,
        hop: Hop,
        line: &Line,
        pressure: f32,
        faces: FaceFlows,
        entity: &ModBlockEntity,
    ) {
        if !trace_enabled() {
            return;
        }
        let flow = |face: Option<flow::Flow>| face.map(|f| (f.fluid.id(), f.progress));
        let inlet = hop.inlets().next().and_then(|side| faces[side as usize]);
        let outlet = hop.outlets().next().and_then(|side| faces[side as usize]);
        let source = hop
            .inlets()
            .any(|side| line.source(hop.pos, side).is_some());
        log::info!(
            "Create fluid pump: {}",
            serde_json::json!({
                "time": game.world.game_time, "pos": hop.pos, "pressure": pressure, "front": line.front.name(),
                "inlet": flow(inlet), "outlet": flow(outlet),
                "storage": source.then(|| line.sources.iter().copied().chain(line.targets.iter().map(|target| target.end))
                    .map(|end| Endpoint::at(game, end, (hop.pos, entity)).map(|endpoint| endpoint.amount())).collect::<Vec<_>>()),
            })
        );
    }

    fn trace_enabled() -> bool {
        static TRACE: std::sync::OnceLock<bool> = std::sync::OnceLock::new();
        *TRACE.get_or_init(|| std::env::var_os("CREATE_TRACE_FLUID_PUMP").is_some())
    }

    fn trace_attachment(pos: Pos, model: &'static str) {
        if !trace_enabled() {
            return;
        }
        thread_local! {
            static DRAWN: RefCell<std::collections::BTreeSet<(Pos, &'static str)>> = const { RefCell::new(std::collections::BTreeSet::new()) };
        }
        if DRAWN.with(|drawn| drawn.borrow_mut().insert((pos, model))) {
            log::info!(
                "Create fluid attachment: {}",
                serde_json::json!({"pos": pos, "model": model})
            );
        }
    }

    fn front_of_pump(state: &BlockState) -> Option<Direction> {
        (state.name == PUMP).then(|| front(state)).flatten()
    }

    pub(in crate::game) fn reacts(game: &Game<'_>, pos: Pos) -> bool {
        game.native_on("create")
            && game.native_block(pos) == PUMP
            && game.may_build()
            && !game.native_sneaking()
            && game
                .held()
                .is_some_and(|held| crate::game::create_port_chassis::wrench(game, held))
    }

    pub(in crate::game) fn right_click(game: &mut Game<'_>, pos: Pos) -> bool {
        if !reacts(game, pos) {
            return false;
        }
        if let Some(front) = state(game, pos).and_then(front)
            && game.native_set_block_property(pos, "facing", front.opposite().name())
        {
            crate::game::create_port_sounds::cog_wrench(game, pos);
        }
        true
    }

    fn pipe_shape(
        game: &GameLevel<'_>,
        mut id: BlockStateId,
        pos: Pos,
        preferred: Direction,
        ignore: Option<Direction>,
    ) -> Option<BlockStateId> {
        let before = game.registry.state(id)?;
        let joined = Direction::ALL.map(|side| {
            let [x, y, z] = relative(pos, side, 1);
            if ignore == Some(side) || !game.world.loaded(x, z) {
                return pipe_open(before, side);
            }
            game.registry
                .state(game.world.block(x, y, z))
                .is_some_and(|state| connects(state, side))
        });
        if !joined.contains(&true)
            && Direction::ALL
                .iter()
                .filter(|&&side| pipe_open(before, side))
                .count()
                == 2
        {
            return Some(id);
        }
        let ports = flow::placed_ports(joined, preferred);
        for (side, open) in Direction::ALL.into_iter().zip(ports) {
            id = game.native_state_with_property(
                id,
                side.name(),
                if open { "true" } else { "false" },
            )?;
        }
        Some(id)
    }

    pub(in crate::game) fn update_shape(
        game: &GameLevel<'_>,
        ticks: &mut horizon_world::level::Ticks,
        pos: Pos,
        id: BlockStateId,
        side: Direction,
    ) -> Option<BlockStateId> {
        if game.native_state_block(id) != Some(PIPE) {
            return None;
        }
        if game.facts.get(id).waterlogged {
            game.native_schedule_fluid_tick(ticks, pos, "minecraft:water", 5);
        }
        pipe_shape(game, id, pos, side, Some(side.opposite()))
    }

    pub(in crate::game) fn placement(
        game: &GameLevel<'_>,
        state: BlockStateId,
        ctx: &PlacementContext,
        block: &str,
        fluid: horizon_world::fluid::FluidState,
    ) -> Option<BlockStateId> {
        let pos = [ctx.pos.x, ctx.pos.y, ctx.pos.z];
        let wet = fluid == horizon_world::fluid::FluidState::WATER;
        let state = game.native_state_with_property(
            state,
            "waterlogged",
            if wet { "true" } else { "false" },
        )?;
        let look = crate::game::create_port::nearest(ctx.yaw, ctx.pitch);
        if block == PIPE {
            return pipe_shape(game, state, pos, look, None);
        }
        if block == VALVE {
            use create_engine::kinetics::Axis;
            let facing = if ctx.sneaking { look } else { look.opposite() };
            let ports = crate::game::create_port_placement::level_ports(game, pos);
            let has_shaft = |side: Direction| ports[side as usize];
            let has_pipe = |side: Direction| {
                let at = relative(pos, side, 1);
                game.registry
                    .state(game.world.block(at[0], at[1], at[2]))
                    .is_some_and(|s| connects(s, side))
            };
            let first = match facing.axis() {
                axis @ (Axis::X | Axis::Z) => {
                    let perpendicular = if axis == Axis::X {
                        Direction::South
                    } else {
                        Direction::East
                    };
                    let vertical_shaft = has_shaft(Direction::Up) || has_shaft(Direction::Down);
                    let horizontal_pipe =
                        has_pipe(perpendicular) || has_pipe(perpendicular.opposite());
                    (axis == Axis::X) == (vertical_shaft || horizontal_pipe)
                }
                Axis::Y => {
                    let prefer = |s: Direction| has_shaft(s) || has_pipe(s.clockwise(Axis::Y));
                    let x = prefer(Direction::East) || prefer(Direction::West);
                    let z = prefer(Direction::North) || prefer(Direction::South);
                    if x != z {
                        x
                    } else {
                        crate::game::create_port_placement::horizontal(ctx.yaw).axis() == Axis::X
                    }
                }
            };
            let state = game.native_state_with_property(state, "facing", facing.name())?;
            return game.native_state_with_property(
                state,
                "axis_along_first",
                if first { "true" } else { "false" },
            );
        }
        let joined: Vec<_> = Direction::ALL
            .into_iter()
            .filter(|&side| {
                let at = relative(pos, side, 1);
                let Some(adjacent) = game.registry.state(game.world.block(at[0], at[1], at[2]))
                else {
                    return false;
                };
                connects(adjacent, side)
            })
            .collect();
        if block == PUMP {
            let want = if ctx.sneaking { look } else { look.opposite() };
            let closest = joined.iter().rev().min_by_key(|&&side| {
                if side == want {
                    0
                } else if side == want.opposite() {
                    2
                } else {
                    1
                }
            });
            let base = if ctx.sneaking {
                want
            } else {
                create_engine::placement::preferred(
                    crate::game::create_port_placement::level_ports(game, pos),
                )
                .map_or(want, Direction::opposite)
            };
            let front = closest
                .filter(|&&side| side.axis() != want.axis() && !ctx.sneaking)
                .copied()
                .unwrap_or(base);
            return game.native_state_with_property(state, "facing", front.name());
        }
        Some(state)
    }

    pub(in crate::game) fn draw(
        game: &Game<'_>,
        pos: Pos,
        entity: &ModBlockEntity,
        draw: &mut BlockEntityDraw,
    ) {
        let Some(block) = state(game, pos) else {
            return;
        };
        let axis = straight_axis(block);
        if block.name == PUMP
            && let Some(facing) = front(block)
        {
            let axis = facing.axis();
            let angle = create_engine::visual::angle(
                draw.game_time as f64 + f64::from(draw.partial),
                crate::game::create_port::number(&entity.nbt, "Speed"),
                create_engine::visual::rotation_offset(pos, axis, false),
            );
            draw.push();
            draw.rotate_about(create_engine::visual::positive_axis(axis), angle, [0.5; 3]);
            crate::game::create_port::face_south(draw, facing);
            game.native_draw_model(draw, "create:block/mechanical_pump/cog", 0xFFFFFF);
            draw.pop();
        }
        if block.name == VALVE
            && let Some(axis) = axis
        {
            let (Some(facing), Some(shaft)) = (front(block), valve_axis(block, true)) else {
                return;
            };
            let angle = create_engine::visual::angle(
                draw.game_time as f64 + f64::from(draw.partial),
                crate::game::create_port::number(&entity.nbt, "Speed"),
                create_engine::visual::rotation_offset(pos, shaft, false),
            );
            draw.push();
            crate::game::create_port::orient(draw, shaft);
            draw.rotate_about([0.0, 1.0, 0.0], angle, [0.5; 3]);
            game.native_draw_model(draw, "create:block/shaft", 0xFFFFFF);
            draw.pop();
            let angle = pointer_angle(game, pos, entity, draw.partial);
            let offset = if axis.index() == 1 || shaft.index() == 0 {
                90.0
            } else {
                0.0
            };
            let pitch = match facing {
                Direction::Up => 0.0,
                Direction::Down => 180.0,
                _ => 90.0,
            };
            draw.push();
            if !matches!(facing, Direction::Up | Direction::Down) {
                crate::game::create_port::face_south(draw, facing);
            }
            draw.rotate_about([1.0, 0.0, 0.0], pitch, [0.5; 3]);
            draw.rotate_about([0.0, 1.0, 0.0], offset + angle, [0.5; 3]);
            if game.native_draw_model(draw, "create:block/fluid_valve/pointer", 0xFFFFFF) {
                trace_attachment(pos, "create:block/fluid_valve/pointer");
            }
            draw.pop();
        }
        if !crate::game::create_port::original_assets() {
            return;
        }
        // PipeAttachmentModel quads supply the tube beyond its core.
        use create_assets::PipeAttachment::{Connection, Drain, Rim, RimConnector};
        let sides = Direction::ALL.into_iter().filter(|&side| {
            if block.name == PIPE {
                pipe_open(block, side)
            } else {
                axis == Some(side.axis())
            }
        });
        for side in sides {
            let neighbor = state(game, relative(pos, side, 1));
            let models: &[create_assets::PipeAttachment] = if block.name == VALVE {
                if neighbor.is_some_and(|state| is_endpoint(&state.name, side.opposite())) {
                    &[Drain]
                } else {
                    &[]
                }
            } else if neighbor.is_some_and(|state| is_endpoint(&state.name, side.opposite())) {
                &[RimConnector, Drain]
            } else if block.name == PUMP {
                &[]
            } else if neighbor.is_some_and(|state| state.name == PIPE) {
                if axis == Some(side.axis()) {
                    &[Connection]
                } else {
                    &[RimConnector]
                }
            } else if neighbor
                .and_then(device_ports)
                .is_some_and(|ports| ports.contains(&side.opposite()))
            {
                &[RimConnector]
            } else {
                &[RimConnector, Rim]
            };
            for part in models {
                let model = part.model(side as usize);
                if game.native_draw_model(draw, model, 0xFFFFFF) {
                    trace_attachment(pos, model);
                }
            }
        }
        if block.name == PIPE
            && [Direction::East, Direction::Up, Direction::South]
                .into_iter()
                .any(|face| {
                    Direction::ALL
                        .into_iter()
                        .filter(|&side| side.axis() != face.axis() && pipe_open(block, side))
                        .count()
                        > 2
                })
        {
            game.native_draw_model(draw, create_assets::PIPE_CASING, 0xFFFFFF);
        }
    }
}

pub(super) fn client_tick(game: &mut Game<'_>) {
    if !game.native_window() || game.remote.is_none() || !game.native_on("create") {
        return;
    }
    let time = game.world.game_time;
    let session = std::ptr::from_ref(&game.world) as usize;
    let dimension = game.dim.id().to_owned();
    let entries: Vec<_> = game
        .world
        .block_entities
        .iter()
        .filter_map(|(&(x, y, z), e)| match e {
            BlockEntity::Mod(e)
                if matches!(
                    e.id.as_str(),
                    ID | tank::BLOCK | pump::PIPE | pump::PUMP | pump::VALVE
                ) =>
            {
                Some(([x, y, z], e.as_ref()))
            }
            _ => None,
        })
        .collect();
    tank::client_tick(session, &dimension, time, &entries);
    pump::client_tick(session, &dimension, time, &entries);
    let rims = pump::rim_events(game, session, &dimension, time, &entries);
    let entries = entries
        .into_iter()
        .filter_map(|(pos, e)| (e.id == ID).then(|| (pos, e.revision())));
    let entries: Vec<_> = entries.collect();
    let live: std::collections::BTreeSet<_> = entries.iter().map(|(pos, _)| *pos).collect();
    MOTION.with(|cache| {
        let mut cache = cache.borrow_mut();
        let cache = cache.dimension(session, &dimension);
        cache.retain(|p, _| live.contains(p));
        for (pos, owner) in entries {
            let m = cache.entry(pos).or_default();
            if m.tick.is_some_and(|t| t > time)
                || m.owner.is_some_and(|old| !old.is_same_create_entity(owner))
            {
                *m = Motion::default();
            }
            m.owner = Some(owner);
            if m.tick == Some(time) { continue; }
            // read(clientPacket) updates the chase target; the lazy tick is a
            // fallback for absent/removed mixers, as in BasinBlockEntity.
            let mixer = game.world.block_entities.get(&(pos[0],pos[1]+2,pos[2]));
            let moving = matches!(mixer, Some(BlockEntity::Mod(e)) if e.id == "create:mechanical_mixer" && crate::game::create_port::integer(&e.nbt,"Running") != 0 && crate::game::create_port::integer(&e.nbt,"Ticks") <= 20);
            if m.tick.is_none() || m.lazy <= 0 || m.moving != moving {
                m.moving = moving;
                m.lazy = 10;
            } else { m.lazy -= 1; }
            m.previous = m.angle;
            m.speed += ((if m.moving {20.0} else {0.0}) - m.speed) * 0.1;
            m.angle += m.speed;
            if let Some(BlockEntity::Mod(entity))=game.world.block_entities.get(&(pos[0],pos[1],pos[2])) {
                for (half,key) in ["InputTanks","OutputTanks"].into_iter().enumerate() {
                    let Ok(levels)=fluids::read_levels(entity.nbt.get(&key.into())) else {continue;};
                    let Ok(contents)=read_tanks(entity,key) else {continue;};
                    for (i,level) in levels.into_iter().enumerate() {
                        let index=half*2+i;
                        if let Some(fluid)=contents[i].as_ref(){m.rendered_fluids[index]=Some(fluid.clone());}
                        let chase=&mut m.fluid_levels[index];
                        if m.received_fluids[index]!=Some(level) {
                            if level.force {chase.value=level.value;chase.previous=level.value;}
                            chase.target=level.target;chase.speed=level.speed;
                            m.received_fluids[index]=Some(level);
                        }
                        chase.tick();
                    }
                }
            }
            m.tick = Some(time);
        }
    });
    for (pos, side, fluid, splash, jet) in rims {
        use crate::game::create_port_particles as particles;
        if let Some(inbound) = jet {
            particles::fluid_jet(game, pos, side, fluid, inbound, splash);
        } else {
            particles::fluid_rim(game, pos, side, fluid, splash);
        }
    }
}
fn rendered_fluids(
    game: &Game<'_>,
    pos: Pos,
    entity: &ModBlockEntity,
    partial: f32,
) -> [(Option<rules::Fluid<fluids::Key>>, f32); 4] {
    MOTION.with(|cache| {
        let mut cache = cache.borrow_mut();
        let motion = cache
            .dimension(std::ptr::from_ref(&game.world) as usize, game.dim.id())
            .get(&pos)
            .filter(|motion| {
                motion
                    .owner
                    .is_some_and(|owner| owner.is_same_create_entity(entity.revision()))
            });
        std::array::from_fn::<_, 4, _>(|i| {
            if let Some(m) = motion {
                return (
                    m.rendered_fluids[i].clone(),
                    m.fluid_levels[i].at(partial) * rules::TANK_CAPACITY as f32,
                );
            }
            let key = if i < 2 { "InputTanks" } else { "OutputTanks" };
            let fluid = read_tanks(entity, key).ok().and_then(|t| t[i % 2].clone());
            let units = fluids::read_levels(entity.nbt.get(&key.into()))
                .map_or(0.0, |l| l[i % 2].value * rules::TANK_CAPACITY as f32);
            (fluid, units)
        })
    })
}

/// MechanicalMixerBlockEntity.renderParticles reads both client inventories and
/// the rendered fluid at partial tick zero, in the source half/slot order.
pub(super) fn mixer_particle_contents(
    game: &Game<'_>,
    pos: Pos,
) -> Option<(Vec<ItemStack>, [Option<Fluid>; 4])> {
    let BlockEntity::Mod(entity) = game.world.block_entities.get(&(pos[0], pos[1], pos[2]))? else {
        return None;
    };
    if entity.id != ID || !crate::game::create_port::inventory_supported(entity) {
        return None;
    }
    let items = entity
        .items
        .iter()
        .take(18)
        .flatten()
        .filter(|stack| stack.count > 0)
        .cloned()
        .collect();
    let fluids = rendered_fluids(game, pos, entity, 0.0).map(|(fluid, units)| {
        fluid
            .filter(|fluid| units >= 1.0 && fluid.key.components.is_empty())
            .and_then(|fluid| Fluid::from_id(&fluid.key.id))
    });
    Some((items, fluids))
}

fn draw_fluids(
    game: &Game<'_>,
    pos: Pos,
    entity: &ModBlockEntity,
    draw: &mut BlockEntityDraw,
) -> f32 {
    let rendered = rendered_fluids(game, pos, entity, draw.partial);
    let total: f32 = rendered.iter().map(|(_, units)| units).sum();
    if total < 1.0 {
        return 0.0;
    }
    let ratio = (total / 2000.0).clamp(0.0, 1.0);
    let height = 2.0 / 16.0 + 12.0 / 16.0 * (1.0 - (1.0 - ratio) * (1.0 - ratio));
    let mut x = 2.0 / 16.0;
    for (fluid, units) in rendered {
        let Some(fluid) = fluid else {
            continue;
        };
        if units < 1.0 {
            continue;
        }
        let next = x + (units / total).clamp(0.0, 1.0) * 12.0 / 16.0;
        super::create_port_fluid_render::draw(
            game,
            draw,
            &native_fluid(&fluid),
            [x, 2.0 / 16.0, 2.0 / 16.0, next, height, 14.0 / 16.0],
            NativeFluidRenderOptions {
                argb: None,
                render_bottom: false,
                // Actual source fixture's stitched blocks atlas is 2048x1024.
                // This is explicit because Horizon stores block sprites in arrays.
                uv_shrink_ratio: 4.0 / 2048.0,
            },
        );
        x = next;
    }
    height
}
pub(super) fn draw(
    game: &Game<'_>,
    pos: Pos,
    entity: &ModBlockEntity,
    draw: &mut BlockEntityDraw,
) -> bool {
    if entity.id != ID {
        return false;
    }
    super::create_port_basin_filter::draw(game, pos, entity, draw);
    // Retained motion belongs to this live BE, including ordinary NBT changes.
    MOTION.with(|cache| {
        let mut cache = cache.borrow_mut();
        let motions = cache.dimension(std::ptr::from_ref(&game.world) as usize, game.dim.id());
        if motions.get(&pos).is_some_and(|m| {
            m.owner
                .is_some_and(|old| !old.is_same_create_entity(entity.revision()))
        }) {
            motions.remove(&pos);
        }
    });
    // restore() truncates supported inventories to18, while opaque unsupported
    // inventories retain every live slot. Borrow the same visible range.
    let end = if crate::game::create_port::inventory_supported(entity) {
        entity.items.len().min(18)
    } else {
        entity.items.len()
    };
    let items = &entity.items[..end];
    let fluid_height = draw_fluids(game, pos, entity, draw);
    let item_height = (fluid_height - 0.3).clamp(0.125, 0.6);
    let mut count = items.iter().flatten().filter(|s| s.count > 0).count();
    if count == 0 {
        return true;
    }
    let rotation = MOTION.with(|cache| {
        let mut cache = cache.borrow_mut();
        cache
            .dimension(std::ptr::from_ref(&game.world) as usize, game.dim.id())
            .get(&pos)
            .map_or(0.0, |m| m.previous + (m.angle - m.previous) * draw.partial)
    });
    // BlockPos.hashCode and RandomSource.create preserve stable item pile offsets.
    let hash = pos[1]
        .wrapping_add(pos[2].wrapping_mul(31))
        .wrapping_mul(31)
        .wrapping_add(pos[0]);
    let mut random = LegacyRandom::new(i64::from(hash));
    let partition = 360.0 / count as f32;
    let radius = if count == 1 { 0.0 } else { 0.125 };
    draw.push();
    draw.translate([0.5, 0.2, 0.5]);
    draw.rotate_about([0.0, 1.0, 0.0], rotation, [0.0; 3]);
    for item in items.iter().flatten().filter(|s| s.count > 0) {
        let angle = partition * count as f32;
        let at =
            crate::game::create_port_mixer::rotate_y([radius, f64::from(item_height), 0.0], angle);
        draw.push();
        if fluid_height > 0.0 {
            let phase = (draw.game_time as f32 + draw.partial) / 12.0 + angle;
            let bob = (crate::game::create_port_mixer::sin(phase) + 1.5) / 32.0;
            draw.translate([0.0, bob, 0.0]);
        }
        draw.translate(at.map(|v| v as f32));
        draw.rotate_about([0.0, 1.0, 0.0], angle + 35.0, [0.0; 3]);
        draw.rotate_about([1.0, 0.0, 0.0], 65.0, [0.0; 3]);
        for _ in 0..=item.count / 8 {
            draw.push();
            draw.translate(std::array::from_fn(|_| {
                (random.next_float() - 0.5) * 2.0 / 16.0
            }));
            game.native_draw_item(
                draw,
                item,
                horizon_assets::item_model::DisplayContext::Ground,
                None,
                0,
            );
            draw.pop();
        }
        draw.pop();
        count -= 1;
    }
    draw.pop();
    true
}
