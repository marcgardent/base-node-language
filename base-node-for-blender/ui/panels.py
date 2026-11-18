import blf
import bpy

from . import actions, keys, prefs, targets
from .operators import edit_tree


class Shortcuts:
    """The shortcut of each button of a panel, greyed: on its right when there is room,
    else listed under the buttons, the keys first, after the button's icon."""

    def __init__(self, context, keymap, buttons):
        self.buttons = buttons  # idname -> (text, icon) of its button
        self.keys = {i: keys.shortcut(keymap, i) for i in buttons}
        self.shown = []
        p = context.preferences
        scale = p.system.ui_scale
        blf.size(0, p.ui_styles[0].widget.points * scale)
        widths = {i: blf.dimensions(0, k)[0] + 16 * scale for i, k in self.keys.items()}
        keys_w = max(widths.values())
        text_w = max(blf.dimensions(0, t)[0] for t, _icon in buttons.values()) + 12 * scale
        room = max(1, context.region.width - 50 * scale)  # less the panel's margins
        self.beside = text_w + 40 * scale + keys_w <= room  # a button has an icon and padding
        self.factor = min(0.75, max(0.25, 1 - keys_w / room))
        # Listed: the icon and the keys, then the name only when it fits whole
        self.listed = {}
        for i, w in widths.items():
            name_w = blf.dimensions(0, buttons[i][0])[0] + 8 * scale
            self.listed[i] = (w + 24 * scale) / room if w + 24 * scale + name_w <= room else None

    def row(self, layout, idname):
        """A row for the button of `idname`, its keys on its right or kept for the list."""
        if not self.beside:
            self.shown.append(idname)
            return layout.row(align=True)
        row = layout.split(factor=self.factor, align=True)
        left = row.row(align=True)
        sub = row.row()
        sub.alignment = "RIGHT"
        sub.active = False
        sub.label(text=self.keys[idname])
        return left

    def button(self, layout, idname):
        text, icon = self.buttons[idname]
        return self.row(layout, idname).operator(idname, text=text, icon=icon)

    def legend(self, layout):
        """The keys of the buttons that had no room for them."""
        if not self.shown:
            return
        col = layout.column(align=True)
        col.active = False
        for idname in self.shown:
            text, icon = self.buttons[idname]
            factor = self.listed[idname]
            if factor is None:
                col.label(text=self.keys[idname], icon=icon)
                continue
            row = col.split(factor=factor)
            row.label(text=self.keys[idname], icon=icon)
            row.label(text=text)


class TEXT_PT_base_node(bpy.types.Panel):
    bl_space_type = "TEXT_EDITOR"
    bl_region_type = "UI"
    bl_category = "Nodes"
    bl_label = "Nodes as Text"

    @classmethod
    def poll(cls, context):
        return actions.is_bn(context.space_data.text)

    def draw(self, context):
        layout = self.layout
        text = context.space_data.text
        col = layout.column(align=True)
        tree = actions.view_tree(text)
        rows = Shortcuts(context, "Text", {
            "base_node.apply_view": ("Apply to Tree", "FILE_REFRESH"),
            "base_node.toggle_view": ("Back to Nodes", "NODETREE"),
            "base_node.format": ("Format", "ALIGN_LEFT"),
            "base_node.complete": ("Suggestions", "VIEWZOOM")})
        if actions.is_view(text):
            row = rows.row(col, "base_node.apply_view")
            row.operator("base_node.apply_view", icon="FILE_REFRESH")
            if tree is not None and getattr(tree, "is_modifier", False):
                row.operator("base_node.add_modifier", text="", icon="MODIFIER").tree = tree.name
            rows.button(col, "base_node.toggle_view")
        rows.button(col, "base_node.format")
        # Suggestions have no button, only keys
        if rows.beside:
            rows.row(col, "base_node.complete").label(text="Suggestions", icon="VIEWZOOM")
        else:
            rows.shown.append("base_node.complete")
        rows.legend(layout)
        options = prefs.get()
        if isinstance(options, bpy.types.AddonPreferences):
            row = layout.row(align=True)
            row.prop(options, "highlight", toggle=True)
            row.prop(options, "auto_complete", text="Auto Suggestions", toggle=True)
            if actions.is_view(text):
                layout.prop(options, "live_apply", toggle=True)

            layout.prop(options, "highlight_mode", text="Highlight")

        draw_targets(layout, text)

        diags = actions.DIAGNOSTICS.get(text.name)
        if diags:
            box = layout.box()
            box.label(text=f"{len(diags)} error(s)", icon="ERROR")
            for d in diags:
                if d.file != text.name:
                    # In a module the text uses: no place to go in this one
                    box.label(text=str(d))
                    continue
                op = box.operator("base_node.goto", text=f"{d.line}:{d.col}  {d.message}", emboss=False)
                op.line, op.col, op.message = d.line, d.col, str(d)

        warnings = actions.WARNINGS.get(text.name)
        if warnings:
            box = layout.box()
            box.label(text=f"{len(warnings)} export warning(s)", icon="INFO")
            for w in warnings:
                box.label(text=w)


