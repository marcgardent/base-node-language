"""Build examples/reaction_diffusion.bn in Blender, check its patterns, its round trip, time it, render it.

  blender -b --factory-startup --python-exit-code 1 --python examples/reaction_diffusion_check.py \
    [-- --no-render] [--no-timings]

1. The groups are saved in a .blend and go through the regression tests' round trip
   (tests/test_libraries.py): tree -> .bn -> tree gives the same text and the same geometry.
2. "reaction diffusion tile" on 128 x 128 vertices, 3000 steps, for each preset: U and V stay in
   [0, 1], V varies (a pattern, not a flat field), and the presets differ from one another.
3. The time of an evaluation for 128 and 256 vertices a side, 1000 and 5000 steps.
4. "growing reaction diffusion" (the Simulation zone) grows from frame to frame.
5. A still of 256 x 256 vertices after 5000 steps: site/images/showcase-reaction-diffusion.png.
"""

import math
import sys
import tempfile
import time
from pathlib import Path

import bpy
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "addon" / "tests"))
import test_libraries  # noqa: E402  (loads the extension as `base_node`)

import base_node  # noqa: E402

SOURCE = (ROOT / "examples" / "reaction_diffusion.bn").read_text(encoding="utf-8")
PRESETS = ("Spots", "Stripes", "Coral", "Mitosis")
# A still needs a material: the graph that renders sets one
SHOWCASE = """
geometry graph showcase(resolution: Int = 256, preset: Menu = Coral, iterations: Int = 5000) -> Geometry {
  return reaction_diffusion_tile(resolution, preset, iterations) |> SetMaterial(material: "Pattern")
}
"""


def set_input(mod, name, value):
    for item in mod.node_group.interface.items_tree:
        if item.item_type == "SOCKET" and item.in_out == "INPUT" and item.name == name:
            getattr(mod.properties.inputs, item.identifier).value = value
            return
    raise KeyError(name)


