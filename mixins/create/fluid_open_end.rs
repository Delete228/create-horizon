// Copyright (c) The Create Team / The Creators of Create
// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT
// OpenEndedPipe water/lava storage and changes to the exposed world block.
use super::{Game, create_port_fluid_codec as codec};
use create_engine::{basin::Fluid, fluid_transport::Fluid as Kind, placement::Direction};
use horizon_core::geometry::{Direction as Face, ShapeOp, VoxelShape};
use horizon_core::random::RandomSource;
use horizon_world::{
    fluid::{FluidKind, FluidState},
    level::flags::UPDATE_ALL,
    nbt::{Compound, Tag},
    registry::BlockStateId,
};

type Pos = [i32; 3];
type Stack = Fluid<codec::Key>;
const CAPACITY: u32 = 1000;

fn facing(side: Direction) -> Face {
    [
        Face::Down,
        Face::Up,
        Face::North,
        Face::South,
        Face::West,
        Face::East,
    ][side as usize]
}

fn shift(pos: Pos, side: Direction) -> Pos {
    let delta = side.vector();
    std::array::from_fn(|i| pos[i] + delta[i])
}

fn state(game: &Game<'_>, [x, y, z]: Pos) -> Option<BlockStateId> {
    game.world.loaded(x, z).then(|| game.world.block(x, y, z))
}

fn variant(game: &Game<'_>, id: BlockStateId, key: &str, value: &str) -> Option<BlockStateId> {
    let registry = game.pack.assets.registry;
    let mut block = registry.state(id)?.clone();
    *block.properties.get_mut(key)? = value.into();
    registry.id(&block)
}

pub(super) struct Space {
    pos: Pos,
    state: BlockStateId,
    surface: Surface,
    fluid: FluidState,
}

enum Surface {
    Replaceable,
    Waterlogged,
    Cauldron(Option<Kind>),
    Hive(bool),
}

impl Space {
    pub(super) fn read(game: &Game<'_>, pos: Pos, side: Direction) -> Option<Self> {
        let height = game.dimension_type().height;
        if !(height.min_y..height.min_y + height.height).contains(&pos[1]) {
            return None;
        }
        let id = state(game, pos)?;
        let behaviour = game.res.behaviours();
        let block = game.pack.assets.registry.state(id)?;
        let surface = match block.name.as_str() {
            "minecraft:lava_cauldron" => Surface::Cauldron(Some(Kind::Lava)),
            "minecraft:water_cauldron" => Surface::Cauldron(
                block
                    .properties
                    .get("level")
                    .is_some_and(|level| level == "3")
                    .then_some(Kind::Water),
            ),
            "minecraft:cauldron" => Surface::Cauldron(None),
            "minecraft:bee_nest" | "minecraft:beehive" => Surface::Hive(
                block
                    .properties
                    .get("honey_level")
                    .is_some_and(|level| level == "5"),
            ),
            _ if behaviour.is_face_sturdy(id, facing(side)) => return None,
            _ if block.properties.contains_key("waterlogged") => Surface::Waterlogged,
            _ if behaviour.is_replaceable(id) => Surface::Replaceable,
            _ => return None,
        };
        Some(Self {
            pos,
            state: id,
            surface,
            fluid: behaviour.fluid(id),
        })
    }

    pub(super) fn source(&self) -> Option<(Kind, u32)> {
        match self.surface {
            Surface::Cauldron(fluid) => return fluid.map(|kind| (kind, CAPACITY)),
            Surface::Hive(full) => return full.then_some((Kind::Honey, 250)),
            _ => {}
        }
        if !self.fluid.is_source() {
            return None;
        }
        match self.fluid.kind() {
            FluidKind::Water => Some((Kind::Water, CAPACITY)),
            FluidKind::Lava => Some((Kind::Lava, CAPACITY)),
            _ => None,
        }
    }

    fn regenerates(&self, game: &Game<'_>, kind: Kind) -> bool {
        let behaviour = game.res.behaviours();
        let rules = game.level_rules();
        if !match kind {
            Kind::Water => rules.water_source_conversion,
            Kind::Lava => rules.lava_source_conversion,
            _ => false,
        } {
            return false;
        }
        let family = self.fluid.kind();
        let source = |id| {
            let fluid = behaviour.fluid(id);
            fluid.kind().same_family(family) && fluid.is_source()
        };
        let has_base = state(game, shift(self.pos, Direction::Down))
            .is_some_and(|id| behaviour.is_solid(id) || source(id));
        has_base
            && [
                Direction::North,
                Direction::South,
                Direction::West,
                Direction::East,
            ]
            .into_iter()
            .filter(|&direction| {
                let Some(id) = state(game, shift(self.pos, direction)).filter(|&id| source(id))
                else {
                    return false;
                };
                // A free-standing liquid has an empty collision face. The
                // only obstruction is the adjacent block's matching face.
                behaviour.collision_shape(id).is_none_or(|shape| {
                    shape
                        .face_shape(facing(direction.opposite()))
                        .is_ok_and(|face| {
                            VoxelShape::block()
                                .join_is_not_empty(&face, ShapeOp::ONLY_FIRST)
                                .unwrap_or(false)
                        })
                })
            })
            .take(2)
            .count()
                == 2
    }

