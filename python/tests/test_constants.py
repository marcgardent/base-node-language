"""Constant input nodes the checker makes: a named datablock, and no datablock at all (`_`)."""

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
