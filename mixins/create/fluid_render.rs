// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT

use super::{Game, native_block_entity_draw::BlockEntityDraw};
use crate::{fluid_render::fluid_box, gfx::FLUID_OVERLAY, mesher::Vertex};
use create_engine::fluid_transport::Fluid;
use glam::Vec3;
use horizon_client::mod_api::{NativeFluidRenderOptions, NativeFluidStack};

pub(super) fn custom_style(game: &Game<'_>, fluid: Fluid) -> Option<(&'static str, u32)> {
    let (sprite, fallback, tint) = match fluid {
        Fluid::Honey => (
            "create:fluid/honey_still",
            "minecraft:block/honey_block_top",
            0xffff_dca0,
        ),
        Fluid::Chocolate => (
            "create:fluid/chocolate_still",
            "minecraft:block/terracotta",
            0xff7e_5147,
        ),
        _ => return None,
    };
    let layers = &game.pack.render.sprite_layers;
    if layers.contains_key(sprite) {
        Some((sprite, 0xffff_ffff))
    } else {
        [fallback, fallback.strip_prefix("minecraft:")?]
            .into_iter()
            .find(|name| layers.contains_key(*name))
            .map(|name| (name, tint))
    }
}

pub(super) fn draw(
    game: &Game<'_>,
    draw: &mut BlockEntityDraw,
    stack: &NativeFluidStack,
    bounds: [f32; 6],
    options: NativeFluidRenderOptions,
) -> bool {
    let Some(fluid) = Fluid::from_id(&stack.fluid) else {
        return false;
    };
    if fluid.has_world_state() {
        return game.native_draw_fluid_box(draw, stack, bounds, options);
    }
    if !stack.components.is_empty() {
        return false;
    }
    if stack.amount <= 0 {
        return true;
    }
    let Some((sprite, tint)) = custom_style(game, fluid) else {
        return false;
    };
    let layer = game.pack.render.sprite_layers[sprite];
    let pose = draw.pose();
    let light = draw.light;
    let argb = options.argb.unwrap_or(tint);
    let color = (argb & 0xff00_ff00) | ((argb >> 16) & 0xff) | ((argb & 0xff) << 16);
    fluid_box(bounds, options, |vertex| {
        draw.vertices_mut().push(Vertex {
            pos: pose
                .transform_point3(Vec3::from_array(vertex.pos))
                .to_array(),
            uv: vertex.uv,
            layer: FLUID_OVERLAY,
            color,
            light,
            normal: [0; 4],
            glint_uv: [layer as f32, 0.0],
        });
    })
}