    fn drain(&self, game: &Game<'_>, kind: Kind) -> Option<Option<WorldWrite>> {
        let write = match self.surface {
            Surface::Hive(_) => self.change(
                variant(game, self.state, "honey_level", "0")?,
                Update::Block,
            ),
            Surface::Cauldron(_) => self.change(
                game.native_default_state("minecraft:cauldron")?,
                Update::Block,
            ),
            Surface::Waterlogged => self.change(
                variant(game, self.state, "waterlogged", "false")?,
                Update::Waterlogged,
            ),
            Surface::Replaceable if self.regenerates(game, kind) => return Some(None),
            Surface::Replaceable => {
                self.change(variant(game, self.state, "level", "14")?, Update::Liquid)
            }
        };
        Some(Some(write))
    }

    fn fill(&self, game: &Game<'_>, kind: Kind) -> Option<WorldWrite> {
        let family = match kind {
            Kind::Water => FluidKind::Water,
            Kind::Lava => FluidKind::Lava,
            _ => return None,
        };
        if self.fluid.is_source()
            || (self.fluid != FluidState::EMPTY && !self.fluid.kind().same_family(family))
        {
            return None;
        }
        let (new, update) = match self.surface {
            Surface::Waterlogged if kind == Kind::Water => (
                variant(game, self.state, "waterlogged", "true")?,
                Update::Waterlogged,
            ),
            Surface::Replaceable => (game.native_default_state(kind.id())?, Update::Liquid),
            Surface::Waterlogged | Surface::Cauldron(_) | Surface::Hive(_) => return None,
        };
        if !super::create_port_server_config::place_fluid_sources() {
            return Some(self.change(self.state, Update::Discard));
        }
        if kind == Kind::Water && game.dimension_type().water_evaporates {
            return Some(self.change(self.state, Update::Vapor));
        }
        Some(self.change(new, update))
    }

    fn reaction(&self, game: &Game<'_>, kind: Kind) -> Option<WorldWrite> {
        let block = match (kind, self.fluid.kind()) {
            (Kind::Water, FluidKind::Lava) => "minecraft:obsidian",
            (Kind::Lava, FluidKind::Water) => "minecraft:stone",
            (Kind::Water, FluidKind::FlowingLava) | (Kind::Lava, FluidKind::FlowingWater) => {
                "minecraft:cobblestone"
            }
            _ => return None,
        };
        Some(self.change(game.native_default_state(block)?, Update::Reaction))
    }

    fn change(&self, new: BlockStateId, update: Update) -> WorldWrite {
        WorldWrite {
            pos: self.pos,
            expected: self.state,
            new,
            update,
        }
    }
}

#[derive(PartialEq, Eq)]
enum Update {
    Liquid,
    Waterlogged,
    Block,
    Reaction,
    Vapor,
    Discard,
}

pub(super) struct WorldWrite {
    pos: Pos,
    expected: BlockStateId,
    new: BlockStateId,
    update: Update,
}

impl WorldWrite {
    pub(super) fn is_reaction(&self) -> bool {
        self.update == Update::Reaction
    }

    /// A previous outlet may have changed this surface during the transfer.
    /// Commit the corresponding prepared contents only if the write succeeds.
    pub(super) fn apply(self, game: &mut Game<'_>) -> Option<bool> {
        if state(game, self.pos) != Some(self.expected) {
            return None;
        }
        if self.update == Update::Discard {
            return Some(false);
        }
        if self.update == Update::Vapor {
            let random = &mut game.world.random;
            let pitch = 2.6 + (random.next_float() - random.next_float()) * 0.8;
            game.with_level(|_, level, _| {
                level.native_play_sound(
                    "minecraft:block.fire.extinguish",
                    self.pos.map(f64::from),
                    4,
                    0.5,
                    pitch,
                );
            });
            return Some(false);
        }
        if !game.native_set_block(game.dim.id(), self.pos, self.new, UPDATE_ALL) {
            return None;
        }
        if self.update == Update::Waterlogged {
            game.with_level(|_, level, ticks| {
                level.native_schedule_fluid_tick(ticks, self.pos, "minecraft:water", 1);
            });
        }
        Some(self.update != Update::Liquid)
    }
}

#[derive(Default)]
pub(super) struct Buffer {
    pub(super) fluid: Option<Stack>,
    pub(super) pulling: bool,
}

