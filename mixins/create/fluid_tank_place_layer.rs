// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT

fn finish_tank_layer(
    game: &mut crate::game::Game<'_>,
    pos: [i32; 3],
    stack: &crate::items::ItemStack,
) {
    crate::game::create_port_fluid_tank::place_layer(game, pos, stack);
}
