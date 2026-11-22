"""Compare two node trees on Blender's own data, whatever the reader writes.

The round trip of the libraries compares the text read from a tree with the text read from the tree
built back: a setting the reader does not write is lost on both sides alike, and passes. This module
looks at the trees themselves. It walks Blender's RNA generically, so that it does not share the
reader's idea of what matters: every property of the interface, of each node and its sockets, of the
links, and the number of nodes of each type.

    differences = compare_trees(original, rebuilt, name=lambda id: id.name.removeprefix("original "))

Each `Difference` has a class (`cls`, a short stable slug of `CLASSES`), the tree, the node, its type,
the property and both values. Presentational things (location, width, color, label, name, select,
frames, reroutes…) are compared too, under the classes `presentation:<what>`, never mixed with the rest.

Matching the nodes. The builder does not keep node names, so the nodes are matched by their place in
the graph. Frames and reroutes are left out of the graph (a link through reroutes is one link from the
first node to the last) and every Group Input node is one node: they all give the interface. Each node
then gets the colours of a Weisfeiler-Lehman refinement run on both trees at once: at level 0 its type
(and the group it calls), at level k+1 its colour at level k with the colours of its neighbours at level
k, by which socket they are linked (by index). Two nodes are matched when one colour, at the deepest
level where it is so, is held by one node of each tree; then from each matched pair to its neighbours
linked through the same sockets; then, in a class of colour that holds as many nodes on both sides
(symmetric branches), one pair at a time, the most alike in settings, then in presentation, then in
place, each followed by its neighbours, so that a branch is paired with one branch; at last by type
alone, the most alike first (a group node calling another group is still that group node). What is
left is missing (or merged into a node of the same settings that feeds the same nodes), or extra.

Blind spots: two nodes no link, colour nor setting tells apart may be paired crosswise, which then
shows only as presentation; a difference near a node blurs its colour, so a tree with many
differences may pair some nodes wrongly (their differences then show as settings and links); a merge
is only seen between nodes of the same settings; a node made into another type is one missing and one
extra; the links of a reroute that nothing feeds are dropped, as Blender gives nothing through it;
what is not RNA (the inside of an image, a driver's expression beyond its path) is not compared.
"""

from __future__ import annotations

import collections
import math
import re
import struct
from dataclasses import dataclass

import bpy

# The classes, the most serious first: what loses or may lose a value or a node, then what only
# shows in the editor
CLASSES = (
    "node-missing",          # a node of the original has no counterpart in the rebuilt tree
    "node-extra",            # a node of the rebuilt tree has none in the original
    "node-merged",           # several nodes of the original are one in the rebuilt tree
    "node-split",            # one node of the original is several in the rebuilt tree
    "link-missing",          # a link of the original is not in the rebuilt tree
    "link-extra",            # a link of the rebuilt tree is not in the original
    "link-muted",            # a link muted on one side only (or a muted link on one side only)
    "link-invalid",          # a link Blender holds invalid on one side only
    "link-order",            # the links of a multi-input in another order
    "group-tree",            # a group node calls another group
    "interface-missing",     # an interface socket or panel of the original is not in the rebuilt tree
    "interface-extra",       # an interface item of the rebuilt tree is not in the original
    "interface",             # a property of an interface socket or panel
    "items-lost",            # a collection of a node (zone, capture, bake, menu items…) has fewer items
    "items-extra",           # … more items
    "setting-lost",          # a node property differs, the rebuilt one being a new node's
    "setting-changed",       # a node property differs otherwise
    "default-lost",          # an unlinked input's value differs, the rebuilt one being a new node's
    "default-drift",         # an unlinked input's value differs otherwise
    "output-value",          # a value a node holds in its output (Value, RGB, Normal) differs
    "socket",                # another property of a socket (enabled, link_limit, pin_gizmo…)
    "socket-count",          # a node has another number of sockets
    "tree-setting",          # a property of the tree itself (is_modifier, description…)
    "tree-asset",            # its asset data (catalog, tags, description…)
    "tree-animation",        # its drivers and animation, as far as their presence
    "float-below-1e-6",      # a float (setting, default, interface) differs by 1e-6 or less
    "default-unavailable",   # the value of an input that its node does not show (unavailable) differs
    "link-unavailable",      # a link into or out of a socket its node does not show (unavailable),
                             # which Blender does not follow, on one side only
    "socket-hide-value",     # hide_value of a socket
    "socket-hide",           # hide of a socket
    "socket-identifier",     # the identifier of a socket of a node that has no interface
    "item-identifier",       # the identifier of an item of a node (index switch, menu, capture…)
    "interface-identifier",  # the identifier of an interface item
    "idprop",                # a custom property
    "presentation",          # presentation:<what>: location, width, color, label, name, select…
)

# Read on every struct and never compared: what RNA says of the struct itself
SKIP = {"rna_type"}
# Constants of the class (bl_idname is the node's type, which matching already holds), the same for
# two nodes of one type
CONSTANTS = {"bl_idname", "bl_label", "bl_description", "bl_icon", "bl_static_type", "bl_width_default",
             "bl_width_min", "bl_width_max", "bl_height_default", "bl_height_min", "bl_height_max",
             "bl_subtype_label", "bl_socket_idname", "bl_use_group_interface"}
# Of a node: what the editor shows and evaluation never reads
NODE_PRESENTATION = {"location", "location_absolute", "width", "height", "name", "label", "color",
                     "use_custom_color", "select", "parent", "hide", "show_options", "show_preview",
                     "show_texture", "panel_states",
                     # Read only, the colour of the node's type or of the group it calls
                     "color_tag",
                     # How a String node's text box is scrolled and how many lines it shows
                     "textbox_state"}