class NODE_PT_base_node(bpy.types.Panel):
    bl_space_type = "NODE_EDITOR"
    bl_region_type = "UI"
    bl_category = "Text"
    bl_label = "Nodes as Text"

    @classmethod
    def poll(cls, context):
        return edit_tree(context) is not None

    def draw(self, context):
        layout = self.layout
        col = layout.column(align=True)
        rows = Shortcuts(context, "Node Editor", {
            "base_node.toggle_view": ("Edit as Text", "TEXT"),
            "base_node.arrange": ("Arrange Nodes", "SNAP_GRID"),
            "base_node.edit_comment": ("Edit Comment", "TEXT"),
            "base_node.copy_bn": ("Copy as .bn", "COPYDOWN"),
            "base_node.paste_bn": ("Paste .bn", "PASTEDOWN")})
        rows.button(col, "base_node.toggle_view")
        rows.button(col, "base_node.arrange")
        rows.button(col, "base_node.edit_comment")
        col = layout.column(align=True)
        tree = edit_tree(context)
        row = rows.row(col, "base_node.copy_bn")
        row.operator("base_node.copy_bn", text="Copy as .bn", icon="COPYDOWN")
        # The selected nodes alone: no keys of their own, a button by the whole tree's
        sub = row.row(align=True)
        sub.enabled = not tree.is_embedded_data and any(n.select for n in tree.nodes)
        sub.operator("base_node.copy_bn", text="", icon="RESTRICT_SELECT_OFF").selected = True
        rows.button(col, "base_node.paste_bn")
        rows.legend(layout)
        options = prefs.get()
        if isinstance(options, bpy.types.AddonPreferences):
            layout.prop(options, "show_comments", text="Comments", toggle=True, icon="TEXT")


classes = (TEXT_PT_base_node, NODE_PT_base_node)


def draw_targets(layout, text):
    """The targets the text fits, and what it uses outside the ones its `// @target` promises."""
    inference, issues = targets.state(text)
    if inference is None:
        return
    box = layout.box()
    promise = targets.promised(text)
    if promise:
        ok = not issues
        box.label(text=f"@target {', '.join(promise)}", icon="CHECKMARK" if ok else "ERROR")
        for i in issues[:5]:
            op = box.operator("base_node.goto", text=f"{i.line}:{i.col}  {i.what} {i.name} outside {i.target}",
                              emboss=False)
            op.line, op.col, op.message = i.line, i.col, str(i)
        if len(issues) > 5:
            box.label(text=f"… and {len(issues) - 5} more")
    # The targets it fits as it is first, then those it fits through a translator
    fits = [t for t, via in inference.fits.items() if via is None]
    fits += [f"{t} (from {via})" for t, via in inference.fits.items() if via is not None]
    box.label(text="Fits: " + (", ".join(fits) or "no target as a whole"), icon="INFO")
    if not inference.fits:
        for graph, names in inference.graphs[:5]:
            box.label(text=f"  {graph}: {', '.join(names) or 'none'}")
