//! Blade's Pixel Nodes for Base Node (`.bn`): the target `blade` (`targets/blade.json`), its
//! translator from `blender`, and its bridge module (`targets/blade/blender_interop.bn`), built in
//! and made known to Blender's library by [`add`] (spec/blade.md).

/// The target files, by name: `targets/<name>.json`.
pub const FILES: &[(&str, &str)] = &[("blade", include_str!("../../targets/blade.json"))];

/// The bridges, by the path the target's `bridges` give.
pub const BRIDGES: &[(&str, &str)] = &[(
    "blade/blender_interop.bn",
    include_str!("../../targets/blade/blender_interop.bn"),
)];

/// Make the target `blade` known to Blender's library: before its first check, once.
pub fn add() -> Result<(), String> {
    base_node_blender::targets::add_targets(FILES, BRIDGES)
}
