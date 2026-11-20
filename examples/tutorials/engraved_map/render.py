"""Build each step of the engraved map tutorial in Blender and render its picture.

  blender -b --factory-startup --python-exit-code 1 --python examples/tutorials/engraved_map/render.py
  blender -b --factory-startup --python-exit-code 1 --python examples/tutorials/engraved_map/render.py -- --only step3

Every step*.bn of this folder is built from scratch in an empty scene, on a sheet of paper, under
the same orthographic camera, straight down, at frame 72, and rendered with EEVEE to
site/images/tutorials/engraved-map-<step>.png. The page shows these files' text: a step that does not
build stops the script. The close step renders steps 5 and 6 again near the north summit, to compare
their lines. The last step draws itself: it is rendered at three earlier frames,
engraved-map-write-<frame>.png. Then engraved_map of the last step is read back to its text and
built again.
"""

import sys
from pathlib import Path

import bpy

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OUT = ROOT / "site" / "images" / "tutorials"
sys.path.insert(0, str(ROOT / "base-node-for-blender" / "tests"))
import test_libraries  # noqa: E402,F401  (loads the extension as `base_node`)

from base_node.host import build_source, export_tree  # noqa: E402

PAPER = (0.84, 0.77, 0.62, 1.0)
DONE = 72  # the frame the last step has finished drawing itself
WRITE_ON = (18, 36, 54)  # frames of the last step, on its way
VIEWS = {
    # name: (centre of the view, width of the view)
    "map": ((0.0, 0.0), 4.3),
    "close": ((-1.2, 0.72), 1.4),
}


def args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    return argv[argv.index("--only") + 1] if "--only" in argv else None


def paper():
    """A sheet under the map: an unlit colour, faintly mottled so that it reads as paper."""
    mat = bpy.data.materials.new("Paper")
    mat.use_nodes = True
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    nodes.clear()
    out = nodes.new("ShaderNodeOutputMaterial")
    emit = nodes.new("ShaderNodeEmission")
    noise = nodes.new("ShaderNodeTexNoise")
    noise.inputs["Scale"].default_value = 3.0
    noise.inputs["Detail"].default_value = 2.0
    ramp = nodes.new("ShaderNodeValToRGB")
    ramp.color_ramp.elements[0].position = 0.3
    ramp.color_ramp.elements[0].color = tuple(c * 0.94 for c in PAPER[:3]) + (1.0,)
    ramp.color_ramp.elements[1].position = 0.7
    ramp.color_ramp.elements[1].color = PAPER
    links.new(noise.outputs["Fac"], ramp.inputs["Fac"])
    links.new(ramp.outputs["Color"], emit.inputs["Color"])
    links.new(emit.outputs["Emission"], out.inputs["Surface"])
    sheet = bpy.data.meshes.new("Paper")
    sheet.from_pydata([(-3, -2.5, -0.01), (3, -2.5, -0.01), (3, 2.5, -0.01), (-3, 2.5, -0.01)], [], [(0, 1, 2, 3)])
    sheet.materials.append(mat)
    bpy.context.scene.collection.objects.link(bpy.data.objects.new("Paper", sheet))


def empty_scene(view="map"):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_EEVEE"
    scene.eevee.taa_render_samples = 16
    scene.render.resolution_x, scene.render.resolution_y = 1000, 750
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGB"
    # Ink and paper are flat colours: shown as they are, with no tone mapping
    scene.view_settings.view_transform = "Standard"
    scene.render.dither_intensity = 0.0  # flat paper compresses well without the dither's noise
    paper()
    data = bpy.data.cameras.new("Camera")
    data.type = "ORTHO"
    centre, data.ortho_scale = VIEWS[view]
    cam = bpy.data.objects.new("Camera", data)
    cam.location = (*centre, 5.0)
    scene.collection.objects.link(cam)
    scene.camera = cam
    return scene


def build(path):
    source = path.read_text(encoding="utf-8")
    groups = {g.name: g for g in build_source(source, filename=path.name)}
    obj = bpy.data.objects.new("Map", bpy.data.meshes.new("Map"))
    bpy.context.scene.collection.objects.link(obj)
    obj.modifiers.new("Map", "NODES").node_group = groups["engraved_map"]
    return obj


def render(name):
    OUT.mkdir(parents=True, exist_ok=True)
    scene = bpy.context.scene
    scene.render.filepath = str(OUT / f"engraved-map-{name}.png")
    bpy.ops.render.render(write_still=True)
    print(f"rendered {scene.render.filepath}")


def check_round_trip(path):
    """engraved_map of the last step reads back to a text that builds the same group again."""
    empty_scene()
    build(path)
    text, warnings = export_tree(bpy.data.node_groups["engraved_map"])
    assert not warnings, warnings
    again, _ = export_tree(build_source(text, filename="engraved_map.bn")[-1])
    assert again == text, "engraved_map does not read back the same"
    print("round trip engraved_map: ok")


def main():
    only = args()
    steps = sorted(HERE.glob("step*.bn"))
    for path in steps:
        step = path.stem.split("_")[0]
        if only and only != step:
            continue
        scene = empty_scene()
        scene.frame_set(DONE)
        build(path)
        render(step)
    if not only or only == "close":
        for path in steps[-3:-1]:
            scene = empty_scene("close")
            scene.frame_set(DONE)
            build(path)
            render(path.stem.split("_")[0] + "-close")
    if not only or only == "write":
        scene = empty_scene()
        build(steps[-1])
        for frame in WRITE_ON:
            scene.frame_set(frame)
            render(f"write-{frame}")
    if not only or only == "round-trip":
        check_round_trip(steps[-1])


main()
