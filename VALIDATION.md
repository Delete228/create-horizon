# Checks and evidence

## Fallback artwork gallery

- [The texture register](docs/fallback-textures.md) covers 152 independent
  16 × 16 textures. The distribution check validates every referenced PNG
  and compares the native archive's bytes with the content mod.
- [The gallery fixture](tools/texture_gallery.py) verifies 84 public
  blocks, 27 additional displays and all 38 standalone items. In the
  same Horizon world, the native build displays the bundled artwork,
  switches to the player-supplied JAR after restart and returns to
  bundled artwork after the JAR is removed.

## Public block and processing audit

- The [block catalog check](tools/block_catalog_checks.py) loaded all 84
  public blocks in each client, compared placed properties and block entity
  IDs, and checked the raw defaults separately. All 84 match, including
  the six raw Fluid Pipe sides and the two sides left open after an
  isolated command placement. The standalone Fluid Tank's two internal
  Horizon properties are checked separately and both default to zero.
- The [crushing recipe check](tools/crusher_recipe_checks.py) feeds one
  item through a Chute into a working pair of wheels. It compares 1,320
  tick samples from 44 distinct inputs, checking intake, countdown,
  application and release. Each run checks mandatory and possible output
  counts against the recipe because the clients have independent RNG
  streams. The bundle includes 45 crushing recipes. Tuff recycling shares
  its only currently registered input with the primary Tuff recipe and
  is not exercised as a separate case. The remaining eight unconditional
  crushing recipes use decorative stones that are outside the current catalog.
  A local JAR import supplies the models and textures for all four new
  materials. An instance with the previous import cache rebuilds it once.
- This pass also rechecked the Fluid Pump, standalone Fluid Tank, Basin
  filter, adjustable chain drive, Clutch, Gearshift, Clockwork Bearing,
  Saw and Drill actor timing, mounted Barrels, sail placement and dyeing,
  Gantry travel and obstructed restart, piston hand actions and the
  standard Mechanical Crafter. Portable Storage Interface also matched the
  natural and redstone-triggered docking traces and passed the native
  refusal and cold restart checks. Loose Crusher input and material
  particles passed their separate comparisons. The moving Harvester,
  Plough, stationary Deployer copper interactions, and Smart Chute amount
  settings passed their paired fixtures.
- The [Hand Crank fixture](tools/crank_support_checks.py) matches six
  support-loss directions, with unrelated neighbor changes leaving the
  crank in place. It checks the dropped item and retained water source,
  dry and submerged hand placement on a slab, and the ordinary Wrench
  click that starts the crank without reorienting it. An older native world
  reloads the same crank ID and wet state in the updated client. The [engineering
  check](tools/engineering_checks.py) compares the submitted crank base
  and handle poses with live speed on all six facings.

## Configuration after world reload

- [Motor and Chassis boards](tools/chassis_value_settings_checks.py) apply
  fresh edits after opening a saved world. The motor's signed RPM and the
  Chassis range are still present after another restart. Escape keeps the
  old value, and a Chassis edit still requires a Wrench at confirmation.
- [Bearing and actuator boards](tools/bearing_value_settings_checks.py)
  compare the displayed choices with Java and commit a different choice
  after reopening the save. A second restart verifies the edit for
  Mechanical, Windmill and Clockwork Bearings, regular and sticky
  Mechanical Pistons, and Rope Pulleys.

## Vertical Funnel audit

- [Brass Funnel](tools/brass_funnel_checks.py) checks real short and long
  presses, the filter preview, Exactly and Up to, the Snowball stack limit,
  release to confirm, and Escape to keep the previous amount. At GUI scale
  4 the compared cursor labels and coordinates agree for `=16`, `≤16`,
  `=32`, and `Any`. The Horizon restart preserves the marked filter and
  Exactly setting. The Java test bridge holds a short press for one client
  tick, so screenshot capture cannot turn it into a long press.
- [Crusher output](tools/crusher_transfer_checks.py) and [Saw output](tools/saw_chute_checks.py)
  compare direct transfer through upward Brass Funnels into ordinary
  inventories. A powered funnel keeps cargo in the source. On release it
  takes matching marked stacks, with rejected stacks staying in the crusher.
  Both fixtures also check a Horizon restart and the other supported
  receivers. The Saw below a downward Crusher remains a blocked exit in both
  games.
- The [Fluid Valve wrench](tools/fluid_valve_wrench_checks.py) and
  [Item Drain comparator](tools/item_drain_comparator_checks.py) comparisons
  also pass against their pinned Java traces.

## November 8–9 parity audit

- [Pipe bends](tools/fluid_pipe_bend_checks.py) compare 65 ticks of a dry
  line that changes direction four times and crosses a chunk boundary.
  Both clients start transferring on tick 47 at 16 mB per tick, with the
  same pressure and fluid progress on each face. Ordinary placement and
  removing and replacing a neighboring tank produce the same ports. The
  waterlogged variant moves lava at the same rate while keeping its water.
- [Pipe branches](tools/fluid_pipe_branch_checks.py) compare 84 ticks in
  each of three closed single-source networks. Both clients share pressure
  by depth, reach a short outlet before a long one, and redirect unaccepted
  flow when a target has only 3 mB of room.
- [Branched Fluid Valves](tools/fluid_valve_branch_checks.py) match all 178
  ticks with one gated outlet and all 250 with two independently gated
  outlets. The comparisons include pointer value, target and speed, valve
  state, pressure rebuild pauses and fluid amounts in the ungated bypass.
  A cold Horizon restart preserves both pointers, their open states and
  all four tank amounts. Restoring the drive leaves the closed branch idle.
- [Fluid Valve pointer frames](tools/fluid_valve_pose_checks.py) compare the
  original JAR model at rest and at 45° of travel. East and west have the
  same negative image slope, and north has the opposite slope, in both
  clients. The native east pointer previously leaned the other way.
- [Fluid Valve single steps](tools/fluid_valve_step_checks.py) freeze a
  moving pointer at 0.3 and step four game ticks. Each client advances
  0.1 per step while keeping the target at 1. The ordinary inline and
  two-branch cold restart regressions pass after this change.
- [Pump range](tools/fluid_pump_range_checks.py) compares five lines at
  each of two configured ranges. All 720 lane snapshots match. The last
  pipe inside the range carries pressure and advances its flow, and the
  pipe beyond it stays idle. A short branch can still fill its tank while
  the longer branch is out of range.
- [Pumps in series](tools/fluid_pump_series_checks.py) match 636 lane
  snapshots across adjacent pumps and three-pipe gaps. The intermediate
  pipes combine the two pressure contributions. Delivery uses the source
  face's pressure at both equal and unequal RPM. The fixture also compares
  the pressure wipe and retained flow at shutdown and restart. Another
  636 snapshots include a capped arm between the pumps. The arm stays
  unpressurized while flow continues along the connecting path.
- [Two inlets and two outlets](tools/fluid_pipe_cross_branch_checks.py)
  match 464 snapshots in the same network. The fixture includes unequal
  path lengths, an inlet with 3 mB, and an outlet with room for 3 mB.
  Pressure, fluid fronts and all four amounts agree at every sampled tick.
- [An active side tank between two pumps](tools/fluid_pump_overlap_checks.py)
  matches all 1,240 lane snapshots. The cases cover pressure favoring
  either direction, a tie, and an initially empty side tank. Check both
  pressure components, all observed flow fronts and the three stored
  amounts while running both pumps, either pump alone, and both again.
  A native restart at tick 70 restores pressure and preserves every lane's
  total. The side tank continues to fill or drain according to the pumps.
- The same fixture with `--paired` matches another 1,240 lane snapshots with
  two side tanks. It compares both branch pressures, flow direction and
  progress, and all four amounts through the same four drive phases. The
  two side tanks also preserve their volumes and resume the expected flow
  directions after restarting the Horizon world.
- [Water and lava between co-directed pumps](tools/fluid_pump_overlap_collision_checks.py)
  match 168 snapshots across the two directions. The branch delivers 90 mB
  before the junction becomes cobblestone, then drops one pipe. The test
  compares the saved contents, retained flow and pressure recovery.
- The `--split` variant matches another 168 snapshots when the break leaves
  a second side tank connected. That branch regains pressure while the
  blocked faces still retain their old flow. A native restart during
  recovery preserves all four tank contents and resumes filling the
  connected tank without another pipe drop.
- [Opposing pumps with no middle storage](tools/fluid_pump_opposed_checks.py)
  match 160 snapshots with both pump faces pushing inward or pulling
  outward. The exterior pressure and inlet flows match at unequal RPM,
  the middle stays idle and neither tank loses fluid. The `--toggle`
  variant matches 180 more snapshots through shutdown and restart,
  including the briefly cleared pressure on the still-powered pump.
  Both fixtures use three pipes between the pumps.
- [Two pump inlets](tools/fluid_pipe_inlet_branch_checks.py) match 504
  pressure, flow and storage snapshots across six closed networks. Each
  equal branch supplies 8 mB per tick at 32 RPM. An extra pipe raises its
  own branch to 16 mB per tick. In both mixed water and lava cases the
  junction becomes cobblestone and drops one pipe before drawing fluid.
  The disconnected faces keep their prior flow during the same rebuild
  ticks in both clients. Both broken junctions and their single pipe drops
  remain after a cold Horizon restart without draining either source.
- [Pipe rim particles](tools/fluid_pipe_rim_checks.py) detect water and lava
  drips at both rims of the pump on activation. The Horizon fixture also
  checks a 20-block cutoff and returns to range without creating a
  new startup drip on an existing flow.
- [Open pipe ends](tools/fluid_pipe_open_checks.py) compare six 90-tick
  sequences. They cover finite water and lava, a regenerating source,
  waterlogged input and both fluids going back into the world. A restart
  with fluid in all six buffers conserves volume. Horizon keeps the buffer
  visible in the save while Java briefly omits it during pressure rebuild.
- [Pipe and cauldron checks](tools/fluid_pipe_cauldron_checks.py) compare four
  90-tick sequences. Full water and lava cauldrons each yield 1,000 mB.
  A partly filled water cauldron stays unchanged, and a pump cannot fill
  an empty cauldron through an open end. Both clients pause transfer while
  the change to an emptied cauldron rebuilds pressure.
- [Paired open inlets](tools/fluid_pipe_open_inlet_pair_checks.py) match
  332 snapshots of a junction drawing from two full water cauldrons or a
  full hive and nest. Both buffers start on the same tick and drain into
  one tank without the rebuild pause of a straight intake. The final tank
  contains 2,000 mB of water or 500 mB of honey. An actual Horizon restart
  with fluid in all four inlet buffers preserves both final totals.
- [Tank height config](tools/fluid_tank_height_config_checks.py) compares
  120 parts at configured heights 2 and 36. Single towers and 2×2 and
  3×3 tanks assign the same controllers, including across a chunk boundary.
- [Tank render bounds](tools/fluid_tank_render_bounds_checks.py) compare
  filled and empty windows with the original assets. Water remains visible
  at the top of a six-block tower after its controller exits the frame, and
  in a four-layer 3×3 tank that crosses a chunk boundary.
- [Tank capacity config](tools/fluid_tank_capacity_config_checks.py) changes
  the active setting from 4 to 2 buckets. An existing single tank and 2×2
  layer still accept 4,000 and 16,000 mB. A new single tank accepts 2,000 mB.
  In both clients the original goggles overlay shows the current configured
  capacity (2,000 and 8,000 mB) even on the existing tanks. A full restart of
  each client preserves the saved amounts and the three overlay snapshots.
  Refilling after the restart uses the new 2,000 and 8,000 mB limits.
- [Over-capacity saved tanks](tools/fluid_tank_overflow_checks.py) retain
  8,001 mB water, 19,000 mB lava and 64,250 mB honey on read, as in Java.
  Each line then transfers 112 mB. The remaining lava and honey can still
  exceed the fill limit without disabling their tank.
- [Paired open outlets](tools/fluid_pipe_open_outlet_pair_checks.py) compare
  516 snapshots of two outlets fed from one closed tank. Two empty branches
  place water on the same tick. With one or two lava branches, obsidian forms
  before the remaining flow resumes. Java briefly omits a 1 mB buffer from
  NBT during one rebuild. Horizon keeps the same fluid visible throughout.
  With `--world-source`, another 516 snapshots compare an open cauldron
  inlet feeding two outlets. The tankless circuit retains 500 mB per empty
  outlet, makes one water source if only one outlet is open, or leaves the
  cauldron full when both outlets react with lava. Horizon retains buffers
  in the save during the brief rebuild in both clients. A cold Horizon
  restart at tick 60, with 774 mB at the inlet and 113 mB at each outlet,
  ends with 500 mB in each of the two outlets.
