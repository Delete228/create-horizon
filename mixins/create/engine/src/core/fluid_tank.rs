// Copyright (c) The Create Team / The Creators of Create
// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT

//! FluidTankBlockEntity and ConnectivityHandler geometry for ordinary tanks.
pub type Pos = [i32; 3];

pub const BLOCK_CAPACITY: u32 = 8_000;
pub const MAX_WIDTH: i32 = 3;
pub const DEFAULT_MAX_HEIGHT: i32 = 32;
// The tallest supported Minecraft dimension is 4,064 blocks.
const MAX_HEIGHT: i32 = 4_064;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct Tank {
    pub root: Pos,
    width: i32,
    height: i32,
}

impl Tank {
    pub fn new(root: Pos, width: i32, height: i32) -> Option<Self> {
        if !(1..=MAX_WIDTH).contains(&width) || !(1..=MAX_HEIGHT).contains(&height) {
            return None;
        }
        // Bound the exclusive ends used by the iterators and checks below.
        root[0].checked_add(width)?;
        root[1].checked_add(height)?;
        root[2].checked_add(width)?;
        Some(Self {
            root,
            width,
            height,
        })
    }

    pub fn single(root: Pos) -> Self {
        Self {
            root,
            width: 1,
            height: 1,
        }
    }

    pub fn width(self) -> i32 {
        self.width
    }

    pub fn height(self) -> i32 {
        self.height
    }

    pub fn volume(self) -> u32 {
        (self.width * self.width * self.height) as u32
    }

    pub fn capacity(self) -> u32 {
        self.volume() * BLOCK_CAPACITY
    }

    pub fn contains(self, [x, y, z]: Pos) -> bool {
        (self.root[0]..self.root[0] + self.width).contains(&x)
            && (self.root[1]..self.root[1] + self.height).contains(&y)
            && (self.root[2]..self.root[2] + self.width).contains(&z)
    }

    pub fn parts(self) -> impl Iterator<Item = Pos> {
        let [x, y, z] = self.root;
        (y..y + self.height).flat_map(move |y| {
            (x..x + self.width).flat_map(move |x| (z..z + self.width).map(move |z| [x, y, z]))
        })
    }

    pub fn columns_loaded(self, mut loaded: impl FnMut(i32, i32) -> bool) -> bool {
        let [x, _, z] = self.root;
        ((x >> 4)..=((x + self.width - 1) >> 4))
            .all(|cx| ((z >> 4)..=((z + self.width - 1) >> 4)).all(|cz| loaded(cx << 4, cz << 4)))
    }

    /// Adjacent members on west, east, north and south, in that bit order.
    pub fn horizontal_mask(self, [x, _, z]: Pos) -> u8 {
        u8::from(x > self.root[0])
            | (u8::from(x + 1 < self.root[0] + self.width) << 1)
            | (u8::from(z > self.root[2]) << 2)
            | (u8::from(z + 1 < self.root[2] + self.width) << 3)
    }

    pub fn shape(self, [x, _, z]: Pos, window: bool) -> &'static str {
        match (window, self.width, x - self.root[0], z - self.root[2]) {
            (true, 1, _, _) => "window",
            (true, 2, 0, 0) => "window_nw",
            (true, 2, 1, 0) => "window_ne",
            (true, 2, 0, 1) => "window_sw",
            (true, 2, 1, 1) => "window_se",
            (true, 3, x, z) if (x - z).abs() == 1 => "window",
            _ => "plain",
        }
    }

    pub fn bottom(self, pos: Pos) -> bool {
        self.root[1] == pos[1]
    }

    pub fn top(self, pos: Pos) -> bool {
        self.root[1] + self.height - 1 == pos[1]
    }

    pub fn liquid_bounds(self, fraction: f32) -> Option<[f32; 6]> {
        let height = self.height as f32 - 9.0 / 16.0;
        if fraction < 1.0 / (512.0 * height) {
            return None;
        }
        let hull = 1.0 / 16.0 + 1.0 / 128.0;
        let floor = 5.0 / 16.0;
        let far = self.width as f32 - hull;
        Some([
            hull,
            floor,
            hull,
            far,
            floor + (fraction * height).min(height),
            far,
        ])
    }

    /// After breaking a part, distribute in Java's y, x, z order. The
    /// surviving controller is first, and removed parts consume no capacity.
    pub fn split(
        self,
        mut amount: u32,
        part_capacity: u32,
        mut survives: impl FnMut(Pos) -> bool,
    ) -> Vec<(Pos, u32)> {
        self.parts()
            .filter(|&pos| survives(pos))
            .map(|pos| {
                let retained = amount.min(part_capacity);
                amount -= retained;
                (pos, retained)
            })
            .collect()
    }
}

