// Copyright (c) The Create Team / The Creators of Create
// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT

//! Private model adaptations for FluidTankModel and its RECTANGLE sprite shifts.
use super::{Reader, invalid};
use serde_json::{Map, Value, json};
use std::io;

pub(super) const DIRECTORY: &str = "create-tank-ct";
const BLOCKSTATE: &str = "assets/create/blockstates/fluid_tank.json";
const MODEL_DIR: &str = "block/fluid_tank";
const SHAPES: [&str; 6] = [
    "plain",
    "window",
    "window_ne",
    "window_nw",
    "window_se",
    "window_sw",
];
const CONNECTIONS: [u8; 10] = [0, 5, 6, 7, 9, 10, 11, 13, 14, 15];
const SPRITES: [&str; 3] = ["fluid_tank", "fluid_tank_top", "fluid_tank_inner"];

#[derive(Clone, Copy)]
enum Side {
    West = 1,
    East = 2,
    North = 4,
    South = 8,
    Down = 16,
    Up = 32,
}

impl Side {
    fn named(name: &str) -> io::Result<Self> {
        match name {
            "west" => Ok(Self::West),
            "east" => Ok(Self::East),
            "north" => Ok(Self::North),
            "south" => Ok(Self::South),
            "down" => Ok(Self::Down),
            "up" => Ok(Self::Up),
            _ => Err(invalid("Unknown Fluid Tank model face")),
        }
    }

    fn opposite(self) -> Self {
        use Side::*;
        match self {
            West => East,
            East => West,
            North => South,
            South => North,
            Down => Up,
            Up => Down,
        }
    }

    fn horizontal(self) -> bool {
        !matches!(self, Self::Down | Self::Up)
    }

    fn joined(self, connections: u8) -> bool {
        connections & self as u8 != 0
    }

    fn tile(self, connections: u8) -> u8 {
        use Side::*;
        // ConnectedTextureBehaviour.buildContext, before projecting RECTANGLE.
        let (right, up) = match self {
            West => (South, Up),
            East => (North, Up),
            North => (West, Up),
            South => (East, Up),
            Down => (East, South),
            Up => (East, North),
        };
        let col = match (
            right.opposite().joined(connections),
            right.joined(connections),
        ) {
            (false, false) => 0,
            (false, true) => 1,
            (true, true) => 2,
            (true, false) => 3,
        };
        let row = match (up.joined(connections), up.opposite().joined(connections)) {
            (false, true) => 0,
            (true, true) => 1,
            (true, false) => 2,
            (false, false) => 3,
        };
        4 * row + col
    }
}

fn atlas(side: Side, sprite: &str) -> Option<&'static str> {
    match (side.horizontal(), sprite) {
        (true, "create:block/fluid_tank") => Some(SPRITES[0]),
        (false, "create:block/fluid_tank_top") => Some(SPRITES[1]),
        (false, "create:block/fluid_tank_inner") => Some(SPRITES[2]),
        _ => None,
    }
}

