"""Render the compositor showcases of the standard library into site/images.

Each showcase is an examples/<module>_showcase.bn whose last graph is a compositor graph: it
becomes the scene's compositor, the scene is rendered by Cycles at 640×360 and saved as
site/images/<module>.png. The showcases are found by that pattern, none listed here.

    blender --background --factory-startup --python examples/render_compositor_showcases.py [-- name ...]

With names (mask2d, merge, grade, …: the <module> of the file), only those are rendered.
A name's underscores are hyphens in its picture's name; `// @showcase scene=… size=WxH` in the head
of a showcase gives it another scene or size.

    blender --background --factory-startup --python examples/render_compositor_showcases.py -- --webp transitions [--frames 96]

renders the last compositor graph of that showcase with a `phase` input as a looping animated WebP,
site/images/<name>.webp, at 640×427 (3:2, the size of a showcase card): its phase from 0 to 1 over
the frames.
"""

from __future__ import annotations

import importlib.util
import math
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXT = ROOT / "base-node-for-blender"
_spec = importlib.util.spec_from_file_location("base_node", EXT / "__init__.py", submodule_search_locations=[str(EXT)])
base_node = importlib.util.module_from_spec(_spec)
sys.modules["base_node"] = base_node
_spec.loader.exec_module(base_node)

import bpy  # noqa: E402
from base_node.lang import parse  # noqa: E402
from base_node.lang.header import directives  # noqa: E402
from mathutils import Vector  # noqa: E402

W, H = 640, 360


def empty_scene(scene):
    """Nothing to render: the showcase draws everything."""


def passes_scene(scene):
    """Three objects on a floor, under a sun and a sky, with the passes that rebuild the beauty."""
    def material(name, color, roughness, metallic=0.0):
        m = bpy.data.materials.new(name)
        bsdf = m.node_tree.nodes["Principled BSDF"]
        bsdf.inputs["Base Color"].default_value = color
        bsdf.inputs["Roughness"].default_value = roughness
        bsdf.inputs["Metallic"].default_value = metallic
        return m

    def add(op, mat, **kw):
        op(**kw)
        o = bpy.context.active_object
        o.data.materials.append(mat)
        return o

    add(bpy.ops.mesh.primitive_plane_add, material("floor", (0.55, 0.52, 0.48, 1), 0.6), size=30)
    s = add(bpy.ops.mesh.primitive_uv_sphere_add, material("red", (0.8, 0.12, 0.08, 1), 0.25),
            radius=1.0, location=(-2.2, 0.0, 1.0), segments=64, ring_count=32)
    bpy.ops.object.shade_smooth()
    add(bpy.ops.mesh.primitive_cube_add, material("blue", (0.1, 0.3, 0.8, 1), 0.5),
        size=1.6, location=(0.4, 1.2, 0.8), rotation=(0, 0, 0.5))
    t = add(bpy.ops.mesh.primitive_torus_add, material("gold", (0.9, 0.65, 0.25, 1), 0.2, 1.0),
            location=(2.6, -0.6, 0.35), major_radius=0.9, minor_radius=0.35)
    bpy.ops.object.shade_smooth()
    del s, t

    sun = bpy.data.objects.new("sun", bpy.data.lights.new("sun", "SUN"))
    sun.data.energy, sun.data.angle = 3.0, math.radians(4)
    sun.rotation_euler = (math.radians(50), 0, math.radians(30))
    scene.collection.objects.link(sun)
    world = bpy.data.worlds.new("sky")
    world.color = (0.25, 0.32, 0.45)
    scene.world = world

    camera = bpy.data.objects.new("camera", bpy.data.cameras.new("camera"))
    camera.location = (0.0, -9.0, 3.6)
    camera.rotation_euler = (math.radians(74), 0, 0)
    scene.collection.objects.link(camera)
    scene.camera = camera
    scene.cycles.samples = 64

    layer = scene.view_layers[0]
    for kind in ("diffuse", "glossy", "transmission"):
        for part in ("direct", "indirect", "color"):
            setattr(layer, f"use_pass_{kind}_{part}", True)
    for p in ("use_pass_emit", "use_pass_environment", "use_pass_z", "use_pass_normal", "use_pass_position"):
        setattr(layer, p, True)


