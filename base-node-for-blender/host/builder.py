"""ir.Graph -> node group.

The whole file is first built into scratch trees, so an error leaves the
file as it was. Then each graph is rebuilt in place, in the group of the
same name: interface sockets that did not change keep their identifier,
so modifier settings and the links of other trees calling the group stay.
"""

import json

import bpy

from .. import blender
from ..blender import ir
from ..lang.errors import BnError, Diagnostic
from ..blender.layout import layout
from ..blender.schema import (ITEM_NODES, MATERIAL, SIGNATURE_NODES, TYPES, is_material, key, option_key,
                           signature_items, snake)
from ..blender.typecheck import REPEAT_ITEMS
from . import comments, modules, outputs
from .arrange import arrange_nodes
from .schema import (ALIASES, BUILTIN_FONT, BUILTIN_PATH, DEPRECATION, PANEL_OPTIONS, TREE_FLAGS, TREE_TYPES,
                     BlenderSchema, builtin_font, fresh_item, fresh_options, datablocks, id_type, item_option_names,
                     new_item, root_panel, same_option, socket_keys, socket_types, text_name, ui_name)

DATABLOCKS = {"OBJECT": "objects", "COLLECTION": "collections", "MATERIAL": "materials",
              "IMAGE": "images", "TEXTURE": "textures", "FONT": "fonts",
              "SOUND": "sounds", "SCENE": "scenes", "MASK": "masks", "TEXT": "texts"}

# Item options set after the links: a Viewer's auto_remove drops an item nothing feeds yet
LATE_OPTIONS = {"auto_remove"}

# Source line of each node, for the text and node editors to follow each other
LINE = "base_node_line"

# Set rather than left to Blender, which translates new names when asked to
FIXED_NAMES = {ir.GROUP_INPUT: "Group Input", ir.GROUP_OUTPUT: "Group Output"}
MATERIAL_NAMES = {ir.GROUP_OUTPUT: "Material Output"}

# How the text writes a zone, for an error on its nodes
ZONE_WORDS = {ir.REPEAT_INPUT: "repeat", ir.REPEAT_OUTPUT: "repeat", ir.SIMULATION_INPUT: "simulate",
              ir.SIMULATION_OUTPUT: "simulate", ir.FOREACH_INPUT: "foreach", ir.FOREACH_OUTPUT: "foreach",
              ir.CLOSURE_INPUT: "closure", ir.CLOSURE_OUTPUT: "closure"}

# Zone output -> its item collection, the input node's following it
ZONE_ITEMS = {ir.REPEAT_OUTPUT: "repeat_items", ir.SIMULATION_OUTPUT: "state_items"}


