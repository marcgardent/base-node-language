"""Repeat zones: `r = repeat(count, state: start, …) -> { … return (state: next, …) }`."""

import pytest

from base_node_blender import BnError, compile_source, ir, parse
from base_node.format import format_source
from base_node.printer import to_source


def compile_one(source, schema):
    return compile_source(source, schema, "t.bn")[-1]


def errors(source, schema):
    with pytest.raises(BnError) as err:
        compile_source(source, schema, "t.bn")
    return [str(d) for d in err.value.diagnostics]


def graph(body):
    return f"geometry graph g(geometry: Geometry, t: Float) -> Float {{\n{body}\n}}\n"


def zone(g):
    rin = next(n for n in g.nodes if n.bl_idname == ir.REPEAT_INPUT)
    return rin, g.node(rin.pair)


def test_fixture_prints_back_unchanged(fixture_text):
    src = fixture_text("repeat.bn")
    assert to_source(parse(src)) == src
    assert format_source(src) == src


def test_a_long_repeat_head_takes_one_state_per_line():
    src = graph("  r = repeat(\n    10,\n    somme_des_valeurs_trouvées: 0.0,\n    amplitude_de_départ: 0.5,\n"
                "    fréquence_de_départ: 1.0) -> {\n    return ()\n  }\n  return r.somme_des_valeurs_trouvées")
    assert to_source(parse(src)) == src


def test_states_become_items_of_both_nodes(schema):
    g = compile_one(graph("  r = repeat(4, somme: 0.0, f: 1.0) -> {\n    return (somme: somme + t * f, f: f * 2.0)\n"
                          "  }\n  return r.somme"), schema)
    rin, rout = zone(g)
    assert rin.items == rout.items == [("somme", "Float"), ("f", "Float")]
    assert rin.values == {"Iterations": 4, "somme": 0.0, "f": 1.0}
    assert rout.name == "r" and [i for i, _l in rout.links] == ["somme", "f"]
    out = g.node(ir.GROUP_OUTPUT)
    assert out.links == [("Float", ir.Link(rout.id, "somme"))]


def test_a_state_left_out_goes_on_unchanged(schema):
    g = compile_one(graph("  r = repeat(4, somme: 0.0, pas: t) -> {\n    return (somme: somme + pas)\n  }\n"
                          "  return r.somme"), schema)
    rin, rout = zone(g)
    assert ("pas", ir.Link(rin.id, "pas")) in rout.links
    assert rin.links == [("pas", ir.Link(ir.GROUP_INPUT, "t"))]


def test_iteration_is_the_turn_number(schema):
    g = compile_one(graph("  r = repeat(3, somme: 0.0) -> {\n    return somme + iteration\n  }\n  return r"), schema)
    rin, _rout = zone(g)
    add = next(n for n in g.nodes if n.bl_idname == "ShaderNodeMath")
    assert ("Value_001", ir.Link(rin.id, "Iteration")) in add.links


def test_names_of_the_body_stay_inside(schema):
    msgs = errors(graph("  r = repeat(3, s: 0.0) -> {\n    d = s * 2.0\n    return d\n  }\n  return d"), schema)
    assert msgs == ["t.bn:6:10  unknown name 'd'"]


@pytest.mark.parametrize("body, message", [
    ("  r = repeat(3, s: 0.0) -> {\n    x = s\n  }\n  return r", "t.bn:2:7  missing return in repeat of 'r'"),
    ("  r = repeat(3, s: 0.0, u: 1.0) -> {\n    return s\n  }\n  return r.s",
     "t.bn:3:5  this repeat has multiple states: return (s: …, u: …)"),
    ("  r = repeat(3, s: 0.0) -> {\n    return (v: s)\n  }\n  return r", "t.bn:3:13  'v' is not a repeat state; states: s"),
    ("  r = repeat(3, s: 0.0, s: 1.0) -> {\n    return ()\n  }\n  return r", "t.bn:2:25  state 's' declared twice"),
    ("  r = repeat(3, iteration: 0.0) -> {\n    return ()\n  }\n  return r",
     "t.bn:2:17  'iteration' is the loop counter: choose another state name"),
    ("  r = repeat(3, s) -> {\n    return ()\n  }\n  return r", "t.bn:2:17  a repeat state is named: repeat(10, state: start)"),
])
def test_wrong_zones_are_reported(schema, body, message):
    assert errors(graph(body), schema) == [message]


@pytest.mark.parametrize("body, message", [
    ("  r = repeat(s: 0.0) -> {\n    return s\n  }\n  return r",
     "t.bn:2:7  repeat expects iteration count first: repeat(10, state: start, …) -> { … }"),
    ("  r = repeat(3) -> {\n    return 1.0\n  }\n  return r",
     "t.bn:2:7  repeat expects at least one state: repeat(10, state: start) -> { … }"),
    ("  r = Grid(1.0, 1.0) -> {\n    return 1.0\n  }\n  return r",
     "t.bn:2:7  'Grid' takes no body: repeat, simulate and foreach do"),
    ("  r = m::repeat(3, s: 0.0) -> {\n    return s\n  }\n  return r",
     "t.bn:2:7  'm::repeat' takes no body: repeat, simulate and foreach do"),
])
def test_the_shape_of_a_repeat_is_the_checker_s(schema, body, message):
    # The language reads any call with a body: which names take one, and with which arguments, Blender's library says
    assert type(parse(graph(body), "t.bn").graphs[0].body[0].value).__name__ == "BodyCall"
    assert errors(graph(body), schema) == [message]


def test_a_call_with_a_body_is_the_value_of_an_assignment():
    with pytest.raises(BnError) as err:
        parse(graph("  return repeat(3, s: 0.0) -> {\n    return s\n  }"), "t.bn")
    assert [str(d) for d in err.value.diagnostics] == [
        "t.bn:2:10  a call with a body is the value of an assignment: r = repeat(…) -> { … }"]


def test_repeat_is_a_name_like_any_other(schema):
    # No word of the language: a state, a local or a graph may be called repeat
    src = ("geometry graph repeat(x: Float) -> Float {\n  return x\n}\n\n"
           "geometry graph g(t: Float) -> Float {\n  repeat_2 = repeat(t)\n  r = repeat(2, repeat: repeat_2) -> {\n"
           "    return repeat * 0.5\n  }\n  return r\n}\n")
    assert to_source(parse(src)) == src and format_source(src) == src
    g = compile_one(src, schema)
    assert [n.group for n in g.nodes if n.group] == ["repeat"]
    assert len([n for n in g.nodes if n.bl_idname == ir.REPEAT_INPUT]) == 1


def test_the_spelling_without_an_arrow_says_what_to_write(schema):
    # `r = repeat(…) {` reads as a call, then a frame with no title: the call of a zone with no body is refused
    old = graph("  r = repeat(3, s: 0.0) {\n    return s\n  }\n  return r")
    assert errors(old, schema)[0] == "t.bn:2:7  repeat takes a body after '->': r = repeat(10, state: start) -> { … }"
    # A frame with no title after a call of any other name is what it was
    framed = graph("  a = sin(t)\n  {\n    b = a * 2.0\n  }\n  return b")
    assert to_source(parse(framed)) == framed
    assert len(compile_one(framed, schema).frames) == 1
