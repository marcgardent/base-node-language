"""Targets: what a destination accepts (spec/targets.md).

A target is one JSON file: the kinds of tree, types, zones and nodes a text may use there, and the
translators that carry a text of another target to it. No target is defined from another.

    check_target(file, "gltf")   -> the Issues of the text outside gltf, [] when it fits
    infer(file)                  -> which targets accept it, natively or through a translator
    translate(file, "blender-compositor", "blade") -> the text renamed for blade

A graph a text calls brings its issues: those of the text, of the stdlib modules it `use`s, and
of the bridges of the target (modules shipped with it). A name that is not a target's raises
ValueError.

`python -m base_node.targets` rewrites the node lists of the blender-* targets from the nodes
Blender reports (targets/backends/blender-<x.y>.json). The `_targets` next to this module is a link
to targets/ in git, and a folder of files in the wheel and the Blender extension.
"""

from __future__ import annotations

import copy
import json
import re
import sys
from dataclasses import dataclass, field, fields, is_dataclass
from pathlib import Path

from . import ast
from .schema import IMPLICIT as SCHEMA_IMPLICIT
from .schema import CURVE, CURVES, RAMP, is_material, key
from .sugar import BINOPS, BOOL_FUNCS, EPSILON, MATH_COMPARE, MATH_FUNCS, VECTOR_FUNCS

HERE = Path(__file__).resolve().parent
# The targets shipped with this package, then the repository's when run from a checkout
DIRS = (HERE / "_targets", HERE.parents[1] / "targets")

ZONE_WORDS = {ast.Repeat: "repeat", ast.Simulate: "simulate", ast.Foreach: "foreach", ast.Closure: "closure"}
ARITHMETIC = {"+", "-", "*", "/"}
PRODUCTS = {"⋅", "×", "dot", "cross", "·"}
COMPARISONS = {"<", "<=", ">", ">=", "==", "!="}
LOGIC = {"and", "or", "xor"}
# Blender targets built from the nodes Blender reports: name -> kind of tree. A graph of any kind
# builds in any tree whose nodes it uses (a compositor graph of math in a geometry tree). blender-gp
# is Geometry Nodes on a Grease Pencil object: Blender accepts every geometry node there
BLENDER = {"blender-geometry": "geometry", "blender-gp": "geometry", "blender-shader": "shader",
           "blender-compositor": "compositor"}
DESCRIPTIONS = {"blender-gp": "Every Geometry Nodes node of Blender {blender}, on a Grease Pencil object"}
BLENDER_KINDS = ["geometry", "shader", "compositor"]
# Blender's zones by kind of tree: repeat and closure are shader and geometry nodes, the others geometry's
ZONES = {"geometry": ["repeat", "foreach", "simulate", "closure"], "shader": ["repeat", "closure"],
         "compositor": ["repeat"]}
# An implicit input (`p: Vector = Position()`) is a setting of the group's interface, not a node
IMPLICIT = sorted(SCHEMA_IMPLICIT)
# A ramp and curves are the value of a node's property (`color_ramp: Ramp(…)`), not nodes
DATA_CALLS = {RAMP, CURVE, CURVES}


@dataclass(frozen=True)
class Issue:
    """Something a text uses outside a target, where it is."""
    graph: str
    what: str  # kind, type, zone, implicit, node, link, graph
    name: str
    line: int
    col: int
    target: str

    def __str__(self):
        return f"Graph '{self.graph}': {self.what} '{self.name}' outside target '{self.target}' (line {self.line})"


@dataclass
class Target:
    name: str
    description: str = ""
    kinds: list = field(default_factory=list)
    types: list = field(default_factory=list)
    zones: list = field(default_factory=list)
    implicit: list = field(default_factory=list)
    nodes: list = field(default_factory=list)
    translators: dict = field(default_factory=dict)
    bridges: list = field(default_factory=list)
    # The inputs of the nodes its rules name, in order: a positional argument finds its input here
    inputs: dict = field(default_factory=dict)
    # "Node.input" (or "Node.*", its other inputs) -> the feeds it accepts (spec/targets.md, Rules)
    rules: dict = field(default_factory=dict)
    # The outputs of the nodes its rules name, in order: a call taken whole is its first
    outputs: dict = field(default_factory=dict)
    # The settings its rules name, with their defaults: a call that does not write one has its default
    settings: dict = field(default_factory=dict)
    # "Node.socket" of the colors and vectors: a multiply there is a Mix, a `*` with one a Vector Math
    vectors: list = field(default_factory=list)
    # Expressions the rules name as feeds, their placeholders the pattern's `inputs`
    patterns: dict = field(default_factory=dict)
    # The nodes the exporter computes when their inputs are values: a call of one on values is a value
    folded: list = field(default_factory=list)
    # Node groups the destination reads as nodes: the start of the group's name -> the node of the rules
    groups: dict = field(default_factory=dict)
    # The nodes the destination reads one of: the first that reaches the material
    once: list = field(default_factory=list)
    # The file it was read from: its bridges are paths relative to it. Not a field of the JSON
    path: Path | None = field(default=None, repr=False, compare=False)


def _bare(name):
    """Whether `name` names a target rather than a path: it comes from texts and target files."""
    return isinstance(name, str) and re.fullmatch(r"[a-z0-9][a-z0-9_-]*", name) is not None


def target_names():
    """Every target found, sorted."""
    for d in DIRS:
        if d.is_dir():
            names = sorted(p.stem for p in d.glob("*.json"))
            if names:
                return names
    return []


def load_target(name):
    """The Target `name`, or the one in the file `name` points at (a path the caller chose)."""
    if isinstance(name, Target):
        return name
    path = None
    if _bare(name):
        path = next((d / f"{name}.json" for d in DIRS if (d / f"{name}.json").is_file()), None)
    elif Path(name).is_file():
        path = Path(name)
    if path is None:
        raise ValueError(f"unknown target '{name}'; targets: {', '.join(target_names())}")
    data = json.loads(path.read_text(encoding="utf-8"))
    return Target(**{f.name: data[f.name] for f in fields(Target) if f.name in data and f.name != "path"},
                  path=path)


# ---- What a graph uses ----

@dataclass(frozen=True)
class Use:
    what: str
    names: tuple  # one of them is enough: `+` is Math or Vector Math
    line: int
    col: int

    @property
    def name(self):
        return " or ".join(self.names)


