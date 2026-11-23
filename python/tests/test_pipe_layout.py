"""The printed layout of a pipe: its head on the statement's line, each step on its own line."""

from pathlib import Path

import pytest

from base_node import parse
from base_node.format import format_source
from base_node.printer import to_source

ROOT = Path(__file__).resolve().parents[2]


def printed(body, params="geometry: Geometry, o: Vector"):
    return to_source(parse(f"geometry graph g({params}) -> Geometry {{\n{body}\n}}\n"))


def test_one_step_goes_to_its_own_line():
    assert printed("  return geometry |> SetShadeSmooth()") == (
        "geometry graph g(geometry: Geometry, o: Vector) -> Geometry {\n"
        "  return geometry\n"
        "    |> SetShadeSmooth()\n"
        "}\n")


def test_every_step_including_the_first_goes_to_its_own_line():
    text = printed("  x = Cube(size: CombineXYZ(x: 2.0)) |> TransformGeometry(scale: (1.0, 1.0, 1.0))\n"
                   "  return geometry |> SetPosition(offset: o) |> SetShadeSmooth()")
    assert text == (
        "geometry graph g(geometry: Geometry, o: Vector) -> Geometry {\n"
        "  x = Cube(size: CombineXYZ(x: 2.0))\n"
        "    |> TransformGeometry(scale: (1.0, 1.0, 1.0))\n"
        "  return geometry\n"
        "    |> SetPosition(offset: o)\n"
        "    |> SetShadeSmooth()\n"
        "}\n")
    assert to_source(parse(text)) == text


def test_a_long_step_takes_one_argument_per_line():
    step = ", ".join(f"{k}: CombineXYZ(x: 1.0, y: 1.0, z: 1.0)" for k in ("translation", "rotation", "scale"))
    text = printed(f"  return geometry |> TransformGeometry({step}) |> SetShadeSmooth()")
    assert text == (
        "geometry graph g(geometry: Geometry, o: Vector) -> Geometry {\n"
        "  return geometry\n"
        "    |> TransformGeometry(\n"
        "      translation: CombineXYZ(x: 1.0, y: 1.0, z: 1.0),\n"
        "      rotation: CombineXYZ(x: 1.0, y: 1.0, z: 1.0),\n"
        "      scale: CombineXYZ(x: 1.0, y: 1.0, z: 1.0))\n"
        "    |> SetShadeSmooth()\n"
        "}\n")
    assert to_source(parse(text)) == text


def test_a_long_head_spreads_further_in_than_the_steps():
    head = ", ".join(f"input_{i}: CombineXYZ(x: 1.0, y: 2.0)" for i in range(4))
    text = printed(f"  return Join({head}) |> SetShadeSmooth()")
    assert "  return Join(\n      input_0: CombineXYZ(x: 1.0, y: 2.0),\n" in text
    assert "      input_3: CombineXYZ(x: 1.0, y: 2.0))\n    |> SetShadeSmooth()\n" in text
    assert to_source(parse(text)) == text


@pytest.mark.parametrize("body", [
    "  return SetPosition(geometry |> SubdivideMesh(level: 2), offset: o)",
    "  x = (geometry |> SubdivideMesh(level: 1)) + (geometry |> SetShadeSmooth())\n  return geometry",
    "  x = (geometry |> SeparateGeometry(selection: true).selection).x\n  return geometry",
    "  return (a: geometry |> SetShadeSmooth(), b: geometry |> SubdivideMesh(level: 2))",
    "  x = CombineXYZ(x: 1.0, y: 1.0, z: 1.0) + (1.0, 2.0, 3.0) * 2.0\n  return geometry",
])
def test_what_fits_stays_on_its_line(body):
    text = printed(body)
    assert text.count("\n") == 2 + body.count("\n") + 1, text
    assert to_source(parse(text)) == text


def body_of(text):
    return text.split("{\n", 1)[1].rsplit("}\n", 1)[0]


def test_a_long_nested_pipe_spreads_one_step_per_line():
    step = "SetPosition(offset: CombineXYZ(x: 1.0, y: 2.0, z: 3.0))"
    text = printed(f"  return JoinGeometry(geometry |> {step} |> {step}, geometry)")
    assert body_of(text) == (
        "  return JoinGeometry(\n"
        "    geometry\n"
        "      |> SetPosition(offset: CombineXYZ(x: 1.0, y: 2.0, z: 3.0))\n"
        "      |> SetPosition(offset: CombineXYZ(x: 1.0, y: 2.0, z: 3.0)),\n"
        "    geometry)\n")
    assert to_source(parse(text)) == text


def test_a_long_pipe_in_parentheses_keeps_them():
    step = "SetPosition(offset: CombineXYZ(x: 1.0, y: 2.0, z: 3.0))"
    text = printed(f"  x = (geometry |> {step}).geometry + (geometry |> {step} |> {step})\n  return x")
    assert body_of(text) == (
        "  x = (geometry |> SetPosition(offset: CombineXYZ(x: 1.0, y: 2.0, z: 3.0))).geometry\n"
        "    + (geometry\n"
        "      |> SetPosition(offset: CombineXYZ(x: 1.0, y: 2.0, z: 3.0))\n"
        "      |> SetPosition(offset: CombineXYZ(x: 1.0, y: 2.0, z: 3.0)))\n"
        "  return x\n")
    assert to_source(parse(text)) == text


