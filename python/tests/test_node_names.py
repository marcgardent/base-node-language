"""A node is written by its UI name in one word (spec/reference.md, Node names)."""

import pytest

from base_node_blender import BnError, compile_source
from base_node_blender.schema import loose, node_name


def errors(source, schema):
    with pytest.raises(BnError) as err:
        compile_source(source, schema, "t.bn")
    return [str(d) for d in err.value.diagnostics]


def graph(body):
    return f"geometry graph g(geometry: Geometry, t: Float) -> Geometry {{\n{body}\n}}"


@pytest.mark.parametrize("label, name", [
    ("Principled BSDF", "PrincipledBSDF"),
    ("Noise Texture", "NoiseTexture"),
    ("Separate XYZ", "SeparateXYZ"),
    ("Set Position", "SetPosition"),
    ("Math", "Math"),
    ("Evaluate at Index", "EvaluateAtIndex"),
    ("Mix (Legacy)", "MixLegacy"),
    ("Hue/Saturation/Value", "HueSaturationValue"),
    ("Brightness/Contrast", "BrightnessContrast"),
    ("Anti-Aliasing", "AntiAliasing"),
    ("Field Min & Max", "FieldMinAndMax"),
    ("Bézier Segment", "BezierSegment"),
    ("RGB to BW", "RGBToBW"),
    ("Stabilize 2D", "Stabilize2D"),
    # A colliding pair: in a compositor tree both read RGBCurves; the one of its Add menu takes it
    ("RGB Curves", "RGBCurves"),
])
def test_the_ui_label_in_one_word(label, name):
    assert node_name(label) == name


def test_a_label_that_starts_with_a_digit_is_no_identifier():
    # The host keeps the former name of such a node (3D Cursor stays Tool3DCursor)
    assert not node_name("3D Cursor")[:1].isalpha()


def test_a_name_no_node_has_is_unknown(schema):
    assert errors(graph("  m = MeshGrid(size_x: 1)\n  return m.mesh"), schema) == [
        "t.bn:2:7  unknown node 'MeshGrid' in a geometry tree; did you mean Grid?"]
    assert errors(graph("  m = GeometryNodeMeshGrid(size_x: 1)\n  return m.mesh"), schema) == [
        "t.bn:2:7  unknown node 'GeometryNodeMeshGrid' in a geometry tree"]


@pytest.mark.parametrize("written", ["set_position", "setposition", "SETPOSITION", "Set_Position"])
def test_a_suggestion_reads_the_ui_name_case_and_spaces_aside(schema, written):
    assert errors(graph(f"  return {written}(geometry)"), schema) == [
        f"t.bn:2:10  unknown node '{written}' in a geometry tree; did you mean SetPosition?"]


def test_loose_drops_case_spaces_and_underscores():
    assert loose("noise texture") == loose("Noise_Texture") == loose("NoiseTexture") == "noisetexture"
