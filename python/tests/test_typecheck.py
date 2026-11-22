import pytest

from base_node_blender import BnError, compile_source, ir
from base_node_blender.layout import layout


def compile_one(source, schema):
    return compile_source(source, schema, "t.bn")[-1]


def errors(source, schema):
    with pytest.raises(BnError) as err:
        compile_source(source, schema, "t.bn")
    return [str(d) for d in err.value.diagnostics]


def graph(body, sig="geometry graph g(geometry: Geometry, t: Float) -> Geometry"):
    return f"{sig} {{\n{body}\n}}"


def test_wave_is_nine_nodes_and_nine_links(schema, fixture_text):
    g = compile_one(fixture_text("wave_v0.bn"), schema)
    assert len(g.nodes) == 9
    assert len(g.edges()) == 9
    by_name = {n.name: n for n in g.nodes if n.name}
    assert by_name["p"].bl_idname == "GeometryNodeInputPosition"
    assert by_name["s"].props == {"operation": "ADD"}
    assert by_name["h"].values == {"Value_001": 0.2}
    out = g.node(ir.GROUP_OUTPUT)
    assert [ident for ident, _link in out.links] == ["Geometry"]


def test_unary_math_has_one_input(schema):
    msgs = errors(graph("  x = Math(t, t, operation: SINE)\n  return geometry"), schema)
    assert msgs == ["t.bn:2:15  Math takes 1 input(s): value"]


def test_unknown_input_lists_inputs(schema):
    msgs = errors(graph("  v = CombineXYZ(w: t)\n  return geometry"), schema)
    assert msgs == ["t.bn:2:18  CombineXYZ has no input 'w'; inputs: x, y, z"]


def test_unknown_enum_value_suggests(schema):
    msgs = errors(graph("  x = Math(t, operation: SINUS)\n  return geometry"), schema)
    assert msgs[0].startswith("t.bn:2:15  operation: unknown SINUS; did you mean SINE?; values: ADD,")


def test_type_mismatch(schema):
    msgs = errors(graph("  return SetPosition(geometry, offset: geometry)"), schema)
    assert msgs == ["t.bn:2:32  SetPosition.offset expects Vector, receives Geometry (geometry)"]


def test_unknown_node_suggests(schema):
    msgs = errors(graph("  return SetPositon(geometry)"), schema)
    assert "did you mean SetPosition" in msgs[0]


def test_all_errors_reported_at_once(schema):
    msgs = errors(graph("  a = Nope()\n  b = CombineXYZ(w: t)\n  return 3"), schema)
    assert len(msgs) == 3


def test_duplicate_sockets_by_identifier(schema):
    msgs = errors(graph("  x = Math(value: t)\n  return geometry"), schema)
    assert "ambiguous" in msgs[0] and "Value_001" in msgs[0]
    g = compile_one(graph("  x = Math(Value_001: t)\n  return geometry"), schema)
    assert g.nodes[2].links[0][0] == "Value_001"


def test_pipe_inserts_first_argument(schema):
    g = compile_one(graph("  return geometry\n    |> SubdivideMesh(level: 2)\n    |> SetShadeSmooth(domain: FACE)"),
                    schema)
    sub, smooth = g.nodes[2], g.nodes[3]
    assert sub.links == [("Mesh", ir.Link(ir.GROUP_INPUT, "geometry"))]
    assert sub.values == {"Level": 2}
    assert smooth.props == {"domain": "FACE"}
    assert smooth.links == [("Geometry", ir.Link(sub.id, "Mesh"))]


def test_multi_input_takes_all_positionals(schema):
    g = compile_one(graph("  a = SetPosition(geometry)\n  return JoinGeometry(geometry, a, geometry)"), schema)
    join = g.nodes[3]
    assert [ident for ident, _ in join.links] == ["Geometry"] * 3


def test_shared_name_is_one_node(schema):
    g = compile_one(graph("  p = Position()\n  v = CombineXYZ(SeparateXYZ(p).x, SeparateXYZ(p).y)\n"
                          "  return SetPosition(geometry, offset: v, position: p)"), schema)
    assert sum(n.bl_idname == "GeometryNodeInputPosition" for n in g.nodes) == 1


