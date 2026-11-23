"""Render the three plates of the promo cut tutorial once, then cut each step from them, as animations.

  blender -b --factory-startup --python-exit-code 1 --python examples/tutorials/promo_cut/render.py
  blender -b --factory-startup --python-exit-code 1 --python examples/tutorials/promo_cut/render.py -- --only step3
  blender -b --factory-startup --python-exit-code 1 --python examples/tutorials/promo_cut/render.py -- --fresh

The plates are three shots of a product launch: an orb on a podium between a magenta and a cyan
light, golden hills with two hot-air balloons, and the title, SUMMER DROP, in glossy letters on a
transparent background. Cycles renders each one once, to site/images/tutorials/promo-cut-plate-*.png,
the files the page gives to download; they are rendered again when this script is newer than them,
or with --fresh.

Every step*.bn of this folder is then built, with those images loaded under their file names, the
names its Image nodes read. Its promo_cut graph is the compositor of an empty scene, rendered frame
by frame into the temp folder and encoded as a looping animated WebP,
site/images/tutorials/promo-cut-<step>.webp: no step renders a 3D scene. A step whose file has a
graph with a progress input (step 1) is animated by that progress, fed by a Value node from 0 to 1
and back, as the scene's compositor feeds a group nothing but its image; the others by the frame.
A step that does not build stops the script. The last step's animation is also the page's top, and
four of its frames side by side are promo-cut-step8-frames.webp. Then the graph of the last step is
read back to its text and built again.
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
FRAMES_DIR = Path(tempfile.gettempdir()) / "base-node-promo-cut"
sys.path.insert(0, str(ROOT / "base-node-for-blender" / "tests"))
import test_libraries  # noqa: E402,F401  (loads the extension as `base_node`)

from base_node.host import build_source, export_tree  # noqa: E402

SAMPLES = 128
WIDTH, HEIGHT = 640, 427
FPS = 24
GRAPH = "promo_cut"
# The frames of each step's animation: one loop
FRAMES = {"step1": 48, "step2": 48, "step3": 72, "step4": 72, "step5": 72, "step6": 48, "step7": 48,
          "step8": 96}
# The frames of the last step shown side by side
STILLS = (10, 34, 58, 84)


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


def material(name, color, roughness, metallic=0.0, emission=None, strength=0.0, coat=0.0):
    m = bpy.data.materials.new(name)
    bsdf = m.node_tree.nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = (*color, 1.0)
    bsdf.inputs["Roughness"].default_value = roughness
    bsdf.inputs["Metallic"].default_value = metallic
    bsdf.inputs["Coat Weight"].default_value = coat
    if emission:
        bsdf.inputs["Emission Color"].default_value = (*emission, 1.0)
        bsdf.inputs["Emission Strength"].default_value = strength
    return m


def emitter(name, color, strength):
    m = bpy.data.materials.new(name)
    nodes = m.node_tree.nodes
    nodes.clear()
    emission = nodes.new("ShaderNodeEmission")
    emission.inputs["Color"].default_value = (*color, 1.0)
    emission.inputs["Strength"].default_value = strength
    out = nodes.new("ShaderNodeOutputMaterial")
    m.node_tree.links.new(emission.outputs[0], out.inputs[0])
    return m


def add(op, mat, smooth=False, **kw):
    op(**kw)
    obj = bpy.context.active_object
    obj.data.materials.append(mat)
    if smooth:
        bpy.ops.object.shade_smooth()
    return obj


def light(scene, kind, location, target, color, energy, size=1.0):
    data = bpy.data.lights.new(f"{kind} light", kind)
    data.color, data.energy = color, energy
    if kind == "AREA":
        data.size = size
    obj = bpy.data.objects.new(data.name, data)
    obj.location = location
    aim(obj, target)
    scene.collection.objects.link(obj)
    return obj


def aim(obj, target):
    obj.rotation_euler = (Vector(target) - Vector(obj.location)).to_track_quat("-Z", "Y").to_euler()


def camera(scene, location, target, lens):
    data = bpy.data.cameras.new("Camera")
    data.lens = lens
    cam = bpy.data.objects.new("Camera", data)
    cam.location = location
    aim(cam, target)
    scene.collection.objects.link(cam)
    scene.camera = cam


def new_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    use_gpu(scene)
    scene.cycles.samples = SAMPLES
    scene.cycles.use_denoising = True
    scene.render.resolution_x, scene.render.resolution_y = WIDTH, HEIGHT
    scene.render.resolution_percentage = 100
    scene.view_settings.view_transform = "AgX"
    scene.view_settings.look = "AgX - Medium High Contrast"
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGB"
    return scene


def world(scene, color):
    w = bpy.data.worlds.new("World")
    w.node_tree.nodes["Background"].inputs["Color"].default_value = (*color, 1.0)
    scene.world = w


def plate_a():
    """The product: an orb in a ring, on a podium, between a magenta and a cyan light, a neon ring behind."""
    scene = new_scene()
    world(scene, (0.004, 0.002, 0.008))
    add(bpy.ops.mesh.primitive_plane_add, material("Floor", (0.02, 0.018, 0.025), 0.18), size=60)
    add(bpy.ops.mesh.primitive_cylinder_add, material("Podium", (0.55, 0.53, 0.6), 0.35), smooth=True,
        vertices=128, radius=1.3, depth=0.6, location=(0, 0, 0.3))
    add(bpy.ops.mesh.primitive_cylinder_add, material("Step", (0.12, 0.1, 0.16), 0.3), smooth=True,
        vertices=128, radius=1.8, depth=0.12, location=(0, 0, 0.06))
    add(bpy.ops.mesh.primitive_uv_sphere_add, material("Orb", (0.9, 0.16, 0.08), 0.3, coat=1.0),
        smooth=True, segments=128, ring_count=64, radius=0.75, location=(0, 0, 1.45))
    add(bpy.ops.mesh.primitive_torus_add, material("Chrome", (0.9, 0.9, 0.95), 0.08, metallic=1.0),
        smooth=True, major_radius=1.15, minor_radius=0.05, major_segments=160, minor_segments=24,
        location=(0, 0, 1.45), rotation=(math.radians(72), math.radians(-18), 0))
    add(bpy.ops.mesh.primitive_torus_add, emitter("Neon", (1.0, 0.1, 0.6), 4.0), smooth=True,
        major_radius=2.6, minor_radius=0.045, major_segments=160, minor_segments=16,
        location=(0, 3.5, 2.0), rotation=(math.radians(90), 0, 0))
    add(bpy.ops.mesh.primitive_torus_add, emitter("Neon blue", (0.05, 0.45, 1.0), 4.0), smooth=True,
        major_radius=3.3, minor_radius=0.03, major_segments=160, minor_segments=16,
        location=(0, 4.5, 2.0), rotation=(math.radians(90), 0, 0))
    light(scene, "AREA", (-3.5, -1.0, 2.6), (0, 0, 1.2), (1.0, 0.1, 0.6), 400, 2.0)
    light(scene, "AREA", (3.5, -0.5, 2.2), (0, 0, 1.2), (0.1, 0.65, 1.0), 400, 2.0)
    light(scene, "AREA", (0.5, -3.0, 5.0), (0, 0, 1.0), (1.0, 0.9, 0.8), 120, 3.0)
    camera(scene, (0.0, -7.2, 1.9), (0.0, 0.0, 1.35), 42)
    return scene


def plate_b():
    """Lifestyle: rolling hills at golden hour, a few trees, two hot-air balloons against the sun."""
    scene = new_scene()
    hills = add(bpy.ops.mesh.primitive_grid_add, material("Grass", (0.32, 0.42, 0.08), 0.8), smooth=True,
                x_subdivisions=400, y_subdivisions=400, size=400)
    tex = bpy.data.textures.new("Hills", "CLOUDS")
    tex.noise_scale, tex.noise_depth = 9.0, 1
    mod = hills.modifiers.new("Hills", "DISPLACE")
    mod.texture, mod.strength, mod.mid_level = tex, 5.0, 0.5
    bpy.context.view_layer.update()
    depsgraph = bpy.context.evaluated_depsgraph_get()

    def ground(x, y):
        hit, where, *_ = scene.ray_cast(depsgraph, (x, y, 50.0), (0, 0, -1))
        return where.z if hit else 0.0

    leaves = material("Leaves", (0.05, 0.16, 0.04), 0.7)
    bark = material("Bark", (0.15, 0.08, 0.04), 0.8)
    for i, (x, y, s) in enumerate(((-6, 6, 1.2), (-4.5, 9, 0.9), (5, 7, 1.1), (7, 13, 1.0), (-9, 16, 1.3),
                                   (2.5, 18, 0.9), (11, 20, 1.2), (-2, 12, 0.7), (-13, 24, 1.1))):
        z = ground(x, y)
        add(bpy.ops.mesh.primitive_cylinder_add, bark, vertices=12, radius=0.12 * s, depth=1.0 * s,
            location=(x, y, z + 0.5 * s))
        add(bpy.ops.mesh.primitive_cone_add, leaves, smooth=True, vertices=24, radius1=0.9 * s,
            depth=2.6 * s, location=(x, y, z + 2.2 * s))
    wicker = material("Wicker", (0.3, 0.17, 0.07), 0.8)
    for x, y, z, r, color in ((-3.5, 22, 7.5, 1.6, (0.85, 0.12, 0.08)), (6.0, 34, 11.0, 1.9, (0.95, 0.65, 0.05))):
        envelope = add(bpy.ops.mesh.primitive_uv_sphere_add, material("Balloon", color, 0.5), smooth=True,
                       segments=48, ring_count=24, radius=r, location=(x, y, z))
        envelope.scale = (1.0, 1.0, 1.2)
        add(bpy.ops.mesh.primitive_cube_add, wicker, size=r * 0.35, location=(x, y, z - r * 1.55))
    sun_elevation, sun_azimuth = math.radians(5.0), math.radians(20.0)
    sun = bpy.data.lights.new("Sun", "SUN")
    sun.energy, sun.color, sun.angle = 4.5, (1.0, 0.6, 0.3), math.radians(2.0)
    sun_obj = bpy.data.objects.new("Sun", sun)
    sun_obj.rotation_euler = (math.radians(90.0) - sun_elevation, 0.0, math.radians(180.0) + sun_azimuth)
    scene.collection.objects.link(sun_obj)
    w = bpy.data.worlds.new("Golden hour")
    scene.world = w
    nodes = w.node_tree.nodes
    sky = nodes.new("ShaderNodeTexSky")
    sky.sky_type = "MULTIPLE_SCATTERING"
    sky.sun_elevation, sky.sun_rotation = sun_elevation, math.radians(90.0) + sun_azimuth
    sky.sun_disc = True
    nodes["Background"].inputs["Strength"].default_value = 0.12
    w.node_tree.links.new(sky.outputs["Color"], nodes["Background"].inputs["Color"])
    eye = (1.0, -8.0, ground(1.0, -8.0) + 2.2)
    camera(scene, eye, (-1.0, 30.0, eye[2] + 3.0), 35)
    return scene


def plate_c():
    """The title: SUMMER DROP in glossy letters, orange to pink, on a transparent background."""
    scene = new_scene()
    scene.render.film_transparent = True
    scene.render.image_settings.color_mode = "RGBA"
    world(scene, (0.05, 0.03, 0.08))
    bpy.ops.object.text_add(location=(0, 0, 0), rotation=(math.radians(90), 0, 0))
    text = bpy.context.active_object
    text.data.body = "SUMMER\nDROP"
    text.data.align_x, text.data.align_y = "CENTER", "CENTER"
    text.data.extrude, text.data.bevel_depth, text.data.bevel_resolution = 0.14, 0.025, 3
    text.data.space_line = 0.85
    text.data.size = 1.5
    m = bpy.data.materials.new("Letters")
    nodes, links = m.node_tree.nodes, m.node_tree.links
    bsdf = nodes["Principled BSDF"]
    bsdf.inputs["Roughness"].default_value = 0.22
    bsdf.inputs["Coat Weight"].default_value = 1.0
    coords = nodes.new("ShaderNodeTexCoord")
    gradient = nodes.new("ShaderNodeTexGradient")
    ramp = nodes.new("ShaderNodeValToRGB")
    ramp.color_ramp.elements[0].color = (1.0, 0.42, 0.02, 1.0)
    ramp.color_ramp.elements[1].color = (0.95, 0.05, 0.45, 1.0)
    links.new(coords.outputs["Generated"], gradient.inputs["Vector"])
    links.new(gradient.outputs["Fac"], ramp.inputs["Fac"])
    links.new(ramp.outputs["Color"], bsdf.inputs["Base Color"])
    text.data.materials.append(m)
    light(scene, "AREA", (-2.5, -6.0, 4.0), (0, 0, 0), (1.0, 0.95, 0.9), 700, 4.0)
    light(scene, "AREA", (5.0, -2.0, -2.5), (0, 0, 0), (0.2, 0.6, 1.0), 500, 3.0)
    light(scene, "AREA", (0.0, 3.0, 3.0), (0, 0, 0), (1.0, 0.3, 0.8), 400, 3.0)
    camera(scene, (0.6, -9.0, -0.6), (0.0, 0.0, 0.0), 50)
    return scene


PLATES = {"a": plate_a, "b": plate_b, "c": plate_c}


def plate_path(name):
    return OUT / f"promo-cut-plate-{name}.png"


def render_plates(fresh):
    OUT.mkdir(parents=True, exist_ok=True)
    for name, setup in PLATES.items():
        path = plate_path(name)
        if path.exists() and not fresh and path.stat().st_mtime > Path(__file__).stat().st_mtime:
            print(f"plate {name}: {path}, kept")
            continue
        scene = setup()
        scene.render.filepath = str(path)
        bpy.ops.render.render(write_still=True)
        print(f"plate {name}: {path}, rendered")


def load_plates():
    """A fresh file with the plates loaded, each under its file name: the names the steps read."""
    bpy.ops.wm.read_factory_settings(use_empty=True)
    for name in PLATES:
        bpy.data.images.load(str(plate_path(name)))


def comp_scene():
    """A scene with nothing to render, its compositor the step's graph, shown as the plates were."""
    # The file's own scene: the compositor's Scene Time reads the frame of the context's scene
    comp = bpy.context.scene
    if comp.camera is None:
        comp.camera = bpy.data.objects.new("Composite camera", bpy.data.cameras.new("Composite camera"))
        comp.collection.objects.link(comp.camera)
    comp.render.engine = "CYCLES"
    comp.cycles.samples = 1
    comp.cycles.device = "CPU"
    comp.render.resolution_x, comp.render.resolution_y = WIDTH, HEIGHT
    comp.render.resolution_percentage = 100
    comp.render.fps = FPS
    comp.render.image_settings.file_format = "PNG"
    comp.render.image_settings.color_mode = "RGB"
    # The plates are pictures already viewed: shown as they are, not viewed again
    comp.view_settings.view_transform = "Standard"
    comp.view_settings.look = "None"
    return comp


