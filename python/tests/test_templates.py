"""Templates: a module's graph generic over a value's type, built once for each type it is called with."""

import pytest

from base_node_blender import BnError, compile_source, format_source, parse
from base_node_blender.schema import NodeSpec, Prop
from fake_schema import FakeSchema, S

SWITCH_TYPES = {"FLOAT": "Float", "INT": "Int", "BOOLEAN": "Bool", "VECTOR": "Vector", "RGBA": "Color",
                "ROTATION": "Rotation", "MATRIX": "Matrix", "STRING": "String"}
ATTRIBUTE_TYPES = {"FLOAT": "Float", "INT": "Int", "FLOAT_VECTOR": "Vector", "FLOAT_COLOR": "Color",
                   "BOOLEAN": "Bool", "QUATERNION": "Rotation", "FLOAT4X4": "Matrix"}
MIX_TYPES = {"FLOAT": "Float", "VECTOR": "Vector", "RGBA": "Color", "ROTATION": "Rotation"}

# Nodes whose sockets take the type of a setting, as in Blender
TYPED = {
    "Switch": (NodeSpec("Switch", "GeometryNodeSwitch", {"input_type": Prop("input_type", "ENUM", tuple(SWITCH_TYPES))}),
               "input_type", SWITCH_TYPES),
    "NamedAttribute": (NodeSpec("NamedAttribute", "GeometryNodeInputNamedAttribute",
                                {"data_type": Prop("data_type", "ENUM", tuple(ATTRIBUTE_TYPES))}),
                       "data_type", ATTRIBUTE_TYPES),
    "Mix": (NodeSpec("Mix", "ShaderNodeMix", {"data_type": Prop("data_type", "ENUM", tuple(MIX_TYPES))}),
            "data_type", MIX_TYPES),
}
# The nodes a compositor tree shares with a geometry tree here
SHARED = {"Math", "VectorMath", "CombineXYZ", "SeparateXYZ", "Mix"}


class Typed(FakeSchema):
    def node(self, kind, name):
        if kind == "compositor" and name not in SHARED:
            return None
        if name in TYPED:
            return TYPED[name][0]
        return super().node("geometry", name)

    def node_names(self, kind):
        names = super().node_names("geometry") + list(TYPED)
        return [n for n in names if kind == "geometry" or n in SHARED]

    def groups(self, kind):
        return {}

    def sockets(self, kind, spec, props):
        if spec.name not in TYPED:
            return super().sockets(kind, spec, props)
        _spec, setting, types = TYPED[spec.name]
        t = types[props.get(setting, "FLOAT")]
        if spec.name == "Switch":
            return [S("Switch", "Bool"), S("False", t), S("True", t)], [S("Output", t)]
        if spec.name == "NamedAttribute":
            return [S("Name", "String")], [S("Attribute", t), S("Exists", "Bool")]
        return [S("Factor", "Float"), S("A", t, "A_" + t), S("B", t, "B_" + t)], [S("Result", t, "Result_" + t)]


ATTRIBUTES = """\
geometry graph attribute_or<T: Float | Int | Bool | Vector | Color | Rotation | Matrix>(
    name: String,
    fallback: T
) -> (value: T) {
  a = NamedAttribute[T](name: name)
  return (value: Switch[T](switch: a.exists, false_: fallback, true_: a.attribute))
}

geometry graph twice<T: Float | Vector>(x: T) -> (y: T) {
  return (y: x + x)
}

geometry graph blend<T: Float | Vector | Color>(a: T, b: T, t: Float = 0.5) -> (value: T) {
  return (value: Mix[T](factor: t, a: a, b: b))
}

geometry graph pick<T: Float | Vector>(name: String, fallback: T) -> (value: T) {
  return (value: twice(attribute_or<T>(name, fallback).value))
}

geometry graph pair<T: Float | Vector, U: Float | Vector>(a: T, b: U) -> (a: T, b: U) {
  return (a: twice(a), b: twice(b))
}

geometry graph halve(x: Float) -> Float {
  return x / 2.0
}
"""


def loader(text=ATTRIBUTES):
    def load(name, source):
        if name != "attrs":
            raise LookupError(f"no text '{name}.bn'")
        return text, "attrs.bn"
    return load


