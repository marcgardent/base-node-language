use std::fs;
use std::path::Path;

use base_node::{format_source, parse, File};
use base_node_blender::targets::{
    check_targets, infer, is_bridge, setting_of, translate, translation_issues, tree_kinds,
};
use base_node_blender::{Issue, UnknownTarget};

/// The Issues of the text outside a target of base-node-blender.
fn check_target(f: &File, target: &str) -> Vec<Issue> {
    base_node_blender::check_target(f, target).unwrap()
}

fn read_stdlib_file(candidates: &[&str]) -> (String, String) {
    let mut last_err = String::new();
    for &name in candidates {
        let relative = format!("../stdlib/{}", name);
        if let Ok(src) = fs::read_to_string(&relative) {
            if let Ok(file) = parse(&src, name) {
                if !file.graphs.is_empty() {
                    return (name.to_string(), src);
                }
            }
            last_err = format!("Candidate '{}' was read but failed parse validation", name);
        }
    }
    panic!(
        "Unable to read valid stdlib file; candidates: {:?}; last error: {}",
        candidates, last_err
    );
}

/// The `.bn` files of `stdlib/`, by name: every module, pro ones included where they are (this
/// repository has the free ones alone).
fn stdlib_names() -> Vec<String> {
    let mut names: Vec<String> = fs::read_dir("../stdlib")
        .unwrap()
        .flatten()
        .map(|e| e.path())
        .filter(|p| p.extension().is_some_and(|x| x == "bn"))
        .map(|p| p.file_stem().unwrap().to_str().unwrap().to_owned())
        .collect();
    names.sort();
    names
}

/// The graphs of `module` Blender built, as export_backend.py wrote them into
/// targets/backends/blender-<x.y>/<module>.json (the newest Blender).
fn graphs_blender_built(module: &str) -> Vec<String> {
    let mut dirs: Vec<_> = fs::read_dir("../targets/backends")
        .unwrap()
        .flatten()
        .map(|e| e.path())
        .filter(|p| p.is_dir())
        .collect();
    dirs.sort_by_key(|p| {
        p.file_name().unwrap().to_str().unwrap()["blender-".len()..]
            .split('.')
            .map(|n| n.parse::<u32>().unwrap())
            .collect::<Vec<_>>()
    });
    let path = dirs.last().unwrap().join(format!("{module}.json"));
    let text = fs::read_to_string(&path).unwrap_or_else(|e| panic!("{}: {e}", path.display()));
    let built: serde_json::Value = serde_json::from_str(&text).unwrap();
    built.as_object().unwrap().keys().cloned().collect()
}

#[test]
fn test_stdlib_conformance() {
    // Every module parses into the graphs Blender built from it, and is in canonical form
    let names = stdlib_names();
    assert!(names.len() >= 11, "{names:?}");
    for name in names {
        let filename = format!("{name}.bn");
        let (_, src) = read_stdlib_file(&[&filename]);

        let file =
            parse(&src, &filename).unwrap_or_else(|e| panic!("Parse error on {}: {}", filename, e));
        let mut graphs: Vec<String> = file.graphs.iter().map(|g| g.name.clone()).collect();
        let mut built = graphs_blender_built(&name);
        graphs.sort();
        built.sort();
        assert_eq!(graphs, built, "Unexpected graphs for {}", filename);

        let formatted = format_source(&src, &filename)
            .unwrap_or_else(|e| panic!("Formatting error on {}: {}", filename, e));

        assert_eq!(formatted, src, "Formatter mismatch on {}", filename);
    }
}

#[test]
fn the_stdlib_keeps_the_targets_it_promises() {
    // A module promises its targets in its head (`// @target`); python/base_node/manifest.py reads
    // the manifest from these heads
    for module in stdlib_names() {
        let filename = format!("{module}.bn");
        let (_, src) = read_stdlib_file(&[&filename]);
        let head = base_node_blender::header(&src, &filename).unwrap();
        let promised: Vec<&str> = head.target.iter().map(String::as_str).collect();
        assert!(!promised.is_empty(), "{module} promises no target");
        assert_eq!(head.module.as_deref(), Some(module.as_str()));
        let file = parse(&src, &filename).unwrap();
        let issues = check_targets(&file, &promised).unwrap();
        assert!(
            issues.is_empty(),
            "{module} is outside {promised:?}: {issues:?}"
        );
    }
}

