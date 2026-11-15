// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT

use crate::kinetics::Pos;

/// Catnip's ShadeSeparatingSuperByteBuffer samples the level after insetting
/// each vertex by 1/16 toward the centre of the assembly's origin block.
/// Affine transforms preserve that inset. Work in camera-relative coordinates
/// until the last addition so distant world coordinates keep their precision.
pub fn sample_cell(camera: [f64; 3], centre: [f32; 3], vertex: [f32; 3]) -> Pos {
    std::array::from_fn(|axis| {
        let centre = f64::from(centre[axis]);
        let inset = centre + (f64::from(vertex[axis]) - centre) * (15.0 / 16.0);
        (camera[axis] + inset).floor() as i32
    })
}

/// The baked and sampled light contributions combine independently. The
/// low byte contains sky light and the next byte contains block light.
pub fn max_light(baked: u32, level: u32) -> u32 {
    let sky = (baked & 0xff).max(level & 0xff);
    let block = (baked >> 8 & 0xff).max(level >> 8 & 0xff);
    sky | (block << 8)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn sample_insets_before_flooring_on_both_sides_of_a_boundary() {
        assert_eq!(
            sample_cell([0.0; 3], [0.5; 3], [16.0, -16.0, 1.0]),
            [15, -15, 0]
        );
        assert_eq!(
            sample_cell([-16.0, 64.0, 16.0], [0.5; 3], [-0.1, 2.0, 16.0]),
            [-17, 65, 31]
        );
    }

    #[test]
    fn the_transformed_inset_matches_local_inset_then_rotation() {
        let camera = [-43.25, 16.0, 72.5];
        let centre = [15.75, -3.0, 5.25];
        // Rotation about X, followed by a camera-relative translation.
        let local = [0.0, 6.0, -4.0];
        let to_relative = |[x, y, z]: [f32; 3]| {
            [
                centre[0] + x - 0.5,
                centre[1] - (z - 0.5),
                centre[2] + y - 0.5,
            ]
        };
        let explicit = to_relative(local.map(|v| (v - 0.5) * (15.0 / 16.0) + 0.5));
        let expected = std::array::from_fn(|i| (camera[i] + f64::from(explicit[i])).floor() as i32);
        assert_eq!(sample_cell(camera, centre, to_relative(local)), expected);
    }

    #[test]
    fn far_samples_are_independent_of_sub_block_camera_position() {
        assert_eq!(
            sample_cell([29_999_997.125, 0.0, 0.0], [0.5; 3], [0.875, 2.0, 0.0]),
            [29_999_997, 1, 0]
        );
        assert_eq!(
            sample_cell([29_999_997.5, 0.0, 0.0], [0.125, 0.5, 0.5], [0.5, 2.0, 0.0]),
            [29_999_997, 1, 0]
        );
    }

    #[test]
    fn world_sky_and_baked_block_light_both_survive() {
        assert_eq!(max_light(0xd030, 0x70f0), 0xd0f0);
        assert_eq!(max_light(0x2070, 0xe040), 0xe070);
        assert_eq!(max_light(0, 0x2000), 0x2000);
    }
}
