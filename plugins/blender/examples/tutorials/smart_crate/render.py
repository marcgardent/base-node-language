"""Build each step of the smart crate tutorial in Blender and render its picture.

  blender -b --factory-startup --python-exit-code 1 --python examples/tutorials/smart_crate/render.py
  blender -b --factory-startup --python-exit-code 1 --python examples/tutorials/smart_crate/render.py -- --only step3

Every step*.bn of this folder is built from scratch in an empty scene, on a floor, under the same
camera, sun and sky, and rendered with Cycles to site/images/tutorials/smart-crate-<step>.png. The
page shows these files' text: a step that does not build stops the script. The close step renders
the last step again, close to a corner of the lid. Then smart_crate of the last step is read back
to its text and built again.
"""

import math
import sys
from pathlib import Path

import bpy

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OUT = ROOT / "site" / "images" / "tutorials"
sys.path.insert(0, str(ROOT / "addon" / "tests"))
import test_libraries  # noqa: E402,F401  (loads the extension as `base_node`)

from base_node.host import build_source, export_tree  # noqa: E402

SAMPLES = 96
VIEWS = {
    # name: (camera location, rotation in degrees, lens)
    "wide": ((1.9, -2.3, 1.75), (66.0, 0.0, 39.0), 40),
    "close": ((0.95, -1.35, 1.2), (72.0, 0.0, 35.0), 45),
}


def args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    return argv[argv.index("--only") + 1] if "--only" in argv else None


def empty_scene(view):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    prefs = bpy.context.preferences.addons["cycles"].preferences
    for kind in ("OPTIX", "CUDA"):
        try:
            prefs.compute_device_type = kind
            prefs.get_devices()
            for device in prefs.devices:
                device.use = True
            scene.cycles.device = "GPU"
            break
        except TypeError:
            continue
    scene.cycles.samples = SAMPLES
    scene.cycles.use_denoising = True
    scene.render.resolution_x, scene.render.resolution_y = 1000, 750
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGB"
    scene.view_settings.view_transform = "AgX"
    # A grey sky lights the shadows; a sun, high in front on the left, the walls the camera sees
    world = bpy.data.worlds.new("Sky")
    world.use_nodes = True
    world.node_tree.nodes["Background"].inputs["Color"].default_value = (0.35, 0.38, 0.42, 1.0)
    scene.world = world
    sun = bpy.data.objects.new("Sun", bpy.data.lights.new("Sun", "SUN"))
    sun.data.energy = 3.5
    sun.rotation_euler = (math.radians(50.0), 0.0, math.radians(-25.0))
    scene.collection.objects.link(sun)
    floor = bpy.data.meshes.new("Floor")
    floor.from_pydata([(-4, -4, 0), (4, -4, 0), (4, 4, 0), (-4, 4, 0)], [], [(0, 1, 2, 3)])
    scene.collection.objects.link(bpy.data.objects.new("Floor", floor))
    location, rotation, lens = VIEWS[view]
    data = bpy.data.cameras.new("Camera")
    data.lens = lens
    cam = bpy.data.objects.new("Camera", data)
    cam.location = location
    cam.rotation_euler = tuple(math.radians(a) for a in rotation)
    scene.collection.objects.link(cam)
    scene.camera = cam
    return scene


def build(path):
    source = path.read_text(encoding="utf-8")
    groups = {g.name: g for g in build_source(source, filename=path.name)}
    obj = bpy.data.objects.new("Crate", bpy.data.meshes.new("Crate"))
    bpy.context.scene.collection.objects.link(obj)
    obj.modifiers.new("Crate", "NODES").node_group = groups["smart_crate"]
    return obj


def render(name):
    OUT.mkdir(parents=True, exist_ok=True)
    scene = bpy.context.scene
    scene.render.filepath = str(OUT / f"smart-crate-{name}.png")
    bpy.ops.render.render(write_still=True)
    print(f"rendered {scene.render.filepath}")


def check_round_trip(path):
    """smart_crate of the last step reads back to a text that builds the same group again."""
    empty_scene("wide")
    build(path)
    text, warnings = export_tree(bpy.data.node_groups["smart_crate"])
    assert not warnings, warnings
    again, _ = export_tree(build_source(text, filename="smart_crate.bn")[-1])
    assert again == text, "smart_crate does not read back the same"
    print("round trip smart_crate: ok")


def main():
    only = args()
    steps = sorted(HERE.glob("step*.bn"))
    for path in steps:
        step = path.stem.split("_")[0]
        if only and only != step:
            continue
        empty_scene("wide")
        build(path)
        render(step)
    if not only or only == "close":
        empty_scene("close")
        build(steps[-1])
        render("close")
    if not only or only == "round-trip":
        check_round_trip(steps[-1])


main()
