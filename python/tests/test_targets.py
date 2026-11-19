"""Targets: what a destination accepts, and which ones a text fits (spec/targets.md)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from base_node import BnError, check_target, check_targets, header, infer, load_target, parse, target_names, translate
from base_node.printer import to_source
from base_node.targets import IMPLICIT, _bridge, _literal, blender_target, catalog, graph_issues, translation_issues

ROOT = Path(__file__).resolve().parents[2]
BACKEND = catalog(ROOT)
# The targets shipped with the package and the extension: links in git to targets/
# The targets of the free part; the studio has its own after them
TARGETS = ["blade", "blender-compositor", "blender-geometry", "blender-gp", "blender-shader", "gltf"]

SHIPPED = (ROOT / "python" / "base_node" / "_targets", ROOT / "base-node-for-blender" / "lang" / "_targets")


def test_the_blender_targets_are_what_blender_reports():
    for name in ("blender-geometry", "blender-gp", "blender-shader", "blender-compositor"):
        written = json.loads((ROOT / "targets" / f"{name}.json").read_text(encoding="utf-8"))
        made = blender_target(name, BACKEND)
        assert {k: written[k] for k in made} == made, f"{name}: run python -m base_node.targets"


@pytest.mark.parametrize("link", SHIPPED, ids=lambda p: p.parent.name)
def test_the_shipped_targets_are_a_link_to_the_repository_s(link):
    assert link.is_symlink() and not link.readlink().is_absolute(), f"{link} is a relative link to targets/"
    assert link.resolve() == (ROOT / "targets").resolve()


def test_the_hand_written_targets_name_nodes_of_their_destination():
    shader = {n["name"] for n in BACKEND["kinds"]["shader"]}
    compositor = {n["name"] for n in BACKEND["kinds"]["compositor"]}
    assert set(load_target("gltf").nodes) < shader
    # Blade's own nodes are its business; what it translates from must be the compositor's
    assert set(load_target("blade").translators["blender-compositor"]["nodes"]) <= compositor


def test_a_translator_leads_to_nodes_of_its_target():
    for name in target_names():
        t = load_target(name)
        for source, tr in t.translators.items():
            assert source in target_names(), f"{name} translates from an unknown target {source}"
            for dst in tr.get("nodes", {}).values():
                node = dst if isinstance(dst, str) else dst["node"]
                if "::" in node:
                    assert _bridge(t, node) is not None, f"{name}: {node} is not a graph of its bridges"
                else:
                    assert node in t.nodes, f"{name}: {node} is not one of its nodes"
            assert set(tr.get("kinds", {}).values()) <= set(t.kinds)


def test_no_graph_blender_builds_is_refused():
    """Blender says in which trees each stdlib graph builds: a target never refuses one it builds.

    Blender may refuse one a target accepts, for a reason no list of nodes says: a socket a node
    has in one kind of tree and not in another, a Menu passed between trees."""
    node_level = ("unknown node", "zone", "an input of type Geometry", "is a compositor graph", "is a shader graph")
    for module, graphs in BACKEND["stdlib"].items():
        f = parse((ROOT / "stdlib" / f"{module}.bn").read_text(encoding="utf-8"), module)
        by_name = {g.name: g for g in f.graphs}
        for name, kinds in graphs.items():
            for kind, verdict in kinds.items():
                issues = graph_issues(by_name[name], f"blender-{kind}", f)
                if verdict == "ok":
                    assert issues == [], f"{module}::{name} builds in a {kind} tree: {[str(i) for i in issues]}"
                elif not issues:
                    assert not any(w in verdict for w in node_level) or "cannot be built" in verdict, \
                        f"{module}::{name} in a {kind} tree: {verdict}"


SHADER = """
shader graph "tint"(base: Color = (0.8, 0.8, 0.8, 1.0), rough: Float = 0.5) -> Shader {
  return PrincipledBSDF(base_color: base, roughness: rough)
}
"""


def test_a_shader_of_principled_bsdf_fits_gltf():
    assert check_target(parse(SHADER), "gltf") == []
    assert "gltf" in infer(parse(SHADER)).fits


def test_a_node_the_exporter_drops_is_outside_gltf():
    f = parse(SHADER.replace("roughness: rough", "roughness: NoiseTexture(scale: 3.0).fac"))
    issues = check_target(f, "gltf")
    assert [(i.what, i.name, i.line) for i in issues] == [("node", "NoiseTexture", 3),
                                                          ("link", "PrincipledBSDF.roughness ← NoiseTexture", 3)]
    assert "gltf" in infer(f).outside and "blender-shader" in infer(f).fits


MATERIAL = """shader(material: true) graph Painted() -> (surface: Shader) {
  t = ImageTexture(vector: UVMap(), image: "Paint")
  return (surface: PrincipledBSDF(base_color: BASE, normal: NORMAL))
}
"""


def material(base="t.color", normal="(0.0, 0.0, 1.0)"):
    return parse(MATERIAL.replace("BASE", base).replace("NORMAL", normal))


def links(f, target="gltf"):
    return [(i.name, i.line) for i in check_target(f, target) if i.what == "link"]


def test_a_texture_times_a_constant_fits_gltf():
    tint = "(0.8, 0.5, 0.5, 1.0)"
    assert check_target(material(), "gltf") == []
    assert check_target(material(f"Mix(1.0, t.color, {tint}, blend_type: MULTIPLY, data_type: RGBA)"), "gltf") == []
    assert check_target(material(f"Mix(a: {tint}, b: t, blend_type: MULTIPLY, data_type: RGBA)"), "gltf") == []
    # The exporter reads a factor and a color attribute peeled from the outside
    assert check_target(material(f"Mix(a: {tint}, b: Mix(a: ColorAttribute().color, b: t.color, "
                                 "blend_type: MULTIPLY, data_type: RGBA), blend_type: MULTIPLY)"), "gltf") == []


def test_two_textures_multiplied_do_not_fit_gltf():
    f = material('Mix(a: t.color, b: ImageTexture(image: "Dirt").color, blend_type: MULTIPLY, data_type: RGBA)')
    assert links(f) == [("PrincipledBSDF.base_color ← Mix(ImageTexture, ImageTexture)", 3)]
    # A Mix that blends rather than multiplies is lost too, and a factor other than 1
    assert links(material("Mix(a: t.color, b: (0.5, 0.5, 0.5, 1.0), data_type: RGBA)"))
    assert links(material("Mix(0.5, t.color, (0.5, 0.5, 0.5, 1.0), blend_type: MULTIPLY, data_type: RGBA)"))
    # Rules are the target's: blender-shader has none and takes it
    assert check_target(f, "blender-shader") == []


def roughness(value):
    return links(parse("shader graph g(rough: Float = 0.5) -> Shader {\n  t = ImageTexture(image: \"R\")\n"
                       f"  return PrincipledBSDF(roughness: {value})\n}}\n"))


def test_a_formula_between_textures_and_constants():
    assert roughness("t.alpha * 0.5") == []
    assert roughness("0.5 * SeparateColor(t.color).green") == []
    assert roughness("Math(t.alpha, rough, operation: MULTIPLY)") == []
    assert roughness("Math(t.alpha, operation: MULTIPLY)") == []  # the other value is its default
    assert roughness("t.alpha * t.alpha") == [("PrincipledBSDF.roughness ← Math(ImageTexture, ImageTexture)", 3)]
    assert roughness("t.alpha + 0.5") == [("PrincipledBSDF.roughness ← Math(ImageTexture)", 3)]
    # Both sides constant: Blender computes the Math before the exporter reads it
    assert roughness("rough * 0.5") == []


def test_a_normal_map_from_an_image_fits_gltf_a_raw_noise_does_not():
    assert check_target(material(normal="NormalMap(color: t.color, strength: 0.8)"), "gltf") == []
    assert check_target(material(normal="NormalMap(1.0, t.color)"), "gltf") == []
    # A piped value is the first input, here the strength
    assert links(material(normal="t.color |> NormalMap(color: t.color)")) == [
        ("NormalMap.strength ← ImageTexture(UVMap)", 3)]
    noisy = material(normal="NoiseTexture(scale: 4.0).color")
    assert links(noisy) == [("PrincipledBSDF.normal ← NoiseTexture", 3)]
    bumpy = material(normal="NormalMap(color: NoiseTexture().color)")
    assert links(bumpy) == [("NormalMap.color ← NoiseTexture", 3)]


def test_a_mapping_on_a_texture_s_vector_fits_gltf():
    f = parse(MATERIAL.replace("UVMap()", "Mapping(vector: TextureCoordinate().uv, scale: (2.0, 2.0, 1.0))")
              .replace("BASE", "t").replace("NORMAL", "(0.0, 0.0, 1.0)"))
    assert check_target(f, "gltf") == []
    # Generated coordinates are not a UV map: the exporter would write the UV map instead
    g = parse(MATERIAL.replace("UVMap()", "TextureCoordinate().generated")
              .replace("BASE", "t").replace("NORMAL", "(0.0, 0.0, 1.0)"))
    assert links(g) == [("ImageTexture.vector ← TextureCoordinate", 2)]
    h = parse(MATERIAL.replace("UVMap()", "Mapping(vector: UVMap(), location: UVMap().uv)")
              .replace("BASE", "t").replace("NORMAL", "(0.0, 0.0, 1.0)"))
    assert links(h) == [("Mapping.location ← UVMap", 2)]


# Materials the gltf rules take or refuse, each exported by Blender too (test_gltf_export.py)
GLTF_CASES = json.loads((ROOT / "conformance" / "gltf-cases.json").read_text(encoding="utf-8"))["cases"]


def gltf_case(case):
    """The text of a case of conformance/gltf-cases.json."""
    if "text" in case:
        return case["text"].replace("NAME", case["name"])
    body = "".join(f"  {line}\n" for line in case["body"].split("\n"))
    return f"shader(material: true) graph {case['name']}() -> ({case.get('outputs', 'surface: Shader')}) {{\n{body}}}\n"


@pytest.mark.parametrize("case", GLTF_CASES, ids=lambda c: c["name"])
def test_what_the_gltf_exporter_reads(case):
    assert [i.name for i in check_target(parse(gltf_case(case)), "gltf")] == case["issues"]


def test_a_ramp_is_the_value_of_a_property_not_a_node():
    f = parse("shader graph g(f: Float) -> Color {\n"
              "  return ColorRamp(factor: f, color_ramp: Ramp((0.0, (0.0, 0.0, 0.0, 1.0)), (1.0, (1.0, 1.0, 1.0, 1.0)))).color\n"
              "}\n")
    assert check_target(f, "blender-shader") == []


def test_a_call_to_a_graph_is_read_through_at_its_line():
    f = parse(gltf_case(next(c for c in GLTF_CASES if c["name"] == "group_shader_refused")))
    assert [(i.graph, i.what, i.line) for i in check_target(f, "gltf")] == [("group_shader_refused", "link", 7)]
    # The graph alone takes its parameter as a constant
    assert graph_issues(f.graphs[0], "gltf", f) == []


def test_the_rules_of_gltf_name_its_nodes_and_their_inputs():
    t = load_target("gltf")
    nodes = {n["name"]: n for n in BACKEND["kinds"]["shader"]}
    groups = set(t.groups.values())
    for node, inputs in t.inputs.items():
        if node in t.patterns or node in groups:
            continue
        # Blender reports the inputs a node shows by default: Math's third comes after
        keys = [s["key"] for s in nodes[node]["inputs"]]
        assert node in t.nodes and inputs[:len(keys)] == keys, f"gltf inputs of {node}"
    for node, outputs in t.outputs.items():
        assert outputs == [s["key"] for s in nodes[node]["outputs"]], f"gltf outputs of {node}"
    for node, settings in t.settings.items():
        defaults = {s["name"]: s.get("default") for s in nodes[node]["settings"]}
        assert settings == {k: defaults[k] for k in settings}, f"gltf settings of {node}"
    for v in t.vectors:
        node, _, socket = v.partition(".")
        if node in t.patterns:
            assert socket in t.inputs[node], v
            continue
        types = {s["key"]: s["type"] for s in nodes[node]["inputs"] + nodes[node]["outputs"]}
        assert types[socket] in ("Color", "Vector"), v
    assert set(t.once) <= set(t.nodes)
    for k, feeds in t.rules.items():
        node, dot, inp = k.partition(".")
        assert node in t.nodes or node in t.patterns or node in groups, k
        if not dot:
            assert all(f in t.patterns for f in feeds), k  # a call as a whole has the shape of a pattern
            continue
        for i in inp.split("+"):
            other, _, theirs = i.rpartition(".")  # an input of another call: `Node.input`
            mine = t.inputs.get(other or node, []) + list(t.settings.get(other or node, {}))
            assert i == "*" or theirs in mine, k
        if inp in t.settings.get(node, {}):
            setting = next(s for s in nodes[node]["settings"] if s["name"] == inp)
            assert set(feeds) <= {i["value"] for i in setting.get("items", [])} | {"any"}, k
            continue
        for feed in feeds:
            if _literal(feed) and node in nodes:
                # A number a rule writes is the default of the input: an input left to it is taken
                default = next(s.get("default") for s in nodes[node]["inputs"] if s["key"] == inp)
                want = feed == "true" if feed in ("true", "false") else pytest.approx(float(feed))
                assert default == want, k
            for term in feed.split("×"):
                term = term.strip()
                name, _, out = term.partition(".")
                known = name in ("constant", "any", "named") or name.startswith(("(", "≠")) or _literal(term) \
                    or name in t.patterns
                assert known or (name in t.nodes and (not out or out in t.outputs.get(name, [out]))), f"{k}: {feed}"


def test_a_formula_counts_as_its_node():
    f = parse("shader graph g(a: Float, b: Float) -> Bool {\n  return a < b\n}\n")
    assert [i.name for i in check_target(f, "blender-shader")] == ["Compare"]  # no Compare in a shader tree
    assert check_target(f, "blender-geometry") == []


def test_an_implicit_input_is_the_target_s_to_allow():
    f = parse("geometry graph g(p: Vector = Position()) -> Vector {\n  return p\n}\n")
    assert check_target(f, "blender-compositor") == []
    assert [i.what for i in check_target(f, "gltf")] == ["kind", "implicit"]
    assert "Position" in IMPLICIT


def test_a_zone_is_the_target_s_to_allow():
    f = parse("geometry graph g(n: Int) -> Float {\n  s = repeat(n, v: 0.0) {\n    return (v: v + 1.0)\n  }\n"
              "  return s.v\n}\n")
    assert check_target(f, "blender-geometry") == []
    assert ("zone", "repeat") in [(i.what, i.name) for i in check_target(f, "gltf")]


def test_a_called_graph_brings_its_nodes():
    f = parse("compositor graph a(c: Color) -> Color {\n  return SetAlpha(c, alpha: 1.0)\n}\n\n"
              "geometry graph b(c: Color) -> Color {\n  return a(c)\n}\n")
    b = f.graphs[1]
    assert graph_issues(b, "blender-compositor", f) == []
    assert [i.what for i in graph_issues(b, "blender-geometry", f)] == ["graph"]


def test_a_stdlib_module_brings_its_nodes():
    f = parse("use merge (with_alpha)\n\ngeometry graph g(c: Color) -> Color {\n  return with_alpha(c, 1.0)\n}\n")
    assert check_target(f, "blender-compositor") == []
    assert check_target(f, "blender-geometry") != []


ONE_TARGET_PER_GRAPH = """// @target blender-geometry, blender-shader