#[test]
fn the_stdlib_fits_what_python_infers() {
    // The same as python/tests: every module fits blender; a module of math builds in a geometry
    // tree and, in Blender 5.3, in the compositor (it compares, and the compositor of Blender 5.2
    // LTS has no Compare node), curves only in Geometry Nodes
    let fits = |name: &str| -> (Vec<String>, Vec<String>) {
        let (filename, src) = read_stdlib_file(&[&format!("{name}.bn")]);
        let file = parse(&src, &filename).unwrap();
        let inf = infer(&file);
        (
            inf.fits.into_keys().collect(),
            tree_kinds(&file, "blender").unwrap(),
        )
    };
    let blender = |kinds: &[&str]| {
        let kinds = kinds.iter().map(|k| (*k).to_owned()).collect();
        (vec!["blender".to_owned()], kinds)
    };
    assert_eq!(fits("math"), blender(&["geometry"]));
    let (_, math) = read_stdlib_file(&["math.bn"]);
    let math = parse(&math, "math.bn").unwrap();
    assert_eq!(
        tree_kinds(&math, "blender@5.3").unwrap(),
        ["geometry", "compositor"]
    );
    assert_eq!(tree_kinds(&math, "blender@5.2-lts").unwrap(), ["geometry"]);
    assert_eq!(fits("curves2d"), blender(&["geometry"]));
    assert_eq!(fits("mask2d"), blender(&["compositor"]));
}

const SHADER: &str =
    "shader graph \"tint\"(base: Color = (0.8, 0.8, 0.8, 1.0), rough: Float = 0.5) -> Shader {
  return PrincipledBSDF(base_color: base, roughness: rough)
}
";

#[test]
fn a_group_node_with_no_tree_fits_every_tree() {
    // `Group()` is what the reader writes of a Group node whose group is missing (as in Python)
    for (kind, ret) in [
        ("geometry", "Geometry"),
        ("shader", "Shader"),
        ("compositor", "Color"),
    ] {
        let src = format!("{kind} graph g() -> {ret} {{\n  empty = Group()\n  return _\n}}\n");
        let f = parse(&src, "t.bn").unwrap();
        assert_eq!(check_target(&f, "blender"), vec![], "{kind}");
    }
}

#[test]
fn a_principled_bsdf_fits_gltf_a_noise_does_not() {
    let f = parse(SHADER, "s.bn").unwrap();
    assert!(check_target(&f, "blender gltf").is_empty());
    assert!(infer(&f).fits.contains_key("blender gltf"));
    let noisy = parse(
        &SHADER.replace(
            "roughness: rough",
            "roughness: NoiseTexture(scale: 3.0).fac",
        ),
        "s.bn",
    )
    .unwrap();
    let issues = check_target(&noisy, "blender gltf");
    assert_eq!(issues.len(), 2);
    assert_eq!(
        (
            issues[0].what.as_str(),
            issues[0].name.as_str(),
            issues[0].line
        ),
        ("node", "NoiseTexture", 2)
    );
    assert_eq!(
        issues[0].to_string(),
        "Graph 'tint': node 'NoiseTexture' outside target 'blender gltf' (line 2)"
    );
    assert_eq!(
        issues[1].to_string(),
        "Graph 'tint': link 'PrincipledBSDF.roughness ← NoiseTexture' outside target 'blender gltf' (line 2)"
    );
}

const MATERIAL: &str = "shader(material: true) graph Painted() -> (surface: Shader) {
  t = ImageTexture[image: \"Paint\"](vector: UVMap())
  return (surface: PrincipledBSDF(base_color: BASE, normal: NORMAL))
}
";

fn material(base: &str, normal: &str) -> File {
    parse(
        &MATERIAL.replace("BASE", base).replace("NORMAL", normal),
        "m.bn",
    )
    .unwrap()
}

/// The links a target refuses: (name, line).
fn links(f: &File, target: &str) -> Vec<(String, usize)> {
    check_target(f, target)
        .into_iter()
        .filter(|i| i.what == "link")
        .map(|i| (i.name, i.line))
        .collect()
}

fn roughness(value: &str) -> Vec<(String, usize)> {
    let src = format!(
        "shader graph g(rough: Float = 0.5) -> Shader {{\n  t = ImageTexture[image: \"R\"]()\n  return PrincipledBSDF(roughness: {value})\n}}\n"
    );
    links(&parse(&src, "r.bn").unwrap(), "blender gltf")
}

const FLAT: &str = "(0.0, 0.0, 1.0)";

#[test]
fn a_texture_times_a_constant_fits_gltf() {
    let tint = "(0.8, 0.5, 0.5, 1.0)";
    assert!(check_target(&material("t.color", FLAT), "blender gltf").is_empty());
    for base in [
        format!("Mix[RGBA, MULTIPLY](1.0, t.color, {tint})"),
        format!("Mix[RGBA, MULTIPLY](a: {tint}, b: t)"),
        format!(
            "Mix[MULTIPLY](a: {tint}, b: Mix[RGBA, MULTIPLY](a: ColorAttribute().color, b: t.color))"
        ),
    ] {
        assert!(check_target(&material(&base, FLAT), "blender gltf").is_empty(), "{base}");
    }
    assert!(roughness("t.alpha * 0.5").is_empty());
    assert!(roughness("0.5 * SeparateColor(color: t.color).green").is_empty());
    assert!(roughness("Math[MULTIPLY](Value: t.alpha, Value_001: rough)").is_empty());
    assert!(roughness("Math[MULTIPLY](Value: t.alpha)").is_empty());
}

