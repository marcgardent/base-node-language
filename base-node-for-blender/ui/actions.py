"""What the operators do, kept apart from them so tests can call it without a UI."""

import hashlib
import os

import bpy

from ..host import build_source, export_tree, modules
from ..host.outputs import find_tree, owner, tree_ref
from ..host.schema import BlenderSchema
from ..blender import BnError, compile_source
from ..blender.naming import name_inputs
from ..blender.ir import ZONE_INPUTS
from ..lang.lexer import span_at

EXT = ".bn"

# Per text name, for the panel: errors of the last build, warnings of the last export.
# Runtime only: they are not saved with the file.
DIAGNOSTICS = {}
WARNINGS = {}
# Per text name: the warnings of the last check or build of a valid text (a call of a deprecated
# graph). They stop nothing: the text is built with them
LINT = {}
CHECKED = {}  # text name -> the source DIAGNOSTICS and LINT speak of: checked, built, or formatted


def found(text, source, diagnostics=None, warnings=None):
    """Keep what a look at this source of the text found: its errors, or none, and its warnings."""
    CHECKED[text.name] = source
    for kept, said in ((DIAGNOSTICS, diagnostics), (LINT, warnings)):
        if said:
            kept[text.name] = said
        else:
            kept.pop(text.name, None)


def is_bn(text):
    return text is not None and text.name.endswith(EXT)


def build_text(text, live=False):
    """Build every graph of the text into its tree of the same name. Raises BnError.

    On an error nothing is built, and the cursor goes to it, unless the build is live:
    then it stays where the user types.
    """
    source = text.as_string()
    found(text, source)
    warnings = []
    try:
        trees = build_source(source, text.name, warnings=warnings)
        found(text, source, None, warnings)
        return trees
    except BnError as e:
        found(text, source, e.diagnostics)
        if not live:
            first = e.diagnostics[0]
            text.cursor_set(first.line - 1, character=max(0, first.col - 1))
        raise


def check_text(text):
    """Parse and check the text without building anything: its errors go to DIAGNOSTICS, the
    warnings of a valid text to LINT.

    Cheaper than a build, to show the errors while typing. True when the text is valid.
    """
    source = text.as_string()
    warnings = []
    try:
        with BlenderSchema() as schema:
            compile_source(source, schema, text.name, modules.load, warnings)
    except BnError as e:
        found(text, source, e.diagnostics)
        return False
    found(text, source, None, warnings)
    return True


def select_at(text, line, col):
    """Select what a diagnostic at a 1-based line and column points to, the cursor at its start."""
    row = max(0, min(line - 1, len(text.lines) - 1))
    body = text.lines[row].body
    start, end = span_at(body, col)
    text.cursor_set(row, character=start)
    if min(end, len(body)) > start:
        text.select_set(row, start, row, min(end, len(body)))


# Text view of a tree: the tree is the only data, the text lives while an area shows it.
VIEW_TREE = "base_node_view"       # ID property of the text: name of the tree it shows
VIEW_MATERIAL = "base_node_view_material"  # ID property of the text: true when that is a material's
VIEW_HASH = "base_node_view_hash"  # ID property of the text: hash of the source the tree holds


def _digest(source):
    return hashlib.sha1(source.encode("utf-8")).hexdigest()


def is_view(text):
    return text is not None and VIEW_TREE in text


def view_tree(text):
    """The tree a view text shows, or None when the text is not a view (or its tree is gone)."""
    name = text.get(VIEW_TREE) if text is not None else None
    if not name:
        return None
    return find_tree(("MATERIAL" if text.get(VIEW_MATERIAL) else "GROUP", name))


def show(text, tree):
    """Make the view text stand for this tree."""
    kind, name = tree_ref(tree)
    text[VIEW_TREE] = name
    text[VIEW_MATERIAL] = kind == "MATERIAL"


def open_view(tree):
    """Write the tree into a hidden text that only stands for it. Returns (text, warnings)."""
    source, warnings = export_tree(tree)
    kind, shown = tree_ref(tree)
    # Leading dot: hidden from the text browser. A material may have the name of a group
    name = f".{shown}{' (material)' if kind == 'MATERIAL' else ''}{EXT}"
    text = bpy.data.texts.get(name) or bpy.data.texts.new(name)
    text.from_string(source)
    text.cursor_set(0)
    text.use_fake_user = False
    show(text, tree)
    text[VIEW_HASH] = _digest(text.as_string())
    WARNINGS[text.name] = warnings
    found(text, text.as_string())
    return text, warnings


def is_applied(text):
    """True when the tree already holds what the view text says."""
    return text.get(VIEW_HASH) == _digest(text.as_string())


def apply_view(text, live=False):
    """Write a view text into its tree, keeping the text. Returns the tree; raises BnError.

    An unchanged text leaves the tree as it is, so its layout survives a look at the code.
    """
    tree = view_tree(text)
    source = text.as_string()
    if tree is not None and text.get(VIEW_HASH) == _digest(source):
        return tree
    trees = build_text(text, live)
    # Callees are written first: when the main graph was renamed in the text, it is the last one
    if trees and tree not in trees:
        tree = trees[-1]
    if tree is not None:
        show(text, tree)
    text[VIEW_HASH] = _digest(source)
    return tree