def test_menu_socket_takes_enum_value(schema):
    g = compile_one(graph('  i = FindInString("abc", "b", mode: LAST)\n  return geometry'), schema)
    assert g.nodes[2].values == {"String": "abc", "Search": "b", "Mode": "LAST"}


def test_unknown_name_is_reported(schema):
    msgs = errors(graph("  return SetPosition(geometrie)"), schema)
    assert msgs == ["t.bn:2:22  unknown name 'geometrie'; did you mean geometry?"]


def test_unknown_name_without_close_name_has_no_hint(schema):
    assert errors(graph("  return SetPosition(qqq)"), schema) == ["t.bn:2:22  unknown name 'qqq'"]


def test_unknown_function_suggests_function(schema, fixture_text):
    src = fixture_text("wave.bn").replace("sin(", "sinn(")
    msgs = errors(src, schema)
    assert msgs[0].startswith("t.bn:3:7  unknown node 'sinn' in a geometry tree; did you mean sin")


def test_unknown_node_is_not_told_of_functions(schema):
    msgs = errors(graph("  p = Postion()\n  return geometry"), schema)
    assert msgs == ["t.bn:2:7  unknown node 'Postion' in a geometry tree; did you mean Position, SetPosition?"]


def test_mismatch_suggests_the_output_that_fits(schema):
    msgs = errors(graph("  c = CaptureAttribute(geometry)\n  return SetPosition(geometry, selection: c)"), schema)
    assert msgs == ["t.bn:3:32  SetPosition.selection expects Bool, receives Geometry (CaptureAttribute); "
                    "did you mean c.selection?"]
    msgs = errors(graph("  return SetPosition(geometry, selection: CaptureAttribute(geometry))"), schema)
    assert msgs[0].endswith("did you mean CaptureAttribute(…).selection?")
    # The suggestion is valid code
    compile_one(graph("  return SetPosition(geometry, selection: CaptureAttribute(geometry).selection)"), schema)


def test_vector_has_components(schema):
    msgs = errors(graph("  p = Position()\n  h = sin(p.w)\n  return geometry"), schema)
    assert msgs == ["t.bn:3:12  Position has no output 'w'; outputs: position; components: x, y, z"]




def test_group_call_and_order(schema):
    src = ("geometry graph main(geometry: Geometry) -> Geometry {\n  return smooth(geometry)\n}\n"
           "geometry graph smooth(mesh: Geometry) -> Geometry {\n  return SetShadeSmooth(mesh)\n}\n")
    graphs = compile_source(src, schema)
    assert [g.name for g in graphs] == ["smooth", "main"]
    call = graphs[1].nodes[2]
    assert (call.bl_idname, call.group) == ("GeometryNodeGroup", "smooth")


def test_group_without_tree(schema):
    """`Group()`: a Group node with no tree, nothing in nor out (T-50)."""
    g = compile_one(graph("  missing = Group()\n  return geometry"), schema)
    node = next(n for n in g.nodes if n.name == "missing")
    assert node.bl_idname == "GeometryNodeGroup" and node.group is None
    assert (node.n_inputs, node.n_outputs, node.links) == (0, 0, [])
    assert errors(graph("  missing = Group(t)\n  return geometry"), schema) == [
        "t.bn:2:13  Group() is a Group node with no tree: it takes no input"]
    assert errors(graph("  return geometry |> Group()"), schema) == [
        "t.bn:2:22  Group() is a Group node with no tree: it takes no input"]


def test_recursion_is_an_error(schema):
    src = "geometry graph a(g: Geometry) -> Geometry {\n  return a(g)\n}"
    assert "recursive" in errors(src, schema)[0]


def test_record_return(schema):
    g = compile_one("geometry graph g(a: Geometry) -> (mesh: Geometry, n: Int) {\n"
                    "  return (mesh: a, n: 3)\n}", schema)
    out = g.node(ir.GROUP_OUTPUT)
    assert out.links == [("mesh", ir.Link(ir.GROUP_INPUT, "a"))]
    assert out.values == {"n": 3}


