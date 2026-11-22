"""Targets: what a destination accepts, and which ones a text fits (spec/targets.md)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from base_node_blender import (BnError, check_target, check_targets, header, infer, load_target, parse, promise_names,
                               target_names, translate, variant_names)
from base_node.printer import to_source
from base_node_blender.targets import (IMPLICIT, Blender, _bridge, _literal, accepted, blender, blender_catalog, catalog,
                                       graph_issues, inferred_names, promise_refusal, sync, translation_issues)

ROOT = Path(__file__).resolve().parents[2]
BACKEND = catalog(ROOT)
# The targets shipped with the package and the extension: links in git to targets/
# The targets of the free part; the studio has its own after them
TARGETS = ["blade", "blender", "blender@5.2-lts", "blender@5.3"]
# What an inference tries: `blender` as the versions promised, whole and by variant
INFERRED = ["blade", "blender", "blender cycles", "blender eevee", "blender gltf"]
VARIANTS = "; variants of blender, written after it: cycles, eevee, gltf"

SHIPPED = (ROOT / "python" / "base_node_blender" / "_targets", ROOT / "base-node-for-blender" / "blender" / "_targets")


def test_the_catalogs_of_blender_are_what_blender_reports():
    backends = sorted((ROOT / "targets" / "backends").glob("blender-*.json"))
    assert backends
    for path in backends:
        backend = json.loads(path.read_text(encoding="utf-8"))
        version = ".".join(backend["blender"].split(".")[:2])
        assert path.stem == f"blender-{version}"
        written = json.loads((ROOT / "targets" / "blender" / f"{version}.json").read_text(encoding="utf-8"))
        assert written == blender_catalog(backend), f"{version}: run python -m base_node_blender.targets"
    # A catalog per backend, and no other
    assert blender().versions == sorted(p.stem.removeprefix("blender-") for p in backends)


def test_the_promised_versions_are_one_list_and_each_has_a_catalog():
    b = blender()
    declared = json.loads((ROOT / "targets" / "blender.json").read_text(encoding="utf-8"))
    assert b.promised == declared["promised"] == ["5.2", "5.3"]
    assert set(b.promised) <= set(b.versions)
    assert [m.name for m in load_target("blender").members] == [b.name(v) for v in b.promised]
    for variant in variant_names():
        assert [m.name for m in load_target(f"blender {variant}").members] == [f"{b.name(v)} {variant}"
                                                                           for v in b.promised]


def test_a_version_a_bare_name_an_alias_and_a_variant():
    assert target_names() == TARGETS and variant_names() == ["cycles", "eevee", "gltf"]
    assert inferred_names() == INFERRED
    assert [n for n in promise_names() if n.startswith("blender")] == [
        "blender", "blender cycles", "blender eevee", "blender gltf",
        "blender@5.2-lts", "blender@5.2-lts cycles", "blender@5.2-lts eevee", "blender@5.2-lts gltf",
        "blender@5.3", "blender@5.3 cycles", "blender@5.3 eevee", "blender@5.3 gltf"]
    one = load_target("blender@5.3")
    assert one.kinds == ["geometry", "shader", "compositor"] == list(one.trees) and not one.members
    assert "Blur" in one.trees["compositor"]["nodes"] and "Blur" not in one.trees["geometry"]["nodes"]
    # An alias is the version it names today
    assert load_target("blender@latest") is one
    assert load_target("blender@latest gltf") is load_target("blender@5.3 gltf")
    lts = load_target("blender@5.2-lts")
    assert load_target("blender@lts") is lts and load_target("blender@lts eevee") is load_target("blender@5.2-lts eevee")
    assert [m.name for m in load_target("blender").members] == ["blender@5.2-lts", "blender@5.3"]
    # The LTS is the older catalog: the compositor of Blender 5.2 has no Compare node
    assert "Compare" in one.trees["compositor"]["nodes"] and "Compare" not in lts.trees["compositor"]["nodes"]
    gltf = load_target("blender@5.3 gltf")
    assert gltf.kinds == ["shader"] and "PrincipledBSDF" in gltf.nodes and gltf.rules and not gltf.trees
    for name in promise_names():
        assert load_target(name).name == name and promise_refusal(name) is None


def test_a_version_without_a_catalog_says_so():
    no = "no catalog for Blender 4.5 in this version of Base Node (catalogs: 5.2, 5.3)"
    for name in ("blender@4.5-lts", "blender@4.5", "blender@4.5-lts gltf", "blender@4.5 eevee"):
        with pytest.raises(ValueError) as e:
            load_target(name)
        assert str(e.value) == f"target '{name}': {no}"
    assert promise_refusal("blender@4.5-lts") == no
    with pytest.raises(ValueError) as e:
        load_target("blender@5.2")
    assert str(e.value) == ("unknown target 'blender@5.2'; targets: " + ", ".join(TARGETS) + VARIANTS
                            + "; Blender 5.2 is an LTS: write 'blender@5.2-lts'")
    with pytest.raises(ValueError) as e:
        load_target("blender@5.3-lts")
    assert str(e.value) == ("unknown target 'blender@5.3-lts'; targets: " + ", ".join(TARGETS) + VARIANTS
                            + "; Blender 5.3 is not an LTS: write 'blender@5.3'")
    for name in ("blender@", "blender@5", "blender@x", "blender nope", "blender  gltf", "blender@5.3 gltf eevee",
                 "blade@1.0", "blade gltf"):
        with pytest.raises(ValueError, match="unknown target"):
            load_target(name)


def test_adding_a_catalog_and_one_line_adds_a_promised_lts(tmp_path):
    """What T-144 did with Blender 5.2: its catalog, and `5.2` in the promised versions."""
    root = tmp_path / "targets"
    (root / "blender").mkdir(parents=True)
    (root / "backends").mkdir()
    for name in ("gltf", "eevee", "cycles"):
        (root / "blender" / f"{name}.json").write_text((ROOT / "targets" / "blender" / f"{name}.json").read_text())
    older = json.loads(json.dumps(BACKEND))
    del older["stdlib"]
    older["blender"] = "5.2.1 LTS"
    older["kinds"]["compositor"] = [n for n in older["kinds"]["compositor"] if n["name"] != "Kuwahara"]
    (root / "backends" / "blender-5.2.json").write_text(json.dumps(older))
    (root / "backends" / "blender-5.3.json").write_text((ROOT / "targets" / "backends" / "blender-5.3.json").read_text())
    assert sorted(p.name for p in sync(tmp_path)) == ["5.2.json", "5.3.json"]
    declared = json.loads((ROOT / "targets" / "blender.json").read_text(encoding="utf-8"))
    assert declared["lts"] == ["5.2"]
    declared["promised"] = ["5.2", "5.3"]
    (root / "blender.json").write_text(json.dumps(declared))
    b = Blender(root)
    assert b.names() == ["blender", "blender@5.2-lts", "blender@5.3"]
    assert b.refusal("5.2-lts", []) is None and b.refusal("lts", []) is None and b.alias("lts") == "5.2"
    assert b.refusal("5.2", []) == ("unknown", "Blender 5.2 is an LTS: write 'blender@5.2-lts'")
    both = b.target(None, None)
    assert [m.name for m in both.members] == ["blender@5.2-lts", "blender@5.3"]
    # A node the LTS has not is an issue of that version; one no version has is the target's
    f = parse("compositor graph g(image: Color) -> Color {\n  return Kuwahara(Cube(image))\n}\n")
    assert [(i.name, i.target) for i in graph_issues(f.graphs[0], both, f)] == [
        ("Kuwahara", "blender@5.2-lts"), ("Cube", "blender")]
    assert [(i.name, i.target) for i in graph_issues(f.graphs[0], b.target("5.3", None), f)] == [
        ("Cube", "blender@5.3")]


def test_an_alias_is_refused_in_the_head_of_a_text():
    text = "// @target {}\n\nshader graph g() -> Float {{\n  return 1.0\n}}\n"
    assert header(text.format("blender@5.3 gltf,  blender   eevee")).target == ["blender@5.3 gltf", "blender eevee"]
    with pytest.raises(BnError) as e:
        header(text.format("blender, blender@latest gltf"), "t.bn")
    assert str(e.value) == (
        "t.bn:1:21  @target 'blender@latest gltf': an alias, for a command line: the version it names changes "
        "with each release of Blender, and the promise of the text would change with it: write the version, "
        "'blender@5.3 gltf'")
    with pytest.raises(BnError) as e:
        header(text.format("blender@lts"), "t.bn")
    assert "an alias, for a command line" in str(e.value)
    with pytest.raises(BnError) as e:
        header(text.format("blender@4.5-lts"), "t.bn")
    assert str(e.value) == ("t.bn:1:12  @target 'blender@4.5-lts': no catalog for Blender 4.5 in this version of "
                            "Base Node (catalogs: 5.2, 5.3)")
    assert header(text.format("blender@5.2-lts"), "t.bn").target == ["blender@5.2-lts"]


@pytest.mark.parametrize("old, new", [("blender-geometry", "blender"), ("blender-gp", "blender"),
                                      ("blender-shader", "blender"), ("blender-compositor", "blender"),
                                      ("gltf", "blender gltf")])
def test_a_name_of_before_says_what_to_write(old, new):
    listed = ", ".join(TARGETS) + VARIANTS + f"; '{old}' is now '{new}'"
    with pytest.raises(ValueError) as e:
        load_target(old)
    assert str(e.value) == f"unknown target '{old}'; targets: {listed}"
    with pytest.raises(BnError) as e:
        header(f"// @target {old}\n\ngeometry graph g() -> Float {{\n  return 1.0\n}}\n", "t.bn")
    assert str(e.value) == f"t.bn:1:12  @target '{old}': one of {listed}"


def engine_variant(name):
    return json.loads((ROOT / "targets" / "blender" / f"{name}.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("name", ["eevee", "cycles"])
def test_an_engine_variant_is_the_shader_tree_without_what_blender_says_is_not_its(name):
    data = engine_variant(name)
    shader = {n["name"] for n in BACKEND["kinds"]["shader"]}
    assert data["experimental"] is True and data["kinds"] == ["shader"]
    # Each node left out is a shader node, with where Blender says so
    assert data["without"] and set(data["without"]) <= shader
    assert all(source.startswith("Blender 5.3.0, ") for source in data["without"].values())
    t = load_target(f"blender@5.3 {name}")
    assert t.experimental and set(t.trees) == {"shader"}
    assert set(t.trees["shader"]["nodes"]) == shader - set(data["without"])
    assert t.trees["shader"]["types"] == load_target("blender@5.3").trees["shader"]["types"]
    # One list for every version: each keeps the shader nodes it has, less the list
    for version in blender().promised:
        has = {n["name"] for n in catalog(ROOT, version)["kinds"]["shader"]}
        of_version = load_target(f"{blender().name(version)} {name}")
        assert set(of_version.trees["shader"]["nodes"]) == has - set(data["without"])


def test_what_a_tooltip_of_blender_says_of_an_engine_is_in_its_variant():
    said = {n["name"]: n["description"] for n in BACKEND["kinds"]["shader"]
            if "only supported in" in (n.get("description") or "")}
    assert said, "no tooltip of this Blender says a node is one engine's"
    for node, tooltip in said.items():
        if "only supported in Cycles" in tooltip:
            assert node in engine_variant("eevee")["without"], node
        if "only supported in EEVEE" in tooltip:
            assert node in engine_variant("cycles")["without"], node


def test_an_engine_variant_takes_shader_graphs_and_the_graphs_they_call():
    toon = parse("shader graph g() -> Shader {\n  return ToonBSDF()\n}\n")
    assert check_target(toon, "blender") == [] == check_target(toon, "blender cycles")
    assert [str(i) for i in check_target(toon, "blender eevee")] == [
        "Graph 'g': node 'ToonBSDF' outside target 'blender eevee' (line 2)"]
    rgb = parse("shader graph g(s: Shader) -> Color {\n  return ShaderToRGB(s).color\n}\n")
    assert check_target(rgb, "blender eevee") == []
    assert [i.name for i in check_target(rgb, "blender@5.3 cycles")] == ["ShaderToRGB"]
    # A graph of another kind is no engine's; one a shader graph calls is built in its tree
    math = parse("geometry graph half(x: Float) -> Float {\n  return x * 0.5\n}\n\n"
                 "shader graph g(x: Float) -> Shader {\n  return Emission(strength: half(x))\n}\n")
    assert [(i.graph, i.what, i.name) for i in check_target(math, "blender eevee")] == [("half", "kind", "geometry")]
    assert graph_issues(math.graphs[1], "blender eevee", math) == []
    infer_ = infer(toon)
    assert infer_.fits["blender cycles"] is None and "blender eevee" in infer_.outside


def test_what_an_editor_colors_is_what_every_tree_and_version_accepts():
    assert {"Blur", "Cube", "PrincipledBSDF"} <= accepted("blender", "node")
    assert "Geometry" in accepted("blender", "type") and "Shader" in accepted("blender@5.3", "type")
    assert "ToonBSDF" not in accepted("blender eevee", "node") and "Cube" not in accepted("blender eevee", "node")
    assert accepted("blender gltf", "node") == set(load_target("blender@5.3 gltf").nodes)
    assert accepted("blade", "node") == set(load_target("blade").nodes)


@pytest.mark.parametrize("link", SHIPPED, ids=lambda p: p.parent.name)
def test_the_shipped_targets_are_a_link_to_the_repository_s(link):
    assert link.is_symlink() and not link.readlink().is_absolute(), f"{link} is a relative link to targets/"
    assert link.resolve() == (ROOT / "targets").resolve()


def test_the_hand_written_targets_name_nodes_of_their_destination():
    shader = {n["name"] for n in BACKEND["kinds"]["shader"]}
    compositor = {n["name"] for n in BACKEND["kinds"]["compositor"]}
    gltf = json.loads((ROOT / "targets" / "blender" / "gltf.json").read_text(encoding="utf-8"))
    assert set(gltf["nodes"]) < shader
    # Every version promised has each of them: the rules read the same in each
    assert all(m.nodes == gltf["nodes"] for m in load_target("blender gltf").members)
    # Blade's own nodes are its business; what it translates from must be the compositor's
    assert set(load_target("blade").translators["blender"]["nodes"]) <= compositor


def test_a_translator_leads_to_nodes_of_its_target():
    for name in TARGETS:
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
    """Each Blender says in which trees each stdlib graph builds: its target never refuses one it
    builds, of a module that promises that version.

    Blender may refuse one a target accepts, for a reason no list of nodes says: a socket a node
    has in one kind of tree and not in another, a Menu passed between trees."""
    node_level = ("unknown node", "zone", "an input of type Geometry", "is a compositor graph", "is a shader graph")
    b = blender()
    for version in b.promised:
        target = b.name(version)
        for module, graphs in catalog(ROOT, version)["stdlib"].items():
            text = (ROOT / "stdlib" / f"{module}.bn").read_text(encoding="utf-8")
            f = parse(text, module)
            # A module that promises another version alone says nothing of this one
            promised = {m.name for t in header(text, module, f).target for m in load_target(t).members or [load_target(t)]}
            if target not in promised:
                continue
            by_name = {g.name: g for g in f.graphs}
            for name, kinds in graphs.items():
                for kind, verdict in kinds.items():
                    where = f"{module}::{name} in a {kind} tree of {target}"
                    issues = graph_issues(by_name[name], target, f, tree=kind)
                    if verdict == "ok":
                        assert issues == [], f"{where} builds: {[str(i) for i in issues]}"
                    elif not issues:
                        assert not any(w in verdict for w in node_level) or "cannot be built" in verdict, \
                            f"{where}: {verdict}"


SHADER = """
shader graph "tint"(base: Color = (0.8, 0.8, 0.8, 1.0), rough: Float = 0.5) -> Shader {
  return PrincipledBSDF(base_color: base, roughness: rough)
}
"""


def test_a_shader_of_principled_bsdf_fits_gltf():
    assert check_target(parse(SHADER), "blender gltf") == []
    assert "blender gltf" in infer(parse(SHADER)).fits


def test_a_node_the_exporter_drops_is_outside_gltf():
    f = parse(SHADER.replace("roughness: rough", "roughness: NoiseTexture(scale: 3.0).fac"))
    issues = check_target(f, "blender gltf")
    assert [(i.what, i.name, i.line) for i in issues] == [("node", "NoiseTexture", 3),
                                                          ("link", "PrincipledBSDF.roughness ← NoiseTexture", 3)]
    assert "blender gltf" in infer(f).outside and "blender" in infer(f).fits


MATERIAL = """shader(material: true) graph Painted() -> (surface: Shader) {
  t = ImageTexture(vector: UVMap(), image: "Paint")
  return (surface: PrincipledBSDF(base_color: BASE, normal: NORMAL))
}
"""


def material(base="t.color", normal="(0.0, 0.0, 1.0)"):
    return parse(MATERIAL.replace("BASE", base).replace("NORMAL", normal))


def links(f, target="blender gltf"):
    return [(i.name, i.line) for i in check_target(f, target) if i.what == "link"]


def test_a_texture_times_a_constant_fits_gltf():
    tint = "(0.8, 0.5, 0.5, 1.0)"
    assert check_target(material(), "blender gltf") == []
    assert check_target(material(f"Mix(1.0, t.color, {tint}, blend_type: MULTIPLY, data_type: RGBA)"), "blender gltf") == []
    assert check_target(material(f"Mix(a: {tint}, b: t, blend_type: MULTIPLY, data_type: RGBA)"), "blender gltf") == []
    # The exporter reads a factor and a color attribute peeled from the outside
    assert check_target(material(f"Mix(a: {tint}, b: Mix(a: ColorAttribute().color, b: t.color, "
                                 "blend_type: MULTIPLY, data_type: RGBA), blend_type: MULTIPLY)"), "blender gltf") == []


def test_two_textures_multiplied_do_not_fit_gltf():
    f = material('Mix(a: t.color, b: ImageTexture(image: "Dirt").color, blend_type: MULTIPLY, data_type: RGBA)')
    assert links(f) == [("PrincipledBSDF.base_color ← Mix(ImageTexture, ImageTexture)", 3)]
    # A Mix that blends rather than multiplies is lost too, and a factor other than 1
    assert links(material("Mix(a: t.color, b: (0.5, 0.5, 0.5, 1.0), data_type: RGBA)"))
    assert links(material("Mix(0.5, t.color, (0.5, 0.5, 0.5, 1.0), blend_type: MULTIPLY, data_type: RGBA)"))
    # Rules are the target's: blender has none and takes it
    assert check_target(f, "blender") == []


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
    assert check_target(material(normal="NormalMap(color: t.color, strength: 0.8)"), "blender gltf") == []
    assert check_target(material(normal="NormalMap(1.0, t.color)"), "blender gltf") == []
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
    assert check_target(f, "blender gltf") == []
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
    assert [i.name for i in check_target(parse(gltf_case(case)), "blender gltf")] == case["issues"]


def test_a_ramp_is_the_value_of_a_property_not_a_node():
    f = parse("shader graph g(f: Float) -> Color {\n"
              "  return ColorRamp(factor: f, color_ramp: Ramp((0.0, (0.0, 0.0, 0.0, 1.0)), (1.0, (1.0, 1.0, 1.0, 1.0)))).color\n"
              "}\n")
    assert check_target(f, "blender") == []


def test_a_call_to_a_graph_is_read_through_at_its_line():
    f = parse(gltf_case(next(c for c in GLTF_CASES if c["name"] == "group_shader_refused")))
    assert [(i.graph, i.what, i.line) for i in check_target(f, "blender gltf")] == [("group_shader_refused", "link", 7)]
    # The graph alone takes its parameter as a constant
    assert graph_issues(f.graphs[0], "blender gltf", f) == []


def test_the_rules_of_gltf_name_its_nodes_and_their_inputs():
    t = load_target("blender@5.3 gltf")
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
    text = "shader graph g(a: Float, b: Float) -> Bool {\n  return a < b\n}\n"
    # A comparison is Compare where the tree has one, else Math: a shader tree has no Compare
    assert check_target(parse(text), "blender") == []
    assert check_target(parse(text.replace("shader", "geometry", 1)), "blender") == []
    g = parse("shader graph g(a: Bool, b: Bool) -> Float {\n  return Compare(a, b)\n}\n")
    assert [i.name for i in check_target(g, "blender")] == ["Compare"]


def test_an_implicit_input_is_the_target_s_to_allow():
    f = parse("geometry graph g(p: Vector = Position()) -> Vector {\n  return p\n}\n")
    assert check_target(f, "blender") == []
    assert [i.what for i in check_target(f, "blender gltf")] == ["kind", "implicit"]
    assert "Position" in IMPLICIT


def test_a_zone_is_the_target_s_to_allow():
    f = parse("geometry graph g(n: Int) -> Float {\n  s = repeat(n, v: 0.0) -> {\n    return (v: v + 1.0)\n  }\n"
              "  return s.v\n}\n")
    assert check_target(f, "blender") == []
    assert ("zone", "repeat") in [(i.what, i.name) for i in check_target(f, "blender gltf")]
    # A zone is its kind of tree's: the compositor has no simulation
    step = "{} graph g(x: Float) -> Float {{\n  s = simulate(v: x) -> {{\n    return (v: v)\n  }}\n  return s.v\n}}\n"
    assert check_target(parse(step.format("geometry")), "blender") == []
    assert [(i.what, i.name) for i in check_target(parse(step.format("compositor")), "blender")] == [("zone", "simulate")]


def test_a_called_graph_brings_its_nodes():
    # A graph is built in the tree of the graph that calls it, whatever its own kind
    f = parse("compositor graph a(c: Color) -> Color {\n  return SetAlpha(c, alpha: 1.0)\n}\n\n"
              "geometry graph b(c: Color) -> Color {\n  return a(c)\n}\n\n"
              "compositor graph c(c: Color) -> Color {\n  return a(c)\n}\n\n"
              "geometry graph half(x: Float) -> Float {\n  return x * 0.5\n}\n\n"
              "compositor graph d(c: Color) -> Color {\n  return SetAlpha(c, alpha: half(1.0))\n}\n")
    a, b, c, _half, d = f.graphs
    assert graph_issues(a, "blender", f) == [] == graph_issues(c, "blender", f)
    assert [(i.what, i.name) for i in graph_issues(b, "blender", f)] == [("graph", "a (node SetAlpha)")]
    assert graph_issues(d, "blender", f) == []


def test_a_stdlib_module_brings_its_nodes():
    f = parse("use merge (with_alpha)\n\ngeometry graph g(c: Color) -> Color {\n  return with_alpha(c, 1.0)\n}\n")
    assert check_target(f, "blender") != []
    assert check_target(parse(to_source(f).replace("geometry graph", "compositor graph")), "blender") == []


ONE_TARGET_PER_GRAPH = """// @target blender gltf, blade