def progress_input(tree):
    return next((item for item in tree.interface.items_tree if item.item_type == "SOCKET"
                 and item.in_out == "INPUT" and item.name == "progress"), None)


def by_progress(tree):
    """A tree that gives the group its progress from a Value node, and the Value node."""
    wrapper = bpy.data.node_groups.new(f"{tree.name} at progress", "CompositorNodeTree")
    wrapper.interface.new_socket("Image", in_out="OUTPUT", socket_type="NodeSocketColor")
    group = wrapper.nodes.new("CompositorNodeGroup")
    group.node_tree = tree
    value = wrapper.nodes.new("ShaderNodeValue")
    wrapper.links.new(value.outputs[0], group.inputs["progress"])
    wrapper.links.new(group.outputs[0], wrapper.nodes.new("NodeGroupOutput").inputs[0])
    return wrapper, value


def build(path):
    """The step's graphs, by name, built with the plates loaded."""
    source = path.read_text(encoding="utf-8")
    return {g.name: g for g in build_source(source, filename=path.name)}


def animate(step, groups):
    """The step's frames into the temp folder, encoded as site/images/tutorials/promo-cut-<step>.webp."""
    comp = comp_scene()
    frames = FRAMES[step]
    driven = [g for g in groups.values() if progress_input(g)]
    value = None
    if driven:
        tree, value = by_progress(driven[0])
    else:
        tree = groups[GRAPH]
    comp.compositing_node_group = tree
    comp.frame_start, comp.frame_end = 1, frames
    folder = FRAMES_DIR / step
    shutil.rmtree(folder, ignore_errors=True)
    folder.mkdir(parents=True)
    for i in range(frames):
        comp.frame_set(i + 1)
        if value is not None:
            # 0 to 1 and back, eased, held a few frames at each end
            t = min(max((1.0 - abs(1.0 - 2.0 * i / frames) - 0.1) / 0.8, 0.0), 1.0)
            value.outputs[0].default_value = t * t * (3.0 - 2.0 * t)
        comp.render.filepath = str(folder / f"frame_{i + 1:04d}.png")
        bpy.ops.render.render(write_still=True, scene=comp.name)
    out = OUT / f"promo-cut-{step}.webp"
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(FPS), "-i", str(folder / "frame_%04d.png"),
         "-c:v", "libwebp_anim", "-lossless", "0", "-q:v", "75", "-compression_level", "6",
         "-loop", "0", "-pix_fmt", "yuv420p", str(out)],
        check=True)
    print(f"encoded {out}, {frames} frames, {out.stat().st_size} bytes")
    return folder


