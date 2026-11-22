import pytest

from base_node_blender.complete import complete, product_sign, signature

from fake_schema import MATH_OPS

HEAD = "geometry graph f(geometry: Geometry, t: Float, v: Vector) -> Geometry {\n"


def at_end(source, schema):
    """Suggestions with the cursor at the end of the source."""
    lines = source.split("\n")
    return complete(source, len(lines), len(lines[-1]) + 1, schema)


def labels(source, schema):
    return [i.label for i in at_end(source, schema)[1]]


def test_inputs_of_the_call_come_first(schema):
    got = labels(HEAD + "  return SetPosition(", schema)
    assert got[:4] == ["geometry", "selection", "position", "offset"], got
    assert "t" in got and "Position" in got  # positional values follow


def test_where_a_value_goes_by_name_only_the_inputs_come(schema):
    assert labels(HEAD + "  x = Math[ADD](", schema) == ["Value", "Value_001"]
    assert labels(HEAD + "  x = CombineXYZ(x: t, ", schema) == ["y", "z"]
    # After the geometry a node works on, and after a piped one
    got = labels(HEAD + "  return SetPosition(geometry, ", schema)
    assert got == ["selection", "position", "offset"], got
    assert labels(HEAD + "  return geometry |> SetPosition(", schema) == ["selection", "position", "offset"]
    # The items of a switch, the values of a multi-input, a function's operands go by position
    assert "t" in labels(HEAD + "  x = IndexSwitch(1, ", schema)
    assert "geometry" in labels(HEAD + "  return JoinGeometry(geometry, ", schema)
    assert "t" in labels(HEAD + "  x = max(t, ", schema)


def test_input_inserts_a_named_argument(schema):
    start, items = at_end(HEAD + "  return SetPosition(geometry, off", schema)
    assert (items[0].label, items[0].insert) == ("offset", "offset: ")
    assert start == len("  return SetPosition(geometry, ") + 1


def test_given_arguments_are_not_suggested_again(schema):
    got = labels(HEAD + "  return SetPosition(geometry, offset: v, ", schema)
    assert "offset" not in got and "selection" in got


def test_enum_values_after_the_setting(schema):
    assert labels(HEAD + "  x = Math[operation: ", schema) == list(MATH_OPS)
    assert labels(HEAD + "  x = Math[operation: SI", schema)[0] == "SINE"


def test_brackets_offer_the_settings_and_parentheses_the_inputs(schema):
    # In brackets: the enum values by position, then the names of the settings; no value of the graph
    got = labels(HEAD + "  x = Math[", schema)
    assert got == [*MATH_OPS, "operation", "use_clamp"], got
    # A setting written is not offered again, whether by position or by name
    got = labels(HEAD + "  x = Math[ADD, ", schema)
    assert got == ["use_clamp"], got
    assert labels(HEAD + "  x = Math[use_clamp: ", schema) == ["true", "false"]
    # In parentheses: inputs, never a setting
    got = labels(HEAD + "  x = Math[ADD](", schema)
    assert got[:2] == ["Value", "Value_001"] and "operation" not in got and "use_clamp" not in got, got
    assert "domain" not in labels(HEAD + "  return SetShadeSmooth(", schema)


def test_repeated_inputs_are_named_by_identifier(schema):
    got = labels(HEAD + "  x = Math(", schema)
    assert got[:2] == ["Value", "Value_001"], got


def test_props_change_the_inputs(schema):
    got = labels(HEAD + "  x = VectorMath[SCALE](", schema)
    assert got[:2] == ["vector", "scale"], got


def test_outputs_of_a_bound_node(schema):
    src = HEAD + "  grid = Grid(size_x: 2.0, size_y: 2.0, vertices_x: 3, vertices_y: 3)\n  return grid."
    assert labels(src, schema) == ["mesh", "uv_map"]


def test_vector_output_also_has_components(schema):
    src = HEAD + "  p = Position()\n  h = p."
    assert labels(src, schema) == ["position", "x", "y", "z"]
    assert labels(HEAD + "  h = v.", schema) == ["x", "y", "z"]


def test_outputs_after_a_call(schema):
    assert labels(HEAD + "  return Grid(size_x: 1.0, size_y: 1.0, vertices_x: 2, vertices_y: 2).m", schema)[0] == "mesh"


