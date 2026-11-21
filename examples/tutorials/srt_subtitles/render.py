"""Build srt_subtitles.bn in Blender and render the picture of its page.

  blender -b --factory-startup --python-exit-code 1 --python examples/tutorials/srt_subtitles/render.py

"srt subtitles" reads sample.srt of this folder at 4 s, the second cue, and its text is rendered
with EEVEE, lit by its own emission, in front of a dark world, under an orthographic camera
straight down on the XY plane: site/images/tutorials/srt-subtitles.png (960×360).
"""

import sys
from pathlib import Path

import bpy

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OUT = ROOT / "site" / "images" / "tutorials" / "srt-subtitles.png"
sys.path.insert(0, str(ROOT / "base-node-for-blender" / "tests"))
import test_libraries  # noqa: E402,F401  (loads the extension as `base_node`)

from base_node.host import build_source  # noqa: E402

SECONDS = 4.0


def subtitles():
    build_source((HERE / "srt_subtitles.bn").read_text(encoding="utf-8"), "srt_subtitles.bn")
    obj = bpy.data.objects.new("Subtitles", bpy.data.meshes.new("Subtitles"))
    bpy.context.scene.collection.objects.link(obj)
    mod = obj.modifiers.new("GN", "NODES")
    mod.node_group = bpy.data.node_groups["srt subtitles"]
    for item in mod.node_group.interface.items_tree:
        if item.item_type == "SOCKET" and item.in_out == "INPUT" and item.name == "file":
            getattr(mod.properties.inputs, item.identifier).value = str(HERE / "sample.srt")
    mat = bpy.data.materials.new("Subtitle")
    nt = mat.node_tree
    nt.nodes.clear()
    emission = nt.nodes.new("ShaderNodeEmission")
    emission.inputs["Color"].default_value = (1.0, 0.92, 0.62, 1.0)
    emission.inputs["Strength"].default_value = 1.6
    output = nt.nodes.new("ShaderNodeOutputMaterial")
    nt.links.new(emission.outputs[0], output.inputs["Surface"])
    # The mesh the group makes has no material of its own: the object's slot gives it one
    obj.data.materials.append(None)
    obj.material_slots[0].link = "OBJECT"
    obj.material_slots[0].material = mat


def scene():
    scene = bpy.context.scene
    world = bpy.data.worlds.new("Dark")
    world.node_tree.nodes["Background"].inputs["Color"].default_value = (0.012, 0.014, 0.022, 1.0)
    scene.world = world
    camera = bpy.data.objects.new("Camera", bpy.data.cameras.new("Camera"))
    camera.data.type = "ORTHO"
    camera.data.ortho_scale = 8.0
    camera.location = (0.0, 0.55, 10.0)
    scene.collection.objects.link(camera)
    scene.camera = camera
    scene.render.engine = "BLENDER_EEVEE"
    scene.render.resolution_x, scene.render.resolution_y = 960, 360
    scene.view_settings.view_transform = "Standard"
    scene.frame_set(round(SECONDS * scene.render.fps / scene.render.fps_base))
    scene.render.filepath = str(OUT)


def main():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    subtitles()
    scene()
    bpy.ops.render.render(write_still=True)
    print(f"rendered {OUT}")


main()
