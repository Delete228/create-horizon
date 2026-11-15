// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT

fn create_changed(
    level: &crate::game::GameLevel<'_>,
    dimension: horizon_world::level::Dimension,
    pos: horizon_core::position::BlockPos,
    old: horizon_world::registry::BlockStateId,
    new: horizon_world::registry::BlockStateId,
) {
    use crate::game::create_port_kinetic_runtime as kinetics;
    use create_engine::kinetics::Axis;

    let dimension = match dimension {
        horizon_world::level::Dimension::Overworld => "minecraft:overworld",
        horizon_world::level::Dimension::Nether => "minecraft:the_nether",
        horizon_world::level::Dimension::End => "minecraft:the_end",
    };
    let pos = [pos.x, pos.y, pos.z];
    let tank = crate::game::create_port_fluid_tank::BLOCK;
    crate::game::create_port_fluid_tank::changed(
        level,
        dimension,
        pos,
        level.native_state_block(old) == Some(tank),
        level.native_state_block(new) == Some(tank),
    );
    crate::game::create_port_millstone::forget(pos);
    crate::game::create_port_fan::changed(dimension, pos);
    crate::game::create_port_particles::changed(dimension, pos);
    crate::game::create_port_drill::changed(dimension, pos);
    kinetics::invalidate();
    let severed_axis = match level.native_state_block(old) {
        Some("create:shaft") => [Axis::X, Axis::Y, Axis::Z]
            .into_iter()
            .find(|axis| level.native_state_with_property(old, "axis", axis.name()) == Some(old)),
        Some("create:creative_motor") => create_engine::placement::Direction::ALL
            .into_iter()
            .find(|side| level.native_state_with_property(old, "facing", side.name()) == Some(old))
            .map(create_engine::placement::Direction::axis),
        _ => None,
    };
    if let Some(axis) = severed_axis
        && level.native_state_block(new) == Some("minecraft:air")
    {
        kinetics::shaft_cut(dimension, pos, axis);
    }
}
