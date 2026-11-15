// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT

use std::{
    cell::{Cell, RefCell},
    collections::BTreeMap,
};

use super::{
    Game, create_port_contraption::mirror_sync,
    create_port_contraption_item_motion::{SLIME_BLOCK, upright_slime_bounce},
};
use create_engine::{
    contraption::{
        Rotation, cargo_bounds,
        contact::{
            ContactBox, linear_face_separation, linear_overlap_response, linear_top_motion,
            rotary_top_motion,
        },
        rotary_contact::{RotaryContact, rotary_contact},
    },
    kinetics::Axis,
};
use horizon_client::collisions::{EntityCollisions, LookupCollisions, SceneCollisions};
use horizon_client_render::create_contraption_scene::{
    KEY, POSE_KEY, Pos, Record, dry_slab_type, dry_straight_stair, full_cube_payload,
    payload_collision_shape, read, upright_side_payload,
};
use horizon_core::geometry::{Aabb, Vec3};
use horizon_world::{
    attachments::Holder,
    chunk::BlockState,
    collision_context::{CollisionContext, CollisionEntity, CollisionItem, EntityContextKind},
    entity_move::MovementRecord,
    entity_obstruction::EntityIdentity,
};

#[derive(Clone, Copy)]
struct ContactClip {
    excluded_controller: Option<Pos>,
}

thread_local! {
    static CONTACT_CLIP: Cell<Option<ContactClip>> = const { Cell::new(None) };
    static PENDING: RefCell<Vec<Transition>> = const { RefCell::new(Vec::new()) };
    static RIDER_ROTORS: RefCell<BTreeMap<Pos, RotorContact>> = const { RefCell::new(BTreeMap::new()) };
    static DEFERRED: RefCell<Option<DeferredContact>> = const { RefCell::new(None) };
    static INTERPOLATION: Cell<Option<Interpolation>> = const { Cell::new(None) };
}

#[derive(Clone, Copy)]
struct Interpolation {
    tick: u64,
    before: Vec3,
    carried: Vec3,
}

struct Transition {
    tick: u64,
    player: Vec3,
    column: (i32, i32),
    previous: Vec<Record>,
    current: Vec<Record>,
}

struct DeferredContact {
    tick: u64,
    before_move: Vec3,
    rotors: Vec<RotorContact>,
}

#[derive(Clone)]
struct RotorContact {
    from: f32,
    record: Record,
    bounds: Option<Aabb>,
}

impl RotorContact {
    fn new(record: Record, previous: Option<&Record>) -> Self {
        let from = previous
            .filter(|previous| {
                previous.same_geometry(&record) && previous.angle == record.previous_angle
            })
            .map_or(record.angle, |previous| previous.angle);
        Self {
            from,
            bounds: Self::bounds(&record),
            record,
        }
    }

    fn begin_tick(&mut self) {
        // In the absence of a new pose, keep the same collision hull without
        // replaying the last transfer.
        self.from = self.record.angle;
    }

    fn receive(&mut self, record: Record, previous: Option<&Record>) {
        let same = self.record.same_geometry(&record);
        let duplicate = same && self.record.angle == record.angle;
        let continuous = same
            && previous.is_some_and(|previous| {
                self.record.angle == previous.angle
                    && previous.angle == record.previous_angle
                    && previous.same_geometry(&record)
            });
        if !duplicate && !continuous {
            // A replacement snapshot or a discontinuity supplies support at
            // its new pose. It supplies no trustworthy transfer path.
            self.from = record.angle;
        }
        if !same {
            self.bounds = Self::bounds(&record);
        }
        self.record = record;
    }

    fn bounds(record: &Record) -> Option<Aabb> {
        let axis = [Axis::X, Axis::Y, Axis::Z][record.axis];
        let [min, max] = cargo_bounds::local_bounds(
            record.blocks.iter().map(|(local, _)| *local),
            cargo_bounds::Motion::Rotary(axis),
        )?;
        let world = |point: [f64; 3]| {
            let [x, y, z] = std::array::from_fn(|i| point[i] + f64::from(record.anchor[i]));
            Vec3::new(x, y, z)
        };
        Some(
            Aabb::new(world(min), world(max))
                .inflate(Vec3::new(2.0, 2.0, 2.0))
                .expand_towards(Vec3::new(0.0, 32.0, 0.0)),
        )
    }
}

