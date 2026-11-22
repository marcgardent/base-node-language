//! Lists the modules of `stdlib/` for `src/stdlib.rs`: one `(name, include_str!(…))` per `.bn`,
//! by name, into `$OUT_DIR/stdlib_modules.rs`. Adding a module adds its file and edits no list; a
//! stdlib with no pro module, as here, lists only the free ones.
//!
//! The same for the files of `targets/blender/` for `src/targets.rs`, one per `.json`, into
//! `$OUT_DIR/blender_files.rs`: the catalog of each version of Blender and the variants. A new
//! catalog adds its file and edits no list.

use std::env;
use std::fs;
use std::path::{Path, PathBuf};

fn main() {
    list("../stdlib", "bn", "stdlib_modules.rs");
    list("../targets/blender", "json", "blender_files.rs");
}

/// Writes `$OUT_DIR/<dest>`: `[(stem, include_str!(path)), …]` of the files of `dir` (relative to
/// the crate) with that extension, by name.
fn list(dir: &str, extension: &str, dest: &str) {
    let dir = Path::new(&env::var("CARGO_MANIFEST_DIR").unwrap()).join(dir);
    println!("cargo:rerun-if-changed={}", dir.display());
    let mut names: Vec<String> = fs::read_dir(&dir)
        .unwrap()
        .flatten()
        .map(|e| e.path())
        .filter(|p| p.extension().is_some_and(|x| x == extension))
        .filter_map(|p| Some(p.file_stem()?.to_str()?.to_owned()))
        .collect();
    names.sort();
    let mut out = String::from("[\n");
    for name in &names {
        let path = dir.join(format!("{name}.{extension}"));
        println!("cargo:rerun-if-changed={}", path.display());
        out += &format!(
            "    ({name:?}, include_str!({:?})),\n",
            path.display().to_string()
        );
    }
    out += "]\n";
    let dest = PathBuf::from(env::var("OUT_DIR").unwrap()).join(dest);
    fs::write(dest, out).unwrap();
}
