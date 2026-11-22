"""Constant input nodes the checker makes: a named datablock, no datablock at all (`_`), and the
values no literal holds (a Rotation, a 4D Vector, an Integer Vector)."""

import pytest

from base_node_blender import BnError, compile_source
from base_node_blender.schema import NodeSpec, Prop, Socket

from fake_schema import FakeSchema


def S(name, type, identifier=None):
    return Socket(name, identifier or name, type)


# Like Blender's: the input nodes of a constant, and two nodes that read a font
NODES = {
    "String": (NodeSpec("String", "FunctionNodeInputString", {"string": Prop("string", "STRING")}),
               [], [S("String", "String")]),
    "Font": (NodeSpec("Font", "GeometryNodeInputFont", {"font": Prop("font", "ID", (), "VectorFont")}),
             [], [S("Font", "Font")]),
    "Object": (NodeSpec("Object", "GeometryNodeInputObject", {"object": Prop("object", "ID", (), "Object")}),
               [], [S("Object", "Object")]),
    "StringToCurves": (NodeSpec("StringToCurves", "GeometryNodeStringToCurves"),
                       [S("String", "String"), S("Size", "Float"), S("Font", "Font")],
                       [S("Curve Instances", "Geometry")]),
    "ObjectInfo": (NodeSpec("ObjectInfo", "GeometryNodeObjectInfo"),
                   [S("Object", "Object")], [S("Geometry", "Geometry")]),
    "JoinStrings": (NodeSpec("JoinStrings", "GeometryNodeStringJoin"),
                    [S("Delimiter", "String")], [S("String", "String")]),
    "Rotation": (NodeSpec("Rotation", "FunctionNodeInputRotation"), [], [S("Rotation", "Rotation")]),
    "Vector": (NodeSpec("Vector", "FunctionNodeInputVector",
                        {"vector_dimensions": Prop("vector_dimensions", "INT")}), [], [S("Vector", "Vector")]),
    "IntegerVector": (NodeSpec("IntegerVector", "FunctionNodeInputIntVector",
                               {"vector_dimensions": Prop("vector_dimensions", "INT")}),
                      [], [S("Vector", "Int_Vector")]),
}


class ConstSchema(FakeSchema):
    def node(self, kind, name):
        return NODES[name][0] if kind == "geometry" and name in NODES else super().node(kind, name)

    def node_names(self, kind):
        return super().node_names(kind) + (list(NODES) if kind == "geometry" else [])

    def sockets(self, kind, spec, props):
        if spec.name in NODES:
            return list(NODES[spec.name][1]), list(NODES[spec.name][2])
        return super().sockets(kind, spec, props)


def compile_one(body, out="Geometry"):
    src = f"geometry graph g(geometry: Geometry) -> {out} {{\n{body}\n}}"
    return compile_source(src, ConstSchema(), "t.bn")[-1]


def errors(body):
    with pytest.raises(BnError) as err:
        compile_one(body)
    return [str(d) for d in err.value.diagnostics]


def test_a_named_font_is_a_font_node():
    g = compile_one('  f = "Bfont Regular"\n  return StringToCurves(string: "Hi", font: f)')
    f = next(n for n in g.nodes if n.name == "f")
    assert (f.bl_idname, f.props) == ("GeometryNodeInputFont", {"font": "Bfont Regular"})
    stc = next(n for n in g.nodes if n.bl_idname == "GeometryNodeStringToCurves")
    assert [(ident, link.node) for ident, link in stc.links] == [("Font", f.id)]
    assert "Font" not in stc.values


def test_a_named_object_feeds_every_input_of_its_type():
    g = compile_one('  o = "Cube"\n  a = ObjectInfo(o)\n  return ObjectInfo(o)')
    o = next(n for n in g.nodes if n.name == "o")
    assert (o.bl_idname, o.props) == ("GeometryNodeInputObject", {"object": "Cube"})
    infos = [n for n in g.nodes if n.bl_idname == "GeometryNodeObjectInfo"]
    assert [[link.node for _i, link in n.links] for n in infos] == [[o.id], [o.id]]


def test_a_string_read_as_a_string_first_stays_one():
    # Its String node is linked already: the font takes its value
    g = compile_one('  f = "Bfont Regular"\n  s = JoinStrings(f)\n'
                    '  return StringToCurves(string: s, font: f)')
    f = next(n for n in g.nodes if n.name == "f")
    assert f.bl_idname == "FunctionNodeInputString"
    stc = next(n for n in g.nodes if n.bl_idname == "GeometryNodeStringToCurves")
    assert stc.values == {"Font": "Bfont Regular"}
    # And a Font node read as a String afterwards gives its name
    g = compile_one('  f = "Bfont Regular"\n  c = StringToCurves(font: f)\n'
                    '  return StringToCurves(string: f, font: f)')
    f = next(n for n in g.nodes if n.name == "f")
    last = [n for n in g.nodes if n.bl_idname == "GeometryNodeStringToCurves"][-1]
    assert f.bl_idname == "GeometryNodeInputFont"
    assert last.values == {"String": "Bfont Regular"} and [i for i, _l in last.links] == ["Font"]


def test_no_datablock_is_an_underscore():
    g = compile_one('  return StringToCurves(string: "Hi", font: _)')
    stc = next(n for n in g.nodes if n.bl_idname == "GeometryNodeStringToCurves")
    assert stc.values == {"String": "Hi", "Font": None}
    g = compile_one("  return StringToCurves(font: Font(font: _))")
    assert next(n for n in g.nodes if n.bl_idname == "GeometryNodeInputFont").props == {"font": None}
    # Elsewhere `_` is still no name
    assert errors("  return StringToCurves(string: _)") == ["t.bn:2:25  unknown name '_'"]


def test_values_no_literal_makes():
    g = compile_one("  return Rotation(rotation_euler: (0.1, 0.2, 0.3))", out="Rotation")
    assert g.nodes[-1].props == {"rotation_euler": (0.1, 0.2, 0.3)}
    # The dimensions first, from the tuple unless written
    g = compile_one("  return Vector(vector: (1.0, 2.0, 3.0, 4.0))", out="Vector")
    assert list(g.nodes[-1].props.items()) == [("vector_dimensions", 4), ("vector", (1.0, 2.0, 3.0, 4.0))]
    g = compile_one("  return Vector(vector: (1.0, 2.0, 3.0, 4.0), vector_dimensions: 4)", out="Vector")
    assert list(g.nodes[-1].props.items()) == [("vector_dimensions", 4), ("vector", (1.0, 2.0, 3.0, 4.0))]
    g = compile_one("  return IntegerVector(vector: (1, 2, 3))", out="Vector")
    assert g.nodes[-1].props == {"vector_dimensions": 3, "vector": (1, 2, 3)}
    assert type(g.nodes[-1].props["vector"][0]) is int


def test_values_no_literal_makes_are_checked():
    assert errors("  r = Rotation(rotation_euler: (0.1, 0.2))\n  return geometry") == \
        ["t.bn:2:16  rotation_euler expects 3 numbers, receives 2"]
    assert errors("  v = Vector(vector: (1.0, 2.0), vector_dimensions: 3)\n  return geometry") == \
        ["t.bn:2:14  vector expects 3 numbers (vector_dimensions), receives 2"]
    assert errors("  v = IntegerVector(vector: (1.5, 2.0, 3.0))\n  return geometry") == \
        ["t.bn:2:21  vector expects whole numbers"]
    assert errors("  r = Rotation(rotation_euler: 1.0)\n  return geometry") == \
        ["t.bn:2:16  rotation_euler expects a tuple of numbers"]