def stills(folder, step):
    """Four frames of the last step side by side, two by two."""
    out = OUT / f"promo-cut-{step}-frames.webp"
    inputs = []
    for f in STILLS:
        inputs += ["-i", str(folder / f"frame_{f:04d}.png")]
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", *inputs, "-filter_complex",
         "[0][1]hstack=2[top];[2][3]hstack=2[bottom];[top][bottom]vstack=2",
         "-c:v", "libwebp", "-q:v", "85", str(out)],
        check=True)
    print(f"wrote {out}")


def check_round_trip(path):
    """promo_cut of the last step reads back to a text that builds the same group again."""
    tree = build(path)[GRAPH]
    text, warnings = export_tree(tree)
    assert not warnings, warnings
    again, _ = export_tree(build_source(text, filename=f"{GRAPH}.bn")[-1])
    assert again == text, f"{GRAPH} does not read back the same"
    print(f"round trip {GRAPH}: ok")


def main():
    only, fresh = args()
    steps = sorted(HERE.glob("step*.bn"))
    render_plates(fresh)
    load_plates()
    for path in steps:
        step = path.stem.split("_")[0]
        groups = build(path)
        if only and only != step:
            continue
        folder = animate(step, groups)
        if path == steps[-1]:
            stills(folder, step)
    if not only or only == "round-trip":
        check_round_trip(steps[-1])


main()
