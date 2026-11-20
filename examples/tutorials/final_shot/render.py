"""Render the plate of the final shot tutorial once, then composite each step from it.

  blender -b --factory-startup --python-exit-code 1 --python examples/tutorials/final_shot/render.py
  blender -b --factory-startup --python-exit-code 1 --python examples/tutorials/final_shot/render.py -- --only step3
  blender -b --factory-startup --python-exit-code 1 --python examples/tutorials/final_shot/render.py -- --fresh

The plate is a dusk shot: a few objects on a square, a lamp post, a row of street lamps going away,
blocks of buildings on the horizon, a low sun from the front left under a sky texture. Cycles renders it
once, with its passes, to a multilayer EXR kept in the temp folder; it is rendered again when this
script is newer than it, or with --fresh.

Every step*.bn of this folder is then built in that scene, as a compositor graph that reads its
Render Layers. Its Render Layers node is swapped for an Image node of the EXR, whose outputs are the
same passes, and an empty scene renders the composite to site/images/tutorials/final-shot-<step>.png:
no step renders the 3D scene again. A step that does not build stops the script. The before / after
picture of the page's top is the first step on the left, the last on the right. Then the graph of
the last step is read back to its text and built again.
"""

import math
import sys
import tempfile
from pathlib import Path

import bpy

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OUT = ROOT / "site" / "images" / "tutorials"
PLATE = Path(tempfile.gettempdir()) / "base-node-final-shot" / "plate.exr"
sys.path.insert(0, str(ROOT / "base-node-for-blender" / "tests"))
import test_libraries  # noqa: E402,F401  (loads the extension as `base_node`)

from base_node.host import build_source, export_tree  # noqa: E402

SAMPLES = 128
WIDTH, HEIGHT = 1000, 750
GRAPH = "final_shot"
# The lamp post's bulb, in the world: relight of step 3 puts its light there
BULB = (1.7, 1.2, 3.05)
# The light passes, noisy out of Cycles, denoised on the plate
DENOISED = {"Diffuse Direct", "Diffuse Indirect", "Glossy Direct", "Glossy Indirect",
            "Transmission Direct", "Transmission Indirect"}


def args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    only = argv[argv.index("--only") + 1] if "--only" in argv else None
    return only, "--fresh" in argv


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


def material(name, color, roughness, metallic=0.0, emission=None, strength=0.0):
    m = bpy.data.materials.new(name)
    bsdf = m.node_tree.nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = (*color, 1.0)
    bsdf.inputs["Roughness"].default_value = roughness
    bsdf.inputs["Metallic"].default_value = metallic
    if emission:
        bsdf.inputs["Emission Color"].default_value = (*emission, 1.0)
        bsdf.inputs["Emission Strength"].default_value = strength
    return m


def add(mesh, mat, location, scale=(1.0, 1.0, 1.0), rotation=(0.0, 0.0, 0.0), smooth=False, name="Object"):
    obj = bpy.data.objects.new(name, mesh)
    obj.location, obj.scale, obj.rotation_euler = location, scale, rotation
    mesh.materials.append(mat)
    if smooth:
        for poly in mesh.polygons:
            poly.use_smooth = True
    bpy.context.scene.collection.objects.link(obj)
    return obj


def primitive(op, **kw):
    """A mesh from one of bpy.ops.mesh's primitives, its object taken away."""
    op(**kw)
    obj = bpy.context.active_object
    mesh = obj.data
    bpy.data.objects.remove(obj)
    return mesh


