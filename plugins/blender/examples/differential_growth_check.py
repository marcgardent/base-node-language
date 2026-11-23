"""Build examples/differential_growth.bn in Blender, check its growth, its round trip, time it, render it.

  blender -b --factory-startup --python-exit-code 1 --python examples/differential_growth_check.py \
    [-- --no-render] [--no-timings] [--no-round-trip]

1. The groups are saved in a .blend and go through the regression tests' round trip
   (tests/test_libraries.py): tree -> .bn -> tree gives the same text and the same geometry.
2. "differential growth" on a circle, for a few step counts: the point count and the length of
   the curve grow, the curve stays one closed curve, it never crosses itself, and two points
   that are not neighbours along it stay apart (more than a quarter of `max length`).
3. The same seed gives the same curve, another seed another one.
4. The time of an evaluation for a few sizes and step counts.
5. "growing differential growth" (the Simulation zone) grows from frame to frame.
6. A still: site/images/showcase-differential-growth.png.
"""

import math
import sys
import tempfile
import time
from pathlib import Path

import bpy
import numpy as np
from mathutils import kdtree

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "addon" / "tests"))
import test_libraries  # noqa: E402  (loads the extension as `base_node`)

import base_node  # noqa: E402

SOURCE = (ROOT / "examples" / "differential_growth.bn").read_text(encoding="utf-8")
MAX_LENGTH = 0.02
# The curve itself, as the vertices and edges of a mesh, in the order of its points
PROBE = """
geometry graph probe(
    size: Float = 0.4,
    iterations: Int = 100,
    "max length": Float = 0.02,
    seed: Int = 0,
    "max points": Int = 10000
) -> Geometry {
  return growth_seed(size, max_length, 0.3, seed)
    |> differential_growth(
      iterations: iterations,
      max_length: max_length,
      radius: max_length * 2.5,
      max_points: max_points)
    |> CurveToMesh()
}

geometry graph "growing probe"() -> Geometry {
  return growth_seed(0.4, 0.02, 0.3, 0)
    |> growing_differential_growth(radius: 0.05)
    |> CurveToMesh()
}
"""
SHOWCASE = """
geometry graph showcase() -> Geometry {
  return differential_growth_coral(size: 0.4, iterations: 500, max_length: 0.015, thickness: 0.005)
    |> SetMaterial(material: "Coral")
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


def evaluate(obj):
    """(points, edges, seconds) of the object's evaluated mesh."""
    obj.update_tag()
    start = time.perf_counter()
    ev = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
    mesh = ev.to_mesh()
    seconds = time.perf_counter() - start
    co = np.empty(len(mesh.vertices) * 3)
    mesh.vertices.foreach_get("co", co)
    edges = np.empty(len(mesh.edges) * 2, dtype=np.int64)
    mesh.edges.foreach_get("vertices", edges)
    ev.to_mesh_clear()
    return co.reshape(-1, 3), edges.reshape(-1, 2), seconds


def grow(obj, **inputs):
    for name, value in inputs.items():
        set_input(obj.modifiers[0], name.replace("_", " "), value)
    return evaluate(obj)


def crossings(p):
    """The pairs of edges of the closed polyline p that cross, but those sharing a point."""
    n = len(p)
    a, b = p, np.roll(p, -1, axis=0)
    mid = (a + b) * 0.5
    reach = np.linalg.norm(b - a, axis=1).max()
    tree = kdtree.KDTree(n)
    for i, m in enumerate(mid):
        tree.insert((m[0], m[1], 0.0), i)
    tree.balance()

    def side(o, u, v):
        return (u[0] - o[0]) * (v[1] - o[1]) - (u[1] - o[1]) * (v[0] - o[0])

    found = []
    for i in range(n):
        for _, j, _ in tree.find_range((mid[i][0], mid[i][1], 0.0), reach):
            if j <= i or j == (i + 1) % n or i == (j + 1) % n:
                continue
            if (side(a[i], b[i], a[j]) * side(a[i], b[i], b[j]) < 0
                    and side(a[j], b[j], a[i]) * side(a[j], b[j], b[i]) < 0):
                found.append((i, j))
    return found