enum Contact {
    Carry([f64; 3], Option<Pos>),
    Push([f64; 3], Option<Pos>),
    Bounce(Vec3),
    Tilted {
        response: RotaryContact,
        transforms: Option<(Rotation, Rotation)>,
        controller: Pos,
    },
}

pub(super) fn reset() {
    PENDING.with(|queue| queue.borrow_mut().clear());
    RIDER_ROTORS.with(|rotors| rotors.borrow_mut().clear());
    DEFERRED.set(None);
    INTERPOLATION.set(None);
}

fn local_contact_player<'a>(
    game: &'a Game<'_>,
) -> Option<&'a horizon_client::motion::PlayerMotion> {
    game.player.as_ref().filter(|player| {
        game.remote.is_some()
            && game.riding.is_none()
            && game.sleeping.is_none()
            && !player.spectator
            && !player.flying
            && player.health.health() > 0.0
    })
}

pub(super) fn player_collision_filter(game: &Game<'_>) -> (Option<Pos>, Option<Aabb>) {
    if let Some(clip) = CONTACT_CLIP.get() {
        // The pose filter applies to the ordinary movement query. Explicit
        // contact motion still collides with every neighboring rotor.
        return (clip.excluded_controller, None);
    }
    let standing = local_contact_player(game).map(|player| {
        horizon_client::pose::Pose::Standing
            .dimensions(player.scale)
            .bounds(player.position)
    });
    (None, standing)
}

pub(super) fn suppress_ordinary_collision(game: &Game<'_>, record: &Record) -> bool {
    if game.remote.is_none()
        || CONTACT_CLIP.get().is_some()
        || (record.axis == Axis::Y.index() && !game.clock.runs_normally())
    {
        return false;
    }
    DEFERRED.with(|deferred| {
        deferred.borrow().as_ref().is_some_and(|deferred| {
            deferred.tick == game.ticks
                && deferred
                    .rotors
                    .binary_search_by_key(&record.controller, |rotor| rotor.record.controller)
                    .ok()
                    .is_some_and(|index| {
                        let current = &deferred.rotors[index].record;
                        current.angle == record.angle && current.same_geometry(record)
                    })
        })
    })
}

fn exact_rider_rotor(record: &Record) -> bool {
    record.stroke.is_none()
        && record.clock_hand.is_none()
        && !record.return_home
        && if record.axis == Axis::Y.index() {
            // The centered Slime payload uses exact impact response without
            // changing contact on the larger standing-platform path.
            matches!(record.blocks.as_ref(), [([0, 0, 0], state)] if state.name == SLIME_BLOCK)
        } else {
            record
                .blocks
                .iter()
                .all(|(_, state)| full_cube_payload(state))
        }
}

fn entity_collisions(game: &Game<'_>, excluded_controller: Option<Pos>) -> Vec<Aabb> {
    // The ordinary collision hook also supplies conservative moving geometry.
    // OBB separation must leave its own collider out, just like Java's entity
    // query. The short-lived guard affects only this collision query.
    struct Restore(Option<ContactClip>);
    impl Drop for Restore {
        fn drop(&mut self) {
            CONTACT_CLIP.set(self.0);
        }
    }
    let _restore = Restore(CONTACT_CLIP.replace(Some(ContactClip {
        excluded_controller,
    })));
    game.player_entity_collisions()
}

pub(super) fn sync(game: &mut Game<'_>, data: &[u8]) {
    let previous = previous_records(game, data);
    mirror_sync(game, data);
    if let Some((column, previous)) = previous
        && let Some(player) = local_contact_player(game)
        && let Some(current) = game
            .world
            .chunks
            .get(&column)
            .and_then(|chunk| read(chunk).ok())
    {
        PENDING.with(|queue| {
            queue.borrow_mut().push(Transition {
                tick: game.ticks,
                player: player.position,
                column,
                previous,
                current: current.into_owned(),
            });
        });
    }
}

