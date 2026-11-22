"""AST -> ir.Graph, checked against a Schema.

Every error is collected with its position, so one pass reports them all.
"""

import copy
import dataclasses
import difflib
import itertools
from dataclasses import dataclass, field

from . import ir, sugar, zones
from ._core import BnError, Diagnostic, ast, colors, parse
from .schema import (CLOSURE_INPUT, CLOSURE_OUTPUT, CLOSURE_TO_LIST, COMBINE_BUNDLE, DATABLOCKS, DEPRECATED, EVALUATE_CLOSURE, FIELD_TYPES, IMPLICIT,
                     ITEM_NODES, ITEM_TYPES, NO_DEFAULT, NO_VALUE, RANGED, SEPARATE_BUNDLE, SIGNATURE_NODES, STRICT,
                     TREE_KINDS, TYPES, CURVE, CURVES, HANDLES, MAPPING_OPTIONS, MATERIAL, MATERIAL_OUTPUTS, RAMP,
                     RAMP_OPTIONS, Socket, can_link, is_material, key, loose, snake)

# `Group()`: a Group node that calls no tree (its group is missing from the file)
EMPTY_GROUP = "Group"

GROUP_NODES = {
    "geometry": "GeometryNodeGroup",
    "shader": "ShaderNodeGroup",
    "compositor": "CompositorNodeGroup",
}


@dataclass
class Out:
    """A node's output. `chosen` is None until `.socket` picks one: the first is used."""
    node: str
    outputs: list
    chosen: Socket | None
    label: str

    @property
    def socket(self):
        return self.chosen or (self.outputs[0] if self.outputs else None)


@dataclass
class Lit:
    value: object
    type: str


@dataclass
class Const(Out):
    """A literal bound to a name: `size = 10`. Its own input node, so the tree keeps the name;
    where only a literal fits (a tuple, a node setting, a menu), its value."""
    lit: Lit = None


# The input node a named literal makes, by its type: (text name, Blender property holding the
# value, or None when the node's output holds it)
# Literal type -> (the node it makes, its property that holds the value or None, its bl_idname): a node
# of that name but another type (Color in a shader tree is an RGB node) leaves the literal alone
CONST_NODES = {"Float": ("Value", None, "ShaderNodeValue"), "Int": ("Integer", "integer", "FunctionNodeInputInt"),
               "Bool": ("Boolean", "boolean", "FunctionNodeInputBool"),
               "Vector": ("Vector", "vector", "FunctionNodeInputVector"),
               "Color": ("Color", "value", "FunctionNodeInputColor"),
               "String": ("String", "string", "FunctionNodeInputString")}
# The Color node of a shader or a compositor tree (the RGB) holds its color on its output
RGB_NODES = {b: ("Color", None, b) for b in ("ShaderNodeRGB", "CompositorNodeRGB")}
# The input node of a datablock, by its type: (its text name, its property holding the datablock).
# A datablock bound to a name is that node, written as a call: `o = Object[object: "Thing"]()`
DATABLOCK_NODES = {"Font": ("Font", "font"), "Object": ("Object", "object"),
                   "Collection": ("Collection", "collection"), "Material": ("Material", "material"),
                   "Image": ("Image", "image")}
# Input nodes whose value is an array the schema does not list among their settings, by bl_idname:
# (the property, whether it holds integers). Written as a setting: Rotation[rotation_euler: (0.1, 0.0, 0.0)]()
VALUE_PROPS = {"FunctionNodeInputRotation": ("rotation_euler", False),
               "FunctionNodeInputVector": ("vector", False),
               "FunctionNodeInputIntVector": ("vector", True)}
# Nodes that hold their value on an output, by bl_idname: (the setting the text names it by, the
# output). Written as a setting: Normal[normal: (0.0, 0.0, 1.0)](). A Value and an RGB node are
# named literals instead: `size = 0.5`, `tint = (1.0, 0.5, 0.0, 1.0)`
OUTPUT_PROPS = {"ShaderNodeNormal": ("normal", "Normal"), "CompositorNodeNormal": ("normal", "Normal")}


@dataclass
class Empty:
    """A zone item with no value, written by its type alone: `cache: Bundle`."""
    type: str


@dataclass
class Typed:
    """An item's value given its type: `height: Float = 1`."""
    value: object
    type: str


@dataclass
class Zone:
    """The zone whose body is being checked."""
    word: str        # repeat, simulate, foreach or closure
    out: object      # its output node
    states: list     # of Socket: what its return may give (repeat, simulate)
    skip: object     # the Skip socket of a simulation
    given: set = field(default_factory=set)  # what the return gave
    outputs: list = field(default_factory=list)  # a foreach's output sockets, once returned


@dataclass
class Sym:
    """A name bound to nothing: an enum value, such as POWER or FACE."""
    name: str


def check(file, schema, filename="<text>", load=None, warnings=None):
    """Checked graphs, callees before callers, those of the modules first. Raises BnError.

    `load(name, source)` gives a module's (text, filename) for a `use`, or raises
    LookupError with the reason; without it, a `use` is an error. `warnings` is a list the
    warnings of a valid text are added to (see `deprecated_calls`): they stop nothing.
    """
    modules = Modules(schema, load)
    order = modules.check(file, filename).order
    if warnings is not None:
        warnings.extend(modules.warnings)
    return order


def deprecation(g):
    """What an ast.Graph says of its leaving, `kind(deprecated: "use curl2") graph curl(…)`: None when
    it stays, else what its author wrote of it, "" for `deprecated: true`."""
    for a in g.settings:
        if a.name == DEPRECATED:
            if isinstance(a.value, ast.String):
                return a.value.value
            return "" if isinstance(a.value, ast.Bool) and a.value.value else None
    return None


def _calls(node):
    """Every ast.Call under an AST node."""
    if isinstance(node, (list, tuple)):
        for item in node:
            yield from _calls(item)
    elif dataclasses.is_dataclass(node):
        if isinstance(node, ast.Call):
            yield node
        for f in dataclasses.fields(node):
            value = getattr(node, f.name)
            if isinstance(value, (list, tuple)) or dataclasses.is_dataclass(value):
                yield from _calls(value)


def deprecated_calls(graphs, callable_, filename="<text>"):
    """A warning at each call, in `graphs`, of a graph marked deprecated, with what its author says.

    `callable_` is {the name a call writes: ast.Graph}, the graphs of the text and those its uses
    bring. A graph that is deprecated itself calls the others without a word: it leaves with them.
    """
    marked = {k: deprecation(g) for k, g in callable_.items()}
    marked = {k: m for k, m in marked.items() if m is not None}
    if not marked:
        return []
    out = []
    for g in graphs:
        if deprecation(g) is not None:
            continue
        for c in _calls(g.body):
            if c.name in marked:
                said = f": {marked[c.name]}" if marked[c.name] else ""
                out.append(Diagnostic(filename, c.line, c.col, f"'{c.name}' is deprecated{said}", "warning"))
    return sorted(out, key=lambda d: (d.line, d.col))


def deprecations(file, filename="<text>", find=None):
    """The warnings of a parsed text, for a reader with no schema to check it with: `deprecated_calls`
    of its graphs. `find(name)` gives the parsed module of a `use`, or None: by default the standard
    library's, as a check against a target finds it."""
    if find is None:
        from .targets import _module as find
    callable_ = {}
    for u in file.uses:
        module = find(u.name)
        if module is None:
            continue
        for g in module.graphs:
            k = key(g.name)
            if u.names is None or k in u.names:
                callable_[k] = g
            for prefix in {u.alias or u.name, u.name}:
                callable_[f"{prefix}::{k}"] = g
    callable_.update((key(g.name), g) for g in file.graphs)
    return deprecated_calls(file.graphs, callable_, filename)


@dataclass
class Unit:
    """A checked file: its graphs by key, and every graph it needs, callees first."""
    graphs: dict  # key -> ast.Graph
    order: list   # of ir.Graph, those of its own modules included


def variant_name(name, kind):
    """The node group a module's graph is built into for a tree of another kind: `bias (Compositor)`.
    Blender names node groups once for every kind of tree, so the variant needs a name of its own."""
    return f"{name} ({kind.capitalize()})"


def instance_name(name, types):
    """The node group a template is built into for its types: `attribute_or (Vector)`, `blend (Float, Color)`."""
    return f"{name} ({', '.join(types)})"


def shown(name, types):
    """A template with its types, as a call writes them: `attribute_or<Vector>`; a graph by its name."""
    return f"{name}<{', '.join(types)}>" if types else name


# A type -> the values a node's type setting gives it by, in the order they are tried: a setting names a
# type in its own words, VECTOR for a Switch, FLOAT_VECTOR for a Named Attribute
TYPE_SETTINGS = {"Float": ("FLOAT",), "Int": ("INT", "INT32"), "Bool": ("BOOLEAN",),
                 "Vector": ("VECTOR", "FLOAT_VECTOR"), "Color": ("RGBA", "FLOAT_COLOR"),
                 "Rotation": ("ROTATION", "QUATERNION"), "Matrix": ("MATRIX", "FLOAT4X4"),
                 "String": ("STRING",), "Menu": ("MENU",), "Geometry": ("GEOMETRY",), "Shader": ("SHADER",),
                 "Object": ("OBJECT",), "Collection": ("COLLECTION",), "Material": ("MATERIAL",),
                 "Image": ("IMAGE",), "Texture": ("TEXTURE",), "Font": ("FONT",), "Sound": ("SOUND",),
                 "Scene": ("SCENE",), "Mask": ("MASK",), "Text": ("TEXT",), "Bundle": ("BUNDLE",), "Closure": ("CLOSURE",)}


def infer_type(found):
    """The type a type parameter takes from what a call gives its inputs, `found` being
    [(input key, type or None, linked)]: the linked values decide, else the literals.
    (type, None); (None, None) when nothing gives it; (None, ((key, type), (key, type))) when two disagree.
    Tree → Text infers by it as well, to write a call's types only where they are needed."""
    found = [(k, t, linked) for k, t, linked in found if t is not None]
    deciding = [(k, t) for k, t, linked in found if linked] or [(k, t) for k, t, _l in found]
    if not deciding:
        return None, None
    other = next(((k, t) for k, t in deciding if t != deciding[0][1]), None)
    if other is not None:
        return None, (deciding[0], other)
    return deciding[0][1], None


# A Switch takes its input_type from its False and True values when the text writes none
SWITCH, SWITCH_PROP, SWITCH_VALUES = "GeometryNodeSwitch", "input_type", ("False", "True")


def switch_value_type(found):
    """The type a Switch takes from its values, `found` being [(input, type or None, linked)]:
    the first linked value's, else the first literal's; None when nothing tells it (the node keeps
    the type a new one has). Tree → Text reads by it too, to write input_type only where needed."""
    found = [(t, linked) for _k, t, linked in found if t is not None]
    deciding = [t for t, linked in found if linked] or [t for t, _l in found]
    return deciding[0] if deciding else None


# The data_type of the Mix a ternary is in a shader or a compositor tree, by the type of its branches;
# a whole number and a Bool go in as Float
MIX_TYPES = {"Float": "FLOAT", "Int": "FLOAT", "Bool": "FLOAT", "Vector": "VECTOR", "Color": "RGBA",
             "Rotation": "ROTATION"}


def branches_type(found):
    """The type the branches of a ternary give it, `found` being [(input, type or None, linked,
    how many numbers when a tuple else 0)]: with a tuple, Color when one has 4 numbers, else Vector
    (tuple_type); else the first linked value's, else the first literal's (switch_value_type).
    Tree → Text reads by it too, to tell the nodes that are a ternary."""
    sizes = [n for _k, _t, _linked, n in found if n]
    if sizes:
        return "Color" if 4 in sizes else "Vector"
    return switch_value_type([f[:3] for f in found])


def takes_list(names):
    return ", ".join(names[:-1]) + " and " + names[-1] if len(names) > 1 else "".join(names)


def type_setting(t, items):
    """The value of a node's type setting, among `items`, that gives it the type t; None if none does."""
    return next((v for v in TYPE_SETTINGS.get(t, ()) if v in items), None)


def specialize(g, types):
    """A copy of a template's ast.Graph with its type parameters replaced: `types` is {name: type}."""
    g = copy.deepcopy(g)
    g.type_params = []

    def walk(o):
        if isinstance(o, ast.Param) and o.type in types:
            o.type = types[o.type]
        if isinstance(o, (list, tuple)):
            for item in o:
                walk(item)
        elif dataclasses.is_dataclass(o):
            for f in dataclasses.fields(o):
                walk(getattr(o, f.name))
    walk(g)
    return g


