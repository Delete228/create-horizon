// Copyright (c) The Create Team / The Creators of Create
// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT
// BasinOperatingBlockEntity/BasinRecipe and the Mixer/Press static recipe filters.
// Create ac0c444d9828da3453ae8cc65338e8de063286fb (6.0.10).
// The two operators keep distinct source caches; live cycles own their recipe Arc
// across a data-pack reload, while every subsequent lookup sees the new generation.
use super::{Game, create_port_basin as basin, create_port_fluid_codec as fluids};
use crate::items::ItemStack;
use create_engine::{basin as rules, fluid_transport::Fluid, transport::SessionCache};
use horizon_client::crafting::{Ingredient, Recipe as Crafting};
use horizon_core::random::RandomSource;
use std::{
    cell::{Cell, RefCell},
    collections::BTreeMap,
    sync::Arc,
};
type Pos = [i32; 3];

pub(super) mod emptying {
    use super::{Fluid, Game, ItemStack};
    use horizon_world::nbt::Tag;

    const HONEY_BOTTLE: &str = "minecraft:honey_bottle";
    pub(in crate::game) const GLASS_BOTTLE: &str = "minecraft:glass_bottle";
    pub(in crate::game) const BOTTLE_AMOUNT: i32 = 250;

    fn bucket_fluid(item: &str) -> Option<&'static str> {
        match item {
            "minecraft:water_bucket" => Some("minecraft:water"),
            "minecraft:lava_bucket" => Some("minecraft:lava"),
            _ => None,
        }
    }

    // PotionFluidHandler maps plain, regular Water Bottles to vanilla water.
    // Other bottle types or custom effects need Create's potion fluid codec.
    fn is_water_bottle(game: &Game<'_>, stack: &ItemStack) -> bool {
        stack.item.as_ref() == "minecraft:potion"
            && stack.potion() == Some(Fluid::Water.id())
            && stack.data().is_some_and(|data| {
                data.potion_extra.iter().all(|(key, value)| {
                    key != "custom_effects"
                        || matches!(value, Tag::List(effects) if effects.is_empty())
                })
            })
            && !game.items().item_in_tag("create:not_potion", &stack.item)
    }

    pub(in crate::game) fn can_empty(game: &Game<'_>, stack: &ItemStack) -> bool {
        stack.item.as_ref() == HONEY_BOTTLE
            || bucket_fluid(&stack.item).is_some()
            || is_water_bottle(game, stack)
    }

    pub(in crate::game) fn empty(
        game: &Game<'_>,
        stack: &ItemStack,
    ) -> Option<(&'static str, i32, ItemStack)> {
        if let Some(expected) = bucket_fluid(&stack.item) {
            let (fluid, amount, container) = game.native_item_fluid_drain(stack, 1000)?;
            return (fluid == expected && amount == 1000).then_some((expected, amount, container));
        }
        if is_water_bottle(game, stack) {
            return Some((
                Fluid::Water.id(),
                BOTTLE_AMOUNT,
                ItemStack::new(GLASS_BOTTLE, 1),
            ));
        }
        if stack.item.as_ref() != HONEY_BOTTLE {
            return None;
        }
        // GenericItemEmptying uses the stock recipe for bottles before the
        // item's fluid capability. Do not consume an unmodeled override.
        let recipe = game
            .native_recipes_of_type("create:emptying")
            .iter()
            .find(|recipe| recipe.id == "create:emptying/honey_bottle")?;
        let [ingredient] = recipe.json["ingredients"].as_array()?.as_slice() else {
            return None;
        };
        if ingredient.as_str() != Some(HONEY_BOTTLE)
            && !(ingredient
                .as_object()
                .is_some_and(|object| object.len() == 1)
                && ingredient["item"] == HONEY_BOTTLE)
        {
            return None;
        }
        let [item, fluid] = recipe.json["results"].as_array()?.as_slice() else {
            return None;
        };
        if fluid.as_object()?.len() != 2
            || fluid["id"] != Fluid::Honey.id()
            || fluid["amount"].as_i64() != Some(i64::from(BOTTLE_AMOUNT))
            || item.as_object()?.len() != 1
            || item["id"] != GLASS_BOTTLE
        {
            return None;
        }
        Some((
            Fluid::Honey.id(),
            BOTTLE_AMOUNT,
            ItemStack::new(GLASS_BOTTLE, 1),
        ))
    }
}

pub(super) mod item_drain {
    use super::{Fluid, Game, ItemStack, Pos, emptying, fluids};
    use crate::{
        containers::ModBlockEntity,
        game::{
            create_port_belt as belt, create_port_fluid_render as fluid_render,
            native_block_entity_draw::BlockEntityDraw,
        },
    };
    use create_engine::{
        basin::FluidLevel, kinetics::Axis, placement::Direction, source_trig,
        transport::Transported,
    };
    use horizon_assets::item_model::DisplayContext;
    use horizon_client::mod_api::{
        NativeFluidAction, NativeFluidDrain, NativeFluidRenderOptions, NativeFluidStack,
        NativeFluidTankView,
    };
    use horizon_core::geometry::trig;
    use horizon_world::nbt::{Compound, Tag};