pub(super) fn begin_tick(game: &mut Game<'_>) {
    let pending = PENDING.take();
    DEFERRED.set(None);
    let Some(before) = local_contact_player(game).map(|player| player.position) else {
        RIDER_ROTORS.with(|rotors| rotors.borrow_mut().clear());
        return;
    };
    let mut rotors = RIDER_ROTORS.take();
    for rotor in rotors.values_mut() {
        rotor.begin_tick();
    }
    for transition in pending {
        // A teleport, unload or disassembly can invalidate a buffered update.
        if transition.tick != game.ticks || transition.player != before {
            continue;
        }
        let Some(resident) = game
            .world
            .chunks
            .get(&transition.column)
            .and_then(|chunk| read(chunk).ok())
        else {
            continue;
        };
        let current = transition
            .current
            .iter()
            .filter(|record| resident.iter().any(|latest| latest.same_geometry(record)));
        let mut early = Vec::new();
        for record in current {
            if !exact_rider_rotor(record)
                || (record.previous_angle == record.angle
                    && !rotors.contains_key(&record.controller))
            {
                early.push(record.clone());
                continue;
            }
            let previous = transition
                .previous
                .iter()
                .find(|previous| previous.same_geometry(record));
            match rotors.entry(record.controller) {
                std::collections::btree_map::Entry::Occupied(mut entry) => {
                    entry.get_mut().receive(record.clone(), previous);
                }
                std::collections::btree_map::Entry::Vacant(entry) => {
                    entry.insert(RotorContact::new(record.clone(), previous));
                }
            }
        }
        if !early.is_empty() {
            carry(game, &transition.previous, &early, false);
        }
    }
    // Snapshots and unloads need not enqueue a move. Revalidate the actual
    // loaded geometry before replacing coarse collision for this tick.
    rotors.retain(|controller, rotor| {
        let column = (controller[0] >> 4, controller[2] >> 4);
        let Some(resident) = game
            .world
            .chunks
            .get(&column)
            .and_then(|chunk| read(chunk).ok())
        else {
            return false;
        };
        let Some(latest) = resident
            .iter()
            .find(|record| record.controller == *controller)
        else {
            return false;
        };
        if !rotor.record.same_geometry(latest) && !exact_rider_rotor(latest) {
            return false;
        }
        rotor.receive(latest.clone(), None);
        true
    });
    let Some(before_move) = local_contact_player(game).map(|player| player.position) else {
        return;
    };
    let tick = game.ticks + 1;
    if !rotors.is_empty() {
        // Java resolves active rotor contacts after the normal local player
        // move. Leave these shapes out of its ordinary terrain collision.
        DEFERRED.set(Some(DeferredContact {
            tick,
            before_move,
            rotors: rotors.values().cloned().collect(),
        }));
    }
    RIDER_ROTORS.set(rotors);
    if before != before_move {
        INTERPOLATION.set(Some(Interpolation {
            tick,
            before,
            carried: before_move,
        }));
    }
}

pub(super) fn finish_tick(game: &mut Game<'_>) {
    if let Some(deferred) = DEFERRED.take()
        && deferred.tick == game.ticks
        && deferred.before_move == game.previous_position
        && local_contact_player(game).is_some()
    {
        for RotorContact {
            from,
            mut record,
            bounds,
        } in deferred.rotors
        {
            if record.axis == Axis::Y.index() && !game.clock.runs_normally() {
                continue;
            }
            if !bounds.is_some_and(|bounds| {
                game.player
                    .as_ref()
                    .is_some_and(|player| bounds.intersects(player.bounds()))
            }) {
                continue;
            }
            let mut previous = record.clone();
            previous.angle = from;
            record.previous_angle = from;
            carry(game, &[previous], &[record], true);
        }
    }
    if let Some(sample) = INTERPOLATION.take()
        && sample.tick == game.ticks
        && sample.carried == game.previous_position
        && local_contact_player(game).is_some()
    {
        // The normal player tick captured the post-contact position. Start
        // the camera/body interpolation before the carrier displacement too.
        game.previous_position = sample.before;
    }
}

