//! The standard library, built into the crate: what a `use` of a stdlib module finds when a text
//! is checked against a target (`stdlib/` of the repository, as Python's `targets._module` reads
//! it). A module is parsed the first time a text uses it, then kept. A module the stdlib does not
//! have is not found: its calls are not followed.

use base_node::ast::File;
use std::sync::OnceLock;

/// (name, text) of each module of `stdlib/`, by name: build.rs lists the `.bn` files there, so
/// adding a module edits nothing here, and a stdlib with no pro module, as here, builds with the
/// free ones alone.
pub const MODULES: &[(&str, &str)] = &include!(concat!(env!("OUT_DIR"), "/stdlib_modules.rs"));

static PARSED: [OnceLock<Option<File>>; MODULES.len()] = [const { OnceLock::new() }; MODULES.len()];

/// Module `name` of the stdlib, parsed; none when the stdlib does not have it.
pub fn module(name: &str) -> Option<File> {
    let i = MODULES.iter().position(|(n, _)| *n == name)?;
    PARSED[i]
        .get_or_init(|| base_node::parse(MODULES[i].1, &format!("{name}.bn")).ok())
        .clone()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn every_module_of_the_stdlib_is_built_in_and_parses() {
        let dir = concat!(env!("CARGO_MANIFEST_DIR"), "/../stdlib");
        let mut names: Vec<String> = std::fs::read_dir(dir)
            .unwrap()
            .flatten()
            .filter_map(|e| {
                let p = e.path();
                let stem = p.file_stem()?.to_str()?.to_owned();
                p.extension().is_some_and(|x| x == "bn").then_some(stem)
            })
            .collect();
        names.sort();
        let mut built_in: Vec<&str> = MODULES.iter().map(|(n, _)| *n).collect();
        built_in.sort();
        assert_eq!(names, built_in);
        for &(name, text) in MODULES {
            assert!(text.contains(&format!("// @module {name}\n")), "{name}");
            assert!(module(name).is_some(), "{name}");
        }
        assert!(module("nope").is_none());
    }
}