fn model_for(source: &Value, connections: u8) -> io::Result<Value> {
    let mut model = source.clone();
    let mut sprites = source["textures"]
        .as_object()
        .ok_or_else(|| invalid("Fluid Tank model has no textures"))?
        .clone();
    let elements = model["elements"]
        .as_array_mut()
        .ok_or_else(|| invalid("Fluid Tank model has no elements"))?;
    for element in elements.iter_mut() {
        // All pinned original models are unrotated, including zero-angle
        // Blockbench rotation records. JSON face keys equal baked directions.
        if let Some(rotation) = element.get("rotation")
            && rotation["angle"].as_f64() != Some(0.0)
        {
            return Err(invalid("Unexpected Fluid Tank model rotation"));
        }
        let faces = element["faces"]
            .as_object_mut()
            .ok_or_else(|| invalid("Fluid Tank element has no faces"))?;
        for (side, mut face) in std::mem::take(faces) {
            if let Some(cull) = face.get("cullface") {
                let group = Side::named(
                    cull.as_str()
                        .ok_or_else(|| invalid("Invalid Fluid Tank cull face"))?,
                )?;
                if group.horizontal() && group.joined(connections) {
                    continue;
                }
                // FluidTankModel returns all surviving original cull groups
                // from getQuads(null), where ordinary neighbor culling cannot
                // suppress them. The original face normal still selects its CT.
                face.as_object_mut()
                    .expect("face with cullface is an object")
                    .remove("cullface");
            }
            let material = face["texture"]
                .as_str()
                .and_then(|texture| match texture.strip_prefix('#') {
                    Some(key) => source["textures"][key].as_str(),
                    None => Some(texture),
                })
                .ok_or_else(|| invalid("Invalid Fluid Tank face texture"))?;
            let direction = Side::named(&side)?;
            if let Some(atlas) = atlas(direction, material) {
                let tile = direction.tile(connections);
                let uv = face["uv"]
                    .as_array_mut()
                    .filter(|uv| uv.len() == 4)
                    .ok_or_else(|| invalid("Fluid Tank CT faces need explicit UVs"))?;
                let offset = [tile % 4, tile / 4].map(|v| 4.0 * f64::from(v));
                for (axis, value) in uv.iter_mut().enumerate() {
                    let pixel = value
                        .as_f64()
                        .ok_or_else(|| invalid("Invalid Fluid Tank CT UV"))?;
                    *value = json!(pixel / 4.0 + offset[axis % 2]);
                }
                let key = format!("create_ct_{atlas}");
                sprites
                    .entry(key.clone())
                    .or_insert_with(|| json!(format!("create:block/{atlas}_connected")));
                face["texture"] = json!(format!("#{key}"));
            }
            faces.insert(side, face);
        }
    }
    elements.retain(|element| {
        element["faces"]
            .as_object()
            .is_some_and(|faces| !faces.is_empty())
    });
    model["textures"] = Value::Object(sprites);
    Ok(model)
}

fn atlas_path(sprite: &str) -> String {
    format!("assets/create/textures/block/{sprite}_connected.png")
}

pub(super) fn add_overlay(reader: &mut Reader) -> io::Result<()> {
    for sprite in SPRITES {
        reader.texture(&format!("create:block/{sprite}_connected"))?;
        if reader.files[&atlas_path(sprite)].get(12..24)
            != Some(b"IHDR\x00\x00\x00\x40\x00\x00\x00\x40")
        {
            return Err(invalid("Expected a 64x64 Fluid Tank connected texture"));
        }
    }
    let state: Value = serde_json::from_slice(&reader.files[BLOCKSTATE])?;
    let variants = state["variants"]
        .as_object()
        .filter(|variants| variants.len() == 24)
        .ok_or_else(|| invalid("Unexpected Fluid Tank blockstate variants"))?;
    let mut connected = Map::new();
    for bottom in [false, true] {
        for top in [false, true] {
            for shape in SHAPES {
                let name = variants
                    .get(&format!("bottom={bottom},shape={shape},top={top}"))
                    .and_then(Value::as_object)
                    .filter(|entry| entry.len() == 1)
                    .and_then(|entry| entry.get("model")?.as_str())
                    .and_then(|name| name.strip_prefix("create:block/fluid_tank/"))
                    .filter(|name| !name.contains('/'))
                    .ok_or_else(|| invalid("Expected an unrotated Fluid Tank model variant"))?;
                let path = format!("assets/create/models/{MODEL_DIR}/{name}.json");
                let model: Value = serde_json::from_slice(
                    reader
                        .files
                        .get(&path)
                        .ok_or_else(|| invalid("Missing Fluid Tank model"))?,
                )?;
                for mask in CONNECTIONS {
                    let model_path = format!("{MODEL_DIR}/connected/{name}_{mask}");
                    let mut bits = mask;
                    if !bottom {
                        bits |= Side::Down as u8;
                    }
                    if !top {
                        bits |= Side::Up as u8;
                    }
                    if reader
                        .files
                        .insert(
                            format!("{DIRECTORY}/assets/create/models/{model_path}.json"),
                            serde_json::to_vec(&model_for(&model, bits)?)?,
                        )
                        .is_some()
                    {
                        return Err(invalid("Duplicate Fluid Tank overlay model"));
                    }
                    connected.insert(
                        format!(
                            "bottom={bottom},create_connections={mask},shape={shape},top={top}"
                        ),
                        json!({"model": format!("create:{model_path}")}),
                    );
                }
            }
        }
    }
    reader.files.insert(
        format!("{DIRECTORY}/{BLOCKSTATE}"),
        serde_json::to_vec(&json!({"variants": connected}))?,
    );
    Ok(())
}

