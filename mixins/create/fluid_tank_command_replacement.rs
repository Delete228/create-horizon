// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT

fn capture_tank_before_command_replacement(
    game: &crate::game::Game<'_>,
    pos: [i32; 3],
    state: horizon_world::registry::BlockStateId,
) {
    crate::game::create_port_fluid_tank::before_command_replacement(game, pos, state);
}
