"""A name the printer writes, the lexer reads back as that name, wherever a name is written.

The names are those of corpus/v1 and of the backends of Blender 5.2 and 5.3 (each socket, panel,
graph, item, setting and enum value), adversarial ones and random ones. Each is printed where a
name goes, the printer deciding bare or quoted, and read back: the name must be the same. A name
the grammar takes no quote for (a binding, a `use`, an `as`) is written by its key, which must be
a bare identifier, its own key. rust/tests/names.rs does the same with the Rust core, and
conformance/name-cases.json holds the keys both must agree on.
"""

import copy
import json
import random
import re
import unicodedata
from dataclasses import fields, is_dataclass
from pathlib import Path

import pytest

from base_node import BnError, ast, parse, to_source, tokenize
from base_node.identifiers import CONTINUE, START, UNICODE_VERSION
from base_node.names import RESERVED, goes_on_name, is_bare, is_identifier, is_word, key, starts_name
from base_node.printer import quote

ROOT = Path(__file__).resolve().parents[2]
CASES = json.loads((ROOT / "conformance" / "name-cases.json").read_text(encoding="utf-8"))

# Names an audit would try: words of the language, signs it reads, digits and letters of every kind
ADVERSARIAL = [
    "", " ", "_", "__", "_1", "a", "a_", "A", "1", "1abc", "2D", "abc1", "a b", " a", "a ", "a-b", "a.b",
    "a::b", "::", "m::a", "a::", "::a", "a::b c", '"', 'a"b', "\\", "a\\b", "\n", "a\nb", "\t", "\r", "\x00",
    "\x1b", "\x7f", "\u2028", "\u00a0", "\u200b", "\u200d", "\ufeff", *sorted(RESERVED),
    *(w + "_" for w in sorted(RESERVED)), "Inf", "NaN", "True", "INF", "use", "from", "as", "in", "hide", "mute",
    "repeat", "simulate", "foreach", "iteration", "delta_time", "index", "element", "é", "e\u0301", "É",
    "Größe", "İ", "ǅ", "ﬁ", "ẞ", "Σ", "ΑΣ", "ρ, θ, φ", "θ", "Ⅻ", "ⅻ", "x²", "²", "½", "٣", "x٣", "٣x", "१२",
    "क्ष", "ক্ষ", "日本語", "한국어", "🙏", "a🙏", "𝔘𝔫𝔦", "a·b", "·", "a⋅b", "a×b", "°", "Rotation °",
    "BA⟂(BC)", "a\u0387b", "‿", "a‿b", "_‿", "Ⓐ", "ª", "º", "µ", "ŉ", "ﷺ", "a\U000e0100", "#ff0000", "#",
    "@", "$", "a$", "Value_001", "Value.001", "Shader_001", "Tessera · Region", "Input Image γ=log ",
]


def random_names(count=3000, seed=1):
    """Names of characters of every kind, ASCII and beyond: a property test with no library."""
    rng = random.Random(seed)
    alphabet = "aZ_09 -.:\"\\·⋅×²٣éΣ\u0301\u200d🙏日"
    out = []
    for _ in range(count):
        n = rng.randint(0, 6)
        chars = []
        for _ in range(n):
            if rng.random() < 0.6:
                chars.append(rng.choice(alphabet))
            else:
                code = rng.randint(0, 0x10FFFF)
                chars.append(chr(code) if not 0xD800 <= code <= 0xDFFF else "a")
        out.append("".join(chars))
    return out


def walk(node, out):
    """Add each name the AST holds."""
    if isinstance(node, (list, tuple)):
        for x in node:
            walk(x, out)
        return
    if not is_dataclass(node):
        return
    for name in ("name", "socket", "alias", "label"):
        value = getattr(node, name, None)
        if isinstance(value, str):
            out.add(value)
    if isinstance(node, ast.Setting) and isinstance(node.value, (ast.Ref, ast.String)):
        out.add(node.value.name if isinstance(node.value, ast.Ref) else node.value.value)
    for f in fields(node):
        walk(getattr(node, f.name), out)


def corpus_names():
    out = set()
    for path in sorted((ROOT / "corpus" / "v1").rglob("*.bn")):
        walk(parse(path.read_text(encoding="utf-8"), str(path)), out)
    return out


def backend():
    """(names, setting names, enum values) of the two backends."""
    names, settings, values = set(), set(), set()
    for version in ("5.2", "5.3"):
        data = json.loads((ROOT / "targets" / "backends" / f"blender-{version}.json").read_text(encoding="utf-8"))
        for nodes in data["kinds"].values():
            for node in nodes:
                names.update((node["name"], node["label"]))
                for s in node.get("settings", []):
                    settings.add(s["name"])
                    values.update(item["value"] for item in s.get("items") or [])
                for shape in [node, *node.get("variants", [])]:
                    for side in ("inputs", "outputs"):
                        for sock in shape.get(side, []):
                            names.update(v for v in (sock.get("name"), sock.get("key"), sock.get("identifier")) if v)
        for path in sorted((ROOT / "targets" / "backends" / f"blender-{version}").glob("*.json")):
            names.update(json.loads(path.read_text(encoding="utf-8")))
    return names, settings, values


