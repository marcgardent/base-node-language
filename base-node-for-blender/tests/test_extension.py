"""Tests for Blender base_node extension.

Run in Blender via:
    blender --background --factory-startup --python-exit-code 1 --python base-node-for-blender/tests/test_extension.py
"""

from __future__ import annotations

import difflib
import importlib.util
import os
import sys
import traceback
from pathlib import Path

EXT_DIR = Path(__file__).resolve().parents[1]
LIB_ROOT = EXT_DIR.parent
STDLIB_DIR = LIB_ROOT / "stdlib"

_spec = importlib.util.spec_from_file_location(
    "base_node", EXT_DIR / "__init__.py", submodule_search_locations=[str(EXT_DIR)]
)
base_node = importlib.util.module_from_spec(_spec)
sys.modules["base_node"] = base_node
_spec.loader.exec_module(base_node)

import bpy


def test_import_and_registration():
    """1. Verify import and registration of base_node."""
    print("-> Test 1: Verifying imports and registration...")
    assert base_node is not None, "base_node not found"
    assert base_node.lang is not None, "base_node.lang missing"
    assert base_node.host is not None, "base_node.host missing"

    # Register and unregister addon
    base_node.register()
    assert hasattr(bpy.types.NodeTree, "base_node_text"), "NodeTree.base_node_text missing"
    assert not hasattr(bpy.types.WindowManager, "base_node_sync"), "the text/tree selection sync is gone"
    print("   ✓ Imports and registration verified")


def test_stdlib_keeps_its_targets():
    """2. Each stdlib module builds in Blender and fits the targets its `// @target` promises."""
    print("-> Test 2: Verifying the targets of the stdlib...")
    from base_node.host.schema import BlenderSchema
    from base_node.lang import compile_source, header, parse
    from base_node.lang.targets import check_targets

    def loader(name: str, _caller: str):
        p = STDLIB_DIR / f"{name}.bn"
        if p.exists():
            return p.read_text(encoding="utf-8"), str(p)
        raise LookupError(f"Module stdlib not found: {name}")

    with BlenderSchema() as schema:
        for filepath in sorted(STDLIB_DIR.glob("*.bn")):
            source = filepath.read_text(encoding="utf-8")
            graphs = compile_source(source, schema, str(filepath), load=loader)
            assert len(graphs) > 0, f"No graph compiled for {filepath.name}"
            promised = header(source, filepath.name).target
            assert promised, f"{filepath.name} promises no target"
            issues = check_targets(parse(source, filepath.name), promised)
            assert issues == [], f"{filepath.name} outside {promised}:\n" + "\n".join(map(str, issues))
            print(f"   ✓ {filepath.name} ({len(graphs)} graphs) fits {', '.join(promised)}")


def test_build_and_round_trip():
    """3. Build and round-trip Tree -> Text -> Tree in Blender."""
    print("-> Test 3: Build and round-trip Tree -> Text -> Tree...")
    from base_node.host import build_source, export_tree

    src = """
geometry graph wave(geometry: Geometry, frequency: Float = 2.0, amplitude: Float = 0.5) -> Geometry {
  "Surface wave along Z"
  p = Position()
  h = sin(p.x * frequency) * amplitude
  return SetPosition(geometry, offset: CombineXYZ(z: h))
}
"""

    # 1. Text -> Tree
    trees = build_source(src, filename="wave.bn")
    assert len(trees) == 1, f"Expected 1 built tree, got {len(trees)}"
    tree = trees[0]
    assert tree.name == "wave", f"Unexpected tree name: {tree.name}"
    assert len(tree.nodes) > 0, "Built tree contains no nodes"

    # Verify attached properties
    assert hasattr(tree, "base_node_text"), "Property base_node_text missing on node group"

    # 2. Tree -> Text
    exported, warnings = export_tree(tree)
    assert "geometry graph wave" in exported, f"Header missing in export:\n{exported}"
    assert "SetPosition" in exported, f"SetPosition missing in export:\n{exported}"

    # 3. Text -> Tree (second pass)
    rebuilt_trees = build_source(exported, filename="wave_rebuilt.bn")
    assert len(rebuilt_trees) == 1
    rebuilt_tree = rebuilt_trees[0]
    assert rebuilt_tree.name == "wave"

    re_exported, _ = export_tree(rebuilt_tree)
    assert re_exported == exported, "Tree -> Text round trip is not stable"
    print("   ✓ Tree -> Text -> Tree round-trip verified")


def test_named_constants():
    """A literal bound to a name is a node of its own: the tree keeps `size = 10`."""
    print("-> Test: named constants survive Text -> Tree -> Text...")
    from base_node.host import build_source, export_tree

    src = """
geometry graph box() -> Geometry {
  size = 10
  scale = 2.5
  offset = (1.0, 2.0, 3.0)
  on = true
  tint = (1.0, 0.5, 0.0, 1.0)
  flat = (0.5, 0.25)
  g = Cube(CombineXYZ(size, scale, -size), size)
  return SetPosition(g.mesh, on, offset: offset + flat)
}
"""
    tree = build_source(src, filename="box.bn")[0]
    kinds = {n.name: n.bl_idname for n in tree.nodes}
    assert kinds["size"] == "FunctionNodeInputInt" and tree.nodes["size"].integer == 10, kinds
    assert kinds["scale"] == "ShaderNodeValue" and tree.nodes["scale"].outputs[0].default_value == 2.5, kinds
    assert kinds["offset"] == "FunctionNodeInputVector", kinds
    assert kinds["on"] == "FunctionNodeInputBool", kinds
    assert kinds["tint"] == "FunctionNodeInputColor", kinds
    # Two numbers: a Vector node in 2D, whose link gives z = 0 to a 3D input
    assert kinds["flat"] == "FunctionNodeInputVector" and tree.nodes["flat"].vector_dimensions == 2, kinds

    exported, warnings = export_tree(tree)
    assert not warnings, warnings
    for line in ("size = 10", "scale = 2.5", "offset = (1.0, 2.0, 3.0)", "on = true",
                 "tint = (1.0, 0.5, 0.0, 1.0)", "flat = (0.5, 0.25)", "-size", "offset + flat"):
        assert line in exported, f"'{line}' lost:\n{exported}"
    again, _ = export_tree(build_source(exported, filename="box2.bn")[0])
    assert again == exported, f"not stable:\n{again}"

    # A Value node made in Blender reads back with its value, not as Value()
    tree = bpy.data.node_groups.new("made_by_hand", "GeometryNodeTree")
    tree.interface.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    out = tree.nodes.new("NodeGroupOutput")
    value = tree.nodes.new("ShaderNodeValue")
    value.outputs[0].default_value = 10.0
    cube = tree.nodes.new("GeometryNodeMeshCube")
    tree.links.new(value.outputs[0], cube.inputs["Vertices X"])
    tree.links.new(cube.outputs[0], out.inputs[0])
    exported, _ = export_tree(tree)
    assert "value = 10.0" in exported, exported
    print("   ✓ Named constants kept")


def test_comments():
    """Comments are kept in the tree, on the nodes they go with, and written back in their places."""
    print("-> Test: comments survive Text -> Tree -> Text...")
    from base_node.host import build_source, export_tree
    from base_node.host.comments import KEY
    from base_node.lang import format_source

    src = """// Above the target line
// @target blender-geometry

// Before the uses
use math (bump)

geometry graph lift(geometry: Geometry) -> Geometry {
  // a callee
  return SetPosition(geometry, offset: CombineXYZ(z: 1.0))
}

// The terrain
geometry graph relief(geometry: Geometry, height: Float = 0.4) -> Geometry {  // its header
  "Displaces vertices"
  // the height
  // on two lines
  h = bump(length(Position()) / 3.0, 0.5, 0.2) * height  // after the code
  // goes on to the next statement: a name is no node
  hh = h
  "Block" #teal {
    // in the frame
    k = hh * 2.0
    // end of the frame
  }  // after its brace
  "Note" {
    // a note
  }
  r = repeat(3, g: geometry) {
    // in the zone
    g2 = SetPosition(g, offset: CombineXYZ(z: h + k))
    // the zone's return
    return (g: g2)  // its end
  }
  // the return
  return lift(r.g)
  // end of the graph
}
// below the graph
"""
    tree = build_source(src, filename="relief.bn")[-1]
    notes = {n.name: n[KEY].to_dict() for n in tree.nodes if KEY in n}
    assert tree[KEY].to_dict() == {
        "head": "// Above the target line", "target": "// @target blender-geometry", "file": "// Before the uses",
        "before": "// The terrain",
        "after": "// its header", "end": "// end of the graph", "below": "// below the graph"}, tree[KEY].to_dict()
    assert notes["h"] == {"before": "// the height\n// on two lines", "after": "// after the code"}, notes
    # `hh = h` makes no node: its comment goes with the next statement, the frame
    assert notes["k"] == {"before": "// in the frame"}, notes
    assert notes["Block"] == {"before": "// goes on to the next statement: a name is no node",
                              "end": "// end of the frame", "end_after": "// after its brace"}, notes
    assert notes["Note"] == {"end": "// a note"}, notes
    assert notes["r"] == {"return_before": "// the zone's return", "return_after": "// its end"}, notes
    assert notes["Group Output"] == {"before": "// the return"}, notes
    # In the callee too: before its return, with its Group Output
    assert bpy.data.node_groups["lift"].nodes["Group Output"][KEY].to_dict() == {"before": "// a callee"}

    exported, warnings = export_tree(tree)
    assert not warnings, warnings
    lines = [line.strip() for line in exported.split("\n")]
    for comment in src.split("\n"):
        if "//" in comment:
            assert comment.strip()[comment.strip().index("//"):] in exported, f"'{comment}' lost:\n{exported}"
    assert lines[0] == "// Above the target line" and lines[2] == "// @target blender-geometry", exported
    assert any(line.startswith("h = bump(") and line.endswith(" * height  // after the code") for line in lines), \
        exported
    assert "}  // after its brace" in lines and "return g2  // its end" in lines, exported
    assert format_source(exported) == exported, "not in the canonical layout"
    again, _ = export_tree(build_source(exported, filename="relief2.bn")[-1])
    assert again == exported, f"not stable:\n{again}"

    # Written from the nodes: the text gives it back before the node's statement, a statement of its own
    from base_node.host.comments import set_comment, room
    from base_node.host.arrange import _box
    tree = build_source(src, filename="relief.bn")[-1]
    length = next(n for n in tree.nodes if n.bl_idname == "ShaderNodeVectorMath")
    set_comment(length, "before", ["written in the graph", "", "after a blank"])
    exported, _ = export_tree(tree)
    assert "  // written in the graph\n  //\n  // after a blank\n  vector_math = length(Position())" in exported, \
        exported
    set_comment(length, "before", [])
    assert KEY not in length, "an empty comment stays"
    set_comment(tree.nodes["h"], "before", [])
    assert tree.nodes["h"][KEY].to_dict() == {"after": "// after the code"}, "the other slots stay"

    # A new tree leaves room over its commented nodes: no other node in their comment's box
    tree = build_source(src.replace("relief", "relief_fresh"), filename="fresh.bn")[-1]
    boxes = {n.name: _box(n, 1.0) for n in tree.nodes if n.bl_idname != "NodeFrame"}
    for n in tree.nodes:
        above = room(n)[0]
        if not above or n.bl_idname == "NodeFrame":
            continue
        x, top = n.location_absolute
        for other, b in boxes.items():
            hit = b.x < x + n.width and x < b.x + b.width and b.y - b.height < top + above and top < b.y
            assert other == n.name or not hit, f"'{other}' lies in the comment of '{n.name}'"
    # A note grows to hold what it says
    note = tree.nodes["Note"]
    assert note.height >= room(note)[1], (note.height, room(note))

    # Built again without them, the tree drops them
    tree = build_source("""geometry graph relief(geometry: Geometry) -> Geometry {
  return geometry
}
""", filename="relief.bn")[-1]
    assert KEY not in tree and not any(KEY in n for n in tree.nodes), "comments left behind"
    print("   ✓ Comments kept on their nodes")


def test_targets_and_linter():
    """4. A tree promises no target; the text's promise comes back with it, and the linter shows what breaks it."""
    print("-> Test 4: Verifying targets on export & highlighter linter...")
    from base_node.host import build_source, export_tree
    from base_node.lang.lexer import tokenize
    from base_node.ui.highlight import classify

    src = """
geometry graph spiral(r: Float = 1.0) -> Geometry {
  c = CurveCircle(radius: r)
  return c.curve
}
"""
    exported, _ = export_tree(build_source(src, filename="spiral.bn")[0])
    assert "@target" not in exported and "@profile" not in exported, exported
    exported, _ = export_tree(build_source("// @target blender-gp\n" + src, filename="spiral2.bn")[0])
    assert exported.startswith("// @target blender-gp\n\n"), exported

    toks = tokenize("use curves2d as c2\n", strict=False)
    classes = dict((t.text, c) for t, c in classify(toks))
    assert classes.get("curves2d") == "namespace"

    toks_call = tokenize("c2::parallel_contour_2d(curve)\n", strict=False)
    classes_call = dict((t.text, c) for t, c in classify(toks_call))
    assert classes_call.get("parallel_contour_2d") == "stdlib_func"

    # Outside the nodes the text's @target allows, CurveCircle is flagged as warning
    toks_node = tokenize("c = CurveCircle(radius: 1.0)\n", strict=False)
    ctx = {"mode": "standard", "allowed_nodes": {"Math", "VectorMath"}, "declared": set()}
    classes_node = dict((t.text, c) for t, c in classify(toks_node, ctx))
    assert classes_node.get("CurveCircle") == "warning"

    print("   ✓ Targets on export and highlighter linter verified")


def test_pipe_symbol():
    """The pipes drawn as ▷: real ones only, and not on the lines being edited."""
    print("-> Test: Pipe symbol...")
    from base_node.lang.lexer import tokenize
    from base_node.ui import pipes, prefs

    line = '  return g |> F(s: "a |> b") |> G()  // c |> d'
    assert pipes.columns(tokenize(line, strict=False)) == [11, 29], "only the pipes outside strings and comments"
    assert pipes.columns(tokenize("a |>", strict=False)) == [2]
    assert pipes.columns(tokenize("    |> F()", strict=False)) == [4], "a step on its own line, as printed"

    text = bpy.data.texts.new("pipes.bn")
    text.from_string("a\nb |> F()\nc |> G()\nd |> H()\n")
    text.cursor_set(1)
    assert list(pipes.raw_lines(text)) == [1], "the cursor's line keeps |>"
    text.cursor_set(3)
    text.select_set(3, 0, 1, 2)  # a selection made upward still covers its lines
    assert list(pipes.raw_lines(text)) == [1, 2, 3]
    bpy.data.texts.remove(text)

    assert prefs.DEFAULTS.pipe_symbol is True, "on by default"
    assert pipes.mono_font() >= 0
    print("   ✓ Pipe symbol verified")


def test_live_apply():
    """While typing, a valid text is built into its tree; an invalid one changes nothing and keeps the cursor."""
    print("-> Test: Live apply...")
    from base_node.host import build_source
    from base_node.ui import actions, live, prefs

    assert prefs.DEFAULTS.live_apply is True, "on by default"
    tree = build_source("geometry graph LiveDemo(geometry: Geometry) -> Geometry {\n  return geometry\n}\n")[0]
    text, _ = actions.open_view(tree)
    assert actions.is_applied(text)

    text.from_string(text.as_string().replace("return geometry", "return geometry |> SetShadeSmooth("))
    row = next(i for i, line in enumerate(text.lines) if "return" in line.body)
    text.cursor_set(row, character=2)
    try:
        actions.apply_view(text, live=True)
        raise AssertionError("an invalid text must not build")
    except Exception as e:
        assert type(e).__name__ == "BnError", e
    assert (text.current_line_index, text.current_character) == (row, 2), "a live build leaves the cursor"
    assert actions.DIAGNOSTICS.get(text.name), "the errors are listed"
    assert not any(n.bl_idname == "GeometryNodeSetShadeSmooth" for n in tree.nodes), "the tree keeps what it had"

    text.from_string(text.as_string().replace("SetShadeSmooth(", "SetShadeSmooth()"))
    actions.apply_view(text, live=True)
    assert any(n.bl_idname == "GeometryNodeSetShadeSmooth" for n in tree.nodes)
    assert actions.is_applied(text) and not actions.DIAGNOSTICS.get(text.name)

    # A text is built once it has rested, and only once per source
    live._seen.clear(), live._tried.clear()
    assert not live.due("t", "a", 0.0), "first seen"
    assert not live.due("t", "a", 0.2), "not rested yet"
    assert live.due("t", "a", 0.2 + live.REST)
    live._tried["t"] = "a"
    assert not live.due("t", "a", 5.0), "already built"
    assert not live.due("t", "ab", 5.0), "changed again: rests anew"
    live._seen.clear(), live._tried.clear()

    actions.close_view(text)
    bpy.data.node_groups.remove(tree)
    print("   ✓ Live apply verified")


def test_live_diagnostics():
    """A shown text is checked once it pauses, without a build; its errors keep their place."""
    print("-> Test: Live diagnostics...")
    import time
    from base_node.ui import actions, live, prefs

    wave = (LIB_ROOT / "python" / "tests" / "fixtures" / "wave.bn").read_text(encoding="utf-8")
    text = bpy.data.texts.new("live_wave.bn")
    text.from_string(wave.replace("sin(", "sinn("))
    groups = len(bpy.data.node_groups)
    shown = live.shown_texts
    live.shown_texts = lambda: {text: []}  # no Text Editor in background mode
    try:
        live._seen.clear(), live._tried.clear()
        live.look(0.0)
        assert text.name not in actions.CHECKED, "just changed: not checked yet"
        live.look(0.05)
        assert text.name not in actions.CHECKED, "typing fast: not checked yet"
        live.look(live.PAUSE + 0.01)
        assert actions.CHECKED[text.name] == text.as_string()
        (d,) = actions.DIAGNOSTICS[text.name]
        assert (d.file, d.line, d.col) == ("live_wave.bn", 3, 7), d
        assert "unknown node 'sinn'" in d.message and "did you mean sin" in d.message, d.message
        assert len(bpy.data.node_groups) == groups, "a check builds nothing"

        # The jump selects what the error points to, the cursor at its start
        actions.select_at(text, d.line, d.col)
        assert (text.current_line_index, text.current_character) == (2, 6)
        assert (text.select_end_line_index, text.select_end_character) == (2, 10)

        # Fixed: the errors go at the next pause, the plain text is never built
        text.from_string(wave)
        live.look(1.0)
        assert text.name in actions.DIAGNOSTICS, "still typing"
        live.look(1.0 + live.PAUSE + 0.01)
        assert text.name not in actions.DIAGNOSTICS and actions.CHECKED[text.name] == wave
        live.look(5.0)
        assert len(bpy.data.node_groups) == groups, "only the text of a tree is built"

        # The text of a tree: checked even when it does not follow the text; built only when it does
        tree = bpy.data.node_groups.new("LiveWave", "GeometryNodeTree")
        view, _ = actions.open_view(tree)
        live.shown_texts = lambda: {view: []}
        bad = wave.replace("geometry graph wave", "geometry graph LiveWave").replace("p.x", "pp.x")
        view.from_string(bad)
        options = prefs.get()
        before = options.live_apply
        options.live_apply = False
        try:
            live.look(10.0), live.look(10.0 + live.PAUSE + 0.01)
            assert "did you mean p?" in actions.DIAGNOSTICS[view.name][0].message
            view.from_string(bad.replace("pp.x", "p.x"))
            live.look(20.0), live.look(20.0 + live.REST + 0.01)
            assert not actions.DIAGNOSTICS.get(view.name)
            assert not any(n.bl_idname == "GeometryNodeSetPosition" for n in tree.nodes), "not applied"
            options.live_apply = True
            live.look(21.0), live.look(30.0)
            assert any(n.bl_idname == "GeometryNodeSetPosition" for n in tree.nodes), "applied once rested"
        finally:
            options.live_apply = before
        # An invalid text of a tree is not built again: its check already found why
        view.from_string(bad)
        live.look(40.0), live.look(40.0 + live.PAUSE + 0.01)
        assert actions.DIAGNOSTICS.get(view.name)
        calls = []
        apply_view = actions.apply_view
        actions.apply_view = lambda *a, **k: calls.append(a)
        try:
            live.look(40.0 + live.REST + 0.1)
        finally:
            actions.apply_view = apply_view
        assert not calls and live._tried[view.name] == bad

        # A check is cheap: well within a tick
        start = time.perf_counter()
        actions.check_text(text)
        assert time.perf_counter() - start < live.TICK

        # The underline: under the token, on the line's bottom, only for the text shown and its lines on screen
        from types import SimpleNamespace
        from base_node.lang import Diagnostic
        from base_node.ui import highlight
        text.from_string(wave.replace("sin(", "sinn("))
        space = SimpleNamespace(text=text, font_size=12, show_word_wrap=False, top=0,
                                region_location_from_cursor=lambda line, col: (10 * col, 400 - 20 * line))
        region = SimpleNamespace(height=500)
        bars = highlight.underlines(space, region, [
            Diagnostic(text.name, 3, 7, "the typo"),
            Diagnostic("other.bn", 3, 7, "in a module"),
            Diagnostic(text.name, 99, 1, "a line gone"),
        ])
        ((x0, y0, x1, y1),) = bars
        assert (x0, x1) == (60, 100) and y0 == 400 - 20 * 2 + 1 and y1 > y0, bars
        space.region_location_from_cursor = lambda line, col: (10 * col, 1200 - 20 * line)
        assert not highlight.underlines(space, region, [Diagnostic(text.name, 3, 7, "")]), "scrolled away"
    finally:
        live.shown_texts = shown
        live._seen.clear(), live._tried.clear()
    for t in (text, view):
        bpy.data.texts.remove(t)
    bpy.data.node_groups.remove(tree)
    print("   ✓ Live diagnostics verified")


