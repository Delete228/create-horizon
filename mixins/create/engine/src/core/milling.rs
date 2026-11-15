// Copyright (c) The Create Team / The Creators of Create
// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT
//! MillstoneBlockEntity.tick/getProcessingSpeed and ProcessingOutput.rollOutput.
//! Inventory mutation and recipe lookup belong to the host adapter.

pub const INPUT_SLOTS: usize = 1;
pub const OUTPUT_SLOTS: usize = 9;
/// `ItemStackHandler.getSlotLimit` in the pinned NeoForge release. Insertion
/// also applies the individual item's stack limit, but tick checks this value.
pub const SLOT_LIMIT: u32 = 99;

/// This method returns one even at zero RPM; `tick` separately checks power.
pub fn processing_speed(rpm: f32) -> i32 {
    ((rpm / 16.0).abs() as i32).clamp(1, 512)
}

/// MillstoneBlockEntity.spawnParticles and Catnip VecHelper.rotate/offsetRandomly.
pub fn particle_vectors(angle_draw: f32, rpm: f32, jitter: [f32; 3]) -> ([f64; 3], [f64; 3]) {
    use crate::{kinetics::Axis, source_trig::rotate};

    let offset = rotate([0.0, 0.0, 0.5], angle_draw * 360.0, Axis::Y);
    let target = rotate(offset, if rpm > 0.0 { 25.0 } else { -25.0 }, Axis::Y);
    let velocity = std::array::from_fn(|i| {
        target[i] - offset[i] + f64::from((jitter[i] - 0.5) * 2.0 * (1.0 / 128.0))
    });
    (offset, velocity)
}

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub struct MillCycle {
    pub timer: i32,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Action {
    None,
    Armed,
    Processing,
    Process,
}

impl MillCycle {
    /// `duration` is None when no recipe currently matches. Create retries such
    /// an input after 100 processing units. A completed cycle must recheck the
    /// recipe before consuming anything, because the input may have changed.
    pub fn tick(
        &mut self,
        rpm: f32,
        outputs: impl IntoIterator<Item = u32>,
        input_present: bool,
        duration: Option<i32>,
    ) -> Action {
        if rpm == 0.0 || outputs.into_iter().any(|count| count == SLOT_LIMIT) {
            return Action::None;
        }
        if self.timer > 0 {
            self.timer -= processing_speed(rpm);
            return if self.timer <= 0 {
                Action::Process
            } else {
                Action::Processing
            };
        }
        if !input_present {
            return Action::None;
        }
        self.timer = duration.unwrap_or(100);
        Action::Armed
    }
}

/// Create rolls each unit independently, retains draws equal to the chance,
/// and consumes no random values for a guaranteed result.
pub fn roll_count(count: u32, chance: f32, mut next_float: impl FnMut() -> f32) -> u32 {
    if chance < 1.0 {
        (0..count).filter(|_| next_float() <= chance).count() as u32
    } else {
        count
    }
}

/// Empty-hand collection prioritises all outputs; only an empty output
/// inventory allows the input to be retrieved.
pub fn collect_input(outputs: impl IntoIterator<Item = u32>) -> bool {
    outputs.into_iter().all(|count| count == 0)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn sixty_four_rpm_processes_one_item_after_an_arming_tick_and_fifty_ticks() {
        let mut cycle = MillCycle::default();
        assert_eq!(cycle.tick(64.0, [], true, Some(200)), Action::Armed);
        for _ in 0..49 {
            assert_eq!(cycle.tick(64.0, [], true, Some(200)), Action::Processing);
        }
        assert_eq!(cycle.tick(64.0, [], true, Some(200)), Action::Process);
        assert_eq!(cycle.timer, 0);
        assert_eq!(cycle.tick(64.0, [], true, Some(200)), Action::Armed);
    }

    #[test]
    fn full_output_and_missing_power_pause_without_resetting_progress() {
        let mut cycle = MillCycle { timer: 53 };
        assert_eq!(cycle.tick(0.0, [1], true, Some(200)), Action::None);
        assert_eq!(cycle.tick(256.0, [99], true, Some(200)), Action::None);
        assert_eq!(cycle.timer, 53);
        assert_eq!(
            cycle.tick(-256.0, [64], true, Some(200)),
            Action::Processing
        );
        assert_eq!(cycle.timer, 37);
    }

    #[test]
    fn in_flight_recipe_and_input_changes_are_only_rechecked_when_processing() {
        let mut cycle = MillCycle { timer: 1 };
        assert_eq!(cycle.tick(512.0, [], false, None), Action::Process);
        assert_eq!(cycle.timer, -31);
        assert_eq!(cycle.tick(512.0, [], false, None), Action::None);
        assert_eq!(cycle.tick(512.0, [], true, None), Action::Armed);
        assert_eq!(cycle.timer, 100);
        // Source does not run process() for zero-duration recipes.
        cycle.timer = 0;
        assert_eq!(cycle.tick(512.0, [], true, Some(0)), Action::Armed);
        assert_eq!(cycle.timer, 0);
    }

    #[test]
    fn rolls_are_per_unit_with_source_boundary_and_rng_consumption() {
        let mut values = [0.0, 0.5, 0.500001, 0.9].into_iter();
        assert_eq!(roll_count(4, 0.5, || values.next().unwrap()), 2);
        assert_eq!(
            roll_count(64, 1.0, || panic!("guaranteed result drew RNG")),
            64
        );
        assert_eq!(roll_count(1, 0.0, || 0.0), 1);
    }

    #[test]
    fn particle_vectors_match_pinned_catnip_float_rounding() {
        // Raw draws and VecHelper results from RandomSource.create(17) in
        // Minecraft 1.21.1 with the pinned Catnip version.
        let angle = f32::from_bits(0x3f3b_78c4);
        let jitter = [0x3f4b_c3e2, 0x3f32_86df, 0x3f17_056c].map(f32::from_bits);
        for (rpm, expected_velocity) in [
            (
                -256.0,
                [
                    0x3fb3_1c4a_98c1_c500,
                    0x3f69_436f_8000_0000,
                    0xbfca_08c4_e0bc_a5f0,
                ],
            ),
            (
                256.0,
                [
                    0x3f9c_648b_a8e1_6800,
                    0x3f69_436f_8000_0000,
                    0x3fcb_b9a5_327f_2090,
                ],
            ),
        ] {
            let (offset, velocity) = particle_vectors(angle, rpm, jitter);
            assert_eq!(
                offset.map(f64::to_bits),
                [0xbfdf_cd64_2000_0000, 0, 0xbfac_697a_c000_0000]
            );
            assert_eq!(velocity.map(f64::to_bits), expected_velocity);
        }
    }

    #[test]
    fn collection_returns_outputs_before_input() {
        assert!(collect_input([0; 9]));
        assert!(!collect_input([0, 0, 1, 0, 0, 0, 0, 0, 0]));
    }
}
