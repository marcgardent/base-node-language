"""`cond ? a : b`: its syntax and layout, and the node it is: a Switch of the type of its branches in a
geometry tree, a Mix by a condition where a Switch takes one value for a whole image."""

import pytest

from base_node import ast
from base_node_blender import BnError, compile_source, format_source, parse
from base_node.printer import to_source
from base_node_blender.typecheck import branches_type
from fake_schema import FakeSchema

SIG = "geometry graph g(geometry: Geometry, a: Float, b: Float, i: Int, v: Vector, on: Bool) -> Geometry"


def graph(body, sig=SIG):
    return f"{sig} {{\n{body}\n  return geometry\n}}\n"


def value(text):
    return parse(graph(f"  x = {text}")).graphs[0].body[0].value


def compile_one(source, schema=None):
    return compile_source(source, schema or FakeSchema(), "t.bn")[-1]


def errors(source, schema=None):
    with pytest.raises(BnError) as err:
        compile_source(source, schema or FakeSchema(), "t.bn")
    return [d.message for d in err.value.diagnostics]


def node(g, name):
    return next(n for n in g.nodes if n.name == name)


# Syntax

def test_a_ternary_binds_loosest_and_chains_to_the_right():
    e = value("a > b or on ? a + 1.0 : b * 2.0")
    assert isinstance(e, ast.Cond) and e.cond.op == "or" and e.then.op == "+" and e.orelse.op == "*"
    e = value("on ? a : a > b ? b : 0.0")
    assert isinstance(e.orelse, ast.Cond) and isinstance(e.orelse.cond, ast.BinOp)
    e = value("on ? a > b ? 1.0 : 2.0 : 3.0")
    assert isinstance(e.then, ast.Cond) and e.orelse.value == 3.0
    # Its branches are whole expressions, pipes too; the pipe before `?` is the condition's
    e = value("on ? geometry |> SubdivideMesh() : geometry")
    assert isinstance(e.then, ast.Pipe)
    e = value("(on ? geometry : geometry) |> SubdivideMesh()")
    assert isinstance(e, ast.Pipe) and isinstance(e.left, ast.Cond)


def test_a_ternary_is_an_argument_by_position_or_by_name():
    e = value("Switch(on ? a : b, true_: on ? f(a) : b)")
    assert [a.name for a in e.args] == [None, "true_"] and all(isinstance(a.value, ast.Cond) for a in e.args)


@pytest.mark.parametrize("text, message", [
    ("on ? a", "expected ':' and the value when the condition is false, cond ? a : b, found"),
    ("on ? : b", "expression expected, found ':'"),
    ("on ? a : ", "expression expected, found"),
])
def test_a_ternary_wants_both_branches(text, message):
    with pytest.raises(BnError) as err:
        parse(graph(f"  x = {text}"))
    assert message in err.value.diagnostics[0].message


@pytest.mark.parametrize("body", [
    "  x = on ? a : b",
    "  x = on ? a : a > b ? b : 0.0",
    "  x = on ? (a > b ? 1.0 : 2.0) : 3.0",
    "  x = (on ? a > 0.0 : a > b) ? 1.0 : 2.0",
    "  x = (on ? a : b) * 2.0 + (a > b ? 1.0 : 0.0)",
    "  x = -(on ? a : b)",
    "  x = not (on ? on : a > b)",
    "  x = on ? SubdivideMesh(geometry) |> SetShadeSmooth() : geometry",
    "  x = (on ? geometry : SubdivideMesh(geometry))\n    |> SetShadeSmooth()",
    "  x = Switch(switch: on ? a : b, true_: on ? (1.0, 0.0, 0.0) : v)",
    "  x = SeparateXYZ(vector: on ? v : (0.0, 0.0, 1.0)).z",
])
def test_a_ternary_prints_back_with_the_parentheses_it_needs(body):
    assert to_source(parse(graph(body))) == graph(body)
    assert format_source(graph(body)) == graph(body)


def test_parentheses_that_change_nothing_go():
    assert format_source(graph("  x = (on) ? (a) : (a > b ? b : 0.0)")) == graph("  x = on ? a : a > b ? b : 0.0")
    assert format_source(graph("  x = on?a:b")) == graph("  x = on ? a : b")


def test_a_long_ternary_breaks_before_each_branch():
    long = ("  x = a_condition_with_a_long_name_of_its_own > another_long_name_for_the_other_side ? "
            "the_first_branch_and_its_long_name * 2.0 : the_second_branch_and_its_long_name + 1.0")
    assert format_source(graph(long)) == graph(
        "  x = a_condition_with_a_long_name_of_its_own > another_long_name_for_the_other_side\n"
        "    ? the_first_branch_and_its_long_name * 2.0\n"
        "    : the_second_branch_and_its_long_name + 1.0")
    # A branch too long for its own line follows the same rule, one step further in
    nested = format_source(graph(
        "  x = on ? a : a_condition_with_a_long_name_of_its_own > another_long_name_for_the_other_side ? "
        "the_first_branch_and_its_long_name * 2.0 + another_term_to_make_it_long : the_second_branch + 1.0"))
    assert nested == graph(
        "  x = on\n"
        "    ? a\n"
        "    : a_condition_with_a_long_name_of_its_own > another_long_name_for_the_other_side\n"
        "      ? the_first_branch_and_its_long_name * 2.0 + another_term_to_make_it_long\n"
        "      : the_second_branch + 1.0")
    assert format_source(nested) == nested


