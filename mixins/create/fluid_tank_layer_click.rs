// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT

fn remember_tank_layer_click(game: &crate::game::Game<'_>, pos: [i32; 3], face: [i32; 3]) {
    crate::game::create_port_fluid_tank::remember_layer_click(game, pos, face);
}
