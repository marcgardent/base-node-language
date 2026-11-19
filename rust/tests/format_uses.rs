//! The uses get sorted, the head comments of the module stay above them, a comment between two
//! uses goes with the use under it, the blank lines stay where they were. The Python formatter has
//! the same cases (python/tests/test_format.py, USE_CASES).

use base_node::format_source;

const GRAPH: &str = "geometry graph g() -> Float {\n  return 1.0\n}\n";

fn check(case: &str, source: &str, expected: &str) {
    let source = format!("{source}{GRAPH}");
    let expected = format!("{expected}{GRAPH}");
    assert_eq!(format_source(&source, "m.bn").unwrap(), expected, "{case}");
    assert_eq!(
        format_source(&expected, "m.bn").unwrap(),
        expected,
        "{case}: not stable"
    );
}

#[test]
fn sorted_after_a_head_comment() {
    let text = "// @module m\n\n// prose\n// more\nuse grade (a, b)\n\nuse merge (c, d)\n\n";
    check("sorted after a head comment", text, text);
}

#[test]
fn unsorted_after_a_head_comment() {
    check(
        "unsorted after a head comment",
        "// @module m\n\n// prose\nuse merge (c, d)\n\nuse grade (a, b)\n\n",
        "// @module m\n\n// prose\nuse grade (a, b)\n\nuse merge (c, d)\n\n",
    );
    check(
        "unsorted after a head comment and a blank line",
        "// head\n\nuse zeta (z)\nuse alpha (a)\n\n",
        "// head\n\nuse alpha (a)\nuse zeta (z)\n\n",
    );
}

#[test]
fn a_comment_between_two_uses_goes_with_the_use_under_it() {
    check(
        "a comment between two uses",
        "// head\nuse merge (c, d)\n// about grade\nuse grade (a, b)\n\n",
        "// head\n\n// about grade\nuse grade (a, b)\nuse merge (c, d)\n\n",
    );
    check(
        "comment groups and blank lines",
        "// @module m\n\n// prose\nuse zeta\n\n// about merge\n// still\nuse merge (c)  // tm\n\n\
         // about alpha\n\nuse alpha\n\n",
        "// @module m\n\n// prose\n\n// about alpha\n\nuse alpha\n\n// about merge\n// still\n\
         use merge (c)  // tm\n\nuse zeta\n\n",
    );
}

#[test]
fn trailing_comments_stay_on_their_use() {
    check(
        "trailing comments",
        "use merge (c, d)  // m\nuse grade (a, b)  // g\n\n",
        "use grade (a, b)  // g\nuse merge (c, d)  // m\n\n",
    );
    check(
        "a comment inside a split use",
        "use zeta (\n  a,  // first\n  b,\n)\nuse alpha\n\n",
        "use alpha\nuse zeta (a, b)  // first\n\n",
    );
}
