import os

import bpy
from bpy_extras.io_utils import ImportHelper

from ..host import comments
from ..host.arrange import arrange_nodes
from ..host.builder import MISSING
from ..host import outputs
from ..host.schema import TREE_TYPES
from ..lang import BnError
from . import actions, prefs


def edit_tree(context):
    """The tree the Node Editor shows, when the text can hold it: a node group, or a
    material's own tree. A world's or a light's tree is not one."""
    space = context.space_data
    tree = getattr(space, "edit_tree", None) if space and space.type == "NODE_EDITOR" else None
    if tree is None or tree.bl_idname not in TREE_TYPES.values():
        return None
    return tree if not tree.is_embedded_data or outputs.owner(tree) is not None else None


def report_error(op, e):
    n = len(e.diagnostics)
    op.report({"ERROR"}, f"{e.diagnostics[0]}" + (f" (+{n - 1} error(s))" if n > 1 else ""))


class BASE_NODE_OT_apply_view(bpy.types.Operator):
    """Write this text into its node tree, and keep editing it"""
    bl_idname = "base_node.apply_view"
    bl_label = "Apply to Tree"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        # Every .bn text: Alt+P must not run one as Python
        space = context.space_data
        return space and space.type == "TEXT_EDITOR" and actions.is_bn(space.text)

    def execute(self, context):
        text = context.space_data.text
        if not actions.is_view(text):
            self.report({"WARNING"}, "Not the text of a tree: Alt+Z in a Node Editor shows one")
            return {"CANCELLED"}
        try:
            tree = actions.apply_view(text)
        except BnError as e:
            report_error(self, e)
            return {"CANCELLED"}
        for area in context.screen.areas:
            if area.type in {"NODE_EDITOR", "VIEW_3D"}:
                area.tag_redraw()
        self.report({"INFO"}, f"'{tree.name}' built" if tree else "nothing built")
        return {"FINISHED"}


class BASE_NODE_OT_format(bpy.types.Operator):
    """Rewrite this text in the canonical layout, keeping its comments"""
    bl_idname = "base_node.format"
    bl_label = "Format"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return context.space_data and context.space_data.type == "TEXT_EDITOR" \
            and actions.is_bn(context.space_data.text)

    def execute(self, context):
        try:
            changed = actions.format_text(context.space_data.text)
        except BnError as e:
            self.report({"ERROR"}, f"nothing formatted: {e.diagnostics[0]}")
            return {"CANCELLED"}
        self.report({"INFO"}, "text formatted" if changed else "text already formatted")
        return {"FINISHED"}


class BASE_NODE_OT_toggle_view(bpy.types.Operator):
    """Show this area's node tree as text, or the text back as its node tree.
    The tree stays the only data: the text is written back into it, then removed"""
    bl_idname = "base_node.toggle_view"
    bl_label = "Nodes ↔ Text"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        space = context.space_data
        if space and space.type == "TEXT_EDITOR":
            return actions.is_view(space.text)
        return edit_tree(context) is not None

    def execute(self, context):
        area = context.area
        if area.type == "TEXT_EDITOR":
            return self.to_nodes(area)
        return self.to_text(context, area)

    def to_text(self, context, area):
        tree = edit_tree(context)
        text, warnings = actions.open_view(tree)
        area.type = "TEXT_EDITOR"
        space = area.spaces.active
        space.text = text
        space.top = 0
        if warnings:
            self.report({"WARNING"}, f"{len(warnings)} export warning(s), see Nodes panel")
        return {"FINISHED"}

    def to_nodes(self, area):
        text = area.spaces.active.text
        try:
            tree = actions.close_view(text)
        except BnError as e:
            report_error(self, e)
            return {"CANCELLED"}
        area.type = "NODE_EDITOR"
        space = area.spaces.active
        # A material's tree is shown through its object: the editor finds it again by itself
        if tree is not None and space.edit_tree != tree and not tree.is_embedded_data:
            space.tree_type = tree.bl_idname
            space.node_tree = tree
        return {"FINISHED"}


