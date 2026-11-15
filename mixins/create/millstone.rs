// Copyright (c) The Create Team / The Creators of Create
// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT
// MillstoneBlock/BlockEntity: processing, filtered capability, falling items,
// empty-hand collection and original NBT. No vanilla container screen is used.
use super::{Game, native_block_entity_draw::BlockEntityDraw};
use crate::{
    containers::{BlockEntity, ModBlockEntity, ModContainer, ModRevision},
    items::ItemStack,
};
use create_engine::{
    kinetics::Axis,
    milling::{self, Action, MillCycle},
    transport::SessionCache,
};
use horizon_core::random::RandomSource;
use horizon_world::nbt::{Compound, Tag};
use std::{
    cell::RefCell,
    collections::{BTreeMap, BTreeSet},
    sync::{Arc, OnceLock},
};

pub(super) const ID: &str = "create:millstone";

thread_local! {
    // Containers::can_place has the item registry but no recipe table at API
    // 359. Its query uses the latest server recipe ingredients compiled here.
    static INPUTS: RefCell<Inputs> = const {RefCell::new(Inputs {
        stamp: None, sources: Vec::new(), accepted: BTreeSet::new(),
        recipes: Vec::new(), last: BTreeMap::new(),
    })};
}

struct Inputs {
    stamp: Option<(usize, i64)>,
    sources: Vec<Arc<serde_json::Value>>,
    accepted: BTreeSet<String>,
    recipes: Vec<CompiledRecipe>,
    last: BTreeMap<(String, [i32; 3]), usize>,
}

pub(super) fn invalidate_recipes() {
    INPUTS.with(|cache| {
        let mut cache = cache.borrow_mut();
        cache.stamp = None;
        cache.sources.clear();
        cache.accepted.clear();
        cache.recipes.clear();
        cache.last.clear();
    });
}

pub(super) fn refresh_recipes(game: &Game<'_>) {
    INPUTS.with(|cache| {
        let mut cache = cache.borrow_mut();
        let stamp = (std::ptr::from_ref(game) as usize, game.world.game_time);
        if cache.stamp == Some(stamp) {
            return;
        }
        if cache
            .stamp
            .is_some_and(|previous| previous.0 != stamp.0 || previous.1 > stamp.1)
        {
            cache.sources.clear();
            cache.last.clear();
            cache.recipes.clear();
            cache.accepted.clear();
        }
        cache.stamp = Some(stamp);
        let recipes = game.native_recipes_of_type("create:milling");
        if recipes.len() == cache.sources.len()
            && recipes
                .iter()
                .zip(&cache.sources)
                .all(|(r, old)| Arc::ptr_eq(&r.json, old))
        {
            return;
        }
        cache.recipes = recipes
            .iter()
            .filter_map(|r| compile_recipe(game, &r.json))
            .collect();
        cache.accepted = cache
            .recipes
            .iter()
            .flat_map(|r| r.input.order.iter().cloned())
            .collect();
        cache.last.clear();
        cache.sources = recipes.iter().map(|r| r.json.clone()).collect();
    });
}

pub(super) fn automation_accepts(stack: &ItemStack) -> bool {
    stack.count > 0 && INPUTS.with(|cache| cache.borrow().accepted.contains(stack.item.as_ref()))
}

/// MillstoneInventoryHandler.canProcess: evaluate the current compiled
/// ingredient predicate, without changing the processing cycle's last recipe.
pub(super) fn can_process(game: &Game<'_>, stack: &ItemStack) -> bool {
    refresh_recipes(game);
    stack.count > 0
        && INPUTS.with(|cache| {
            cache
                .borrow()
                .recipes
                .iter()
                .any(|recipe| recipe.input.test(stack))
        })
}

#[derive(Clone)]
struct Recipe {
    duration: i32,
    outputs: Vec<(ItemStack, f32)>,
}

