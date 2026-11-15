// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT

// Complete ordinary tanks on a vertical Mechanical Bearing or Rope Pulley.
use super::{
    Game, create_port_contraption as contraption, create_port_fluid_codec as fluids,
    create_port_fluid_tank as tank, native_world_draw::NativeWorldDraw,
};
use crate::containers::BlockEntity;
use create_engine::{
    contraption::QuarterTurn,
    fluid_tank::{BLOCK_CAPACITY, Pos, Tank},
    placement::Direction,
};
use glam::{DVec3, Vec3};
use horizon_client::block_entity_render::vertex_light;
use horizon_client_render::create_contraption_scene::{
    MAX_BLOCKS, MAX_RECORDS, Record, StrokeKind, TANK_STORAGE_KEY,
};
use horizon_world::{
    attachments::{
        AttachmentCodec, AttachmentError, AttachmentType, Attachments, Holder,
        create_contraption_attachment::decoded,
    },
    chunk::BlockState,
    nbt::{Compound, Tag},
    registry::BlockStateId,
};
use std::collections::{BTreeMap, BTreeSet};

#[derive(Clone)]
pub(super) struct Cargo(Vec<tank::Record>);
type Store = BTreeMap<Pos, Cargo>;

const TANKS: AttachmentType<Store> = AttachmentType {
    namespace: "create",
    name: TANK_STORAGE_KEY,
    default: Store::new,
    codec: Some(AttachmentCodec { encode, decode }),
    copy_on_death: false,
    // Only typed renderable fluid, in the same update as its owner's scene.
    sync: true,
};

fn add(left: Pos, right: Pos) -> Option<Pos> {
    Some([
        left[0].checked_add(right[0])?,
        left[1].checked_add(right[1])?,
        left[2].checked_add(right[2])?,
    ])
}

fn matching_footprint(game: &Game<'_>, cargo: &Cargo, blocks: &[(Pos, BlockState)]) -> bool {
    let expected: BTreeMap<_, _> = cargo
        .0
        .iter()
        .flat_map(|record| record.tank.parts().map(move |pos| (pos, record)))
        .collect();
    let mut found = BTreeSet::new();
    for (pos, block) in blocks.iter().filter(|(_, state)| state.name == tank::BLOCK) {
        let Some(record) = expected.get(pos) else {
            return false;
        };
        let Some(state) = tank::mounted_state(game, record, *pos) else {
            return false;
        };
        if !found.insert(*pos) || game.pack.assets.registry.state(state) != Some(block) {
            return false;
        }
    }
    found.len() == expected.len()
}

pub(super) fn capture(
    game: &Game<'_>,
    anchor: Pos,
    blocks: &[(Pos, BlockState)],
) -> Result<Cargo, AttachmentError> {
    let mut roots = BTreeSet::new();
    let mut result = Cargo(Vec::new());
    for (local, block) in blocks.iter().filter(|(_, state)| state.name == tank::BLOCK) {
        let source = add(anchor, *local).ok_or(AttachmentError::Encode)?;
        let mut record = tank::endpoint(game, source).ok_or(AttachmentError::Encode)?;
        let absolute = record.tank;
        if game
            .pack
            .assets
            .registry
            .state(contraption::state(game, source))
            != Some(block)
        {
            return Err(AttachmentError::Encode);
        }
        if !roots.insert(absolute.root) {
            continue;
        }
        if !tank::canonical_mount(game, &record)
            || !absolute
                .parts()
                .all(|part| contraption::column(part) == contraption::column(anchor))
        {
            return Err(AttachmentError::Encode);
        }
        let local = std::array::from_fn(|axis| absolute.root[axis] - anchor[axis]);
        record.tank =
            Tank::new(local, absolute.width(), absolute.height()).ok_or(AttachmentError::Encode)?;
        result.0.push(record);
    }
    (result.0.is_empty() || matching_footprint(game, &result, blocks))
        .then_some(result)
        .ok_or(AttachmentError::Encode)
}

fn private_map(
    game: &mut Game<'_>,
    key: [i32; 2],
) -> Result<(Store, Attachments), AttachmentError> {
    let attachments = game.attachment_map_quiet(Holder::Chunk(key))?;
    let store = attachments.get_existing(&TANKS)?.unwrap_or_default();
    Ok((store, attachments.clone()))
}