def _walk(o, out):
    if isinstance(o, list):
        for x in o:
            _walk(x, out)
        return
    if not is_dataclass(o):
        return
    line, col = getattr(o, "line", 0), getattr(o, "col", 0)
    if isinstance(o, ast.Call):
        out.append(("call", o.name, line, col))
    elif isinstance(o, ast.BinOp):
        out.append(("op", o.op, line, col))
    elif isinstance(o, ast.Neg):
        out.append(("op", "-", line, col))
    elif isinstance(o, ast.Not):
        out.append(("op", "not", line, col))
    elif isinstance(o, ast.Cond):
        out.append(("op", "?", line, col))
    elif type(o) in ZONE_WORDS:
        out.append(("zone", ZONE_WORDS[type(o)], line, col))
    for f in fields(o):
        _walk(getattr(o, f.name), out)


def _assigns(o):
    if isinstance(o, list):
        return [a for x in o for a in _assigns(x)]
    if not is_dataclass(o):
        return []
    here = [o] if isinstance(o, ast.Assign) else []
    return here + [a for f in fields(o) for a in _assigns(getattr(o, f.name))]


def _local_names(file, find=None):
    """Names a call may give that are not nodes: the graphs of the text and what its uses import.

    A use of every graph of a module `find` finds imports its graphs; of one it does not find, any
    name (`every`)."""
    names, modules = set(), set()
    for g in file.graphs:
        names.add(g.name)
        names.add(key(g.name))
    every = False
    for u in file.uses:
        modules.add(u.alias or u.name)
        modules.add(u.name)
        if u.names is not None:
            names.update(u.names)
            continue
        m = find(u.name) if find is not None else None
        if m is None:
            every = True
        else:
            names.update(key(g.name) for g in m.graphs)
    return names, modules, every


def uses(graph, local=frozenset(), modules=frozenset(), every=False):
    """What `graph` needs of a target: its kind, types, zones and nodes, as Uses."""
    out = [Use("kind", (graph.kind,), graph.line, graph.col)]
    for p in list(ast.flatten(graph.params)) + list(ast.flatten(graph.outputs)):
        out.append(Use("type", (p.type,), p.line, p.col))
    for p in ast.flatten(graph.params):
        d = p.default
        if isinstance(d, ast.Call) and not d.args and d.name in IMPLICIT:
            out.append(Use("implicit", (d.name,), p.line, p.col))
    found = []
    _walk(graph.body, found)
    # A call on a name the graph binds evaluates the closure it holds
    bound = {a.name for a in _assigns(graph.body)}
    for what, name, line, col in found:
        if what == "zone":
            out.append(Use("zone", (name,), line, col))
        elif what == "op":
            if name in ARITHMETIC:
                out.append(Use("node", ("Math", "VectorMath"), line, col))
            elif name in PRODUCTS:
                out.append(Use("node", ("VectorMath",), line, col))
            elif name in COMPARISONS:
                # Compare where the tree has one, else Math (a shader tree)
                out.append(Use("node", ("Compare", "Math"), line, col))
            elif name in LOGIC or name == "not":
                out.append(Use("node", ("BooleanMath",), line, col))
            elif name == "?":
                # A Switch where it chooses for each element, else a Mix by the condition (typecheck.ternary)
                out.append(Use("node", ("Switch",) if graph.kind == "geometry" else ("Mix", "MixShader"), line, col))
        elif "::" in name:
            if name.split("::", 1)[0] not in modules:
                out.append(Use("node", (name,), line, col))
        elif name in bound and name not in local:
            out.append(Use("node", ("EvaluateClosure",), line, col))
        elif name in local or every or name in DATA_CALLS:
            continue
        elif name in BOOL_FUNCS:
            out.append(Use("node", ("BooleanMath",), line, col))
        elif name in MATH_FUNCS or name in VECTOR_FUNCS:
            out.append(Use("node", tuple(n for n, d in (("Math", MATH_FUNCS), ("VectorMath", VECTOR_FUNCS))
                                         if name in d), line, col))
        else:
            out.append(Use("node", (name,), line, col))
    return out


def _graphs(file):
    if isinstance(file, ast.File):
        return file, file.graphs
    graphs = list(file) if isinstance(file, (list, tuple)) else [file]
    return ast.File(graphs=graphs), graphs


def _allowed(target, what):
    return {"kind": target.kinds, "type": target.types, "zone": target.zones, "implicit": target.implicit,
            "node": target.nodes}[what]


# Where a `use` without a source finds its module: the stdlib of the checkout, then the add-on's
STDLIB_DIRS = (HERE.parents[1] / "stdlib", HERE.parent / "stdlib")
_modules = {}


def _module(name):
    """The parsed stdlib module `name`, or None when it is not found."""
    if name not in _modules:
        from .parser import parse

        path = next((d / f"{name}.bn" for d in STDLIB_DIRS if (d / f"{name}.bn").is_file()), None)
        _modules[name] = parse(path.read_text(encoding="utf-8"), str(path)) if path else None
    return _modules[name]


_bridge_files = {}


def _bridges(target):
    """{module name: parsed module} of the bridges of `target`: its `bridges`, paths relative to its file."""
    target = load_target(target)
    out = {}
    if target.path is None:
        return out
    for rel in target.bridges:
        path = (target.path.parent / rel).resolve()
        if path not in _bridge_files:
            from .parser import parse

            _bridge_files[path] = parse(path.read_text(encoding="utf-8"), str(path)) if path.is_file() else None
        if _bridge_files[path] is not None:
            out[Path(rel).stem] = _bridge_files[path]
    return out


def _finder(target):
    """Where a check against `target` finds the module of a `use`: the target's bridges, then the stdlib."""
    bridges = _bridges(target)
    return lambda name: bridges[name] if name in bridges else _module(name)


def _callees(graph, file, find=_module):
    """(graph, its file) for each graph of the text or of a module it uses that `graph` calls."""
    called = set()
    _calls(graph.body, called)
    for g in file.graphs:
        if g is not graph and (g.name in called or key(g.name) in called):
            yield g, file
    for u in file.uses:
        m = find(u.name)
        if m is None:
            continue
        prefix = u.alias or u.name
        for g in m.graphs:
            k = key(g.name)
            names = u.names if u.names is not None else [k]
            if (k in names and k in called) or f"{prefix}::{k}" in called:
                yield g, m


def graph_issues(graph, target, file=None, _seen=None):
    """The Issues of one graph outside `target`, with those of the graphs it calls.

    The graphs it calls are those of the text, and of the modules it uses: the bridges of `target`
    and the stdlib."""
    target = load_target(target)
    find = _finder(target)
    local, modules, every = _local_names(file, find) if file is not None else (set(), set(), False)
    allowed = {w: set(_allowed(target, w)) for w in ("kind", "type", "zone", "implicit", "node")}
    out = []
    for u in uses(graph, local, modules, every):
        if not any(n in allowed[u.what] for n in u.names):
            out.append(Issue(graph.name, u.what, u.name, u.line, u.col, target.name))
    out += link_issues(graph, target, local, file)
    if file is not None:
        seen = (_seen or set()) | {id(graph)}
        for g, f in _callees(graph, file, find):
            if id(g) in seen:
                continue
            # Its links are read where it is called, through the values the call gives
            inner = [i for i in graph_issues(g, target, f, seen) if i.what != "link"]
            if inner:
                first = inner[0]
                out.append(Issue(graph.name, "graph", f"{key(g.name)} ({first.what} {first.name})",
                                 first.line, first.col, target.name))
    return out


