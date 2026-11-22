"""Settings in brackets: `Name[SETTING, key: value](inputs)`, read by the core into `settings`.

The core knows no node: what a setting is called and what it takes, the host says. The shared
cases of conformance/bracket-cases.json are read by test_conformance.py; these look at the tree.
"""

from dataclasses import asdict

import pytest

from base_node import BnError, parse, to_source
from base_node import ast
from base_node.lexer import tokenize

HEAD = "kind graph g(a: Float, s: String) -> Float {\n"


def value_of(line):
    """The value of the first statement of a graph whose body is `line`, then `return a`."""
    return parse(HEAD + f"  {line}\n  return a\n}}\n").graphs[0].body[0].value


def test_brackets_are_tokens():
    assert [t.kind for t in tokenize("M[X]()")][:5] == ["IDENT", "[", "IDENT", "]", "("]


def test_settings_in_source_order_with_optional_keys():
    c = value_of('x = Math[ADD, use_clamp: true](Value: a, Value_001: 2.0)')
    assert [s.name for s in c.settings] == [None, "use_clamp"]
    assert isinstance(c.settings[0].value, ast.Ref) and c.settings[0].value.name == "ADD"
    assert isinstance(c.settings[1].value, ast.Bool) and c.settings[1].value.value is True
    # Positions are those of the setting, the key's when it has one
    assert [(s.line, s.col) for s in c.settings] == [(2, 12), (2, 17)]
    # The inputs stay arguments, apart from the settings
    assert [a.name for a in c.args] == ["Value", "Value_001"]


def test_values_a_setting_takes():
    c = value_of('x = T[-1, 2.5, "4D", false, _, (0.1, -0.2), Ramp((0.0, (1.0, 0.5, 0.0)), interpolation: EASE)]()')
    kinds = [type(s.value).__name__ for s in c.settings]
    assert kinds == ["Number", "Number", "String", "Bool", "Ref", "Tuple", "Call"]
    assert c.settings[0].value.value == -1 and c.settings[0].value.is_int
    assert c.settings[4].value.name == "_"
    ramp = c.settings[6].value
    assert ramp.name == "Ramp" and [a.name for a in ramp.args] == [None, "interpolation"]
    assert c.args == []


def test_body_call_and_pipe_and_template_take_settings():
    g = parse(HEAD + "  r = each[FACE](a, item: a) -> {\n    return item\n  }\n"
              "  p = a |> Store[INT, CURVE](name: \"i\")\n"
              "  t = pick<Vector>[POINT](s)\n  return a\n}\n").graphs[0]
    body = g.body[0].value
    assert isinstance(body, ast.BodyCall) and [s.value.name for s in body.settings] == ["FACE"]
    step = g.body[1].value.call
    assert step.name == "Store" and [s.value.name for s in step.settings] == ["INT", "CURVE"]
    t = g.body[2].value
    assert t.type_args == ["Vector"] and [s.value.name for s in t.settings] == ["POINT"]


def test_a_call_without_brackets_has_no_settings():
    c = value_of("x = Math(Value: a, Value_001: 2.0)")
    assert c.settings == [] and len(c.args) == 2


def test_the_tree_holds_settings_as_their_own_field():
    c = value_of("x = Math[ADD, use_clamp: true](Value: a)")
    d = asdict(c)
    assert d["settings"] == [
        {"name": None, "value": {"name": "ADD", "line": 2, "col": 12}, "line": 2, "col": 12},
        {"name": "use_clamp", "value": {"value": True, "line": 2, "col": 28}, "line": 2, "col": 17},
    ]


def test_printed_back():
    src = HEAD + "  x = Math[ADD, use_clamp: true](Value: a, Value_001: 2.0)\n  return x\n}\n"
    assert to_source(parse(src)) == src


@pytest.mark.parametrize("line, at, says", [
    ("x = Math[a](Value: 2.0)", (2, 12), "'a' holds a value"),
    ("x = Math[mode: (1, a)](Value: 2.0)", (2, 22), "'a' holds a value"),
    ("x = Math[](Value: a)", (2, 11), "empty settings"),
    ("x = Math[ADD]", (3, 3), "'(' and the inputs"),
    ("x = Math[use_clamp: true, ADD](Value: a)", (2, 29), "positional setting after named"),
])
def test_refused(line, at, says):
    with pytest.raises(BnError) as err:
        value_of(line)
    d = err.value.diagnostics[0]
    assert (d.line, d.col) == at and says in d.message


def test_nesting_in_settings_is_limited():
    deep = "(" * 40 + "1.0" + ")" * 40
    with pytest.raises(BnError) as err:
        value_of(f"x = T[{deep}]()")
    assert "nested too deeply" in err.value.diagnostics[0].message