def light_scene(scene):
    """The scene of the passes showcase with emissive balls and a glowing ring among its objects."""
    passes_scene(scene)

    def emitter(name, color, strength):
        m = bpy.data.materials.new(name)
        m.use_nodes = True
        nodes = m.node_tree.nodes
        nodes.clear()
        emission = nodes.new("ShaderNodeEmission")
        emission.inputs["Color"].default_value = color
        emission.inputs["Strength"].default_value = strength
        output = nodes.new("ShaderNodeOutputMaterial")
        m.node_tree.links.new(emission.outputs[0], output.inputs[0])
        return m

    # Lamps placed by where they show: x and y across the frame from 0 to 1, at a distance from the camera
    bpy.context.view_layer.update()
    camera = scene.camera
    half = math.tan(camera.data.angle / 2)
    lamps = ((0.2, 0.82, 6.0, (1.0, 0.75, 0.4, 1)), (0.47, 0.6, 6.5, (0.5, 0.8, 1.0, 1)),
             (0.88, 0.84, 7.0, (1.0, 0.4, 0.7, 1)), (0.13, 0.3, 5.0, (0.7, 1.0, 0.6, 1)),
             (0.43, 0.38, 5.5, (1.0, 0.85, 0.6, 1)), (0.93, 0.33, 6.0, (0.6, 0.7, 1.0, 1)))
    for i, (u, v, d, color) in enumerate(lamps):
        ray = Vector(((u - 0.5) * 2 * half, (v - 0.5) * 2 * half * H / W, -1.0)) * d
        bpy.ops.mesh.primitive_uv_sphere_add(radius=0.07, location=camera.matrix_world @ ray)
        bpy.context.active_object.data.materials.append(emitter(f"lamp {i}", color, 20.0))
    bpy.ops.mesh.primitive_torus_add(location=(0.4, 1.2, 2.0), major_radius=0.7, minor_radius=0.04,
                                     rotation=(math.radians(70), 0, 0))
    bpy.context.active_object.data.materials.append(emitter("ring", (1.0, 0.85, 0.6, 1), 6.0))


def panorama_scene(scene):
    """The scene of the passes showcase seen all around: an equirectangular camera among its objects, at 2:1."""
    passes_scene(scene)
    camera = scene.camera
    camera.data.type = "PANO"
    camera.data.panorama_type = "EQUIRECTANGULAR"
    camera.location = (0.0, -2.6, 1.2)
    camera.rotation_euler = (math.radians(90), 0, 0)
    scene.render.resolution_y = W // 2
    world = bpy.data.worlds.new("sky texture")
    world.use_nodes = True
    nodes = world.node_tree.nodes
    sky = nodes.new("ShaderNodeTexSky")
    sky.sun_elevation, sky.sun_rotation, sky.sun_disc = math.radians(25), math.radians(150), False
    nodes["Background"].inputs["Strength"].default_value = 0.04
    world.node_tree.links.new(sky.outputs["Color"], nodes["Background"].inputs["Color"])
    scene.world = world


SCENES = {"empty": empty_scene, "passes": passes_scene, "light": light_scene, "panorama": panorama_scene}


def showcases():
    """{name: (file, scene, (width, height))} of every examples/<name>_showcase.bn whose last graph
    is a compositor graph, by name. A line `// @showcase scene=passes size=1024x512` of its head
    chooses its scene (SCENES, default empty) and its size (default W × H): adding a showcase edits
    nothing here."""
    found = {}
    for path in sorted((ROOT / "examples").glob("*_showcase.bn")):
        source = path.read_text(encoding="utf-8")
        graphs = parse(source, path.name).graphs
        if not graphs or graphs[-1].kind != "compositor":
            continue
        say = dict(word.split("=", 1) for _name, value, _line, _col in directives(source)
                   if _name == "showcase" for word in value.split())
        size = tuple(int(n) for n in say.get("size", f"{W}x{H}").split("x"))
        found[path.stem.removesuffix("_showcase")] = (path.name, SCENES[say.get("scene", "empty")], size)
    return found


