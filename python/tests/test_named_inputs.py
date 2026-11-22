"""A node's inputs go by name (spec/reference.md, 5, Inputs), but those the canonical form leaves unnamed:
the geometry a node works on, the items of a switch, the values of a multi-input and the inputs before
them. A graph, a group of the file and a function take their values by position. The naming pass
writes the names."""

import pytest

from fake_schema import FakeSchema, S
from base_node_blender import BnError, compile_source, format_source
from base_node_blender.naming import call_at, name_inputs
from base_node_blender.schema import GroupSpec, NodeSpec, Prop

HEAD = "geometry graph g(geometry: Geometry, a: Float, b: Float, i: Int, v: Vector, on: Bool) -> Geometry {\n"


def graph(body, head=HEAD):
    return f"{head}{body}\n}}\n"


class Wider(FakeSchema):
    """The fake nodes, with a node that has an input before its multi-input, and a compositor tree whose
    nodes work on an image."""

    def node(self, kind, name):
        if name == "MeshBoolean" and kind == "geometry":
            return NodeSpec("MeshBoolean", "GeometryNodeMeshBoolean",
                            {"operation": Prop("operation", "ENUM", ("INTERSECT", "UNION", "DIFFERENCE"))})
        if name == "Blur" and kind == "compositor":
            return NodeSpec("Blur", "CompositorNodeBlur")
        if kind == "compositor" and name in ("Math", "CombineXYZ"):
            return super().node("geometry", name)
        return super().node(kind, name)

    def node_names(self, kind):
        return super().node_names("geometry") + ["MeshBoolean", "Blur"]

    def sockets(self, kind, spec, props):
        if spec.name == "MeshBoolean":
            return ([S("Mesh 1", "Geometry"), S("Mesh 2", "Geometry", multi=True), S("Self Intersection", "Bool")],
                    [S("Mesh", "Geometry")])
        if spec.name == "Blur":
            return [S("Image", "Color"), S("Size", "Float")], [S("Image", "Color")]
        return super().sockets(kind, spec, props)


@pytest.fixture
def wider():
    return Wider()


def errors(src, schema):
    with pytest.raises(BnError) as e:
        compile_source(src, schema, "t.bn")
    return [str(d) for d in e.value.diagnostics]


def compiles(src, schema):
    return compile_source(src, schema, "t.bn")


# The error, at the value, with the name to write

def test_a_value_by_position_is_an_error_that_tells_the_name(schema):
    assert errors(graph("  x = Math[ADD](a, b)\n  return geometry"), schema) == [
        "t.bn:2:17  Math: input 1 is 'Value'; write it by name, Math[ADD](Value: a, …)",
        "t.bn:2:20  Math: input 2 is 'Value_001'; write it by name, Math[ADD](…, Value_001: b)"]


def test_the_name_is_the_key_of_the_input_the_value_goes_to(schema):
    # A unary operation has one Value: its key; a long value is not repeated
    assert errors(graph("  x = Math[SINE](a * b + a * b + a * b + a)\n  return geometry"), schema) == [
        "t.bn:2:18  Math: input 1 is 'value'; write it by name, Math[SINE](value: …)"]
    assert errors(graph("  x = CombineXYZ(a, z: b)\n  return geometry"), schema) == [
        "t.bn:2:18  CombineXYZ: input 1 is 'x'; write it by name, CombineXYZ(x: a, …)"]


def test_the_named_form_builds(schema):
    g = compiles(graph("  x = Math[ADD](Value: a, Value_001: b)\n  return geometry"), schema)[0]
    math = next(n for n in g.nodes if n.bl_idname == "ShaderNodeMath")
    assert [ident for ident, _l in math.links] == ["Value", "Value_001"]


# What the canonical form leaves unnamed

def test_the_geometry_a_node_works_on_goes_first_unnamed(schema):
    compiles(graph("  return SetPosition(geometry, offset: v)"), schema)
    compiles(graph("  return geometry |> SubdivideMesh(level: 2) |> SetPosition(offset: v)"), schema)
    # Its next inputs go by name
    assert errors(graph("  return SetPosition(geometry, on)"), schema) == [
        "t.bn:2:32  SetPosition: input 2 is 'selection'; write it by name, SetPosition(…, selection: on)"]
    assert errors(graph("  return geometry |> SubdivideMesh(2)"), schema) == [
        "t.bn:2:36  SubdivideMesh: input 2 is 'level'; write it by name, SubdivideMesh(…, level: 2)"]


def test_a_pipe_passes_on_what_a_node_works_on_only(schema):
    assert errors(graph("  x = v |> SeparateXYZ()\n  return geometry"), schema) == [
        "t.bn:2:12  SeparateXYZ: input 1 is 'vector'; write it by name, SeparateXYZ(vector: …)"]


