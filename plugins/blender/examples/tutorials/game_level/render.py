"""Build each step of the game level tutorial in Blender and render its picture.

  blender -b --factory-startup --python-exit-code 1 --python examples/tutorials/game_level/render.py
  blender -b --factory-startup --python-exit-code 1 --python examples/tutorials/game_level/render.py -- --only step3

Every step*.bn of this folder is built from scratch in an empty scene, under the same camera, daylight
sky and sun, and rendered with Cycles to site/images/tutorials/game-level-<step>.png. The page shows
these files' text: a step that does not build stops the script. The webp step renders the last step
close to the stream, the time of its flow driven over one cycle, as a looping animated WebP,
game-level-stream.webp (ffmpeg with libwebp_anim). The lightmap and lod steps render what a beauty
render cannot show of the last step: its lightmap UV map laid flat (game-level-lightmap.png) and its
levels of detail seen from above (game-level-lod.png). Then game_level of the last step is read back
to its text and built again.
"""

import math
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import bpy
from mathutils import Vector

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OUT = ROOT / "site" / "images" / "tutorials"
sys.path.insert(0, str(ROOT / "addon" / "tests"))
import test_libraries  # noqa: E402,F401  (loads the extension as `base_node`)

from base_node.host import build_source, export_tree  # noqa: E402

SAMPLES = 64
VIEWS = {
    # name: (camera location, target, lens); wide is the camera haze() fades from
    "wide": ((-64.0, -17.0, 12.0), (-1.0, -11.5, -1.3), 29),
    "stream": ((-47.0, -31.0, 6.0), (-27.0, -27.0, -1.0), 30),
}
FRAMES = 48  # of the animated stream: one cycle of the two-phase blend, so that it loops
# The levels of detail, from above: lod_level 0 to 3, each a colour, its cells drawn darker
LOD_COLORS = ((0.15, 0.45, 0.2), (0.85, 0.72, 0.15), (0.9, 0.42, 0.12), (0.7, 0.12, 0.12))


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


def daylight(scene):
    """A soft daylight sky and a warm sun from the south-west, 32 degrees high: the showcase's."""
    world = bpy.data.worlds.new("Day")
    world.use_nodes = True
    nodes, links = world.node_tree.nodes, world.node_tree.links
    background = nodes["Background"]
    background.inputs["Strength"].default_value = 0.12
    sky = nodes.new("ShaderNodeTexSky")
    sky.sky_type = "MULTIPLE_SCATTERING"
    sky.sun_disc = False
    sky.sun_elevation = math.radians(32)
    sky.sun_rotation = math.radians(235)
    sky.air_density = 1.4
    sky.aerosol_density = 2.0
    richer = nodes.new("ShaderNodeHueSaturation")
    richer.inputs["Saturation"].default_value = 1.6
    links.new(sky.outputs["Color"], richer.inputs["Color"])
    links.new(richer.outputs["Color"], background.inputs["Color"])
    scene.world = world
    data = bpy.data.lights.new("Sun", "SUN")
    data.energy = 3.2
    data.angle = math.radians(4.0)
    data.color = (1.0, 0.88, 0.72)
    sun = bpy.data.objects.new("Sun", data)
    elevation, azimuth = math.radians(32), math.radians(235)
    towards = -Vector((
        math.cos(elevation) * math.cos(azimuth),
        math.cos(elevation) * math.sin(azimuth),
        math.sin(elevation),
    ))
    sun.rotation_euler = towards.to_track_quat("-Z", "Y").to_euler()
    scene.collection.objects.link(sun)


def camera(scene, view):
    location, aim, lens = VIEWS[view]
    data = bpy.data.cameras.new("Camera")
    data.lens = lens
    data.clip_end = 5000.0
    cam = bpy.data.objects.new("Camera", data)
    cam.location = location
    cam.rotation_euler = (Vector(aim) - Vector(location)).to_track_quat("-Z", "Y").to_euler()
    scene.collection.objects.link(cam)
    scene.camera = cam


