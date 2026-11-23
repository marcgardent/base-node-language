"""Build each step of the title sequence tutorial in Blender and render its picture or its animation.

  blender -b --factory-startup --python-exit-code 1 --python examples/tutorials/title_sequence/render.py
  blender -b --factory-startup --python-exit-code 1 --python examples/tutorials/title_sequence/render.py -- --only step3

Every step*.bn of this folder is built from scratch in an empty scene, in front of the same dark
gradient card, under the same orthographic camera straight down on the XY plane, and rendered with
EEVEE and a bloom from the compositor. A step that moves is rendered frame after frame, from the
first frame of the scene, as its simulations need, to an animated WebP that loops,
site/images/tutorials/title-sequence-<step>.webp (640×427); the still step to a PNG. The page shows
these files' text: a step that does not build stops the script. Then title_sequence of the last
step is read back to its text and built again.
"""

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import bpy

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OUT = ROOT / "site" / "images" / "tutorials"
sys.path.insert(0, str(ROOT / "addon" / "tests"))
import test_libraries  # noqa: E402,F401  (loads the extension as `base_node`)

from base_node.host import build_source, export_tree  # noqa: E402

FRAMES = 96  # 4 s at 24 frames a second: the whole sequence, from nothing back to nothing
STILL = 60  # the frame of a step that does not move yet
WIDTH = 12.0  # of the view, in metres of the XY plane
TOP = (0.035, 0.012, 0.075)  # the card: violet at the top, near black at the bottom, lighter behind the title
BOTTOM = (0.002, 0.003, 0.012)
MOVES = {"step1": False}  # every other step moves
# The frames of a folder as a WebP that loops, quality 75, by Pillow (outside Blender, whose Python
# has no Pillow): ffmpeg's libwebp_anim keeps only the rectangle that changed from one frame to the
# next, and its edges show as boxes on the gradient of the card: here every frame is whole (kmax=1).
ENCODE = """
import sys
from pathlib import Path
from PIL import Image
frames = [Image.open(p).convert("RGB") for p in sorted(Path(sys.argv[1]).glob("frame_*.png"))]
frames[0].save(sys.argv[2], save_all=True, append_images=frames[1:], duration=round(1000 / 24),
               loop=0, quality=75, method=6, kmin=0, kmax=1)
"""


def args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    only = argv[argv.index("--only") + 1] if "--only" in argv else None
    frames = int(argv[argv.index("--frames") + 1]) if "--frames" in argv else FRAMES
    return only, frames


def card():
    """A card behind the title: an unlit vertical gradient, with a soft glow behind the middle."""
    mat = bpy.data.materials.new("Card")
    mat.use_nodes = True
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    nodes.clear()
    out = nodes.new("ShaderNodeOutputMaterial")
    emit = nodes.new("ShaderNodeEmission")
    coords = nodes.new("ShaderNodeTexCoord")
    xyz = nodes.new("ShaderNodeSeparateXYZ")
    links.new(coords.outputs["Object"], xyz.inputs["Vector"])
    # Bottom to top, 0 to 1
    up = nodes.new("ShaderNodeMapRange")
    up.inputs["From Min"].default_value, up.inputs["From Max"].default_value = -4.0, 4.0
    links.new(xyz.outputs["Y"], up.inputs["Value"])
    ramp = nodes.new("ShaderNodeValToRGB")
    ramp.color_ramp.elements[0].color = (*BOTTOM, 1.0)
    ramp.color_ramp.elements[1].color = (*TOP, 1.0)
    links.new(up.outputs["Result"], ramp.inputs["Fac"])
    # A glow, 1 at the middle and 0 four metres away, squashed vertically
    squash = nodes.new("ShaderNodeVectorMath")
    squash.operation = "MULTIPLY"
    squash.inputs[1].default_value = (0.22, 0.45, 0.0)
    links.new(coords.outputs["Object"], squash.inputs[0])
    gradient = nodes.new("ShaderNodeTexGradient")
    gradient.gradient_type = "SPHERICAL"
    links.new(squash.outputs["Vector"], gradient.inputs["Vector"])
    glow = nodes.new("ShaderNodeMix")
    glow.data_type = "RGBA"
    glow.blend_type = "ADD"
    glow.inputs["B"].default_value = (0.06, 0.018, 0.10, 1.0)
    links.new(gradient.outputs["Fac"], glow.inputs["Factor"])
    links.new(ramp.outputs["Color"], glow.inputs["A"])
    links.new(glow.outputs["Result"], emit.inputs["Color"])
    links.new(emit.outputs["Emission"], out.inputs["Surface"])
    w, h = WIDTH * 0.6, WIDTH * 0.45
    sheet = bpy.data.meshes.new("Card")
    sheet.from_pydata([(-w, -h, -0.5), (w, -h, -0.5), (w, h, -0.5), (-w, h, -0.5)], [], [(0, 1, 2, 3)])
    sheet.materials.append(mat)
    bpy.context.scene.collection.objects.link(bpy.data.objects.new("Card", sheet))