def apart(p, gap=3):
    """The least distance between two points at least `gap` places apart along the closed curve."""
    n = len(p)
    tree = kdtree.KDTree(n)
    for i, q in enumerate(p):
        tree.insert((q[0], q[1], 0.0), i)
    tree.balance()
    best = math.inf
    for i, q in enumerate(p):
        for _, j, d in tree.find_n((q[0], q[1], 0.0), 2 * gap + 4):
            k = abs(i - j)
            if min(k, n - k) >= gap:
                best = min(best, d)
    return best


def shape(points, edges):
    """Point count, length, least distance of points apart, crossings, and whether it is one loop."""
    n = len(points)
    loop = len(edges) == n and np.array_equal(np.sort(edges[:, 0]), np.arange(n))
    loop = loop and all((edges[:, 1] - edges[:, 0]) % n == 1)
    p = points[:, :2]
    length = np.linalg.norm(np.roll(p, -1, axis=0) - p, axis=1).sum()
    return n, length, apart(p), len(crossings(p)), loop


def check_round_trip():
    blend = Path(tempfile.mkdtemp()) / "differential_growth.blend"
    bpy.data.libraries.write(str(blend), {g for g in bpy.data.node_groups})
    records, _ = test_libraries.round_trip(blend)
    for name, record in sorted(records.items()):
        print(f"round trip {name}: {record['status']}{' ' + str(record.get('on', '')) if 'on' in record else ''}")
    assert all(r["status"] == "ok" for r in records.values()), records
    # Every graph of the file is a group that went through the round trip: a missing record fails
    graphs = {g.name for g in base_node.lang.parse(SOURCE, "differential_growth.bn").graphs}
    missing = graphs - set(records)
    assert not missing, f"no round trip for {sorted(missing)}"
    print(f"round trip: {len(graphs)} graphs of the file, {len(records)} records")


def check_growth(obj):
    before = None
    for iterations in (0, 50, 100, 200, 400):
        points, edges, seconds = grow(obj, iterations=iterations)
        n, length, gap, crossed, loop = shape(points, edges)
        print(f"{iterations} steps: {n} points, length {length:.3f}, "
              f"least distance apart {gap:.4f} ({gap / MAX_LENGTH:.2f} max length), "
              f"{crossed} crossings, one closed curve: {loop} ({seconds:.2f} s)")
        assert np.isfinite(points).all()
        assert loop, "the curve is no longer one closed curve"
        assert crossed == 0, "the curve crosses itself"
        assert gap > 0.25 * MAX_LENGTH, "two points that are not neighbours touch"
        if before:
            assert n > before[0] and length > before[1], "the curve does not grow"
        before = (n, length)
    # The cap on the points holds
    n = shape(*grow(obj, iterations=400, max_points=1000)[:2])[0]
    print(f"400 steps, at most 1000 points: {n} points")
    assert n < 1000 * 2, "max points does not hold"
    set_input(obj.modifiers[0], "max points", 10000)


def check_seed(obj):
    a = grow(obj, iterations=200, seed=0)[0]
    b = grow(obj, iterations=200, seed=0)[0]
    c = grow(obj, iterations=200, seed=1)[0]
    same = a.shape == b.shape and np.array_equal(a, b)
    print(f"seed 0 twice: the same curve {same}; seed 1: {len(c)} points against {len(a)}")
    assert same, "the same seed gives another curve"
    assert a.shape != c.shape or not np.allclose(a, c), "another seed gives the same curve"
    set_input(obj.modifiers[0], "seed", 0)