    pub(in crate::game) const BLOCK: &str = "create:item_drain";
    const CAPACITY: i32 = 1500;
    const FILLING_TIME: i32 = 20;
    const EXCHANGE: i32 = 5;
    const STEP: f32 = 0.125;
    const POSE_NUDGE: f32 = (0.5 / 8.0 - 0.5) * 0.004;
    type Cargo = Transported<ItemStack>;

    fn float(value: f32) -> Tag {
        Tag::Float(value.to_bits())
    }

    pub(in crate::game) fn default_nbt() -> Compound {
        let segment = Compound::from([
            ("TankContent".into(), Tag::Compound(Compound::new())),
            (
                "Level".into(),
                Tag::Compound(Compound::from([
                    ("Value".into(), float(0.0)),
                    ("Target".into(), float(0.0)),
                    ("Speed".into(), float(0.25)),
                ])),
            ),
        ]);
        Compound::from([
            ("ProcessingTicks".into(), Tag::Int(0)),
            ("Tanks".into(), Tag::List(vec![Tag::Compound(segment)])),
        ])
    }

    pub(in crate::game) struct Tank {
        pub(in crate::game) fluid: &'static str,
        pub(in crate::game) amount: i32,
        level: FluidLevel,
    }

    impl Tank {
        fn accepts(&self, fluid: &str, amount: i32) -> bool {
            (self.amount == 0 || self.fluid == fluid) && CAPACITY - self.amount >= amount
        }

        fn fill(&mut self, fluid: &'static str, amount: i32) {
            self.fluid = fluid;
            self.set_amount(self.amount + amount);
        }

        pub(in crate::game) fn set_amount(&mut self, amount: i32) {
            self.amount = amount;
            self.level.target = self.amount as f32 / CAPACITY as f32;
            self.level.speed = 0.25;
        }

        fn content(&self, amount: i32) -> NativeFluidStack {
            NativeFluidStack {
                fluid: self.fluid.into(),
                amount,
                components: Compound::new(),
            }
        }
    }

    fn read_tank(entity: &ModBlockEntity) -> Option<Tank> {
        let Tag::List(tanks) = entity.nbt.get(&"Tanks".into())? else {
            return None;
        };
        let [segment] = tanks.as_slice() else {
            return None;
        };
        let content = fluids::read_content(segment.get("TankContent"), CAPACITY as u32).ok()?;
        let (fluid, amount) = if let Some(stored) = content {
            if !stored.key.components.is_empty() {
                return None;
            }
            let fluid = Fluid::from_id(&stored.key.id)?.id();
            (fluid, stored.amount as i32)
        } else {
            ("minecraft:water", 0)
        };
        let level = segment.get("Level")?;
        let scalar = |key| match level.get(key)? {
            Tag::Float(bits) => Some(f32::from_bits(*bits)).filter(|v| v.is_finite()),
            _ => None,
        };
        Some(Tank {
            fluid,
            amount,
            level: FluidLevel {
                value: scalar("Value")?,
                target: scalar("Target")?,
                speed: scalar("Speed")?,
                ..FluidLevel::default()
            },
        })
    }

    pub(in crate::game) fn comparator(entity: &ModBlockEntity) -> i32 {
        if entity.id != BLOCK {
            return 0;
        }
        read_tank(entity).map_or(0, |tank| {
            // ComparatorUtil's floor of 14 times the fill fraction, plus one for fluid.
            14 * tank.amount / CAPACITY + i32::from(tank.amount > 0)
        })
    }

    pub(in crate::game) fn tooltip(
        game: &Game<'_>,
        [x, y, z]: Pos,
    ) -> Vec<horizon_client::text::Text> {
        let Some(crate::containers::BlockEntity::Mod(entity)) =
            game.world.block_entities.get(&(x, y, z))
        else {
            return Vec::new();
        };
        let Some(tank) = read_tank(entity) else {
            return Vec::new();
        };
        let fluid = (tank.amount > 0).then_some((tank.fluid, tank.amount as u32));
        crate::game::create_port_goggles::fluid_container(game, CAPACITY as u32, fluid)
    }

    fn save_tank(entity: &mut ModBlockEntity, tank: &Tank, exchanged: bool) {
        let Some(Tag::List(segments)) = entity.nbt.get_mut(&"Tanks".into()) else {
            return;
        };
        let [Tag::Compound(segment)] = segments.as_mut_slice() else {
            return;
        };
        if let Some(Tag::Compound(level)) = segment.get_mut(&"Level".into()) {
            level.insert("Value".into(), float(tank.level.value));
            level.insert("Target".into(), float(tank.level.target));
            level.insert("Speed".into(), float(tank.level.speed));
        }
        if exchanged {
            let mut content = Compound::new();
            if tank.amount > 0 {
                let fluid = Tag::Compound(Compound::from([
                    ("id".into(), Tag::String(tank.fluid.into())),
                    ("amount".into(), Tag::Int(tank.amount)),
                ]));
                content.insert("Fluid".into(), fluid);
            }
            segment.insert("TankContent".into(), Tag::Compound(content));
        }
    }

