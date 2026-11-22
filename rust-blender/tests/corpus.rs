//! The reference corpus, `corpus/v1/<library>/<group>.bn`, read as Blender 5.3 wrote it: every
//! text fits the target `blender@5.3`, as python/tests/test_corpus.py checks in Python. That it
//! parses and is canonical is rust/tests/corpus.rs's. Not in a packaged crate, which holds no corpus.

use std::fs;
use std::path::Path;

use base_node::parse;

#[test]
fn every_corpus_text_fits_blender_5_3() {
    let v1 = Path::new("../corpus/v1");
    if !v1.exists() {
        return;
    }
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
