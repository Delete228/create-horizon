// Copyright (c) The Create Team / The Creators of Create
// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT

use std::cell::{Cell, OnceCell};

use super::{Game, native_ticks::TickRound};
use create_engine::{
    contraption::{
        contact::ContactBox,
        rotary_contact::{RotaryContact, rotary_contact},
    },
    kinetics::Axis,
    source_trig::rotate,
};
use horizon_client::{
    collisions::{EntityCollisions, SceneCollisions},
    entities::ItemEntity,
};
use horizon_client_render::create_contraption_scene::{
    ACTIVE, Pos, Record, read, upright_side_payload,
};
use horizon_core::geometry::{Aabb, Vec3};
use horizon_world::{
    collision_context::{CollisionContext, CollisionEntity, EntityContextKind},
    entity_obstruction::EntityIdentity,
};

thread_local! {
    static COLLISION_FILTER: Cell<(Option<Pos>, bool)> = const { Cell::new((None, false)) };
}

pub(super) fn collision_filter() -> (Option<Pos>, bool) {
    COLLISION_FILTER.get()
}

fn with_collision_filter<T>(filter: (Option<Pos>, bool), run: impl FnOnce() -> T) -> T {
    struct Restore((Option<Pos>, bool));
    impl Drop for Restore {
        fn drop(&mut self) {
            COLLISION_FILTER.set(self.0);
        }
    }
    let _restore = Restore(COLLISION_FILTER.replace(filter));
    run()
}

struct Carrier {
    record: Record,
    shapes: OnceCell<Vec<ContactBox>>,
    bounds: Aabb,
    obstacles: OnceCell<Vec<Aabb>>,
    has_slime: bool,
}

pub(super) const SLIME_BLOCK: &str = "minecraft:slime_block";

impl Carrier {
    fn new(record: Record) -> Option<Self> {
        if !upright_side_payload(&record) {
            return None;
        }
        let pivot = record.anchor.map(|v| f64::from(v) + 0.5);
        let mut radius_squared = 0.0_f64;
        let mut lower = f64::INFINITY;
        let mut upper = f64::NEG_INFINITY;
        let mut has_slime = false;
        for (local, state) in record.blocks.iter() {
            let [x, y, z] = local.map(f64::from);
            radius_squared = radius_squared.max(x * x + z * z);
            lower = lower.min(y);
            upper = upper.max(y + 1.0);
            has_slime |= state.name == SLIME_BLOCK;
        }
        // Include the corner of each cube and the source collider's broad-phase slack.
        let radius = radius_squared.sqrt() + 2.0;
        let bounds = Aabb::new(
            Vec3::new(
                pivot[0] - radius,
                pivot[1] - 0.5 + lower - 1.0,
                pivot[2] - radius,
            ),
            Vec3::new(
                pivot[0] + radius,
                pivot[1] - 0.5 + upper + 1.0,
                pivot[2] + radius,
            ),
        );
        Some(Self {
            record,
            shapes: OnceCell::new(),
            bounds,
            obstacles: OnceCell::new(),
            has_slime,
        })
    }

    fn shapes(&self) -> &[ContactBox] {
        self.shapes.get_or_init(|| {
            self.record
                .blocks
                .iter()
                .map(|(local, _)| ContactBox::cube(local.map(f64::from)))
                .collect()
        })
    }
}

struct Contact {
    position: Vec3,
    velocity: Vec3,
    surface: bool,
    bounced: bool,
}

