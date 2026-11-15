# Portable Storage Interface

The item interface uses the movement probe from
`PortableStorageInterfaceMovement` and the station state from
`PortableStorageInterfaceBlockEntity` in Create 6.0.10. The Rust engine keeps
both rules in `create_engine::contraption::portable_storage`. The inventory
bridge follows `PortableItemInterfaceBlockEntity`.

The probe sits 1.85 blocks in front of the moving interface's center.
It checks its grid cell and one more cell in the nearest cardinal direction.
That direction must be within 0.5 of the rotated unit vector. The station
must face the probe and be unpowered. If the moving probe is about to pass
the center of its partner, the actor stalls and keeps the link alive. When
the station's timer reaches four, the actor releases its stall.

The station starts at timer 14. A live link permits item transfer while the
timer is in the inclusive connected window, from four through 64 at the
default timeout. Each successful real insertion or extraction resets the
timer to 64. A failed transfer or a simulation leaves the timer alone.
Comparator output uses the timer window. Item access also requires a live
owner. The saved `Timer`, `Distance` and `Powered` fields preserve the visible
state. The running owner and keepalive are rediscovered in the world.
A stalled Rope Pulley, vertical Mechanical Piston or Gantry saves the
target of its working interface. The Gantry keeps its target beside the
moving scene because the carriage has left the terrain. On reload the
driver checks that the same station is loaded, facing the probe and
unpowered before restoring the stall and reconnecting.

`tools/portable_storage_reference_checks.py` records a 32 RPM vertical
bearing carrying a chest and a moving interface. A station supplies a hopper
with three wheat and two sticks that carry custom data. The fixture checks
the connection angle, extraction cadence, held angle, timer release, and
comparator wire. It then powers the station during an active transfer and
checks that the next revolution reconnects after power is removed.

Horizon supports one moving item interface on a vertical Mechanical Bearing,
dry Rope Pulley, vertical Mechanical Piston or Gantry, with a mounted
inventory and a matching stationary interface in the same loaded chunk
column. A vanilla Hopper directly below the stationary interface extracts
one item per eight-tick cycle. A [Chute](chute.md) in the same position
pulls up to 16 matching items into its ordinary transit. Both routes carry
the original item components. A rejected transfer leaves the stack in the
mounted chest and the timeout continues counting down.

A dry Chute above the same stationary interface feeds the moving chest.
It first simulates insertion at the midpoint, then commits at the exit.
Existing matching stacks fill before empty slots. The unaccepted remainder
stays in the Chute. A successful insertion refreshes the link. A full chest
or interrupted link leaves the source stack intact and does not refresh it.

The supplied fallback models use the mod's own textures. The optional local
JAR provides the original casing, stem and head. The server sends the station's
timer, distance and power to the client. The fixed head uses the squared
connection progress. The moving head follows its own linear chase at one
quarter block per tick. Both interpolate between client ticks. The middle
piece changes its appearance when the fixed side connects or the moving side
settles. Generic item capabilities and fluid interfaces remain open. Craft
the interface from a Chute and an Andesite Casing. [Chute](chute.md)

`tools/portable_storage_native_checks.py` runs the shared geometry headlessly
and compares bearing, interface, hopper, chest and comparator observations
against the Java trace. Separate cases exercise an incompatible nearly full
hopper and a process restart during transfer.
`tools/portable_chute_input_checks.py` checks full, partial, tagged and
power-interrupted insertion in both clients, including a native restart.
`tools/pulley_portable_storage_checks.py` compares 200 ticks in each
direction. It checks the offset and station timer, five Hopper transfers
with item components, resumption at timer four, and landing the empty Chest
and moving interface. The cold case also saves and restarts each process
while docked with items still in transit. It checks that the held offset
and tagged cargo survive, and compares the release and landing after
aligning the traces on the release event.
`tools/piston_portable_storage_checks.py` checks the same transfer while a
vertical Mechanical Piston extends four blocks. It verifies the dock and
tagged cargo across a cold restart, and compares release at timer four after
the station and controller reload in a different order.
`tools/gantry_portable_storage_checks.py` uses a horizontal rail with a
side-facing dock. The cold case checks the saved carriage coordinate and
working target, verifies that the remaining tagged items arrive after
reload, and confirms that the target is removed after landing.
The [rendered Gantry check](../tools/portable_storage_animation_checks.py)
samples both heads before, during and after transfer with the original JAR.
It checks intermediate extension, the lit middle pieces, retraction and
arrival of the tagged cargo.