class Modules:
    """Checks a file and the modules it uses, each module once."""

    def __init__(self, schema, load):
        self.schema = schema
        self.load = load
        self.done = {}  # (name, source) -> Unit
        self.units = {}  # id of a Use -> the Unit it loaded
        # id of a module's ast.Graph -> (module ident, what its graphs may call, filename, unsure)
        self.owners = {}
        self.variants = {}  # (module ident, graph key, kind) -> (ir.Graph or None, diagnostics)
        self.variant_graphs = {}  # name of a variant's group -> its ir.Graph
        self.collecting = []  # for each file being checked, the variants its graphs call
        self.warnings = []  # of the text checked, not of its modules: what a valid text should change

    def check(self, file, filename, ident=None, stack=()):
        diags = []
        imported = self.imports(file, filename, stack, diags)
        by_name = {}
        # Graphs are called by their key: "Smooth by Angle" is called as smooth_by_angle(...)
        for g in file.graphs:
            if key(g.name) in by_name:
                diags.append(Diagnostic(filename, g.line, g.col, f"graph '{key(g.name)}' defined twice"))
            elif key(g.name) in imported:
                diags.append(Diagnostic(filename, g.line, g.col, f"'{key(g.name)}' is defined here and imported from "
                                                                 f"{imported[key(g.name)][1].name}"))
            elif key(g.name) in sugar.FUNCS:
                # It would take every call of the function in the file, and of the files that use it
                diags.append(Diagnostic(filename, g.line, g.col, function_name(key(g.name))))
            by_name[key(g.name)] = g
        callable_ = {k: g for k, (g, _u) in imported.items()} | by_name
        order = self.needed(file.uses, imported)
        # A module that failed would make every call to it an unknown node too
        unsure = any(id(u) not in self.units for u in file.uses)
        if ident is not None:
            # A module's graphs may be built again in a tree of another kind, or for a template's types: see variant
            for g in file.graphs:
                self.owners[id(g)] = (ident, callable_, filename, unsure)
        variants = []
        self.collecting.append(variants)
        try:
            # A template is built for the types its calls give: checked here for each of its types
            graphs = [g for g in file.graphs if not g.type_params]
            own = check_graphs(graphs, by_name, callable_, self.schema, filename, diags, unsure, self)
        finally:
            self.collecting.pop()
        for g in file.graphs:
            if g.type_params:
                self.check_template(g, callable_, filename, diags, unsure)
        if diags:
            raise BnError(diags)
        if ident is None:
            self.warnings += deprecated_calls(file.graphs, callable_, filename)
        for g in own:
            g.module = ident
        seen = set()
        return Unit(by_name, [g for g in order + variants + own if not (g.name in seen or seen.add(g.name))])

    def check_template(self, g, callable_, filename, diags, unsure):
        """A template checked once for each of its types: an error of every type is written once,
        one of some types after the template and its types (`attribute_or<Matrix>: …`)."""
        ok = True
        seen = set()
        keys = {p.key for p in g.params} | {o.key for o in g.outputs}
        for t in g.type_params:
            def error(message):
                diags.append(Diagnostic(filename, t.line, t.col, message))
            if t.name in TYPES:
                error(f"'{t.name}' is a type: name a type parameter otherwise, such as T")
                ok = False
            elif t.name in seen:
                error(f"type parameter '{t.name}' defined twice")
                ok = False
            elif t.name in keys:
                error(f"'{t.name}' is a type parameter and an input or output of '{key(g.name)}'")
                ok = False
            seen.add(t.name)
            for x in t.types:
                if x not in TYPES:
                    error(f"unknown type '{x}' in the constraint of {t.name}; expected: {', '.join(TYPES)}")
                    ok = False
        if not ok:
            return
        found = []  # (types, diagnostics) for each combination of types
        for types in itertools.product(*(list(dict.fromkeys(t.types)) for t in g.type_params)):
            mapping = dict(zip((t.name for t in g.type_params), types))
            local = []
            checker = GraphChecker(specialize(g, mapping), callable_, self.schema, filename, local)
            checker.unsure = unsure
            checker.modules = self
            checker.type_args = mapping
            # The groups its calls build while it is checked are not the text's: no caller needs them
            self.collecting.append([])
            try:
                checker.run()
            finally:
                self.collecting.pop()
            found.append((types, local))
        common = set.intersection(*({(d.line, d.col, d.message) for d in local} for _t, local in found))
        written = set()
        for types, local in found:
            for d in local:
                at = (d.line, d.col, d.message)
                if at in common:
                    if at not in written:
                        written.add(at)
                        diags.append(d)
                else:
                    diags.append(Diagnostic(d.file, d.line, d.col, f"{shown(key(g.name), types)}: {d.message}"))

    def variant(self, callee, kind, types=()):
        """(ir.Graph, diagnostics) of a module's graph built for a tree of `kind` and, for a template,
        for its `types`; or (None, why).

        Its body is checked again as a graph of that kind and those types: a graph of math nodes alone
        (Math, Map Range, Mix…) works in every tree. `why` is None when the graph is not a module's: a
        text calls its own graphs from their own kind of tree only, and its templates through a use
        only, for Tree → Text to write the call back from the group's tags.
        """
        owner = self.owners.get(id(callee))
        if owner is None:
            return None, None
        ident, callable_, filename, unsure = owner
        at = (ident, key(callee.name), tuple(types), kind)
        if at not in self.variants:
            # Being built: a call of the same graph inside it is a recursion
            self.variants[at] = (None, [Diagnostic(filename, callee.line, callee.col,
                                                   f"recursive call: '{shown(key(callee.name), types)}' "
                                                   "calls itself")])
            mapping = dict(zip((t.name for t in callee.type_params), types))
            g = specialize(callee, mapping)
            g.kind = kind
            diags = []
            checker = GraphChecker(g, callable_, self.schema, filename, diags)
            checker.unsure = unsure
            checker.modules = self
            checker.variant = kind != callee.kind
            checker.type_args = mapping
            made = checker.run()
            if made is None or diags:
                self.variants[at] = (None, diags or [Diagnostic(filename, callee.line, callee.col, "not built")])
            else:
                made.name = instance_name(callee.name, types) if types else callee.name
                if kind != callee.kind:
                    made.name = variant_name(made.name, kind)
                made.called_as = callee.name
                made.module = ident
                if types:
                    made.types = list(types)
                    made.type_inputs = [[i for i, p in enumerate(callee.params) if p.type == t.name]
                                        for t in callee.type_params]
                self.variants[at] = (made, [])
                self.variant_graphs[made.name] = made
        made, diags = self.variants[at]
        if made is not None and self.collecting:
            self.collect(made, self.collecting[-1])
        return made, diags

    def collect(self, g, into):
        """A variant into the list of the file calling it, after the variants it calls."""
        if g in into:
            return
        for n in g.nodes:
            callee = self.variant_graphs.get(n.group)
            if callee is not None and callee is not g:
                self.collect(callee, into)
        into.append(g)

    def imports(self, file, filename, stack, diags):
        """{key: (ast.Graph, its Use)} of the graphs the uses bring."""
        imported = {}
        names = set()
        for u in file.uses:
            def error(message):
                diags.append(Diagnostic(filename, u.line, u.col, message))
            if u.name in names:
                error(f"module '{u.name}' imported twice: only one use per module")
                continue
            names.add(u.name)
            unit = self.unit(u, stack, error)
            if unit is None:
                continue
            self.units[id(u)] = unit
            wanted = u.names if u.names is not None else list(unit.graphs)
            for k in wanted:
                if k not in unit.graphs:
                    error(f"'{k}' is not in module {u.name}; graphs: {short_list(sorted(unit.graphs))}")
                elif is_material(unit.graphs[k].settings):
                    if u.names is not None:
                        error(f"'{k}' is a material: a use brings node groups only")
                    continue
                elif k in imported and imported[k][1].name != u.name:
                    error(f"'{k}' is in {imported[k][1].name} and in {u.name}: "
                          f"disambiguate with use {u.name} (…)")
                else:
                    imported[k] = (unit.graphs[k], u)

            # Register namespaced calls: <alias>::<func> and <name>::<func>
            prefix = getattr(u, "alias", None) or u.name
            for k, g in unit.graphs.items():
                if is_material(g.settings):
                    continue
                imported[f"{prefix}::{k}"] = (g, u)
                if getattr(u, "alias", None):
                    imported[f"{u.name}::{k}"] = (g, u)
        return imported

    def unit(self, u, stack, error):
        ident = (u.name, u.source)
        if ident in stack:
            error("circular import: " + " -> ".join(n for n, _s in stack + (ident,)))
            return None
        if ident in self.done:
            return self.done[ident]
        if self.load is None:
            error("use: no module loader configured")
            return None
        try:
            text, filename = self.load(u.name, u.source)
        except LookupError as e:
            error(f"module '{u.name}': {e.args[0] if e.args else e}")
            return None
        try:
            unit = self.check(parse(text, filename), filename, ident, stack + (ident,))
        except BnError as e:
            first, n = e.diagnostics[0], len(e.diagnostics)
            error(f"module '{u.name}': {first}" + (f" (+{n - 1} error(s))" if n > 1 else ""))
            return None
        self.done[ident] = unit
        return unit

    def needed(self, uses, imported):
        """The modules' graphs to build: a whole module, or the names listed and what they call."""
        out = []
        for u in uses:
            unit = self.units.get(id(u))
            if unit is None:
                continue
            if u.names is None:
                # A module's materials stay in it: a use brings node groups
                out += [g for g in unit.order if not is_material(g.settings)]
                continue
            by_ir = {g.name: g for g in unit.order}
            keep = set()
            todo = [unit.graphs[k].name for k in u.names if k in unit.graphs]
            while todo:
                name = todo.pop()
                if name in keep or name not in by_ir:
                    continue
                keep.add(name)
                todo += [n.group for n in by_ir[name].nodes if n.group]
            out += [g for g in unit.order if g.name in keep]
        return out


def check_graphs(graphs, by_name, callable_, schema, filename, diags, unsure=False, modules=None):
    """The file's own graphs, checked, callees before callers."""
    checked, calls = {}, {}
    for g in graphs:
        c = GraphChecker(g, callable_, schema, filename, diags)
        c.unsure = unsure
        c.modules = modules
        checked[key(g.name)] = c.run()
        calls[key(g.name)] = c.calls

    order = []
    state = {}

    def visit(name, via):
        if state.get(name) == "done":
            return
        if state.get(name) == "open":
            g = by_name[via]
            diags.append(Diagnostic(filename, g.line, g.col, f"recursive call: '{via}' calls '{name}'"))
            return
        state[name] = "open"
        for callee in calls.get(name, ()):
            visit(callee, name)
        state[name] = "done"
        if checked.get(name):
            order.append(checked[name])

    for g in graphs:
        visit(key(g.name), key(g.name))
    return order


