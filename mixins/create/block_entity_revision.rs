// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT

use crate::containers::ModRevision;

pub(super) trait EntityRevision {
    fn create_entity_identity(self) -> u64;
    fn is_same_create_entity(self, other: ModRevision) -> bool;
}

impl EntityRevision for ModRevision {
    fn create_entity_identity(self) -> u64 {
        *self.__horizon_mixins_create_block_entity_identity()
    }

    fn is_same_create_entity(self, other: ModRevision) -> bool {
        self.create_entity_identity() == other.create_entity_identity()
    }
}