def test_the_image_a_compositor_node_works_on_goes_first_unnamed(wider):
    head = "compositor graph c(image: Color, a: Float) -> Color {\n"
    compiles(graph("  return image |> Blur(size: a)", head), wider)
    compiles(graph("  return Blur(image, size: a)", head), wider)
    # A value written in place is no image a node works on: it is named, as a tree reads it back
    assert errors(graph("  return Blur((1.0, 0.0, 0.0, 1.0), size: a)", head), wider)[0].startswith(
        "t.bn:2:15  Blur: input 1 is 'image'; write it by name, Blur(image: (1.0, 0.0, 0.0, 1.0), …)")
    # A shader tree has no such input: a node of a shader tree names them all
    assert errors(graph("  return Blur(image, size: a)", "shader graph s(image: Color, a: Float) -> Color {\n"),
                  wider) != []


def test_the_items_of_a_switch_go_by_position(schema):
    compiles(graph("  x = IndexSwitch(i, a, b, 2.0)\n  return geometry"), schema)


def test_the_values_of_a_multi_input_and_the_inputs_before_it_go_by_position(schema, wider):
    compiles(graph("  return JoinGeometry(geometry, geometry, geometry)"), schema)
    compiles(graph("  return MeshBoolean(geometry, geometry, geometry, self_intersection: on).mesh"), wider)
    compiles(graph("  return MeshBoolean(mesh_1: geometry, mesh_2: geometry, mesh_2: geometry).mesh"), wider)


# What takes its values by position

def test_a_graph_a_group_and_a_function_take_values_by_position(schema):
    src = ("geometry graph lift(geometry: Geometry, h: Float) -> Geometry {\n"
           "  return SetPosition(geometry, offset: CombineXYZ(z: h))\n}\n\n"
           + graph("  x = max(a, b) + sin(a) + pow(a, 2.0)\n  return lift(geometry, x)"))
    compiles(src, schema)
    schema.existing["bump"] = GroupSpec("Bump", (("Geometry", "Geometry"), ("Height", "Float")),
                                        (("Geometry", "Geometry"),))
    compiles(graph("  return bump(geometry, a)"), schema)


def test_zones_operators_and_ternaries_are_as_they_are(schema):
    compiles(graph("  r = repeat(3, g: geometry) -> {\n    return (g: g |> SubdivideMesh(level: 1))\n  }\n"
                   "  e = foreach[FACE](r, p: Position()) -> {\n    return (p: p)\n  }\n"
                   "  h = on ? a : b * 2.0\n"
                   "  return r |> SetPosition(offset: CombineXYZ(z: h))"), schema)


def test_the_fixed_inputs_of_a_bundle_and_a_closure_go_by_position(schema):
    compiles(graph("  n = CombineBundle(h: a)\n  s = SeparateBundle(n) -> (h: Float)\n"
                   "  return geometry |> SetPosition(offset: CombineXYZ(z: s.h))"), schema)


# The naming pass

TEXT = """// Lifts a mesh
geometry graph g(geometry: Geometry, a: Float, b: Float, v: Vector) -> Geometry {
  // the height
  h = Math[ADD](a, b)  // a sum

  p = v |> SeparateXYZ()
  return geometry
    |> SetPosition(on_top(a), offset: CombineXYZ(p.x, z: h))
}

geometry graph on_top(x: Float) -> Bool {
  return x > 0.5
}
"""

NAMED = """// Lifts a mesh
geometry graph g(geometry: Geometry, a: Float, b: Float, v: Vector) -> Geometry {
  // the height
  h = Math[ADD](Value: a, Value_001: b)  // a sum

  p = SeparateXYZ(vector: v)
  return geometry
    |> SetPosition(selection: on_top(a), offset: CombineXYZ(x: p.x, z: h))
}

geometry graph on_top(x: Float) -> Bool {
  return x > 0.5
}
"""


def test_the_pass_names_the_values_and_keeps_comments_and_blank_lines(schema):
    assert name_inputs(TEXT, schema) == NAMED
    compiles(NAMED, schema)


def test_the_pass_is_idempotent_and_prints_as_the_formatter(schema):
    assert name_inputs(NAMED, schema) == NAMED
    messy = "geometry graph f(geometry: Geometry) -> Geometry {\n  return   geometry|>SubdivideMesh( level:1 )\n}\n"
    assert name_inputs(messy, schema) == format_source(messy)


def test_the_pass_names_what_it_can_in_a_text_with_other_errors(schema):
    src = graph("  x = Math[ADD](a, nope)\n  return geometry")
    assert "Math[ADD](Value: a, Value_001: nope)" in name_inputs(src, schema)


def test_the_pass_names_the_call_under_the_cursor_only(schema):
    src = graph("  x = Math[ADD](a, CombineXYZ(a, b).x)\n  return geometry")
    # On the inner call's values, or on its name
    for col in (34, 23):
        assert "Math[ADD](a, CombineXYZ(x: a, y: b).x)" in name_inputs(src, schema, at=(2, col))
    # On the outer call's
    assert "Math[ADD](Value: a, Value_001: CombineXYZ(a, b).x)" in name_inputs(src, schema, at=(2, 18))
    assert call_at(src, 1, 3) is None


def test_the_pass_refuses_a_text_that_does_not_parse(schema):
    with pytest.raises(BnError):
        name_inputs("geometry graph g( {\n", schema)