class GraphChecker:
    def __init__(self, graph, graphs, schema, filename, diags):
        self.g = graph
        self.graphs = graphs
        self.schema = schema
        self.filename = filename
        self.diags = diags
        self.nodes = []
        self.env = {}
        self.calls = set()
        self.separated = {}  # (node id, output identifier) -> SeparateXYZ node id, for p.x
        self.conditions = set()  # ids of the Math nodes a comparison wrote, where the tree has no Compare
        self.frames = []
        self.last_frame = {}  # (parent frame id, title) -> id of the last frame opened so
        self.returned = None
        self.zone = None  # inside a zone's body: the Zone
        self.signatures = {}  # Closure Output id -> (input items, output items, item options) it defines
        self.frame_now = None
        self.unsure = False  # a module failed to load: an unknown call may be one of its graphs
        # The Modules that build a module's graph for this kind of tree, or a template for its types
        # (variant); None for a graph checked alone
        self.modules = None
        self.type_args = {}  # in a template's body: {type parameter: the type it is built for}
        self.variant = False  # a module's graph checked again for another kind of tree
        self.implicit = []  # (input key, field) a variant's call must give: see group_signature

    def error(self, at, message):
        self.diags.append(Diagnostic(self.filename, at.line, at.col, message))

    def unknown(self, at, name):
        """A name bound to nothing, with the names of this graph it looks like: a typo, most often."""
        close = difflib.get_close_matches(name, list(self.env), 3)
        hint = f"; did you mean {', '.join(close)}?" if close else ""
        self.error(at, f"unknown name '{name}'{hint}")

    def run(self):
        g = self.g
        if g.kind == "pixel":
            self.error(g, "pixel is not a Blender tree kind; expected: geometry, shader, compositor")
            return None
        if g.kind not in TREE_KINDS:
            self.error(g, f"unknown tree kind '{g.kind}'; expected: {', '.join(TREE_KINDS)}")
            return None

        ok = True
        for p in g.params + g.outputs:
            if p.type not in TYPES:
                self.error(p, f"unknown type '{p.type}'; expected: {', '.join(TYPES)}")
                ok = False
        if not ok:
            return None

        defaults = self.defaults()
        gin = ir.Node(ir.GROUP_INPUT, "NodeGroupInput", n_outputs=len(g.params), line=g.line, col=g.col)
        gout = ir.Node(ir.GROUP_OUTPUT, "NodeGroupOutput", n_inputs=len(g.outputs), line=g.line, col=g.col)
        self.nodes += [gin, gout]
        for p in g.params:
            if p.key in self.env:
                self.error(p, f"parameter '{p.key}' defined twice" + twice_hint(p))
            sock = Socket(p.name, p.key, p.type)
            self.env[p.key] = Out(ir.GROUP_INPUT, [sock], sock, p.key)
        keys = set()
        for o in g.outputs:
            if o.key in keys:
                self.error(o, f"output '{o.key}' defined twice" + twice_hint(o))
            keys.add(o.key)

        self.statements(g.body, gout, None)
        if not self.returned:
            self.error(g, f"missing return in '{g.name}'")

        graph = ir.Graph(g.kind, g.name, [(p.name, p.type) for p in g.params],
                         [(o.name, o.type) for o in g.outputs], self.nodes, g.line, g.col, self.frames, defaults)
        graph.options = self.options()
        graph.description = g.description
        graph.input_keys = [p.key for p in g.params]
        graph.output_keys = [o.key for o in g.outputs]
        graph.panels, graph.panel_of = self.panels()
        graph.settings = self.literal_options(g.settings, "setting")
        if DEPRECATED in graph.settings:
            # Not the tree's: said to whoever calls the graph (deprecated_calls)
            del graph.settings[DEPRECATED]
            written = next(a for a in g.settings if a.name == DEPRECATED)
            if isinstance(written.value, (ast.String, ast.Bool)):
                graph.deprecated = deprecation(g)
            else:
                self.error(written, f"setting '{DEPRECATED}': true, or what to use instead, in quotes")
        if MATERIAL in graph.settings:
            self.material(graph)
        return graph

    def material(self, graph):
        """A material's own tree: no input, and the Material Output's sockets as outputs."""
        g = self.g
        if not isinstance(graph.settings[MATERIAL], bool):
            self.error(g, f"setting '{MATERIAL}': true or false")
            return
        if not graph.settings[MATERIAL]:
            return
        if g.kind != "shader":
            self.error(g, f"only a shader graph is a material, not a {g.kind} graph")
            return
        if g.params:
            self.error(g.params[0], "a material takes no input: its values are written in its nodes")
        for o in g.outputs:
            wanted = MATERIAL_OUTPUTS.get(o.key)
            if wanted is None:
                self.error(o, f"'{o.key}' is not a Material Output socket; outputs: "
                              + ", ".join(f"{k}: {t}" for k, t in MATERIAL_OUTPUTS.items()))
            elif o.type != wanted:
                self.error(o, f"Material Output '{o.key}' is a {wanted}, not a {o.type}")

    def panels(self):
        """(ir panels, {(side, key): panel id}) from the panels of both lists, one per path of names."""
        found = {}  # path of names -> (ir.Panel, whether its settings were given)
        panel_of = {}

        def walk(items, side, path, parent):
            seen_panel = None
            names = set()
            for n, item in enumerate(items):
                if isinstance(item, ast.Param):
                    if seen_panel is not None:
                        self.error(item, f"'{item.name}' comes after panel '{seen_panel.name}': "
                                         "Blender places sockets before panels")
                    if parent is not None:
                        panel_of[(side, item.key)] = parent.id
                    self.toggle(item, side, parent, n)
                    continue
                seen_panel = item
                if item.name in names:
                    self.error(item, f"panel '{item.name}' written twice in the same list")
                    continue
                names.add(item.name)
                here = path + (item.name,)
                if here not in found:
                    panel = ir.Panel(f"p{len(found)}", item.name, parent.id if parent else None,
                                     line=item.line, col=item.col)
                    found[here] = (panel, False)
                panel, given = found[here]
                if item.options:
                    if given:
                        self.error(item, f"panel '{item.name}' settings given twice: "
                                         "define them once, in the first list where it appears")
                    else:
                        panel.options = self.literal_options(item.options, "setting")
                        found[here] = (panel, True)
                walk(item.items, side, here, panel)

        walk(self.g.tree("INPUT"), "INPUT", (), None)
        if not self.g.single_output:
            walk(self.g.tree("OUTPUT"), "OUTPUT", (), None)
        return [p for p, _given in found.values()], panel_of

    def toggle(self, p, side, panel, position):
        """`"Settings": Bool(is_panel_toggle: true)` turns its panel on and off, as Blender has it."""
        flag = next((a for a in p.options if a.name == "is_panel_toggle"), None)
        if flag is None or not (isinstance(flag.value, ast.Bool) and flag.value.value):
            return
        if side != "INPUT" or panel is None or p.type != "Bool":
            self.error(flag, "is_panel_toggle: must be a Bool input, the first in a panel")
        elif position != 0:
            self.error(flag, f"is_panel_toggle: toggle switch must be first in panel '{panel.name}'")
        elif p.name != panel.name:
            self.error(flag, f"is_panel_toggle: toggle switch must match panel name '{panel.name}'")

    def literal_options(self, items, what):
        """{name: value} of `(name: value, …)` settings, each a plain value: Blender checks the names."""
        found = {}
        for a in items:
            if a.name in found:
                self.error(a, f"{what} '{a.name}' given twice")
                continue
            v = a.value
            if isinstance(v, ast.Ref):
                found[a.name] = v.name
            elif isinstance(v, (ast.Number, ast.String, ast.Bool, ast.Neg)) and isinstance(self.eval(v), Lit):
                found[a.name] = self.eval(v).value
            else:
                self.error(a, f"{what} '{a.name}': expected number, true/false, string, or enum value like FACTOR")
        return found

    # Interface

    def defaults(self):
        """{input key: {"value", "min", "max", "implicit"}} from `name: Type = default in lo..hi`."""
        for o in self.g.outputs:
            if o.default is not None or o.range is not None:
                self.error(o, f"output '{o.name}' has no default value or range")
        out = {}
        for p in self.g.params:
            spec = {}
            d = p.default
            if isinstance(d, ast.Call) and d.name in IMPLICIT:
                mode, wanted = IMPLICIT[d.name]
                if d.args:
                    self.error(d, f"{d.name}() default value does not take arguments")
                elif self.g.kind != "geometry":
                    # A field taken from the context: geometry trees have them, the others not.
                    # A module's graph built for another tree has none: its callers give the value
                    if not self.variant:
                        self.error(d, f"{d.name}() default value only applies in a geometry tree")
                elif p.type != wanted:
                    self.error(d, f"{d.name}() default value only applies to a {wanted} input")
                else:
                    spec["implicit"] = mode
            elif d is not None:
                value = self.default_value(p, d)
                if value is not None:
                    spec["value"] = value
            if p.range is not None:
                bounds = self.bounds(p)
                if bounds is not None:
                    spec.update((k, v) for k, v in zip(("min", "max"), bounds) if v is not None)
            if spec:
                out[p.key] = spec
        return out

    def options(self):
        """{(side, name): {property: value}} from `x: Float(subtype: FACTOR, …)`.

        The property names are Blender's, checked by the builder; here only their values are."""
        out = {}
        for side, params in (("INPUT", self.g.params), ("OUTPUT", self.g.outputs)):
            for p in params:
                found = {}
                for a in p.options:
                    # An output has no default to give its size: its dimensions are an option
                    if a.name in WRITTEN_ELSEWHERE and not (side == "OUTPUT" and a.name == "dimensions"):
                        self.error(a, f"{a.name} is written {WRITTEN_ELSEWHERE[a.name]}")
                        continue
                    if a.name in found:
                        self.error(a, f"option '{a.name}' given twice")
                        continue
                    value = self.option_value(a)
                    if value is not None:
                        found[a.name] = value
                if found:
                    out[(side, p.key)] = found
        return out

    def option_value(self, a):
        """The value of `option: value`, a literal or an enum name; None after an error."""
        v = a.value
        if isinstance(v, ast.Ref):
            return v.name
        if isinstance(v, (ast.Number, ast.String, ast.Bool, ast.Neg)) and isinstance(self.eval(v), Lit):
            return self.eval(v).value
        self.error(a, f"option '{a.name}': expected number, true/false, string, or enum value like FACTOR")
        return None

    def item_options(self, c, a):
        """{option: value} from `name(option: value): …`, by the item's Blender property names.

        The names are checked by the builder, against the item; here only the values are."""
        found = {}
        for o in a.options:
            if o.name in ("name", "socket_type", "data_type", "type"):
                self.error(o, f"{c.name}: item name and type must be written 'name: value'")
                continue
            if o.name in found:
                self.error(o, f"option '{o.name}' given twice")
                continue
            value = self.option_value(o)
            if value is not None:
                found[o.name] = value
        return found

    def default_value(self, p, d):
        t = p.type
        if t in NO_DEFAULT:
            self.error(d, f"a {t} input does not take a default value")
            return None
        if t in BARE_NAMES and isinstance(d, (ast.Ref, ast.String)):
            return d.name if isinstance(d, ast.Ref) else d.value
        if not isinstance(d, (ast.Number, ast.String, ast.Bool, ast.Tuple, ast.Neg)):
            self.error(d, f"default value for '{p.name}': expected number, tuple, true/false, string"
                          f" or {', '.join(n + '()' for n in IMPLICIT)}")
            return None
        v = self.eval(d)
        if v is None:
            return None
        if t == "Float" and v.type in ("Int", "Float"):
            return float(v.value)
        if t in ("Int", "Bool") and v.type == t:
            return v.value
        # A Vector of 2 or 4 numbers sets the socket's dimensions
        if t == "Vector" and isinstance(v.value, tuple) or t == "Rotation" and v.type == "Vector" and len(v.value) == 3:
            return v.value
        if t == "Color" and v.type in ("Vector", "Color") and len(v.value) in (3, 4):
            return v.value
        if (t == "String" or t in DATABLOCKS) and v.type == "String":
            return v.value
        self.error(d, f"default value of type {v.type} for a {t} input")
        return None

    def bounds(self, p):
        at = p.range[0] or p.range[1]
        if p.type not in RANGED:
            self.error(at, f"a {p.type} input does not take bounds; bounds apply to: {', '.join(sorted(RANGED))}")
            return None
        values = []
        for b in p.range:
            if b is None:
                values.append(None)
                continue
            v = self.eval(b) if isinstance(b, (ast.Number, ast.Neg)) else None
            if not (isinstance(v, Lit) and v.type in ("Int", "Float")) or p.type == "Int" and v.type != "Int":
                self.error(b, f"bound for '{p.name}': expected a{'n integer' if p.type == 'Int' else ''} number")
                return None
            values.append(v.value if p.type == "Int" else float(v.value))
        if None not in values and values[0] > values[1]:
            self.error(at, f"bounds for '{p.name}': min exceeds max")
            return None
        return tuple(values)

    # Statements

    def statements(self, body, gout, frame):
        """Check a block; the nodes each statement makes go into `frame`."""
        for stmt in body:
            if self.returned and not (isinstance(stmt, ast.Frame) and not stmt.body):
                self.error(stmt, "statement after return")
                return
            created = len(self.nodes)
            self.frame_now = frame
            if isinstance(stmt, ast.Frame):
                self.frame_stmt(stmt, gout, frame)
                continue
            if isinstance(stmt, ast.Assign):
                self.assign_stmt(stmt)
            elif self.zone is not None:
                self.zone_return(stmt)
                self.returned = stmt
                self.zone.out.frame = frame
                self.look(self.zone.out, stmt.look)
            else:
                self.return_stmt(stmt, gout)
                self.returned = stmt
                gout.frame = frame
                self.look(gout, stmt.look)
            for n in self.nodes[created:]:
                # A repeat body has placed its own nodes, frames included
                if n.frame is None:
                    n.frame = frame

    def frame_stmt(self, f, gout, parent):
        color = None
        if f.color is not None:
            color = colors.rgb(f.color[1:])
            if color is None:
                self.error(f, f"unknown color '{f.color}': expected #rrggbb, #rgb or CSS name (#orange, #teal…)")
        if f.continued:
            # The statements go on in the last frame of that title opened in the same block
            known = self.last_frame.get((parent, f.label))
            if known is None:
                title = f"'{f.label}'" if f.label is not None else "untitled"
                self.error(f, f"no earlier {title} frame in this block to continue")
                return
            self.statements(f.body, gout, known)
            return
        frame = ir.Frame(f"f{len(self.frames)}", f.label, color, parent, f.line, f.col)
        self.frames.append(frame)
        if f.body:
            # A note is not continued: the frames around statements are
            self.last_frame[(parent, f.label)] = frame.id
        self.statements(f.body, gout, frame.id)

    def assign_stmt(self, stmt):
        if stmt.name in self.env:
            self.error(stmt, f"'{stmt.name}' is already defined")
            return
        created = len(self.nodes)
        if isinstance(stmt.value, ast.BODIES):
            # A call with a body is a zone, a graph with no name a Closure zone
            zone, refused = zones.read(stmt.value)
            if refused is not None:
                self.error(*refused)
                value = None
            elif isinstance(zone, zones.Foreach):
                value = self.foreach(zone, stmt.name)
            elif isinstance(zone, zones.Closure):
                value = self.closure(zone, stmt.name)
            else:
                value = self.state_zone(zone, stmt.name, zones.WORDS[type(zone)])
        else:
            value = self.eval(stmt.value)
            if isinstance(value, Lit):
                value = self.const(stmt, value)
        if value is None:
            # Keep the name known, so later uses do not report it again
            self.env[stmt.name] = None
            return
        made = isinstance(value, Out) and value.node in {n.id for n in self.nodes[created:]}
        if made:
            node = next(n for n in self.nodes if n.id == value.node)
            if node.name is None:
                node.name = stmt.name
            self.look(node, stmt.look)
        elif stmt.look is not None:
            self.error(stmt.look, f"@: '{stmt.name}' does not produce its own node")
        self.env[stmt.name] = value

    def const(self, stmt, lit):
        """`size = 10`: a Value, Int, Bool… node named `size`, or the literal alone when none fits."""
        made = CONST_NODES.get(lit.type)
        if made is None:
            return lit
        spec = self.schema.node(self.g.kind, made[0])
        if spec is not None and lit.type == "Color" and spec.bl_idname in RGB_NODES:
            made = RGB_NODES[spec.bl_idname]
        if spec is None or spec.bl_idname != made[2]:
            return lit
        inputs, outputs = self.schema.sockets(self.g.kind, spec, {})
        if len(outputs) != 1:
            return lit
        node = ir.Node(f"n{len(self.nodes)}", spec.bl_idname, n_inputs=len(inputs), n_outputs=len(outputs),
                       line=stmt.line, col=stmt.col)
        value = float(lit.value) if lit.type == "Float" else lit.value
        if made[1] is None:
            node.out_values[outputs[0].identifier] = value
        else:
            if lit.type == "Vector" and len(value) == 2:
                # A 2D vector: the node takes two numbers once its dimensions say so
                node.props["vector_dimensions"] = 2
            node.props[made[1]] = value
        self.nodes.append(node)
        return Const(node.id, outputs, None, stmt.name, lit)

    def named_string(self, const, sock, where):
        """What to write for a named string given to a datablock input: `o = "Thing"` is a String
        node, which no datablock input reads. The name in place, or the datablock's input node."""
        value = const.lit.value
        hint = f'write the name in place, {sock.key}: "{value}"'
        made = DATABLOCK_NODES.get(sock.type)
        spec = self.schema.node(self.g.kind, made[0]) if made else None
        if spec is not None:
            hint += f', or name a {made[0]} node: {const.label} = {made[0]}[{made[1]}: "{value}"]()'
        return f"{where} expects {sock.type}, receives a String ({const.label}): {hint}"

    def value_prop(self, spec, node, v, a):
        """`Rotation[rotation_euler: (0.1, 0.0, 0.0)]()`, `Vector[vector: (1.0, 2.0, 3.0, 4.0)]()`: the value
        of an input node that no literal makes, a tuple of as many numbers as the node holds. A Vector's
        vector_dimensions follow the tuple, unless written."""
        prop, integers = VALUE_PROPS[spec.bl_idname]
        if isinstance(v, Const):
            v = v.lit
        if not (isinstance(v, Lit) and isinstance(v.value, tuple)):
            self.error(a, f"{prop} expects a tuple of numbers")
            return
        value = v.value
        if "vector_dimensions" in spec.props:
            size = node.props.setdefault("vector_dimensions", len(value))
            if not isinstance(size, int) or size != len(value):
                self.error(a, f"{prop} expects {size} numbers (vector_dimensions), receives {len(value)}")
                return
        elif len(value) != 3:
            self.error(a, f"{prop} expects 3 numbers, receives {len(value)}")
            return
        if integers:
            if any(x != int(x) for x in value):
                self.error(a, f"{prop} expects whole numbers")
                return
            value = tuple(int(x) for x in value)
        node.props[prop] = value

    def look(self, node, look):
        """`@ "Label" #color hide mute`: the Blender properties of how a node is shown."""
        if look is None:
            return
        if look.label is not None:
            node.look["label"] = look.label
        if look.color is not None:
            color = colors.rgb(look.color[1:])
            if color is None:
                self.error(look, f"unknown color '{look.color}': expected #rrggbb, #rgb or CSS name (#orange, #teal…)")
            else:
                node.look["use_custom_color"] = True
                node.look["color"] = color
        node.look.update((flag, True) for flag in look.flags)

    def return_stmt(self, stmt, gout):
        gout.line, gout.col = stmt.line, stmt.col
        outs = [Socket(o.name, o.key, o.type) for o in self.g.outputs]
        if isinstance(stmt.value, ast.Record):
            # Outputs left out stay unlinked, as Blender allows
            given = {}
            for f in self.untyped(stmt.value.fields):
                sock = find_socket(outs, f.name)
                if isinstance(sock, list):
                    self.error(f, f"'{f.name}' is ambiguous; outputs: {', '.join(s.identifier for s in sock)}")
                    continue
                if sock is None:
                    self.error(f, f"'{f.name}' is not an output; outputs: {', '.join(s.name for s in outs)}")
                    continue
                if sock.identifier in given:
                    self.error(f, f"output '{f.name}' given twice")
                    continue
                given[sock.identifier] = f
                value = self.eval(f.value)
                if value is not None:
                    self.connect(gout, sock, value, f, "return")
            return
        if not self.g.single_output:
            self.error(stmt, f"graph has multiple outputs: return ({', '.join(s.name + ': …' for s in outs)})")
            return
        value = self.eval(stmt.value)
        if value is not None:
            self.connect(gout, outs[0], value, stmt.value, "return")

    # Zones

    def state_zone(self, e, name, word):
        """A Repeat or a Simulation zone: its input node takes the starting states (and a
        Repeat its count), its body computes the next states from the current ones, its
        output node gives the last."""
        repeat = word == "repeat"
        zin = ir.Node(f"n{len(self.nodes)}", ir.REPEAT_INPUT if repeat else ir.SIMULATION_INPUT,
                      line=e.line, col=e.col)
        zout = ir.Node(f"n{len(self.nodes) + 1}", ir.REPEAT_OUTPUT if repeat else ir.SIMULATION_OUTPUT,
                       line=e.line, col=e.col)
        zin.pair = zout.id
        self.nodes += [zin, zout]
        count = self.eval(e.count) if repeat else None
        allowed = REPEAT_ITEMS if repeat else SIMULATION_ITEMS
        starts, items, keys = [], [], []
        for a in e.states:
            if a.name is None:
                # A state is a named value: `repeat(n, total: 0.0)`, not `repeat(n, total)`
                self.error(a, f"a {word} state is named: {word}({'10, ' if repeat else ''}state: start)")
                continue
            v = self.zone_value(a)
            # `"Delta Time" as dt: …`: the body, the return and the users name the state dt
            k = a.alias or key(a.name)
            if k in keys or key(a.name) in {key(n) for n, _t in items} and not a.alias:
                self.error(a, f"state '{a.name}' declared twice")
                continue
            if k in STATE_NAMES[word]:
                self.error(a, STATE_NAMES[word][k])
                continue
            if v is None:
                continue
            if isinstance(v, Sym):
                self.unknown(a, v.name)
                continue
            t = value_type(v)
            if t not in allowed:
                self.error(a, f"a {word} state cannot have type {t}")
                continue
            items.append((a.name, t))
            keys.append(k)
            starts.append((a, v))
        zin.items = zout.items = items
        # Linked by the item's name, known in text by its key. A state named like a socket of
        # the zone itself (`Iteration` beside the iteration) is linked by its number: `#0`, `#1`…
        fixed = {n for side in ir.ZONE_SOCKETS[zin.bl_idname] + ir.ZONE_SOCKETS[zout.bl_idname] for n in side}
        states = [Socket(n if k == key(n) else k, f"#{i}" if n in fixed else n, t)
                  for i, ((n, t), k) in enumerate(zip(items, keys))]
        if repeat:
            zin_inputs = [Socket("Iterations", "Iterations", "Int")] + states
            zin_outputs = [Socket("Iteration", "Iteration", "Int")] + states
            skip = None
        else:
            zin_inputs = states
            zin_outputs = [Socket("Delta Time", "Delta Time", "Float")] + states
            skip = Socket("Skip", "Skip", "Bool")
        zin.n_inputs, zin.n_outputs = len(zin_inputs), len(zin_outputs)
        zout.n_inputs, zout.n_outputs = len(states) + (skip is not None), len(states)
        if count is not None:
            self.connect(zin, zin_inputs[0], count, e.count, word)
        for (a, v), sock in zip(starts, states):
            if not isinstance(v, Empty):
                self.connect(zin, sock, v, a, word)

        # The body sees the outer names, the states and the input's own output; its names stay inside
        zone = Zone(word, zout, states, skip)
        names = {key(s.name): s for s in states}
        names["iteration" if repeat else "delta_time"] = zin_outputs[0]
        self.body(e, name, zone, zin, zin_outputs, names)
        # A state the body does not return goes on unchanged
        for sock in states:
            if sock.name not in zone.given:
                zout.links.append((sock.identifier, ir.Link(zin.id, sock.identifier)))
        # With no state left, uses of the name would only repeat the error
        return Out(zout.id, states, None, name) if states else None

    def foreach(self, e, name):
        """A For Each Geometry Element zone: its input node takes the geometry, the selection
        and the input items, its body runs once per element, and the items its return gives
        make the output node's main and generation items."""
        zin = ir.Node(f"n{len(self.nodes)}", ir.FOREACH_INPUT, line=e.line, col=e.col)
        zout = ir.Node(f"n{len(self.nodes) + 1}", ir.FOREACH_OUTPUT, line=e.line, col=e.col)
        zin.pair = zout.id
        zout.items = []
        self.nodes += [zin, zout]
        geometry = self.zone_value(e.geometry)
        self.foreach_settings(e, zout)
        selection, given, values, items = None, set(), [], []
        for a in e.args:
            k = key(a.name)
            if k in given:
                self.error(a, f"'{a.name}' given twice")
                continue
            given.add(k)
            if k == "selection":
                selection = (self.eval(a.value), a)
                continue
            if k in ("index", "element"):
                self.error(a, f"'{k}' is the element's {'index' if k == 'index' else 'geometry'}: "
                              "choose another item name")
                continue
            v = self.zone_value(a)
            if v is None:
                continue
            if isinstance(v, Sym):
                self.unknown(a, v.name)
                continue
            t = value_type(v)
            if t not in FOREACH_INPUT_ITEMS:
                self.error(a, f"a foreach input item cannot have type {t}")
                continue
            items.append((a.name, t))
            values.append((a, v))
        zin.items = items
        sockets = [Socket(n, n, t) for n, t in items]
        zin_inputs = [Socket("Geometry", "Geometry", "Geometry"), Socket("Selection", "Selection", "Bool")] + sockets
        zin_outputs = [Socket("Index", "Index", "Int"), Socket("Element", "Element", "Geometry")] + sockets
        zin.n_inputs, zin.n_outputs = len(zin_inputs), len(zin_outputs)
        if isinstance(geometry, Sym):
            self.unknown(e.geometry, geometry.name)
        elif isinstance(geometry, Empty) and geometry.type != "Geometry":
            self.error(e.geometry, f"foreach.geometry expects Geometry, receives {geometry.type}")
        elif geometry is not None and not isinstance(geometry, Empty):
            self.connect(zin, zin_inputs[0], geometry, e.geometry, "foreach")
        if selection is not None and selection[0] is not None:
            self.connect(zin, zin_inputs[1], *selection, "foreach")
        for (a, v), sock in zip(values, sockets):
            if not isinstance(v, Empty):
                self.connect(zin, sock, v, a, "foreach")

        zone = Zone("foreach", zout, [], None)
        zone.outputs = [Socket("Geometry", ir.FOREACH_GEOMETRY, "Geometry")]
        names = {key(s.name): s for s in sockets}
        names.update(index=zin_outputs[0], element=zin_outputs[1])
        self.body(e, name, zone, zin, zin_outputs, names)
        zout.n_outputs = len(zone.outputs)
        return Out(zout.id, zone.outputs, None, name)

    def foreach_settings(self, e, zout):
        """`foreach[FACE](…)`: the domain, its one setting, by position or named."""
        for n, s in enumerate(e.settings):
            if s.name not in (None, "domain"):
                self.error(s, f"foreach has no setting '{s.name}'; settings: domain")
            elif n:
                self.error(s, "setting 'domain' given twice")
            elif isinstance(s.value, ast.Ref) and s.value.name in FOREACH_DOMAINS:
                zout.props["domain"] = s.value.name
            else:
                self.error(s, f"domain expects one of {', '.join(FOREACH_DOMAINS)}")

    def body(self, e, name, zone, zin, zin_outputs, names):
        """Check a zone's body, which sees the outer names and `names`, outputs of the zone's input."""
        saved = self.env, self.returned, self.zone
        self.env = dict(self.env)
        for k, sock in names.items():
            self.env[k] = Out(zin.id, zin_outputs, sock, k)
        self.returned = None
        self.zone = zone
        frame = self.frame_now
        self.statements(e.body, None, frame)
        if not self.returned:
            self.error(e, f"missing return in {zone.word} of '{name}'")
        zin.frame = zone.out.frame = frame
        self.env, self.returned, self.zone = saved
        self.frame_now = frame

    def zone_value(self, a):
        """The value of an item, an Arg (or an expression): a type alone is an item with no value,
        `cache: Bundle`; `name: Type = value` gives the item that type, `name: Type = _` none."""
        if isinstance(a, ast.Arg) and a.type is not None:
            t = a.type.type
            if t not in TYPES:
                self.error(a.type, f"unknown type '{t}'; expected: {', '.join(TYPES)}")
                return None
            if is_no_value(a.value):
                return Empty(t)
            v = self.eval(a.value)
            return Typed(v, t) if v is not None else None
        v = self.eval(a.value if isinstance(a, ast.Arg) else a)
        if isinstance(v, Sym) and v.name in TYPES:
            return Empty(v.name)
        return v

    def zone_return(self, stmt):
        if self.zone.word == "foreach":
            self.foreach_return(stmt)
            return
        zone, word = self.zone, self.zone.word
        states = zone.states
        if word == "closure":
            what, whats, twice = "closure output", "outputs", "output '{}' returned twice"
        else:
            what, whats, twice = f"{word} state", "states", "state '{}' returned twice"
        if isinstance(stmt.value, ast.Record):
            for f in stmt.value.fields:
                if zone.skip is not None and key(f.name) == "skip":
                    if "skip" in zone.given:
                        self.error(f, "skip returned twice")
                        continue
                    zone.given.add("skip")
                    value = self.eval(f.value)
                    if value is not None:
                        self.connect(zone.out, zone.skip, value, f, word)
                    continue
                sock = next((s for s in states if key(f.name) == key(s.name)), None)
                if sock is None:
                    self.error(f, f"'{f.name}' is not a {what}; {whats}: "
                                  f"{', '.join(s.name for s in states) or 'none'}")
                    continue
                if sock.name in zone.given:
                    self.error(f, twice.format(f.name))
                    continue
                zone.given.add(sock.name)
                self.state(sock, self.zone_value(f), f)
            return
        if len(states) != 1:
            many = (f"this {word} has multiple states" if word != "closure" else
                    "this closure has multiple outputs" if states else "this closure has no outputs")
            self.error(stmt, f"{many}: return ({', '.join(s.name + ': …' for s in states)})")
            return
        zone.given.add(states[0].name)
        self.state(states[0], self.zone_value(stmt.value), stmt.value)

    def state(self, sock, value, at):
        """The next value of a state: linked, set, or left empty by its type alone."""
        if isinstance(value, Empty):
            if value.type != sock.type:
                self.error(at, f"{self.zone.word}.{sock.key} expects {sock.type}, receives {value.type}")
        elif value is not None:
            self.connect(self.zone.out, sock, value, at, self.zone.word)

    def foreach_return(self, stmt):
        """The items of a For Each output: main items, then each Geometry with its attributes."""
        zone = self.zone
        if not isinstance(stmt.value, ast.Record):
            self.error(stmt, "foreach returns items by name: return (item: v, mesh: g, …)")
            return
        main, generation, seen = [], [], set()
        for f in stmt.value.fields:
            if key(f.name) in seen:
                self.error(f, f"item '{f.name}' returned twice")
                continue
            seen.add(key(f.name))
            v = self.zone_value(f)
            if v is None:
                continue
            if isinstance(v, Sym):
                self.unknown(f, v.name)
                continue
            t = value_type(v)
            if t == "Geometry" or generation:
                if t not in FOREACH_ITEMS and t != "Geometry":
                    self.error(f, f"a foreach generated attribute cannot have type {t}")
                    continue
                generation.append((f, v, t))
            elif t not in FOREACH_ITEMS:
                self.error(f, f"a foreach item cannot have type {t}")
                continue
            else:
                main.append((f, v, t))
        zone.out.items = [(f.name, t) for f, _v, t in main + generation]
        zone.out.main = len(main)
        zone.out.n_inputs = len(zone.out.items)
        sockets = [Socket(n, n, t) for n, t in zone.out.items]
        if any(s.key == "geometry" for s in sockets):
            # Then only the zone's name alone gives it
            zone.outputs = [Socket(ir.FOREACH_GEOMETRY, ir.FOREACH_GEOMETRY, "Geometry")]
        zone.outputs += sockets
        for (f, v, _t), sock in zip(main + generation, sockets):
            if not isinstance(v, Empty):
                self.connect(zone.out, sock, v, f, "foreach")

    def untyped(self, fields):
        """The fields of a return: a type before `=` belongs to an item, not to an output."""
        for f in fields:
            if f.type is not None:
                self.error(f, f"'{f.name}': types cannot be specified in a return")
            else:
                yield f

    # Closure zones

    def closure(self, e, name):
        """A Closure zone: its input node gives the closure's inputs to its body, its output
        node takes what the body returns and gives the closure. The body captures the outer names."""
        cin = ir.Node(f"n{len(self.nodes)}", CLOSURE_INPUT, line=e.line, col=e.col)
        cout = ir.Node(f"n{len(self.nodes) + 1}", CLOSURE_OUTPUT, line=e.line, col=e.col)
        cin.pair = cout.id
        self.nodes += [cin, cout]
        options = {}
        items = self.declared(e.params, "in", options, "closure")
        outs = self.declared(e.outputs, "out", options, "closure")
        for n in (cin, cout):
            n.items, n.out_items, n.item_options = items, outs, options
        inputs = item_sockets(items)
        results = item_sockets(outs)
        cin.n_outputs = len(inputs)
        cout.n_inputs, cout.n_outputs = len(results), 1

        # The body sees the outer names and the inputs; its own names stay inside
        zone = Zone("closure", cout, results, None)
        self.body(e, name, zone, cin, inputs, {key(s.name): s for s in inputs})
        self.signatures[cout.id] = (items, outs, options)
        return Out(cout.id, [Socket("Closure", "Closure", "Closure")], None, name)

    def declared(self, params, side, options, what):
        """(name, type) of items declared as `name: Type(structure_type: …)`; their options go in `options`."""
        items = []
        for p in params:
            if p.type not in ITEM_TYPES:
                self.error(p, f"unknown type '{p.type}'; expected: {', '.join(ITEM_TYPES)}")
                continue
            if p.default is not None or p.range is not None:
                self.error(p, f"a {what} item has no default value or range")
                continue
            if key(p.name) in {key(n) for n, _t in items}:
                self.error(p, f"item '{p.name}' declared twice")
                continue
            items.append((p.name, p.type))
            found = self.item_options(p, p)
            if found:
                options[p.name if side == "in" else ("out", p.name)] = found
        return items

    # Bundles and closure calls

    def signature_call(self, c, spec, piped, target=None):
        """Combine Bundle, Separate Bundle and Evaluate Closure: nodes whose items the text gives a type each.

        `target` is the closure of `f(x: …)`, a call on a name; else it is the first positional value."""
        node = ir.Node("", spec.bl_idname, line=c.line, col=c.col)
        positional = [(piped, c)] if piped is not None else []
        named = []
        self.settings(c, spec, node)
        for a in c.args:
            if a.name is None:
                positional.append((None if is_no_value(a.value) else self.eval(a.value), a.value))
            else:
                named.append((a, self.zone_value(a)))
        fixed = SIGNATURE_NODES[spec.bl_idname]["inputs"][0]
        if target is not None:
            if positional:
                self.error(positional[0][1], f"a closure takes inputs by name: {c.name}(x: …)")
                return None
            positional = [(target, c)]
        if len(positional) > fixed:
            if spec.bl_idname == SEPARATE_BUNDLE:
                self.error(positional[fixed][1], "SeparateBundle takes the bundle alone: "
                                                 "SeparateBundle(b) -> (name: Type, …)")
            elif spec.bl_idname == CLOSURE_TO_LIST:
                self.error(positional[fixed][1], "ClosureToList takes Count and Closure: "
                                                 "ClosureToList(count, closure) -> (name: Type, …)")
            else:
                self.error(positional[fixed][1], f"{c.name}: items are passed by name, {c.name}(…, name: value)")
            return None

        options = {}
        if spec.bl_idname == COMBINE_BUNDLE:
            if c.outputs is not None:
                self.error(c, "CombineBundle has only one output, the bundle: no '->'")
                return None
            items, values = self.given_items(c, named, options)
        elif spec.bl_idname in (SEPARATE_BUNDLE, CLOSURE_TO_LIST):
            fixed_sockets = self.schema.sockets(self.g.kind, spec, node.props)[0][:fixed]
            fixed_values = [None] * fixed
            if spec.bl_idname == CLOSURE_TO_LIST and len(positional) == 1 and not named:
                val, _arg = positional[0]
                if value_type(val) == "Closure":
                    fixed_values[1] = positional[0]
                else:
                    fixed_values[0] = positional[0]
            else:
                for idx, pos in enumerate(positional):
                    if idx < fixed:
                        fixed_values[idx] = pos
            for a, v in named:
                sock = find_socket(fixed_sockets, a.name)
                if isinstance(sock, Socket):
                    matched_idx = fixed_sockets.index(sock)
                    if fixed_values[matched_idx] is not None:
                        self.error(a, f"input '{a.name}' given twice")
                        return None
                    fixed_values[matched_idx] = (v, a.value)
                else:
                    usage = "SeparateBundle(b)" if spec.bl_idname == SEPARATE_BUNDLE else "ClosureToList(count, closure)"
                    self.error(a, f"{spec.name} declares items after '->': "
                                  f"{usage} -> (name: Type, …)")
                    return None
            if c.outputs is None:
                usage = "SeparateBundle(b)" if spec.bl_idname == SEPARATE_BUNDLE else "ClosureToList(count, closure)"
                self.error(c, f"{spec.name} declares items: {usage} -> (name: Type, …)")
                return None
            items, values = [], []
            positional = fixed_values
        elif c.outputs is not None:
            items, values = self.given_items(c, named, options)
        else:
            # Evaluate Closure without `->`: the items of the closure it is given, defined in this graph
            closure = positional[0][0] if positional else None
            sig = self.signatures.get(closure.node) if isinstance(closure, Out) else None
            if sig is None:
                self.error(c, f"{c.name}: closure signature is not known here; declare its items: "
                              f"{c.name}(x: Float = …) -> (r: Float)")
                return None
            items, outs, sig_options = sig
            options = dict(sig_options)
            node.out_items = outs
            values = []
            for a, v in named:
                if isinstance(v, (Empty, Typed)):
                    self.error(a, f"'{a.name}': when given a type, outputs must also be declared: {c.name}(…) -> (…)")
                    return None
                if a.options:
                    self.error(a, f"'{a.name}': when given options, outputs must also be declared: {c.name}(…) -> (…)")
                    return None
                name = next((n for n, _t in items if key(n) == key(a.name)), None)
                if name is None:
                    self.error(a, f"closure has no input '{a.name}'; inputs: "
                                  f"{', '.join(n for n, _t in items) or 'none'}")
                elif v is not None and not (isinstance(v, Sym) and v.name == NO_VALUE):
                    values.append((name, v, a))
        if items is None:
            return None
        if c.outputs is not None:
            node.out_items = self.declared(c.outputs, "out", options, c.name)
        if spec.bl_idname not in (SEPARATE_BUNDLE, CLOSURE_TO_LIST):
            node.items = items
        node.item_options = options

        sides = SIGNATURE_NODES[spec.bl_idname]
        fixed_inputs, fixed_outputs = self.schema.sockets(self.g.kind, spec, node.props)
        inputs = fixed_inputs[:sides["inputs"][0]] + item_sockets(node.items or [])
        outputs = fixed_outputs[:sides["outputs"][0]] + item_sockets(node.out_items or [])
        node.n_inputs, node.n_outputs = len(inputs), len(outputs)
        # Numbered once its arguments have made their own nodes
        node.id = f"n{len(self.nodes)}"
        self.nodes.append(node)
        for pos, sock in zip(positional, inputs):
            if pos is not None:
                v, a = pos
                if v is not None:
                    self.connect(node, sock, v, a, c.name)
        names = [n for n, _t in node.items or []]
        for name, v, a in values:
            self.connect(node, inputs[fixed + names.index(name)], v, a, c.name)
        return Out(node.id, outputs, None, c.name)

    def given_items(self, c, named, options):
        """(items, values) from `name: value`, `name: Type = value` and `name: Type` arguments;
        (None, None) on error."""
        items, values = [], []
        ok = True
        for a, v in named:
            if key(a.name) in {key(n) for n, _t in items}:
                self.error(a, f"{c.name}: '{a.name}' given twice")
                ok = False
                continue
            if isinstance(v, Sym):
                if v.name == NO_VALUE:
                    self.error(a, f"'{a.name}' has no value: specify its type, {a.name}: Float")
                else:
                    self.unknown(a.value, v.name)
                ok = False
                continue
            if v is None:
                ok = False
                continue
            t = value_type(v)
            if t not in ITEM_TYPES:
                self.error(a, f"{c.name}: no item of type {t}")
                ok = False
                continue
            items.append((a.name, t))
            found = self.item_options(c, a)
            if found:
                options[a.name] = found
            if not isinstance(v, Empty):
                values.append((a.name, v, a))
        return (items, values) if ok else (None, None)

    # Expressions

    def eval(self, e):
        if isinstance(e, ast.Number):
            return Lit(e.value, "Int" if e.is_int else "Float")
        if isinstance(e, ast.String):
            return Lit(e.value, "String")
        if isinstance(e, ast.Bool):
            return Lit(e.value, "Bool")
        if isinstance(e, ast.Tuple):
            return self.tuple(e)
        if isinstance(e, ast.Ref):
            if e.name in self.env:
                return self.env[e.name]
            return Sym(e.name)
        if isinstance(e, ast.Member):
            return self.member(e, self.eval(e.target))
        if isinstance(e, ast.Call):
            return self.call(e)
        if isinstance(e, ast.Pipe):
            left = self.eval(e.left)
            if left is None:
                return None
            if isinstance(e.call, ast.Member):
                return self.member(e.call, self.call(e.call.target, piped=left))
            return self.call(e.call, piped=left)
        if isinstance(e, ast.BinOp) and e.op == "+":
            return self.plus(e)
        if isinstance(e, ast.BinOp):
            return self.formula(e, e.op, [(self.eval(e.left), e.left), (self.eval(e.right), e.right)])
        if isinstance(e, ast.Not):
            return self.formula(e, "not", [(self.eval(e.value), e.value)])
        if isinstance(e, ast.Cond):
            return self.ternary(e)
        if isinstance(e, ast.Neg):
            v = self.eval(e.value)
            if isinstance(v, Lit) and v.type in ("Int", "Float"):
                return Lit(-v.value, v.type)
            if isinstance(v, Lit) and isinstance(v.value, tuple):
                return Lit(tuple(-x for x in v.value), v.type)
            # -x is x times -1: Math Multiply, or Vector Math Scale
            return self.formula(e, "neg", [(v, e.value), (Lit(-1.0, "Float"), e)])
        raise TypeError(e)

    def tuple(self, e):
        values = []
        for item in e.items:
            v = self.eval(item)
            if isinstance(v, Const):
                v = v.lit
            if not (isinstance(v, Lit) and v.type in ("Int", "Float")):
                self.error(item, "a tuple contains only numbers")
                return None
            values.append(float(v.value))
        if len(values) not in (2, 3, 4):
            self.error(e, "a tuple takes 2, 3 or 4 numbers")
            return None
        return Lit(tuple(values), "Color" if len(values) == 4 else "Vector")

    def member(self, e, target):
        if target is None:
            return None
        if isinstance(target, Sym):
            self.unknown(e.target, target.name)
            return None
        if not isinstance(target, Out):
            self.error(e, f"'.{e.socket}' only applies to a node")
            return None
        # A Color goes into Separate XYZ as a vector, its alpha left out; an integer vector as floats
        if e.socket in sugar.COMPONENTS and target.socket is not None and target.socket.type in sugar.VECTOR \
                and (target.chosen is not None or find_socket(target.outputs, e.socket) is None):
            return self.component(e, target)
        if target.chosen is not None:
            self.error(e, f"'{target.label}' is already an output ({target.chosen.type}); '.{e.socket}' does not exist")
            return None
        sock = find_socket(target.outputs, e.socket)
        if isinstance(sock, list):
            self.error(e, f"'{e.socket}' is ambiguous; use identifier: {', '.join(s.identifier for s in sock)}")
            return None
        if sock is None:
            parts = ("; components: " + ", ".join(sugar.COMPONENTS)
                     if target.socket is not None and target.socket.type in sugar.VECTOR else "")
            self.error(e, f"{target.label} has no output '{e.socket}'; outputs: {socket_keys(target.outputs)}{parts}")
            return None
        return Out(target.node, target.outputs, sock, f"{target.label}.{e.socket}")

    def component(self, e, target):
        """`v.x`: one Separate XYZ per vector or color, shared by its components."""
        src = target.socket
        spec = self.schema.node(self.g.kind, "SeparateXYZ")
        if spec is None:
            self.error(e, f"no SeparateXYZ in a {self.g.kind} tree")
            return None
        inputs, outputs = self.schema.sockets(self.g.kind, spec, {})
        memo = (target.node, src.identifier)
        if memo not in self.separated:
            node = ir.Node(f"n{len(self.nodes)}", spec.bl_idname, n_inputs=len(inputs),
                           n_outputs=len(outputs), line=e.line, col=e.col)
            self.nodes.append(node)
            self.connect(node, inputs[0], target, e, "SeparateXYZ")
            self.separated[memo] = node.id
        sock = find_socket(outputs, e.socket)
        return Out(self.separated[memo], outputs, sock, f"{target.label}.{e.socket}")

    def plus(self, e):
        """`a + b + c`: one Join Geometry for geometries, else Math or Vector Math, pair by pair.

        Joining is the same whatever the parentheses, so `a + (b + c)` is one
        Join too: the canonical graph has no Join feeding a Join of its own.
        """
        steps = []
        while isinstance(e, ast.BinOp) and e.op == "+":
            steps.append(e)
            e = e.left
        steps.reverse()
        v = self.eval(e)
        if value_type(v) == "Geometry":
            return self.join(steps[0], [(v, e)] + [(self.eval(t), t) for s in steps for t in plus_terms(s.right)])
        for s in steps:
            right = self.eval(s.right)
            if value_type(right) == "Geometry" and v is not None:
                self.error(s.left, f"'+' joins Geometry, not {value_type(v)}")
                return None
            v = self.formula(s, "+", [(v, s.left), (right, s.right)])
        return v

    def join(self, at, terms):
        for v, a in terms:
            if v is None:
                return None
            if isinstance(v, Sym):
                self.unknown(a, v.name)
                return None
            if value_type(v) != "Geometry":
                self.error(a, f"'+' joins Geometry, not {value_type(v)}")
                return None
        spec = self.schema.node(self.g.kind, "JoinGeometry")
        if spec is None:
            self.error(at, f"no JoinGeometry in a {self.g.kind} tree")
            return None
        inputs, outputs = self.schema.sockets(self.g.kind, spec, {})
        node = ir.Node(f"n{len(self.nodes)}", spec.bl_idname, n_inputs=len(inputs), n_outputs=len(outputs),
                       line=at.line, col=at.col)
        self.nodes.append(node)
        for v, a in terms:
            self.connect(node, inputs[0], v, a, "+")
        return Out(node.id, outputs, None, "+")

    def is_function(self, name):
        return (name in sugar.FUNCS and name not in self.graphs
                and self.schema.node(self.g.kind, name) is None)

    def formula(self, at, op, operands):
        """A Math, Vector Math or Compare node for an operator or a function, from evaluated operands."""
        for v, a in operands:
            if v is None:
                return None
            if isinstance(v, Sym):
                self.unknown(a, v.name)
                return None
        if op in sugar.COMPARE and self.schema.node(self.g.kind, "Compare") is None:
            return self.math_comparison(at, op, operands)
        try:
            name, props, order = sugar.choose(op, [value_type(v) for v, _a in operands])
        except ValueError as err:
            self.error(at, str(err))
            return None
        spec = self.schema.node(self.g.kind, name)
        if spec is None:
            self.error(at, f"no {name} in a {self.g.kind} tree")
            return None
        inputs, outputs = self.schema.sockets(self.g.kind, spec, props)
        n_inputs = len(inputs)
        if name in sugar.OPERANDS:
            inputs = inputs[:sugar.OPERANDS[name]]
        if len(inputs) != len(operands):
            self.error(at, f"{op} expects {len(inputs)} argument(s), receives {len(operands)}")
            return None
        node = ir.Node(f"n{len(self.nodes)}", spec.bl_idname, props=dict(props), n_inputs=n_inputs,
                       n_outputs=len(outputs), line=at.line, col=at.col)
        self.nodes.append(node)
        for sock, i in zip(inputs, order):
            v, a = operands[i]
            self.connect(node, sock, operand_tuple(v, sock), a, op)
        return Out(node.id, outputs, None, op)

    def math_comparison(self, at, op, operands):
        """A comparison in a tree with no Compare node (a shader tree): Math on numbers, a Float 0 or 1.
        `>` and `<` are Math's own, `==` its Compare with Compare's Epsilon; `>=`, `<=` and `!=` are
        the opposite one taken from 1."""
        try:
            operation, negated = sugar.math_compare(op, [value_type(v) for v, _a in operands])
        except ValueError as err:
            self.error(at, f"{err}: a {self.g.kind} tree has no Compare node")
            return None
        values = list(operands)
        if operation == "COMPARE":
            values.append((Lit(sugar.EPSILON, "Float"), at))
        out = self.math_node(at, operation, values, op)
        if out is not None and negated:
            out = self.math_node(at, "SUBTRACT", [(Lit(1.0, "Float"), at), (out, at)], op)
        return out

    def math_node(self, at, operation, values, label):
        """One Math node of a comparison, its inputs taken in order."""
        spec = self.schema.node(self.g.kind, "Math")
        if spec is None:
            self.error(at, f"no Compare nor Math in a {self.g.kind} tree")
            return None
        props = {"operation": operation}
        inputs, outputs = self.schema.sockets(self.g.kind, spec, props)
        node = ir.Node(f"n{len(self.nodes)}", spec.bl_idname, props=props, n_inputs=len(inputs),
                       n_outputs=len(outputs), line=at.line, col=at.col)
        self.nodes.append(node)
        self.conditions.add(node.id)
        for sock, (v, a) in zip(inputs, values):
            self.connect(node, sock, v, a, label)
        return Out(node.id, outputs, None, label)

    def is_condition(self, v):
        """Whether a value says yes or no: a Bool, or what a comparison gives in a tree with no Compare
        node, a Math node that is Greater Than, Less Than or Compare, or such a one taken from 1.
        A name keeps it: the node it is bound to is looked at."""
        if value_type(v) == "Bool":
            return True
        if not isinstance(v, Out):
            return False
        if v.node in self.conditions:
            return True
        return math_condition(next((n for n in self.nodes if n.id == v.node), None), self.nodes)

    def ternary(self, e):
        """`cond ? then : orelse`. Where a Switch chooses for each element, in a geometry tree, a Switch
        of the type of its branches. In a shader or a compositor tree a Switch takes one value for a
        whole image, so it is a Mix by a condition (0 or 1), a Mix Shader for shaders: both branches
        are computed, and the condition must be one, as a Mix by any Float blends."""
        cond, then, orelse = [(self.eval(x), x) for x in (e.cond, e.then, e.orelse)]
        values = [cond, orelse, then]  # as the inputs of the nodes go: the value when false first
        for v, a in values:
            if v is None:
                return None
            if isinstance(v, Sym):
                self.unknown(a, v.name)
                return None
        (cond, _), (orelse, _), (then, _) = values
        positional = []
        if self.switches():
            name = "Switch"
            spec = self.schema.node(self.g.kind, name)
            keys = ("switch", "False", "True")
        else:
            found = [(k, value_type(v), isinstance(v, Out), len(v.value) if is_tuple(v) else 0)
                     for k, v in (("False", orelse), ("True", then))]
            t = branches_type(found)
            name = "MixShader" if t == "Shader" else "Mix"
            spec = self.schema.node(self.g.kind, name)
            setting = MIX_TYPES.get(t)
            if spec is None or name == "Mix" and setting not in spec.props["data_type"].items:
                takes = [x for x in dict.fromkeys(MIX_TYPES) if x not in ("Int", "Bool")]
                takes += ["Shader"] if self.schema.node(self.g.kind, "MixShader") is not None else []
                self.error(e, f"'? :' chooses between {takes_list(takes)} in a {self.g.kind} tree, not {t}")
                return None
            if not self.is_condition(cond):
                self.error(e.cond, f"the condition of '? :' is a {value_type(cond)}: in a {self.g.kind} tree it "
                                   f"is built with {name}, which blends by any number and does not choose. "
                                   f"Write a comparison (f > 0.5 ? a : b), or call {name}(factor: f, …) to blend")
                return None
            keys = ("factor", "a", "b") if name == "Mix" else ("factor", "Shader", "Shader_001")
        if spec is None:
            self.error(e, f"no {name} in a {self.g.kind} tree")
            return None
        node = ir.Node(f"n{len(self.nodes)}", spec.bl_idname, line=e.line, col=e.col)
        named = [(k, v, a) for k, (v, a) in zip(keys, values)]
        if name == "Mix":
            node.props["data_type"] = setting
        else:
            self.tuple_type(spec, node, positional, named)
            self.switch_type(spec, node, positional, named)
        inputs, outputs = self.schema.sockets(self.g.kind, spec, node.props)
        node.n_inputs, node.n_outputs = len(inputs), len(outputs)
        self.nodes.append(node)
        places = ("the condition of '? :'", "the value of '? :' when false", "the value of '? :' when true")
        for (k, v, a), where in zip(named, places):
            self.connect(node, find_socket(inputs, k), v, a, "? :", where)
        return Out(node.id, outputs, None, "? :")

    def switches(self):
        """Whether a Switch of this tree chooses for each element: a geometry tree's. A shader's or a
        compositor's takes one value for the whole image, and gives its False input when given more."""
        return self.g.kind == "geometry" and self.schema.node(self.g.kind, "Switch") is not None

    def call(self, c, piped=None):
        spec = None if c.name in self.graphs or self.is_function(c.name) else self.schema.node(self.g.kind, c.name)
        if spec is not None and spec.bl_idname in (COMBINE_BUNDLE, SEPARATE_BUNDLE, EVALUATE_CLOSURE, CLOSURE_TO_LIST):
            return self.signature_call(c, spec, piped)
        if spec is None and c.name not in self.graphs and not self.is_function(c.name) \
                and self.existing_group(c) is None and isinstance(self.env.get(c.name), Out) \
                and value_type(self.env[c.name]) == "Closure":
            # A call on a name that holds a closure, when nothing else has that name: Evaluate Closure
            evaluate = self.schema.node(self.g.kind, "EvaluateClosure")
            if evaluate is not None:
                return self.signature_call(c, evaluate, piped, target=self.env[c.name])
        if c.outputs is not None:
            self.error(c, f"'->' declares items of SeparateBundle or EvaluateClosure, not {c.name}")
            return None
        if c.type_args is not None and c.name not in self.graphs:
            if c.name in self.env:
                # A name the parser cannot know holds a value, `iteration` in a repeat: `<` compared
                self.error(c, f"'{c.name}' is a value, not a template: "
                              f"a comparison goes in parentheses, ({c.name} < {c.type_args[0]})")
            elif spec is None and not self.unsure and not self.is_function(c.name) \
                    and self.existing_group(c) is None:
                # Nothing has that name: `x < y, z > (w)` compares an unknown x as much as it calls it
                self.unknown(c, c.name)
            else:
                self.error(c, f"'{c.name}' is not a template: it takes no type")
            return None
        items = self.takes_items(c.name)
        for a in c.args:
            if a.type is not None and not items:
                self.error(a, f"'{a.name}: {a.type.type} = …' gives an item type: for item nodes, "
                              "zones, or EvaluateClosure")
                return None
        if c.settings and (c.name in self.graphs or self.is_function(c.name) or spec is None
                           and (c.name == EMPTY_GROUP or self.existing_group(c) is not None)):
            # A graph, a group of the file, a function: none has settings, only a node does
            self.error(c.settings[0], f"{c.name} has no settings")
            return None
        if self.is_function(c.name):
            operands = [(piped, c)] if piped is not None else []
            for a in c.args:
                if a.name is not None:
                    self.error(a, f"{c.name} does not take named arguments")
                    return None
                operands.append((self.eval(a.value), a.value))
            return self.formula(c, c.name, operands)

        positional = [(piped, c)] if piped is not None else []
        named = []
        failed = False
        for a in c.args:
            if a.alias and not items:
                self.error(a, f"'{a.name} as {a.alias}': only item node items take an alias key")
            if a.options and not items:
                self.error(a, f"'{a.name}(…)': only item node items take options")
            # An item may be given its type, or be its type alone
            v = self.zone_value(a) if items and a.name is not None else self.eval(a.value)
            failed |= v is None
            if a.name is None:
                positional.append((v, a.value))
            else:
                named.append((a.name, v, a))

        node = ir.Node(f"n{len(self.nodes)}", "", line=c.line, col=c.col)
        self.implicit = []
        spec = None if c.name in self.graphs else self.schema.node(self.g.kind, c.name)
        group = self.existing_group(c) if c.name not in self.graphs and spec is None else None
        if c.name in self.graphs:
            inputs, outputs = self.group_signature(c, node, positional, named)
            if inputs is None:
                return None
        elif group is not None:
            if isinstance(group, list):
                self.error(c, f"'{c.name}' refers to multiple groups in the file: "
                              f"{', '.join(g.name for g in group)}")
                return None
            node.bl_idname = GROUP_NODES[self.g.kind]
            node.group = group.name
            inputs = [Socket(n, k, t) for n, k, t in group.keys("INPUT")]
            outputs = [Socket(n, k, t) for n, k, t in group.keys("OUTPUT")]
        elif spec is None and c.name == EMPTY_GROUP:
            if positional or named:
                self.error(c, f"{EMPTY_GROUP}() is a Group node with no tree: it takes no input")
                return None
            node.bl_idname = GROUP_NODES[self.g.kind]
            inputs, outputs = [], []
        else:
            if spec is None:
                if self.unsure:
                    return None
                # A node, a graph of the file, or, written in lower case, a function such as sin
                funcs = sorted(sugar.FUNCS) if c.name[:1].islower() else []
                nodes = self.schema.node_names(self.g.kind)
                close = suggest(c.name, nodes, [*self.graphs, *funcs])
                hint = f"; did you mean {', '.join(close)}?" if close else ""
                self.error(c, f"unknown node '{c.name}' in a {self.g.kind} tree{hint}")
                return None
            node.bl_idname = spec.bl_idname
            self.settings(c, spec, node)
            if spec.bl_idname in ITEM_NODES:
                inputs, outputs = self.item_sockets(c, spec, node, positional, named)
                if inputs is None:
                    return None
            else:
                self.tuple_type(spec, node, positional, named)
                self.switch_type(spec, node, positional, named)
                inputs, outputs = self.schema.sockets(self.g.kind, spec, node.props)

        node.n_inputs, node.n_outputs = len(inputs), len(outputs)
        self.nodes.append(node)
        if failed:
            named = [(n, v, a) for n, v, a in named if v is not None]

        given = set()
        i = 0
        for v, a in positional:
            if i >= len(inputs):
                self.error(a, f"{c.name} takes {len(inputs)} input(s): {socket_keys(inputs)}")
                break
            sock = inputs[i]
            # A value that failed still takes its place: the next ones go to their own inputs
            if v is not None:
                self.connect(node, sock, v, a, c.name)
            given.add(sock.identifier)
            if not sock.multi_input:
                i += 1

        for name, v, a in named:
            sock = find_socket(inputs, name)
            if isinstance(sock, list):
                self.error(a, f"'{name}' is ambiguous; use identifier: {', '.join(s.identifier for s in sock)}")
                continue
            if sock is None:
                self.error(a, f"{c.name} has no input '{name}'; inputs: {socket_keys(inputs)}")
                continue
            if sock.identifier in given and not sock.multi_input:
                self.error(a, f"input '{name}' given twice")
                continue
            given.add(sock.identifier)
            self.connect(node, sock, v, a, c.name)

        for k, field_ in self.implicit:
            if k not in given:
                self.error(c, f"{c.name}: give '{k}', which is {field_}() in a geometry tree only")
        self.implicit = []
        return Out(node.id, outputs, None, c.name)

    def tuple_type(self, spec, node, positional, named):
        """A tuple only fits a Vector or a Color: when one would reach a number input of a node
        whose type is a setting the call does not write (Switch, Mix, Compare, Store Named
        Attribute…), the node takes the type of its tuples, Color when one has 4 numbers."""
        tuples = [(i, None, v) for i, (v, _a) in enumerate(positional) if is_tuple(v)]
        tuples += [(None, n, v) for n, v, _a in named if is_tuple(v)]
        if not tuples:
            return

        def fit(props):
            inputs = self.schema.sockets(self.g.kind, spec, props)[0]
            for i, name, _v in tuples:
                sock = input_at(inputs, i) if name is None else find_socket(inputs, name)
                if not isinstance(sock, Socket) or sock.type not in TUPLE_SOCKETS:
                    return False
            return True

        if fit(node.props):
            return
        color = any(len(v.value) == 4 for _i, _n, v in tuples)
        for prop in spec.props.values():
            if prop.kind != "ENUM" or prop.name not in TYPE_PROPS or prop.name in node.props:
                continue
            for value in TYPE_VALUES["Color" if color else "Vector"]:
                if value in prop.items and fit({**node.props, prop.name: value}):
                    node.props[prop.name] = value
                    return

    def switch_type(self, spec, node, positional, named):
        """A Switch whose input_type the call does not write takes the type of its values, like the
        switches of items: a new Switch is a Float one in a geometry tree, a Color one in a shader
        or a compositor tree, and `Switch(b, 0.0, SceneTime().frame)` is a Float switch in all of them.
        Tuples choose by tuple_type."""
        prop = spec.props.get(SWITCH_PROP)
        if spec.bl_idname != SWITCH or prop is None or prop.name in node.props:
            return
        if any(is_tuple(v) for v, _a in positional) or any(is_tuple(v) for _n, v, _a in named):
            return
        inputs = self.schema.sockets(self.g.kind, spec, node.props)[0]
        values = [(input_at(inputs, i), v) for i, (v, _a) in enumerate(positional)]
        values += [(find_socket(inputs, n), v) for n, v, _a in named]
        found = [(sock.identifier, value_type(v), isinstance(v, Out)) for sock, v in values
                 if isinstance(sock, Socket) and sock.identifier in SWITCH_VALUES]
        t = switch_value_type(found)
        if t is None or any(s.type == t for s in inputs if s.identifier in SWITCH_VALUES):
            return  # a new Switch is of that type already
        value = type_setting(t, prop.items)
        if value is not None:
            node.props[prop.name] = value

    def takes_items(self, name):
        spec = None if name in self.graphs else self.schema.node(self.g.kind, name)
        return spec is not None and spec.bl_idname in ITEM_NODES

    def item_sockets(self, c, spec, node, positional, named):
        """(inputs, outputs) of a node whose items the call makes, which it records in node.items."""
        shape = ITEM_NODES[spec.bl_idname]
        fixed = self.schema.sockets(self.g.kind, spec, node.props)[0][:shape.inputs]
        if shape.named:
            if len(positional) > shape.inputs:
                self.error(positional[shape.inputs][1], f"{c.name}: items are passed by name, "
                                                        f"{c.name}(…, name: value)")
                return None, None
            # An item under a key of its own may be named like a fixed input
            given = [(n, v, a) for n, v, a in named if a.alias or find_socket(fixed, n) is None]
            named[:] = [(n, v, a) for n, v, a in named if not a.alias and find_socket(fixed, n) is not None]
        else:
            given = [(str(k), v, a) for k, (v, a) in enumerate(positional[shape.inputs:])]
            del positional[shape.inputs:]
        for name, _v, a in named:
            if a.options:
                self.error(a, f"{c.name}: '{name}' is a node input, not an item; it does not take options")
        items, values, options, keys = [], [], {}, []
        for name, v, a in given:
            alias = getattr(a, "alias", None)
            if key(name) in {key(n) for n, _t in items}:
                self.error(a, f"{c.name}: '{name}' given twice")
                continue
            if alias and (find_socket(fixed, alias) is not None or alias in spec.props or alias in keys):
                self.error(a, f"{c.name}: key '{alias}' is already an input, setting, or item of the node")
                continue
            if not alias and shape.named and (key(name) in keys or name in keys):
                self.error(a, f"{c.name}: '{name}' is already an item key")
                continue
            if getattr(a, "options", None):
                options[name] = self.item_options(c, a)
            if isinstance(v, Sym) and v.name == NO_VALUE and not shape.typed:
                # An empty item: no link, its default value (an empty geometry…)
                items.append((name, None))
                keys.append(alias)
                continue
            if isinstance(v, Sym) and not shape.typed and node.props.get("data_type") == "MENU":
                # A menu item's name: IndexSwitch[MENU](i, Read, Compute)
                items.append((name, "Menu"))
                keys.append(alias)
                values.append((alias or name, v, a))
                continue
            if isinstance(v, Sym):
                self.unknown(a, v.name)
                continue
            if v is None:
                continue
            t = value_type(v)
            allowed = shape.types or tuple(ITEM_TYPES)
            if shape.typed and t not in allowed:
                self.error(a, f"{c.name}: no {t} item; types: {', '.join(allowed)}")
                return None, None
            items.append((name, t))
            keys.append(alias)
            if not isinstance(v, Empty):
                # Its type alone is an item with no link, holding the default value of its type
                values.append((alias or name, v, a))
        if not shape.typed:
            # The items share the node's data_type: written, or the type of the first one
            chosen = node.props.get("data_type")
            typed = [t for _n, t in items if t is not None]
            t = DATA_TYPES.get(chosen) if chosen else typed[0] if typed else "Float"
            tuples = [v for _n, v, _a in values if is_tuple(v)]
            color = any(len(v.value) == 4 for v in tuples)
            if not chosen and tuples and (t not in TUPLE_SOCKETS or color and t != "Color"):
                # A tuple only fits a Vector or a Color: IndexSwitch(i, 1.0, (0.5, 0.5, 0.0))
                t = "Color" if color else "Vector"
            if t not in ITEM_TYPES:
                self.error(c, f"{c.name}: no items of type {chosen or t}")
                return None, None
            node.props["data_type"] = ITEM_TYPES[t]
            items = [(name, t) for name, _t in items]
        node.items = items
        node.item_options = {n: o for n, o in options.items() if o}
        inputs, outputs = self.schema.sockets(self.g.kind, spec, node.props)
        # An item with a key of its own goes by it in text, and by its number to the builder
        names = [(k or name, f"#{i}" if k else name) for i, ((name, _t), k) in enumerate(zip(items, keys))]
        sockets = [Socket(n, ident, t, size=ITEM_SIZES.get(t, 0)) for (n, ident), (_name, t) in zip(names, items)]
        # Each value to its own item, by name: an empty one in between is skipped
        named += values
        added = {"value": sockets, "flag": [Socket(n, ident, "Bool") for n, ident in names]}.get(shape.out, [])
        return inputs[:shape.inputs] + sockets, outputs[:shape.outputs] + added

    def existing_group(self, c):
        """A node group of the file with that key, when the text does not define one."""
        groups = getattr(self.schema, "groups", None)
        return groups(self.g.kind).get(c.name) if groups else None

    def group_signature(self, c, node, positional=(), named=()):
        callee = self.graphs[c.name]
        if is_material(callee.settings):
            self.error(c, f"'{c.name}' is a material, not a node group: no graph calls it")
            return None, None
        node.bl_idname = GROUP_NODES[self.g.kind]
        types = ()
        if callee.type_params:
            types = self.template_types(c, callee, positional, named)
            if types is None:
                return None, None
        elif c.type_args is not None:
            self.error(c, f"'{c.name}' is not a template: it takes no type")
            return None, None
        if not types and callee.kind == self.g.kind:
            self.calls.add(c.name)
            node.group = callee.name
            return ([Socket(p.name, p.key, p.type) for p in callee.params],
                    [Socket(o.name, o.key, o.type) for o in callee.outputs])
        # A module's graph is built again for this kind of tree, when its nodes are there too, and a
        # template for the types of the call
        made, why = self.modules.variant(callee, self.g.kind, types) if self.modules else (None, None)
        if made is None:
            self.not_built(c, callee, types, why)
            return None, None
        node.group = made.name
        if callee.kind != self.g.kind:
            # A field a geometry tree takes from the context: here the call gives it
            self.implicit = [(p.key, p.default.name) for p in callee.params
                             if isinstance(p.default, ast.Call) and p.default.name in IMPLICIT]
        return ([Socket(n, k, t) for (n, t), k in zip(made.inputs, made.input_keys)],
                [Socket(n, k, t) for (n, t), k in zip(made.outputs, made.output_keys)])

    def not_built(self, c, callee, types, why):
        """Why a module's graph is not built for this call: the first error of its body, or that the
        graph is the text's own."""
        what = shown(c.name, types)
        if why:
            first = why[0]
            where = f"{first.message} ({first.file}:{first.line})"
            if callee.kind != self.g.kind:
                self.error(c, f"'{what}' is a {callee.kind} graph that cannot be built in a "
                              f"{self.g.kind} tree: {where}")
            else:
                self.error(c, f"'{what}' cannot be built: {where}")
        elif types:
            self.error(c, f"'{c.name}' is a template: a template is a module's graph, brought by a use")
        else:
            self.error(c, f"'{c.name}' is a {callee.kind} graph, not {self.g.kind}; "
                          "a graph of a module (use) is built for every kind of tree")

    def template_types(self, c, callee, positional, named):
        """The types a template is called with: written (`f<Vector>(…)`), else inferred from the
        arguments given to its inputs of a type parameter, linked ones first, then literals."""
        params = callee.type_params
        names = [t.name for t in params]

        def allowed(t, p):
            if t in p.types:
                return True
            self.error(c, f"{c.name}: {p.name} cannot be {t}; {p.name} is one of {', '.join(p.types)}")
            return False

        if c.type_args is not None:
            types = [self.type_args.get(t, t) for t in c.type_args]
            if len(types) != len(params):
                self.error(c, f"{c.name} takes {len(params)} type(s) ({', '.join(names)}), not {len(types)}")
                return None
            return types if all([allowed(t, p) for t, p in zip(types, params)]) else None
        given = []  # (input, value)
        for (v, _a), p in zip(positional, callee.params):
            given.append((p, v))
        for name, v, _a in named:
            p = next((p for p in callee.params if name in (p.key, p.name)), None)
            if p is not None:
                given.append((p, v))
        types = []
        for t in params:
            found = [(p.key, value_type(v), isinstance(v, Out)) for p, v in given if p.type == t.name]
            chosen, clash = infer_type(found)
            if clash is not None:
                (k1, t1), (k2, t2) = clash
                self.error(c, f"{c.name}: {t.name} is {t1} by '{k1}' and {t2} by '{k2}'; write the type, "
                              f"as {shown(c.name, [t1])}(…)")
                return None
            if chosen is None:
                self.error(c, f"{c.name}: write the type of {t.name}, as {shown(c.name, [t.types[0]])}(…); "
                              "no argument gives it")
                return None
            if not allowed(chosen, t):
                return None
            types.append(chosen)
        return types

    def type_setting(self, v, prop, a, owner):
        """`Mix[data_type: T]` in a template's body: the value of the setting for T's type, or None."""
        t = self.type_args[v.name]
        values = TYPE_SETTINGS.get(t, ())
        chosen = next((x for x in values if not prop.items or x in prop.items), None)
        if chosen is None:
            self.error(a, f"{v.name} is {t}: {owner} has no {prop.name} for {t}; "
                          f"values: {short_list(prop.items)}")
        return chosen

    def settings(self, c, spec, node):
        """The settings a call writes in brackets, into node.props and node.data: `Math[ADD,
        use_clamp: true]`. A setting by position is an enum value: it goes to the first enum setting
        of the node, in Blender's order, that holds it (a template's type to the first one that has a
        value for it). The others are named."""
        given = set()
        value = None
        names = setting_names(spec)
        for s in c.settings:
            v = self.setting_value(s)
            if v is None:
                continue
            if s.name is None:
                prop = self.positional_setting(c, spec, s, v)
                if prop is None:
                    continue
                name = prop.name
            else:
                name = s.name
            if name in given:
                self.error(s, f"setting '{name}' given twice")
                continue
            given.add(name)
            if name in spec.data:
                self.data_prop(node, spec.data[name], s)
            elif name in spec.props:
                self.prop(node, spec.props[name], v, s, c.name)
            elif spec.bl_idname in VALUE_PROPS and VALUE_PROPS[spec.bl_idname][0] == name:
                value = (v, s)
            elif spec.bl_idname in OUTPUT_PROPS and OUTPUT_PROPS[spec.bl_idname][0] == name:
                if isinstance(v, Lit) and isinstance(v.value, tuple) and len(v.value) == 3:
                    node.out_values[OUTPUT_PROPS[spec.bl_idname][1]] = v.value
                else:
                    self.error(s, f"{name} expects 3 numbers: {name}: (0.0, 0.0, 1.0)")
            else:
                close = difflib.get_close_matches(name, names, 1)
                hint = f"; did you mean {close[0]}?" if close else ""
                listed = f"; settings: {short_list(names)}" if names else ": it has none"
                self.error(s, f"{c.name} has no setting '{name}'{hint}{listed}")
        if value is not None:
            # Once its dimensions are set: they make the array that holds it
            self.value_prop(spec, node, *value)

    def setting_value(self, s):
        """What a setting holds, as the checker sees it: Lit, Sym (an enum value, a template's type,
        `_`), or the ast.Call of a ramp or curves. None after an error."""
        v = s.value
        if isinstance(v, ast.Ref):
            if v.name in self.env:
                # A name only the zone or the checker knows holds a value: `iteration`, `index`
                self.error(v, f"'{v.name}' holds a value, and no wire feeds a setting: "
                              "give it in the parentheses, Name[SETTING](input: value)")
                return None
            return Sym(v.name)
        if isinstance(v, ast.Call):
            return v
        return self.eval(v)

    def positional_setting(self, c, spec, s, v):
        """The enum setting a setting given by position goes to, or None after an error."""
        enums = [p for p in spec.props.values() if p.kind == "ENUM"]
        if isinstance(v, Sym) and v.name in self.type_args:
            t = self.type_args[v.name]
            values = TYPE_SETTINGS.get(t, ())
            found = next((p for p in enums if any(x in p.items for x in values)), None)
            # Else the first setting of a type, which says what it holds
            found = found or next((p for p in enums if any(x in p.items for v in TYPE_SETTINGS.values() for x in v)),
                                  None)
            if found is None:
                self.error(s, f"{v.name} is {t}: {c.name} has no setting of a type")
            return found
        word = v.name if isinstance(v, Sym) and v.name != NO_VALUE else \
            v.value if isinstance(v, Lit) and v.type == "String" else None
        if word is None:
            names = setting_names(spec)
            self.error(s, f"{c.name}: a setting by position is an enum value; name the others, "
                          f"{c.name}[{names[0] if names else 'name'}: …]")
            return None
        found = next((p for p in enums if word in p.items), None)
        if found is None:
            values = [x for p in enums for x in p.items]
            close = difflib.get_close_matches(word, values, 1)
            hint = f"; did you mean {close[0]}?" if close else ""
            listed = f"; settings: {short_list([p.name for p in enums])}" if enums else ""
            self.error(s, f"no setting of {c.name} takes {word}{hint}{listed}")
        return found

    def prop(self, node, prop, v, a, owner=None):
        if isinstance(v, Const):
            v = v.lit
        if prop.kind == "ENUM" and isinstance(v, Sym) and v.name in self.type_args:
            value = self.type_setting(v, prop, a, owner or "the node")
            if value is not None:
                node.props[prop.name] = value
            return
        if prop.kind == "ENUM":
            value = v.name if isinstance(v, Sym) else v.value if isinstance(v, Lit) and v.type == "String" else None
            if value is None:
                self.error(a, f"{prop.name} expects a value like {prop.items[0] if prop.items else 'MODE'}")
                return
            if prop.items and value not in prop.items:
                close = difflib.get_close_matches(value, prop.items, 1)
                hint = f"; did you mean {close[0]}?" if close else ""
                self.error(a, f"{prop.name}: unknown {value}{hint}; values: {short_list(prop.items)}")
                return
        elif prop.kind == "BOOLEAN" and isinstance(v, Lit) and v.type == "Bool":
            value = v.value
        elif prop.kind == "INT" and isinstance(v, Lit) and v.type == "Int":
            value = v.value
        elif prop.kind == "FLOAT" and isinstance(v, Lit) and v.type in ("Int", "Float"):
            value = float(v.value)
        elif prop.kind in ("STRING", "ID") and isinstance(v, Lit) and v.type == "String":
            value = v.value
        elif prop.kind == "ID" and isinstance(v, Sym) and v.name == NO_VALUE:
            value = None  # no datablock: a Font node left without its font
        elif prop.kind == "ID":
            self.error(a, f'{prop.name} expects a datablock name ({prop.datablock or "ID"}): "Name"')
            return
        else:
            self.error(a, f"{prop.name} expects a {prop.kind.lower()} value")
            return
        node.props[prop.name] = value

    # Ramps and curves

    def data_prop(self, node, prop, a):
        """A ramp or the curves of a node, as written: Ramp(…), Curve(…), Curves(c: Curve(…))."""
        if a.name in node.data:
            self.error(a, f"{a.name} given twice")
            return
        value = self.ramp(prop, a.value) if prop.kind == "RAMP" else self.mapping(prop, a.value)
        if value is not None:
            node.data[prop.name] = value

    def ramp(self, prop, v):
        if not (isinstance(v, ast.Call) and v.name == RAMP):
            self.error(v, f"{prop.name} expects {RAMP}((position, color), …)")
            return None
        stops, options = [], {}
        for a in v.args:
            if a.name is None:
                stop = self.ramp_stop(a.value)
                if stop is None:
                    return None
                stops.append(stop)
            elif not self.data_option(a, RAMP, RAMP_OPTIONS, options):
                return None
        if not stops:
            self.error(v, f"a {RAMP} has one stop at least: (position, color)")
            return None
        return {"stops": stops, "options": options}

    def ramp_stop(self, e):
        position = plain_number(e.items[0]) if isinstance(e, ast.Tuple) and len(e.items) == 2 else None
        color = plain_numbers(e.items[1]) if position is not None else None
        if color is None or len(color) not in (3, 4):
            self.error(e, f"a {RAMP} stop is (position, color): (0.5, (1.0, 0.5, 0.0, 1.0))")
            return None
        if not 0.0 <= position <= 1.0:
            self.error(e, f"a {RAMP} stop's position is from 0.0 to 1.0, not {position}")
            return None
        return position, color if len(color) == 4 else (*color, 1.0)

    def mapping(self, prop, v):
        """{"curves": {channel number: points}, "options": …}: one Curve, or Curves by channel."""
        channels = prop.items
        if not channels:
            if not (isinstance(v, ast.Call) and v.name == CURVE):
                self.error(v, f"{prop.name} expects {CURVE}((x, y), …)")
                return None
            options = {}
            points = self.curve(v, options)
            return None if points is None else {"curves": {0: points}, "options": options}
        if not (isinstance(v, ast.Call) and v.name == CURVES):
            self.error(v, f"{prop.name} expects {CURVES}({channels[0]}: {CURVE}((x, y), …), …); "
                          f"channels: {', '.join(channels)}")
            return None
        curves, options = {}, {}
        for a in v.args:
            if a.name in channels:
                if channels.index(a.name) in curves:
                    self.error(a, f"curve '{a.name}' given twice")
                    return None
                if not (isinstance(a.value, ast.Call) and a.value.name == CURVE):
                    self.error(a, f"{a.name} expects {CURVE}((x, y), …)")
                    return None
                points = self.curve(a.value, None)
                if points is None:
                    return None
                curves[channels.index(a.name)] = points
            elif a.name is None:
                self.error(a, f"{CURVES} takes its curves by channel ({', '.join(channels)}): "
                              f"{channels[0]}: {CURVE}(…)")
                return None
            elif not self.data_option(a, CURVES, MAPPING_OPTIONS, options, channels):
                return None
        return {"curves": curves, "options": options}

    def curve(self, c, options):
        """The points of a Curve(…); its settings go to `options`, or are refused when None:
        those of several curves are their Curves'."""
        points = []
        for a in c.args:
            if a.name is not None:
                if options is None:
                    self.error(a, f"'{a.name}' is a setting of the {CURVES}, not of one {CURVE}")
                    return None
                if not self.data_option(a, CURVE, MAPPING_OPTIONS, options):
                    return None
                continue
            e = a.value
            xy = [plain_number(i) for i in e.items[:2]] if isinstance(e, ast.Tuple) and len(e.items) in (2, 3) else []
            handle = e.items[2].name if len(xy) == 2 and len(e.items) == 3 and isinstance(e.items[2], ast.Ref) \
                else "AUTO" if len(xy) == 2 and len(e.items) == 2 else None
            if None in xy or handle not in HANDLES:
                self.error(e, f"a {CURVE} point is (x, y), or (x, y, handle) with handle one of "
                              f"{', '.join(HANDLES)}")
                return None
            points.append((xy[0], xy[1], handle))
        if len(points) < 2:
            self.error(c, f"a {CURVE} has two points at least: (x, y)")
            return None
        return points

    def data_option(self, a, call, known, options, channels=()):
        """One named setting of a Ramp, Curve or Curves into `options`; False on an error."""
        if a.name not in known:
            names = [*channels, *known]
            self.error(a, f"{call} has no setting '{a.name}'; settings: {', '.join(names)}")
            return False
        if a.name in options:
            self.error(a, f"setting '{a.name}' given twice")
            return False
        kind, v = known[a.name], a.value
        if isinstance(kind, tuple):
            value = v.name if isinstance(v, ast.Ref) and v.name in kind else None
        elif kind == "BOOLEAN":
            value = v.value if isinstance(v, ast.Bool) else None
        elif kind == "FLOAT":
            value = plain_number(v)
        else:
            value = plain_numbers(v)
            value = value if value is not None and len(value) == 3 else None
        if value is None:
            what = f"one of {', '.join(kind)}" if isinstance(kind, tuple) else \
                {"BOOLEAN": "true or false", "FLOAT": "a number", "COLOR": "a color (r, g, b)"}[kind]
            self.error(a, f"{a.name} expects {what}")
            return False
        options[a.name] = value
        return True

    def connect(self, node, sock, v, at, label, where=None):
        """Link or set one input of `node` from a value. `where` names the input in an error, when
        the text does not write its key."""
        if isinstance(v, Typed):
            v = v.value
        if isinstance(v, Empty):
            self.error(at, f"{label}: a bare type ({v.type}) only applies to an item")
            return
        where = where or (f"{label}.{sock.key}" if label != "return" else f"output '{sock.name}'")
        if isinstance(v, Const) and v.lit.type == "String" and sock.type in DATABLOCKS:
            self.error(at, self.named_string(v, sock, where))
            return
        if isinstance(v, Const) and not can_link(v.socket.type, sock.type):
            v = v.lit
        if isinstance(v, Out):
            src = v.socket
            if src is None:
                self.error(at, f"'{v.label}' has no output")
            elif not can_link(src.type, sock.type):
                hint = other_output(v, sock.type, self.env)
                self.error(at, f"{where} expects {sock.type}, receives {src.type} ({v.label}){hint}")
            else:
                node.links.append((sock.identifier, ir.Link(v.node, src.identifier)))
            return
        # A gizmo's value holds a number when nothing is linked to it; a join, nothing
        if sock.multi_input and sock.type in NO_DEFAULT:
            self.error(at, f"{where} only accepts links")
            return
        if isinstance(v, Sym):
            if sock.type in DATABLOCKS and v.name == NO_VALUE:
                # No datablock at all: a String to Curves left without its font
                node.values[sock.identifier] = None
            elif sock.type in BARE_NAMES and v.name != NO_VALUE:
                # A menu item, a material: a name bound to nothing in the graph is its own
                node.values[sock.identifier] = v.name
            else:
                self.unknown(at, v.name)
            return
        ok = (v.type == sock.type
              or (sock.type == "Menu" and v.type == "String")
              or (sock.type in DATABLOCKS and v.type == "String")
              or (sock.type not in STRICT and v.type not in STRICT))
        if not ok:
            self.error(at, f"{where} expects {sock.type}, receives {v.type}")
            return
        if isinstance(v.value, tuple) and not fits(v.value, sock):
            if sock.type in TUPLE_SOCKETS:
                sizes = "3 or 4" if sock.type == "Color" else str(sock.size)
                self.error(at, f"{where} expects a {sock.type} of {sizes} numbers, receives {len(v.value)}"
                               f"{size_hint(v.value, sock)}")
            else:
                self.error(at, f"{where} expects {sock.type}, receives a {v.type} tuple")
            return
        if sock.type == "Int" and v.type == "Float":
            # Blender would not round it: say so rather than fail at build
            self.error(at, f"{where} expects an integer: {int(v.value)} rather than {v.value}")
            return
        node.values[sock.identifier] = v.value


