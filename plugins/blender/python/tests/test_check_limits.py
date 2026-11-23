"""The checker reads what the parser reads, up to its limits (spec/reference.md, "Limits", of the core),
and a text that comes from anyone ends with graphs or a BnError, never a crash or a hang."""

import random
from pathlib import Path

from base_node_blender import MAX_HEIGHT, MAX_NESTING, BnError, compile_source, format_source, parse
from base_node.lexer import tokenize

ROOT = Path(__file__).resolve().parents[2]
HEAD = "geometry graph g(a: Float, v: Vector) -> Float {\n  return "
TAIL = "\n}\n"

# name -> the source nested n times, of the shapes the checker builds
SHAPES = {
    "parentheses": lambda n: HEAD + "(" * n + "a" + ")" * n + TAIL,
    "minus": lambda n: HEAD + "-" * n + "a" + TAIL,
    "calls": lambda n: HEAD + "abs(" * n + "a" + ")" * n + TAIL,
    "zones": lambda n: ("geometry graph g(a: Float) -> Float {\n" + "x = repeat(2, a: a) -> {\n" * n
                        + "return a\n}\n" * n + "return a\n}\n"),
}
# The same for what stands side by side in the text and one inside another in the tree: n operators
CHAINS = {
    "plus": lambda n: HEAD + "a" + " + a" * n + TAIL,
    "times": lambda n: HEAD + "a" + " * a" * n + TAIL,
    "and": lambda n: HEAD + "a" + " and a" * n + TAIL,
    "or": lambda n: HEAD + "a" + " or a" * n + TAIL,
    "pipe": lambda n: HEAD + "a" + " |> abs()" * n + TAIL,
}


def test_nesting_up_to_the_limit(schema):
    for shape in SHAPES.values():
        compile_source(shape(MAX_NESTING), schema)


def test_chain_up_to_the_limit(schema):
    for chain in CHAINS.values():
        compile_source(chain(MAX_HEIGHT - 1), schema)


def corpus():
    paths = sorted((ROOT / "stdlib").glob("*.bn")) + sorted((ROOT / "python" / "tests" / "fixtures").glob("*.bn"))
    return [p.read_text(encoding="utf-8") for p in paths]


FRAGMENTS = ["(", ")", "[", "]", "{", "}", ",", ":", "::", "=", "->", "|>", ".", "..", "@", "#", '"', "\n", "-", "not ",
             "closure(", "repeat(", "simulate(", "foreach(", "use ", " as ", " in ", "return ", "graph ", "é", "\x00",
             "9" * 30, "1e999", "//", "\\", "\\u{", "inf"]


def mutated(source, rng):
    """The source cut somewhere, or with a few tokens dropped, doubled or put in."""
    if rng.random() < 0.25:
        return source[:rng.randrange(len(source))]
    for _ in range(rng.randint(1, 4)):
        i = rng.randrange(len(source))
        j = min(len(source), i + rng.randint(0, 12))
        source = source[:i] + rng.choice(["", source[i:j] * 2, rng.choice(FRAGMENTS)]) + source[j:]
    return source


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