def _calls(o, out):
    found = []
    _walk(o, found)
    out.update(name for what, name, _, _ in found if what == "call")


def check_target(file, target):
    """The Issues of the text (a File, or graphs) outside `target`: [] when every graph fits it."""
    file, graphs = _graphs(file)
    target = load_target(target)
    return [i for g in graphs for i in graph_issues(g, target, file)]


def check_targets(file, targets):
    """The Issues of the graphs that fit none of `targets` (a text may promise several, one per graph)."""
    file, graphs = _graphs(file)
    targets = [load_target(t) for t in targets]
    out = []
    for g in graphs:
        per = [graph_issues(g, t, file) for t in targets]
        if per and all(per):
            out += min(per, key=len)
    return out


# ---- Rules: what may feed what ----

TIMES = "×"
DEFAULT = object()  # an input the call does not give: its default value, a constant
ABSENT = object()  # an input of another call the graph does not make: nothing feeds it, not even a value
# The inputs text names by a key of their own (schema.INPUT_KEYS), by node name: Blender's
# identifier, which a call may still write, is read as that key
IDENTIFIERS = {
    "MixShader": {"Shader": "a", "Shader_001": "b"},
    "AddShader": {"Shader": "a", "Shader_001": "b"},
}

# The inputs of a Material Output, which a material's return feeds
MATERIAL_SOCKETS = ("surface", "volume", "displacement", "thickness")


def _pattern(text):
    """A feed of a rule as (core, the factors around it): `ImageTexture × constant` -> ("ImageTexture", ["constant"])."""
    terms = [t.strip() for t in text.split(TIMES)]
    return terms[0], terms[1:]


_written = {}


def _expression(text):
    """The expression a pattern of a target writes, parsed."""
    if text not in _written:
        from .parser import parse

        f = parse(f"shader graph pattern() -> Float {{\n  return {text}\n}}\n", "<pattern>")
        _written[text] = f.graphs[0].body[-1].value
    return _written[text]


def _formula(op):
    """The node a formula writes, by its operator."""
    if op in ARITHMETIC:
        return "Math"
    if op in PRODUCTS:
        return "VectorMath"
    if op in COMPARISONS:
        return "Compare"
    return "BooleanMath"


def _math_comparison(e):
    """A comparison as the Math nodes it writes in a tree with no Compare node (sugar.MATH_COMPARE):
    `a >= b` is `1.0 - Math(a, b, operation: LESS_THAN)`."""
    operation, negated = MATH_COMPARE[e.op]
    args = [ast.Arg(None, e.left, e.line, e.col), ast.Arg(None, e.right, e.line, e.col)]
    if operation == "COMPARE":
        args.append(ast.Arg(None, ast.Number(EPSILON, False, e.line, e.col), e.line, e.col))
    args.append(ast.Arg("operation", ast.Ref(operation, e.line, e.col), e.line, e.col))
    call = ast.Call("Math", args, e.line, e.col)
    if negated:
        return ast.BinOp("-", ast.Number(1.0, False, e.line, e.col), call, e.line, e.col)
    return call


def _literal(t):
    """Whether a feed is a number, `true` or `false`: that value, or an input left to its default."""
    if t in ("true", "false"):
        return True
    try:
        float(t)
    except ValueError:
        return False
    return True


def _number(e):
    """The value of a number literal, negated or not, else None."""
    if isinstance(e, ast.Number):
        return e.value
    if isinstance(e, ast.Neg) and isinstance(e.value, ast.Number):
        return -e.value.value
    return None


def _calls_in(o, out):
    """Every call of `o`, in the order of the text, as (call, the value piped into it or None)."""
    if isinstance(o, list):
        for x in o:
            _calls_in(x, out)
        return
    if not is_dataclass(o):
        return
    if isinstance(o, ast.Pipe):
        _calls_in(o.left, out)
        call = o.call.target if isinstance(o.call, ast.Member) else o.call
        if isinstance(call, ast.Call):
            out.append((call, o.left))
            _calls_in(call.args, out)
        else:
            _calls_in(o.call, out)
        return
    if isinstance(o, ast.Call):
        out.append((o, None))
    for f in fields(o):
        _calls_in(getattr(o, f.name), out)


class _Values:
    """The values of several inputs of one call, which a pattern written as a tuple takes together."""

    def __init__(self, items):
        self.items = items


class _State:
    """What a match found: the values its placeholders hold, and the calls its patterns write."""

    def __init__(self, other=None):
        self.held = dict(other.held) if other else {}
        self.eaten = set(other.eaten) if other else set()

    def take(self, other):
        self.held, self.eaten = other.held, other.eaten