def compile_(src, module=ATTRIBUTES):
    return compile_source(src, Typed(), "t.bn", loader(module))


def errors(src, module=ATTRIBUTES):
    with pytest.raises(BnError) as err:
        compile_(src, module)
    return [d.message for d in err.value.diagnostics]


def graph(body, params="v: Vector", out="Vector", uses="use attrs\n\n"):
    return f"{uses}geometry graph g({params}) -> {out} {{\n  {body}\n}}\n"


def by_name(graphs):
    return {g.name: g for g in graphs}


def test_a_call_builds_the_template_for_the_type_of_its_arguments():
    graphs = by_name(compile_(graph('return attribute_or("rest", v)')))
    group = graphs["attribute_or (Vector)"]
    assert (group.called_as, group.types, group.module) == ("attribute_or", ["Vector"], ("attrs", None))
    assert group.inputs == [("name", "String"), ("fallback", "Vector")]
    assert group.outputs == [("value", "Vector")]
    props = {n.bl_idname: n.props for n in group.nodes}
    # T is the value of each setting for the type, in the setting's own words
    assert props["GeometryNodeInputNamedAttribute"] == {"data_type": "FLOAT_VECTOR"}
    assert props["GeometryNodeSwitch"] == {"input_type": "VECTOR"}
    call = next(n for n in graphs["g"].nodes if n.group)
    assert call.group == "attribute_or (Vector)"
    # The template itself is no group
    assert "attribute_or" not in graphs


def test_one_group_for_each_type_shared_by_every_caller():
    src = ("use attrs (attribute_or)\n\n"
           "geometry graph a(v: Vector, c: Color) -> Vector {\n"
           '  k = attribute_or("tint", c)\n  return attribute_or("rest", v)\n}\n\n'
           "geometry graph b(v: Vector) -> Vector {\n"
           '  return attribute_or("rest", v)\n}\n')
    names = [g.name for g in compile_(src)]
    assert names == ["attribute_or (Color)", "attribute_or (Vector)", "a", "b"]


def test_the_type_written_wins():
    graphs = by_name(compile_(graph("return attribute_or<Color>(\"tint\", v)", out="Color")))
    assert graphs["attribute_or (Color)"].types == ["Color"]
    assert {n.props.get("input_type") for n in graphs["attribute_or (Color)"].nodes} >= {"RGBA"}


def test_a_literal_gives_its_type_when_nothing_linked_does():
    graphs = by_name(compile_(graph('return attribute_or("w", 2.0)', params="", out="Float")))
    assert "attribute_or (Float)" in graphs
    graphs = by_name(compile_(graph('return attribute_or("p", (0.0, 0.0, 1.0))', params="")))
    assert "attribute_or (Vector)" in graphs
    # A linked value decides before a literal
    graphs = by_name(compile_(graph("return blend(v, (1.0, 0.0, 0.0))")))
    assert "blend (Vector)" in graphs


def test_a_type_out_of_the_constraint_is_refused():
    assert errors(graph("return twice(2)", params="", out="Float")) == [
        "twice: T cannot be Int; T is one of Float, Vector"]
    assert errors(graph("return twice<Color>(v)")) == [
        "twice: T cannot be Color; T is one of Float, Vector"]


def test_arguments_that_disagree_are_refused():
    assert errors(graph("return blend(v, c)", params="v: Vector, c: Color")) == [
        "blend: T is Vector by 'a' and Color by 'b'; write the type, as blend<Vector>(…)"]


def test_a_call_that_gives_no_type_is_refused():
    assert errors(graph('return attribute_or(name: "x")', params="", out="Float")) == [
        "attribute_or: write the type of T, as attribute_or<Float>(…); no argument gives it"]


def test_the_number_of_types():
    assert errors(graph("return twice<Float, Vector>(v)")) == ["twice takes 1 type(s) (T), not 2"]
    graphs = by_name(compile_(graph("p = pair(v, 1.0)\n  return v")))
    assert "pair (Vector, Float)" in graphs
    assert {"twice (Vector)", "twice (Float)"} <= set(graphs)


def test_types_given_to_what_is_no_template():
    assert errors(graph("return halve<Float>(1.0)", params="", out="Float")) == [
        "'halve' is not a template: it takes no type"]
    assert errors(graph("return CombineXYZ<Float>(x: 1.0)", params="")) == [
        "'CombineXYZ' is not a template: it takes no type"]


