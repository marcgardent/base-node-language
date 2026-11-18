"""The node schema, read from Blender rather than written by hand.

Every node type is created once in a hidden scratch tree to list its
properties. Sockets depend on properties (Math SINE has one input), so they
are read on demand with the properties set, and memoized.
"""

import bpy

from ..lang.schema import (ITEM_NODES, ITEM_TYPES, MAPPING_OPTIONS, RAMP_OPTIONS, TYPES, GroupSpec, NodeSpec, Prop,
                           Socket, interface_keys, key, node_name)

TREE_TYPES = {
    "geometry": "GeometryNodeTree",
    "shader": "ShaderNodeTree",
    "compositor": "CompositorNodeTree",
}

# Stripped from bl_idname to make the former text name; earlier prefixes win a clash of UI names
PREFIXES = ("GeometryNode", "FunctionNode", "ShaderNode", "CompositorNode", "TextureNode", "Node")

# When two nodes of a tree kind have the same UI name, the one its Add menu offers takes it, the other
# keeps its former name. Without an entry here the order of PREFIXES decides: Switch in a compositor
# tree is GeometryNodeSwitch, the one its menu offers, and CompositorNodeSwitch keeps its full bl_idname
MENU = {("compositor", "RGBCurves"): "CompositorNodeCurveRGB"}

# Handled by the builder, purely visual, or paired zones that v0 does not write
SKIP = {
    "NodeGroupInput", "NodeGroupOutput", "NodeReroute", "NodeFrame", "NodeImplicitConversion",
    "NodeUndefined", "NodeCustomGroup", "GeometryNodeGroup", "ShaderNodeGroup", "CompositorNodeGroup",
}
ZONES = ("SimulationInput", "SimulationOutput", "RepeatInput", "RepeatOutput",
         "ForeachGeometryElementInput", "ForeachGeometryElementOutput", "ClosureInput", "ClosureOutput")

SOCKET_TYPES = {
    "VALUE": "Float", "INT": "Int", "BOOLEAN": "Bool", "VECTOR": "Vector", "RGBA": "Color",
    "ROTATION": "Rotation", "MATRIX": "Matrix", "STRING": "String", "MENU": "Menu",
    "GEOMETRY": "Geometry", "SHADER": "Shader", "OBJECT": "Object", "COLLECTION": "Collection",
    "MATERIAL": "Material", "IMAGE": "Image", "TEXTURE": "Texture", "BUNDLE": "Bundle",
    "CLOSURE": "Closure",
}

PROP_KINDS = {"ENUM", "BOOLEAN", "INT", "FLOAT", "STRING"}

# Where the item list of a node stands in its panel: the editor's, not the tree's
UI_PROPS = {"active_index", "active_input_index", "active_output_index"}

# Datablock properties the text writes otherwise: a group node's tree is its call
ID_SKIP = {"node_tree"}

# Node data the text writes in calls of its own: a Color Ramp's stops (Ramp), a curve's points (Curve)
DATA_KINDS = {"ColorRamp": "RAMP", "CurveMapping": "CURVES"}
# The channels of a node's curves, by the end of its bl_idname; a single curve has none
CHANNELS = {"RGBCurve": ("r", "g", "b", "c"), "CurveRGB": ("r", "g", "b", "c"), "VectorCurve": ("x", "y", "z"),
            "HueCorrect": ("h", "s", "v")}
_data = {}  # (version, kind, bl_idname) -> {property: data_value} of a new node


def channels(bl_idname, count):
    """The text names of `count` curves of a node: none for one, r g b c for RGB Curves…"""
    if count == 1:
        return ()
    names = next((v for k, v in CHANNELS.items() if bl_idname.endswith(k) and len(v) == count), None)
    return names or tuple(f"curve{i}" for i in range(count))


def data_value(data):
    """What a ramp or a curve mapping holds, as ir.Node.data has it: see lang.ir.Node.data.
    A ramp's stops in the order of their positions, as Blender evaluates them."""
    if isinstance(data, bpy.types.ColorRamp):
        stops = sorted(((e.position, tuple(e.color)) for e in data.elements), key=lambda s: s[0])
        return {"stops": stops, "options": {o: getattr(data, o) for o in RAMP_OPTIONS}}
    options = {o: tuple(getattr(data, o)) if MAPPING_OPTIONS[o] == "COLOR" else getattr(data, o)
               for o in MAPPING_OPTIONS}
    return {"curves": {i: [(p.location[0], p.location[1], p.handle_type) for p in c.points]
                       for i, c in enumerate(data.curves)}, "options": options}


