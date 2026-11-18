"""A .bn file dropped on Blender: its head says what it offers, a dialog lets the user choose.

    // @offer library, groups, example, modifier

- library: copy the file into the Module Folder of the preferences, for `use name` in every file;
- groups: build its graphs into the .blend, as File > Import does;
- example: an object carries a graph that makes its own geometry, as its modifier;
- modifier: a modifier graph goes on the object the file fell on, else the selected objects,
  else on a new mesh (`// @mesh`).

Only a file reaches Blender this way: a dropped link or text is a string Python cannot catch,
and opening a .bn never makes a network request (see host/modules.py).
"""

import os

import bmesh
import bpy

from ..host import modules
from ..lang import BnError, header
from . import actions, prefs

ACTIONS = (
    ("AUTO", "Most Useful", "The modifier on the object under the mouse, else the example, else the groups"),
    ("LIBRARY", "Install as Library", ("Copy the file into the Module Folder, so that `use <module>` "
                                       "finds it in every .blend")),
    ("GROUPS", "Import into the .blend", "Build every graph of the file, the groups kept with a fake user"),
    ("EXAMPLE", "Instantiate the Example", ("Add an object that carries a graph making its own geometry, "
                                            "as its Geometry Nodes modifier")),
    ("MODIFIER", "Add as Modifier", ("Add the modifier graph to the object the file was dropped on, "
                                     "else to the selected objects, else to a new mesh")),
)
OFFER = {"library": "LIBRARY", "groups": "GROUPS", "example": "EXAMPLE", "modifier": "MODIFIER"}
# The objects a Geometry Nodes modifier goes on (as Add as Modifier)
GEOMETRY_OBJECTS = {"MESH", "CURVES", "POINTCLOUD", "VOLUME", "GREASEPENCIL"}
DROP_SPACES = {"VIEW_3D", "NODE_EDITOR", "TEXT_EDITOR"}


# The last file read, for the dialog that draws it again and again: (path, mtime, size) -> (source, header)
_LAST = {}


def read(path):
    """(source, header) of a dropped file. Raises OSError, BnError."""
    st = os.stat(path)
    stamp = (os.path.realpath(path), st.st_mtime_ns, st.st_size)
    if stamp in _LAST:
        return _LAST[stamp]
    source = modules.read(path)
    _LAST.clear()
    _LAST[stamp] = source, header(source, os.path.basename(path))
    return _LAST[stamp]


def offered(h):
    return [OFFER[o] for o in h.offer]


def most_useful(h, has_target):
    """The action a dialog starts on: the modifier on a target, else the example, else the groups."""
    choices = offered(h)
    for action, ok in (("MODIFIER", has_target), ("EXAMPLE", True), ("GROUPS", True)):
        if ok and action in choices:
            return action
    return choices[0] if choices else "GROUPS"


def object_under(context, event):
    """The object under the mouse in a 3D Viewport, or None."""
    from bpy_extras import view3d_utils
    region, rv3d = context.region, context.region_data
    if context.area is None or context.area.type != "VIEW_3D" or region is None or rv3d is None:
        return None
    coord = (event.mouse_region_x, event.mouse_region_y)
    origin = view3d_utils.region_2d_to_origin_3d(region, rv3d, coord)
    direction = view3d_utils.region_2d_to_vector_3d(region, rv3d, coord)
    hit, _location, _normal, _index, obj, _matrix = context.scene.ray_cast(
        context.evaluated_depsgraph_get(), origin, direction)
    return obj.original if hit and obj is not None else None


def targets(context, name):
    """The objects the modifier goes on: the one named (under the mouse), else the selected ones
    that take a Geometry Nodes modifier. Empty: a new mesh is made."""
    obj = bpy.data.objects.get(name) if name else None
    if obj is not None and obj.type in GEOMETRY_OBJECTS:
        return [obj]
    return [o for o in getattr(context, "selected_objects", None) or () if o.type in GEOMETRY_OBJECTS]


