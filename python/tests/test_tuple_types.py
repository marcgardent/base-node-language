"""A tuple only fits a Vector or a Color: a node whose type is a setting takes the type of its tuples."""

import pytest

from base_node_blender import BnError, compile_source


def node(body, schema, bl_idname):
    src = f"geometry graph g(geometry: Geometry, b: Bool, i: Int, t: Float) -> Geometry {{\n{body}\n}}\n"
    g = compile_source(src, schema, "t.bn")[-1]
    return next(n for n in g.nodes if n.bl_idname == bl_idname)


def errors(body, schema):
    src = f"geometry graph g(geometry: Geometry, b: Bool, i: Int, t: Float) -> Geometry {{\n{body}\n}}\n"
    with pytest.raises(BnError) as err:
        compile_source(src, schema, "t.bn")
    return [d.message for d in err.value.diagnostics]


def store(value):
    return f'  v = {value}\n  return StoreNamedAttribute(geometry, name: "x", value: v, data_type: FLOAT_VECTOR)'


@pytest.mark.parametrize("value, props", [
    ("Switch(b, (1.0, 0.0, 0.0), (0.5, 0.5, 0.0))", {"input_type": "VECTOR"}),
    ("Switch(b, Position(), (0.5, 0.5, 0.0))", {"input_type": "VECTOR"}),
    ("Switch(b, true_: (0.5, 0.5, 0.0))", {"input_type": "VECTOR"}),
    ("Switch(b, (1.0, 0.0, 0.0, 1.0), (0.5, 0.5, 0.0))", {"input_type": "RGBA"}),
    ("Switch(b, 1.0, 2.0)", {}),
    ("Mix(0.5, (1.0, 0.0, 0.0), (0.5, 0.5, 0.0))", {"data_type": "VECTOR"}),
    ("Mix(0.5, (1.0, 0.0, 0.0, 1.0), Position())", {"data_type": "RGBA"}),
    ("Mix(t, 1.0, 2.0)", {}),
    ("Compare((1.0, 0.0, 0.0), Position())", {"data_type": "VECTOR"}),
    ("Compare(a: (1.0, 0.0, 0.0, 1.0), b: (0.0, 0.0, 0.0, 1.0), operation: EQUAL)",
     {"data_type": "RGBA", "operation": "EQUAL"}),
])
def test_tuples_choose_the_type(schema, value, props):
    name = value.split("(")[0]
    bl = {"Switch": "GeometryNodeSwitch", "Mix": "ShaderNodeMix", "Compare": "FunctionNodeCompare"}[name]
    n = node(store(value), schema, bl)
    assert n.props == props


def test_a_written_type_stays(schema):
    n = node(store("Switch(b, (1.0, 0.0, 0.0), (0.5, 0.5, 0.0), input_type: RGBA)"), schema, "GeometryNodeSwitch")
    assert n.props == {"input_type": "RGBA"}
    assert n.values == {"False": (1.0, 0.0, 0.0), "True": (0.5, 0.5, 0.0)}


def test_store_named_attribute_takes_float_vector(schema):
    n = node('  return StoreNamedAttribute(geometry, name: "x", value: (1.0, 0.0, 0.0))', schema,
             "GeometryNodeStoreNamedAttribute")
    assert n.props == {"data_type": "FLOAT_VECTOR"}
    n = node('  return StoreNamedAttribute(geometry, name: "x", value: (1.0, 0.0, 0.0, 1.0))', schema,
             "GeometryNodeStoreNamedAttribute")
    assert n.props == {"data_type": "FLOAT_COLOR"}


@pytest.mark.parametrize("value, data_type", [
    ("IndexSwitch(i, (1.0, 0.0, 0.0), (0.5, 0.5, 0.0))", "VECTOR"),
    ("IndexSwitch(i, 1.0, (0.5, 0.5, 0.0))", "VECTOR"),
    ("IndexSwitch(i, Position(), (0.5, 0.5, 0.0, 1.0))", "RGBA"),
    ("IndexSwitch(i, (1.0, 0.0, 0.0), (0.5, 0.5, 0.0, 1.0))", "RGBA"),
    ("IndexSwitch(i, 1.0, 2.0)", "FLOAT"),
])
def test_switch_items_take_the_type_of_their_tuples(schema, value, data_type):
    n = node(store(value), schema, "GeometryNodeIndexSwitch")
    assert n.props == {"data_type": data_type}


def test_menu_switch_items_take_the_type_of_their_tuples(schema):
    n = node(store("MenuSwitch(A: 1.0, B: (0.5, 0.5, 0.0))"), schema, "GeometryNodeMenuSwitch")
    assert n.props == {"data_type": "VECTOR"}


@pytest.mark.parametrize("value, message", [
    # A tuple into a number: Blender would refuse it at build
    ("Switch(b, (1.0, 0.0, 0.0), (0.5, 0.5, 0.0), input_type: FLOAT)",
     "Switch.false_ expects Float, receives a Vector tuple"),
    ("Math((1.0, 2.0, 3.0), 2.0)", "Math.value expects Float, receives a Vector tuple"),
    # A tuple of the wrong length, into a node's input: the message says how to write it
    ("Switch(b, (1.0, 0.0), (0.5, 0.5))", "Switch.false_ expects a Vector of 3 numbers, receives 2; write (1.0, 0.0, 0.0)"),
    ("Switch(b, (1.0, 0.0, 0.0, 1.0), (0.5, 0.5, 0.0, 1.0), input_type: VECTOR)",
     "Switch.false_ expects a Vector of 3 numbers, receives 4; write (1.0, 0.0, 0.0)"),
    ("IndexSwitch(i, (1.0, 0.0), (0.5, 0.5))", "IndexSwitch._0 expects a Vector of 3 numbers, receives 2; write (1.0, 0.0, 0.0)"),
])
def test_a_tuple_that_cannot_be_built_is_refused(schema, value, message):
    assert message in errors(store(value), schema)


def test_a_color_takes_three_numbers(schema):
    n = node(store("Switch(b, (1.0, 0.0, 0.0), (0.5, 0.5, 0.0), input_type: RGBA)"), schema, "GeometryNodeSwitch")
    assert n.values == {"False": (1.0, 0.0, 0.0), "True": (0.5, 0.5, 0.0)}