- [Pipe spill reactions](tools/fluid_pipe_spill_checks.py) compare five
  50-tick traces with still and flowing water and lava, plus a waterlogged
  slab. Both clients form obsidian, stone or cobblestone on the same tick,
  with the original 2,000 mB still in the supplying tank.
- [An open inlet on a branched pipe](tools/fluid_pipe_branch_source_checks.py)
  supplies two tanks in four 130-tick traces. Finite water and a lava
  cauldron split into 500 mB per tank. A waterlogged block sends 997 mB to
  the second tank when the first has only 3 mB of room. A regenerating
  water source stays in place and feeds both tanks equally.
- [An open outlet on a branched pipe](tools/fluid_pipe_branch_outlet_checks.py)
  matches four 185-tick traces with a second outlet feeding a tank. It
  covers a nearly full tank, an already blocked pipe and an obsidian
  reaction that pauses the remaining outlet for four ticks. Fluid stays
  accounted for in tanks, the open-end buffer and the resulting source.
- The [open pipe check](tools/fluid_pipe_open_checks.py) also compares
  155 ticks in the Nether. Both clients evaporate two buckets of water,
  leaving the outlet empty, and place one lava source before stopping.
  The evaporation code uses Create's sound event, position, volume and
  pitch range. The fixture measures fluid volumes and block states.
  With `pipesPlaceFluidSourceBlocks` disabled, a further 155-tick run
  confirms both outlets discard full buffers without creating blocks.
- The [open source fixture](tools/fluid_pipe_cauldron_checks.py) also
  compares a full bee nest, a full beehive, a partially filled hive and
  refused filling. Each full block yields 250 mB, with the same pressure
  pause as Java. A cold restart at 80 mB transferred preserves the other
  170 mB in both inlet buffers.
- [Honey and Chocolate pump routes](tools/custom_fluid_storage_checks.py)
  compare 280 ticks across four cases, including the last 3 mB of space
  and refusal to mix the two fluids. The native routes continue after a
  cold restart. Separate frames verify both fluids are visible with
  imported and bundled resources. In the imported tank scene, Horizon
  uses the original still sprites and renders them slightly brighter.
- [Open pipe particles](tools/fluid_pipe_jet_checks.py) compare water intake
  and lava output with the original client. The sprites, tint and lava's
  block light match. The samples check the original spawn ranges and
  direction-dependent velocities.
- [Open pipe entity effects](tools/fluid_pipe_effect_checks.py) check eight
  mobs across 26 ticks without placing a fluid source. A successful water
  fill extinguishes burning sheep without hurting a Blaze. Lava ignites for
  60 ticks on a fifth world tick. Ordinary fire damage begins the next tick
  and fire resistance prevents it. The downward outlet reaches farther
  below, and a blocked outlet leaves both the source and the mob unchanged.
- [Open pipe dousing](tools/fluid_pipe_douse_checks.py) compares a fire,
  candle, campfire and outside control on the first eligible water fill.
  Both clients extinguish the first three and leave the control burning.
  An integrated player catches fire under the lava outlet and is
  extinguished under the water outlet with both exposed blocks still air.
- [Open pipe items and arrows](tools/fluid_pipe_portable_checks.py) compare
  seven entities over 27 ticks. Lava ignites an ordinary dropped item and
  regular and spectral arrows for 60 ticks. The item takes ordinary fire
  damage the following tick. Default netherite and a stack with an explicit
  fire-resistance component stay intact, and water clears burning items and
  arrows. This fixture measures server state. Dropped-item flame rendering
  and prototype resistance removals remain outside its scope.
- [Pump endpoints](tools/fluid_pump_basin_checks.py) compare eight
  70-tick traces with Basins and Item Drains. Check Basin output priority,
  full targets, side and bottom extraction, blocked top access, and a
  final 12 mB transfer that empties the Drain.
- [Multiblock tank schematics](tools/schematic_tank_checks.py) use an actual
  Java export with 37 tank parts. Horizon restores all 12 horizontal
  transforms and checks a cold restart, including across a chunk border.
  Java loses windows or controller links in nine transforms. A partial
  source, an existing touching tank and an obstruction refuse the whole
  Horizon paste. Both clients clear the exported liquid on creative paste.
- [Moving tanks](tools/bearing_tank_checks.py) compare capture of a whole
  2×2×2 Tank from a single attached member. Empty, water and lava cases
  match the Java bearing angles and rotated controller location. The
  native fixture carries 19,000 mB through a blocked landing, clean
  restart and repeated capture. A touching independent tank stays in
  place. The original JAR shows fluid in motion after restart. Virtual
  light propagation inside the moving structure is still open.
- The [rotating rider check](tools/contraption_rider_checks.py) records the
  angle and position together on the Java client. Across 13 descending blade
  samples between −95° and −125°, the maximum height difference dropped
  from 0.073 to 0.0041 blocks after moving active full-cube rotor contact
  to the end of the local player tick. The full sweep still has a maximum
  difference of about 0.101 blocks. The horizontal camera checks pass with
  bundled and locally imported assets. An original-JAR run with additional
  diagnostic logging exposed intermittent missed carry during uneven pose
  delivery. Its worst observed position difference was 0.692 blocks.
- The same fixture now holds the server for three local ticks, then stalls
  the client window while the server advances the rotor by 9.6°. The player
  keeps the same horizontal position during the hold, and the later descent
  matches Java within 0.0019 blocks. A separate diagnostic-load replay
  matches the descent within 0.0041 blocks. Unit cases check duplicate poses,
  ticks with no update, a contiguous burst and discontinuous or replaced
  geometry.
- [Moving Slime Block contact](tools/rotary_slime_item_checks.py) compares
  four airborne rebound ticks and the first impact on stone and on slime
  below the bounce threshold. The largest measured Java/Horizon position
  or velocity component difference is `5.32e-8`. The old Horizon client
  treated the hard slime impact like stone. The [rotary contact oracle](tools/rotary_contact_oracle.py)
  compares separation, time of impact, surface contact, normal and hit
  location in 103,680 player and item cases on all three axes.
- [Belt surface phase](tools/belt_render_oracle.py) compares 1,600 configurations
  against the pinned Flywheel visual and shader. The [native mesh check](tools/belt_render_game_checks.py)
  verifies 60 submitted meshes across four facings and five slopes. The east-facing live lane
  shows opposite motion on the upper and return surfaces in both clients.
  Both surfaces stop and reverse, and the stopped texture phase matches.
  The compared native crops are about four to five gray levels brighter.
  The separate six-lane transport fixture still matches 16 of 18 phases.
  In the south-facing horizontal lane, the first two Java segments name
  each other as kinetic sources and retain 32 RPM after disconnecting. The
  same result is recorded with imported and bundled assets. Horizon
  intentionally keeps the normal 32, 0, −32 RPM sequence in this lane.
- [Fan entity discovery](tools/fan_search_checks.py) compares 34 observations
  across four lanes, covering dropped items and sheep during steady flow,
  a neighbor update, an unblocked outlet and a motor restart. All observations
  match after separating the obstruction and entity search schedules. The old
  adapter applied force early in 11 observations.
- [Hot and wet fan effects](tools/fan_hazard_checks.py) match 40 mob samples
  for health, burning time and hurt time. Lava ignites a sheep for 200 ticks
  and smoke for 40. A Blaze resists the lava jet and takes drowning damage
  in the water current. Both clients give the player a first 4-point lava
  hit and extinguish the fire on the first wet tick. The player countdown
  continues between native control queries, so exact timer comparison covers
  mobs only.
- [Fan airflow particles](tools/fan_particle_java_checks.py) compare the four
  processing media with the original JAR in both clients. The smoke push and
  haunting pull follow the observed 4.84375-block outlet. A full obstruction
  and a 1/32-block opening retire the particles on their first update. The
  comparison checks direction, bounds, lifetime, sprite frames, and color
  ranges across separately seeded runs.
- [Upward fan ground contact](tools/fan_player_ground_checks.py) matches all
  20 position, velocity, and ground-contact observations. A 1 RPM upward
  current changes vertical velocity while the player stays on the grate.
  The previous Horizon adapter cleared ground contact in all ten powered
  observations.
- [Fan server settings](tools/fan_config_checks.py) match four client current
  ranges and 59 processing observations. Signed RPM selects the 29- or 7-block
  maximum before scaling on either facing. The fan detects a distant obstruction
  on the configured check. A running server picks up a valid four-to-zero-tick
  processing edit on the next new stack.
- [Fan-powered vertical Chutes](tools/chute_fan_checks.py) match all 165
  cargo, position and airflow observations with the original JAR. Hopper
  input arrives in the top Barrel on tick 29. A full Barrel holds the stack
  halfway, including across an actual Horizon process restart. After one slot
  is freed, the seven-item stack arrives on tick 45. Reversing the motor
  publishes the new airflow on the same tick as Java and leaves the cargo
  safely parked in the lower Chute.
- [Suction from an upper Fan](tools/chute_suction_checks.py) matches 30
  full observations in uninterrupted and cold Horizon runs. The open Chute
  reaches three blocks. A trapdoor shortens the reach to 1.84375 blocks,
  so the nearby stack is captured and the farther stack stays in the world.
  A two-Chute column pulls seven component-bearing items from its lower
  Barrel and returns the stack intact when the Fan stops. The same Java
  fixture also records a 128 RPM split yielding 64 RPM in each branch.
- [A lower Fan feeding a dry Chute fork](tools/chute_split_checks.py)
  matches 124 observations each with uninterrupted and restarted Java
  references. A 128 RPM source splits into two 64 RPM branches. The straight
  branch wins a tie. An occupied straight branch diverts the marked cargo
  through the angled branch across a chunk boundary without moving the
  parked stack. Both clients resume from the same saved offset and reach the
  upper Barrel one tick later after restart, when the upper Chute ticks first.
- [Chute suction from horizontal Belts](tools/chute_belt_suction_checks.py)
  matches 30 observations in uninterrupted and cold runs. Seven marked items
  enter at offsets 0.1 from the Belt directly below or -1.9 from three blocks
  below. Cargo exactly half a block from segment center remains on the Belt,
  and a full-block obstruction prevents extraction.
- [Chute suction from a Depot](tools/chute_depot_suction_checks.py) matches
  48 lane ticks with the original JAR. All 23 marked items enter the Chute on
  the first tick, both from the Depot directly underneath and across one air
  block. The four output items stay in the Depot. A bare dry Fan and a solid
  obstruction both leave the held stack in place. Additional Horizon checks
  cover an occupied Chute, an output-only Depot and an unsupported buffer size.
- [Chute air particles](tools/chute_air_particle_checks.py) compare actual
  rendered particles in five lanes. The checks cover upward exhaust, suction
  below a Chute, a solid obstruction, reversed motion and an idle Chute.
  The original-JAR and fallback clients agree on sprite progression, size,
  opacity, lifetime and bounded motion at the default particle setting.
- [Chute cargo rendering](tools/chute_cargo_render_checks.py) checks three
  original-JAR screenshots with the Chute outside the frame. A stack 2.875
  blocks below the Chute is visible with suction or a window. An opaque Chute
  without suction hides the same stack.
- [Chute cargo motion](tools/chute_cargo_motion_checks.py) observes live
  render fractions while an upper Fan lifts a dropped item. Java and Horizon
  draw intermediate poses and hold the parked cargo at offset 0.5. The
  server retains the original `ItemPosition` field in its saved data.
- [Waterlogged Chutes](tools/wet_chute_checks.py) match 70 transfer observations
  in each of the uninterrupted and cold runs. A Barrel feeds a marked 23-item
  stack through two wet Chutes in the original batches. A side Hopper feeds
  its own marked item through a second wet column. Both clients preserve the
  in-flight stacks and waterlogged states during restart. The lanes use
  separate columns and distinct block-entity hash slots to keep reload order
  repeatable. Real placement clicks agree on the facing, shape and waterlogged
  state in air and in a water source.