def plate_scene():
    """The 3D scene: a square at dusk, and the passes the compositor rebuilds it from."""
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.name = "Scene"
    scene.render.engine = "CYCLES"
    use_gpu(scene)
    scene.cycles.samples = SAMPLES
    scene.cycles.use_denoising = True
    scene.render.resolution_x, scene.render.resolution_y = WIDTH, HEIGHT
    scene.view_settings.view_transform = "AgX"

    # Ground: a dark paving, a little glossy; a few things on it, a lamp post, street lamps away
    ground = material("Paving", (0.08, 0.075, 0.07), 0.35)
    concrete = material("Concrete", (0.5, 0.48, 0.45), 0.7)
    terracotta = material("Terracotta", (0.55, 0.2, 0.1), 0.45)
    wood = material("Wood", (0.42, 0.26, 0.13), 0.6)
    steel = material("Steel", (0.6, 0.6, 0.62), 0.25, metallic=1.0)
    paint = material("Paint", (0.07, 0.2, 0.26), 0.35)
    iron = material("Iron", (0.03, 0.03, 0.03), 0.5)
    block = material("Building", (0.2, 0.19, 0.18), 0.85)
    bulb = material("Bulb", (1.0, 0.8, 0.5), 0.3, emission=(1.0, 0.62, 0.3), strength=60.0)
    window = material("Window", (0.1, 0.1, 0.1), 0.3, emission=(1.0, 0.7, 0.4), strength=4.0)

    add(primitive(bpy.ops.mesh.primitive_plane_add, size=400), ground, (0, 0, 0), name="Ground")
    add(primitive(bpy.ops.mesh.primitive_uv_sphere_add, segments=96, ring_count=48), terracotta,
        (-1.2, 2.2, 0.9), scale=(0.9, 0.9, 0.9), smooth=True, name="Sphere")
    add(primitive(bpy.ops.mesh.primitive_cube_add), wood, (0.9, 3.4, 0.5), scale=(0.5, 0.5, 0.5),
        rotation=(0, 0, math.radians(20)), name="Crate")
    add(primitive(bpy.ops.mesh.primitive_cube_add), wood, (1.0, 3.35, 1.3), scale=(0.3, 0.3, 0.3),
        rotation=(0, 0, math.radians(-10)), name="Crate small")
    add(primitive(bpy.ops.mesh.primitive_cylinder_add, vertices=64), concrete, (-3.4, 5.5, 1.6),
        scale=(0.45, 0.45, 1.6), smooth=True, name="Pillar")
    add(primitive(bpy.ops.mesh.primitive_torus_add, major_radius=0.55, minor_radius=0.18,
                  major_segments=96, minor_segments=32), steel,
        (0.1, 1.0, 0.18), smooth=True, name="Ring")
    add(primitive(bpy.ops.mesh.primitive_cube_add), paint, (3.6, 6.0, 0.9), scale=(1.4, 0.6, 0.9),
        rotation=(0, 0, math.radians(-25)), name="Bench block")

    # The lamp post on the right, its light a point lamp in the bulb
    add(primitive(bpy.ops.mesh.primitive_cylinder_add, vertices=24), iron, (BULB[0], BULB[1], 1.5),
        scale=(0.05, 0.05, 1.5), smooth=True, name="Post")
    add(primitive(bpy.ops.mesh.primitive_uv_sphere_add, segments=32, ring_count=16), bulb, BULB,
        scale=(0.12, 0.12, 0.12), smooth=True, name="Bulb")
    lamp = bpy.data.lights.new("Lamp", "POINT")
    lamp.energy, lamp.color, lamp.shadow_soft_size = 300.0, (1.0, 0.62, 0.32), 0.12
    lamp_obj = bpy.data.objects.new("Lamp", lamp)
    lamp_obj.location = BULB
    scene.collection.objects.link(lamp_obj)
    lamp_obj.visible_camera = False

    # Street lamps along an avenue, going away to the right
    for i in range(10):
        y = 10.0 + i * 9.0
        x = 6.5 + i * 0.8
        add(primitive(bpy.ops.mesh.primitive_cylinder_add, vertices=16), iron, (x, y, 2.0),
            scale=(0.06, 0.06, 2.0), name=f"Street post {i}")
        add(primitive(bpy.ops.mesh.primitive_uv_sphere_add, segments=24, ring_count=12), bulb,
            (x, y, 4.05), scale=(0.15, 0.15, 0.15), smooth=True, name=f"Street bulb {i}")

    # Blocks of buildings on the horizon, a few lit windows
    blocks = ((-75, 230, 34, 30), (-28, 255, 40, 50), (18, 240, 26, 38), (62, 262, 44, 26), (110, 248, 34, 44))
    for i, (x, y, w, h) in enumerate(blocks):
        add(primitive(bpy.ops.mesh.primitive_cube_add), block, (x, y, h / 2), scale=(w / 2, 10, h / 2),
            name=f"Block {i}")
        for j in range(6):
            add(primitive(bpy.ops.mesh.primitive_plane_add, size=1.0), window,
                (x - w / 3 + (j * 7 % 3) * w / 3, y - 10.05, h * (0.2 + 0.12 * j)),
                scale=(3.0, 2.0, 1.0), rotation=(math.radians(90), 0, 0), name=f"Window {i}.{j}")

    # A low sun from the front left, out of the frame: long shadows across the square; the sky
    # texture of the same sun
    elevation, azimuth = math.radians(4.0), math.radians(55.0)
    sun = bpy.data.lights.new("Sun", "SUN")
    sun.energy, sun.color, sun.angle = 4.0, (1.0, 0.55, 0.3), math.radians(1.5)
    sun_obj = bpy.data.objects.new("Sun", sun)
    # Turned so that its light comes from +y and -x, toward the camera, down
    sun_obj.rotation_euler = (math.radians(90.0) - elevation, 0.0, math.radians(180.0) + azimuth)
    scene.collection.objects.link(sun_obj)
    world = bpy.data.worlds.new("Dusk")
    scene.world = world
    nodes = world.node_tree.nodes
    sky = nodes.new("ShaderNodeTexSky")
    sky.sky_type = "MULTIPLE_SCATTERING"
    sky.sun_elevation, sky.sun_rotation = elevation, math.radians(90.0) + azimuth
    sky.sun_disc = False
    nodes["Background"].inputs["Strength"].default_value = 0.07
    world.node_tree.links.new(sky.outputs["Color"], nodes["Background"].inputs["Color"])

    data = bpy.data.cameras.new("Camera")
    data.lens = 32
    cam = bpy.data.objects.new("Camera", data)
    cam.location = (0.2, -6.5, 0.9)
    cam.rotation_euler = (math.radians(91.0), 0.0, math.radians(-2.0))
    scene.collection.objects.link(cam)
    scene.camera = cam

    layer = scene.view_layers[0]
    for kind in ("diffuse", "glossy", "transmission"):
        for part in ("direct", "indirect", "color"):
            setattr(layer, f"use_pass_{kind}_{part}", True)
    for name in ("use_pass_emit", "use_pass_environment", "use_pass_z", "use_pass_normal", "use_pass_position"):
        setattr(layer, name, True)
    return scene