BACKEND_NAMES, BACKEND_SETTINGS, BACKEND_VALUES = backend()
ALL_NAMES = sorted(corpus_names() | BACKEND_NAMES | BACKEND_SETTINGS | BACKEND_VALUES | set(ADVERSARIAL)
                   | set(random_names()) | {c["name"] for c in CASES["cases"]})
# Most names are words of ASCII letters, digits and `_`, which print and read alike: a few hundred of
# them stand for the others, and every other name is tried
PLAIN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
NAMES = [n for n in ALL_NAMES if not PLAIN.fullmatch(n) or n in RESERVED] \
    + [n for n in ALL_NAMES if PLAIN.fullmatch(n) and n not in RESERVED][::20]


def first(node, kind):
    """The first node of that type in the AST, depth first."""
    found = []

    def go(n):
        if found:
            return
        if isinstance(n, (list, tuple)):
            for x in n:
                go(x)
        elif is_dataclass(n):
            if isinstance(n, kind):
                found.append(n)
                return
            for f in fields(n):
                go(getattr(n, f.name))
    go(node)
    return found[0]


# Every place a name is printed, in one text: graph, panel, input, `as`, output, binding, input
# key, output access, setting, module path, frame, return field, `use` and its file
TEMPLATE = parse(
    'use m as n (k) from "m.bn"\n\n'
    'geometry graph g("Panel" {\n    "P" as templatealias: Float,\n    templateinput: Float\n  }) -> (o: Float) {\n'
    "  b = F[E, s: 1.0](i: templateinput).o\n  \"Frame\" {\n    c = m::h(b)\n  }\n  return (o: c)\n}\n",
    "names.bn")


def graph_of(f):
    return f.graphs[0]


def call_of(f):
    return graph_of(f).body[0].value.target


def frame_call(f):
    return graph_of(f).body[1].body[0].value


def ref_or_string(n):
    return ast.Ref(n, 0, 0) if is_word(n) else ast.String(n, 0, 0)


def value_of(v):
    return v.name if isinstance(v, ast.Ref) else v.value


def positions(n):
    """(where, change, read, written): how `n` is put where a name is printed, read back from the
    text printed, and what must be read. A name the grammar takes no quote for is its key there."""
    k = key(n)
    panel = lambda f: graph_of(f).param_tree[0]  # noqa: E731
    return [
        ("graph name", lambda f: setattr(graph_of(f), "name", n), lambda f: graph_of(f).name, n),
        ("panel", lambda f: setattr(panel(f), "name", n), lambda f: panel(f).name, n),
        ("input", lambda f: setattr(panel(f).items[1], "name", n), lambda f: panel(f).items[1].name, n),
        ("as key", lambda f: (setattr(panel(f).items[0], "name", n), setattr(panel(f).items[0], "alias", k)),
         lambda f: (panel(f).items[0].name, panel(f).items[0].alias), (n, k)),
        ("output", lambda f: setattr(graph_of(f).outputs[0], "name", n), lambda f: graph_of(f).outputs[0].name, n),
        ("return field", lambda f: setattr(graph_of(f).body[-1].value.fields[0], "name", n),
         lambda f: graph_of(f).body[-1].value.fields[0].name, n),
        ("input key", lambda f: setattr(call_of(f).args[0], "name", n), lambda f: call_of(f).args[0].name, n),
        ("output access", lambda f: setattr(graph_of(f).body[0].value, "socket", n),
         lambda f: graph_of(f).body[0].value.socket, n),
        ("enum value", lambda f: setattr(call_of(f).settings[0], "value", ref_or_string(n)),
         lambda f: value_of(call_of(f).settings[0].value), n),
        ("module path", lambda f: setattr(frame_call(f), "name", "m::" + n), lambda f: frame_call(f).name, "m::" + n),
        ("frame title", lambda f: setattr(graph_of(f).body[1], "label", n), lambda f: graph_of(f).body[1].label, n),
        ("binding", lambda f: (setattr(graph_of(f).body[0], "name", k),
                               setattr(frame_call(f).args[0], "value", ast.Ref(k, 0, 0))),
         lambda f: (graph_of(f).body[0].name, frame_call(f).args[0].value.name), (k, k)),
        ("use", lambda f: setattr(f.uses[0], "names", [k]), lambda f: f.uses[0].names, [k]),
        ("use source", lambda f: setattr(f.uses[0], "source", n), lambda f: f.uses[0].source, n),
    ]


