use std::fs;
use std::path::Path;

use base_node::targets::{check_targets, infer, is_bridge, translate, translation_issues};
use base_node::{format_source, parse, File, Issue, UnknownTarget};

/// The Issues of the text outside a target of base-node.
fn check_target(f: &File, target: &str) -> Vec<Issue> {
    base_node::check_target(f, target).unwrap()
}

fn read_stdlib_file(candidates: &[&str]) -> (String, String) {
    let mut last_err = String::new();
    for &name in candidates {
        let relative = format!("../stdlib/{}", name);
        let content = fs::read_to_string(&relative).or_else(|_| {
            fs::read_to_string(format!(
                "/home/marcgardent/base-node-library/stdlib/{}",
                name
            ))
        });
        if let Ok(src) = content {
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

#[test]
fn test_stdlib_conformance() {
    let files: &[(&[&str], usize)] = &[
        (&["math.bn"], 47),
        (&["sdf2d.bn"], 17),
        (&["curves2d.bn"], 7),
        (&["patterns2d.bn"], 5),
        (&["planar2d.bn"], 4),
        (&["fillet2d.bn"], 4),
        (&["mask2d.bn"], 9),
        (&["merge.bn"], 32),
        (&["grade.bn"], 20),
        (&["stmap.bn"], 12),
        (&["qc.bn"], 24),
    ];

    for (candidates, expected_graphs) in files {
        let (filename, src) = read_stdlib_file(candidates);

        let file =
            parse(&src, &filename).unwrap_or_else(|e| panic!("Parse error on {}: {}", filename, e));
        assert_eq!(
            file.graphs.len(),
            *expected_graphs,
            "Unexpected graph count for {}",
            filename
        );

        let formatted = format_source(&src, &filename)
            .unwrap_or_else(|e| panic!("Formatting error on {}: {}", filename, e));

        assert_eq!(formatted, src, "Formatter mismatch on {}", filename);
    }
}

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

#[test]
fn the_stdlib_keeps_the_targets_it_promises() {
    let manifest: serde_json::Value =
        serde_json::from_str(&fs::read_to_string("../stdlib/manifest.json").unwrap()).unwrap();
    for (module, entry) in manifest["modules"].as_object().unwrap() {
        let promised: Vec<&str> = entry["targets"]
            .as_array()
            .unwrap()
            .iter()
            .map(|t| t.as_str().unwrap())
            .collect();
        assert!(!promised.is_empty(), "{module} promises no target");
        let (filename, src) = read_stdlib_file(&[entry["file"].as_str().unwrap()]);
        let file = parse(&src, &filename).unwrap();
        let issues = check_targets(&file, &promised).unwrap();
        assert!(
            issues.is_empty(),
            "{module} is outside {promised:?}: {issues:?}"
        );
        let head = base_node::header(&src, &filename).unwrap();
        assert_eq!(head.target, promised, "{module}: its head and the manifest");
    }
}

#[test]
fn the_stdlib_fits_what_python_infers() {
    // The same as python/tests: a module of math fits the compositor, curves only Geometry Nodes
    // (on any object, Grease Pencil too)
    let fits = |name: &str| -> Vec<String> {
        let (filename, src) = read_stdlib_file(&[&format!("{name}.bn")]);
        let inf = infer(&parse(&src, &filename).unwrap());
        inf.fits.into_keys().collect()
    };
    assert_eq!(
        fits("math"),
        ["blender-compositor", "blender-geometry", "blender-gp"]
    );
    assert_eq!(fits("curves2d"), ["blender-geometry", "blender-gp"]);
    assert_eq!(fits("mask2d"), ["blender-compositor"]);
}

const SHADER: &str =
    "shader graph \"tint\"(base: Color = (0.8, 0.8, 0.8, 1.0), rough: Float = 0.5) -> Shader {
  return PrincipledBSDF(base_color: base, roughness: rough)
}
";

#[test]
fn a_principled_bsdf_fits_gltf_a_noise_does_not() {
    let f = parse(SHADER, "s.bn").unwrap();
    assert!(check_target(&f, "gltf").is_empty());
    assert!(infer(&f).fits.contains_key("gltf"));
    let noisy = parse(
        &SHADER.replace(
            "roughness: rough",
            "roughness: NoiseTexture(scale: 3.0).fac",
        ),
        "s.bn",
    )
    .unwrap();
    let issues = check_target(&noisy, "gltf");
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
        "Graph 'tint': node 'NoiseTexture' outside target 'gltf' (line 2)"
    );
    assert_eq!(
        issues[1].to_string(),
        "Graph 'tint': link 'PrincipledBSDF.roughness ← NoiseTexture' outside target 'gltf' (line 2)"
    );
}

const MATERIAL: &str = "shader(material: true) graph Painted() -> (surface: Shader) {
  t = ImageTexture(vector: UVMap(), image: \"Paint\")
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
        "shader graph g(rough: Float = 0.5) -> Shader {{\n  t = ImageTexture(image: \"R\")\n  return PrincipledBSDF(roughness: {value})\n}}\n"
    );
    links(&parse(&src, "r.bn").unwrap(), "gltf")
}