def top_camera(scene, centre, size, resolution):
    """Straight down, orthographic, size metres across: a map reads best from above."""
    data = bpy.data.cameras.new("Top")
    data.type = "ORTHO"
    data.ortho_scale = size
    data.clip_end = 1000.0
    cam = bpy.data.objects.new("Top", data)
    cam.location = (centre[0], centre[1], 200.0)
    scene.collection.objects.link(cam)
    scene.camera = cam
    scene.render.resolution_x, scene.render.resolution_y = resolution


def build(path):
    source = path.read_text(encoding="utf-8")
    groups = {g.name: g for g in build_source(source, filename=path.name)}
    obj = bpy.data.objects.new("Level", bpy.data.meshes.new("Level"))
    bpy.context.scene.collection.objects.link(obj)
    obj.modifiers.new("Level", "NODES").node_group = groups["game_level"]
    return obj


def render(name):
    OUT.mkdir(parents=True, exist_ok=True)
    scene = bpy.context.scene
    scene.render.filepath = str(OUT / f"game-level-{name}.png")
    bpy.ops.render.render(write_still=True)
    print(f"rendered {scene.render.filepath}")


def still(path, view, name):
    scene = empty_scene()
    daylight(scene)
    camera(scene, view)
    build(path)
    render(name)


def emission(material, color_socket_of):
    """Turn material into one lit by nothing, its colour made by color_socket_of(nodes, links)."""
    nodes, links = material.node_tree.nodes, material.node_tree.links
    nodes.clear()
    glow = nodes.new("ShaderNodeEmission")
    out = nodes.new("ShaderNodeOutputMaterial")
    links.new(color_socket_of(nodes, links), glow.inputs["Color"])
    links.new(glow.outputs["Emission"], out.inputs["Surface"])


def with_wire(nodes, links, color, darker=0.35):
    """color, its edges drawn darker one pixel wide."""
    wire = nodes.new("ShaderNodeWireframe")
    wire.use_pixel_size = True
    wire.inputs["Size"].default_value = 1.0
    mix = nodes.new("ShaderNodeMix")
    mix.data_type = "RGBA"
    mix.blend_type = "MULTIPLY"
    socket = {s.identifier: s for s in [*mix.inputs, *mix.outputs]}
    socket["B_Color"].default_value = (darker, darker, darker, 1.0)
    links.new(wire.outputs["Fac"], socket["Factor_Float"])
    links.new(color, socket["A_Color"])
    return socket["Result_Color"]


def render_lod(path):
    """The level's ground from above, each point coloured by its lod_level, the cells drawn: they
    grow past 70 m from the camera, which stands at the left edge."""
    scene = empty_scene()
    daylight(scene)
    top_camera(scene, (40.0, 0.0), 240.0, (960, 560))
    scene.view_settings.view_transform = "Standard"
    build(path)

    def levels(nodes, links):
        read = nodes.new("ShaderNodeAttribute")
        read.attribute_name = "lod_level"
        share = nodes.new("ShaderNodeMath")
        share.operation = "DIVIDE"
        share.inputs[1].default_value = len(LOD_COLORS) - 1
        ramp = nodes.new("ShaderNodeValToRGB")
        ramp.color_ramp.interpolation = "CONSTANT"
        elements = ramp.color_ramp.elements
        while len(elements) < len(LOD_COLORS):
            elements.new(0.5)
        for i, (element, color) in enumerate(zip(elements, LOD_COLORS)):
            element.position = max(i - 0.5, 0.0) / (len(LOD_COLORS) - 1)
            element.color = (*color, 1.0)
        links.new(read.outputs["Fac"], share.inputs[0])
        links.new(share.outputs["Value"], ramp.inputs["Fac"])
        return with_wire(nodes, links, ramp.outputs["Color"])

    emission(bpy.data.materials["Ground"], levels)
    render("lod")


