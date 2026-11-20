"""Build each step of the clone wall tutorial in Blender and render its picture or its animation.

  blender -b --factory-startup --python-exit-code 1 --python examples/tutorials/clone_wall/render.py
  blender -b --factory-startup --python-exit-code 1 --python examples/tutorials/clone_wall/render.py -- --only step5

Every step*.bn of this folder is built from scratch in an empty scene, in front of the same seamless
backdrop, under the same camera and soft lights, and rendered with EEVEE to
site/images/tutorials/clone-wall-<step>.png. A step that moves (ANIMATED) is also rendered frame by
frame, LOOP frames after PREROLL frames that only run its simulations, to a looping animated WebP,
clone-wall-<step>.webp; its PNG is the first frame of the loop. The falloffs sweep once in LOOP
frames and are off the wall when the loop joins up, so it joins with no jump; a step that does not
loop by itself (PINGPONG) is played forward then back. The page shows these files' text: a step that does not build stops
the script. Then clone_wall of the last step is read back to its text and built again.
"""

import math
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import bpy

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OUT = ROOT / "site" / "images" / "tutorials"
sys.path.insert(0, str(ROOT / "base-node-for-blender" / "tests"))
import test_libraries  # noqa: E402,F401  (loads the extension as `base_node`)

from base_node.host import build_source, export_tree  # noqa: E402

SAMPLES = 48
SIZE = (640, 427)  # 3:2, the size of the animations, and of the stills beside them
PREROLL = 72  # frames simulated before the loop, one sweep: the springs settle, the falloff is off the wall
LOOP = 72  # frames, 3 s at 24 fps: one sweep of the falloffs
ANIMATED = {"step4", "step5", "step6", "step7", "step8"}
# The steps whose motion does not loop by itself (a noise flowing on): LOOP frames, played forward then back
PINGPONG = {"step4"}
CAMERA = ((3.3, -6.4, 2.05), (0.15, 0.0, 1.2), 50)  # location, target, lens
BACKDROP = (0.2, 0.27, 0.42)  # a dusty blue, behind clones of warm cream


def args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    return argv[argv.index("--only") + 1] if "--only" in argv else None


def empty_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_EEVEE"
    scene.eevee.taa_render_samples = SAMPLES
    scene.eevee.use_raytracing = True
    scene.eevee.use_shadows = True
    scene.eevee.ray_tracing_options.resolution_scale = "1"
    scene.eevee.fast_gi_resolution = "1"
    scene.eevee.fast_gi_quality = 0.5
    scene.eevee.shadow_ray_count = 2
    scene.render.resolution_x, scene.render.resolution_y = SIZE
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGB"
    scene.view_settings.view_transform = "AgX"
    scene.view_settings.look = "AgX - Punchy"
    scene.render.fps = 24
    scene.frame_start, scene.frame_end = 1, PREROLL + LOOP
    studio(scene)
    return scene


def backdrop(scene):
    """A sweep: the floor curves up into the wall behind, with no line where they meet."""
    rows, radius, wall = [], 2.0, 3.0
    for i in range(9):  # the floor, from the front to the start of the curve
        rows.append((-8.0 + i * (8.0 + wall - radius) / 8.0, 0.0))
    for i in range(1, 17):  # the quarter circle
        a = math.radians(90.0 * i / 16.0)
        rows.append((wall - radius + radius * math.sin(a), radius - radius * math.cos(a)))
    for i in range(1, 5):  # the wall, up out of the picture
        rows.append((wall, radius + i * 2.0))
    verts = [(x, y, z) for y, z in rows for x in (-12.0, 12.0)]
    faces = [(2 * i, 2 * i + 1, 2 * i + 3, 2 * i + 2) for i in range(len(rows) - 1)]
    mesh = bpy.data.meshes.new("Backdrop")
    mesh.from_pydata(verts, [], faces)
    for poly in mesh.polygons:
        poly.use_smooth = True
    material = bpy.data.materials.new("Backdrop")
    material.use_nodes = True
    bsdf = material.node_tree.nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = (*BACKDROP, 1.0)
    bsdf.inputs["Roughness"].default_value = 0.8
    mesh.materials.append(material)
    scene.collection.objects.link(bpy.data.objects.new("Backdrop", mesh))