fn previous_records(game: &Game<'_>, data: &[u8]) -> Option<((i32, i32), Vec<Record>)> {
    local_contact_player(game)?;
    let message = horizon_protocol::attachment_sync::decode(data).ok()?;
    let Holder::Chunk([x, z]) = message.holder else {
        return None;
    };
    if message.replace
        || !message.changes.iter().any(|change| {
            change.namespace == "create".into()
                && (change.name == KEY.into() || change.name == POSE_KEY.into())
                && change.value.is_some()
        })
    {
        return None;
    }
    let column = (x, z);
    let records = read(game.world.chunks.get(&column)?).ok()?.into_owned();
    Some((column, records))
}

fn carry(game: &mut Game<'_>, previous: &[Record], current: &[Record], post_move: bool) {
    let max_step = game
        .player
        .as_mut()
        .and_then(|player| player.attribute("minecraft:step_height").ok())
        .map_or(0.6, |step| step as f32);
    let Some(player) = &game.player else { return };
    let bounds = player.bounds();
    let feet = bounds.bottom_center().components();
    let size = bounds.size();
    let body = ContactBox {
        min: bounds.min_position().components(),
        max: bounds.max_position().components(),
    };
    let mut linear_body = body;
    if size.y > 1.0 {
        linear_body.max[1] -= 2.0 / 16.0;
    }
    // Preserve the existing priority of platform transfer and linear contact
    // when a nearby rotor also has a side overlap in this column.
    let mut side = None;
    let contact = current.iter().find_map(|record| {
        let before = previous
            .iter()
            .find(|before| before.same_geometry(record))?;
        let full_blocks = record
            .blocks
            .iter()
            .filter(|(_, state)| full_cube_payload(state))
            .map(|(local, _)| *local);
        let tops = || {
            payload_colliders(game, record, [0.0; 3], |state| {
                dry_slab_type(state).is_some() || dry_straight_stair(state)
            })
        };
        let half_extents = [size.x * 0.5, size.z * 0.5];
        // The last applied transform must match this update's predecessor.
        // Snapshots and duplicate updates never apply a second displacement.
        match (before.stroke, record.stroke) {
            (None, None)
                if record.axis == 1
                    && !post_move
                    && before.angle == record.previous_angle
                    && before.angle != record.angle =>
            {
                if player.ground.on_ground
                    && let Some(motion) = rotary_top_motion(
                        record.anchor,
                        [before.angle, record.angle],
                        tops(),
                        feet,
                        half_extents,
                    )
                {
                    // Create resolves this rotor's shape before moving the
                    // contact point through the ordinary world colliders.
                    return Some(Contact::Carry(motion, Some(record.controller)));
                }
                if side.is_some() || !upright_side_payload(record) {
                    return None;
                }
                let response = rotary_contact(
                    Axis::Y,
                    record.anchor,
                    record.angle,
                    body,
                    player.velocity.components(),
                    full_blocks.map(|block| ContactBox::cube(block.map(f64::from))),
                    max_step,
                );
                // Keep the existing path for support, lift and step-up. This
                // pass supplies only hard separation of the side of the body.
                if response.separation[1] == 0.0 && response.separation != [0.0; 3] {
                    side = Some(Contact::Push(response.separation, Some(record.controller)));
                }
                None
            }
            (None, None)
                if before.angle == record.previous_angle
                    && (before.angle != record.angle || post_move) =>
            {
                let axis = [Axis::X, Axis::Y, Axis::Z][record.axis];
                let response = rotary_contact(
                    axis,
                    record.anchor,
                    record.angle,
                    body,
                    player.velocity.components(),
                    payload_colliders(game, record, [0.0; 3], |_| true),
                    max_step,
                );
                if axis == Axis::Y
                    && !player.shift_key_down
                    && let Some(velocity) = upright_slime_bounce(
                        record,
                        player.position,
                        bounds,
                        player.velocity,
                        response,
                    )
                {
                    return Some(Contact::Bounce(velocity));
                }
                let transforms = if before.angle == record.angle {
                    None
                } else {
                    Some((
                        Rotation::new(record.anchor, axis, before.angle)?,
                        Rotation::new(record.anchor, axis, record.angle)?,
                    ))
                };
                (response.surface || response.separation != [0.0; 3]).then_some(Contact::Tilted {
                    response,
                    transforms,
                    controller: record.controller,
                })
            }
            (Some(previous), Some(current))
                if previous.offset == current.previous && previous.offset != current.offset =>
            {
                let previous_origin = before.origin_at(1.0);
                let current_origin = record.origin_at(1.0);
                if player.ground.on_ground
                    && let Some(motion) = linear_top_motion(
                        previous_origin,
                        current_origin,
                        tops(),
                        feet,
                        half_extents,
                    )
                {
                    return Some(Contact::Carry(motion, None));
                }
                if record.axis == 1 {
                    linear_face_separation(
                        previous_origin,
                        current_origin,
                        full_blocks,
                        linear_body.min,
                        linear_body.max,
                    )
                    .map(|motion| Contact::Push(motion, None))
                } else {
                    let shapes: Vec<_> =
                        payload_colliders(game, record, current_origin, |_| true).collect();
                    // Horizon's ordinary collision path establishes ground
                    // contact. A touching top needs no hard separation.
                    if !shapes.iter().any(|&shape| linear_body.penetrates(shape)) {
                        return None;
                    }
                    linear_overlap_response(linear_body, &shapes, max_step)
                        .map(|motion| Contact::Push(motion, None))
                }
            }
            _ => None,
        }
    });
    let Some(contact) = contact.or(side) else {
        return;
    };
    let (motion, separate, excluded) = match contact {
        Contact::Carry(motion, excluded) => (motion, false, excluded),
        Contact::Push(motion, excluded) => (motion, true, excluded),
        Contact::Bounce(velocity) => {
            let at = player.position.components();
            if let Some(player) = game.player.as_mut() {
                player.velocity = velocity;
            }
            game.audio.play("minecraft:block.slime_block.fall", Some(at), 0.5, 1.0);
            return;
        }
        Contact::Tilted {
            response,
            controller,
            ..
        } => (response.separation, true, Some(controller)),
    };
    let movement = Vec3::new(motion[0], motion[1], motion[2]);

    let entities = entity_collisions(game, excluded);
    let from = player.position;
    let context = CollisionContext::for_entity(
        CollisionEntity {
            identity: EntityIdentity(0),
            kind: EntityContextKind::Player,
            y: from.y,
            descending: player.shift_key_down,
            main_hand: Some(CollisionItem::EMPTY),
        },
        false,
    );
    let mut world = EntityCollisions {
        blocks: SceneCollisions {
            world: &game.world,
            binding: game.collision,
            subject: Some(player.powder_snow_subject()),
        },
        entities: &entities,
        border: player
            .border
            .as_ref()
            .map(|border| (border, [from.x, from.z])),
    };
    // Clip platform transfer against normal terrain and entity shapes while
    // retaining the rider's ground flag and own velocity.
    let Ok(mut allowed) = world.resolve_with_context(bounds, movement, 0.0, false, context) else {
        return;
    };
    if let Contact::Tilted {
        response,
        transforms: Some((previous, current)),
        ..
    } = contact
        && response.surface
    {
        let corrected = from.add_vector(allowed);
        let next = current.to_world(previous.to_local(corrected.components()));
        // Java clips the full transfer against terrain, then keeps the
        // rider's Y from separation and the in-tick impact response.
        let transfer = Vec3::new(
            next[0] - corrected.x,
            next[1] - corrected.y,
            next[2] - corrected.z,
        );
        let Ok(clipped) =
            world.resolve_with_context(bounds.move_by(allowed), transfer, 0.0, false, context)
        else {
            return;
        };
        allowed = allowed.add_vector(clipped.horizontal());
    }
    if let Some(player) = &mut game.player {
        let to = from.add_vector(allowed);
        if to != from {
            player.history.add(MovementRecord {
                from,
                to,
                original: Some(movement),
            });
        }
        if let Contact::Tilted { response, .. } = contact {
            player.velocity.y *= response.impact_fraction;
            if movement.y * player.velocity.y < 0.0 {
                player.velocity.y = 0.0;
            }
            if response.surface {
                player.fall_distance = 0.0;
                player.ground.on_ground = true;
            }
        }
        if separate {
            let response = movement.components();
            let mut velocity = player.velocity.components();
            for axis in [0, 2] {
                if response[axis].abs() > 1.0 / 128.0 && velocity[axis] * response[axis] < 0.0 {
                    velocity[axis] = 0.0;
                }
            }
            player.velocity = Vec3::new(velocity[0], velocity[1], velocity[2]);
        }
        player.position = to;
    }
}