# The sockets whose value is a name, written bare when nothing of the graph is bound to it:
# a menu's item (`mode: Read`), a material (`material: Rust`, a graph of the text or of the file)
BARE_NAMES = ("Menu", "Material")

# Interface settings the text writes in their own way, not as options
WRITTEN_ELSEWHERE = {
    "name": "before the colon", "socket_type": "after the colon: x: Float",
    "bl_socket_idname": "with type and subtype", "default_value": "after =: x: Float = 1.0",
    "min_value": "with in: x: Float in 0.0..1.0", "max_value": "with in: x: Float in 0.0..1.0",
    "default_input": "after =: p: Vector = Position()", "dimensions": "from default size: (0.5, 0.5) (an output's: Vector(dimensions: 2))",
}

# Text type -> the socket type of a zone item, for each kind of item Blender takes
REPEAT_ITEMS = {t: v for t, v in ITEM_TYPES.items() if t != "Shader"}
SIMULATION_ITEMS = {t: ITEM_TYPES[t] for t in FIELD_TYPES + ("String", "Geometry", "Bundle")}
FOREACH_INPUT_ITEMS = {t: ITEM_TYPES[t] for t in FIELD_TYPES + ("Menu",)}
FOREACH_ITEMS = {t: ITEM_TYPES[t] for t in FIELD_TYPES}  # main items, and generated attributes
FOREACH_DOMAINS = ("POINT", "EDGE", "FACE", "CORNER", "CURVE", "INSTANCE", "LAYER")