def test_names_in_the_body(schema):
    src = HEAD + "  p = Position()\n  "
    got = labels(src, schema)
    assert got[:4] == ["p", "geometry", "t", "v"], got
    assert "return" in got and "sin" in got and "SetPosition" in got
    start, items = at_end(src + "Set", schema)
    assert [i.insert for i in items] == ["SetPosition(", "SetShadeSmooth("]
    assert start == 3


def test_initials(schema):
    assert labels(HEAD + "  x = SP", schema)[0] == "SetPosition"


def test_pipe_takes_calls_only(schema):
    got = labels(HEAD + "  return geometry\n    |> ", schema)
    assert "geometry" not in got and "SetPosition" in got


def test_calls_to_graphs_of_the_file(schema, fixture_text):
    src = fixture_text("round_trip.bn")
    cut = src.index("smooth_mesh(") + len("smooth_mesh(")
    lines = src[:cut].split("\n")
    _, items = complete(src, len(lines), len(lines[-1]) + 1, schema)
    assert [i.label for i in items[:2]] == ["mesh", "level"]
    assert "smooth_mesh" not in [i.label for i in at_end(src[:src.index("|>")], schema)[1]]


def test_types_in_the_header(schema):
    assert labels("geometry graph f(a: Fl", schema) == ["Float"]
    assert "Geometry" in labels("geometry graph f(a: Float) -> ", schema)
    assert labels("geometry graph f(a", schema) == []


def test_top_level(schema):
    assert labels("geo", schema) == ["geometry"]
    assert labels("geometry ", schema) == ["graph"]
    assert labels(HEAD + "}\n", schema)[:1] == ["geometry"]


def test_nothing_in_strings_comments_or_after_a_value(schema):
    assert labels(HEAD + '  x = SetMaterial(geometry, material: "Ru', schema) == []
    assert labels(HEAD + "  // Set", schema) == []
    assert labels(HEAD + "  x = t ", schema) == []
    assert labels(HEAD + "  x = 1", schema) == []


def test_values_after_a_comparison(schema):
    assert labels(HEAD + "  x = t >= ", schema)[:3] == ["geometry", "t", "v"]


def test_colors_after_a_hash(schema):
    start, items = at_end(HEAD + '  "Noise" #tom', schema)
    assert items[0].label == "tomato" and items[0].insert == "tomato" and items[0].detail == "#ff6347"
    assert start == len('  "Noise" #') + 1


def test_names_from_a_frame_are_seen_after_it(schema):
    got = labels(HEAD + '  "Noise" #orange {\n    p = Position()\n  }\n  "Relief" {\n    ', schema)
    assert "p" in got and "return" in got


@pytest.mark.parametrize("typed, expected", [
    ("  a = n dot ", (8, 11, "⋅")), ("  a = (n + u) cross ", (14, 19, "×")), ('  a = "x" dot ', (10, 13, "⋅")),
    ("  a = dot ", None), ("  a = n dot", None), ("  // n dot ", None), ("  a = n.dotx ", None),
    ("  return dot ", None),
])
def test_product_words_swap_after_an_operand(typed, expected):
    assert product_sign(typed) == expected


def test_graphs_of_a_use_and_groups_of_the_file(schema):
    from base_node_blender.schema import GroupSpec
    schema.existing = {"lift_up": GroupSpec("Lift Up", (("z", "Float"),), (("Vector", "Vector"),))}
    maths = "geometry graph bosse(x: Float, centre: Float) -> Float {\n  return x\n}\n" \
            "geometry graph pic(x: Float) -> Float {\n  return x\n}\n"

    def load(name, source):
        if name != "maths":
            raise LookupError(name)
        return maths, "maths.bn"
    src = "use maths (bosse)\nuse absent\n\n" + HEAD + "  h = "
    lines = src.split("\n")
    _, items = complete(src, len(lines), len(lines[-1]) + 1, schema, load)
    got = [i.label for i in items]
    assert "bosse" in got and "lift_up" in got and "pic" not in got, got
    src += "bosse("
    _, items = complete(src, len(lines), len(lines[-1]) + len("bosse(") + 1, schema, load)
    assert [i.label for i in items[:2]] == ["x", "centre"]


