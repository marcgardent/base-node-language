"""A module's graph called from another kind of tree: `use math (bias)` in a compositor graph."""

import pytest

from base_node_blender import BnError, compile_source
from fake_schema import FakeSchema

# The math nodes a compositor tree shares with a geometry tree, as in Blender
SHARED = {"Math", "VectorMath", "CombineXYZ", "SeparateXYZ", "Switch", "Compare", "Value", "Vector"}


class TwoTrees(FakeSchema):
    """Geometry nodes, and a compositor tree with only the math ones."""

    def node(self, kind, name):
        if kind == "compositor":
            return super().node("geometry", name) if name in SHARED else None
        return super().node(kind, name)

    def node_names(self, kind):
        return [n for n in super().node_names("geometry") if kind == "geometry" or n in SHARED]


MATHS = """\
geometry graph double(x: Float) -> Float {
  return x * 2.0
}

geometry graph quadruple(x: Float) -> Float {
  return double(double(x))
}

geometry graph lift(p: Vector = Position(), h: Float = 1.0) -> Vector {
  return p + CombineXYZ(z: h)
}

geometry graph moved(geometry: Geometry) -> Geometry {
  return SetPosition(geometry, offset: CombineXYZ(z: 1.0))
}
"""


def loader(text=MATHS):
    def load(name, source):
        if name != "maths":
            raise LookupError(f"no text '{name}.bn'")
        return text, "maths.bn"
    return load


def compile_(src):
    return compile_source(src, TwoTrees(), "t.bn", loader())


def errors(src):
    with pytest.raises(BnError) as err:
        compile_(src)
    return [d.message for d in err.value.diagnostics]


def test_a_module_graph_is_built_for_the_tree_that_calls_it():
    graphs = compile_("use maths (quadruple)\n\n"
                      "compositor graph look(x: Float) -> Float {\n  return quadruple(x)\n}\n")
    by_name = {g.name: g for g in graphs}
    # The geometry graphs the use brings, and their compositor variants, callees first
    assert [g.name for g in graphs] == ["double", "quadruple", "double (Compositor)", "quadruple (Compositor)",
                                        "look"]
    variant = by_name["quadruple (Compositor)"]
    assert (variant.kind, variant.called_as, variant.module) == ("compositor", "quadruple", ("maths", None))
    assert {n.group for n in variant.nodes if n.group} == {"double (Compositor)"}
    call = next(n for n in by_name["look"].nodes if n.group)
    assert (call.bl_idname, call.group) == ("CompositorNodeGroup", "quadruple (Compositor)")
    # The geometry graphs are left as they were
    assert by_name["quadruple"].kind == "geometry"
    assert {n.group for n in by_name["quadruple"].nodes if n.group} == {"double"}


def test_one_variant_for_every_caller():
    graphs = compile_("use maths (double)\n\n"
                      "compositor graph a(x: Float) -> Float {\n  return double(x)\n}\n\n"
                      "compositor graph b(x: Float) -> Float {\n  return double(double(x))\n}\n")
    assert [g.name for g in graphs] == ["double", "double (Compositor)", "a", "b"]


def test_a_context_field_is_given_by_the_call():
    graphs = compile_("use maths (lift)\n\n"
                      "compositor graph g(v: Vector) -> Vector {\n  return lift(v, 2.0)\n}\n")
    variant = next(g for g in graphs if g.name == "lift (Compositor)")
    assert "implicit" not in variant.defaults.get("p", {})
    assert errors("use maths (lift)\n\ncompositor graph g() -> Vector {\n  return lift(h: 2.0)\n}\n") == [
        "lift: give 'p', which is Position() in a geometry tree only"]


def test_a_graph_whose_nodes_the_tree_lacks_is_refused_with_the_reason():
    msgs = errors("use maths (moved)\n\ncompositor graph g(x: Float) -> Float {\n  m = moved(x)\n  return x\n}\n")
    assert len(msgs) == 1
    assert msgs[0].startswith("'moved' is a geometry graph that cannot be built in a compositor tree: "
                              "unknown node 'SetPosition' in a compositor tree")
    assert msgs[0].endswith("(maths.bn:14)")


def test_a_graph_of_the_text_itself_keeps_to_its_kind():
    src = ("geometry graph double(x: Float) -> Float {\n  return x * 2.0\n}\n\n"
           "compositor graph g(x: Float) -> Float {\n  return double(x)\n}\n")
    assert errors(src) == ["'double' is a geometry graph, not compositor; "
                           "a graph of a module (use) is built for every kind of tree"]


class ShaderToo(TwoTrees):
    """…and a shader tree, which has the math nodes but Compare."""

    def node(self, kind, name):
        if kind == "shader":
            return FakeSchema.node(self, "geometry", name) if name in SHARED - {"Compare"} else None
        return super().node(kind, name)


STEPS = """\
geometry graph above(x: Float, edge: Float = 0.5) -> Float {
  return (x >= edge) * 2.0
}
"""


def test_a_comparison_is_built_as_each_tree_can():
    graphs = compile_source("use maths (above)\n\nshader graph s(x: Float) -> Float {\n  return above(x)\n}\n",
                            ShaderToo(), "t.bn", loader(STEPS))
    by_name = {g.name: g for g in graphs}
    # Compare in the geometry tree it was written for, Math in the shader tree, which has no Compare
    assert [(n.bl_idname, n.props.get("operation")) for n in by_name["above"].nodes if n.props] == [
        ("FunctionNodeCompare", "GREATER_EQUAL"), ("ShaderNodeMath", "MULTIPLY")]
    assert [(n.bl_idname, n.props.get("operation")) for n in by_name["above (Shader)"].nodes if n.props] == [
        ("ShaderNodeMath", "LESS_THAN"), ("ShaderNodeMath", "SUBTRACT"), ("ShaderNodeMath", "MULTIPLY")]