    pub(in crate::game) fn fluid_tank(game: &Game<'_>, [x, y, z]: Pos) -> Option<Tank> {
        let crate::containers::BlockEntity::Mod(entity) =
            game.world.block_entities.get(&(x, y, z))?
        else {
            return None;
        };
        (entity.id == BLOCK).then(|| read_tank(entity)).flatten()
    }

    pub(in crate::game) fn fluid_view(
        game: &Game<'_>,
        pos: Pos,
    ) -> Option<Vec<NativeFluidTankView>> {
        let tank = fluid_tank(game, pos)?;
        Some(vec![NativeFluidTankView {
            tank: 0,
            content: (tank.amount > 0).then(|| tank.content(tank.amount)),
            capacity: CAPACITY,
            can_fill: false,
            can_drain: true,
        }])
    }

    pub(in crate::game) fn fluid_drain(
        game: &mut Game<'_>,
        pos: Pos,
        request: &NativeFluidDrain,
        action: NativeFluidAction,
    ) -> Option<NativeFluidStack> {
        let mut tank = fluid_tank(game, pos)?;
        let maximum = match request {
            NativeFluidDrain::Any(maximum) => *maximum,
            NativeFluidDrain::Exact(stack)
                if stack.fluid == tank.fluid && stack.components.is_empty() =>
            {
                stack.amount
            }
            _ => return None,
        };
        let amount = maximum.min(tank.amount);
        if amount <= 0 {
            return None;
        }
        #[allow(unreachable_patterns)]
        match action {
            NativeFluidAction::Simulate => {}
            NativeFluidAction::Execute => {
                tank.set_amount(tank.amount - amount);
                set_fluid(game, pos, &tank);
                notify_fluid(game, pos);
            }
            _ => return None,
        }
        Some(tank.content(amount))
    }

    pub(in crate::game) fn set_fluid(game: &mut Game<'_>, pos: Pos, tank: &Tank) {
        game.native_with_mod_block_entity(pos, |entity| save_tank(entity, tank, true));
    }

    pub(in crate::game) fn notify_fluid(game: &mut Game<'_>, pos: Pos) {
        game.native_block_entity_sync(pos);
        game.native_update_output_neighbors(game.dim.id(), pos);
    }

    fn save_cargo(entity: &mut ModBlockEntity, cargo: Option<&Cargo>, ticks: i32) -> bool {
        let tag = cargo.map(belt::write_item);
        if entity.nbt.get(&"HeldItem".into()) == tag.as_ref()
            && crate::game::create_port::integer(&entity.nbt, "ProcessingTicks") == ticks
        {
            return false;
        }
        entity.items[0] = cargo.map(|item| belt::game_stack(&item.stack));
        entity.nbt.insert("ProcessingTicks".into(), Tag::Int(ticks));
        if let Some(tag) = tag {
            entity.nbt.insert("HeldItem".into(), tag);
        } else {
            entity.nbt.remove(&"HeldItem".into());
        }
        true
    }

    pub(in crate::game) fn predicts_use(game: &Game<'_>, pos: Pos) -> bool {
        let secondary_with_item = game.native_sneaking()
            && (game
                .inventory
                .get(game.selected)
                .is_some_and(Option::is_some)
                || game.offhand.is_some());
        game.native_on("create")
            && game.native_block(pos) == BLOCK
            && !secondary_with_item
            && game
                .held()
                .is_none_or(|stack| stack.count == 0 || emptying::can_empty(game, stack))
    }

    pub(in crate::game) fn right_click(game: &mut Game<'_>, pos: Pos) -> bool {
        if !predicts_use(game, pos) {
            return false;
        }
        if let Some(held) = game.held().filter(|stack| stack.count > 0) {
            let count = held.count;
            let Some((fluid, amount, container)) = emptying::empty(game, held) else {
                return true;
            };
            let poured = game.native_with_mod_block_entity(pos, |entity| {
                if entity.id != BLOCK {
                    return false;
                }
                let Some(mut tank) = read_tank(entity).filter(|tank| tank.accepts(fluid, amount))
                else {
                    return false;
                };
                tank.fill(fluid, amount);
                save_tank(entity, &tank, true);
                true
            }) == Some(true);
            if poured {
                if !game.creative {
                    if count == 1 {
                        *game.held_mut() = Some(container);
                    } else {
                        game.consume_held();
                        crate::game::create_port_basin::give_container(game, pos, container);
                    }
                }
                notify_fluid(game, pos);
            }
        } else {
            let cargo = game
                .native_with_mod_block_entity(pos, |entity| {
                    if entity.id != BLOCK || !entity.nbt.contains_key(&"HeldItem".into()) {
                        return None;
                    }
                    let stack = entity.items.first()?.clone()?;
                    let ticks = crate::game::create_port::integer(&entity.nbt, "ProcessingTicks");
                    save_cargo(entity, None, ticks);
                    Some(stack)
                })
                .flatten();
            if let Some(cargo) = cargo {
                crate::game::create_port_basin::give_container(game, pos, cargo);
                game.native_block_entity_sync(pos);
            }
        }
        true
    }

