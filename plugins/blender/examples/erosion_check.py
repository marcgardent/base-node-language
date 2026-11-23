"""Build examples/erosion.bn in Blender, check that it erodes, that it round-trips, time it, render it.

  blender -b --factory-startup --python-exit-code 1 --python examples/erosion_check.py [-- --no-render]

1. The graphs are built into node groups, and "eroded hills" evaluated on 128 x 128 vertices with no
   iteration and with 50: the heights must change, the volume of ground plus sediment must stay.
2. The groups are saved in a .blend and go through the regression tests' round trip
   (tests/test_libraries.py): tree -> .bn -> tree gives the same text and the same geometry.
3. The time of an evaluation, for 128 and 256 vertices a side, 50 and 200 iterations.
4. A still of 256 x 256 vertices after 200 iterations: site/images/showcase-erosion.png.
"""

import math
import sys
import tempfile
import time
from pathlib import Path

import bpy
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "base-node-for-blender" / "tests"))
import test_libraries  # noqa: E402  (loads the extension as `base_node`)

import base_node  # noqa: E402

SOURCE = (ROOT / "examples" / "erosion.bn").read_text(encoding="utf-8")
# A still needs a material: the graph that renders sets one
SHOWCASE = """
geometry graph showcase(resolution: Int = 256, iterations: Int = 200) -> Geometry {
  return eroded_hills(resolution: resolution, iterations: iterations) |> SetMaterial(material: "Eroded")
}
"""


def set_input(mod, name, value):
    for item in mod.node_group.interface.items_tree:
        if item.item_type == "SOCKET" and item.in_out == "INPUT" and item.name == name:
            getattr(mod.properties.inputs, item.identifier).value = value


def evaluate(obj, resolution, iterations):
    """(heights, sediment, seconds) of the object's evaluated mesh."""
    mod = obj.modifiers[0]
    set_input(mod, "resolution", resolution)
    set_input(mod, "iterations", iterations)
    obj.update_tag()
    start = time.perf_counter()
    ev = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
    mesh = ev.to_mesh()
    seconds = time.perf_counter() - start
    co = np.empty(len(mesh.vertices) * 3)
    mesh.vertices.foreach_get("co", co)
    sediment = np.zeros(len(mesh.vertices))
    if "sediment" in mesh.attributes:
        mesh.attributes["sediment"].data.foreach_get("value", sediment)
    ev.to_mesh_clear()
    return co[2::3].copy(), sediment, seconds


def terrain_object(group, material=None):
    mesh = bpy.data.meshes.new(group.name)
    if material:
        mesh.materials.append(material)
    obj = bpy.data.objects.new(group.name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    obj.modifiers.new("GN", "NODES").node_group = group
    return obj


def check_erosion():
    obj = terrain_object(bpy.data.node_groups["eroded hills"])
    z0, _, _ = evaluate(obj, 128, 0)
    z1, s1, _ = evaluate(obj, 128, 50)
    dz = z1 - z0
    print(f"heights before [{z0.min():.3f}, {z0.max():.3f}], after [{z1.min():.3f}, {z1.max():.3f}]; "
          f"dug {-dz.min():.3f}, filled {dz.max():.3f}, mean |dz| {np.abs(dz).mean():.4f}; "
          f"ground + sediment: {z0.mean():.6f} -> {z1.mean() + s1.mean():.6f}")
    assert np.isfinite(z1).all()
    assert np.abs(dz).mean() > 0.005, "the terrain did not change"
    assert dz.min() < -0.05 and dz.max() > 0.05, "no channel dug, no sediment left"
    assert abs(z1.mean() + s1.mean() - z0.mean()) < 1e-4, "ground was lost or made"
    return obj


def check_round_trip():
    blend = Path(tempfile.mkdtemp()) / "erosion.blend"
    bpy.data.libraries.write(str(blend), {g for g in bpy.data.node_groups})
    records, _ = test_libraries.round_trip(blend)
    for name, record in sorted(records.items()):
        print(f"round trip {name}: {record['status']}{' ' + str(record.get('on', '')) if 'on' in record else ''}")
    assert all(r["status"] == "ok" for r in records.values()), records


def timings(obj):
    for resolution in (128, 256):
        for iterations in (50, 200):
            seconds = min(evaluate(obj, resolution, iterations)[2] for _ in range(2))
            print(f"time {resolution} x {resolution}, {iterations} iterations: {seconds:.2f} s")


def eroded_material():
    """Grass on gentle slopes, rock on steep ones, sand where the sediment lies, blue where water stays."""
    mat = bpy.data.materials.new("Eroded")
    nt = mat.node_tree
    bsdf = nt.nodes["Principled BSDF"]
    bsdf.inputs["Roughness"].default_value = 0.85

    def attribute(name, low, high):
        a = nt.nodes.new("ShaderNodeAttribute")
        a.attribute_name = name
        r = nt.nodes.new("ShaderNodeMapRange")
        r.inputs["From Min"].default_value, r.inputs["From Max"].default_value = low, high
        nt.links.new(a.outputs["Fac"], r.inputs["Value"])
        return r.outputs[0]

    def mix(factor, a, b):
        m = nt.nodes.new("ShaderNodeMix")
        m.data_type = "RGBA"
        nt.links.new(factor, m.inputs["Factor"])
        for socket, value in ((m.inputs["A"], a), (m.inputs["B"], b)):
            if isinstance(value, tuple):
                socket.default_value = value
            else:
                nt.links.new(value, socket)
        return m.outputs["Result"]

    geometry = nt.nodes.new("ShaderNodeNewGeometry")
    up = nt.nodes.new("ShaderNodeSeparateXYZ")
    nt.links.new(geometry.outputs["Normal"], up.inputs[0])
    steep = nt.nodes.new("ShaderNodeMapRange")
    steep.inputs["From Min"].default_value, steep.inputs["From Max"].default_value = 0.9, 0.7
    nt.links.new(up.outputs["Z"], steep.inputs["Value"])
    color = mix(steep.outputs[0], (0.16, 0.26, 0.06, 1.0), (0.30, 0.23, 0.18, 1.0))
    color = mix(attribute("sediment", 0.0, 0.02), color, (0.78, 0.66, 0.45, 1.0))
    color = mix(attribute("water", 0.02, 0.08), color, (0.06, 0.18, 0.30, 1.0))
    nt.links.new(color, bsdf.inputs["Base Color"])
    return mat


def render(path):
    scene = bpy.context.scene
    material = eroded_material()
    base_node.host.build_source(SOURCE + SHOWCASE, "erosion.bn")
    terrain_object(bpy.data.node_groups["showcase"], material)
    world = bpy.data.worlds.new("Sky")
    world.node_tree.nodes["Background"].inputs["Color"].default_value = (0.045, 0.052, 0.068, 1.0)
    scene.world = world
    sun = bpy.data.objects.new("Sun", bpy.data.lights.new("Sun", "SUN"))
    sun.data.energy = 4.0
    sun.rotation_euler = (math.radians(58), 0.0, math.radians(-35))
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
    base_node.host.build_source(SOURCE, "erosion.bn")
    check_round_trip()  # it clears the groups and the objects: built again below
    base_node.host.build_source(SOURCE, "erosion.bn")
    obj = check_erosion()
    timings(obj)
    bpy.data.objects.remove(obj)
    if "--no-render" not in args:
        render(ROOT / "site" / "images" / "showcase-erosion.png")


main()