# Names a zone's body gives itself, which no state may take
STATE_NAMES = {
    "repeat": {"iteration": "'iteration' is the loop counter: choose another state name"},
    "simulate": {"delta_time": "'delta_time' is the elapsed time since previous step: "
                               "choose another state name",
                 "skip": "'skip' is returned via return (…, skip: …): choose another state name"},
}
DATA_TYPES = {v: t for t, v in ITEM_TYPES.items()}


def function_name(name):
    """Why a graph may not be named like a function: the call would no longer be a formula."""
    node = "Boolean Math" if name in sugar.BOOL_FUNCS else "Math" if name not in sugar.VECTOR_FUNCS \
        else "Vector Math" if name not in sugar.MATH_FUNCS else "Math or Vector Math"
    return f"graph '{name}' has the name of the function {name}: {name}(…) is a {node} node; give the graph another name"


def size_hint(value, sock):
    """How to write a tuple of the wrong size for a 3D vector: `; write (0.1, 0.0, 0.0)`."""
    if sock.type != "Vector" or sock.size != 3 or len(value) not in (2, 4):
        return ""
    fixed = value + (0.0,) if len(value) == 2 else value[:3]
    return f"; write ({', '.join(repr(float(x)) for x in fixed)})"


def twice_hint(p):
    """How to keep two sockets of the same name: give one a key of its own."""
    return f'; to keep both, alias the other with as: "{p.name}" as {snake(p.name)}_2: {p.type}'