    pub(in crate::game) fn insert(
        game: &mut Game<'_>,
        pos: Pos,
        incoming: &Cargo,
        from: Direction,
    ) -> u32 {
        if from.axis() == Axis::Y
            || incoming.stack.count == 0
            || !emptying::can_empty(game, &incoming.stack.payload)
        {
            return 0;
        }
        let mut cargo = incoming.source_copy();
        cargo.stack.count = 1;
        cargo.position = 0.0;
        cargo.previous_position = 0.0;
        cargo.previous_side_offset = cargo.side_offset;
        cargo.inserted_from = from;
        let accepted = game.native_with_mod_block_entity(pos, |entity| {
            if entity.id != BLOCK
                || entity.items.len() != 1
                || entity.nbt.contains_key(&"HeldItem".into())
                || entity.items[0].is_some()
                || read_tank(entity).is_none()
            {
                return false;
            }
            save_cargo(entity, Some(&cargo), 0)
        }) == Some(true);
        if accepted {
            game.native_block_entity_sync(pos);
        }
        u32::from(accepted)
    }

    fn output(game: &mut Game<'_>, pos: Pos, cargo: &Cargo) -> u32 {
        let direction = cargo.inserted_from;
        let delta = direction.vector();
        let target = std::array::from_fn(|i| pos[i] + delta[i]);
        if !crate::game::create_port_contraption::resident(game, target) {
            return 0;
        }
        match game.native_block(target).as_str() {
            "create:depot" => belt::insert_depot_from_side(game, target, cargo, direction),
            "create:belt" => {
                if belt::insert_belt_from_side(game, target, cargo, direction, false) {
                    cargo.stack.count
                } else {
                    0
                }
            }
            "minecraft:air" => {
                let at = [
                    f64::from(pos[0]) + 0.5 + f64::from(delta[0]) * 0.75,
                    f64::from(pos[1]) + 0.875,
                    f64::from(pos[2]) + 0.5 + f64::from(delta[2]) * 0.75,
                ];
                game.spawn_item(
                    belt::game_stack(&cargo.stack),
                    at,
                    [
                        f64::from(delta[0]) * f64::from(STEP),
                        0.125,
                        f64::from(delta[2]) * f64::from(STEP),
                    ],
                    10,
                );
                cargo.stack.count
            }
            _ => 0,
        }
    }

    pub(in crate::game) fn tick(game: &mut Game<'_>, pos: Pos, entity: &mut ModBlockEntity) {
        if entity.id != BLOCK || entity.items.len() != 1 {
            return;
        }
        let Some(mut tank) = read_tank(entity) else {
            return;
        };
        tank.level.tick();
        if tank.level.value != tank.level.previous {
            save_tank(entity, &tank, false);
            game.native_block_entity_sync(pos);
        }
        let Some(saved) = entity.nbt.get(&"HeldItem".into()) else {
            entity.nbt.insert("ProcessingTicks".into(), Tag::Int(0));
            return;
        };
        let Some(mut cargo) = belt::read_item(game, saved) else {
            return;
        };
        let mut ticks = crate::game::create_port::integer(&entity.nbt, "ProcessingTicks");
        if cargo.inserted_from.axis() == Axis::Y || !(0..=FILLING_TIME).contains(&ticks) {
            return;
        }
        if ticks > 0 {
            cargo.previous_position = 0.5;
            ticks -= 1;
            if ticks >= EXCHANGE {
                let stack = belt::game_stack(&cargo.stack);
                if let Some((fluid, amount, container)) = emptying::empty(game, &stack) {
                    if !tank.accepts(fluid, amount) {
                        ticks = FILLING_TIME;
                    } else if ticks == EXCHANGE {
                        cargo.stack = belt::core_stack(game, container);
                        tank.fill(fluid, amount);
                        save_tank(entity, &tank, true);
                    }
                } else {
                    ticks = 0;
                }
            }
        } else {
            cargo.previous_position = cargo.position;
            cargo.previous_side_offset = cargo.side_offset;
            cargo.position += STEP;
            if cargo.position > 1.0 {
                cargo.position = 1.0;
                cargo.stack.count -= output(game, pos, &cargo);
            } else if cargo.previous_position < 0.5
                && cargo.position >= 0.5
                && emptying::can_empty(game, &cargo.stack.payload)
            {
                cargo.position = 0.5;
                ticks = FILLING_TIME;
            }
        }
        let held = (cargo.stack.count != 0).then_some(&cargo);
        if save_cargo(entity, held, ticks) {
            game.native_block_entity_sync(pos);
        }
    }