def test_pixel_kind_rejected_by_blender_schema(schema):
    assert "pixel" in errors("pixel graph p(i: Color) -> Color {\n  return i\n}", schema)[0]


def test_layout_goes_left_to_right(schema, fixture_text):
    g = compile_one(fixture_text("wave_v0.bn"), schema)
    pos = layout(g)
    for src, dst in g.edges():
        assert pos[src][0] < pos[dst][0]
    assert pos[ir.GROUP_OUTPUT][0] == max(x for x, _y in pos.values())
    assert layout(g) == pos


def test_quoted_names_are_used_by_their_key(schema):
    src = ('geometry graph "Smooth by Angle"(Mesh: Geometry, "Fur Density": Float) -> Geometry {\n'
           "  return SetPosition(Mesh, offset: CombineXYZ(z: fur_density))\n}\n"
           "geometry graph main(geometry: Geometry) -> Geometry {\n"
           "  return smooth_by_angle(geometry, fur_density: 0.5)\n}\n")
    callee, main = compile_source(src, schema)
    assert callee.inputs == [("Mesh", "Geometry"), ("Fur Density", "Float")]
    call = main.nodes[2]
    assert call.group == "Smooth by Angle"
    # Group sockets are named in the ir by their key, as links to the group input are
    assert call.values == {"fur_density": 0.5}
    assert callee.input_keys == ["Mesh", "fur_density"]


def test_outputs_may_stay_unlinked(schema):
    g = compile_one("geometry graph g(a: Geometry) -> (mesh: Geometry, n: Int) {\n  return (n: 3)\n}", schema)
    assert g.node(ir.GROUP_OUTPUT).values == {"n": 3}
    g = compile_one("geometry graph g(a: Geometry) -> () {\n  return ()\n}", schema)
    assert g.outputs == []


def test_datablock_by_name(schema):
    from fake_schema import NODES, S
    from base_node_blender.schema import NodeSpec
    NODES["SetMaterial"] = (NodeSpec("SetMaterial", "GeometryNodeSetMaterial"),
                            [S("Geometry", "Geometry"), S("Selection", "Bool"), S("Material", "Material")],
                            [S("Geometry", "Geometry")])
    try:
        g = compile_one(graph('  return SetMaterial(geometry, material: "Rust")'), schema)
        assert g.nodes[2].values == {"Material": "Rust"}
        assert "expects Material" in errors(graph("  return SetMaterial(geometry, material: 3)"), schema)[0]
        # A material is written bare too, as a graph is called; a name bound in the graph is that value
        g = compile_one(graph("  return SetMaterial(geometry, material: Rust)"), schema)
        assert g.nodes[2].values == {"Material": "Rust"}
        assert "expects Material, receives Float" in errors(graph(
            "  Rust = 1.0\n  return SetMaterial(geometry, material: Rust)"), schema)[0]
    finally:
        del NODES["SetMaterial"]


def test_a_float_literal_does_not_go_into_an_int(schema):
    with pytest.raises(BnError, match="expects an integer: 3 rather than 3.0"):
        compile_source("geometry graph g() -> Geometry {\n  return Grid(1.0, 1.0, 3.0, 3)\n}\n", schema)


def test_a_gizmo_links_the_value_it_moves(schema):
    g = compile_one(graph("  m = CombineTransform(Position())\n"
                          "  return geometry + LinearGizmo(t, position: Position(), draw_style: BOX)\n"
                          "    + TransformGizmo(m, position: Position())"), schema)
    linear = next(n for n in g.nodes if n.bl_idname == "GeometryNodeGizmoLinear")
    assert [ident for ident, _ in linear.links] == ["Value", "Position"]
    assert linear.links[0][1] == ir.Link(ir.GROUP_INPUT, "t") and linear.props == {"draw_style": "BOX"}
    transform = next(n for n in g.nodes if n.bl_idname == "GeometryNodeGizmoTransform")
    m = next(n for n in g.nodes if n.name == "m")
    assert transform.links[0] == ("Value", ir.Link(m.id, "Transform"))


