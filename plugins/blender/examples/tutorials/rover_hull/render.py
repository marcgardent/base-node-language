"""Build each step of the rover hull tutorial in Blender and render its picture.

  blender -b --factory-startup --python-exit-code 1 --python examples/tutorials/rover_hull/render.py
  blender -b --factory-startup --python-exit-code 1 --python examples/tutorials/rover_hull/render.py -- --only step3

Every step*.bn of this folder is built from scratch in the same scene: a stony desert under a sky
texture, a low golden sun raking the side and the nose of the rover. The hull is the step's; the
desert, the rocks and the six wheels are this script's, plain materials of their own, and so are the
parts it dresses the hull with (bevelled edges, hatches, a solar panel, an antenna dish, camera
lenses), none with a UV map, the painted ones in the step's own material. Step 1 is seen from afar,
the others on the corner of the nose and a fender, and rendered with Cycles to
site/images/tutorials/rover-hull-<step>.png. The page shows these files' text: a step that does not
build stops the script. The close step renders the last step again, close to the nose. Then rover_hull of the last step is read back to its text and built again.
"""

import math
import random
import sys
from pathlib import Path

import bmesh
import bpy
from mathutils import Euler, Matrix, Vector, noise

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OUT = ROOT / "site" / "images" / "tutorials"
sys.path.insert(0, str(ROOT / "addon" / "tests"))
import test_libraries  # noqa: E402,F401  (loads the extension as `base_node`)

from base_node.host import build_source, export_tree  # noqa: E402

SAMPLES = 64
VIEWS = {
    # name: (camera location, target, lens)
    "wide": ((4.3, -3.9, 1.5), (0.0, 0.0, 0.62), 50),
    "corner": ((2.35, -2.15, 1.15), (0.25, -0.15, 0.62), 42),
    "close": ((1.5, -1.3, 0.98), (0.55, -0.35, 0.66), 40),
}
VIEW = {"step1": "wide"}  # the first step from afar, the others on the corner of the nose and a fender
# Elevation and azimuth of the sun, in degrees: low and golden, raking the side and the nose
SUN = (13.0, -78.0)


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
    scene.view_settings.look = "AgX - Punchy"
    return scene


def material(name, color, roughness, metallic=0.0):
    m = bpy.data.materials.new(name)
    bsdf = m.node_tree.nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = (*color, 1.0)
    bsdf.inputs["Roughness"].default_value = roughness
    bsdf.inputs["Metallic"].default_value = metallic
    return m


def stony(name, dark, light, scale, bump):
    """Sand or stone: two tones mixed by a noise, a finer noise as bump."""
    m = material(name, dark, 0.95)
    nodes, links = m.node_tree.nodes, m.node_tree.links
    bsdf = nodes["Principled BSDF"]
    coords = nodes.new("ShaderNodeTexCoord")
    tone = nodes.new("ShaderNodeTexNoise")
    tone.inputs["Scale"].default_value = scale
    tone.inputs["Detail"].default_value = 8.0
    ramp = nodes.new("ShaderNodeValToRGB")
    ramp.color_ramp.elements[0].position, ramp.color_ramp.elements[1].position = 0.35, 0.65
    ramp.color_ramp.elements[0].color, ramp.color_ramp.elements[1].color = (*dark, 1.0), (*light, 1.0)
    grain = nodes.new("ShaderNodeTexNoise")
    grain.inputs["Scale"].default_value = scale * 60.0
    grain.inputs["Detail"].default_value = 6.0
    relief = nodes.new("ShaderNodeBump")
    relief.inputs["Strength"].default_value = bump
    links.new(coords.outputs["Object"], tone.inputs["Vector"])
    links.new(coords.outputs["Object"], grain.inputs["Vector"])
    links.new(tone.outputs["Fac"], ramp.inputs["Fac"])
    links.new(ramp.outputs["Color"], bsdf.inputs["Base Color"])
    links.new(grain.outputs["Fac"], relief.inputs["Height"])
    links.new(relief.outputs["Normal"], bsdf.inputs["Normal"])
    return m


def add(name, mesh, mat, location=(0.0, 0.0, 0.0), rotation=(0.0, 0.0, 0.0), scale=(1.0, 1.0, 1.0)):
    while mesh.uv_layers:
        mesh.uv_layers.remove(mesh.uv_layers[0])
    obj = bpy.data.objects.new(name, mesh)
    obj.location, obj.rotation_euler, obj.scale = location, rotation, scale
    mesh.materials.append(mat)
    bpy.context.scene.collection.objects.link(obj)
    return obj