def build_source(source, filename="<text>", load=None, warnings=None):
    """Compile a .bn source and build its graphs, and those its `use` lines bring.

    `load(name, source)` finds the modules, `modules.load` by default; `warnings` is a list the
    warnings of the source are added to: they stop nothing.
    Returns the node groups of the source's own graphs, raises BnError.
    """
    with BlenderSchema() as schema:
        graphs = blender.compile_source(source, schema, filename, load or modules.load, warnings)
    builder = Builder(filename, graphs)

    scratch = {}
    made = []  # the scratch datablocks: groups, and the materials owning their own trees
    try:
        for g in graphs:
            if is_material(g.settings):
                # A material's own tree is checked in a material of its own, made first: a graph of
                # the text before it may already set it (`SetMaterial(material: "Clay")`)
                mat = bpy.data.materials.new(f".base_node_check_{g.name}")
                made.append(mat)
                scratch[g.name] = mat.node_tree
                mat.node_tree.nodes.clear()
                builder.materials[g.name] = mat
        for g in graphs:
            if outputs.offered(g, builder.called) and g.name not in builder.materials:
                # A shader group nobody calls is a material too: a graph may set it, before or after it
                mat = bpy.data.materials.new(f".base_node_check_{g.name}")
                made.append(mat)
                builder.materials[g.name] = mat
        for g in graphs:
            if is_material(g.settings):
                builder.build(g, scratch[g.name], scratch)
                continue
            tree = bpy.data.node_groups.new(f".base_node_check_{g.name}", TREE_TYPES[g.kind])
            made.append(tree)
            scratch[g.name] = tree
            builder.build(g, tree, scratch)
    finally:
        # At once: each removal alone looks through the whole file for the users of what goes
        bpy.data.batch_remove(made)

    # The materials the text defines exist before any graph sets them
    targets = {g.name: builder.target(g) for g in graphs if is_material(g.settings)}
    builder.materials = {name: outputs.owner(tree) for name, tree in targets.items()}
    groups = {}
    for g in graphs:
        if outputs.offered(g, builder.called):
            # Its material exists before the graphs that set it are built; offer() fills it after
            groups[g.name] = builder.target(g)
            mat = outputs.reserve(groups[g.name])
            if mat is not None:
                builder.materials[g.name] = mat
    built = {}
    for g in graphs:
        tree = built[g.name] = builder.build(g, targets.get(g.name) or groups.get(g.name) or builder.target(g), built)
        mark(tree, g.module, g.called_as, g.types, g.type_inputs)
    comments.keep(source, filename, graphs, built, builder.made)
    for g in graphs:
        tree = built[g.name]
        # A new tree is laid out by the text; once commented, it leaves room for its comments
        if g.module is None and g.name in builder.fresh and any(comments.KEY in n for n in tree.nodes):
            arrange_nodes(tree, room=comments.room)
        # A shader graph's return feeds a material's Material Output, a compositor graph's the Composite
        outputs.offer(tree, g, builder.called)
    return [built[g.name] for g in graphs if g.module is None]


def mark(tree, module, called_as=None, types=None, type_inputs=None):
    """Say which module a group comes from, so that Tree → Text writes its use back, and which
    graph of it, for one built for another kind of tree or a template's for its types."""
    if called_as is None:
        tree.pop(modules.GRAPH, None)
    else:
        tree[modules.GRAPH] = called_as
    if types is None:
        tree.pop(modules.TYPES, None)
    else:
        tree[modules.TYPES] = json.dumps({"types": types, "inputs": type_inputs})
    if module is None:
        tree.pop(modules.MODULE, None)
        tree.pop(modules.SOURCE, None)
        if hasattr(tree, "base_node_text"):
            tree.base_node_text = None  # the tree is the data; no text stands behind it
        return
    name, source = module
    tree[modules.MODULE] = name
    tree[modules.SOURCE] = source or ""
    if hasattr(tree, "base_node_text"):
        # A text module goes along with the group when it is appended elsewhere
        tree.base_node_text = bpy.data.texts.get(name + ".bn") if source is None else None


def target(g):
    """The group to rebuild: the existing one of that name, else a new one."""
    tree = bpy.data.node_groups.get(g.name)
    if tree is not None and tree.bl_idname == TREE_TYPES[g.kind] and tree.library is None:
        return tree
    return bpy.data.node_groups.new(g.name, TREE_TYPES[g.kind])


def material_target(g):
    """The tree of the material to rebuild: the existing one of that name, else a new one.
    Returns None for a material linked from a library, which is not this file's to change."""
    mat = bpy.data.materials.get(g.name)
    if mat is not None and mat.library is not None:
        return None
    if mat is None:
        mat = bpy.data.materials.new(g.name)
        mat.node_tree.nodes.clear()  # a new material's Principled BSDF is not the text's
    # Its own tree now: no longer the material of a shader group, which leaves it alone
    mat.pop(outputs.MATERIAL_GROUP, None)
    return mat.node_tree


