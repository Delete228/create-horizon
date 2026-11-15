// Copyright (c) The Create Team / The Creators of Create
// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT

//! FluidTankBlock and FluidTankBlockEntity.writeSafe, Create 6.0.10.

use super::{BlockState, Compound, Issue, Mirror, Options, PlannedBlock, Schematic, Tag};
use std::collections::BTreeMap;

pub(super) const BLOCK: &str = "create:fluid_tank";
type Pos = [i32; 3];

/// A validated static footprint in transformed schematic coordinates.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct Tank {
    pub root: Pos,
    pub width: i32,
    pub height: i32,
}

impl Tank {
    fn new(root: Pos, width: i32, height: i32) -> Option<Self> {
        // Create 6.0.10's default tank config and hard-coded width cap.
        ((1..=3).contains(&width) && (1..=32).contains(&height)).then_some(Self {
            root,
            width,
            height,
        })
    }

    fn parts(self) -> impl Iterator<Item = Pos> {
        let [x, y, z] = self.root;
        (y..y + self.height).flat_map(move |y| {
            (x..x + self.width).flat_map(move |x| (z..z + self.width).map(move |z| [x, y, z]))
        })
    }

    fn single(self) -> bool {
        self.width == 1 && self.height == 1
    }
}

pub(super) fn validate_state(state: &BlockState) -> Result<(), String> {
    let property = |key| state.properties.get(key).map(String::as_str);
    if !["top", "bottom"]
        .into_iter()
        .all(|key| matches!(property(key), Some("true" | "false")))
        || !matches!(
            property("shape"),
            Some("plain" | "window" | "window_nw" | "window_ne" | "window_sw" | "window_se")
        )
    {
        return Err("a schematic Fluid Tank requires explicit top, bottom and shape".into());
    }
    Ok(())
}

pub(super) fn transform_shape<'a>(shape: &'a str, options: &Options) -> &'a str {
    // FluidTankBlock.mirror is applied before FluidTankBlock.rotate. The
    // corner labels are clockwise, starting at the northwest corner.
    let corners = ["window_nw", "window_ne", "window_se", "window_sw"];
    let Some(index) = corners.iter().position(|&corner| corner == shape) else {
        return shape;
    };
    let mirrored = match options.mirror {
        Mirror::None => index,
        Mirror::LeftRight => 3 - index,
        Mirror::FrontBack => index ^ 1,
    };
    corners[(mirrored + usize::from(options.quarter_turns)) % corners.len()]
}

fn position(raw: &Compound, key: &str) -> Option<Pos> {
    match raw.get(key) {
        Some(Tag::IntArray(values)) => values.as_slice().try_into().ok(),
        _ => None,
    }
}

pub(super) fn validate_data(raw: &Compound) -> Result<(), String> {
    let declaration = (raw.get("Size"), raw.get("Height"), raw.get("Window"));
    match declaration {
        (Some(Tag::Int(width)), Some(Tag::Int(height)), Some(Tag::Byte(0 | 1)))
            if Tank::new([0; 3], *width, *height).is_some() && !raw.contains_key("Controller") => {}
        (None, None, None) if !raw.contains_key("TankContent") => {}
        _ => return Err("invalid Fluid Tank controller dimensions or Window".into()),
    }
    if ["Controller", "LastKnownPos"]
        .into_iter()
        .any(|key| raw.contains_key(key) && position(raw, key).is_none())
        || ["TankContent", "Boiler"]
            .into_iter()
            .any(|key| raw.get(key).is_some_and(|tag| tag.as_compound().is_none()))
        || raw
            .get("components")
            .is_some_and(|tag| !matches!(tag, Tag::Compound(comp) if comp.is_empty()))
        || raw
            .get("Luminosity")
            .is_some_and(|tag| !matches!(tag, Tag::Int(0..=15)))
        || raw
            .get("Uninitialized")
            .is_some_and(|tag| !matches!(tag, Tag::Byte(0 | 1)))
    {
        return Err("invalid Fluid Tank source metadata".into());
    }
    Ok(())
}

fn matches_geometry(tank: Tank, pos: Pos, window: bool, state: &BlockState) -> bool {
    let [x, y, z] = std::array::from_fn(|axis| pos[axis] - tank.root[axis]);
    let shape = match (window, tank.width, x, z) {
        (true, 1, _, _) => "window",
        (true, 2, 0, 0) => "window_nw",
        (true, 2, 1, 0) => "window_ne",
        (true, 2, 0, 1) => "window_sw",
        (true, 2, 1, 1) => "window_se",
        (true, 3, x, z) if (x - z).abs() == 1 => "window",
        _ => "plain",
    };
    state.properties["shape"] == shape
        && (state.properties["top"] == "true") == (y == tank.height - 1)
        && (state.properties["bottom"] == "true") == (y == 0)
}

