"""A .bn text may come from anyone: reading it ends with a tree or a BnError, never a crash or a hang.

The limits are those of spec/reference.md, "Limits"; rust/tests/limits.rs holds the same cases.
"""

import random
from pathlib import Path

import pytest

from base_node_blender import MAX_HEIGHT, MAX_NESTING, MAX_SOURCE_BYTES, BnError, compile_source, format_source, parse
from base_node.lexer import tokenize
from base_node.printer import quote

ROOT = Path(__file__).resolve().parents[2]
HEAD = "geometry graph g(a: Float, v: Vector) -> Float {\n  return "
TAIL = "\n}\n"

# name -> the source nested n times
SHAPES = {
    "parentheses": lambda n: HEAD + "(" * n + "a" + ")" * n + TAIL,
    "minus": lambda n: HEAD + "-" * n + "a" + TAIL,
    "not": lambda n: HEAD + "not " * n + "a" + TAIL,
    "calls": lambda n: HEAD + "Math(" * n + "a" + ")" * n + TAIL,
    "options": lambda n: HEAD + "Math(" + "x(" * (n - 1) + ")" * n + TAIL,
    "frames": lambda n: "geometry graph g(a: Float) -> Float {\n" + "{\n" * n + "}\n" * n + "  return a\n}\n",
    "zones": lambda n: ("geometry graph g(a: Float) -> Float {\n" + "x = repeat(2, a: a) -> {\n" * n
                        + "return a\n}\n" * n + "return a\n}\n"),
    "panels": lambda n: 'geometry graph g(' + '"P" { ' * n + "a: Float" + " }" * n + ") -> Float {\n  return a\n}\n",
}
# The same for what stands side by side in the text and one inside another in the tree: n operators
CHAINS = {
    "plus": lambda n: HEAD + "a" + " + a" * n + TAIL,
    "times": lambda n: HEAD + "a" + " * a" * n + TAIL,
    "and": lambda n: HEAD + "a" + " and a" * n + TAIL,
    "or": lambda n: HEAD + "a" + " or a" * n + TAIL,
    "pipe": lambda n: HEAD + "a" + " |> Math()" * n + TAIL,
    "member": lambda n: HEAD + "v" + ".x" * n + TAIL,
}


@pytest.mark.parametrize("shape", SHAPES)
def test_nesting_up_to_the_limit(shape, schema):
    source = SHAPES[shape](MAX_NESTING)
    parse(source)
    format_source(source)
    if shape in ("parentheses", "minus", "calls", "zones"):
        compile_source(source, schema)


@pytest.mark.parametrize("shape", SHAPES)
@pytest.mark.parametrize("n", [MAX_NESTING + 1, 20_000])
def test_nesting_past_the_limit_is_an_error(shape, n):
    with pytest.raises(BnError, match="nested too deeply"):
        parse(SHAPES[shape](n))


@pytest.mark.parametrize("chain", CHAINS)
def test_chain_up_to_the_limit(chain, schema):
    source = CHAINS[chain](MAX_HEIGHT - 1)
    parse(source)
    format_source(source)
    if chain != "member":
        compile_source(source, schema)


@pytest.mark.parametrize("chain", CHAINS)
@pytest.mark.parametrize("n", [MAX_HEIGHT, 20_000])
def test_chain_past_the_limit_is_an_error(chain, n):
    with pytest.raises(BnError, match="nested too deeply"):
        parse(CHAINS[chain](n))


def test_chains_inside_brackets_add_up():
    # Neither the brackets nor one chain passes its limit; the tree they make does
    step = MAX_HEIGHT // 8
    source = HEAD + "Math(" * 9 + "a" + (" + a" * step + ")") * 9 + TAIL
    parse(HEAD + "Math(" * 7 + "a" + (" + a" * step + ")") * 7 + TAIL)
    with pytest.raises(BnError, match="nested too deeply"):
        parse(source)


@pytest.mark.parametrize("number", ["9223372036854775808", "9" * 100_000, "1e999", "1.0e400"])
def test_number_too_large(number):
    with pytest.raises(BnError, match="number too large"):
        parse(HEAD + number + TAIL)


def test_largest_numbers():
    value = parse(HEAD + "9223372036854775807" + TAIL).graphs[0].body[0].value
    assert (value.value, value.is_int) == (2 ** 63 - 1, True)
    parse(HEAD + "1.7e308" + TAIL)


def test_source_too_large():
    padding = "// " + "x" * 1021 + "\n"
    source = padding * (MAX_SOURCE_BYTES // 1024) + HEAD + "a" + TAIL
    with pytest.raises(BnError, match="source too large"):
        parse(source)
    with pytest.raises(BnError, match="source too large"):
        format_source(source)
    # Bytes of UTF-8 are counted, not characters
    with pytest.raises(BnError, match="source too large"):
        parse("// " + "é" * (MAX_SOURCE_BYTES // 2) + "\n" + HEAD + "a" + TAIL)


def test_quote_cannot_be_left():
    # A label read from a node, written back: what would close the string is replaced
    text = quote('x" }\ngeometry graph evil() -> Float {\r')
    assert text[0] == text[-1] == '"' and '"' not in text[1:-1]
    assert "\n" not in text and "\r" not in text
    assert [t.kind for t in tokenize(text)] == ["STRING", "EOF"]


def corpus():
    paths = sorted((ROOT / "conformance").glob("*.bn")) + sorted((ROOT / "stdlib").glob("*.bn")) \
        + sorted((ROOT / "python" / "tests" / "fixtures").glob("*.bn"))
    return [p.read_text(encoding="utf-8") for p in paths]


FRAGMENTS = ["(", ")", "{", "}", ",", ":", "::", "=", "->", "|>", ".", "..", "@", "#", '"', "\n", "-", "not ",
             "closure(", "repeat(", "simulate(", "foreach(", "use ", " as ", " in ", "return ", "graph ", "é", "\x00",
             "9" * 30, "1e999", "//"]


def mutated(source, rng):
    """The source cut somewhere, or with a few tokens dropped, doubled or put in."""
    if rng.random() < 0.25:
        return source[:rng.randrange(len(source))]
    for _ in range(rng.randint(1, 4)):
        i = rng.randrange(len(source))
        j = min(len(source), i + rng.randint(0, 12))
        source = source[:i] + rng.choice(["", source[i:j] * 2, rng.choice(FRAGMENTS)]) + source[j:]
    return source


def test_text_cut_anywhere_only_raises_bn_errors():
    # A look ahead must not read past the end of file: `x = graph() ->` and nothing after
    for name in ("conformance/all_features.bn", "python/tests/fixtures/zones.bn", "python/tests/fixtures/bundles.bn"):
        source = (ROOT / name).read_text(encoding="utf-8")
        for end in range(len(source)):
            try:
                parse(source[:end])
            except BnError:
                pass
    for tail in ("x = graph() ->", "x = graph() -> (a: Float)", "x = closure(", "x = simulate()", "x = f(a()"):
        with pytest.raises(BnError):
            parse("geometry graph g() -> Float {\n  " + tail)


def test_mutated_sources_only_raise_bn_errors(schema):
    rng = random.Random(20261115)
    sources = corpus()
    assert len(sources) > 20
    for _ in range(1500):
        source = mutated(rng.choice(sources), rng)
        tokenize(source, strict=False)
        for read in (parse, format_source, lambda s: compile_source(s, schema)):
            try:
                read(source)
            except BnError:
                pass
