"""What the checker makes of a node's settings in brackets (spec/reference.md, Expressions).

A setting by position is an enum value: it goes to the first enum setting of the node, in
Blender's order, that holds it. Every other setting is named. An argument in parentheses is an
input, always.
"""

import pytest

from base_node_blender import BnError, compile_source
from base_node_blender.schema import NodeSpec, Prop
from fake_schema import S, FakeSchema


def compile_one(source, schema):
    return compile_source(source, schema, "t.bn")[-1]


def errors(source, schema):
    with pytest.raises(BnError) as err:
        compile_source(source, schema, "t.bn")
    return [str(d) for d in err.value.diagnostics]


def graph(body, sig="geometry graph g(geometry: Geometry, t: Float) -> Geometry"):
    return f"{sig} {{\n{body}\n}}"


class Axes(FakeSchema):
    """A node with two enum settings that share their values, as Align Euler to Vector has."""

    def node(self, kind, name):
        if name == "AlignEulerToVector" and kind == "geometry":
            return NodeSpec("AlignEulerToVector", "FunctionNodeAlignEulerToVector", {
                "axis": Prop("axis", "ENUM", ("X", "Y", "Z")),
                "pivot_axis": Prop("pivot_axis", "ENUM", ("AUTO", "X", "Y", "Z")),
            })
        return super().node(kind, name)

    def sockets(self, kind, spec, props):
        if spec.name == "AlignEulerToVector":
            return [S("Rotation", "Vector"), S("Factor", "Float"), S("Vector", "Vector")], [S("Rotation", "Vector")]
        return super().sockets(kind, spec, props)


def node(src, schema, bl_idname):
    return next(n for n in compile_one(src, schema).nodes if n.bl_idname == bl_idname)


def test_an_enum_value_by_position_goes_to_the_setting_that_holds_it(schema):
    n = node(graph("  c = Compare[INT, EQUAL](a: 1, b: 2)\n  return geometry"), schema, "FunctionNodeCompare")
    assert n.props == {"data_type": "INT", "operation": "EQUAL"}
    # In any order: each value finds its own setting
    n = node(graph("  c = Compare[EQUAL, INT](a: 1, b: 2)\n  return geometry"), schema, "FunctionNodeCompare")
    assert n.props == {"data_type": "INT", "operation": "EQUAL"}


def test_a_value_two_settings_hold_goes_to_the_first():
    schema = Axes()
    n = node(graph("  r = AlignEulerToVector[X, pivot_axis: Z](vector: (1.0, 0.0, 0.0))\n  return geometry"),
             schema, "FunctionNodeAlignEulerToVector")
    assert n.props == {"axis": "X", "pivot_axis": "Z"}
    # The second takes it by name
    n = node(graph("  r = AlignEulerToVector[pivot_axis: X](vector: (1.0, 0.0, 0.0))\n  return geometry"),
             schema, "FunctionNodeAlignEulerToVector")
    assert n.props == {"pivot_axis": "X"}


def test_named_settings_of_every_kind(schema):
    n = node(graph("  x = Math[ADD, use_clamp: true](Value: t, Value_001: 1.0)\n  return geometry"), schema, "ShaderNodeMath")
    assert n.props == {"operation": "ADD", "use_clamp": True}


@pytest.mark.parametrize("call, message", [
    ("Math[ADDD](Value: t, Value_001: 1.0)", "2:12  no setting of Math takes ADDD; did you mean ADD?; settings: operation"),
    ("Math[clamp: true](Value: t, Value_001: 1.0)", "2:12  Math has no setting 'clamp'; did you mean use_clamp?; "
                                  "settings: operation, use_clamp"),
    ("Math[ADD, operation: SUBTRACT](Value: t, Value_001: 1.0)", "2:17  setting 'operation' given twice"),
    ("Math[true](Value: t, Value_001: 1.0)", "2:12  Math: a setting by position is an enum value; name the others, "
                           "Math[operation: …]"),
    ("Math[use_clamp: 1.0](Value: t, Value_001: 1.0)", "2:12  use_clamp expects a boolean value"),
    ("Math[operation: 2](Value: t, Value_001: 1.0)", "2:12  operation expects a value like ADD"),
    ("Position[POINT]()", "2:16  no setting of Position takes POINT"),
    ("Position[name: 1]()", "2:16  Position has no setting 'name': it has none"),
])
def test_a_setting_says_what_is_wrong(schema, call, message):
    assert errors(graph(f"  x = {call}\n  return geometry"), schema) == [f"t.bn:{message}"]


