# Create Horizon: overall porting roadmap

The goal is the **Create 6.0.10** experience pinned in `compatibility.json`: the same
machines, interactions, data, interfaces, sound and effects. Rust code may have a
different internal structure. Matching models or individual formulas alone does
not mean a subsystem is complete. Java addon JARs are not executed here.

Legend: `[x]` means a verified, bounded item; `[ ]` means pending or only partly
ported. A large subsystem will be checked off only after all its listed behavior
has been verified. Current detailed limits are in
[COMPATIBILITY.md](compatibility.md), with evidence in [VALIDATION.md](../VALIDATION.md).
Completion percentages are rough estimates, not a count of the rows below.

The 0.7 checkpoints cover Encased Chain Drive, generator timing, fan component
handling and the built-in resources. [Gameplay report](reviews/0.7-report.md)
· [Review route](reviews/0.7-test-world.md)

The 0.8 development builds include rotary and linear contraptions,
Super Glue, Sticker, small moving farms, and two-way Chute transfer through
an item dock. The current checkpoint verifies farm shutdown and bearing
landing through dry foliage against Java.
[Contraption review route](reviews/0.8-contraption-world.md)
· [Release audit](reviews/0.8-release-audit.md)

[0.9 parity review world](reviews/0.9-parity-world.md)

## Current priority

Build the shared contraption engine alongside the remaining stationary machines.
Keep the Java comparisons as regressions and schedule presentation refinements
with the systems they depend on.

1. Define a durable cross-chunk write protocol before allowing a structure
   to span columns. Verify recovery after a crash between column writes.
2. Expand mounted storage, terrain contact and actor use. Keep the existing
   Java traces as regressions. [Architecture and results](contraptions.md)
3. Add shared schematic fixtures for repeating the same machine checks in
   both games, including the crop and tree farms.

| Subsystem | Verified bounded foundation | Next acceptance criterion |
|---|---|---|
| Installation and resources | Working native pipeline, local JAR | Verify the next release through the same route |
| Kinetic network | Basic shafts, gears, gearboxes, stress and Encased Chain Drive; bounded source-event traces | Source ownership, propagation transients, effects and complex connections |
| Item processing | Presses, fans, millstones, stationary saws, linked Crafter hand input and a full Precision Mechanism line | Remaining recipe families, automation and presentation |
| Rotation sources | Creative Motor, Hand Crank, water wheels | Other sources, control and power systems |
| UI and visual feedback | Java comparisons of motor and Basin tooltips; other UI/effects are partial | Complete layout and lifecycle of supported screens, original lighting |
| Schematics | Bounded `.nbt` preflight and creative paste with horizontal rotation and mirroring | Preview/UI and broader block/entity transformations |
| Transport and automation | Horizontal Belts with casings and rider support, dry and waterlogged vertical Chutes, and ordinary machine input and output | Sloped Belt riders, more Funnel and Tunnel modes, Mechanical Arms |
| Mixing and heating | Basin/Mixer recipes, wet and dry stirring effects, heated brass, burner and fuel | Remaining recipes, interactions and combined heat regression |
| Fluids | Multiblock Fluid Tanks, Basin fluids, branched networks, co-directed pumps with up to two side tanks, opposing pumps with a closed middle, valves, open ends, Item Drain | More endpoints between pumps, loops, other fluid machines and boilers |
| Contraptions | Bearings, pistons, Gantry and Rope Pulley with bounded cargo, riders and farm tools | Broader payloads, cross-chunk ownership, more drives, contact and portable storage |
| Trains and logistics | Pending | Tracks, trains, schedules, cargo |
| Ponder and guides | Pending | Original scenes, controls and presentation |
| Addons | Architectural requirement | Public Rust contracts; then Sable and Aeronautics |

## 1. Distribution, identifiers and validation

- [x] Build the mod from GitHub through the standard Horizon Launcher with pinned versions.
- [x] Load original resources from the player's local JAR without publishing them.
- [x] Built-in models work without the JAR. An actual game switches back when
  the JAR is removed, even with the cache still present.
- [x] Original IDs for supported blocks, items and recipes; import 61 localizations.
- [x] Verified separate native worlds for 0.3, 0.4 and 0.5, preserving older worlds.
- [x] Independent Java oracles for selected algorithms and real native checks.
- [x] Separate actual Java Create 6.0.10 client and local comparison bridge.
- [ ] Complete set of shared comparison scenarios for both clients.
- [ ] All supported screens, effects, sounds and animations match the reference.
- [ ] LAN/dedicated-server, data reload and resource reload regression tests.
- [ ] Complete table of original save fields and migration tests between port releases.
- [x] Separate 0.6 world: 13 stations, independent run of 15 groups, 6 survival crafts,
  2 actual restarts and inspection of 19 images. Binary boundaries are in the report.