const FLAT: &str = "(0.0, 0.0, 1.0)";

#[test]
fn a_texture_times_a_constant_fits_gltf() {
    let tint = "(0.8, 0.5, 0.5, 1.0)";
    assert!(check_target(&material("t.color", FLAT), "gltf").is_empty());
    for base in [
        format!("Mix(1.0, t.color, {tint}, blend_type: MULTIPLY, data_type: RGBA)"),
        format!("Mix(a: {tint}, b: t, blend_type: MULTIPLY, data_type: RGBA)"),
        format!(
            "Mix(a: {tint}, b: Mix(a: ColorAttribute().color, b: t.color, blend_type: MULTIPLY, data_type: RGBA), blend_type: MULTIPLY)"
        ),
    ] {
        assert!(check_target(&material(&base, FLAT), "gltf").is_empty(), "{base}");
    }
    assert!(roughness("t.alpha * 0.5").is_empty());
    assert!(roughness("0.5 * SeparateColor(t.color).green").is_empty());
    assert!(roughness("Math(t.alpha, rough, operation: MULTIPLY)").is_empty());
    assert!(roughness("Math(t.alpha, operation: MULTIPLY)").is_empty());
}

#[test]
fn two_textures_multiplied_do_not_fit_gltf() {
    let f = material(
        "Mix(a: t.color, b: ImageTexture(image: \"Dirt\").color, blend_type: MULTIPLY, data_type: RGBA)",
        FLAT,
    );
    assert_eq!(
        links(&f, "gltf"),
        [(
            "PrincipledBSDF.base_color ← Mix(ImageTexture, ImageTexture)".to_owned(),
            3
        )]
    );
    assert!(check_target(&f, "blender-shader").is_empty());
    assert!(!links(
        &material(
            "Mix(0.5, t.color, (0.5, 0.5, 0.5, 1.0), blend_type: MULTIPLY, data_type: RGBA)",
            FLAT
        ),
        "gltf"
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
            check_target(&material("t", normal), "gltf").is_empty(),
            "{normal}"
        );
    }
    let case = |normal: &str| links(&material("t", normal), "gltf");
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
    assert!(check_target(&f, "gltf").is_empty());
    assert_eq!(
        links(&with("TextureCoordinate().generated"), "gltf"),
        [("ImageTexture.vector ← TextureCoordinate".to_owned(), 2)]
    );
    assert_eq!(
        links(
            &with("Mapping(vector: UVMap(), location: UVMap().uv)"),
            "gltf"
        ),
        [("Mapping.location ← UVMap".to_owned(), 2)]
    );
}