def new_object(group, material=None):
    mesh = bpy.data.meshes.new(group.name)
    if material:
        mesh.materials.append(material)
    obj = bpy.data.objects.new(group.name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    obj.modifiers.new("GN", "NODES").node_group = group
    return obj


def chemicals(obj):
    """(U, V, seconds) of the object's evaluated mesh."""
    obj.update_tag()
    start = time.perf_counter()
    ev = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
    mesh = ev.to_mesh()
    seconds = time.perf_counter() - start
    c = np.empty(len(mesh.vertices) * 3)
    mesh.attributes["gray scott"].data.foreach_get("vector", c)
    ev.to_mesh_clear()
    return c[0::3].copy(), c[1::3].copy(), seconds


def tile(obj, resolution, preset, iterations):
    mod = obj.modifiers[0]
    set_input(mod, "resolution", resolution)
    set_input(mod, "preset", preset)
    set_input(mod, "iterations", iterations)
    return chemicals(obj)


def check_round_trip():
    blend = Path(tempfile.mkdtemp()) / "reaction_diffusion.blend"
    bpy.data.libraries.write(str(blend), {g for g in bpy.data.node_groups})
    records, _ = test_libraries.round_trip(blend)
    for name, record in sorted(records.items()):
        print(f"round trip {name}: {record['status']}{' ' + str(record.get('on', '')) if 'on' in record else ''}")
    assert all(r["status"] == "ok" for r in records.values()), records
    # Every graph of the file is a group that went through the round trip: a missing record fails
    graphs = {g.name for g in base_node.lang.parse(SOURCE, "reaction_diffusion.bn").graphs}
    missing = graphs - set(records)
    assert not missing, f"no round trip for {sorted(missing)}"
    print(f"round trip: {len(graphs)} graphs of the file, {len(records)} records")


def check_patterns(obj):
    seen = {}
    for preset in PRESETS:
        u, v, seconds = tile(obj, 128, preset, 3000)
        print(f"{preset}: U [{u.min():.3f}, {u.max():.3f}], V [{v.min():.3f}, {v.max():.3f}], "
              f"V mean {v.mean():.4f}, V std {v.std():.4f}, V > 0.2 on {np.mean(v > 0.2):.1%} ({seconds:.2f} s)")
        seen[preset] = (u, v)
    for preset, (u, v) in seen.items():
        assert np.isfinite(u).all() and np.isfinite(v).all()
        assert u.min() >= -1e-6 and u.max() <= 1 + 1e-6 and v.min() >= -1e-6 and v.max() <= 1 + 1e-6, preset
        assert v.std() > 0.05, f"{preset}: no pattern"
        seen[preset] = v > 0.2
    for i, a in enumerate(PRESETS):
        for b in PRESETS[i + 1:]:
            differ = np.mean(seen[a] != seen[b])
            print(f"{a} / {b}: {differ:.1%} of the cells differ")
            assert differ > 0.1, f"{a} and {b} give the same pattern"


def check_simulation():
    obj = new_object(bpy.data.node_groups["growing reaction diffusion"])
    bm = bpy.data.meshes.new("grid")
    # The Grid node's vertex order: x then y
    n = 64
    xs = np.linspace(-1.0, 1.0, n)
    bm.vertices.add(n * n)
    bm.vertices.foreach_set("co", np.array([(x, y, 0.0) for x in xs for y in xs]).ravel())
    obj.data = bm
    scene = bpy.context.scene
    stats = []
    for frame in (1, 10, 20, 40):
        scene.frame_set(frame)
        u, v, _ = chemicals(obj)
        stats.append(v.std())
        print(f"simulation frame {frame}: V mean {v.mean():.4f}, V std {v.std():.4f}")
    assert stats[-1] > stats[0] and stats[-1] > 0.05, "the simulation does not grow"
    scene.frame_set(1)
    bpy.data.objects.remove(obj)


def timings(obj):
    for resolution in (128, 256):
        for iterations in (1000, 5000):
            seconds = tile(obj, resolution, "Coral", iterations)[2]
            print(f"time {resolution} x {resolution}, {iterations} steps: {seconds:.2f} s")


def pattern_material():
    """Deep blue where V is low, warm where it is high."""
    mat = bpy.data.materials.new("Pattern")
    nt = mat.node_tree
    bsdf = nt.nodes["Principled BSDF"]
    bsdf.inputs["Roughness"].default_value = 0.4
    attribute = nt.nodes.new("ShaderNodeAttribute")
    attribute.attribute_name = "v"
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    stops = ramp.color_ramp.elements
    stops[0].position, stops[0].color = 0.0, (0.02, 0.05, 0.16, 1.0)
    stops[1].position, stops[1].color = 0.35, (1.0, 0.55, 0.16, 1.0)
    middle = stops.new(0.15)
    middle.color = (0.10, 0.45, 0.60, 1.0)
    nt.links.new(attribute.outputs["Fac"], ramp.inputs["Fac"])
    nt.links.new(ramp.outputs["Color"], bsdf.inputs["Base Color"])
    return mat


def render(path):
    scene = bpy.context.scene
    material = pattern_material()
    base_node.host.build_source(SOURCE + SHOWCASE, "reaction_diffusion.bn")
    new_object(bpy.data.node_groups["showcase"], material)
    world = bpy.data.worlds.new("Sky")
    world.node_tree.nodes["Background"].inputs["Color"].default_value = (0.045, 0.052, 0.068, 1.0)
    scene.world = world
    sun = bpy.data.objects.new("Sun", bpy.data.lights.new("Sun", "SUN"))
    sun.data.energy = 4.0
    sun.rotation_euler = (math.radians(50), 0.0, math.radians(-35))
    scene.collection.objects.link(sun)
    camera = bpy.data.objects.new("Camera", bpy.data.cameras.new("Camera"))
    camera.location = (0.0, -5.0, 3.6)
    camera.rotation_euler = (math.radians(55), 0.0, 0.0)
    camera.data.lens = 40
    scene.collection.objects.link(camera)
    scene.camera = camera
    scene.render.engine = "BLENDER_EEVEE"
    scene.render.resolution_x, scene.render.resolution_y = 960, 640
    scene.view_settings.view_transform = "AgX"
    scene.render.filepath = str(path)
    bpy.ops.render.render(write_still=True)
    print(f"rendered {path}")


def main():
    args = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    bpy.ops.wm.read_factory_settings(use_empty=True)
    base_node.register()
    base_node.host.build_source(SOURCE, "reaction_diffusion.bn")
    if "--no-round-trip" not in args:
        check_round_trip()  # it clears the groups and the objects: built again below
    base_node.host.build_source(SOURCE, "reaction_diffusion.bn")
    obj = new_object(bpy.data.node_groups["reaction diffusion tile"])
    check_patterns(obj)
    if "--no-timings" not in args:
        timings(obj)
    bpy.data.objects.remove(obj)
    check_simulation()
    if "--no-render" not in args:
        render(ROOT / "site" / "images" / "showcase-reaction-diffusion.png")


main()