def test_a_gizmo_value_takes_a_number_a_join_does_not(schema):
    g = compile_one(graph("  return geometry + LinearGizmo(2.0)"), schema)
    assert next(n for n in g.nodes if n.bl_idname == "GeometryNodeGizmoLinear").values == {"Value": 2.0}
    assert "only accepts links" in errors(graph("  return JoinGeometry(1.0)"), schema)[0]
    assert "only accepts links" in errors(graph("  return TransformGizmo((1.0, 0.0, 0.0))"), schema)[0]


def test_a_failed_argument_keeps_its_place(schema):
    # The second value still goes to the second input: one error, not a cascade
    src = graph("  x = Position() * nope.y\n"
                "  return SetPosition(geometry, offset: TransformDirection(x, CombineTransform()))")
    assert errors(src, schema) == ["t.bn:2:20  unknown name 'nope'"]


def test_datablock_property_takes_a_name(schema):
    g = compile_one(graph('  i = Image(image: "brick")\n  return geometry'), schema)
    assert next(n for n in g.nodes if n.name == "i").props == {"image": "brick"}
    msgs = errors(graph("  i = Image(image: 3)\n  return geometry"), schema)
    assert msgs == ['t.bn:2:13  image expects a datablock name (Image): "Name"']


def test_implicit_default_is_for_geometry_trees(schema):
    msgs = errors("shader graph s(p: Vector = Position()) -> Vector {\n  return p\n}", schema)
    assert msgs == ["t.bn:1:28  Position() default value only applies in a geometry tree"]


def test_material_takes_material_output_sockets(schema):
    g = compile_one("shader(material: true) graph m() -> (thickness: Float) {\n  return (thickness: 0.5)\n}", schema)
    assert g.settings == {"material": True}
    assert g.outputs == [("thickness", "Float")]


def test_material_has_no_input_and_known_outputs(schema):
    src = "shader(material: true) graph m(p: Float) -> (surface: Float, glow: Shader) {\n  return (surface: p)\n}"
    assert errors(src, schema) == [
        "t.bn:1:32  a material takes no input: its values are written in its nodes",
        "t.bn:1:46  Material Output 'surface' is a Shader, not a Float",
        "t.bn:1:62  'glow' is not a Material Output socket; outputs: surface: Shader, volume: Shader, "
        "displacement: Vector, thickness: Float",
    ]


def test_only_a_shader_graph_is_a_material(schema):
    src = "geometry(material: true) graph m(geometry: Geometry) -> Geometry {\n  return geometry\n}"
    assert errors(src, schema) == ["t.bn:1:1  only a shader graph is a material, not a geometry graph"]


def test_no_graph_calls_a_material(schema):
    src = ("shader(material: true) graph m() -> (thickness: Float) {\n  return (thickness: 0.5)\n}\n"
           "shader graph s() -> Float {\n  return m().thickness\n}")
    assert errors(src, schema) == ["t.bn:5:10  'm' is a material, not a node group: no graph calls it"]


def test_ramp_and_curves_are_node_data(schema):
    src = graph("  r = ColorRamp(factor: t, color_ramp: Ramp((0.0, (0.0, 0.0, 0.0)), (0.5, (1.0, 0.5, 0.0, 1.0)), "
                "interpolation: EASE))\n"
                "  f = FloatCurve(value: r.alpha, mapping: Curve((0.0, 0.0), (0.5, 0.8, VECTOR), (1.0, -1.0), "
                "extend: HORIZONTAL))\n"
                "  c = RGBCurves(color: r.color, mapping: Curves(c: Curve((0.0, 0.1), (1.0, 0.9)), "
                "black_level: (0.1, 0.1, 0.1)))\n"
                "  return SetPosition(geometry, offset: CombineXYZ(x: c.color, z: f))")
    g = compile_one(src, schema)
    by_name = {n.name: n for n in g.nodes if n.name}
    assert by_name["r"].data == {"color_ramp": {
        "stops": [(0.0, (0.0, 0.0, 0.0, 1.0)), (0.5, (1.0, 0.5, 0.0, 1.0))], "options": {"interpolation": "EASE"}}}
    assert by_name["r"].props == {}
    assert by_name["f"].data == {"mapping": {
        "curves": {0: [(0.0, 0.0, "AUTO"), (0.5, 0.8, "VECTOR"), (1.0, -1.0, "AUTO")]}, "options": {"extend": "HORIZONTAL"}}}
    assert by_name["c"].data == {"mapping": {
        "curves": {3: [(0.0, 0.1, "AUTO"), (1.0, 0.9, "AUTO")]}, "options": {"black_level": (0.1, 0.1, 0.1)}}}


