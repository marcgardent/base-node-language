"""Build examples/tuple_tiles.bn in a windowed Blender, show its group in a full-window Node Editor,
frame the switches and save a screenshot of that area (site/images/tuple-tiles-nodes.png). Needs a window:
  blender --factory-startup --window-geometry 0 0 1600 1000 --python examples/tuple_tiles_screenshot.py -- site/images/tuple-tiles-nodes.png"""
import importlib.util
import os
import sys

import bpy

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = sys.argv[sys.argv.index("--") + 1]
EXT = os.path.join(ROOT, "addon")
spec = importlib.util.spec_from_file_location("base_node", os.path.join(EXT, "__init__.py"),
                                              submodule_search_locations=[EXT])
mod = importlib.util.module_from_spec(spec)
sys.modules["base_node"] = mod
spec.loader.exec_module(mod)
mod.register()
from base_node.host import build_source  # noqa: E402

bpy.data.materials.new("TupleTiles")
src = open(os.path.join(ROOT, "examples", "tuple_tiles.bn"), encoding="utf-8").read()
tree = build_source(src, "tuple_tiles.bn")[-1]
for n in tree.nodes:
    t = getattr(n, "input_type", None) or getattr(n, "data_type", None)
    if n.bl_idname in ("GeometryNodeSwitch", "ShaderNodeMix", "GeometryNodeIndexSwitch"):
        print("NODE", n.bl_idname, t)

state = {"step": 0}


def area_of(screen):
    return max(screen.areas, key=lambda a: a.width * a.height)


def tick():
    win = bpy.context.window_manager.windows[0]
    screen = win.screen
    area = area_of(screen)
    step = state["step"]
    state["step"] += 1
    if step == 0:
        area.type = "NODE_EDITOR"
        area.ui_type = "GeometryNodeTree"
        space = area.spaces.active
        space.pin = True
        space.node_tree = tree
        space.show_region_ui = False
        space.show_region_toolbar = False
        return 0.5
    region = next(r for r in area.regions if r.type == "WINDOW")
    with bpy.context.temp_override(window=win, area=area, region=region):
        if step == 1:
            bpy.ops.screen.screen_full_area(use_hide_panels=True)
            return 0.5
        if step == 2:
            for n in tree.nodes:
                n.select = n.bl_idname in ("GeometryNodeSwitch", "ShaderNodeMix", "GeometryNodeIndexSwitch",
                                           "FunctionNodeCompare", "GeometryNodeStoreNamedAttribute")
            bpy.ops.node.view_selected()
            return 0.6
        if step == 3:
            for n in tree.nodes:
                n.select = False
            return 0.6
        bpy.ops.screen.screenshot_area(filepath=OUT)
    print("SHOT", OUT)
    bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(tick, first_interval=1.5)