class _Links:
    """What feeds the inputs of one graph's nodes, read against the rules of a target."""

    def __init__(self, graph, target, local):
        self.target, self.local, self.kind = target, local, graph.kind
        # A name the graph binds holds an expression, or the result of a zone
        self.values = {a.name: a.value for a in _assigns(graph.body)}
        self.params = {}
        for p in ast.flatten(graph.params):
            self.params[p.name] = self.params[key(p.name)] = p.type
        self.vectors = {v.lower() for v in target.vectors}
        self.compared = {}  # id of a comparison -> (it, the Math nodes it writes where there is no Compare)

    def follow(self, e):
        """`e`, through the names it goes by. A comparison, in a target with no Compare node, is the
        Math nodes it writes there."""
        for _ in range(64):
            if not (isinstance(e, ast.Ref) and e.name in self.values):
                break
            e = self.values[e.name]
        if isinstance(e, ast.BinOp) and e.op in COMPARISONS and "Compare" not in self.target.nodes:
            if id(e) not in self.compared:
                self.compared[id(e)] = (e, _math_comparison(e))
            e = self.compared[id(e)][1]
        return e

    def constant(self, e):
        """Whether `e` is a value rather than a link: a literal, a parameter, an input left to its default."""
        if e is DEFAULT:
            return True
        if e is ABSENT or isinstance(e, _Values):
            return False
        e = self.follow(e)
        if isinstance(e, (ast.Number, ast.Bool, ast.String)):
            return True
        if isinstance(e, ast.Ref):  # a parameter, or a setting's value such as MULTIPLY
            return e.name not in self.values
        if isinstance(e, ast.Tuple):
            return all(self.constant(i) for i in e.items)
        if isinstance(e, ast.Neg):
            return self.constant(e.value)
        # The exporter computes a node it folds whose inputs are values
        n = self.node(e)
        return n is not None and n[0] in self.target.folded and all(self.constant(v) for _, v in n[2])

    def name(self, call):
        n = call.name
        if n in self.local or "::" in n:
            return n
        if n in BOOL_FUNCS:
            return "BooleanMath"
        if n in MATH_FUNCS:
            return "Math"
        if n in VECTOR_FUNCS:
            return "VectorMath"
        return n

    def node(self, e):
        """(node, the output taken or None, [(input name or None, value)]) of `e`, None when no node makes it."""
        if e is DEFAULT or e is ABSENT or isinstance(e, _Values):
            return None
        e = self.follow(e)
        socket = None
        if isinstance(e, ast.Member):
            socket, e = e.socket, self.follow(e.target)
        if isinstance(e, ast.Pipe):
            call = e.call
            if isinstance(call, ast.Member):
                socket, call = call.socket, call.target
            if not isinstance(call, ast.Call):
                return None
            return self.name(call), socket, [(None, e.left)] + [(a.name, a.value) for a in call.args]
        if isinstance(e, ast.Call):
            return self.name(e), socket, [(a.name, a.value) for a in e.args]
        if isinstance(e, ast.BinOp):
            node = _formula(e.op)
            if node == "Math" and (self.vector(e.left) or self.vector(e.right)):
                node = "VectorMath"
            return node, socket, [(None, e.left), (None, e.right)]
        if isinstance(e, ast.Neg):
            return "VectorMath" if self.vector(e.value) else "Math", socket, [(None, e.value)]
        if isinstance(e, ast.Not):
            return "BooleanMath", socket, [(None, e.value)]
        if isinstance(e, ast.Cond):
            # The node of a ternary (typecheck.ternary); a Mix Shader's branches are not told from a Mix's here
            if self.kind == "geometry":
                return "Switch", socket, [("switch", e.cond), ("false_", e.orelse), ("true_", e.then)]
            return "Mix", socket, [("factor", e.cond), ("a", e.orelse), ("b", e.then)]
        return None

    def given(self, node, args):
        """[(input, value)] of a call: a positional argument takes the input of its place in `inputs`."""
        order = self.target.inputs.get(node, [])
        out = []
        for i, (n, v) in enumerate(args):
            if n is not None:
                out.append((IDENTIFIERS.get(node, {}).get(n, n), v))
            elif i < len(order):
                out.append((order[i], v))
        return out

    def lowered(self, node, args):
        return {k.lower(): v for k, v in self.given(node, args)}

    def word(self, v):
        """The value of a setting as written (`MULTIPLY`, `"UV"`), None when it is not one."""
        v = self.follow(v)
        if isinstance(v, ast.Ref):
            return v.name
        if isinstance(v, ast.String):
            return v.value
        if isinstance(v, (ast.Number, ast.Bool)):
            return str(v.value).lower()
        return None

    def setting(self, node, given, name):
        """The value of setting `name` of a call: given, written by its formula, or its default."""
        if name in given:
            return self.word(given[name])
        return self.target.settings.get(node, {}).get(name)

    def operation(self, e, node, given):
        """The operation of a Math or Vector Math: its formula's (`*`, `round`), else its setting."""
        e = self.follow(e)
        if isinstance(e, ast.Member):
            e = self.follow(e.target)
        if isinstance(e, ast.BinOp) and e.op in BINOPS:
            return BINOPS[e.op]
        if isinstance(e, ast.Call) and node == "Math" and e.name in MATH_FUNCS:
            return MATH_FUNCS[e.name]
        if isinstance(e, ast.Call) and node == "VectorMath" and e.name in VECTOR_FUNCS:
            return VECTOR_FUNCS[e.name]
        return self.setting(node, given, "operation")

    def one(self, v):
        if v is None:
            return True
        v = self.follow(v)
        return isinstance(v, ast.Number) and v.value == 1

    def vector(self, e):
        """Whether `e` holds a color or a vector, which a `*` takes to a Vector Math."""
        if e is DEFAULT or isinstance(e, _Values):
            return False
        f = self.follow(e)
        if isinstance(f, ast.Tuple):
            return True
        if isinstance(f, ast.Ref):
            return self.params.get(f.name) in ("Color", "Vector")
        if isinstance(f, ast.BinOp):
            return f.op not in ("⋅", "·", "dot") and (self.vector(f.left) or self.vector(f.right))
        if isinstance(f, ast.Neg):
            return self.vector(f.value)
        n = self.node(e)
        if n is None:
            return False
        node, socket, _ = n
        return f"{node}.{socket or self.first(node)}".lower() in self.vectors

    def first(self, node):
        """The output a call taken whole gives: its first."""
        outs = self.target.outputs.get(node)
        return outs[0] if outs else ""

    def color(self, node, inp):
        """Whether input `inp` of `node` (or placeholder of a pattern) is a color or a vector."""
        return f"{node}.{inp}".lower() in self.vectors

    def multiply(self, e, color):
        """The two values `e` multiplies as the exporter reads it on an input of that type, None when it is not.

        On a color input the exporter reads a Mix whose data_type is RGBA (written, or taken from a
        tuple of 4), blend_type MULTIPLY and factor 1; on a number input a Math whose operation is
        MULTIPLY: the `*` formula of two numbers, or the node."""
        if e is DEFAULT or isinstance(e, _Values):
            return None
        f = self.follow(e)
        if isinstance(f, ast.BinOp):
            if f.op != "*" or color or self.vector(f.left) or self.vector(f.right):
                return None
            return f.left, f.right
        n = self.node(e)
        if n is None:
            return None
        node, _, args = n
        given = self.lowered(node, args)
        if not color and node == "Math" and self.operation(e, node, given) == "MULTIPLY":
            a, b = "value", "value_001"
        elif (color and node == "Mix" and self.setting(node, given, "blend_type") == "MULTIPLY"
              and self.one(given.get("factor")) and self.rgba(node, given)):
            a, b = "a", "b"
        else:
            return None
        return given.get(a, DEFAULT), given.get(b, DEFAULT)

    def rgba(self, node, given):
        """Whether a Mix mixes colors: its data_type, or a tuple of 4 among its inputs."""
        if "data_type" in given:
            return self.setting(node, given, "data_type") == "RGBA"
        return any(isinstance(self.follow(v), ast.Tuple) and len(self.follow(v).items) == 4
                   for k, v in given.items() if k in ("factor", "a", "b"))

    # -- Matching a feed

    def accepts(self, e, feeds, color, st):
        """Whether one of `feeds` takes `e`; `st` keeps what the one that does found."""
        for p in feeds:
            trial = _State(st)
            if self.match(e, *_pattern(p), color, trial):
                st.take(trial)
                return True
        return False

    def match(self, e, core, around, color, st):
        """Whether `e` is `core` multiplied by each of `around`, peeled one at a time from the outside."""
        if not around:
            return self.term(e, core, color, st)
        m = self.multiply(e, color)
        if m is None:
            return False
        x, y = m
        for i, t in enumerate(around):
            rest = around[:i] + around[i + 1:]
            if (self.term(x, t, color, st) and self.match(y, core, rest, color, st)) or \
                    (self.term(y, t, color, st) and self.match(x, core, rest, color, st)):
                return True
        return False

    def term(self, e, t, color, st):
        """Whether `e` is `constant`, `any`, a tuple, a pattern, `Node` (any of its outputs) or `Node.output`."""
        if t == "constant":
            return self.constant(e)
        if t == "any":
            self.eat(e, st)
            return True
        if t.startswith("("):
            return self.tuple_of(e, [i.strip() for i in t.strip("()").split(",")])
        if t.startswith("≠"):
            # A value other than this number
            return e is not DEFAULT and self.constant(e) and not self.literal(e, t[1:].strip())
        if t == "named":
            # A value of its own name: a named constant is a Value node
            return isinstance(e, ast.Ref) and e.name in self.values and _number(self.follow(e)) is not None
        if _literal(t):
            return e is DEFAULT or self.literal(e, t)
        if t in self.target.patterns:
            return self.pattern(e, t, st)
        name, _, out = t.partition(".")
        n = self.node(e)
        if n is None or n[0] != name:
            return False
        return not out or (n[1] or self.first(name)).lower() == out.lower()

    def literal(self, e, t):
        """Whether `e` is the number (or `true`, `false`) written `t`."""
        f = self.follow(e) if e is not DEFAULT and e is not ABSENT else None
        if t in ("true", "false"):
            return isinstance(f, ast.Bool) and f.value == (t == "true")
        n = _number(f) if f is not None else None
        return n is not None and abs(n - float(t)) <= 1e-4

    def tuple_of(self, e, items):
        """Whether `e` is a tuple whose items are these numbers or constants; an input left to its default is."""
        if e is DEFAULT:
            return True
        f = self.follow(e)
        if not isinstance(f, ast.Tuple) or len(f.items) != len(items):
            return False
        for v, want in zip(f.items, items):
            if want == "constant":
                if not self.constant(v):
                    return False
            elif _number(self.follow(v)) is None or abs(_number(self.follow(v)) - float(want)) > 1e-4:
                return False
        return True

    def pattern(self, e, name, st):
        for text in self.target.patterns[name]:
            trial = _State(st)
            if self.shape(e, _expression(text), name, trial):
                st.take(trial)
                return True
        return False

    def shape(self, e, p, name, st):
        """Whether `e` has the shape of `p`, an expression of pattern `name` whose placeholders are its inputs.

        A placeholder takes any value its rule (`Pattern.placeholder`) accepts, the same wherever it
        appears; a call of the pattern is a call of that node, its inputs and settings as written."""
        holes = self.target.inputs.get(name, [])
        if isinstance(p, ast.Ref) and p.name in holes:
            if p.name in st.held:
                return self.same(e, st.held[p.name])
            st.held[p.name] = e
            feeds = self.target.rules.get(f"{name}.{p.name}")
            return feeds is None or self.accepts(e, feeds, self.color(name, p.name), st)
        if isinstance(e, _Values):
            return isinstance(p, ast.Tuple) and len(p.items) == len(e.items) and \
                all(self.shape(v, q, name, st) for v, q in zip(e.items, p.items))
        if e is DEFAULT:
            return False
        f = self.follow(e)
        if _number(p) is not None:
            return _number(f) is not None and abs(_number(f) - _number(p)) <= 1e-4
        if isinstance(p, ast.Ref):
            return self.word(f) is not None and self.word(f).lower() == p.name.lower()
        if isinstance(p, ast.Tuple):
            return isinstance(f, ast.Tuple) and len(f.items) == len(p.items) and \
                all(self.shape(v, q, name, st) for v, q in zip(f.items, p.items))
        if isinstance(p, ast.Member):
            return isinstance(f, ast.Member) and f.socket.lower() == p.socket.lower() and \
                self.shape(f.target, p.target, name, st)
        n = self.node(f)
        # The node a pattern writes, read without the names of the text: a formula of it is a Math
        if isinstance(p, ast.Call):
            pn = (self.name(p), [(a.name, a.value) for a in p.args])
        elif isinstance(p, ast.BinOp):
            pn = (_formula(p.op), [(None, p.left), (None, p.right)])
        else:
            return False
        if n is None or n[1] is not None or n[0] != pn[0]:
            return False
        node = n[0]
        given, written = self.lowered(node, n[2]), self.lowered(node, pn[1])
        if node in ("Math", "VectorMath") and self.operation(p, node, written) != self.operation(f, node, given):
            return False
        inputs = [i.lower() for i in self.target.inputs.get(node, [])]
        for k, v in written.items():
            if k == "operation":
                continue
            if k not in inputs:
                if (self.setting(node, given, k) or "").lower() != (self.word(v) or "").lower():
                    return False
            elif not self.shape(given.get(k, DEFAULT), v, name, st):
                return False
        call = f.call.target if isinstance(f, ast.Pipe) and isinstance(f.call, ast.Member) else \
            f.call if isinstance(f, ast.Pipe) else f
        st.eaten.add(id(call))
        return True

    def same(self, a, b):
        """Whether two values a placeholder takes are one: the same node, or equal numbers."""
        fa, fb = self.follow(a), self.follow(b)
        if fa is fb:
            return True
        if isinstance(fa, ast.Member) and isinstance(fb, ast.Member):
            return fa.socket == fb.socket and self.same(fa.target, fb.target)
        na, nb = _number(fa) if fa is not DEFAULT else None, _number(fb) if fb is not DEFAULT else None
        return na is not None and na == nb

    def eat(self, e, st):
        """Every call `e` makes: a placeholder the exporter does not read speaks for them."""
        if e is DEFAULT or isinstance(e, _Values):
            return
        found = []
        seen = set()
        todo = [e]
        while todo:
            x = self.follow(todo.pop())
            if id(x) in seen:
                continue
            seen.add(id(x))
            _calls_in(x, found)
            refs = []
            _refs(x, refs)
            todo += refs
        st.eaten.update(id(c) for c, _ in found)

    def reach(self, e):
        """The calls `e` makes, through the names it reads, in the order of their inputs: each once."""
        out, seen = [], set()

        def walk(o):
            if isinstance(o, list):
                for x in o:
                    walk(x)
                return
            if isinstance(o, ast.Ref) and o.name in self.values:
                if o.name not in seen:
                    seen.add(o.name)
                    walk(self.values[o.name])
                return
            if not is_dataclass(o):
                return
            if isinstance(o, ast.Call) and all(c is not o for c in out):
                out.append(o)
            for f in fields(o):
                walk(getattr(o, f.name))

        walk(e)
        return out

    # -- What the issue says

    def describe(self, e):
        """What feeds an input, in short: `constant`, `NoiseTexture`, `Math(ImageTexture, ImageTexture)`."""
        if self.constant(e):
            return "constant"
        n = self.node(e)
        if n is None:
            return self.opaque(e)
        node, _, args = n
        inner = [self.short(v) for _, v in args if not self.constant(v)]
        return f"{node}({', '.join(inner)})" if inner else node

    def short(self, e):
        n = self.node(e)
        return n[0] if n is not None else self.opaque(e)

    def opaque(self, e):
        if isinstance(e, ast.Ref):
            return e.name
        return "tuple" if isinstance(self.follow(e), ast.Tuple) else "value"