#[test]
fn two_textures_multiplied_do_not_fit_gltf() {
    let f = material(
        "Mix[RGBA, MULTIPLY](a: t.color, b: ImageTexture[image: \"Dirt\"]().color)",
        FLAT,
    );
    assert_eq!(
        links(&f, "blender gltf"),
        [(
            "PrincipledBSDF.base_color ← Mix(ImageTexture, ImageTexture)".to_owned(),
            3
        )]
    );
    assert!(check_target(&f, "blender").is_empty());
    assert!(!links(
        &material(
            "Mix[RGBA, MULTIPLY](0.5, t.color, (0.5, 0.5, 0.5, 1.0))",
            FLAT
        ),
        "blender gltf"
    )
    .is_empty());
    let one = |s: &str| vec![(s.to_owned(), 3)];
    assert_eq!(
        roughness("t.alpha * t.alpha"),
        one("PrincipledBSDF.roughness ← Math(ImageTexture, ImageTexture)")
    );
    assert_eq!(
        roughness("t.alpha + 0.5"),
        one("PrincipledBSDF.roughness ← Math(ImageTexture)")
    );
    // Both sides constant: Blender computes the Math before the exporter reads it
    assert!(roughness("rough * 0.5").is_empty());
}

#[test]
fn a_normal_map_from_an_image_fits_gltf_a_raw_noise_does_not() {
    for normal in [
        "NormalMap(color: t.color, strength: 0.8)",
        "NormalMap(1.0, t.color)",
    ] {
        assert!(
            check_target(&material("t", normal), "blender gltf").is_empty(),
            "{normal}"
        );
    }
    let case = |normal: &str| links(&material("t", normal), "blender gltf");
    assert_eq!(
        case("t.color |> NormalMap(color: t.color)"),
        [("NormalMap.strength ← ImageTexture(UVMap)".to_owned(), 3)]
    );
    assert_eq!(
        case("NoiseTexture(scale: 4.0).color"),
        [("PrincipledBSDF.normal ← NoiseTexture".to_owned(), 3)]
    );
    assert_eq!(
        case("NormalMap(color: NoiseTexture().color)"),
        [("NormalMap.color ← NoiseTexture".to_owned(), 3)]
    );
}

#[test]
fn a_mapping_on_a_texture_s_vector_fits_gltf() {
    let with = |vector: &str| {
        parse(
            &MATERIAL
                .replace("UVMap()", vector)
                .replace("BASE", "t")
                .replace("NORMAL", FLAT),
            "m.bn",
        )
        .unwrap()
    };
    let f = with("Mapping(vector: TextureCoordinate().uv, scale: (2.0, 2.0, 1.0))");
    assert!(check_target(&f, "blender gltf").is_empty());
    assert_eq!(
        links(&with("TextureCoordinate().generated"), "blender gltf"),
        [("ImageTexture.vector ← TextureCoordinate".to_owned(), 2)]
    );
    assert_eq!(
        links(
            &with("Mapping(vector: UVMap(), location: UVMap().uv)"),
            "blender gltf"
        ),
        [("Mapping.location ← UVMap".to_owned(), 2)]
    );
}

#[test]
fn a_formula_an_implicit_input_and_a_zone_count() {
    let cmp = |kind: &str| {
        let src = format!("{kind} graph g(a: Float, b: Float) -> Bool {{\n  return a < b\n}}\n");
        check_target(&parse(&src, "c.bn").unwrap(), "blender")
            .into_iter()
            .map(|i| i.name)
            .collect::<Vec<String>>()
    };
    // A comparison is Compare where the tree has one, else Math: a shader tree has no Compare
    assert!(cmp("shader").is_empty());
    assert!(cmp("geometry").is_empty());
    let node = parse(
        "shader graph g(a: Bool, b: Bool) -> Float {\n  return Compare(a: a, b: b)\n}\n",
        "c.bn",
    )
    .unwrap();
    let names: Vec<String> = check_target(&node, "blender")
        .into_iter()
        .map(|i| i.name)
        .collect();
    assert_eq!(names, ["Compare"]);

    let implicit = parse(
        "geometry graph g(p: Vector = Position()) -> Vector {\n  return p\n}\n",
        "i.bn",
    )
    .unwrap();
    assert!(check_target(&implicit, "blender").is_empty());
    let what: Vec<String> = check_target(&implicit, "blender gltf")
        .into_iter()
        .map(|i| i.what)
        .collect();
    assert_eq!(what, ["kind", "implicit"]);

    let zone = parse(
        "geometry graph g(n: Int) -> Float {\n  s = repeat(n, v: 0.0) -> {\n    return (v: v + 1.0)\n  }\n  return s.v\n}\n",
        "z.bn",
    )
    .unwrap();
    assert!(check_target(&zone, "blender").is_empty());
    assert!(check_target(&zone, "blender gltf")
        .iter()
        .any(|i| i.what == "zone" && i.name == "repeat"));
    // A zone is its kind of tree's: the compositor has no simulation
    let step = |kind: &str| {
        let src = format!("{kind} graph g(x: Float) -> Float {{\n  s = simulate(v: x) -> {{\n    return (v: v)\n  }}\n  return s.v\n}}\n");
        check_target(&parse(&src, "s.bn").unwrap(), "blender")
            .into_iter()
            .map(|i| (i.what, i.name))
            .collect::<Vec<_>>()
    };
    assert!(step("geometry").is_empty());
    assert_eq!(
        step("compositor"),
        [("zone".to_owned(), "simulate".to_owned())]
    );
}

