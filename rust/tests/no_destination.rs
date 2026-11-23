//! The core names no destination: nothing of Blender, no node, no socket, no kind of tree, no
//! target, and it depends on no host library. What belongs to a destination is its host library's.
//! The same rule as python/tests/test_versioning.py, test_core_knows_no_destination.

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

/// The lines of the crate's sources, tests and manifest that name a file of a host.
fn plugin_files(root: &Path) -> Vec<String> {
    let folder = concat!("plugins", "/");
    let mut paths = vec![root.join("Cargo.toml")];
    for dir in ["src", "tests"] {
        paths.extend(
            fs::read_dir(root.join(dir))
                .unwrap()
                .flatten()
                .map(|e| e.path()),
        );
    }
    paths.sort();
    let mut found = Vec::new();
    for path in &paths {
        let text = fs::read_to_string(path).unwrap();
        for (n, line) in text.lines().enumerate() {
            if line.contains(folder) {
                found.push(format!("{}:{}: {}", path.display(), n + 1, line.trim()));
            }
        }
    }
    found
}

#[test]
fn the_core_reads_no_plugin() {
    // A host lives in its own folder and depends on the core: a checkout without it builds the
    // core and passes its tests, so nothing of the crate names a file there
    let root = Path::new(env!("CARGO_MANIFEST_DIR"));
    let found = plugin_files(root);
    assert!(found.is_empty(), "{}", found.join("\n"));
}
