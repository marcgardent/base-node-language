//! The head of a .bn file as the core reads it (`// @module`, `// @target`…): what it knows is
//! checked, what a host adds is given back as written, for the host to judge. The Python package's
//! `python/base_node/header.py`; what a host makes of the head is tested with its library.

use base_node::header::directives;
use base_node::{header, read_head};

const GRAPH: &str = "kind graph g() -> Float {\n  return 1.0\n}\n";

fn errors(source: &str, targets: &[&str]) -> Vec<(usize, usize, String)> {
    header(source, "f.bn", targets)
        .unwrap_err()
        .diagnostics
        .into_iter()
        .map(|d| (d.line, d.col, d.message))
        .collect()
}

#[test]
fn text_directives_and_quotes() {
    let h = header(
        &format!("// @module waves\n// @title \"Waves\"\n// @author Marc G.\n// @license MIT OR Apache-2.0\n// @version 1.2.0\n// @edition 2026\n\n{GRAPH}"),
        "f.bn",
        &[],
    )
    .unwrap();
    assert_eq!(h.module.as_deref(), Some("waves"));
    assert_eq!(h.title.as_deref(), Some("Waves"));
    assert_eq!(h.author.as_deref(), Some("Marc G."));
    assert_eq!(h.license.as_deref(), Some("MIT OR Apache-2.0"));
    assert_eq!(h.version.as_deref(), Some("1.2.0"));
    assert_eq!(h.edition.as_deref(), Some("2026"));
    assert!(h.target.is_empty());
    assert_eq!(h.lines["title"], 2);
}

#[test]
fn only_the_head_holds_directives() {
    let src = format!("// a note\n\n// @title A\n{GRAPH}// @title B\n");
    let found = directives(&src);
    assert_eq!(found.len(), 1);
    assert_eq!(
        (found[0].name.as_str(), found[0].line, found[0].col),
        ("title", 3, 11)
    );
    // No space before the value: a comment
    assert!(directives("// @title\"A\"\n").is_empty());
}

#[test]
fn any_name_is_a_target_unless_the_caller_names_them() {
    let src = format!("// @target \"here\", there, here\n\n{GRAPH}");
    assert_eq!(header(&src, "f.bn", &[]).unwrap().target, ["here", "there"]);
    assert_eq!(
        header(&src, "f.bn", &["here", "there"]).unwrap().target,
        ["here", "there"]
    );
    assert_eq!(
        errors(&src, &["here", "elsewhere"]),
        [(1, 20, "@target 'there': one of here, elsewhere".to_owned())]
    );
}

#[test]
fn a_malformed_module_name() {
    assert_eq!(
        errors(&format!("// @module my-module\n{GRAPH}"), &[]),
        [(
            1,
            12,
            "@module 'my-module': a module is named by an identifier (letters, digits, _), its file being <name>.bn"
                .to_owned()
        )]
    );
}

#[test]
fn a_directive_twice_or_empty() {
    assert_eq!(
        errors(&format!("// @title A\n// @title B\n{GRAPH}"), &[]),
        [(2, 11, "@title is already set on line 1".to_owned())]
    );
    assert_eq!(
        errors(&format!("// @author\n{GRAPH}"), &[]),
        [(1, 11, "@author needs a value".to_owned())]
    );
}

