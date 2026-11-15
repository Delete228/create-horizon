// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT

fn server_config_read(config: &crate::game::NativeConfigFile) {
    crate::game::create_port_server_config::load(config);
}
