// Copyright (c) The Create Team / The Creators of Create
// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT

use super::{LegacyRandom, Light, Particle, ParticleEngine, RandomSource};

pub fn particle(
    engine: &mut ParticleEngine,
    at: [f64; 3],
    motion: [f64; 3],
    lava: bool,
) -> Option<Particle> {
    let (sprite, tint) = if lava {
        ("block/lava_still", 0xffffff)
    } else {
        ("block/water_still", 0x3f76e4)
    };
    sprite_particle(engine, at, motion, sprite, tint, lava)
}

pub fn sprite_particle(
    engine: &mut ParticleEngine,
    at: [f64; 3],
    motion: [f64; 3],
    sprite: &str,
    tint: u32,
    luminous: bool,
) -> Option<Particle> {
    if engine.calculate_particle_level(true) == 2 {
        return None;
    }
    Some(terrain(engine, at, motion, sprite, tint, luminous))
}

/// `ClientLevel.addParticle` for a visible fluid stack, with the ordinary
/// distance limit and particle setting used by the Mechanical Mixer.
pub fn nearby_sprite_particle(
    engine: &mut ParticleEngine,
    at: [f64; 3],
    motion: [f64; 3],
    sprite: &str,
    tint: u32,
    luminous: bool,
) -> Option<Particle> {
    let minimal = engine.calculate_particle_level(false) == 2;
    let distance: f64 = at
        .iter()
        .zip(engine.camera)
        .map(|(p, c)| (p - c).powi(2))
        .sum();
    (distance <= 1024.0 && !minimal).then(|| terrain(engine, at, motion, sprite, tint, luminous))
}

fn terrain(
    engine: &mut ParticleEngine,
    at: [f64; 3],
    motion: [f64; 3],
    sprite: &str,
    tint: u32,
    luminous: bool,
) -> Particle {
    let mut random = LegacyRandom::new(engine.seeds.next_long());
    let mut particle = Particle::terrain(&mut random, at, motion, sprite.into(), 0xFFFFFF);
    let [r, g, b] = [16, 8, 0].map(|shift| 0.8 * (((tint >> shift) & 255) as f32 / 255.0));
    particle.rgba = [r, g, b, 1.0];
    particle.velocity = motion;
    if luminous {
        particle.light = Light::Block15;
    }
    particle
}