class Builder:
    def __init__(self, filename, graphs):
        self.filename = filename
        self.graphs = {g.name: g for g in graphs}
        # Only the graphs nobody calls are offered as modifiers
        self.called = {n.group for g in graphs for n in g.nodes if n.group}
        self.late = []  # (item, option, value) to set once the links are made
        self.made = {}  # graph name -> (nodes, frames): ir id -> the Blender node made for it
        self.fresh = set()  # names of the graphs whose tree had no node to keep the place of
        self.materials = {}  # name of a material the text defines -> the material it is built into

    def datablock(self, kind, collection, name):
        """The datablock `name` of `collection` (bpy.data.materials…), a material the text defines first."""
        if kind.upper() == "MATERIAL" and name in self.materials:
            return self.materials[name]
        if kind.upper() in ("FONT", "VECTORFONT") and name == BUILTIN_FONT:
            # Blender's own font, under whatever name this file gives it ("Bfont Regular.001" once a
            # library brought its own copy), loaded when the file has none: a new String to Curves loads it
            return next((f for f in bpy.data.fonts if builtin_font(f)), None) \
                or bpy.data.fonts.load(BUILTIN_PATH, check_existing=True)
        return collection.get(name)

    def fail(self, node, message):
        raise BnError([Diagnostic(self.filename, node.line, node.col, message)])

    def target(self, g):
        if not is_material(g.settings):
            return target(g)
        tree = material_target(g)
        if tree is None:
            self.fail(g, f"material '{g.name}' is linked from a library: it cannot be rebuilt here")
        return tree

    def build(self, g, tree, built):
        # Named nodes keep their place across rebuilds
        kept = {n.name: n.location_absolute.copy() for n in tree.nodes}
        if kept:
            self.fresh.discard(g.name)
        else:
            self.fresh.add(g.name)
        tree.nodes.clear()
        if is_material(g.settings):
            # A material's own tree: no interface, its Material Output stands for the Group Output
            unknown = [s for s in g.settings if s not in (MATERIAL, "target")]
            if unknown:
                self.fail(g, f"unknown setting '{unknown[0]}' of a material; settings: {MATERIAL}, target")
            self.ids = {}
            self.fill(tree, g, built, kept)
            out = self.made[g.name][0][ir.GROUP_OUTPUT]
            try:
                out.target = g.settings.get("target", "ALL")
            except TypeError as e:
                self.fail(g, f"setting 'target': {e}")
            out.is_active_output = True
            tree.description = g.description or ""
            return tree
        allowed = socket_types(tree.bl_idname)
        for name, type in g.outputs + g.inputs:
            if type not in allowed:
                self.fail(g, f"'{name}': a {g.kind} tree has no {type} socket; types: {', '.join(allowed)}")
        self.ids = sync_interface(tree, g)
        self.aliases(tree, g)
        self.panels(tree, g)
        self.settings(tree, g)
        self.fill(tree, g, built, kept)
        tree.description = g.description or ""
        # Kept on the group for Tree → Text to write it back: Blender has no word for it
        if g.deprecated is None:
            tree.pop(DEPRECATION, None)
        else:
            tree[DEPRECATION] = g.deprecated
        # The subtype first: it makes the socket again, with its own defaults
        self.options(tree, g)
        # After the links: a menu input only has its items once it feeds a menu
        self.defaults(tree, g)
        return tree

    def aliases(self, tree, g):
        """Keep on the group the keys the text gave with `as`, for Tree → Text to write them back."""
        aliases = {self.ids[(io, k)]: {"name": name, "key": k} for io in ("INPUT", "OUTPUT")
                   for (name, _type), k in zip(g.inputs if io == "INPUT" else g.outputs, g.keys(io))
                   if k != key(name)}
        if aliases:
            tree[ALIASES] = aliases
        else:
            tree.pop(ALIASES, None)

    def settings(self, tree, g):
        """The tree's settings as written, else a new tree's. Unless written, a graph nobody
        calls whose first input and output are geometries is a modifier, and another is not."""
        unknown = [s for s in g.settings if s != MATERIAL and (s not in TREE_FLAGS or not hasattr(tree, s))]
        if unknown:
            self.fail(g, f"unknown setting '{unknown[0]}'; settings: {', '.join(TREE_FLAGS)}"
                         + (f", {MATERIAL}" if g.kind == "shader" else ""))
        modifier = bool(g.name not in self.called and g.inputs[:1] and g.outputs[:1]
                        and g.inputs[0][1] == g.outputs[0][1] == "Geometry")
        for flag, fresh in dict(TREE_FLAGS, is_modifier=modifier).items():
            if not hasattr(tree, flag):
                continue
            value = g.settings.get(flag, fresh)
            if not isinstance(value, bool):
                self.fail(g, f"setting '{flag}': true or false")
            setattr(tree, flag, value)

    def panels(self, tree, g):
        """Each panel's settings as written, else a new panel's."""
        made = {p.id: item for p, item in zip(g.panels, panel_items(tree, g))}
        for p in g.panels:
            unknown = [o for o in p.options if o not in PANEL_OPTIONS]
            if unknown:
                self.fail(p, f"panel '{p.name}': unknown setting '{unknown[0]}'; settings: "
                             f"{', '.join(PANEL_OPTIONS)}")
            for option, fresh in PANEL_OPTIONS.items():
                try:
                    setattr(made[p.id], option, p.options.get(option, fresh))
                except (TypeError, ValueError) as e:
                    self.fail(p, f"panel '{p.name}' setting '{option}': {e}")

    def item(self, tree, io, k):
        """The interface socket of a text key, found again: setting some options makes it anew."""
        ident = self.ids[(io, k)]
        return next(i for i in tree.interface.items_tree if i.item_type == "SOCKET" and i.identifier == ident)

    def options(self, tree, g):
        """Each socket's other settings as written (subtype, description…), else a new socket's."""
        for io, names in (("INPUT", g.inputs), ("OUTPUT", g.outputs)):
            for (name, _type), k in zip(names, g.keys(io)):
                item = self.item(tree, io, k)
                fresh = fresh_options(item.socket_type, io, tree.bl_idname)
                wanted = g.options.get((io, k), {})
                unknown = [o for o in wanted if o not in fresh]
                if unknown:
                    self.fail(g, f"'{name}': unknown option '{unknown[0]}'; options: {', '.join(fresh)}")
                # The dimensions first, which make another item (Vector2D…), then the subtype
                for option in sorted(fresh, key=lambda o: (o != "dimensions", o != "subtype")):
                    value = wanted.get(option, fresh[option])
                    if same_option(option, getattr(item, option), value):
                        continue
                    try:
                        setattr(item, option, value)
                    except (TypeError, ValueError) as e:
                        self.fail(g, f"option '{option}' of '{name}': {e}")
                    item = self.item(tree, io, k)

    def defaults(self, tree, g):
        """Each input's default, bounds and implicit field as written, else a new socket's."""
        for (name, _type), k in zip(g.inputs, g.input_keys):
            item = self.item(tree, "INPUT", k)
            spec = g.defaults.get(k, {})
            fresh = fresh_item(item.socket_type, tree.bl_idname)
            if "min_value" in fresh:
                set_changed(item, "min_value", spec.get("min", fresh["min_value"]))
                set_changed(item, "max_value", spec.get("max", fresh["max_value"]))
            if "default_input" in fresh:
                set_changed(item, "default_input", spec.get("implicit", fresh["default_input"]))
            if "default_value" not in fresh:
                continue
            value = spec.get("value", fresh["default_value"])
            if item.socket_type.removeprefix("NodeSocket").upper() in DATABLOCKS and isinstance(value, str):
                kind = item.socket_type.removeprefix("NodeSocket").upper()
                found = self.datablock(kind, getattr(bpy.data, DATABLOCKS[kind]), value)
                if found is None:
                    self.fail(g, f"'{name}': {_type} '{value}' not found in file")
                value = found
            elif item.socket_type == "NodeSocketVector" and hasattr(item, "dimensions"):
                if item.dimensions != len(value):
                    # The item changes type (Vector2D…): its default holds the new size once fetched again
                    item.dimensions = len(value)
                    item = self.item(tree, "INPUT", k)
            elif isinstance(value, tuple) and len(value) == 3 and len(item.default_value) == 4:
                value = (*value, 1.0)
            elif item.socket_type == "NodeSocketMenu" and value == "":
                continue  # no item chosen, which Blender refuses to be told once the menu has items
            try:
                set_changed(item, "default_value", value)
            except (TypeError, ValueError) as e:
                self.fail(g, f"default value of '{name}': {e}")

    def fill(self, tree, g, built, kept):
        pos = layout(g)
        frames = {}
        material = is_material(g.settings)
        fixed = MATERIAL_NAMES if material else FIXED_NAMES
        # A frame is named after its title, unless a node of the text takes that name
        names = {n.name or fixed.get(n.id) for n in g.nodes}
        for f in g.frames:
            frame = tree.nodes.new("NodeFrame")
            frames[f.id] = frame
            if f.label:
                frame.label = f.label
                if f.label not in names:
                    frame.name = f.label
            if f.color:
                frame.use_custom_color = True
                frame.color = f.color
            frame[LINE] = f.line
            if f.parent:
                frame.parent = frames[f.parent]
            # A frame around nodes shrinks to them; a note needs a place and a size of its own
            if f.id in pos:
                frame.location_absolute = kept.get(frame.name, pos[f.id])
                frame.width = max(frame.width, 12 * len(f.label or ""))

        nodes = {}
        self.made[g.name] = (nodes, frames)
        for n in g.nodes:
            idname = n.bl_idname
            if material and n.id == ir.GROUP_INPUT:
                continue  # a material takes no input, and a Group Input in it renders black
            if material and n.id == ir.GROUP_OUTPUT:
                idname = outputs.MATERIAL_OUTPUT
            try:
                node = tree.nodes.new(idname)
            except RuntimeError:
                # A zone or a node of another tree kind: `simulate` is Geometry Nodes' only
                what = ZONE_WORDS.get(n.bl_idname) or ui_name(n.bl_idname) or text_name(n.bl_idname)
                self.fail(n, f"{what} does not exist in a {g.kind} tree")
            nodes[n.id] = node
            name = n.name or fixed.get(n.id)
            if name:
                node.name = name
            node[LINE] = n.line
            if n.frame:
                node.parent = frames[n.frame]
            for prop, value in n.look.items():
                setattr(node, prop, value)
            if n.group:
                # A group of the file the text does not define is used as it is
                node.node_tree = built[n.group] if n.group in self.graphs else bpy.data.node_groups[n.group]
            for prop, value in n.props.items():
                datablock = id_type(node.bl_rna.properties[prop]) if prop in node.bl_rna.properties else None
                if datablock and isinstance(value, str):
                    found = self.datablock(datablock, datablocks(datablock), value)
                    if found is None:
                        self.fail(n, f"{prop}: {datablock} '{value}' not found in file")
                    value = found
                try:
                    setattr(node, prop, value)
                except (TypeError, ValueError, AttributeError) as e:
                    self.fail(n, f"{prop}: {e}")
            for prop, value in n.data.items():
                self.data(n, getattr(node, prop), value)

        # Zones: pair each input with its output, then give the output its items (the input follows)
        for n in g.nodes:
            if n.pair:
                nodes[n.id].pair_with_output(nodes[n.pair])
        for n in g.nodes:
            if n.items is not None and n.bl_idname in ZONE_ITEMS:
                fill_items(getattr(nodes[n.id], ZONE_ITEMS[n.bl_idname]), n.items)
            elif n.items is not None and n.bl_idname == ir.FOREACH_OUTPUT:
                fill_items(nodes[n.id].main_items, n.items[:n.main])
                fill_items(nodes[n.id].generation_items, n.items[n.main:])
            elif n.items is not None and n.bl_idname == ir.FOREACH_INPUT:
                fill_items(nodes[n.pair].input_items, n.items)
            elif n.items is not None and n.bl_idname in ITEM_NODES:
                self.items(nodes[n.id], n)
            elif signature_items(n.bl_idname):
                for attr, shape in signature_items(n.bl_idname):
                    self.item_list(nodes[n.id], n, shape, getattr(n, attr) or [], attr)

        menus = []
        for n in g.nodes:
            if n.id not in nodes:
                continue  # a material's Group Input, not made
            node = nodes[n.id]
            name = n.name or fixed.get(n.id)
            node.location_absolute = kept[name] if name in kept else pos[n.id]

            for ident, value in n.values.items():
                sock = self.socket(g, n, node, ident, "inputs")
                if sock.type == "MENU":
                    menus.append((n, ident, sock, value))
                    continue
                try:
                    sock.default_value = self.coerce(n, sock, value)
                except (TypeError, ValueError) as e:
                    self.fail(n, f"{ident}: {e}")
            for ident, value in n.out_values.items():
                sock = self.socket(g, n, node, ident, "outputs")
                try:
                    sock.default_value = self.coerce(n, sock, value)
                except (TypeError, ValueError) as e:
                    self.fail(n, f"{ident}: {e}")

        # The links into the output last: until it is fed, a new link changes nothing the users of
        # the tree see, and Blender does not look through the whole file for them
        # Blender joins the links of a multi-input from the highest multi_input_sort_id down (the
        # top one in the editor first) and gives each new link the next id: the links of one input
        # are made last value first, so that the first value written is the first joined
        links = []
        for n in g.nodes:
            fed = {}
            for ident, link in n.links:
                fed.setdefault(ident, []).append(link)
            links += [(n, ident, link) for ident, many in fed.items() for link in reversed(many)]
        order = sorted(range(len(links)), key=lambda i: links[i][0].id == ir.GROUP_OUTPUT)
        refused = []
        for i in order:
            n, ident, link = links[i]
            src = self.socket(g, g.node(link.node), nodes[link.node], link.output, "outputs")
            dst = self.socket(g, n, nodes[n.id], ident, "inputs")
            made = tree.links.new(src, dst)
            if not made.is_valid:
                refused.append((i, n, made, src, dst))
        refused = [r[1:] for r in sorted(refused, key=lambda r: r[0])]
        if refused:
            # A link into a zone made before the zone knows its body (a closure in a repeat) is
            # only valid once Blender has updated the tree
            tree.update_tag()
            bpy.context.view_layer.update()
        for n, made, src, dst in refused:
            if not made.is_valid:
                self.fail(n, f"Blender rejected link {src.name} ({src.type}) → {dst.name} ({dst.type})")
        # A menu input only has its items once linked to the menu it feeds, and the tree updated
        updated = False
        for n, ident, sock, value in menus:
            if not updated and value not in {i.identifier for i in sock.bl_rna.properties["default_value"].enum_items}:
                tree.update_tag()
                bpy.context.view_layer.update()
                updated = True
            try:
                sock.default_value = self.coerce(n, sock, value)
            except (TypeError, ValueError) as e:
                self.fail(n, f"{ident}: {e}")
        # Once linked: an item set to remove itself goes at once while nothing feeds it
        for item, option, value in self.late:
            setattr(item, option, value)
        self.late.clear()

    def data(self, n, data, value):
        """A ramp's stops or a curve mapping's points as the text gives them: see ir.Node.data."""
        for option, v in value["options"].items():
            try:
                setattr(data, option, v)
            except (TypeError, ValueError) as e:
                self.fail(n, f"{option}: {e}")
        if "stops" in value:
            # Each stop made at its place: a ramp keeps its stops in the order of their positions
            stops = sorted(value["stops"], key=lambda s: s[0])
            elements = data.elements
            while len(elements) > 1:
                elements.remove(elements[-1])
            elements[0].position, elements[0].color = stops[0]
            for position, color in stops[1:]:
                elements.new(position).color = color
            return
        for i, points in value["curves"].items():
            curve = data.curves[i]
            # A curve keeps two points: the ends first, then the others, each made at its place
            while len(curve.points) > 2:
                curve.points.remove(curve.points[1])
            for p, (x, y, handle) in zip(curve.points, (points[0], points[-1])):
                p.location = (x, y)
                p.handle_type = handle
            for x, y, handle in points[1:-1]:
                curve.points.new(x, y).handle_type = handle
        data.update()

    def items(self, node, n):
        """The items of a node of ITEM_NODES, in the order of the text, with their options."""
        self.item_list(node, n, ITEM_NODES[n.bl_idname], n.items, "items")

    def item_list(self, node, n, shape, items, attr):
        """One item collection of a node, as the text lists it, with each item's options."""
        getattr(node, shape.collection).clear()
        for name, type in items:
            new_item(node, shape, name, type)
        # Options once every item is there: a new item may change those before it.
        # Fetched again, as adding items may move the earlier ones in memory
        for (name, _type), item in zip(items, getattr(node, shape.collection)):
            if shape.named and item.name != name:
                self.fail(n, f"Blender renames item '{name}' to '{item.name}': "
                             "item names cannot be paths (no '/', '.', '-', or ':')")
            wanted = n.item_options.get(option_key(attr, name), {})
            known = item_option_names(item, shape)
            unknown = [o for o in wanted if o not in known]
            if unknown:
                self.fail(n, f"item '{name}': unknown option '{unknown[0]}'; "
                             f"options: {', '.join(known) or 'none'}")
            for option, value in wanted.items():
                if option in LATE_OPTIONS:
                    self.late.append((item, option, value))
                    continue
                try:
                    setattr(item, option, value)
                except (TypeError, ValueError) as e:
                    self.fail(n, f"option '{option}' of item '{name}': {e}")

    def socket(self, g, n, node, ident, side):
        """A Blender socket from its text identifier.

        Interface sockets (group input and output, group nodes) are named in
        text but numbered in Blender, so they are found by position.
        """
        sockets = getattr(node, side)
        names = None
        io = "INPUT" if side == "inputs" else "OUTPUT"
        if n.id == ir.GROUP_INPUT:
            names = [(k, None) for k in g.input_keys]
        elif n.id == ir.GROUP_OUTPUT and node.bl_idname == outputs.MATERIAL_OUTPUT:
            # A material's outputs are the Material Output's sockets, by key: surface…
            found = next((s for s in sockets if snake(s.name) == ident), None)
            if found is None:
                self.fail(n, f"Material Output has no socket '{ident}'")
            return found
        elif n.id == ir.GROUP_OUTPUT:
            names = [(k, None) for k in g.output_keys]
        elif n.group in self.graphs:
            names = [(k, None) for k in self.graphs[n.group].keys(io)]
        elif n.group:
            names = [(k, None) for k in socket_keys(node.node_tree, io).values()]
        elif n.bl_idname in SIGNATURE_NODES:
            # The fixed sockets by identifier, then the items by their number: #0, #1…
            fixed = SIGNATURE_NODES[n.bl_idname][side][0]
            sockets = [s for s in sockets if s.type != "CUSTOM"]
            if ident.startswith("#"):
                return sockets[fixed + int(ident[1:])]
            found = next((s for s in sockets[:fixed] if s.identifier == ident), None)
            if found is None:
                self.fail(n, f"socket '{ident}' not found in Blender")
            return found
        elif n.items is not None and n.bl_idname in ITEM_NODES:
            # The fixed sockets by identifier, then the items by position
            shape = ITEM_NODES[n.bl_idname]
            sockets = [s for s in sockets if s.type != "CUSTOM"]
            fixed = shape.inputs if side == "inputs" else shape.outputs
            if ident.startswith("#"):
                # An item with a key of its own (`Selection as captured`), by its number
                return sockets[fixed + int(ident[1:])]
            found = next((s for s in sockets[:fixed] if s.identifier == ident), None)
            if found is not None:
                return found
            return sockets[fixed + [name for name, _t in n.items].index(ident)]
        elif n.items is not None:
            # Zone items are numbered by Blender too, after the zone node's fixed sockets
            fixed = ir.ZONE_SOCKETS[n.bl_idname][side == "outputs"]
            names = [(name, None) for name in fixed] + n.items
            sockets = [s for s in sockets if s.type != "CUSTOM"]
            if ident.startswith("#"):
                # A state named like a socket of the zone (`Iteration`), by its number
                return sockets[len(fixed) + int(ident[1:])]
        if names is not None:
            return sockets[[name for name, _t in names].index(ident)]
        sock = next((s for s in sockets if s.identifier == ident), None)
        if sock is None:
            self.fail(n, f"socket '{ident}' not found in Blender")
        return sock

    def coerce(self, n, sock, value):
        if sock.type in DATABLOCKS and isinstance(value, str):
            found = self.datablock(sock.type, getattr(bpy.data, DATABLOCKS[sock.type]), value)
            if found is None:
                self.fail(n, f"{sock.type.title()} '{value}' not found in file")
            return found
        return coerce(sock, value)