def test_a_template_calls_another_with_its_own_type():
    graphs = by_name(compile_(graph('return pick("rest", v)')))
    assert {"pick (Vector)", "attribute_or (Vector)", "twice (Vector)"} <= set(graphs)
    names = [g.name for g in compile_(graph('return pick("rest", v)'))]
    # Callees first
    assert names.index("attribute_or (Vector)") < names.index("pick (Vector)")
    assert names.index("twice (Vector)") < names.index("pick (Vector)")


def test_operators_follow_the_type():
    graphs = by_name(compile_(graph("a = twice(1.0)\n  return twice(v)")))
    assert {n.bl_idname for n in graphs["twice (Float)"].nodes} >= {"ShaderNodeMath"}
    assert {n.bl_idname for n in graphs["twice (Vector)"].nodes} >= {"ShaderNodeVectorMath"}


def test_built_for_another_kind_of_tree_too():
    src = "use attrs (twice)\n\ncompositor graph c(x: Float) -> Float {\n  return twice(x)\n}\n"
    graphs = by_name(compile_(src))
    group = graphs["twice (Float) (Compositor)"]
    assert (group.kind, group.called_as, group.types) == ("compositor", "twice", ["Float"])
    msgs = errors("use attrs (attribute_or)\n\ncompositor graph c(x: Float) -> Float {\n"
                  '  return attribute_or("w", x)\n}\n')
    assert len(msgs) == 1
    assert msgs[0].startswith("'attribute_or<Float>' is a geometry graph that cannot be built in a compositor "
                              "tree: unknown node 'NamedAttribute' in a compositor tree")


def test_a_text_calls_its_own_template_through_a_use_only():
    own = ("geometry graph twice<T: Float | Vector>(x: T) -> (y: T) {\n  return (y: x + x)\n}\n\n"
           "geometry graph g(v: Vector) -> Vector {\n  return twice(v)\n}\n")
    assert errors(own) == ["'twice' is a template: a template is a module's graph, brought by a use"]
    # Defined alone, it is checked for each of its types and builds no group
    assert compile_source(own.split("\n\n")[0] + "\n", Typed(), "t.bn") == []


def test_a_module_template_is_checked_for_each_type():
    module = ("geometry graph blend<T: Float | Matrix>(a: T, b: T) -> (value: T) {\n"
              "  return (value: Mix[T](factor: 0.5, a: a, b: b))\n}\n")
    with pytest.raises(BnError) as err:
        compile_source(module, Typed(), "attrs.bn")
    msgs = [d.message for d in err.value.diagnostics]
    # The author meets the error, for the type that has it only
    assert all(m.startswith("blend<Matrix>: ") for m in msgs)
    assert "blend<Matrix>: T is Matrix: Mix has no data_type for Matrix; values: FLOAT, VECTOR, RGBA, ROTATION" in msgs
    # And a text using the module, at its use
    assert errors(graph("return v"), module)[0].startswith("module 'attrs': attrs.bn:2:")


def test_an_error_of_every_type_is_written_once():
    src = ("geometry graph f<T: Float | Vector>(x: T) -> (y: T) {\n  return (y: x + nope)\n}\n")
    with pytest.raises(BnError) as err:
        compile_source(src, Typed(), "t.bn")
    assert [d.message for d in err.value.diagnostics] == ["unknown name 'nope'"]


def test_type_parameters_are_checked():
    def msgs(head):
        with pytest.raises(BnError) as err:
            compile_source(f"geometry graph f<{head}>(x: Float) -> Float {{\n  return x\n}}\n", Typed(), "t.bn")
        return [d.message for d in err.value.diagnostics]
    assert msgs("Float: Float | Vector") == ["'Float' is a type: name a type parameter otherwise, such as T"]
    assert msgs("T: Float, T: Vector") == ["type parameter 'T' defined twice"]
    assert msgs("T: Float | Flot")[0].startswith("unknown type 'Flot' in the constraint of T; expected: Float")
    assert msgs("x: Float") == ["'x' is a type parameter and an input or output of 'f'"]


def test_a_template_that_calls_itself():
    module = "geometry graph f<T: Float>(x: T) -> (y: T) {\n  return (y: f(x).y)\n}\n"
    msgs = errors(graph("return v"), module)
    assert len(msgs) == 1 and "recursive call: 'f<Float>' calls itself" in msgs[0]


