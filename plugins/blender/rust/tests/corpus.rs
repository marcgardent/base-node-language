//! The reference corpus, `corpus/v1/<library>/<group>.bn`: the groups of third-party libraries as
//! the reader of Blender writes them, as Blender 5.3 wrote them. Every text parses, and is in
//! canonical form: the formatter of the core prints it unchanged; and every text fits the target
//! `blender@5.3`, as python/tests/test_corpus.py checks in Python. Not in a packaged crate, which
//! holds no corpus.

use std::fs;
use std::path::{Path, PathBuf};

use base_node::{format_source, parse};

/// The `.bn` files of `corpus/v1`, by library then group.
fn corpus_files(v1: &Path) -> Vec<PathBuf> {
    let mut files = Vec::new();
    for library in fs::read_dir(v1).unwrap().flatten() {
        if library.path().is_dir() {
            for f in fs::read_dir(library.path()).unwrap().flatten() {
                if f.path().extension().is_some_and(|x| x == "bn") {
                    files.push(f.path());
                }
            }
        }
    }
    files.sort();
    files
}

#[test]
fn every_corpus_text_parses_and_is_canonical() {
    let v1 = Path::new("../corpus/v1");
    if !v1.exists() {
        return;
    }
    let files = corpus_files(v1);
    assert!(!files.is_empty());
    let mut wrong = Vec::new();
    for path in &files {
        let name = path.strip_prefix(v1).unwrap().to_str().unwrap();
        let src = fs::read_to_string(path).unwrap();
        match parse(&src, name) {
            Err(e) => wrong.push(format!("{name}: {e}")),
            Ok(file) if file.graphs.is_empty() => wrong.push(format!("{name}: no graph")),
            Ok(_) => match format_source(&src, name) {
                Err(e) => wrong.push(format!("{name}: formatting: {e}")),
                Ok(printed) if printed != src => {
                    wrong.push(format!("{name}: the formatter prints it otherwise"))
                }
                Ok(_) => {}
            },
        }
    }
    assert!(
        wrong.is_empty(),
        "{} of {} texts:\n{}",
        wrong.len(),
        files.len(),
        wrong.join("\n")
    );
}

#[test]
fn every_corpus_text_fits_blender_5_3() {
    let v1 = Path::new("../corpus/v1");
    if !v1.exists() {
        return;
    }
    let files = corpus_files(v1);
    assert!(!files.is_empty());
    let mut wrong = Vec::new();
    for path in &files {
        let name = path.strip_prefix(v1).unwrap().to_str().unwrap();
        let src = fs::read_to_string(path).unwrap();
        let file = parse(&src, name).unwrap_or_else(|e| panic!("{name}: {e}"));
        for issue in base_node_blender::check_target(&file, "blender@5.3").unwrap() {
            wrong.push(format!("{name}: {issue}"));
        }
    }
    assert!(
        wrong.is_empty(),
        "{} issues in {} texts:\n{}",
        wrong.len(),
        files.len(),
        wrong.join("\n")
    );
}
