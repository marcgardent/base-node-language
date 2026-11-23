"""The names of Blender read back wherever the printer writes them: those of corpus/v1 and of the
backends of Blender 5.2 and 5.3 (each socket, panel, graph, item, setting and enum value). Each is
printed where a name goes, the printer of the core deciding bare or quoted, and read back: the name
must be the same. The core's tests do the same with adversarial and random names.
"""

import copy
import json
import re
from dataclasses import fields, is_dataclass
from pathlib import Path

from base_node import BnError, ast, parse, to_source, tokenize
from base_node.names import RESERVED, is_bare, is_word, key
from base_node.printer import quote

ROOT = Path(__file__).resolve().parents[2]


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
ALL_NAMES = sorted(corpus_names() | BACKEND_NAMES | BACKEND_SETTINGS | BACKEND_VALUES)
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


def test_every_name_of_blender_reads_back_wherever_it_is_printed():
    wrong = [m for n in NAMES for m in mismatches(n, positions(n))]
    assert not wrong, f"{len(wrong)} mismatches, of {len(NAMES)} names:\n" + "\n".join(wrong[:40])


def test_a_key_is_a_bare_name_of_its_own():
    for n in NAMES:
        k = key(n)
        assert is_bare(k) and key(k) == k, (n, k)
        assert [t.kind for t in tokenize(k)] == ["IDENT", "EOF"] and tokenize(k)[0].text == k, (n, k)


def test_the_settings_and_enum_values_of_blender_are_bare():
    """The grammar takes no quoted setting name: every setting of Blender is written bare."""
    assert BACKEND_SETTINGS and all(is_bare(s) for s in BACKEND_SETTINGS)
    # An enum value that is no bare name is written as a string, `NoiseTexture[noise_dimensions: "3D"]`
    assert "3D" in BACKEND_VALUES and not is_word("3D") and quote("3D") == '"3D"'


def test_a_setting_name_reads_back():
    for s in sorted(BACKEND_SETTINGS):
        place = ("setting", lambda f: setattr(call_of(f).settings[1], "name", s), lambda f: call_of(f).settings[1].name, s)
        assert not mismatches(s, [place])