#[test]
fn a_formula_an_implicit_input_and_a_zone_count() {
    let cmp = parse(
        "shader graph g(a: Float, b: Float) -> Bool {\n  return a < b\n}\n",
        "c.bn",
    )
    .unwrap();
    let names: Vec<String> = check_target(&cmp, "blender-shader")
        .into_iter()
        .map(|i| i.name)
        .collect();
    assert_eq!(names, ["Compare"]);
    assert!(check_target(&cmp, "blender-geometry").is_empty());

    let implicit = parse(
        "geometry graph g(p: Vector = Position()) -> Vector {\n  return p\n}\n",
        "i.bn",
    )
    .unwrap();
    assert!(check_target(&implicit, "blender-compositor").is_empty());
    let what: Vec<String> = check_target(&implicit, "gltf")
        .into_iter()
        .map(|i| i.what)
        .collect();
    assert_eq!(what, ["kind", "implicit"]);

    let zone = parse(
        "geometry graph g(n: Int) -> Float {\n  s = repeat(n, v: 0.0) {\n    return (v: v + 1.0)\n  }\n  return s.v\n}\n",
        "z.bn",
    )
    .unwrap();
    assert!(check_target(&zone, "blender-geometry").is_empty());
    assert!(check_target(&zone, "gltf")
        .iter()
        .any(|i| i.what == "zone" && i.name == "repeat"));
}

#[test]
fn a_called_graph_brings_its_nodes() {
    let f = parse(
        "compositor graph a(c: Color) -> Color {\n  return SetAlpha(c, alpha: 1.0)\n}\n\ngeometry graph b(c: Color) -> Color {\n  return a(c)\n}\n",
        "a.bn",
    )
    .unwrap();
    assert!(check_target(&f, "blender-compositor").is_empty());
    let geo = base_node::load_target("blender-geometry").unwrap();
    let issues = base_node::targets::graph_issues(&f, 1, geo, None);
    let what: Vec<&str> = issues.iter().map(|i| i.what.as_str()).collect();
    assert_eq!(what, ["graph"]);
}

// The same cases as python/tests/test_targets.py

#[test]
fn a_stdlib_module_brings_its_nodes() {
    let m = parse("use merge (with_alpha)\n\ngeometry graph g(c: Color) -> Color {\n  return with_alpha(c, 1.0)\n}\n", "m.bn").unwrap();
    assert!(check_target(&m, "blender-compositor").is_empty());
    assert!(!check_target(&m, "blender-geometry").is_empty());
    // A resolver finds other modules; the stdlib is still found
    let none = |_: &str| None;
    assert!(!base_node::check_target_with(&m, "blender-geometry", &none)
        .unwrap()
        .is_empty());
}

#[test]
fn a_stdlib_module_used_whole_brings_its_graphs_only() {
    let used = |module: &str| {
        let src = format!("use {module}\n\ngeometry graph g(c: Color) -> Color {{\n  return SetAlpha(c, alpha: 1.0)\n}}\n");
        let issues = check_target(&parse(&src, "u.bn").unwrap(), "blender-geometry");
        issues.iter().map(|i| i.to_string()).collect::<Vec<_>>()
    };
    assert_eq!(
        used("merge"),
        ["Graph 'g': node 'SetAlpha' outside target 'blender-geometry' (line 4)"]
    );
    // A module that is not found may hold any graph
    assert!(used("mine").is_empty());
}

const PAINT: &str = "compositor graph paint(image: Color) -> Color {
  soft = Kuwahara(image, size: 8.0)
  return Mix(image, Kuwahara(soft), factor: 0.5)
}
";

const PAINTED: &str = "use blender_interop

pixel graph paint(image: Color) -> Color {
  soft = blender_interop::kuwahara(image, size: 8.0)
  return Mix(image, blender_interop::kuwahara(soft), factor: 0.5)
}
";