# Anywhere below a node or an interface item: which item of a list the editor shows as active, whether
# it is selected or unfolded
NESTED_PRESENTATION = {"select", "show_expanded", "active_index", "active_item", "active_input_index",
                       "active_output_index", "active_generation_index", "active_main_index", "active_tag"}
# Of a node, not compared, each for its reason
NODE_FILTERED = {
    # The size the editor drew it at: 0 in the background, and only drawing sets it
    "dimensions",
    # Made by Blender from the node's type and sockets when it is muted; `mute` is compared
    "internal_links",
    # The sockets and the links are compared on their own
    "inputs", "outputs",
}
# Of a socket, not compared, each for its reason
SOCKET_FILTERED = {
    # Its node: the socket is compared as a socket of that node
    "node",
    # Whether it is linked: the links are compared on their own
    "is_linked",
    # What Blender infers when it updates the tree (the shape of a field, an inferred structure, the
    # icon, a socket the evaluation would not use): not stored, made again from the rest
    "display_shape", "inferred_structure_type", "is_icon_visible", "is_inactive",
    # The socket's label, read only, made from the node's or the interface's
    "label",
}
SOCKET_KINDS = {"hide": "socket-hide", "hide_value": "socket-hide-value", "identifier": "socket-identifier"}
# Of an interface item, not compared, each for its reason
INTERFACE_FILTERED = {
    # Its place: the items are compared in order, with the path of the panel holding them
    "index", "position", "parent",
    # A panel's items are compared as items of the interface, each with its panel's path
    "interface_items",
}
INTERFACE_IDENTIFIERS = {"identifier", "persistent_uid"}
# Of the tree as an ID, not compared, each for its reason
TREE_FILTERED = {
    # What any ID has that is not its own: runtime state, users, its file
    "name_full", "id_type", "session_uid", "is_evaluated", "original", "users", "use_extra_user",
    "is_embedded_data", "is_linked_packed", "is_missing", "is_runtime_data", "is_editable", "tag",
    "is_library_indirect", "library", "library_weak_reference", "override_library", "preview",
    # A hash of the whole ID: the rest says what it hashes
    "deep_hash",
    # The tree's type, which is its bl_idname: matched
    "type",
    # Compared on their own
    "nodes", "links", "interface", "asset_data", "animation_data",
    # The add-on's own pointer to the text it was built from: the builder's bookkeeping
    "base_node_text",
}
TREE_PRESENTATION = {"view_center", "annotation", "default_group_node_width", "color_tag"}
# Custom properties the add-on itself writes (base_node_line, base_node_module…): the builder's
# bookkeeping, not part of the tree it rebuilds
OWN_IDPROPS = "base_node_"
# The nodes that hold a value in an output (the text writes it); another node's output default is
# never read, and is not compared
VALUE_OUTPUTS = {"ShaderNodeValue", "ShaderNodeRGB", "ShaderNodeNormal", "CompositorNodeValue",
                 "CompositorNodeRGB", "CompositorNodeNormal"}
# The kinds of a flattened node's values that say what it does: two nodes alike in these are one
# node twice (a merge)
MEANINGFUL = {"setting", "default", "output-value", "items", "group-tree", "socket-count", "socket"}
# Out of the graph: a frame holds nodes, a reroute passes a link on
FRAME, REROUTE, GROUP_INPUT = "NodeFrame", "NodeReroute", "NodeGroupInput"
INTERFACE_NODES = {GROUP_INPUT, "NodeGroupOutput"}
NOT_IN_GRAPH = {FRAME, REROUTE}
# Below this, absolutely or relatively, a float that differs is `float-below-1e-6`
EPSILON = 1e-6
DEPTH = 6  # how deep a struct is walked below a node (a curve mapping's curves' points: 3)


@dataclass(frozen=True)
class Difference:
    cls: str
    tree: str
    node: str = ""
    node_type: str = ""
    prop: str = ""
    a: object = None
    b: object = None

    def __str__(self):
        where = " ".join(x for x in (self.tree, self.node, self.prop) if x)
        return f"[{self.cls}] {where}: {self.a!r} -> {self.b!r}"


def severity(cls):
    """The rank of a class in CLASSES, `presentation:*` last."""
    return CLASSES.index("presentation" if cls.startswith("presentation") else cls)


# --- Values -----------------------------------------------------------------------------------

class Ref:
    """A value that points to a node, a socket or an interface item of its own tree: equal when it
    points to the counterpart."""

    __slots__ = ("kind", "key")

    def __init__(self, kind, key):
        self.kind, self.key = kind, key

    def __repr__(self):
        return f"<{self.kind} {self.key}>"


def floats(x):
    """True for a float, or a tuple holding one."""
    return isinstance(x, float) or (isinstance(x, tuple) and any(floats(v) for v in x))


def same(a, b):
    """Bit for bit: 0.0 and -0.0 differ, two NaN are the same (the payload of a NaN is no setting)."""
    if isinstance(a, float) and isinstance(b, float):
        return struct.pack("<d", a) == struct.pack("<d", b) or (math.isnan(a) and math.isnan(b))
    if isinstance(a, tuple) and isinstance(b, tuple):
        return len(a) == len(b) and all(same(x, y) for x, y in zip(a, b))
    return type(a) is type(b) and a == b


def close(a, b):
    """Every float of `a` within EPSILON of `b`'s (absolutely or relatively), the rest the same."""
    if isinstance(a, float) and isinstance(b, float):
        if same(a, b):
            return True
        if math.isinf(a) or math.isinf(b) or math.isnan(a) or math.isnan(b):
            return False
        d = abs(a - b)
        return d <= EPSILON or d <= EPSILON * max(abs(a), abs(b))
    if isinstance(a, tuple) and isinstance(b, tuple):
        return len(a) == len(b) and all(close(x, y) for x, y in zip(a, b))
    return same(a, b)


