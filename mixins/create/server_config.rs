// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT

use super::{NativeConfig, NativeConfigFile, NativeConfigKind};
use create_engine::{
    fan,
    fluid_tank::{BLOCK_CAPACITY, DEFAULT_MAX_HEIGHT},
    fluid_transport::DEFAULT_PUMP_RANGE,
};
use std::{
    cell::Cell,
    sync::{
        Arc,
        atomic::{AtomicU32, Ordering},
    },
};

const ID: &str = "create";
const FILE: &str = "create-server.toml";
const DEFAULT: &str = "\
[fluids]
# Allow open pipe ends to place fluid sources.
pipesPlaceFluidSourceBlocks = true
mechanicalPumpRange = 16
fluidTankMaxHeight = 32
fluidTankCapacity = 8

[recipes]
bulkPressing = false
bulkCutting = false
allowStonecuttingOnSaw = true

[kinetics.encasedFan]
fanPushDistance = 20
fanPullDistance = 20
fanBlockCheckRate = 30
fanRotationArgmax = 256
fanProcessingTime = 150
";

thread_local! {
    static PLACE_FLUID_SOURCES: Cell<bool> = const { Cell::new(true) };
    static PUMP_RANGE: Cell<i32> = const { Cell::new(DEFAULT_PUMP_RANGE) };
    static TANK_HEIGHT: Cell<i32> = const { Cell::new(DEFAULT_MAX_HEIGHT) };
    static TANK_CAPACITY: Arc<AtomicU32> = Arc::new(AtomicU32::new(BLOCK_CAPACITY));
    static FAN: Cell<fan::Config> = const { Cell::new(fan::Config::DEFAULT) };
    static BULK_PRESSING: Cell<bool> = const { Cell::new(false) };
    static BULK_CUTTING: Cell<bool> = const { Cell::new(false) };
    static SAW_STONECUTTING: Cell<bool> = const { Cell::new(true) };
}

pub(super) fn register(configs: &mut Vec<NativeConfig>) {
    configs.push(NativeConfig::new(ID, NativeConfigKind::Server, DEFAULT));
}

fn is_create(config: &NativeConfigFile) -> bool {
    config.mod_id == ID && config.file == FILE && config.kind == NativeConfigKind::Server
}

pub(super) fn load(config: &NativeConfigFile) {
    if !is_create(config) {
        return;
    }
    match config.text.parse::<toml::Table>() {
        Ok(settings) => {
            let fluids = settings.get("fluids");
            let value = fluids
                .and_then(|fluids| fluids.get("pipesPlaceFluidSourceBlocks"))
                .and_then(toml::Value::as_bool)
                .unwrap_or(true);
            PLACE_FLUID_SOURCES.set(value);
            let encased_fan = settings
                .get("kinetics")
                .and_then(|kinetics| kinetics.get("encasedFan"));
            let number = |value: Option<&toml::Value>, minimum, fallback| match value {
                Some(toml::Value::Integer(value)) => {
                    (*value).clamp(i64::from(minimum), i64::from(i32::MAX)) as i32
                }
                Some(toml::Value::Float(value)) => {
                    value.min(f64::from(i32::MAX)).max(f64::from(minimum)) as i32
                }
                _ => fallback,
            };
            PUMP_RANGE.set(number(
                fluids.and_then(|fluids| fluids.get("mechanicalPumpRange")),
                1,
                DEFAULT_PUMP_RANGE,
            ));
            TANK_HEIGHT.set(number(
                fluids.and_then(|fluids| fluids.get("fluidTankMaxHeight")),
                1,
                DEFAULT_MAX_HEIGHT,
            ));
            let buckets = number(
                fluids.and_then(|fluids| fluids.get("fluidTankCapacity")),
                1,
                (BLOCK_CAPACITY / 1000) as i32,
            ) as u32;
            TANK_CAPACITY.with(|capacity| {
                capacity.store(
                    buckets.saturating_mul(1000).min(i32::MAX as u32),
                    Ordering::Relaxed,
                );
            });
            let recipes = settings.get("recipes");
            let recipe_option = |key, default| {
                recipes
                    .and_then(|recipes| recipes.get(key))
                    .and_then(toml::Value::as_bool)
                    .unwrap_or(default)
            };
            BULK_PRESSING.set(recipe_option("bulkPressing", false));
            BULK_CUTTING.set(recipe_option("bulkCutting", false));
            SAW_STONECUTTING.set(recipe_option("allowStonecuttingOnSaw", true));
            let fan_number = |key, minimum, fallback| {
                number(encased_fan.and_then(|fan| fan.get(key)), minimum, fallback)
            };
            let default = fan::Config::DEFAULT;
            FAN.set(fan::Config {
                push_distance: fan_number("fanPushDistance", 5, default.push_distance),
                pull_distance: fan_number("fanPullDistance", 5, default.pull_distance),
                block_check_rate: fan_number("fanBlockCheckRate", 10, default.block_check_rate),
                rotation_argmax: fan_number("fanRotationArgmax", 64, default.rotation_argmax),
                processing_time: fan_number("fanProcessingTime", 0, default.processing_time),
            });
        }
        Err(error) => log::warn!("Could not read {}: {error}", config.path.display()),
    }
}

pub(super) fn unload(config: &NativeConfigFile) {
    if is_create(config) {
        PLACE_FLUID_SOURCES.set(true);
        PUMP_RANGE.set(DEFAULT_PUMP_RANGE);
        TANK_HEIGHT.set(DEFAULT_MAX_HEIGHT);
        TANK_CAPACITY.with(|capacity| capacity.store(BLOCK_CAPACITY, Ordering::Relaxed));
        FAN.set(fan::Config::DEFAULT);
        BULK_PRESSING.set(false);
        BULK_CUTTING.set(false);
        SAW_STONECUTTING.set(true);
    }
}

pub(super) fn place_fluid_sources() -> bool {
    PLACE_FLUID_SOURCES.get()
}

pub(super) fn pump_range() -> i32 {
    PUMP_RANGE.get()
}

pub(super) fn fluid_tank_max_height() -> i32 {
    TANK_HEIGHT.get()
}

pub(super) fn fluid_tank_capacity() -> u32 {
    TANK_CAPACITY.with(|capacity| capacity.load(Ordering::Relaxed))
}

pub(super) fn fluid_tank_capacity_source() -> Arc<AtomicU32> {
    TANK_CAPACITY.with(Arc::clone)
}

pub(super) fn fan() -> fan::Config {
    FAN.get()
}

pub(super) fn bulk_pressing() -> bool {
    BULK_PRESSING.get()
}

pub(super) fn bulk_cutting() -> bool {
    BULK_CUTTING.get()
}

pub(super) fn saw_stonecutting() -> bool {
    SAW_STONECUTTING.get()
}