#[test]
fn a_bridge_carries_a_node_blade_has_not() {
    let f = parse(PAINT, "p.bn").unwrap();
    assert_eq!(
        infer(&f).fits.get("blade"),
        Some(&Some("blender-compositor".to_owned()))
    );
    let text = base_node::format_file(&translate(&f, "blender-compositor", "blade").unwrap());
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
        base_node::load_target("blade").unwrap().bridges,
        ["blade/blender_interop.bn"]
    );
    assert!(check_target(&parse(&src, "blender_interop.bn").unwrap(), "blade").is_empty());
}

#[test]
fn an_unknown_target_is_an_error() {
    let f = parse(COMPOSITE, "c.bn").unwrap();
    let message = "unknown target 'nope'; targets: blade, blender-compositor, blender-geometry, blender-gp, blender-shader, gltf";
    let empty = File {
        uses: vec![],
        graphs: vec![],
    };
    let nope = UnknownTarget("nope".to_owned());
    assert_eq!(base_node::load_target("nope").unwrap_err(), nope);
    assert_eq!(base_node::check_target(&f, "nope").unwrap_err(), nope);
    assert_eq!(base_node::check_target(&empty, "nope").unwrap_err(), nope);
    assert_eq!(check_targets(&f, &["blade", "nope"]).unwrap_err(), nope);
    assert_eq!(
        translation_issues(&f, "blender-compositor", "nope").unwrap_err(),
        nope
    );
    assert_eq!(nope.to_string(), message);
    assert_eq!(
        translate(&f, "blender-compositor", "nope").unwrap_err(),
        message
    );
}

#[test]
fn what_inference_holds() {
    let inf = infer(&parse(COMPOSITE, "c.bn").unwrap());
    let fits: Vec<(&str, Option<&str>)> = inf
        .fits
        .iter()
        .map(|(t, v)| (t.as_str(), v.as_deref()))
        .collect();
    assert_eq!(
        fits,
        [
            ("blade", Some("blender-compositor")),
            ("blender-compositor", None)
        ]
    );
    let outside: Vec<&str> = inf.outside.keys().map(String::as_str).collect();
    assert_eq!(
        outside,
        ["blender-geometry", "blender-gp", "blender-shader", "gltf"]
    );
    assert_eq!(
        inf.graphs,
        [("soften".to_owned(), vec!["blender-compositor".to_owned()])]
    );
    assert_eq!(
        inf.lines(),
        [
            "Compatible: blender-compositor, blade (translated from blender-compositor)",
            "Outside blender-geometry: node Blur (line 2)",
            "Outside blender-gp: node Blur (line 2)",
            "Outside blender-shader: node Blur (line 2)",
            "Outside gltf: kind compositor (line 1) and 1 more",
        ]
    );
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
    names.sort();
    assert_eq!(names, base_node::target_names());
}

const COMPOSITE: &str = "compositor graph soften(image: Color, size: Float = 4.0) -> Color {
  blurred = Blur(image, size: size)
  return Mix(image, blurred, factor: 0.5)
}
";