def plain(value):
    """An RNA value as plain Python: tuples of floats, ints, strings."""
    if isinstance(value, (bool, int, float, str)) or value is None:
        return value
    if isinstance(value, (set, frozenset)):
        return tuple(sorted(value))
    try:
        return tuple(plain(v) for v in value)
    except TypeError:
        return repr(value)


def idprop(value):
    """A custom property as plain Python."""
    if hasattr(value, "to_dict"):
        return repr(sorted(value.to_dict().items()))
    if hasattr(value, "to_list"):
        return plain(value.to_list())
    if isinstance(value, bpy.types.ID):
        return ("ID", type(value).__name__, value.name)
    return plain(value)


# --- RNA walk ---------------------------------------------------------------------------------

_PROPS = {}


def props(s):
    """(identifier, type, is_array, is_enum_flag) of each property of the struct, cached by type."""
    rna = s.bl_rna
    found = _PROPS.get(rna.identifier)
    if found is None:
        found = _PROPS[rna.identifier] = [
            (p.identifier, p.type, getattr(p, "is_array", False), getattr(p, "is_enum_flag", False))
            for p in rna.properties if p.identifier not in SKIP]
    return found


class Side:
    """One tree as the comparator sees it: its graph without frames and reroutes, its flattened nodes."""

    def __init__(self, tree, name):
        self.tree, self.name = tree, name
        self.nodes = [n for n in tree.nodes if n.bl_idname not in NOT_IN_GRAPH]
        self.group_inputs = [n for n in self.nodes if n.bl_idname == GROUP_INPUT]
        # Every Group Input is one node of the graph: they all give the interface
        self.keys = {}
        for n in self.nodes:
            self.keys[n.as_pointer()] = "GI" if n.bl_idname == GROUP_INPUT else n.as_pointer()
        self.graph_nodes = list(dict.fromkeys(self.keys.values()))
        self.node_of = {}
        for n in self.nodes:
            self.node_of.setdefault(self.keys[n.as_pointer()], n)
        self.index = {}  # socket pointer -> (node pointer, is_output, index)
        for n in tree.nodes:
            for side, sockets in ((False, n.inputs), (True, n.outputs)):
                for i, s in enumerate(sockets):
                    self.index[s.as_pointer()] = (n.as_pointer(), side, i)
        self.links = self._links()
        self.ins, self.outs = {k: [] for k in self.graph_nodes}, {k: [] for k in self.graph_nodes}
        for l in self.links:
            self.outs[l["src"]].append(l)
            self.ins[l["dst"]].append(l)
        # An input fed by a valid link that is not muted: its default value is not read
        self.fed = {l["dst_socket"] for l in self.links if l["valid"] and not l["muted"]}

    def _links(self):
        """The links between nodes of the graph, through reroutes: a link into a reroute goes on to
        where the reroute's links go, muted if one of them is."""
        into = {}
        for l in self.tree.links:
            into.setdefault(l.to_socket.as_pointer(), []).append(l)
        found = []
        for l in self.tree.links:
            if l.to_node.bl_idname == REROUTE:
                continue
            src, muted, valid = l, l.is_muted, l.is_valid
            seen = set()
            while src is not None and src.from_node.bl_idname == REROUTE:
                rr = src.from_node
                if rr.as_pointer() in seen:
                    src = None
                    break
                seen.add(rr.as_pointer())
                feeding = into.get(rr.inputs[0].as_pointer(), [])
                src = feeding[0] if feeding else None
                if src is not None:
                    muted, valid = muted or src.is_muted, valid and src.is_valid
            if src is None or src.from_node.bl_idname == FRAME:
                continue  # a reroute nothing feeds gives nothing
            _n, _o, si = self.index[src.from_socket.as_pointer()]
            _n, _o, di = self.index[l.to_socket.as_pointer()]
            found.append({"src": self.keys[src.from_node.as_pointer()], "si": si,
                          "dst": self.keys[l.to_node.as_pointer()], "di": di,
                          "dst_socket": l.to_socket.as_pointer(), "multi": l.to_socket.is_multi_input,
                          "muted": muted, "valid": valid, "sort": l.multi_input_sort_id,
                          "dead": unavailable(src.from_socket) or unavailable(l.to_socket)})
        return found