class BASE_NODE_OT_copy_bn(bpy.types.Operator):
    """Put this node tree on the clipboard as .bn text, with the groups it calls: pasted in
    another file, or in a forum post, the text builds on its own"""
    bl_idname = "base_node.copy_bn"
    bl_label = "Copy as .bn"
    bl_options = {"REGISTER"}

    selected: bpy.props.BoolProperty(
        name="Selected Only", default=False, options={"SKIP_SAVE"},
        description="Copy only the selected nodes, as a graph of their own: the links to the others go")

    @classmethod
    def poll(cls, context):
        return edit_tree(context) is not None

    @classmethod
    def description(cls, context, properties):
        if properties.selected:
            return "Put the selected nodes on the clipboard as .bn text, a graph of their own"
        return cls.__doc__

    def execute(self, context):
        tree = edit_tree(context)
        if self.selected and tree.is_embedded_data:
            self.report({"WARNING"}, "A material's own tree is copied whole: Copy as .bn")
            return {"CANCELLED"}
        if self.selected and not any(n.select for n in tree.nodes):
            self.report({"WARNING"}, "No node selected")
            return {"CANCELLED"}
        text, warnings = actions.copy_text(tree, self.selected)
        context.window_manager.clipboard = text
        what = "selected nodes" if self.selected else f"'{outputs.tree_ref(tree)[1]}'"
        message = f"{what} copied as .bn ({text.count(chr(10))} lines)"
        if warnings:
            self.report({"WARNING"}, f"{message}; {len(warnings)} warning(s): {warnings[0]}")
        else:
            self.report({"INFO"}, message)
        return {"FINISHED"}


class BASE_NODE_OT_paste_bn(bpy.types.Operator):
    """Build the .bn text of the clipboard into this file: node groups, materials, compositor.
    A graph of the name of an existing group rebuilds it in place, as File > Import does"""
    bl_idname = "base_node.paste_bn"
    bl_label = "Paste .bn"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        space = context.space_data
        return space is not None and space.type == "NODE_EDITOR"

    def execute(self, context):
        source = context.window_manager.clipboard
        if not source.strip():
            self.report({"ERROR"}, "The clipboard holds no text")
            return {"CANCELLED"}
        before = set(bpy.data.node_groups) | set(bpy.data.materials)
        try:
            trees = actions.paste_text(source)
        except BnError as e:
            # Nothing was built: the text is checked in scratch trees first
            report_error(self, e)
            return {"CANCELLED"}
        names = [outputs.tree_ref(t)[1] for t in trees]
        rebuilt = [n for t, n in zip(trees, names) if (outputs.owner(t) if t.is_embedded_data else t) in before]
        tree = actions.entry(trees)
        space = context.space_data
        if tree is not None and not tree.is_embedded_data:
            space.tree_type = tree.bl_idname
            # Pinned: else the editor goes back at once to the active object's modifier or material
            space.pin = True
            space.node_tree = tree
        message = f"'{names[0]}' pasted" if len(trees) == 1 else f"{len(trees)} trees pasted"
        if rebuilt:
            message += f"; rebuilt in place: {', '.join(rebuilt)}"
        self.report({"INFO"}, message)
        return {"FINISHED"}