def render_lightmap(path):
    """The lightmap UV map of the houses laid flat: each face of the town at its place in the unit
    square, in the colour of its house, its edges drawn."""
    scene = empty_scene()
    obj = build(path)
    mesh = obj.evaluated_get(bpy.context.evaluated_depsgraph_get()).to_mesh()
    tint = mesh.attributes["tint"].data
    uv = mesh.attributes["lightmap"].data
    points, faces, colors = [], [], []
    for face in mesh.polygons:
        if any(tint[v].color[3] == 0.0 for v in face.vertices):
            continue  # not a house: the lightmap is theirs
        start = len(points)
        points += [(*uv[c].vector, 0.0) for c in face.loop_indices]
        faces.append(range(start, len(points)))
        colors += [tint[face.vertices[0]].color] * len(face.loop_indices)
    obj.modifiers.clear()
    layout = bpy.data.meshes.new("Layout")
    layout.from_pydata(points, [], faces)
    layout.color_attributes.new("tint", "FLOAT_COLOR", "POINT").data.foreach_set(
        "color", [x for c in colors for x in c])
    flat = bpy.data.objects.new("Layout", layout)
    scene.collection.objects.link(flat)
    square = bpy.data.meshes.new("Square")
    square.from_pydata([(0, 0, -0.01), (1, 0, -0.01), (1, 1, -0.01), (0, 1, -0.01)], [], [(0, 1, 2, 3)])
    sheet = bpy.data.objects.new("Square", square)
    scene.collection.objects.link(sheet)
    for target, paint in ((flat, None), (sheet, (0.9, 0.9, 0.88))):
        material = bpy.data.materials.new(target.name)
        material.use_nodes = True
        target.data.materials.append(material)

        def colour(nodes, links, paint=paint):
            if paint:
                rgb = nodes.new("ShaderNodeRGB")
                rgb.outputs[0].default_value = (*paint, 1.0)
                return rgb.outputs[0]
            read = nodes.new("ShaderNodeAttribute")
            read.attribute_name = "tint"
            return with_wire(nodes, links, read.outputs["Color"])

        emission(material, colour)
    world = bpy.data.worlds.new("Paper")
    world.color = (0.25, 0.25, 0.25)
    scene.world = world
    top_camera(scene, (0.5, 0.5), 1.08, (600, 600))
    scene.view_settings.view_transform = "Standard"
    scene.cycles.samples = 16
    render("lightmap")


def flow_time(value):
    """Set the time of the two-phase blend in the material Stream: a shader graph has no clock."""
    for node in bpy.data.materials["Stream"].node_tree.nodes:
        if node.type == "GROUP" and "time" in node.inputs and not node.inputs["time"].is_linked:
            node.inputs["time"].default_value = value


def render_webp(path):
    """The stream, close, flowing: one cycle of the blend in FRAMES frames, an animated WebP."""
    scene = empty_scene()
    daylight(scene)
    camera(scene, "stream")
    build(path)
    scene.render.resolution_x, scene.render.resolution_y = 640, 480
    scene.cycles.samples = 32
    frames = Path(tempfile.mkdtemp(prefix="game-level-stream-"))
    for i in range(FRAMES):
        flow_time(i / FRAMES)
        scene.render.filepath = str(frames / f"frame_{i:04d}.png")
        bpy.ops.render.render(write_still=True)
    out = OUT / "game-level-stream.webp"
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-framerate", "24",
         "-i", str(frames / "frame_%04d.png"), "-c:v", "libwebp_anim", "-lossless", "0",
         "-q:v", "75", "-compression_level", "6", "-loop", "0", "-pix_fmt", "yuv420p", str(out)],
        check=True,
    )
    shutil.rmtree(frames)
    print(f"rendered {out}")


def check_round_trip(path):
    """game_level of the last step reads back to a text that builds the same group again."""
    empty_scene()
    build(path)
    text, warnings = export_tree(bpy.data.node_groups["game_level"])
    assert not warnings, warnings
    again, _ = export_tree(build_source(text, filename="game_level.bn")[-1])
    assert again == text, "game_level does not read back the same"
    print("round trip game_level: ok")


def main():
    only = args()
    steps = sorted(HERE.glob("step*.bn"))
    for path in steps:
        step = path.stem.split("_")[0]
        if not only or only == step:
            still(path, "wide", step)
    if not only or only == "webp":
        render_webp(steps[-1])
    if not only or only == "lod":
        render_lod(steps[-1])
    if not only or only == "lightmap":
        render_lightmap(steps[-1])
    if not only or only == "round-trip":
        check_round_trip(steps[-1])


main()
