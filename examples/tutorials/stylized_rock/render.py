"""Build each step of the stylized rock tutorial in Blender and render its picture.

  blender -b --factory-startup --python-exit-code 1 --python examples/tutorials/stylized_rock/render.py
  blender -b --factory-startup --python-exit-code 1 --python examples/tutorials/stylized_rock/render.py -- --only step3

Every step*.bn of this folder is built from scratch in an empty scene and rendered with Cycles to
site/images/tutorials/stylized-rock-<step>.png: the rock alone before a slate sky for the first
five, as a sculpt in its viewport, the whole planet for the last one. The page shows
these files' text: a step that does not build stops the script. The seeds picture puts the rock of
step 5 side by side for four seeds, the seed input of its modifier. Then stylized_rock of step 5 is read back to its text and built
again.

The turn is not a picture of the page: it is the tutorial's thumbnail, the planet of the last step
turning once about its axis, square, under a low strong sun that the steps do not have,
site/images/tutorials/stylized-rock-turn.webp (ffmpeg encodes it).
"""

import math
import shutil
import subprocess
import sys
from pathlib import Path

import bpy

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OUT = ROOT / "site" / "images" / "tutorials"
sys.path.insert(0, str(ROOT / "base-node-for-blender" / "tests"))
import test_libraries  # noqa: E402,F401  (loads the extension as `base_node`)

from base_node.host import build_source, export_tree  # noqa: E402

SAMPLES = 96
VIEWS = {
    # name: (camera location, what it looks at, lens)
    "rock": ((1.3, -2.1, 0.7), (0.0, 0.0, 0.0), 60),
    "seeds": ((0.0, -8.4, 1.0), (0.0, 0.0, 0.0), 60),
    "planet": ((4.6, -7.4, 3.0), (0.0, 0.0, 0.0), 50),
    "turn": ((0.0, -9.0, 2.6), (0.0, 0.0, 0.0), 66),
}
TURN = {"frames": 60, "fps": 20, "size": 640}
SEEDS = (1, 2, 3, 4)  # of the seeds picture; the steps show seed 0


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
    # A slate sky, seen behind the rock and lighting its shadows; a sun in front on the right
    world = bpy.data.worlds.new("Sky")
    world.use_nodes = True
    background = world.node_tree.nodes["Background"]
    background.inputs["Color"].default_value = (0.06, 0.065, 0.1, 1.0)
    background.inputs["Strength"].default_value = 1.5
    scene.world = world
    sun = bpy.data.objects.new("Sun", bpy.data.lights.new("Sun", "SUN"))
    sun.data.energy = 4.5
    sun.data.angle = 0.3
    sun.rotation_euler = (math.radians(55.0), 0.0, math.radians(35.0))
    scene.collection.objects.link(sun)
    location, target, lens = VIEWS[view]
    data = bpy.data.cameras.new("Camera")
    data.lens = lens
    cam = bpy.data.objects.new("Camera", data)
    cam.location = location
    aim = bpy.data.objects.new("Aim", None)
    aim.location = target
    scene.collection.objects.link(aim)
    cam.constraints.new("TRACK_TO").target = aim
    scene.collection.objects.link(cam)
    scene.camera = cam
    scene["sun"] = sun
    scene["sky"] = world
    return scene


def build(path, graph="stylized_rock", seeds=(0,), apart=0.0):
    """An object carrying `graph` of the file a seed, side by side apart metres."""
    source = path.read_text(encoding="utf-8")
    group = {g.name: g for g in build_source(source, filename=path.name)}[graph]
    seed = next(i for i in group.interface.items_tree
                if i.item_type == "SOCKET" and i.in_out == "INPUT" and i.name.lower() == "seed")
    for n, value in enumerate(seeds):
        obj = bpy.data.objects.new("Rock", bpy.data.meshes.new("Rock"))
        obj.location.x = (n - (len(seeds) - 1) / 2) * apart
        bpy.context.scene.collection.objects.link(obj)
        modifier = obj.modifiers.new("Rock", "NODES")
        modifier.node_group = group
        getattr(modifier.properties.inputs, seed.identifier).value = value
    return obj


def render(name):
    OUT.mkdir(parents=True, exist_ok=True)
    scene = bpy.context.scene
    scene.render.filepath = str(OUT / f"stylized-rock-{name}.png")
    bpy.ops.render.render(write_still=True)
    print(f"rendered {scene.render.filepath}")


def turn(path):
    """The planet turning once, as the thumbnail: square, a low sun and a dim sky for the relief."""
    scene = empty_scene("turn")
    scene.render.resolution_x = scene.render.resolution_y = TURN["size"]
    scene.cycles.samples = 48
    scene["sun"].data.energy = 5.5
    scene["sun"].data.angle = 0.05
    scene["sun"].rotation_euler = (math.radians(68.0), 0.0, math.radians(55.0))
    scene["sky"].node_tree.nodes["Background"].inputs["Strength"].default_value = 0.7
    planet = build(path, "rock_planet")
    folder = Path(bpy.app.tempdir) / "turn"
    shutil.rmtree(folder, ignore_errors=True)
    folder.mkdir(parents=True)
    for i in range(TURN["frames"]):
        planet.rotation_euler.z = math.tau * i / TURN["frames"]
        scene.render.filepath = str(folder / f"frame_{i + 1:04d}.png")
        bpy.ops.render.render(write_still=True)
    out = OUT / "stylized-rock-turn.webp"
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(TURN["fps"]),
         "-i", str(folder / "frame_%04d.png"), "-c:v", "libwebp_anim", "-lossless", "0",
         "-q:v", "75", "-compression_level", "6", "-loop", "0", "-pix_fmt", "yuv420p", str(out)],
        check=True)
    print(f"encoded {out}, {TURN['frames']} frames, {out.stat().st_size} bytes")


def check_round_trip(path):
    """stylized_rock of step 5 reads back to a text that builds the same group again."""
    empty_scene("rock")
    build(path)
    text, warnings = export_tree(bpy.data.node_groups["stylized_rock"])
    assert not warnings, warnings
    again, _ = export_tree(build_source(text, filename="stylized_rock.bn")[-1])
    assert again == text, "stylized_rock does not read back the same"
    print("round trip stylized_rock: ok")


def main():
    only = args()
    steps = sorted(HERE.glob("step*.bn"))
    rock = steps[4]
    for path in steps:
        step = path.stem.split("_")[0]
        if only and only != step:
            continue
        planet = path is steps[-1]
        empty_scene("planet" if planet else "rock")
        build(path, "rock_planet" if planet else "stylized_rock")
        render(step)
    if not only or only == "seeds":
        empty_scene("seeds")
        build(rock, seeds=SEEDS, apart=1.15)
        render("seeds")
    if not only or only == "turn":
        turn(steps[-1])
    if not only or only == "round-trip":
        check_round_trip(rock)


main()
