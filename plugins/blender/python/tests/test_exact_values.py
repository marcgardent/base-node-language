"""What a tree holds, the checker takes from the text as it is: a set of enum values, infinity and NaN, a
graph that returns nothing (spec/reference.md, 2 and 5)."""

import math

import pytest

from base_node_blender import BnError, compile_source
from base_node_blender.backend import BackendSchema
from base_node_blender.ir import GROUP_OUTPUT


@pytest.fixture(scope="module")
def schema():
    return BackendSchema("5.3")


def graph(body, head="geometry graph g(geometry: Geometry) -> Geometry {"):
    return f"{head}\n{body}\n}}\n"


def nodes(src, schema, idname):
    g = compile_source(src, schema, "t.bn")[-1]
    return [n for n in g.nodes if n.bl_idname == idname]


def errors(src, schema):
    with pytest.raises(BnError) as e:
        compile_source(src, schema, "t.bn")
    return [d.message for d in e.value.diagnostics]


@pytest.mark.parametrize("written, held", [("(LEFT,)", ("LEFT",)), ("(RIGHT, LEFT)", ("LEFT", "RIGHT")),
                                           ("()", ())])
def test_a_flag_set_is_a_tuple_of_its_values(schema, written, held):
    src = graph(f"  return SetHandleType[mode: {written}](geometry)")
    node, = nodes(src, schema, "GeometryNodeCurveSetHandles")
    assert node.props["mode"] == held


@pytest.mark.parametrize("written, message", [
    ("LEFT", "mode is a set of values, in parentheses: mode: (LEFT,)"),
    ("(LEFT, UP)", "mode: unknown UP; values: LEFT, RIGHT"),
    ("(LEFT, LEFT)", "mode: a value given twice"),
])
def test_a_flag_set_is_checked(schema, written, message):
    assert errors(graph(f"  return SetHandleType[mode: {written}](geometry)"), schema) == [message]


def test_infinity_and_nan_are_values(schema):
    src = graph("  return SetPosition(geometry, offset: CombineXYZ(x: inf, y: -inf, z: nan))")
    node, = nodes(src, schema, "ShaderNodeCombineXYZ")
    x, y, z = (node.values[k] for k in ("X", "Y", "Z"))
    assert x == math.inf and y == -math.inf and math.isnan(z)


def test_minus_zero_stays(schema):
    node, = nodes(graph("  return SetPosition(geometry, offset: CombineXYZ(x: -0.0))"), schema, "ShaderNodeCombineXYZ")
    assert math.copysign(1.0, node.values["X"]) == -1.0


def test_a_graph_without_return_has_no_group_output(schema):
    g = compile_source("geometry graph g() -> () {\n  p = Position()\n}\n", schema, "t.bn")[-1]
    assert GROUP_OUTPUT not in {n.id for n in g.nodes}
    g = compile_source("geometry graph g() -> () {\n  return ()\n}\n", schema, "t.bn")[-1]
    assert GROUP_OUTPUT in {n.id for n in g.nodes}
    warnings = []
    g = compile_source("geometry graph g() -> Float {\n  p = Position()\n}\n", schema, "t.bn", warnings=warnings)[-1]
    assert GROUP_OUTPUT not in {n.id for n in g.nodes}
    assert [str(w) for w in warnings] == [
        "t.bn:1:1  warning: no return in 'g': its tree has no Group Output node, its outputs give nothing"]