class Comparator:
    """Compares trees; `name(id)` is the name an ID is known by on both sides (the survey's originals
    are renamed `original <name>`). Nested groups are compared once each, by name."""

    def __init__(self, name=None, recurse=True):
        self.name = name or (lambda id: id.name)
        self.recurse = recurse
        self.seen = set()
        self.queue = []
        self.fresh_trees = {}
        self.fresh_nodes = {}

    def close(self):
        for t in self.fresh_trees.values():
            bpy.data.node_groups.remove(t)
        self.fresh_trees.clear()
        self.fresh_nodes.clear()

    # A new node of a type, flattened: whether a value that differs is a new node's
    def fresh(self, tree, bl_idname):
        k = (tree.bl_idname, bl_idname)
        if k not in self.fresh_nodes:
            t = self.fresh_trees.get(tree.bl_idname)
            if t is None:
                t = self.fresh_trees[tree.bl_idname] = bpy.data.node_groups.new(".tree_compare fresh",
                                                                                tree.bl_idname)
            try:
                n = t.nodes.new(bl_idname)
                side = Side(t, "")
                self.fresh_nodes[k] = self.flatten_node(n, side)
                t.nodes.remove(n)
            except RuntimeError:
                self.fresh_nodes[k] = {}
        return self.fresh_nodes[k]

    def ref_id(self, value):
        if isinstance(value, bpy.types.VectorFont) and value.filepath == "<builtin>":
            # Blender's own font, under whatever name the file gives its copy (Bfont Regular.001
            # once a library brought one): the same font
            return ("ID", "VectorFont", "<builtin>", None)
        return ("ID", type(value).__name__, self.name(value),
                value.library.filepath if value.library is not None else None)

    def value(self, v, side):
        """A pointer as a comparable value: an ID by its type and name, a node, socket or
        interface item of the tree as a Ref; None for a struct to walk."""
        if v is None:
            return None, None
        if isinstance(v, bpy.types.ID):
            return self.ref_id(v), v
        if isinstance(v, bpy.types.Node):
            return Ref("node", v.as_pointer()), None
        if isinstance(v, bpy.types.NodeSocket):
            return Ref("socket", side.index.get(v.as_pointer()) if side else None), None
        if isinstance(v, bpy.types.NodeTreeInterfaceItem):
            return ("interface item", item_path(v)), None
        return False, None

    def walk(self, s, path, out, kind, side, depth, presentation=()):
        """Flatten the struct's properties into out[path] = (kind, value)."""
        for ident, ptype, is_array, flag in props(s):
            if ident in CONSTANTS:
                continue
            sub = f"{path}.{ident}" if path else ident
            k = "presentation:" + ident if ident in presentation or ident in NESTED_PRESENTATION else kind
            if ident == "color" and s.bl_rna.properties[ident].is_readonly:
                k = "presentation:item-color"  # an item's colour, read only: that of its type
            try:
                v = getattr(s, ident)
            except Exception:  # a property RNA lists and refuses to give in this state
                continue
            if ptype == "POINTER":
                val, idv = self.value(v, side)
                if val is False:
                    if depth < DEPTH:
                        self.walk(v, sub, out, k, side, depth + 1)
                    continue
                out[sub] = (k, val)
            elif ptype == "COLLECTION":
                items = list(v)
                out[sub + "#len"] = (k, len(items))
                if depth < DEPTH:
                    for i, item in enumerate(items):
                        val, _idv = self.value(item, side)
                        if val is False:
                            self.walk(item, f"{sub}[{i}]", out, k, side, depth + 1)
                        else:
                            out[f"{sub}[{i}]"] = (k, val)
            else:
                out[sub] = (k, plain(v))

    def flatten_node(self, n, side):
        out = {}
        self.walk_node(n, out, side)
        return out

    def walk_node(self, n, out, side):
        for ident, ptype, is_array, flag in props(n):
            if ident in NODE_FILTERED or ident in CONSTANTS:
                continue
            kind = "presentation:" + ident if ident in NODE_PRESENTATION | NESTED_PRESENTATION else "setting"
            if ident == "active_item":
                continue  # the item the editor shows as active, which active_index says
            if ident == "parent":
                p = n.parent
                out["parent"] = (kind, p.label or p.name if p is not None else None)
                continue
            if ident == "panel_states":
                out["panel_states"] = (kind, tuple(plain(getattr(p, "is_collapsed", None))
                                                   for p in n.panel_states))
                continue
            try:
                v = getattr(n, ident)
            except Exception:
                continue
            if ptype == "POINTER":
                val, idv = self.value(v, side)
                if val is False:
                    self.walk(v, ident, out, kind, side, 1)
                    continue
                if isinstance(idv, bpy.types.NodeTree):
                    kind = "group-tree"
                out[ident] = (kind, val)
            elif ptype == "COLLECTION":
                items = list(v)
                out[ident + "#len"] = ("items", len(items))
                for i, item in enumerate(items):
                    self.walk(item, f"{ident}[{i}]", out, kind, side, 1)
                    # A counter Blender gives each item, from which its sockets' identifiers are made
                    if f"{ident}[{i}].identifier" in out:
                        out[f"{ident}[{i}].identifier"] = ("item-identifier", out[f"{ident}[{i}].identifier"][1])
            else:
                out[ident] = (kind, plain(v))
        # Custom properties, but the builder's own
        for key in n.keys():
            if not key.startswith(OWN_IDPROPS):
                out[f"[{key!r}]"] = ("idprop", idprop(n[key]))
        for io, sockets in (("inputs", n.inputs), ("outputs", n.outputs)):
            out[f"{io}#len"] = ("socket-count", len(sockets))
            for i, s in enumerate(sockets):
                self.walk_socket(n, s, f"{io}[{i}]", io == "outputs", out, side)

    def walk_socket(self, n, s, path, output, out, side):
        for ident, ptype, is_array, flag in props(s):
            if ident in SOCKET_FILTERED or ident in CONSTANTS:
                continue
            sub = f"{path}.{ident}"
            try:
                v = getattr(s, ident)
            except Exception:
                continue
            if ident == "default_value":
                if output:
                    if n.bl_idname not in VALUE_OUTPUTS:
                        continue  # never read: see VALUE_OUTPUTS
                    kind = "output-value"
                elif s.as_pointer() in side.fed:
                    continue  # a linked input's value is not read
                elif unavailable(s):
                    kind = "default-unavailable"
                else:
                    kind = "default"
            elif ident in ("select", "show_expanded"):
                kind = "presentation:socket-" + ident
            elif ident == "identifier" and (n.bl_idname in INTERFACE_NODES or hasattr(n, "node_tree")):
                continue  # made from the interface's identifiers, compared as `interface-identifier`
            else:
                kind = SOCKET_KINDS.get(ident, "socket")
            if ptype == "POINTER":
                val, _idv = self.value(v, side)
                if val is False:
                    self.walk(v, sub, out, kind, side, 2)
                    continue
                out[sub] = (kind, val)
            elif ptype == "COLLECTION":
                out[sub + "#len"] = (kind, len(v))
            else:
                out[sub] = (kind, plain(v))
        # A socket holds no custom property

    # --- Matching ---------------------------------------------------------------------------

    def colours(self, a, b):
        """[{(side, key): colour}] for each level of the refinement, on both trees at once."""
        palette = {}

        def intern(x):
            return palette.setdefault(x, len(palette))

        def label(side, k):
            n = side.node_of[k]
            tree = getattr(n, "node_tree", None)
            return (n.bl_idname, self.name(tree) if tree is not None else None)

        level = {}
        for tag, side in (("a", a), ("b", b)):
            for k in side.graph_nodes:
                level[tag, k] = intern(label(side, k))
        levels = [level]
        for _ in range(64):
            new = {}
            for tag, side in (("a", a), ("b", b)):
                for k in side.graph_nodes:
                    ins = tuple(sorted((l["di"], l["si"], level[tag, l["src"]]) for l in side.ins[k]))
                    outs = tuple(sorted((l["si"], l["di"], level[tag, l["dst"]]) for l in side.outs[k]))
                    new[tag, k] = intern((level[tag, k], ins, outs))
            if len(set(new.values())) == len(set(level.values())):
                break
            level = new
            levels.append(level)
        return levels

    def match(self, a, b):
        """{a key: b key} of the nodes of the graph."""
        levels = self.colours(a, b)
        m, taken = {}, set()

        def free(side_tag, side):
            return [k for k in side.graph_nodes if (k not in m if side_tag == "a" else k not in taken)]

        work = []

        def pair(x, y):
            m[x] = y
            taken.add(y)
            work.append((x, y))

        def groups(level):
            g = {}
            for k in free("a", a):
                g.setdefault(level["a", k], ([], []))[0].append(k)
            for k in free("b", b):
                g.setdefault(level["b", k], ([], []))[1].append(k)
            return g

        def propagate():
            """From each pair newly matched to its neighbours: a node linked through the same sockets
            to the counterpart, of the same type, the only one."""
            while work:
                x, y = work.pop()
                for mine, theirs, far in ((a.outs[x], b.outs[y], "dst"), (a.ins[x], b.ins[y], "src")):
                    for l in mine:
                        u = l[far]
                        if u in m:
                            continue
                        cands = list(dict.fromkeys(
                            t[far] for t in theirs if t[far] not in taken
                            and (t["si"], t["di"]) == (l["si"], l["di"])
                            and levels[0]["b", t[far]] == levels[0]["a", u]))
                        if len(cands) == 1:
                            pair(u, cands[0])

        if "GI" in a.graph_nodes and "GI" in b.graph_nodes:
            pair("GI", "GI")
        for level in reversed(levels):
            for xs, ys in groups(level).values():
                if len(xs) == 1 and len(ys) == 1:
                    pair(xs[0], ys[0])
        propagate()
        # Nodes no colour tells apart (two symmetric branches): one pair at a time, the most alike,
        # and its neighbours from it, so that a branch is matched with one branch
        for level in reversed(levels):
            for xs, ys in groups(level).values():
                while True:
                    xs = [x for x in xs if x not in m]
                    ys = [y for y in ys if y not in taken]
                    if not xs or len(xs) != len(ys):
                        break
                    x, y = self.closest(a, b, xs, ys)[0]
                    pair(x, y)
                    propagate()
        # At last by type alone: a group node that calls another group is still that group node
        by_type = {}
        for k in free("a", a):
            by_type.setdefault(a.node_of[k].bl_idname, ([], []))[0].append(k)
        for k in free("b", b):
            by_type.setdefault(b.node_of[k].bl_idname, ([], []))[1].append(k)
        for xs, ys in by_type.values():
            for x, y in self.closest(a, b, xs, ys):
                pair(x, y)
        return m

    def closest(self, a, b, xs, ys):
        """Pairs of the nodes `xs` of a and `ys` of b that no link tells apart: the most alike first
        (settings, then what the editor shows, then the place in the tree)."""
        def features(side, k):
            sets, look = set(), set()
            for p, (kind, v) in side.flat[k].items():
                if not isinstance(v, Ref):
                    (look if kind.startswith("presentation") else sets).add((p, repr(v)))
            return sets, look

        if len(xs) * len(ys) > 4096:  # too many to weigh each pair: in the order of the tree
            return list(zip(xs, ys))
        fx = {x: features(a, x) for x in xs}
        fy = {y: features(b, y) for y in ys}
        scores = sorted(((-len(fx[x][0] & fy[y][0]), -len(fx[x][1] & fy[y][1]), abs(i - j), i, j)
                         for i, x in enumerate(xs) for j, y in enumerate(ys)))
        used_x, used_y, found = set(), set(), []
        for *_score, i, j in scores:
            if i in used_x or j in used_y:
                continue
            used_x.add(i)
            used_y.add(j)
            found.append((xs[i], ys[j]))
        return found

    # --- Comparing --------------------------------------------------------------------------

    def compare(self, a_tree, b_tree):
        """The differences of `b_tree` from `a_tree`, then of the nested groups not yet compared."""
        found = self._compare(a_tree, b_tree)
        while self.queue:
            x, y = self.queue.pop(0)
            found += self._compare(x, y)
        return found

    def _compare(self, a_tree, b_tree):
        self.seen.add((a_tree.as_pointer(), b_tree.as_pointer()))
        tname = self.name(a_tree)
        out = []

        def diff(cls, node=None, prop="", va=None, vb=None):
            out.append(Difference(cls, tname, node_label(node) if node is not None else "",
                                  node.bl_idname if node is not None else "", prop, va, vb))

        self.tree_level(a_tree, b_tree, diff)
        self.interface(a_tree, b_tree, diff)
        sides = []
        for t in (a_tree, b_tree):
            side = Side(t, self.name(t))
            side.flat = {k: self.flatten_node(side.node_of[k], side) for k in side.graph_nodes}
            sides.append(side)
        a, b = sides
        m = self.match(a, b)
        inverse = {y: x for x, y in m.items()}
        # Refs to nodes are equal when they point to counterparts: by the node's key
        ref_a = {n.as_pointer(): a.keys[n.as_pointer()] for n in a.nodes}
        ref_b = {n.as_pointer(): b.keys[n.as_pointer()] for n in b.nodes}

        def counterpart(ref_value, side_ref):
            if ref_value.kind == "node":
                k = side_ref.get(ref_value.key)
                return ("node", m.get(k, ("unmatched", k)) if side_ref is ref_a else k)
            node, out_, i = ref_value.key or (None, None, None)
            k = side_ref.get(node)
            return ("socket", m.get(k, ("unmatched", k)) if side_ref is ref_a else k, out_, i)

        for x, y in m.items():
            na, nb = a.node_of[x], b.node_of[y]
            fa, fb = a.flat[x], b.flat[y]
            fresh = None
            # A collection (items, sockets) whose number differs: said once by its number, with the
            # items of both sides, rather than item by item in places that no longer match
            uneven = {p[:-4] + "[" for p in fa.keys() & fb.keys() if p.endswith("#len") and fa[p][1] != fb[p][1]}
            items_uneven = any(q not in ("inputs[", "outputs[") for q in uneven)
            for p in sorted(fa.keys() | fb.keys()):
                ka, va = fa.get(p, (None, None))
                kb, vb = fb.get(p, (None, None))
                if any(p.startswith(q) for q in uneven):
                    continue
                if p.endswith("#len") and p[:-4] + "[" in uneven:
                    if (ka or kb) == "socket-count" and items_uneven:
                        continue  # the sockets of the items, which their number says
                    if (ka or kb) == "socket-count":
                        diff("socket-count", na, p, va, vb)
                    elif (ka or kb).startswith("presentation"):
                        diff(ka or kb, na, p, va, vb)
                    else:
                        diff("items-lost" if (va or 0) > (vb or 0) else "items-extra", na, p,
                             summary(fa, p[:-4]), summary(fb, p[:-4]))
                    continue
                if p in fa and p in fb:
                    if isinstance(va, Ref) or isinstance(vb, Ref):
                        if not (isinstance(va, Ref) and isinstance(vb, Ref)) \
                                or counterpart(va, ref_a) != counterpart(vb, ref_b):
                            diff(ka if ka != "setting" else "setting-changed", na, p, va, vb)
                        continue
                    if same(va, vb):
                        continue
                    kind = ka if ka == kb else kb if ka.startswith("default") else ka
                    if kind.startswith("presentation"):
                        diff(kind, na, p, va, vb)
                        continue
                    if floats(va) and floats(vb) and close(va, vb):
                        diff("float-below-1e-6", na, p, va, vb)
                        continue
                    if kind in ("setting", "default"):
                        if fresh is None:
                            fresh = self.fresh(b_tree, nb.bl_idname)
                        lost = p in fresh and same(fresh[p][1], vb)
                        kind = {"setting": ("setting-lost", "setting-changed"),
                                "default": ("default-lost", "default-drift")}[kind][0 if lost else 1]
                    diff(kind, na, p, va, vb)
                else:
                    k = ka or kb
                    if k.startswith("default") and (ka is None) != (kb is None):
                        # A default read on one side only: the input is linked on the other, which
                        # the links say
                        continue
                    diff(k if not k.startswith("setting") else "setting-changed", na, p, va, vb)
            if self.recurse:
                ta, tb = getattr(na, "node_tree", None), getattr(nb, "node_tree", None)
                if ta is not None and tb is not None and self.name(ta) == self.name(tb) \
                        and (ta.as_pointer(), tb.as_pointer()) not in self.seen:
                    self.seen.add((ta.as_pointer(), tb.as_pointer()))
                    self.queue.append((ta, tb))

        # Nodes with no counterpart: merged into a node of the same settings feeding the same nodes,
        # else missing (extra)
        merged = {}
        for tag, side, other, mm, cls_one, cls_many in (("a", a, b, m, "node-missing", "node-merged"),
                                                        ("b", b, a, inverse, "node-extra", "node-split")):
            matched_here = set(mm)
            for k in side.graph_nodes:
                if k in matched_here:
                    continue
                n = side.node_of[k]
                into = self.twin(side, other, k, mm)
                if k == "GI" and not side.outs[k]:
                    # A Group Input nothing is linked from gives nothing: it is only drawn
                    diff("presentation:group-input", n, "count", len(a.group_inputs), len(b.group_inputs))
                elif into is not None:
                    merged[(tag, k)] = into
                    diff(cls_many, n, "", node_label(n), node_label(other.node_of[mm[into]]))
                else:
                    diff(cls_one, n, "", node_label(n) if tag == "a" else None,
                         None if tag == "a" else node_label(n))
        # Several Group Input nodes are one of the graph: their number tells a merge. One nothing is
        # linked from gives nothing: it is only drawn
        linked_a = [n for n in a.group_inputs if any(o.is_linked for o in n.outputs)]
        linked_b = [n for n in b.group_inputs if any(o.is_linked for o in n.outputs)]
        ga, gb = len(linked_a), len(linked_b)
        if ga > gb and gb:
            diff("node-merged", linked_a[0], "count", ga, gb)
        elif gb > ga and ga:
            diff("node-split", linked_b[0], "count", ga, gb)
        if len(a.group_inputs) - ga != len(b.group_inputs) - gb and ga and gb:
            diff("presentation:group-input", a.group_inputs[0], "unlinked count",
                 len(a.group_inputs) - ga, len(b.group_inputs) - gb)
        ga, gb = len(a.group_inputs), len(b.group_inputs)
        for x in range(min(ga, gb)):
            if x == 0:
                continue  # the first one is compared as the Group Input of the graph
            na, nb = a.group_inputs[x], b.group_inputs[x]
            fa, fb = self.flatten_node(na, a), self.flatten_node(nb, b)
            for p in sorted(fa.keys() & fb.keys()):
                if not same(fa[p][1], fb[p][1]) and not isinstance(fa[p][1], Ref):
                    diff(fa[p][0] if fa[p][0] != "setting" else "setting-changed", na, p, fa[p][1], fb[p][1])

        self.links(a, b, m, merged, diff)
        # Frames and reroutes: how many, by type
        for t in (FRAME, REROUTE):
            ca = sum(1 for n in a_tree.nodes if n.bl_idname == t)
            cb = sum(1 for n in b_tree.nodes if n.bl_idname == t)
            if ca != cb:
                out.append(Difference("presentation:" + ("frame" if t == FRAME else "reroute"), tname, "", t,
                                      "count", ca, cb))
        return out

    def twin(self, side, other, k, mm):
        """The node of `other` that `k`, unmatched, is merged into: one of the same type and settings,
        matched, whose counterpart feeds the counterparts of the nodes `k` feeds."""
        n = side.node_of[k]
        flat = side.flat[k]
        # What it does, not how it shows (hidden sockets) nor what Blender numbered
        settings = {p: v for p, (kind, v) in flat.items()
                    if kind in MEANINGFUL and not isinstance(v, Ref)}
        for j in side.graph_nodes:
            if j == k or j not in mm or side.node_of[j].bl_idname != n.bl_idname:
                continue
            fj = side.flat[j]
            if any(p not in fj or not same(fj[p][1], v) for p, v in settings.items()):
                continue
            mine = {(l["si"], mm.get(l["dst"]), l["di"]) for l in side.outs[k]}
            theirs = {(l["si"], l["dst"], l["di"]) for l in other.outs[mm[j]]}
            if mine and mine <= theirs:
                return j
        return None

    def links(self, a, b, m, merged, diff):
        def keyed(side, mapping):
            found = {}
            for l in side.links:
                s, d = mapping(l["src"]), mapping(l["dst"])
                if s is None or d is None:
                    continue  # a node with no counterpart: said as such
                found.setdefault((s, l["si"], d, l["di"]), []).append(l)
            return found

        def map_a(k):
            if k in m:
                return m[k]
            if ("a", k) in merged:
                return m[merged[("a", k)]]
            return None

        inverse = {y: x for x, y in m.items()}

        def map_b(k):
            if k in inverse:
                return k
            if ("b", k) in merged:
                return merged[("b", k)]
            return None

        la, lb = keyed(a, map_a), keyed(b, map_b)

        def end(side, k, i, output):
            n = side.node_of[k]
            sockets = n.outputs if output else n.inputs
            return f"{node_label(n)}.{'outputs' if output else 'inputs'}[{i}]" \
                   + (f"({sockets[i].identifier})" if i < len(sockets) else "")

        def text(side, l):
            return f"{end(side, l['src'], l['si'], True)} -> {end(side, l['dst'], l['di'], False)}"

        for key in la.keys() - lb.keys():
            for l in la[key]:
                # A muted link lost: muted on one side only
                diff("link-unavailable" if l["dead"] else "link-muted" if l["muted"] else "link-missing",
                     a.node_of[l["dst"]], f"inputs[{l['di']}]", text(a, l), None)
        for key in lb.keys() - la.keys():
            for l in lb[key]:
                diff("link-unavailable" if l["dead"] else "link-muted" if l["muted"] else "link-extra",
                     b.node_of[l["dst"]], f"inputs[{l['di']}]", None, text(b, l))
        for key in la.keys() & lb.keys():
            x, y = la[key][0], lb[key][0]
            if x["muted"] != y["muted"]:
                diff("link-muted", a.node_of[x["dst"]], f"inputs[{x['di']}]", x["muted"], y["muted"])
            if x["valid"] != y["valid"]:
                diff("link-invalid", a.node_of[x["dst"]], f"inputs[{x['di']}]", x["valid"], y["valid"])
        # Multi-inputs: Blender joins their links from the highest sort id down
        order_a, order_b = {}, {}
        for side, mapping, order in ((a, map_a, order_a), (b, map_b, order_b)):
            for l in side.links:
                if not l["multi"]:
                    continue
                s, d = mapping(l["src"]), mapping(l["dst"])
                if s is None or d is None:
                    continue
                order.setdefault((d, l["di"]), []).append((-l["sort"], (s, l["si"])))
        for key in order_a.keys() & order_b.keys():
            xs = [v for _s, v in sorted(order_a[key])]
            ys = [v for _s, v in sorted(order_b[key])]
            if collections.Counter(xs) == collections.Counter(ys) and xs != ys:
                diff("link-order", a.node_of[inverse[key[0]]], f"inputs[{key[1]}]",
                     [i for i, _ in enumerate(xs)], [xs.index(v) for v in ys])

    def tree_level(self, a, b, diff):
        fa, fb = {}, {}
        for t, f in ((a, fa), (b, fb)):
            for ident, ptype, is_array, flag in props(t):
                if ident in TREE_FILTERED or ident in CONSTANTS:
                    continue
                kind = "presentation:tree-" + ident if ident in TREE_PRESENTATION else "tree-setting"
                v = getattr(t, ident)
                if ptype == "POINTER":
                    val, _ = self.value(v, None)
                    f[ident] = (kind, val if val is not False else repr(v))
                elif ptype == "COLLECTION":
                    f[ident] = (kind, len(v))
                else:
                    f[ident] = (kind, self.name(t) if ident == "name" else plain(v))
            f["asset_data"] = ("tree-asset", t.asset_data is not None)
            if t.asset_data is not None:
                self.walk(t.asset_data, "asset_data", f, "tree-asset", None, 1)
            ad = t.animation_data
            if ad is not None and ad.action is None and not len(ad.drivers) and not len(ad.nla_tracks):
                ad = None  # animation data that animates nothing: as none
            f["animation_data"] = ("tree-animation", None if ad is None else (
                ad.action.name if ad.action else None, len(ad.drivers),
                tuple(sorted(d.data_path for d in ad.drivers))))
            for key in t.keys():
                if not key.startswith(OWN_IDPROPS):
                    f[f"[{key!r}]"] = ("idprop", idprop(t[key]))
        for p in sorted(fa.keys() | fb.keys()):
            ka, va = fa.get(p, (None, None))
            kb, vb = fb.get(p, (None, None))
            if p in fa and p in fb and same(va, vb):
                continue
            if p.startswith("asset_data.") and not same(fa["asset_data"][1], fb["asset_data"][1]):
                continue  # an asset on one side only: said once
            diff(ka or kb, None, p, va, vb)

    def interface(self, a, b, diff):
        """The interface items in order, aligned by (kind, side, name, type), each item's properties."""
        import difflib

        def items(t):
            return list(t.interface.items_tree)

        def key(i):
            return (i.item_type, getattr(i, "in_out", None), i.name, getattr(i, "socket_type", None),
                    item_path(i.parent))

        ia, ib = items(a), items(b)
        sm = difflib.SequenceMatcher(a=[key(i) for i in ia], b=[key(i) for i in ib], autojunk=False)
        for op, a0, a1, b0, b1 in sm.get_opcodes():
            if op == "equal":
                for x, y in zip(ia[a0:a1], ib[b0:b1]):
                    self.interface_item(x, y, diff)
                continue
            # A changed item of the same place and kind: its properties; else missing and extra
            xs, ys = ia[a0:a1], ib[b0:b1]
            if op == "replace" and len(xs) == len(ys):
                for x, y in zip(xs, ys):
                    if x.item_type == y.item_type and getattr(x, "in_out", None) == getattr(y, "in_out", None):
                        # Its name and type are said with its other properties; its panel here
                        if key(x)[-1] != key(y)[-1]:
                            diff("interface", None, f"{item_label(x)}.panel", key(x)[-1], key(y)[-1])
                        self.interface_item(x, y, diff)
                    else:
                        diff("interface-missing", None, item_label(x), item_label(x), None)
                        diff("interface-extra", None, item_label(y), None, item_label(y))
                continue
            for x in xs:
                diff("interface-missing", None, item_label(x), item_label(x), None)
            for y in ys:
                diff("interface-extra", None, item_label(y), None, item_label(y))

    def interface_item(self, x, y, diff):
        fx, fy = {}, {}
        for item, f in ((x, fx), (y, fy)):
            for ident, ptype, is_array, flag in props(item):
                if ident in INTERFACE_FILTERED or ident in CONSTANTS:
                    continue
                kind = ("interface-identifier" if ident in INTERFACE_IDENTIFIERS else
                        "presentation:interface-" + ident if ident in NESTED_PRESENTATION else "interface")
                try:
                    v = getattr(item, ident)
                except Exception:
                    continue
                if ptype == "POINTER":
                    val, _ = self.value(v, None)
                    if val is False:
                        self.walk(v, ident, f, kind, None, 1)
                    else:
                        f[ident] = (kind, val)
                elif ptype == "COLLECTION":
                    f[ident + "#len"] = (kind, len(v))
                else:
                    f[ident] = (kind, plain(v))
        for p in sorted(fx.keys() | fy.keys()):
            kx, vx = fx.get(p, (None, None))
            ky, vy = fy.get(p, (None, None))
            if p in fx and p in fy and same(vx, vy):
                continue
            kind = kx or ky
            if kind == "interface" and p in fx and p in fy and floats(vx) and floats(vy) and close(vx, vy):
                kind = "float-below-1e-6"
            diff(kind, None, f"{item_label(x)}.{p}", vx, vy)


