//! The core names no destination: nothing of Blender, no node, no socket, no kind of tree, no
//! target, and it depends on no host library. What belongs to a destination is its library's
//! (rust-blender/). The same rule as python/tests/test_versioning.py, test_core_knows_no_destination.

use std::fs;
use std::path::Path;

/// Words of a destination, whatever their case.
const WORDS: [&str; 11] = [
    "blender",
    "nodesocket",
    "shadernode",
    "geometrynode",
    "compositornode",
    "base_node_",
    "_targets",
    "geometry",
    "shader",
    "compositor",
    "modifier",
];

fn named(file: &str, text: &str) -> Vec<String> {
    text.lines()
        .enumerate()
        .filter(|(_, line)| {
            let lower = line.to_lowercase();
            WORDS.iter().any(|w| lower.contains(w))
        })
        .map(|(n, line)| format!("{file}:{}: {}", n + 1, line.trim()))
        .collect()
}

#[test]
fn the_core_knows_no_destination() {
    let root = Path::new(env!("CARGO_MANIFEST_DIR"));
    let mut sources: Vec<_> = fs::read_dir(root.join("src"))
        .unwrap()
        .flatten()
        .map(|e| e.path())
        .collect();
    sources.sort();
    assert!(
        sources
            .iter()
            .all(|p| p.extension().is_some_and(|x| x == "rs")),
        "{sources:?}"
    );
    assert!(sources.len() >= 8, "{sources:?}");
    let mut found = Vec::new();
    for path in &sources {
        let file = path.file_name().unwrap().to_str().unwrap();
        found.extend(named(file, &fs::read_to_string(path).unwrap()));
    }
    // The manifest too: the core depends on no host library, and embeds nothing
    found.extend(named(
        "Cargo.toml",
        &fs::read_to_string(root.join("Cargo.toml")).unwrap(),
    ));
    assert!(!root.join("build.rs").exists(), "the core embeds no file");
    assert!(found.is_empty(), "{}", found.join("\n"));
}

#[test]
fn the_rule_finds_what_it_forbids() {
    assert_eq!(
        named("x.rs", "let a = 1;\n// a Shader socket\n"),
        ["x.rs:2: // a Shader socket"]
    );
    // No file is excused: the grammar has no word of a destination
    assert_eq!(named("ast.rs", "    pub geometry: Expr,").len(), 1);
}