def new_mesh(context, kind, name):
    """A new object of a mesh made as Blender's Add menu makes it (size 2), at the 3D cursor."""
    bm = bmesh.new()
    if kind == "cube":
        bmesh.ops.create_cube(bm, size=2.0)
    elif kind == "plane":
        bmesh.ops.create_grid(bm, x_segments=1, y_segments=1, size=1.0)
    elif kind == "grid":
        bmesh.ops.create_grid(bm, x_segments=10, y_segments=10, size=1.0)
    elif kind == "sphere":
        bmesh.ops.create_uvsphere(bm, u_segments=32, v_segments=16, radius=1.0)
    elif kind == "cylinder":
        bmesh.ops.create_cone(bm, cap_ends=True, segments=32, radius1=1.0, radius2=1.0, depth=2.0)
    mesh = bpy.data.meshes.new(name)
    bm.to_mesh(mesh)
    bm.free()
    return add_object(context, name, mesh)


def add_object(context, name, mesh):
    """A new object of this mesh in the active collection, at the 3D cursor, selected and active."""
    obj = bpy.data.objects.new(name, mesh)
    collection = getattr(context, "collection", None) or context.scene.collection
    collection.objects.link(obj)
    obj.location = context.scene.cursor.location
    for o in getattr(context, "selected_objects", None) or ():
        o.select_set(False)
    obj.select_set(True)
    context.view_layer.objects.active = obj
    return obj


def add_modifier(obj, tree):
    mod = obj.modifiers.new(tree.name, "NODES")
    mod.node_group = tree
    return mod


def group(trees, name):
    """The node group a graph of the file was built into."""
    return next((t for t in trees if t.name == name and not t.is_embedded_data), None) \
        or bpy.data.node_groups.get(name)


def report_bn(op, e):
    n = len(e.diagnostics)
    op.report({"ERROR"}, f"{e.diagnostics[0]}" + (f" (+{n - 1} error(s))" if n > 1 else ""))