def render(name, showcase, frames=0):
    """Its picture, or with frames its animated WebP by the phase of its reel."""
    filename, setup, (width, height) = showcase
    if frames:
        width, height = 640, 427
    bpy.ops.wm.read_factory_settings(use_empty=True)
    base_node.register()
    from base_node.host import build_source

    scene = bpy.context.scene
    scene.name = "Scene"
    scene.render.engine = "CYCLES"
    scene.cycles.samples, scene.cycles.device = 1, "CPU"
    scene.render.resolution_x, scene.render.resolution_y, scene.render.resolution_percentage = width, height, 100
    scene.render.image_settings.file_format = "PNG"
    scene.view_settings.view_transform = "Standard"
    setup(scene)
    if scene.camera is None:
        camera = bpy.data.objects.new("camera", bpy.data.cameras.new("camera"))
        scene.collection.objects.link(camera)
        scene.camera = camera

    path = ROOT / "examples" / filename
    trees = build_source(path.read_text(encoding="utf-8"), str(path))
    image = name.replace("_", "-")
    if frames:
        animate(scene, trees, image, frames)
    else:
        scene.compositing_node_group = trees[-1]
        scene.render.filepath = str(ROOT / "site" / "images" / f"{image}.png")
        bpy.ops.render.render(write_still=True)
        print(f"rendered {filename} -> site/images/{image}.png")
    base_node.unregister()


def phase_input(tree):
    return next((item for item in tree.interface.items_tree if item.item_type == "SOCKET"
                 and item.in_out == "INPUT" and item.name == "phase"), None)


def use_gpu(scene):
    """Cycles on the GPU when there is one: many frames to render."""
    cycles = bpy.context.preferences.addons["cycles"].preferences
    for kind in ("OPTIX", "CUDA", "HIP", "METAL", "ONEAPI"):
        try:
            cycles.compute_device_type = kind
        except TypeError:
            continue
        cycles.get_devices()
        gpus = [d for d in cycles.devices if d.type == kind]
        if gpus:
            for d in cycles.devices:
                d.use = d.type == kind
            scene.cycles.device = "GPU"
            return


def animate(scene, trees, image, frames):
    """The last tree with a phase input, its phase from 0 to 1 over the frames, as site/images/<image>.webp."""
    reel = [t for t in trees if t.bl_idname == "CompositorNodeTree" and phase_input(t)]
    if not reel:
        sys.exit(f"no compositor graph with a phase input in {image}")
    # The scene's compositor feeds a group its image alone: the phase comes from a Value node
    wrapper = bpy.data.node_groups.new("reel at phase", "CompositorNodeTree")
    wrapper.interface.new_socket("Image", in_out="INPUT", socket_type="NodeSocketColor")
    wrapper.interface.new_socket("Image", in_out="OUTPUT", socket_type="NodeSocketColor")
    group = wrapper.nodes.new("CompositorNodeGroup")
    group.node_tree = reel[-1]
    value = wrapper.nodes.new("ShaderNodeValue")
    wrapper.links.new(wrapper.nodes.new("NodeGroupInput").outputs[0], group.inputs[0])
    wrapper.links.new(value.outputs[0], group.inputs["phase"])
    wrapper.links.new(group.outputs[0], wrapper.nodes.new("NodeGroupOutput").inputs[0])
    scene.compositing_node_group = wrapper
    # 3:2 shows more above and below than 16:9: back the camera a little and look down a little more
    scene.camera.location.y -= 1.2
    scene.camera.rotation_euler.x -= math.radians(4)
    use_gpu(scene)
    tmp = Path("/tmp") / f"bn_webp_{image}"
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    for i in range(frames):
        value.outputs[0].default_value = i / frames
        scene.render.filepath = str(tmp / f"frame_{i:04d}.png")
        bpy.ops.render.render(write_still=True)
    out = ROOT / "site" / "images" / f"{image}.webp"
    subprocess.run(["python3", "-I", str(ROOT / "examples" / "encode_webp.py"), str(tmp), str(out)], check=True)
    print(f"encoded site/images/{image}.webp, {frames} frames, {out.stat().st_size} bytes")


def main():
    found = showcases()
    args = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    if "--webp" in args:
        frames = int(args[args.index("--frames") + 1]) if "--frames" in args else 96
        render(args[args.index("--webp") + 1], found[args[args.index("--webp") + 1]], frames)
        return
    for name in args or list(found):
        render(name, found[name])


if __name__ == "__main__":
    main()