#[test]
fn a_called_graph_brings_its_nodes() {
    // A graph is built in the tree of the graph that calls it, whatever its own kind
    let f = parse(
        "compositor graph a(c: Color) -> Color {\n  return SetAlpha(c, alpha: 1.0)\n}\n\ngeometry graph b(c: Color) -> Color {\n  return a(c)\n}\n\ncompositor graph c(c: Color) -> Color {\n  return a(c)\n}\n\ngeometry graph half(x: Float) -> Float {\n  return x * 0.5\n}\n\ncompositor graph d(c: Color) -> Color {\n  return SetAlpha(c, alpha: half(1.0))\n}\n",
        "a.bn",
    )
    .unwrap();
    let blender = base_node_blender::load_target("blender").unwrap();
    let issues = |at: usize| -> Vec<(String, String)> {
        base_node_blender::targets::graph_issues(&f, at, blender, None)
            .into_iter()
            .map(|i| (i.what, i.name))
            .collect()
    };
    assert!(issues(0).is_empty() && issues(2).is_empty() && issues(4).is_empty());
    assert_eq!(
        issues(1),
        [("graph".to_owned(), "a (node SetAlpha)".to_owned())]
    );
}

// The same cases as python/tests/test_targets.py

#[test]
fn a_stdlib_module_brings_its_nodes() {
    let m = parse("use merge (with_alpha)\n\ngeometry graph g(c: Color) -> Color {\n  return with_alpha(c, 1.0)\n}\n", "m.bn").unwrap();
    assert!(!check_target(&m, "blender").is_empty());
    assert_eq!(tree_kinds(&m, "blender").unwrap(), ["compositor"]);
    // A resolver finds other modules; the stdlib is still found
    let none = |_: &str| None;
    assert!(!base_node_blender::check_target_with(&m, "blender", &none)
        .unwrap()
        .is_empty());
}

#[test]
fn a_stdlib_module_used_whole_brings_its_graphs_only() {
    let used = |module: &str| {
        let src = format!("use {module}\n\ngeometry graph g(c: Color) -> Color {{\n  return SetAlpha(c, alpha: 1.0)\n}}\n");
        let issues = check_target(&parse(&src, "u.bn").unwrap(), "blender");
        issues.iter().map(|i| i.to_string()).collect::<Vec<_>>()
    };
    assert_eq!(
        used("merge"),
        ["Graph 'g': node 'SetAlpha' outside target 'blender' (line 4)"]
    );
    // A module that is not found may hold any graph
    assert!(used("mine").is_empty());
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
    let src = fs::read_to_string("../targets/blade/blender_interop.bn").unwrap();
    assert_eq!(
        base_node_blender::load_target("blade").unwrap().bridges,
        ["blade/blender_interop.bn"]
    );
    assert!(check_target(&parse(&src, "blender_interop.bn").unwrap(), "blade").is_empty());
}

#[test]
fn an_unknown_target_is_an_error() {
    let f = parse(COMPOSITE, "c.bn").unwrap();
    let message = format!(
        "unknown target 'nope'; targets: {}; variants of blender, written after it: cycles, eevee, gltf",
        targets().join(", ")
    );
    let empty = File {
        uses: vec![],
        graphs: vec![],
    };
    let nope = UnknownTarget("nope".to_owned());
    assert_eq!(base_node_blender::load_target("nope").unwrap_err(), nope);
    assert_eq!(
        base_node_blender::check_target(&f, "nope").unwrap_err(),
        nope
    );
    assert_eq!(
        base_node_blender::check_target(&empty, "nope").unwrap_err(),
        nope
    );
    assert_eq!(check_targets(&f, &["blade", "nope"]).unwrap_err(), nope);
    assert_eq!(translation_issues(&f, "blender", "nope").unwrap_err(), nope);
    assert_eq!(nope.to_string(), message);
    assert_eq!(translate(&f, "blender", "nope").unwrap_err(), message);
    assert_eq!(base_node_blender::target_names(), targets());
}

