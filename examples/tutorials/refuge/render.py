"""Build each step of the refuge tutorial in Blender and render its picture.

  blender -b --factory-startup --python-exit-code 1 --python examples/tutorials/refuge/render.py
  blender -b --factory-startup --python-exit-code 1 --python examples/tutorials/refuge/render.py -- --only step3

Every step*.bn of this folder is built from scratch in an empty scene, on a floor, under the same
camera, sun and sky, and rendered with Cycles to site/images/tutorials/refuge-<step>.png. The page
shows these files' text: a step that does not build stops the script. The side step renders the
last step again, closer, on the door, the vents and the hatch. Then refuge of the last step
is read back to its text and built again.
"""

import math
import sys
from pathlib import Path

import bpy
from mathutils import Vector

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OUT = ROOT / "site" / "images" / "tutorials"
sys.path.insert(0, str(ROOT / "base-node-for-blender" / "tests"))
import test_libraries  # noqa: E402,F401  (loads the extension as `base_node`)

from base_node.host import build_source, export_tree  # noqa: E402

SAMPLES = 64
VIEWS = {
    # name: (camera location, the point it looks at, lens)
    "wide": ((6.6, -7.4, 3.4), (0.15, 0.0, 2.3), 41),
    "side": ((5.4, -4.5, 2.5), (0.3, 0.0, 2.05), 28),
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
    # The machine is shared: a few threads only
    scene.render.threads_mode = "FIXED"
    scene.render.threads = 2
    scene.cycles.samples = SAMPLES
    scene.cycles.use_denoising = True
    scene.render.resolution_x, scene.render.resolution_y = 1000, 750
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGB"
    scene.view_settings.view_transform = "AgX"
    # A pale sky lights the shadows; a sun, high on the left behind the camera, the front and the
    # right wall
    world = bpy.data.worlds.new("Sky")
    world.use_nodes = True
    world.node_tree.nodes["Background"].inputs["Color"].default_value = (0.42, 0.47, 0.55, 1.0)
    scene.world = world
    sun = bpy.data.objects.new("Sun", bpy.data.lights.new("Sun", "SUN"))
    sun.data.energy = 3.5
    sun.data.angle = math.radians(2.0)
    sun.rotation_euler = (math.radians(52.0), 0.0, math.radians(18.0))
    scene.collection.objects.link(sun)
    floor = bpy.data.meshes.new("Floor")
    floor.from_pydata([(-30, -30, 0), (30, -30, 0), (30, 30, 0), (-30, 30, 0)], [], [(0, 1, 2, 3)])
    scene.collection.objects.link(bpy.data.objects.new("Floor", floor))
    location, target, lens = VIEWS[view]
    data = bpy.data.cameras.new("Camera")
    data.lens = lens
    cam = bpy.data.objects.new("Camera", data)
    cam.location = location
    look = Vector(target) - Vector(location)
    cam.rotation_euler = look.to_track_quat("-Z", "Y").to_euler()
    scene.collection.objects.link(cam)
    scene.camera = cam
    return scene


def build(path):
    source = path.read_text(encoding="utf-8")
    groups = {g.name: g for g in build_source(source, filename=path.name)}
    obj = bpy.data.objects.new("Refuge", bpy.data.meshes.new("Refuge"))
    bpy.context.scene.collection.objects.link(obj)
    obj.modifiers.new("Refuge", "NODES").node_group = groups["refuge"]
    # A group that fails in Blender leaves an empty mesh: stop there
    mesh = obj.evaluated_get(bpy.context.evaluated_depsgraph_get()).data
    assert len(mesh.polygons) > 0, f"{path.name}: refuge makes no faces"
    print(f"{path.name}: {len(mesh.polygons)} faces")
    return obj


def render(name):
    OUT.mkdir(parents=True, exist_ok=True)
    scene = bpy.context.scene
    scene.render.filepath = str(OUT / f"refuge-{name}.png")
    bpy.ops.render.render(write_still=True)
    print(f"rendered {scene.render.filepath}")


def check_round_trip(path):
    """refuge of the last step reads back to a text that builds the same group again."""
    empty_scene("wide")
    build(path)
    text, warnings = export_tree(bpy.data.node_groups["refuge"])
    assert not warnings, warnings
    again, _ = export_tree(build_source(text, filename="refuge.bn")[-1])
    assert again == text, "refuge does not read back the same"
    print("round trip refuge: ok")


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
    if not only or only == "side":
        empty_scene("side")
        build(steps[-1])
        render("side")
    if not only or only == "round-trip":
        check_round_trip(steps[-1])


main()