def test_comments_stay_beside_a_ternary():
    src = graph("  // which one\n  x = on ? a : b  // this one")
    assert format_source(src) == src


# The node it is

def switch(g, name="x"):
    n = node(g, name)
    assert n.bl_idname == "GeometryNodeSwitch"
    return n.props, n.values, [i for i, _l in n.links]


def test_a_ternary_is_a_switch_of_the_type_of_its_branches():
    assert switch(compile_one(graph("  x = on ? a : b"))) == ({}, {}, ["Switch", "False", "True"])
    assert switch(compile_one(graph("  x = a > b ? 1.0 : 0.0"))) == ({}, {"False": 0.0, "True": 1.0}, ["Switch"])
    assert switch(compile_one(graph("  x = on ? i : 0")))[0] == {"input_type": "INT"}
    assert switch(compile_one(graph("  x = on ? v : (0.0, 0.0, 1.0)")))[0] == {"input_type": "VECTOR"}
    assert switch(compile_one(graph("  x = on ? (1.0, 0.0, 0.0, 1.0) : (0.0, 0.0, 1.0)")))[0] == {"input_type": "RGBA"}
    assert switch(compile_one(graph('  x = on ? "yes" : "no"')))[0] == {"input_type": "STRING"}
    assert switch(compile_one(graph("  x = on ? SubdivideMesh(geometry) : geometry")))[0] == {"input_type": "GEOMETRY"}
    # A linked value decides before a literal, as for Switch(…)
    assert switch(compile_one(graph("  x = on ? 0 : a"))) == ({}, {"True": 0}, ["Switch", "False"])


def test_each_part_of_a_ternary_is_built_once():
    g = compile_one(graph("  x = sin(a) > 0.0 ? cos(a) : sqrt(b)"))
    assert sorted(n.props["operation"] for n in g.nodes if n.bl_idname == "ShaderNodeMath") == \
        ["COSINE", "SINE", "SQRT"]
    # The same nodes as the call
    call = compile_one(graph("  x = Switch(switch: sin(a) > 0.0, false_: sqrt(b), true_: cos(a))"))
    assert switch(g) == switch(call) and len(g.nodes) == len(call.nodes)


def test_a_ternary_s_errors_name_its_parts():
    assert errors(graph("  x = on ? a : geometry")) == [
        "the value of '? :' when true expects Geometry, receives Float (a)"]
    assert errors(graph("  x = geometry ? a : b")) == [
        "the condition of '? :' expects Bool, receives Geometry (geometry)"]
    assert errors(graph("  x = on ? a : nothing")) == ["unknown name 'nothing'"]


class Images(FakeSchema):
    """A tree whose Switch takes one value for a whole image: every node of the fake tree, under the
    name of a shader tree."""

    def node(self, kind, name):
        return super().node("geometry", name)


def mix(g, name="x"):
    n = node(g, name)
    assert n.bl_idname == "ShaderNodeMix"
    return n.props, n.values, [i for i, _l in n.links]


SHADER = "shader graph g(a: Float, b: Float, i: Int, v: Vector, on: Bool) -> Float"


def shader(body):
    return f"{SHADER} {{\n{body}\n  return a\n}}\n"


def test_where_a_switch_takes_one_value_a_ternary_is_a_mix():
    g = compile_one(shader("  x = a > b ? a : b"), Images())
    assert mix(g) == ({"data_type": "FLOAT"}, {}, ["Factor_Float", "A_Float", "B_Float"])
    # The value when false is A, the one a factor of 0 gives
    assert mix(compile_one(shader("  x = on ? 1.0 : 2.0"), Images()))[1] == {"A_Float": 2.0, "B_Float": 1.0}
    assert mix(compile_one(shader("  x = on ? v : (0.0, 0.0, 1.0)"), Images()))[0] == {"data_type": "VECTOR"}
    assert mix(compile_one(shader("  x = on ? (1.0, 0.0, 0.0, 1.0) : (0.0, 0.0, 1.0)"), Images()))[0] == \
        {"data_type": "RGBA"}
    # A whole number and a Bool go in as Float
    assert mix(compile_one(shader("  x = on ? i : 0"), Images()))[0] == {"data_type": "FLOAT"}
    assert not [n for n in g.nodes if n.bl_idname == "GeometryNodeSwitch"]


def test_a_mix_wants_a_condition():
    assert errors(shader("  x = a ? 1.0 : 2.0"), Images()) == [
        "the condition of '? :' is a Float: in a shader tree it is built with Mix, which blends by any number "
        "and does not choose. Write a comparison (f > 0.5 ? a : b), or call Mix(factor: f, …) to blend"]
    # A comparison by its name is one still
    compile_one(shader("  hot = a > b\n  x = hot ? 1.0 : 2.0"), Images())


def test_a_mix_carries_a_few_types():
    assert errors(shader('  x = on ? "yes" : "no"'), Images()) == [
        "'? :' chooses between Float, Vector, Color and Rotation in a shader tree, not String"]


def test_the_type_of_the_branches():
    assert branches_type([("False", "Float", True, 0), ("True", "Int", False, 0)]) == "Float"
    assert branches_type([("False", "Int", False, 0), ("True", "Vector", True, 0)]) == "Vector"
    assert branches_type([("False", "Vector", True, 0), ("True", "Vector", False, 3)]) == "Vector"
    assert branches_type([("False", "Vector", False, 3), ("True", "Color", False, 4)]) == "Color"
    assert branches_type([("False", None, False, 0), ("True", None, False, 0)]) is None