/// Choose the largest complete footprint, wider on equal volume. A merge
/// must own the entire footprint of every source and keep its fluid.
pub fn largest<K: PartialEq>(
    root: Pos,
    max_height: i32,
    mut part: impl FnMut(Pos) -> Option<(Tank, Option<K>)>,
) -> Option<Tank> {
    let (base, _) = part(root)?;
    if base.root != root {
        return None;
    }
    let max_height = max_height.clamp(1, MAX_HEIGHT);
    let mut best = base;
    for width in base.width..=MAX_WIDTH {
        let mut fluid = None;
        let mut required_height = 1;
        'layers: for height in 1..=max_height {
            let candidate = Tank::new(root, width, height)?;
            for x in root[0]..root[0] + width {
                for z in root[2]..root[2] + width {
                    let Some((source, key)) = part([x, root[1] + height - 1, z]) else {
                        break 'layers;
                    };
                    let [sx, sy, sz] = source.root;
                    if sx < root[0]
                        || sy < root[1]
                        || sz < root[2]
                        || sx + source.width > root[0] + width
                        || sz + source.width > root[2] + width
                        || (source != base && source.width == width && source.height == max_height)
                    {
                        break 'layers;
                    }
                    if let Some(key) = key {
                        if fluid.as_ref().is_some_and(|fluid| *fluid != key) {
                            break 'layers;
                        }
                        fluid = Some(key);
                    }
                    required_height = required_height.max(sy - root[1] + source.height);
                }
            }
            if height >= required_height && candidate.volume() >= best.volume() {
                best = candidate;
            }
        }
    }
    Some(best)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn complete_layers_width_ties_and_limits() {
        let root = [-1, 4, 15];
        let square = Tank::new(root, 3, 3).unwrap();
        let choice = largest::<()>(root, DEFAULT_MAX_HEIGHT, |pos| {
            (square.contains(pos) || pos[0] == root[0] && pos[2] == root[2])
                .then_some((Tank::single(pos), None))
        });
        assert_eq!(choice, Tank::new(root, 1, 32));
        let choice = largest::<()>(root, DEFAULT_MAX_HEIGHT, |pos| {
            let tower = pos[0] == root[0] && pos[2] == root[2] && pos[1] < root[1] + 27;
            (square.contains(pos) || tower).then_some((Tank::single(pos), None))
        });
        assert_eq!(choice, Some(square));
        assert_eq!(square.capacity(), 216_000);
        assert_eq!(Tank::new(root, 3, 32).unwrap().capacity(), 2_304_000);
        assert!(!square.columns_loaded(|x, z| x < 0 || z < 16));
    }

    #[test]
    fn merge_neither_partitions_other_controllers_nor_mixes_fluids() {
        let root = [0, 0, 0];
        let base = Tank::single(root);
        let other = Tank::new([1, 0, 0], 1, 3).unwrap();
        let square = Tank::new(root, 2, 1).unwrap();
        assert_eq!(
            largest::<()>(root, DEFAULT_MAX_HEIGHT, |pos| {
                if other.contains(pos) {
                    Some((other, None))
                } else {
                    square.contains(pos).then_some((Tank::single(pos), None))
                }
            }),
            Some(base)
        );
        assert_eq!(
            largest(root, DEFAULT_MAX_HEIGHT, |pos| {
                square.contains(pos).then_some((
                    Tank::single(pos),
                    match pos {
                        [1, 0, 0] => Some("water"),
                        [1, 0, 1] => Some("lava"),
                        _ => None,
                    },
                ))
            }),
            Some(base)
        );
    }

    #[test]
    fn break_controller_and_split_into_only_surviving_parts() {
        let tank = Tank::new([0, 0, 0], 2, 2).unwrap();
        let split = tank.split(25_000, BLOCK_CAPACITY, |p| p != tank.root && p != [1, 0, 0]);
        assert_eq!(
            &split[..4],
            &[
                ([0, 0, 1], 8_000),
                ([1, 0, 1], 8_000),
                ([0, 1, 0], 8_000),
                ([0, 1, 1], 1_000)
            ]
        );
        let split = tank.split(tank.capacity(), BLOCK_CAPACITY, |p| p != [1, 1, 1]);
        assert_eq!(split.iter().map(|(_, amount)| amount).sum::<u32>(), 56_000);
        assert_eq!(split[0], (tank.root, 8_000));
    }

    #[test]
    fn connected_faces_stop_at_the_footprint() {
        let root = [15, 10, -1];
        assert_eq!(Tank::single(root).horizontal_mask(root), 0);
        let wide = Tank::new(root, 3, 2).unwrap();
        assert_eq!(wide.horizontal_mask(root), 2 | 8);
        assert_eq!(wide.horizontal_mask([17, 11, -1]), 1 | 8);
        assert_eq!(wide.horizontal_mask([16, 10, 0]), 15);
        assert_eq!(wide.horizontal_mask([16, 11, 1]), 1 | 2 | 4);
    }

    #[test]
    fn java_window_and_liquid_geometry() {
        let tank = Tank::new([0, 0, 0], 2, 2).unwrap();
        assert_eq!(tank.shape([1, 1, 0], true), "window_ne");
        assert_eq!(tank.shape([0, 1, 1], true), "window_sw");
        assert_eq!(tank.shape([1, 1, 1], false), "plain");
        let wide = Tank::new([0, 0, 0], 3, 2).unwrap();
        assert_eq!(wide.shape([1, 0, 2], true), "window");
        assert_eq!(wide.shape([2, 0, 2], true), "plain");
        assert_eq!(wide.shape([1, 0, 1], true), "plain");
        assert_eq!(
            tank.liquid_bounds(1.0),
            Some([
                9.0 / 128.0,
                5.0 / 16.0,
                9.0 / 128.0,
                2.0 - 9.0 / 128.0,
                1.75,
                2.0 - 9.0 / 128.0
            ])
        );
        assert!(tank.liquid_bounds(0.0).is_none());
    }
}