def rounded(value):
    """A data_value, or a part of it, rounded as Blender's UI shows it: comparable."""
    if isinstance(value, float):
        return round(value, 5)
    if isinstance(value, (list, tuple)):
        return tuple(rounded(v) for v in value)
    if isinstance(value, dict):
        return {k: rounded(v) for k, v in value.items()}
    return value


# Per Blender version and kind: ({text name: NodeSpec}, {bl_idname: NodeSpec}, {former name: text name}),
# and the socket memo
_specs = {}
_sockets = {}


def id_type(prop):
    """The datablock type a node property points to (Image, Object…), else None."""
    if prop.type != "POINTER" or prop.is_readonly:
        return None
    cls = getattr(bpy.types, prop.fixed_type.identifier, None)
    return prop.fixed_type.identifier if isinstance(cls, type) and issubclass(cls, bpy.types.ID) else None


def datablocks(type_name):
    """The bpy.data collection of a datablock type: Image -> bpy.data.images."""
    for p in bpy.types.BlendData.bl_rna.properties:
        if p.type == "COLLECTION" and p.fixed_type.identifier == type_name:
            return getattr(bpy.data, p.identifier)
    return None


def text_name(bl_idname):
    """The name a node had before its UI name: its bl_idname without its prefix, `TexNoise`."""
    for prefix in PREFIXES:
        if bl_idname.startswith(prefix) and len(bl_idname) > len(prefix):
            return bl_idname[len(prefix):]
    return bl_idname


def ui_name(bl_idname):
    """The text name of a node type from its English label (bl_rna.name, never translated), else None.

    A label that starts with a digit (`3D Cursor`) makes no identifier: that node keeps its former name."""
    cls = getattr(bpy.types, bl_idname, None)
    name = node_name(cls.bl_rna.name) if cls is not None else ""
    return name if name[:1].isalpha() else None


def socket_info(sock):
    value = getattr(sock, "default_value", None)
    size = len(value) if hasattr(value, "__len__") and not isinstance(value, str) else 0
    return Socket(sock.name, sock.identifier, SOCKET_TYPES.get(sock.type, sock.type.title()),
                  sock.is_multi_input, size)


def available(sockets):
    return [socket_info(s) for s in sockets if not s.is_unavailable and s.type != "CUSTOM"]


