"""The target `blade`: Blade's Pixel Nodes, which a text of `blender` reaches through its translator
and its bridge (spec/blade.md). The same cases as rust/tests/blade.rs."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from base_node.printer import to_source
from base_node_blender import (check_target, check_targets, header, infer, load_target, parse, promise_names,
                               target_names, translate)
from base_node_blender.targets import _bridge, accepted, catalog, translation_issues

ROOT = Path(__file__).resolve().parents[2]
BLENDER = Path(__import__("base_node_blender").__file__).resolve().parents[2]


def test_blade_is_a_target_of_its_own():
    assert "blade" in target_names() and "blade" in promise_names()
    assert accepted("blade", "node") == set(load_target("blade").nodes)
    for name in ("blade@1.0", "blade gltf"):
        with pytest.raises(ValueError, match="unknown target"):
            load_target(name)


def test_what_blade_translates_from_is_the_compositor_s():
    # Blade's own nodes are its business; what it translates from must be the compositor's
    compositor = {n["name"] for n in catalog(BLENDER)["kinds"]["compositor"]}
    assert set(load_target("blade").translators["blender"]["nodes"]) <= compositor


def test_the_translator_leads_to_nodes_of_blade():
    t = load_target("blade")
    for source, tr in t.translators.items():
        assert source in target_names(), f"blade translates from an unknown target {source}"
        for dst in tr.get("nodes", {}).values():
            node = dst if isinstance(dst, str) else dst["node"]
            if "::" in node:
                assert _bridge(t, node) is not None, f"{node} is not a graph of its bridges"
            else:
                assert node in t.nodes, f"{node} is not one of its nodes"
        assert set(tr.get("kinds", {}).values()) <= set(t.kinds)


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


COMPOSITE = """compositor graph soften(image: Color, size: Float = 4.0) -> Color {
  blurred = Blur(image, size: size)
  return Mix(factor: 0.5, a: image, b: blurred)
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


PAINT = """compositor graph paint(image: Color) -> Color {
  soft = Kuwahara(image, size: 8.0)
  return Mix(factor: 0.5, a: image, b: Kuwahara(soft))
}
"""

PAINTED = """use blender_interop

pixel graph paint(image: Color) -> Color {
  soft = blender_interop::kuwahara(image, size: 8.0)
  return Mix(factor: 0.5, a: image, b: blender_interop::kuwahara(soft))
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


def test_what_inference_holds():
    inf = infer(parse(COMPOSITE))
    assert list(inf.fits.items()) == [("blade", "blender"), ("blender", None)]
    assert inf.graphs == [("soften", ["blender"])]
    assert inf.lines() == ["Compatible: blender, blade (translated from blender)"]


def test_a_translator_renames_a_node():
    f = parse("compositor graph g(image: Color) -> Color {\n  return RGBCurves(image)\n}\n")
    assert translate(f, "blender", "blade").graphs[0].body[0].value.name == "Curves"


def test_a_translator_renames_inputs_and_settings():
    f = parse(
        "compositor graph g(image: Color) -> Color {\n"
        "  blurred = Blur(image, size: 4.0)\n"
        "  mixed = MixLegacy[MULTIPLY](color1: image, color2: blurred)\n"
        "  return ColorRamp[color_ramp: Ramp((0.0, (0.0, 0.0, 0.0, 1.0)), (1.0, (1.0, 1.0, 1.0, 1.0)))](factor: mixed)\n"
        "}\n"
    )
    text = to_source(translate(f, "blender", "blade"))
    assert "Blur(image, radius: 4.0)" in text
    # A setting by position stays as it is written, one by name takes its new name
    assert "Mix[MULTIPLY](a: image, b: blurred)" in text
    assert "ColorRamp[ramp: Ramp((0.0, (0.0, 0.0, 0.0, 1.0)), (1.0, (1.0, 1.0, 1.0, 1.0)))](" in text
    assert "image: mixed)" in text


def test_what_the_editor_shows():
    lines = infer(parse(COMPOSITE)).lines()
    assert lines[0].startswith("Compatible: blender")
    assert "blade (translated from blender)" in lines[0]
    assert not any(line.startswith("Outside blender ") for line in lines)


def test_the_head_promises_blade():
    h = header('// @target "blender@5.3  gltf", blade\n\ngeometry graph g() -> Float {\n  return 1.0\n}\n')
    assert h.target == ["blender@5.3 gltf", "blade"]


def test_a_target_of_blender_s_library_is_not_added_again(tmp_path):
    from base_node_blender.targets import add_targets

    (tmp_path / "blade.json").write_text((ROOT / "targets" / "blade.json").read_text(encoding="utf-8"))
    with pytest.raises(ValueError, match="'blade'"):
        add_targets(tmp_path)