def test_tree_without_output():
    """A tree with no Group Output node reads as a graph that returns nothing, and builds again."""
    print("-> Test: Tree without output...")
    from base_node.host import build_source, export_tree

    tree = bpy.data.node_groups.new("NoOutput", "GeometryNodeTree")
    tree.interface.new_socket("Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
    tree.interface.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    tree.nodes.new("NodeGroupInput")
    source, _ = export_tree(tree)
    assert "return ()" in source, source
    build_source(source, "no_output.bn")
    bpy.data.node_groups.remove(tree)
    print("   ✓ Tree without output verified")


def test_multi_input_order():
    """The values of a multi-input are joined in the order written, and read back in that order."""
    print("-> Test: Multi-input order...")
    from base_node.host import build_source, export_tree

    src = """geometry graph joined_in_order() -> Geometry {
  return JoinGeometry(
    Points(count: 1, position: (1.0, 0.0, 0.0)),
    Points(count: 1, position: (2.0, 0.0, 0.0)),
    Points(count: 1, position: (3.0, 0.0, 0.0)))
}
"""
    (tree,) = build_source(src, "joined_in_order.bn")
    join = next(n for n in tree.nodes if n.bl_idname == "GeometryNodeJoinGeometry")
    # Blender lists the links of a multi-input as it joins them and draws them: top one first
    top_down = [l.from_node.inputs["Position"].default_value[0] for l in join.inputs[0].links]
    assert top_down == [1.0, 2.0, 3.0], top_down

    ob = bpy.data.objects.new("joined_in_order", bpy.data.meshes.new("joined_in_order"))
    bpy.context.scene.collection.objects.link(ob)
    try:
        ob.modifiers.new("join", "NODES").node_group = tree
        evaluated = ob.evaluated_get(bpy.context.evaluated_depsgraph_get())
        geometry = evaluated.evaluated_geometry()   # kept: the cloud lives as long as it
        xs = [round(p.co.x, 6) for p in geometry.pointcloud.points]
        assert xs == [1.0, 2.0, 3.0], f"points joined as {xs}"
    finally:
        bpy.data.objects.remove(ob)

    exported, _ = export_tree(tree)
    assert exported.index("1.0, 0.0") < exported.index("2.0, 0.0") < exported.index("3.0, 0.0"), exported
    (rebuilt,) = build_source(exported, "joined_in_order.bn")
    assert export_tree(rebuilt)[0] == exported, "multi-input round trip is not stable"
    print("   ✓ Multi-input order verified")


def test_planar2d_shape_builder_pick():
    """planar2d's shape builder pick keeps, whole and in place, the regions the seed points pick, every seed's:
    the one a seed is in, or the nearest within pick_radius, and deletes the others (T-136)."""
    print("-> Test: planar2d shape builder pick...")
    import numpy as np
    from base_node.host import build_source

    # Three discs: A of radius 1 at x = 0, B of radius 1 at x = 3, C of radius 2 at x = 8. One seed is in A,
    # the other at the centre of C, 2 from its edge, further than pick_radius: both are in their region
    src = """use planar2d

geometry graph pick_probe_{n}() -> Geometry {{
  discs = JoinGeometry(
    CurveCircle(radius: 1.0).curve,
    TransformGeometry(CurveCircle(radius: 1.0).curve, translation: (3.0, 0.0, 0.0)),
    TransformGeometry(CurveCircle(radius: 2.0).curve, translation: (8.0, 0.0, 0.0)))
  seeds = JoinGeometry(
    Points(count: 1, position: (0.2, 0.0, 0.0)),
    Points(count: 1, position: ({x}, 0.0, 0.0)))
  return shape_builder_pick(discs, seeds, pick_radius: 0.5)
}}
"""
    before = set(bpy.data.node_groups)
    ob = bpy.data.objects.new("pick_probe", bpy.data.meshes.new("pick_probe"))
    bpy.context.scene.collection.objects.link(ob)
    modifier = ob.modifiers.new("pick", "NODES")

    def picked(offset):
        """The points of the regions kept, the second seed offset from C's centre towards B."""
        n = len(bpy.data.node_groups)
        build_source(src.format(n=n, x=8.0 - offset), f"pick_probe_{n}.bn")
        modifier.node_group = bpy.data.node_groups[f"pick_probe_{n}"]
        geometry = ob.evaluated_get(bpy.context.evaluated_depsgraph_get()).evaluated_geometry()
        mesh = geometry.mesh   # lives as long as geometry
        p = np.zeros(len(mesh.vertices) * 3)
        mesh.vertices.foreach_get("co", p)
        return p.reshape(-1, 3)

    try:
        p = picked(0.0)
        assert np.abs(p[:, 2]).max(initial=0.0) < 1e-6, f"regions moved off the plane, z {p[:, 2].min()}"
        a, b, c = p[:, 0] < 1.5, (p[:, 0] > 1.5) & (p[:, 0] < 4.5), p[:, 0] > 5.5
        # Whole: the fill of a circle of 32 points keeps its 32 points
        assert (a.sum(), b.sum(), c.sum()) == (32, 0, 32), f"A, B, C keep {a.sum()}, {b.sum()}, {c.sum()} points"
        assert np.allclose(np.hypot(p[c, 0] - 8.0, p[c, 1]), 2.0, atol=1e-5), "C is not whole or not in place"
        # A seed outside C, 0.3 from its edge, picks it; at 0.7, further than pick_radius, nothing
        assert (picked(2.3)[:, 0] > 5.5).sum() == 32, "a seed 0.3 from C does not pick it"
        p = picked(2.7)
        assert ((p[:, 0] < 1.5).sum(), (p[:, 0] > 5.5).sum()) == (32, 0), "a seed 0.7 from C picks it"
    finally:
        bpy.data.objects.remove(ob)
        bpy.data.batch_remove([g for g in bpy.data.node_groups if g not in before])
    print("   ✓ planar2d shape builder pick: every seed's region kept whole and in place, the others deleted")


RUST = """shader graph rust(uv: Vector) -> Shader {
  n = NoiseTexture(vector: uv, scale: 8.0)
  return PrincipledBSDF(
    base_color: ColorRamp(factor: n.factor).color,
    roughness: n.factor * 0.5 + 0.4)
}
"""

LOOK = """compositor graph look(image: Color) -> Color {
  return image
    |> Glare(type: "Fog Glow").image
    |> ColorBalance("Base Lift": 0.95)
}
"""


def test_shader_and_compositor():
    """Shader and compositor graphs build, read back the same, and feed a material or the Composite."""
    print("-> Test: Shader and compositor trees...")
    from base_node.host import build_source, export_tree
    from base_node.lang import BnError

    for source, tree_type in ((RUST, "ShaderNodeTree"), (LOOK, "CompositorNodeTree")):
        tree, = build_source(source, "t.bn")
        assert tree.bl_idname == tree_type, tree.bl_idname
        text, warnings = export_tree(tree)
        assert text == source and not warnings, (text, warnings)

    # The shader group is a material: its node feeds the Material Output
    rust = bpy.data.node_groups["rust"]
    mat = bpy.data.materials["rust"]
    group = next(n for n in mat.node_tree.nodes if n.bl_idname == "ShaderNodeGroup")
    out = next(n for n in mat.node_tree.nodes if n.bl_idname == "ShaderNodeOutputMaterial")
    assert group.node_tree == rust
    assert [(link.from_node, link.from_socket.name) for link in out.inputs["Surface"].links] == [(group, "Shader")]
    # Its inputs are the material's settings: they stay through a rebuild, and no other material is made
    group.inputs["uv"].default_value = (1.0, 2.0, 3.0)
    build_source(RUST, "t.bn")
    assert tuple(group.inputs["uv"].default_value) == (1.0, 2.0, 3.0)
    assert [m.name for m in bpy.data.materials if m.name.startswith("rust")] == ["rust"]

    # The compositor group is the scene's compositor, once
    scene = bpy.context.scene
    build_source(LOOK, "t.bn")
    assert [e.node_group for e in scene.compositor_effects] == [bpy.data.node_groups["look"]]

    # Named outputs go to the Material Output's sockets of the same names; a called graph is no material
    build_source("""shader graph bumpy_part() -> Float {
  return 0.5
}

shader graph bumpy() -> (surface: Shader, displacement: Vector) {
  return (surface: DiffuseBSDF(), displacement: Displacement(height: bumpy_part()))
}
""", "t.bn")
    out = next(n for n in bpy.data.materials["bumpy"].node_tree.nodes if n.bl_idname == "ShaderNodeOutputMaterial")
    assert [(s.name, [link.from_socket.name for link in s.links]) for s in out.inputs if s.links] == \
        [("Surface", ["surface"]), ("Displacement", ["displacement"])]
    assert "bumpy_part" not in bpy.data.materials

    # A material of that name the builder did not make is left as it is
    mine = bpy.data.materials.new("mine")
    nodes = [n.bl_idname for n in mine.node_tree.nodes]
    build_source("shader graph mine() -> Shader {\n  return DiffuseBSDF()\n}\n", "t.bn")
    assert [n.bl_idname for n in mine.node_tree.nodes] == nodes
    assert [m.name for m in bpy.data.materials if m.name.startswith("mine")] == ["mine"]

    # A datablock property is written by its name
    image = bpy.data.images.new("brick", 4, 4)
    wall = """shader graph wall(uv: Vector) -> Shader {
  t = ImageTexture(vector: uv, image: "brick")
  return DiffuseBSDF(color: t.color)
}
"""
    tree, = build_source(wall, "t.bn")
    assert next(n for n in tree.nodes if n.bl_idname == "ShaderNodeTexImage").image == image
    assert export_tree(tree)[0] == wall
    # A ramp is written in the text
    ramp = tree.nodes.new("ShaderNodeValToRGB")
    ramp.color_ramp.elements.new(0.5).color = (1.0, 0.5, 0.0, 1.0)
    tree.links.new(ramp.outputs["Color"], next(n for n in tree.nodes if n.bl_idname == "ShaderNodeBsdfDiffuse").inputs[0])
    text, warnings = export_tree(tree)
    assert ("      color_ramp: Ramp(\n"
            "        (0.0, (0.0, 0.0, 0.0, 1.0)),\n"
            "        (0.5, (1.0, 0.5, 0.0, 1.0)),\n"
            "        (1.0, (1.0, 1.0, 1.0, 1.0)))).color)\n") in text and not warnings, (text, warnings)

    def error(source):
        try:
            build_source(source, "t.bn")
        except BnError as e:
            return str(e.diagnostics[0])
        raise AssertionError(f"built: {source}")

    assert error('shader graph w() -> Shader {\n  return DiffuseBSDF(color: ImageTexture(image: "nope").color)\n}') \
        == "t.bn:2:29  image: Image 'nope' not found in file"
    assert error("shader graph g(g: Geometry) -> Shader {\n  return DiffuseBSDF()\n}") \
        == "t.bn:1:1  'g': a shader tree has no Geometry socket; types: Float, Int, Bool, Vector, Color, " \
           "String, Menu, Shader, Bundle, Closure"
    assert error("compositor graph c(x: Float) -> Float {\n  s = simulate(v: x) {\n    return (v: v)\n  }\n"
                 "  return s.v\n}") == "t.bn:2:7  simulate does not exist in a compositor tree"

    # The Node Editor's text view takes shader and compositor groups, and a material's own tree
    assert shown(rust) == rust and shown(bpy.data.node_groups["look"]) is not None
    assert shown(mat.node_tree) == mat.node_tree
    world = bpy.data.worlds.new("w")  # with a tree of its own
    assert shown(world.node_tree) is None, "a world's tree is no material"
    bpy.data.worlds.remove(world)

    for e in list(scene.compositor_effects):
        scene.compositor_effects.remove(e)
    for name in ("rust", "bumpy", "mine"):
        bpy.data.materials.remove(bpy.data.materials[name])
    for name in ("rust", "look", "bumpy", "bumpy_part", "mine", "wall"):
        bpy.data.node_groups.remove(bpy.data.node_groups[name])
    bpy.data.images.remove(image)
    print("   ✓ Shader and compositor trees verified")


def shown(tree):
    """The tree the Node Editor's text view takes when it shows this one, else None."""
    from types import SimpleNamespace
    from base_node.ui.operators import edit_tree
    return edit_tree(SimpleNamespace(space_data=SimpleNamespace(type="NODE_EDITOR", edit_tree=tree)))


KEPT = """// @target blender-geometry

geometry graph kept(geometry: Geometry, source: Geometry) -> Geometry {
  return geometry
    |> SeparateGeometry(selection: Position().z > 0.0).selection
    |> TransferAttributes(
      source: source,
      attribute_names: FieldToList("Attribute Names": "id")).target
    |> SetPosition(offset: CombineXYZ(z: 1.0))
}
"""


CONTRAST = """use math (gain, luminance)

compositor graph contrast(image: Color, amount: Float = 0.3 in 0.0..1.0) -> Color {
  return Mix(
    factor: gain(x: luminance(image), contrast: amount),
    a: image,
    b: (1.0, 1.0, 1.0, 1.0),
    data_type: RGBA)
}
"""


def test_module_graphs_in_other_trees():
    """A module's geometry graph called from a compositor graph is built again in a compositor group,
    and read back as the use and the call it was."""
    print("-> Test: Module graphs in other kinds of trees...")
    from base_node.host import build_source, export_tree, modules
    from base_node.lang import BnError

    before = set(bpy.data.node_groups)
    tree, = build_source(CONTRAST, "t.bn")
    groups = {g.name: g for g in bpy.data.node_groups}
    # gain calls bias: each has its compositor variant, which says the graph it is
    for name in ("bias", "gain", "luminance"):
        variant = groups[f"{name} (Compositor)"]
        assert variant.bl_idname == "CompositorNodeTree", variant.bl_idname
        assert (variant[modules.GRAPH], variant[modules.MODULE]) == (name, "math")
        assert groups[name].bl_idname == "GeometryNodeTree"
    called = {n.node_tree.name for n in tree.nodes if n.bl_idname == "CompositorNodeGroup"}
    assert called == {"gain (Compositor)", "luminance (Compositor)"}, called
    assert {n.node_tree.name for n in groups["gain (Compositor)"].nodes if n.bl_idname == "CompositorNodeGroup"} \
        == {"bias (Compositor)"}
    text, warnings = export_tree(tree)
    assert text == CONTRAST and not warnings, (text, warnings)
    # Built again, the variants are rebuilt in place
    build_source(text, "t.bn")
    assert sorted(g.name for g in bpy.data.node_groups) == sorted(groups), \
        sorted(g.name for g in bpy.data.node_groups)

    # A graph whose nodes the tree lacks is refused with the reason
    try:
        build_source("use math (random_direction)\n\nshader graph s(i: Int) -> Vector {\n"
                     "  return random_direction(i, 1)\n}\n", "s.bn")
    except BnError as e:
        message = str(e.diagnostics[0])
    else:
        raise AssertionError("random_direction built in a shader tree")
    assert message.startswith("s.bn:4:10  'random_direction' is a geometry graph that cannot be built in a shader "
                              "tree: unknown node 'RandomValue' in a shader tree"), message
    # A comparison is no such node: Compare in the geometry tree, Math in a shader tree, which has no Compare
    built = build_source("use math (gain)\n\nshader graph s(x: Float) -> Float {\n  return gain(x, 0.3)\n}\n", "s.bn")
    variant = bpy.data.node_groups["gain (Shader)"]
    assert not [n for n in variant.nodes if n.bl_idname == "FunctionNodeCompare"]
    assert [n.operation for n in variant.nodes if n.bl_idname == "ShaderNodeMath"
            and n.operation in ("LESS_THAN", "GREATER_THAN")] == ["LESS_THAN"]
    assert [n.operation for n in bpy.data.node_groups["gain"].nodes if n.bl_idname == "FunctionNodeCompare"] \
        == ["LESS_THAN"]
    assert built

    bpy.data.batch_remove([g for g in bpy.data.node_groups if g not in before])
    print("   ✓ Module graphs in other kinds of trees verified")


TEMPLATES = """geometry graph attribute_or<T: Float | Vector | Color>(name: String, fallback: T) -> (value: T) {
  a = NamedAttribute(name: name, data_type: T)
  return (value: Switch(switch: a.exists, false_: fallback, true_: a.attribute, input_type: T))
}
"""

FALLBACKS = """// @target blender-geometry

use attrs (attribute_or)

geometry graph fallbacks(geometry: Geometry, offset: Vector) -> Geometry {
  rest = attribute_or(name: "rest", fallback: offset)
  tint = attribute_or<Color>(name: "tint")
  return geometry
    |> SetPosition(offset: rest)
    |> StoreNamedAttribute(name: "col", value: tint, data_type: FLOAT_COLOR)
}
"""


def test_templates():
    """A module's template is built into a group for each type it is called with, and read back as
    the use and the calls it was: the type written only where the arguments do not infer it."""
    print("-> Test: Templates...")
    from base_node.host import build_source, export_tree, modules

    before = set(bpy.data.node_groups)
    module = bpy.data.texts.new("attrs.bn")
    module.write(TEMPLATES)
    try:
        tree, = build_source(FALLBACKS, "t.bn")
        groups = {g.name: g for g in bpy.data.node_groups}
        for t, setting in (("Vector", "FLOAT_VECTOR"), ("Color", "FLOAT_COLOR")):
            group = groups[f"attribute_or ({t})"]
            assert (group[modules.GRAPH], group[modules.MODULE]) == ("attribute_or", "attrs")
            assert modules.template_of(group) == ([t], [[1]]), modules.template_of(group)
            attribute = next(n for n in group.nodes if n.bl_idname == "GeometryNodeInputNamedAttribute")
            assert attribute.data_type == setting, attribute.data_type
        assert "attribute_or" not in groups
        text, warnings = export_tree(tree)
        assert text == FALLBACKS and not warnings, (text, warnings)
        # Built again, the groups are rebuilt in place
        build_source(text, "t.bn")
        assert sorted(g.name for g in bpy.data.node_groups) == sorted(groups)
    finally:
        bpy.data.texts.remove(module)
        bpy.data.batch_remove([g for g in bpy.data.node_groups if g not in before])
    print("   ✓ Templates verified")


class CompositorBench:
    """A scene of its own whose compositor renders one node group at a time, read back as 32-bit floats.

    Its images are float buffers of made up pixels, premultiplied and not color managed; a group's input is
    fed by one of them, by its name, or else by the output of that name of the scene's Render Layers."""

    def __init__(self, name: str, width: int, height: int):
        import tempfile

        self.images_before = set(bpy.data.images)
        self.scene = scene = bpy.data.scenes.new(f".base_node {name}")
        scene.render.engine = "CYCLES"
        scene.cycles.samples, scene.cycles.device = 1, "CPU"
        r = scene.render
        r.resolution_x, r.resolution_y, r.resolution_percentage = width, height, 100
        r.image_settings.file_format, r.image_settings.color_depth = "OPEN_EXR", "32"
        r.image_settings.color_mode = "RGBA"
        scene.view_settings.view_transform = "Standard"
        self.camera = bpy.data.objects.new(f".base_node {name}", bpy.data.cameras.new(f".base_node {name}"))
        scene.collection.objects.link(self.camera)
        scene.camera = self.camera
        self.objects = [self.camera]
        self.tree = bpy.data.node_groups.new(f".base_node {name}", "CompositorNodeTree")
        self.tree.interface.new_socket("Image", in_out="OUTPUT", socket_type="NodeSocketColor")
        scene.compositor_effects.new(name=self.tree.name).node_group = self.tree
        self.name = name
        self.images: dict = {}
        self.path = os.path.join(tempfile.mkdtemp(prefix=f"base-node-{name}-"), f"{name}.exr")

    def image(self, name: str, pixels) -> None:
        """An image of these pixels (height, width, 4), to feed a group's input by its name."""
        height, width = pixels.shape[:2]
        image = bpy.data.images.new(f".base_node {self.name} {name}", width, height, alpha=True, float_buffer=True)
        image.colorspace_settings.name = "Non-Color"
        image.alpha_mode = "PREMUL"
        image.pixels[:] = pixels.ravel()
        self.images[name] = image

    def render(self, group: str, feed: dict, inputs: dict | None = None, output=0):
        """The group's output, its inputs fed by the images or Render Layers outputs named in feed."""
        import numpy as np

        tree = self.tree
        tree.nodes.clear()
        node = tree.nodes.new("CompositorNodeGroup")
        node.node_tree = bpy.data.node_groups[group]
        layers = None
        for key, name in feed.items():
            if name in self.images:
                source = tree.nodes.new("CompositorNodeImage")
                source.image = self.images[name]
                tree.links.new(source.outputs["Image"], node.inputs[key])
            else:
                if layers is None:
                    layers = tree.nodes.new("CompositorNodeRLayers")
                    layers.scene = self.scene
                tree.links.new(layers.outputs[name], node.inputs[key])
        for k, v in (inputs or {}).items():
            node.inputs[k].default_value = v
        tree.links.new(node.outputs[output], tree.nodes.new("NodeGroupOutput").inputs[0])
        r = self.scene.render
        r.filepath = self.path
        bpy.ops.render.render(write_still=True, scene=self.scene.name)
        image = bpy.data.images.load(r.filepath)
        try:
            return np.array(image.pixels[:]).reshape(r.resolution_y, r.resolution_x, 4)
        finally:
            bpy.data.images.remove(image)

    def close(self) -> None:
        """Removes the scene, its objects, its tree and the images made since it was, its render's among them."""
        bpy.data.scenes.remove(self.scene)
        for obj in self.objects:
            bpy.data.objects.remove(obj)
        bpy.data.batch_remove([i for i in bpy.data.images if i not in self.images_before])
        bpy.data.node_groups.remove(self.tree)


def assert_close(what: str, got, expected, tolerance: float = 1e-5) -> None:
    """got is expected, by an error relative past 1: large values are as precise as 32-bit floats keep them."""
    import numpy as np

    error = (np.abs(got - expected) / np.maximum(np.abs(expected), 1.0)).max()
    assert error < tolerance, f"{what}: off by {error}"


def test_mask2d_render():
    """mask2d's masks, rendered by the compositor at 16:9, are the signed distances of their shapes in
    the image's uniform coordinates, their edge smoothed over one pixel plus the feather."""
    print("-> Test: mask2d rendered by the compositor...")
    import math

    import numpy as np
    from base_node.host import build_source

    W, H = 64, 36
    before = set(bpy.data.node_groups)
    build_source("use mask2d (box_mask, circle_mask)\n\n"
                 "compositor graph mask_probe(image: Color) -> Float {\n  return circle_mask(image).mask\n}\n", "m.bn")
    bench = CompositorBench("masks", W, H)

    def render(group, inputs):
        return bench.render(group, {"image": "Image"}, inputs, "Mask")[..., 0]

    # Uniform coordinates of each pixel's center: origin at the middle, y up, the width from -1 to 1
    px = 2.0 / max(W, H)
    i, j = np.meshgrid(np.arange(W), np.arange(H))
    x, y = (i + 0.5 - W / 2) * px, (j + 0.5 - H / 2) * px

    def mask(d, feather=0.0):
        e = (px + feather) * 0.5
        t = np.clip((d + e) / (2 * e), 0, 1)
        return 1 - t * t * (3 - 2 * t)

    try:
        got = render("circle mask", {"radius": 0.4, "feather": 0.1, "center": (0.3, -0.1)})
        want = mask(np.hypot(x - 0.3, y + 0.1) - 0.4, 0.1)
        assert np.abs(got - want).max() < 1e-4, np.abs(got - want).max()

        c, s = math.cos(-0.4), math.sin(-0.4)
        u, v = c * (x + 0.2) - s * (y - 0.1), s * (x + 0.2) + c * (y - 0.1)
        qx, qy = abs(u) - 0.5 + 0.1, abs(v) - 0.3 + 0.1
        d = np.hypot(np.maximum(qx, 0), np.maximum(qy, 0)) + np.minimum(np.maximum(qx, qy), 0) - 0.1
        got = render("box mask", {"half size": (0.5, 0.3), "roundness": 0.1, "center": (-0.2, 0.1), "angle": 0.4})
        assert np.abs(got - mask(d)).max() < 1e-4, np.abs(got - mask(d)).max()
    finally:
        bench.close()
        bpy.data.batch_remove([g for g in bpy.data.node_groups if g not in before])
    print("   ✓ mask2d rendered by the compositor, as its distances say")


def test_merge_render():
    """merge's operations, rendered by the compositor on two premultiplied images, give their formulas on
    the four channels, faded back to b by mix and mask."""
    print("-> Test: merge rendered by the compositor...")
    import numpy as np
    from base_node.host import build_source

    W, H = 16, 8
    before = set(bpy.data.node_groups)
    build_source("use merge\n\n"
                 "compositor graph merge_probe(a: Color, b: Color) -> Color {\n  return over(a, b)\n}\n", "m.bn")
    rng = np.random.default_rng(7)

    def premultiplied(cleared):
        alpha = rng.uniform(0.0, 1.0, (H, W, 1))
        alpha[cleared] = 0.0
        return np.concatenate([rng.uniform(0.0, 1.0, (H, W, 3)) * alpha, alpha], axis=2)

    # Some pixels of each with no alpha, some of both, for the divisions
    a = premultiplied((slice(0, 2), slice(0, 4)))
    b = premultiplied((slice(0, 2), slice(2, 6)))
    bench = CompositorBench("merge", W, H)
    bench.image("a", a)
    bench.image("b", b)

    def render(group, inputs=None, feed=None):
        return bench.render(group, feed or {"a": "a", "b": "b"}, inputs)

    aa, ab = a[..., 3:], b[..., 3:]
    with np.errstate(divide="ignore", invalid="ignore"):
        def safe(x, y):
            return np.where(y == 0.0, 0.0, x / np.where(y == 0.0, 1.0, y))

        want = {
            "over": a + b * (1 - aa),
            "under": a * (1 - ab) + b,
            "in": a * ab,
            "out": a * (1 - ab),
            "atop": a * ab + b * (1 - aa),
            "exclusive or": a * (1 - ab) + b * (1 - aa),
            "stencil": b * (1 - aa),
            "mask": b * aa,
            "matte": a * aa + b * (1 - aa),
            "conjoint over": a + b * np.where(aa > ab, 0.0, safe(1 - aa, ab)),
            "disjoint over": a + b * np.where(aa + ab < 1, 1.0, safe(1 - aa, ab)),
            "copy": a,
            "plus": a + b,
            "minus": a - b,
            "from": b - a,
            "average": (a + b) / 2,
            "multiply": a * b,
            "divide": safe(a, b),
            "screen": a + b - a * b,
            "maximum": np.maximum(a, b),
            "minimum": np.minimum(a, b),
            "difference": np.abs(a - b),
            "hypot": np.sqrt(a * a + b * b),
            "geometric": safe(2 * a * b, a + b),
        }
    try:
        for group, expected in want.items():
            # Relative past 1: the quotients of divide are large, in 32-bit floats
            assert_close(group, render(group), expected)
        got = render("over", {"mix": 0.25, "mask": 0.5})
        assert_close("over faded by mix and mask", got, b + (a + b * (1 - aa) - b) * 0.125)
        straight = render("unpremult", feed={"image": "a"})
        assert np.abs(straight[..., :3] * aa - a[..., :3]).max() < 1e-5
        assert np.abs(straight[aa[..., 0] == 0.0][:, :3]).max() == 0.0
    finally:
        bench.close()
        bpy.data.batch_remove([g for g in bpy.data.node_groups if g not in before])
    print(f"   ✓ merge rendered by the compositor: {len(want)} operations, as their formulas say")


def test_grade_render():
    """grade's colour tools, rendered by the compositor on a premultiplied image, give their formulas on the
    unpremultiplied colours, multiplied by the alpha again, the alpha left alone."""
    print("-> Test: grade rendered by the compositor...")
    import math

    import numpy as np
    from base_node.host import build_source

    W, H = 16, 8
    before = set(bpy.data.node_groups)
    build_source("use grade\n\n"
                 "compositor graph grade_probe(image: Color) -> Color {\n  return grade(image)\n}\n", "g.bn")
    rng = np.random.default_rng(11)

    def premultiplied(low, high):
        alpha = rng.uniform(0.05, 1.0, (H, W, 1))
        alpha[0:2, 0:4] = 0.0
        alpha[2:4, 0:4] = 1.0
        return np.concatenate([rng.uniform(low, high, (H, W, 3)) * alpha, alpha], axis=2)

    # Colours below 0 and above 1 for the clamps and powers; codes from 0 to 1 for Cineon
    sources = {"image": premultiplied(-0.2, 1.6), "codes": premultiplied(0.0, 1.0)}
    bench = CompositorBench("grade", W, H)
    for name, pixels in sources.items():
        bench.image(name, pixels)

    def render(group, inputs=None, source="image"):
        return bench.render(group, {"image": source}, inputs)

    def straight(source):
        pixels = sources[source]
        alpha = pixels[..., 3:]
        return np.where(alpha == 0.0, 0.0, pixels[..., :3] / np.where(alpha == 0.0, 1.0, alpha)), alpha

    def graded(rgb, source="image", t=1.0):
        """The graded straight colours, premultiplied, faded back to the image by t."""
        pixels = sources[source]
        alpha = pixels[..., 3:]
        return np.concatenate([rgb * alpha, alpha], axis=2) * t + pixels * (1.0 - t)

    def spow(x, e):
        return np.maximum(x, 0.0) ** e + np.minimum(x, 0.0)

    def smoothstep(x, a, b):
        t = np.clip((x - a) / (b - a), 0.0, 1.0)
        return t * t * (3.0 - 2.0 * t)

    c, _ = straight("image")
    codes, _ = straight("codes")
    luma709 = c @ np.array([0.2126, 0.7152, 0.0722])
    p = {"blackpoint": (0.05, 0.1, 0.0), "whitepoint": (0.9, 1.1, 1.2), "lift": (0.02, -0.03, 0.05),
         "gain": (1.2, 0.9, 1.1), "multiply": (1.1, 1.0, 0.95), "offset": (0.01, 0.02, -0.01),
         "gamma": (1.4, 0.8, 1.1)}
    n = {k: np.array(v) for k, v in p.items()}
    A = n["multiply"] * (n["gain"] - n["lift"]) / (n["whitepoint"] - n["blackpoint"])
    B = n["offset"] + n["lift"] - A * n["blackpoint"]
    forward = spow(A * c + B, 1.0 / n["gamma"])
    backward = (spow(c, n["gamma"]) - B) / A
    assert np.abs(spow(A * backward + B, 1.0 / n["gamma"]) - c).max() < 1e-9

    cc = {"saturation": 1.2, "contrast": 1.1, "gamma": 0.9, "gain": 1.05, "offset": 0.01,
          "shadows saturation": 0.7, "shadows contrast": 1.3, "shadows gamma": 1.2, "shadows gain": 0.8,
          "shadows offset": 0.02, "midtones saturation": 1.4, "midtones contrast": 0.9, "midtones gamma": 1.1,
          "midtones gain": 1.1, "midtones offset": -0.01, "highlights saturation": 0.8,
          "highlights contrast": 1.2, "highlights gamma": 0.8, "highlights gain": 0.9,
          "highlights offset": 0.03, "shadows end": 0.3, "highlights start": 0.4, "highlights end": 1.2}

    def correct(range_):
        s = cc["saturation"] * cc[f"{range_} saturation"]
        k = cc["contrast"] * cc[f"{range_} contrast"]
        g = cc["gamma"] * cc[f"{range_} gamma"]
        gain = cc["gain"] * cc[f"{range_} gain"]
        off = cc["offset"] + cc[f"{range_} offset"]
        lum = luma709[..., None]
        return spow(spow((lum + (c - lum) * s) / 0.18, k) * 0.18, 1.0 / g) * gain + off

    low = (1.0 - smoothstep(luma709, 0.0, cc["shadows end"]))[..., None]
    high = smoothstep(luma709, cc["highlights start"], cc["highlights end"])[..., None]

    def saturated(weights, s):
        lum = (c @ np.array(weights))[..., None]
        return c * s + lum * (1.0 - s)

    angle = 0.7
    axis = np.ones(3) / math.sqrt(3.0)
    turned = (c * math.cos(angle) + np.cross(axis, c) * math.sin(angle)
              + axis * (c @ axis)[..., None] * (1.0 - math.cos(angle)))
    k = 1.1 - 0.6
    soft = np.minimum(c, 0.6) + 1.1 - k * np.exp((0.6 - np.maximum(c, 0.6)) / k) - 0.6
    offset = 10.0 ** ((95.0 - 685.0) * 0.002 / 0.6)
    lin = (10.0 ** ((codes * 1023.0 - 685.0) * 0.002 / 0.6) - offset) / (1.0 - offset)
    log = (685.0 + np.log10(codes * (1.0 - offset) + offset) * 0.6 / 0.002) / 1023.0

    want = [
        ("grade", p, "image", graded(np.maximum(forward, 0.0))),
        ("grade", {**p, "clamp_black": False, "clamp_white": True}, "image", graded(np.minimum(forward, 1.0))),
        ("grade", {**p, "reverse": True, "clamp_black": False}, "image", graded(backward)),
        ("grade", {**p, "mix": 0.25, "mask": 0.5}, "image", graded(np.maximum(forward, 0.0), t=0.125)),
        ("color correct", cc, "image",
         graded(correct("shadows") * low + correct("midtones") * (1.0 - low - high) + correct("highlights") * high)),
        ("saturation", {"s": 1.6}, "image", graded(saturated((0.2126, 0.7152, 0.0722), 1.6))),
        ("saturation", {"s": 0.4, "luma": "Rec2020"}, "image", graded(saturated((0.2627, 0.678, 0.0593), 0.4))),
        ("saturation", {"s": 1.3, "luma": "ACEScg"}, "image",
         graded(saturated((0.2722287, 0.6740818, 0.0536895), 1.3))),
        ("hue shift", {"angle": angle}, "image", graded(turned)),
        ("exposure stops", {"stops": 1.5}, "image", graded(c * 2.0 ** 1.5)),
        ("soft clip", {"start": 0.6, "limit": 1.1}, "image", graded(soft)),
        ("clamp channels", {"low": (-0.1, 0.0, 0.2), "high": (0.8, 0.9, 1.0)}, "image",
         graded(np.clip(c, (-0.1, 0.0, 0.2), (0.8, 0.9, 1.0)))),
        ("log2lin", {}, "codes", graded(lin, "codes")),
        ("lin2log", {}, "codes", graded(log, "codes")),
    ]
    try:
        for group, inputs, source, expected in want:
            # Relative past 1: powers and Cineon codes are large, in 32-bit floats
            assert_close(f"{group} {inputs}", render(group, inputs, source), expected)
        assert (soft < 1.1).all() and np.abs(lin[codes == 95.0 / 1023.0]).max(initial=0.0) < 1e-9
    finally:
        bench.close()
        bpy.data.batch_remove([g for g in bpy.data.node_groups if g not in before])
    print(f"   ✓ grade rendered by the compositor: {len(want)} renders, as their formulas say")


def test_stmap_render():
    """stmap's STMaps, rendered by the compositor, are the coordinates numpy computes for them, at the centres
    of the pixels; the images remapped by them take their colours there."""
    print("-> Test: stmap rendered by the compositor...")
    import numpy as np
    from base_node.host import build_source

    W, H = 16, 8
    before = set(bpy.data.node_groups)
    build_source("use stmap\n\n"
                 "compositor graph stmap_probe(image: Color) -> Color {\n  return tile(image, 2, 3, true)\n}\n", "s.bn")
    rng = np.random.default_rng(11)
    image = np.concatenate([rng.uniform(0.0, 1.0, (H, W, 3)), np.ones((H, W, 1))], axis=2)
    bench = CompositorBench("stmap", W, H)
    bench.image("image", image)

    def render(group, inputs=None, feed=None, size=(W, H)):
        bench.scene.render.resolution_x, bench.scene.render.resolution_y = size
        return bench.render(group, feed or {"image": "image"}, inputs)

    def centres(w, h):
        i, j = np.meshgrid(np.arange(w), np.arange(h))
        return (i + 0.5) / w, (j + 0.5) / h

    def assert_stmap(what, got, u, v, coverage=1.0):
        want = np.stack(np.broadcast_arrays(u, v, np.zeros_like(u), coverage), axis=-1)
        assert_close(what, got, want)

    u, v = centres(W, H)
    try:
        ramp = render("uv ramp")
        assert_stmap("uv ramp", ramp, u, v)
        bench.image("ramp", ramp)
        assert_close("identity", render("stmap apply", feed={"image": "image", "stmap": "ramp"}), image)
        # The coverage, in the STMap's alpha, fades the result
        half = ramp.copy()
        half[..., 3] = 0.5
        bench.image("half", half)
        assert_close("coverage", render("stmap apply", feed={"image": "image", "stmap": "half"}), image * 0.5)

        def repeat(t, mirror):
            f = t % 1.0
            return f + (np.floor(t) % 2.0) * (1.0 - 2.0 * f) if mirror else f

        for mirror in (False, True):
            p = {"rows": 3, "columns": 2, "mirror": mirror}
            assert_stmap(f"tile stmap {mirror}", render("tile stmap", p), repeat(u * 2, mirror), repeat(v * 3, mirror))
        # Two tiles across: each pixel halfway between two of the image's, their mean
        got = render("tile", {"rows": 1, "columns": 2})
        half = (image[:, 0::2] + image[:, 1::2]) * 0.5
        assert_close("tile", got, np.concatenate([half, half], axis=1))
        got = render("tile", {"rows": 1, "columns": 2, "mirror": True})
        assert_close("tile mirror", got, np.concatenate([half, half[:, ::-1]], axis=1))

        for h, vert in ((True, False), (False, True), (True, True)):
            p = {"horizontal": h, "vertical": vert}
            assert_stmap(f"mirror stmap {p}", render("mirror stmap", p), 1 - u if h else u, 1 - v if vert else v)
            flipped = image[::-1 if vert else 1, ::-1 if h else 1]
            assert_close(f"mirror {p}", render("mirror", p), flipped)

        # Reformat to 8 × 8 and to 32 × 8: the image 2:1 fitted, filled, stretched
        for w, h in ((8, 8), (32, 8)):
            cu, cv = centres(w, h)
            k = (W / H) / (w / h)
            for mode, (su, sv) in {"Fit": (max(1, 1 / k), max(1, k)), "Fill": (min(1, 1 / k), min(1, k)),
                                   "Distort": (1, 1)}.items():
                p = {"width": w, "height": h, "mode": mode}
                assert_stmap(f"reformat stmap {p}", render("reformat stmap", p, size=(w, h)),
                             (cu - 0.5) * su + 0.5, (cv - 0.5) * sv + 0.5)
        # Fitted in a square, the image keeps its rows 2 to 5 and its columns, by halves; the rest is clear
        got = render("reformat", {"width": 8, "height": 8, "mode": "Fit"}, size=(8, 8))
        assert np.abs(got[:2]).max() == 0.0 and np.abs(got[6:]).max() == 0.0
        assert_close("reformat fit", got[2:6], (image[:, 0::2] + image[:, 1::2])[::2] * 0.25
                     + (image[:, 0::2] + image[:, 1::2])[1::2] * 0.25)
    finally:
        bench.close()
        bpy.data.batch_remove([g for g in bpy.data.node_groups if g not in before])
    print("   ✓ stmap rendered by the compositor: its STMaps are numpy's, its images taken where they say")


def test_stmap_canvas_render():
    """stmap's canvas has the size asked, odd or even, to the pixel: its coordinates are at the centres of
    its pixels, (i + 0.5) / width, and an image already of that size stays as it is (T-135)."""
    print("-> Test: stmap canvas of odd and even sizes...")
    import numpy as np
    from base_node.host import build_source

    before = set(bpy.data.node_groups)
    build_source("use stmap\n\n"
                 "compositor graph canvas_size(image: Color, width: Int = 1, height: Int = 1) -> Color {\n"
                 "  d = ImageInfo(canvas(image, width, height)).dimensions\n"
                 "  return CombineColor(d.x, d.y, 0.0, 1.0)\n}\n\n"
                 "compositor graph canvas_uv(image: Color, width: Int = 1, height: Int = 1) -> Color {\n"
                 "  p = ImageCoordinates(canvas(image, width, height)).normalized\n"
                 "  return CombineColor(p.x, p.y, 0.0, 1.0)\n}\n", "canvas_probe.bn")
    rng = np.random.default_rng(13)
    bench = CompositorBench("canvas", 8, 8)
    bench.image("source", np.concatenate([rng.uniform(0.0, 1.0, (48, 96, 3)), np.ones((48, 96, 1))], axis=2))
    def render(group, feed, w, h):
        """The canvas rendered, cut out of the render where it is opaque: Blender renders 4 pixels a side at
        least, and draws a smaller canvas inside, transparent around it."""
        got = bench.render(group, {"image": feed}, {"width": w, "height": h})
        rows, cols = np.nonzero(got[..., 3].any(axis=1))[0], np.nonzero(got[..., 3].any(axis=0))[0]
        assert (len(rows), len(cols)) == (h, w), f"{group} {w} × {h} covers {len(cols)} × {len(rows)} pixels"
        return got[rows[0]:rows[-1] + 1, cols[0]:cols[-1] + 1]

    try:
        for w, h in ((65, 33), (1, 1), (3, 5), (64, 32)):
            bench.scene.render.resolution_x, bench.scene.render.resolution_y = max(w, 4), max(h, 4)
            size = bench.render("canvas_size", {"image": "source"}, {"width": w, "height": h})
            assert tuple(size[0, 0, :2]) == (w, h), f"canvas {w} × {h} is {size[0, 0, 0]:g} × {size[0, 0, 1]:g}"
            i, j = np.meshgrid(np.arange(w), np.arange(h))
            want = np.stack(np.broadcast_arrays((i + 0.5) / w, (j + 0.5) / h, 0.0, 1.0), axis=-1)
            assert_close(f"canvas {w} × {h} coordinates", render("canvas_uv", "source", w, h), want)
            # An image of the canvas' own size is its canvas
            image = np.concatenate([rng.uniform(0.0, 1.0, (h, w, 3)), np.ones((h, w, 1))], axis=2)
            bench.image(f"{w}x{h}", image)
            assert_close(f"canvas {w} × {h} of its size", render("canvas", f"{w}x{h}", w, h), image)
    finally:
        bench.close()
        bpy.data.batch_remove([g for g in bpy.data.node_groups if g not in before])
    print("   ✓ stmap canvas: 65 × 33, 1 × 1, 3 × 5 and 64 × 32 to the pixel, at the centres of their pixels")


def test_qc_render():
    """qc's patterns, rendered by the compositor, are numpy's pixel for pixel: the bars at their columns, the
    wheel's hue and saturation, the ramp, the shapes, grid and checker; its checks find what a made-up image
    holds: values above 1 and below 0, NaN, infinities, the zones of its stops, its alpha."""
    print("-> Test: qc rendered by the compositor...")
    import colorsys
    import math

    import numpy as np
    from base_node.host import build_source

    W, H = 28, 16
    before = set(bpy.data.node_groups)
    # A probe whose red, times 10³⁰, holds infinities the compositor made: Python's are clamped to ±3.4e38
    build_source("use qc\n\n"
                 "compositor graph qc_inf_probe(image: Color) -> Color {\n"
                 "  c = SeparateColor(image)\n"
                 "  return nan_inf_check(CombineColor(c.red * 1e30, c.green, c.blue, c.alpha))\n}\n", "q.bn")
    bench = CompositorBench("qc", W, H)
    rng = np.random.default_rng(5)
    bench.image("blank", np.zeros((H, W, 4)))

    def render(group, inputs=None, feed=None, output=0):
        return bench.render(group, feed or {"image": "blank"}, inputs, output)

    i, j = np.meshgrid(np.arange(W), np.arange(H))
    px = 2.0 / max(W, H)
    x, y = (i + 0.5 - W / 2) * px, (j + 0.5 - H / 2) * px
    ex, ey = W / max(W, H), H / max(W, H)

    def rgba(*channels):
        return np.stack(np.broadcast_arrays(*channels), axis=-1).astype(float)

    def smooth(d, edge, softness):
        t = np.clip((d - edge) / (-max(softness, 1e-6)), 0, 1)
        return t * t * (3 - 2 * t)

    def gray(v, a=1.0):
        return rgba(v, v, v, a)

    def luma(img):
        return img[..., 0] * 0.2126 + img[..., 1] * 0.7152 + img[..., 2] * 0.0722

    def mixed(a, b, m):
        m = m[..., None].astype(float)
        return np.asarray(a, float) * m + np.asarray(b, float) * (1 - m)

    try:
        # ---- Patterns ----
        assert_close("constant", render("constant", {"color": (0.2, 0.4, 0.6, 0.8)}), rgba(0.2, 0.4, 0.6, 0.8 + 0 * x))
        # Seven bars of four columns: white, yellow, cyan, green, magenta, red, blue, at 0.75
        bars = render("color bars")
        palette = [(1, 1, 1), (1, 1, 0), (0, 1, 1), (0, 1, 0), (1, 0, 1), (1, 0, 0), (0, 0, 1)]
        for k, color in enumerate(palette):
            assert_close(f"bar {k}", bars[:, 4 * k:4 * k + 4], rgba(*(0.75 * c for c in color), 1.0 + 0 * x[:, :4]))
        assert_close("bars at 100 %", render("color bars", {"level": 1.0})[0, ::4, :3], np.array(palette, float))

        # The wheel: hue by the angle, saturation by the distance, in a disk of radius the smaller half side
        r = min(ex, ey)
        d = np.hypot(x, y)
        hue = (np.arctan2(y, x) / (2 * math.pi)) % 1.0
        sat = np.minimum(d / r, 1.0)
        rgb = np.vectorize(colorsys.hsv_to_rgb)(hue, sat, 1.0)
        e = px * 0.5
        t = np.clip((d - r + e) / (2 * e), 0, 1)
        cover = 1 - t * t * (3 - 2 * t)
        wheel = render("color wheel")
        assert_close("color wheel", wheel, rgba(*(c * cover for c in rgb), cover), 1e-4)
        # Red to the right of the center, green a third of a turn on, blue two thirds
        for angle, want in ((0.0, (1, 0, 0)), (120.0, (0, 1, 0)), (240.0, (0, 0, 1))):
            a = math.radians(angle)
            # the pixel nearest the point at 0.9 of the radius in that direction, whose hue is near
            n = np.argmin(np.hypot(x - 0.9 * r * math.cos(a), y - 0.9 * r * math.sin(a)))
            got = wheel.reshape(-1, 4)[n, :3]
            assert np.argmax(got) == np.argmax(want) and got.max() > 0.8, (angle, got)
        assert wheel[0, 0, 3] == 0.0 and wheel[H // 2, W // 2, 3] == 1.0

        for angle in (0.0, 90.0, 30.0, -135.0):
            a = math.radians(angle)
            c, s = math.cos(a), math.sin(a)
            t = 0.5 + 0.5 * (x * c + y * s) / (abs(c) * ex + abs(s) * ey)
            got = render("ramp", {"from": (1.0, 0.0, 0.2, 1.0), "to": (0.0, 0.5, 1.0, 0.5), "angle": a})
            want = rgba(1 - t, 0.5 * t, 0.2 * (1 - t) + t, (1 - t) + 0.5 * t)
            assert_close(f"ramp {angle}", got, want)
        # At 0 the ramp goes from the left to the right across the whole width, by the pixels' centres
        got = render("ramp", {"angle": 0.0})
        assert_close("ramp 0", got[..., 0], (i + 0.5) / W)

        for softness in (0.4, 0.0):
            m = smooth(np.hypot(x - 0.2, y + 0.1), 0.45, 0.45 * softness)
            got = render("radial", {"center": (0.2, -0.1), "radius": 0.45, "softness": softness})
            assert_close(f"radial {softness}", got, gray(m, m), 1e-4)
        for softness in (0.15, 0.0):
            m = smooth(np.abs(x + 0.1), 0.53, softness) * smooth(np.abs(y - 0.05), 0.27, softness)
            got = render("rectangle", {"center": (-0.1, 0.05), "size": (1.06, 0.54), "softness": softness})
            assert_close(f"rectangle {softness}", got, gray(m, m), 1e-4)
        assert render("rectangle", {"softness": 0.0})[..., 3].max() == 1.0

        lines = ((i % 5) < 2) | ((j % 5) < 2)
        got = render("grid", {"spacing": 5.0, "width": 2.0, "color": (1.0, 0.5, 0.25, 1.0)})
        assert_close("grid", got, rgba(1.0, 0.5, 0.25, 1.0) * lines[..., None])
        odd = ((i // 3 + j // 3) % 2)
        got = render("checkerboard", {"size": 3.0, "color0": (0.1, 0.2, 0.3, 1.0), "color1": (0.9, 0.8, 0.7, 0.5)})
        assert_close("checkerboard", got, mixed((0.9, 0.8, 0.7, 0.5), (0.1, 0.2, 0.3, 1.0), odd))
        assert_close("checkerboard origin", got[0, 0], np.array([0.1, 0.2, 0.3, 1.0]))

        # ---- Checks ----
        # An image of grays whose luminance is 0.18 × 2^s, s from -8 to 6 stops, away from the zones' edges
        edges = np.array([-6.0, -4.0, -2.0, -0.5, 0.5, 1.5, 2.5, 4.0])
        stops = rng.uniform(-8.0, 6.0, (H, W))
        stops += np.where(np.abs(stops[..., None] - edges).min(-1) < 0.05, 0.1, 0.0)
        level = 0.18 * 2.0 ** stops
        level[0, 0] = 0.0
        bench.image("stops", gray(level))
        zones = [(0.3, 0.0, 0.45), (0.0, 0.1, 0.8), (0.0, 0.55, 0.65), (0.25, 0.25, 0.25), (0.1, 0.75, 0.1),
                 (0.95, 0.5, 0.65), (0.7, 0.7, 0.7), (1.0, 0.85, 0.0), (1.0, 0.0, 0.0)]
        zone = np.searchsorted(edges, np.where(level > 0, stops, -100.0), side="right")
        want = np.concatenate([np.array(zones)[zone], np.ones((H, W, 1))], axis=-1)
        assert_close("false color", render("false color", feed={"image": "stops"}), want, 1e-4)

        # Values from -0.5 to 1.5: above 1 in red, below 0 in blue (above wins), the rest its luma in gray
        img = np.concatenate([rng.uniform(-0.5, 1.5, (H, W, 3)), rng.uniform(0.0, 1.0, (H, W, 1))], axis=-1)
        img[:2] = np.clip(img[:2], 0.0, 1.0)
        bench.image("img", img)
        above = img[..., :3].max(-1) > 1.0
        below = img[..., :3].min(-1) < 0.0
        rest = gray(np.clip(luma(img), 0, 1))
        want = mixed((1.0, 0.0, 0.0, 1.0), mixed((0.0, 0.3, 1.0, 1.0), rest, below), above)
        assert above.any() and below.any() and (~above & ~below).any()
        assert_close("clip check", render("clip check", feed={"image": "img"}), want)

        # NaN in each channel, ±3.4e38 (Python's infinities) and 1e31; and infinities made in the graph
        bad = np.full((H, W, 4), 0.5)
        bad[..., 3] = 1.0
        nan = np.zeros((H, W), bool)
        inf = np.zeros((H, W), bool)
        for k in range(4):
            bad[1, 2 + k, k] = np.nan
            nan[1, 2 + k] = True
        bad[3, 4, 0] = np.inf
        bad[3, 5, 1] = -np.inf
        bad[3, 6, 2] = 1e31
        bad[3, 7, 0], bad[3, 7, 1] = np.nan, np.inf
        bad[5, 3, 0] = 2.0
        inf[3, 4:7] = True
        nan[3, 7] = True
        bench.image("bad", bad)
        rest = gray(np.clip(luma(np.nan_to_num(bad, nan=0.0)), 0, 1))
        rest[3, 4:8, :3] = 1.0
        want = mixed((1.0, 0.0, 1.0, 1.0), mixed((0.0, 1.0, 1.0, 1.0), rest, inf), nan)
        got = render("nan inf check", feed={"image": "bad"})
        ok = ~(nan | inf)
        assert np.isfinite(got).all(), "a NaN or an infinity got through"
        assert_close("nan inf check: NaN", got[nan], want[nan])
        assert_close("nan inf check: inf", got[inf], want[inf])
        assert_close("nan inf check: rest", got[ok], want[ok])
        # Times 10³⁰ in the graph: 3.4e38 and 2.0 become infinite or past 10³⁰, 0.5 does not
        got = render("qc_inf_probe", feed={"image": "bad"})
        assert_close("graph's inf", got[3, 4], np.array([0.0, 1.0, 1.0, 1.0]))
        assert_close("graph's 2e30", got[5, 3], np.array([0.0, 1.0, 1.0, 1.0]))
        assert_close("graph's 5e29", got[0, 0], gray(np.float64(luma(np.array([5e29, 0.5, 0.5])).clip(0, 1))))
        assert_close("graph's NaN", got[1, 2], np.array([1.0, 0.0, 1.0, 1.0]))

        # Zebra stripes, two pixels wide, where the luma passes 0.5; the image elsewhere
        stripe = ((i + j) % 4) < 2
        want = mixed(gray(stripe.astype(float)), img, luma(img) > 0.5)
        assert_close("zebra", render("zebra", {"level": 0.5, "width": 2.0}, feed={"image": "img"}), want)

        # Alpha 0, 1 and between, premultiplied, over a checker of 4 pixels; the alpha alone
        alpha = rng.choice([0.0, 1.0, 0.5], (H, W))
        pm = np.concatenate([rng.uniform(0.0, 1.0, (H, W, 3)) * alpha[..., None], alpha[..., None]], axis=-1)
        bench.image("pm", pm)
        checker = mixed((0.4, 0.4, 0.4, 1.0), (0.2, 0.2, 0.2, 1.0), (i // 4 + j // 4) % 2)
        got = render("alpha check", {"size": 4.0}, feed={"image": "pm"})
        assert_close("alpha check", got, pm + checker * (1 - alpha[..., None]))
        assert_close("alpha check alpha", render("alpha check", feed={"image": "pm"}, output="Alpha"), gray(alpha))

        # The largest difference of the four channels, times gain, as heat; 0 between an image and itself
        got = render("diff view", {"gain": 4.0}, feed={"a": "img", "b": "pm"})
        dv = np.abs(img - pm).max(-1) * 4.0
        assert_close("diff view", got, rgba(np.clip(3 * dv, 0, 1), np.clip(3 * dv - 1, 0, 1), np.clip(3 * dv - 2, 0, 1), 1.0))
        assert_close("diff view same", render("diff view", feed={"a": "img", "b": "img"}), rgba(0 * x, 0, 0, 1.0))
    finally:
        bench.close()
        bpy.data.batch_remove([g for g in bpy.data.node_groups if g not in before])
    print("   ✓ qc rendered by the compositor: its patterns are numpy's, its checks find what the image holds")


def test_formula_operands_render():
    """An integer vector is a vector in a formula (Image Info's Dimensions, Image Coordinates' Pixel),
    as Blender converts it; a 2-tuple is (x, y, 0) and a colour tuple leaves its alpha out. Rendered,
    and read back as written."""
    print("-> Test: formula operands rendered by the compositor...")
    import numpy as np
    from base_node.host import build_source, export_tree

    W, H = 8, 6
    before = set(bpy.data.node_groups)
    build_source("compositor graph half_size(image: Color) -> Float {\n"
                 "  return length(ImageInfo(image).dimensions * 0.5 + (1.0, 1.0))\n}\n\n"
                 "compositor graph pixel_tint(image: Color, m: Float) -> Color {\n"
                 "  return ImageCoordinates(image).pixel * (1.0, 0.5, 0.25, 1.0) * m\n}\n\n"
                 "compositor graph width(image: Color) -> Float {\n"
                 "  return ImageInfo(image).dimensions.x\n}\n", "operands.bn")
    bench = CompositorBench("operands", W, H)
    bench.image("blank", np.zeros((H, W, 4)))
    try:
        # (8, 6) * 0.5 + (1, 1, 0) is (5, 4, 0)
        got = bench.render("half_size", {"image": "blank"})[..., 0]
        assert_close("half size", got, np.full((H, W), np.hypot(5.0, 4.0)))
        # The pixel's integer coordinates, from the bottom left, times (1, 0.5, 0.25) and m
        i, j = np.meshgrid(np.arange(W), np.arange(H))
        got = bench.render("pixel_tint", {"image": "blank"}, {"m": 2.0})[..., :3]
        assert_close("pixel tint", got, np.stack([2.0 * i, 1.0 * j, 0.0 * i], axis=-1))
        assert_close("width", bench.render("width", {"image": "blank"})[..., 0], np.full((H, W), float(W)))
        text, _ = export_tree(bpy.data.node_groups["width"])
        assert "return ImageInfo(image).dimensions.x" in text, text
        text, _ = export_tree(bpy.data.node_groups["half_size"])
        assert "length(ImageInfo(image).dimensions * 0.5 + (1.0, 1.0, 0.0))" in text, text
        text, _ = export_tree(bpy.data.node_groups["pixel_tint"])
        assert "ImageCoordinates(image).pixel * (1.0, 0.5, 0.25) * m" in text, text
    finally:
        bench.close()
        bpy.data.batch_remove([g for g in bpy.data.node_groups if g not in before])
    print("   ✓ Integer vectors and 2- or 4-number tuples in formulas: rendered, read back")


def test_pipe_through_chosen_output():
    """A geometry going on through one output of a node of several reads as a pipe, as an image does."""
    print("-> Test: Pipe through a chosen output...")
    from base_node.host import build_source, export_tree

    tree, = build_source(KEPT, "t.bn")
    text, warnings = export_tree(tree)
    assert text == KEPT and not warnings, (text, warnings)
    print("   ✓ Pipe through a chosen output verified")


def test_material_tree():
    """A material's own tree reads as a `shader(material: true)` graph, and builds back into it."""
    print("-> Test: A material's own tree...")
    from base_node.host import build_source, export_tree
    from base_node.lang import BnError
    from base_node.ui import actions

    # Made by hand, as a user does: a new material, a noise into its Principled BSDF
    mat = bpy.data.materials.new("Clay")
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    bsdf = next(n for n in nodes if n.bl_idname == "ShaderNodeBsdfPrincipled")
    out = next(n for n in nodes if n.bl_idname == "ShaderNodeOutputMaterial")
    noise = nodes.new("ShaderNodeTexNoise")
    noise.inputs["Scale"].default_value = 12.0
    links.new(noise.outputs["Fac"], bsdf.inputs["Roughness"])
    bump = nodes.new("ShaderNodeDisplacement")
    links.new(noise.outputs["Fac"], bump.inputs["Height"])
    links.new(bump.outputs["Displacement"], out.inputs["Displacement"])
    bsdf.inputs["Base Color"].default_value = (0.8, 0.3, 0.2, 1.0)

    assert shown(mat.node_tree) == mat.node_tree
    text, warnings = export_tree(mat.node_tree)
    assert not warnings, warnings
    assert text.startswith("shader(material: true) graph Clay() -> (surface: Shader, displacement: Vector) {"), text
    assert "PrincipledBSDF(" in text and "NoiseTexture(" in text and "@target" not in text, text

    # Built again: the same material, the same tree, nothing else made
    built, = build_source(text, "clay.bn")
    assert built == mat.node_tree and "Clay" not in bpy.data.node_groups
    assert [m.name for m in bpy.data.materials if m.name.startswith("Clay")] == ["Clay"]
    assert export_tree(mat.node_tree) == (text, [])
    out = next(n for n in mat.node_tree.nodes if n.bl_idname == "ShaderNodeOutputMaterial")
    assert out.is_active_output and not any(n.bl_idname == "NodeGroupInput" for n in mat.node_tree.nodes)
    assert [(s.name, s.links[0].from_node.bl_idname) for s in out.inputs if s.links] == \
        [("Surface", "ShaderNodeBsdfPrincipled"), ("Displacement", "ShaderNodeDisplacement")]

    # Written from text: a new material of that name
    source = """shader(material: true) graph Glow() -> (surface: Shader) {
  return (surface: Emission(color: (1.0, 0.5, 0.0, 1.0), strength: 4.0))
}
"""
    glow_tree, = build_source(source, "glow.bn")
    glow = bpy.data.materials["Glow"]
    assert glow_tree == glow.node_tree and "Glow" not in bpy.data.node_groups
    assert sorted(n.bl_idname for n in glow.node_tree.nodes) == ["ShaderNodeEmission", "ShaderNodeOutputMaterial"]
    assert export_tree(glow.node_tree) == (source, [])

    # A Material Output for one render engine says so; another one is a node of the text
    two = """shader(material: true, target: EEVEE) graph Two() -> (surface: Shader) {
  output_material = MaterialOutput(surface: Emission(), is_active_output: false, target: CYCLES)
  return (surface: DiffuseBSDF())
}
"""
    two_tree, = build_source(two, "two.bn")
    assert sorted((n.target, n.is_active_output) for n in two_tree.nodes if n.bl_idname == "ShaderNodeOutputMaterial") \
        == [("CYCLES", False), ("EEVEE", True)]
    assert export_tree(two_tree) == (two, [])

    # The material of a shader group becomes the text's own tree, and the group leaves it alone
    build_source("shader graph Tint() -> Shader {\n  return DiffuseBSDF()\n}\n", "t.bn")
    tint = bpy.data.materials["Tint"]
    build_source("shader(material: true) graph Tint() -> (surface: Shader) {\n  return (surface: Emission())\n}\n", "t.bn")
    build_source("shader graph Tint() -> Shader {\n  return DiffuseBSDF()\n}\n", "t.bn")
    assert [n.bl_idname for n in tint.node_tree.nodes if n.bl_idname != "ShaderNodeOutputMaterial"] == \
        ["ShaderNodeEmission"]

    def error(source):
        try:
            build_source(source, "t.bn")
        except BnError as e:
            return str(e.diagnostics[0])
        raise AssertionError(f"built: {source}")

    assert error("shader(material: true) graph Glow(p: Float) -> (surface: Shader) {\n"
                 "  return (surface: Emission(strength: p))\n}") \
        == "t.bn:1:35  a material takes no input: its values are written in its nodes"
    # A failed build leaves the material as it was, and no scratch material behind
    assert export_tree(glow.node_tree) == (source, [])
    assert not [m for m in bpy.data.materials if m.name.startswith(".base_node")]

    # The text view of a material: written back into it
    view, _ = actions.open_view(glow.node_tree)
    assert view.name == ".Glow (material).bn" and actions.view_tree(view) == glow.node_tree
    view.from_string(view.as_string().replace("4.0", "2.0"))
    assert actions.close_view(view) == glow.node_tree
    emission = next(n for n in glow.node_tree.nodes if n.bl_idname == "ShaderNodeEmission")
    assert emission.inputs["Strength"].default_value == 2.0

    # A geometry graph sets a material the same text defines, before or after it: the loop closes
    sets = """geometry graph ball() -> Geometry {
  return UVSphere().mesh
    |> SetMaterial(material: Terracotta)
}
"""
    terracotta = """shader(material: true) graph Terracotta() -> (surface: Shader) {
  return (surface: PrincipledBSDF(roughness: 0.8))
}
"""
    for i, source in enumerate((sets + "\n" + terracotta, terracotta + "\n" + sets)):
        assert "Terracotta" not in bpy.data.materials or i, "a material left from another test"
        build_source(source, "ball.bn")
        set_material = next(n for n in bpy.data.node_groups["ball"].nodes if n.bl_idname == "GeometryNodeSetMaterial")
        assert set_material.inputs["Material"].default_value == bpy.data.materials["Terracotta"]
        assert export_tree(bpy.data.node_groups["ball"])[0].endswith(sets)
        assert not [m for m in bpy.data.materials if m.name.startswith(".base_node")]
    assert len([m for m in bpy.data.materials if m.name.startswith("Terracotta")]) == 1, "built twice"

    # The material of a shader group nobody calls is set the same way, before or after it
    sets = """geometry graph ball() -> Geometry {
  return UVSphere().mesh
    |> SetMaterial(material: Brick)
}
"""
    brick = """shader graph Brick(color: Color = (0.6, 0.2, 0.1)) -> Shader {
  return DiffuseBSDF(color: color)
}
"""
    for source in (sets + "\n" + brick, brick + "\n" + sets):
        build_source(source, "ball.bn")
        mat = bpy.data.materials["Brick"]
        set_material = next(n for n in bpy.data.node_groups["ball"].nodes if n.bl_idname == "GeometryNodeSetMaterial")
        assert set_material.inputs["Material"].default_value == mat
        group = next(n for n in mat.node_tree.nodes if n.bl_idname == "ShaderNodeGroup")
        assert group.node_tree == bpy.data.node_groups["Brick"] and group.outputs["Shader"].links
        # Made before the group had its inputs, the material still takes their defaults
        assert [round(v, 3) for v in group.inputs["color"].default_value[:3]] == [0.6, 0.2, 0.1]
        assert export_tree(bpy.data.node_groups["ball"])[0].endswith(sets)
        assert not [m for m in bpy.data.materials if m.name.startswith(".base_node")]
    assert [m.name for m in bpy.data.materials if m.name.startswith("Brick")] == ["Brick"], "built twice"

    # In quotes, a material named like a name of the graph, or that makes no identifier
    for name, written in (("size", '"size"'), ("Old Brick", '"Old Brick"'), ("cross", '"cross"')):
        bpy.data.materials.new(name)
        tree, = build_source('geometry graph ball(size: Float = 1.0) -> Geometry {\n'
                             f'  return UVSphere(radius: size).mesh |> SetMaterial(material: {written})\n}}\n', "b.bn")
        assert f"SetMaterial(material: {written})" in export_tree(tree)[0], export_tree(tree)[0]
        bpy.data.materials.remove(bpy.data.materials[name])
    bpy.data.materials.remove(bpy.data.materials["Brick"])
    bpy.data.node_groups.remove(bpy.data.node_groups["Brick"])

    for name in ("Clay", "Glow", "Tint", "Two", "Terracotta"):
        bpy.data.materials.remove(bpy.data.materials[name])
    bpy.data.node_groups.remove(bpy.data.node_groups["Tint"])
    bpy.data.node_groups.remove(bpy.data.node_groups["ball"])
    print("   ✓ A material's own tree verified")


RAMPS = """shader graph ramps(f: Float, c: Color, v: Vector) -> (shade: Color, bend: Vector) {
  r = ColorRamp(
    factor: f,
    color_ramp: Ramp(
      (0.0, (0.1, 0.0, 0.0, 1.0)),
      (0.25, (1.0, 0.5, 0.0, 0.5)),
      (1.0, (0.0, 0.0, 1.0, 1.0)),
      interpolation: EASE,
      color_mode: HSV,
      hue_interpolation: FAR))
  k = FloatCurve(
    value: r.alpha,
    mapping: Curve(
      (0.0, 0.2),
      (0.4, 0.9, VECTOR),
      (1.0, 0.0),
      extend: HORIZONTAL,
      use_clip: false,
      clip_min_y: -1.0))
  s = RGBCurves(
    color: r.color,
    mapping: Curves(
      r: Curve((0.0, 0.0), (0.5, 0.7), (1.0, 1.0)),
      c: Curve((0.0, 0.1), (1.0, 0.9, AUTO_CLAMPED)),
      black_level: (0.05, 0.05, 0.05)))
  return (
    shade: MixLegacy(factor: k, color1: s, color2: c),
    bend: VectorCurves(vector: v, mapping: Curves(z: Curve((-1.0, 1.0), (1.0, -1.0)))))
}
"""

HUE = """compositor graph hue(image: Color) -> Color {
  return HueCorrect(image, mapping: Curves(s: Curve((0.0, 0.5), (0.5, 0.8), (1.0, 0.5))))
}
"""


def test_ramps_and_curves():
    """A Color Ramp's stops and the points of curves are written in the text and built back."""
    print("-> Test: Ramps and curves...")
    from base_node.host import build_source, export_tree
    from base_node.lang import BnError

    tree, = build_source(RAMPS, "t.bn")
    by_type = {n.bl_idname: n for n in tree.nodes}
    ramp = by_type["ShaderNodeValToRGB"].color_ramp
    assert [(round(e.position, 3), tuple(round(c, 3) for c in e.color)) for e in ramp.elements] == \
        [(0.0, (0.1, 0.0, 0.0, 1.0)), (0.25, (1.0, 0.5, 0.0, 0.5)), (1.0, (0.0, 0.0, 1.0, 1.0))]
    assert (ramp.interpolation, ramp.color_mode, ramp.hue_interpolation) == ("EASE", "HSV", "FAR")
    curve = by_type["ShaderNodeFloatCurve"].mapping
    assert [(tuple(round(c, 3) for c in p.location), p.handle_type) for p in curve.curves[0].points] == \
        [((0.0, 0.2), "AUTO"), ((0.4, 0.9), "VECTOR"), ((1.0, 0.0), "AUTO")]
    assert curve.extend == "HORIZONTAL" and not curve.use_clip and curve.clip_min_y == -1.0
    rgb = by_type["ShaderNodeRGBCurve"].mapping
    # Blender's order is R, G, B, then C, the curve of all three
    assert [len(c.points) for c in rgb.curves] == [3, 2, 2, 2]
    assert rgb.curves[3].points[1].handle_type == "AUTO_CLAMPED"
    assert round(rgb.black_level[0], 3) == 0.05
    assert [tuple(p.location) for p in by_type["ShaderNodeVectorCurve"].mapping.curves[2].points] == [(-1.0, 1.0), (1.0, -1.0)]
    assert export_tree(tree) == (RAMPS, [])
    # Built again from its own text, nothing moves
    build_source(export_tree(tree)[0], "t.bn")
    assert export_tree(tree) == (RAMPS, [])

    # The shared fixture, a material with its ramp and curve, reads back as written
    fixture = (LIB_ROOT / "python" / "tests" / "fixtures" / "materials.bn").read_text(encoding="utf-8")
    made = build_source(fixture, "materials.bn")
    assert made[0] == bpy.data.materials["Clay"].node_tree
    assert "\n".join(export_tree(t)[0] for t in made) == fixture
    bpy.data.materials.remove(bpy.data.materials["Clay"])
    bpy.data.node_groups.remove(bpy.data.node_groups["tint"])

    hue, = build_source(HUE, "t.bn")
    assert export_tree(hue) == (HUE, [])

    # Edited by hand: the text follows. The nodes are taken again: the builds since may have
    # freed the ramp and the curve taken above, and Python would then point to freed memory
    by_type = {n.bl_idname: n for n in tree.nodes}
    ramp = by_type["ShaderNodeValToRGB"].color_ramp
    curve = by_type["ShaderNodeFloatCurve"].mapping
    ramp.elements.remove(ramp.elements[1])
    curve.curves[0].points.new(0.7, 0.3)
    curve.update()
    text = export_tree(tree)[0]
    assert "Ramp(\n      (0.0, (0.1, 0.0, 0.0, 1.0)),\n      (1.0, (0.0, 0.0, 1.0, 1.0)),\n" in text, text
    assert "(0.7, 0.3)" in text, text
    build_source(text, "t.bn")
    assert export_tree(tree)[0] == text

    def error(source):
        try:
            build_source(source, "t.bn")
        except BnError as e:
            return str(e.diagnostics[0])
        raise AssertionError(f"built: {source}")

    assert error("shader graph g(f: Float) -> Color {\n  return ColorRamp(factor: f, color_ramp: Ramp((0.5, (1.0, 1.0, 1.0)), "
                 "interpolation: SMOOTH)).color\n}") \
        == "t.bn:2:72  interpolation expects one of EASE, CARDINAL, LINEAR, B_SPLINE, CONSTANT"
    assert error("shader graph g(c: Color) -> Color {\n  return RGBCurves(color: c, mapping: Curve((0.0, 0.0), (1.0, 1.0)))\n}") \
        == "t.bn:2:39  mapping expects Curves(r: Curve((x, y), …), …); channels: r, g, b, c"

    bpy.data.node_groups.remove(tree)
    bpy.data.node_groups.remove(hue)
    for e in list(bpy.context.scene.compositor_effects):
        bpy.context.scene.compositor_effects.remove(e)
    print("   ✓ Ramps and curves verified")


def test_text_view():
    """5. A tree shown as text is written back into it, and the text goes away."""
    print("-> Test 5: Text view of a tree...")
    from base_node.host import build_source
    from base_node.lang import BnError
    from base_node.ui import actions

    tree = build_source("""
geometry graph view_me(geometry: Geometry) -> Geometry {
  return SetPosition(geometry, offset: CombineXYZ(z: 1.0))
}
""", filename="view_me.bn")[0]
    texts_before = set(bpy.data.texts)

    # A tree linked to a text by an older version is unlinked when it is built again
    legacy = bpy.data.texts.new("legacy_view_me.bn")
    tree.base_node_text = legacy
    build_source(actions.export_tree(tree)[0], "view_me.bn")
    assert tree.base_node_text is None, "a rebuilt tree still points at a text"
    bpy.data.texts.remove(legacy)

    # Unchanged: the tree is left as it is, the text is removed
    text, _ = actions.open_view(tree)
    assert text.name.startswith(".") and actions.is_view(text) and actions.view_tree(text) == tree
    node = tree.nodes[0]
    node.location = (123.0, 45.0)
    assert actions.close_view(text) == tree
    assert tree.nodes[0].location[0] == 123.0, "an unchanged text rebuilt the tree"
    assert set(bpy.data.texts) == texts_before, "the view text was not removed"
    assert tree.base_node_text is None, "the view linked the tree to a text"

    # Applied: the tree is rebuilt and the text stays open; closing then rebuilds nothing more
    text, _ = actions.open_view(tree)
    text.from_string(text.as_string().replace("z: 1.0", "z: 2.0"))
    assert actions.apply_view(text) == tree and text.name in bpy.data.texts
    combine = next(n for n in tree.nodes if n.bl_idname == "ShaderNodeCombineXYZ")
    assert combine.inputs["Z"].default_value == 2.0, "the applied text did not reach the tree"
    combine.location = (7.0, 7.0)
    assert actions.close_view(text) == tree
    combine = next(n for n in tree.nodes if n.bl_idname == "ShaderNodeCombineXYZ")
    assert combine.location[0] == 7.0, "closing an applied text rebuilt the tree"

    # Changed: closing rebuilds the tree from the text
    text, _ = actions.open_view(tree)
    text.from_string(text.as_string().replace("z: 2.0", "z: 4.0"))
    assert actions.close_view(text) == tree
    combine = next(n for n in tree.nodes if n.bl_idname == "ShaderNodeCombineXYZ")
    assert combine.inputs["Z"].default_value == 4.0, "the edited text did not reach the tree"
    assert set(bpy.data.texts) == texts_before

    # Broken: the text stays, with its errors, until it builds
    text, _ = actions.open_view(tree)
    text.from_string(text.as_string().replace("SetPosition(", "SetPosition(("))
    try:
        actions.close_view(text)
        raise AssertionError("a broken text closed")
    except BnError:
        pass
    assert text.name in bpy.data.texts and text.name in actions.DIAGNOSTICS
    text.from_string(text.as_string().replace("SetPosition((", "SetPosition("))
    assert actions.close_view(text) == tree

    # Renamed in the text: the area follows the new tree
    text, _ = actions.open_view(tree)
    text.from_string(text.as_string().replace("graph view_me", "graph view_me_2"))
    renamed = actions.close_view(text)
    assert renamed is not None and renamed.name == "view_me_2", renamed
    print("   ✓ Text view verified")


def test_import_files():
    """6. File > Import builds the graphs of .bn files, finding the modules next to them."""
    print("-> Test 6: Import .bn files...")
    import os
    from base_node.host import modules
    from base_node.lang import BnError
    from base_node.ui import actions

    # curves2d uses math: found next to it, and kept with its path for a later build
    trees = actions.import_file(str(STDLIB_DIR / "curves2d.bn"))
    assert trees and all(t.get(modules.MODULE) is None for t in trees), "curves2d's own graphs became module groups"
    math_groups = [g for g in bpy.data.node_groups if g.get(modules.MODULE) == "math"]
    assert math_groups, "curves2d's use of math built nothing"
    assert all(os.path.samefile(g[modules.SOURCE], STDLIB_DIR / "math.bn") for g in math_groups)

    # A text view of a tree that calls math builds again without any math.bn text
    caller = next(t for t in trees if any(n.bl_idname == "GeometryNodeGroup" and n.node_tree in math_groups
                                          for n in t.nodes))
    text, _ = actions.open_view(caller)
    assert "use math" in text.as_string()
    text.from_string(text.as_string() + "\n")
    assert actions.close_view(text) == caller

    # A file elsewhere finds its modules in the module folders: by default, the stdlib bundled with the add-on
    import tempfile
    assert modules.FOLDERS == [modules.STDLIB], modules.FOLDERS
    assert os.path.isfile(os.path.join(modules.STDLIB, "math.bn")), "the stdlib is not bundled"
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "lifted.bn")
        with open(path, "w", encoding="utf-8") as f:
            f.write("use math (sine01)\n\ngeometry graph lifted(geometry: Geometry) -> Geometry {\n"
                    "  return SetPosition(geometry, offset: CombineXYZ(z: sine01(1.0)))\n}\n")
        modules.FOLDERS[:] = []
        try:
            actions.import_file(path)
            raise AssertionError("math found with no module folder")
        except BnError:
            pass
        finally:
            modules.FOLDERS[:] = [modules.STDLIB]
        trees = actions.import_file(path)
    assert [t.name for t in trees] == ["lifted"], trees
    assert trees[0].use_fake_user, "an imported group nothing uses is lost on save"

    # Files imported together: one sets a material that a file after it in the list defines
    with tempfile.TemporaryDirectory() as tmp:
        for name, text in (("a_ball.bn", "geometry graph a_ball() -> Geometry {\n"
                                         "  return UVSphere().mesh |> SetMaterial(material: Zinc)\n}\n"),
                           ("b_zinc.bn", "shader(material: true) graph Zinc() -> (surface: Shader) {\n"
                                         "  return (surface: PrincipledBSDF(metallic: 1.0))\n}\n")):
            with open(os.path.join(tmp, name), "w", encoding="utf-8") as f:
                f.write(text)
        result = bpy.ops.base_node.import_bn(directory=tmp + os.sep,
                                             files=[{"name": "a_ball.bn"}, {"name": "b_zinc.bn"}])
    assert result == {"FINISHED"}, result
    set_material = next(n for n in bpy.data.node_groups["a_ball"].nodes if n.bl_idname == "GeometryNodeSetMaterial")
    assert set_material.inputs["Material"].default_value == bpy.data.materials["Zinc"]
    assert bpy.data.materials["Zinc"].use_fake_user
    bpy.data.node_groups.remove(bpy.data.node_groups["a_ball"])
    bpy.data.materials.remove(bpy.data.materials["Zinc"])
    print("   ✓ Import verified")


LIFTED = """// @target blender-geometry

use math (sine01)

geometry graph lift(z: Float) -> Vector {
  return CombineXYZ(z: sine01(x: z))
}

geometry graph lifted(geometry: Geometry) -> Geometry {
  return SetPosition(geometry, offset: lift(z: 1.0))
}
"""

CLAY = """shader(material: true) graph Clay() -> (surface: Shader) {
  return (surface: PrincipledBSDF(roughness: 0.7))
}
"""


def file_state():
    """What a paste may change: the names of the groups, materials and texts, and each group's nodes."""
    return (sorted((g.name, g.bl_idname, len(g.nodes)) for g in bpy.data.node_groups),
            sorted(m.name for m in bpy.data.materials), sorted(t.name for t in bpy.data.texts))


def paste_operator(source, space=None):
    """Run Paste .bn on a clipboard holding `source`, as the Node Editor would. (result, reports, space)

    Background mode has no clipboard (it reads back empty): the operator gets one of its own.
    """
    from types import SimpleNamespace
    from base_node.ui.operators import BASE_NODE_OT_paste_bn
    reports = []
    space = space or SimpleNamespace(type="NODE_EDITOR", tree_type="GeometryNodeTree", node_tree=None)
    context = SimpleNamespace(window_manager=SimpleNamespace(clipboard=source), space_data=space)
    op = SimpleNamespace(report=lambda kind, message: reports.append((set(kind), message)))
    return BASE_NODE_OT_paste_bn.execute(op, context), reports, space


def copy_operator(tree, selected=False):
    """Run Copy as .bn on the Node Editor showing `tree`. (result, reports, clipboard)"""
    from types import SimpleNamespace
    from base_node.ui.operators import BASE_NODE_OT_copy_bn
    reports = []
    wm = SimpleNamespace(clipboard="")
    context = SimpleNamespace(window_manager=wm, space_data=SimpleNamespace(type="NODE_EDITOR", edit_tree=tree))
    op = SimpleNamespace(selected=selected, report=lambda kind, message: reports.append((set(kind), message)))
    return BASE_NODE_OT_copy_bn.execute(op, context), reports, wm.clipboard


def test_copy_paste():
    """Copy as .bn puts a text that builds on its own in another file; Paste .bn builds it, or nothing."""
    print("-> Test: Copy as .bn and Paste .bn...")
    from types import SimpleNamespace
    from base_node.host import build_source, export_tree, modules
    from base_node.lang import BnError
    from base_node.ui import actions

    def forget(names):
        """Remove the groups and materials of these names, as if the text were pasted in another file."""
        bpy.data.batch_remove([g for g in bpy.data.node_groups if g.name in names or g.get(modules.MODULE)]
                              + [m for m in bpy.data.materials if m.name in names])

    # Geometry Nodes: a nested group goes in the text, the stdlib module stays a use
    build_source(LIFTED, "lifted.bn")
    lifted = bpy.data.node_groups["lifted"]
    result, reports, copied = copy_operator(lifted)
    assert copied == LIFTED, copied
    assert result == {"FINISHED"} and reports == [({"INFO"}, "'lifted' copied as .bn (11 lines)")], reports
    # A stdlib module File > Import found next to a file keeps that path: the copy still writes a bare use
    for g in bpy.data.node_groups:
        if g.get(modules.MODULE) == "math":
            g[modules.SOURCE] = os.path.join(modules.STDLIB, "math.bn")
    assert 'from "' in export_tree(lifted)[0], "the path of the import is no longer written"
    assert actions.copy_text(lifted) == (LIFTED, [])
    forget({"lifted", "lift"})
    result, reports, space = paste_operator(copied)
    assert result == {"FINISHED"}, reports
    assert reports == [({"INFO"}, "2 trees pasted")], reports
    lifted = bpy.data.node_groups["lifted"]
    # The graph no other one calls is shown
    assert space.node_tree == lifted and space.tree_type == "GeometryNodeTree", space
    assert lifted.use_fake_user and bpy.data.node_groups["lift"].use_fake_user
    assert any(g.get(modules.MODULE) == "math" for g in bpy.data.node_groups), "the use of math built nothing"
    assert actions.copy_text(lifted) == (LIFTED, [])
    # Pasted again in the same file: the groups are rebuilt in place, and said so
    result, reports, _space = paste_operator(copied)
    assert reports == [({"INFO"}, "2 trees pasted; rebuilt in place: lift, lifted")], reports

    # A module of this file alone, a text of the .blend, is written in the text: no use left to find
    mylib = bpy.data.texts.new("mylib.bn")
    mylib.from_string("geometry graph twice(x: Float) -> Float {\n  return x * 2.0\n}\n")
    tree, = build_source("use mylib (twice)\n\ngeometry graph doubled(geometry: Geometry) -> Geometry {\n"
                         "  return SetPosition(geometry, offset: CombineXYZ(z: twice(0.5)))\n}\n", "d.bn")
    text, warnings = actions.copy_text(tree)
    assert "use mylib" not in text and "graph twice(x: Float)" in text and not warnings, (text, warnings)
    assert "use mylib" in export_tree(tree)[0], "the text view no longer writes the use"
    bpy.data.texts.remove(mylib)
    forget({"doubled", "twice"})
    assert [t.name for t in actions.paste_text(text)] == ["twice", "doubled"]
    assert actions.copy_text(bpy.data.node_groups["doubled"])[0] == text
    forget({"doubled", "twice", "lifted", "lift"})

    # A material's own tree, its Material Output the return
    build_source(CLAY, "clay.bn")
    result, reports, copied = copy_operator(bpy.data.materials["Clay"].node_tree)
    assert result == {"FINISHED"} and copied == CLAY, (reports, copied)
    forget({"Clay"})
    result, reports, space = paste_operator(copied)
    assert result == {"FINISHED"} and reports == [({"INFO"}, "'Clay' pasted")], reports
    clay = bpy.data.materials["Clay"]
    assert clay.use_fake_user and export_tree(clay.node_tree)[0] == CLAY
    # A material's tree is shown through its object: the editor is left as it is
    assert space.node_tree is None
    forget({"Clay"})

    # A compositor tree
    scene = bpy.context.scene
    effects = [e.node_group for e in scene.compositor_effects]
    build_source(LOOK, "look.bn")
    copied = copy_operator(bpy.data.node_groups["look"])[2]
    assert copied == LOOK, copied
    forget({"look"})
    space = paste_operator(copied, SimpleNamespace(type="NODE_EDITOR", tree_type="CompositorNodeTree",
                                                   node_tree=None))[2]
    look = bpy.data.node_groups["look"]
    assert space.node_tree == look and space.tree_type == "CompositorNodeTree"
    assert export_tree(look)[0] == LOOK
    for e in list(scene.compositor_effects):
        if e.node_group not in effects:
            scene.compositor_effects.remove(e)
    forget({"look"})

    # The selected nodes alone, as a graph of their own; the tree and the file are left as they were
    tree, = build_source("geometry graph picked(geometry: Geometry) -> Geometry {\n"
                         "  offset = CombineXYZ(z: 2.0)\n"
                         "  return SetPosition(geometry, offset: offset) |> TransformGeometry(scale: (2.0, 2.0, 2.0))\n"
                         "}\n", "picked.bn")
    whole = export_tree(tree)[0]
    before = file_state()
    for n in tree.nodes:
        n.select = n.bl_idname in {"ShaderNodeCombineXYZ", "GeometryNodeSetPosition"}
    result, reports, copied = copy_operator(tree, selected=True)
    assert result == {"FINISHED"} and reports[0][1].startswith("selected nodes copied"), reports
    # The links to the nodes left out go: the Set Position reads no geometry, the Transform is not there
    assert copied == ('geometry(is_modifier: true) graph "picked selection"() -> () {\n'
                      "  offset = CombineXYZ(z: 2.0)\n"
                      "  set_position = SetPosition(offset: offset)\n"
                      "  return ()\n"
                      "}\n"), copied
    assert file_state() == before and export_tree(tree)[0] == whole, "copying the selection changed the file"
    pasted, = actions.paste_text(copied)
    assert pasted.name == "picked selection" and \
        sorted(n.bl_idname for n in pasted.nodes) == ["GeometryNodeSetPosition", "NodeGroupInput",
                                                      "NodeGroupOutput", "ShaderNodeCombineXYZ"], \
        [n.bl_idname for n in pasted.nodes]
    # With the Group Input and Output, the interface goes along
    for n in tree.nodes:
        n.select = True
    assert actions.copy_text(tree, selected=True)[0] == whole.replace("graph picked(", 'graph "picked selection"(')
    for n in tree.nodes:
        n.select = False
    assert copy_operator(tree, selected=True)[:2] == ({"CANCELLED"}, [({"WARNING"}, "No node selected")])
    forget({"picked", "picked selection"})

    # Invalid text: the error says its line, and nothing of the file changes, not even the graphs before it
    build_source(LIFTED, "lifted.bn")
    before = file_state()
    broken = LIFTED.replace("lift(z: 1.0))", "lift(z: 1.0))\n}\n\ngeometry graph after() -> Geometry {\n  return Nope()")
    broken = broken.replace("CombineXYZ(z: sine01(x: z))", "CombineXYZ(z: sine01(x: z)) + true")
    for source in (broken, "geometry graph broken(geometry: Geometry) -> Geometry {\n  return Nope(\n}\n"):
        try:
            actions.paste_text(source)
            raise AssertionError(f"pasted: {source}")
        except BnError as e:
            assert e.diagnostics[0].file == actions.CLIPBOARD, e.diagnostics[0]
        result, reports, space = paste_operator(source)
        assert result == {"CANCELLED"} and space.node_tree is None, reports
        (kind, message), = reports
        assert kind == {"ERROR"} and message.startswith(f"{actions.CLIPBOARD}:"), message
        assert file_state() == before, "a failed paste changed the file"
    assert reports[0][1].startswith("clipboard:3:"), reports
    assert paste_operator("  \n")[:2] == ({"CANCELLED"}, [({"ERROR"}, "The clipboard holds no text")])
    assert file_state() == before
    forget({"lifted", "lift"})

    # The block the README and the website give to paste is examples/ripples.bn, and it builds as is
    import html
    ripples = (LIB_ROOT / "examples" / "ripples.bn").read_text(encoding="utf-8")
    assert f"```bn\n{ripples}```" in (LIB_ROOT / "README.md").read_text(encoding="utf-8"), "README block"
    site = (LIB_ROOT / "site" / "index.html").read_text(encoding="utf-8")
    assert f'<pre id="paste-me"><code>{html.escape(ripples.rstrip(chr(10)), quote=False)}</code></pre>' in site, \
        "website block"
    pasted = actions.paste_text(ripples)
    shown_tree = actions.entry(pasted)
    assert shown_tree is not None and shown_tree.name == "ripples", pasted
    obj = bpy.data.objects.new("ripples", bpy.data.meshes.new("ripples"))
    bpy.context.scene.collection.objects.link(obj)
    obj.modifiers.new("ripples", "NODES").node_group = shown_tree
    mesh = obj.evaluated_get(bpy.context.evaluated_depsgraph_get()).to_mesh()
    assert len(mesh.vertices) == 40 * 40 * 8 and "color" in mesh.attributes, len(mesh.vertices)
    obj.to_mesh_clear()
    mesh_data = obj.data
    bpy.data.objects.remove(obj)
    bpy.data.meshes.remove(mesh_data)
    forget({"ripples"})

    # The keys: Ctrl+Shift+C / Ctrl+Shift+V in the Node Editor, which Blender's own keymap leaves free
    from base_node.ui import keys
    wm = bpy.context.window_manager
    if wm.keyconfigs.addon is not None:
        km = wm.keyconfigs.addon.keymaps["Node Editor"]
        mine = {k.idname: (k.type, k.ctrl or k.oskey, k.shift, k.alt) for k in km.keymap_items}
        assert mine["base_node.copy_bn"] == ("C", True, True, False), mine
        assert mine["base_node.paste_bn"] == ("V", True, True, False), mine
        assert keys.shortcut("Node Editor", "base_node.copy_bn"), "the panel would show no keys"
    # Blender's default keymap is empty in background mode: its source says what it binds, for
    # either select mouse, in the keymaps a Node Editor's region reads (the window's, the screen's, its own)
    import importlib.util
    path = os.path.join(bpy.utils.system_resource("SCRIPTS"), "presets", "keyconfig", "keymap_data",
                        "blender_default.py")
    spec = importlib.util.spec_from_file_location("blender_default", path)
    default = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(default)
    seen = 0
    for mouse in ("LEFT", "RIGHT"):
        for name, _where, data in default.generate_keymaps(default.Params(select_mouse=mouse)):
            if name not in {"Window", "Screen", "Node Generic", "Node Editor"} and not name.startswith("Node Tool"):
                continue
            for item in data["items"]:
                if item is None:
                    continue
                seen += 1
                k = item[1]
                ctrl = k.get("ctrl") or k.get("oskey") or k.get("any")
                assert not (k["type"] in {"C", "V"} and k.get("shift") and ctrl and not k.get("alt")), \
                    f"{item[0]} has {k} in {name} already"
    assert seen > 100, f"only {seen} default keys read"
    print("   ✓ Copy as .bn and Paste .bn verified")


def test_zones_read_back():
    """7. Trees as Blender lets one make them, around zones, read back into text that builds."""
    print("-> Test 7: Zones read back...")
    from base_node.host import build_source, export_tree

    def round_trip(tree):
        text, warnings = export_tree(tree)
        rebuilt = build_source(text, filename=f"{tree.name}.bn")[-1]
        again, _ = export_tree(rebuilt)
        assert again == text, f"not stable:\n{text}\n---\n{again}"
        return text, warnings

    # A frame around nodes inside a zone and outside it: one frame, continued in the zone
    framed, = build_source("""
geometry graph framed(geometry: Geometry) -> Geometry {
  "F" {
    up = CombineXYZ(z: 0.1) @ hide
  }
  s = simulate(mesh: geometry) {
    "F" .. {
      moved = SetPosition(mesh, offset: up) @ hide
    }
    return moved
  }
  return s
}
""", filename="framed.bn")
    text, warnings = round_trip(framed)
    assert not warnings, warnings
    assert len([n for n in framed.nodes if n.bl_idname == "NodeFrame"]) == 1
    assert '"F" .. {' in text, text

    # A state Blender calls "Delta Time", beside the zone's own elapsed time
    timed, = build_source("""
geometry graph timed(geometry: Geometry) -> (Geometry: Geometry, Time: Float) {
  s = simulate(mesh: geometry, "Delta Time" as delta_time_2: 0.0) {
    return (mesh: mesh, delta_time_2: delta_time_2 + delta_time)
  }
  return (Geometry: s.mesh, Time: s.delta_time_2)
}
""", filename="timed.bn")
    zout = next(n for n in timed.nodes if n.bl_idname == "GeometryNodeSimulationOutput")
    assert [i.name for i in zout.state_items] == ["mesh", "Delta Time"]
    text, warnings = round_trip(timed)
    assert not warnings, warnings
    assert '"Delta Time" as delta_time_2' in text and "delta_time_2 + delta_time" in text, text

    # A generation item of a foreach named like its main geometry
    each, = build_source("""
geometry graph each(geometry: Geometry) -> (Geometry: Geometry, Points: Geometry) {
  e = foreach(geometry, domain: FACE) {
    return (points: Points(1))
  }
  return (Geometry: e, Points: e.points)
}
""", filename="each.bn")
    zout = next(n for n in each.nodes if n.bl_idname == "GeometryNodeForeachGeometryElementOutput")
    zout.generation_items[0].name = "Geometry"
    text, _warnings = round_trip(each)
    assert "e.Geometry" in text, text

    # A repeat in a repeat reading the iteration and a state of the outer one, which its own hide;
    # `outer * 2.0` sits in the outer zone, but is written in the inner one, where it is used
    nested, = build_source("""
geometry graph nested(geometry: Geometry) -> Geometry {
  r = repeat(3, mesh: geometry) {
    outer = iteration
    first = mesh
    r2 = repeat(2, mesh: mesh) {
      return SetPosition(mesh, offset: CombineXYZ(x: outer * 2.0, z: outer + iteration * 10)) + first
    }
    return r2
  }
  return r
}
""", filename="nested.bn")
    text, warnings = round_trip(nested)
    assert not warnings, warnings
    for line in ("iteration_2 = iteration", "mesh_2 = mesh", "iteration_2 * 2.0", "iteration_2 + iteration * 10", "+ mesh_2"):
        assert line in text, f"{line!r} not in:\n{text}"
    print("   ✓ Zones read back")


# Socket type -> Store Named Attribute data type, for the field outputs of a group
STORED = {"VALUE": "FLOAT", "VECTOR": "FLOAT_VECTOR", "INT": "INT", "BOOLEAN": "BOOLEAN",
          "RGBA": "FLOAT_COLOR", "ROTATION": "QUATERNION", "MATRIX": "FLOAT4X4"}


def stable(tree):
    """Text of `tree`, built and read back: the same text again, or AssertionError."""
    from base_node.host import build_source, export_tree

    text, warnings = export_tree(tree)
    rebuilt = build_source(text, filename=f"{tree.name}.bn")[-1]
    again, _ = export_tree(rebuilt)
    assert again == text, f"not stable:\n{text}\n---\n{again}"
    return text, warnings


def test_color_components():
    """A Color into Separate XYZ reads as `color.x` and builds again; a Float keeps its Separate XYZ (T-48)."""
    print("-> Test: Color components...")
    tree = bpy.data.node_groups.new("ColorParts", "GeometryNodeTree")
    tree.interface.new_socket("Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
    tree.interface.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    nodes, links = tree.nodes, tree.links
    gin, gout = nodes.new("NodeGroupInput"), nodes.new("NodeGroupOutput")
    voronoi = nodes.new("ShaderNodeTexVoronoi")
    sep = nodes.new("ShaderNodeSeparateXYZ")
    links.new(voronoi.outputs["Color"], sep.inputs["Vector"])
    value = nodes.new("ShaderNodeValue")
    sep_2 = nodes.new("ShaderNodeSeparateXYZ")
    links.new(value.outputs[0], sep_2.inputs["Vector"])
    combine = nodes.new("ShaderNodeCombineXYZ")
    links.new(sep.outputs["X"], combine.inputs["X"])
    links.new(sep.outputs["Z"], combine.inputs["Y"])
    links.new(sep_2.outputs["Y"], combine.inputs["Z"])
    setpos = nodes.new("GeometryNodeSetPosition")
    links.new(gin.outputs[0], setpos.inputs["Geometry"])
    links.new(combine.outputs[0], setpos.inputs["Offset"])
    links.new(setpos.outputs[0], gout.inputs[0])
    text, _ = stable(tree)
    assert "voronoi_texture.color.x" in text and "voronoi_texture.color.z" in text, text
    assert "SeparateXYZ(" in text, text  # the Float's, which `.y` would not take
    bpy.data.node_groups.remove(bpy.data.node_groups["ColorParts"])
    print("   ✓ Color components verified")


TWINS = """geometry graph twins(
    Menu: Menu = Scalar,
    Scalar: Float,
    Menu as menu_2: Menu = Center,
    Offset: Float = 2.0
) -> (Value: Float) {
  a = MenuSwitch(menu: Menu, Scalar: 1.0, Label: 2.0, data_type: FLOAT)
  b = MenuSwitch(menu: menu_2, Transform: 3.0, Center: 4.0, data_type: FLOAT)
  return (Value: a.output * b.output + Scalar + Offset)
}
"""


def test_inputs_of_one_name_rebuilt():
    """Two inputs of one name keep their own sockets when the group is built again (T-49)."""
    print("-> Test: Inputs of one name rebuilt...")
    from base_node.host import build_source, export_tree

    first = build_source(TWINS, filename="twins.bn")[-1]
    text, _ = export_tree(first)
    tree = build_source(text, filename="twins.bn")[-1]
    inputs = [(i.name, i.socket_type) for i in tree.interface.items_tree
              if i.item_type == "SOCKET" and i.in_out == "INPUT"]
    assert inputs == [("Menu", "NodeSocketMenu"), ("Scalar", "NodeSocketFloat"),
                      ("Menu", "NodeSocketMenu"), ("Offset", "NodeSocketFloat")], inputs
    again, _ = export_tree(tree)
    assert again == text, f"not stable:\n{text}\n---\n{again}"
    assert "Menu: Menu = Scalar" in text and "Menu as menu_2: Menu = Center" in text, text
    bpy.data.node_groups.remove(tree)
    print("   ✓ Inputs of one name rebuilt")


def test_smooth_functions_and_shader_keys():
    """`smooth_min(a, b, k)` and `smooth_max(a, b, k)` are Math nodes of three operands, and the two
    Shader inputs of Mix Shader and Add Shader are `a` and `b`: both read back as written, and
    Blender's identifiers (`Shader`, `Shader_001`) are still read."""
    print("-> Test: smooth_min, smooth_max, MixShader(a:, b:)...")
    from base_node.host import build_source, export_tree
    from base_node.lang.errors import BnError

    smooth = ("geometry graph blend(a: Float, b: Float, k: Float = 0.25) -> Float {\n"
              "  return smooth_min(a, b, k) + smooth_max(a, 2.0, 0.5)\n}\n")
    tree = build_source(smooth, filename="smooth.bn")[-1]
    ops = sorted(n.operation for n in tree.nodes if n.bl_idname == "ShaderNodeMath")
    assert ops == ["ADD", "SMOOTH_MAX", "SMOOTH_MIN"], ops
    low = next(n for n in tree.nodes if n.bl_idname == "ShaderNodeMath" and n.operation == "SMOOTH_MIN")
    assert [len(i.links) for i in low.inputs] == [1, 1, 1], "smooth_min links its three operands"
    text, warnings = export_tree(tree)
    assert not warnings, warnings
    assert text == smooth, text
    bpy.data.node_groups.remove(tree)

    layers = ("shader graph layers(f: Float = 0.5) -> Shader {\n"
              "  glow = AddShader(a: DiffuseBSDF(), b: Emission())\n"
              "  return MixShader(factor: f, a: glow, b: GlossyBSDF())\n}\n")
    tree = build_source(layers, filename="layers.bn")[-1]
    mix = next(n for n in tree.nodes if n.bl_idname == "ShaderNodeMixShader")
    assert [l.from_node.bl_idname for i in mix.inputs[1:] for l in i.links] == \
        ["ShaderNodeAddShader", "ShaderNodeBsdfAnisotropic"], "a is the first Shader, b the second"
    text, warnings = export_tree(tree)
    assert not warnings, warnings
    assert text == layers, text
    bpy.data.node_groups.remove(tree)
    # By Blender's identifiers, the same tree: it reads back by a and b
    old = layers.replace("a: glow, b:", "Shader: glow, Shader_001:").replace("a: DiffuseBSDF(), b:",
                                                                             "Shader: DiffuseBSDF(), Shader_001:")
    assert "Shader_001: GlossyBSDF()" in old and "Shader_001: Emission()" in old, old
    tree = build_source(old, filename="layers.bn")[-1]
    assert export_tree(tree)[0] == layers, export_tree(tree)[0]
    bpy.data.node_groups.remove(tree)
    # The inputs an error lists are the keys; a shared name is still ambiguous
    try:
        build_source("shader graph g() -> Shader {\n  return MixShader(nope: 1.0)\n}\n", filename="g.bn")
        raise AssertionError("MixShader(nope: …) was built")
    except BnError as err:
        assert "inputs: factor, a, b" in str(err), err
    print("   ✓ smooth_min, smooth_max, MixShader(a:, b:)")


def test_comparisons_in_a_shader_tree():
    """A shader tree has no Compare node: there `<`, `<=`, `>`, `>=`, `==` and `!=` are Math nodes
    giving a Float 0 or 1, and read back as written. A geometry tree keeps its Compare."""
    print("-> Test: Comparisons in a shader tree...")
    from base_node.host import build_source, export_tree
    from base_node.lang.errors import BnError

    def math(tree):
        return [n.operation for n in tree.nodes if n.bl_idname == "ShaderNodeMath"]

    six = ("shader graph six(\n    a: Float,\n    b: Float\n"
           ") -> (gt: Float, lt: Float, ge: Float, le: Float, eq: Float, ne: Float) {\n"
           "  return (gt: a > b, lt: a < b, ge: a >= b, le: a <= b, eq: a == b, ne: a != b)\n}\n")
    tree = build_source(six, filename="six.bn")[-1]
    assert not [n for n in tree.nodes if n.bl_idname == "FunctionNodeCompare"]
    assert sorted(math(tree)) == ["COMPARE", "COMPARE", "GREATER_THAN", "GREATER_THAN", "LESS_THAN", "LESS_THAN",
                                  "SUBTRACT", "SUBTRACT", "SUBTRACT"], math(tree)
    for n in tree.nodes:
        if n.bl_idname == "ShaderNodeMath" and n.operation == "COMPARE":
            assert abs(n.inputs[2].default_value - 0.001) < 1e-9, n.inputs[2].default_value
        if n.bl_idname == "ShaderNodeMath" and n.operation == "SUBTRACT":
            assert n.inputs[0].default_value == 1.0 and not n.inputs[0].links and n.inputs[1].links
    text, warnings = export_tree(tree)
    assert not warnings, warnings
    assert text == six, text
    bpy.data.node_groups.remove(tree)

    def read(body, sig="shader graph g(a: Float, b: Float) -> Float"):
        tree = build_source(f"{sig} {{\n{body}\n}}\n", filename="g.bn")[-1]
        text, warnings = export_tree(tree)
        assert not warnings, warnings
        bpy.data.node_groups.remove(tree)
        return text.split("{\n", 1)[1].rsplit("\n}", 1)[0]

    # Written by hand, the same nodes: they read back as the operator, which then stays
    assert read("  return Math(a, b, operation: GREATER_THAN)") == "  return a > b"
    assert read("  return 1.0 - (a < b)") == "  return a >= b"
    assert read("  return 1.0 - Math(a, b, operation: GREATER_THAN)") == "  return a <= b"
    assert read("  return Math(a, b, 0.001, operation: COMPARE)") == "  return a == b"
    assert read("  return a >= b") == "  return a >= b"
    # Another epsilon is not `==`: Math's own default is 0.5
    assert read("  return Math(a, b, operation: COMPARE)") == \
        "  return Math(Value: a, Value_001: b, operation: COMPARE)"
    assert read("  return Math(a, b, 0.1, operation: COMPARE)") == \
        "  return Math(Value: a, Value_001: b, Value_002: 0.1, operation: COMPARE)"
    # A comparison bound to a name is a node of its own: 1 minus it stays a subtraction
    assert read("  low = a < b\n  return low * (1.0 - low)") == "  low = a < b\n  return low * (1.0 - low)"
    # Twice from 1 is no operator of its own
    assert read("  return 1.0 - (a >= b)") == "  return 1.0 - (a >= b)"
    # In formulas, by precedence
    assert read("  return (a > b) * (a + 1.0 <= b * 2.0)") == "  return (a > b) * (a + 1.0 <= b * 2.0)"

    # Numbers only: a shader tree has no Compare node to compare vectors or colors
    try:
        build_source("shader graph g(v: Vector) -> Float {\n  return v > 0.5\n}\n", filename="g.bn")
        raise AssertionError("a Vector was compared in a shader tree")
    except BnError as err:
        assert "'>' compares numbers only, not Vector: a shader tree has no Compare node" in str(err), err

    # A geometry tree has Compare: nothing changes there, and Math's comparisons stay calls
    geo = ("geometry graph g(a: Float, b: Float) -> (c: Bool, m: Float, n: Float) {\n"
           "  return (\n    c: a >= b,\n    m: Math(Value: a, Value_001: b, operation: GREATER_THAN),\n"
           "    n: 1.0 - Math(Value: a, Value_001: b, operation: LESS_THAN))\n}\n")
    tree = build_source(geo, filename="geo.bn")[-1]
    assert [n.operation for n in tree.nodes if n.bl_idname == "FunctionNodeCompare"] == ["GREATER_EQUAL"]
    text, warnings = export_tree(tree)
    assert not warnings, warnings
    assert text == geo, text
    bpy.data.node_groups.remove(tree)
    print("   ✓ Comparisons in a shader tree")


def test_ternary():
    """`cond ? a : b`: a Switch of the type of its branches in a geometry tree; a Mix by a condition,
    or a Mix Shader, in a shader and a compositor tree, where a Switch takes one value for a whole
    image. Each reads back as written; the nodes that are not one stay calls."""
    print("-> Test: Ternary...")
    from base_node.host import build_source, export_tree
    from base_node.lang.errors import BnError

    def read(source, check=None):
        tree = build_source(source, filename="g.bn")[-1]
        if check is not None:
            check(tree)
        text, warnings = export_tree(tree)
        assert not warnings, warnings
        bpy.data.node_groups.remove(tree)
        return text

    def body(text):
        return text.split("{\n", 1)[1].rsplit("\n}", 1)[0]

    def fails(source, message):
        try:
            build_source(source, filename="g.bn")
            raise AssertionError(f"built: {source}")
        except BnError as err:
            assert message in str(err), err

    # Geometry: a Switch of each type
    geo = ("geometry graph g(\n    m: Geometry,\n    a: Float,\n    b: Float,\n    i: Int,\n    v: Vector,\n"
           "    c: Color,\n    s: String\n"
           ") -> (f: Float, n: Int, w: Vector, k: Color, t: String, g: Geometry, deep: Float, sum: Float) {\n"
           "  return (\n"
           "    f: a > b ? a : b,\n"
           "    n: a > b ? i : 0,\n"
           "    w: a > b ? v : (0.0, 0.0, 1.0),\n"
           "    k: a > b ? c : (1.0, 0.0, 0.0, 1.0),\n"
           "    t: a > b ? s : \"none\",\n"
           "    g: a > b ? SubdivideMesh(m) : m,\n"
           "    deep: a > b ? (a > 0.0 ? 1.0 : 2.0) : b > 0.0 ? 3.0 : 4.0,\n"
           "    sum: (a > b ? a : 0.0) + 1.0)\n}\n")

    def switches(tree):
        types = sorted(n.input_type for n in tree.nodes if n.bl_idname == "GeometryNodeSwitch")
        assert types == sorted(["FLOAT", "INT", "VECTOR", "RGBA", "STRING", "GEOMETRY"] + ["FLOAT"] * 4), types
        assert not [n for n in tree.nodes if n.bl_idname == "ShaderNodeMix"]

    assert read(geo, switches) == geo, read(geo)

    def geometry(text, expected=None):
        out = body(read(f"geometry graph g(m: Geometry, on: Bool, a: Float, r: Rotation) -> Geometry {{\n{text}\n}}\n"))
        assert expected is None or out == expected, out
        return out

    # A Switch written as a call is the same node: it reads back as the ternary, which then stays
    geometry("  return Switch(switch: on, false_: m, true_: SubdivideMesh(m))",
             "  return on ? SubdivideMesh(m) : m")
    # A branch left alone is written in a ternary, when the text can write it
    geometry("  return SetPosition(m, offset: Switch(switch: on, true_: a))",
             "  return SetPosition(m, offset: on ? a : 0.0)")
    # …and where it cannot (no geometry), the Switch stays a call
    geometry("  return Switch(switch: on, true_: m)",
             "  return Switch(switch: on, true_: m, input_type: GEOMETRY)")
    # A Switch nothing switches stays a call
    geometry("  return Switch(false_: m, true_: SubdivideMesh(m))",
             "  return Switch(false_: m, true_: SubdivideMesh(m), input_type: GEOMETRY)")
    # A Switch whose type its branches do not give says it, in a call: a Rotation's tuple reads as a Vector
    kept = "  x = Switch(switch: on, false_: (0.0, 0.0, 0.0), true_: r, input_type: ROTATION)\n" \
           "  return m\n    |> RotateInstances(rotation: x)"
    text = geometry(kept)
    assert "Switch(switch: on, true_: r, input_type: ROTATION)" in text and "?" not in text, text
    # In a geometry tree a Mix is a Mix
    assert geometry("  return m |> SetPosition(offset: Mix(factor: a > 0.5, a: (0.0, 0.0, 0.0), b: (0.0, 0.0, 1.0)))") \
        .count("?") == 0

    # Shader: a Mix by a condition, a Mix Shader for shaders
    shade = ("shader graph g(a: Float, b: Float, v: Vector, c: Color, on: Bool) -> (f: Float, w: Vector, "
             "k: Color, s: Shader, n: Float) {\n"
             "  return (\n"
             "    f: a > b ? a : b,\n"
             "    w: a >= b ? v : (0.0, 0.0, 1.0),\n"
             "    k: on ? c : (1.0, 0.0, 0.0, 1.0),\n"
             "    s: a == b ? DiffuseBSDF() : GlossyBSDF(),\n"
             "    n: a < b ? 1.0 : a > 1.0 ? 2.0 : 3.0)\n}\n")

    def mixes(tree):
        types = sorted(n.data_type for n in tree.nodes if n.bl_idname == "ShaderNodeMix")
        assert types == ["FLOAT", "FLOAT", "FLOAT", "RGBA", "VECTOR"], types
        assert len([n for n in tree.nodes if n.bl_idname == "ShaderNodeMixShader"]) == 1
        assert not [n for n in tree.nodes if n.bl_idname == "GeometryNodeSwitch"]
        for n in tree.nodes:
            if n.bl_idname == "ShaderNodeMix":
                assert n.blend_type == "MIX" and n.factor_mode == "UNIFORM" and n.clamp_factor

    from base_node.lang import format_source
    shade = format_source(shade)
    assert read(shade, mixes) == shade, read(shade)

    def shader(text, sig="shader graph g(a: Float, b: Float, on: Bool, c: Color) -> Float"):
        return body(read(f"{sig} {{\n{text}\n}}\n"))

    # By hand, the same nodes
    assert shader("  return Mix(factor: a > b, a: 1.0, b: 2.0)") == "  return a > b ? 2.0 : 1.0"
    assert shader("  hot = a > b\n  return hot * (hot ? a : b)") == "  hot = a > b\n  return hot * (hot ? a : b)"
    # A Mix by any number blends: it stays a call, and so does one with a setting of its own
    assert shader("  return Mix(factor: a, a: 1.0, b: 2.0)") == "  return Mix(factor: a, a: 1.0, b: 2.0)"
    assert "?" not in shader("  return Mix(factor: a > b, a: c, b: (1.0, 0.0, 0.0, 1.0), blend_type: MULTIPLY, "
                             "data_type: RGBA).x")
    # A Switch of a shader tree stays a Switch
    assert shader("  return Switch(switch: on, false_: a, true_: b)").startswith(
        "  return Switch(switch: on, false_: a, true_: b")
    fails("shader graph g(a: Float, b: Float) -> Float {\n  return a ? 1.0 : b\n}\n",
          "the condition of '? :' is a Float: in a shader tree it is built with Mix, which blends by any number")
    fails('shader graph g(on: Bool) -> Float {\n  x = on ? "a" : "b"\n  return 1.0\n}\n',
          "'? :' chooses between Float, Vector, Color, Rotation and Shader in a shader tree, not String")

    # Compositor: a Mix too, by a Compare
    comp = ("compositor graph g(image: Color, a: Float, b: Float) -> (image: Color, f: Float) {\n"
            "  return (image: a > b ? image : (0.0, 0.0, 0.0, 1.0), f: a <= b ? a : b)\n}\n")

    def composite(tree):
        assert sorted(n.data_type for n in tree.nodes if n.bl_idname == "ShaderNodeMix") == ["FLOAT", "RGBA"]
        assert len([n for n in tree.nodes if n.bl_idname == "FunctionNodeCompare"]) == 2
        assert not [n for n in tree.nodes if n.bl_idname in ("GeometryNodeSwitch", "CompositorNodeSwitch")]

    assert read(comp, composite) == comp, read(comp)
    fails('compositor graph g(on: Bool, s: String) -> Float {\n  x = on ? "a" : s\n  return 1.0\n}\n',
          "'? :' chooses between Float, Vector, Color and Rotation in a compositor tree, not String")

    # What a geometry Switch gives is the branch chosen
    counts = []
    for big in ("false", "true"):
        tree = build_source(f"geometry graph pick() -> Geometry {{\n  big = {big}\n"
                            "  return big ? Grid(vertices_x: 4, vertices_y: 4) : Grid(vertices_x: 2, vertices_y: 2)\n}\n",
                            filename="pick.bn")[-1]
        obj = bpy.data.objects.new("pick", bpy.data.meshes.new("pick"))
        bpy.context.scene.collection.objects.link(obj)
        obj.modifiers.new("pick", "NODES").node_group = tree
        counts.append(len(obj.evaluated_get(bpy.context.evaluated_depsgraph_get()).data.vertices))
        bpy.data.objects.remove(obj)
        bpy.data.node_groups.remove(tree)
    assert counts == [4, 16], counts
    print("   ✓ Ternary")


def test_outputs_of_one_name_rebuilt():
    """Two outputs of one name, as in the compositor Essentials' Film Grain, are returned by key:
    their shared name would be ambiguous."""
    print("-> Test: Outputs of one name rebuilt...")
    from base_node.host import build_source, export_tree

    tree = bpy.data.node_groups.new("TwinOutputs", "GeometryNodeTree")
    tree.interface.new_socket("Lvl 1", in_out="OUTPUT", socket_type="NodeSocketColor")
    tree.interface.new_socket("Lvl 1", in_out="OUTPUT", socket_type="NodeSocketFloat")
    gout = tree.nodes.new("NodeGroupOutput")
    noise = tree.nodes.new("ShaderNodeTexNoise")
    tree.links.new(noise.outputs["Color"], gout.inputs[0])
    tree.links.new(noise.outputs[1], gout.inputs[1])  # Fac, Factor since 5.3
    noise_float = noise.outputs[1].name
    text, _ = export_tree(tree)
    assert '-> ("Lvl 1": Color, "Lvl 1" as lvl_1_float: Float)' in text, text
    assert "lvl_1: noise_texture.color" in text and "lvl_1_float: noise_texture" in text, text
    bpy.data.node_groups.remove(tree)
    rebuilt = build_source(text, filename="twin_outputs.bn")[-1]
    outputs = [(i.name, i.socket_type) for i in rebuilt.interface.items_tree
               if i.item_type == "SOCKET" and i.in_out == "OUTPUT"]
    assert outputs == [("Lvl 1", "NodeSocketColor"), ("Lvl 1", "NodeSocketFloat")], outputs
    gout = next(n for n in rebuilt.nodes if n.bl_idname == "NodeGroupOutput")
    assert [l.from_socket.name for l in gout.inputs[0].links] == ["Color"], gout.inputs[0].links
    assert [l.from_socket.name for l in gout.inputs[1].links] == [noise_float], gout.inputs[1].links
    again, _ = export_tree(rebuilt)
    assert again == text, f"not stable:\n{text}\n---\n{again}"
    bpy.data.node_groups.remove(rebuilt)
    print("   ✓ Outputs of one name rebuilt")


TUPLE_TYPES = """geometry graph tuple_types(geometry: Geometry, b: Bool, i: Int) -> Geometry {
  sw = Switch(b, (1.0, 0.0, 0.0), (0.5, 0.5, 0.0))
  sw_link = Switch(b, Position(), (0.5, 0.5, 0.0))
  sw_color = Switch(b, (1.0, 0.0, 0.0, 1.0), (0.5, 0.5, 0.0))
  mix = Mix(0.5, (1.0, 0.0, 0.0), (0.5, 0.5, 0.0))
  mix_color = Mix(0.5, (1.0, 0.0, 0.0, 1.0), (0.0, 0.0, 1.0, 1.0))
  above = Compare(Position(), (0.5, 0.5, 0.0))
  index = IndexSwitch(i, 1.0, (0.5, 0.5, 0.0))
  menu = MenuSwitch(A: (1.0, 0.0, 0.0), B: (0.5, 0.5, 0.0, 1.0))
  return geometry
    |> StoreNamedAttribute(name: "sw", value: sw + sw_link + mix, data_type: FLOAT_VECTOR)
    |> StoreNamedAttribute(name: "color", value: sw_color, data_type: FLOAT_COLOR)
    |> StoreNamedAttribute(name: "mix", value: mix_color, data_type: FLOAT_COLOR)
    |> StoreNamedAttribute(name: "above", value: above, data_type: BOOLEAN)
    |> StoreNamedAttribute(name: "index", value: index, data_type: FLOAT_VECTOR)
    |> StoreNamedAttribute(name: "menu", value: menu.output, data_type: FLOAT_COLOR)
    |> StoreNamedAttribute(name: "store", value: (0.0, 0.0, 1.0))
}
"""


def graph_shape(tree):
    """The nodes of `tree` with their type settings and the values of their free inputs, and its links:
    what two builds of one graph share, whatever their node names and places."""
    def value(sock):
        v = getattr(sock, "default_value", None)
        return tuple(round(x, 6) for x in v) if hasattr(v, "__len__") and not isinstance(v, str) else v

    def settings(n):
        return tuple((p, getattr(n, p)) for p in ("input_type", "data_type", "operation") if hasattr(n, p))

    def label(n):
        return (n.bl_idname, settings(n),
                tuple((s.identifier, value(s)) for s in n.inputs if s.enabled and not s.links))

    nodes = sorted(label(n) for n in tree.nodes)
    links = sorted((label(l.from_node), l.from_socket.identifier, label(l.to_node), l.to_socket.identifier)
                   for l in tree.links)
    return nodes, links


def test_tuples_choose_the_type():
    """A tuple only fits a Vector or a Color: Switch, Mix, Compare, the switches of items and Store
    Named Attribute take the type of their tuples when the text writes none, Color for 4 numbers."""
    print("-> Test: Tuples choose the type...")
    from base_node.host import build_source, export_tree
    from base_node.host.schema import BlenderSchema
    from base_node.lang import compile_source
    from base_node.lang.errors import BnError

    tree = build_source(TUPLE_TYPES, filename="tuple_types.bn")[-1]
    types = sorted((n.bl_idname, getattr(n, "input_type", None) or n.data_type) for n in tree.nodes
                   if hasattr(n, "input_type") or hasattr(n, "data_type"))
    assert types == [
        ("FunctionNodeCompare", "VECTOR"),
        ("GeometryNodeIndexSwitch", "VECTOR"),
        ("GeometryNodeMenuSwitch", "RGBA"),
        ("GeometryNodeStoreNamedAttribute", "BOOLEAN"),
        ("GeometryNodeStoreNamedAttribute", "FLOAT_COLOR"),
        ("GeometryNodeStoreNamedAttribute", "FLOAT_COLOR"),
        ("GeometryNodeStoreNamedAttribute", "FLOAT_COLOR"),
        ("GeometryNodeStoreNamedAttribute", "FLOAT_VECTOR"),
        ("GeometryNodeStoreNamedAttribute", "FLOAT_VECTOR"),
        ("GeometryNodeStoreNamedAttribute", "FLOAT_VECTOR"),
        ("GeometryNodeSwitch", "RGBA"),
        ("GeometryNodeSwitch", "VECTOR"),
        ("GeometryNodeSwitch", "VECTOR"),
        ("ShaderNodeMix", "RGBA"),
        ("ShaderNodeMix", "VECTOR"),
    ], types
    sw = next(n for n in tree.nodes if n.bl_idname == "GeometryNodeSwitch" and not n.inputs["False"].links
              and n.input_type == "RGBA")
    assert tuple(sw.inputs["True"].default_value) == (0.5, 0.5, 0.0, 1.0), tuple(sw.inputs["True"].default_value)
    # Tree -> text -> tree: the same graph
    text, _ = export_tree(tree)
    first = graph_shape(tree)
    bpy.data.node_groups.remove(tree)
    rebuilt = build_source(text, filename="tuple_types.bn")[-1]
    assert graph_shape(rebuilt) == first, f"not the same graph:\n{text}"
    again, _ = export_tree(rebuilt)
    assert again == text, f"not stable:\n{text}\n---\n{again}"
    bpy.data.node_groups.remove(rebuilt)

    # The example of the docs: no input_type or data_type for its switches, the same graph read back
    material = bpy.data.materials.new("TupleTiles")
    example = (LIB_ROOT / "examples" / "tuple_tiles.bn").read_text(encoding="utf-8")
    tree = build_source(example, filename="tuple_tiles.bn")[-1]
    types = sorted((n.bl_idname, getattr(n, "input_type", None) or n.data_type) for n in tree.nodes
                   if n.bl_idname in ("GeometryNodeSwitch", "GeometryNodeIndexSwitch", "ShaderNodeMix"))
    assert types == [("GeometryNodeIndexSwitch", "RGBA"), ("GeometryNodeSwitch", "VECTOR"),
                     ("ShaderNodeMix", "RGBA")], types
    text, _ = export_tree(tree)
    first = graph_shape(tree)
    bpy.data.node_groups.remove(tree)
    rebuilt = build_source(text, filename="tuple_tiles.bn")[-1]
    assert graph_shape(rebuilt) == first, f"not the same graph:\n{text}"
    again, _ = export_tree(rebuilt)
    assert again == text, f"not stable:\n{text}\n---\n{again}"
    bpy.data.node_groups.remove(rebuilt)
    bpy.data.materials.remove(material)

    # What Blender cannot build, the checker refuses
    refused = {
        "Switch(b, (1.0, 0.0), (0.5, 0.5))":
            "Switch.false_ expects a Vector of 3 numbers, receives 2; write (1.0, 0.0, 0.0)",
        "Switch(b, (1.0, 0.0, 0.0), 2.0, input_type: FLOAT)": "Switch.false_ expects Float, receives a Vector tuple",
        "Mix(0.5, (1.0, 0.0, 0.0, 1.0), Position(), data_type: VECTOR)":
            "Mix.a expects a Vector of 3 numbers, receives 4; write (1.0, 0.0, 0.0)",
    }
    with BlenderSchema() as schema:
        for value, message in refused.items():
            src = (f"geometry graph refused(geometry: Geometry, b: Bool) -> Geometry {{\n  v = {value}\n"
                   f'  return StoreNamedAttribute(geometry, name: "v", value: v, data_type: FLOAT_VECTOR)\n}}\n')
            try:
                compile_source(src, schema, "refused.bn")
            except BnError as e:
                got = [d.message for d in e.diagnostics]
                assert message in got, (value, got)
            else:
                raise AssertionError(f"{value}: accepted, but Blender cannot build it")
    print("   ✓ Tuples choose the type")


SWITCH_TYPES = """\
compositor graph frame_or_zero(animated: Bool) -> Float {
  return Switch(switch: animated, false_: 0.0, true_: SceneTime().frame)
}

shader graph value_or_zero(on: Bool, x: Float) -> Float {
  return Switch(switch: on, false_: 0.0, true_: x * 2.0)
}

compositor graph colour_switch(on: Bool, image: Color) -> Color {
  return Switch(switch: on, false_: image, true_: (0.0, 0.0, 0.0, 1.0))
}

compositor graph written_type(on: Bool, x: Float) -> Color {
  return Switch(switch: on, false_: x, true_: 1.0, input_type: RGBA)
}

geometry graph count_or_size(on: Bool, x: Float, i: Int) -> Float {
  return Switch(on, 1, 2) + Switch(on, 1, x) + Switch(on, 1, x, input_type: INT) + Switch(on, i, 2, input_type: FLOAT)
}
"""


def test_switch_takes_the_type_of_its_values():
    """A Switch whose input_type the text does not write takes the type of its values, a linked one
    first: a Float switch in a compositor or a shader tree, where a new Switch is a Color one. Read
    back, input_type is written where it is not a new Switch's, and where the values tell another."""
    print("-> Test: Switch takes the type of its values...")
    from base_node.host import build_source, export_tree

    trees = build_source(SWITCH_TYPES, filename="switch_types.bn")
    switches = {t.name: sorted(n.input_type for n in t.nodes if n.bl_idname == "GeometryNodeSwitch")
                for t in trees}
    assert switches == {
        "frame_or_zero": ["FLOAT"],
        "value_or_zero": ["FLOAT"],
        "colour_switch": ["RGBA"],
        "written_type": ["RGBA"],
        "count_or_size": ["FLOAT", "FLOAT", "INT", "INT"],
    }, switches
    frame = next(t for t in trees if t.name == "frame_or_zero")
    sw = next(n for n in frame.nodes if n.bl_idname == "GeometryNodeSwitch")
    assert sw.outputs[0].type == "VALUE" and sw.inputs["True"].links[0].from_node.bl_idname == \
        "CompositorNodeSceneTime", (sw.outputs[0].type, sw.inputs["True"].links)
    # Tree -> text -> tree: the same graph; a Float switch of a compositor tree says it is one, as a
    # Float one of a geometry tree whose values are integers
    for name in list(switches):
        tree = bpy.data.node_groups[name]
        text, _ = export_tree(tree)
        assert text.count("input_type") == {"frame_or_zero": 1, "value_or_zero": 1,
                                            "count_or_size": 2}.get(name, 0), text
        first = graph_shape(tree)
        rebuilt = build_source(text, filename=f"{name}.bn")[-1]
        assert graph_shape(rebuilt) == first, f"not the same graph:\n{text}"
        again, _ = export_tree(rebuilt)
        assert again == text, f"not stable:\n{text}\n---\n{again}"
        bpy.data.node_groups.remove(rebuilt)
    for name in switches:
        if name in bpy.data.node_groups:
            bpy.data.node_groups.remove(bpy.data.node_groups[name])
    print("   ✓ Switch takes the type of its values")


def test_vector_output_dimensions():
    """A 2D Vector output, as in the compositor Essentials' Transform and Project, stays 2D: an output
    has no default to give its size, so it is written as an option."""
    print("-> Test: Vector output dimensions...")
    from base_node.host import build_source, export_tree

    tree = bpy.data.node_groups.new("FlatVector", "CompositorNodeTree")
    item = tree.interface.new_socket("UV", in_out="OUTPUT", socket_type="NodeSocketVector")
    item.dimensions = 2
    tree.interface.new_socket("Depth", in_out="OUTPUT", socket_type="NodeSocketVector")
    text, _ = export_tree(tree)
    assert "UV: Vector(dimensions: 2)" in text and "Depth: Vector)" in text, text
    bpy.data.node_groups.remove(tree)
    rebuilt = build_source(text, filename="flat_vector.bn")[-1]
    dims = [i.dimensions for i in rebuilt.interface.items_tree if i.item_type == "SOCKET"]
    assert dims == [2, 3], dims
    again, _ = export_tree(rebuilt)
    assert again == text, f"not stable:\n{text}\n---\n{again}"
    bpy.data.node_groups.remove(rebuilt)
    try:
        build_source('compositor graph bad(uv: Vector(dimensions: 2)) -> Float { return 1.0 }',
                     filename="bad.bn")
        raise AssertionError("an input's dimensions given as an option was accepted")
    except Exception as e:
        assert "written from default size" in str(e), e
    print("   ✓ Vector output dimensions kept")


def test_shader_constants_and_old_names():
    """An RGB node keeps its color, in a shader and a compositor tree, and a node named as Blender 2.8
    named it (`ColorRamp`) is not taken for a name given by hand: it would hide the call."""
    print("-> Test: Shader constants and old names...")
    from base_node.host import build_source, export_tree

    for tree_type, rgb in (("ShaderNodeTree", "ShaderNodeRGB"), ("CompositorNodeTree", "CompositorNodeRGB")):
        tree = bpy.data.node_groups.new("Red", tree_type)
        tree.interface.new_socket("Color", in_out="OUTPUT", socket_type="NodeSocketColor")
        node = tree.nodes.new(rgb)
        node.outputs[0].default_value = (1.0, 0.0, 0.0, 1.0)
        tree.links.new(node.outputs[0], tree.nodes.new("NodeGroupOutput").inputs[0])
        text, _ = export_tree(tree)
        assert "color = (1.0, 0.0, 0.0, 1.0)" in text, text
        bpy.data.node_groups.remove(tree)
        rebuilt = build_source(text, filename="red.bn")[-1]
        colors = [tuple(n.outputs[0].default_value) for n in rebuilt.nodes if n.bl_idname == rgb]
        assert colors == [(1.0, 0.0, 0.0, 1.0)], (tree_type, colors)
        bpy.data.node_groups.remove(rebuilt)

    tree = bpy.data.node_groups.new("Ramped", "ShaderNodeTree")
    tree.interface.new_socket("Fac", in_out="INPUT", socket_type="NodeSocketFloat")
    tree.interface.new_socket("Color", in_out="OUTPUT", socket_type="NodeSocketColor")
    ramp = tree.nodes.new("ShaderNodeValToRGB")
    ramp.name = "ColorRamp"
    mix = tree.nodes.new("ShaderNodeMix")
    mix.data_type = "RGBA"
    tree.links.new(tree.nodes.new("NodeGroupInput").outputs[0], ramp.inputs[0])
    tree.links.new(ramp.outputs[0], mix.inputs["A"] if "A" in mix.inputs else mix.inputs[6])
    tree.links.new(ramp.outputs[0], mix.inputs[7])
    tree.links.new(mix.outputs[2], tree.nodes.new("NodeGroupOutput").inputs[0])
    text, _ = export_tree(tree)
    assert "color_ramp = ColorRamp(" in text and "ColorRamp = " not in text, text
    bpy.data.node_groups.remove(tree)
    rebuilt = build_source(text, filename="ramped.bn")[-1]
    again, _ = export_tree(rebuilt)
    assert again == text, f"not stable:\n{text}\n---\n{again}"
    bpy.data.node_groups.remove(rebuilt)
    print("   ✓ Shader constants and old names verified")


def test_states_named_like_the_zone():
    """A Repeat state named `Iteration`, beside the zone's own iteration, keeps its own links
    when built again (T-51)."""
    print("-> Test: States named like the zone...")
    tree = bpy.data.node_groups.new("CountedTwice", "GeometryNodeTree")
    tree.interface.new_socket("Value", in_out="OUTPUT", socket_type="NodeSocketInt")
    nodes, links = tree.nodes, tree.links
    gout = nodes.new("NodeGroupOutput")
    zin, zout = nodes.new("GeometryNodeRepeatInput"), nodes.new("GeometryNodeRepeatOutput")
    zin.pair_with_output(zout)
    zout.repeat_items.clear()
    zout.repeat_items.new("INT", "Iteration")
    zin.inputs["Iterations"].default_value = 4
    add = nodes.new("ShaderNodeMath")
    add.operation = "MULTIPLY"
    # The state times the zone's iteration: either one on the other's input reads otherwise
    links.new(zin.outputs[1], add.inputs[0])
    links.new(zin.outputs[0], add.inputs[1])
    links.new(add.outputs[0], zout.inputs[0])
    links.new(zout.outputs[0], gout.inputs[0])
    text, warnings = stable(tree)
    assert not warnings, warnings
    assert "Iteration: 0" in text and "Iteration * iteration" in text, text

    from base_node.host import build_source
    rebuilt = build_source(text, filename="CountedTwice.bn")[-1]
    zin = next(n for n in rebuilt.nodes if n.bl_idname == "GeometryNodeRepeatInput")
    used = {(link.from_socket.identifier, link.to_socket.identifier) for link in rebuilt.links
            if link.from_node == zin and link.to_node.bl_idname == "ShaderNodeMath"}
    assert used == {(zin.outputs[1].identifier, "Value"), ("Iteration", "Value_001")}, used
    bpy.data.node_groups.remove(rebuilt)
    print("   ✓ States named like the zone")


def test_node_names():
    """A node is written by its English UI name in one word, the only name read (T-53)."""
    print("-> Test: Node names...")
    from base_node.host import build_source
    from base_node.host.schema import BlenderSchema
    from base_node.lang import BnError

    with BlenderSchema() as schema:
        def name(kind, idname):
            return schema.node_of(kind, idname).name

        assert name("shader", "ShaderNodeBsdfPrincipled") == "PrincipledBSDF"
        assert name("shader", "ShaderNodeTexNoise") == "NoiseTexture"
        assert name("geometry", "ShaderNodeSeparateXYZ") == "SeparateXYZ"
        assert name("geometry", "GeometryNodeSetPosition") == "SetPosition"
        assert name("geometry", "GeometryNodeFieldAtIndex") == "EvaluateAtIndex"
        assert name("shader", "ShaderNodeMixRGB") == "MixLegacy" and name("shader", "ShaderNodeMix") == "Mix"
        # A label that is no identifier keeps the former name
        assert name("geometry", "GeometryNodeTool3DCursor") == "Tool3DCursor"
        # The colliding pairs of a compositor tree: the node of its Add menu takes the UI name
        assert name("compositor", "CompositorNodeCurveRGB") == "RGBCurves"
        assert name("compositor", "ShaderNodeRGBCurve") == "RGBCurve"
        assert name("shader", "ShaderNodeRGBCurve") == "RGBCurves"
        assert name("compositor", "GeometryNodeSwitch") == "Switch"
        assert name("compositor", "CompositorNodeSwitch") == "CompositorNodeSwitch"
        # Names are unique in each kind, and an old name is never one of them
        for kind in ("geometry", "shader", "compositor"):
            names = schema.node_names(kind)
            assert len(names) == len(set(names)), kind
            assert not set(schema.renamed(kind)) & set(names), kind

    def error(source):
        try:
            build_source(source, "t.bn")
        except BnError as e:
            return str(e.diagnostics[0])
        raise AssertionError(f"built: {source}")

    assert error("shader graph s() -> Shader {\n  return BsdfPrincipled()\n}") \
        == "t.bn:2:10  unknown node 'BsdfPrincipled' in a shader tree; it is now written PrincipledBSDF"
    assert error("shader graph s() -> Shader {\n  return ShaderNodeBsdfPrincipled()\n}") \
        == "t.bn:2:10  unknown node 'ShaderNodeBsdfPrincipled' in a shader tree; it is now written PrincipledBSDF"
    assert error("shader graph s() -> Float {\n  return noise_texture().fac\n}") \
        == "t.bn:2:10  unknown node 'noise_texture' in a shader tree; did you mean NoiseTexture?"
    assert error("geometry graph g() -> Geometry {\n  return meshline()\n}") \
        == "t.bn:2:10  unknown node 'meshline' in a geometry tree; did you mean MeshLine?"
    print("   ✓ UI names written and read, old names refused with the new one")


def test_group_without_tree():
    """A Group node whose tree is missing reads as `Group()` and builds again (T-50)."""
    print("-> Test: Group without tree...")
    tree = bpy.data.node_groups.new("NoTreeCaller", "GeometryNodeTree")
    tree.interface.new_socket("Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
    tree.interface.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    gin, gout = tree.nodes.new("NodeGroupInput"), tree.nodes.new("NodeGroupOutput")
    tree.links.new(gin.outputs[0], gout.inputs[0])
    tree.nodes.new("GeometryNodeGroup")
    text, warnings = stable(tree)
    assert "= Group()" in text, text
    assert any("no tree" in w for w in warnings), warnings
    rebuilt = bpy.data.node_groups["NoTreeCaller"]
    empty = [n for n in rebuilt.nodes if n.bl_idname == "GeometryNodeGroup"]
    assert len(empty) == 1 and empty[0].node_tree is None, empty
    bpy.data.node_groups.remove(rebuilt)
    print("   ✓ Group without tree verified")


def caller(group, fed):
    """A modifier tree calling `group`: the object's geometry into its geometry inputs, Position
    into its float and vector inputs when `fed`, and each of its field outputs stored as an attribute."""
    t = bpy.data.node_groups.new(f".calls {group.name}", "GeometryNodeTree")
    t.interface.new_socket("Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
    t.interface.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    gin, gout = t.nodes.new("NodeGroupInput"), t.nodes.new("NodeGroupOutput")
    call = t.nodes.new("GeometryNodeGroup")
    call.node_tree = group
    position = t.nodes.new("GeometryNodeInputPosition")
    xyz = t.nodes.new("ShaderNodeSeparateXYZ")
    t.links.new(position.outputs[0], xyz.inputs[0])
    for s in call.inputs:
        if s.type == "GEOMETRY":
            t.links.new(gin.outputs[0], s)
        elif fed and s.type == "VECTOR":
            t.links.new(position.outputs[0], s)
        elif fed and s.type in ("VALUE", "INT"):
            t.links.new(xyz.outputs[0], s)
    out = next((s for s in call.outputs if s.type == "GEOMETRY"), gin.outputs[0])
    for i, s in enumerate(call.outputs):
        if s.type in STORED:
            store = t.nodes.new("GeometryNodeStoreNamedAttribute")
            store.data_type = STORED[s.type]
            store.inputs["Name"].default_value = f"out_{i}"
            t.links.new(out, store.inputs["Geometry"])
            t.links.new(s, store.inputs["Value"])
            out = store.outputs[0]
    t.links.new(out, gout.inputs[0])
    return t


def attribute_values(a):
    """The values of the attribute `a`, flat, floats rounded to 4 decimals: read in one call, not item by item."""
    import numpy as np

    n = len(a.data)
    first = a.data[0] if n else None
    key = next((k for k in ("vector", "value", "color") if hasattr(first, k)), None)
    if key is None:
        return np.empty(0)
    v = getattr(first, key)
    if isinstance(v, str):
        return np.array([getattr(item, key) for item in a.data])
    if not hasattr(v, "__len__"):
        flat = [v]
    elif len(v) and hasattr(v[0], "__len__"):  # a matrix is rows of floats
        flat = [y for x in v for y in x]
    else:
        flat = list(v)
    sample = flat[0] if flat else 0.0
    dtype = np.bool_ if isinstance(sample, bool) else np.int32 if isinstance(sample, int) else np.float32
    values = np.empty(n * len(flat), dtype=dtype)
    a.data.foreach_get(key, values)
    if dtype is np.float32:
        values = np.round(values.astype(np.float64), 4) + 0.0  # + 0.0: -0.0 is 0.0
    return values


def fingerprint(obj):
    """Sizes and rounded values of every attribute of the evaluated geometry of `obj`."""
    geometry = obj.evaluated_get(bpy.context.evaluated_depsgraph_get()).evaluated_geometry()
    found = {}
    for component in ("mesh", "curves", "pointcloud"):
        data = getattr(geometry, component, None)
        if data is None:
            continue
        for a in data.attributes:
            if a.name.startswith("."):
                continue
            values = attribute_values(a)
            found[f"{component}:{a.domain}:{a.name}:{a.data_type}"] = (len(a.data), hash(values.tobytes()))
    instances = geometry.instances_pointcloud()
    found["instances"] = len(instances.points) if instances is not None else 0
    return found


EVALUATIONS = ("mesh", "curves", "mesh caller", "mesh caller fed")


def evaluations(group, kinds=EVALUATIONS):
    """The kinds of `evaluate` that fit `group`: as a modifier only when its first output is a
    geometry and it has a Group Output (else Blender warns on every frame and evaluates nothing);
    through a caller always."""
    outputs = [i for i in group.interface.items_tree if i.item_type == "SOCKET" and i.in_out == "OUTPUT"]
    modifier = (bool(outputs) and outputs[0].socket_type == "NodeSocketGeometry"
                and any(n.bl_idname == "NodeGroupOutput" for n in group.nodes))
    return tuple(k for k in kinds if modifier or "caller" in k)


def evaluate(group, kind):
    """Fingerprints of `group` as a modifier on a fresh mesh or curves object, over a few frames."""
    # The objects of the scene go; those a group uses, appended with it, out of any scene, stay
    for o in [o for o in bpy.data.objects if o.users_scene]:
        bpy.data.objects.remove(o)
    scene = bpy.context.scene
    scene.frame_set(1)
    if kind.startswith("mesh"):
        bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=3)
    else:
        bpy.ops.curve.primitive_bezier_circle_add()
        bpy.ops.object.convert(target="CURVES")
    obj = bpy.context.object
    modifier = obj.modifiers.new("GN", "NODES")
    modifier.node_group = caller(group, kind.endswith("fed")) if "caller" in kind else group
    # The simulations step from frame to frame
    prints = []
    for frame in (1, 2, 3, 10):
        scene.frame_set(frame)
        prints.append(fingerprint(obj))
    return prints


def credits(name):
    """The header of the .bn of an asset of the fixture: where it comes from, under which license."""
    return (f"// {name}, from Cartesian Caramel's Everyday Nodes\n"
            "// Author: Cartesian Caramel\n"
            "// Source: https://github.com/cartesiancaramel/blender-remote-asset-library-test-v1 (6c078f7)\n"
            "// License: CC0-1.0, https://creativecommons.org/publicdomain/zero/1.0/\n"
            "// Written by Base Node from tests/fixtures/everyday_geometry_nodes.blend;\n"
            "// to write it again: BASE_NODE_UPDATE_FIXTURES=1, see tests/fixtures/README.md\n"
            "\n")


def test_arrange():
    """10. Arrange a tree: links go left to right, no two nodes overlap, frames keep their nodes."""
    print("-> Test 10: Arranging nodes...")
    from base_node.host import build_source
    from base_node.host.arrange import _box, arrange_nodes

    src = """
geometry graph ripple(geometry: Geometry, frequency: Float = 2.0, amplitude: Float = 0.5) -> Geometry {
  p = Position()
  "Height" {
    r = length(p)
    h = sin(r * frequency) * amplitude
  }
  return SetPosition(geometry, offset: CombineXYZ(z: h))
}
"""
    tree = build_source(src, filename="ripple.bn")[0]
    nodes = [n for n in tree.nodes if n.bl_idname != "NodeFrame"]
    for i, n in enumerate(nodes):  # scrambled
        n.location_absolute = ((i * 377) % 900, (i * 613) % 700)
    assert arrange_nodes(tree) == len(nodes)

    for l in tree.links:
        assert l.from_node.location_absolute.x < l.to_node.location_absolute.x, \
            f"{l.from_node.name} -> {l.to_node.name} goes right to left"
    scale = bpy.context.preferences.system.ui_scale or 1.0
    rects = []
    for n in nodes:
        b = _box(n, scale)
        rects.append((n.name, b.x, b.y, b.x + b.width, b.y - b.height))
    for i, (a, ax0, ay0, ax1, ay1) in enumerate(rects):
        for b, bx0, by0, bx1, by1 in rects[i + 1:]:
            assert ax1 <= bx0 or bx1 <= ax0 or ay1 >= by0 or by1 >= ay0, f"{a} and {b} overlap"
    framed = {n.name for n in nodes if n.parent}
    assert framed, "the frame lost its nodes"
    inside = [r for r in rects if r[0] in framed]
    left, right = min(r[1] for r in inside), max(r[3] for r in inside)
    top, bottom = max(r[2] for r in inside), min(r[4] for r in inside)
    for name, x0, y0, x1, y1 in rects:
        if name not in framed:
            assert x1 <= left or x0 >= right or y1 >= top or y0 <= bottom, f"{name} is inside the frame"
    print(f"   ✓ {len(nodes)} nodes arranged")


def test_idioms_build():
    """Every example of spec/idioms.md builds as it is written."""
    print("-> Test: The examples of the idioms build...")
    import re

    from base_node.host import build_source

    text = (LIB_ROOT / "spec" / "idioms.md").read_text(encoding="utf-8")
    blocks = re.findall(r"```bn\n(.*?)```", text, re.S)
    assert len(blocks) >= 10, len(blocks)
    for i, block in enumerate(blocks):
        before = set(bpy.data.node_groups)
        build_source(block, f"idiom_{i}.bn")
        bpy.data.batch_remove([g for g in bpy.data.node_groups if g not in before])
    print(f"   ✓ {len(blocks)} examples built")


def test_real_world_assets():
    """8. Third-party assets (tests/fixtures, CC0) read as text, built back, evaluate the same."""
    print("-> Test 8: Real-world assets...")
    from base_node.host import build_source, export_tree
    from base_node.lang.schema import key

    fixture = EXT_DIR / "tests" / "fixtures" / "everyday_geometry_nodes.blend"
    with bpy.data.libraries.load(str(fixture), link=False) as (src, dst):
        dst.node_groups = list(src.node_groups)
    loaded = list(dst.node_groups)
    assets = sorted((g for g in loaded if g.asset_data is not None), key=lambda g: g.name)
    assert len(assets) == 17, [g.name for g in assets]

    texts = {}
    for g in assets:
        text, warnings = export_tree(g)
        # Only frames interleaved with others are lost: they come back as two frames each
        lost = [w for w in warnings if "is split" not in w]
        assert not lost, f"{g.name}: {lost}"
        texts[g.name] = text
    # The texts are kept beside the fixture, to read and to see what a change of the reader changes
    expected_dir = fixture.with_suffix("")
    if os.environ.get("BASE_NODE_UPDATE_FIXTURES"):
        expected_dir.mkdir(exist_ok=True)
        for old in expected_dir.glob("*.bn"):
            old.unlink()
        for name, text in texts.items():
            (expected_dir / f"{key(name)}.bn").write_text(credits(name) + text, encoding="utf-8")
    changed, files = [], {}
    for name, text in texts.items():
        path = expected_dir / f"{key(name)}.bn"
        expected = files[name] = path.read_text(encoding="utf-8") if path.exists() else ""
        if credits(name) + text != expected:
            changed.append("".join(difflib.unified_diff(
                expected.splitlines(True), (credits(name) + text).splitlines(True),
                f"{path.name} (expected)", f"{path.name} (read)", n=1)))
    assert not changed, ("the assets read otherwise than tests/fixtures/everyday_geometry_nodes/*.bn; "
                         "if that is wanted, rerun with BASE_NODE_UPDATE_FIXTURES=1\n" + "\n".join(changed)[:4000])
    assert len(list(expected_dir.glob("*.bn"))) == len(texts), "a .bn of the fixtures has no asset"
    # The originals step aside: the texts build groups of the same names
    originals = {}
    for g in loaded:
        name = g.name
        g.name = f"original {name}"
        originals[name] = g

    # Built from the files themselves: the tree keeps their credits, and gives the file back
    for name, text in texts.items():
        tree = build_source(files[name], filename=f"{key(name)}.bn")[-1]
        assert tree.name == name, tree.name
        again, _ = export_tree(tree)
        assert again == files[name], f"{name}: Tree -> Text is not stable"
    for name in texts:
        for kind in evaluations(originals[name]):
            want = evaluate(originals[name], kind)
            got = evaluate(bpy.data.node_groups[name], kind)
            assert got == want, f"{name}: evaluates otherwise once rebuilt ({kind})"
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o)
    print(f"   ✓ {len(texts)} real-world assets rebuilt from text, same results")


DROP_EXAMPLE = LIB_ROOT / "examples" / "drop_example.bn"


def test_drop_bn():
    """A dropped .bn: its head says what it offers, base_node.drop_bn does each of these."""
    print("-> Test: Dropping a .bn file...")
    import shutil
    import tempfile
    from types import SimpleNamespace
    from base_node.host import build_source, modules
    from base_node.ui import drop, prefs

    # The file handler routes the .bn files Blender is given to the operator
    fh = bpy.types.FileHandler.bl_rna_get_subclass_py("BASE_NODE_FH_bn")
    assert fh is not None, "the .bn file handler is not registered"
    assert fh.bl_file_extensions == ".bn" and fh.bl_import_operator == "base_node.drop_bn"
    # Background mode has no window, hence no area: poll_drop is given the space it reads
    for space, ok in (("VIEW_3D", True), ("NODE_EDITOR", True), ("TEXT_EDITOR", True), ("PROPERTIES", False)):
        assert fh.poll_drop(SimpleNamespace(space_data=SimpleNamespace(type=space))) is ok, space
    assert not fh.poll_drop(SimpleNamespace(space_data=None))

    names = ("ripple_field", "wave modifier", "wave")

    def clean():
        for o in [o for o in bpy.data.objects if any(m.type == "NODES" and m.node_group
                                                     and m.node_group.name in names for m in o.modifiers)]:
            bpy.data.objects.remove(o)
        for n in names:
            if n in bpy.data.node_groups:
                bpy.data.node_groups.remove(bpy.data.node_groups[n])

    def select(*objs):
        for o in bpy.context.view_layer.objects:
            o.select_set(o in objs)

    def carries(obj, name):
        return [m.node_group.name for m in obj.modifiers if m.type == "NODES"] == [name]

    path = str(DROP_EXAMPLE)
    h = drop.read(path)[1]
    assert drop.most_useful(h, True) == "MODIFIER" and drop.most_useful(h, False) == "EXAMPLE"

    # groups: every graph, kept by a fake user
    clean()
    assert bpy.ops.base_node.drop_bn(filepath=path, action="GROUPS") == {"FINISHED"}
    assert all(bpy.data.node_groups[n].use_fake_user for n in names), names
    assert bpy.data.node_groups["wave modifier"].is_modifier and not bpy.data.node_groups["wave"].is_modifier

    # example: a new object whose modifier is the graph, at the 3D cursor; it makes its own geometry
    clean()
    before = set(bpy.data.objects)
    assert bpy.ops.base_node.drop_bn(filepath=path, action="EXAMPLE") == {"FINISHED"}
    obj, = set(bpy.data.objects) - before
    assert carries(obj, "ripple_field") and bpy.context.view_layer.objects.active == obj
    made = obj.evaluated_get(bpy.context.evaluated_depsgraph_get()).data
    assert len(made.vertices) > 1000, len(made.vertices)

    # modifier: on the selected objects
    clean()
    a = bpy.data.objects.new("drop_a", bpy.data.meshes.new("drop_a"))
    b = bpy.data.objects.new("drop_b", bpy.data.meshes.new("drop_b"))
    for o in (a, b):
        bpy.context.scene.collection.objects.link(o)
    select(a, b)
    before = set(bpy.data.objects)
    assert bpy.ops.base_node.drop_bn(filepath=path, action="MODIFIER") == {"FINISHED"}
    assert set(bpy.data.objects) == before and carries(a, "wave modifier") and carries(b, "wave modifier")
    # …on the object the file fell on, whatever is selected
    a.modifiers.clear()
    b.modifiers.clear()
    assert bpy.ops.base_node.drop_bn(filepath=path, action="MODIFIER", target="drop_b") == {"FINISHED"}
    assert not a.modifiers and carries(b, "wave modifier")
    # …and with nothing selected, on a new mesh of the file's @mesh (grid)
    select()
    assert bpy.ops.base_node.drop_bn(filepath=path) == {"FINISHED"}  # AUTO, no target: the example
    assert len(set(bpy.data.objects) - before) == 1
    before = set(bpy.data.objects)
    select()
    assert bpy.ops.base_node.drop_bn(filepath=path, action="MODIFIER") == {"FINISHED"}
    grid, = set(bpy.data.objects) - before
    assert grid.name.startswith("Grid") and carries(grid, "wave modifier"), grid.name
    assert len(grid.data.polygons) == 100 and len(grid.data.vertices) > 100
    with tempfile.TemporaryDirectory() as tmp:
        sphere = os.path.join(tmp, "sphere.bn")
        with open(path, encoding="utf-8") as f:
            text = f.read().replace("// @mesh grid", "// @mesh sphere")
        with open(sphere, "w", encoding="utf-8") as f:
            f.write(text)
        before = set(bpy.data.objects)
        select()
        assert bpy.ops.base_node.drop_bn(filepath=sphere, action="MODIFIER") == {"FINISHED"}
        ball, = set(bpy.data.objects) - before
        assert ball.name.startswith("Sphere") and len(ball.data.vertices) == 32 * 15 + 2
    for o in (a, b, grid, ball):
        bpy.data.objects.remove(o)
    clean()

    # library: copied into the Module Folder, never over another text unless asked, then `use` finds it
    saved = prefs.DEFAULTS.module_folder
    try:
        prefs.DEFAULTS.module_folder = ""
        prefs.apply_folders()
        try:
            bpy.ops.base_node.drop_bn(filepath=path, action="LIBRARY")
            raise AssertionError("installed with no Module Folder")
        except RuntimeError as e:
            assert "no Module Folder: set one in Edit > Preferences" in str(e), e
        with tempfile.TemporaryDirectory() as tmp:
            prefs.DEFAULTS.module_folder = tmp
            prefs.apply_folders()
            installed = os.path.join(tmp, "drop_example.bn")
            assert bpy.ops.base_node.drop_bn(filepath=path, action="LIBRARY") == {"FINISHED"}
            with open(installed, encoding="utf-8") as f, open(path, encoding="utf-8") as g:
                assert f.read() == g.read()
            assert bpy.ops.base_node.drop_bn(filepath=path, action="LIBRARY") == {"FINISHED"}  # the same: fine
            with open(installed, "a", encoding="utf-8") as f:
                f.write("// mine\n")
            try:
                bpy.ops.base_node.drop_bn(filepath=path, action="LIBRARY")
                raise AssertionError("another text was overwritten")
            except RuntimeError as e:
                assert "already exists, with another text" in str(e), e
            with open(installed, encoding="utf-8") as f:
                assert f.read().endswith("// mine\n")
            assert bpy.ops.base_node.drop_bn(filepath=path, action="LIBRARY", overwrite=True) == {"FINISHED"}
            with open(installed, encoding="utf-8") as f:
                assert not f.read().endswith("// mine\n")
            trees = build_source("use drop_example (wave_modifier)\n\n"
                                 "geometry graph twice_waved(geometry: Geometry) -> Geometry {\n"
                                 "  return wave_modifier(wave_modifier(geometry))\n}\n", "uses.bn")
            assert [t.name for t in trees] == ["twice_waved"], trees
            waved = [g for g in bpy.data.node_groups if g.get(modules.MODULE) == "drop_example"]
            assert {g.name for g in waved} >= {"wave modifier", "wave"}, waved
            for g in trees + waved:
                bpy.data.node_groups.remove(g)
    finally:
        prefs.DEFAULTS.module_folder = saved
        prefs.apply_folders()

    # A head in error: the error, with its place, and nothing changes
    with tempfile.TemporaryDirectory() as tmp:
        for name, head, needle in (
                ("bad.bn", "// @offer groups, instance\n", "bad.bn:1:19  @offer 'instance': one of"),
                ("wrong.bn", "// @example \"wave modifier\"\n", "wrong.bn:1:13  @example 'wave modifier': not a"),
                ("nomodule.bn", "// @module drop-example\n", "nomodule.bn:1:12  @module 'drop-example'")):
            bad = os.path.join(tmp, name)
            with open(path, encoding="utf-8") as f:
                text = f.read().split("\n\n", 1)[1]  # its body: its own head out
            with open(bad, "w", encoding="utf-8") as f:
                f.write(head + text)
            state = file_state(), sorted(o.name for o in bpy.data.objects)
            for action in ("AUTO", "GROUPS", "MODIFIER"):
                try:
                    bpy.ops.base_node.drop_bn(filepath=bad, action=action)
                    raise AssertionError(f"{name} built")
                except RuntimeError as e:
                    assert needle in str(e), e
            assert (file_state(), sorted(o.name for o in bpy.data.objects)) == state
        # An error of the body: the build's, with its place, and nothing built
        broken = os.path.join(tmp, "broken.bn")
        with open(broken, "w", encoding="utf-8") as f:
            f.write("// @offer groups, example\n\ngeometry graph g() -> Geometry {\n  return Nothing()\n}\n")
        state = file_state(), sorted(o.name for o in bpy.data.objects)
        try:
            bpy.ops.base_node.drop_bn(filepath=broken, action="EXAMPLE")
            raise AssertionError("broken.bn built")
        except RuntimeError as e:
            assert "broken.bn:4:10  unknown node 'Nothing'" in str(e), e
        assert (file_state(), sorted(o.name for o in bpy.data.objects)) == state
        # A choice the file does not offer is refused
        only = os.path.join(tmp, "only.bn")
        with open(only, "w", encoding="utf-8") as f:
            f.write("// @offer groups\n" + text)
        try:
            bpy.ops.base_node.drop_bn(filepath=only, action="MODIFIER")
            raise AssertionError("a modifier not offered")
        except RuntimeError as e:
            assert "does not offer modifier; it offers: groups" in str(e), e
    print("   ✓ Dropping a .bn verified")


def test_gltf_export():
    """The gltf target against Blender's glTF exporter (test_gltf_export.py)."""
    spec = importlib.util.spec_from_file_location("test_gltf_export", EXT_DIR / "tests" / "test_gltf_export.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.test_gltf_export()


def pack_tests():
    """The test_* functions of tests/packs/test_*.py, file by file, in the order they are written.

    A pack's tests are a file of their own, so that adding a pack edits no list here; they import
    this file's helpers (`from test_extension import *`). The public mirror has no tests/packs/.
    """
    sys.modules.setdefault("test_extension", sys.modules[__name__])
    found = []
    for path in sorted((Path(__file__).resolve().parent / "packs").glob("test_*.py")):
        spec = importlib.util.spec_from_file_location(f"packs.{path.stem}", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        found += [fn for name, fn in vars(module).items()
                  if name.startswith("test_") and callable(fn) and fn.__module__ == module.__name__]
    return found


def main():
    print("=== Starting Base Node Blender extension tests ===")
    tests = [
        test_import_and_registration,
        test_stdlib_keeps_its_targets,
        test_build_and_round_trip,
        test_named_constants,
        test_comments,
        test_targets_and_linter,
        test_pipe_symbol,
        test_live_apply,
        test_live_diagnostics,
        test_tree_without_output,
        test_multi_input_order,
        test_planar2d_shape_builder_pick,
        test_shader_and_compositor,
        test_module_graphs_in_other_trees,
        test_templates,
        test_mask2d_render,
        test_merge_render,
        test_grade_render,
        test_stmap_render,
        test_stmap_canvas_render,
        test_qc_render,
        test_formula_operands_render,
        test_pipe_through_chosen_output,
        test_material_tree,
        test_ramps_and_curves,
        test_text_view,
        test_import_files,
        test_copy_paste,
        test_drop_bn,
        test_zones_read_back,
        test_color_components,
        test_inputs_of_one_name_rebuilt,
        test_smooth_functions_and_shader_keys,
        test_comparisons_in_a_shader_tree,
        test_ternary,
        test_outputs_of_one_name_rebuilt,
        test_tuples_choose_the_type,
        test_switch_takes_the_type_of_its_values,
        test_vector_output_dimensions,
        test_shader_constants_and_old_names,
        test_states_named_like_the_zone,
        test_node_names,
        test_group_without_tree,
        test_arrange,
        test_idioms_build,
        test_real_world_assets,
        test_gltf_export,
    ]
    tests += pack_tests()
    failed = 0
    for fn in tests:
        try:
            fn()
        except Exception:
            failed += 1
            traceback.print_exc()

    if failed:
        print(f"\n❌ FAILED: {failed} test(s) failed")
        sys.exit(1)
    else:
        print(f"\n✅ SUCCESS: 100% of tests ({len(tests)}/{len(tests)}) passed successfully!")
        sys.exit(0)


if __name__ == "__main__":
    main()
