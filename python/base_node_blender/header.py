"""What a .bn file says of itself to Blender: the head the core reads (python/base_node/header.py),
and what the file offers when it is dropped on Blender.

    // @module mesh_maps
    // @offer library, groups

`@target` names targets of targets/ (`blender@5.3 gltf`: a target, a version of it, a variant; an
alias such as `blender@latest` is the command line's, not a text's); `@offer`, `@example`, `@modifier` and `@mesh` tell the add-on
what it may do with the file (see `OFFERS`), and are checked against its graphs.
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields, is_dataclass

from ._core import BnError, CoreHeader, Diagnostic, ast, key, parse, read_head, unquote
from .targets import promise_refusal

# What a dropped file may be used for, in the order a dialog lists them
OFFERS = ("library", "groups", "example", "modifier")
# The mesh `modifier` makes when no object takes the modifier
MESHES = ("cube", "plane", "sphere", "cylinder", "grid")
KNOWN = ("offer", "example", "modifier", "mesh")


@dataclass
class Header(CoreHeader):
    """The directives of a file, checked against its graphs.

    `offer` is what the file offers, as written or inferred; `example` and `modifier` the
    graph each of these uses (None when not offered), `examples` and `modifiers` every graph
    that could be used. `lines` keeps the line of each directive written.
    """
    offer: list = field(default_factory=list)
    offer_written: bool = False
    example: str | None = None
    modifier: str | None = None
    mesh: str = "cube"
    examples: list = field(default_factory=list)
    modifiers: list = field(default_factory=list)


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
    head, get, diags = read_head(source, filename, promise_refusal, KNOWN)
    h = Header(**vars(head))

    def error(line, col, message):
        diags.append(Diagnostic(filename, line, col, message))

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
        name = unquote(value)
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