def _refs(o, out):
    """The names `o` reads."""
    if isinstance(o, list):
        for x in o:
            _refs(x, out)
        return
    if isinstance(o, ast.Ref):
        out.append(o)
        return
    if is_dataclass(o):
        for f in fields(o):
            _refs(getattr(o, f.name), out)


def _split(rules):
    """The rules of a target by node: {input: (input as written, feeds)}, [(inputs, feeds)] of the rules
    on several inputs together, and the feeds of the rules on a call as a whole."""
    one, many, whole = {}, {}, {}
    for k, feeds in rules.items():
        node, dot, inp = k.partition(".")
        if not dot:
            whole[node] = feeds
        elif "+" in inp:
            many.setdefault(node, []).append(([i.strip().lower() for i in inp.split("+")], feeds))
        else:
            one.setdefault(node, {})[inp.lower()] = (inp, feeds)
    return one, many, whole


def _material_output(graph, file):
    """The Material Output a material's return feeds, as a call; None for a graph that is not a material.

    A `shader(material: true)` graph is a material, and so is a shader graph of the text no other
    calls whose first output is a Shader: its outputs go by name, the first Shader to Surface when
    none is named so."""
    if graph.kind != "shader":
        return None
    outs = ast.flatten(graph.outputs)
    if not is_material(graph.settings):
        if file is None or not outs or outs[0].type != "Shader":
            return None
        called = set()
        for g in file.graphs:
            if g.name != graph.name:
                _calls(g.body, called)
        if graph.name in called or key(graph.name) in called:
            return None
    ret = next((s for s in reversed(graph.body) if isinstance(s, ast.Return)), None)
    if ret is None:
        return None
    if isinstance(ret.value, ast.Record):
        given = [(a.name, a.value) for a in ret.value.fields]
    else:
        given = [(outs[0].name if outs else "surface", ret.value)]
    types = {key(p.name): p.type for p in outs}
    if not any(n.lower() == "surface" for n, _ in given):
        first = next((n for n, _ in given if types.get(n) == "Shader"), None)
        given = [("surface" if n == first else n, v) for n, v in given]
    args = [ast.Arg(n.lower(), v, ret.line, ret.col) for n, v in given if n.lower() in MATERIAL_SOCKETS]
    return ast.Call("MaterialOutput", args, ret.line, ret.col)


