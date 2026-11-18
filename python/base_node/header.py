"""What a .bn file says of itself: the `// @name value` lines at its head.

    // @module mesh_maps
    // @title Mesh maps
    // @author Marc
    // @license MIT
    // @offer library, groups

The head is the comment and blank lines before the first `use` or graph. `@module`,
`@version` and `@edition` are those of the standard library, `@target` the targets the file
promises to fit (spec/targets.md); the others tell a
host what it may do with the file when it is dropped on it (see `OFFERS`). A directive this
module does not know is left alone, for other tools to read; one it knows is checked.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, fields, is_dataclass

from . import ast
from .errors import BnError, Diagnostic
from .parser import parse
from .schema import key

# What a dropped file may be used for, in the order a dialog lists them
OFFERS = ("library", "groups", "example", "modifier")
# The mesh `modifier` makes when no object takes the modifier
MESHES = ("cube", "plane", "sphere", "cylinder", "grid")
TEXT = ("title", "author", "license", "version", "edition")
KNOWN = {"module", "target", "offer", "example", "modifier", "mesh", *TEXT}

DIRECTIVE = re.compile(r"//\s*@(?P<name>[A-Za-z_][\w-]*)(?P<space>\s*)(?P<value>.*)$")


@dataclass
class Header:
    """The directives of a file, checked against its graphs.

    `offer` is what the file offers, as written or inferred; `example` and `modifier` the
    graph each of these uses (None when not offered), `examples` and `modifiers` every graph
    that could be used. `lines` keeps the line of each directive written.
    """
    module: str | None = None
    version: str | None = None
    target: list = field(default_factory=list)  # the targets promised, none when not written
    edition: str | None = None
    title: str | None = None
    author: str | None = None
    license: str | None = None
    offer: list = field(default_factory=list)
    offer_written: bool = False
    example: str | None = None
    modifier: str | None = None
    mesh: str = "cube"
    examples: list = field(default_factory=list)
    modifiers: list = field(default_factory=list)
    lines: dict = field(default_factory=dict)


def directives(source):
    """[(name, value, line, col of the value)] of the head of the source, as written."""
    out = []
    for number, raw in enumerate(source.splitlines(), 1):
        text = raw.strip()
        if not text:
            continue
        if not text.startswith("//"):
            break
        m = DIRECTIVE.match(text)
        if m is None or (m.group("value") and not m.group("space")):
            continue  # a comment, or `// @target"x"`: not a directive
        col = raw.index(text) + m.start("value") + 1
        out.append((m.group("name"), m.group("value").strip(), number, col))
    return out


def _unquote(value):
    """A quoted name, or a bare one, as written: None when it is neither."""
    if len(value) >= 2 and value[0] == value[-1] == '"':
        inner = value[1:-1]
        return inner if '"' not in inner and inner else None
    return value if value.isidentifier() else None


def _calls(node, out):
    """Add to `out` the name of every call under an AST node."""
    if isinstance(node, list):
        for item in node:
            _calls(item, out)
    elif is_dataclass(node):
        if isinstance(node, ast.Call):
            out.add(node.name)
        for f in fields(node):
            value = getattr(node, f.name)
            if isinstance(value, (list,)) or is_dataclass(value):
                _calls(value, out)


def _setting(g, name):
    """The value of a tree setting the graph writes, as `geometry(is_modifier: true) graph`, or None."""
    for arg in g.settings:
        if arg.name == name and isinstance(arg.value, ast.Bool):
            return arg.value.value
    return None


def shapes(file):
    """(examples, modifiers): the names of the graphs nobody calls that make their own geometry
    (a Geometry output, no Geometry input), then of those that are modifiers (first input and
    first output Geometry, as the Blender builder decides)."""
    called = set()
    for g in file.graphs:
        _calls(g.body, called)
    examples, modifiers = [], []
    for g in file.graphs:
        if g.kind != "geometry" or key(g.name) in called or g.type_params:
            continue
        ins = [p.type for p in ast.flatten(g.params)]
        outs = [p.type for p in ast.flatten(g.outputs)]
        modifier = _setting(g, "is_modifier")
        if modifier is None:
            modifier = bool(ins and outs and ins[0] == outs[0] == "Geometry")
        if modifier:
            modifiers.append(g.name)
        if "Geometry" in outs and "Geometry" not in ins:
            examples.append(g.name)
    return examples, modifiers


def header(source, filename="<text>", file=None):
    """The checked Header of a .bn source. Raises BnError: a malformed directive, a choice
    offered that no graph allows, a graph named that is not one of the file or not of its shape.

    `file` is the source's AST when the caller has it already: else the source is parsed, and
    a syntax error is raised as it is.
    """
    h = Header()
    diags = []

    def error(line, col, message):
        diags.append(Diagnostic(filename, line, col, message))

    written = {}
    for name, value, line, col in directives(source):
        if name not in KNOWN:
            continue
        if name in written:
            error(line, col, f"@{name} is already set on line {written[name][1]}")
            continue
        written[name] = (value, line, col)
        h.lines[name] = line
        if not value:
            error(line, col, f"@{name} needs a value")

    def get(name):
        value, line, col = written.get(name, ("", 0, 0))
        return (value, line, col) if value else (None, line, col)

    for name in TEXT:
        value = get(name)[0]
        if value and len(value) >= 2 and value[0] == value[-1] == '"':
            value = value[1:-1]
        setattr(h, name, value)
    value, line, col = get("target")
    if value is not None:
        from .targets import target_names

        known, at = target_names(), col
        for part in value.split(","):
            word = part.strip().strip('"')
            where = at + len(part) - len(part.lstrip())
            at += len(part) + 1
            if known and word not in known:
                error(line, where, f"@target '{word}': one of {', '.join(known)}")
            elif word not in h.target:
                h.target.append(word)
    value, line, col = get("module")
    if value is not None:
        name = _unquote(value)
        if name is None or not name.isidentifier():
            error(line, col, f"@module '{value}': a module is named by an identifier "
                             "(letters, digits, _), its file being <name>.bn")
        else:
            h.module = name
    value, line, col = get("mesh")
    if value is not None:
        if value.strip('"') in MESHES:
            h.mesh = value.strip('"')
        else:
            error(line, col, f"@mesh '{value}': one of {', '.join(MESHES)}")

    file = file if file is not None else parse(source, filename)
    h.examples, h.modifiers = shapes(file)
    by_key = {key(g.name): g.name for g in file.graphs}

    def pick(kind, candidates, shape):
        value, line, col = get(kind)
        if value is None:
            return candidates[-1] if candidates else None  # the last graph is the file's main one
        name = _unquote(value)
        if name is None:
            error(line, col, f"@{kind} {value}: a graph's name, quoted, or a bare identifier")
            return None
        graph = name if name in by_key.values() else by_key.get(key(name))
        if graph is None:
            error(line, col, f"@{kind} '{name}': no graph of that name in this file")
            return None
        if graph not in candidates:
            error(line, col, f"@{kind} '{name}': {shape}")
            return None
        return graph

    example = pick("example", h.examples, "not a geometry graph nobody calls that makes its own geometry "
                                          "(a Geometry output, no Geometry input)")
    modifier = pick("modifier", h.modifiers, "not a modifier: a geometry graph nobody calls whose first "
                                             "input and output are Geometry")

    value, line, col = get("offer")
    if value is not None:
        h.offer_written = True
        offered, at = [], col
        for part in value.split(","):
            word = part.strip()
            where = at + len(part) - len(part.lstrip())
            at += len(part) + 1
            if word not in OFFERS:
                error(line, where, f"@offer '{word}': one of {', '.join(OFFERS)}")
            elif word not in offered:
                offered.append(word)
        why = {"library": (h.module, "there is no @module to install the file as"),
               "example": (example, "no geometry graph nobody calls makes its own geometry"),
               "modifier": (modifier, "no geometry graph nobody calls has Geometry as first input and output")}
        source_of = {"library": "module", "example": "example", "modifier": "modifier"}
        for word in offered:
            # A directive already in error says why: once is enough
            told = any(d.line == h.lines.get(source_of.get(word)) for d in diags)
            if word in why and why[word][0] is None and not told:
                error(line, col, f"@offer {word}: {why[word][1]}")
        h.offer = [o for o in OFFERS if o in offered]
    else:
        h.offer = [o for o, ok in (("library", h.module), ("groups", True), ("example", example),
                                   ("modifier", modifier)) if ok]
    h.example = example if "example" in h.offer else None
    h.modifier = modifier if "modifier" in h.offer else None
    if diags:
        raise BnError(diags)
    return h
