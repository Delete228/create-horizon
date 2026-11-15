// Copyright (c) The Create Team / The Creators of Create
// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT

//! Single-axis bearings in Create's `ContinuousOBBCollider`.
use super::contact::ContactBox;
use crate::{
    kinetics::{Axis, Pos},
    source_trig::{cos, sin},
};

const BODY_INFLATION: f64 = 1.0e-7;
const SEPARATION_EPSILON: f64 = 1.0e-4;
const Y: usize = 1;
const AXES: [[f64; 3]; 3] = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]];

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct RotaryContact {
    pub separation: [f64; 3],
    pub impact_fraction: f64,
    pub surface: bool,
    pub normal: [f64; 3],
    /// The world-oriented offset from the midpoint between the body center and feet.
    pub location: [f64; 3],
}

fn dot(left: [f64; 3], right: [f64; 3]) -> f64 {
    left[0] * right[0] + left[1] * right[1] + left[2] * right[2]
}

fn projected_extent(axis: [f64; 3], extent: [f64; 3]) -> f64 {
    dot(axis.map(f64::abs), extent)
}

fn signed_epsilon(depth: f64) -> f64 {
    if depth == 0.0 {
        depth
    } else {
        depth + SEPARATION_EPSILON.copysign(depth)
    }
}

struct AxisTest {
    direction: [f64; 3],
    offset: f64,
    block_extent: f64,
    body_extent: f64,
    velocity: f64,
    block_axis: bool,
}

struct BoxResponse {
    separation: [f64; 3],
    impact: f64,
    normal: [f64; 3],
    location: [f64; 3],
}

fn box_response(
    axes: impl IntoIterator<Item = AxisTest>,
    up: [f64; 3],
    max_step: f32,
) -> Option<BoxResponse> {
    let mut minimum = (f64::MAX, [0.0; 3]);
    let mut normal = (f64::MAX, [0.0; 3]);
    let mut location = [0.0; 3];
    let mut step = f64::MAX;
    let mut entry = -1.0f64;
    let mut exit = f64::MAX;
    for axis in axes {
        let distance = axis.offset.abs();
        let combined_extent = axis.block_extent + axis.body_extent;
        let gap = distance - combined_extent;
        if gap > 0.0 {
            if axis.velocity * axis.offset >= 0.0 || gap > axis.velocity.abs() {
                return None;
            }
            entry = entry.max(gap / axis.velocity.abs());
            exit = exit.min((gap + axis.block_extent + axis.body_extent) / axis.velocity.abs());
        } else {
            let projected_up = dot(axis.direction, up);
            if projected_up != 0.0 {
                let lift =
                    (combined_extent - axis.offset * projected_up.signum()) / projected_up.abs();
                step = step.min(lift);
            }
        }
        // A centered axis has no separating sign. Original later axes win ties.
        if distance != 0.0 {
            let depth = gap.abs().copysign(axis.offset);
            if axis.block_axis && -gap <= normal.0.abs() {
                normal = (depth, axis.direction);
            }
            if -gap <= minimum.0.abs() {
                minimum = (depth, axis.direction);
                let extent = if axis.block_axis {
                    axis.block_extent
                } else {
                    axis.body_extent
                };
                let inset = if depth == 0.0 { 0.0 } else { 0.125 };
                let offset = axis.offset.signum() * -extent - axis.offset.signum() * inset;
                location = axis.direction.map(|n| n * offset);
            }
        }
    }
    let mut separation = [0.0; 3];
    if entry == -1.0 {
        separation = if step <= f64::from(max_step) {
            up.map(|n| n * signed_epsilon(step))
        } else {
            minimum.1.map(|n| n * signed_epsilon(minimum.0))
        };
    }
    // Java keeps a vertical-pass surface candidate even when the swept
    // intervals miss in time. Only a discrete or in-tick hit changes motion.
    let impact = if entry == -1.0 {
        0.0
    } else if entry > 0.0 && entry <= exit && entry < 1.0 {
        entry
    } else {
        -1.0
    };
    Some(BoxResponse {
        separation,
        impact,
        normal: normal.1.map(|n| n * signed_epsilon(normal.0)),
        location,
    })
}

