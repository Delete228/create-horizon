// Copyright (c) The Create Team / The Creators of Create
// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT

fn create_crafter_hopper_eject(
    game: &mut crate::game::Game<'_>,
    pos: (i32, i32, i32),
    state: horizon_world::registry::BlockStateId,
    hopper: &crate::game::machines::View,
) -> std::ops::ControlFlow<bool> {
    use crate::containers::ModContainer;
    use crate::game::{create_port_saw_processing::crafter, machines};
    use std::{ops::ControlFlow, sync::Arc};

    if !game.native_on("create") {
        return ControlFlow::Continue(());
    }
    let Some(facing) = game
        .containers()
        .prop(state, "facing")
        .and_then(machines::dir_from_name)
    else {
        return ControlFlow::Continue(());
    };
    let front = machines::offset(pos, facing);
    let target = [front.0, front.1, front.2];
    if game.native_block(target) != crafter::BLOCK {
        return ControlFlow::Continue(());
    }
    game.native_hopper_inventory_search([pos.0, pos.1, pos.2], Some(target), None);
    let Some(slot @ [x, y, z]) = crafter::hopper_input(game, target) else {
        return ControlFlow::Break(false);
    };
    let face = facing.opposite();
    let mut faces = std::array::from_fn(|_| Vec::new());
    faces[face as usize].push(0);
    let into = machines::View {
        parts: vec![((x, y, z), 1)],
        kind: machines::Kind::Mod,
        container: Some(Arc::new(ModContainer {
            slots: 1,
            faces,
            inputs: vec![0],
            outputs: Vec::new(),
            menu: None,
        })),
    };
    // Vanilla still chooses the source item and owns rollback, notifications
    // and Hopper cooldown. Only the receiving physical slot is substituted.
    let moved = game.eject_into(pos, hopper, &into, face);
    if moved {
        crafter::fed_by_hopper(game, slot);
    }
    ControlFlow::Break(moved)
}