def test_parse_and_print():
    src = ("geometry graph blend<T: Float | Vector, U: Float | Color>(a: T, b: U) -> (value: T) {\n"
           "  c = attribute_or<Vector>(\"rest\", a)\n"
           "  return (value: a |> twice<T>())\n"
           "}\n")
    g = parse(src).graphs[0]
    assert [(t.name, t.types) for t in g.type_params] == [("T", ["Float", "Vector"]), ("U", ["Float", "Color"])]
    assert g.body[0].value.type_args == ["Vector"]
    assert format_source(src) == src
    # A comparison is no call's types
    assert parse("geometry graph g(a: Float, b: Float) -> Bool {\n  return a < b\n}\n").graphs[0]


def test_a_name_that_holds_a_value_is_no_template():
    def args(src):
        g = parse(src).graphs[-1]
        call = g.body[-1].value
        return [(type(a.value).__name__, getattr(a.value, "op", None)) for a in call.args]

    compared = [("BinOp", "<"), ("BinOp", ">")]
    head = 'geometry graph g(a: Float, b: Float, c: Float, d: Float, "Seed" as s: Float) -> Float {\n'
    # An input, by its key
    assert args(head + "  return max(a < b, c > (d))\n}\n") == compared
    assert args(head + "  return max(s < b, c > (d))\n}\n") == compared
    # A name bound before, in the block or in a frame of it
    assert args(head + "  k = a\n  return max(k < b, c > (d))\n}\n") == compared
    assert args(head + "  {\n    k = a\n  }\n  return max(k < b, c > (d))\n}\n") == compared
    # Inside a body: its items, and the names around
    body = parse(head + "  r = f(1, v: a) -> {\n    return max(v < b, k > (v))\n  }\n  return r\n}\n")
    assert [type(x.value).__name__ for x in body.graphs[0].body[0].value.body[0].value.args] == ["BinOp", "BinOp"]
    inner = parse(head + "  h = graph(x: Float) -> Float {\n    return max(x < a, b > (x))\n  }\n  return h(x: a)\n}\n")
    assert [type(x.value).__name__ for x in inner.graphs[0].body[0].value.body[0].value.args] == ["BinOp", "BinOp"]
    # A name holds no value before its statement, after the body it is an item of, nor in another graph
    call = [("Call", None)]
    assert args(head + "  return max(k < b, c > (d))\n}\n") == call
    assert args(head + "  r = f(1, v: a) -> {\n    return v\n  }\n  return max(v < b, c > (d))\n}\n") == call
    other = "geometry graph h(k: Float) -> Float {\n  return k\n}\n\n"
    assert args(other + "geometry graph g(b: Float) -> Float {\n  return max(k < b, b > (b))\n}\n") == call
    # Two comparisons in a row are refused, not read as a call
    with pytest.raises(BnError) as err:
        parse(head + "  x = a < b > (c)\n  return x\n}\n")
    assert "only one comparison at a time" in str(err.value)
    # The types of a call, by a name that is none of the graph's values
    src = 'geometry graph pick<T: Float | Vector>(value: T, i: Int) -> (value: T) {\n' \
          '  return (value: index_mix<T>(value, i).value)\n}\n'
    assert parse(src).graphs[0].body[0].value.fields[0].value.target.type_args == ["T"]
    assert format_source(src) == src


def test_what_the_parser_reads_as_types_for_want_of_a_value():
    # A name nothing binds: refused as unknown, as the comparisons would be
    assert errors(graph("return CombineXYZ(x: max(nope < v, z > (v)))", params="v: Float")) == [
        "unknown name 'nope'"]
    # A name its zone gives the body holds a value there: the parser reads comparisons
    body = "r = repeat(3, s: 0.0) -> {\n    return max(iteration < v, v > (s))\n  }\n  return CombineXYZ(x: r)"
    assert compile_(graph(body, params="v: Float"))


def test_a_type_parameter_lists_its_types():
    with pytest.raises(BnError) as err:
        parse("geometry graph f<T>(x: T) -> (y: T) {\n  return (y: x)\n}\n")
    assert "a type parameter lists its types: <T: Float | Vector>" in str(err.value)