def test_a_setting_in_parentheses_is_an_input_like_any_other(schema):
    assert errors(graph("  x = Math(Value: t, Value_001: 1.0, operation: ADD)\n  return geometry"), schema) == [
        "t.bn:2:38  Math has no input 'operation'; inputs: Value, Value_001"]


def test_only_a_node_has_settings(schema):
    src = ("geometry graph f(x: Float) -> Float {\n  return x\n}\n\n"
           "geometry graph g(geometry: Geometry, t: Float) -> Geometry {\n"
           "  a = f[ADD](t)\n  b = sin[ADD](t)\n  return geometry\n}\n")
    assert errors(src, schema) == ["t.bn:6:9  f has no settings", "t.bn:7:11  sin has no settings"]


def test_a_name_the_zone_gives_holds_a_value(schema):
    src = graph("  r = repeat(3, s: 0.0) -> {\n    m = Math[iteration](Value: s, Value_001: 1.0)\n    return (s: m)\n  }\n"
                "  return geometry")
    assert errors(src, schema) == ["t.bn:3:14  'iteration' holds a value, and no wire feeds a setting: "
                                   "give it in the parentheses, Name[SETTING](input: value)"]


def test_the_domain_of_a_foreach_is_its_setting(schema):
    for written in ("FACE", "domain: FACE"):
        g = compile_one(graph(f"  e = foreach[{written}](geometry) -> {{\n    return (mesh: element)\n  }}\n"
                              "  return geometry"), schema)
        out = next(n for n in g.nodes if n.bl_idname == "GeometryNodeForeachGeometryElementOutput")
        assert out.props == {"domain": "FACE"}
    assert errors(graph("  e = foreach[size: 2](geometry) -> {\n    return (mesh: element)\n  }\n"
                        "  return geometry"), schema) == ["t.bn:2:15  foreach has no setting 'size'; settings: domain"]


@pytest.mark.parametrize("word", ["repeat", "simulate"])
def test_repeat_and_simulate_have_no_settings(schema, word):
    count = "3, " if word == "repeat" else ""
    src = graph(f"  r = {word}[FACE]({count}s: 0.0) -> {{\n    return (s: s)\n  }}\n  return geometry")
    assert errors(src, schema) == [f"t.bn:2:7  {word} has no settings"]


# A number Blender cannot keep: a warning where it is written, and the tree holds Blender's value

def warned(body, schema):
    warnings = []
    compile_source(graph(body), schema, "t.bn", warnings=warnings)
    return [str(w) for w in warnings]


@pytest.mark.parametrize("written", ["0.1", "1e-7", "3.141593", "0.5", "16777216.0", "-2.75"])
def test_a_number_a_float_keeps_is_not_warned_of(schema, written):
    assert warned(f"  x = Math[ADD](Value: t, Value_001: {written})\n  return geometry", schema) == []


@pytest.mark.parametrize("written, kept", [("16777217.0", "16777216.0"), ("0.123456789123", "0.12345679")])
def test_a_number_a_float_cannot_keep_is_warned_of_where_it_is_written(schema, written, kept):
    assert warned(f"  x = Math[ADD](Value: t, Value_001: {written})\n  return geometry", schema) == [
        f"t.bn:2:38  warning: precision lost: {written} is stored as {kept} (IEEE 754 single precision)"]


def test_every_place_a_float_lands_is_looked_at(schema):
    src = ("geometry graph g(geometry: Geometry, t: Float = 0.123456789123 in 0.0..16777217.0) -> Geometry {\n"
           "  v = CombineXYZ(x: 0.1, y: 16777217.0, z: 0.0)\n"
           "  return geometry |> SetPosition(offset: (1.0, 2.0, 0.123456789123))\n}\n")
    warnings = []
    compile_source(src, schema, "t.bn", warnings=warnings)
    assert [(w.line, w.col, w.severity) for w in warnings] == [
        (1, 49, "warning"), (1, 72, "warning"), (2, 29, "warning"), (3, 53, "warning")]


def test_the_command_line_warns_of_a_number_too(tmp_path, capsys):
    from base_node_blender.cli import main

    path = tmp_path / "p.bn"
    path.write_text("geometry graph g(t: Float) -> Float {\n  return t * 16777217.0\n}\n", encoding="utf-8")
    assert main(["check", "--target", "blender", str(path)]) == 0
    assert capsys.readouterr().err == (
        f"{path.name}:2:14  warning: precision lost: 16777217.0 is stored as 16777216.0 (IEEE 754 single precision)\n")