def mismatches(n, places):
    """What of `places` does not read back: the name put in each of them, printed once."""
    file = copy.deepcopy(TEMPLATE)
    for _where, change, _read, _written in places:
        change(file)
    try:
        back = parse(to_source(file), "names.bn")
    except BnError as e:
        if len(places) == 1:
            return [f"{places[0][0]}: {n!r} is refused: {e}"]
        # Which place makes the text unreadable: each on its own
        return [m for place in places for m in mismatches(n, [place])]
    return [f"{where}: {n!r} read back as {read(back)!r}" for where, _c, read, written in places
            if read(back) != written]


def test_every_name_reads_back_wherever_it_is_printed():
    wrong = [m for n in NAMES for m in mismatches(n, positions(n))]
    assert not wrong, f"{len(wrong)} mismatches, of {len(NAMES)} names:\n" + "\n".join(wrong[:40])


def test_a_key_is_a_bare_name_of_its_own():
    for n in NAMES:
        k = key(n)
        assert is_bare(k) and key(k) == k, (n, k)
        assert [t.kind for t in tokenize(k)] == ["IDENT", "EOF"] and tokenize(k)[0].text == k, (n, k)


def test_bare_is_what_the_lexer_reads_as_one_name():
    for n in NAMES:
        tokens = [] if not n else tokenize(n, strict=False)
        one = len(tokens) == 2 and tokens[0].kind == "IDENT" and tokens[0].text == n
        assert is_bare(n) == (one and n not in RESERVED), n


def test_the_settings_and_enum_values_of_blender_are_bare():
    """The grammar takes no quoted setting name: every setting of Blender is written bare."""
    assert BACKEND_SETTINGS and all(is_bare(s) for s in BACKEND_SETTINGS)
    # An enum value that is no bare name is written as a string, `NoiseTexture[noise_dimensions: "3D"]`
    assert "3D" in BACKEND_VALUES and not is_word("3D") and quote("3D") == '"3D"'


def test_a_setting_name_reads_back():
    for s in sorted(BACKEND_SETTINGS):
        place = ("setting", lambda f: setattr(call_of(f).settings[1], "name", s), lambda f: call_of(f).settings[1].name, s)
        assert not mismatches(s, [place])


def test_what_each_rule_says():
    assert is_bare("ρ_θ_φ") and is_bare("_") and is_bare("Größe") and is_bare("e\u0301")
    for n in ("x²", "½", "٣x", "a·b", "a b", "", "inf", "not", "dot", "a\u200bb"):
        assert not is_bare(n), n
    assert not is_word("_") and is_word("FACE")
    assert key("Rotation °") == "rotation" and key("x²") == "x" and key("٣x") == "_٣x" and key("") == "_"
    assert key("inf") == "inf_" and key("a·b") == "a_b" and key("ΑΣ Β") == "ας_β"
    # The digits of a number are ASCII's: `٣` and `²` are neither a number nor a name
    for text in ("٣", "x = ²"):
        with pytest.raises(BnError, match="unexpected character"):
            tokenize(text)


@pytest.mark.parametrize("case", CASES["cases"], ids=lambda c: repr(c["name"]))
def test_name_cases_read_as_rust_reads_them(case):
    """The key and the printed form of a name, as rust/tests/names.rs finds them."""
    n = case["name"]
    assert (key(n), is_bare(n), is_word(n)) == (case["key"], case["bare"], case["word"])


def rust_table(name):
    text = (ROOT / "rust" / "src" / "identifiers.rs").read_text(encoding="utf-8")
    body = re.search(rf"const {name}: &\[u32\] = &\[(.*?)\];", text, re.S).group(1)
    return tuple(int(x, 16) for x in re.findall(r"0x[0-9a-f]+", body))


def test_the_rust_core_holds_the_same_tables():
    text = (ROOT / "rust" / "src" / "identifiers.rs").read_text(encoding="utf-8")
    assert f'UNICODE_VERSION: &str = "{UNICODE_VERSION}"' in text
    assert rust_table("START") == START and rust_table("CONTINUE") == CONTINUE


def test_the_tables_are_unicodes_identifiers():
    """The tables say what Python's identifiers do, `·` aside. A Python of another Unicode differs
    only by the characters one of the two versions has not assigned, and by the four Unicode 15.1
    let into its identifiers (the joiners U+200C and U+200D, the middle dots U+30FB and U+FF65):
    Unicode never takes a character out."""
    version = lambda v: tuple(int(x) for x in v.split("."))  # noqa: E731
    older, newer = (version(unicodedata.unidata_version) < version(UNICODE_VERSION),
                    version(unicodedata.unidata_version) > version(UNICODE_VERSION))
    for code in range(0x80, 0x110000, 3):
        c = chr(code)
        for ours, python in ((starts_name(c), c.isidentifier()), (goes_on_name(c), ("a" + c).isidentifier())):
            python = python and c != "·"
            if ours != python:
                # A character the older of the two versions has not assigned
                late = unicodedata.category(c) == "Cn" or c in "\u200c\u200d\u30fb\uff65"
                assert (older and ours and late) or (newer and python), hex(code)
    assert is_identifier("a\u0387b") and not goes_on_name("·")