    pub(in crate::game) fn draw(
        game: &Game<'_>,
        pos: Pos,
        entity: &ModBlockEntity,
        draw: &mut BlockEntityDraw,
    ) {
        let tank = read_tank(entity).filter(|tank| tank.amount > 0);
        let render_options = |render_bottom| NativeFluidRenderOptions {
            argb: None,
            render_bottom,
            uv_shrink_ratio: 4.0 / 2048.0,
        };
        let render_fluid = |fluid: &str, amount| NativeFluidStack {
            fluid: fluid.into(),
            amount,
            components: Compound::new(),
        };
        if let Some(tank) = tank.as_ref().filter(|tank| tank.level.value > 0.0) {
            fluid_render::draw(
                game,
                draw,
                &render_fluid(tank.fluid, tank.amount),
                [
                    2.0 / 16.0,
                    5.0 / 16.0,
                    2.0 / 16.0,
                    14.0 / 16.0,
                    5.0 / 16.0 + 7.0 / 16.0 * tank.level.value.clamp(0.0, 1.0),
                    14.0 / 16.0,
                ],
                render_options(false),
            );
        }
        let Some(item) = entity
            .nbt
            .get(&"HeldItem".into())
            .and_then(|tag| belt::read_item(game, tag))
        else {
            return;
        };
        if item.inserted_from.axis() == Axis::Y {
            return;
        }
        let stack = belt::game_stack(&item.stack);
        let ticks = crate::game::create_port::integer(&entity.nbt, "ProcessingTicks");
        let progress = (1.0 - (ticks as f32 - draw.partial - 5.0) / 10.0).clamp(0.0, 1.0);
        if 0.0 < progress && progress < 1.0 {
            let fluid = emptying::empty(game, &stack)
                .map(|(fluid, amount, _)| render_fluid(fluid, amount))
                .or_else(|| {
                    tank.as_ref()
                        .map(|tank| render_fluid(tank.fluid, tank.amount))
                });
            if let Some(fluid) = fluid {
                // ItemDrainRenderer inflates a zero-width AABB by a negative value.
                // AABB orders the resulting X/Z coordinates and shortens the Y range.
                let width = ((1.0 - f64::from(2.0 * progress - 1.0).powi(2)) as f32) / 32.0;
                fluid_render::draw(
                    game,
                    draw,
                    &fluid,
                    [
                        0.5 - width,
                        0.25 + width,
                        0.5 - width,
                        0.5 + width,
                        1.0 - width,
                        0.5 + width,
                    ],
                    render_options(true),
                );
            }
        }
        let delta = item.inserted_from.vector();
        let along_x = item.inserted_from.axis() == Axis::X;
        let fraction =
            item.previous_position + (item.position - item.previous_position) * draw.partial;
        let side = item.previous_side_offset
            + (item.side_offset - item.previous_side_offset) * draw.partial;
        let offset = [
            delta[0] as f32 * (fraction - 0.5),
            delta[2] as f32 * (fraction - 0.5),
        ];
        let (axis, angle) = if along_x {
            (Axis::Z, -(delta[0] as f32) * fraction * 360.0)
        } else {
            (Axis::X, delta[2] as f32 * fraction * 360.0)
        };
        let upright = belt::upright(game, &stack);
        draw.push();
        draw.translate([
            0.5 + POSE_NUDGE + offset[0] + if along_x { 0.0 } else { side },
            15.0 / 16.0 + POSE_NUDGE + if upright { 3.0 / 32.0 } else { 0.0 },
            0.5 + POSE_NUDGE + offset[1] - if along_x { side } else { 0.0 },
        ]);
        let axis_vector = if along_x {
            [0.0, 0.0, 1.0]
        } else {
            [1.0, 0.0, 0.0]
        };
        draw.rotate_about(axis_vector, angle, [0.0; 3]);
        if upright {
            if let Some(camera) = game.native_camera() {
                let diff = [
                    f64::from(pos[0]) + 0.5 + f64::from(offset[0]) - camera.position[0],
                    f64::from(pos[1]) + 0.5 - camera.position[1],
                    f64::from(pos[2]) + 0.5 + f64::from(offset[1]) - camera.position[2],
                ];
                let [x, _, z] = source_trig::rotate(diff, angle, axis);
                let yaw = trig::atan2(z, -x) as f32;
                let yaw = (f64::from(yaw) - std::f64::consts::FRAC_PI_2) as f32;
                draw.rotate_about([0.0, 1.0, 0.0], yaw.to_degrees(), [0.0; 3]);
            }
            draw.translate([0.0, 0.0, -1.0 / 16.0]);
        }
        draw.scale([0.5; 3]);
        if !upright {
            draw.rotate_about([1.0, 0.0, 0.0], 90.0, [0.0; 3]);
        }
        game.native_draw_item(draw, &stack, DisplayContext::Fixed, None, 0);
        draw.pop();
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Ord, PartialOrd)]
pub(super) enum Operator {
    Mixing,
    Compacting,
}
impl Operator {
    fn recipe_type(self) -> &'static str {
        match self {
            Self::Mixing => "create:mixing",
            Self::Compacting => "create:compacting",
        }
    }
}
#[derive(Clone)]
enum Input {
    Item(Ingredient),
    BlockTag(String),
}
#[derive(Clone)]
pub(super) struct Recipe {
    pub(super) id: String,
    inputs: Vec<Input>,
    fluids: Vec<String>,
    pub(super) core: rules::Recipe<basin::Key, fluids::Key>,
}
#[derive(Default)]
struct Recipes {
    generation: u64,
    source: Vec<Arc<serde_json::Value>>,
    vanilla: usize,
    compiled: Vec<Arc<Recipe>>,
}

