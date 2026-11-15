# Chute

The dry vertical Chute uses `ChuteBlockEntity`, `ChuteItemHandler` and
`ItemHelper.extract` from Create 6.0.10. Its block and block entity both use
`create:chute`. A stack in transit saves as `Item` and `ItemPosition`. The
airflow fields retain their original names and are zero without driven airflow.

Put a supported container above the Chute to pull items through its bottom
face. It takes up to 16 from the first eligible stack and any later stacks
with the same item and components. It drops 0.2 blocks per tick and waits at
the midpoint while the output is full. A second Chute below starts a new
transit when it accepts the stack. A container below receives the item through
its top face, filling matching stacks before empty slots. An open bottom
emits an item entity.

Vanilla hoppers also reach the Chute's ordinary single slot. Empty-hand use
recovers the held stack. A wrench switches between normal and window for a
vertical Chute. Use a Block of Industrial Iron on either shape to encase it
without consuming the block. The wrench removes the casing. These transitions
keep the item in transit and its position. The bundled models have their
own shell and window textures. The optional original JAR supplies Create's
models and textures. The client interpolates cargo in the window or under
an opaque Chute with suction. Pickup particles remain open.

An Iron Ingot between two Iron Sheets makes four Chutes. One Chute and one
Andesite Casing craft a Portable Storage Interface. Both recipes retain their
original IDs and ingredients.
Manual crafting works in the vanilla crafting-table menu. The pinned Horizon
recipe-book index currently omits mod namespaces.

Ordinary Chutes connect diagonally in four directions. Hopper input works
in the tested dry and waterlogged vertical and angled placements. A single
Encased Fan can drive a straight column or feed one straight and one angled
branch from below, including through waterlogged ordinary Chutes. Smart
Chutes have their own filter and amount settings. The detailed cases and
remaining limits are in the [compatibility guide](compatibility.md).

`tools/chute_reference_checks.py` captures 90 ticks from four original Java
layouts. `tools/chute_native_checks.py` compares the same chest, two-chute,
blocked-output and hopper layouts. It also checks a separate process restart
with an item in transit, item pickup followed by a drop from an open bottom,
and both recipes in an offscreen survival crafting table.

A Chute under a connected item Portable Storage Interface pulls directly
from the moving chest. This route uses the same 16-item limit and slot order.
`tools/portable_chute_checks.py` compares its tick trace with Java and checks
that a restart preserves both the batch in transit and the mounted remainder.
