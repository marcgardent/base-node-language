"""Bake the maps of each step of the tileable stone tutorial, show them tiled, and lay the last on a floor.

  blender -b --factory-startup --python-exit-code 1 --python examples/tutorials/tileable_stone/render.py
  blender -b --factory-startup --python-exit-code 1 --python examples/tutorials/tileable_stone/render.py -- --only step3

Every step*.bn of this folder is a compositor graph, tileable_stone, whose outputs are maps of one
texture of 1024 pixels. Each output is rendered alone, by an empty scene whose compositor is the
step's graph, to a 32-bit EXR in the temp folder: the maps as the compositor computes them. Each
map is then shown two by two, so that a seam would show where the copies meet, beside the other
maps of its step, in site/images/tutorials/tileable-stone-<step>.png. Heights, masks and normals
are shown as they are, the albedo with the sRGB curve of a display. A step that does not build
stops the script.

The maps of the last step go on a floor of 6 m by 6 m, the texture repeated three by three, through
the shader group stone_surface of that same step, displaced for real by Cycles: under a low sun in
a courtyard (step7.png, the page's top), and seen from above (step7-tiles.png), where the tiles
meet at 2 m and 4 m. Then the graph of the last step is read back to its text and built again.
"""

import math
import sys
import tempfile
from pathlib import Path

import bpy
import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OUT = ROOT / "site" / "images" / "tutorials"
BAKE = Path(tempfile.gettempdir()) / "base-node-tileable-stone"
sys.path.insert(0, str(ROOT / "addon" / "tests"))
import test_libraries  # noqa: E402,F401  (loads the extension as `base_node`)

from base_node.host import build_source, export_tree  # noqa: E402

GRAPH = "tileable_stone"
SURFACE = "stone_surface"
SIZE = 1024  # px, the texture of every step
WIDTH, HEIGHT = 1000, 750
SAMPLES = 96
BACKGROUND = 0.075  # the frame of the map pictures, as displayed
TILE = 2.0  # m, one repeat of the texture on the floor
COLOR_MAPS = {"albedo"}  # shown with the display's curve; the other maps are data


def args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    return argv[argv.index("--only") + 1] if "--only" in argv else None


def use_gpu(scene):
    prefs = bpy.context.preferences.addons["cycles"].preferences
    for kind in ("OPTIX", "CUDA"):
        try:
            prefs.compute_device_type = kind
            prefs.get_devices()
            for device in prefs.devices:
                device.use = True
            scene.cycles.device = "GPU"
            return
        except TypeError:
            continue


def build(path):
    """The groups of a step, by name."""
    return {g.name: g for g in build_source(path.read_text(encoding="utf-8"), filename=path.name)}


def bake_scene():
    """A scene with nothing to render, the size of the texture."""
    scene = bpy.data.scenes.get("Bake")
    if scene is None:
        scene = bpy.data.scenes.new("Bake")
        scene.camera = bpy.data.objects.new("Bake camera", bpy.data.cameras.new("Bake camera"))
        scene.collection.objects.link(scene.camera)
    scene.render.engine = "CYCLES"
    scene.cycles.samples = 1
    scene.cycles.device = "CPU"
    scene.render.resolution_x = scene.render.resolution_y = SIZE
    scene.render.resolution_percentage = 100
    return scene


def bake(tree, step):
    """The outputs of the step's graph written by one render, as a texture painter exports its maps:
    a File Output node takes each one to BAKE/<step>/<output>.exr, 32-bit. {output: path}."""
    scene = bake_scene()
    folder = BAKE / step
    folder.mkdir(parents=True, exist_ok=True)
    for old in folder.glob("*.exr"):
        old.unlink()
    wrapper = bpy.data.node_groups.new(f"bake {step}", "CompositorNodeTree")
    wrapper.interface.new_socket("Image", in_out="INPUT", socket_type="NodeSocketColor")
    wrapper.interface.new_socket("Image", in_out="OUTPUT", socket_type="NodeSocketColor")
    group = wrapper.nodes.new("CompositorNodeGroup")
    group.node_tree = tree
    wrapper.links.new(wrapper.nodes.new("NodeGroupInput").outputs[0], group.inputs[0])
    wrapper.links.new(group.outputs[0], wrapper.nodes.new("NodeGroupOutput").inputs[0])
    out = wrapper.nodes.new("CompositorNodeOutputFile")
    out.directory, out.file_name = str(folder), ""
    out.format.media_type = "IMAGE"
    out.format.file_format = "OPEN_EXR"
    out.format.color_depth = "32"
    out.format.exr_codec = "ZIP"
    names = [s.name for s in tree.interface.items_tree if s.item_type == "SOCKET" and s.in_out == "OUTPUT"]
    for name in names:
        out.file_output_items.new("RGBA", name)
        wrapper.links.new(group.outputs[name], out.inputs[name])
    scene.compositing_node_group = wrapper
    bpy.ops.render.render(write_still=False, scene=scene.name)
    maps = {}
    for name in names:
        written = sorted(folder.glob(f"{name}*.exr"))
        assert written, f"no map {name} written in {folder}: {sorted(folder.iterdir())}"
        maps[name] = written[0].rename(folder / f"{name}.exr")
        print(f"baked {maps[name]}")
    return maps