fn compile(game: &Game<'_>, id: &str, json: &serde_json::Value) -> Option<Recipe> {
    // Strict bounded codecs: no unknown ingredient fields can be dropped to
    // turn an unsupported predicate into a simpler item/fluid match.
    let heat = match json.get("heat_requirement") {
        None => rules::HeatRequirement::None,
        Some(v) => match v.as_str()? {
            "none" => rules::HeatRequirement::None,
            "heated" => rules::HeatRequirement::Heated,
            "superheated" => rules::HeatRequirement::Superheated,
            _ => return None,
        },
    };
    let mut inputs = Vec::new();
    let mut fluids = Vec::new();
    let mut fluid_amounts = Vec::new();
    for i in json["ingredients"].as_array()? {
        match i.get("type").and_then(serde_json::Value::as_str) {
            Some(kind @ ("neoforge:single" | "neoforge:tag")) => {
                if i.as_object()?.len() != 3 {
                    return None;
                }
                let fluid = match kind {
                    "neoforge:single" => Fluid::from_id(i["fluid"].as_str()?)?,
                    // The stock Create tag has one member in the currently
                    // supported fluid set. Custom fluid tag resolution is open.
                    "neoforge:tag" if id == "create:compacting/honey" && i["tag"] == "c:honey" => {
                        Fluid::Honey
                    }
                    _ => return None,
                };
                let amount = i["amount"].as_u64()?;
                if !(1..=i32::MAX as u64).contains(&amount) {
                    return None;
                }
                fluids.push(fluid.id().to_owned());
                fluid_amounts.push(amount as u32);
            }
            Some("neoforge:block_tag") => {
                if i.as_object()?.len() != 2 {
                    return None;
                }
                inputs.push(Input::BlockTag(i["tag"].as_str()?.to_owned()));
            }
            Some(_) => return None,
            None => inputs.push(Input::Item(
                game.native_recipe_ingredient(&plain_ingredient(i)?)?,
            )),
        }
    }
    let results = json["results"].as_array()?;
    if inputs.len() + fluids.len() == 0
        || inputs.len() > 64
        || fluids.len() > 2
        || results.is_empty()
        || results.len() > 4
    {
        return None;
    }
    let (mut outputs, mut fluid_outputs) = (Vec::new(), Vec::new());
    if results.iter().any(|row| row.get("amount").is_some()) {
        for row in results {
            let id = row["id"].as_str()?;
            let amount = u32::try_from(row["amount"].as_u64()?).ok()?;
            if row.as_object()?.len() != 2
                || Fluid::from_id(id).is_none()
                || !(1..=i32::MAX as u32).contains(&amount)
            {
                return None;
            }
            fluid_outputs.push(rules::Fluid {
                key: fluids::Key {
                    id: id.to_owned(),
                    components: Default::default(),
                },
                amount,
            });
        }
    } else {
        for r in results {
            let fields = r.as_object()?;
            if fields.keys().any(|k| {
                !matches!(
                    k.as_str(),
                    "id" | "item" | "count" | "chance" | "components"
                )
            }) || (fields.contains_key("id") && fields.contains_key("item"))
                || r.get("count")
                    .is_some_and(|v| v.as_u64().is_none_or(|v| !(1..=99).contains(&v)))
                || r.get("chance").is_some_and(|v| v.as_f64().is_none())
                || r.get("components").is_some_and(|v| !v.is_object())
            {
                return None;
            }
            let mut r = r.clone();
            if r.get("id").is_none() {
                r["id"] = r["item"].clone();
            }
            let stack = game.native_recipe_result(&r)?;
            let chance = r["chance"].as_f64().unwrap_or(1.0) as f32;
            if !chance.is_finite() || !(0.0..=1.0).contains(&chance) {
                return None;
            }
            outputs.push(rules::Roll {
                stack: basin::core_stack(game, &stack),
                chance,
            });
        }
    }
    Some(Recipe {
        id: id.to_owned(),
        core: rules::Recipe {
            kind: rules::RecipeKind::Basin,
            item_ingredients: inputs.len(),
            fluid_amounts,
            outputs,
            fluid_outputs,
            heat,
            duration: match json
                .get("processing_time")
                .or_else(|| json.get("processingTime"))
            {
                None => 0,
                Some(v) => i32::try_from(v.as_i64()?).ok()?,
            },
        },
        inputs,
        fluids,
    })
}
fn plain_ingredient(i: &serde_json::Value) -> Option<serde_json::Value> {
    if let Some(id) = i.as_str() {
        return id.contains(':').then(|| i.clone());
    }
    if let Some(children) = i.as_array() {
        if children.is_empty() {
            return None;
        }
        return children
            .iter()
            .map(plain_ingredient)
            .collect::<Option<Vec<_>>>()
            .map(serde_json::Value::Array);
    }
    if i.as_object()?.len() != 1 {
        return None;
    }
    super::create_port::ingredient(i)
}