def item_sockets(items):
    """Sockets of declared items, numbered by position: `#0`, `#1`… The builder finds them so."""
    return [Socket(name, f"#{i}", t) for i, (name, t) in enumerate(items)]


MATH = "ShaderNodeMath"


def math_condition(node, nodes):
    """Whether a node is a comparison written with Math: Greater Than, Less Than, Compare, or 1 minus one."""
    if node is None or node.bl_idname != MATH:
        return False
    operation = node.props.get("operation")
    if operation in {m for m, _negated in sugar.MATH_COMPARE.values()}:
        return True
    # Math's inputs are Value, Value_001 and Value_002
    if operation != "SUBTRACT" or node.values.get("Value") != 1.0 or len(node.links) != 1 \
            or node.links[0][0] != "Value_001":
        return False
    link = node.links[0][1]
    return math_condition(next((n for n in nodes if n.id == link.node), None), nodes)


def is_no_value(e):
    return isinstance(e, ast.Ref) and e.name == NO_VALUE


def plus_terms(e):
    """The terms of `a + (b + c)`, parentheses aside."""
    if isinstance(e, ast.BinOp) and e.op == "+":
        return plus_terms(e.left) + plus_terms(e.right)
    return [e]


# The sockets a tuple of numbers can set; a Color takes (r, g, b) too, its alpha 1
TUPLE_SOCKETS = ("Vector", "Color", "Rotation")
# The settings that choose a node's socket types, and their values for a tuple
TYPE_PROPS = ("data_type", "input_type")
TYPE_VALUES = {"Vector": ("VECTOR", "FLOAT_VECTOR"), "Color": ("RGBA", "FLOAT_COLOR")}
# How many numbers an item of a switch holds
ITEM_SIZES = {"Vector": 3, "Rotation": 3, "Color": 4}