pub(super) fn in_cache(files: &Map<String, Value>) -> bool {
    let prefix = format!("{DIRECTORY}/assets/create/models/{MODEL_DIR}/connected/");
    files.contains_key(&format!("{DIRECTORY}/{BLOCKSTATE}"))
        && SPRITES
            .iter()
            .all(|sprite| files.contains_key(&atlas_path(sprite)))
        && files
            .keys()
            .filter(|path| path.starts_with(&prefix))
            .count()
            == 24 * CONNECTIONS.len()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn rectangle_tile_layout_for_square_top_bottom_and_tower_sides() {
        use Side::*;
        let masks = [10, 11, 9, 14, 15, 13, 6, 7, 5];
        assert_eq!(
            masks.map(|mask| Up.tile(mask)),
            [1, 2, 3, 5, 6, 7, 9, 10, 11]
        );
        assert_eq!(
            masks.map(|mask| Down.tile(mask)),
            [9, 10, 11, 5, 6, 7, 1, 2, 3]
        );
        let tower = [0, Up as u8, Down as u8, Up as u8 | Down as u8];
        for side in [North, South, West, East] {
            assert_eq!(tower.map(|mask| side.tile(mask)), [12, 8, 0, 4]);
        }
        assert_eq!(North.tile(East as u8), 15);
        assert_eq!(South.tile(East as u8), 13);
        assert_eq!(West.tile(South as u8), 13);
        assert_eq!(East.tile(South as u8), 15);
    }

    #[test]
    fn original_cull_group_and_original_normal_are_separate() {
        let face = |sprite, cull| json!({"uv":[0,4,16,12], "texture":sprite, "cullface": cull});
        let source = json!({
            "textures": {"side":"create:block/fluid_tank", "top":"create:block/fluid_tank_top",
                         "inner":"create:block/fluid_tank_inner", "window":"create:block/fluid_tank_window"},
            "elements": [{"from":[0,0,0], "to":[16,16,16], "faces":{
                "north": face("#side", "south"), "south": face("#side", "north"),
                "up": face("#inner", "up"), "down": face("#top", "down"),
                "west": face("#window", "west")
            }}]
        });
        let model = model_for(&source, Side::South as u8 | Side::East as u8).unwrap();
        let faces = &model["elements"][0]["faces"];
        assert!(faces.get("north").is_none());
        assert_eq!(
            faces["south"],
            json!({"texture":"#create_ct_fluid_tank", "uv":[4.0,13.0,8.0,15.0]})
        );
        assert_eq!(
            faces["up"],
            json!({"texture":"#create_ct_fluid_tank_inner", "uv":[4.0,1.0,8.0,3.0]})
        );
        assert_eq!(
            faces["down"],
            json!({"texture":"#create_ct_fluid_tank_top", "uv":[4.0,9.0,8.0,11.0]})
        );
        assert_eq!(
            faces["west"],
            json!({"texture":"#window", "uv":[0,4,16,12]})
        );
        assert_eq!(source["elements"][0]["faces"]["north"]["cullface"], "south");
    }
}