def check_simulation():
    obj = new_object(bpy.data.node_groups["growing probe"])
    scene = bpy.context.scene
    seen = []
    # A Simulation zone steps once per frame when the frames come one after the other
    for frame in range(1, 61):
        scene.frame_set(frame)
        if frame not in (1, 20, 40, 60):
            continue
        points, edges, _ = evaluate(obj)
        n, length, gap, crossed, loop = shape(points, edges)
        seen.append((n, length))
        print(f"simulation frame {frame}: {n} points, length {length:.3f}, "
              f"least distance apart {gap / MAX_LENGTH:.2f} max length, {crossed} crossings")
        assert loop and crossed == 0
    assert all(b[0] > a[0] and b[1] > a[1] for a, b in zip(seen, seen[1:])), "the simulation does not grow"
    scene.frame_set(1)
    bpy.data.objects.remove(obj)


def timings(obj):
    for size, max_length in ((0.4, 0.02), (0.4, 0.01)):
        for iterations in (200, 400):
            points, _, seconds = grow(obj, size=size, max_length=max_length, iterations=iterations)
            print(f"time size {size}, max length {max_length}, {iterations} steps: "
                  f"{len(points)} points, {seconds:.2f} s")
    set_input(obj.modifiers[0], "max length", MAX_LENGTH)


def coral_material():
    """A warm coral, lighter where the points come from one side of the first circle."""
    mat = bpy.data.materials.new("Coral")
    nt = mat.node_tree
    bsdf = nt.nodes["Principled BSDF"]
    bsdf.inputs["Roughness"].default_value = 0.35
    attribute = nt.nodes.new("ShaderNodeAttribute")
    attribute.attribute_name = "origin"
    angle = nt.nodes.new("ShaderNodeSeparateXYZ")
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    ramp.color_ramp.interpolation = "EASE"
    stops = ramp.color_ramp.elements
    stops[0].position, stops[0].color = 0.0, (0.95, 0.30, 0.18, 1.0)
    stops[1].position, stops[1].color = 1.0, (1.0, 0.78, 0.35, 1.0)
    stops.new(0.5).color = (0.85, 0.20, 0.38, 1.0)
    remap = nt.nodes.new("ShaderNodeMapRange")
    remap.inputs["From Min"].default_value = -1.0
    nt.links.new(attribute.outputs["Vector"], angle.inputs["Vector"])
    nt.links.new(angle.outputs["Y"], remap.inputs["Value"])
    nt.links.new(remap.outputs["Result"], ramp.inputs["Fac"])
    nt.links.new(ramp.outputs["Color"], bsdf.inputs["Base Color"])
    return mat


def render(path):
    scene = bpy.context.scene
    material = coral_material()
    base_node.host.build_source(SOURCE + SHOWCASE, "differential_growth.bn")
    new_object(bpy.data.node_groups["showcase"], material)
    # A dark slab under the coral, to catch its shadow
    bpy.ops.mesh.primitive_plane_add(size=8.0, location=(0.0, 0.0, -0.005))
    ground = bpy.data.materials.new("Ground")
    ground.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (0.03, 0.04, 0.06, 1.0)
    bpy.context.object.data.materials.append(ground)
    world = bpy.data.worlds.new("Sky")
    world.node_tree.nodes["Background"].inputs["Color"].default_value = (0.045, 0.052, 0.068, 1.0)
    scene.world = world
    sun = bpy.data.objects.new("Sun", bpy.data.lights.new("Sun", "SUN"))
    sun.data.energy = 4.0
    sun.rotation_euler = (math.radians(35), 0.0, math.radians(-35))
    scene.collection.objects.link(sun)
    camera = bpy.data.objects.new("Camera", bpy.data.cameras.new("Camera"))
    camera.data.type = "ORTHO"
    camera.data.ortho_scale = 2.6
    camera.location = (0.0, 0.0, 5.0)
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
    base_node.host.build_source(SOURCE, "differential_growth.bn")
    if "--no-round-trip" not in args:
        check_round_trip()  # it clears the groups and the objects: built again below
    base_node.host.build_source(SOURCE + PROBE, "differential_growth.bn")
    obj = new_object(bpy.data.node_groups["probe"])
    check_growth(obj)
    check_seed(obj)
    if "--no-timings" not in args:
        timings(obj)
    bpy.data.objects.remove(obj)
    check_simulation()
    if "--no-render" not in args:
        render(ROOT / "site" / "images" / "showcase-differential-growth.png")


main()