def bloom(scene):
    """The compositor's bloom on what shines: the letters, the sparks, the comet."""
    tree = bpy.data.node_groups.new("Bloom", "CompositorNodeTree")
    tree.interface.new_socket("Image", in_out="OUTPUT", socket_type="NodeSocketColor")
    layers = tree.nodes.new("CompositorNodeRLayers")
    glare = tree.nodes.new("CompositorNodeGlare")
    glare.inputs["Type"].default_value = "Bloom"
    glare.inputs["Quality"].default_value = "High"
    glare.inputs["Threshold"].default_value = 0.6
    glare.inputs["Strength"].default_value = 0.7
    glare.inputs["Size"].default_value = 0.6
    out = tree.nodes.new("NodeGroupOutput")
    tree.links.new(layers.outputs["Image"], glare.inputs["Image"])
    tree.links.new(glare.outputs["Image"], out.inputs[0])
    scene.compositing_node_group = tree


def empty_scene(width, height):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_EEVEE"
    scene.eevee.taa_render_samples = 16
    scene.render.resolution_x, scene.render.resolution_y = width, height
    scene.render.fps = 24
    scene.frame_start, scene.frame_end = 1, FRAMES
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGB"
    scene.view_settings.view_transform = "AgX"
    scene.view_settings.look = "AgX - Medium High Contrast"
    card()
    bloom(scene)
    data = bpy.data.cameras.new("Camera")
    data.type = "ORTHO"
    data.ortho_scale = WIDTH
    cam = bpy.data.objects.new("Camera", data)
    cam.location = (0.0, 0.0, 10.0)
    scene.collection.objects.link(cam)
    scene.camera = cam
    return scene


def build(path):
    source = path.read_text(encoding="utf-8")
    groups = {g.name: g for g in build_source(source, filename=path.name)}
    obj = bpy.data.objects.new("Title", bpy.data.meshes.new("Title"))
    bpy.context.scene.collection.objects.link(obj)
    obj.modifiers.new("Title", "NODES").node_group = groups["title_sequence"]
    # A letter that fades in is blended, not dithered: the dither's noise would crawl from frame to frame
    for mat in bpy.data.materials:
        if mat.name != "Card":
            mat.surface_render_method = "BLENDED"
    return obj


def render_still(scene, step):
    OUT.mkdir(parents=True, exist_ok=True)
    for frame in range(1, STILL + 1):
        scene.frame_set(frame)
    scene.render.filepath = str(OUT / f"title-sequence-{step}.png")
    bpy.ops.render.render(write_still=True)
    print(f"rendered {scene.render.filepath}")


def render_animation(scene, step, frames):
    """Every frame from the first, in order, as a simulation needs; encoded as a WebP that loops."""
    OUT.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix=f"title-sequence-{step}-"))
    try:
        for frame in range(1, frames + 1):
            scene.frame_set(frame)
            scene.render.filepath = str(tmp / f"frame_{frame:04d}.png")
            bpy.ops.render.render(write_still=True)
        out = OUT / f"title-sequence-{step}.webp"
        subprocess.run(["python3", "-I", "-c", ENCODE, str(tmp), str(out)], check=True)
        print(f"rendered {out}, {out.stat().st_size} bytes")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def check_round_trip(path):
    """title_sequence of the last step reads back to a text that builds the same group again."""
    empty_scene(640, 427)
    build(path)
    text, warnings = export_tree(bpy.data.node_groups["title_sequence"])
    assert not warnings, warnings
    again, _ = export_tree(build_source(text, filename="title_sequence.bn")[-1])
    assert again == text, "title_sequence does not read back the same"
    print("round trip title_sequence: ok")


def main():
    only, frames = args()
    steps = sorted(HERE.glob("step*.bn"))
    for path in steps:
        step = path.stem.split("_")[0]
        if only and only != step:
            continue
        if MOVES.get(step, True):
            scene = empty_scene(640, 427)
            build(path)
            render_animation(scene, step, frames)
        else:
            scene = empty_scene(960, 640)
            build(path)
            render_still(scene, step)
    if not only or only == "round-trip":
        check_round_trip(steps[-1])


main()
