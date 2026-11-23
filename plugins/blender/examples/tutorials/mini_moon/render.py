"""Build each step of the mini moon tutorial in Blender and render its picture.

  blender -b --factory-startup --python-exit-code 1 --python examples/tutorials/mini_moon/render.py
  blender -b --factory-startup --python-exit-code 1 --python examples/tutorials/mini_moon/render.py -- --only step3

Every step*.bn of this folder is built from scratch in an empty scene, under the same camera and sun,
and rendered with Cycles to site/images/tutorials/mini-moon-<step>.png. The page shows these files'
text: a step that does not build stops the script.

The phases step renders the last step three more times, the sun moving round the moon: full, quarter,
crescent. Then the groups (geometry and shader) and the material of the last step go through the
regression tests' round trip (tests/test_libraries.py).
"""

import math
import sys
import tempfile
from pathlib import Path

import bpy
from mathutils import Vector

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OUT = ROOT / "site" / "images" / "tutorials"
sys.path.insert(0, str(ROOT / "addon" / "tests"))
import test_libraries  # noqa: E402  (loads the extension as `base_node`)

from base_node.host import build_source, export_tree  # noqa: E402

SAMPLES = 96
SUN = 75.0  # degrees round the moon from the camera: the light of the steps, a fat crescent's
PHASES = {"full": 8.0, "quarter": 90.0, "crescent": 135.0}


def args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    return argv[argv.index("--only") + 1] if "--only" in argv else None


def empty_scene():
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
    scene.render.resolution_x = scene.render.resolution_y = 800
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGB"
    scene.view_settings.view_transform = "AgX"
    scene.render.film_transparent = True  # the sky stays black
    # No sky: the night side of the moon is lit by nothing
    world = bpy.data.worlds.new("Space")
    world.use_nodes = True
    world.node_tree.nodes["Background"].inputs["Color"].default_value = (0.0, 0.0, 0.0, 1.0)
    scene.world = world
    data = bpy.data.cameras.new("Camera")
    data.lens = 120
    cam = bpy.data.objects.new("Camera", data)
    cam.location = (0.0, -9.0, 0.0)
    cam.rotation_euler = (math.radians(90.0), 0.0, 0.0)
    scene.collection.objects.link(cam)
    scene.camera = cam
    return scene


def sun(scene, angle, energy=6.0):
    """A sun `angle` degrees round the moon from the camera, on its right, a little above."""
    a = math.radians(angle)
    towards = Vector((math.sin(a), -math.cos(a), 0.25)).normalized()  # from the moon to the sun
    data = bpy.data.lights.new("Sun", "SUN")
    data.energy = energy
    data.angle = math.radians(0.5)
    obj = bpy.data.objects.new("Sun", data)
    obj.rotation_euler = Vector((0.0, 0.0, 1.0)).rotation_difference(towards).to_euler()
    scene.collection.objects.link(obj)


def build(path):
    source = path.read_text(encoding="utf-8")
    groups = {g.name: g for g in build_source(source, filename=path.name)}
    obj = bpy.data.objects.new("Moon", bpy.data.meshes.new("Moon"))
    bpy.context.scene.collection.objects.link(obj)
    obj.modifiers.new("Moon", "NODES").node_group = groups["mini_moon"]
    return obj


def render(name):
    OUT.mkdir(parents=True, exist_ok=True)
    scene = bpy.context.scene
    scene.render.filepath = str(OUT / f"mini-moon-{name}.png")
    bpy.ops.render.render(write_still=True)
    print(f"rendered {scene.render.filepath}")


def check_round_trip(path):
    """The regression tests' round trip, for the groups and the material of the last step.

    It builds the Geometry Nodes groups again before the materials, so `mini_moon`, which sets the
    material Regolith of the same text, cannot build there: its text is checked here instead.
    """
    empty_scene()
    build(path)
    text, _ = export_tree(bpy.data.node_groups["mini_moon"])
    again, _ = export_tree(build_source(text, filename="mini_moon.bn")[-1])
    assert again == text, "mini_moon does not read back the same"
    print("round trip mini_moon: ok (with its material)")

    blend = Path(tempfile.mkdtemp()) / "mini_moon.blend"
    bpy.data.libraries.write(str(blend), set(bpy.data.node_groups) | set(bpy.data.materials))
    records, _ = test_libraries.round_trip(blend, trees=("geometry", "shader", "material"))
    records.pop("mini_moon")
    for name, record in sorted(records.items()):
        print(f"round trip {name}: {record['status']}")
    assert records and all(r["status"] == "ok" for r in records.values()), records


def main():
    only = args()
    steps = sorted(HERE.glob("step*.bn"))
    for path in steps:
        step = path.stem.split("_")[0]
        if only and only != step:
            continue
        scene = empty_scene()
        sun(scene, SUN)
        build(path)
        render(step)
    if not only or only == "phases":
        for name, angle in PHASES.items():
            scene = empty_scene()
            sun(scene, angle)
            build(steps[-1])
            render(name)
    if not only or only == "round-trip":
        check_round_trip(steps[-1])


main()
