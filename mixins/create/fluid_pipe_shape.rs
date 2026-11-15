// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT

fn create_pipe_shape(
    level: &crate::game::GameLevel<'_>,
    ticks: &mut horizon_world::level::Ticks,
    pos: horizon_core::position::BlockPos,
    state: horizon_world::registry::BlockStateId,
    direction: horizon_core::geometry::Direction,
    new: &mut Option<horizon_world::registry::BlockStateId>,
) {
    let direction = crate::game::create_port_placement::direction(direction);
    if let Some(shape) = crate::game::create_port_basin::pump::update_shape(
        level, ticks, [pos.x, pos.y, pos.z], state, direction,
    ) {
        *new = Some(shape);
    }
}