- The `--wet` [lower-Fan](tools/chute_fan_checks.py) and
  [upper-Fan](tools/chute_suction_checks.py) runs match 165 lane ticks and 30
  complete snapshots with a native restart. Waterlogged Chutes retain the
  original reversal and blocked-receiver behavior. Upper suction reaches 3
  blocks in open space and 1.84375 blocks at the trapdoor. Seven marked items
  return to the lower Barrel after power stops. The wet
  [fork](tools/chute_split_checks.py) matches 124 observations in each of the
  uninterrupted and cold runs, including diversion across a loaded chunk
  boundary. Java and Horizon reopen the same in-flight stack at tick 13.
  The straight and angled branches deliver at ticks 30 and 50, measured from
  startup. Use `--java --cold --wet --java-root .local/PREPARED_ROOT`
  to run the original test in a separate prepared Java directory.
- [Hopper input to angled Chutes](tools/angled_chute_hopper_checks.py) matches
  84 observations in dry and waterlogged lanes. The Hopper waits while the
  angled Chute is occupied and inserts on tick 15 once the lower Barrel has
  room. All three marked stacks keep their quantities and components.
- [Dry Chutes](tools/chute_native_checks.py) hold a marked stack over a
  powered, downward-facing Andesite Funnel and resume at the same tick as
  Java when the funnel is replaced by a Chest. The [Smart Chute comparison](tools/smart_chute_checks.py)
  also covers an exact-four extraction from a Chest into an open outlet.
  Three matching items wait in the source until four can be extracted.
  Both clients open the amount board and confirm Exactly 16 while the outlet
  is open. [Amount board fixture](tools/brass_funnel_checks.py)
- [Rope Pulley coil](tools/pulley_coil_visual_checks.py) uses the original
  16×32 strip from the local JAR. Both clients show scrolling and reversal
  at three matched offsets during lowering and retraction. Screenshot
  readback can span a simulation tick, so frame-exact phase is unmeasured.
- [Moving Deployer hand](tools/deployer_actor_visual_checks.py) records the
  hand extension passed to each client's renderer before, during and after
  the same bearing stalls against a log. The source wave matched 157 Java
  and 292 Horizon stall frames. The accompanying [actor check](tools/bearing_actor_phase_checks.py)
  matches all 140 Saw and Drill angle/target observations and checks that an
  unsupported filtered Saw remains in the world with its filter.
  The two-Deployer farm still passes its crop, tree and cold-resume cases,
  and the 2,048-block rotor advances across 143 rendered frames.
- [Basin recipe filter](tools/basin_output_filter_checks.py) matches five
  observations of ordinary clicks, recipe rejection and a mid-cycle filter
  change. The running batch finishes and the next batch waits until the
  filter is cleared. A Horizon restart retains the selected sample and
  input stacks. The four existing Press/Basin traces and native restart
  controls still pass, as do 16 physical item-contact scenes and the
  existing Fluid Valve and Crafter comparisons.
- [Basin item spout](tools/basin_spout_checks.py) compares eight states against
  Java Create. A full Basin leaves two brass ingots buffered while another
  recipe waits for output space. The native world reloads with both ingots
  intact. Both clients move one ingot on the first available tick each time
  space opens. Wrench choices, obstruction and route restoration also agree.
- [Basin fluid spout](tools/basin_fluid_spout_checks.py) uses the same private
  fluid-only mixing recipes in Java Create and Horizon. Water and lava each
  wait in `FluidOverflow` when only 100 mB is free and transfer the entire
  250 mB batch on the first tick with sufficient room. A cold Horizon reload
  retains the queue, and the next recipe waits while the queue is occupied.
  Closing the only route clears the queue when the spout faces down. Reopening
  the route moves fluid from the local output tanks into the queue and then
  into the receiver. Horizon also retains an unported fluid payload opaquely.
- [Stock honey and chocolate recipes](tools/basin_melt_checks.py) compare a
  cold mixer, a heated melt, fluid in the receiving Basin after a cold Horizon
  restart and compaction back into the original item. Both clients transfer
  1,000 mB of honey or 250 mB of chocolate through the side spout.
- [Smart Chute Hopper input](tools/smart_chute_hopper_checks.py) matches top
  and side Hopper transfers with plain filters. Both clients skip an earlier
  mismatched Hopper slot, park one marked item and leave later matching items
  upstream until the outlet opens. The first six cargo ticks agree, and a
  cold Horizon restart retains the parked item and its components.
- [Honey Bottle Item Drain](tools/item_drain_checks.py) matches 65 samples
  across three Belt lanes and a cold restart. The drain empties 250 mB on
  the original exchange tick, waits when capacity is insufficient, and
  sends a glass bottle to the Depot after the outlet opens. The
  [hand fixture](tools/item_drain_hand_checks.py) covers Survival, Creative,
  incompatible fluid, insufficient capacity and cargo retrieval. With the
  original JAR, the honey jet and fill surface render in both clients, with
  visible differences in where the jet overlaps the bottle.
- [Direct Honey Bottle use](tools/basin_tank_bottle_hand_checks.py) compares
  five real clicks with the original JAR in both clients. Survival consumes
  the filled bottle and returns glass when used on a Basin. A normal Fluid
  Tank accepts 250 mB in Creative and keeps the marked held bottle. It
  refuses in Survival, and neither container fills an empty Glass Bottle.
- [Direct Water Bottle use](tools/basin_tank_bottle_hand_checks.py) compares
  ten clicks with the original JAR. The Basin returns a 250 mB Water Bottle
  with the original potion component and retains the other marked Glass
  Bottle from a stack. Creative keeps the held bottle. A normal Fluid Tank
  refuses Survival use and exchanges 250 mB in Creative. Both containers
  reject insufficient volume or space.
- [Water Bottle Item Drain](tools/item_drain_checks.py) matches 195
  observations across three Belt lanes, including a cold restart with a
  blocked outlet and a nearly full drain. The held Water Bottle retains its
  potion component until the original 250 mB exchange tick. The
  [hand fixture](tools/item_drain_hand_checks.py) matches five more cases.
- [Crushing Wheel recipe components](tools/crusher_component_recipe_checks.py)
  compare a recipe with two different component patches on the same output
  item. Both clients keep two separate stacks while a Depot is blocked and
  deliver them in the same order. Horizon retains them through a cold restart
  and leaves input for a malformed recipe upstream.

## November 8 development checkpoint