#[test]
fn what_inference_holds() {
    let inf = infer(&parse(COMPOSITE, "c.bn").unwrap());
    let fits: Vec<(&str, Option<&str>)> = inf
        .fits
        .iter()
        .map(|(t, v)| (t.as_str(), v.as_deref()))
        .collect();
    assert_eq!(fits, [("blade", Some("blender")), ("blender", None)]);
    let outside: Vec<&str> = inf.outside.keys().map(String::as_str).collect();
    let others: Vec<&str> = base_node_blender::inferred_names()
        .into_iter()
        // A variant of blender is about shaders: it is not tried for a text that holds none
        .filter(|t| !["blade", "blender"].contains(t) && !t.contains(' '))
        .collect();
    assert_eq!(outside, others);
    assert_eq!(
        inf.graphs,
        [("soften".to_owned(), vec!["blender".to_owned()])]
    );
    assert_eq!(
        inf.lines(),
        ["Compatible: blender, blade (translated from blender)"]
    );
}

/// The targets of `targets/`.
fn targets() -> Vec<&'static str> {
    vec!["blade", "blender", "blender@5.2-lts", "blender@5.3"]
}

#[test]
fn the_targets_are_the_files_of_targets() {
    let mut names: Vec<String> = fs::read_dir("../targets")
        .unwrap()
        .flatten()
        .filter_map(|e| {
            let p = e.path();
            let stem = p.file_stem()?.to_str()?.to_owned();
            p.extension().is_some_and(|x| x == "json").then_some(stem)
        })
        .collect();
    // `blender` has a catalog per version next to it, targets/blender/<x.y>.json: each is a name
    let catalogs: Vec<String> = fs::read_dir("../targets/blender")
        .unwrap()
        .flatten()
        .filter_map(|e| e.path().file_stem()?.to_str().map(str::to_owned))
        .filter(|stem| stem.starts_with(|c: char| c.is_ascii_digit()))
        .map(|version| {
            // An LTS says so in its name
            let lts = if version == "5.2" { "-lts" } else { "" };
            format!("blender@{version}{lts}")
        })
        .collect();
    names.extend(catalogs);
    names.sort();
    assert_eq!(names, base_node_blender::target_names());
}

const COMPOSITE: &str = "compositor graph soften(image: Color, size: Float = 4.0) -> Color {
  blurred = Blur(image, size: size)
  return Mix(factor: 0.5, a: image, b: blurred)
}
";