def _graphs_of(file, find=_module):
    """name -> (graph, its file) for the graphs a call of `file` may name: its own, and its modules'."""
    found = {}
    for g in file.graphs:
        found[g.name] = found[key(g.name)] = (g, file)
    for u in file.uses:
        m = find(u.name)
        if m is None:
            continue
        prefix = u.alias or u.name
        for g in m.graphs:
            k = key(g.name)
            found[f"{prefix}::{k}"] = (g, m)
            if u.names is None or k in u.names:
                found.setdefault(k, (g, m))
    return found


def _relocate(o, line, col):
    if isinstance(o, list):
        for x in o:
            _relocate(x, line, col)
        return
    if not is_dataclass(o):
        return
    if hasattr(o, "line"):
        o.line, o.col = line, col
    for f in fields(o):
        _relocate(getattr(o, f.name), line, col)


def _group(name, groups):
    """The node of the rules a group of that name is read as, None for another group."""
    return next((node for start, node in groups.items() if name.lower().startswith(start.lower())), None)


def _inline(graph, file, find=_module, target=None):
    """A copy of `graph` where a call to a graph of the text or of a module it uses is that graph's body,
    its parameters the values the call gives, at the line of the call: Blender's exporter reads through
    a group as through the nodes it holds. A group the destination reads as a node (`groups`) is a call
    to that node instead, every input given by its name: the value of the call, or the default. An input
    the destination does not read by that name, to the letter, says so."""
    out = copy.deepcopy(graph)
    hoisted, count, finders = [], [0], {}

    def finder(f):
        if id(f) not in finders:
            finders[id(f)] = _graphs_of(f, find)
        return finders[id(f)]

    def substitute(o, names, values):
        if isinstance(o, list):
            return [substitute(x, names, values) for x in o]
        if isinstance(o, ast.Ref):
            if o.name in names:
                o.name = names[o.name]
            elif o.name in values:
                return copy.deepcopy(values[o.name])
            return o
        if not is_dataclass(o):
            return o
        if isinstance(o, ast.Assign) and o.name in names:
            o.name = names[o.name]
        for f in fields(o):
            setattr(o, f.name, substitute(getattr(o, f.name), names, values))
        return o

    def expand(call, piped, socket, f, depth):
        found = finder(f).get(call.name)
        if found is None or depth > 16:
            return None
        callee, cf = found
        count[0] += 1
        n = count[0]
        positional = ([piped] if piped is not None else []) + [a.value for a in call.args if a.name is None]
        named = {a.name: a.value for a in call.args if a.name is not None}
        node = _group(callee.name, target.groups) if target is not None else None
        read = target.inputs.get(node, []) if node is not None else []
        values, args = {}, []
        for i, p in enumerate(ast.flatten(callee.params)):
            k = key(p.name)
            v = named.get(k, named.get(p.name))
            if v is None and i < len(positional):
                v = positional[i]
            if v is None and node is not None:
                v = copy.deepcopy(p.default) if p.default is not None else ast.Number(0.0, False, call.line, call.col)
            if v is None:
                v = p.default if p.default is not None else ast.Ref(f"{k}@{n}", call.line, call.col)
            values[k] = values[p.name] = v
            args.append(ast.Arg(p.name if p.name in read else f"{p.name} (not read)", v, call.line, call.col))
        if node is not None:
            return ast.Call(node, args, call.line, call.col)
        names = {a.name: f"{a.name}@{n}" for a in _assigns(callee.body)}
        body = copy.deepcopy(callee.body)
        _relocate(body, call.line, call.col)
        body = transform(substitute(body, names, values), cf, depth + 1)
        ret = next((s for s in reversed(body) if isinstance(s, ast.Return)), None)
        hoisted.extend(s for s in body if s is not ret)
        if ret is None:
            return None
        if isinstance(ret.value, ast.Record):
            fields_ = ret.value.fields
            pick = next((a for a in fields_ if socket is not None and a.name.lower() == socket.lower()), None)
            return (pick or fields_[0]).value if fields_ else None
        return ret.value

    def graph_call(call, f):
        return isinstance(call, ast.Call) and call.name in finder(f)

    def transform(o, f, depth):
        if isinstance(o, list):
            return [transform(x, f, depth) for x in o]
        if not is_dataclass(o):
            return o
        if isinstance(o, ast.Member) and graph_call(o.target, f):
            o.target.args = transform(o.target.args, f, depth)
            r = expand(o.target, None, o.socket, f, depth)
            return o if r is None else r
        if isinstance(o, ast.Pipe):
            call, socket = o.call, None
            if isinstance(call, ast.Member):
                call, socket = call.target, call.socket
            if graph_call(call, f):
                left = transform(o.left, f, depth)
                call.args = transform(call.args, f, depth)
                r = expand(call, left, socket, f, depth)
                return o if r is None else r
        if isinstance(o, ast.Call) and graph_call(o, f):
            o.args = transform(o.args, f, depth)
            r = expand(o, None, None, f, depth)
            return o if r is None else r
        for fl in fields(o):
            setattr(o, fl.name, transform(getattr(o, fl.name), f, depth))
        return o

    out.body = transform(out.body, file, 0)
    out.body = hoisted + out.body
    return out


