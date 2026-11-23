//! The head of a .bn file (`// @module`, `// @offer`…) is made of comments: the formatter keeps
//! it as written, so that a file formatted here still says what it offers when dropped on Blender.
//! The directives are read and checked here as by the Python package (python/base_node_blender/header.py),
//! message for message: the tests below are its tests.

use std::fs;

use base_node::header::directives;
use base_node::{format_source, parse};
use base_node_blender::{header, Header};

fn head(source: &str) -> Vec<&str> {
    source
        .lines()
        .take_while(|l| l.trim().is_empty() || l.starts_with("//"))
        .collect()
}

#[test]
fn the_formatter_keeps_the_directives() {
    let src = fs::read_to_string("../examples/drop_example.bn").unwrap();
    parse(&src, "drop_example.bn").unwrap();
    let formatted = format_source(&src, "drop_example.bn").unwrap();
    assert_eq!(head(&formatted), head(&src));
    assert!(formatted.starts_with("// @module drop_example\n"));
    assert!(formatted.contains("// @offer library, groups, example, modifier\n"));
    assert!(formatted.contains("// @modifier \"wave modifier\"\n"));
}

#[test]
fn unknown_directives_are_comments_too() {
    let src = "// @gallery-id 42\n// @offer groups\n\ngeometry graph g() -> Geometry {\n  return Grid()\n}\n";
    assert_eq!(format_source(src, "g.bn").unwrap(), src);
}

const MAKER: &str = "geometry graph field() -> Geometry {\n  return Grid(size_x: 1.0, size_y: 1.0, vertices_x: 2, vertices_y: 2)\n}\n";
const MODIFIER: &str =
    "geometry graph lift(geometry: Geometry) -> Geometry {\n  return SetPosition(geometry)\n}\n";
const HELPER: &str = "geometry graph half(x: Float) -> Float {\n  return x / 2.0\n}\n";

fn ok(source: &str) -> Header {
    header(source, "f.bn").unwrap()
}

fn errors(source: &str) -> Vec<(usize, usize, String)> {
    header(source, "f.bn")
        .unwrap_err()
        .diagnostics
        .into_iter()
        .map(|d| (d.line, d.col, d.message))
        .collect()
}

fn offer(h: &Header) -> Vec<&str> {
    h.offer.iter().map(String::as_str).collect()
}

#[test]
fn the_stdlib_head_is_read() {
    let src = fs::read_to_string("../stdlib/curves2d.bn").unwrap();
    let h = header(&src, "curves2d.bn").unwrap();
    assert_eq!(h.module.as_deref(), Some("curves2d"));
    assert_eq!(h.version.as_deref(), Some(base_node::STDLIB_VERSION));
    assert_eq!(h.target, ["blender"]);
    assert_eq!(h.edition.as_deref(), Some("2026"));
    assert_eq!(offer(&h)[..2], ["library", "groups"]);
}

#[test]
fn text_directives_and_quotes() {
    let h = ok(&format!(
        "// @title \"Waves\"\n// @author Marc G.\n// @license MIT OR Apache-2.0\n// @target \"blender@5.3  gltf\", blender\n\n{MAKER}"
    ));
    assert_eq!(h.title.as_deref(), Some("Waves"));
    assert_eq!(h.author.as_deref(), Some("Marc G."));
    assert_eq!(h.license.as_deref(), Some("MIT OR Apache-2.0"));
    assert_eq!(h.target, ["blender@5.3 gltf", "blender"]);
    assert!(h.module.is_none());
    assert_eq!(h.mesh, "cube");
}

#[test]
fn only_the_head_holds_directives() {
    let src = format!("// a comment\n\n// @module first\nuse math\n// @module later\n{MAKER}");
    let d: Vec<(String, String)> = directives(&src)
        .into_iter()
        .map(|d| (d.name, d.value))
        .collect();
    assert_eq!(d, [("module".to_owned(), "first".to_owned())]);
    assert!(directives(&format!("// @target\"x\"\n// see @module\n{MAKER}")).is_empty());
}

#[test]
fn inference_of_the_offers() {
    assert_eq!(offer(&ok(MAKER)), ["groups", "example"]);
    assert_eq!(offer(&ok(MODIFIER)), ["groups", "modifier"]);
    assert_eq!(offer(&ok(HELPER)), ["groups"]);
    let all = ok(&format!("// @module waves\n{MAKER}{MODIFIER}"));
    assert_eq!(offer(&all), ["library", "groups", "example", "modifier"]);
}