def primitive(op, smooth=False, **kw):
    """A mesh from one of bpy.ops.mesh's primitives, its object taken away."""
    op(**kw)
    obj = bpy.context.active_object
    mesh = obj.data
    bpy.data.objects.remove(obj)
    if smooth:
        mesh.shade_smooth()
    return mesh


def ground():
    """A stony desert to the horizon: flat under the rover, low dunes beyond, hills far away."""
    mesh = primitive(bpy.ops.mesh.primitive_grid_add, x_subdivisions=500, y_subdivisions=500, size=600.0)
    for v in mesh.vertices:
        p = v.co
        r = math.hypot(p.x, p.y)
        far = min(max((r - 25.0) / 80.0, 0.0), 1.0)
        dunes = noise.fractal(Vector((p.x / 9.0, p.y / 9.0, 0.0)), 0.8, 2.0, 4) * 0.35
        hills = max(noise.fractal(Vector((p.x / 90.0, p.y / 90.0, 3.0)), 0.7, 2.0, 4), -0.2) * 14.0
        p.z = dunes * min(r / 4.0, 1.0) + hills * far * far
    mesh.shade_smooth()
    add("Ground", mesh, stony("Sand", (0.15, 0.1, 0.065), (0.3, 0.2, 0.13), 0.35, 0.45))


def rocks():
    """Stones of every size around the rover, out of its way and of the camera's."""
    stone = stony("Stone", (0.12, 0.1, 0.085), (0.3, 0.26, 0.21), 3.0, 0.6)
    rng = random.Random(4)
    placed = 0
    while placed < 320:
        # The first ones are pebbles near the rover, the others stones further away
        reach = 5.0 if placed < 220 else 18.0
        x, y = rng.uniform(-reach, reach), rng.uniform(-reach, reach + 4.0)
        if abs(x) < 1.1 and abs(y) < 0.95 or (x > 1.5 and y < -1.0 and abs(y + x) < 1.5):
            continue
        size = 0.012 + rng.random() ** 2 * 0.05 if placed < 220 else 0.05 + rng.random() ** 3 * 0.5
        mesh = primitive(bpy.ops.mesh.primitive_ico_sphere_add, subdivisions=2 if size < 0.1 else 3,
                         radius=1.0, smooth=True)
        seed = Vector((rng.random() * 50.0, rng.random() * 50.0, 0.0))
        for v in mesh.vertices:
            v.co *= 1.0 + 0.35 * noise.fractal(v.co * 0.9 + seed, 0.6, 2.0, 3)
        add(f"Rock {placed}", mesh, stone, (x, y, size * 0.25),
            (rng.random() * 3.0, rng.random() * 3.0, rng.random() * 3.0),
            (size * rng.uniform(1.0, 1.6), size, size * rng.uniform(0.5, 0.9)))
        placed += 1


def boxes(parts):
    """One mesh of boxes, each given as (size, matrix): no UV map, flat shaded."""
    bm = bmesh.new()
    for size, matrix in parts:
        bmesh.ops.create_cube(bm, size=1.0, matrix=matrix @ Matrix.Diagonal((*size, 1.0)))
    mesh = bpy.data.meshes.new("Boxes")
    bm.to_mesh(mesh)
    bm.free()
    return mesh


def cylinder(radius, depth, segments=48, radius2=None, matrix=None):
    """A cylinder (or a cone) along z, no UV map, its sides smooth."""
    bm = bmesh.new()
    bmesh.ops.create_cone(bm, cap_ends=True, segments=segments, radius1=radius,
                          radius2=radius if radius2 is None else radius2, depth=depth,
                          matrix=matrix or Matrix.Identity(4))
    for face in bm.faces:
        face.smooth = len(face.verts) == 4
    mesh = bpy.data.meshes.new("Cylinder")
    bm.to_mesh(mesh)
    bm.free()
    return mesh


def bevelled(obj, width, segments=2):
    mod = obj.modifiers.new("Bevel", "BEVEL")
    mod.width, mod.segments, mod.limit_method = width, segments, "ANGLE"
    return obj


ACROSS = Matrix.Rotation(math.radians(90.0), 4, "X")  # z along y: an axle's direction


