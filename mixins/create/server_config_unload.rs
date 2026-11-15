// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT

fn server_config_unload(config: &crate::game::NativeConfigFile) {
    crate::game::create_port_server_config::unload(config);
}
