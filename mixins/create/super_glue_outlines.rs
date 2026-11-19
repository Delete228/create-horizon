// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT

fn create_super_glue_outlines(
    game: &crate::game::Game<'_>,
    primitives: &mut horizon_client::world_primitives::WorldPrimitives,
) {
    crate::game::create_port_super_glue::outlines(game, primitives);
}