def is_tuple(v):
    """A tuple literal, not a named one (a Vector node, linked like any output)."""
    return isinstance(v, Lit) and isinstance(v.value, tuple)


def operand_tuple(v, sock):
    """A tuple of a formula, as Blender converts a socket to a 3D vector: (x, y) is (x, y, 0),
    (r, g, b, a) leaves its alpha out. Into a node's input, a tuple has the socket's size."""
    if not is_tuple(v) or sock.type != "Vector" or sock.size != 3:
        return v
    if len(v.value) == 2:
        return Lit(v.value + (0.0,), "Vector")
    if len(v.value) == 4:
        return Lit(v.value[:3], "Vector")
    return v


def fits(value, sock):
    """Whether a tuple can be the socket's value, as the builder sets it."""
    if sock.type not in TUPLE_SOCKETS:
        return False
    if not sock.size:
        return True
    return len(value) == sock.size or sock.type == "Color" and len(value) == 3


def input_at(inputs, i):
    """The input the i-th value by position goes to: a multi-input takes the ones after it."""
    j = 0
    for _ in range(i):
        if j >= len(inputs):
            return None
        if not inputs[j].multi_input:
            j += 1
    return inputs[j] if j < len(inputs) else None


def value_type(v):
    if isinstance(v, Out):
        return v.socket.type if v.socket else None
    if isinstance(v, (Lit, Empty, Typed)):
        return v.type
    return None


