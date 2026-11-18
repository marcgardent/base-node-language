//! The standard library, built into the crate: what a `use` of a stdlib module finds when a text
//! is checked against a target (`stdlib/` of the repository, as Python's `targets._module` reads
//! it). A module is parsed the first time a text uses it, then kept. A module the stdlib does not
//! have is not found: its calls are not followed.

use crate::ast::File;
use std::sync::OnceLock;

macro_rules! modules {
    ($($name:literal),* $(,)?) => {
        [$(($name, include_str!(concat!("../../stdlib/", $name, ".bn")))),*]
    };
}

/// (name, text) of each module of `stdlib/`: the free ones, then the pro ones, which
/// studio/export_public.py cuts out of the public mirror.
pub const MODULES: &[(&str, &str)] = &modules!(
    "curves2d",
    "fillet2d",
    "grade",
    "mask2d",
    "math",
    "merge",
    "patterns2d",
    "planar2d",
    "qc",
    "sdf2d",
    "stmap",
);

static PARSED: [OnceLock<Option<File>>; MODULES.len()] = [const { OnceLock::new() }; MODULES.len()];

/// Module `name` of the stdlib, parsed; none when the stdlib does not have it.
pub fn module(name: &str) -> Option<File> {
    let i = MODULES.iter().position(|(n, _)| *n == name)?;
    PARSED[i]
        .get_or_init(|| crate::parse(MODULES[i].1, &format!("{name}.bn")).ok())
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