def pixels(path):
    """The map as an array of rows from the bottom, RGBA, linear as computed."""
    image = bpy.data.images.load(str(path), check_existing=False)
    w, h = image.size
    array = np.array(image.pixels[:], dtype=np.float32).reshape(h, w, 4)
    bpy.data.images.remove(image)
    return array


def to_display(name, array):
    """What a texture painter shows of a map: data as it is, a colour through the sRGB curve."""
    rgb = np.clip(array[..., :3], 0.0, 1.0)
    if name in COLOR_MAPS:
        rgb = np.where(rgb <= 0.0031308, rgb * 12.92, 1.055 * np.power(rgb, 1.0 / 2.4) - 0.055)
    return rgb


def resized(rgb, size):
    """The square picture scaled to size pixels, by Blender's own scaling."""
    h, w, _ = rgb.shape
    image = bpy.data.images.new("resize", w, h, float_buffer=True)
    image.pixels.foreach_set(np.dstack([rgb, np.ones((h, w))]).astype(np.float32).ravel())
    image.scale(size, size)
    out = np.array(image.pixels[:], dtype=np.float32).reshape(size, size, 4)[..., :3]
    bpy.data.images.remove(image)
    return out


def layout(count):
    """The squares (x, y, size) of count panels in the frame, x from the left, y from the top."""
    if count == 1:
        return [((WIDTH - 690) // 2, 30, 690)]
    if count == 2:
        s = 470
        x0 = (WIDTH - 2 * s - 20) // 2
        return [(x0, (HEIGHT - s) // 2, s), (x0 + s + 20, (HEIGHT - s) // 2, s)]
    if count == 3:
        # Two small on the left, one above the other, and the last, the result, large on the right
        small = (HEIGHT - 48) // 2
        large = WIDTH - small - 16 - 2 * 16
        x0 = (WIDTH - small - 16 - large) // 2
        return [(x0, 16, small), (x0, 32 + small, small), (x0 + small + 16, (HEIGHT - large) // 2, large)]
    s = 352
    x0, y0 = (WIDTH - 2 * s - 16) // 2, (HEIGHT - 2 * s - 16) // 2
    return [(x0 + (i % 2) * (s + 16), y0 + (i // 2) * (s + 16), s) for i in range(count)]


def save_png(rgb, path):
    """An array of rows from the bottom, display values, written as an 8-bit PNG."""
    h, w, _ = rgb.shape
    image = bpy.data.images.new(path.stem, w, h)
    image.pixels.foreach_set(np.dstack([np.clip(rgb, 0, 1), np.ones((h, w))]).astype(np.float32).ravel())
    image.filepath_raw = str(path)
    image.file_format = "PNG"
    image.save()
    bpy.data.images.remove(image)
    print(f"rendered {path}")


def show_maps(maps, step):
    """The maps of a step, each tiled two by two, side by side on a dark frame."""
    frame = np.full((HEIGHT, WIDTH, 3), BACKGROUND, dtype=np.float32)
    for (name, path), (x, y, s) in zip(maps.items(), layout(len(maps))):
        tiled = np.tile(to_display(name, pixels(path)), (2, 2, 1))
        bottom = HEIGHT - y - s
        frame[bottom:bottom + s, x:x + s] = resized(tiled, s)
    OUT.mkdir(parents=True, exist_ok=True)
    save_png(frame, OUT / f"tileable-stone-{step}.png")


# ---- The floor ----

def material(name, color, roughness):
    m = bpy.data.materials.new(name)
    bsdf = m.node_tree.nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = (*color, 1.0)
    bsdf.inputs["Roughness"].default_value = roughness
    return m


def stone_material(maps, surface):
    """The maps of the last step through its shader group, the texture repeated every TILE metres."""
    m = bpy.data.materials.new("Tileable stone")
    m.displacement_method = "BOTH"
    nodes, links = m.node_tree.nodes, m.node_tree.links
    nodes.remove(nodes["Principled BSDF"])
    out = nodes["Material Output"]
    coords = nodes.new("ShaderNodeTexCoord")
    mapping = nodes.new("ShaderNodeMapping")
    mapping.inputs["Scale"].default_value = (1.0 / TILE, 1.0 / TILE, 1.0)
    links.new(coords.outputs["Object"], mapping.inputs["Vector"])
    group = nodes.new("ShaderNodeGroup")
    group.node_tree = surface
    for name, path in maps.items():
        if name not in group.inputs:
            continue
        image = bpy.data.images.load(str(path), check_existing=True)
        image.colorspace_settings.name = "Linear Rec.709" if name in COLOR_MAPS else "Non-Color"
        tex = nodes.new("ShaderNodeTexImage")
        tex.image = image
        tex.interpolation = "Cubic" if name == "height" else "Linear"
        links.new(mapping.outputs["Vector"], tex.inputs["Vector"])
        links.new(tex.outputs["Color"], group.inputs[name])
    links.new(group.outputs["bsdf"], out.inputs["Surface"])
    links.new(group.outputs["displacement"], out.inputs["Displacement"])
    return m


def add(mesh, mat, location, scale=(1.0, 1.0, 1.0), rotation=(0.0, 0.0, 0.0), smooth=False, name="Object"):
    obj = bpy.data.objects.new(name, mesh)
    obj.location, obj.scale, obj.rotation_euler = location, scale, rotation
    mesh.materials.append(mat)
    if smooth:
        for poly in mesh.polygons:
            poly.use_smooth = True
    bpy.data.scenes["Floor"].collection.objects.link(obj)
    return obj


def primitive(op, **kw):
    """A mesh from one of bpy.ops.mesh's primitives, its object taken away."""
    op(**kw)
    obj = bpy.context.active_object
    mesh = obj.data
    bpy.data.objects.remove(obj)
    return mesh


def floor_scene(maps, surface):
    """A courtyard at the end of the afternoon: the stone floor, three by three tiles, a few things on it."""
    scene = bpy.data.scenes.new("Floor")
    scene.render.engine = "CYCLES"
    use_gpu(scene)
    scene.cycles.samples = SAMPLES
    scene.cycles.use_denoising = True
    scene.render.resolution_x, scene.render.resolution_y = WIDTH, HEIGHT
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGB"
    scene.view_settings.view_transform = "AgX"
    scene.view_settings.look = "AgX - Medium High Contrast"

    stone = stone_material(maps, surface)
    floor = primitive(bpy.ops.mesh.primitive_grid_add, x_subdivisions=900, y_subdivisions=900, size=3 * TILE)
    add(floor, stone, (0, 0, 0), name="Floor")
    # Around the floor, gravel; on it, terracotta pots and a wooden bench; plaster walls behind and
    # on the left close the courtyard
    gravel = material("Gravel", (0.16, 0.15, 0.13), 0.9)
    terracotta = material("Terracotta", (0.5, 0.2, 0.1), 0.6)
    wood = material("Wood", (0.33, 0.2, 0.1), 0.65)
    plaster = material("Plaster", (0.62, 0.55, 0.45), 0.85)
    add(primitive(bpy.ops.mesh.primitive_plane_add, size=200), gravel, (0, 0, -0.01), name="Ground")
    props = [
        add(primitive(bpy.ops.mesh.primitive_cylinder_add, vertices=64), terracotta, (-2.3, 2.2, 0.3),
            scale=(0.32, 0.32, 0.3), smooth=True, name="Pot"),
        add(primitive(bpy.ops.mesh.primitive_cylinder_add, vertices=64), terracotta, (-2.45, 1.4, 0.2),
            scale=(0.22, 0.22, 0.2), smooth=True, name="Pot small"),
        add(primitive(bpy.ops.mesh.primitive_cube_add), wood, (0.6, 2.45, 0.42), scale=(0.9, 0.22, 0.04),
            name="Bench seat"),
        add(primitive(bpy.ops.mesh.primitive_cube_add), plaster, (0.0, 3.0 + 0.2, 1.5),
            scale=(4.0, 0.2, 1.5), name="Wall"),
        add(primitive(bpy.ops.mesh.primitive_cube_add), plaster, (-3.0 - 0.2, 0.0, 1.5),
            scale=(0.2, 4.0, 1.5), name="Wall left"),
    ]
    for dx in (-0.75, 0.75):
        props.append(add(primitive(bpy.ops.mesh.primitive_cube_add), wood, (0.6 + dx, 2.45, 0.2),
                         scale=(0.05, 0.2, 0.2), name="Bench leg"))
    # White marks on the gravel where the copies of the texture meet, for the view from above
    chalk = material("Chalk", (0.8, 0.8, 0.78), 0.8)
    marks = []
    for at in (-TILE / 2, TILE / 2):
        for side in (-1, 1):
            edge = side * (3 * TILE / 2 + 0.2)
            marks.append(add(primitive(bpy.ops.mesh.primitive_cube_add), chalk, (at, edge, 0.0),
                             scale=(0.025, 0.15, 0.01), name="Mark"))
            marks.append(add(primitive(bpy.ops.mesh.primitive_cube_add), chalk, (edge, at, 0.0),
                             scale=(0.15, 0.025, 0.01), name="Mark"))

    # A low sun from the right, where the courtyard is open, raking across the floor: every stone
    # throws its shadow to the left
    elevation, azimuth = math.radians(18.0), math.radians(100.0)
    sun = bpy.data.lights.new("Sun", "SUN")
    sun.energy, sun.color, sun.angle = 6.0, (1.0, 0.8, 0.58), math.radians(1.0)
    sun_obj = bpy.data.objects.new("Sun", sun)
    sun_obj.rotation_euler = (math.radians(90.0) - elevation, 0.0, azimuth)
    scene.collection.objects.link(sun_obj)
    world = bpy.data.worlds.new("Afternoon")
    scene.world = world
    nodes = world.node_tree.nodes
    sky = nodes.new("ShaderNodeTexSky")
    sky.sky_type = "MULTIPLE_SCATTERING"
    sky.sun_elevation, sky.sun_rotation = elevation, azimuth - math.radians(90.0)
    sky.sun_disc = False
    nodes["Background"].inputs["Strength"].default_value = 0.12
    world.node_tree.links.new(sky.outputs["Color"], nodes["Background"].inputs["Color"])
    scene["props"], scene["marks"] = [o.name for o in props], [o.name for o in marks]
    return scene


def camera(scene, location, rotation, lens=35.0, ortho=0.0):
    data = bpy.data.cameras.new("Camera")
    data.lens = lens
    if ortho:
        data.type, data.ortho_scale = "ORTHO", ortho
    cam = bpy.data.objects.new("Camera", data)
    cam.location, cam.rotation_euler = location, [math.radians(a) for a in rotation]
    scene.collection.objects.link(cam)
    scene.camera = cam
    return cam


def show(names, visible):
    for name in names:
        bpy.data.objects[name].hide_render = not visible


def render_floor(maps, surface):
    scene = floor_scene(maps, surface)
    OUT.mkdir(parents=True, exist_ok=True)
    # In the courtyard, from a standing eye: the floor, the pots, the bench, the walls
    show(scene["marks"], False)
    camera(scene, (1.4, -3.7, 1.6), (64.0, 0.0, 24.0), lens=28.0)
    scene.render.filepath = str(OUT / "tileable-stone-step7.png")
    bpy.ops.render.render(write_still=True, scene=scene.name)
    print(f"rendered {scene.render.filepath}")
    # From above, the floor alone: its nine copies of the texture, meeting where the marks are
    show(scene["props"], False)
    show(scene["marks"], True)
    camera(scene, (0.0, 0.0, 10.0), (0.0, 0.0, 0.0), ortho=(3 * TILE + 0.8) * WIDTH / HEIGHT)
    scene.render.filepath = str(OUT / "tileable-stone-step7-tiles.png")
    bpy.ops.render.render(write_still=True, scene=scene.name)
    print(f"rendered {scene.render.filepath}")


def check_round_trip(path):
    """The two graphs of the last step read back to a text that builds the same groups again."""
    groups = build(path)
    for name in (GRAPH, SURFACE):
        text, warnings = export_tree(groups[name])
        assert not warnings, warnings
        again, _ = export_tree(build_source(text, filename="round_trip.bn")[-1])
        assert again == text, f"{name} does not read back the same"
        print(f"round trip {name}: ok")


def main():
    only = args()
    bpy.ops.wm.read_factory_settings(use_empty=True)
    steps = sorted(HERE.glob("step*.bn"))
    for path in steps:
        step = path.stem.split("_")[0]
        if only and only != step:
            continue
        groups = build(path)
        maps = bake(groups[GRAPH], step)
        if SURFACE in groups:
            render_floor(maps, groups[SURFACE])
        else:
            show_maps(maps, step)
    if not only or only == "round-trip":
        check_round_trip(steps[-1])


main()