struct CompiledRecipe {
    input: horizon_client::crafting::Ingredient,
    recipe: Recipe,
}

fn compile_recipe(game: &Game<'_>, json: &serde_json::Value) -> Option<CompiledRecipe> {
    let input = json["ingredients"]
        .as_array()
        .and_then(|a| a.first())
        .and_then(crate::game::create_port::ingredient)
        .and_then(|i| game.native_recipe_ingredient(&i))?;
    let outputs: Option<Vec<_>> = json["results"]
        .as_array()?
        .iter()
        .map(|output| compile_output(game, output))
        .collect();
    Some(CompiledRecipe {
        input,
        recipe: Recipe {
            duration: json["processing_time"]
                .as_i64()
                .or_else(|| json["processingTime"].as_i64())
                .unwrap_or(0) as i32,
            outputs: outputs?,
        },
    })
}

fn compile_output(game: &Game<'_>, output: &serde_json::Value) -> Option<(ItemStack, f32)> {
    use serde_json::Value;

    let mut legacy;
    let stack = if output.get("id").is_some() {
        output
    } else {
        // ProcessingOutput.CODEC_OLD: `item` is an ItemStack.SINGLE_ITEM_CODEC
        // value; `count` and `chance` belong to the outer result.
        legacy = match output.get("item")? {
            Value::Object(item) => Value::Object(item.clone()),
            // Accept the prior native shorthand for legacy item IDs.
            Value::String(id) => serde_json::json!({ "id": id }),
            _ => return None,
        };
        legacy["count"] = output.get("count").cloned().unwrap_or(Value::from(1));
        &legacy
    };
    if stack
        .get("components")
        .is_some_and(|value| !value.is_object())
    {
        return None;
    }
    let chance = match output.get("chance") {
        Some(chance) => chance.as_f64()? as f32,
        None => 1.0,
    };
    if !chance.is_finite() || chance < 0.0 {
        return None;
    }
    Some((game.native_recipe_result(stack)?, chance))
}

pub(super) fn forget(pos: [i32; 3]) {
    INPUTS.with(|cache| cache.borrow_mut().last.retain(|(_, p), _| *p != pos));
}

fn recipe(game: &Game<'_>, pos: [i32; 3], stack: &ItemStack) -> Option<Recipe> {
    INPUTS.with(|cache| {
        let mut cache = cache.borrow_mut();
        let key = (game.dim.id().to_owned(), pos);
        let index = cache
            .last
            .get(&key)
            .copied()
            .filter(|i| cache.recipes.get(*i).is_some_and(|r| r.input.test(stack)))
            .or_else(|| cache.recipes.iter().position(|r| r.input.test(stack)))?;
        cache.last.insert(key, index);
        Some(cache.recipes[index].recipe.clone())
    })
}

pub(super) fn container(block: &str, container: &mut Option<ModContainer>) {
    if block == ID && container.is_none() {
        *container = Some(ModContainer {
            slots: milling::INPUT_SLOTS + milling::OUTPUT_SLOTS,
            faces: std::array::from_fn(|_| (0..10).collect()),
            inputs: vec![0],
            outputs: (1..10).collect(),
            menu: None,
        });
    }
}

fn inventory(slots: &[Option<ItemStack>]) -> Tag {
    let items = slots
        .iter()
        .enumerate()
        .filter_map(|(slot, item)| {
            let Tag::Compound(mut tag) = horizon_items::item_nbt::item_to_nbt(item.as_ref()?)
            else {
                return None;
            };
            tag.insert("Slot".into(), Tag::Int(slot as i32));
            Some(Tag::Compound(tag))
        })
        .collect();
    Tag::Compound(Compound::from([
        ("Size".into(), Tag::Int(slots.len() as i32)),
        ("Items".into(), Tag::List(items)),
    ]))
}

fn restore(entity: &mut ModBlockEntity) {
    // Canonical inventory is decoded before publication. Never re-read an old
    // bridge snapshot after ordinary automation has already changed live slots.
    if crate::game::create_port::inventory_supported(entity) {
        entity.items.resize(10, None);
    }
}