def wheels():
    """Six wheels under the fenders: treaded tyres on spoked rims, on two rocker beams."""
    rubber = material("Rubber", (0.022, 0.02, 0.019), 0.85)
    rim = material("Rim", (0.55, 0.55, 0.57), 0.3, metallic=1.0)
    steel = material("Steel", (0.08, 0.08, 0.085), 0.4, metallic=1.0)
    # Chevrons of tread around the tyre: two blocks per step, turned either way
    lugs = []
    for i in range(30):
        turn = Matrix.Rotation(2.0 * math.pi * i / 30, 4, "Y")
        for side in (-1.0, 1.0):
            lugs.append(((0.03, 0.07, 0.016), turn @ Matrix.Translation((0.0, side * 0.04, 0.235))
                         @ Matrix.Rotation(side * 0.45, 4, "Z")))
    for x in (-0.65, 0.0, 0.65):
        for y in (-0.7, 0.7):
            out = 1.0 if y > 0 else -1.0
            bevelled(add("Tyre", cylinder(0.235, 0.16, 64, matrix=ACROSS), rubber, (x, y, 0.26)), 0.03, 3)
            bevelled(add("Tread", boxes(lugs), rubber, (x, y, 0.26)), 0.004, 1)
            add("Rim", cylinder(0.15, 0.17, 48, matrix=ACROSS), rim, (x, y, 0.26))
            spokes = [((0.27, 0.03, 0.03), Matrix.Rotation(math.pi * k / 3, 4, "Y")
                       @ Matrix.Translation((0.0, out * 0.08, 0.0))) for k in range(3)]
            add("Spokes", boxes(spokes), rim, (x, y, 0.26))
            add("Hub", cylinder(0.045, 0.24, 24, matrix=ACROSS), steel, (x, y, 0.26))
        add("Axle", cylinder(0.025, 1.3, 16, matrix=ACROSS), steel, (x, 0.0, 0.26))
    for y in (-0.6, 0.6):
        add("Rocker", boxes([((1.5, 0.05, 0.06), Matrix.Identity(4))]), steel, (0.0, y, 0.33))


def dressing(paint):
    """What the step's hull lacks to be a rover: bevelled edges, hatches, a solar panel, the mast's
    cameras and an antenna dish. All without UVs; the painted parts take the step's own material."""
    bevelled(bpy.data.objects["Hull"], 0.012, 2)
    glass = material("Glass", (0.01, 0.012, 0.015), 0.05)
    steel = bpy.data.materials["Steel"]
    cells = material("Cells", (0.02, 0.035, 0.09), 0.25, metallic=0.4)
    nodes, links = cells.node_tree.nodes, cells.node_tree.links
    grid = nodes.new("ShaderNodeTexBrick")
    grid.offset = 0.0
    grid.inputs["Scale"].default_value = 9.0
    grid.inputs["Mortar Size"].default_value = 0.012
    grid.inputs["Color1"].default_value = (0.02, 0.035, 0.09, 1.0)
    grid.inputs["Color2"].default_value = (0.025, 0.04, 0.1, 1.0)
    grid.inputs["Mortar"].default_value = (0.5, 0.52, 0.55, 1.0)
    coords = nodes.new("ShaderNodeTexCoord")
    links.new(coords.outputs["Object"], grid.inputs["Vector"])
    links.new(grid.outputs["Color"], nodes["Principled BSDF"].inputs["Base Color"])
    # Two hatches, on the body in front of the deck and on the deck, and their handles
    hatches = boxes([((0.3, 0.32, 0.03), Matrix.Translation((0.2, -0.22, 0.765))),
                     ((0.26, 0.24, 0.03), Matrix.Translation((-0.22, -0.2, 0.965)))])
    bevelled(add("Hatches", hatches, paint), 0.006, 2)
    add("Handles", boxes([((0.03, 0.16, 0.025), Matrix.Translation((0.31, -0.22, 0.79))),
                          ((0.03, 0.12, 0.025), Matrix.Translation((-0.12, -0.2, 0.99)))]), steel)
    # A solar panel on the back of the deck, tilted up to the sky, on two posts
    tilt = Matrix.Translation((-0.58, 0.12, 1.04)) @ Matrix.Rotation(math.radians(-12.0), 4, "Y")
    bevelled(add("Panel frame", boxes([((0.38, 0.6, 0.03), tilt)]), paint), 0.006, 2)
    add("Cells", boxes([((0.34, 0.56, 0.01), tilt @ Matrix.Translation((0.0, 0.0, 0.017)))]), cells)
    add("Posts", boxes([((0.03, 0.03, 0.1), Matrix.Translation((-0.58, y, 0.99))) for y in (-0.12, 0.36)]), steel)
    # The mast's head: two camera lenses looking ahead
    for dy in (-0.1, 0.1):
        add("Lens", cylinder(0.035, 0.05, 32, matrix=Matrix.Rotation(math.radians(90.0), 4, "Y")), glass,
            (0.29, 0.32 + dy, 1.37))
    # An antenna dish on a short pole at the back corner of the body, turned to the sky
    add("Pole", cylinder(0.014, 0.3, 16), steel, (-0.8, -0.42, 0.9))
    turned = (math.radians(30.0), math.radians(30.0), 0.0)
    # Its mesh placed where it stands, the object at the origin: the material reads object coordinates
    dish = cylinder(0.03, 0.06, 48, radius2=0.15)
    dish.transform(Matrix.Translation((-0.8, -0.42, 1.07)) @ Euler(turned).to_matrix().to_4x4())
    bevelled(add("Dish", dish, paint), 0.004, 2)
    add("Feed", cylinder(0.01, 0.2, 12), steel, (-0.76, -0.47, 1.14), turned)


