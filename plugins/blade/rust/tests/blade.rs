//! The target `blade`: Blade's Pixel Nodes, which a text of `blender` reaches through its
//! translator and its bridge (spec/blade.md). The same cases as python/tests/test_blade.py.

use std::fs;
use std::sync::Once;

use base_node::{format_source, parse, File};
use base_node_blender::targets::{infer, is_bridge, translate};
use base_node_blender::Issue;

/// Blade's target known to Blender's library, before any check.
fn setup() {
    static ADDED: Once = Once::new();
    ADDED.call_once(|| base_node_blade::add().unwrap());
}

/// The Issues of the text outside a target.
fn check_target(f: &File, target: &str) -> Vec<Issue> {
    setup();
    base_node_blender::check_target(f, target).unwrap()
}

#[test]
fn blade_is_a_target_of_its_own() {
    setup();
    assert!(base_node_blender::target_names().contains(&"blade"));
    for name in ["blade@1.0", "blade gltf"] {
        assert!(base_node_blender::load_target(name).is_err(), "{name}");
    }
    // A name there is already is refused, and so is any target once they are read
    assert!(base_node_blade::add().is_err());
}

#[test]
fn what_inference_holds() {
    setup();
    let inf = infer(&parse(COMPOSITE, "c.bn").unwrap());
    let fits: Vec<(&str, Option<&str>)> = inf
        .fits
        .iter()
        .map(|(t, v)| (t.as_str(), v.as_deref()))
        .collect();
    assert_eq!(fits, [("blade", Some("blender")), ("blender", None)]);
    assert_eq!(
        inf.lines(),
        ["Compatible: blender, blade (translated from blender)"]
    );
}

#[test]
fn the_head_promises_blade() {
    setup();
    let src = "// @target \"blender@5.3  gltf\", blade\n\ngeometry graph g() -> Float {\n  return 1.0\n}\n";
    let h = base_node_blender::header(src, "f.bn").unwrap();
    assert_eq!(h.target, ["blender@5.3 gltf", "blade"]);
}

const PAINT: &str = "compositor graph paint(image: Color) -> Color {
  soft = Kuwahara(image, size: 8.0)
  return Mix(factor: 0.5, a: image, b: Kuwahara(soft))
}
";

const PAINTED: &str = "use blender_interop

pixel graph paint(image: Color) -> Color {
  soft = blender_interop::kuwahara(image, size: 8.0)
  return Mix(factor: 0.5, a: image, b: blender_interop::kuwahara(soft))
}
";

#[test]
fn a_bridge_carries_a_node_blade_has_not() {
    setup();
    let f = parse(PAINT, "p.bn").unwrap();
    assert_eq!(
        infer(&f).fits.get("blade"),
        Some(&Some("blender".to_owned()))
    );
    let text = base_node::format_file(&translate(&f, "blender", "blade").unwrap());
    // The call is the bridge's, the text uses its module once
    assert_eq!(text, PAINTED);
    let out = parse(&text, "p.bn").unwrap();
    assert!(check_target(&out, "blade").is_empty());
    let fits: Vec<(String, Option<String>)> = infer(&out).fits.into_iter().collect();
    assert_eq!(fits, [("blade".to_owned(), None)]);
}

#[test]
fn the_bridge_module_fits_its_target() {
    setup();
    let src = fs::read_to_string("../targets/blade/blender_interop.bn").unwrap();
    assert_eq!(
        base_node_blender::load_target("blade").unwrap().bridges,
        ["blade/blender_interop.bn"]
    );
    assert!(check_target(&parse(&src, "blender_interop.bn").unwrap(), "blade").is_empty());
}

const COMPOSITE: &str = "compositor graph soften(image: Color, size: Float = 4.0) -> Color {
  blurred = Blur(image, size: size)
  return Mix(factor: 0.5, a: image, b: blurred)
}
";

#[test]
fn a_compositor_text_reaches_blade_through_its_translator() {
    setup();
    let f = parse(COMPOSITE, "c.bn").unwrap();
    let inf = infer(&f);
    assert_eq!(inf.fits.get("blender"), Some(&None));
    assert_eq!(inf.fits.get("blade"), Some(&Some("blender".to_owned())));
    let out = translate(&f, "blender", "blade").unwrap();
    assert_eq!(out.graphs[0].kind, "pixel");
    assert!(format_source(&base_node::format_file(&out), "out.bn")
        .unwrap()
        .contains("pixel graph soften"));
    assert_eq!(f.graphs[0].kind, "compositor");
    let lines = inf.lines();
    assert!(lines[0].starts_with("Compatible: blender"), "{lines:?}");
    assert!(
        lines[0].contains("blade (translated from blender)"),
        "{lines:?}"
    );
    assert!(
        !lines.iter().any(|l| l.starts_with("Outside blender ")),
        "{lines:?}"
    );

    let pixelate = parse(
        &COMPOSITE.replace("Blur(image, size: size)", "Pixelate(image)"),
        "k.bn",
    )
    .unwrap();
    assert!(infer(&pixelate).outside.contains_key("blade"));
    let err = translate(&pixelate, "blender", "blade").unwrap_err();
    assert!(err.contains("Pixelate"), "{err}");

    let curves = parse(
        "compositor graph g(image: Color) -> Color {\n  return RGBCurves(image)\n}\n",
        "r.bn",
    )
    .unwrap();
    let out = translate(&curves, "blender", "blade").unwrap();
    let base_node::ast::Stmt::Return(r) = &out.graphs[0].body[0] else {
        panic!()
    };
    let base_node::ast::ReturnValue::Expr(base_node::ast::Expr::Call(c)) = &r.value else {
        panic!()
    };
    assert_eq!(c.name, "Curves");
}

#[test]
fn a_translator_renames_inputs_and_settings() {
    setup();
    let f = parse(
        "compositor graph g(image: Color) -> Color {\n  blurred = Blur(image, size: 4.0)\n  mixed = MixLegacy[MULTIPLY](color1: image, color2: blurred)\n  return ColorRamp[color_ramp: Ramp((0.0, (0.0, 0.0, 0.0, 1.0)), (1.0, (1.0, 1.0, 1.0, 1.0)))](factor: mixed)\n}\n",
        "m.bn",
    )
    .unwrap();
    let out = translate(&f, "blender", "blade").unwrap();
    let text = base_node::format_file(&out);
    assert!(text.contains("Blur(image, radius: 4.0)"), "{text}");
    // A setting by position stays as it is written, one by name takes its new name
    assert!(
        text.contains("Mix[MULTIPLY](a: image, b: blurred)"),
        "{text}"
    );
    assert!(
        text.contains(
            "ColorRamp[ramp: Ramp((0.0, (0.0, 0.0, 0.0, 1.0)), (1.0, (1.0, 1.0, 1.0, 1.0)))]("
        ),
        "{text}"
    );
    assert!(text.contains("image: mixed)"), "{text}");
}

#[test]
fn blades_translator_reaches_blades_nodes() {
    setup();
    let blade = base_node_blender::targets::load_target("blade").unwrap();
    for rename in blade.translators["blender"].nodes.values() {
        let node = rename.node();
        let reached = if node.contains("::") {
            is_bridge(blade, node)
        } else {
            blade.nodes.iter().any(|n| n == node)
        };
        assert!(reached, "{node}");
    }
}
