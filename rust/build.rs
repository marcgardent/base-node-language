//! Lists the modules of `stdlib/` for `src/stdlib.rs`: one `(name, include_str!(…))` per `.bn`,
//! by name, into `$OUT_DIR/stdlib_modules.rs`. Adding a module adds its file and edits no list; the
//! public mirror, which has no pro module, lists only the free ones.

use std::env;
use std::fs;
use std::path::{Path, PathBuf};

fn main() {
    let dir = Path::new(&env::var("CARGO_MANIFEST_DIR").unwrap()).join("../stdlib");
    println!("cargo:rerun-if-changed={}", dir.display());
    let mut names: Vec<String> = fs::read_dir(&dir)
        .unwrap()
        .flatten()
        .map(|e| e.path())
        .filter(|p| p.extension().is_some_and(|x| x == "bn"))
        .filter_map(|p| Some(p.file_stem()?.to_str()?.to_owned()))
        .collect();
    names.sort();
    let mut out = String::from("[\n");
    for name in &names {
        let path = dir.join(format!("{name}.bn"));
        println!("cargo:rerun-if-changed={}", path.display());
        out += &format!(
            "    ({name:?}, include_str!({:?})),\n",
            path.display().to_string()
        );
    }
    out += "]\n";
    let dest = PathBuf::from(env::var("OUT_DIR").unwrap()).join("stdlib_modules.rs");
    fs::write(dest, out).unwrap();
}
