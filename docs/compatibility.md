# Original Create identifiers and data

Version 0.9.0 pins unmodified upstream Horizon, includes independent built-in
artwork, and retains local import of the original Create resources.
[Horizon and Nightly checks](official-horizon.md)

The 0.8.0-alpha.16 development checkpoint matches the original Deployer's
final visit before the bearing stops. Vertical Mechanical Bearings can land
in dry vanilla leaves, and blocked landings can still be retried after a
restart. Two moving Deployers can share one mounted chest and preserve their
stock, filters and visit state across restarts. Capture and restoration
currently share one chunk column.
[Contraption guide](contraptions.md)

The sections marked 0.3–0.5 below retain the released historical boundaries.
The installed review checkpoint is **0.6.0-alpha.2**: see [REPORT_06.md](https://github.com/Delete228/create-horizon/blob/eb8b96e8ea1db698b79bb61fd1caf6c963f31652/REPORT_06.md)
and [DEVELOPMENT_06.md](https://github.com/Delete228/create-horizon/blob/eb8b96e8ea1db698b79bb61fd1caf6c963f31652/DEVELOPMENT_06.md) for scoped integration evidence and
remaining differences. It adds limited schematic placement, bare-belt transport,
Basin/Mixer/fluid/heat processing and Press compacting, not complete Create parity.

For the new Press adapter, `Mode` retains WORLD=0, BELT=1 and BASIN=2.
The `[recipes]` option `bulkPressing` in `config/create-server.toml` defaults
to `false`. Set it to `true` to press the full stack on a Depot or Belt, and
all recipe-matching grounded stacks in range in World mode. A config reload
changes the setting for Presses already in the world.
`ParticleItems` is consumed once by client-update construction and is not saved;
empty later updates clear the client's retained field. The active recipe object
is transient and retained through datapack reload, not encoded as a new recipe
field in the save. Canonical input/output inventories retain unknown sibling
data; unsupported predicates/structures fail explicitly. The measured one-tick
kinetic startup difference is historical; the bounded 0.7 source-event/ticker-order
comparison supersedes it without adding a timer offset.

Version 0.7 adds `create:encased_chain_drive`
with entity type `create:encased_shaft` and the original 24 combinations of `axis`,
`axis_along_first` and `part`. The isolated original default is axis Y,
`axis_along_first=true`, `part=none`. Two source crafting recipes and the complete
source loot data are preserved. Ordinary interactions, six settled chain scenes
and real native restarts were checked in the alpha.1 build. Full propagation and
presentation parity remain open. [0.7 report](reviews/0.7-report.md)

The target's per-stack `minecraft:damage_resistant` canonical
`{types:"#minecraft:is_fire"}` maps to original 1.21.1 `FIRE_RESISTANT` presence.
Explicit removal overrides the default component. Recognized partial selectors
do not grant full-fire resistance; unknown/malformed selectors are conservatively
retained when no recipe applies. This is not a general component data fixer.
Actual recipes retain priority. The 0.5 default-only description below is historical.

The 0.7 generator adapter distinguishes source initialization, actual GUI/crank/
wrench/flow callbacks and raw NBT reads. An initialized motor's `/data` edit is
not an ordinary live settings action in original Create. Bounded Press/Basin
traces match 1,488 ordinary tick samples without time alignment; authentic
cold-loaded Java networks, source ownership and flicker/breakage remain pending.

The behavior reference is Create **6.0.10**, Minecraft **1.21.1**, source commit
`ac0c444d9828da3453ae8cc65338e8de063286fb`. The target is Horizon's Minecraft
**26.3** implementation. Cross-version Java world interchange is outside the
current requirement. Preserve upstream identifiers and data conventions when
implementing each feature, and test save/reload inside Horizon.

| Block / item ID | Block entity type ID | Implemented state / data |
| --- | --- | --- |
| `create:shaft` | `create:simple_kinetic` | `axis`, `waterlogged` (default false) |
| `create:cogwheel` | `create:simple_kinetic` | `axis`, `waterlogged` (default false) |
| `create:large_cogwheel` | `create:simple_kinetic` | `axis`, `waterlogged` (default false) |
| `create:flywheel` | `create:flywheel` | `axis` (default Y) and common kinetic data. Wheel speed and angle are client-side and are not saved. |
| `create:creative_motor` | `create:motor` | `facing`; `ScrollValue` int, default 16 |
| `create:mechanical_press` | `create:mechanical_press` | horizontal `facing`; `Running`, `Finished` bytes; `Ticks`, `Mode` ints (WORLD=0, BELT=1, BASIN=2) |
| `create:depot` | `create:depot` | `waterlogged` (default false), no facing/open state; `HeldItem`, `OutputBuffer` |
| `create:gearbox` | `create:gearbox` | `axis` |
| `create:clutch`, `create:gearshift` | corresponding block ID | `axis`, `powered` |
| `create:hand_crank` | `create:hand_crank` | `facing`, `waterlogged`; `InUse` int, `Backwards` byte |
| `create:andesite_encased_shaft`, `create:brass_encased_shaft` | `create:encased_shaft` | `axis` |
| `create:andesite_encased_cogwheel`, `create:brass_encased_cogwheel` | `create:encased_cogwheel` | `axis`, `top_shaft`, `bottom_shaft` |
| `create:andesite_encased_large_cogwheel`, `create:brass_encased_large_cogwheel` | `create:encased_large_cogwheel` | Same state and common kinetic data |
| `create:encased_chain_drive` | `create:encased_shaft` | `axis`, `axis_along_first`, `part` (`none`, `start`, `middle`, `end`) |
| `create:adjustable_chain_gearshift` | `create:adjustable_chain_gearshift` | Same chain properties and `powered`. Integer `Signal` stores the analog redstone strength. |
| `create:millstone` | `create:millstone` | no block-state properties; `Timer` int, `InputInventory`, `OutputInventory` |
| `create:smart_chute` | `create:smart_chute` | `powered`, `Filter`, `FilterAmount`, `UpTo`, and the normal Chute cargo and position fields |
| `create:crushing_wheel` | `create:crushing_wheel` | `axis`, axial shaft at each end, 8 SU/RPM |
| `create:crushing_wheel_controller` | `create:crushing_wheel_controller` | Internal `facing` and `valid` states, `Speed` float and 32-slot `Inventory` with the original processing fields |
| `create:brass_funnel` | `create:funnel` | Dry vertical placement; `extracting`, `powered`, `waterlogged`, plain `Filter`, `FilterAmount`, `UpTo` and `TransferCooldown` |
| `create:item_drain` | `create:item_drain` | 1500 mB `Tanks`, transported `HeldItem` and `ProcessingTicks` |
| `create:basin` | `create:basin` | `facing`, `InputItems`, `OutputItems`, `InputTanks`, `OutputTanks`, `Overflow`, `FluidOverflow`, `PreferredSpoutput` and `DisabledSpoutput` |
| `create:mechanical_crafter` | `create:mechanical_crafter` | Horizontal `facing`, `pointing`, `Inventory`, `ConnectedInput`, `GroupedItems.Grid`, `Phase` and `CountDown`; 2 SU/RPM |
| `create:encased_fan` | `create:encased_fan` | six-way `facing`, default `north`; common kinetic `Speed` |
| `create:mechanical_drill` | `create:drill` | six-way `facing`, `waterlogged`; defaults `north`, false; `Progress`, `NextTick`, `Breaking` |

A Basin's side spout feeds items, water, lava, honey and chocolate into a Basin
one block lower and one block to the side. A clear space between the two openings lets the source choose
the route automatically. Wrench the active side away from the filter to
disable it, or Wrench another side to prefer it. A full receiver keeps the
finished stacks in the source across saves. When space opens, the source
transfers the items that fit and keeps the remainder. It waits for room for
each complete fluid batch. Opening a side route moves existing output fluid
into the queue, and a return to the downward position clears the fluid queue.
Other receivers and the spout's output effects remain open.

A heated Mixer melts a Honey Block into 1,000 mB of honey or a Bar of
Chocolate into 250 mB of chocolate. A Press compacts those amounts back
into the corresponding item. The stock `c:honey` ingredient matches
`create:honey`. Custom fluid tag overrides and milk mixing remain open.
Use a Honey Bottle on the Basin below its filter slot to pour 250 mB.
Survival returns a Glass Bottle. An empty Glass Bottle cannot draw honey
back out of the Basin.
An ordinary Water Bottle also pours 250 mB. Use a Glass Bottle to draw
that amount of water and receive a Water Bottle in Survival. Creative
keeps the held bottle while changing the stored volume.

Static casings/storage blocks and alloy/metal/wrench items retain their upstream
`create:*` IDs. Encased shafts unwrap to and drop `create:shaft`.

Apply either casing to a dry cogwheel without consuming the casing. A matching
shaft neighbor opens its end at the time of encasing. Use a Wrench on an axial
face to toggle that end, or on a tooth face to rotate the axis. Sneak-use the
Wrench to restore the original cogwheel. The original casing models and moving
parts load from the optional JAR. Neighbor-connected textures, face-sensitive
pick-block and moving Encased Cogwheels remain pending. Horizontal schematic
transforms keep each shaft on the correct signed end of the axis.

The building-blocks tab includes the cut, polished cut, cut bricks and small
bricks variants of andesite, granite and diorite, plus layered andesite. Each
has its original stonecutting recipe and can be cut back into the corresponding
vanilla stone. The local Create JAR supplies their base models and textures.
Layered andesite uses its ordinary cube model while connected textures are
pending. The tab uses cut andesite as its icon until the ornate iron window is
available.

Zinc and Deepslate Zinc Ore use the original `create:zinc_ore` feature
with eight attempts, vein size 12 and height anchors −63 and 70. The pinned
Java config defaults to enabled generation. Horizon enables the feature with
the port and uses 26.3 world generation in new chunks. The original mining
tool tier, Silk Touch, Fortune and cooking recipes are retained. Raw Zinc
can be packed into its original storage block.

The downward Crushing Wheel pair takes supported inputs from a dry Chute
or catches falling stacks. It looks up Crushing recipes before Milling
recipes. The bundled crushing recipes include supported raw metals and
their storage blocks, ores, Obsidian, Wool, Tuff and the standalone Diorite
recipe from the stock Java installation without Ex Nihilo. The wheels eject
into open space or transfer onto a Depot, where the top stack and output buffer
control backpressure. An item without a recipe runs the original 100-duration
cycle and yields no items whether it falls into the wheels or arrives through
a Chute. Inputs with an unported recipe such as Netherrack remain upstream.
The controller retains its original inventory
and cycle fields through a restart, and loose outputs retain the original bypass
data. The Experience Nugget currently drops as an item. Consuming it,
entity-specific collision and damage, and other directions and output
destinations are pending.

A vertical Smart Chute can use an ordinary item as a ghost filter. The
default configuration pulls up to 64 matching items at once. A powered
Chute parks its cargo halfway along the block and resumes after the signal
clears. The filter and cargo survive a restart. Hold use over the filter when
the Chute feeds an inventory to choose Up to or Exactly. The board uses the
sample item's stack limit. Smart Chutes and Brass Funnels load a legacy zero
as Up to the saved sample's stack limit. Replacing the sample keeps that
amount. An ordinary Hopper can feed a dry Smart Chute from above or the side.
The chute refuses mismatches, powered transfers and additional cargo while
occupied. Special filters and airflow remain open.

Ordinary dry Chutes connect diagonally in four directions. A complete empty
line can be pasted from a source schematic with a horizontal rotation or
mirror. Loaded Chutes, airflow and partial diagonal routes need their own
import policy. Stationary vertical Chutes also carry ordinary inventory
cargo while waterlogged, including from an upper Barrel or side Hopper.
A Hopper can also feed an empty ordinary angled Chute in air or water.
Placing a Chute into a water source preserves the source in the block state.

An upward-facing Encased Fan below a straight run of ordinary dry Chutes
passes its signed speed through the column. A side Hopper can feed cargo for
upward transport into a barrel. A full receiver holds the stack halfway,
including across a restart. Changing the Fan's direction reverses the item
motion. A downward-facing Fan above a straight run pulls loose items or
extracts from an ordinary container below. The collision shape under the
Chute determines how far it can reach. Cargo parks halfway below the Fan and
falls back when power stops. A single bottom Fan can also feed one straight
and one angled branch in a dry ordinary run. The two branches each inherit
half the push and the straight branch wins a tie. An occupied straight branch
can send the stack through the angled branch across a loaded chunk boundary.
These straight runs and the single lower-Fan fork also work through waterlogged
ordinary Chutes. Both branches of the fork preserve their cargo and delivery
timing across a cold restart. The original collision geometry still limits
upper suction.
The same upper Fan can extract a stack from a stopped horizontal Belt under
an ordinary Chute. The stack must be less than half a block from the segment
center, within the collision-limited reach. A dry ordinary Chute can also
draw the full held stack from a Depot directly below it or across one air
block, leaving the Depot output buffer intact. A solid block stops the
transfer. A bare dry Fan leaves the Depot stack in place. Sloped Belts,
paired Fans, larger airflow networks, and powered Smart Chutes remain open.

Powered Chutes use their own airflow billboards in the window and the clear
space they blow into or draw from. These particles use Minecraft's generic
sprites in both resource modes. The current Horizon particle controller omits
these billboards on Minimal. Java still shows occasional ones at that setting.
Vertical Chutes render cargo in their windows and below an opaque Chute with
suction. The item remains visible when the Chute itself is outside the frame.
The client interpolates its pose between authoritative item offsets and holds
its final pose when the cargo parks.

Horizontal Mechanical Belts can feed dry Chutes and receive their downward
output, even when the receiving Belt is stopped. An incomplete Belt or a
Chute that rejects the item holds the cargo upstream.
The same item and components continue after a restart. Andesite and Brass
Casing use the original per-segment states, and dye or washing changes the
color of the full Belt. Dry horizontal Belts carry grounded local players
across bare segments and segments with Andesite or Brass Casing. Sloped
Belts and other passenger types remain open.

The original JAR supplies the full scrolling strips for plain and dyed Belts.
The private import keeps both halves available to the renderer. Without a JAR,
the simplified Belt surface uses static vanilla textures.

Mechanical Crafters support manual front-slot loading and the original
5×5 Crushing Wheel recipe in a same-facing array inside one chunk column.
The finished stack drops at the front of the last Crafter or enters a Depot.
The phase, countdown and component-bearing grouped items can resume after
a restart. The 21-Crafter test matches all 62 Java ticks. A full 5×5 grid
can use a redstone pulse or four Crafter Slot Covers for its empty corners.
The finished stack can feed into a Chest, Trapped Chest, Barrel or Hopper
above, below or beside the Crafter. The transfer fills matching stacks before
empty slots. The Crafter also feeds a horizontal Belt from above or from the
side. A stopped Belt retains the result in the Crafter. A solid target
without a receiving inventory causes the result to drop at the Crafter's
front.
A dry Chute or Smart Chute can also receive the finished stack. The Crafter
keeps the result while the Chute is occupied or the Smart Chute is locked.
It retries an open Chute every tick and a stacked Chute on its ordinary
lazy tick.
Ordinary shaped and shapeless recipes use the loaded crafting table's recipe
order, within a 3×3 occupied area. Mirrored patterns and empty cells follow
the normal crafting rules. A recipe marked `_manual_only` stays manual.
Equal item remainders occupy separate output
cells and wait for space, as with the three buckets from a cake.
Use a Wrench on the shared edge of two same-facing Crafters from an accessible
side or back to link or separate their inputs. Feeding any linked member by
hand fills available slots from the top row down, ordered by facing within
each row. Covered and busy slots are skipped, and empty-hand pickup stays
local. The group keeps Create's controller and relative offsets across saves.
Player removal repairs the surviving loaded members. Removal by commands
and disconnected groups with unloaded members remain pending.
A vanilla Hopper pointed at a linked member feeds the same slot order and
skips covered, occupied and busy slots. It keeps its eight-tick transfer
cooldown. A Hopper underneath cannot extract these ingredients.
A Chute above a linked member and an upward collecting Funnel also feed the
group. A finished Crafter can feed a differently facing linked group. Each
available member receives one item and the source keeps any remainder.
The animation shows ingredients merging and the finished item turning, with
the export and crafting particles. With the original JAR, the small belt uses
Create's four-frame export animation. Two crafters pointing at each other show
arrows. Further automation, edge outlines, connected textures, special recipes
and mixed remainders remain open.

Right-click the front of a stopped Deployer to swap your entire held stack
with its hand, including item components and tool damage. An empty hand
takes the stored stack. The ghost filter stays in place and can differ from
the stored item. This also works in Adventure mode. A front Wrench click
switches Use or Attack while keeping the stored stack.

A stationary downward Deployer uses supported saplings and bone meal with
item data such as custom markers and enchantment glint. It consumes one when
the vanilla action accepts it and preserves the remaining stack, including
through a restart. Its front hand accepts this stock while turning when it
passes the ghost filter. Item-driven block state overrides still need support.

A downward Deployer can apply the original small and large cogwheel recipes
to cargo on a Depot or bare horizontal Belt. It also has the original
vanilla copper wax, unwax and deoxidation recipes. Those recipes keep the
Honeycomb Block or Axe in the hand, including the Axe's current damage.
Changing a filter during a stroke lets that stroke finish. While waiting,
the mod parks a mismatched hand until the player changes it. Java moves
it to an overflow inventory.

The Precision Mechanism recipe takes five rounds of three tools. A Depot
keeps the original `create:sequenced_assembly` component through an actual
restart, and Survival hand transfer retains it. A horizontal Belt can run
all 15 operations in a line of Deployers across a chunk boundary. The final
roll uses the original 150-weight pool. Client-side progress UI, creative inventory
round-trips and general sequenced recipe types remain open.


A dry vertical Brass Funnel can filter with a plain item sample. Downward
extraction uses the original eight-tick cooldown, a default limit of 64, and
the stored Exactly or Up to setting. Tap use over the filter to change its
sample. Hold use to open the amount board, then release to confirm the
selection. The same controls use a simpler panel without the optional
Create JAR. An upward collector accepts direct output from a downward
Crushing Wheel Controller or an adjacent upward Saw into an ordinary inventory.
The source retains cargo while the funnel is powered or its filter rejects
it. Airborne intake, special filter items and Belt Funnel variants remain
open.

An Item Drain accepts water and lava buckets, Honey Bottles and ordinary
Water Bottles from a bare horizontal Belt. It stores 1,000 mB from a bucket
or 250 mB from a bottle and sends the empty container to a neighboring Depot
or Belt.
With an incompatible or full tank, it waits at the pour position. With a
blocked Depot or stopped outgoing Belt, it holds the container at the exit.
The checked flows match the pinned Java tick traces and survive a restart.
Right-click with a supported full container to pour directly into the tank.
Survival returns an empty container. Creative and a refused pour both keep
the full container and its components. An empty hand retrieves an item waiting
on the Drain. A comparator reads the tank's fill level, including through one
solid conductor. Java and Horizon match the two-tick delay after the checked
conveyor or hand pour. A pipe can extract from the bottom or any side.
It cannot fill the Drain, and the top does not expose fluid storage.
Other item containers are pending. The original JAR supplies the body model.
The container highlights and their overlap with the stream still differ.

With the reference Create defaults, ordinary Fluid Tanks form complete
square layers one to three blocks wide and up to 32 layers tall. Each block
contributes 8,000 mB. The controller at
minimum X, Y and Z owns the fluid. All parts expose that storage on every
side, including parts across a loaded chunk boundary. In Creative, a full
or empty bucket moves 1,000 mB and stays in the player's hand. Survival
uses vanilla bucket interactions. A Wrench toggles the entire structure's
windows. Comparators and Engineer's Goggles read the shared fill level
and capacity from any part. The Item Drain also shows its fluid contents
in the goggles overlay.

The save uses Create's `TankContent`, `Size`, `Height` and member
`Controller` fields. Breaking a block redistributes fluid over surviving
parts before they reconnect. Formation keeps incompatible fluids apart
and only absorbs complete existing tanks. A deferred split survives a
clean restart while part of the footprint is unloaded. Recovery after an
interruption during chunk writes has separate requirements.

A normal placement against the top or bottom of a wider tank fills in
the rest of that layer when the player has enough blocks and the space
is clear. Sneaking and side placement place just the clicked block.
Lava gives off light according to the level in the windowed tank. A
Wrench closes the windows and removes that light. The surface geometry
uses the controller's width and height. With the original JAR, the roof
and side textures join within the same tank and keep their borders where
separate tanks touch. Interior lighting is darker in Horizon. Creative
schematic paste restores complete tanks through rotations and reflections,
with empty storage as in Java. A vertical Mechanical Bearing can capture
a complete ordinary tank in one loaded chunk column. The tank keeps its
shell, windows, water or lava during movement and gets a new controller
at its rotated corner when placed. The bearing waits if the destination
is blocked, including across a restart. The restored lava tank lights
its surroundings again. A dry Rope Pulley can also lift or lower a complete
tank within one loaded chunk column. Empty tanks and tanks carrying water,
honey or chocolate preserve their members and contents through a restart
and landing in the tested layouts. New groups use `fluids.fluidTankMaxHeight`
(32 by default). New tank inventories use `fluids.fluidTankCapacity`
(8 buckets per block by default). An already initialized inventory keeps
its physical limit when the setting changes. The goggles use the current
setting for their displayed capacity, including after restarting the world.
A controller rebuilt on load takes the current setting as its new physical limit.
A tank can load an amount above its fill limit. It
refuses additional fluid until space becomes available and can still
drain the saved amount. Virtual lighting inside moving cargo, boilers
and moving tanks spanning chunk columns remain open.

Fluid Pipes and a Mechanical Pump can move water or lava between tanks
and Basins on horizontal or vertical routes. A waterlogged pipe keeps its
external water. A Basin fills its input tanks and drains its output tanks
first. The pump takes power from a cog and pushes in the direction it faces.
Use a Wrench to reverse the pump. The default `fluids.mechanicalPumpRange`
of 16 reaches a tank through up to 15 pipes on each side, including across
loaded chunks. A pipe just inside the range retains pressure even when its
branch has no reachable tank. Shorter branches continue to transfer fluid.
Co-directed pumps can work in series through a single path between each
pair. The pressures add between pumps and the source face still sets the
rate of transfer. Short capped arms leave that path working and have no
pressure. Both pumps need power for sustained delivery.
With one or two closed side tanks between two co-directed pumps, both pumps
contribute pressure to the connecting network. Each side tank can receive or
supply fluid as flows change direction. The Java comparisons cover water with
unequal and equal RPM, empty side tanks, and drive changes.
After a simple line fills, one unbranched inlet at 32 RPM supplies 16 mB per
tick. A full tank or one
containing another fluid blocks the transfer. The supported lines resume after
a restart. With a single source, a pump can feed multiple closed outlets.
The first outlet to receive fluid can start transferring while another
branch fills. Once more than one outlet is ready, they share the supply.
Unused capacity on one branch goes to an outlet that can still accept it.
Multiple closed inlets can share a junction. Each inlet has its own rate
from its local pressure and starts when its flow reaches an outlet. If
water and lava meet inside the junction, it becomes cobblestone and drops
the pipe. The pump rebuilds pressure and the tanks retain their contents
in the tested layouts. Between co-directed pumps, a second side tank can
remain connected after the junction breaks. It regains pressure and resumes
filling with the surviving supply, including after a restart.
Two closed inlets and two closed outlets can operate together, including
uneven path lengths or a tank close to empty or full.
The original JAR supplies the pipe connections and tank collars. The
pump can emit vanilla water or lava drips at its active rims. One open
inlet can supply one or more closed outlets. A network with a closed
inlet can release fluid through separate open outlets and keep supplying its
other branches. The pipe keeps up to 1,000 mB at the open end while
transferring, including after a restart. A regenerating water source
stays in place and the pipe can empty a waterlogged block.
An open source can feed an open outlet on a separate world cell. One
cauldron can leave 500 mB in each of two outlet buffers.
Full water and lava cauldrons supply 1,000 mB. Partial cauldrons cannot
supply a pipe, and a pump cannot refill a cauldron through an open end.
Full bee nests and beehives supply 250 mB of honey and reset their honey
level. A partially filled hive stays unchanged. Open inlets can share a
closed outlet and retain independent buffers. A junction can draw from two
cauldrons or hives without pausing when those blocks empty.
When discharged into the other fluid, water turns a lava source into
obsidian and lava turns a water source into stone. Either combination
with flowing liquid yields cobblestone. These reactions leave the source
tank's fluid amount unchanged.
In the Nether, water discharged from an open end evaporates with an
extinguish sound and lava forms a normal source block.
Set `fluids.pipesPlaceFluidSourceBlocks = false` in `config/create-server.toml`
or the world's `serverconfig/create-server.toml` to discard full outlet
buffers instead of placing source blocks. The default is `true`.
An open end shows a moving stream with the original fluid tint.

Closed routes can carry Honey and Chocolate between Fluid Tanks and
Basins. They retain the original fluid IDs and separate incompatible
contents. Fluid Tanks show both through their windows and in the Goggles.
The local JAR supplies the two original still textures. Honey and Chocolate
world source blocks and flowing terrain need custom world fluids.
In Creative, use a Honey Bottle on a normal Fluid Tank to add 250 mB
while keeping the held bottle. In Survival it remains in your hand and
the tank stays unchanged. An empty Glass Bottle cannot draw honey from
the tank.
An ordinary Water Bottle and a Glass Bottle add or remove 250 mB of
water in Creative, with the same capacity checks. Other potion fluids,
including splash, lingering and custom-effect potions, remain open.

A supported line can include `create:fluid_valve` on a branch, with an
independent shaft for each valve. Drive the perpendicular shaft with positive
RPM to open it or negative RPM to close it. At zero RPM
the pointer stays where it is, and the valve keeps its last fully open or
closed state. A closed valve still carries pressure and stops fluid transfer.
The save uses `enabled` and Create's `Pointer` compound. The Wrench rotates
the casing and changes the shaft and pipe axes as in Java while retaining
the pointer position. The original JAR supplies the block and pointer
models. The pointer moves between server ticks as it opens and closes.
Other branches resume after the pressure rebuild when a valve changes state.

Loops, more than two active side tanks between pumps, open side endpoints
between pumps, shared open outlet cells and additional fluid machines remain
open. Opposing pumps on a closed line without middle storage keep pressure
on their exterior legs and leave the middle idle. Opposing pumps sharing
an active side endpoint remain open. The supported water and lava
effects include dousing exposed entities and blocks, setting fire to
entities and igniting arrows. Remote visuals for burning items and world
effects for custom fluids still need work.

The four sheet items retain `create:iron_sheet`, `create:golden_sheet` and
`create:copper_sheet` and `create:brass_sheet`. Kinetic entities retain `Speed` as a float. Depot data
uses `HeldItem.Item`, `Pos`, `PrevPos`, `Offset`, `PrevOffset`, `InSegment`,
`Angle`, `InDirection`; its eight output slots use `OutputBuffer.Size` and
`OutputBuffer.Items`. The creative tab uses upstream `itemGroup.create.base`.
All original locale files are imported unchanged from the player's supported
JAR; they are not included in the public repository.

## Present limits

This is an identifier/data convention baseline, not a completed Java serializer.
Horizon also saves its generic `Items` container field. Item stacks use Horizon's
26.3 item codec. Belt deliveries store the current and previous transport
positions of the Depot's held item. Hopper insertion and extraction follow
the ordinary Depot rules for its held slot and output buffer. A Java Depot's
`HeldItem` still needs an import path into Horizon slots. Waterlogged placement
and fluid ticks remain open.

Network serialization (`Source`, `Network`) is not fully represented yet. The prototype also stores diagnostic `Capacity`, `Stress`,
`NetworkStatus` and press bookkeeping `Applied`/`LastTick`; these are port-specific
extra fields. The `create_horizon.Ports` compound stores diagnostic physical port speeds.
Gearbox `Speed` uses a fixed reference port rather than Create's source-facing
basis; physical port ratios are preserved. Hand crank rendered motion now uses the original independent/chasing angle. Complete that schema alongside the corresponding behaviors, retaining
unknown loaded fields and documenting migrations. Existing 0.1 block entity IDs
remain accepted at runtime; newly placed blocks use the canonical type IDs above.

## Evidence

`tools/placement_oracle.py` compares Rust decisions to AST-extracted original
Java methods for 27,648 contexts. `tools/smoke.py` tests actual player placement,
depot exchange without a menu, item counts/components and save/reload, as well as
the small powered press chain. These tests do not establish full Create parity.


## 0.3 behavior boundary

The ordinary depot uses default `bulkPressing=false`, nine internal slots, direct
top exchange and a dynamic automation insertion predicate. Wire update tags carry
an explicit empty `HeldItem` compound when clearing the client; saved empty depots
omit it. This accounts for Horizon's merge semantics without leaving a stale item.
Motor updates use a bounded custom channel with server validation of packet size,
range, player, distance and target block; they do not implement Create's packet format.

The graph covers loaded components up to 4096 nodes, four-port gearboxes and split
clutch halves. Compatible generators choose the faster driver. Inconsistent cycles,
opposing sources and excessive speeds conservatively stop the component; original
breakage/network rebuilding is incomplete. Server configs are currently pinned to
the relevant Create defaults. World item scan timing/scatter, particles, random
sound variation, water and some collision/interaction shapes need later parity work.

## 0.4 data and behavior boundary

`create:speedometer` and `create:stressometer` retain `facing`, `axis_along_first`,
`Value` float and `Color` int. `create:vertical_gearbox` is an item alias for the
original `create:gearbox` block; normal/vertical recipes and axis-sensitive drops
use upstream IDs. `create:goggles` uses the head equipment slot and the original
3D head model through Horizon's item-display selection.

`create:water_wheel` retains six-way `facing`; `create:large_water_wheel` has `axis`
and `extension`. Both save `FlowScore` int and `Material.Name`, default spruce.
The invisible structural block uses the canonical `create:water_wheel_structure`
ID and `facing`. The port currently gives structural blocks a lightweight ticking
block entity to clean up missing masters; Java does not. The master also stores
`create_horizon.StructureReady` as a port-specific initialization marker.

World-axis angular transforms and crank motion have direct source/pose checks.
Gauge interpolation and comparator formulas are implemented with default config.
Native HUD layout, connection hints and rotation indicators remain provisional;
complete Java UI/Ponder/particle-provider parity is a later increment. Fluid
currents come from Horizon's vanilla sampler; Create's extra water-spread restriction
above wheel axes is not yet ported. Collision/selection shapes still include
conservative template approximations. This release adds generators, not moving
contraptions or fluid-handling machinery.

## 0.5 data and behavior boundary

The public catalog contains 24 block items and 15 standalone items: 39 creative-tab
entries, plus the internal water-wheel structural block. New item IDs are
`create:propeller`, `create:wheat_flour` and `create:dough`. The exported set has
123 source recipes and 35 tags. Processing includes 47 `create:milling`, ten
`create:splashing` and 19 `create:haunting` recipes with implemented Create or
vanilla inputs/results. Cooking uses Minecraft's real smelting, smoking and
blasting lookup; the exported dough-to-bread recipes remain
`minecraft:smelting` and `minecraft:smoking`, not invented Create recipe types.

The millstone has a fixed Y rotation axis, a shaft connection only underneath,
and the source small-cog connection behavior. Its source collision consists of a
16×6×16 base and a 12×10×12 centered upper part. One input slot and nine output
slots retain the original inventory names; Horizon also stores its generic
container representation and `create_horizon:millstone` bridge snapshot. Empty
hand collection takes output first, or input if no output exists. Recipe-filtered
automation, landed items, per-item probability rolls and timer handling are
implemented; native integration and save/reload coverage are recorded separately
in `VALIDATION.md`.
The Millstone pauses if any output slot holds 99 items, the NeoForge handler
limit. A normal 64-item stack still permits milling into the other slots.
Both modern milling results and legacy single-stack `item` results keep their
item components and leave the input's crafting remainder in the output buffer.
Millstone item particles follow the client processing timer. The retry arm
tick is quiet, and a running timer emits around the original half-block ring
with the tangent reversed when the rotation reverses.

An upward Mechanical Saw normally takes one item at a time. Set
`recipes.bulkCutting = true` in `config/create-server.toml` or the world's
`serverconfig/create-server.toml` for stack input from a Belt, dry Chute or
landed item. Bulk recipes use the original batch duration. Set
`recipes.allowStonecuttingOnSaw = false` to disable vanilla Stonecutting
recipes while keeping Create cutting recipes available.
Existing Saws keep their input limit until the block entity reloads or is
replaced. After a Saw has looked up recipes, run `/reload` to apply a change
to `allowStonecuttingOnSaw`.

The fan's shaft is opposite `facing`; both directions and all six orientations
are represented. Airflow range, push/pull choice, processing segments, partial
obstacle sampling, propeller speed and stack-dependent processing timers are
source-derived. Current targets include dropped items, cargo on Depots and
Belts, local players and mobs. Water washes, lit ordinary fire and campfires
smoke, soul fire and soul campfires haunt, and lava blasts. Blasting can
destroy items, including smokeable food, according
to the source policy; it is not a general-purpose way to cook food.
The blasting adapter reads the effective fire resistance, including the
supported per-stack full-fire component override and explicit removal.
Other damage selectors keep their original data and need separate parity checks.

`create:fan_transparent` and block/fluid `fan_processing_catalysts/*` retain the
supported source entries; unavailable Create blocks are omitted. Until the API
exposes fluid-tag queries, the adapter recognizes vanilla water/lava IDs and
waterlogged blocks explicitly. This is not arbitrary mod-fluid compatibility.
Recipe caches refresh when server data loads or reloads.

The `[kinetics.encasedFan]` table in `create-server.toml` supports Create's
`fanPushDistance`, `fanPullDistance`, `fanBlockCheckRate`, `fanRotationArgmax`
and `fanProcessingTime` settings. Distance selection follows the signed RPM.
The configured processing time applies when a stack starts a new cycle.

Depot-held progress uses `HeldItem.FanProcessingType` and
`HeldItem.FanProcessingTime`. Dropped-item progress now uses the original
`NeoForgeData.CreateData.Processing.Type` and `Time` entity NBT fields, retained
through Horizon's existing persistent unknown-field storage. Native save/reload
tests verify the exact remaining timer, preserved unknown sibling keys and
one-time conversion. Normal unfrozen play has been checked for player push,
pull and smoking damage. Live Java and Horizon checks also agree on mob
effects at a dry-to-haunting boundary, including Java's single-precision
position at the fan face. A frozen motor-start check still needs investigation.
Other entity types and further particle, sound and collision cases remain open.

The stationary mechanical drill uses the source rear shaft, six orientations and
12-pixel directional casing collision. Its front target, progress and retry timing
follow `DrillBlockEntity`/`BlockBreakingKineticBlockEntity`; ordinary block loot is
used rather than creative-mode drops. Its new crafting recipe uses the existing
alloy/casing/iron ingredients. Contraption movement, entity damage and automatic
target placement are outside this increment.
The native destruction path also leaves Create's cobblestone-generator shortcut,
ice-specific melting and custom zero-motion drop spawning for a later increment.

## Behavioral parity strategy

Rust organization follows the native runtime and may combine several Java
classes into cached data and small functions. Acceptance depends on observable
behavior, not a class-for-class translation. The existing AST-based oracles
compare selected unchanged Java method bodies against Rust with restricted
development contexts; they do not run the full original mod.

The paired schematic checks paste the same authored 1.21.1 files in Create
and Horizon. For a supported palette, put the file in the Horizon instance's
`schematics` folder and use
`/create schematic paste FILE.nbt X Y Z [quarter_turns [mirror]]` in Creative
with operator permission. The mirror values are `none`, `left_right` and
`front_back`. The mirror is applied first, followed by zero to three clockwise
quarter turns around the supplied anchor. The placement can extend into
negative offsets from the anchor. The transformed palette is limited to
verified simple blocks, logs, shafts, Flywheels, Creative Motors, Mechanical
Presses, Depots, empty horizontal Belts, unlinked Crafters and inactive
empty Deployers in USE mode. Unsupported Deployer data or an unsafe
destination refuses the paste before any cells are written. See the
[paired checks](../VALIDATION.md) for the layouts.
Cross-version world interchange remains outside the supported scope.