shader graph tint(c: Color) -> Shader {
  return Emission(color: c)
}

pixel graph soft(image: Color) -> Color {
  return Blur(image, radius: 2.0)
}
"""


def test_a_text_may_promise_one_target_per_graph():
    src = ONE_TARGET_PER_GRAPH
    f = parse(src)
    assert infer(f).fits == {}  # neither target takes every graph
    assert check_targets(f, ["blender gltf", "blade"]) == []
    assert check_targets(f, ["blender gltf"]) != [] != check_targets(f, ["blade"])
    assert header(src).target == ["blender gltf", "blade"]


def test_blender_takes_the_graphs_of_each_kind_of_tree():
    f = parse("geometry graph lift(mesh: Geometry) -> Geometry {\n"
              "  return SetPosition(mesh, offset: CombineXYZ(z: 1.0))\n}\n\n"
              "shader graph tint(c: Color) -> Shader {\n  return Emission(color: c)\n}\n\n"
              "compositor graph soft(image: Color) -> Color {\n  return Blur(image)\n}\n")
    inf = infer(f)
    assert inf.fits == {"blender": None}
    assert inf.graphs == [("lift", ["blender"]), ("tint", ["blender", "blender cycles", "blender eevee", "blender gltf"]
                                                  + (["materialx"] if "materialx" in TARGETS else [])),
                          ("soft", ["blender"])]
    # Each against the nodes of its kind: a geometry node in a shader graph is outside
    wrong = parse("shader graph g(mesh: Geometry) -> Geometry {\n  return SetPosition(mesh)\n}\n")
    assert [(i.what, i.name) for i in check_target(wrong, "blender")] == [
        ("type", "Geometry"), ("type", "Geometry"), ("node", "SetPosition")]
    # A kind that is no tree of Blender's
    pixel = parse("pixel graph g(x: Float) -> Float {\n  return x * 2.0\n}\n")
    assert [(i.what, i.name) for i in check_target(pixel, "blender")] == [("kind", "pixel")]


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
    assert fits["blender"] is None
    assert fits["blade"] == "blender"
    out = translate(f, "blender", "blade")
    assert out.graphs[0].kind == "pixel"
    assert "pixel graph soften" in to_source(out)
    assert f.graphs[0].kind == "compositor"  # the text itself is left as it was


def test_a_node_the_translator_does_not_list_stays_out():
    f = parse(COMPOSITE.replace("Blur(image, size: size)", "Pixelate(image)"))
    inf = infer(f)
    assert "blade" in inf.outside
    with pytest.raises(ValueError, match="Pixelate"):
        translate(f, "blender", "blade")


# The same cases as rust-blender/tests/conformance.rs

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
    assert infer(f).fits["blade"] == "blender"
    text = to_source(translate(f, "blender", "blade"))
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
    issues = translation_issues(parse(PAINT), "blender", str(path))
    assert [(i.what, i.name, i.line) for i in issues] == [
        ("graph", "blender_interop::kuwahara (node Median)", 2),
        ("graph", "blender_interop::kuwahara (node Median)", 3)]


def test_a_stdlib_module_used_whole_brings_its_graphs_only():
    used = "use {}\n\ngeometry graph g(c: Color) -> Color {{\n  return SetAlpha(c, alpha: 1.0)\n}}\n"
    assert [str(i) for i in check_target(parse(used.format("merge")), "blender")] == [
        "Graph 'g': node 'SetAlpha' outside target 'blender' (line 4)"]
    assert [str(i) for i in check_target(parse(used.format("merge")), "blender@5.3")] == [
        "Graph 'g': node 'SetAlpha' outside target 'blender@5.3' (line 4)"]
    # A module that is not found may hold any graph
    assert check_target(parse(used.format("mine")), "blender") == []


def test_an_unknown_target_is_an_error():
    f = parse(COMPOSITE)
    assert target_names() == TARGETS
    message = "unknown target 'nope'; targets: " + ", ".join(TARGETS) + VARIANTS
    for call in (lambda: load_target("nope"), lambda: check_target(f, "nope"),
                 lambda: check_target([], "nope"), lambda: check_targets(f, ["blade", "nope"]),
                 lambda: translate(f, "blender", "nope")):
        with pytest.raises(ValueError) as e:
            call()
        assert str(e.value) == message


def test_what_inference_holds():
    inf = infer(parse(COMPOSITE))
    assert list(inf.fits.items()) == [("blade", "blender"), ("blender", None)]
    # A variant of blender is about shaders: it is not tried for a text that holds none
    assert list(inf.outside) == [t for t in INFERRED if t not in ("blade", "blender") and " " not in t]
    assert inf.graphs == [("soften", ["blender"])]
    lines = [
        "Compatible: blender, blade (translated from blender)",
    ]
    assert inf.lines() == lines


def test_a_translator_renames_a_node():
    f = parse("compositor graph g(image: Color) -> Color {\n  return RGBCurves(image)\n}\n")
    assert translate(f, "blender", "blade").graphs[0].body[0].value.name == "Curves"


def test_a_translator_renames_inputs_and_settings():
    f = parse(
        "compositor graph g(image: Color) -> Color {\n"
        "  blurred = Blur(image, size: 4.0)\n"
        "  return MixLegacy(image, color2: blurred, blend_type: MULTIPLY)\n"
        "}\n"
    )
    text = to_source(translate(f, "blender", "blade"))
    assert "Blur(image, radius: 4.0)" in text
    assert "Mix(image, b: blurred, blend: MULTIPLY)" in text


def test_what_the_editor_shows():
    lines = infer(parse(COMPOSITE)).lines()
    assert lines[0].startswith("Compatible: blender")
    assert "blade (translated from blender)" in lines[0]
    assert not any(line.startswith("Outside blender ") for line in lines)
    shader = infer(parse("shader graph g() -> Shader {\n  return PrincipledBSDF(roughness: NoiseTexture(scale: 3.0).fac)\n}\n")).lines()
    assert shader[0].startswith("Compatible: blender, blender cycles, blender eevee")
    assert any(line.startswith("Outside blender gltf: node NoiseTexture (line 2)") for line in shader)


def test_a_target_is_named_not_reached_by_path():
    with pytest.raises(ValueError):
        load_target("../targets/blender/gltf")


def test_a_ternary_is_the_node_of_the_tree_it_is_built_in():
    # A geometry graph called from a shader graph is built in the shader tree: its ternary is a Mix
    # there, which Blender 5.2 has, and no Switch, which its shader tree has not
    f = parse("geometry graph pick(on: Bool) -> Float {\n  return on ? 1.0 : 0.0\n}\n\n"
              "shader graph s(x: Float) -> Float {\n  return pick(x > 0.5)\n}\n")
    assert check_target(f, "blender@5.2-lts") == []
    by_name = {g.name: g for g in f.graphs}
    assert [i.name for i in graph_issues(by_name["pick"], "blender@5.2-lts", f, tree="geometry")] == []
    assert [i.name for i in graph_issues(by_name["pick"], "blender@5.3", f, tree="shader")] == []
