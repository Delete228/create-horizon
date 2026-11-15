# Install Create for Horizon

1. Create an instance in Horizon Launcher with **Nightly `9f42064`** for
   Minecraft 26.3. If the Launcher asks to prepare the game files, finish
   that step before building the mod.
2. Open **Mods → Add from GitHub** and paste the project URL.

   ```text
   https://github.com/Delete228/create-horizon/tree/main
   ```

3. Open the instance's native mod build screen and select **Build**. Review the
   launcher's native-code prompt before confirming. The launcher builds the
   pinned engine and installs the bundled content.
4. Select **Play**. In Creative, open the **Create for Horizon** tab.

The mod includes its own models and pixel textures. The original Create look
needs a local Create 6.0.10 JAR. [Resource setup](assets.md)

## Supported versions

The 0.9.0 source build targets Minecraft 26.3 and pins official Horizon
Nightly `9f42064` from November 13 and the accepted Horizon Mixins revision.
Native mods in the same build need compatible pins.
The original Java Create reference is 6.0.10 for Minecraft 1.21.1.
[Exact revisions](../compatibility.json) · [Official Horizon source](https://github.com/horizon-rust/horizon/tree/nightly-source/2026-11-13-9f42064)

For the 0.7 test world and evidence, see the [review route](reviews/0.7-test-world.md)
and [checkpoint report](reviews/0.7-report.md). Earlier launcher builds and
installation results are recorded in [validation](../VALIDATION.md).