- [x] Alpha.3 candidate: accepted upstream Mixins, native package and developer build.
- [x] macOS `.app` metadata and native-data fix merged upstream.
  [Horizon #9529](https://github.com/horizon-rust/horizon/pull/9529)
- [ ] Retest a clean installation with the updated Launcher and official Horizon.
- [x] Separate 0.7 developer review world: 23 independent audit groups, 16 inspected
  frames and two actual restart comparisons; resumed fixture correction disclosed.
- [x] Separate 0.9 parity world with the original local JAR. Exercise fluid,
  transport and workshop stands through a full restart, then reopen the
  restored initial save. [Review guide](reviews/0.9-parity-world.md)
- [x] Submit the 0.7.0-alpha.2 archive to the native mod registry.
  [Registry submission #252](https://github.com/horizon-rust/horizon-mods/pull/252)
- [x] Complete registry review and publish the 0.7.0-alpha.2 listing.
  [Create for Horizon](https://playhorizon.dev/mods/create)

## 2. Rotation and engineer's tools

- [x] Shafts, small/large cogwheels, basic gear ratios and speed limit.
- [x] Gearbox, Clutch, Gearshift, original directions and rotating parts.
- [x] Hand Crank, motor, small and large water wheels: basic mechanics and persistence.
- [x] Hand Crank mounting on partial collision shapes, waterlogging, drops
  on support loss, and ordinary Wrench activation. See the
  [paired fixture](../tools/crank_support_checks.py).
- [x] Wrench, rotation/removal, encased shafts; basic Speedometer/Stressometer.
- [x] Dry Andesite and Brass Encased Cogwheels in both sizes, with independent
  shaft ends, Wrench interactions and source casing/rotating models from the
  local JAR. See the [paired fixture](../tools/encased_cog_checks.py).
- [ ] Encased Cogwheel connected textures, face-sensitive pick-block,
  and contraption integration.
- [x] Manual Copper Casing recipes and the NeoForge convention tags for
  stripped logs and wood. Connected textures and advancements remain pending.
- [x] Encased Chain Drive: 24 source states, placement/shape updates, ordinary Wrench,
  two recipes, six actual Java/native settled scenes and a native restart.
- [x] Bounded generator publication from initialization, GUI, crank and wrench events;
  raw NBT reads remain distinct. Per-component publication and lifetime cache tests.
- [ ] Complete source ownership, flicker/breakage, loaded-network and instantaneous
  detach semantics from RotationPropagator.
- [x] Adjustable Chain Gearshift. Settled shaft speeds and block states for all
  16 redstone strengths from either input end, plus native save/reload.
- [x] Adjustable Chain Gearshift redstone transitions: 66 matching
  Java and Horizon lane observations, including a short pulse and reload.
- [ ] Adjustable Chain Gearshift full visual parity.
- [x] Original Rose Quartz, Sand Paper, Electron Tube and Brass Hand recipes.
  Hand and ground polishing unlock the Deployer and Adjustable Chain Gearshift recipes.
- [ ] Remaining redstone controls, belt and gearbox connection variants.
- [x] Straight Clutch and Gearshift lines with either input end. Compare the
  immediate detach, next-tick reattachment and short pulses in Java and
  Horizon. [Transmission review](reviews/transmission.md)
- [x] Clutch and Gearshift across two loaded columns, including redstone,
  immediate shaft detach, replacement and a native restart in the tested
  loaded networks.
- [x] Flywheel with shaft connections on three axes, original item and wheel
  models from the local JAR, and separate acceleration and coast animation.
- [ ] Clutch/Gearshift and Hand Crank in all network/animation edge cases.
- [ ] Original goggles tooltips and value settings, including RU/EN, colors, units and fading.
- [ ] Original speed/overstress particles, placement assistance, outlines and sound loops.
- [ ] Rotational Speed Controller, Sequenced Gearshift and redstone modules.
  The [Java controller fixture](../tools/speed_controller_java_checks.py) covers
  both shaft faces and the perpendicular large cog above. At a target of zero,
  cog input owns the idle controller while its shafts remain outside the
  network. Shaft input still passes through the controller and owns the idle
  cog. Competing inputs can retain different owners even when their geometry
  and RPM match. Removing the same source can then yield different speeds.
  A real settings-board change publishes the new rotation immediately. The
  shared stress total reflects both domains on the next tick. The board clamps
  either direction to at least 1 RPM. A raw `ScrollValue` edit instead clears
  the controller's own rotation and owner while neighboring drills retain
  their old speeds during the measured 12 ticks. The solver needs to preserve
  the source tree and distinguish these events before exposing the block.
- [x] Windmill Bearing: wool sails, assembly, rear shaft output and restoration.
- [ ] Complete Windmill controls, sail blocks, Steam Engine, boiler and other stress sources/consumers.

## 3. Item processing and transport

- [x] Depot: top interaction, collection, output buffer, dropped items and hoppers.
- [x] Bounded Depot slide and press lifecycle: canonical pose, lock release,
  two cycles and two sheets. Compared 101 unshifted lifecycle samples against
  the pinned Java client.
- [x] Press: single-item cycle, basic recipes, acceleration, blocked output and save/reload.
- [x] Millstone: input, timer, chance outputs, collection and persistence.
- [x] Millstone legacy datapack outputs with item components and crafting
  remainders. Match Hopper intake, the 99-item pause threshold and resumed
  processing beside a normal 64-item stack after a cold restart.
- [x] Millstone particles on both rotation directions. Compare the retry
  cadence, the full-output pause and the motor stop/restart in live clients.
- [x] Fan: item movement, processing media and item/Depot processing.
- [x] Bounded effective fire-resistance components: prototype/removal, canonical
  full-fire tag and recipe priority; actual Java/native scenes and native restart.
- [ ] General damage-selector/data-fixer equivalence across Minecraft versions.
- [x] Stationary drill: breaking the block in front, drops, speed and stopping.
- [x] Stationary Drill across a chunk boundary. Six Java and Horizon
  cases cover placement order, breaking ticks, shared loot origin, pickup
  delay, the block-drops rule and ore experience.
- [x] Stationary Drill with a water/lava cobblestone generator and an ordinary
  Hopper. Match block retention, normal inventory cadence and the first
  output after a cold restart. The second post-restart output can differ by one tick.
- [x] Upward Saw output to a neighboring Depot, including blocked and partial
  delivery across a chunk boundary, both output directions and native reloads.
- [x] Upward Saw output to a neighboring Millstone, including input filtering,
  components, backpressure and same-tick inventory publication after a restart.
- [x] Upward Saw output onto a bare horizontal Belt, including inline and
  side entry, rejected insertion, position traces and a native restart.
- [x] Upward Saw output into a dry Chute or Smart Chute across a chunk boundary.
  Preserve the full stack through filtering, redstone changes and restart.
- [x] Bare Belt output to a Millstone. Match accepted, partial and refused
  insertion and preserve accepted items when the world closes on the transfer tick.
- [x] Fan push, pull and smoking damage on a player in normal simulation.
  Match Java's living-entity effects at a dry-to-haunting boundary.
- [ ] Remaining fan entity types, frozen motor-start timing and further particle
  and sound comparisons.
- [ ] Full observable parity of already supported machines, including item animation.
- [x] Bounded press over a bare belt: single-item processing, holding the remainder,
  output through a Depot/hopper, independent power loss and an actual restart.
- [x] Bounded fan over a bare belt: washing, media changes,
  unsupported input, stopped belt, two-current queue and an actual restart.
- [x] Press/belt retain their cycle and items through 20 frozen steps;
  processing resumes after unfreezing, as in actual Java Create.
- [x] Bounded dry Basin/Mixer: original inventories, hopper IO,
  empty-hand collection, 30 RPM threshold, power loss, blocked output,
  recipes/bucket remainder and an actual restart. Cycle times of 83/62 ticks were
  checked against actual Java Create.
- [x] Canonical Depot/Basin/Millstone inventories: load before the first tick,
  removal of inventory halves, hopper IO and components; unsupported explicit `Size` is preserved
  opaquely without losing contents. Actual restart and empty
  network-root no-op were checked; this is not yet an arbitrary Java data fixer.
- [x] Bounded Basin: water/lava in two input and two output segments,
  ordinary buckets, dough for 1000 mB and mud for 250 mB; persistence and real native rendering.
- [x] Bounded heating: a filled burner with coal and a running Mixer
  turn `2 copper + 2 zinc → 4 brass`; power/heat loss does not consume input.
- [ ] Complete burner: combined ordinary-interaction run, networking, exact lighting,
  retained visual lifecycle, goggles and all effects without known differences.
- [x] Belt connector green and red dust preview between clicks. Real Java and
  Horizon captures and accepted/rejected connection checks.
  [Review route](reviews/belt-preview.md)
- [x] Six belt layouts assembled through the connector in each client.
  Item travel matched in 16 of 18 powered, stopped and reversed phases.
  The remaining two phases share a Java source loop on one horizontal lane.
  Replacing a belt preserves the new chain and ejects the old load once.
  [Motion review](reviews/belt-motion.md)
- [x] Original Belt scroll strips retain their full height. Frame captures on
  straight and sloped belts keep the stripes visible at every sampled step.
- [ ] Belts: exact render phase and lighting, item shadows, complete lifecycle and IO.
- [x] Dry horizontal Belts carry a grounded local player across bare segments
  and segments with Andesite or Brass Casing. Compare both X directions,
  Z movement, steering, crouching, a stop and a wall.
- [ ] Belt passengers on slopes and other actors. Moving surfaces also need
  transformed contact geometry and a world-space movement request.
- [x] Bounded surface geometry: X rotation fixed; 1600 source cases,
  60 actual Game/CPU draw cases and inspection of limited Java/native views.
- [x] Bounded bare-belt foundation: connector, original shapes, RPM transmission,
  items, output Depots/hoppers and persistence through an actual restart.
- [x] All 16 Belt colors and ordinary washing, with chain-wide persistence.
  Andesite and Brass Casing apply per segment across the five Belt shapes.
- [x] Horizontal Belt to dry Chute or Smart Chute and back onto a Belt.
  Include stopped output, filter and redstone refusal, and cold restart.
- [ ] Funnels/tunnels/chutes, filters, brass/andesite rules and batch transfer.
- [x] Dry vertical Andesite Funnel with an ordinary inventory. Verify the
  original stack order, Wrench, extraction cooldown and redstone.
- [x] Crouched Wrench pickup for the dry vertical Funnel in Survival and Creative.
- [x] Dry Smart Chute with a plain ghost filter, the default 64-item limit,
  powered parking and an actual restart.
- [x] Shared amount panel for extracting Smart Chutes and vertical Brass
  Funnels, with ordinary filter taps, per-item limits and both transfer modes.
- [x] Vanilla Hopper input into a dry Smart Chute from the top or side. Match
  plain filters, redstone refusal, the first six transit ticks and a restart.
  [Paired fixture](../tools/smart_chute_hopper_checks.py)
- [x] Bottom-Fan airflow through a straight ordinary Chute column, including
  Hopper input, reversal, blocked receivers and a cold restart.
- [x] Upper-Fan suction through a straight ordinary Chute column. Loose
  items, collision limits, lower Barrel extraction and cold cargo return
  agree with Java.
- [x] Bottom-Fan airflow through one dry fork with straight and angled outputs.
  Match equal-priority routing, blocked diversion and marked cargo across a
  loaded chunk boundary, including both clients' post-restart tick order.
- [x] Upper-Fan suction from horizontal Belts. Compare the strict center
  boundary, air gap, solid obstruction, saved offsets and item components.
- [x] Upper-Fan suction from a Depot through an ordinary dry Chute. Compare
  direct and air-gap extraction, the output buffer, and solid obstruction.
  [Paired fixture](../tools/chute_depot_suction_checks.py)
- [x] Chute airflow particles at the default setting. Compare the window,
  open exhaust, reversed air and collision-limited suction.
- [ ] Smart Chute special filters, sloped Belt suction, paired Fans
  and larger airflow networks.
- [x] Cargo visibility below a windowless Chute with suction. Compare the
  window and opaque controls when the Chute block is outside the view.
- [x] Cargo interpolation between visible Chute ticks, including a steady
  parked pose and the original server-side item offset.
- [ ] Occasional Chute air particles on Minimal.
- [x] Dry vertical Brass Funnel with plain filters, full matching batches,
  redstone, original cooldown and saved amount. Verify filter/count hover.
- [ ] Funnel dropped-item intake, horizontal and wet placement, Belt Funnels,
  and advanced filter items.
- [x] Ordinary physical item intake into the Basin and Millstone: original scenes,
  partial transfer, components and an actual restart.
- [x] Bounded Press/Basin: separate compacting pool, square crafting recipes,
  ice and three stone types with lava; repetition, stopping, overstress and persistence.
- [x] Bounded Press/Basin startup: 1,488 unshifted per-tick observations match,
  respecting actual source events and ticker order; no timer offset.
- [ ] Authentic cold-loaded Java/network traces and full propagation-order coverage.
- [x] Press client foundation: packets, pause/interpolation, three modes and
  item-particle order checked by oracles and actual Game tests.
- [x] Loose-item Press trigger and strike boxes. Verify the first grounded
  target, marked remainders and one-sheet pickup delay.
  [Paired fixture](../tools/press_world_checks.py)
- [x] Original `bulkPressing` option on the ground, Depot and Belt. Verify
  full-stack outputs and reload the setting on an already placed Press.
  [Paired fixture](../tools/press_bulk_checks.py)
- [x] Loose-item Press cooldown after a completed stroke. Verify waiting for
  the next scan and freezing the countdown while drive is disconnected.
  [Paired fixture](../tools/press_scan_checks.py)
- [x] First loose-item Press scan from a new Motor or established Clutch.
  Verify the initial ten powered ticks after a long stop and a world restart.
  [Paired fixture](../tools/press_scan_checks.py)
- [x] Ordinary Basin recipe output filter. An active recipe completes after
  the sample changes, and the next one is selected using the new sample.
- [x] Item spouts between Basins. Compare backpressure, partial transfers,
  restart and Wrench routing. [Paired fixture](../tools/basin_spout_checks.py)
- [x] Water and lava spouts between Basins. Compare whole-batch backpressure,
  transfer on the first available tick, a Horizon restart with fluid waiting,
  output tank migration and loss of the only route.
  [Paired fixture](../tools/basin_fluid_spout_checks.py)
- [x] Stock honey and chocolate melts, Basin side transfer, and compaction
  back into a Honey Block or a Bar of Chocolate. Match heat refusal, fluid
  amounts and restart. [Paired fixture](../tools/basin_melt_checks.py)
- [x] Mixer stir particles for occupied slots and visible supported fluids.
  Compare per-tick emission count, direction, sprites, tint and a native
  mid-stir freeze. [Paired fixture](../tools/mixer_particle_checks.py)
- [ ] Complete Basin/Mixer: special filters, more receivers, side-output
  effects, mixed item/fluid results and additional fluid types and recipes.
- [x] Downward Crushing Wheels with direct Chute feed, cobblestone and gravel,
  original processing state and cold restart comparisons.
- [x] Downward Crushing Wheels to a Depot. Compare an occupied top slot,
  a blocked buffer, partial transfer and component retention after a restart.
- [x] Downward Crushing Wheels to a horizontal Belt, dry Chute and Millstone.
  Compare stopped output, partial transfer, item components and restart.
- [x] Downward Crushing Wheels with loose diamond ore and raw iron. Compare
  capture, intake of a marked stack, processing and ejection on every tick.
- [x] Loose and Chute-fed items without a Crushing or Milling recipe. Match
  the original consumption cycle while preserving inputs for unported recipes.
  [Loose fixture](../tools/crusher_no_recipe_checks.py) · [Chute fixture](../tools/crushing_wheel_checks.py)
- [x] Crushing recipe components. Keep different patches on the same output
  item separate while blocked, after a restart and during Depot delivery.
  [Paired fixture](../tools/crusher_component_recipe_checks.py)
- [ ] Crushing Wheel collisions with queued items and other entities, damage,
  and other directions. Expand recipes, output destinations and presentation.
  Add the Experience Nugget's XP interaction.
- [x] Mechanical Crafters with ordinary manual input, original directions,
  a full 5×5 Crushing Wheel recipe and cold continuation. Match the 21-block
  Create 6.0.10 phase trace.
- [x] Redstone start in a full 5×5 Crafter grid with four empty corners and
  direct output to a Depot. Keep the finished stack when the Depot is blocked
  and release it after an actual restart.
- [x] Crafter Slot Covers with ordinary front clicks and downward chest output
  with partial transfer and an actual restart.
- [x] Ordinary shaped and shapeless Crafting Table recipes in a Crafter grid
  up to 3×3. Compare a mirrored axe, a shapeless book, and a cake with blocked
  bucket output that resumes after a native restart.
  [Paired fixture](../tools/crafter_standard_checks.py)
- [x] Empty unlinked Mechanical Crafters in source schematics. Rotation and
  mirror cases match Java, with active or occupied entities rejected atomically.
- [x] Empty dry Chute lines in source schematics, with horizontal rotation and
  mirroring. Incomplete outlets and live cargo are refused before placement.
- [x] Empty standalone Fluid Tanks in source schematics. Keep plain and
  windowed states and reject touching tanks or saved fluids before placement.
- [x] Complete Fluid Tank multiblocks from a Java schematic export. Rebuild
  relative controllers after rotation and reflection, clear stored liquid,
  and reject an obstructed or partial footprint before any placement.
- [x] Crafter ingredient merge and finished-item turn captured in both clients.
  The export and crafting particle events are implemented.
- [x] Downward Crafter output to a horizontal Belt, including a stopped Belt,
  an actual restart and delivery of both wheels on the first powered tick.
- [x] Wrench-linked Crafter inputs and manual feeding in the original slot
  order. Controller offsets survive a restart and separate when a member is
  removed with a Wrench. [Paired fixture](../tools/crafter_link_checks.py)
- [x] Side and upward Crafter outlets. Match stacked container insertion,
  front ejection at a solid target and side entry into a horizontal Belt.
  [Paired fixture](../tools/crafter_outlet_checks.py)
- [x] Crafter output into open and stacked Chutes and powered Smart Chutes.
  Match the different retry schedules. [Paired fixture](../tools/crafter_chute_checks.py)
- [x] Vanilla Hopper input into a linked Crafter array. Match the original
  slot order, cooldown and automatic craft after loading.
  [Paired fixture](../tools/crafter_hopper_checks.py)
- [x] Chute, upward collecting Funnel and differently facing Crafter input
  into linked Crafters. Match components, partial transfers and retries.
  [Paired fixture](../tools/crafter_machine_input_checks.py)
- [ ] Further Crafter automation, edge outlines and connected textures.
- [ ] Crafter special recipes, mixed remainders and remaining animation work.
- [x] Downward Deployer over a Depot and bare Belt. Match small and large
  Cogwheel application, item counts, hand changes and native restart.
- [x] Downward Deployer for vanilla copper waxing, wax removal and oxidation
  removal. Preserve the marked tool and its existing damage.
- [x] Precision Mechanism on a Depot. Match all 15 original steps, saved
  component, Survival transfer and wrong-tool rejection after a restart.
- [x] Automatic Precision Assembly through 15 Deployers on one Belt across a
  chunk boundary. Save and resume after the seventh operation.
- [ ] Remaining Mechanical Saw, Deployer, Spout, Item Drain and Sand Paper
  behavior.
- [ ] General Sequenced Assembly, client progress bar and networked creative
  inventory support for incomplete items.
- [ ] Smart Observer, Stockpile Switch, Packager, packages and factory logistics.

## 4. Schematics and contraptions

- [x] Bounded GZIP/NBT reader, strict palette/state/data checks before writing.
- [x] Bounded creative paste for supported blocks and safe NBT. Unimplemented
  blocks, entities and unsupported data are rejected during preflight.
- [x] Identical bytes of a five-block schematic produced one Copper Sheet in Java and Horizon;
  result collection was checked within a bounded time, without claiming exact timing.
- [x] Bounded horizontal rotations around the schematic anchor. The same
  eight-block Flywheel and Press layout runs in all four directions in both games.
- [x] Bounded horizontal mirrors before rotation. All eight combinations
  preserve the original supported states, motor settings and production.
- [x] Empty inactive Deployers in USE mode, including all 144 orientation
  and transform combinations and atomic refusal of unsafe source or destination data.
- [x] All 48 Encased Cogwheel states in schematics, including all 12 horizontal
  rotations and mirrors of the signed shaft ends.
- [ ] Rotate and mirror the remaining blocks, block entities and entities.
- [ ] Original Schematic and Quill, preview, UI, deployment and Schematicannon.
- [x] Core captures connected blocks with host-provided attachment rules and
  preserves their snapshots through a failed restoration preflight.
- [x] Bearing angle trace and snapped log placement on X, Y and Z verified
  against the isolated Java client. [Architecture and results](contraptions.md)
- [x] Linear, Secondary Linear and Radial Chassis on a vertical Mechanical
  Bearing, including sticky faces, saved ranges and blocked landing recovery.
- [x] Chassis on a dry Gantry Carriage, including sticky capture, translated
  landing and saved ranges after an obstructed restart.
- [x] Chassis on a dry Rope Pulley with the selected range restored after
  restart and landing.
- [x] Chassis and glue on regular and sticky Mechanical Pistons, including
  forced linear rows, radial cargo and saved ranges after a cold restart.
- [x] Wrench range board for the three chassis variants, with single and Ctrl
  group settings and the saved value on reopen.
- [ ] Chassis attached-block outlines, other drivers and complete block movement rules.
- [x] Mechanical Bearing: native assembly, rotation, restart and orphan recovery.
- [x] Separate geometry and pose sync, including older saved records and a
  stationary structure after a cold client/server restart.
- [x] Smooth Bearing and Piston frame interpolation at the default tick rate.
- [x] 2,048-block limit for simple Bearing cargo in one column, with a
  same-tick Java comparison and a native cold landing.
- [x] The same limit for plain Rope Pulley cargo in one column, with a
  compact saved payload and full block counts after a native cold landing.
- [x] The same total for plain vertical Mechanical Pistons, including the
  head and poles, with a cold landing and regular versus sticky return.
- [x] The same total for a Gantry Carriage and plain cargo on a rail within
  one column, with a powered stop and resume after a cold load.
- [x] Original Mechanical, Windmill and Clockwork Bearing settings boards,
  including saved settings and a live Windmill direction change.
- [x] Regular and Sticky Mechanical Piston and Rope Pulley settings boards,
  including waiting, queued clicks and landing after a mode change.
- [x] Dry oak and smooth stone slabs on bearings, with narrow collision
  shapes, state rotation and native reload. Full item contact timing remains open.
- [x] Isolated dry straight oak and stone stairs on bearings and pistons.
  Registry tread geometry and 18 landed states checked in the original.
- [x] Grounded rider transfer on both treads of dry straight stairs on a
  horizontal bearing or piston, with Java and Horizon checks.
- [ ] Stairs that join at corners and waterlogged stairs.
- [x] Twenty-four full-cube Create blocks on bearings and sticky pistons,
  including the solid palettes, zinc blocks and casings.
- [x] Windmill Sail Frame and sixteen sail colors. Dye, shear, placement,
  windmill capture, generated speed and restart verified.
- [ ] Windmill sail placement preview and canvas contact behavior.
- [x] Clockwork Bearing: both hands and three modes, with atomic restoration.
- [x] Regular and sticky Mechanical Pistons: Java tick comparison, retraction,
  terrain stop, restart and recovery in one column.
- [x] Rope Pulley, dry rope and cargo. Lowering, capture, retraction, restart
  and rope break, checked against Java.
- [x] Gantry, bounded loaded rail and carriage. Motion, redstone stop, power
  transfer and restart checked in game.
- [x] Cart Assembler rail actions, mounted cart assembly rules and coupling
  corrections in the engine, with single and coupled Java reference fixtures.
- [ ] Complete Rope Pulley and Gantry presentation, wet lines, coupled pulleys,
  sequenced movement and elevator controls.
- [ ] Native Cart Assembler rails, cart coupling, mounted payload and renderer.
- [x] Dropped-item collision, grounded rotary and linear rider transfer, and
  collision of narrow piston poles in Horizon.
- [x] A full-cube Y-axis rotor carries a dropped item through a loaded neighbor
  at the same end-of-level-tick phase as Java, with a falling control.
- [x] Local player lift on a rising bearing blade and tick-aligned rider
  interpolation. Live Java and Horizon checks cover a rising and receding blade.
- [x] Grounded bottom-slab rider keeps its rotation radius in Horizon. Live
  Java and Horizon traces preserve feet height. Position sampled at matched
  bearing angles still differs by up to 0.154 blocks.
- [x] Unobstructed and wall-constrained side pushes from a horizontal piston,
  including mirrored wall exits checked in Java.
- [x] Side pushes and wall sliding from full cubes on a vertical Mechanical
  Bearing, with a pinned JAR geometry oracle and separate live-client tests.
- [x] One ordinary mounted chest on a vertical Mechanical Bearing, with crop
  and cutter loot, item components, restart and landing recovery.
- [x] One closed barrel on a Mechanical Bearing, including horizontal and
  vertical turns, slot contents and item components after a native restart.
- [x] Two ordinary chests or barrels on a vertical Mechanical Bearing,
  including mixed pairs, ordered banks, obstructed landing and a cold restart.
- [x] An ordinary single Chest and closed Barrel on one dry Gantry within
  one column. The mixed pair retains slot order, item components and facing
  after a cold restart and landing.
- [x] Upward and downward dry vertical Gantry travel in one column. Java
  and Horizon match the in-flight position and both landed banks.
- [x] A mixed pair on a dry Rope Pulley. Cold landing retains both banks.
  Solid cargo replaces ordinary Stone with the Java drop, and a Bedrock
  obstruction retains cargo through restart until the cell is cleared.
- [x] A Chest and Barrel on a vertical Mechanical Piston within one column.
  The extension trace and settled inventories match Java, including a
  process restart with both banks in flight.
- [x] Dry Piston cargo replaces ordinary Stone with the Java drop. A Bedrock
  obstruction retains both banks through restart and releases them once
  the cell is cleared.
- [x] Ordinary chest cargo on Gantry, dry Rope Pulley and both Mechanical
  Pistons. Preserve components and slot order through translated landing and
  an obstructed restart.
- [x] Ordinary single Chest and closed Barrel menus on supported moving
  structures, with original titles, active banks and validated close handling.
- [ ] Full entity contact, larger mounted inventories and double chests.
- [ ] Cross-chunk capture and restoration. First validate a durable two-column
  write with both columns loaded. Recovery must replay an interrupted write
  before either column becomes visible, including across a region boundary.
- [x] Explicit boundary regression. Java can capture and land across a region
  edge. Horizon preserves both source blocks when it refuses either case,
  including after a cold reload.
- [x] Harvester on supported crops, moving Saw and Drill with cutting stalls,
  and horizontal stationary Saw tree felling.
- [x] Harvester blade phase based on distance traveled, including reverse and
  stopped motion.
- [x] First active-cell selection on a newly assembled Mechanical Bearing,
  checked by wheat harvest and Saw output through a portable dock.
- [x] Saw and Drill stall timing on a Mechanical Bearing, with cutting
  progress resumed after a cold restart.
- [x] Mounted Deployer hand and pole oscillation during a bearing stall.
- [ ] Full actor tick ordering and saved movement contexts across all drivers.
- [x] Moving Plough tilling, snow clearing and protection of farmland crops.
- [x] Moving Plough impulses on ordinary living mobs, checked for overlap,
  backward motion, a blocked cell and the original launch tick.
- [x] Downward Deployer planting from its own stock on a vertical Mechanical
  Bearing, with forty matching Java tick samples and restart coverage.
- [x] Deployer refill from a single mounted chest and a moving Saw on the same
  farm. First matching slot, blocked planting and restart checked.
- [x] Two filtered moving Deployers sharing one chest, with separate hand
  stock, bone meal use and restart at the next visited cell.
- [x] Ordinary Deployer filter slot, with ghost selection, clearing and
  hover hints on the supported faces.
- [x] Front hand exchange on a stopped Deployer. Keep full item components
  across saves, including damaged tools and marked stacks, and compare
  Adventure exchange and Wrench modes with Java.
- [x] Chute-to-Deployer farm supply and shutdown, matching 125 Java ticks
  and the final distribution across planted saplings, chest and hand.
- [x] Vertical Mechanical Bearing landing through dry vanilla leaves,
  including guarded retries and drop persistence in Horizon.
- [ ] Advanced Deployer filters and powered overflow.
- [x] Stationary downward Deployer planting with plain saplings, redstone
  lock, speed pause and cold-stroke resume.
- [x] Stationary planting and fertilizing with marked stacks. Keep the
  remaining item components when a stroke uses one and across a restart.
  Load matching stock through the front during a powered stroke.
- [x] Stationary Deployer held sapling with the original fixed and spinning
  display poses.
- [x] Stationary Deployer Use and Attack timing. Match the original empty-hand
  Use interaction with a lever and the Attack stroke that leaves it unchanged.
- [ ] Deployer attacks on entities and blocks, fist bumps, and switching modes
  on a moving contraption.
- [x] Stationary downward Deployer applying ordinary bone meal to supported
  targets, including valid attempts where growth fails.
- [x] Super Glue selection and transfer planner. Deployer stroke, target and
  storage rules checked against Java traces.
- [x] Two-click Super Glue and single-column bearing transfer, with durability
  and saved volume checks.
- [x] Super Glue transfer on dry Gantry and Rope Pulley, with off-origin
  capture and bounds restored after a cold native restart.
- [x] Super Glue first-corner face particles and confirmed or removed volume
  edge particles.
- [x] Offhand Super Glue for ordinary placements in one column.
- [ ] Original Glue outlines, offhand particles for other players, and
  transfer on other drivers.
- [x] Sticker redstone latch and bearing capture through its extended head.
- [x] Sticker head interpolation and stationary attachment feedback.
- [ ] Sticker bounce, wrench and computer interaction.
- [x] Upward stationary Saw wood processing through native item collision,
  with saved progress and Java comparisons of the cutting and ejection cycle.
- [x] Upward Saw's stock vanilla plank variants, stonecutting and Andesite
  Alloy, including recipe rotation and the saved plain output filter.
- [x] Upward Saw ordinary output filter slot, replacement and clearing.
- [x] Horizontal Belt feed into an upward Saw. One log enters while it is
  stopped and resumes cutting after a cold restart. Remaining logs wait.
- [x] Dry vertical Chute feeds an upward Saw one item at a time, including
  while stopped. The rest waits in the Chute and resumes after a cold restart.
- [x] Original Saw server options for bulk cutting and disabling vanilla
  Stonecutting. Match Belt, Chute and landed batches, saved input and the
  distinct lifetimes of block-entity limits and recipe search settings.
- [ ] Remaining Saw recipes, automation, advanced filter items, hover feedback
  and cutting particles.
- [x] Portable Storage Interface unloading from one moving chest into a
  vanilla hopper, with redstone, comparator, item components and restart.
- [x] A dry Rope Pulley docks one moving item interface in its chunk column,
  pauses to unload a chest into a Hopper, resumes and lands both blocks.
  Upward and downward traces match Java. A cold restart preserves the dock
  position and the items still in transit.
- [x] A vertical Mechanical Piston docks a moving item interface and chest
  with the same Hopper transfer, held offset, release and landing as Java,
  including across a cold restart.
- [x] Gantry docks a moving item interface within one loaded chunk column.
  Hopper extraction, release and landing match Java, and a cold restart
  retains the working dock and items still in transit.
- [x] Dry vertical Chutes with container and stacked transfer, manual crafting,
  and direct unloading from one moving chest through a portable interface.
- [x] Stationary waterlogged vertical Chutes with Barrel and side Hopper input.
  Match cold restart with cargo in both columns and placement in air or water.
- [x] Fan airflow through waterlogged ordinary Chutes. Compare upper suction
  limits, lower-Fan reversal, both straight native restarts and one wet fork.
- [x] Cold restart of the waterlogged fork in the original Java and Horizon
  clients. The in-flight stack and both delivery ticks match.
- [x] Dry diagonal Chutes in all four directions. Place by clicking a side,
  route cargo through two connected slopes, and update shapes on disconnection.
- [x] Hopper admission to ordinary angled Chutes in air and water. Match
  occupied-slot refusal and resumed transfer when the destination opens.
- [x] Vertical Chutes deliver to Depots and Millstones. Compare blocked
  Depot slots, recipe refusal, partial Millstone input and saved cargo.
- [x] Industrial Iron encasement on a dry vertical Chute. Ordinary clicks
  preserve the moving stack and its components, including on restart.
- [x] Chute input into a moving chest through a portable interface, including
  partial transfer and component preservation.
- [ ] Generic portable item automation, fluid interfaces, and Plough
  contact with players and falling blocks.
- [ ] Shared-schematic checks: identical machines produce identical results in both clients.

## 5. Fluids, railways and other content

- [x] Thirteen solid andesite, granite and diorite variants with the original stonecutting recipes,
  drops, local models and a building-blocks tab. Layered connected textures remain open.
- [x] Industrial and Weathered Iron Blocks, their Stonecutter recipes, Wrench pickup,
  and fan washing with the original output count.
- [x] Zinc and Deepslate Zinc Ore generate in new Overworld chunks.
  Raw Zinc, its storage block and the original furnace and blast furnace recipes
  complete the ordinary zinc supply route.
- [x] Straight dry Fluid Pipes and one Mechanical Pump between standalone tanks.
  Water and lava, RPM and pressure traces, Wrench reversal, backpressure,
  cross-chunk transfer and cold restart.
- [x] One inline Fluid Valve in the dry straight line. Signed shaft speed,
  pressure while closed, partial-travel stops, cold restart, resumed flow
  and face-sensitive Wrench rotation.
- [x] Dry pipe bends across loaded chunks. Match hand placement, neighbor
  reconnection, per-face pressure and startup transfer with Java.
  [Paired fixture](../tools/fluid_pipe_bend_checks.py)
- [x] Waterlogged pipe placement and lava transfer without replacing the water.
- [x] Closed pump networks with one source and multiple outlets. Match
  branch pressure, separate fill fronts and partial capacity.
- [x] Independently powered Fluid Valves on separate branches of one
  pump. Match pointer timing, independent gating and pressure rebuild.
  Compare rendered pointer travel on east, west and north-facing valves.
  A pointer already in motion keeps its original chase during single steps.
- [x] Configurable pump range. Compare pressure at the cutoff and fluid
  delivery on a short branch beside an out-of-range branch.
- [x] Co-directed pumps in series on an unbranched connecting path. Match
  additive pressure, source-based delivery, shutdown and restart. A capped
  side arm stays dry while the connecting path works.
- [x] One or two active side tanks between two co-directed pumps. Verify
  both pressure components, directions, fluid fronts and transfers across
  changes to which pump is powered.
- [x] Water and lava collision on a side branch between two co-directed
  pumps. Compare the broken junction, pipe drop, pressure and fluid volumes.
  When a second branch survives, verify that it regains pressure and its
  tank resumes filling, including after a Horizon restart.
- [x] Two opposing pumps without middle storage. Verify exterior pressure
  and flow, no transfer between the pumps, and conservation in both tanks
  when stopping and restarting one drive across a three-pipe middle.
- [x] Closed pump networks with multiple inlets. Verify unequal path
  lengths, an empty or nearly empty inlet, and water–lava collisions.
- [x] Two closed inlets and two closed outlets in the same network. Match
  pressures, fluid fronts and amounts, including small inlet and outlet limits.
- [x] Startup rim drips for water and lava and the original render distance.
- [x] An open end on an unbranched pump route. Compare finite and
  regenerating sources, waterlogged intake, source placement, fluid
  particles and recovery of partially filled buffers after a restart.
- [x] Draw from full water and lava cauldrons. Leave partial cauldrons
  alone and refuse to fill a cauldron from an open end.
- [x] Draw 250 mB of honey from a full bee nest or beehive. Keep the
  untransferred amount through restart and leave partial hives alone.
- [x] Honey and Chocolate in closed pump lines and tank windows. Verify
  separate contents, capacity, cold restart and local JAR sprites.
- [x] Direct Honey Bottle exchange with the Basin in Survival and the
  normal Fluid Tank in Creative. Compare Survival tank refusal and empty
  Glass Bottle use on both containers.
- [x] Ordinary Water Bottle and Glass Bottle exchange with the Basin and
  normal Fluid Tank. Match potion components, stacked containers, Creative
  behavior and refusal at insufficient volume or capacity.
- [x] Open-outlet reactions with still and flowing water or lava. Match
  obsidian, stone and cobblestone formation without draining the tank.
- [x] One open inlet supplying multiple closed outlets, including finite
  and renewable water, lava cauldrons and unequal free capacity.
- [x] Two open inlets at a junction. Match buffer timing, continuous draw
  after emptying, and total delivery from cauldrons, bee nests and beehives.
- [x] One open outlet alongside closed tank outlets. A blocked branch
  drops out and a spill reaction rebuilds the remaining network's pressure.
- [x] Two open outlets on separate cells. Verify simultaneous placement,
  one or two reactions and conservation from the closed supply tank.
- [x] A cauldron feeding two open outlets. Verify independent buffers,
  reaction without consumption and conservation through the rebuild and
  across a full Horizon restart.
- [x] Evaporate water in the Nether and continue to place lava sources.
- [x] Honor the original server option that disables source block placement.
- [ ] More than two active side tanks or open side endpoints between pumps,
  active side endpoints and adjacent-drive rebuilds for opposing pumps,
  loops, collisions involving custom fluids, shared open outlet cells and
  other fluid machines.
- [x] Item Drain from a bare Belt to a Depot. Water bucket, full tank,
  blocked exit, resumed cargo and original resource rendering.
- [x] Item Drain with a held water bucket in Survival and Creative. Match a
  refused pour and empty-hand cargo recovery, including item components.
- [x] Item Drain comparator directly adjacent or behind a solid conductor.
  Match signal strength and timing after a conveyor or hand pour.
- [x] Lava buckets through a Belt or by hand. Keep incompatible fluids separate.
- [x] Honey bottles through a Belt or by hand. Match 250 mB exchange, glass
  bottle delivery, blocked capacity, restart and Survival or Creative use.
- [x] Ordinary Water Bottles through a Belt or by hand. Match the
  component-bearing bottle through a restart, glass bottle delivery,
  blocked capacity and Survival or Creative use.
- [x] Item Drain output to a horizontal Belt across a chunk boundary, with a
  stopped outlet and actual restart before release.
- [x] Standalone Fluid Tank for water and lava. Creative bucket interaction,
  original tank save data, Wrench windows and comparator output.
- [x] Fluid Tank towers and complete 2×2 and 3×3 layers. Shared bucket and
  comparator behavior, Wrench windows, controller ownership and restart.
- [x] Configurable Fluid Tank height with grouping above and below the
  default. Keep over-capacity saved fluid accessible to drain.
- [x] Configurable Fluid Tank capacity for new inventories, with existing
  inventory limits and the original goggles display during a live change
  and after restart.
- [x] Fluid Tank and Item Drain contents in the Engineer's Goggles overlay.
- [x] Automatic top and bottom layer placement with Java's stock, space and
  sneaking checks, including cold restart.
- [x] Lava light by layer and window visibility, measured across a chunk
  boundary in both clients.
- [x] Deferred tank splits after a clean restart with an unloaded controller
  or member column.
- [x] Connected Fluid Tank textures with the original JAR, including roofs,
  vertical frames, separate neighboring tanks and a clean restart.
- [x] Keep fluid visible in high windows when the controller leaves the frame.
- [x] Straight pump lines between Fluid Tanks and Basins. Match transfer
  startup, input and output tank order, and backpressure against Java.
- [x] Pump extraction from the Item Drain's side and bottom, with top and
  fill refusal and a final partial transfer.
  [Paired fixture](../tools/fluid_pump_basin_checks.py)
- [x] Empty, water and lava Tank groups on a vertical Mechanical Bearing
  within one chunk column. Capture from a member, connected shell, fluid
  in motion, obstruction handling, rotated landing and cold restart.
- [x] Complete ordinary Tank groups on a dry Rope Pulley within one column.
  Compare empty, Water, Honey and Chocolate during capture, cold restart
  and landing in both directions.
- [ ] Boilers, virtual moving-tank light and assemblies spanning chunk columns.
- [ ] Other Drain containers, Hose Pulley, Spout, displays and fluid levels.
- [ ] Trains: tracks, signals, stations, assembly, controls, schedules and persistence.
- [ ] Logistics networks, Redstone Links, Display Links and Display Boards.
- [ ] Materials/ores/world generation, decorative families and the full crafting set.
- [ ] Other equipment, tools, consumables and entity interactions.
- [ ] Original configurations, achievements/advancements, recipe integration and Ponder tutorials.

## 6. Extensibility and future mods

- [ ] Documented Rust APIs for kinetics, recipes, transported items, UI and contraptions.
- [ ] Stable contraption identity, coordinate systems and world/transform boundary.
- [ ] Separate Sable physics adapter with force, collision, persistence and network tests.
- [ ] Create Aeronautics on verified Create/Sable, without decorative substitutes for physics.
- [ ] Example external Rust addon and API version policy.

Keep Java comparisons beside each new subsystem. Playable stages receive a
build, validation evidence and a separate review world.
