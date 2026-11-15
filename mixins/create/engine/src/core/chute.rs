// Copyright (c) The Create Team / The Creators of Create
// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT

//! Chute transit and the ordinary Chute's `ItemHelper.extract(UPTO)`.

pub const ENTRY: f32 = 1.0;
const WAIT: f32 = 0.5;
const PULL_LIMIT: u32 = 16;

#[derive(Clone, Copy, Debug, PartialEq)]
pub enum Step {
    Position(f32),
    Output,
}

pub fn motion(push: f32, pull: f32) -> f32 {
    let fan = (push + pull) / 64.0;
    (fan.clamp(-20.0, 20.0) + if fan <= 0.0 { -4.0 } else { 0.0 }) / 20.0
}

pub fn suction_range(speed: f32) -> f32 {
    if speed >= 128.0 {
        3.0
    } else if speed >= 64.0 {
        2.0
    } else if speed >= 32.0 {
        1.0
    } else {
        (speed / 32.0).max(0.0)
    }
}

pub fn step(position: f32, motion: f32, can_output: impl FnOnce() -> bool) -> Step {
    let next = position + motion;
    if motion == 0.0 {
        return Step::Position(next);
    }
    let (past_midpoint, past_end) = if motion > 0.0 {
        (next > WAIT, next > 1.0)
    } else {
        (next < WAIT, next < 0.0)
    };
    if !past_midpoint {
        return Step::Position(next);
    }
    if !can_output() {
        return Step::Position(WAIT);
    }
    if past_end {
        Step::Output
    } else {
        Step::Position(next)
    }
}

pub struct Source<'a, T> {
    pub slot: usize,
    pub stack: &'a T,
    pub count: u32,
    pub maximum: u32,
}

/// Preserve source order. The first accessible stack chooses the identity;
/// later candidates of that identity are skipped when they would exceed its
/// stack maximum, as in ItemHelper.canItemStackAmountsStack.
pub fn pull_plan<'a, T: 'a>(
    slots: impl IntoIterator<Item = Source<'a, T>>,
    same: impl Fn(&T, &T) -> bool,
) -> Vec<(usize, u32)> {
    let mut result = Vec::new();
    let mut identity = None;
    let mut total = 0;
    for slot in slots {
        let count = slot.count.min(slot.maximum).min(PULL_LIMIT - total);
        if count == 0
            || identity
                .is_some_and(|first| !same(first, slot.stack) || total + count > slot.maximum)
        {
            continue;
        }
        identity = Some(slot.stack);
        result.push((slot.slot, count));
        total += count;
        if total == PULL_LIMIT {
            break;
        }
    }
    result
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn gravity_uses_the_java_f32_threshold_and_waits_at_the_midpoint() {
        let mut pos = ENTRY;
        let gravity = motion(0.0, 0.0);
        for expected in [0.8, 0.6, 0.40000004, 0.20000003, 2.9802322e-8] {
            assert_eq!(step(pos, gravity, || true), Step::Position(expected));
            pos = expected;
        }
        assert_eq!(step(pos, gravity, || true), Step::Output);
        assert_eq!(step(0.6, gravity, || false), Step::Position(0.5));
        assert_eq!(step(0.5, gravity, || false), Step::Position(0.5));
        assert_eq!(step(0.5, gravity, || true), Step::Position(0.3));
        assert_eq!(step(0.10000001, gravity, || true), Step::Output);
        assert_eq!(
            step(0.8, gravity, || panic!("above midpoint")),
            Step::Position(0.6)
        );
    }

    #[test]
    fn a_fan_reverses_the_item_and_the_side_that_can_block_it() {
        let upward = motion(128.0, 0.0);
        assert_eq!(upward, 0.1);
        assert_eq!(motion(-128.0, 0.0), -0.3);
        assert_eq!(
            step(0.4, upward, || panic!("at midpoint")),
            Step::Position(0.5)
        );
        assert_eq!(step(0.5, upward, || false), Step::Position(0.5));
        assert_eq!(step(0.9, upward, || true), Step::Position(1.0));
        assert_eq!(step(1.0, upward, || true), Step::Output);
    }

    #[test]
    fn lower_suction_uses_the_source_thresholds() {
        for (speed, range) in [
            (-128.0, 0.0),
            (16.0, 0.5),
            (32.0, 1.0),
            (63.0, 1.0),
            (64.0, 2.0),
            (127.0, 2.0),
            (128.0, 3.0),
            (256.0, 3.0),
        ] {
            assert_eq!(suction_range(speed), range);
        }
    }

    #[test]
    fn slot_order_and_component_identity_match_the_java_pull() {
        let rows = [
            (0, "wheat", 10, 64),
            (1, "plank", 5, 64),
            (4, "tagged wheat", 7, 64),
            (5, "wheat", 12, 64),
        ];
        let slots = rows.iter().map(|(slot, stack, count, maximum)| Source {
            slot: *slot,
            stack,
            count: *count,
            maximum: *maximum,
        });
        assert_eq!(pull_plan(slots, |a, b| a == b), [(0, 10), (5, 6)]);
        let rows = [(0, "small", 6, 8), (1, "small", 4, 8), (2, "small", 2, 8)];
        let slots = rows.iter().map(|(slot, stack, count, maximum)| Source {
            slot: *slot,
            stack,
            count: *count,
            maximum: *maximum,
        });
        assert_eq!(pull_plan(slots, |a, b| a == b), [(0, 6), (2, 2)]);
    }
}