#[test]
fn a_compositor_text_reaches_blade_through_its_translator() {
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
    let f = parse(
        "compositor graph g(image: Color) -> Color {\n  blurred = Blur(image, size: 4.0)\n  mixed = MixLegacy[MULTIPLY](color1: image, color2: blurred)\n  return ColorRamp[color_ramp: Ramp((0.0, (0.0, 0.0, 0.0, 1.0)), (1.0, (1.0, 1.0, 1.0, 1.0)))](factor: mixed)\n}\n",
        "m.bn",
    )
    .unwrap();
    let out = translate(&f, "blender", "blade").unwrap();
    let text = base_node::format_file(&out);
    assert!(text.contains("Blur(image, radius: 4.0)"), "{text}");
    // A setting by position stays as it is written, one by name takes its new name
    assert!(text.contains("Mix[MULTIPLY](a: image, b: blurred)"), "{text}");
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

#[test]
fn test_versioning_and_manifest() {
    // The core's constants are checked with the core (rust/tests/conformance.rs)
    assert_eq!(base_node::VERSION, base_node::STDLIB_VERSION);

    let manifest_path = Path::new("../stdlib/manifest.json");
    let manifest_content =
        fs::read_to_string(manifest_path).expect("Failed to read stdlib/manifest.json");

    let v: serde_json::Value =
        serde_json::from_str(&manifest_content).expect("Invalid JSON in manifest.json");
    assert_eq!(v["stdlib_version"], base_node::STDLIB_VERSION);
    assert_eq!(v["edition"], "2026");

    // The modules say their entries in their heads: the file holds what is the library's
    assert!(v.get("modules").is_none());
    let names = stdlib_names();
    for module in ["math", "sdf2d", "curves2d", "patterns2d", "mask2d"] {
        assert!(names.iter().any(|n| n == module), "{module}");
    }
}

#[test]
fn test_a_call_on_a_closure_is_evaluate_closure() {
    // The asset evaluates a closure it holds in a variable: Evaluate Closure, a Geometry Nodes node
    let path =
        "../base-node-for-blender/tests/fixtures/everyday_geometry_nodes/bevel_mesh_basic.bn";
    let src = std::fs::read_to_string(path).expect("fixture");
    let file = parse(&src, "bevel_mesh_basic.bn").expect("parses");
    let issues = check_target(&file, "blender");
    assert!(
        issues.is_empty(),
        "{:?}",
        issues.iter().map(|i| i.to_string()).collect::<Vec<_>>()
    );
    assert_eq!(tree_kinds(&file, "blender").unwrap(), ["geometry"]);
}

/// The cases the Python tests and Blender's exporter read too (test_gltf_export.py).
fn gltf_cases() -> Vec<serde_json::Value> {
    let corpus: serde_json::Value =
        serde_json::from_str(&fs::read_to_string("../conformance/gltf-cases.json").unwrap())
            .unwrap();
    corpus["cases"].as_array().unwrap().clone()
}

/// The text of a case of conformance/gltf-cases.json.
fn gltf_case(case: &serde_json::Value) -> String {
    let name = case["name"].as_str().unwrap();
    if let Some(text) = case["text"].as_str() {
        return text.replace("NAME", name);
    }
    let body: String = case["body"]
        .as_str()
        .unwrap()
        .split('\n')
        .map(|l| format!("  {l}\n"))
        .collect();
    let outputs = case["outputs"].as_str().unwrap_or("surface: Shader");
    format!("shader(material: true) graph {name}() -> ({outputs}) {{\n{body}}}\n")
}

#[test]
fn what_the_gltf_exporter_reads() {
    for case in gltf_cases() {
        let f = parse(&gltf_case(&case), "case.bn").unwrap();
        let got: Vec<String> = check_target(&f, "blender gltf")
            .into_iter()
            .map(|i| i.name)
            .collect();
        let want: Vec<String> = case["issues"]
            .as_array()
            .unwrap()
            .iter()
            .map(|i| i.as_str().unwrap().to_owned())
            .collect();
        assert_eq!(got, want, "{}", case["name"]);
    }
}

#[test]
fn a_setting_by_position_goes_to_the_first_enum_setting_that_holds_it() {
    assert_eq!(setting_of("shader", "Math", "MULTIPLY"), Some("operation"));
    assert_eq!(setting_of("geometry", "Compare", "INT"), Some("data_type"));
    assert_eq!(
        setting_of("geometry", "Compare", "EQUAL"),
        Some("operation")
    );
    // X is in `axis` and `pivot_axis`: the first, in Blender's order
    assert_eq!(
        setting_of("geometry", "AlignEulerToVector", "X"),
        Some("axis")
    );
    assert_eq!(setting_of("shader", "Math", "NOPE"), None);
    assert_eq!(setting_of("shader", "Nope", "ADD"), None);
}

#[test]
fn a_rule_reads_a_setting_by_position_or_by_name_never_in_parentheses() {
    let texture = |call: &str| {
        let src = format!(
            "shader(material: true) graph m() -> (surface: Shader) {{\n  t = {call}\n  return (surface: PrincipledBSDF(base_color: t))\n}}\n"
        );
        let f = parse(&src, "m.bn").unwrap();
        check_target(&f, "blender gltf")
            .into_iter()
            .map(|i| i.name)
            .collect::<Vec<_>>()
    };
    let clip = vec!["ImageTexture.extension ← CLIP".to_owned()];
    assert_eq!(
        texture("ImageTexture[CLIP, image: \"Paint\"](vector: UVMap())"),
        clip
    );
    assert_eq!(
        texture("ImageTexture[image: \"Paint\", extension: CLIP](vector: UVMap())"),
        clip
    );
    // No image in the brackets: no texture
    assert_eq!(
        texture("ImageTexture[MIRROR](vector: UVMap())"),
        vec!["ImageTexture.image ← none".to_owned()]
    );
}

#[test]
fn a_ramp_is_the_value_of_a_property_not_a_node() {
    let f = parse(
        "shader graph g(f: Float) -> Color {\n  return ColorRamp[color_ramp: Ramp((0.0, (0.0, 0.0, 0.0, 1.0)), (1.0, (1.0, 1.0, 1.0, 1.0)))](factor: f).color\n}\n",
        "g.bn",
    )
    .unwrap();
    assert!(check_target(&f, "blender").is_empty());
}

#[test]
fn a_call_to_a_graph_is_read_through_at_its_line() {
    let case = gltf_cases()
        .into_iter()
        .find(|c| c["name"] == "group_shader_refused")
        .unwrap();
    let f = parse(&gltf_case(&case), "case.bn").unwrap();
    let got: Vec<(String, String, usize)> = check_target(&f, "blender gltf")
        .into_iter()
        .map(|i| (i.graph, i.what, i.line))
        .collect();
    assert_eq!(
        got,
        [("group_shader_refused".to_owned(), "link".to_owned(), 7)]
    );
}

// ---- blender, by version (the same cases as python/tests/test_targets.py) ----

const VARIANTS: &str = "; variants of blender, written after it: cycles, eevee, gltf";

fn refused(name: &str) -> String {
    base_node_blender::load_target(name)
        .unwrap_err()
        .to_string()
}

#[test]
fn a_version_a_bare_name_an_alias_and_a_variant() {
    use base_node_blender::{load_target, promise_names, promise_refusal, variant_names};
    assert_eq!(variant_names(), ["cycles", "eevee", "gltf"]);
    let blender: Vec<&str> = promise_names()
        .into_iter()
        .filter(|n| n.starts_with("blender"))
        .collect();
    assert_eq!(
        blender,
        [
            "blender",
            "blender cycles",
            "blender eevee",
            "blender gltf",
            "blender@5.2-lts",
            "blender@5.2-lts cycles",
            "blender@5.2-lts eevee",
            "blender@5.2-lts gltf",
            "blender@5.3",
            "blender@5.3 cycles",
            "blender@5.3 eevee",
            "blender@5.3 gltf"
        ]
    );
    let one = load_target("blender@5.3").unwrap();
    assert_eq!(one.kinds, ["geometry", "shader", "compositor"]);
    assert!(one.members.is_empty());
    assert!(one.trees["compositor"].nodes.contains(&"Blur".to_owned()));
    assert!(!one.trees["geometry"].nodes.contains(&"Blur".to_owned()));
    // The bare name is every version promised; an alias the version it names today
    let all = load_target("blender").unwrap();
    let members: Vec<&str> = all.members.iter().map(|m| m.name.as_str()).collect();
    assert_eq!(members, ["blender@5.2-lts", "blender@5.3"]);
    let lts = load_target("blender@5.2-lts").unwrap();
    assert_eq!(load_target("blender@lts").unwrap().name, "blender@5.2-lts");
    assert_eq!(
        load_target("blender@lts eevee").unwrap().name,
        "blender@5.2-lts eevee"
    );
    // The LTS is the older catalog: the compositor of Blender 5.2 has no Compare node
    assert!(one.trees["compositor"]
        .nodes
        .contains(&"Compare".to_owned()));
    assert!(!lts.trees["compositor"]
        .nodes
        .contains(&"Compare".to_owned()));
    assert_eq!(load_target("blender@latest").unwrap().name, "blender@5.3");
    assert_eq!(
        load_target("blender@latest gltf").unwrap().name,
        "blender@5.3 gltf"
    );
    let gltf = load_target("blender@5.3 gltf").unwrap();
    assert_eq!(gltf.kinds, ["shader"]);
    assert!(gltf.nodes.contains(&"PrincipledBSDF".to_owned()) && !gltf.rules.is_empty());
    assert_eq!(load_target("blender gltf").unwrap().members[1], *gltf);
    for name in promise_names() {
        assert_eq!(load_target(name).unwrap().name, name);
        assert_eq!(promise_refusal(name), None);
    }
}

#[test]
fn a_version_without_a_catalog_says_so() {
    let no = "no catalog for Blender 4.5 in this version of Base Node (catalogs: 5.2, 5.3)";
    for name in [
        "blender@4.5-lts",
        "blender@4.5",
        "blender@4.5-lts gltf",
        "blender@4.5 eevee",
    ] {
        assert_eq!(refused(name), format!("target '{name}': {no}"));
    }
    assert_eq!(
        base_node_blender::promise_refusal("blender@4.5-lts").as_deref(),
        Some(no)
    );
    assert_eq!(
        refused("blender@5.2"),
        format!(
            "unknown target 'blender@5.2'; targets: {}{VARIANTS}; Blender 5.2 is an LTS: write 'blender@5.2-lts'",
            targets().join(", ")
        )
    );
    assert_eq!(
        refused("blender@5.3-lts"),
        format!(
            "unknown target 'blender@5.3-lts'; targets: {}{VARIANTS}; Blender 5.3 is not an LTS: write 'blender@5.3'",
            targets().join(", ")
        )
    );
    for name in [
        "blender@",
        "blender@5",
        "blender@x",
        "blender nope",
        "blender  gltf",
        "blender@5.3 gltf eevee",
        "blade@1.0",
        "blade gltf",
    ] {
        assert!(refused(name).starts_with("unknown target"), "{name}");
    }
}

#[test]
fn an_alias_is_refused_in_the_head_of_a_text() {
    let text = |targets: &str| {
        format!("// @target {targets}\n\nshader graph g() -> Float {{\n  return 1.0\n}}\n")
    };
    let head =
        base_node_blender::header(&text("blender@5.3 gltf,  blender   eevee"), "t.bn").unwrap();
    assert_eq!(head.target, ["blender@5.3 gltf", "blender eevee"]);
    let said = |targets: &str| {
        base_node_blender::header(&text(targets), "t.bn")
            .unwrap_err()
            .to_string()
    };
    assert_eq!(
        said("blender, blender@latest gltf"),
        "t.bn:1:21: @target 'blender@latest gltf': an alias, for a command line: the version it names changes \
         with each release of Blender, and the promise of the text would change with it: write the version, \
         'blender@5.3 gltf'"
    );
    assert!(said("blender@lts").contains("an alias, for a command line"));
    assert_eq!(
        said("blender@4.5-lts"),
        "t.bn:1:12: @target 'blender@4.5-lts': no catalog for Blender 4.5 in this version of Base Node (catalogs: 5.2, 5.3)"
    );
    let lts = base_node_blender::header(&text("blender@5.2-lts"), "t.bn").unwrap();
    assert_eq!(lts.target, ["blender@5.2-lts"]);
}

#[test]
fn an_engine_variant_takes_shader_graphs_and_the_graphs_they_call() {
    let toon = parse(
        "shader graph g() -> Shader {\n  return ToonBSDF()\n}\n",
        "t.bn",
    )
    .unwrap();
    assert!(check_target(&toon, "blender").is_empty());
    assert!(check_target(&toon, "blender cycles").is_empty());
    let said: Vec<String> = check_target(&toon, "blender eevee")
        .iter()
        .map(|i| i.to_string())
        .collect();
    assert_eq!(
        said,
        ["Graph 'g': node 'ToonBSDF' outside target 'blender eevee' (line 2)"]
    );
    let rgb = parse(
        "shader graph g(s: Shader) -> Color {\n  return ShaderToRGB(shader: s).color\n}\n",
        "r.bn",
    )
    .unwrap();
    assert!(check_target(&rgb, "blender eevee").is_empty());
    let names: Vec<String> = check_target(&rgb, "blender@5.3 cycles")
        .into_iter()
        .map(|i| i.name)
        .collect();
    assert_eq!(names, ["ShaderToRGB"]);
    // A graph of another kind is no engine's; one a shader graph calls is built in its tree
    let math = parse(
        "geometry graph half(x: Float) -> Float {\n  return x * 0.5\n}\n\nshader graph g(x: Float) -> Shader {\n  return Emission(strength: half(x))\n}\n",
        "m.bn",
    )
    .unwrap();
    let outside: Vec<(String, String, String)> = check_target(&math, "blender eevee")
        .into_iter()
        .map(|i| (i.graph, i.what, i.name))
        .collect();
    assert_eq!(
        outside,
        [("half".to_owned(), "kind".to_owned(), "geometry".to_owned())]
    );
    let eevee = base_node_blender::load_target("blender eevee").unwrap();
    assert!(eevee.experimental);
    assert!(base_node_blender::targets::graph_issues(&math, 1, eevee, None).is_empty());
    let inf = infer(&toon);
    assert_eq!(inf.fits.get("blender cycles"), Some(&None));
    assert!(inf.outside.contains_key("blender eevee"));
}

#[test]
fn blender_takes_the_graphs_of_each_kind_of_tree() {
    let f = parse(
        "geometry graph lift(mesh: Geometry) -> Geometry {\n  return SetPosition(mesh, offset: CombineXYZ(z: 1.0))\n}\n\nshader graph tint(c: Color) -> Shader {\n  return Emission(color: c)\n}\n\ncompositor graph soft(image: Color) -> Color {\n  return Blur(image)\n}\n",
        "k.bn",
    )
    .unwrap();
    let inf = infer(&f);
    let fits: Vec<&str> = inf.fits.keys().map(String::as_str).collect();
    assert_eq!(fits, ["blender"]);
    assert_eq!(
        inf.graphs[0],
        ("lift".to_owned(), vec!["blender".to_owned()])
    );
    assert_eq!(
        inf.graphs[2],
        ("soft".to_owned(), vec!["blender".to_owned()])
    );
    assert_eq!(
        inf.graphs[1].1[..4],
        ["blender", "blender cycles", "blender eevee", "blender gltf"]
    );
    // Each against the nodes of its kind: a geometry node in a shader graph is outside
    let wrong = parse(
        "shader graph g(mesh: Geometry) -> Geometry {\n  return SetPosition(mesh)\n}\n",
        "w.bn",
    )
    .unwrap();
    let outside: Vec<(String, String)> = check_target(&wrong, "blender")
        .into_iter()
        .map(|i| (i.what, i.name))
        .collect();
    assert_eq!(
        outside,
        [
            ("type".to_owned(), "Geometry".to_owned()),
            ("type".to_owned(), "Geometry".to_owned()),
            ("node".to_owned(), "SetPosition".to_owned())
        ]
    );
    // A kind that is no tree of Blender's
    let pixel = parse(
        "pixel graph g(x: Float) -> Float {\n  return x * 2.0\n}\n",
        "p.bn",
    )
    .unwrap();
    let outside: Vec<(String, String)> = check_target(&pixel, "blender")
        .into_iter()
        .map(|i| (i.what, i.name))
        .collect();
    assert_eq!(outside, [("kind".to_owned(), "pixel".to_owned())]);
}