pub(super) fn data(entity: &mut ModBlockEntity) -> bool {
    if entity.id != ID || !crate::game::create_port::inventory_supported(entity) {
        return false;
    }
    entity.items.resize(10, None);
    let mut changed = false;
    for (key, range) in [("InputInventory", 0..1), ("OutputInventory", 1..10)] {
        let Tag::Compound(updated) = inventory(&entity.items[range]) else {
            unreachable!();
        };
        let mut value = match entity.nbt.get(&key.into()) {
            Some(Tag::Compound(existing)) => existing.clone(),
            _ => Compound::new(),
        };
        value.extend(updated);
        let value = Tag::Compound(value);
        let key_nbt = key.into();
        changed |= entity.nbt.get(&key_nbt) != Some(&value);
        entity.nbt.insert(key_nbt, value.clone());
    }
    changed
}

pub(super) fn publish_inventory(game: &mut Game<'_>, pos: [i32; 3]) {
    // Direct input can run after the Millstone's block entity tick.
    if game.native_with_mod_block_entity(pos, data) == Some(true) {
        game.native_block_entity_sync(pos);
    }
}

pub(super) fn insert_from_transport(
    game: &mut Game<'_>,
    pos: [i32; 3],
    stack: &ItemStack,
    simulate: bool,
) -> u32 {
    let [x, y, z] = pos;
    let Some(BlockEntity::Mod(entity)) = game.world.block_entities.get(&(x, y, z)) else {
        return 0;
    };
    if entity.id != ID
        || !super::create_port::inventory_supported(entity)
        || !can_process(game, stack)
    {
        return 0;
    }
    if simulate {
        let present = match entity.items.first().and_then(Option::as_ref) {
            Some(current) if !current.same_item_same_components(stack) => return 0,
            Some(current) => current.count,
            None => 0,
        };
        return stack
            .count
            .min(max_stack(game, stack).saturating_sub(present));
    }
    let remaining = game
        .native_insert_item(pos, horizon_core::geometry::Direction::Up, stack.clone())
        .map_or(0, |rest| rest.count);
    if remaining < stack.count {
        publish_inventory(game, pos);
    }
    stack.count - remaining
}

fn max_stack(game: &Game<'_>, stack: &ItemStack) -> u32 {
    super::create_port::stack_maximum(game, stack)
}

/// Called after the kinetic network has resolved the current signed RPM.
pub(super) fn tick(
    game: &mut Game<'_>,
    pos: [i32; 3],
    entity: &mut ModBlockEntity,
    rpm: f32,
) -> bool {
    if entity.id != ID || !crate::game::create_port::inventory_supported(entity) {
        return false;
    }
    refresh_recipes(game);
    restore(entity);
    let input = entity.items[0].clone().filter(|s| s.count > 0);
    let mut cycle = MillCycle {
        timer: crate::game::create_port::integer(&entity.nbt, "Timer"),
    };
    let blocked = rpm == 0.0
        || entity.items[1..]
            .iter()
            .flatten()
            .any(|s| s.count == milling::SLOT_LIMIT);
    let matching = if cycle.timer <= 0 && !blocked {
        input.as_ref().and_then(|input| recipe(game, pos, input))
    } else {
        None
    };
    let action = cycle.tick(
        rpm,
        entity.items[1..]
            .iter()
            .map(|s| s.as_ref().map_or(0, |s| s.count)),
        input.is_some(),
        matching.as_ref().map(|r| r.duration),
    );
    entity.nbt.insert("Timer".into(), Tag::Int(cycle.timer));
    if action == Action::Process
        && let Some(input) = input
        && let Some(recipe) = matching.or_else(|| recipe(game, pos, &input))
    {
        let remainder = game
            .items()
            .get(&input.item)
            .and_then(|item| item.crafting_remainder.clone());
        entity.items[0] = if input.count > 1 {
            let mut stack = input;
            stack.count -= 1;
            Some(stack)
        } else {
            None
        };
        for (mut output, chance) in recipe.outputs {
            output.count =
                milling::roll_count(output.count, chance, || game.world.random.next_float());
            if output.count == 0 {
                continue;
            }
            let max = max_stack(game, &output).min(milling::SLOT_LIMIT);
            // Original insertItemStacked ignores remainder when the buffer
            // cannot fit a complete roll; preserve that behavior.
            let _ = crate::game::create_port_inventory::insert(&mut entity.items[1..], output, max);
        }
        if let Some(remainder) = remainder {
            let stack = ItemStack::new(&remainder, 1);
            let max = max_stack(game, &stack).min(milling::SLOT_LIMIT);
            let _ = crate::game::create_port_inventory::insert(&mut entity.items[1..], stack, max);
        }
    }
    let inventory_changed = data(entity);
    inventory_changed || matches!(action, Action::Armed | Action::Process)
}