thread_local! {
    static WORLDS: RefCell<SessionCache<BTreeMap<Operator, Recipes>>> = RefCell::new(SessionCache::default());
    // WorldTables replaces its contents in place, so a table address alone
    // cannot invalidate vanilla-only recipe/tag lookups on resource reload.
    static GENERATION: Cell<u64> = const { Cell::new(0) };
}
pub(super) fn reset(reload: bool) {
    if reload {
        GENERATION.with(|generation| generation.set(generation.get().wrapping_add(1)));
    } else {
        WORLDS.with(|cache| cache.borrow_mut().clear());
    }
}
fn with_recipes<R>(
    game: &Game<'_>,
    operator: Operator,
    action: impl FnOnce(&mut Recipes) -> R,
) -> R {
    WORLDS.with(|cache| {
        action(
            cache
                .borrow_mut()
                .dimension(std::ptr::from_ref(&game.world) as usize, game.dim.id())
                .entry(operator)
                .or_default(),
        )
    })
}
// MechanicalPress.canCompress/ItemHelper.matchAllIngredients compare the
// displayed item arrays in order. Predicate identity/components are not compared.
fn can_compress(ingredients: &[Ingredient]) -> bool {
    matches!(ingredients.len(), 4 | 9)
        && ingredients.iter().all(|i| i.order == ingredients[0].order)
}
fn recipes(game: &Game<'_>, operator: Operator) -> Vec<Arc<Recipe>> {
    with_recipes(game, operator, |cache| {
        let custom = game.native_recipes_of_type(operator.recipe_type());
        let table = game.recipes();
        let vanilla = std::ptr::from_ref(table) as usize;
        let generation = GENERATION.with(Cell::get);
        if cache.generation == generation
            && cache.vanilla == vanilla
            && cache.source.len() == custom.len()
            && custom
                .iter()
                .zip(&cache.source)
                .all(|(r, old)| Arc::ptr_eq(&r.json, old))
        {
            return cache.compiled.clone();
        }
        let mut compiled: Vec<_> = custom
            .iter()
            .filter_map(|r| compile(game, &r.id, &r.json))
            .map(Arc::new)
            .collect();
        for (id, recipe) in &table.crafting {
            if id.ends_with("_manual_only") {
                continue;
            }
            let (ingredients, result, shaped) = match recipe {
                Crafting::Shapeless {
                    ingredients,
                    result,
                } => (ingredients.clone(), result, false),
                Crafting::Shaped { cells, result, .. } if operator == Operator::Compacting => {
                    // An empty shaped cell is Ingredient.EMPTY in the original
                    // list, not an omitted ingredient. It must participate in
                    // both the 4/9 size test and displayed-array comparison.
                    let inputs = cells
                        .iter()
                        .map(|i| i.clone().unwrap_or_else(|| Ingredient::of(Vec::new())))
                        .collect();
                    (inputs, result, true)
                }
                _ => continue,
            };
            let compress = can_compress(&ingredients);
            let accepted = match operator {
                Operator::Mixing => !shaped && ingredients.len() > 1 && !compress,
                Operator::Compacting => compress,
            };
            if !accepted {
                continue;
            }
            let output = result.create();
            if output.count == 0 || output.item.as_ref() == "minecraft:air" {
                continue;
            }
            compiled.push(Arc::new(Recipe {
                id: horizon_client::crafting::recipe_id(id),
                inputs: ingredients.iter().cloned().map(Input::Item).collect(),
                fluids: Vec::new(),
                core: rules::Recipe {
                    kind: rules::RecipeKind::Crafting,
                    item_ingredients: ingredients.len(),
                    fluid_amounts: Vec::new(),
                    outputs: vec![rules::Roll {
                        stack: basin::core_stack(game, &output),
                        chance: 1.0,
                    }],
                    fluid_outputs: Vec::new(),
                    heat: rules::HeatRequirement::None,
                    duration: 0,
                },
            }));
        }
        cache.generation = generation;
        cache.vanilla = vanilla;
        cache.source = custom.iter().map(|r| r.json.clone()).collect();
        cache.compiled = compiled;
        cache.compiled.clone()
    })
}