def test_a_long_tuple_spreads_one_item_per_line():
    items = ", ".join(f"({i}.0, {i}.5, {i}.25)" for i in range(8))
    text = printed(f"  x = Points(position: ({items}))\n  return geometry")
    assert body_of(text) == (
        "  x = Points(\n"
        "    position: (\n"
        + "".join(f"      ({i}.0, {i}.5, {i}.25),\n" for i in range(7))
        + "      (7.0, 7.5, 7.25)))\n"
        "  return geometry\n")
    assert to_source(parse(text)) == text


def test_a_long_record_spreads_one_field_per_line():
    fields = ", ".join(f"field_{i}: geometry" for i in range(6))
    text = printed(f"  return ({fields})")
    assert body_of(text) == "  return (\n" + "".join(f"    field_{i}: geometry,\n" for i in range(5)) \
        + "    field_5: geometry)\n"
    assert to_source(parse(text)) == text


def test_a_long_operator_chain_breaks_before_each_operator():
    switch = "Switch[GEOMETRY](switch: o.x > 0.0, true_: SetPosition(geometry, offset: o))"
    text = printed(f"  return {switch} + {switch} - geometry")
    assert body_of(text) == (
        f"  return {switch}\n"
        f"    + {switch}\n"
        "    - geometry\n")
    assert to_source(parse(text)) == text


def test_a_first_operand_too_long_spreads_further_in_than_the_operators():
    long = "SetPosition(geometry, offset: CombineXYZ(x: o.x, y: o.y, z: o.z), selection: o.x > 0.0)"
    text = printed(f"  return {long} * {long}")
    assert body_of(text) == (
        f"  return {long}\n"
        f"    * {long}\n")
    text = printed(f"  return ({long}, {long}).x + o")
    assert body_of(text) == (
        "  return (\n"
        f"      {long},\n"
        f"      {long}).x\n"
        "    + o\n")
    assert to_source(parse(text)) == text


def test_a_call_through_a_chosen_output_spreads():
    args = ", ".join(f"input_{i}: CombineXYZ(x: 1.0)" for i in range(4))
    text = printed(f"  return SeparateGeometry(geometry, {args}).selection")
    assert body_of(text) == (
        "  return SeparateGeometry(\n"
        "    geometry,\n"
        + "".join(f"    input_{i}: CombineXYZ(x: 1.0),\n" for i in range(3))
        + "    input_3: CombineXYZ(x: 1.0)).selection\n")
    assert to_source(parse(text)) == text


def test_a_long_param_spreads_its_options():
    text = printed("  return geometry", 'geometry: Geometry, o: Vector(subtype: TRANSLATION, description: '
                   '"How far each point moves, along each axis of the object") = (1.0, 1.0, 1.0)')
    assert text.startswith(
        "geometry graph g(\n"
        "    geometry: Geometry,\n"
        "    o: Vector(\n"
        "      subtype: TRANSLATION,\n"
        '      description: "How far each point moves, along each axis of the object") = (1.0, 1.0, 1.0)\n'
        ") -> Geometry {\n"), text
    assert to_source(parse(text)) == text


def test_no_line_is_wider_than_the_limit_but_for_one_long_token():
    deep = "geometry"
    for i in range(12):
        deep = f"SetPosition({deep}, offset: CombineXYZ(x: {i}.0, y: o.y * {i}.5, z: o.z - {i}.25))"
    text = printed(f"  return {deep} + {deep}")
    assert max(len(line) for line in text.split("\n")) <= 100
    assert to_source(parse(text)) == text


def test_format_keeps_comments_by_their_code():
    source = ("geometry graph g(geometry: Geometry) -> Geometry {\n"
              "  return geometry |> SubdivideMesh(level: 2)  // finer\n"
              "    // then shade\n"
              "    |> SetShadeSmooth()  // smooth\n"
              "}\n")
    text = format_source(source)
    assert text == ("geometry graph g(geometry: Geometry) -> Geometry {\n"
                    "  return geometry\n"
                    "    |> SubdivideMesh(level: 2)  // finer\n"
                    "    // then shade\n"
                    "    |> SetShadeSmooth()  // smooth\n"
                    "}\n")
    assert format_source(text) == text


def corpus():
    return sorted((ROOT / "conformance").glob("*.bn")) + sorted((ROOT / "python" / "tests" / "fixtures").glob("*.bn"))


@pytest.mark.parametrize("path", corpus(), ids=lambda p: str(p.relative_to(ROOT)))
def test_printing_is_a_fixed_point(path):
    once = to_source(parse(path.read_text(encoding="utf-8"), str(path)))
    assert to_source(parse(once, str(path))) == once
    formatted = format_source(path.read_text(encoding="utf-8"), str(path))
    assert format_source(formatted, str(path)) == formatted