def close_view(text):
    """Write a view text into its tree, then remove the text. Returns the tree; raises BnError.

    On an error the text stays, with its diagnostics, so that it can be fixed.
    """
    tree = apply_view(text)
    WARNINGS.pop(text.name, None)
    DIAGNOSTICS.pop(text.name, None)
    LINT.pop(text.name, None)
    CHECKED.pop(text.name, None)
    bpy.data.texts.remove(text)
    return tree


def format_text(text, at=None):
    """Rewrite the text in the canonical form: its layout, and the inputs of Blender's nodes by name, as
    Blender's sockets go. True when it changed; raises BnError when it does not parse.

    `at`, a 1-based (line, column), names the inputs of the call there only and leaves the rest of the
    text as it is (naming.name_inputs)."""
    source = text.as_string()
    # Its type errors stay listed: the text that has them is checked anew once it changes
    try:
        with BlenderSchema() as schema:
            formatted = name_inputs(source, schema, text.name, modules.load, at=at, in_place=at is not None)
    except BnError as e:
        found(text, source, e.diagnostics)
        first = e.diagnostics[0]
        text.cursor_set(first.line - 1, character=max(0, first.col - 1))
        raise
    if formatted == source:
        return False
    line, char = text.current_line_index, text.current_character
    text.from_string(formatted)
    line = min(line, len(text.lines) - 1)
    text.cursor_set(line, character=min(char, len(text.lines[line].body)))
    return True


def import_file(path, warnings=None):
    """Build every graph of a .bn file into the trees of the same names. Returns them; raises BnError, OSError.
    `warnings` is a list the warnings of the build are added to (a datablock the file does not have).

    Its `use` lines find their modules in the .blend's texts, next to the file, then in the module folders.
    """
    source = modules.read(path)
    here = os.path.dirname(os.path.abspath(path))
    beside = {}

    def load(name, src):
        if src is None and bpy.data.texts.get(name + EXT) is None:
            found = modules.find(name, [here])
            if found is not None:
                beside[name] = found
                modules.pick(found)
        return modules.load(name, src, [here, *modules.FOLDERS])

    trees = build_source(source, os.path.basename(path), load, warnings)
    # A module found next to the file keeps its path, so that the text view of a tree finds it again
    for g in bpy.data.node_groups:
        name = g.get(modules.MODULE)
        if name in beside and not g.get(modules.SOURCE):
            g[modules.SOURCE] = beside[name]
    return _kept(trees)


def _kept(trees):
    """The trees, each kept by a fake user: an imported group nothing uses yet would be lost when
    the .blend is saved."""
    for t in trees:
        kept = owner(t) if t.is_embedded_data else t
        if kept is not None:
            kept.use_fake_user = True
    return trees


# Copy and paste of .bn text, kept apart from the clipboard: Blender has none in background mode.
CLIPBOARD = "clipboard"  # the file name in the errors of a pasted text: "clipboard:3:5  …"


def copy_text(tree, selected=False):
    """(text, warnings): the tree as a .bn text that builds on its own in another file.

    The groups it calls are in the text, those of a module too, unless the module is one of
    the standard library: that one stays a `use`, found in every file. With `selected`, only the
    selected nodes are written, as a graph "<tree> selection" (see `selection_copy`).
    """
    if not selected or not any(n.select for n in tree.nodes):
        return export_tree(tree, portable=True)
    copy = selection_copy(tree)
    try:
        return export_tree(copy, portable=True, name=f"{tree.name} selection")
    finally:
        bpy.data.node_groups.remove(copy)


def selection_copy(tree):
    """A copy of a node group with only its selected nodes, to remove once read.

    A zone goes whole, its input with its output. The links to the nodes left out go too: their
    inputs keep their values. The group's inputs stay only with a selected Group Input, its
    outputs with a selected Group Output.
    """
    keep = {n.name for n in tree.nodes if n.select}
    for n in tree.nodes:
        out = getattr(n, "paired_output", None)
        if n.bl_idname in ZONE_INPUTS and out is not None and (n.name in keep or out.name in keep):
            keep |= {n.name, out.name}
    copy = tree.copy()
    for n in [n for n in copy.nodes if n.name not in keep]:
        copy.nodes.remove(n)
    present = {n.bl_idname for n in copy.nodes}
    interface = copy.interface
    for io, node in (("INPUT", "NodeGroupInput"), ("OUTPUT", "NodeGroupOutput")):
        if node not in present:
            for item in [i for i in interface.items_tree if i.item_type == "SOCKET" and i.in_out == io]:
                interface.remove(item)
    for item in reversed(list(interface.items_tree)):
        if item.item_type == "PANEL" and not item.interface_items:
            interface.remove(item)
    return copy


def paste_text(source):
    """Build every graph of a pasted .bn text, as File > Import does. Returns its trees; raises BnError.

    The text is compiled and built in scratch trees first: on an error nothing of the file changes.
    A graph rebuilds the group (or material) of its name in place, as an import does.
    """
    return _kept(build_source(source, CLIPBOARD))


def entry(trees):
    """The one tree of a pasted text that no other one of it calls, or None when there are several."""
    called = {getattr(n, "node_tree", None) for t in trees for n in t.nodes}
    roots = [t for t in trees if t not in called]
    return roots[0] if len(roots) == 1 else None