impl Buffer {
    /// Keep ownership of fluid debited from this inlet if a planned outlet
    /// could not apply its world change.
    pub(super) fn refund(&mut self, returned: Stack) {
        if let Some(stored) = &mut self.fluid {
            debug_assert_eq!(stored.key, returned.key);
            stored.amount += returned.amount;
            debug_assert!(stored.amount <= CAPACITY);
        } else {
            self.fluid = Some(returned);
        }
    }

    pub(super) fn read(tag: Option<&Tag>, face: Direction) -> Option<Self> {
        let Some(tag) = tag else {
            return Some(Self::default());
        };
        let Tag::Compound(fields) = tag else {
            return None;
        };
        if fields.keys().any(|key| {
            !matches!(
                key.to_string_lossy().as_str(),
                "Fluid" | "Location" | "Pulling"
            )
        }) {
            return None;
        }
        let location = fields.get(&"Location".into())?;
        let Tag::String(stored_face) = location.get("Face")? else {
            return None;
        };
        if !stored_face
            .to_string_lossy()
            .eq_ignore_ascii_case(face.name())
            || !matches!(location.get("Pos"), Some(Tag::IntArray(pos)) if pos.len() == 3)
        {
            return None;
        }
        let Some(Tag::Byte(pulling @ (0 | 1))) = fields.get(&"Pulling".into()) else {
            return None;
        };
        let content = Tag::Compound(
            fields
                .get(&"Fluid".into())
                .cloned()
                .map_or_else(Compound::new, |fluid| {
                    Compound::from([("Fluid".into(), fluid)])
                }),
        );
        let fluid = codec::read_content(Some(&content), CAPACITY).ok()?;
        if fluid.as_ref().is_some_and(|stack| {
            !stack.key.components.is_empty()
                || !Kind::from_id(&stack.key.id)
                    .is_some_and(|kind| kind.has_world_state() || kind == Kind::Honey)
        }) {
            return None;
        }
        Some(Self {
            fluid,
            pulling: *pulling != 0,
        })
    }

    pub(super) fn write(&self, pos: Pos, face: Direction) -> Option<Tag> {
        let Tag::Compound(mut fields) = codec::write_content(self.fluid.as_ref(), CAPACITY).ok()?
        else {
            return None;
        };
        fields.insert("Pulling".into(), Tag::Byte(i8::from(self.pulling)));
        fields.insert(
            "Location".into(),
            Tag::Compound(Compound::from([
                (
                    "Face".into(),
                    Tag::String(face.name().to_ascii_uppercase().as_str().into()),
                ),
                ("Pos".into(), Tag::IntArray(pos.to_vec())),
            ])),
        );
        Some(Tag::Compound(fields))
    }

    pub(super) fn drain(
        &mut self,
        game: &Game<'_>,
        space: &Space,
        stack: &Stack,
        simulate: bool,
    ) -> (u32, Option<WorldWrite>) {
        let kind = Kind::from_id(&stack.key.id);
        let stored = self.fluid.as_mut().filter(|stored| stored.key == stack.key);
        if let Some(stored) = stored {
            let used = stored.amount.min(stack.amount);
            if !simulate {
                stored.amount -= used;
                if stored.amount == 0 {
                    self.fluid = None;
                }
            }
            return (used, None);
        }
        let Some((kind, available)) = space.source().filter(|&(source, _)| Some(source) == kind)
        else {
            return (0, None);
        };
        let amount = stack.amount.min(available);
        let Some(world) = space.drain(game, kind) else {
            return (0, None);
        };
        if !simulate {
            self.pulling = true;
            self.fluid = (amount < available).then(|| Stack {
                key: stack.key.clone(),
                amount: available - amount,
            });
            return (amount, world);
        }
        (amount, None)
    }

    pub(super) fn fill(
        &mut self,
        game: &Game<'_>,
        space: &Space,
        stack: &Stack,
    ) -> (u32, Option<WorldWrite>) {
        let Some(kind) = Kind::from_id(&stack.key.id) else {
            return (0, None);
        };
        if let Some(reaction) = space.reaction(game, kind) {
            // Create changes the exposed block during its fill probe before
            // accounting for fluid accepted by the outlet.
            return (0, Some(reaction));
        }
        let Some(world) = space.fill(game, kind) else {
            return (0, None);
        };
        let previous = self
            .fluid
            .as_ref()
            .filter(|stored| stored.key == stack.key)
            .map_or(0, |stored| stored.amount);
        // OpenEndFluidHandler chooses the effect from the stored fluid before
        // filling. The first water/lava transfer into an empty end is 1 mB.
        let amount = if previous == 0 {
            stack.amount.min(1)
        } else {
            stack.amount.min(CAPACITY - previous)
        };
        self.pulling = false;
        if previous + amount == CAPACITY {
            self.fluid = None;
            (amount, Some(world))
        } else {
            self.fluid = Some(Stack {
                key: stack.key.clone(),
                amount: previous + amount,
            });
            (amount, None)
        }
    }
}
