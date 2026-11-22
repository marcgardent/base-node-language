"""Tree -> text -> tree is exact: any string, inf and nan, a set of enum values read back as written.

The cases about the text are shared with Rust (conformance/exact-cases.json); these look at the tree,
the tokens and the printer. rust/tests/exact.rs holds the same.
"""

import math
import random

import pytest

from base_node import BnError, ast, format_source, parse
from base_node.lexer import span_at, tokenize, width
from base_node.names import key, snake
from base_node.printer import call_name, expr, quote

HEAD = "geometry graph g(a: Float) -> Float {\n"


def value(source):
    """The value of `x = …`, the first statement of a graph."""
    return parse(HEAD + f"  x = {source}\n  return a\n}}\n").graphs[0].body[0].value


def test_any_string_reads_back_as_it_was():
    rng = random.Random(7)
    alphabet = [chr(c) for c in range(0x80)] + ["é", "✓", "😀", " ", "﻿", "\U0010ffff"]
    strings = ["", '"', "\\", "\\u{41}", "\r\n", "\x00", "\x7f"] + [
        "".join(rng.choice(alphabet) for _ in range(rng.randrange(12))) for _ in range(500)]
    for s in strings:
        tokens = tokenize(quote(s))
        assert [(t.kind, t.text) for t in tokens] == [("STRING", s), ("EOF", "")], repr(s)
        assert value(f"F(s: {quote(s)})").args[0].value.value == s


def test_the_canonical_escapes():
    assert quote('a"b\\c') == r'"a\"b\\c"'
    assert quote("\n\t\r") == r'"\n\t\r"'
    assert quote("\x00\x1b\x7f") == r'"\u{0}\u{1b}\u{7f}"'
    # Every other character is itself, a line separator and a non-character too
    assert quote("é😀 \U0010ffff") == '"é😀 \U0010ffff"'


def test_escapes_are_read_in_either_case():
    assert value(r'"\u{1F600}\u{1f600}\u{000041}"').value == "😀😀A"


def test_a_raw_tab_is_read_as_itself_and_printed_escaped():
    assert value('"a\tb"').value == "a\tb"
    assert format_source(HEAD + '  x = "a\tb"\n  return a\n}\n') == HEAD + '  x = "a\\tb"\n  return a\n}\n'


def test_a_string_token_measures_its_source():
    t = tokenize(r'x = "a\"b\u{1F600}" + y')[2]
    assert (t.kind, t.text, t.col, width(t)) == ("STRING", 'a"b😀', 5, 15)
    assert tokenize(r'x = "a\"b\u{1F600}" + y')[3].col == 21
    # What a diagnostic points to is the whole string, escapes and quotes
    assert span_at(r'  s = F("a\"b")', 10) == (8, 14)


@pytest.mark.parametrize("line, value, size", [
    ('"abc', "abc", 4),                # unclosed: to the line's end
    (r'"a\qb"', r"a\qb", 6),           # an unknown escape is kept as written
    (r'"a\u{110000}', r"a\u{110000}", 12),
    ('"ab\\', "ab\\", 4),             # a backslash at the end
])
def test_the_editor_reads_any_string(line, value, size):
    t = tokenize(line, strict=False)[0]
    assert (t.text, width(t)) == (value, size)


def test_a_comment_after_an_escaped_string_stays_after_it():
    source = HEAD + '  x = "say \\"hi\\""  // a note\n  return a\n}\n'
    assert format_source(source) == source


@pytest.mark.parametrize("escape", [r"\q", r"\u41", r"\u{}", r"\u{110000}", r"\u{d800}", r"\u{dfff}", r"\u{1234567}"])
def test_an_unknown_escape_is_refused_at_its_backslash(escape):
    with pytest.raises(BnError) as err:
        tokenize(f'x = "ok{escape}"', "t.bn")
    d = err.value.diagnostics[0]
    assert (d.line, d.col) == (1, 8)
    assert d.message.startswith("unknown escape '\\")
    assert r"\", \\, \n, \t, \r and \u{…}" in d.message


def test_inf_and_nan_are_floats():
    inf, minus, nan = value("inf"), value("-inf"), value("nan")
    assert isinstance(inf, ast.Number) and inf.value == math.inf and not inf.is_int
    assert minus.value == -math.inf and not minus.is_int
    assert math.isnan(nan.value) and not nan.is_int
    assert [expr(e) for e in (inf, minus, nan)] == ["inf", "-inf", "nan"]
    assert expr(ast.Number(-math.nan, False, 0, 0)) == "nan"
    assert [t.kind for t in tokenize("inf nan inf_x Inf nan2")][:5] == ["NUMBER", "NUMBER", "IDENT", "IDENT", "IDENT"]


def test_a_setting_takes_inf():
    setting = value("Value[value: -inf]()").settings[0]
    assert setting.value.value == -math.inf


def test_inf_and_nan_are_reserved():
    assert snake("inf") == "inf_" and key("nan") == "nan_" and key("Inf") == "Inf"
    with pytest.raises(BnError, match="'nan' is a reserved word: choose another name"):
        parse(HEAD + "  r = repeat(2, nan: a) -> {\n    return a\n  }\n  return a\n}\n")


def test_a_qualified_name_after_the_module_is_quoted_when_not_identifiers():
    assert call_name("m::f") == "m::f" and call_name("m::a::b") == "m::a::b" and call_name("f") == "f"
    assert call_name("m::Big Blend") == 'm::"Big Blend"'
    assert call_name("m::x::Big Blend") == 'm::"x::Big Blend"'
    assert [call_name(f"m::{w}") for w in ("true", "inf", "dot")] == ['m::"true"', 'm::"inf"', 'm::"dot"']
    for name in ("m::Big Blend", "m::x::Big Blend", 'm::say "hi"', "m::inf", "m::a::b"):
        call = value(f"{call_name(name)}(a)")
        assert call.name == name


def test_settings_hold_a_set_of_enum_values():
    one, none, two, alone = (value(f"HandleTypeSelection[mode: {v}]()").settings[0].value
                             for v in ("(LEFT,)", "()", "(LEFT, RIGHT)", "(LEFT)"))
    assert isinstance(one, ast.Tuple) and [i.name for i in one.items] == ["LEFT"]
    assert isinstance(none, ast.Tuple) and none.items == []
    assert [i.name for i in two.items] == ["LEFT", "RIGHT"]
    assert isinstance(alone, ast.Ref) and alone.name == "LEFT"
    assert [expr(v) for v in (one, none, two)] == ["(LEFT,)", "()", "(LEFT, RIGHT)"]


def test_a_one_item_tuple_spread_over_lines_keeps_its_comma():
    long = "A" * 100
    source = HEAD + f"  x = HandleTypeSelection[\n    mode: (\n      {long},)]()\n  return a\n}}\n"
    assert format_source(source) == source
    assert isinstance(parse(source).graphs[0].body[0].value.settings[0].value, ast.Tuple)


def test_outside_settings_a_comma_makes_no_tuple():
    assert isinstance(value("(a,)"), ast.Ref)


def test_a_string_with_escapes_is_one_string_to_a_highlighter():
    from base_node_cli.refdoc import highlight
    html = highlight(r'x = F(s: "a \"b\" \u{1F600}", t: inf)')
    assert '<span class="str">&quot;a \\&quot;b\\&quot; \\u{1F600}&quot;</span>' in html
    assert '<span class="num">inf</span>' in html
