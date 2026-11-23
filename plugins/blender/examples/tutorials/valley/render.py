"""Build each step of the valley tutorial in Blender and render its picture.

  blender -b --factory-startup --python-exit-code 1 --python examples/tutorials/valley/render.py
  blender -b --factory-startup --python-exit-code 1 --python examples/tutorials/valley/render.py -- --only step3

Every step*.bn of this folder is built from scratch in an empty scene, under the same camera, sun
and sky, and rendered with Cycles to site/images/tutorials/valley-<step>.png. The page shows these
files' text: a step that does not build stops the script. Step 7 is seen from near a boulder: its
change is too small from afar. The terraces step renders steps 3 and 4 again, close to a hillside,
to compare them. The maps step renders the maps that the hydraulic erosion of step 5 stores (water,
wetness, change of height), seen from above, each one through a material that shows that attribute
and nothing else. The close step renders the last step again, from the floor of the valley. Then
valley of the last step is read back to its text and built again.
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

SAMPLES = 64
VIEWS = {
    # name: (camera location, target, lens)
    "wide": ((-6.6, -2.1, 5.4), (0.5, 0.0, -0.25), 38),
    "terraces": ((-1.4, 0.4, 1.7), (0.5, -1.5, 0.5), 35),
    "rocks": ((-1.25, 0.45, 1.15), (-0.9, 1.45, 0.4), 32),
    "close": ((-3.0, -1.0, 0.45), (-1.6, 0.6, 0.25), 32),
}
CLOSE = {"step7": "rocks"}  # the steps seen from near the ground: their change is small from afar
# The maps of step 5: attribute, and the colours of its ramp at the values given
MAPS = {
    "water": ("terrain_water", ((0.0, (0.0, 0.0, 0.0)), (0.04, (0.25, 0.6, 1.0)))),
    "wetness": ("terrain_wetness", ((0.0, (0.0, 0.0, 0.0)), (0.02, (0.35, 0.95, 1.0)))),
    # Dug in red, laid down in yellow, nothing in dark grey
    "change": ("terrain_change", ((-0.04, (0.9, 0.15, 0.05)), (0.0, (0.03, 0.03, 0.03)), (0.04, (1.0, 0.85, 0.2)))),
}


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
    return scene


def lights(scene):
    """A blue sky for the shadows, a warm sun low on the left: it rakes the terraces."""
    world = bpy.data.worlds.new("Sky")
    world.use_nodes = True
    world.node_tree.nodes["Background"].inputs["Color"].default_value = (0.3, 0.42, 0.62, 1.0)
    world.node_tree.nodes["Background"].inputs["Strength"].default_value = 0.5
    scene.world = world
    data = bpy.data.lights.new("Sun", "SUN")
    data.energy = 4.0
    data.angle = math.radians(2.0)
    data.color = (1.0, 0.92, 0.8)
    sun = bpy.data.objects.new("Sun", data)
    sun.rotation_euler = (math.radians(60.0), 0.0, math.radians(-15.0))
    scene.collection.objects.link(sun)


def camera(scene, view):
    location, aim, lens = VIEWS[view]
    target = bpy.data.objects.new("Target", None)
    target.location = aim
    scene.collection.objects.link(target)
    data = bpy.data.cameras.new("Camera")
    data.lens = lens
    cam = bpy.data.objects.new("Camera", data)
    cam.location = location
    cam.constraints.new("TRACK_TO").target = target
    scene.collection.objects.link(cam)
    scene.camera = cam


def top_camera(scene):
    """Straight down on the whole valley, 6 m by 4 m: a map reads best from above."""
    data = bpy.data.cameras.new("Top")
    data.type = "ORTHO"
    data.ortho_scale = 6.0
    cam = bpy.data.objects.new("Top", data)
    cam.location = (0.0, 0.0, 5.0)
    scene.collection.objects.link(cam)
    scene.camera = cam
    scene.render.resolution_x, scene.render.resolution_y = 600, 400
    scene.view_settings.view_transform = "Standard"
    scene.cycles.samples = 8


def build(path):
    source = path.read_text(encoding="utf-8")
    groups = {g.name: g for g in build_source(source, filename=path.name)}
    obj = bpy.data.objects.new("Valley", bpy.data.meshes.new("Valley"))
    bpy.context.scene.collection.objects.link(obj)
    obj.modifiers.new("Valley", "NODES").node_group = groups["valley"]
    return obj


def show_map(material, attribute, stops):
    """Turn material into one that shows an attribute of the points through a colour ramp, lit by
    nothing, so that the map reads as it is."""
    nodes, links = material.node_tree.nodes, material.node_tree.links
    nodes.clear()
    read = nodes.new("ShaderNodeAttribute")
    read.attribute_name = attribute
    low, high = stops[0][0], stops[-1][0]
    scale = nodes.new("ShaderNodeMapRange")
    scale.inputs["From Min"].default_value = low
    scale.inputs["From Max"].default_value = high
    ramp = nodes.new("ShaderNodeValToRGB")
    elements = ramp.color_ramp.elements
    while len(elements) < len(stops):
        elements.new(0.5)
    for element, (value, color) in zip(elements, stops):
        element.position = (value - low) / (high - low)
        element.color = (*color, 1.0)
    glow = nodes.new("ShaderNodeEmission")
    out = nodes.new("ShaderNodeOutputMaterial")
    links.new(read.outputs["Fac"], scale.inputs["Value"])
    links.new(scale.outputs["Result"], ramp.inputs["Fac"])
    links.new(ramp.outputs["Color"], glow.inputs["Color"])
    links.new(glow.outputs["Emission"], out.inputs["Surface"])


def render(name):
    OUT.mkdir(parents=True, exist_ok=True)
    scene = bpy.context.scene
    scene.render.filepath = str(OUT / f"valley-{name}.png")
    bpy.ops.render.render(write_still=True)
    print(f"rendered {scene.render.filepath}")


def render_maps(path):
    """The maps of hydraulic erosion, from above, each through its own material instead of Ground."""
    for name, (attribute, stops) in MAPS.items():
        scene = empty_scene()
        top_camera(scene)
        build(path)
        show_map(bpy.data.materials["Ground"], attribute, stops)
        render(f"map-{name}")


def check_round_trip(path):
    """valley of the last step reads back to a text that builds the same group again."""
    empty_scene()
    build(path)
    text, warnings = export_tree(bpy.data.node_groups["valley"])
    assert not warnings, warnings
    again, _ = export_tree(build_source(text, filename="valley.bn")[-1])
    assert again == text, "valley does not read back the same"
    print("round trip valley: ok")


def still(path, view, name):
    scene = empty_scene()
    lights(scene)
    camera(scene, view)
    build(path)
    render(name)


def main():
    only = args()
    steps = sorted(HERE.glob("step*.bn"))
    for path in steps:
        step = path.stem.split("_")[0]
        if not only or only == step:
            still(path, CLOSE.get(step, "wide"), step)
    if not only or only == "terraces":
        for path in steps[2:4]:
            still(path, "terraces", path.stem.split("_")[0] + "-terraces")
    if not only or only == "maps":
        render_maps(steps[4])
    if not only or only == "close":
        still(steps[-1], "close", "close")
    if not only or only == "round-trip":
        check_round_trip(steps[-1])


main()