geometry graph lift(mesh: Geometry) -> Geometry {
  return SetPosition(mesh, offset: CombineXYZ(z: 1.0))
}

shader graph tint(c: Color) -> Shader {
  return Emission(color: c)
}
"""


def test_a_text_may_promise_one_target_per_graph():
    src = ONE_TARGET_PER_GRAPH
    f = parse(src)
    assert infer(f).fits == {}  # neither target takes every graph
    assert check_targets(f, ["blender-geometry", "blender-shader"]) == []
    assert header(src).target == ["blender-geometry", "blender-shader"]


def test_an_unknown_target_in_the_head():
    with pytest.raises(BnError) as e:
        header("// @target blender-nodes\n\ngeometry graph g() -> Float {\n  return 1.0\n}\n")
    assert "@target 'blender-nodes'" in e.value.diagnostics[0].message


COMPOSITE = """compositor graph soften(image: Color, size: Float = 4.0) -> Color {
  blurred = Blur(image, size: size)
  return Mix(image, blurred, factor: 0.5)
}
"""


def test_a_text_reaches_blade_through_its_translator():
    f = parse(COMPOSITE)
    fits = infer(f).fits
    assert fits["blender-compositor"] is None
    assert fits["blade"] == "blender-compositor"
    out = translate(f, "blender-compositor", "blade")
    assert out.graphs[0].kind == "pixel"
    assert "pixel graph soften" in to_source(out)
    assert f.graphs[0].kind == "compositor"  # the text itself is left as it was


def test_a_node_the_translator_does_not_list_stays_out():
    f = parse(COMPOSITE.replace("Blur(image, size: size)", "Pixelate(image)"))
    inf = infer(f)
    assert "blade" in inf.outside
    with pytest.raises(ValueError, match="Pixelate"):
        translate(f, "blender-compositor", "blade")


# The same cases as rust/tests/conformance.rs

PAINT = """compositor graph paint(image: Color) -> Color {
  soft = Kuwahara(image, size: 8.0)
  return Mix(image, Kuwahara(soft), factor: 0.5)
}
"""

PAINTED = """use blender_interop

