// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT

use crate::kinetics::{Axis, Pos};

#[derive(Clone, Copy)]
pub enum Motion {
    Rotary(Axis),
    Translating,
    Piston { poles: usize },
}

/// Create's capture bounds and the swept bounds of a rotary contraption.
/// Piston pole cells already describe its extension collision box.
pub fn local_bounds(
    blocks: impl IntoIterator<Item = Pos>,
    motion: Motion,
) -> Option<[[f64; 3]; 2]> {
    let mut blocks = blocks.into_iter().peekable();
    let first = blocks.peek()?.map(f64::from);
    let mut min = first;
    let mut max = first.map(|coordinate| coordinate + 1.0);
    let mut count = 0;
    let axis = match motion {
        Motion::Rotary(axis) => Some(axis.index()),
        _ => None,
    };
    let mut radius_sq = 0.0_f64;
    for block in blocks {
        let pos = block.map(f64::from);
        for i in 0..3 {
            min[i] = min[i].min(pos[i]);
            max[i] = max[i].max(pos[i] + 1.0);
        }
        if let Some(axis) = axis {
            let a = pos[(axis + 1) % 3];
            let b = pos[(axis + 2) % 3];
            radius_sq = radius_sq.max(a * a + b * b);
        }
        count += 1;
    }
    // Contraption.searchMovedStructure seeds the bounds with the origin cube.
    // PistonContraption starts with a point when it captures extra cargo and
    // uses only the extension box when the pole train is the whole payload.
    let origin_max = match motion {
        Motion::Piston { poles } if count <= poles => return Some([min, max]),
        Motion::Piston { .. } => 0.0,
        _ => 1.0,
    };
    let radius = radius_sq.sqrt().ceil();
    for i in 0..3 {
        if axis.is_some_and(|axis| i != axis) {
            min[i] = -radius - 1.0;
            max[i] = radius + 2.0;
        } else {
            min[i] = min[i].min(0.0);
            max[i] = max[i].max(origin_max);
        }
    }
    Some([min, max])
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn rotary_bounds_round_radius_up_and_keep_the_axial_extent() {
        let blocks = [[2, 4, 2], [-1, 5, 0]];
        assert_eq!(
            local_bounds(blocks, Motion::Rotary(Axis::Y)),
            Some([[-4.0, 0.0, -4.0], [5.0, 6.0, 5.0]])
        );
        assert_eq!(
            local_bounds([[3, 0, 0]], Motion::Rotary(Axis::X)),
            Some([[0.0, -1.0, -1.0], [4.0, 2.0, 2.0]])
        );
    }

    #[test]
    fn translating_bounds_include_the_origin_cube_and_whole_cargo_blocks() {
        assert_eq!(
            local_bounds([[1, -2, 0], [3, -1, 2]], Motion::Translating),
            Some([[0.0, -2.0, 0.0], [4.0, 1.0, 3.0]])
        );
        assert_eq!(local_bounds([], Motion::Translating), None);
    }

    #[test]
    fn piston_extension_only_excludes_the_origin_and_cargo_adds_the_origin_point() {
        let poles = Motion::Piston { poles: 2 };
        assert_eq!(
            local_bounds([[1, 0, 0], [2, 0, 0]], poles),
            Some([[1.0, 0.0, 0.0], [3.0, 1.0, 1.0]])
        );
        assert_eq!(
            local_bounds([[1, 0, 0], [2, 0, 0], [3, 1, 1]], poles),
            Some([[0.0, 0.0, 0.0], [4.0, 2.0, 2.0]])
        );
    }
}