def set_changed(item, prop, value):
    """Set an interface socket's property unless it already holds that value: each change of the
    interface updates the trees that use it, which Blender finds by looking through the whole file."""
    current = getattr(item, prop)
    if hasattr(current, "__len__") and not isinstance(current, str):
        current = tuple(current)
        same = hasattr(value, "__len__") and not isinstance(value, str) and current == tuple(value)
    else:
        same = type(current) is type(value) and current == value
    if not same:
        setattr(item, prop, value)


def fill_items(items, wanted):
    """A zone's item collection, as the text lists it."""
    items.clear()
    for name, type in wanted:
        items.new(REPEAT_ITEMS[type], name)


def coerce(sock, value):
    """A text literal as the socket's default_value."""
    current = sock.default_value
    if isinstance(value, (int, float)) and not isinstance(value, bool) and hasattr(current, "__len__") \
            and not isinstance(current, str):
        return [value] * len(current)
    if isinstance(value, tuple) and len(value) == 3 and hasattr(current, "__len__") and len(current) == 4:
        return (*value, 1.0)
    return value


def sync_interface(tree, g):
    """Make the interface match the signature and its panels, reusing the sockets and panels
    that did not change. Returns {(side, key): socket identifier}."""
    iface = tree.interface
    sockets = [i for i in iface.items_tree if i.item_type == "SOCKET"]
    old = {}
    for item in iface.items_tree:
        if item.item_type == "PANEL":
            old.setdefault(path(item), item)
    panels = {}
    for p in g.panels:
        here = (panels[p.parent][1] if p.parent else ()) + (p.name,)
        found = old.pop(here, None)
        panels[p.id] = (found or iface.new_panel(p.name), here)
    for item in old.values():
        iface.remove(item)
    keep = []
    for io, names in (("OUTPUT", g.outputs), ("INPUT", g.inputs)):
        for (name, type), k in zip(names, g.keys(io)):
            where = panels[g.panel_of[(io, k)]][1] if (io, k) in g.panel_of else ()
            # Two sockets of one name: each kept once, the one already in that panel first
            taken = [i for _io, _k, i in keep]
            same = [i for i in sockets if i.name == name and i.in_out == io
                    and i.socket_type == TYPES[type] and i not in taken]
            found = next((i for i in same if path(i.parent) == where), same[0] if same else None)
            keep.append((io, k, found or iface.new_socket(name, in_out=io, socket_type=TYPES[type])))
    taken = [i for _io, _k, i in keep]
    for item in sockets:
        if item not in taken:
            iface.remove(item)
    # Blender's order in each panel: its outputs, its inputs, then its panels
    children = {None: []}
    for p in g.panels:
        children[p.id] = []
    for io, k, item in keep:
        children[g.panel_of.get((io, k))].append(item)
    for p in g.panels:
        children[p.parent].append(panels[p.id][0])
    containers = [(root_panel(tree) if parent is None else panels[parent][0], children[parent])
                  for parent in [None] + [p.id for p in g.panels]]
    # Each move updates the trees that use this one: none when every item is already in its place
    if any(container is not None and list(container.interface_items) != items for container, items in containers):
        for container, items in containers:
            # Each to the end in turn: a move to a given position counts the item itself
            for item in items:
                iface.move_to_parent(item, container, len(container.interface_items))
    return {(io, k): item.identifier for io, k, item in keep}


def path(item):
    """Names of a panel and the panels around it, outermost first; () for the root."""
    names = []
    while item is not None and item.parent is not None:
        names.insert(0, item.name)
        item = item.parent
    return tuple(names)


def panel_items(tree, g):
    """The interface panels of g's panels, in the same order."""
    by_path = {path(i): i for i in tree.interface.items_tree if i.item_type == "PANEL"}
    paths = {}
    for p in g.panels:
        paths[p.id] = (paths[p.parent] if p.parent else ()) + (p.name,)
    return [by_path[paths[p.id]] for p in g.panels]