#[test]
fn a_called_graph_is_neither_example_nor_modifier() {
    let h = ok(&format!(
        "{MAKER}geometry graph both() -> Geometry {{\n  return field()\n}}\n"
    ));
    assert_eq!(h.examples, ["both"]);
    assert_eq!(h.example.as_deref(), Some("both"));
    let called = format!(
        "{MODIFIER}geometry graph twice(geometry: Geometry) -> Geometry {{\n  return lift(lift(geometry))\n}}\n"
    );
    assert_eq!(ok(&called).modifiers, ["twice"]);
}

#[test]
fn the_written_setting_decides_the_modifier() {
    let src = "geometry(is_modifier: false) graph lift(geometry: Geometry) -> Geometry {\n  return geometry\n}\n";
    assert!(ok(src).modifiers.is_empty());
}

#[test]
fn a_graph_named_with_escapes() {
    // The string of a directive is a string of the language: a graph named with a `"` is named there
    let lift = MODIFIER.replace("graph lift", r#"graph "the \"lift\"""#);
    let h = ok(&format!("{}\n{lift}", r#"// @modifier "the \"lift\"""#));
    assert_eq!(h.modifier.as_deref(), Some("the \"lift\""));
    let field = MAKER.replace("graph field", r#"graph "C:\\field \u{1F600}""#);
    let h = ok(&format!(
        "{}\n{field}",
        r#"// @example "C:\\field \u{1F600}""#
    ));
    assert_eq!(h.example.as_deref(), Some("C:\\field \u{1F600}"));
    // An unknown escape, or quotes that are not one string, name no graph
    for written in [r#""the \qlift""#, r#""the" "lift""#, r#""""#] {
        let e = errors(&format!("// @modifier {written}\n{lift}"));
        assert_eq!(e.len(), 1);
        assert_eq!(
            e[0].2,
            format!("@modifier {written}: a graph's name, quoted, or a bare identifier")
        );
    }
    assert_eq!(ok(&format!("// @mesh \"grid\"\n{MODIFIER}")).mesh, "grid");
    assert_eq!(
        errors(&format!("// @mesh \"grid\n{MODIFIER}")),
        [(
            1,
            10,
            "@mesh '\"grid': one of cube, plane, sphere, cylinder, grid".to_owned()
        )]
    );
}

#[test]
fn the_last_graph_is_used_unless_named() {
    let two = format!("{MAKER}{}", MAKER.replace("field", "meadow"));
    assert_eq!(ok(&two).example.as_deref(), Some("meadow"));
    assert_eq!(
        ok(&format!("// @example field\n{two}")).example.as_deref(),
        Some("field")
    );
    let named = format!(
        "// @modifier \"the lift\"\n{}{MODIFIER}",
        MODIFIER.replace("graph lift", "graph \"the lift\"")
    );
    assert_eq!(ok(&named).modifier.as_deref(), Some("the lift"));
    assert_eq!(
        ok(&format!("// @modifier \"lift\"\n{MODIFIER}"))
            .modifier
            .as_deref(),
        Some("lift")
    );
}

#[test]
fn written_offers_are_kept_in_order() {
    let h = ok(&format!("// @offer modifier, groups\n{MODIFIER}"));
    assert!(h.offer_written);
    assert_eq!(offer(&h), ["groups", "modifier"]);
    assert!(ok(&format!("// @offer groups\n{MODIFIER}"))
        .modifier
        .is_none());
}

#[test]
fn the_mesh() {
    assert_eq!(ok(&format!("// @mesh sphere\n{MODIFIER}")).mesh, "sphere");
    assert_eq!(
        errors(&format!("// @mesh torus\n{MODIFIER}")),
        [(
            1,
            10,
            "@mesh 'torus': one of cube, plane, sphere, cylinder, grid".to_owned()
        )]
    );
}

#[test]
fn unknown_directives_are_ignored() {
    let h = ok(&format!("// @gallery-id 42\n// @thumbnail x.png\n{MAKER}"));
    assert_eq!(offer(&h), ["groups", "example"]);
}

#[test]
fn an_unknown_offer() {
    assert_eq!(
        errors(&format!("// @offer groups, instance\n{MAKER}")),
        [(
            1,
            19,
            "@offer 'instance': one of library, groups, example, modifier".to_owned()
        )]
    );
}

#[test]
fn an_offer_no_graph_allows() {
    assert_eq!(
        errors(&format!("// @offer modifier\n{MAKER}")),
        [(
            1,
            11,
            "@offer modifier: no geometry graph nobody calls has Geometry as first input and output"
                .to_owned()
        )]
    );
    assert!(errors(&format!("// @offer example\n{MODIFIER}"))[0]
        .2
        .starts_with("@offer example: no geometry graph"));
    assert_eq!(
        errors(&format!("// @offer library\n{MAKER}")),
        [(
            1,
            11,
            "@offer library: there is no @module to install the file as".to_owned()
        )]
    );
}

#[test]
fn a_graph_named_that_is_not_of_the_file() {
    assert_eq!(
        errors(&format!("// @example meadow\n{MAKER}")),
        [(
            1,
            13,
            "@example 'meadow': no graph of that name in this file".to_owned()
        )]
    );
}

#[test]
fn a_graph_named_of_the_wrong_shape() {
    let e = errors(&format!("// @modifier field\n{MAKER}{MODIFIER}"));
    assert_eq!(e.len(), 1);
    assert_eq!((e[0].0, e[0].1), (1, 14));
    assert!(e[0].2.starts_with("@modifier 'field': not a modifier"));
    let e = errors(&format!("// @example half\n{HELPER}{MAKER}"));
    assert!(e[0].2.starts_with(
        "@example 'half': not a geometry graph nobody calls that makes its own geometry"
    ));
    let e = errors(&format!("// @example \"a b\n{MAKER}"));
    assert!(e[0]
        .2
        .contains("a graph's name, quoted, or a bare identifier"));
}

#[test]
fn a_malformed_module_name() {
    assert_eq!(
        errors(&format!("// @module mesh-maps\n{MAKER}")),
        [(
            1,
            12,
            "@module 'mesh-maps': a module is named by an identifier (letters, digits, _), its file being <name>.bn"
                .to_owned()
        )]
    );
    // Said once, not again by an @offer library that needs it.
    assert_eq!(
        errors(&format!("// @module ../evil\n// @offer library\n{MAKER}")).len(),
        1
    );
}

#[test]
fn a_directive_twice_or_empty() {
    assert_eq!(
        errors(&format!("// @title A\n// @title B\n{MAKER}")),
        [(2, 11, "@title is already set on line 1".to_owned())]
    );
    assert_eq!(
        errors(&format!("// @author\n{MAKER}")),
        [(1, 11, "@author needs a value".to_owned())]
    );
}

#[test]
fn an_edition_the_core_does_not_know_is_refused_here_too() {
    let e = header(&format!("// @edition 2028\n{MAKER}"), "f.bn").unwrap_err();
    let found: Vec<_> = e
        .diagnostics
        .iter()
        .map(|d| (d.line, d.col, d.message.as_str()))
        .collect();
    assert_eq!(
        found,
        [(
            1,
            13,
            "@edition '2028': not an edition this reader knows (2026)"
        )]
    );
}

#[test]
fn a_syntax_error_is_the_parser_s() {
    let e = header("// @title x\ngeometry graph (", "f.bn").unwrap_err();
    assert_eq!(e.diagnostics[0].line, 2);
}

#[test]
fn the_drop_example() {
    let src = fs::read_to_string("../examples/drop_example.bn").unwrap();
    let h = header(&src, "drop_example.bn").unwrap();
    assert_eq!(h.module.as_deref(), Some("drop_example"));
    assert_eq!(h.title.as_deref(), Some("Ripples and waves"));
    assert_eq!(h.license.as_deref(), Some("MIT"));
    assert_eq!(h.mesh, "grid");
    assert_eq!(offer(&h), ["library", "groups", "example", "modifier"]);
    assert_eq!(h.example.as_deref(), Some("ripple_field"));
    assert_eq!(h.modifier.as_deref(), Some("wave modifier"));
}

#[test]
fn an_unknown_target_in_the_head() {
    let src =
        "// @target blender, blender-nodes\n\ngeometry graph g() -> Float {\n  return 1.0\n}\n";
    let e = header(src, "f.bn").unwrap_err();
    let d = &e.diagnostics[0];
    assert!(
        d.message
            .starts_with("@target 'blender-nodes': one of blender, "),
        "{}",
        d.message
    );
    assert_eq!((d.line, d.col), (1, 21));
}