def area(scene, name, location, energy, size, color=(1.0, 1.0, 1.0)):
    data = bpy.data.lights.new(name, "AREA")
    data.energy, data.size, data.color = energy, size, color
    light = bpy.data.objects.new(name, data)
    light.location = location
    aim = light.constraints.new("TRACK_TO")
    aim.target = scene.objects["Target"]
    scene.collection.objects.link(light)


def studio(scene):
    """The backdrop, a camera, a big warm key on the left, a cool fill on the right, a rim above."""
    target = bpy.data.objects.new("Target", None)
    location, aim, lens = CAMERA
    target.location = aim
    scene.collection.objects.link(target)
    world = bpy.data.worlds.new("Studio")
    world.use_nodes = True
    world.node_tree.nodes["Background"].inputs["Color"].default_value = (*BACKDROP, 1.0)
    world.node_tree.nodes["Background"].inputs["Strength"].default_value = 0.25
    scene.world = world
    backdrop(scene)
    area(scene, "Key", (-4.0, -4.5, 4.5), 620.0, 4.0, (1.0, 0.93, 0.85))
    area(scene, "Fill", (5.5, -3.5, 1.5), 90.0, 5.0, (0.8, 0.88, 1.0))
    area(scene, "Rim", (1.0, 2.0, 5.5), 260.0, 2.0)
    data = bpy.data.cameras.new("Camera")
    data.lens = lens
    cam = bpy.data.objects.new("Camera", data)
    cam.location = location
    cam.constraints.new("TRACK_TO").target = target
    scene.collection.objects.link(cam)
    scene.camera = cam


def build(path):
    source = path.read_text(encoding="utf-8")
    groups = {g.name: g for g in build_source(source, filename=path.name)}
    obj = bpy.data.objects.new("CloneWall", bpy.data.meshes.new("CloneWall"))
    bpy.context.scene.collection.objects.link(obj)
    obj.modifiers.new("CloneWall", "NODES").node_group = groups["clone_wall"]
    return obj


def render(name):
    OUT.mkdir(parents=True, exist_ok=True)
    scene = bpy.context.scene
    scene.render.filepath = str(OUT / f"clone-wall-{name}.png")
    bpy.ops.render.render(write_still=True)
    print(f"rendered {scene.render.filepath}")


def animate(name):
    """LOOP frames after PREROLL, as a looping animated WebP; the first of them as the PNG."""
    scene = bpy.context.scene
    frames = Path(tempfile.mkdtemp(prefix=f"clone_wall_{name}_"))
    for frame in range(1, PREROLL + 1):  # the simulations run frame by frame, from the first
        scene.frame_set(frame)
    for i in range(LOOP):
        scene.frame_set(PREROLL + 1 + i)
        scene.render.filepath = str(frames / f"frame_{i:04d}.png")
        bpy.ops.render.render(write_still=True)
    OUT.mkdir(parents=True, exist_ok=True)
    if name in PINGPONG:
        for i in range(LOOP - 2, 0, -1):
            shutil.copy(frames / f"frame_{i:04d}.png", frames / f"frame_{2 * LOOP - 2 - i:04d}.png")
    shutil.copy(frames / "frame_0000.png", OUT / f"clone-wall-{name}.png")
    webp = OUT / f"clone-wall-{name}.webp"
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-framerate", "24",
         "-i", str(frames / "frame_%04d.png"),
         "-c:v", "libwebp_anim", "-lossless", "0", "-q:v", "80",
         "-compression_level", "6", "-loop", "0", "-pix_fmt", "yuv420p", str(webp)],
        check=True,
    )
    shutil.rmtree(frames)
    print(f"rendered {webp}, {webp.stat().st_size} bytes")


def check_round_trip(path):
    """clone_wall of the last step reads back to a text that builds the same group again."""
    empty_scene()
    build(path)
    text, warnings = export_tree(bpy.data.node_groups["clone_wall"])
    assert not warnings, warnings
    again, _ = export_tree(build_source(text, filename="clone_wall.bn")[-1])
    assert again == text, "clone_wall does not read back the same"
    print("round trip clone_wall: ok")


def main():
    only = args()
    steps = sorted(HERE.glob("step*.bn"))
    for path in steps:
        step = path.stem.split("_")[0]
        if only and only != step:
            continue
        empty_scene()
        build(path)
        if step in ANIMATED:
            animate(step)
        else:
            render(step)
    if not only or only == "round-trip":
        check_round_trip(steps[-1])


main()