#[test]
fn a_compositor_text_reaches_blade_through_its_translator() {
    let f = parse(COMPOSITE, "c.bn").unwrap();
    let inf = infer(&f);
    assert_eq!(inf.fits.get("blender-compositor"), Some(&None));
    assert_eq!(
        inf.fits.get("blade"),
        Some(&Some("blender-compositor".to_owned()))
    );
    let out = translate(&f, "blender-compositor", "blade").unwrap();
    assert_eq!(out.graphs[0].kind, "pixel");
    assert!(format_source(&base_node::format_file(&out), "out.bn")
        .unwrap()
        .contains("pixel graph soften"));
    assert_eq!(f.graphs[0].kind, "compositor");
    let lines = inf.lines();
    assert!(
        lines[0].starts_with("Compatible: blender-compositor"),
        "{lines:?}"
    );
    assert!(
        lines[0].contains("blade (translated from blender-compositor)"),
        "{lines:?}"
    );
    assert!(
        lines
            .iter()
            .any(|l| l.starts_with("Outside gltf: kind compositor")),
        "{lines:?}"
    );

    let pixelate = parse(
        &COMPOSITE.replace("Blur(image, size: size)", "Pixelate(image)"),
        "k.bn",
    )
    .unwrap();
    assert!(infer(&pixelate).outside.contains_key("blade"));
    let err = translate(&pixelate, "blender-compositor", "blade").unwrap_err();
    assert!(err.contains("Pixelate"), "{err}");

    let curves = parse(
        "compositor graph g(image: Color) -> Color {\n  return RGBCurves(image)\n}\n",
        "r.bn",
    )
    .unwrap();
    let out = translate(&curves, "blender-compositor", "blade").unwrap();
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
        "compositor graph g(image: Color) -> Color {\n  blurred = Blur(image, size: 4.0)\n  return MixLegacy(image, color2: blurred, blend_type: MULTIPLY)\n}\n",
        "m.bn",
    )
    .unwrap();
    let out = translate(&f, "blender-compositor", "blade").unwrap();
    let text = base_node::format_file(&out);
    assert!(text.contains("Blur(image, radius: 4.0)"), "{text}");
    assert!(
        text.contains("Mix(image, b: blurred, blend: MULTIPLY)"),
        "{text}"
    );
}

#[test]
fn blades_translator_reaches_blades_nodes() {
    let blade = base_node::targets::load_target("blade").unwrap();
    for rename in blade.translators["blender-compositor"].nodes.values() {
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
    assert_eq!(base_node::VERSION, "0.12.0");
    assert_eq!(base_node::EDITION, "2026");
    assert_eq!(base_node::STDLIB_VERSION, "0.12.0");

    let manifest_path = Path::new("../stdlib/manifest.json");
    let manifest_content = fs::read_to_string(manifest_path)
        .or_else(|_| fs::read_to_string("/home/marcgardent/base-node-library/stdlib/manifest.json"))
        .expect("Failed to read stdlib/manifest.json");

    let v: serde_json::Value =
        serde_json::from_str(&manifest_content).expect("Invalid JSON in manifest.json");
    assert_eq!(v["stdlib_version"], "0.12.0");
    assert_eq!(v["edition"], "2026");

    let modules = v["modules"].as_object().expect("Expected modules object");
    assert!(modules.contains_key("math"));
    assert!(modules.contains_key("sdf2d"));
    assert!(modules.contains_key("curves2d"));
    assert!(modules.contains_key("patterns2d"));
    assert!(modules.contains_key("mask2d"));
}

#[test]
fn test_a_call_on_a_closure_is_evaluate_closure() {
    // The asset evaluates a closure it holds in a variable: Evaluate Closure, a Geometry Nodes node
    let path =
        "../base-node-for-blender/tests/fixtures/everyday_geometry_nodes/bevel_mesh_basic.bn";
    let src = std::fs::read_to_string(path).expect("fixture");
    let file = parse(&src, "bevel_mesh_basic.bn").expect("parses");
    let issues = check_target(&file, "blender-geometry");
    assert!(
        issues.is_empty(),
        "{:?}",
        issues.iter().map(|i| i.to_string()).collect::<Vec<_>>()
    );
    assert!(!check_target(&file, "blender-compositor").is_empty());
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
        let got: Vec<String> = check_target(&f, "gltf")
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
fn a_call_to_a_graph_is_read_through_at_its_line() {
    let case = gltf_cases()
        .into_iter()
        .find(|c| c["name"] == "group_shader_refused")
        .unwrap();
    let f = parse(&gltf_case(&case), "case.bn").unwrap();
    let got: Vec<(String, String, usize)> = check_target(&f, "gltf")
        .into_iter()
        .map(|i| (i.graph, i.what, i.line))
        .collect();
    assert_eq!(
        got,
        [("group_shader_refused".to_owned(), "link".to_owned(), 7)]
    );
}
