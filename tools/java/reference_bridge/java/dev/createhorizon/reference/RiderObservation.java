// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT

package dev.createhorizon.reference;

import com.google.gson.JsonArray;
import com.google.gson.JsonObject;
import com.simibubi.create.content.contraptions.ControlledContraptionEntity;
import net.minecraft.client.Minecraft;
import net.minecraft.core.BlockPos;
import net.minecraft.world.entity.Entity;
import net.minecraft.world.phys.AABB;
import net.minecraft.world.phys.Vec3;

final class RiderObservation {
    private static JsonObject beforeTick;
    private static JsonObject afterTick;

    private RiderObservation() {}

    private static JsonArray vector(Vec3 position) {
        JsonArray values = new JsonArray();
        values.add(position.x);
        values.add(position.y);
        values.add(position.z);
        return values;
    }

    private static JsonObject rider(Entity player) {
        JsonObject result = new JsonObject();
        result.add("position", vector(player.position()));
        result.add("velocity", vector(player.getDeltaMovement()));
        result.addProperty("grounded", player.onGround());
        result.addProperty("player_tick", player.tickCount);
        return result;
    }

    static void tick(Entity entity, boolean before) {
        if (entity != Minecraft.getInstance().player)
            return;
        if (before)
            beforeTick = rider(entity);
        else
            afterTick = rider(entity);
    }

    static JsonObject sample(BlockPos anchor) {
        Minecraft client = Minecraft.getInstance();
        if (client.level == null || client.player == null)
            throw new IllegalStateException("No reference client rider");

        JsonObject result = rider(client.player);
        result.add("before_player_tick", beforeTick);
        result.add("after_player_tick", afterTick);
        result.addProperty("angle", 0.0);

        Vec3 origin = Vec3.atLowerCornerOf(anchor);
        for (var contraption : client.level.getEntitiesOfClass(ControlledContraptionEntity.class,
                new AABB(anchor).inflate(1), entity -> entity.isAlive() && origin.equals(entity.getAnchorVec()))) {
            result.addProperty("angle", contraption.getAngle(1));
            result.addProperty("previous_angle", contraption.getAngle(0));
            result.add("point_motion", vector(contraption.getContactPointMotion(client.player.position())));
            break;
        }
        return result;
    }
}