#[test]
fn an_edition_this_reader_does_not_know() {
    // python/tests/test_header.py holds the same cases
    let unknown = "@edition '2028': not an edition this reader knows (2026)".to_owned();
    assert_eq!(base_node::EDITIONS, ["2026"]);
    let src = format!("// A text of later\n// @edition 2028\n{GRAPH}");
    assert_eq!(errors(&src, &[]), [(2, 13, unknown.clone())]);
    for e in [
        base_node::parse(&src, "f.bn").unwrap_err(),
        base_node::format_source(&src, "f.bn").unwrap_err(),
    ] {
        let d = &e.diagnostics[0];
        assert_eq!(e.diagnostics.len(), 1);
        assert_eq!(
            (d.filename.as_str(), d.line, d.col, d.message.clone()),
            ("f.bn", 2, 13, unknown.clone())
        );
    }
    assert_eq!(
        errors(&format!("// @edition \"2028\"\n{GRAPH}"), &[]),
        [(1, 13, unknown)]
    );
    // The one it knows, quoted or not, and none at all: the latest
    for head in ["// @edition 2026\n", "// @edition \"2026\"\n", ""] {
        let src = format!("{head}{GRAPH}");
        assert!(base_node::parse(&src, "f.bn").is_ok());
        assert!(base_node::format_source(&src, "f.bn").is_ok());
    }
    assert_eq!(header(GRAPH, "f.bn", &[]).unwrap().edition, None);
    // Only the head names the edition: a comment under the first graph is a comment
    assert!(base_node::parse(&format!("{GRAPH}// @edition 2028\n"), "f.bn").is_ok());
    // Written twice, the first is the file's; with no value, the head says so
    assert_eq!(
        errors(&format!("// @edition 2026\n// @edition 2028\n{GRAPH}"), &[]),
        [(2, 13, "@edition is already set on line 1".to_owned())]
    );
    assert!(base_node::parse(&format!("// @edition\n{GRAPH}"), "f.bn").is_ok());
}

#[test]
fn the_text_is_not_parsed() {
    // The head is read from the comments alone: a syntax error below is the parser's to tell
    let h = header("// @title x\nkind graph (", "f.bn", &[]).unwrap();
    assert_eq!(h.title.as_deref(), Some("x"));
}

#[test]
fn a_host_s_directives_are_given_back_as_written() {
    let src = format!(
        "// @title A\n// @mine  \"one\", two\n// @other\n// @mine again\n// @unknown x\n{GRAPH}"
    );
    // Without the host naming them, they are comments
    assert!(header(&src, "f.bn", &[]).is_ok());
    let head = read_head(&src, "f.bn", &[], &["mine", "other", "absent"]);
    let mine = head.get("mine").unwrap();
    assert_eq!(
        (mine.value.as_str(), mine.line, mine.col),
        ("\"one\", two", 2, 11)
    );
    assert!(head.get("other").is_none());
    assert!(head.get("absent").is_none());
    assert!(head.get("unknown").is_none());
    assert_eq!(head.header.title.as_deref(), Some("A"));
    assert_eq!(head.header.lines["mine"], 2);
    assert_eq!(head.header.lines["other"], 3);
    let found: Vec<_> = head
        .diagnostics
        .iter()
        .map(|d| (d.line, d.col, d.message.as_str()))
        .collect();
    assert_eq!(
        found,
        [
            (3, 10, "@other needs a value"),
            (4, 10, "@mine is already set on line 2")
        ]
    );
}

#[test]
fn text_directives_read_escapes() {
    let src = format!(
        "{}\n{}\n{}\n{}\n{GRAPH}",
        r#"// @title "Say \"hi\" \u{1F600}""#,
        r#"// @author "A\\B""#,
        r#"// @target "blender@5.3", "bl\u{61}de""#,
        r#"// @module "waves""#,
    );
    let h = header(&src, "f.bn", &[]).unwrap();
    assert_eq!(h.title.as_deref(), Some("Say \"hi\" \u{1F600}"));
    assert_eq!(h.author.as_deref(), Some("A\\B"));
    assert_eq!(h.target, ["blender@5.3", "blade"]);
    assert_eq!(h.module.as_deref(), Some("waves"));
    // Free text that is not one string stays as written
    let h = header(
        &format!("// @title \"Waves\" and \"Ripples\"\n{GRAPH}"),
        "f.bn",
        &[],
    )
    .unwrap();
    assert_eq!(h.title.as_deref(), Some("\"Waves\" and \"Ripples\""));
    let h = header(&format!("// @title \"Waves\n{GRAPH}"), "f.bn", &[]).unwrap();
    assert_eq!(h.title.as_deref(), Some("\"Waves"));
}
