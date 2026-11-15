// Copyright (c) The Create Team / The Creators of Create
// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT
//! PipeConnection and FluidNetwork rules from Create 6.0.10.
//! The caller supplies per-block ticking order and endpoint storage.

use crate::placement::Direction;

/// The default pump range counts the endpoint as one of its blocks.
pub const DEFAULT_PUMP_RANGE: i32 = 16;

pub fn other_port([first, second]: [Direction; 2], inlet: Direction) -> Option<Direction> {
    if inlet == first {
        Some(second)
    } else if inlet == second {
        Some(first)
    } else {
        None
    }
}

/// Isolated pipes keep two opposite ports. One real connection uses its
/// opposite as the open end. Two or more neighbors determine the shape.
pub fn placed_ports(mut joined: [bool; 6], preferred: Direction) -> [bool; 6] {
    let mut real = Direction::ALL
        .into_iter()
        .filter(|&side| joined[side as usize]);
    if let Some(first) = real.next() {
        if real.next().is_none() {
            joined[first.opposite() as usize] = true;
        }
    } else {
        joined[preferred as usize] = true;
        joined[preferred.opposite() as usize] = true;
    }
    joined
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Fluid {
    Water,
    Lava,
    Honey,
    Chocolate,
}

impl Fluid {
    pub fn from_id(id: &str) -> Option<Self> {
        match id {
            "minecraft:water" => Some(Self::Water),
            "minecraft:lava" => Some(Self::Lava),
            "create:honey" => Some(Self::Honey),
            "create:chocolate" => Some(Self::Chocolate),
            _ => None,
        }
    }

    pub fn id(self) -> &'static str {
        match self {
            Self::Water => "minecraft:water",
            Self::Lava => "minecraft:lava",
            Self::Honey => "create:honey",
            Self::Chocolate => "create:chocolate",
        }
    }

    /// Whether this can exist as a fluid block in Horizon.
    pub fn has_world_state(self) -> bool {
        matches!(self, Self::Water | Self::Lava)
    }
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Flow {
    pub fluid: Fluid,
    pub progress: f32,
}

impl Flow {
    pub fn complete(self) -> Option<Fluid> {
        (self.progress == 1.0).then_some(self.fluid)
    }
}

#[derive(Clone, Copy, Debug, Default, PartialEq)]
pub struct Faces {
    pub inlet: Option<Flow>,
    pub outlet: Option<Flow>,
}

impl Faces {
    pub fn complete(self, fluid: Fluid) -> bool {
        self.inlet.and_then(Flow::complete) == Some(fluid)
            && self.outlet.and_then(Flow::complete) == Some(fluid)
    }

    /// A complete flow can turn around; an incomplete one is cleared on a
    /// single-pressure reversal (`flipFlowsIfPressureReversed`).
    pub fn reversed(self) -> Self {
        Self {
            inlet: self.outlet.filter(|flow| flow.complete().is_some()),
            outlet: self.inlet.filter(|flow| flow.complete().is_some()),
        }
    }

    pub fn tick(&mut self, input: Option<Fluid>, pressure: f32) {
        let internal = self.inlet.and_then(Flow::complete);
        self.inlet = advance_face(self.inlet, input, pressure);
        self.outlet = advance_face(self.outlet, internal, pressure);
    }
}

pub fn advance_face(before: Option<Flow>, input: Option<Fluid>, pressure: f32) -> Option<Flow> {
    let input = input?;
    let progress = match before {
        Some(flow) if flow.fluid == input => flow.progress,
        Some(_) => return None,
        None => 0.0,
    };
    Some(Flow {
        fluid: input,
        progress: (progress + progress_step(pressure)).min(1.0),
    })
}

fn progress_step(pressure: f32) -> f32 {
    1.0 / 32.0 + (pressure / 128.0).clamp(0.0, 1.0) * 31.0 / 32.0
}

#[derive(Clone, Copy, Debug, Default, PartialEq)]
pub struct Pressure {
    pub inbound: f32,
    pub outward: f32,
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct DirectedFlow {
    pub flow: Flow,
    pub inbound: bool,
}

impl Pressure {
    fn for_direction(self, inbound: bool) -> f32 {
        if inbound { self.inbound } else { self.outward }
    }

    fn preferred_inbound(self) -> bool {
        self.inbound > self.outward
    }

    pub fn flip(self, mut flow: DirectedFlow) -> Option<DirectedFlow> {
        let single_pressure = (self.inbound > 0.0) != (self.outward > 0.0);
        if single_pressure && flow.inbound != self.preferred_inbound() {
            flow.flow.complete()?;
            flow.inbound = !flow.inbound;
        }
        Some(flow)
    }

    /// PipeConnection keeps the active direction until the alternate can
    /// supply fluid. Ties first try the outward flow, then the inbound flow.
    pub fn tick(
        self,
        current: Option<DirectedFlow>,
        external: Option<Fluid>,
        internal: Option<Fluid>,
    ) -> Option<DirectedFlow> {
        let fluid = |inbound| if inbound { external } else { internal };
        let preferred = self.preferred_inbound();
        let mut flow = if let Some(active) = current {
            if (self.inbound == 0.0 && self.outward == 0.0)
                || fluid(active.inbound) != Some(active.flow.fluid)
            {
                return None;
            }
            if active.inbound != preferred
                && let Some(available) = fluid(preferred)
            {
                DirectedFlow {
                    flow: Flow {
                        fluid: available,
                        progress: 0.0,
                    },
                    inbound: preferred,
                }
            } else {
                active
            }
        } else {
            [preferred, !preferred].into_iter().find_map(|inbound| {
                let available = fluid(inbound)?;
                (self.for_direction(inbound) > 0.0).then_some(DirectedFlow {
                    flow: Flow {
                        fluid: available,
                        progress: 0.0,
                    },
                    inbound,
                })
            })?
        };
        flow.flow.progress =
            (flow.flow.progress + progress_step(self.for_direction(flow.inbound))).min(1.0);
        Some(flow)
    }
}

pub fn transfer_rate(pressure: f32) -> i32 {
    (pressure / 2.0).max(1.0) as i32
}

/// A pump shares its pressure across all valid faces at the same depth.
pub fn pressure_divisor(faces_at_depth: usize) -> usize {
    faces_at_depth.saturating_sub(1).max(1)
}

/// Distribute a source's simulated drain in discovery order. An outlet that
/// refuses part of its share drops out, and the rest divide the excess.
pub fn distribute(amount: u32, outputs: usize, mut fill: impl FnMut(usize, u32) -> u32) -> u32 {
    if outputs == 1 && amount != 0 {
        return fill(0, amount).min(amount);
    }
    let mut remaining = amount;
    let mut available: Vec<_> = (0..outputs).collect();
    while remaining > 0 && !available.is_empty() {
        let count = available.len() as u32;
        let share = remaining / count;
        let mut remainder = remaining % count;
        available.retain(|&index| {
            let quota = share + u32::from(remainder > 0);
            remainder = remainder.saturating_sub(1);
            if quota == 0 {
                return true;
            }
            let accepted = fill(index, quota).min(quota);
            remaining -= accepted;
            accepted == quota
        });
    }
    amount - remaining
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn overlapping_pressure_can_start_against_its_preferred_direction() {
        let water = Some(Fluid::Water);
        let pressure = Pressure {
            inbound: 32.0,
            outward: 8.0,
        };
        let outbound = pressure.tick(None, None, water).unwrap();
        assert!(!outbound.inbound);
        assert_eq!(outbound.flow.progress, progress_step(8.0));
        let inbound = pressure.tick(Some(outbound), water, water).unwrap();
        assert!(inbound.inbound);
        assert_eq!(inbound.flow.progress, progress_step(32.0));
        assert_eq!(pressure.flip(outbound), Some(outbound));
        assert_eq!(
            Pressure {
                inbound: 32.0,
                outward: 0.0
            }
            .flip(outbound),
            None
        );

        let tie = Pressure {
            inbound: 16.0,
            outward: 16.0,
        };
        assert!(!tie.tick(None, water, water).unwrap().inbound);
        assert!(tie.tick(None, water, None).unwrap().inbound);
        assert_eq!(tie.tick(Some(inbound), None, water), None);
    }

    #[test]
    fn create_fluids_have_canonical_ids_without_world_states() {
        for (id, kind) in [
            ("create:honey", Fluid::Honey),
            ("create:chocolate", Fluid::Chocolate),
        ] {
            assert_eq!(Fluid::from_id(id), Some(kind));
            assert_eq!(kind.id(), id);
            assert!(!kind.has_world_state());
        }
        assert!(Fluid::Water.has_world_state() && Fluid::Lava.has_world_state());
        assert_eq!(Fluid::from_id("create:tea"), None);
    }

    #[test]
    fn placement_joins_elbows_and_route_requires_the_reciprocal_port() {
        use Direction::{Down, East, North, South, West};
        let mask = |sides: &[Direction]| Direction::ALL.map(|side| sides.contains(&side));
        assert_eq!(placed_ports(mask(&[]), North), mask(&[North, South]));
        assert_eq!(placed_ports(mask(&[West]), North), mask(&[West, East]));
        assert_eq!(
            placed_ports(mask(&[West, North]), East),
            mask(&[West, North])
        );
        assert_eq!(
            placed_ports(mask(&[West, North, Down]), East),
            mask(&[West, North, Down])
        );
        assert_eq!(other_port([West, North], West), Some(North));
        assert_eq!(other_port([West, North], North), Some(West));
        assert_eq!(other_port([West, North], East), None);
    }

    #[test]
    fn branch_pressure_and_discovery_order_shares() {
        assert_eq!([2, 3, 4, 6].map(pressure_divisor), [1, 2, 3, 5]);
        for (total, capacity, expected) in [
            (16, [100, 100, 100], [6, 5, 5]),
            (16, [3, 100, 0], [3, 13, 0]),
            (4, [0, 0, 100], [0, 0, 4]),
            (16, [1, 2, 3], [1, 2, 3]),
            (1, [0, 0, 0], [0, 0, 0]),
        ] {
            let mut filled = [0; 3];
            let sent = distribute(total, filled.len(), |index, amount| {
                let accepted = amount.min(capacity[index] - filled[index]);
                filled[index] += accepted;
                accepted
            });
            assert_eq!(filled, expected);
            assert_eq!(sent, expected.into_iter().sum());
        }
    }

    #[test]
    fn six_java_startups_follow_device_registration_order() {
        for (length, pressure, reverse, first, rate) in [
            (1, 32.0, false, 9, 16),
            (3, 32.0, false, 23, 16),
            (5, 32.0, false, 37, 16),
            (3, 32.0, true, 24, 16),
            (3, 4.0, false, 101, 2),
            (3, 64.0, false, 11, 32),
        ] {
            let mut faces = vec![Faces::default(); length];
            let mut first_transfer = None;
            for tick in 1..=115 {
                for i in 0..length {
                    let index = if reverse { length - 1 - i } else { i };
                    let fluid = Fluid::Water;
                    if index == 0 && tick >= 4 && faces.iter().all(|f| f.complete(fluid)) {
                        first_transfer.get_or_insert(tick);
                    }
                    let inlet = if index == 0 {
                        Some(fluid)
                    } else {
                        faces[index - 1].outlet.and_then(Flow::complete)
                    };
                    faces[index].tick(inlet, pressure);
                }
            }
            assert_eq!(first_transfer, Some(first));
            assert_eq!(transfer_rate(pressure), rate);
        }
    }

    #[test]
    fn fluid_switch_clears_the_face_before_restarting() {
        let mut faces = Faces::default();
        faces.tick(Some(Fluid::Water), 128.0);
        faces.tick(Some(Fluid::Lava), 128.0);
        assert_eq!(faces.inlet, None);
        assert_eq!(faces.outlet.and_then(Flow::complete), Some(Fluid::Water));
        faces.tick(Some(Fluid::Lava), 128.0);
        assert_eq!(faces.inlet.and_then(Flow::complete), Some(Fluid::Lava));
        assert_eq!(faces.outlet, None);
    }

    #[test]
    fn reversal_keeps_only_complete_connections() {
        let faces = Faces {
            inlet: Some(Flow {
                fluid: Fluid::Water,
                progress: 1.0,
            }),
            outlet: Some(Flow {
                fluid: Fluid::Water,
                progress: 0.25,
            }),
        };
        assert_eq!(
            faces.reversed(),
            Faces {
                inlet: None,
                outlet: faces.inlet
            }
        );
    }
}