/// Resolve the local player's body against payload collision boxes. The source
/// uses only its vertical pass for a bearing rotating around X or Z.
pub fn rotary_contact(
    axis: Axis,
    anchor: Pos,
    angle: f32,
    body: ContactBox,
    velocity: [f64; 3],
    shapes: impl IntoIterator<Item = ContactBox>,
    max_step: f32,
) -> RotaryContact {
    // AngleHelper.rad and Matrix3d are distinct from the rendered
    // transform. Preserve the 1.21.1 float table lookups used by the collider.
    let radians = (f64::from(-angle) / 180.0 * std::f64::consts::PI) as f32;
    let (sin, cos) = if radians == 0.0 {
        (0.0, 1.0)
    } else {
        (f64::from(sin(radians)), f64::from(cos(radians)))
    };
    let rows = match axis {
        Axis::X => [AXES[0], [0.0, cos, -sin], [0.0, sin, cos]],
        Axis::Y => [[cos, 0.0, sin], AXES[Y], [-sin, 0.0, cos]],
        Axis::Z => [[cos, -sin, 0.0], [sin, cos, 0.0], AXES[2]],
    };
    let columns: [[f64; 3]; 3] = std::array::from_fn(|i| rows.map(|row| row[i]));
    let directions = columns.map(|axis| {
        let length = dot(axis, axis).sqrt();
        axis.map(|v| v / length)
    });
    // Construct the source AABB in this order. Rounding after translation
    // and inflation can decide which of two equal axes supplies the hit.
    let half: [f64; 3] = std::array::from_fn(|i| (body.max[i] - body.min[i]) * 0.5);
    let feet = [body.min[0] + half[0], body.min[Y], body.min[2] + half[2]];
    let world_center = [feet[0], feet[Y] + half[Y], feet[2]];
    let relative = std::array::from_fn(|i| world_center[i] - f64::from(anchor[i]) - 0.5);
    let mut local_feet = rows.map(|row| dot(row, relative) + 0.5);
    local_feet[Y] -= half[Y];
    let mut contracted = body.max;
    if half[Y] > 0.5 {
        // Java locates the body using its full center before contracting
        // the local player's head by 2/16.
        contracted[Y] -= 2.0 / 16.0;
    }
    let local_bounds: [[f64; 2]; 3] = std::array::from_fn(|i| {
        let translation = local_feet[i] - feet[i];
        [
            body.min[i] + translation - BODY_INFLATION,
            contracted[i] + translation + BODY_INFLATION,
        ]
    });
    let extent = local_bounds.map(|[min, max]| (max - min) * 0.5);
    let center: [f64; 3] = std::array::from_fn(|i| local_bounds[i][0] + extent[i]);
    let rotated_extent = rows.map(|axis| projected_extent(axis, extent));
    let broad_extent: [f64; 3] =
        std::array::from_fn(|i| projected_extent(rows[i], [extent[i]; 3]) + 0.5);
    let motion = rows.map(|axis| dot(axis, velocity));
    let original_motion = columns.map(|axis| dot(axis, motion));
    let candidates: Vec<_> = shapes
        .into_iter()
        .filter_map(|shape| {
            let at: [f64; 3] = std::array::from_fn(|i| (shape.min[i] + shape.max[i]) * 0.5);
            let radius = std::array::from_fn(|i| (shape.max[i] - shape.min[i]) * 0.5);
            (0..3)
                .all(|i| (center[i] + motion[i] - at[i]).abs() <= broad_extent[i] + radius[i])
                .then_some((at, radius))
        })
        .collect();
    let mut separation = [0.0; 3];
    let mut impact_fraction = 1.0f64;
    let mut surface = false;
    let mut normal = [0.0; 3];
    let mut location = [0.0; 3];
    for vertical_pass in [false, true] {
        if axis != Axis::Y && !vertical_pass {
            continue;
        }
        for (block, radius) in &candidates {
            let delta = std::array::from_fn::<_, 3, _>(|i| center[i] + separation[i] - block[i]);
            let delta_original = columns.map(|axis| dot(axis, delta));
            let local_axes = (0..3).map(|i| AxisTest {
                direction: AXES[i],
                offset: delta[i],
                block_extent: radius[i],
                body_extent: rotated_extent[i],
                velocity: motion[i],
                block_axis: true,
            });
            let entity_axes = (0..3).map(|i| AxisTest {
                direction: directions[i],
                offset: delta_original[i],
                block_extent: projected_extent(columns[i], *radius),
                body_extent: extent[i],
                velocity: original_motion[i],
                block_axis: false,
            });
            if let Some(response) =
                box_response(local_axes.chain(entity_axes), directions[Y], max_step)
            {
                for (total, component) in separation.iter_mut().zip(response.separation) {
                    *total += component;
                }
                if response.impact >= 0.0 && response.impact < impact_fraction {
                    normal = response.normal;
                    location = response.location;
                    if response.impact > 0.0 {
                        impact_fraction = response.impact;
                    }
                }
                surface |= vertical_pass;
            }
        }
        if vertical_pass || (separation[Y] == 0.0 && impact_fraction == 1.0) {
            break;
        }
        separation[0] *= 129.0 / 128.0;
        separation[2] *= 129.0 / 128.0;
    }
    let normal = columns.map(|axis| dot(axis, normal));
    let length = dot(normal, normal).sqrt();
    RotaryContact {
        separation: columns.map(|axis| dot(axis, separation)),
        impact_fraction,
        surface,
        normal: if length < 1.0e-5 {
            [0.0; 3]
        } else {
            normal.map(|n| n / length)
        },
        location: columns.map(|axis| dot(axis, location)),
    }
}