def lights(scene):
    """A sky texture of the sun's own position, and the sun."""
    elevation, azimuth = (math.radians(a) for a in SUN)
    data = bpy.data.lights.new("Sun", "SUN")
    data.energy = 5.0
    data.angle = math.radians(1.0)
    data.color = (1.0, 0.72, 0.45)
    sun = bpy.data.objects.new("Sun", data)
    toward = Vector((math.cos(elevation) * math.cos(azimuth), math.cos(elevation) * math.sin(azimuth), math.sin(elevation)))
    sun.rotation_euler = toward.to_track_quat("Z", "Y").to_euler()
    scene.collection.objects.link(sun)
    world = bpy.data.worlds.new("Sky")
    scene.world = world
    nodes = world.node_tree.nodes
    sky = nodes.new("ShaderNodeTexSky")
    sky.sky_type = "MULTIPLE_SCATTERING"
    sky.sun_elevation = elevation
    sky.sun_rotation = azimuth + math.radians(90.0)
    sky.sun_disc = False
    nodes["Background"].inputs["Strength"].default_value = 0.12
    world.node_tree.links.new(sky.outputs["Color"], nodes["Background"].inputs["Color"])


def camera(scene, view):
    location, aim, lens = VIEWS[view]
    target = bpy.data.objects.new("Target", None)
    target.location = aim
    scene.collection.objects.link(target)
    data = bpy.data.cameras.new("Camera")
    data.lens = lens
    data.clip_end = 1000.0
    cam = bpy.data.objects.new("Camera", data)
    cam.location = location
    cam.constraints.new("TRACK_TO").target = target
    scene.collection.objects.link(cam)
    scene.camera = cam


def setting(view):
    scene = empty_scene()
    lights(scene)
    camera(scene, view)
    ground()
    rocks()
    wheels()
    return scene


def build(path):
    source = path.read_text(encoding="utf-8")
    groups = {g.name: g for g in build_source(source, filename=path.name)}
    obj = bpy.data.objects.new("Hull", bpy.data.meshes.new("Hull"))
    bpy.context.scene.collection.objects.link(obj)
    obj.modifiers.new("Hull", "NODES").node_group = groups["rover_hull"]
    return obj


def render(name):
    OUT.mkdir(parents=True, exist_ok=True)
    scene = bpy.context.scene
    scene.render.filepath = str(OUT / f"rover-hull-{name}.png")
    bpy.ops.render.render(write_still=True)
    print(f"rendered {scene.render.filepath}")


def check_round_trip(path):
    """rover_hull of the last step reads back to a text that builds the same group again."""
    empty_scene()
    build(path)
    text, warnings = export_tree(bpy.data.node_groups["rover_hull"])
    assert not warnings, warnings
    again, _ = export_tree(build_source(text, filename="rover_hull.bn")[-1])
    assert again == text, "rover_hull does not read back the same"
    print("round trip rover_hull: ok")


def main():
    only = args()
    steps = sorted(HERE.glob("step*.bn"))
    for path in steps:
        step = path.stem.split("_")[0]
        if not only or only == step:
            setting(VIEW.get(step, "corner"))
            build(path)
            dressing(bpy.data.materials["HullPaint"])
            render(step)
    if not only or only == "close":
        setting("close")
        build(steps[-1])
        dressing(bpy.data.materials["HullPaint"])
        render("close")
    if not only or only == "round-trip":
        check_round_trip(steps[-1])


main()