fn check_links(source: &BTreeMap<Pos, (&BlockState, Option<&Compound>)>, tank: Tank) -> bool {
    // Original StructureTemplate exports world-coordinate links. Use those
    // only to verify source ownership, then regenerate links at the destination.
    let source_root = source[&tank.root]
        .1
        .and_then(|raw| position(raw, "LastKnownPos"))
        .or_else(|| {
            tank.parts()
                .filter_map(|pos| source[&pos].1)
                .find_map(|raw| position(raw, "Controller"))
        });
    tank.parts().all(|pos| {
        let Some(raw) = source[&pos].1 else {
            return pos == tank.root && tank.single();
        };
        if pos != tank.root && raw.contains_key("Size") {
            return false;
        }
        if position(raw, "Controller").is_some_and(|controller| Some(controller) != source_root) {
            return false;
        }
        match (source_root, position(raw, "LastKnownPos")) {
            (Some(root), Some(known)) => (0..3).all(|axis| {
                i64::from(known[axis]) - i64::from(root[axis])
                    == i64::from(pos[axis]) - i64::from(tank.root[axis])
            }),
            _ => true,
        }
    })
}

pub(super) fn prepare(
    schematic: &Schematic,
    blocks: &mut [(bool, PlannedBlock)],
    options: &Options,
) -> Result<BTreeMap<Pos, Tank>, Vec<Issue>> {
    let source: BTreeMap<_, _> = schematic
        .blocks
        .iter()
        .filter_map(|block| {
            let state = schematic.palettes[0].get(block.state_index)?;
            (state.name == BLOCK)
                .then_some((block.relative_pos, (state, block.block_entity.as_ref())))
        })
        .collect();
    let mut occupied = BTreeMap::new();
    let mut issues = Vec::new();
    let mut fail = |pos, message: &str| {
        issues.push(Issue {
            path: "blocks".into(),
            relative_pos: Some(pos),
            message: message.into(),
        })
    };
    let transform = |pos| super::transform_position(pos, options);
    for (&root, &(state, raw)) in &source {
        let (tank, window) = match raw {
            None => (
                Tank {
                    root,
                    width: 1,
                    height: 1,
                },
                state.properties["shape"] == "window",
            ),
            Some(data) => {
                let (Some(Tag::Int(width)), Some(Tag::Int(height)), Some(Tag::Byte(window))) =
                    (data.get("Size"), data.get("Height"), data.get("Window"))
                else {
                    continue;
                };
                (
                    Tank::new(root, *width, *height).expect("validated tank dimensions"),
                    *window != 0,
                )
            }
        };
        if !tank.parts().all(|pos| {
            source
                .get(&pos)
                .is_some_and(|(state, _)| matches_geometry(tank, pos, window, state))
        }) || !check_links(&source, tank)
        {
            fail(
                root,
                "Fluid Tank controller must own one complete footprint with matching states and links",
            );
            continue;
        }
        let corner = [root[0] + tank.width - 1, root[1], root[2] + tank.width - 1];
        let first = transform(root);
        let last = transform(corner);
        let placed_root = std::array::from_fn(|axis| first[axis].min(last[axis]));
        let placed = Tank {
            root: placed_root,
            ..tank
        };
        for pos in placed.parts() {
            if occupied.insert(pos, (placed, window)).is_some() {
                fail(pos, "overlapping schematic Fluid Tank controllers");
            }
        }
    }
    for &pos in source.keys() {
        if !occupied.contains_key(&transform(pos)) {
            fail(pos, "schematic Fluid Tank part has no complete controller");
        }
    }
    for (&[x, y, z], &(tank, _)) in &occupied {
        if [[x + 1, y, z], [x, y + 1, z], [x, y, z + 1]]
            .into_iter()
            .any(|other| {
                occupied
                    .get(&other)
                    .is_some_and(|(neighbor, _)| *neighbor != tank)
            })
        {
            fail(
                [x, y, z],
                "independent schematic Fluid Tank groups must not touch",
            );
        }
    }
    for (_, block) in blocks.iter().filter(|(_, block)| block.state.name == BLOCK) {
        if block.block_entity.is_none() {
            fail(
                block.relative_pos,
                "a schematic Fluid Tank requires a registered block entity",
            );
        }
    }
    if !issues.is_empty() {
        return Err(issues);
    }

    for (_, block) in blocks
        .iter_mut()
        .filter(|(_, block)| block.state.name == BLOCK)
    {
        let (tank, window) = occupied[&block.relative_pos];
        let data = &mut block
            .block_entity
            .as_mut()
            .expect("registered tank entity")
            .data;
        data.clear();
        if block.relative_pos == tank.root {
            data.extend([
                ("Window".into(), Tag::Byte(i8::from(window))),
                ("Size".into(), Tag::Int(tank.width)),
                ("Height".into(), Tag::Int(tank.height)),
            ]);
        }
    }
    Ok(occupied
        .into_iter()
        .map(|(pos, (tank, _))| (pos, tank))
        .collect())
}