pixel graph paint(image: Color) -> Color {
  soft = blender_interop::kuwahara(image, size: 8.0)
  return Mix(image, blender_interop::kuwahara(soft), factor: 0.5)
}
"""


def test_a_bridge_carries_a_node_blade_has_not():
    f = parse(PAINT)
    assert infer(f).fits["blade"] == "blender-compositor"
    text = to_source(translate(f, "blender-compositor", "blade"))
    assert text == PAINTED  # the call is the bridge's, the text uses its module once
    assert check_target(parse(text), "blade") == []
    assert infer(parse(text)).fits == {"blade": None}


def test_the_bridge_module_fits_its_target():
    path = ROOT / "targets" / "blade" / "blender_interop.bn"
    assert load_target("blade").bridges == ["blade/blender_interop.bn"]
    assert check_target(parse(path.read_text(encoding="utf-8")), "blade") == []


def test_a_bridge_graph_outside_its_target_is_refused(tmp_path):
    blade = json.loads((ROOT / "targets" / "blade.json").read_text(encoding="utf-8"))
    blade["nodes"].remove("Median")
    blade["bridges"] = [str(ROOT / "targets" / "blade" / "blender_interop.bn")]
    path = tmp_path / "narrow.json"
    path.write_text(json.dumps(blade), encoding="utf-8")
    issues = translation_issues(parse(PAINT), "blender-compositor", str(path))
    assert [(i.what, i.name, i.line) for i in issues] == [
        ("graph", "blender_interop::kuwahara (node Median)", 2),
        ("graph", "blender_interop::kuwahara (node Median)", 3)]


def test_a_stdlib_module_used_whole_brings_its_graphs_only():
    used = "use {}\n\ngeometry graph g(c: Color) -> Color {{\n  return SetAlpha(c, alpha: 1.0)\n}}\n"
    assert [str(i) for i in check_target(parse(used.format("merge")), "blender-geometry")] == [
        "Graph 'g': node 'SetAlpha' outside target 'blender-geometry' (line 4)"]
    # A module that is not found may hold any graph
    assert check_target(parse(used.format("mine")), "blender-geometry") == []


def test_an_unknown_target_is_an_error():
    f = parse(COMPOSITE)
    assert target_names() == TARGETS
    message = "unknown target 'nope'; targets: " + ", ".join(TARGETS)
    for call in (lambda: load_target("nope"), lambda: check_target(f, "nope"),
                 lambda: check_target([], "nope"), lambda: check_targets(f, ["blade", "nope"]),
                 lambda: translate(f, "blender-compositor", "nope")):
        with pytest.raises(ValueError) as e:
            call()
        assert str(e.value) == message


def test_what_inference_holds():
    inf = infer(parse(COMPOSITE))
    assert list(inf.fits.items()) == [("blade", "blender-compositor"), ("blender-compositor", None)]
    assert list(inf.outside) == [t for t in TARGETS if t not in ("blade", "blender-compositor")]
    assert inf.graphs == [("soften", ["blender-compositor"])]
    lines = [
        "Compatible: blender-compositor, blade (translated from blender-compositor)",
        "Outside blender-geometry: node Blur (line 2)",
        "Outside blender-gp: node Blur (line 2)",
        "Outside blender-shader: node Blur (line 2)",
        "Outside gltf: kind compositor (line 1) and 1 more",
    ]
    assert inf.lines() == lines


def test_a_translator_renames_a_node():
    f = parse("compositor graph g(image: Color) -> Color {\n  return RGBCurves(image)\n}\n")
    assert translate(f, "blender-compositor", "blade").graphs[0].body[0].value.name == "Curves"


def test_a_translator_renames_inputs_and_settings():
    f = parse(
        "compositor graph g(image: Color) -> Color {\n"
        "  blurred = Blur(image, size: 4.0)\n"
        "  return MixLegacy(image, color2: blurred, blend_type: MULTIPLY)\n"
        "}\n"
    )
    text = to_source(translate(f, "blender-compositor", "blade"))
    assert "Blur(image, radius: 4.0)" in text
    assert "Mix(image, b: blurred, blend: MULTIPLY)" in text


def test_what_the_editor_shows():
    lines = infer(parse(COMPOSITE)).lines()
    assert lines[0].startswith("Compatible: blender-compositor")
    assert "blade (translated from blender-compositor)" in lines[0]
    assert any(line.startswith("Outside gltf: kind compositor") for line in lines)


def test_a_target_is_named_not_reached_by_path():
    with pytest.raises(ValueError):
        load_target("../targets/gltf")
