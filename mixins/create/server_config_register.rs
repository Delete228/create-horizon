// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT

fn server_config_register(configs: &mut Vec<crate::game::NativeConfig>) {
    crate::game::create_port_server_config::register(configs);
}