class BlenderSchema:
    """Use as a context manager: the scratch trees are removed on exit."""

    def __init__(self):
        self.version = bpy.app.version
        self.scratch = {}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        bpy.data.batch_remove(list(self.scratch.values()))
        self.scratch.clear()

    def tree(self, kind):
        if kind not in self.scratch:
            self.scratch[kind] = bpy.data.node_groups.new(f".base_node_scratch_{kind}", TREE_TYPES[kind])
        return self.scratch[kind]

    def specs(self, kind):
        key = (self.version, kind)
        if key not in _specs:
            _specs[key] = self.read_specs(kind)
        return _specs[key]

    def read_specs(self, kind):
        tree = self.tree(kind)
        base = {p.identifier for p in bpy.types.Node.bl_rna.properties}
        found = {}
        for idname in sorted(dir(bpy.types)):
            cls = getattr(bpy.types, idname)
            if (idname in SKIP or idname.endswith(ZONES) or not isinstance(cls, type)
                    or not issubclass(cls, bpy.types.Node) or cls is bpy.types.Node):
                continue
            try:
                node = tree.nodes.new(idname)
            except RuntimeError:
                continue  # not available in this tree kind
            props, data = {}, {}
            for p in node.bl_rna.properties:
                if p.type == "POINTER" and p.fixed_type.identifier in DATA_KINDS:
                    data_kind = DATA_KINDS[p.fixed_type.identifier]
                    names = channels(idname, len(getattr(node, p.identifier).curves)) if data_kind == "CURVES" else ()
                    data[p.identifier] = Prop(p.identifier, data_kind, names)
                    continue
                datablock = id_type(p)
                if datablock and p.identifier not in base and p.identifier not in ID_SKIP:
                    props[p.identifier] = Prop(p.identifier, "ID", (), datablock)
                    continue
                if p.identifier in base or p.type not in PROP_KINDS or p.is_readonly or p.identifier in UI_PROPS:
                    continue
                if getattr(p, "is_array", False) or getattr(p, "array_length", 0):
                    continue  # a color or a vector property: not in the text yet
                if p.type == "ENUM" and p.is_enum_flag:
                    continue
                items = tuple(i.identifier for i in p.enum_items) if p.type == "ENUM" else ()
                props[p.identifier] = Prop(p.identifier, p.type, items)
            tree.nodes.remove(node)
            found[idname] = (props, data)

        rank = {p: i for i, p in enumerate(PREFIXES)}

        def prefix_rank(idname):
            return next((rank[p] for p in PREFIXES if idname.startswith(p)), len(PREFIXES))

        ordered = sorted(found, key=prefix_rank)
        former = former_names(ordered)
        wanted = {}  # UI name -> the bl_idnames that read it, the winner first
        for idname in ordered:
            name = ui_name(idname)
            if name is not None:
                wanted.setdefault(name, []).append(idname)
        names = {}
        for name, idnames in wanted.items():
            first = MENU.get((kind, name)) if MENU.get((kind, name)) in idnames else idnames[0]
            names[first] = name
            for idname in idnames:
                if idname != first:
                    names[idname] = former[idname][0]
        for idname in ordered:
            names.setdefault(idname, former[idname][0])
        taken = {}
        for idname in ordered:
            name = names[idname]
            if name in taken:  # a former name kept beside the same UI name elsewhere: never so far
                name = idname
            taken[name] = idname
        specs = {name: NodeSpec(name, idname, *found[idname]) for name, idname in taken.items()}
        by_idname = {s.bl_idname: s for s in specs.values()}
        # What an old text wrote, the full bl_idname too: refused, with the name it is now written by
        renamed = {}
        for idname in ordered:
            for old in (*former[idname], idname):
                if old not in specs and old not in renamed:
                    renamed[old] = by_idname[idname].name
        return specs, by_idname, renamed

    # Schema protocol

    def node(self, kind, name):
        return self.specs(kind)[0].get(name) if kind in TREE_TYPES else None

    def node_of(self, kind, bl_idname):
        """The NodeSpec of a node type of the tree kind, by its bl_idname, else None."""
        return self.specs(kind)[1].get(bl_idname) if kind in TREE_TYPES else None

    def node_names(self, kind):
        return sorted(self.specs(kind)[0]) if kind in TREE_TYPES else []

    def renamed(self, kind):
        return self.specs(kind)[2] if kind in TREE_TYPES else {}

    def sockets(self, kind, spec, props):
        inputs, outputs, _values, _props = self.fresh(kind, spec, props)
        return list(inputs), list(outputs)

    def groups(self, kind):
        """{key: GroupSpec} of the file's node groups of that kind, hidden ones (.name) aside."""
        types = {v: k for k, v in TYPES.items()}
        found = {}
        for tree in bpy.data.node_groups if kind in TREE_TYPES else ():
            if tree.bl_idname != TREE_TYPES[kind] or tree.name.startswith("."):
                continue
            items = [i for i in tree.interface.items_tree if i.item_type == "SOCKET"]
            sig = [tuple((i.name, types.get(i.socket_type, i.socket_type.removeprefix("NodeSocket")))
                         for i in items if i.in_out == io) for io in ("INPUT", "OUTPUT")]
            keys = [tuple(socket_keys(tree, io).values()) for io in ("INPUT", "OUTPUT")]
            spec = GroupSpec(tree.name, *sig, *keys)
            k = key(tree.name)
            if k in found:
                spec = (found[k] if isinstance(found[k], list) else [found[k]]) + [spec]
            found[k] = spec
        return found

    def fresh_data(self, kind, spec):
        """{property: data_value} of the ramps and curves of a new node."""
        key = (self.version, kind, spec.bl_idname)
        if key not in _data:
            fresh = self.tree(kind).nodes.new(spec.bl_idname)
            try:
                _data[key] = {n: data_value(getattr(fresh, n)) for n in spec.data}
            finally:
                self.tree(kind).nodes.remove(fresh)
        return _data[key]

    def defaults(self, kind, spec, props):
        """What a new node holds once `props` are set: ({input identifier: value}, {prop: value})."""
        _inputs, _outputs, values, prop_values = self.fresh(kind, spec, props)
        return values, prop_values

    def fresh(self, kind, spec, props):
        key = (self.version, kind, spec.bl_idname, tuple(sorted(props.items())))
        if key not in _sockets:
            tree = self.tree(kind)
            node = tree.nodes.new(spec.bl_idname)
            try:
                for name, value in props.items():
                    try:
                        setattr(node, name, value)
                    except (TypeError, ValueError, AttributeError):
                        pass  # the builder reports it, with Blender's own message
                values = {s.identifier: snapshot(s) for s in node.inputs}
                prop_values = {p: id_name(getattr(node, p)) for p in spec.props}
                _sockets[key] = (available(node.inputs), available(node.outputs), values, prop_values)
            finally:
                tree.nodes.remove(node)
        return _sockets[key]