@pytest.mark.parametrize("value, message", [
    ("3", "2:40  color_ramp expects Ramp((position, color), …)"),
    ("Ramp()", "2:40  a Ramp has one stop at least: (position, color)"),
    ("Ramp((2.0, (1.0, 1.0, 1.0)))", "2:45  a Ramp stop's position is from 0.0 to 1.0, not 2.0"),
    ("Ramp((0.5, 1.0))", "2:45  a Ramp stop is (position, color): (0.5, (1.0, 0.5, 0.0, 1.0))"),
    ("Ramp((0.5, (1.0, 1.0, 1.0)), interpolation: SMOOTH)",
     "2:69  interpolation expects one of EASE, CARDINAL, LINEAR, B_SPLINE, CONSTANT"),
    ("Ramp((0.5, (1.0, 1.0, 1.0)), mode: HSV)",
     "2:69  Ramp has no setting 'mode'; settings: interpolation, color_mode, hue_interpolation"),
])
def test_a_ramp_says_what_it_expects(schema, value, message):
    assert errors(graph(f"  r = ColorRamp(factor: t, color_ramp: {value})\n  return geometry"), schema) == \
        [f"t.bn:{message}"]


@pytest.mark.parametrize("node, value, message", [
    ("FloatCurve", "Curve((0.0, 0.0))", "2:27  a Curve has two points at least: (x, y)"),
    ("FloatCurve", "Curve((0.0, 0.0), (1.0, 1.0, SHARP))",
     "2:45  a Curve point is (x, y), or (x, y, handle) with handle one of AUTO, AUTO_CLAMPED, VECTOR"),
    ("RGBCurves", "Curve((0.0, 0.0), (1.0, 1.0))",
     "2:26  mapping expects Curves(r: Curve((x, y), …), …); channels: r, g, b, c"),
    ("RGBCurves", "Curves(Curve((0.0, 0.0), (1.0, 1.0)))",
     "2:33  Curves takes its curves by channel (r, g, b, c): r: Curve(…)"),
    ("RGBCurves", "Curves(r: Curve((0.0, 0.0), (1.0, 1.0), tone: FILMLIKE))",
     "2:66  'tone' is a setting of the Curves, not of one Curve"),
])
def test_curves_say_what_they_expect(schema, node, value, message):
    assert errors(graph(f"  r = {node}(mapping: {value})\n  return geometry"), schema) == [f"t.bn:{message}"]


# Deprecated graphs: `kind(deprecated: "what to use instead") graph …`

OLD = """\
geometry(deprecated: "use twice") graph double(x: Float) -> Float {
  return x * 2.0
}

geometry(deprecated: true) graph half(x: Float) -> Float {
  return double(x) / 4.0
}

geometry(deprecated: false) graph twice(x: Float) -> Float {
  return x * 2.0
}
"""


