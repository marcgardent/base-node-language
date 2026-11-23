"""Build each step of the lunar ground tutorial in Blender and render its picture.

  blender -b --factory-startup --python-exit-code 1 --python examples/tutorials/lunar_ground/render.py
  blender -b --factory-startup --python-exit-code 1 --python examples/tutorials/lunar_ground/render.py -- --only step3

Every step*.bn of this folder is built from scratch in an empty scene, under the same camera and sun,
and rendered with Cycles to site/images/tutorials/lunar-ground-<step>.png. The page shows these
files' text: a step that does not build stops the script.

The close step renders the last two steps again from near the ground, to compare their details.
The light step renders the last step twice more, under a high sun and under a grazing one.
Then the groups and the material of the last step go through the regression tests' round trip
(tests/test_libraries.py): tree -> .bn -> tree gives the same text and the same result.
"""

import math
import sys
import tempfile
from pathlib import Path

import bpy

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OUT = ROOT / "site" / "images" / "tutorials"
sys.path.insert(0, str(ROOT / "addon" / "tests"))
import test_libraries  # noqa: E402  (loads the extension as `base_node`)

from base_node.host import build_source  # noqa: E402

SAMPLES = 96
TOP = {"step3", "step4"}  # seen from above


def args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    only = argv[argv.index("--only") + 1] if "--only" in argv else None
    return only


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
    scene.render.resolution_x = 1200
    scene.render.resolution_y = 560
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGB"
    scene.view_settings.view_transform = "AgX"
    scene.render.film_transparent = True  # the sky stays black, whatever light the world gives
    # The Moon has no air: a black sky; a faint world light stands for the light the ground sends back
    world = bpy.data.worlds.new("Space")
    world.use_nodes = True
    world.node_tree.nodes["Background"].inputs["Color"].default_value = (0.012, 0.012, 0.014, 1.0)
    scene.world = world
    return scene


def sun(scene, elevation, azimuth=-110.0, energy=7.0):
    """A sun `elevation` degrees above the horizon."""
    data = bpy.data.lights.new("Sun", "SUN")
    data.energy = energy
    data.angle = math.radians(0.5)
    obj = bpy.data.objects.new("Sun", data)
    obj.rotation_euler = (math.radians(90.0 - elevation), 0.0, math.radians(azimuth))
    scene.collection.objects.link(obj)


def top_camera(scene):
    """Straight down on the whole square: the cells of steps 3 and 4 show best from above."""
    data = bpy.data.cameras.new("Top")
    data.type = "ORTHO"
    data.ortho_scale = 4.1
    cam = bpy.data.objects.new("Top", data)
    cam.location = (0.0, 0.0, 5.0)
    scene.collection.objects.link(cam)
    scene.camera = cam
    scene.render.resolution_x = scene.render.resolution_y = 640


def camera(scene):
    target = bpy.data.objects.new("Target", None)
    target.location = (0.2, 0.4, -0.15)
    scene.collection.objects.link(target)
    data = bpy.data.cameras.new("Camera")
    data.lens = 35
    cam = bpy.data.objects.new("Camera", data)
    cam.location = (-3.1, -4.3, 1.55)
    track = cam.constraints.new("TRACK_TO")
    track.target = target
    scene.collection.objects.link(cam)
    scene.camera = cam


def close_camera(scene):
    """Low and near, on a corner of the square: the details of steps 7 and 8 side by side."""
    target = bpy.data.objects.new("Target", None)
    target.location = (0.1, -0.5, -0.12)
    scene.collection.objects.link(target)
    data = bpy.data.cameras.new("Close")
    data.lens = 35
    cam = bpy.data.objects.new("Close", data)
    cam.location = (-0.9, -1.75, 0.32)
    track = cam.constraints.new("TRACK_TO")
    track.target = target
    scene.collection.objects.link(cam)
    scene.camera = cam


def build(path):
    source = path.read_text(encoding="utf-8")
    groups = {g.name: g for g in build_source(source, filename=path.name)}
    mesh = bpy.data.meshes.new("Ground")
    obj = bpy.data.objects.new("Ground", mesh)
    bpy.context.scene.collection.objects.link(obj)
    obj.modifiers.new("Ground", "NODES").node_group = groups["lunar_ground"]
    return obj


def render(name):
    OUT.mkdir(parents=True, exist_ok=True)
    scene = bpy.context.scene
    scene.render.filepath = str(OUT / f"lunar-ground-{name}.png")
    bpy.ops.render.render(write_still=True)
    print(f"rendered {scene.render.filepath}")


def check_round_trip(path):
    """The regression tests' round trip, for the groups (geometry and shader) and the material of the last step.

    It builds the Geometry Nodes groups again before the materials, so `lunar_ground`, which sets the
    material Regolith of the same text, cannot build there: its text is checked here instead, in a file
    that has the material, and must read back the same.
    """
    from base_node.host import export_tree

    empty_scene()
    build(path)
    text, _ = export_tree(bpy.data.node_groups["lunar_ground"])
    groups = build_source(text, filename="lunar_ground.bn")
    again, _ = export_tree(groups[-1])
    assert again == text, "lunar_ground does not read back the same"
    print("round trip lunar_ground: ok (with its material)")

    blend = Path(tempfile.mkdtemp()) / "lunar_ground.blend"
    bpy.data.libraries.write(str(blend), set(bpy.data.node_groups) | set(bpy.data.materials))
    records, _ = test_libraries.round_trip(blend, trees=("geometry", "shader", "material"))
    records.pop("lunar_ground")
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
        (top_camera if step in TOP else camera)(scene)
        sun(scene, elevation=14.0)
        build(path)
        render(step)
    if not only or only == "close":
        for path in steps[-2:]:
            scene = empty_scene()
            close_camera(scene)
            sun(scene, elevation=14.0)
            build(path)
            render(path.stem.split("_")[0] + "-close")
    if not only or only == "light":
        for name, elevation in (("light-high", 70.0), ("light-low", 6.0)):
            scene = empty_scene()
            camera(scene)
            sun(scene, elevation=elevation)
            build(steps[-1])
            render(name)
    if not only or only == "round-trip":
        check_round_trip(steps[-1])


main()