def root_panel(tree):
    """The panel around the whole interface, None when it is empty. Blender 5.2 has no
    interface.root_panel, but every item at the top has it as parent."""
    iface = tree.interface
    if hasattr(iface, "root_panel"):
        return iface.root_panel
    return next((i.parent for i in iface.items_tree if i.parent.parent is None), None)


# On a built group: {socket identifier: {"name", "key"}} for the sockets the text named with `as`
ALIASES = "base_node_aliases"


def socket_keys(tree, io):
    """{identifier: text key} of one side of a group's interface, in order: see interface_keys.

    The keys the text gave with `as` stay, as long as the socket keeps its name."""
    types = {v: k for k, v in TYPES.items()}
    items = [i for i in tree.interface.items_tree if i.item_type == "SOCKET" and i.in_out == io]
    stored = tree.get(ALIASES, {})
    given = [stored[i.identifier]["key"] if i.identifier in stored and stored[i.identifier]["name"] == i.name
             else None for i in items]
    keys = interface_keys([(i.name, i.parent.name if i.parent.parent is not None else None,
                            types.get(i.socket_type, i.socket_type.removeprefix("NodeSocket"))) for i in items], given)
    return {i.identifier: k for i, k in zip(items, keys)}


# Settings of a tree as a new one has them: the text writes those that differ, in this order.
# is_modifier is the builder's to decide, unless the text says otherwise
TREE_FLAGS = {"is_modifier": False, "is_tool": False, "is_mode_object": False, "is_mode_edit": False,
              "is_mode_sculpt": False, "is_mode_paint": False, "is_type_mesh": False, "is_type_curve": False,
              "is_type_pointcloud": False, "is_type_grease_pencil": False, "use_wait_for_click": False,
              "show_modifier_manage_panel": True}

# A panel's settings, as a new one has them; its name is written before its brace
PANEL_OPTIONS = {"description": "", "default_closed": False}


# What a new interface input of each socket type holds: the text writes only what differs
INTERFACE_FIELDS = ("default_value", "min_value", "max_value", "default_input")
_fresh_items = {}


def fresh_item(socket_type, tree_type="GeometryNodeTree"):
    """{field: value} of a new group input of `socket_type` in a tree of `tree_type`, fields it has only."""
    if (socket_type, tree_type) not in _fresh_items:
        tree = bpy.data.node_groups.new(".base_node_fresh", tree_type)
        try:
            item = tree.interface.new_socket("x", in_out="INPUT", socket_type=socket_type)
            _fresh_items[(socket_type, tree_type)] = {f: snapshot(item) if f == "default_value" else getattr(item, f)
                                                      for f in INTERFACE_FIELDS if hasattr(item, f)}
        finally:
            bpy.data.node_groups.remove(tree)
    return _fresh_items[(socket_type, tree_type)]


_socket_types = {}


def socket_types(tree_type):
    """The text types an interface socket of a `tree_type` tree may have, in TYPES' order:
    a shader tree has no Geometry, a compositor tree no Shader."""
    if tree_type not in _socket_types:
        tree = bpy.data.node_groups.new(".base_node_fresh", tree_type)
        found = []
        try:
            for text, socket_type in TYPES.items():
                try:
                    tree.interface.new_socket("x", in_out="INPUT", socket_type=socket_type)
                except TypeError:
                    continue
                found.append(text)
        finally:
            bpy.data.node_groups.remove(tree)
        _socket_types[tree_type] = found
    return _socket_types[tree_type]


# Interface settings the text writes otherwise than as options, or that are the editor's
NOT_OPTIONS = {"name", "socket_type", "bl_socket_idname", "default_value", "min_value", "max_value",
               "default_input", "dimensions", "select"}
_fresh_options = {}


def option_names(item):
    """The settings of an interface socket that the text writes as options, in Blender's order.

    An output's `dimensions` is one: an input's is the size of its default, an output has none."""
    return [p.identifier for p in item.bl_rna.properties
            if not p.is_readonly
            and (p.identifier not in NOT_OPTIONS or p.identifier == "dimensions" and item.in_out == "OUTPUT")
            and p.type in ("BOOLEAN", "ENUM", "STRING", "INT", "FLOAT")
            and not getattr(p, "is_array", False) and not (p.type == "ENUM" and p.is_enum_flag)]