def _whole(call, piped):
    """A call as a value: the call, or the value piped into it."""
    return call if piped is None else ast.Pipe(piped, call, call.line, call.col)


def link_issues(graph, target, local=frozenset(), file=None):
    """The links of `graph` the rules of `target` refuse, as Issues `what="link"` at the line of the call.

    With the file of the graph, a call to a graph of the text or of a module it uses is read through,
    as Blender's exporter reads through a group, and a material's return feeds its Material Output.
    A target without rules refuses none."""
    target = load_target(target)
    if not target.rules:
        return []
    if file is not None:
        graph = _inline(graph, file, _finder(target), target)
    one, many, whole = _split(target.rules)
    links = _Links(graph, target, local)
    found = []
    _calls_in(graph.body, found)
    output = _material_output(graph, file)
    if output is not None:
        found.append((output, None))
    def elsewhere(name):
        """The value of `Node.input`: that input of the first call to `Node`, ABSENT without one."""
        node, _, inp = name.partition(".")
        c = next((c for c, _ in found if c.name.lower() == node), None)
        if c is None:
            return ABSENT
        given = links.lowered(c.name, [(a.name, a.value) for a in c.args])
        return given.get(inp, DEFAULT)

    # A call some rule takes as a whole speaks for the calls its pattern writes
    eaten, fits = set(), {}
    for c, piped in found:
        if c.name in whole and c.name not in local:
            st = _State()
            fits[id(c)] = links.accepts(_whole(c, piped), whole[c.name], False, st)
            if fits[id(c)]:
                eaten |= st.eaten - {id(c)}
    out = []
    for c, piped in found:
        if c.name in local:
            continue
        if id(c) in fits and not fits[id(c)]:
            what = links.describe(_whole(c, piped))
            out.append((id(c), Issue(graph.name, "link", what, c.line, c.col, target.name)))
            continue
        mine = one.get(c.name)
        if mine is None:
            continue
        st = _State()
        args = ([(None, piped)] if piped is not None else []) + [(a.name, a.value) for a in c.args]
        given = links.given(c.name, args)
        settings = {s.lower(): d for s, d in target.settings.get(c.name, {}).items()}
        refused = []
        for inp, v in given:
            name, feeds = mine.get(inp.lower(), mine.get("*", (None, None)))
            if feeds is None:
                continue
            if inp.lower() in settings and name != "*":
                word = links.word(v)
                if word is None or not _takes(feeds, word):
                    refused.append((inp, word or links.describe(v)))
            elif not links.accepts(v, feeds, links.color(c.name, inp), st):
                refused.append((inp if name == "*" else name, links.describe(v)))
        written = {inp.lower() for inp, _ in given}
        for s, default in sorted(settings.items()):
            if s in mine and s not in written and (default is None or not _takes(mine[s][1], default)):
                refused.append((mine[s][0], default or "none"))
        values = {inp.lower(): v for inp, v in given}
        for inputs, feeds in many.get(c.name, []):
            together = [values.get(i, DEFAULT) if "." not in i else elsewhere(i) for i in inputs]
            if any(r.lower() in inputs for r, _ in refused) and links.accepts(_Values(together), feeds, False, st):
                refused = [r for r in refused if r[0].lower() not in inputs]
        eaten |= st.eaten
        for inp, what in refused:
            out.append((id(c), Issue(graph.name, "link", f"{c.name}.{inp} ← {what}", c.line, c.col, target.name)))
    out = [i for k, i in out if k not in eaten]
    # Of a node the destination reads once, it reads the last the material reaches, inputs in order
    if output is not None:
        reached = links.reach(output)
        for node in target.once:
            reach = [c for c in reached if c.name == node and id(c) not in eaten]
            out += [Issue(graph.name, "link", f"{node} (not the one read)", c.line, c.col, target.name)
                    for c in reach[:-1]]
    return out


def _takes(feeds, word):
    """Whether a rule on a setting takes that value: one of its feeds, or `any`."""
    return "any" in feeds or word.lower() in (f.lower() for f in feeds)


# ---- Translators ----

def _translator(target, source):
    return load_target(target).translators.get(source)


def _bridge(target, name):
    """(graph, its module) of the bridge `module::graph` of `target`; None when the target has no such graph."""
    module, _, k = name.partition("::")
    m = _bridges(target).get(module)
    g = next((g for g in m.graphs if key(g.name) == k), None) if m is not None else None
    return (g, m) if g is not None else None