pub(super) fn reacts(game: &Game<'_>, pos: [i32; 3]) -> bool {
    game.native_on("create")
        && game.native_block(pos) == ID
        && game
            .held()
            .is_none_or(|s| s.count == 0 || s.item.as_ref() == "minecraft:air")
}

pub(super) fn right_click(game: &mut Game<'_>, pos: [i32; 3]) -> bool {
    if crate::game::create_port::inventory_blocked(game, pos) {
        return true;
    }
    if !reacts(game, pos) {
        return false;
    }
    let Some(stacks) = game.native_with_mod_block_entity(pos, |entity| {
        restore(entity);
        let take_input = milling::collect_input(
            entity.items[1..]
                .iter()
                .map(|s| s.as_ref().map_or(0, |s| s.count)),
        );
        let stacks = if take_input {
            entity.items[..1]
                .iter_mut()
                .filter_map(Option::take)
                .collect::<Vec<_>>()
        } else {
            entity.items[1..]
                .iter_mut()
                .filter_map(Option::take)
                .collect::<Vec<_>>()
        };
        data(entity);
        stacks
    }) else {
        return false;
    };
    let uuid = game.native_acting_id();
    for stack in stacks {
        if let Some(rest) = game.native_give_stack(uuid, stack)
            && let Some(player) = game.native_player()
        {
            game.spawn_item(
                rest,
                [player.x, player.y + 1.0, player.z],
                [0.0, 0.2, 0.0],
                10,
            );
        }
    }
    game.native_block_entity_sync(pos);
    true
}

pub(super) fn draw(
    game: &Game<'_>,
    pos: [i32; 3],
    entity: &ModBlockEntity,
    draw: &mut BlockEntityDraw,
) -> bool {
    if entity.id != ID {
        return false;
    }
    let angle = create_engine::visual::angle(
        draw.game_time as f64 + f64::from(draw.partial),
        crate::game::create_port::number(&entity.nbt, "Speed"),
        create_engine::visual::rotation_offset(pos, Axis::Y, false),
    );
    draw.push();
    draw.rotate_about([0.0, 1.0, 0.0], angle, [0.5; 3]);
    game.native_draw_model(
        draw,
        "create:block/millstone/inner",
        crate::game::create_port_presentation::kinetic_tint(game, pos),
    );
    draw.pop();
    true
}

struct ClientMillstone {
    revision: ModRevision,
    cycle: MillCycle,
    rpm: f32,
    full: bool,
    input: Option<ItemStack>,
}