def fresh_options(socket_type, in_out, tree_type="GeometryNodeTree"):
    """{option: value} of a new interface socket in a tree of `tree_type`: what the text leaves out.
    A Shader socket only exists in a shader tree."""
    k = (socket_type, in_out, tree_type)
    if k not in _fresh_options:
        tree = bpy.data.node_groups.new(".base_node_fresh", tree_type)
        try:
            item = tree.interface.new_socket("x", in_out=in_out, socket_type=socket_type)
            _fresh_options[k] = {o: getattr(item, o) for o in option_names(item)}
        finally:
            bpy.data.node_groups.remove(tree)
    return _fresh_options[k]


def new_item(node, shape, name, type):
    """Add one item to a node of ITEM_NODES, as `new()` of its collection wants it."""
    items = getattr(node, shape.collection)
    if not shape.named:
        return items.new()
    if not shape.typed:
        return items.new(name)
    if shape.kinds is not None:
        item = items.new(name)
        setattr(item, shape.type_prop, shape.kinds[type])
        return item
    return items.new(ITEM_TYPES[type], name)


def item_option_names(item, shape):
    """The settings of an item that the text writes as its options, in Blender's order."""
    return [p.identifier for p in item.bl_rna.properties
            if not p.is_readonly and p.identifier not in ("name", shape.type_prop)
            and p.type in ("BOOLEAN", "ENUM", "STRING", "INT", "FLOAT")
            and not getattr(p, "is_array", False) and not (p.type == "ENUM" and p.is_enum_flag)]


_fresh_item_options = {}


def fresh_item_options(bl_idname, items, shape=None):
    """[{option: value}] of the (name, type) items made in that order on a new node, as the
    builder makes them: what the text leaves out. Blender sets some from the items before
    (a Bake's Geometry item becomes an attribute holder once a field follows it)."""
    shape = shape or ITEM_NODES[bl_idname]
    key = (bl_idname, shape.collection, tuple(items))
    if key not in _fresh_item_options:
        tree = bpy.data.node_groups.new(".base_node_fresh", "GeometryNodeTree")
        try:
            node = tree.nodes.new(bl_idname)
            getattr(node, shape.collection).clear()
            for name, type in items:
                new_item(node, shape, name, type)
            _fresh_item_options[key] = [{o: getattr(i, o) for o in item_option_names(i, shape)}
                                        for i in getattr(node, shape.collection)]
        finally:
            bpy.data.node_groups.remove(tree)
    return _fresh_item_options[key]
_fresh_values = {}


def fresh_item_value(bl_idname, collection, socket_type):
    """The value the input socket of a new item holds: a closure's output, an evaluation's input."""
    k = (bl_idname, collection, socket_type)
    if k not in _fresh_values:
        tree = bpy.data.node_groups.new(".base_node_fresh", "GeometryNodeTree")
        try:
            node = tree.nodes.new(bl_idname)
            items = getattr(node, collection)
            items.clear()
            items.new(socket_type, "x")
            _fresh_values[k] = snapshot([s for s in node.inputs if s.type != "CUSTOM"][-1])
        finally:
            bpy.data.node_groups.remove(tree)
    return _fresh_values[k]


def id_name(value):
    """A property's value as the text holds it: a datablock by its name."""
    return value.name if isinstance(value, bpy.types.ID) else value


def same_option(name, a, b):
    # Sockets made before Blender 4 say NONE where new ones say DEFAULT
    plain = {"NONE", "DEFAULT"}
    return a == b or name == "subtype" and a in plain and b in plain


def snapshot(sock):
    """A socket's default_value as plain Python: tuples for vectors, names for datablocks."""
    value = getattr(sock, "default_value", None)
    if isinstance(value, bpy.types.ID):
        return value.name
    if hasattr(value, "__len__") and not isinstance(value, str):
        return tuple(value)
    return value


def former_names(ordered):
    """{bl_idname: (its former text name, the other names it was read by)}, `ordered` by PREFIXES.

    The bl_idname without its prefix, or without `Input` too when no other node takes that
    (GeometryNodeInputPosition was Position), or the full bl_idname when another one came first."""
    taken, out = set(), {}
    stripped = {text_name(i) for i in ordered}
    for idname in ordered:
        name = text_name(idname)
        short = name[len("Input"):] if name.startswith("Input") and len(name) > 5 else None
        if short and short not in taken and short not in stripped:
            name = short
        if name in taken:
            name = idname
        taken.add(name)
        out[idname] = (name,) + ((text_name(idname),) if name != text_name(idname) else ())
    return out