def translation_issues(file, source, target):
    """Why the text, fitting `source`, does not reach `target` through its translator; None without one.

    A node the translator sends to a bridge (`module::graph`) reaches `target` when the target has
    that graph and it fits the target."""
    t = load_target(target)
    tr = t.translators.get(source)
    if tr is None:
        return None
    file, graphs = _graphs(file)
    issues = check_target(file, source)
    if issues:
        return issues
    local, modules, every = _local_names(file, _finder(source))
    kinds, nodes = tr.get("kinds", {}), _rename(tr.get("nodes", {}))
    out = []
    for g in graphs:
        for u in uses(g, local, modules, every):
            if u.what == "kind":
                ok = kinds.get(g.kind, g.kind if g.kind in t.kinds else None) is not None
            elif u.what == "node":
                to = next((nodes[n][0] for n in u.names if n in nodes), None)
                ok = to is not None
                if ok and "::" in to:
                    found = _bridge(t, to)
                    inner = graph_issues(found[0], t, found[1]) if found is not None else None
                    if inner is None:
                        ok = False
                    elif inner:
                        first = inner[0]
                        out.append(Issue(g.name, "graph", f"{to} ({first.what} {first.name})", u.line, u.col,
                                         t.name))
            else:
                ok = any(n in _allowed(t, u.what) for n in u.names)
            if not ok:
                out.append(Issue(g.name, u.what, u.name, u.line, u.col, t.name))
    return out


def _rename(node_map):
    """{source node: (target node, {input: input}, {setting: setting})} from a translator's nodes."""
    out = {}
    for src, dst in node_map.items():
        if isinstance(dst, str):
            out[src] = (dst, {}, {})
        else:
            out[src] = (dst["node"], dst.get("inputs", {}), dst.get("settings", {}))
    return out


def translate(file, source, target):
    """A copy of the text (a File) for `target`: kinds and nodes renamed by its translator from `source`.

    A node sent to a bridge becomes a call of its module (`blender_interop::kuwahara`), and the text
    uses the module, once. Raises ValueError with the issues when the text does not reach `target`
    that way.
    """
    issues = translation_issues(file, source, target)
    if issues is None:
        raise ValueError(f"target '{target}' has no translator from '{source}'")
    if issues:
        raise ValueError("\n".join(map(str, issues)))
    tr = _translator(target, source)
    kinds, nodes = tr.get("kinds", {}), _rename(tr.get("nodes", {}))
    out = copy.deepcopy(file)
    bridged = []

    def visit(o):
        if isinstance(o, list):
            for x in o:
                visit(x)
            return
        if not is_dataclass(o):
            return
        if isinstance(o, ast.Call) and o.name in nodes:
            name, inputs, settings = nodes[o.name]
            o.name = name
            if "::" in name and name.split("::", 1)[0] not in bridged:
                bridged.append(name.split("::", 1)[0])
            for a in o.args:
                if a.name is not None:
                    a.name = inputs.get(a.name, settings.get(a.name, a.name))
        for f in fields(o):
            visit(getattr(o, f.name))

    for g in out.graphs:
        g.kind = kinds.get(g.kind, g.kind)
        visit(g)
    for module in bridged:
        if not any(u.name == module and u.alias in (None, module) for u in out.uses):
            out.uses.append(ast.Use(module, None, None, 0, 0))
    return out


# ---- Inference ----

@dataclass
class Inference:
    fits: dict     # target -> None when it accepts the text as it is, else the target it translates from; sorted
    outside: dict  # target -> its Issues, for the targets that do not accept the text; sorted
    graphs: list   # (graph name, the targets that accept it as it is), in the order of the text

    def lines(self):
        """What an editor shows: `Compatible: …`, `Outside: …`."""
        out = []
        fits = [t for t, v in self.fits.items() if v is None]
        fits += [f"{t} (translated from {v})" for t, v in self.fits.items() if v is not None]
        out.append("Compatible: " + (", ".join(fits) or "none"))
        for t, issues in self.outside.items():
            first = issues[0]
            out.append(f"Outside {t}: {first.what} {first.name} (line {first.line})"
                       + (f" and {len(issues) - 1} more" if len(issues) > 1 else ""))
        return out


def infer(file, targets=None):
    """Which targets accept the text: as it is, or through one of their translators."""
    file, graphs = _graphs(file)
    names = sorted(targets) if targets is not None else target_names()
    fits, outside = {}, {}
    for t in names:
        issues = check_target(file, t)
        if not issues:
            fits[t] = None
        else:
            outside[t] = issues
    for t in list(outside):
        for source in sorted(load_target(t).translators):
            if source in fits and fits[source] is None and translation_issues(file, source, t) == []:
                fits[t] = source
                del outside[t]
                break
    per_graph = [(g.name, [t for t in names if not graph_issues(g, t, file)]) for g in graphs]
    return Inference(dict(sorted(fits.items())), outside, per_graph)


# ---- The blender-* targets, from what Blender reports ----

def catalog(root):
    """The newest targets/backends/blender-<x.y>.json under `root`, its `stdlib` read from the file
    of each module next to it (blender-<x.y>/<module>.json)."""
    files = sorted((root / "targets" / "backends").glob("blender-*.json"),
                   key=lambda p: tuple(int(x) for x in re.findall(r"\d+", p.stem)))
    if not files:
        raise FileNotFoundError(f"no {root}/targets/backends/blender-*.json")
    backend = json.loads(files[-1].read_text(encoding="utf-8"))
    backend["stdlib"] = {p.stem: json.loads(p.read_text(encoding="utf-8"))
                         for p in sorted(files[-1].with_suffix("").glob("*.json"))}
    return backend


def blender_target(name, backend):
    kind, kinds = BLENDER[name], BLENDER_KINDS
    nodes = backend["kinds"][kind]
    types = sorted({s["type"] for n in nodes for s in n["inputs"] + n["outputs"]})
    return {
        "name": name,
        "description": DESCRIPTIONS.get(name, f"Every {kind} node of Blender {{blender}}").format(
            blender=backend["blender"]),
        "kinds": kinds,
        "types": types,
        "zones": ZONES[kind],
        "implicit": IMPLICIT,
        "nodes": sorted(n["name"] for n in nodes),
    }


def dump(data):
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def sync(root):
    """Rewrite the blender-* targets of `root`/targets from its backend. Returns the paths written."""
    written = []
    backend = catalog(root)
    for name in BLENDER:
        p = root / "targets" / f"{name}.json"
        old = json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}
        new = {**blender_target(name, backend), **{k: v for k, v in old.items()
                                                   if k in ("translators", "bridges")}}
        if old != new:
            p.write_text(dump(new), encoding="utf-8")
            written.append(p)
    return written


def main(argv=None):
    root = HERE.parents[1]
    for p in sync(root):
        print(f"wrote {p.relative_to(root)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