struct Context<'a, 'b> {
    game: &'a mut Game<'b>,
    inputs: &'a [Input],
    fluids: &'a [String],
}
impl rules::Context<basin::Key, fluids::Key> for Context<'_, '_> {
    fn item_matches(&mut self, ingredient: usize, item: &rules::Item<basin::Key>) -> bool {
        match &self.inputs[ingredient] {
            Input::Item(input) => input.test(&item.key.0),
            Input::BlockTag(tag) => self
                .game
                .items()
                .get(&item.key.0.item)
                .and_then(|info| info.block)
                .and_then(|state| self.game.pack.assets.registry.state(state))
                .is_some_and(|state| {
                    self.game
                        .native_server_block_in_tag(state, tag)
                        .unwrap_or(false)
                }),
        }
    }
    fn fluid_matches(&mut self, ingredient: usize, fluid: &rules::Fluid<fluids::Key>) -> bool {
        // NeoForge single fluid ingredients match the fluid holder, ignoring
        // the stack component patch; consumed storage still keeps that patch.
        self.fluids[ingredient] == fluid.key.id
    }
    fn remainder(&mut self, unit: &rules::Item<basin::Key>) -> Option<rules::Item<basin::Key>> {
        let item = self
            .game
            .items()
            .get(&unit.key.0.item)?
            .crafting_remainder
            .clone()?;
        Some(basin::core_stack(self.game, &ItemStack::new(&item, 1)))
    }
    fn random(&mut self) -> f32 {
        self.game.world.random.next_float()
    }
}
pub(super) fn matching(
    game: &mut Game<'_>,
    pos: Pos,
    basin: &mut basin::Basin,
    recipe: &Recipe,
) -> bool {
    let Some(filter) = super::create_port_basin_filter::current(game, pos) else {
        return false;
    };
    if let Some(filter) = filter {
        // BasinRecipe.match checks the declared first item, or the first
        // fluid for a fluid-only recipe, before simulation rolls any results.
        let accepted = if let Some(result) = recipe.core.outputs.first() {
            filter.item == result.stack.key.0.item
        } else if let Some(result) = recipe.core.fluid_outputs.first() {
            result.key.components.is_empty()
                && game
                    .native_item_fluid_drain(&filter, 1000)
                    .is_some_and(|(fluid, _, _)| fluid == result.key.id)
        } else {
            false
        };
        if !accepted {
            return false;
        }
    }
    if recipe.core.kind == rules::RecipeKind::Basin {
        basin.heat = basin::heat(game, pos);
    }
    basin
        .match_recipe(
            &recipe.core,
            true,
            true,
            &mut Context {
                game,
                inputs: &recipe.inputs,
                fluids: &recipe.fluids,
            },
        )
        .success()
}
pub(super) fn choose(
    game: &mut Game<'_>,
    pos: Pos,
    basin: &mut basin::Basin,
    operator: Operator,
) -> Option<Arc<Recipe>> {
    if (basin.input.iter().chain(&basin.output).all(Option::is_none)
        && basin
            .input_fluids
            .iter()
            .chain(&basin.output_fluids)
            .all(Option::is_none))
        || !basin.can_continue_processing()
    {
        return None;
    }
    // Source tests EVERY candidate before sorting: even match simulations roll
    // probabilistic outputs. Do not short-circuit at the first successful one.
    let variants: std::collections::BTreeSet<_> = basin
        .input
        .iter()
        .chain(&basin.output)
        .flatten()
        .filter(|s| s.count > 0)
        .map(|s| s.key.0.item.to_string())
        .collect();
    let mut found: Vec<_> = recipes(game, operator)
        .into_iter()
        // RecipeTrie indexes simple ingredients by item variant, without
        // counts/components. Its universal key admits non-simple predicates.
        .filter(|r| {
            r.inputs.iter().all(|i| match i {
                Input::BlockTag(_) => true,
                Input::Item(i) => {
                    i.custom.is_some()
                        || i.children.is_some()
                        || i.order.iter().any(|item| variants.contains(item.as_str()))
                }
            })
        })
        .filter(|r| matching(game, pos, basin, r))
        .collect();
    found.sort_by_key(|r| std::cmp::Reverse(r.inputs.len()));
    found.into_iter().next()
}
pub(super) fn apply(game: &mut Game<'_>, pos: Pos, recipe: Option<&Recipe>) -> bool {
    let Some(recipe) = recipe else {
        return false;
    };
    let Some(mut state) = basin::read(game, pos) else {
        return false;
    };
    if recipe.core.kind == rules::RecipeKind::Basin {
        state.heat = basin::heat(game, pos);
    }
    let was_empty = state.can_continue_processing();
    let report = state.apply(
        &recipe.core,
        false,
        &mut Context {
            game,
            inputs: &recipe.inputs,
            fluids: &recipe.fluids,
        },
    );
    // Preserve known source partial-consumption/output-overbooking failures.
    if report.changed() {
        basin::write(game, pos, &state);
    }
    if !report.success() {
        return false;
    }
    was_empty && matching(game, pos, &mut state, recipe)
}