fn commit(
    game: &mut Game<'_>,
    key: [i32; 2],
    store: Store,
    before: Attachments,
    apply: impl FnOnce(&mut Game<'_>) -> bool,
) -> bool {
    let Ok(map) = game.attachment_map_quiet(Holder::Chunk(key)) else {
        return false;
    };
    let changed = if store.is_empty() {
        map.remove(&TANKS).map(|_| ())
    } else {
        map.set(&TANKS, store)
    };
    if changed.is_ok() && apply(game) {
        return true;
    }
    if let Ok(map) = game.attachment_map_quiet(Holder::Chunk(key)) {
        *map = before;
    }
    false
}

pub(super) fn commit_capture(
    game: &mut Game<'_>,
    key: [i32; 2],
    controller: Pos,
    cargo: Cargo,
    apply: impl FnOnce(&mut Game<'_>) -> bool,
) -> bool {
    if cargo.0.is_empty() {
        return apply(game);
    }
    let Ok((mut store, before)) = private_map(game, key) else {
        return false;
    };
    if store.insert(controller, cargo).is_some() {
        return false;
    }
    commit(game, key, store, before, apply)
}

pub(super) struct Landing {
    store: Store,
    before: Attachments,
    destinations: BTreeMap<Pos, (BlockStateId, BlockEntity)>,
}

impl Landing {
    pub(super) fn state(&self, pos: Pos) -> Option<BlockStateId> {
        self.destinations.get(&pos).map(|(state, _)| *state)
    }
}

pub(super) fn prepare_landing(
    game: &mut Game<'_>,
    key: [i32; 2],
    record: &Record,
    origin: Pos,
    turn: QuarterTurn,
) -> Result<Option<Landing>, AttachmentError> {
    if !record
        .blocks
        .iter()
        .any(|(_, block)| block.name == tank::BLOCK)
    {
        return Ok(None);
    }
    if record.axis != 1
        || record.return_home
        || record.clock_hand.is_some()
        || (record.stroke.is_some()
            && (record.stroke_kind() != Some(StrokeKind::RopePulley)
                || turn != QuarterTurn::IDENTITY))
    {
        return Err(AttachmentError::Decode);
    }
    let (mut store, before) = private_map(game, key)?;
    let cargo = store
        .remove(&record.controller)
        .ok_or(AttachmentError::Decode)?;
    if !matching_footprint(game, &cargo, &record.blocks) {
        return Err(AttachmentError::Decode);
    }
    let mut destinations = BTreeMap::new();
    for mut mounted in cargo.0 {
        let local = mounted.tank;
        let opposite = add(local.root, [local.width() - 1, 0, local.width() - 1])
            .ok_or(AttachmentError::Decode)?;
        let a = turn
            .place(origin, local.root)
            .ok_or(AttachmentError::Encode)?;
        let b = turn
            .place(origin, opposite)
            .ok_or(AttachmentError::Encode)?;
        let root = std::array::from_fn(|axis| a[axis].min(b[axis]));
        let placed =
            Tank::new(root, local.width(), local.height()).ok_or(AttachmentError::Encode)?;
        mounted.tank = placed;
        for pos in placed.parts() {
            if contraption::column(pos) != key
                || !contraption::resident(game, pos)
                || game
                    .world
                    .block_entities
                    .contains_key(&(pos[0], pos[1], pos[2]))
                || Direction::ALL.into_iter().any(|face| {
                    add(pos, face.vector()).is_none_or(|neighbor| {
                        !game.world.loaded(neighbor[0], neighbor[2])
                            || game.native_block(neighbor) == tank::BLOCK
                    })
                })
            {
                return Err(AttachmentError::Encode);
            }
            let state = tank::mounted_state(game, &mounted, pos).ok_or(AttachmentError::Encode)?;
            let Some(BlockEntity::Mod(mut entity)) = game.new_block_entity_for_state(state) else {
                return Err(AttachmentError::Encode);
            };
            entity.nbt = tank::mounted_nbt(&mounted, pos).ok_or(AttachmentError::Encode)?;
            if destinations
                .insert(pos, (state, BlockEntity::Mod(entity)))
                .is_some()
            {
                return Err(AttachmentError::Encode);
            }
        }
    }
    Ok(Some(Landing {
        store,
        before,
        destinations,
    }))
}

pub(super) fn commit_landing(
    game: &mut Game<'_>,
    key: [i32; 2],
    landing: Option<Landing>,
    apply: impl FnOnce(&mut Game<'_>) -> bool,
) -> bool {
    let Some(landing) = landing else {
        return apply(game);
    };
    if !commit(game, key, landing.store, landing.before, apply) {
        return false;
    }
    for (pos, (_, entity)) in landing.destinations {
        game.world
            .block_entities
            .insert((pos[0], pos[1], pos[2]), entity);
        game.native_block_entity_sync(pos);
        game.native_update_output_neighbors(game.dim.id(), pos);
    }
    true
}

pub(super) fn has_storage(map: &Attachments) -> bool {
    map.has(&TANKS)
}

pub(super) fn cache_mirror(map: &mut Attachments) {
    let _ = map.get_existing(&TANKS);
}

pub(super) fn draw_mounted(
    game: &Game<'_>,
    map: &Attachments,
    controller: Pos,
    draw: &mut NativeWorldDraw,
) {
    let Some(cargo) = decoded(map, &TANKS).and_then(|store| store.get(&controller)) else {
        return;
    };
    let previous = draw.light;
    for record in cargo
        .0
        .iter()
        .filter(|record| record.window && record.fluid.is_some())
    {
        draw.push();
        draw.translate(record.tank.root.map(|axis| axis as f32));
        // Java BlockEntityRenderHelper samples the transformed controller's centre.
        let [x, y, z] = (DVec3::from_array(draw.camera)
            + draw.pose().transform_point3(Vec3::splat(0.5)).as_dvec3())
        .floor()
        .to_array()
        .map(|axis| axis as i32);
        draw.light = vertex_light(game.world.light(x, y, z));
        tank::draw_fluid(game, record, record.fraction(), draw);
        draw.pop();
    }
    draw.light = previous;
}

fn encode(store: &Store) -> Result<Compound, AttachmentError> {
    if store.len() > MAX_RECORDS {
        return Err(AttachmentError::Encode);
    }
    let mut entries = Vec::new();
    for (owner, cargo) in store {
        if !valid_cargo(cargo) {
            return Err(AttachmentError::Encode);
        }
        for record in &cargo.0 {
            let mut fields = Compound::from([
                // Keep the first sidecar's owner key for existing saves.
                ("Bearing".into(), Tag::IntArray(owner.to_vec())),
                (
                    "Controller".into(),
                    Tag::IntArray(record.tank.root.to_vec()),
                ),
                ("Size".into(), Tag::Int(record.tank.width())),
                ("Height".into(), Tag::Int(record.tank.height())),
                ("Window".into(), Tag::Byte(i8::from(record.window))),
            ]);
            if record.part_capacity != BLOCK_CAPACITY {
                fields.insert("PartCapacity".into(), Tag::Int(record.part_capacity as i32));
            }
            if let Some(fluid) = &record.fluid {
                fields.insert(
                    "TankContent".into(),
                    fluids::write_content(Some(fluid), tank::SAVED_AMOUNT_LIMIT)
                        .map_err(|_| AttachmentError::Encode)?,
                );
            }
            entries.push(Tag::Compound(fields));
        }
    }
    Ok(Compound::from([("Tanks".into(), Tag::List(entries))]))
}

fn valid_cargo(cargo: &Cargo) -> bool {
    let mut seen = BTreeSet::new();
    !cargo.0.is_empty()
        && cargo
            .0
            .iter()
            .flat_map(|record| record.tank.parts())
            .all(|pos| {
                pos.into_iter()
                    .all(|coordinate| coordinate.unsigned_abs() <= 15)
                    && seen.insert(pos)
            })
        && seen.len() <= MAX_BLOCKS
}

fn decode(saved: &Compound) -> Result<Store, AttachmentError> {
    let Some(Tag::List(entries)) = saved.get(&"Tanks".into()) else {
        return Err(AttachmentError::Decode);
    };
    if saved.len() != 1 || entries.len() > MAX_RECORDS * MAX_BLOCKS {
        return Err(AttachmentError::Decode);
    }
    let mut store = Store::new();
    let position = |entry: &Tag, key| match entry.get(key) {
        Some(Tag::IntArray(values)) => values.as_slice().try_into().ok(),
        _ => None,
    };
    for entry in entries {
        let (
            Tag::Compound(fields),
            Some(owner),
            Some(root),
            Some(Tag::Int(width)),
            Some(Tag::Int(height)),
            Some(Tag::Byte(window @ (0 | 1))),
        ) = (
            entry,
            position(entry, "Bearing"),
            position(entry, "Controller"),
            entry.get("Size"),
            entry.get("Height"),
            entry.get("Window"),
        )
        else {
            return Err(AttachmentError::Decode);
        };
        let content = entry.get("TankContent");
        let capacity = entry.get("PartCapacity");
        if fields.len() != 5 + usize::from(content.is_some()) + usize::from(capacity.is_some()) {
            return Err(AttachmentError::Decode);
        }
        let tank = Tank::new(root, *width, *height).ok_or(AttachmentError::Decode)?;
        let fluid = match content {
            None => None, // The older empty-tank sidecar has the same key.
            Some(content) => Some(
                fluids::read_content(Some(content), tank::SAVED_AMOUNT_LIMIT)
                    .map_err(|_| AttachmentError::Decode)?
                    .filter(|fluid| fluid.key.components.is_empty())
                    .ok_or(AttachmentError::Decode)?,
            ),
        };
        store
            .entry(owner)
            .or_insert_with(|| Cargo(Vec::new()))
            .0
            .push(tank::Record {
                tank,
                part_capacity: tank::read_capacity(capacity).ok_or(AttachmentError::Decode)?,
                window: *window != 0,
                fluid,
            });
    }
    if store.len() > MAX_RECORDS || !store.values().all(valid_cargo) {
        return Err(AttachmentError::Decode);
    }
    Ok(store)
}