pub(super) fn tick_items(
    game: &mut Game<'_>,
    round: &mut TickRound,
    original: impl FnOnce(&mut Game<'_>, &mut TickRound),
) {
    if game.native_authoritative() && game.world.attachments.has(&ACTIVE) {
        if game.level_pass.running == Some(true) {
            // This runs after scheduled block work and before the block
            // entity list, even when the world has no dropped items.
            super::create_port_portable_storage::tick_piston_docks(game);
        }
        // Create resolves these contacts after the whole level tick. Coarse
        // rotor boxes in the ordinary item move would bounce it prematurely.
        with_collision_filter((None, true), || original(game, round));
    } else {
        original(game, round);
    }
}

pub(super) fn tick_post(game: &mut Game<'_>) {
    if game.level_pass.running != Some(true)
        || game.dropped.is_empty()
        || !game.world.attachments.has(&ACTIVE)
    {
        return;
    }
    let mut carriers: Vec<_> = game
        .world
        .chunks
        .values()
        .filter_map(|chunk| read(chunk).ok())
        .flat_map(|records| records.into_owned())
        .filter_map(Carrier::new)
        .collect();
    if carriers.is_empty() {
        return;
    }
    carriers.sort_unstable_by_key(|carrier| carrier.record.controller);
    let ticking = game.entity_ticking_area();
    for index in 0..game.dropped.len() {
        let item = &game.dropped[index];
        if !ticking(
            item.position.x.floor() as i32,
            item.position.z.floor() as i32,
        ) {
            continue;
        }
        let reach = Vec3::new(
            item.velocity.x.abs(),
            item.velocity.y.abs(),
            item.velocity.z.abs(),
        );
        let bounds = item.bounds().inflate(reach);
        if let Some(result) = carriers
            .iter()
            .filter(|carrier| carrier.bounds.intersects(bounds))
            .find_map(|carrier| contact(game, item, carrier))
        {
            let item = &mut game.dropped[index];
            item.needs_sync |= item.position != result.position || item.velocity != result.velocity;
            item.position = result.position;
            item.velocity = result.velocity;
            item.on_ground |= result.surface;
            if result.bounced {
                game.with_level(|_, level, _| {
                    level.native_play_sound(
                        "minecraft:block.slime_block.fall",
                        result.position.components(),
                        4,
                        0.5,
                        1.0,
                    );
                });
            }
        }
    }
}

fn vector([x, y, z]: [f64; 3]) -> Vec3 {
    Vec3::new(x, y, z)
}

fn pivot(record: &Record) -> Vec3 {
    vector(record.anchor.map(|p| f64::from(p) + 0.5))
}

fn contact_point_motion(record: &Record, position: Vec3) -> Vec3 {
    let relative = position.subtract(pivot(record));
    let local = rotate(relative.components(), -record.previous_angle, Axis::Y);
    vector(rotate(local, record.angle, Axis::Y)).subtract(relative)
}

pub(super) fn upright_slime_bounce(
    record: &Record,
    position: Vec3,
    bounds: Aabb,
    velocity: Vec3,
    response: RotaryContact,
) -> Option<Vec3> {
    if (response.separation == [0.0; 3] && response.impact_fraction == 1.0)
        || response.normal == [0.0; 3]
        || response.location == [0.0; 3]
    {
        return None;
    }
    let mut hit = position
        .add_vector(bounds.center())
        .scale(0.5)
        .add_vector(vector(response.location));
    if response.impact_fraction != 1.0 {
        hit.y += velocity.y * response.impact_fraction;
    }
    let offset = hit.subtract(pivot(record));
    let local = rotate(offset.components(), -record.previous_angle, Axis::Y)
        .map(|coordinate| (coordinate + 0.5).floor() as i32);
    if !record
        .blocks
        .iter()
        .any(|(pos, state)| *pos == local && state.name == SLIME_BLOCK)
    {
        return None;
    }
    let normal = vector(response.normal);
    let incoming = velocity.subtract(contact_point_motion(record, position));
    let delta = normal.scale(0.8 * 2.0 * incoming.dot(normal));
    (delta.length_squared() >= f64::from(0.1_f32)).then(|| velocity.subtract(delta))
}

fn contact(game: &Game<'_>, item: &ItemEntity, carrier: &Carrier) -> Option<Contact> {
    let bounds = item.bounds();
    let body = ContactBox {
        min: bounds.min_position().components(),
        max: bounds.max_position().components(),
    };
    let record = &carrier.record;
    let response = rotary_contact(
        Axis::Y,
        record.anchor,
        record.angle,
        body,
        item.velocity.components(),
        carrier.shapes().iter().copied(),
        0.0,
    );
    if (!response.surface && response.separation == [0.0; 3] && response.impact_fraction == 1.0)
        || item.inside_block(&game.world, game.collision)
    {
        return None;
    }
    if carrier.has_slime
        && let Some(velocity) =
            upright_slime_bounce(record, item.position, bounds, item.velocity, response)
    {
        return Some(Contact {
            position: item.position,
            velocity,
            surface: false,
            bounced: true,
        });
    }
    if !response.surface && response.separation == [0.0; 3] {
        return None;
    }
    let entities = carrier.obstacles.get_or_init(|| {
        with_collision_filter((Some(record.controller), false), || {
            game.item_entity_collisions()
        })
    });
    let mut world = EntityCollisions {
        blocks: SceneCollisions {
            world: &game.world,
            binding: game.collision,
            subject: None,
        },
        entities,
        border: Some((game.border.geometry(), [item.position.x, item.position.z])),
    };
    let mut position = item.position;
    let context = CollisionContext::for_entity(
        CollisionEntity {
            identity: EntityIdentity(u64::from(item.id)),
            kind: EntityContextKind::Item,
            y: position.y,
            descending: false,
            main_hand: None,
        },
        false,
    );
    let wanted = vector(response.separation);
    let allowed = world
        .resolve_with_context(bounds, wanted, 0.0, false, context)
        .ok()?;
    position = position.add_vector(allowed);

    let mut velocity = item.velocity.components();
    velocity[1] *= response.impact_fraction;
    for (i, threshold) in [1.0 / 128.0, 0.0, 1.0 / 128.0].into_iter().enumerate() {
        if response.separation[i].abs() > threshold && velocity[i] * response.separation[i] < 0.0 {
            velocity[i] = 0.0;
        }
    }
    if response.surface {
        let transfer = contact_point_motion(record, position);
        let allowed = world
            .resolve_with_context(bounds.move_by(allowed), transfer, 0.0, false, context)
            .ok()?;
        position = position.add_vector(allowed);
        velocity[0] *= 0.5;
        velocity[2] *= 0.5;
    }
    Some(Contact {
        position,
        velocity: vector(velocity),
        surface: response.surface,
        bounced: false,
    })
}