class BASE_NODE_OT_drop_bn(bpy.types.Operator):
    """Open a dropped .bn file: install it as a library, import its groups, instantiate its
    example or add its modifier, as its head offers"""
    bl_idname = "base_node.drop_bn"
    bl_label = "Open Base Node File"
    bl_options = {"REGISTER", "UNDO"}

    filepath: bpy.props.StringProperty(name="File", subtype="FILE_PATH", options={"SKIP_SAVE"})
    action: bpy.props.EnumProperty(name="Action", items=ACTIONS, default="AUTO", options={"SKIP_SAVE"})
    target: bpy.props.StringProperty(
        name="Target", options={"SKIP_SAVE"},
        description="The object the modifier goes on: the one the file was dropped on. "
                    "Empty: the selected objects, else a new mesh")
    overwrite: bpy.props.BoolProperty(
        name="Overwrite", default=False, options={"SKIP_SAVE"},
        description="Replace the file of that name in the Module Folder, that holds another text")

    @classmethod
    def poll(cls, context):
        return context.scene is not None

    def invoke(self, context, event):
        try:
            _source, h = read(self.filepath)
        except OSError as e:
            self.report({"ERROR"}, f"{os.path.basename(self.filepath)}: {e.strerror}")
            return {"CANCELLED"}
        except BnError as e:
            report_bn(self, e)
            return {"CANCELLED"}
        obj = object_under(context, event)
        if obj is not None and obj.type in GEOMETRY_OBJECTS:
            self.target = obj.name
        # In the viewport, the file falls on an object or beside them: the selection counts when
        # it was dropped elsewhere (a Node Editor, a Text Editor)
        in_viewport = context.area is not None and context.area.type == "VIEW_3D"
        self.action = most_useful(h, bool(self.target) or (not in_viewport and bool(targets(context, ""))))
        title = h.title or os.path.basename(self.filepath)
        return context.window_manager.invoke_props_dialog(self, width=460, title=title, confirm_text="Open")

    def draw(self, context):
        layout = self.layout
        try:
            source, h = read(self.filepath)
        except (OSError, BnError) as e:
            layout.label(text=str(e).splitlines()[0], icon="ERROR")
            return
        col = layout.column(align=True)
        col.label(text=os.path.basename(self.filepath), icon="FILE_TEXT")
        for label, value in (("Author", h.author), ("License", h.license), ("Version", h.version)):
            if value:
                col.label(text=f"{label}: {value}")
        layout.separator()
        col = layout.column(align=True)
        for action in offered(h):
            col.prop_enum(self, "action", action)
        action = self.action if self.action != "AUTO" else most_useful(h, bool(self.target))
        box = layout.box()
        if action == "LIBRARY":
            try:
                path, state = modules.installed(h.module, prefs.get().module_folder, source)
            except LookupError as e:
                box.label(text=str(e), icon="ERROR")
            else:
                box.label(text=f"use {h.module}  ←  {path}")
                if state == "same":
                    box.label(text="Already installed: the file holds this text", icon="CHECKMARK")
                elif state == "other":
                    box.prop(self, "overwrite", text="Overwrite the file of that name (another text)")
        elif action == "EXAMPLE":
            box.label(text=f"A new object carries '{h.example}'", icon="OBJECT_DATA")
        elif action == "MODIFIER":
            on = targets(context, self.target)
            if self.target and on and on[0].name == self.target:
                what = f"on '{self.target}', under the mouse"
            elif on:
                what = f"on the {len(on)} selected object(s)" if len(on) > 1 else f"on '{on[0].name}', selected"
            else:
                what = f"on a new {h.mesh}"
            box.label(text=f"'{h.modifier}' {what}", icon="MODIFIER")
        else:
            box.label(text="Every graph becomes a node group of this file", icon="NODETREE")

    def execute(self, context):
        try:
            source, h = read(self.filepath)
        except OSError as e:
            self.report({"ERROR"}, f"{os.path.basename(self.filepath)}: {e.strerror}")
            return {"CANCELLED"}
        except BnError as e:
            # A head in error: nothing is built nor copied
            report_bn(self, e)
            return {"CANCELLED"}
        action = self.action if self.action != "AUTO" else most_useful(h, bool(targets(context, self.target)))
        if action not in offered(h):
            self.report({"ERROR"}, f"{os.path.basename(self.filepath)} does not offer {action.lower()}; "
                                   f"it offers: {', '.join(h.offer)}")
            return {"CANCELLED"}
        if action == "LIBRARY":
            return self.library(source, h)
        try:
            trees = actions.import_file(self.filepath)
        except BnError as e:
            report_bn(self, e)
            return {"CANCELLED"}
        except OSError as e:
            self.report({"ERROR"}, f"{os.path.basename(self.filepath)}: {e.strerror}")
            return {"CANCELLED"}
        if action == "GROUPS":
            self.report({"INFO"}, f"{len(trees)} tree(s) imported from {os.path.basename(self.filepath)}")
            return {"FINISHED"}
        if action == "EXAMPLE":
            tree = group(trees, h.example)
            obj = add_object(context, tree.name, bpy.data.meshes.new(tree.name))
            add_modifier(obj, tree)
            self.report({"INFO"}, f"'{obj.name}' carries '{tree.name}'")
            return {"FINISHED"}
        tree = group(trees, h.modifier)
        on = targets(context, self.target) or [new_mesh(context, h.mesh, h.mesh.capitalize())]
        for obj in on:
            add_modifier(obj, tree)
        self.report({"INFO"}, f"modifier '{tree.name}' added to {', '.join(o.name for o in on)}")
        return {"FINISHED"}

    def library(self, source, h):
        try:
            path, written = modules.install(h.module, prefs.get().module_folder, source, self.overwrite)
        except LookupError as e:
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}
        prefs.apply_folders()
        self.report({"INFO"}, f"`use {h.module}` finds {path}" + ("" if written else " (already installed)"))
        return {"FINISHED"}


class BASE_NODE_FH_bn(bpy.types.FileHandler):
    bl_idname = "BASE_NODE_FH_bn"
    bl_label = "Base Node (.bn)"
    bl_import_operator = "base_node.drop_bn"
    bl_file_extensions = ".bn"

    @classmethod
    def poll_drop(cls, context):
        space = getattr(context, "space_data", None)
        return space is not None and space.type in DROP_SPACES


classes = (BASE_NODE_OT_drop_bn, BASE_NODE_FH_bn)