def unavailable(socket):
    """A socket its node does not show in its present mode (the B of a Math node that adds…)."""
    return not socket.enabled or socket.is_unavailable


def summary(flat, collection):
    """The items of a collection of a flattened node: [{property: value}]."""
    items = {}
    pattern = re.compile(re.escape(collection) + r"\[(\d+)\]\.(.+)")
    for p, (_kind, v) in flat.items():
        found = pattern.fullmatch(p)
        if found:
            items.setdefault(int(found.group(1)), {})[found.group(2)] = v
    return [items[i] for i in sorted(items)]


def item_path(item):
    """The names of an interface item's panels and its own, outermost first."""
    names = []
    while item is not None and getattr(item, "parent", None) is not None:
        names.insert(0, item.name)
        item = item.parent
    return tuple(names)


def item_label(item):
    side = getattr(item, "in_out", None)
    return f"interface {item.item_type.lower()}{' ' + side.lower() if side else ''} {'/'.join(item_path(item)) or item.name!r}"


def node_label(n):
    return f"{n.bl_idname} {n.name!r}"


def compare_trees(a, b, name=None, recurse=True):
    """The differences of tree `b` from tree `a` (and of the groups their group nodes call, once each,
    when `recurse`), most serious first. `name(id)` is the name an ID is known by on both sides."""
    c = Comparator(name, recurse)
    try:
        found = c.compare(a, b)
    finally:
        c.close()
    return sorted(found, key=lambda d: severity(d.cls))
