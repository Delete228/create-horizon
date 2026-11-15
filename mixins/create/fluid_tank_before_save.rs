// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT

fn fluid_tank_before_save(game: &mut crate::game::Game<'_>) {
    crate::game::create_port_fluid_tank::before_save(game);
}