def find_socket(sockets, name):
    """By identifier, then UI name, then snake_case key. A list when ambiguous."""
    for attr in ("identifier", "name", "key"):
        found = [s for s in sockets if getattr(s, attr) == name]
        if len(found) == 1:
            return found[0]
        if found:
            return found
    return None


def socket_keys(sockets):
    """How to name each socket in text: its key, or its identifier when the key repeats."""
    keys = [s.key for s in sockets]
    return ", ".join(k if keys.count(k) == 1 else s.identifier for k, s in zip(keys, sockets)) or "none"


def other_output(v, wanted, env):
    """'; did you mean n.mesh?' when the node gives a `wanted` value from an output other than its first."""
    if v.chosen is not None:
        return ""  # the output was named: it is not a slip
    keys = [s.key for s in v.outputs]
    fits = [k if keys.count(k) == 1 else s.identifier
            for k, s in zip(keys, v.outputs) if can_link(s.type, wanted)]
    # Written as it is in the text: the name it was given, else the call
    name = next((k for k, x in env.items() if x is v), f"{v.label}(…)")
    return f"; did you mean {', '.join(f'{name}.{k}' for k in fits[:3])}?" if fits else ""


def setting_names(spec):
    """The settings of a node, in Blender's order: its properties, ramps and curves, and the value an
    input node holds in an array (VALUE_PROPS)."""
    held = [VALUE_PROPS[spec.bl_idname][0]] if spec.bl_idname in VALUE_PROPS else []
    held += [OUTPUT_PROPS[spec.bl_idname][0]] if spec.bl_idname in OUTPUT_PROPS else []
    return [*spec.props, *spec.data, *held]


def short_list(items, limit=12):
    items = list(items)
    return ", ".join(items[:limit]) + (", …" if len(items) > limit else "")


def plain_number(e):
    """The value of a number written as such, `-0.5` too, else None."""
    if isinstance(e, ast.Neg):
        v = plain_number(e.value)
        return None if v is None else -v
    return float(e.value) if isinstance(e, ast.Number) else None


def plain_numbers(e):
    """The values of a tuple of numbers, else None."""
    if not isinstance(e, ast.Tuple):
        return None
    values = tuple(plain_number(i) for i in e.items)
    return None if None in values else values


def suggest(name, nodes, others=()):
    """The names close to an unknown one, at most three: a node first by its UI name, case, spaces and
    underscores aside (`noise_texture`, `noisetexture` -> NoiseTexture), then as difflib sees them."""
    same = [n for n in nodes if loose(n) == loose(name)]
    if same:
        return same[:3]
    by_loose = {}
    for n in nodes:
        by_loose.setdefault(loose(n), n)
    close = difflib.get_close_matches(name, [*nodes, *others], 3)
    close += [by_loose[k] for k in difflib.get_close_matches(loose(name), list(by_loose), 3)]
    return list(dict.fromkeys(close))[:3]