def render_plate(scene, fresh):
    if PLATE.exists() and not fresh and PLATE.stat().st_mtime > Path(__file__).stat().st_mtime:
        print(f"plate: {PLATE}, kept")
        return
    PLATE.parent.mkdir(parents=True, exist_ok=True)
    for old in PLATE.parent.glob("*.exr"):
        old.unlink()
    # Cycles denoises the Combined pass only: the light passes are denoised here, by the plate's
    # own compositor, and written with the others under the names Render Layers gives them, as a
    # render farm would deliver them
    tree = bpy.data.node_groups.new("Plate", "CompositorNodeTree")
    layers = tree.nodes.new("CompositorNodeRLayers")
    out = tree.nodes.new("CompositorNodeOutputFile")
    out.directory, out.file_name = str(PLATE.parent), PLATE.stem
    out.format.media_type = "MULTI_LAYER_IMAGE"
    out.format.file_format = "OPEN_EXR_MULTILAYER"
    out.format.color_depth = "32"
    out.format.exr_codec = "ZIP"
    for socket in layers.outputs:
        if not socket.enabled or socket.name == "Noisy Image":
            continue
        kind = {"VALUE": "FLOAT", "VECTOR": "VECTOR"}.get(socket.type, "RGBA")
        out.file_output_items.new(kind, socket.name)
        source = socket
        if socket.name in DENOISED:
            denoise = tree.nodes.new("CompositorNodeDenoise")
            tree.links.new(socket, denoise.inputs["Image"])
            source = denoise.outputs[0]
        tree.links.new(source, out.inputs[socket.name])
    scene.compositing_node_group = tree
    bpy.ops.render.render(write_still=False)
    written = sorted(PLATE.parent.glob("*.exr"))
    assert written, f"no plate written in {PLATE.parent}"
    written[0].rename(PLATE)
    scene.compositing_node_group = None
    print(f"plate: {PLATE}, rendered")