impl ClientMillstone {
    fn read(entity: &ModBlockEntity) -> Self {
        let items = |key: &str| match entity.nbt.get(&key.into()).and_then(|v| v.get("Items")) {
            Some(Tag::List(items)) => items.as_slice(),
            _ => &[],
        };
        let read = horizon_items::item_nbt::item_from_nbt;
        Self {
            revision: entity.revision(),
            cycle: MillCycle {
                timer: super::create_port::integer(&entity.nbt, "Timer"),
            },
            rpm: super::create_port::number(&entity.nbt, "Speed"),
            full: items("OutputInventory")
                .iter()
                .filter_map(read)
                .any(|stack| stack.count == milling::SLOT_LIMIT),
            input: items("InputInventory")
                .first()
                .and_then(read)
                .filter(|stack| stack.count > 0),
        }
    }
}

type ClientMillstones = BTreeMap<(i32, i32, i32), ClientMillstone>;
thread_local! {
    static CLIENT: RefCell<SessionCache<ClientMillstones>> = RefCell::new(SessionCache::default());
}

/// Mirrors the client branch of MillstoneBlockEntity.tick. Packet updates
/// load the authoritative timer. Between updates, the local timer counts
/// down, emits on the final decrement, and stays quiet on the next arm.
pub(super) fn client_tick(game: &mut Game<'_>) {
    if !game.native_window() || !game.native_on("create") || !game.clock.runs_normally() {
        return;
    }
    static TRACE: OnceLock<bool> = OnceLock::new();
    let trace = *TRACE.get_or_init(|| std::env::var_os("CREATE_HORIZON_PARTICLE_TRACE").is_some());
    let mut particles = Vec::new();
    CLIENT.with(|cache| {
        let mut cache = cache.borrow_mut();
        let states = cache.dimension(std::ptr::from_ref(&game.world) as usize, game.dim.id());
        states.retain(|pos, _| {
            matches!(game.world.block_entities.get(pos), Some(BlockEntity::Mod(entity)) if entity.id == ID)
        });
        for (&pos, entity) in &game.world.block_entities {
            let BlockEntity::Mod(entity) = entity else {
                continue;
            };
            if entity.id != ID {
                continue;
            }
            let state = states.entry(pos).or_insert_with(|| ClientMillstone::read(entity));
            if state.revision != entity.revision() {
                *state = ClientMillstone::read(entity);
            }
            let pos = [pos.0, pos.1, pos.2];
            let Some(input) = state.input.as_ref() else {
                continue;
            };
            if state.rpm == 0.0 || state.full {
                continue;
            }
            let duration = if state.cycle.timer <= 0 {
                refresh_recipes(game);
                recipe(game, pos, input).map(|recipe| recipe.duration)
            } else {
                None
            };
            let before = state.cycle.timer;
            let action = state.cycle.tick(state.rpm, [], true, duration);
            if matches!(action, Action::Processing | Action::Process) {
                particles.push((pos, state.rpm, before, input.clone()));
            } else if trace && action == Action::Armed {
                log::info!("Create millstone particle: {}", serde_json::json!({
                    "event": "armed", "pos": pos, "tick": game.world.game_time,
                    "timer": state.cycle.timer,
                }));
            }
        }
    });
    for (pos, rpm, before, input) in particles {
        let angle = game.world.random.next_float();
        let jitter = std::array::from_fn(|_| game.world.random.next_float());
        let (offset, velocity) = milling::particle_vectors(angle, rpm, jitter);
        let position = std::array::from_fn(|i| f64::from(pos[i]) + 0.5 + offset[i]);
        let options = game.item_particle(&input);
        let kind = options.ty.name();
        let previous = trace.then(|| game.particles.made().get(kind).copied().unwrap_or(0));
        game.particles.add(&options, position, velocity);
        if let Some(previous) = previous {
            let accepted = game.particles.made().get(kind).copied().unwrap_or(0) - previous;
            log::info!(
                "Create millstone particle: {}",
                serde_json::json!({
                    "event": "spawn", "pos": pos, "tick": game.world.game_time, "rpm": rpm,
                    "timer": before, "item": input.item.as_ref(), "position": position,
                    "velocity": velocity, "accepted": accepted,
                })
            );
        }
    }
}