The local client build uses official Nightly `2ebf00a` with the published
changes from [Horizon #11098](https://github.com/horizon-rust/horizon/pull/11098),
[Horizon #11116](https://github.com/horizon-rust/horizon/pull/11116) and
[Horizon #11068](https://github.com/horizon-rust/horizon/pull/11068). This is a
developer source build. The three changes are applied in a separate checkout.

- The [release audit](docs/reviews/0.8-release-audit.md) records the current
  boundaries and the checks to repeat on the first official Nightly with
  all required APIs. The [region-edge comparison](tools/contraption_column_boundary_checks.py)
  exercises separate cross-column source and destination cases. Java
  captures and lands both. Horizon refuses each capture and retains both
  source blocks after a cold restart.
- [Straight stair riders](tools/contraption_stair_rider_checks.py) stand on
  each tread of a dry oak stair on a bearing and on a piston. Both clients
  preserve the supported heights and follow the drive in all four cases.
  The existing rotary and piston slab rider fixtures also pass.
- [Dropped items on a cross-column sweep](tools/bearing_chunk_sweep_checks.py)
  match all nine horizontal Java position samples, including the seven
  samples after contact. Support height and the nearby falling control also
  match the fixture. The old item missed up to 0.357 blocks of horizontal
  travel because it stayed at its original X/Z position.
- [Saw and Deployer filters](tools/contraption_filter_hover_checks.py) match
  nine Java hint and target-face cases with imported or bundled resources.
  Ordinary set, replace, clear and saved filter checks still pass.
- [Crusher output](tools/crusher_transfer_checks.py) matches 60 block
  observations over ten Java ticks. It covers a stopped Belt, a filled dry
  Chute and a Millstone with partial acceptance, item components and an
  unmatched item. A cold Horizon restart preserves the waiting output.
  The earlier Depot and loose ore checks also pass.
- [Crusher particles](tools/crusher_particle_checks.py) compare real item
  drops in both clients. Java showed exactly four new particles in each
  of 16 sampled ticks for both Cobblestone and Raw Iron. Horizon's renderer
  accepted four per observed tick, with the matching block or item sprite.
  The native fixture passed with imported and bundled models.
  The fixture also covers ambient crit sparks, invalid wheel pairs and
  a completed recipe whose output cannot leave. The paired captures show
  the two materials at the same camera angle, with different lighting.
- The [native frame check](tools/contraption_frame_checks.py) sampled
  156 rendered rotary poses and 156 rendered piston poses without a
  backwards step. The [particle check](tools/particle_checks.py) uses
  the real motor board for power changes. It passed the generator
  burst and goggles checks, four fan media, airflow reversal and stop
  cleanup. These checks do not compare full rendered frames to Java.
- The same audit re-ran the bearing and linear movement boards, chassis range
  board, mounted Chest and Barrel menus, cross-column kinetic transmission,
  mixed casing Belt riders, Fluid Valve, Saw-to-Depot output, ordinary Crafter
  recipes and four rotated production schematics.
- [Moving riders](tools/contraption_rider_checks.py) record the camera on a
  rotating platform with the player standing and walking. The largest short
  frame steps in the verification run were 0.032 and 0.062 blocks respectively.
  The same rising blade lifts the player by about two blocks in Java and
  Horizon. The largest sampled position difference at a shared angle was 0.318
  blocks across 51 observations. The previous Horizon build dropped through
  that blade to the floor.
- The [rotary contact oracle](tools/rotary_contact_oracle.py) matches separation,
  impact fraction and surface contact for 51,840 Java cases across X, Y and Z.
  The [native rider checks](tools/contraption_collision_checks.py) also cover
  horizontal and vertical piston transfer, side pushes into a wall, freezing,
  piston poles and dropped items. The separate piston, Rope Pulley and Gantry
  fixtures still pass their Java comparisons and native restarts.
- [Flywheel connections](tools/flywheel_checks.py) transmit 32 RPM along each of
  the three axes and settle to zero after disconnecting. The powered state
  survives a Horizon restart. Ordinary placement matches neighbor preference
  and the fallback for conflicting shaft axes. The Wrench rotates X to Z
  through the top face. The [animation probe](tools/flywheel_motion_oracle.py)
  matched all 7,520 angle samples against Catnip's Java chaser, including
  reverse rotation and coasting. Both fallback and locally imported models
  were inspected in the running client.
- [Stationary Drill drops](tools/drill_drop_checks.py) match the breaking tick
  in six chunk-edge fixtures. Wheat and seeds share a position, with zero
  initial velocity and ten ticks of pickup delay. Ore spawns experience in the
  same vanilla range. The block-drops rule suppresses both loot and ore experience.
- [Drill-fed cobblestone generator](tools/drill_cobble_checks.py) compares
  88 active observations across five layouts. Water, lava and a collecting
  Hopper keep the Cobblestone in place. Full inventory, ordinary breaking
  without a collector and the block-drops rule match. Both clients restore
  the saved state after a cold restart and deliver the first resumed item on
  tick seven. The second arrives on Java tick 19 and Horizon tick 20.
- [Cross-chunk transmission](tools/cross_chunk_kinetics_checks.py) matches all
  64 action observations and all four Horizon reload checks. Cutting the
  boundary shaft stops the disconnected branch during the same action and the
  driven branch keeps rotating. The event path requires a fully loaded idle
  component with no split transmission.
- [Short-range Fan and Depot](tools/fan_depot_range_checks.py) matches all 12
  Java observations. An upward fan beneath a waterlogged Depot starts washing
  flour on tick one and yields one Dough on tick 153. The matching dry Depot
  keeps the flour throughout.
- [Saw-to-Depot transfer](tools/saw_depot_checks.py) matches the inventories,
  direction and cycle state of six blocks over 39 ticks. The cases cover both
  directions of rotation, backpressure from a held stack and from the output
  buffer, and partial delivery across native reloads. Another 22-tick trace
  confirms the default Saw takes one item from a dropped stack.
- [Saw-to-Millstone transfer](tools/saw_millstone_checks.py) matches seven
  block observations across 24 ticks. The cases include cross-column delivery,
  rejection of an unsuitable item, partial insertion into a nearly full
  Millstone, preserved components and a native restart.
- [Saw-to-belt transfer](tools/saw_belt_checks.py) matches all 263 block
  observations across five layouts. They cover inline and side entry, item
  position and interpolation, rejected reversed, stopped and occupied
  entries, and saved cargo after a native restart.
- [Saw-to-Chute transfer](tools/saw_chute_checks.py) matches 48 ticks in
  four cross-column lanes. Plain and matching Smart Chutes receive marked
  stacks. The Saw holds rejected cargo through a native restart and publishes
  on the same tick after changing the filter or removing redstone power.
- [Belt-to-Saw intake](tools/belt_saw_checks.py) retains a marked log in
  the stopped Saw and two on the Belt through a cold restart in each
  client. Cutting and export match. Five of 103 samples show a one-tick
  difference in Belt refills or Chute deliveries after the reload.
  The same fixture with `--chute-inlet` matches all 103 samples exactly.
- [Saw server options](tools/saw_config_checks.py) compare twelve-item
  inputs from a Belt, a dry Chute and a landed stack. With bulk cutting
  enabled, a stopped Saw buffers the marked stack and its original
  100-unit timer through a cold Horizon restart. When Stonecutting is
  disabled, both clients return the original marked Stone and still strip
  the oak logs.
  With `--hot-toggle`, both clients keep a loaded Saw's old bulk limit and
  use the new limit for a freshly placed Saw. The previously cached recipe
  list changes after `/reload`.
- [Chute-to-Depot input](tools/chute_depot_checks.py) matches 48 lane-tick
  observations. A held item or occupied output buffer blocks delivery.
  The marked stack enters with the original vertical pose after release.
- [Stacked Smart Chutes](tools/stacked_chute_power_checks.py) match 19 ticks
  in both placement orders. An adjacent signal holds the marked stack in
  the upper Chute before its next handoff. Removing the signal releases
  the same stack into the barrel below.
- [Belt-to-Millstone transfer](tools/belt_millstone_checks.py) matches
  full and partial acceptance, recipe rejection and a full receiver.
  The canonical input is visible on the transfer tick even if the
  Millstone already ticked. A restart at that point preserves the accepted
  items and components. The Saw-to-Millstone test also passed again.
  With `--chute` the four dry inlet cases match Java as well, including
  partial insertion into a nearly full slot and retention through a restart.
- [Hopper-fed Millstone recipe](tools/millstone_recipe_codec_checks.py)
  compares a datapack with modern and legacy component-bearing results. A
  99-item output slot pauses both clients while the Hopper feeds two marked
  bottles. Horizon retains them through a cold restart. With 64 items left
  in that slot, both clients mill one bottle per cycle, keep distinct paper
  stacks with the same item ID, and return two glass bottles. Each cycle
  follows the original 8, 4, 0 timer sequence at 64 RPM.
- [Millstone item particles](tools/millstone_particle_checks.py) compare
  fresh diamond particles at ±256 RPM, the quiet retry-arm tick, the
  99-item pause, and motor removal and replacement. Java samples the live
  particle engine. Horizon traces accepted spawns with the original JAR.
  An engine test compares the Catnip position and velocity bits separately.
- [Belt-to-Chute-to-Belt](tools/belt_chute_checks.py) matches 120 warm,
  cold, release and running samples across plain and Smart Chute lanes.
  Two Java restarts produced different ticker orders, advancing the first
  Smart Chute transfer by one tick in one run. The comparison accepts a
  complete match to either measured Java trace via repeated `--reference`.
  An incomplete native receiver retains the marked cargo in the Chute until
  it is replaced by a complete Belt.
- [Chute-fed Crushing Wheels](tools/crushing_wheel_checks.py) match 476
  active lane observations for downward wheel pairs, including unequal RPM,
  both ticker orders, stop/resume, Milling fallback and Crushing recipe
  priority. Both clients preserve the inventory and timer before and after
  recipe application through real restarts. The downward output position,
  initial velocity, pickup delay and bypass tag match. A diamond without a
  recipe is consumed on tick six. The completed flag resets on an empty load
  and Netherrack remains in the Chute. Independent random results are checked
  by range.
- [Free-falling ore](tools/crusher_drop_checks.py) matches 400 per-tick
  observations across two downward Crushing Wheel pairs. Both clients catch
  the items on tick 8 and store each stack and its custom data on tick 32.
  The wheels eject the diamond ore results on tick 51 and the four raw iron
  results on tick 183.
- [Loose items without a recipe](tools/crusher_no_recipe_checks.py) matches
  110 ticks per lane for paper and four sticks, including capture, the
  marked input stack and a 100-duration cycle. Both runs end without an
  output drop. The native check preserves Netherrack for its unported recipe.
- [Standalone Diorite crushing](tools/crusher_recipe_checks.py) matches 30
  tick samples, from Chute intake through the 350-duration cycle. The recipe
  gives Quartz with a 25% chance. The native package carries its original ID
  alongside the recipe for decorative Diorite.
  Independent chance outputs are checked against their recipe bounds.
- Mixed colored cargo restores the same cells on a Mechanical Bearing after
  a real Horizon restart. The [separate swept-volume check](tools/bearing_chunk_sweep_checks.py)
  matches nine angles, neighboring-column item support and all 15 landing
  cells. Item movement across the rotating surface still differs horizontally.
  Cross-chunk capture and restoration remain outside the supported boundary.
- [Dry slab cargo](tools/bearing_slab_checks.py) keeps its geometry on the
  moving bearing and restores all 21 cells after a native restart. The Y
  turn preserves the slab halves and the X/Z half turns invert them.
  Waterlogged slabs are refused. Dropped-item support heights match within
  Java's contact offset of about 0.0001 blocks. The lower slab's initial
  contact timing still differs.
- [Rotated schematics](tools/schematic_rotation_checks.py) use the same
  authored file in the original creative placement and in Horizon. All four
  placements match coordinates, states and RPM, with one Copper Sheet made
  by each press. Unsupported rotations and blocked destinations are refused
  before any changes are written.
- [Mirrored schematics](tools/schematic_mirror_checks.py) match all eight
  mirror/quarter-turn pairs on 11 observed cells each. Both motor settings,
  signed RPM, both shaft axes and the eight Copper Sheets match. Invalid
  mirror values, unsupported blocks and bedrock leave the target untouched.
- [Mounted barrels](tools/bearing_barrel_checks.py) match the original
  position, lid direction and contents after a native restart on two axes.
  The refusal checks preserve open, named, locked and loot-table barrels.
- [Paired mounted inventories](tools/bearing_mounted_pair_checks.py) cover
  chest/barrel, chest/chest and barrel/barrel on a vertical Mechanical
  Bearing. Java determines the bank order, and Horizon preserves that order
  and the item components through a cold reload and landing. A save from
  the preceding single-bank build also cold-loads. An obstructed landing
  preserves both banks for a retry.
- [Repeated bearing starts](tools/bearing_repeat_checks.py) cover five ordinary
  clutch cycles with the same chest and barrel. Both clients agree on their
  mounting order, facing and tagged contents after each landing. Horizon
  cold-loads each moving structure before landing it.
- [Mounted storage menus](tools/mounted_menu_checks.py) open an ordinary Chest
  and Barrel in both clients, split their stacks and compare the landed slots.
  Both clients open the chest while it is turning and close it on landing.
  The native check also covers a parked cold reload, a wall in front of the
  target, a click followed immediately by close, and a held cursor stack when
  the player leaves range or dies.
- [Rendered frame continuity](tools/contraption_frame_checks.py) records the
  angles and translations actually submitted to Horizon's renderer. In the
  initial trace, the Bearing played seven frames backwards and the Piston
  played eight. The corrected trace of the same fixtures moves forward across
  both local tick boundaries and arrivals of authoritative poses.
- [Bearing capacity](tools/bearing_capacity_checks.py) checks the default
  Create limit with a Mechanical Bearing and a plain slime payload. Both
  clients capture 2,048 blocks and reach 91.20001 degrees on the sampled tick.
  Horizon lands the payload after a cold restart. Both leave the sampled
  source blocks in place when a 2,049th block is added.
- [Rope Pulley capacity](tools/pulley_capacity_checks.py) checks the same
  limit on a vertical lift. Both implementations reach offset 5.5 after 12
  ticks and land all 2,048 blocks. Horizon saves the packed payload and
  completes the lift after a cold restart. Both leave all 2,049 blocks in
  place when capture exceeds the limit.
- [Rope Pulley Tank cargo](tools/pulley_tank_checks.py) checks a complete
  2×2×2 tank. Empty, Water and Honey loads lift to the pulley. A Chocolate
  load descends and lands after power is removed. The Horizon fixtures
  restart during each move and verify every landed member and fluid amount.
- [Vertical piston capacity](tools/piston_capacity_checks.py) checks both
  directions with 2,043 cargo blocks and five moving head and pole blocks.
  Both reach offset 2.5 at tick 12 and refuse a 2,049th block. Horizon
  cold-loads and lands both assemblies. The regular Piston leaves all cargo
  at full extension and the Sticky Piston retracts it to the original cells.
- [Gantry capacity](tools/gantry_capacity_checks.py) compares 2,047 cargo
  blocks plus the carriage. Both reach offset 0.5 after six ticks. Horizon
  cold-loads the assembly, parks it at the powered middle rail and resumes
  when power is removed. Both land all the cargo and refuse a 2,049th block.
- [Adjustable Chain Gearshift transitions](tools/adjustable_chain_transition_checks.py)
  match all 66 lane observations, including analog changes, an instantaneous
  redstone pulse and a native reload. The model state changes at the
  neighbor notification and analog speed changes on the block entity tick.
- [Piston slab cargo](tools/piston_slab_checks.py) matches half-block
  shapes and the ordinary/sticky retraction outcomes after a native restart
  at 0.46875 blocks of extension. In the [grounded player check](tools/piston_slab_rider_checks.py),
  the rider follows the measured Horizon stroke on both slab halves.
  Java's observed client motion differs from its server stroke sample by
  one tick. The [rotary rider check](tools/rotary_slab_rider_checks.py)
  preserves the lower slab's foot height in both clients. The maximum radial
  drift in the Horizon trace fell from 0.0603 blocks to below 0.000001 blocks.
  Java's radial drift was 0.000354 blocks. The sampled player position still
  differs by up to 0.154 blocks when matched by the separately observed
  bearing angle. The separate full-cube dropped-item fixture is recorded in
  the release audit above.
- [Dry straight stairs](tools/contraption_stair_checks.py) match the 18 landed
  states across quarter, half and three-quarter turns on all three axes.
  A sticky piston preserves both states. Dropped items settle on the two
  tread heights within Java's contact offset of about 0.0001 blocks. The
  native fixture also covers wet stairs and obstructed landing preflight.
- [Solid Create cargo](tools/contraption_solid_checks.py) keeps all 24
  original block IDs on a bearing and a sticky piston. The paired pose
  samples, four in-flight cube contacts and an air control match within the
  original item collision offset. A separate fallback render check reopens
  the save and shows four samples while their stationary cells remain air.
- [Andesite building blocks](tools/andesite_palette_checks.py) use six
  stonecutting recipes checked against the pinned source. Horizon's real
  Stonecutter makes all five variants and converts them back through the
  original family tag. Placing and mining each returns one block. Two
  client starts verified built-in models and original models from the JAR,
  with byte-for-byte matches for 21 original files. Layered andesite still
  lacks connected textures.
- The same fixture verifies eight more solid blocks across granite and
  diorite, ten original recipes and one drop per block. The combined local
  import check covers 40 original files across the three families.
- [Industrial and Weathered Iron](tools/iron_palette_checks.py) both cut
  two blocks per ingot through the ordinary Stonecutter in each client.
  Normal Wrench use leaves the blocks in place, and crouched use returns
  one to the player. An ordinary water-fed Fan processes two Industrial
  Iron Blocks into two Weathered Iron Blocks on a Depot. The local JAR
  import matches 48 original palette resource files.
- [Chute encasement](tools/chute_encasement_checks.py) preserves seven
  marked items and their transit position across four ordinary transitions.
  Industrial Iron is reusable. After a Horizon restart, opening the outlet
  transfers the marked stack intact. Java and Horizon used the same
  survival inputs, and Horizon ran with its built-in resources.
- [Dry vertical Andesite Funnels](tools/funnel_checks.py) match ordinary
  placement on a chest, Wrench toggling, manual insertion into the upward
  opening and extraction in both directions. The existing stack is filled
  before an empty slot, components survive, and an obstructing item keeps
  the next one from leaving the downward opening. Redstone pauses
  extraction and clears its cooldown.
- [Crouched Wrench pickup](tools/funnel_interaction_checks.py) removes the
  dry vertical Funnel and returns one block in Survival or zero in
  Creative. The Wrench is undamaged and no second item drops. The same
  Java fixture records intake before landing as an outstanding case.
- [Zinc ore](tools/zinc_checks.py) appears in nine new ordinary Overworld
  columns in each client. The mining checks match the stone and iron tool
  requirements and Silk Touch results. Fortune drops remain in the source
  range. Both furnace types yield an ingot from normal ore, deepslate ore
  and raw zinc. The samples come from Minecraft 1.21.1 and 26.3 terrain
  independently.

- [Crafter presentation](tools/crafter_visual_checks.py) compares loaded,
  merging and crafting frames in both actual clients. The regular 21-Crafter
  run still matches all 62 phase samples per block after the rendering changes.
- [Crafter-to-Belt output](tools/crafter_java_checks.py) matches 88 warm ticks
  while the Belt is stopped and 10 release ticks after a native restart.
  The exact Belt entry side, segment, position and previous position match.
- [Directional Crafter output](tools/crafter_outlet_checks.py) compares
  side Chest stacking, upward Barrel output, front ejection at a solid wall,
  and side insertion into segment 2 of a stopped then powered Belt. The
  matched entry records the original side and previous lateral offset.
- [Crafter Chute output](tools/crafter_chute_checks.py) compares blocked
  results and the release tick for open, stacked and powered Smart Chutes.
  The final stack and position agree in each lane.
- [Linked Crafter Hopper input](tools/crafter_hopper_checks.py) compares the
  eight-tick cooldown, slot priority, blocked slots and automatic crafting
  with Java. The native fixture reloads the group before completing the run.
- [Linked Crafter machine input](tools/crafter_machine_input_checks.py) compares
  Chute output, a collecting Funnel's held remainder and a differently facing
  Crafter's finished product. The test checks item components and retries when
  another slot becomes available.
- [Deployer schematic paste](tools/schematic_deployer_checks.py) matches all
  144 Java orientation and transform cases. Unsafe source data, occupied
  destinations and active destinations are refused before the first write.
- [Encased Cogwheel schematic paste](tools/schematic_encased_cog_checks.py)
  matches 576 placements using the same `.nbt` bytes. All 48 states keep their
  block entity type and expose the correct signed shaft ends after transforms.
- [Deployer transport](tools/deployer_transport_checks.py) matches all 85
  ticks in three lanes for ordinary and large Cogwheels and an incompatible
  input. A native restart preserves the in-flight hand and transport state.
  [Filter changes during a stroke](tools/deployer_filter_transport_checks.py)
  match all 16 samples, including both results and the marked hand remainder.
- [Stopped Deployer hand exchange](tools/deployer_hand_exchange_checks.py)
  compares nine cases across real cold restarts in Java and Horizon with the
  original JAR. The front click swaps a marked iron stack and damaged
  pickaxe, keeps the ghost filter and item data, and works in Adventure.
  The wrench switches modes without replacing the stored pickaxe. Front-view
  captures show the iron's glint in Use and the upright pickaxe in Attack.
- [Marked stationary Deployer stock](tools/deployer_stationary_components_checks.py)
  compares oak planting and stage-six wheat fertilizing with original Java.
  Both operations consume one marked, glinting item per use. Two cold
  Horizon restarts preserve the remaining stack with the original JAR loaded.
  The running check also replays a front click during expansion at 32 RPM
  with an oak filter, then verifies the planted sapling and marked remainder.
- [Deployer modes](tools/deployer_mode_checks.py) match 168 samples over two
  stationary lanes at 32 RPM. The Use hand switches a vanilla lever on ticks
  19 and 62. The Attack hand has the same stroke timer and leaves its lever
  alone. Five real clicks confirm front-hand mode switching, rear shaft
  rotation and retention of the stock and mode after restarting Horizon.
  The rendered goggles lines match Java text, colors, font widths and bounds.
- [Copper treatment](tools/deployer_copper_checks.py) matches 70 ticks across
  four lanes, including repeated oxidation removal, one refused input and
  unchanged tool components and damage.
- [Precision Mechanism](tools/sequenced_checks.py) compares 21 checkpoints in
  Java and Horizon, including all 14 saved intermediate components and a
  native restart after step seven. An independent Survival pickup and
  re-deposit advances from step one to step two with the same component.
  Independent random worlds are checked against the source pool.
- [Automatic Precision Assembly](tools/sequenced_belt_checks.py) matches all
  460 sampled ticks and item positions on a 17-segment Belt after a Horizon
  restart at tick 168. Each Deployer uses one tool and the Depot receives one
  result at tick 379. The comparison allows independent final rolls.
- [Lava Item Drain](tools/item_drain_checks.py) matches 65 samples across
  three lanes, including an incompatible 500 mB water tank and a real restart.
  [Hand interaction](tools/item_drain_hand_checks.py) matches Survival,
  Creative, full-tank refusal and marked cargo retrieval. The
  [Drain-to-Belt run](tools/item_drain_belt_checks.py) matches 38 warm and
  12 resumed ticks across a column boundary, including the entry pose.
- [Dry Belt riders](tools/belt_rider_checks.py) match Java player motion on
  horizontal Belts across a chunk boundary, including direction, steering,
  crouching, stopping and a collision with a wall. The `--cased` run adds
  Andesite and Brass segments, mixed controllers, and a transition from
  casing to a bare segment. Server positions match after stopping and at
  the wall.
- [Belt casings](tools/belt_casing_checks.py) and
  [dyes](tools/belt_dye_checks.py) were checked in Java and in native clients
  with fallback and imported resources, including persistence after restart.
- [Harvester flowers and saplings](tools/harvester_bush_checks.py) match 90
  block observations on a moving Mechanical Bearing. Dandelion, poppy, oak
  and birch saplings drop one item apiece. Young wheat stays planted.
- [Dry diagonal Chutes](tools/diagonal_chute_checks.py) match 92 samples
  across four directions, with ordinary side placement, two diagonal
  handoffs, item components and the detached shape after removal.
  The blocked middle Chute holds the same seven marked ingots after a
  full restart in each client. The [shape oracle](tools/chute_shape_oracle.py)
  checks all 40 outline and collision variants against original Java shapes.
- [Chute schematics](tools/schematic_chute_checks.py) match 144 authoritative
  state and empty block-entity observations using the same `.nbt` bytes
  in 12 rotations and mirrors. Disconnected and loaded templates are rejected
  before any destination block is changed.
- [Fluid Tank schematics](tools/schematic_tank_checks.py) match 48
  authoritative samples in 12 rotations and mirrors. Both window states stay
  intact and the first tick records the new position. Touching tanks and
  templates containing saved fluid are refused before any blocks are written.
- [Straight Pump lines](tools/fluid_pump_native_checks.py) match 115 ticks in
  each of six [Java cases](tools/fluid_pump_java_checks.py), including both
  fluids, both RPM signs and both placement orders. The fixture also checks
  backpressure, actual Wrench reversal, cold restart and motor removal. The
  original-resource run checks rendered connections and tank collars.
- [Inline Fluid Valve](tools/fluid_valve_native_checks.py) matches the
  [Java reference](tools/fluid_valve_java_checks.py) at 32 RPM. The pointer
  opens in ten ticks, the first transfer follows 18 ticks later, and an
  uninterrupted close moves 160 mB before stopping. Both clients retain a
  partially closed valve through a cold restart. The built-in pointer renders
  without a JAR, and the original model renders with a supplied JAR.
- [Fluid Valve Wrench rotation](tools/fluid_valve_wrench_checks.py) matches
  nine ordinary clicks on three faces of valves with all six initial facings.
  The open state and pointer position survive every rotation. The existing
  [piston hand actions](tools/piston_interaction_checks.py) also passed with
  the shared rotation code.
- The five Fluid Tank, Fluid Pipe, Mechanical Pump and Fluid Valve recipes
  match the pinned Java ingredients, patterns and results. All five crafted
  through the ordinary Horizon Survival crafting menu.

The [offscreen engineering run](tools/engineering_checks.py) used ordinary
crank clicks on all six facings and measured the rendered base and handle
against live shaft speed. It also passed gearbox/clutch/gearshift poses, the
goggles HUD, gauge comparators, water wheel behavior and 13 manual crafts.
The staged Horizon client library ran 1,300 tests: 1,164 passed, 135 were
ignored and the source-shape guard `hook_points_stay_hookable` failed on an
unchanged existing gauge hook. All five mounted inventory tests passed.
The full original-resource graphical smoke also passed placement, value
settings, engineering tools, fan processing, drill drops and the saved
machine regressions in one native run.

## 0.8.0-alpha.5 chassis, saw and Deployer crafting

The Linear, Secondary Linear and Radial Chassis retain their sticky faces
and saved ranges on a vertical Mechanical Bearing. Two matching Java layouts
cover adjacency, axis and radial reach. The native fixtures exercise
obstructed recovery, real process restarts, rotated states, placement by hand
and drops. Both resource modes ran the chassis fixtures.

An upward Saw processes oak logs and stripped oak logs on the same ticks as
the original in the 24-tick fixture. An unmatched Diamond passes through
unchanged. Ejection and cold restart midway through the cycle passed in
Horizon. The original-asset capture shows the input stack on the blade.

The survival fixture crafts Sand Paper, Red Sand Paper, Rose Quartz, an
Electron Tube, a Brass Hand and the Deployer in the ordinary crafting menu.
Real input checks the 32-tick polish, either hand, dropped quartz, early
release with components intact, final durability and an invalid item. The
original JAR fixture verifies the six item models and two sanding sounds.

Native block drops cover both Gearbox orientations, Encased Chain Drive,
the colored sail, Mechanical Saw and Deployer. The exporter now translates
legacy loot condition discriminators for Horizon's 26.3 evaluator.
Super Glue's restart fixture also checks a one-cell volume and verifies that
one click selects the first corner without duplicating the offhand action.

The separate grounded tree-farm fixture on alpha.4 generated a vanilla oak,
cut 14 trunk blocks and 233 leaves, then resumed after a cold restart and
replanted the original cell. The chest retained all 14 logs. A second run
used real bone meal to grow a planted sapling and repeated cutting and
replanting. The test uses a lower Saw arm attached with Super Glue.

All 242 Rust tests, 15 Python tests, strict Clippy and the pinned native
archive check passed.

## 0.8.0-alpha.4 farm actors and Super Glue

The Deployer matches the reference angle and planted cells over 40 ticks
from its held stack and over 50 more observations with a mounted chest.
The refill trace checks the first matching slot, preserving the held
sapling on invalid soil, and exact stock exhaustion. Two native cold
restarts cover stopping and resuming. A shared Saw and Deployer rotor
cuts three trunk blocks, stores them and plants seven new saplings.

The Plough matches both passes in the Java field, including protected
wheat, three cleared snow layers, three snowballs and one Hanging Roots.
Player clicks in both games cover piston slime, wrench refusal when
extended and the teardown of a static extension line.

The horizontal piston wall fixture matches both lateral endpoints.
The discrete resolver has 945 comparisons against the original JAR.
Grounded riders, dropped items and pole contact passed native regression.

Super Glue passed eight native scenarios covering selection, item damage,
removal, snapped transfer, failed capture of a split volume and orphan
recovery across a real restart. The original client supplied the selection
and wear reference. The build includes the tree farm, Plough and Glue
stations in the [review world](docs/reviews/0.8-contraption-world.md).

## 0.8.0-alpha.3 moving cargo and sails

The original Create 6.0.10 client and Horizon agree on slot order and rotated
landing for the single mounted chest. Horizon also preserved item components
through a real restart, recaptured the chest after landing, recovered it after
an obstructed controller removal, and collected Saw and Drill drops. Full
inventory overflow and loot from a neighboring column drop into the world.

The sail fixture matches the Java dye and shear interactions and the eight-sail
windmill's 1 RPM. The axial sail stays outside the assembly. Both native
resource modes passed assembly, process restart and restoration. A separate
offscreen review world checks the original sail meshes and the ordinary
closed chest on the moving structure.

The player interaction fixture covers Survival slime consumption, Creative
slime retention, wrenching the retracted piston, refusal while extended and
teardown through a real left click on a pole. It also detects a server crash
when an invalid wrench click reaches the Depot handler. The translated
full-block push covers unobstructed contact. The blocked push still differs
from the sideways displacement in the Java fixture.

Four Java cart-assembler scenes and 722 bitwise coupling comparisons cover
the new cart engine. Cart behavior is not connected to Horizon in this build.
The workspace passed 232 Rust tests, 14 Python tests, strict Clippy and official
native archive validation.

## 0.8.0-alpha.2 contraptions

The native build was checked against Create 6.0.10 on three Mechanical
Bearing axes, three Clockwork modes, regular and sticky piston rigs,
a Rope Pulley with dry cargo, and Gantry Carriage motion and redstone stops.
The comparisons include 120 pairs of hand angles, 176 piston samples,
48 pulley ticks with 80 block observations, and 273 Gantry assertions.

Separate Horizon runs cover saving a moving structure, removing its driver,
retrying an obstructed placement and restoring the payload once. Offscreen
checks cover items on moving surfaces, rotary and linear player transfer,
and clipping against a wall. Native actor fixtures exercise crop loot and
replanting, tree felling, drilling and resumed motion. A separate run matches
32 ticks of stationary horizontal Saw progress.

The review world includes native stations with original local resources. The
native bundle also works with the included models. Read the supported scope
and the in-game route before extending the fixtures.

[Contraption checks](docs/contraptions.md) · [Review route](docs/reviews/0.8-contraption-world.md)

## Belt motion and Depot pressing

Six identical connector-built lanes cover east and south orientation with
level, upward and downward belts. The real Java and Horizon captures cover
forward, stopped and reversed drive. RPM, item step and side offset agreed in
16 of 18 phases. In the south-facing horizontal lane, Java retained +32 RPM
through a cyclic source reference while Horizon stopped and reversed. Item
shadows and continuous texture phase remain open.

Ten successive captures on each of four driven lanes checked three middle
segments per frame. Java showed the stripes in all 120 observations. The
previous Horizon build showed them in 36. The updated build showed them in
all 120 and matched the median signed displacement in every lane. The old
atlas path cropped the 16×32 scrolling strips to 16×16. The importer now
keeps the full strips in the local resource cache. The
[native mesh fixture](tools/belt_render_game_checks.py) verifies all 34
atlas rectangles and the submitted UV coordinates against the original
renderer calculation.

Two native rebuild checks cover a level belt replaced with an upward belt and
a full replacement with identical block states. The new load stays on the
replacement and the old load drops once. The real press, belt, Depot, hopper
and chest route also passed, including its freeze regression.

The Depot now slides the held item before delivering it to the same press
callbacks used by belts. In the source comparison, the first ten Depot pose
records and all 101 Press lifecycle samples matched Java without aligning
the clocks. The two cycles began at ticks 9 and 28 and produced two sheets.
This fixture uses a single copper-ingot stack at the edge of the Depot.

The [loose-item Press fixture](tools/press_world_checks.py) compares the
smaller trigger box and larger strike box at 64 RPM. A grounded stone takes
priority over four marked copper ingots. Removing it permits one sheet and leaves
three marked ingots. An edge ingot stays idle until a centered stack starts
a stroke, then the strike converts the edge ingot and leaves the centered
stack intact. A split result has a ten-tick pickup delay and bounded random
motion on all three axes. Horizon sent one 15-particle burst for each of the
two successful strikes.

The [bulk Press fixture](tools/press_bulk_checks.py) loads the original
`bulkPressing` option. A World strike processes stacks of four copper ingots
and six iron ingots while leaving a stone. The Depot and Belt process seven
and nine copper ingots in one stroke. A live config reload switches an
already placed Press back to single-item operation. In that mode the stone
takes priority and the four marked copper ingots stay intact.

The [Press scan fixture](tools/press_scan_checks.py) matches 799 per-tick
RPM and Press state observations across Java and Horizon. A newly created
or loaded Press starts with a ten-tick countdown. In the independent
first-hit fixtures, a grounded item waits 72 unpowered ticks while the rig
uses a new Motor, an established Clutch or a real restart with the Clutch
disconnected. The first cycles begin at rows 83, 82 and 82. After a prior
stroke completes, the next stroke starts at tick 11 when an ingot arrives
between scans, and at tick 22 when it arrives while the Clutch is
disconnected. The countdown pauses while the drive is stopped. Repeated
starts are 33 ticks apart after a grounded strike and 42 after an empty
strike in the two startup rigs.

The Basin/Mixer retained its 83-tick first cycle and 62-tick repeat cycle.
Eight Mixer HUD scenes passed their text, style and layout comparisons.
The source sound-method oracle passed 2,776 cases. The latter measures
parameters and lifecycle rather than audio output.

The [Mixer particles fixture](tools/mixer_particle_checks.py) observed 63
consecutive emission ticks in each client. The dry lane emitted two item
particles per tick. The wet lane emitted one each of flour, water and honey.
The original JAR replay matched sprites, water and honey colors, and signed
launch geometry. The idle lane stayed quiet. Horizon paused emissions during
a mid-stir freeze, resumed on unfreeze, and saved one recipe output per lane.

[Review world and remaining limits](docs/reviews/belt-motion.md)

## Belt connector preview

The same right-click sequence in Create 6.0.10 and Horizon produced green dust
between compatible shafts and red dust when the second shaft had a different
axis. The incompatible click left both shafts intact. The compatible click
formed the five belt segments. Horizon's client trace verified that emission
starts after the first shaft is selected and ends after a valid connection.
Both clients were rendered and the captures were inspected.

The real native press/belt integration check passed all five groups without
the original JAR. The workspace passed 133 Rust tests, 14 Python tests and
strict Clippy. The [belt review route](docs/reviews/belt-preview.md) describes
the delivered scene and its boundaries.

## Chain gearshift and copper casing in 0.8.0-alpha.1

- `tools/adjustable_chain_checks.py` compared 36 settled cases in the pinned
  Java client and the native client, including all 16 signal strengths from
  each end of a mixed chain, changes while the motor is running and power
  removal. An actual Horizon restart retained `Signal`, block states and RPM.
- `tools/copper_casing_checks.py` compared seven real player interactions,
  including stripped bamboo, a stem and hyphae, Creative item retention and
  rejection of an unstripped log. Converted blocks and copper counts matched.
- Both blocks rendered in separate Horizon review worlds with and without
  the player-supplied JAR. A real lever click changed the left rig's output
  from 32 to 64 RPM. The screenshots cover model loading and the powered
  appearance. They do not measure animation or lighting parity.
- 132 Rust tests, 14 Python tests, strict workspace Clippy and official
  native archive validation passed.

Native build SHA-256
`d7fcf9df49c7729afca036e06dc8f5efe0b8c24636d886ef9493e040e9a64fa4`.
The `create-0.8.0-alpha.1.hnmod` archive SHA-256 is
`5c4d4eab4a0e4f3a32f5bfa4a04dd422feb7df518943a0ee0fcf800515e5d6f8`.
The reviewed mechanics and known differences are in the
[0.8 review world guide](docs/reviews/0.8-test-world.md).

## Optional resources in 0.7.0-alpha.2

A disposable Horizon world was opened three times with the same native build.
On the first launch without the JAR, a powered belt, both wheel sizes, a gauge
and the press rendered with built-in models. The press turned one Copper Ingot
into one Copper Sheet. Adding the supported JAR switched the models to the
original art. Removing it switched the models back even with the import cache
present. The sheet remained in the Depot across both restarts. The built-in
burner uses vanilla fire while the atlas may still log the optional original
flame sprites as missing.

Native build SHA-256
`dd4786638fd3a943256519b9c4e7818f8c6fdc88b2506e3c1b0dbc32c659a352`.
The matching `create-0.7.0-alpha.2.hnmod` passed the pinned Horizon archive and
registry release checks. Archive SHA-256
`13638c5571ef7ac32be5bb19ddac90959796d6c102122de09f6a81d39be74d97`.
All 131 Rust tests, 14 Python tests and portable strict Clippy passed.

## Launcher review for 0.6.0-alpha.2

Source bundle `d6a82f59e7622d9ad74e5cc200699776fa7e0e66`; Horizon
`9c7f9b2215dfed497aba5522c44f38926628648d`; official Mixins
`a1e13326306c6bc074b11e6a4926deb551c4083e`. The unmodified Launcher built
`native-9c7f9b2-b81e43cfc1d2` with the performance profile. Executable SHA256:
`c640101923ecabea1400982c22935008a78d138e771700965b9b3d418d4eb9a3`.

Installed **Create Factory 0.6**, world **CreateFactory06**. The GitHub
installation attempt hit the anonymous API limit. The validated local native
archive was compared byte for byte with all 143 corresponding files in the
public commit; no GitHub origin receipt was fabricated. The user instance's
official native-build confirmed Up to date. This is not a fresh successful
alpha.2 add-github installation. Previous instances and saves were preserved.

- Portable Rust: 124 tests; recipe exporter: 10 Python tests; workspace strict
  Clippy, formatting, package contracts and pinned official archive checks PASS.
- Shared compression predicate: 3015 pinned MIT source contexts PASS. Client
  PressingBehaviour oracle: 6034 contexts / 13 original methods PASS, scoped
  authored contexts and request traces, not full original gameplay.
- Complete woven Game: 6 prepared-resource tests PASS, including actual recipe
  IO/reload, press client receipt/RNG, press server lifecycle and previous
  item-contact/Mixer regressions. Stage restored byte for byte.
- Real item physics: 16 Java scenes / 128 native snapshots match, components,
  partial transfer and a real restart PASS.
- Press/Basin:four 180-tick original/native scenes have exact final outputs,
  controls and a true cold restart PASS. Strict absolute equality FAIL: native
  starts one tick earlier (impacts 31/93 vs 32/94; repeat interval 62). All 414
  differing fields remain unshifted. No artificial startup delay was added.
- New source world independently checked on a disposable dev-binary clone:
  15 groups, 6 survival crafts, 2 verified process restarts PASS; all 19 PNGs viewed.
  Source 31 save files and 14 schematic fixtures unchanged.
- Final performance binary independently opens another copy: 3 new rigs,
  ordinary pickup, native captures, audio-enabled device/events and a real
  process restart PASS. Three PNGs viewed. This does not relabel the full
  15-group dev audit as a performance audit or establish Java acoustic/pixel parity.
- Full injected production client strict Clippy still reports 6 previously
  recorded diagnostics outside the new modules; a whole-client green claim
  is intentionally absent.

The original world was copied unchanged to the user instance; level.dat SHA256
`b6dd3157e24c550459fff61f655c8d8dbbbd1b612f603f405ef9aa78c3f3f99a`.
Evidence: `.local/final-port-checks.json`,
`.local/press-basin-adapter-bquz33pp/result.json`,
`.local/press-basin-native-zquk3sv2/result.json`,
`.local/review06-audit-ao91u2a8/aggregate-result.json` and separate image review,
`.local/final-performance-check-ejbjii2j/result.json` and separate image review,
`.local/final-user-install-result.json`. Failed fixture attempts are retained.

The route and known differences are in [TESTING_06.md](https://github.com/Delete228/create-horizon/blob/eb8b96e8ea1db698b79bb61fd1caf6c963f31652/TESTING_06.md),
[REPORT_06.md](https://github.com/Delete228/create-horizon/blob/eb8b96e8ea1db698b79bb61fd1caf6c963f31652/REPORT_06.md) and [DEVELOPMENT_06.md](https://github.com/Delete228/create-horizon/blob/eb8b96e8ea1db698b79bb61fd1caf6c963f31652/DEVELOPMENT_06.md).
The entries below describe earlier binaries and are not silently transferred
to this checkpoint.


## Production machinery 0.5.0 (4 November 2026)

The pinned Horizon API 359 / Minecraft 26.3 and Create 6.0.10 are unchanged.
Official performance build: `native-fc02103-722bc455fcbe`.

- **56 Rust tests**: 41 for independent gameplay logic and 15 for assets.
  Formatting, Clippy with warnings denied, and source-package contracts passed.
- **157 204 Java comparisons** across eight oracles: the previous 75 145,
  millstone 24 409, fan 17 680, and stationary drill 39 970. The fan oracle also
  checks 566 956 timer transitions. Selected method bodies are extracted through
  the JDK AST; world/recipe contexts use explicitly bounded test adapters.
- The native millstone/fan run passed:
  `.local/smoke-omefnu7i/result.json`. It checked input filtering, components,
  hoppers, probabilistic outputs, full-output blocking, rotation transmission,
  four media, dropped items, obstructions, sign changes, and a real restart.
- Independent fan audit: `.local/smoke-audit05-comjxyyz/audit-result.json`
  and `.local/smoke-audit05-an8iwh2i/audit-result.json`. All six input faces,
  reversed media order, obstructions/slabs, fresh progress after reinsertion,
  exact 153/303 calls for 16/17 items, and hopper extraction/filling within one
  tick without carrying over the old timer.
- Dropped-item persistence was checked with a real restart:
  `.local/smoke-ri_t_bv9/result.json` and its transcript. The fields
  `NeoForgeData.CreateData.Processing.Type/Time` resume the remaining time,
  preserve unknown sibling keys, and complete processing exactly once.
- Independent native drill: `.local/drill-smoke-g4o3ujex/result.json`.
  All six directions, 4 SU/RPM, ordinary stone/diamond-ore loot without a tool
  and regardless of the player's creative mode, bedrock, `block_drops`, clutch
  pause, progress clearing on an unbreakable target, and a restart yielding
  exactly one obsidian. This checks the stationary drill.
- Asset import: 324 private files, including 288 original files and 36 derived
  wheel-material variants. All 61 locales are preserved byte for byte;
  root models/textures for the new machines were compared with the original JAR.
  `.local/content-05-import/validation.json`, cache schema 7.
- All three archives were accepted by Horizon's standard validator; they contain
  no original Create or Minecraft assets.
- **The complete final Metal/audio run passed without skips**:
  `.local/smoke-hd1a1k8a/result.json`, 2 729 control commands. It includes all
  previous scenarios, 24 actual crafts, the millstone, four airflow types,
  stationary drill, press reset of fan progress, and a real restart. It checked
  exact remaining timers/unknown sibling NBT fields on a dropped item, saved
  inventories, and completion exactly once. The second launch reused the verified
  cache of all 324 assets. Both launches opened the normal MacBook Air Speakers
  audio output; the log contains no errors or warnings.
  This checks audio events/startup, not perceived sound quality.

Additional review found a difference at the press/fan boundary:
`BeltPressingCallbacks.whenItemHeld` clears previous fan progress before creating
results and remainders. The adapter now performs the same reset while preserving
unrelated `HeldItem` keys. A new native scenario reproduces the bug on the earlier
`389d0c06ae5e` build and checks a fresh full timer after a real press impact.
It passed on `722bc455fcbe` for a single input and a stack remainder:
`.local/smoke-audit05-frwj19pm/audit-result.json`. In both cases the new timer
runs 151→141 over ten ticks; the transported item's unrelated field is preserved.

A separate audit of the prepared **CreateProcessing05** map also passed on the
exact `722bc455fcbe` build: `.local/review-map-clone3-i_0qdnkc/review-map-result.json`.
Eight check groups include all 39 catalog entries, press/render clearing,
instruments/comparator, reversal of both wheels, millstone with real hoppers,
four airflows with eight outputs each, drill with one new cobblestone,
five crafts through the actual menu, and empty-bucket return. Seven gameplay
screenshots were viewed. Checks ran on a copy: `final-integrity.json` confirms
that all 29 source-map files are unchanged. The user walkthrough is in
[TESTING_05.md](https://github.com/Delete228/create-horizon/blob/eb8b96e8ea1db698b79bb61fd1caf6c963f31652/TESTING_05.md).

The standard **Add from GitHub** installed the published source commit
`16c5d454b1b9860da01b78474ea5206f0664d384` into a new empty test instance.
`native-build --profile performance` confirmed **Up to date / 0 s** and the exact
`722bc455fcbe` build. All 69 source files matched the local package byte for
byte; manifest JSON fields are identical, with the official exporter removing
the final newline. SHA-256 of the local `.hnmod`:
`f49534cc3d558eb6baca9b1479e48a8c1d2a33031b098c5fa037fa1c4d4e0c49`.
SHA-256 of the GitHub archive installed by the Launcher:
`6e88ee5b86f21fd756b09e8d9511516896d5cb4e2051214fbb73577ac2aa53f5`.
[Source-commit CI](https://github.com/Delete228/create-horizon/actions/runs/41732420020)
passed, including all eight Java oracles.

The mod was also installed into the user's **Create Processing 0.5** using the
actual `mods add-github` command with a link to this exact commit; a genuine
origin receipt exists. The ordinary repository URL hit the anonymous GitHub API
limit in this attempt; the `/commit/…` URL worked. The installed package again
reported **Up to date / 0 s**, selecting `native-fc02103-722bc455fcbe`; the previous
global Nightly and old instances were preserved. After restarting the GUI, its
window confirmed **Create Processing 0.5**, one mod, one world, and the correct
native version. Evidence: `.local/05-github-fresh-install.log`,
`.local/05-github-fresh-build.log`, `.local/05-github-byte-audit.json`,
`.local/05-user-github-install.log`, `.local/05-installed-build.log`,
`.local/05-install.json`.

The official Launcher's normal windowed `play` opened **CreateProcessing05**
on the final build. It confirmed 36 carried entries, equipped goggles,
original models/Russian labels, the verified 324-asset cache, and the normal
audio device. The game was left paused. The gameplay screenshot was viewed;
evidence is in `.local/visible05-bpomhiqr/result.json`, `review.png`, and
`.local/05-visible.json`. Audit copies do not replace the original user world.

Comparison of the new machines' matrices actually submitted for rendering uses
Java angles at **the same fractional frame times**. Computing an ideal
instantaneous speed from two frames gives small deviations due to the source
`float`; this was checked on saved millstone matrices. The test uses the original
Java method, rather than weakening the direction check.

Evidence: `.local/05-{core,clippy,performance,package}.log`,
`.local/05-oracles.json`; gameplay transcripts are beside the referenced results.
These checks do not establish full Create support, networked multi-client play,
moving contraptions, or cross-version Java/Horizon world exchange.

## Instruments and water wheels 0.4.0 (4 November 2026)

The same pinned Horizon API 359 / Minecraft 26.3 and Create 6.0.10 apply. The new
performance build `native-fc02103-6533e4389288` was produced by the official Launcher.

- **39 Rust tests**, formatting, Clippy, and source-package contracts passed.
- **75 145 Java comparisons**: the previous four oracles plus 6 388 new cases
  covering phases, angles (including large times), crank acceleration/reversal/
  coast-down, the speed scale, and wheel RPM limits. Method bodies come from the
  pinned source through the JDK AST. These are isolated contexts, not a full NeoForge run.
- The instrument gameplay scenario `.local/smoke-7t9g60e4/result.json` passed with
  Metal and audio: three gauge axes, comparator output 4→15, actual equipping of
  goggles, HUD, actual matrices of three transmissions and the crank in all six
  orientations, eight brass sheets, wheel currents/reversal/power, wood changes
  without consumption, placement refusal without item loss, retry above a floor,
  breaking a structural part with one wheel returned and all parts cleared,
  eight new actual crafts, and save/restart.
- 258 imported files matched the original JAR byte for byte, including 61 languages,
  four OBJ and three MTL files. Another 36 material variants are created only in
  the private cache. Total: 294 files, schema 5. Public archives omit these assets.
- Three 0.4.0 archives were accepted by Horizon's standard validator. `.hnmod` SHA-256:
  `b7e8c6ba112d02d25c572dbee12f8796b1608a5e8d07dd178337b6cfb41b8021`.

Additional evidence: `.local/04-{core,clippy,oracles,performance,packages}.log`,
`.local/04-resource-audit.json`, `.local/visual-oracle/result.json`.
The complete Metal/audio regression also passed:
`.local/smoke-a6vb0yx3/result.json`, without skips. A separate **Create Engineering 0.4**
instance and **CreateEngineering04** world were prepared; the package was compared
byte for byte with the published source commit `2c9b9d8`.
This intermediate version is preserved; the owner chose to review 0.5 directly.


## Foundation 0.3.0 (3 November 2026)

Base environment: macOS arm64 / Apple M4, Rust 1.99.1, Horizon API 359 / Minecraft
26.3. Create 6.0.10, source `ac0c444d9828da3453ae8cc65338e8de063286fb`.
Exact dependencies are pinned in `compatibility.json`.

| Check | Result and scope |
| --- | --- |
| Rust | 34 tests: kinetic components/clutch halves, source-speed priority, gearbox, transmissions, overload, traversal bounds, press cycle, quantities/buffer, motor controls, asset import/recovery/isolation. Clippy without warnings. |
| Original Java | 75 capacity/stress scenarios, 27 648 placements, 31 752 connection/port equations, 9 282 press-result routing/speed/head-curve scenarios. Original method bodies were extracted through the JDK AST; Minecraft/world/recipe contexts use explicit adapters. Full NeoForge was not run. |
| Assets | All 217 `assets/create` files from the set of 218, including 61 languages, `sounds.json`, and 38 OGG files, matched the local JAR byte for byte. Cache schema 3. Neither these files nor the JAR are published. |
| Depot/client | Top exchange, replacement/merging, buffer, components, Shift/side click. Item selection is checked in the actual render callback: it is empty after extraction, beyond just the server slot. The wire snapshot explicitly clears `HeldItem`. |
| Transmissions | Real redstone switches the clutch and gearshift direction. All four gearbox ports and perpendicular large cogs transmit the expected speeds. |
| Interactions | Crank 32 RPM / Shift −32 / stop; Survival casings consume material, encasing does not consume the casing, wrench rotation/removal and return of depot contents. |
| Automation | A hopper does not merge an input into a busy depot's stack; top-slot/buffer extraction preserves quantities. A fallen item is picked up and returned with `custom_data`. Three dropped ingots were pressed without a depot. |
| Actual crafts | 11 recipes executed through the 3×3 crafting-table menu and server click-slot: alloy, shaft, two cogs, crank, gearbox, clutch, gearshift, press, depot, wrench. Result and final inventory were checked. |
| Motor | Actual native-screen clicks select +128 / −64 RPM, scrolling changes it to −63, and speed reaches the shaft. The value is checked after restart. |
| Packages | Three 0.3.0 archives were accepted by standard `cargo-horizon-mod check`. The native package includes all public content; no separate `.hmod` is needed. |

Latest complete intermediate Metal run: `.local/smoke-0u4woeb4/result.json`.
Hoppers and world pressing were also checked in `.local/smoke-8rr__rei/transcript.json`;
that headless run stopped at the crafting-table menu (`no renderer yet`). Headless
mode now explicitly skips menu checks; Metal executes them. Results are retained
and are not counted as a complete headless pass.

Performance build: `native-fc02103-7ea49a8f5494`, built by the unmodified official
Launcher 0.2.37. The final expanded Metal run passed without skips: `.local/smoke-ncu3notg/result.json`.
It checked extraction after the first impact (7 inputs + 1 sheet), no duplicate
result, eight sound events/impacts for eight inputs, return of all eight sheets
and cleared rendering, power loss/restoration, and a gold cycle across restart.
Standard audio opened MacBook Air Speakers; the log contains no errors.
This checks startup/events/assets, not perceived sound quality. Test worlds were
disposable; original user worlds were not used.

Local evidence: `.local/foundation-unit.log`, `.local/foundation-clippy.log`,
`.local/{network,placement,rotation,processing}-oracle/result.json`,
`.local/foundation-resource-audit.json`, `.local/foundation-packages.log`,
`.local/foundation-performance.log`. Installation commands and tests are in the
repository; local game assets and results are not in Git.

Source package `12d83a0233317484b697292af0c7623ced074ec9` was published;
[CI](https://github.com/Delete228/create-horizon/actions/runs/41701109989) passed
all stages, including four Java oracles. Native archive SHA-256:
`0dd5758a7db5e7955b295e881f8ebe51a24f01a947e4d7c809e546f0bd8b086d`.

`mods add-github` for 0.3 was blocked by the anonymous GitHub API limit in both
the normal and isolated launcher homes. Instead, every file in the verified local
`.hnmod` was compared with the source archive of this published commit. The package
was installed into a new **Create Foundation 0.3** without a fabricated GitHub
origin receipt. Automatic GitHub updates for this specific instance are therefore
not yet configured; ordinary `mods add-github` can be used once the limit clears.
This is not a successful end-to-end GitHub installation for 0.3; the standard path
was previously verified for 0.2 (history below).

The exact performance build was transferred from the official native-build cache.
A new `native-build --instance "Create Foundation 0.3" --profile performance` read
the installed package and confirmed **Up to date (no build needed)** / the same
version. The new **CreateFoundation03** world was prepared through standard `play`
and the control API: 26 items, redstone transmissions, gearbox, manually driven
press, casings, crafting table, and 8 finished sheets. Old worlds were neither
opened nor replaced. Local evidence: `.local/foundation-source-install-audit.json`,
`.local/foundation-installed-build.log`, `.local/foundation-review-world-result.json`.

Original gearbox, clutch, gearshift, wrench and depot models with a finished sheet
were viewed in gameplay screenshots of the new gallery. The final normal windowed
launch was confirmed through the API: world `CreateFoundation03`, then `paused`.
macOS was locked, so CUA could not check the Launcher window/instance list;
the normal window did not return a screenshot while locked. A separate offscreen
launch of **the same new world** was used for inspection, then the normal windowed
client was left paused. Evidence: `.local/foundation-visible-state.json`,
screenshots `.local/foundation-{gallery,transmissions,press-results}.png`.

Automated tests do not establish complete Create support. The owner's listening/
visual review remains separate; exact particles, random sound variations,
kinetic atmosphere, smoothing, and the original UI were not yet complete at this stage.

# Prototype and installation checks

## Iteration 0.2.0: placement and direct depot interaction

Native package: `b839dcb0c9b6674367b6f05eaf50dc75d7234854`.
Behavior/asset reference: Create **6.0.10**, source
`ac0c444d9828da3453ae8cc65338e8de063286fb`. The adjacent Java checkout was not
switched: tools read pinned files through Git.

| Check | Result and scope |
| --- | --- |
| Rust and CI | 24 tests (14 core, 10 importer), formatting, package contract, and Clippy passed. [Source-package CI](https://github.com/Delete228/create-horizon/actions/runs/41687537157) passed. [Next CI](https://github.com/Delete228/create-horizon/actions/runs/41688429604) also ran both Java oracles successfully on JDK 25. |
| Placement versus Java | 27 648 combinations for shaft, cogs, and motor matched the AST-extracted original methods. Context, neighboring ports, and Minecraft types use adapters. |
| Stress versus Java | 75 scenarios again matched unchanged `KineticNetwork.java` from the same release. This is not a complete graph/NeoForge check. |
| In-game placement | 12 scenarios: X/Y/Z axes, adjacent shaft, Shift, inherited cog axis, motor, and horizontal press. |
| Direct depot | A top click places the whole stack without a GUI, an empty hand collects it, another item replaces it; identical items merge after return. Quantity is conserved. Side face, Shift, and return of eight output slots were checked. |
| Components and persistence | The candle's `custom_data` survived placement/return and save, restart, and extraction again. |
| Client result | A cancellable HEAD on `remote_block_reacts` returns Success for a top depot click. Without it the client sent an offhand action and immediately took back the deposited item. Inventory exchange remains on the named server hook. |
| Original assets | All 110 imported files, including 61 languages, were compared with the JAR byte for byte. Cache schema 2 refreshes the previous set. Original files were not added to Git or port archives. |
| Complete gameplay runs | Headless without the JAR and Metal with the JAR passed: placement/depot, iron, power loss, copper after restoration, and a gold cycle across restart. Metal uses final performance build `native-fc02103-0554886ea08b`. Screenshots were viewed: original depot, candle, and copper sheet are visible in the world. |
| Standard pipeline | Unmodified Launcher 0.2.37 downloaded the package by GitHub commit and built the installed `.hnmod`. Its SHA-256: `0f648187005c30879b40340b08b3401e63cc3356882923f65e8a41823a81ef80`. All 0.2.0 archives were accepted by the standard validator. |
| User gallery | New **Create Review 0.2** instance, **CreateReview02** world: the factory produced 8 iron sheets; orientations, depots, and items were prepared. Standard performance `native-build` confirmed Up to date. A normal windowed launch through the same Launcher opened the world with original graphics and Russian names; the game was left paused. |

While preparing the user instance, the anonymous GitHub API hit its rate limit:
the exact package downloaded through the standard pipeline, its genuine origin,
and the verified build cache were reused. Previous instances/worlds were not
opened or replaced. macOS was locked during the final CUA check of the Launcher
window; its refreshed instance list was not visually confirmed. Selection and
version were confirmed by the standard CLI, and the open new world by the
control API and a gameplay screenshot.

The fixture sends rotation/Shift early and waits for server delivery before
clicking, then waits for synchronization after the click. The Java oracle checks
the algorithm; the gameplay run checks the adapter. The headless run preceded
the depot collision-height correction to the original 13/16;
the final Metal run includes that correction.

Local results, not published in Git: `.local/placement-oracle/result.json`,
`.local/network-oracle/result.json`, `.local/locale-check-result.json`,
`.local/smoke-mhi4i1uo/result.json` (headless), `.local/smoke-yvme8bge/result.json`
(Metal), `.local/review02-world-result.json`, `.local/review02-visible-state.json`.

Persistence was checked within Horizon. Cross-version Java-world transfer is
outside the requirement; the full Create system had not yet been ported.
Exceptions are listed in [COMPATIBILITY.md](docs/compatibility.md). Animations, water,
sound, multiplayer, and the remaining machinery required later iterations.

## First-stage results (0.1.0)

Date: 3 November 2026. macOS arm64, Apple M4, Rust 1.99.1.
Exact commits and versions are listed in [compatibility.json](compatibility.json).

| Check | Result and scope |
| --- | --- |
| `horizon-port-pack` | Ran `import`, `inventory --offline`, `carry`, `report`, `check`. 8913 files; Create coverage marked `partial`. This is data import; Java code is not executed. |
| Rust core | 12 unit tests passed: connections, speeds, conflicting sources, overload, disconnection, press cycle, and head motion curve. |
| Asset importer | 9 unit tests passed: public-content preparation, recovery and isolation, model dependencies and PNG metadata, repeated import and cache recovery, no JAR, multiple JARs, wrong SHA-256, path traversal, model cycles, missing assets, Java loaders, size limit, and input-file symlink. All fixtures are synthetic. |
| Clippy | `--workspace --all-targets -- -D warnings` passed for the core and importer. |
| Java comparison | 75 power/stress scenarios matched unchanged `KineticNetwork.java`. Block/world use minimal adapters; this is not a full NeoForge test. |
| Native integration | Horizon with eight named hooks and three pinned mixins for content/resource loading passed `cargo check` and built into an executable client. |
| Archives | Official `cargo-horizon-mod check` accepted the content `.hmod`, native `.hnmod`, and combined `.hmod`. The package now pins the published corrected Mixins commit; no local patch is needed. |
| Headless game | Motor → shaft → two cogs → press → depot produced 8 iron sheets. |
| Power loss | With the shaft removed, 4 copper ingots remained unprocessed; restoring the shaft yielded 4 sheets. |
| World persistence | The game closed during a cycle with 3 gold ingots; restarting the same test world yielded 3 gold sheets. |
| Graphics and screen | The same scenario passed with Metal in `--offscreen`; the depot interface opened. Screenshots were viewed: provisional models and the slotted item are visible. Mouse item dragging was not separately checked. |
| Automatic in-game import | A new isolated Metal scenario ran with normal public content and the JAR in `horizon-mods/create-resources/`. The game imported and enabled 49 files itself; each was also compared with the original JAR byte for byte. Models and the copper-sheet texture were checked in screenshots. Iron, copper, power loss, and the gold cycle across save passed again. The second launch used the verified cache. |
| Resource reload | F3+T passed with the original JAR, after its removal, and after its return. Logs/screenshots confirm switching to provisional models and back. The original JAR was unchanged. |
| Public archives | After adding the importer, all three archives passed the official validator again. They contain no PNG, OGG, JAR, or Java classes; original assets are not packaged. |
| Official Launcher | A separate Create Prototype was created, the verified client imported, and the public content archive installed. New world CreateDemo launched through `horizon-launcher play`; Create content loaded, Metal worked, and the player's selected item was `create:creative_motor`. |
| Importer in the installed instance | Create Prototype updated to `imported-2026-11-03-78bafb5`. Official `play --instance create-prototype` opened the title screen offscreen: 49 assets imported from the JAR beside the mod, and Metal rendered its first frame. State `screen: title`, `world: null`; CreateDemo was not opened. The normal selected Nightly was preserved. |

## Standard GitHub installation (3 November 2026)

Source package at commit `73a9ccba62f619c4a7d0288a7d42c1146a3a8f52` was checked.
[CI for this commit](https://github.com/Delete228/create-horizon/actions/runs/41677935703)
passed: formatting, 21 Rust tests, source-installation contract, and Clippy.

- Unmodified installed Horizon Launcher **0.2.37** built the client with standard
  `native-build`, profile `dev`, and the full client feature set.
  The Launcher itself installed Mixins through `cargo install --git` at commit
  `a1e13326306c6bc074b11e6a4926deb551c4083e`. Tool source was not edited.
- `mods add-github` installed the exact published commit into a new isolated
  instance. Both revisions, all public content, and the absence of original
  PNG/OGG/JAR/classes were checked in the installed `.hnmod`.
- That installed package was then built, without specifying the working checkout
  directory. The result was `native-fc02103-0ac3c457cc78`. Repeating the command
  reported **Up to date (no build needed)** and used the same build.
- Both complete gameplay scenarios used this client **without `--dev-mod` and
  without a separate content archive**. Without the JAR, iron/copper pressing,
  power loss, restoration, and the gold cycle across restart passed.
- The Metal/JAR scenario also passed all operations, opened the depot, and reused
  the verified cache. The interface screenshot was viewed: the original copper
  sheet is visible in its slot. Before checking the menu, the fixture clears the
  hand and waits for the server-thread response, avoiding dependence on picking
  up items dropped during setup.

- Separate title-screen launches checked an invalid JAR, `mod.create` disabled
  after earlier enablement, and the original JAR. An invalid JAR produces a
  diagnosable fallback; a disabled mod enables neither content nor the importer.
- The standard **performance** profile was also built:
  `native-fc02103-1ba8788c96b6`. It was installed into new **Create Native** and
  launched with the ordinary Launcher `play` command. New **CreateInstallCheck**
  produced 8 iron sheets; the world, rig, and nine items were saved for visual review.
- The Launcher window was refreshed after CLI installation. Its UI confirmed the
  selected Native build and GitHub mod `create` with **Up to date** status.
  Later user-instance preparation reused the genuine package, GitHub receipt,
  and verified build cache because of the anonymous API limit; this was not an
  import of a separately hand-built game executable.

Isolation: new launcher/game/XDG homes and disposable worlds; assets, verified
compiler, and Cargo cache were cloned locally on APFS. This is a clean mod install
and a standard-build-path check with warm caches, not a measurement of first-time
dependency downloads on an empty computer. Gameplay tests disable audio through
the environment; the standard build retains audio/controllers features.

This iteration does not claim accuracy of every model/mechanic, multiplayer, or
the remaining Create blocks. The verified chain remains the bounded prototype
from the plan.

Local evidence, excluded from Git:

- `.local/native-startup-hqgsf5ag/result.json` — invalid JAR, disabling, and enabling.
- `.local/user-native-world-result.json` — performance, Launcher launch, and saved rig.
- `.local/user-native-build.log` — repeated standard build using the ready cache.

- `.local/official-launcher-check.log` — first official Launcher build.
- `.local/github-install-result.json` — installation response for the published commit.
- `.local/native-cache-check.log` — reuse of the completed build.
- `.local/smoke-346h0dtw/result.json` — complete cycle without the original JAR.
- `.local/smoke-menojh3s/result.json` — complete cycle with the original JAR and Metal.
- `.local/smoke-menojh3s/depot.png` — open interface and original copper sheet.

Local evidence, excluded from Git:

- [Import report](.local/port-work/coverage.md).
- [Headless result](.local/smoke-3507mg3u/result.json).
- [Graphics result](.local/smoke-8ekcjs2r/result.json).
- [Machinery](.local/smoke-8ekcjs2r/factory.png) and [depot screen](.local/smoke-8ekcjs2r/depot.png).
- [Automatic import and working machinery](.local/smoke-5_mrnj1k/result.json).
- [Resource switching through F3+T](.local/smoke-5_mrnj1k/asset-cycle-result.json).
- [Original models](.local/smoke-5_mrnj1k/reload-restored.png) and [provisional models after JAR removal](.local/smoke-5_mrnj1k/reload-without-jar.png).

Games ran in separate working directories/homes with copied assets. Each scenario
created its own world in its working directory. Existing user worlds were not
used. Source repositories `../Create` and `../horizon` remained unchanged.

At this point, the next stage still needed two-client checks, large networks and
chunk unloading, full depot/hopper interactions, and further Java animation/render
comparisons. Remaining Create machinery had not yet been ported. A working chain
does not establish that the entire mod is ready or fully compatible with Java.