def from_plate(tree):
    """The tree with its Render Layers swapped for the plate: an Image node of the same passes."""
    image = bpy.data.images.get(PLATE.name) or bpy.data.images.load(str(PLATE))
    for node in [n for n in tree.nodes if n.bl_idname == "CompositorNodeRLayers"]:
        plate = tree.nodes.new("CompositorNodeImage")
        plate.image = image
        plate.location = node.location
        outputs = {o.name: o for o in plate.outputs}
        for link in [l for l in tree.links if l.from_node == node]:
            name = link.from_socket.name
            if name not in outputs:
                raise SystemExit(f"the plate has no pass {name!r}; it has {sorted(outputs)}")
            tree.links.new(outputs[name], link.to_socket)
        tree.nodes.remove(node)


def composite(tree, name):
    """Render the tree on the plate, in a scene with nothing to render."""
    comp = bpy.data.scenes.get("Composite")
    if comp is None:
        comp = bpy.data.scenes.new("Composite")
        comp.camera = bpy.data.objects.new("Composite camera", bpy.data.cameras.new("Composite camera"))
        comp.collection.objects.link(comp.camera)
    comp.render.engine = "CYCLES"
    comp.cycles.samples = 1
    comp.cycles.device = "CPU"
    comp.render.resolution_x, comp.render.resolution_y = WIDTH, HEIGHT
    comp.render.resolution_percentage = 100
    comp.render.image_settings.file_format = "PNG"
    comp.render.image_settings.color_mode = "RGB"
    comp.view_settings.view_transform = "AgX"
    comp.compositing_node_group = tree
    OUT.mkdir(parents=True, exist_ok=True)
    comp.render.filepath = str(OUT / f"final-shot-{name}.png")
    bpy.ops.render.render(write_still=True, scene=comp.name)
    print(f"rendered {comp.render.filepath}")


def build(path):
    """The step's graph, built in the plate's scene: its Render Layers has the plate's passes."""
    source = path.read_text(encoding="utf-8")
    groups = {g.name: g for g in build_source(source, filename=path.name)}
    return groups[GRAPH]


def before_after(first, last):
    """The first step on the left, the last on the right of 40 % of the width: the picture of the page's top."""
    tree = bpy.data.node_groups.new("before after", "CompositorNodeTree")
    tree.interface.new_socket("Image", in_out="OUTPUT", socket_type="NodeSocketColor")
    a = tree.nodes.new("CompositorNodeGroup")
    a.node_tree = first
    b = tree.nodes.new("CompositorNodeGroup")
    b.node_tree = last
    coords = tree.nodes.new("CompositorNodeImageCoordinates")
    tree.links.new(a.outputs[0], coords.inputs[0])
    xyz = tree.nodes.new("ShaderNodeSeparateXYZ")
    tree.links.new(coords.outputs["Normalized"], xyz.inputs[0])
    right = tree.nodes.new("ShaderNodeMath")
    right.operation = "GREATER_THAN"
    right.inputs[1].default_value = 0.4
    tree.links.new(xyz.outputs["X"], right.inputs[0])
    mix = tree.nodes.new("ShaderNodeMix")
    mix.data_type = "RGBA"
    tree.links.new(right.outputs[0], mix.inputs["Factor"])
    tree.links.new(a.outputs[0], mix.inputs["A"])
    tree.links.new(b.outputs[0], mix.inputs["B"])
    out = tree.nodes.new("NodeGroupOutput")
    tree.links.new(mix.outputs["Result"], out.inputs[0])
    return tree


def check_round_trip(path):
    """final_shot of the last step reads back to a text that builds the same group again."""
    plate_scene()
    tree = build(path)
    text, warnings = export_tree(tree)
    assert not warnings, warnings
    again, _ = export_tree(build_source(text, filename=f"{GRAPH}.bn")[-1])
    assert again == text, f"{GRAPH} does not read back the same"
    print(f"round trip {GRAPH}: ok")


def main():
    only, fresh = args()
    steps = sorted(HERE.glob("step*.bn"))
    render_plate(plate_scene(), fresh)
    built = {}
    for path in steps:
        step = path.stem.split("_")[0]
        if only and only not in (step, "hero"):
            continue
        tree = build(path)
        tree.name = f"{GRAPH} {step}"
        from_plate(tree)
        built[step] = tree
        if not only or only == step:
            composite(tree, step)
    if not only or only == "hero":
        first, last = steps[0].stem.split("_")[0], steps[-1].stem.split("_")[0]
        composite(before_after(built[first], built[last]), "hero")
    if not only or only == "round-trip":
        check_round_trip(steps[-1])


main()