def test_a_call_of_a_deprecated_graph_is_warned_of(schema):
    from base_node_blender import deprecations, parse

    source = OLD + "\ngeometry graph g(x: Float) -> Float {\n  y = double(x) + twice(x)\n  return half(y)\n}\n"
    warnings = []
    graphs = compile_source(source, schema, "t.bn", warnings=warnings)
    # The text is valid and whole: the graphs are those of a text without the mark
    assert [g.name for g in graphs] == ["double", "half", "twice", "g"]
    assert [g.deprecated for g in graphs] == ["use twice", "", None, None]
    assert all("deprecated" not in g.settings for g in graphs)
    # At each call, with what the author wrote; none inside a graph that is deprecated itself
    assert [str(w) for w in warnings] == ["t.bn:14:7  warning: 'double' is deprecated: use twice",
                                         "t.bn:15:10  warning: 'half' is deprecated"]
    assert {w.severity for w in warnings} == {"warning"}
    # Without a schema, as the command line reads it: the same
    assert deprecations(parse(source, "t.bn"), "t.bn") == warnings
    # Nobody asking for them, they are not said
    assert compile_source(source, schema, "t.bn")


def test_a_deprecated_graph_of_a_module(schema):
    from base_node_blender import deprecations, parse

    def load(name, source):
        return OLD, f"{name}.bn"

    def find(name):
        return parse(OLD, f"{name}.bn")

    for use, call, at in (("use old", "double", 4), ("use old (double)", "double", 4), ("use old", "old::double", 4),
                          ("use old as o", "o::double", 4)):
        source = f"{use}\n\ngeometry graph g(x: Float) -> Float {{\n  return {call}(x)\n}}\n"
        warnings = []
        compile_source(source, schema, "t.bn", load, warnings)
        # Of the text, not of its module: `half` calling `double` in old.bn is its author's to see
        assert [str(w) for w in warnings] == [f"t.bn:{at}:10  warning: '{call}' is deprecated: use twice"], use
        assert deprecations(parse(source, "t.bn"), "t.bn", find) == warnings
    source = "use old (twice)\n\ngeometry graph g(x: Float) -> Float {\n  return twice(x)\n}\n"
    warnings = []
    compile_source(source, schema, "t.bn", load, warnings)
    assert warnings == [] and deprecations(parse(source, "t.bn"), "t.bn", find) == []


def test_a_warning_comes_with_no_error(schema):
    source = OLD + "\ngeometry graph g(x: Float) -> Float {\n  return double(y)\n}\n"
    warnings = []
    assert errors(source, schema) == ["t.bn:14:17  unknown name 'y'"]
    with pytest.raises(BnError):
        compile_source(source, schema, "t.bn", warnings=warnings)
    assert warnings == []


def test_what_deprecated_takes(schema):
    for value in ("SOON", "1", "(1.0, 2.0)"):
        msgs = errors(f"geometry(deprecated: {value}) graph f(x: Float) -> Float {{\n  return x\n}}\n", schema)
        assert len(msgs) == 1 and "deprecated" in msgs[0], msgs
    assert errors("geometry(deprecated: SOON) graph f(x: Float) -> Float {\n  return x\n}\n", schema) == [
        "t.bn:1:10  setting 'deprecated': true, or what to use instead, in quotes"]


def test_deprecated_is_written_back():
    from base_node_blender import format_source, parse, to_source

    assert format_source(OLD, "t.bn") == OLD and to_source(parse(OLD, "t.bn")) == OLD


def test_inputs_with_a_key_of_their_own():
    """Mix Shader's two Shader inputs are `a` and `b` (schema.INPUT_KEYS); Blender's identifiers are
    still read, and any other node of repeated names falls back on them."""
    from base_node_blender.schema import Socket, input_key
    from base_node_blender.typecheck import find_socket, socket_keys

    def sockets(node):
        return [Socket("Factor", "Fac", "Float")] + [
            Socket("Shader", i, "Shader", alias=input_key(node, i)) for i in ("Shader", "Shader_001")]

    mix = sockets("ShaderNodeMixShader")
    assert socket_keys(mix) == "factor, a, b"
    assert find_socket(mix, "a") is mix[1] and find_socket(mix, "b") is mix[2]
    assert find_socket(mix, "Shader") is mix[1] and find_socket(mix, "Shader_001") is mix[2]
    assert find_socket(mix, "shader") is None
    other = sockets("ShaderNodeSomethingElse")
    assert socket_keys(other) == "factor, Shader, Shader_001"
    assert find_socket(other, "a") is None
