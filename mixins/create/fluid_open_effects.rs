// Copyright (c) The Create Team / The Creators of Create
// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT

// OpenEndedPipe's WaterEffectHandler and LavaEffectHandler.
use super::{Game, create_port_fan::blasting_fire_resistance};
use create_engine::{fluid_transport::Fluid, placement::Direction};
use horizon_client::projectiles::ProjectileKind;
use horizon_core::{
    geometry::{Aabb, Vec3},
    position::BlockPos,
};

const FIRE_TICKS: i32 = 3 * 20;

/// The outlet's exposed block and one block below it. A down-facing end
/// reaches a second block below. The box uses entity bounds, not feet cells.
fn bounds([x, y, z]: [i32; 3], side: Direction) -> Aabb {
    let (x, y, z) = (f64::from(x), f64::from(y), f64::from(z));
    Aabb::new(
        Vec3::new(x, y - if side == Direction::Down { 2.0 } else { 1.0 }, z),
        Vec3::new(x + 1.0, y + 1.0, z + 1.0),
    )
}

fn douse_blocks(game: &mut Game<'_>, area: Aabb) {
    // BlockPos.betweenClosedStream(AABB) floors both corners, including
    // cells on the upper faces even though entity intersection is strict.
    let min = area.min_position();
    let max = area.max_position();
    for z in min.z.floor() as i32..=max.z.floor() as i32 {
        for y in min.y.floor() as i32..=max.y.floor() as i32 {
            for x in min.x.floor() as i32..=max.x.floor() as i32 {
                if game.world.loaded(x, z) {
                    douse_block(game, [x, y, z]);
                }
            }
        }
    }
}

fn douse_block(game: &mut Game<'_>, [x, y, z]: [i32; 3]) {
    let pos = [x, y, z];
    let id = game.world.block(x, y, z);
    if id == game.world.air {
        return;
    }
    let registry = game.pack.assets.registry;
    let Some(state) = registry.state(id) else {
        return;
    };
    if game.block_in_tag("minecraft:fire", &state.name) {
        let _ = game.level_set(pos, game.world.air);
        return;
    }
    if state.properties.get("lit").is_none_or(|lit| lit != "true") {
        return;
    }
    if game.with_level(|b, level, ticks| b.extinguish_candle(level, ticks, BlockPos::new(x, y, z)))
    {
        let _ = game.process_level_events();
    } else if game.block_in_tag("minecraft:campfires", &state.name) {
        let mut unlit = state.clone();
        unlit.properties.insert("lit".into(), "false".into());
        if let Ok(unlit) = registry.resolve(&unlit) {
            game.level_event_at(1009, pos, 0);
            game.post_block_game_event("minecraft:block_change", pos, None, None);
            let _ = game.level_set(pos, unlit);
        }
    }
}

fn affect_portable(game: &mut Game<'_>, area: Aabb, fluid: Fluid) {
    let items = world_items!(game);
    for item in &mut game.dropped {
        if item.health <= 0 || !area.intersects(item.bounds()) {
            continue;
        }
        let prototype = items
            .get(&item.stack.item)
            .is_some_and(|i| i.fire_resistant);
        if blasting_fire_resistance(&item.stack, prototype) != Some(false) {
            continue;
        }
        match fluid {
            Fluid::Water => item.fire_ticks = item.fire_ticks.min(0),
            // The vanilla item tick still clears fire for a prototype whose
            // resistance was explicitly removed. Keep such stacks untouched.
            Fluid::Lava if !items.resists_fire(&item.stack, "minecraft:in_fire") => {
                item.fire_ticks = item.fire_ticks.max(FIRE_TICKS);
            }
            _ => {}
        }
    }
    for projectile in &mut game.creatures.projectiles {
        // Regular, tipped and spectral arrows share the same fire state.
        if !matches!(projectile.kind, ProjectileKind::Arrow { .. })
            || !area.intersects(projectile.bounds())
        {
            continue;
        }
        let Some(arrow) = projectile.arrow.as_mut() else {
            continue;
        };
        let before = arrow.fire_ticks;
        match fluid {
            Fluid::Water => arrow.clear_fire(),
            Fluid::Lava => arrow.ignite_for_ticks(FIRE_TICKS),
            _ => {}
        }
        projectile.needs_sync |= arrow.fire_ticks != before;
    }
}

/// Run once for a committed fill into an open outlet, including a partial
/// fill of its internal buffer. The source handler has no contact damage:
/// only vanilla burning can hurt an entity subsequently ignited here.
pub(super) fn apply(game: &mut Game<'_>, output: [i32; 3], side: Direction, fluid: Fluid) {
    if !matches!(fluid, Fluid::Water | Fluid::Lava) || game.world.game_time.rem_euclid(5) != 0 {
        return;
    }
    let area = bounds(output, side);
    for mob in &mut game.mobs {
        if mob.removed || !area.intersects(mob.bounds()) {
            continue;
        }
        let before = mob.fire_ticks;
        match fluid {
            Fluid::Water if mob.is_on_fire() => mob.fire_ticks = 0,
            Fluid::Lava if !mob.kind.flags.fire_immune => mob.ignite_for_ticks(FIRE_TICKS),
            _ => {}
        }
        mob.needs_sync |= mob.fire_ticks != before;
    }
    game.for_each_player(|game| {
        let Some(player) = game.player.as_mut().filter(|p| area.intersects(p.bounds())) else {
            return;
        };
        match fluid {
            Fluid::Water if player.fire_ticks > 0 => player.set_remaining_fire_ticks(0),
            Fluid::Lava => {
                let _ = player.ignite_for_ticks(FIRE_TICKS);
            }
            _ => {}
        }
    });
    affect_portable(game, area, fluid);
    if fluid == Fluid::Water {
        douse_blocks(game, area);
    }
}
