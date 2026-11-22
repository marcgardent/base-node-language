//! The texts every implementation reads the same: those of `conformance/` and the fixtures of the
//! Python tests parse, and are in canonical form. What a destination accepts of them is checked
//! with its library (rust-blender/tests/conformance.rs).

use std::fs;
use std::path::Path;

use base_node::{format_source, parse};

#[test]
fn test_compat_1_0_files() {
    let compat_dir = Path::new("../conformance");
    if !compat_dir.exists() {
        return;
    }

    for entry in fs::read_dir(compat_dir).unwrap() {
        let entry = entry.unwrap();
        let path = entry.path();
        if path.extension().and_then(|s| s.to_str()) == Some("bn") {
            let filename = path.file_name().unwrap().to_str().unwrap();
            let src = fs::read_to_string(&path).unwrap();
            let file = parse(&src, filename)
                .unwrap_or_else(|e| panic!("Parse error on compat {}: {}", filename, e));
            assert!(!file.graphs.is_empty());

            let formatted = format_source(&src, filename)
                .unwrap_or_else(|e| panic!("Formatting error on compat {}: {}", filename, e));

            if filename == "shapes.bn" {
                // shapes.bn contains 1.0 variants (dot, cross, ·) that the formatter canonicalizes
                let idempotent = format_source(&formatted, filename).unwrap();
                assert_eq!(
                    idempotent, formatted,
                    "Formatting not idempotent on shapes.bn"
                );
            } else {
                assert_eq!(
                    formatted, src,
                    "Formatting not character-identical on compat {}",
                    filename
                );
            }
        }
    }
}

#[test]
fn test_examples_and_fixtures() {
    let fixtures_dir = Path::new("../python/tests/fixtures");
    if fixtures_dir.exists() {
        for entry in fs::read_dir(fixtures_dir).unwrap() {
            let entry = entry.unwrap();
            let path = entry.path();
            if path.extension().and_then(|s| s.to_str()) == Some("bn") {
                let filename = path.file_name().unwrap().to_str().unwrap();
                let src = fs::read_to_string(&path).unwrap();
                let file = parse(&src, filename)
                    .unwrap_or_else(|e| panic!("Parse error on fixture {}: {}", filename, e));
                assert!(!file.graphs.is_empty());

                let formatted = format_source(&src, filename).unwrap();
                assert_eq!(
                    formatted, src,
                    "Formatting not character-identical on fixture {}",
                    filename
                );
            }
        }
    }
}

/// `name < … > (`: a call with types, or comparisons where name holds a value
/// (python/tests/test_conformance.py reads the same cases).
#[test]
fn chevrons_read_as_python_reads_them() {
    read_as_written("../conformance/chevron-cases.json");
}

/// `Name[SETTING, key: value](inputs)`: a call's settings, read and laid out as
/// python/tests/test_conformance.py does.
#[test]
fn settings_in_brackets_read_as_python_reads_them() {
    read_as_written("../conformance/bracket-cases.json");
}

/// The cases of a file of conformance/: each prints back as `formatted`, or is refused at `error`.
fn read_as_written(path: &str) {
    let corpus: serde_json::Value =
        serde_json::from_str(&fs::read_to_string(path).unwrap()).unwrap();
    for case in corpus["cases"].as_array().unwrap() {
        let name = case["name"].as_str().unwrap();
        let text = case["text"].as_str().unwrap();
        if let Some(error) = case["error"].as_str() {
            let e = parse(text, "case.bn").expect_err(name);
            let d = &e.diagnostics[0];
            assert_eq!(format!("{}:{}", d.line, d.col), error, "{name}");
        } else {
            let formatted =
                format_source(text, "case.bn").unwrap_or_else(|e| panic!("{name}: {e}"));
            assert_eq!(formatted, case["formatted"].as_str().unwrap(), "{name}");
        }
    }
}

#[test]
fn test_versioning() {
    // One version for the crate and the stdlib (make bump writes both); the crate's is Cargo.toml's
    assert_eq!(base_node::VERSION, base_node::STDLIB_VERSION);
    assert_eq!(base_node::EDITION, "2026");
}

#[test]
fn a_missing_tree_kind_names_no_kind() {
    // The kinds of tree are a host's: the core says only that one is expected
    let e = parse("12 graph g() -> Float {\n  return 1.0\n}\n", "g.bn").unwrap_err();
    assert_eq!(e.diagnostics[0].message, "expected tree kind, found '12'");
}

#[test]
fn a_graph_marked_deprecated_is_read_and_written_back() {
    // The mark is a setting of the graph, with no grammar of its own: whoever checks the calls
    // of a text warns of it (in Python, python/base_node_blender/typecheck.py)
    let src = "kind(deprecated: \"use twice\") graph double(x: Float) -> Float {\n  return x * 2.0\n}\n\n\
               kind(deprecated: true) graph half(x: Float) -> Float {\n  return x / 2.0\n}\n";
    let file = parse(src, "old.bn").unwrap();
    let said: Vec<_> = file
        .graphs
        .iter()
        .map(|g| (g.settings[0].name.as_deref(), &g.settings[0].value))
        .collect();
    assert!(matches!(
        said[0],
        (Some("deprecated"), base_node::ast::Expr::String(s)) if s.value == "use twice"
    ));
    assert!(matches!(
        said[1],
        (Some("deprecated"), base_node::ast::Expr::Bool(b)) if b.value
    ));
    assert_eq!(format_source(src, "old.bn").unwrap(), src);
}