class BASE_NODE_OT_goto(bpy.types.Operator):
    """Select what this error points to, and scroll to it"""
    bl_idname = "base_node.goto"
    bl_label = "Go to Error"
    bl_options = {"INTERNAL"}

    line: bpy.props.IntProperty()
    col: bpy.props.IntProperty(default=1)
    message: bpy.props.StringProperty(options={"SKIP_SAVE"})

    @classmethod
    def poll(cls, context):
        return context.space_data and context.space_data.type == "TEXT_EDITOR" and context.space_data.text

    @classmethod
    def description(cls, context, properties):
        # The whole message: the panel may be too narrow for it
        return properties.message or cls.__doc__

    def execute(self, context):
        space = context.space_data
        actions.select_at(space.text, self.line, self.col)
        space.top = max(0, self.line - 1 - space.visible_lines // 2)
        return {"FINISHED"}


class BASE_NODE_OT_add_modifier(bpy.types.Operator):
    """Add this node tree as a Geometry Nodes modifier of the active object"""
    bl_idname = "base_node.add_modifier"
    bl_label = "Add as Modifier"
    bl_options = {"REGISTER", "UNDO"}

    tree: bpy.props.StringProperty()

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.type in {"MESH", "CURVES", "POINTCLOUD", "VOLUME", "GREASEPENCIL"}

    def execute(self, context):
        tree = bpy.data.node_groups.get(self.tree)
        if tree is None:
            return {"CANCELLED"}
        obj = context.active_object
        mod = obj.modifiers.new(tree.name, "NODES")
        mod.node_group = tree
        self.report({"INFO"}, f"modifier '{mod.name}' added to {obj.name}")
        return {"FINISHED"}


class BASE_NODE_OT_import(bpy.types.Operator, ImportHelper):
    """Build the node trees of .bn files; their `use` lines also find modules next to them"""
    bl_idname = "base_node.import_bn"
    bl_label = "Import Base Node (.bn)"
    bl_options = {"REGISTER", "UNDO", "PRESET"}

    filename_ext = ".bn"
    filter_glob: bpy.props.StringProperty(default="*.bn", options={"HIDDEN"})
    files: bpy.props.CollectionProperty(type=bpy.types.OperatorFileListElement, options={"HIDDEN", "SKIP_SAVE"})
    directory: bpy.props.StringProperty(subtype="DIR_PATH", options={"HIDDEN", "SKIP_SAVE"})

    def execute(self, context):
        names = [f.name for f in self.files if f.name] or [os.path.basename(self.filepath)]
        folder = self.directory or os.path.dirname(self.filepath)
        built, errors, warned = {}, {}, {}
        pending = names
        while pending:
            # A file may set a material another file defines: those that failed, or missed a
            # datablock, go again after the others, as long as a round builds something
            failing = []
            for name in pending:
                path = os.path.join(folder, name)
                try:
                    warnings = []
                    built.update((id(t), t) for t in actions.import_file(path, warnings))
                    errors.pop(name, None)
                    warned.pop(name, None)
                    if any(d.message.startswith(MISSING) for d in warnings):
                        failing.append(name)
                        warned[name] = warnings
                except BnError as e:
                    failing.append(name)
                    n = len(e.diagnostics)
                    errors[name] = f"{e.diagnostics[0]}" + (f" (+{n - 1} error(s))" if n > 1 else "")
                except OSError as e:
                    failing.append(name)
                    errors[name] = f"{name}: {e.strerror}"
            if len(failing) == len(pending):
                break
            pending = failing
        failed = [name for name in names if name in errors]
        for name in failed:
            self.report({"ERROR"}, errors[name])
        for name in names:
            for d in warned.get(name, ()):
                self.report({"WARNING"}, str(d))
        if not built:
            return {"CANCELLED"}
        message = f"{len(built)} tree(s) imported from {len(names) - len(failed)} file(s)"
        if failed:
            message += f"; failed: {', '.join(failed)}"
        self.report({"WARNING"} if failed else {"INFO"}, message)
        return {"FINISHED"}


class BASE_NODE_OT_arrange(bpy.types.Operator):
    """Lay out the selected nodes, or all of them when none is: links go left to right,
    in line with their sockets, and each frame keeps its nodes together"""
    bl_idname = "base_node.arrange"
    bl_label = "Arrange Nodes"
    bl_options = {"REGISTER", "UNDO"}

    spacing: bpy.props.IntVectorProperty(name="Spacing", size=2, default=(50, 50), min=0, subtype="XYZ",
                                         description="Room between two columns, then between two nodes of a column")

    @classmethod
    def poll(cls, context):
        space = context.space_data
        return space is not None and space.type == "NODE_EDITOR" and space.edit_tree is not None

    def execute(self, context):
        tree = context.space_data.edit_tree
        nodes = [n for n in tree.nodes if n.select] or list(tree.nodes)
        # A node never drawn has no size yet: draw once, so that the layout uses the real ones
        if context.window and any(not n.dimensions.y for n in nodes if n.bl_idname not in {"NodeFrame", "NodeReroute"}):
            bpy.ops.wm.redraw_timer(type="DRAW", iterations=0)
        # Room for the comments drawn over the nodes, when they are
        room = comments.room if prefs.get().show_comments else None
        count = arrange_nodes(tree, nodes, spacing=self.spacing, room=room)
        if not count:
            self.report({"WARNING"}, "no node to arrange")
            return {"CANCELLED"}
        return {"FINISHED"}


# A comment the dialog shows: its lines so far, then an empty one to write the next
MAX_LINES = 24


class BaseNodeCommentLine(bpy.types.PropertyGroup):
    body: bpy.props.StringProperty(name="Line", description="One line of the comment")


class BASE_NODE_OT_edit_comment(bpy.types.Operator):
    """Write the comment shown over the active node. The text gives it back as `//` lines before
    the node's statement"""
    bl_idname = "base_node.edit_comment"
    bl_label = "Edit Comment"
    bl_options = {"REGISTER", "UNDO"}

    lines: bpy.props.CollectionProperty(type=BaseNodeCommentLine)

    @classmethod
    def poll(cls, context):
        tree = edit_tree(context)
        node = tree.nodes.active if tree is not None else None
        if node is None or node.bl_idname in comments.UNWRITTEN:
            cls.poll_message_set("Select a node that has a statement in the text: "
                                 "not a Group Input, a reroute or a zone's input")
            return False
        return True

    def invoke(self, context, event):
        node = edit_tree(context).nodes.active
        written = comments.lines_of(comments.notes_of(node), ("before",))
        self.lines.clear()
        for i in range(MAX_LINES):
            self.lines.add().body = written[i] if i < len(written) else ""
        return context.window_manager.invoke_props_dialog(self, width=420, title=f"Comment on {node.name}")

    def draw(self, context):
        col = self.layout.column(align=True)
        last = max((i for i, line in enumerate(self.lines) if line.body), default=-1)
        for line in list(self.lines)[:min(last + 2, MAX_LINES)]:
            col.prop(line, "body", text="")
        after = comments.lines_of(comments.notes_of(edit_tree(context).nodes.active), ("after",))
        if after:
            self.layout.label(text=f"On its line: {' '.join(after)}", icon="INFO")

    def execute(self, context):
        node = edit_tree(context).nodes.active
        lines = [line.body for line in self.lines]
        while lines and not lines[-1].strip():
            lines.pop()
        comments.set_comment(node, "before", lines)
        context.area.tag_redraw()
        return {"FINISHED"}


def menu_arrange(self, context):
    self.layout.separator()
    self.layout.operator(BASE_NODE_OT_arrange.bl_idname, icon="SNAP_GRID")
    self.layout.operator(BASE_NODE_OT_edit_comment.bl_idname, icon="TEXT")
    self.layout.separator()
    self.layout.operator(BASE_NODE_OT_copy_bn.bl_idname, icon="COPYDOWN")
    self.layout.operator(BASE_NODE_OT_copy_bn.bl_idname, text="Copy Selected as .bn", icon="COPYDOWN").selected = True
    self.layout.operator(BASE_NODE_OT_paste_bn.bl_idname, icon="PASTEDOWN")


def menu_comment(self, context):
    self.layout.separator()
    self.layout.operator(BASE_NODE_OT_edit_comment.bl_idname, icon="TEXT")


def menu_import(self, context):
    self.layout.operator(BASE_NODE_OT_import.bl_idname, text="Base Node (.bn)")


classes = (BASE_NODE_OT_import, BASE_NODE_OT_apply_view, BASE_NODE_OT_format, BASE_NODE_OT_toggle_view, BASE_NODE_OT_goto,
           BASE_NODE_OT_add_modifier, BASE_NODE_OT_arrange, BaseNodeCommentLine, BASE_NODE_OT_edit_comment,
           BASE_NODE_OT_copy_bn, BASE_NODE_OT_paste_bn)