fn payload_colliders<'a>(
    game: &'a Game<'_>,
    record: &'a Record,
    origin: [f64; 3],
    include_partial: impl Fn(&BlockState) -> bool + 'a,
) -> impl Iterator<Item = ContactBox> + 'a {
    record.blocks.iter().flat_map(move |(local, state)| {
        let at: [f64; 3] = std::array::from_fn(|i| origin[i] + f64::from(local[i]));
        let cube = full_cube_payload(state).then(|| ContactBox::cube(at));
        let shape = if cube.is_none() && include_partial(state) {
            let mut lookup = LookupCollisions {
                block: &|_, _, _| game.world.air,
                binding: game.collision,
            };
            payload_collision_shape(game.collision, &mut lookup, state, *local)
        } else {
            None
        };
        let mut index = 0;
        cube.into_iter().chain(std::iter::from_fn(move || {
            let bounds = shape.as_ref()?.boxes().get(index)?;
            index += 1;
            let min = bounds.min_position().components();
            let max = bounds.max_position().components();
            Some(ContactBox {
                min: std::array::from_fn(|i| at[i] + min[i]),
                max: std::array::from_fn(|i| at[i] + max[i]),
            })
        }))
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    fn sample(previous_angle: f32, angle: f32) -> Record {
        Record {
            controller: [0, 64, 0],
            anchor: [1, 64, 0],
            axis: 0,
            angle,
            previous_angle,
            rpm: 8.0,
            stalled: false,
            return_home: false,
            stroke: None,
            clock_hand: None,
            blocks: vec![(
                [0; 3],
                BlockState {
                    name: "minecraft:stone".into(),
                    properties: Default::default(),
                },
            )]
            .into(),
        }
    }

    #[test]
    fn absent_updates_keep_the_hull_without_replaying_displacement() {
        let initial = sample(0.0, 0.0);
        let mut rotor = RotorContact::new(sample(0.0, 2.4), Some(&initial));
        assert_eq!((rotor.from, rotor.record.angle), (0.0, 2.4));
        for _ in 0..3 {
            rotor.begin_tick();
            rotor.receive(sample(0.0, 2.4), None);
            assert_eq!((rotor.from, rotor.record.angle), (2.4, 2.4));
        }
    }

    #[test]
    fn one_client_tick_coalesces_contiguous_updates_and_ignores_duplicates() {
        let initial = sample(0.0, 0.0);
        let first = sample(0.0, 2.4);
        let second = sample(2.4, 4.8);
        let third = sample(4.8, 7.2);
        let mut rotor = RotorContact::new(first.clone(), Some(&initial));
        rotor.begin_tick();
        rotor.receive(second.clone(), Some(&first));
        rotor.receive(third.clone(), Some(&second));
        rotor.receive(third, None);
        assert_eq!((rotor.from, rotor.record.angle), (2.4, 7.2));
    }

    #[test]
    fn broken_predecessor_or_replaced_geometry_uses_only_the_new_hull() {
        let initial = sample(0.0, 0.0);
        let mut rotor = RotorContact::new(sample(0.0, 2.4), Some(&initial));
        let unknown = sample(4.8, 7.2);
        rotor.receive(unknown.clone(), Some(&sample(2.4, 4.8)));
        assert_eq!((rotor.from, rotor.record.angle), (7.2, 7.2));

        let mut replacement = sample(7.2, 9.6);
        replacement.anchor[0] += 1;
        rotor.receive(replacement.clone(), Some(&unknown));
        assert_eq!((rotor.from, rotor.record.angle), (9.6, 9.6));
        let mut following = sample(9.6, 12.0);
        following.anchor = replacement.anchor;
        rotor.receive(following, Some(&replacement));
        assert_eq!((rotor.from, rotor.record.angle), (9.6, 12.0));
    }
}