def test_asked_after_a_value_gives_the_next_inputs(schema):
    src = HEAD + "  return SetPosition(geometry, offset: Position()"
    lines = src.split("\n")
    assert complete(src, len(lines), len(lines[-1]) + 1, schema)[1] == []  # not by itself
    start, items = complete(src, len(lines), len(lines[-1]) + 1, schema, asked=True)
    # The geometry was given by position: the inputs after it
    assert [i.insert for i in items][:2] == [", selection: ", ", position: "], items
    assert "offset" not in [i.label for i in items]
    assert start == len(lines[-1]) + 1  # nothing replaced
    # After a number too, which is not a word being typed
    src = HEAD + "  return SetPosition(geometry, offset: 10"
    lines = src.split("\n")
    assert complete(src, len(lines), len(lines[-1]) + 1, schema, asked=True)[1]


def sig(source, schema):
    lines = source.split("\n")
    return signature(source, len(lines), len(lines[-1]) + 1, schema)


def test_signature_of_the_call_the_cursor_is_in(schema):
    s = sig(HEAD + "  return SetPosition(geometry, offset: v, ", schema)
    assert s.name == "SetPosition"
    assert [(k, st) for k, _t, st in s.inputs] == [
        ("geometry", "given"), ("selection", ""), ("position", ""), ("offset", "given")]
    assert s.outputs == (("geometry", "Geometry"),)
    s = sig(HEAD + "  return SetPosition(geometry, offset: Position(", schema)
    assert s.name == "Position"
    s = sig(HEAD + "  return SetPosition(geometry, offset: ", schema)
    assert dict((k, st) for k, _t, st in s.inputs)["offset"] == "current"
    s = sig(HEAD + "  return geometry |> SetPosition(", schema)
    assert s.inputs[0][2] == "given"  # the pipe gives the first input
    # Past its settings, a call's inputs; in its brackets, its settings
    s = sig(HEAD + "  x = Math[ADD](1.0, ", schema)
    assert [(k, st) for k, _t, st in s.inputs] == [("Value", "given"), ("Value_001", "")]
    s = sig(HEAD + "  x = Math[ADD, ", schema)
    assert [(k, st) for k, _t, st in s.inputs] == [("operation", "given"), ("use_clamp", "")]
    assert sig(HEAD + "  return SetPosition(geometry)", schema) is None
    assert sig(HEAD + "  x = 1.0", schema) is None


def test_a_comment_line_offers_the_targets(schema):
    start, items = at_end("//", schema)
    assert [i.label for i in items][:2] == ["@target blade", "@target blender"]
    assert (start, items[0].insert) == (3, " @target blade")  # right after `//`
    start, items = at_end("  // @target blender g", schema)
    assert [i.insert for i in items] == [" @target blender gltf"] and start == 5
    assert "@target blender@5.3 eevee" in labels("// @tar", schema)
    assert not [label for label in labels("// @tar", schema) if "@latest" in label or "@lts" in label]


def test_an_ordinary_comment_offers_nothing(schema):
    assert labels("// a note", schema) == []
    assert labels("a = 1 // @tar", schema) == []


def test_search_as_blenders_add_menu():
    """As Shift+A: each piece is the start of a word of the label, in any order, one typo forgiven."""
    from base_node_blender.complete import Item, matching

    names = ["CurveCircle", "MeshCircle", "NoiseTexture", "VoronoiTexture", "WhiteNoiseTexture",
             "InstanceOnPoints", "SetHandlePositions", "SetPosition"]
    items = [Item(n, n, "node", "node") for n in names]

    def found(typed):
        return [i.label for i in matching(items, typed)]

    assert found("setpos")[0] == "SetPosition"  # the start of the label first
    assert found("posset")[:2] == ["SetPosition", "SetHandlePositions"]  # any order, fewest words first
    assert found("circcurve") == ["CurveCircle"]
    assert found("texnoise")[0] == "NoiseTexture"
    assert found("NoiTex")[0] == "NoiseTexture"  # before VoronoiTexture, which only contains it
    assert found("noise_tex")[0] == found("tex_noise")[0] == "NoiseTexture"
    assert found("instpoint") == ["InstanceOnPoints"]
    assert found("nosie")[0] == "NoiseTexture"  # one typo
    assert found("SP")[0] == "SetPosition"  # initials
    assert found("zzz") == []
    assert found("") == names
