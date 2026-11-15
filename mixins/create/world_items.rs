// Copyright (c) The Create Team / The Creators of Create
// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT
// SharedDepotBlockMethods.onLanded and MechanicalPressBlockEntity world input.
use super::Game;
use crate::{containers::ModBlockEntity, items::ItemStack};
use create_engine::placement::Direction;
use horizon_core::random::RandomSource;
use horizon_items::item_nbt::item_to_nbt;
use horizon_world::nbt::Tag;
pub(super) fn catch(game: &mut Game<'_>, pos: [i32; 3], entity: &mut ModBlockEntity) {
    if entity.items.iter().any(Option::is_some) {
        return;
    }
    let dim = game.dim.id().to_owned();
    let min = [
        f64::from(pos[0]),
        f64::from(pos[1]) + 13.0 / 16.0 - 0.01,
        f64::from(pos[2]),
    ];
    let max = [min[0] + 1.0, f64::from(pos[1]) + 1.0, min[2] + 1.0];
    for dropped in game.native_item_entities(&dim, min, max) {
        if !game
            .dropped
            .iter()
            .any(|e| e.id == dropped.id && e.on_ground)
        {
            continue;
        }
        if dropped.position[1] < min[1]
            || dropped.position[0] < min[0]
            || dropped.position[0] > max[0]
            || dropped.position[2] < min[2]
            || dropped.position[2] > max[2]
        {
            continue;
        }
        let mut accepted = dropped.stack.clone();
        accepted.count = accepted
            .count
            .min(game.native_max_stack_size(&accepted.item).unwrap_or(64));
        let mut rest = dropped.stack;
        rest.count -= accepted.count;
        if game.native_set_item_entity(&dim, dropped.id, rest) {
            let record = super::create_port_belt::depot_item(game, &accepted, 0.5, Direction::Down);
            entity.items[0] = Some(accepted);
            entity.nbt.insert("HeldItem".into(), record);
            crate::game::create_port_sounds::land(game, pos);
            break;
        }
    }
}
#[derive(Clone)]
pub(super) struct Input {
    pub id: u32,
    pub position: [f64; 3],
    pub stack: ItemStack,
}
/// The idle scan deflates the block box by an eighth of a block. The actual
/// stroke uses the full box and still considers items without a recipe.
pub(super) fn inputs(game: &Game<'_>, press: [i32; 3], margin: f64) -> Vec<Input> {
    let min = [
        f64::from(press[0]),
        f64::from(press[1] - 1),
        f64::from(press[2]),
    ];
    game.native_item_entities(
        game.dim.id(),
        min.map(|v| v + margin),
        min.map(|v| v + 1.0 - margin),
    )
    .into_iter()
    .filter(|item| game.dropped.iter().any(|e| e.id == item.id && e.on_ground))
    .map(|item| Input {
        id: item.id,
        position: item.position,
        stack: item.stack,
    })
    .collect()
}
pub(super) fn strike(game: &mut Game<'_>, pos: [i32; 3], bulk: bool) -> (bool, Vec<Tag>) {
    // PressingBehaviour.applyInWorld stops at the first grounded item in
    // nonbulk mode, regardless of whether it has a recipe.
    let limit = if bulk { usize::MAX } else { 1 };
    let inputs = inputs(game, pos, 0.0);
    let grounded = !inputs.is_empty();
    let particles = inputs
        .into_iter()
        .take(limit)
        .filter_map(|input| {
            let outputs = super::create_port::press_outputs(game, &input.stack, bulk)?;
            let particles = press(game, input, outputs, bulk)?;
            Some(item_to_nbt(&particles))
        })
        .collect();
    (grounded, particles)
}

fn press(
    game: &mut Game<'_>,
    input: Input,
    outputs: Vec<ItemStack>,
    bulk: bool,
) -> Option<ItemStack> {
    let dim = game.dim.id().to_owned();
    let velocity = game
        .dropped
        .iter()
        .find(|e| e.id == input.id && e.stack == input.stack && e.on_ground)?
        .velocity;
    let mut particle = input.stack;
    let mut outputs = outputs.into_iter();
    let output = outputs.next()?;
    if bulk || particle.count == 1 {
        // RecipeApplier keeps the original entity for the first result and
        // gives extra result entities its current movement.
        if !game.native_set_item_entity(&dim, input.id, output) {
            return None;
        }
        for extra in outputs {
            game.spawn_item(
                extra,
                input.position,
                [velocity.x, velocity.y, velocity.z],
                0,
            );
        }
    } else {
        // Java stores the live source stack for particles, then shrinks it.
        particle.count -= 1;
        if !game.native_set_item_entity(&dim, input.id, particle.clone()) {
            return None;
        }
        for stack in std::iter::once(output).chain(outputs) {
            let motion = std::array::from_fn(|_| {
                f64::from((game.world.random.next_float() - 0.5) * 2.0 * 0.05)
            });
            game.spawn_item(stack, input.position, motion, 10);
            if std::env::var_os("CREATE_HORIZON_TRACE").is_some() {
                log::info!(
                    "Create press world split: {}",
                    serde_json::json!({
                        "position": input.position, "motion": motion, "pickup_delay": 10,
                    })
                );
            }
        }
    }
    Some(particle)
}
