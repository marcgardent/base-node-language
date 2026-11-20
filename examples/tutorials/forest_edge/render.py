"""Build each step of the forest edge tutorial in Blender and render its picture.

  blender -b --factory-startup --python-exit-code 1 --python examples/tutorials/forest_edge/render.py
  blender -b --factory-startup --python-exit-code 1 --python examples/tutorials/forest_edge/render.py -- --only step3

Every step*.bn of this folder is built from scratch in an empty scene, under the same camera, sun
and sky, and rendered with Cycles to site/images/tutorials/forest-edge-<step>.png. The page shows
these files' text: a step that does not build stops the script. The scene camera is given to the
camera input of the steps that have one. Each step prints how many instances it makes, by layer:
the page quotes these counts. The above step renders the last step again from high above the
hillside, the camera of the other pictures still the one it culls for: what that camera does not
see is gone. The close step renders the last step from the path, for its own camera. Then forest_edge of the last step is read
back to its text and built again.
"""

import math
import sys
from pathlib import Path

import bpy

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OUT = ROOT / "site" / "images" / "tutorials"
sys.path.insert(0, str(ROOT / "base-node-for-blender" / "tests"))
import test_libraries  # noqa: E402,F401  (loads the extension as `base_node`)

from base_node.host import build_source, export_tree  # noqa: E402

SAMPLES = 64
VIEWS = {
    # name: (camera location, target, lens)
    "wide": ((-36.0, -86.0, 11.0), (0.0, 0.0, 8.0), 30),
    "close": ((-2.0, -40.0, 4.2), (6.0, -10.0, 4.0), 30),
    "above": ((-30.0, -95.0, 170.0), (-8.0, -25.0, 0.0), 50),
}
LAYERS = {1: "trees", 2: "bushes", 3: "rocks", 4: "grass"}


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
    scene.render.resolution_x, scene.render.resolution_y = 1000, 750
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGB"
    scene.view_settings.view_transform = "AgX"
    scene.view_settings.look = "AgX - Medium High Contrast"
    scene.view_settings.exposure = -0.7
    return scene


SUN_ELEVATION, SUN_ROTATION = 24.0, -65.0  # degrees: low, from behind the camera on its left


def lights(scene):
    """A blue sky, pale at the horizon and deep overhead, and a warm sun low on the left: long
    shadows across the slope."""
    world = bpy.data.worlds.new("Sky")
    world.use_nodes = True
    nodes, links = world.node_tree.nodes, world.node_tree.links
    direction = nodes.new("ShaderNodeTexCoord")
    height = nodes.new("ShaderNodeSeparateXYZ")
    ramp = nodes.new("ShaderNodeValToRGB")
    ramp.color_ramp.elements[0].position = 0.0
    ramp.color_ramp.elements[0].color = (0.78, 0.86, 0.95, 1.0)
    ramp.color_ramp.elements[1].position = 0.45
    ramp.color_ramp.elements[1].color = (0.22, 0.45, 0.88, 1.0)
    background = nodes["Background"]
    background.inputs["Strength"].default_value = 1.2
    links.new(direction.outputs["Generated"], height.inputs["Vector"])
    links.new(height.outputs["Z"], ramp.inputs["Fac"])
    links.new(ramp.outputs["Color"], background.inputs["Color"])
    scene.world = world
    data = bpy.data.lights.new("Sun", "SUN")
    data.energy = 5.0
    data.angle = math.radians(1.5)
    data.color = (1.0, 0.9, 0.76)
    sun = bpy.data.objects.new("Sun", data)
    sun.rotation_euler = (math.radians(90.0 - SUN_ELEVATION), 0.0, math.radians(SUN_ROTATION))
    scene.collection.objects.link(sun)


def camera(scene, view, name="Camera"):
    location, aim, lens = VIEWS[view]
    target = bpy.data.objects.new(name + " target", None)
    target.location = aim
    scene.collection.objects.link(target)
    data = bpy.data.cameras.new(name)
    data.lens = lens
    data.clip_end = 1000.0
    cam = bpy.data.objects.new(name, data)
    cam.location = location
    cam.constraints.new("TRACK_TO").target = target
    scene.collection.objects.link(cam)
    return cam


def build(path, eye):
    """The step on an object, eye given to its camera input when it has one."""
    source = path.read_text(encoding="utf-8")
    groups = {g.name: g for g in build_source(source, filename=path.name)}
    group = groups["forest_edge"]
    obj = bpy.data.objects.new("Forest edge", bpy.data.meshes.new("Forest edge"))
    bpy.context.scene.collection.objects.link(obj)
    modifier = obj.modifiers.new("Forest edge", "NODES")
    modifier.node_group = group
    for item in group.interface.items_tree:
        if getattr(item, "in_out", None) == "INPUT" and item.socket_type == "NodeSocketObject":
            getattr(modifier.properties.inputs, item.identifier).value = eye
    return obj


def count(obj, step):
    """How many instances the step makes, by the layer each one stores: the counts the page quotes."""
    bpy.context.view_layer.update()
    evaluated = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
    geometry = evaluated.evaluated_geometry()  # holds what instances_pointcloud gives
    instances = geometry.instances_pointcloud()
    if instances is None:
        print(f"count {step}: no instances")
        return
    layer = instances.attributes.get("biome_layer")
    if layer is None:
        print(f"count {step}: {len(instances.points)} instances")
        return
    tally = {}
    for value in layer.data:
        tally[value.value] = tally.get(value.value, 0) + 1
    shown = ", ".join(f"{LAYERS.get(k, k)} {n}" for k, n in sorted(tally.items()))
    print(f"count {step}: {len(instances.points)} instances ({shown})")


def render(name):
    OUT.mkdir(parents=True, exist_ok=True)
    scene = bpy.context.scene
    scene.render.filepath = str(OUT / f"forest-edge-{name}.png")
    bpy.ops.render.render(write_still=True)
    print(f"rendered {scene.render.filepath}")


def still(path, view, name, eye_view=None):
    """The step from view, culled for the camera of eye view: the same one unless given."""
    scene = empty_scene()
    lights(scene)
    shot = camera(scene, view)
    eye = camera(scene, eye_view, "Eye") if eye_view else shot
    scene.camera = shot
    count(build(path, eye), name)
    render(name)


def check_round_trip(path):
    """forest_edge of the last step reads back to a text that builds the same group again."""
    empty_scene()
    build(path, None)
    text, warnings = export_tree(bpy.data.node_groups["forest_edge"])
    assert not warnings, warnings
    again, _ = export_tree(build_source(text, filename="forest_edge.bn")[-1])
    assert again == text, "forest_edge does not read back the same"
    print("round trip forest_edge: ok")


def main():
    only = args()
    steps = sorted(HERE.glob("step*.bn"))
    for path in steps:
        step = path.stem.split("_")[0]
        if not only or only == step:
            still(path, "wide", step)
    if not only or only == "above":
        still(steps[-1], "above", "above", eye_view="wide")
    if not only or only == "close":
        still(steps[-1], "close", "close")
    if not only or only == "round-trip":
        check_round_trip(steps[-1])


main()
