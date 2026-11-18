"""What a formula's operands may be: a tuple of 2 or 4 numbers, an integer vector, and a graph
that may not take a function's name."""

import pytest

from base_node import BnError, compile_source


def compile_one(source, schema):
    return compile_source(source, schema, "t.bn")[-1]


def errors(source, schema):
    with pytest.raises(BnError) as err:
        compile_source(source, schema, "t.bn")
    return [d.message for d in err.value.diagnostics]


def vector_math(g):
    return [n for n in g.nodes if n.bl_idname == "ShaderNodeVectorMath"]


def returns(body, out="Vector", params="c: Vector, m: Float"):
    return f"geometry graph g({params}) -> {out} {{\n{body}\n}}\n"


@pytest.mark.parametrize("formula, value", [
    # A 2D offset in image work: z is 0
    ("c + (0.1, 0.0)", (0.1, 0.0, 0.0)),
    ("(0.5, 0.5) - c", (0.5, 0.5, 0.0)),
    # A colour: its alpha is left out, as Blender converts a Color to a Vector
    ("c * (1.0, 0.4, 0.1, 1.0)", (1.0, 0.4, 0.1)),
])
def test_a_formula_takes_a_tuple_of_two_or_four_numbers(schema, formula, value):
    g = compile_one(returns(f"  return {formula}"), schema)
    [n] = vector_math(g)
    assert value in n.values.values()


def test_a_colour_tuple_scaled_by_a_number(schema):
    g = compile_one(returns("  return (1.0, 0.4, 0.1, 1.0) * m"), schema)
    [n] = vector_math(g)
    assert n.props == {"operation": "SCALE"}
    assert n.values == {"Vector": (1.0, 0.4, 0.1)}


def test_a_node_input_keeps_its_size_and_says_how_to_write_it(schema):
    assert errors(returns("  return Switch(true, (1.0, 0.0), (0.5, 0.5, 0.0))", params="m: Float"), schema) == [
        "Switch.false_ expects a Vector of 3 numbers, receives 2; write (1.0, 0.0, 0.0)"]


@pytest.mark.parametrize("formula, op", [
    ("ImageInfo(c).dimensions * 0.5", "SCALE"),
    ("ImageInfo(c).dimensions / ImageInfo(c).resolution", "DIVIDE"),
    ("length(ImageInfo(c).dimensions)", "LENGTH"),
])
def test_an_integer_vector_is_a_vector_in_a_formula(schema, formula, op):
    g = compile_one(returns(f"  return {formula}", out="Float" if op == "LENGTH" else "Vector",
                            params="c: Color"), schema)
    [n] = vector_math(g)
    assert n.props == {"operation": op}
    info = next(x for x in g.nodes if x.bl_idname == "CompositorNodeImageInfo")
    assert any(link.node == info.id for _sock, link in n.links)


def test_an_integer_vector_has_components(schema):
    g = compile_one(returns("  return ImageInfo(c).dimensions.x * 0.5", out="Float", params="c: Color"), schema)
    assert any(n.bl_idname == "ShaderNodeSeparateXYZ" for n in g.nodes)


@pytest.mark.parametrize("name, node", [
    ("max", "Math or Vector Math"),
    ("sqrt", "Math"),
    ("length", "Vector Math"),
    ("nand", "Boolean Math"),
])
def test_a_graph_may_not_take_the_name_of_a_function(schema, name, node):
    src = (f"geometry graph {name}(a: Float, b: Float) -> Float {{\n  return a\n}}\n"
           "geometry graph h(x: Float) -> Float {\n  return x\n}\n")
    assert errors(src, schema) == [
        f"graph '{name}' has the name of the function {name}: {name}(…) is a {node} node; give the graph another name"]


def test_a_graph_named_otherwise_is_called(schema):
    src = ("geometry graph maximum(a: Float, b: Float) -> Float {\n  return max(a, b)\n}\n"
           "geometry graph h(x: Float) -> Float {\n  return maximum(max(x, 0.0), 1.0)\n}\n")
    g = compile_one(src, schema)
    assert any(n.bl_idname == "ShaderNodeMath" and n.props == {"operation": "MAXIMUM"} for n in g.nodes)
    assert any(n.group == "maximum" for n in g.nodes)
