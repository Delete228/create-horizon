// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT

fn create_render_bounds(
    game: &crate::game::Game<'_>,
    pos: [i32; 3],
    block: &str,
    entity: &crate::containers::ModBlockEntity,
    bounds: &mut [f32; 6],
) {
    crate::game::create_port_belt::render_bounds(game, pos, entity, bounds);
    crate::game::create_port_mixer::bounds(entity, bounds);
    if entity.id == crate::game::create_port_fluid_tank::BLOCK {
        crate::game::create_port_fluid_tank::render_bounds(pos, entity, bounds);
    }
    if crate::game::create_port_chute::is_chute(&entity.id) {
        // ChuteBlockEntity expands its render box three blocks below the opening.
        bounds[1] = bounds[1].min(-3.0);
    }
    if block == "create:large_water_wheel"
        || block == crate::game::create_port_portable_storage::BLOCK
    {
        *bounds = [-2.0, -2.0, -2.0, 3.0, 3.0, 3.0];
    }
}
