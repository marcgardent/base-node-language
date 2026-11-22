"""Tests of tree_compare.py: on small trees made by hand, a copy changed in one thing shows exactly
that difference, and a copy unchanged none.

Run in Blender via:
    blender --background --factory-startup --python-exit-code 1 \
      --python base-node-for-blender/tests/test_tree_compare.py
"""

from __future__ import annotations

import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import tree_compare as TC  # noqa: E402

import bpy  # noqa: E402


def clear():
    for g in list(bpy.data.node_groups):
        bpy.data.node_groups.remove(g)


def sample(name="Sample"):
    """Group Input -> Set Position (offset from Position * a Math) -> Join Geometry -> Group Output,
    with an unconnected Value node."""
    t = bpy.data.node_groups.new(name, "GeometryNodeTree")
    t.interface.new_socket("Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
    size = t.interface.new_socket("Size", in_out="INPUT", socket_type="NodeSocketFloat")
    size.default_value, size.min_value, size.description = 2.0, 0.0, "How big"
    t.interface.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    gi, go = t.nodes.new("NodeGroupInput"), t.nodes.new("NodeGroupOutput")
    sp = t.nodes.new("GeometryNodeSetPosition")
    pos = t.nodes.new("GeometryNodeInputPosition")
    vm = t.nodes.new("ShaderNodeVectorMath")
    vm.operation = "SCALE"
    math = t.nodes.new("ShaderNodeMath")
    math.operation = "POWER"
    math.inputs[1].default_value = 3.0
    join = t.nodes.new("GeometryNodeJoinGeometry")
    value = t.nodes.new("ShaderNodeValue")
    value.outputs[0].default_value = 0.25
    t.links.new(gi.outputs[0], sp.inputs[0])
    t.links.new(pos.outputs[0], vm.inputs[0])
    t.links.new(gi.outputs[1], math.inputs[0])
    t.links.new(math.outputs[0], vm.inputs["Scale"])
    t.links.new(vm.outputs[0], sp.inputs["Offset"])
    t.links.new(sp.outputs[0], join.inputs[0])
    t.links.new(gi.outputs[0], join.inputs[0])
    t.links.new(join.outputs[0], go.inputs[0])
    for i, n in enumerate(t.nodes):
        n.location = (200 * i, 0)
    return t


def twin(t):
    """A copy of `t`, known by the same name."""
    c = t.copy()
    c.use_fake_user = t.use_fake_user  # ID.copy() leaves the fake user out
    if t.asset_data is not None:  # and the asset data
        c.asset_mark()
        for p in ("description", "author", "license", "copyright", "catalog_id"):
            setattr(c.asset_data, p, getattr(t.asset_data, p))
    return c


def diffs(a, b, names=None):
    names = dict(names or {})
    names.setdefault(b.name, a.name)
    return TC.compare_trees(a, b, name=lambda id: names.get(id.name, id.name))


def classes(found):
    return sorted({d.cls for d in found})


def expect(found, *wanted):
    got = classes(found)
    assert got == sorted(wanted), f"expected {sorted(wanted)}, got {got}:\n" + "\n".join(map(str, found))


def node(t, idname):
    return next(n for n in t.nodes if n.bl_idname == idname)


def changed(edit, *wanted, base=sample, presentation=True):
    """A copy of the sample, `edit(copy)`, shows exactly the classes `wanted` (but those of
    presentation, unless `presentation`: what an edit moves in the editor besides)."""
    clear()
    a = base()
    b = twin(a)
    edit(b)
    found = diffs(a, b)
    expect([d for d in found if presentation or not d.cls.startswith("presentation")], *wanted)
    return found


# --- Tests ------------------------------------------------------------------------------------

def test_copy_is_the_same():
    clear()
    a = sample()
    expect(diffs(a, twin(a)))


def test_matching_by_structure():
    """The same graph made in another order, the nodes named otherwise: matched by their place, only
    their names and locations differ."""
    clear()
    a = sample("A")
    b = bpy.data.node_groups.new("B", "GeometryNodeTree")
    for item in a.interface.items_tree:
        s = b.interface.new_socket(item.name, in_out=item.in_out, socket_type=item.socket_type)
        for p in ("default_value", "min_value", "description"):
            if hasattr(item, p):
                setattr(s, p, getattr(item, p))
    made = {}
    for n in reversed(list(a.nodes)):
        m = made[n.name] = b.nodes.new(n.bl_idname)
        m.name = "other " + n.name
        for p in ("operation",):
            if hasattr(n, p):
                setattr(m, p, getattr(n, p))
        for x, y in zip(n.inputs, m.inputs):
            if hasattr(x, "default_value"):
                y.default_value = x.default_value
        for x, y in zip(n.outputs, m.outputs):
            if hasattr(x, "default_value"):
                y.default_value = x.default_value
        m.location = n.location
    # The links in another order too, those of the multi-input in theirs
    def ends(l):
        out = list(l.from_node.outputs).index(l.from_socket)
        into = list(l.to_node.inputs).index(l.to_socket)
        return made[l.from_node.name].outputs[out], made[l.to_node.name].inputs[into]

    for l in reversed(list(a.links)):
        if not l.to_socket.is_multi_input:
            b.links.new(*ends(l))
    for l in sorted((l for l in a.links if l.to_socket.is_multi_input), key=lambda l: l.multi_input_sort_id):
        b.links.new(*ends(l))
    found = diffs(a, b)
    # Blender numbers the interface's sockets in the order they are made
    expect(found, "interface-identifier", "presentation:name")


def test_setting():
    changed(lambda b: setattr(node(b, "ShaderNodeMath"), "operation", "ADD"), "setting-lost")
    changed(lambda b: setattr(node(b, "ShaderNodeMath"), "operation", "SUBTRACT"), "setting-changed")
    changed(lambda b: setattr(node(b, "ShaderNodeMath"), "use_clamp", True), "setting-changed")


def test_muted_node():
    def unmute(t):
        node(t, "ShaderNodeMath").mute = True
        return t
    found = changed(lambda b: setattr(node(b, "ShaderNodeMath"), "mute", False), "setting-lost",
                    base=lambda: unmute(sample()))
    assert found[0].prop == "mute", found


def test_default():
    changed(lambda b: setattr(node(b, "ShaderNodeMath").inputs[1], "default_value", 0.5), "default-lost")
    changed(lambda b: setattr(node(b, "ShaderNodeMath").inputs[1], "default_value", 4.0), "default-drift")
    found = changed(lambda b: setattr(node(b, "ShaderNodeMath").inputs[1], "default_value", 3.0 + 5e-7),
                    "float-below-1e-6")
    assert found[0].a != found[0].b, found
    changed(lambda b: setattr(node(b, "ShaderNodeMath").inputs[2], "default_value", 0.75), "default-unavailable")
    # A linked input's value is not read
    changed(lambda b: setattr(node(b, "GeometryNodeSetPosition").inputs["Offset"], "default_value", (1, 2, 3)))


def test_floats_bit_for_bit():
    clear()
    a = sample()
    node(a, "ShaderNodeMath").inputs[1].default_value = 0.0
    b = twin(a)
    node(b, "ShaderNodeMath").inputs[1].default_value = -0.0
    expect(diffs(a, b), "float-below-1e-6")
    for x, y, cls in ((float("inf"), float("inf"), None), (float("nan"), float("nan"), None),
                      (float("inf"), 3.4e38, "default-drift"), (float("nan"), 0.5, "default-lost")):
        node(a, "ShaderNodeMath").inputs[1].default_value = x
        node(b, "ShaderNodeMath").inputs[1].default_value = y
        expect(diffs(a, b), *([cls] if cls else []))


def test_output_value():
    changed(lambda b: setattr(node(b, "ShaderNodeValue").outputs[0], "default_value", 0.5), "output-value")


def test_sockets():
    changed(lambda b: setattr(node(b, "ShaderNodeMath").inputs[1], "hide", True), "socket-hide")
    changed(lambda b: setattr(node(b, "ShaderNodeMath").inputs[1], "hide_value", True), "socket-hide-value")


def test_nodes():
    changed(lambda b: b.nodes.remove(node(b, "GeometryNodeInputPosition")), "node-missing")
    changed(lambda b: b.nodes.new("ShaderNodeValue"), "node-extra")
    changed(lambda b: b.nodes.new("GeometryNodeGroup"), "node-extra")
    changed(lambda b: b.nodes.remove(node(b, "ShaderNodeValue")), "node-missing")


def test_group_inputs():
    def two(t):
        gi2 = t.nodes.new("NodeGroupInput")
        t.links.new(gi2.outputs[1], node(t, "ShaderNodeMath").inputs[0])
        return t

    def merge(b):
        gis = [n for n in b.nodes if n.bl_idname == "NodeGroupInput"]
        b.nodes.remove(gis[1])
        b.links.new(gis[0].outputs[1], node(b, "ShaderNodeMath").inputs[0])

    changed(merge, "node-merged", base=lambda: two(sample()))
    changed(two, "node-split")
    # A Group Input nothing is linked from: only drawn
    changed(lambda b: b.nodes.new("NodeGroupInput"), "presentation:group-input")


def test_merged_input_node():
    """Two Position nodes feeding two nodes, made one feeding both: merged."""
    def two(t):
        p2 = t.nodes.new("GeometryNodeInputPosition")
        t.links.new(p2.outputs[0], node(t, "GeometryNodeSetPosition").inputs["Position"])
        return t

    def merge(b):
        ps = [n for n in b.nodes if n.bl_idname == "GeometryNodeInputPosition"]
        b.nodes.remove(ps[1])
        b.links.new(ps[0].outputs[0], node(b, "GeometryNodeSetPosition").inputs["Position"])

    changed(merge, "node-merged", base=lambda: two(sample()), presentation=False)


def test_links():
    def drop(b):
        b.links.remove(next(l for l in b.links if l.from_node.bl_idname == "GeometryNodeInputPosition"))
    changed(drop, "link-missing")
    changed(lambda b: b.links.new(node(b, "ShaderNodeValue").outputs[0], node(b, "ShaderNodeMath").inputs[1]),
            "link-extra")

    def mute(b):
        next(l for l in b.links if l.from_node.bl_idname == "GeometryNodeInputPosition").is_muted = True
    changed(mute, "link-muted")
    # Into the third input of a Math node that raises to a power, which it does not show
    changed(lambda b: b.links.new(node(b, "ShaderNodeValue").outputs[0], node(b, "ShaderNodeMath").inputs[2]),
            "link-unavailable")

    def swap(b):
        join = node(b, "GeometryNodeJoinGeometry")
        fed = sorted((l for l in b.links if l.to_node == join), key=lambda l: -l.multi_input_sort_id)
        sources = [l.from_socket for l in fed]
        for l in fed:
            b.links.remove(l)
        for s in sources:  # the first joined is the last made
            b.links.new(s, join.inputs[0])
    changed(swap, "link-order")


def test_reroutes_and_frames():
    def reroute(b):
        l = next(l for l in b.links if l.from_node.bl_idname == "GeometryNodeInputPosition")
        r = b.nodes.new("NodeReroute")
        src, dst = l.from_socket, l.to_socket
        b.links.remove(l)
        b.links.new(src, r.inputs[0])
        b.links.new(r.outputs[0], dst)
    changed(reroute, "presentation:reroute")

    def frame(b):
        f = b.nodes.new("NodeFrame")
        node(b, "ShaderNodeMath").parent = f
    changed(frame, "presentation:frame", "presentation:parent")


def test_presentation():
    changed(lambda b: setattr(node(b, "ShaderNodeMath"), "location", (5, 5)), "presentation:location",
            "presentation:location_absolute")
    changed(lambda b: setattr(node(b, "ShaderNodeMath"), "label", "x"), "presentation:label")
    changed(lambda b: setattr(node(b, "ShaderNodeMath"), "name", "x"), "presentation:name")
    changed(lambda b: setattr(node(b, "ShaderNodeMath"), "width", 300), "presentation:width")
    changed(lambda b: setattr(node(b, "ShaderNodeMath"), "hide", True), "presentation:hide")


def test_interface():
    def item(t, name):
        return next(i for i in t.interface.items_tree if i.name == name)
    changed(lambda b: setattr(item(b, "Size"), "description", "Other"), "interface")
    changed(lambda b: setattr(item(b, "Size"), "min_value", -1.0), "interface")
    changed(lambda b: setattr(item(b, "Size"), "hide_in_modifier", True), "interface")
    changed(lambda b: setattr(item(b, "Size"), "default_value", 2.0 + 1e-6), "float-below-1e-6")
    changed(lambda b: b.interface.new_panel("Extra"), "interface-extra")
    # A new socket is a socket more on the Group Input
    changed(lambda b: b.interface.new_socket("More", in_out="INPUT", socket_type="NodeSocketInt"),
            "interface-extra", "socket-count")


def test_items():
    def capture(t):
        c = t.nodes.new("GeometryNodeCaptureAttribute")
        c.capture_items.new("FLOAT", "A")
        c.capture_items.new("VECTOR", "B")
        return t

    def drop(b):
        c = node(b, "GeometryNodeCaptureAttribute")
        c.capture_items.remove(c.capture_items[1])
    found = changed(drop, "items-lost", base=lambda: capture(sample()), presentation=False)
    assert found[0].a == [{"name": "A", "data_type": "FLOAT"}, {"name": "B", "data_type": "FLOAT_VECTOR"}] \
        or len(found[0].a) == 2, found[0]
    changed(lambda b: node(b, "GeometryNodeCaptureAttribute").capture_items.new("INT", "C"), "items-extra",
            base=lambda: capture(sample()), presentation=False)
    # An item of another type: its sockets are of that type, their value an int
    changed(lambda b: setattr(node(b, "GeometryNodeCaptureAttribute").capture_items[0], "data_type", "INT"),
            "setting-changed", "socket", "default-drift", base=lambda: capture(sample()), presentation=False)

    def again(b):
        # The same items made again: Blender gives them new identifiers
        c = node(b, "GeometryNodeCaptureAttribute")
        c.capture_items.clear()
        c.capture_items.new("FLOAT", "A")
        c.capture_items.new("VECTOR", "B")
    # A capture item shows no identifier of its own: its sockets' say it
    changed(again, "socket-identifier", base=lambda: capture(sample()))

    def switch(t):
        n = t.nodes.new("GeometryNodeIndexSwitch")
        n.index_switch_items.new()
        return t

    def again_switch(b):
        n = node(b, "GeometryNodeIndexSwitch")
        n.index_switch_items.clear()
        for _ in range(3):
            n.index_switch_items.new()
    changed(again_switch, "item-identifier", "socket-identifier", base=lambda: switch(sample()))


def test_ramp():
    def ramp(t):
        t.nodes.new("ShaderNodeValToRGB")
        return t
    changed(lambda b: setattr(node(b, "ShaderNodeValToRGB").color_ramp.elements[1], "position", 0.5),
            "setting-changed", base=lambda: ramp(sample()))
    changed(lambda b: node(b, "ShaderNodeValToRGB").color_ramp.elements.new(0.3), "items-extra",
            base=lambda: ramp(sample()))


def test_group_node_and_nested():
    clear()
    inner = sample("Inner")
    outer = bpy.data.node_groups.new("Outer", "GeometryNodeTree")
    outer.nodes.new("GeometryNodeGroup").node_tree = inner
    inner2 = twin(inner)
    outer2 = twin(outer)
    node(outer2, "GeometryNodeGroup").node_tree = inner2
    names = {inner2.name: "Inner"}
    expect(diffs(outer, outer2, names))
    node(inner2, "ShaderNodeMath").operation = "ADD"
    found = diffs(outer, outer2, names)
    expect(found, "setting-lost")
    assert found[0].tree == "Inner", found
    # Another group called
    other = sample("Other")
    node(outer2, "GeometryNodeGroup").node_tree = other
    expect(diffs(outer, outer2, names), "group-tree")


def test_tree_level():
    changed(lambda b: setattr(b, "description", "Other"), "tree-setting")
    changed(lambda b: setattr(b, "is_modifier", True), "tree-setting")
    changed(lambda b: node(b, "ShaderNodeMath").__setitem__("note", 1), "idprop")
    # The builder's own bookkeeping is no difference
    changed(lambda b: node(b, "ShaderNodeMath").__setitem__("base_node_line", 3))


def test_asset():
    def asset(t):
        t.asset_mark()
        t.asset_data.description = "One"
        return t
    changed(lambda b: setattr(b.asset_data, "description", "Two"), "tree-asset", base=lambda: asset(sample()))


def test_array_and_flag_settings():
    """A node with an array setting and one with a flag-set setting, found by scanning RNA."""
    clear()
    t = bpy.data.node_groups.new(".scan", "GeometryNodeTree")
    array = flags = None
    for name in sorted(dir(bpy.types)):
        cls = getattr(bpy.types, name)
        if not (isinstance(cls, type) and issubclass(cls, bpy.types.Node)) or cls is bpy.types.Node:
            continue
        try:
            n = t.nodes.new(name)
        except RuntimeError:
            continue
        for p in n.bl_rna.properties:
            if p.is_readonly or p.identifier in TC.NODE_PRESENTATION | TC.NODE_FILTERED | TC.CONSTANTS:
                continue
            if array is None and getattr(p, "is_array", False) and p.type in ("BOOLEAN", "INT", "FLOAT"):
                array = (name, p.identifier)
            if flags is None and p.type == "ENUM" and p.is_enum_flag and len(p.enum_items) > 1:
                flags = (name, p.identifier)
    bpy.data.node_groups.remove(t)
    for found, edit in ((array, lambda n, p: setattr(n, p, [not v if isinstance(v, bool) else v + 1
                                                           for v in getattr(n, p)])),
                        (flags, lambda n, p: setattr(n, p, {i.identifier for i in n.bl_rna.properties[p].enum_items}
                                                     - set(getattr(n, p)) or {n.bl_rna.properties[p].enum_items[0].identifier}))):
        if found is None:
            print(f"   (no such setting in Blender {bpy.app.version_string})")
            continue
        idname, prop = found

        def base(idname=idname):
            t = sample()
            t.nodes.new(idname)
            return t
        clear()
        a = base()
        b = twin(a)
        edit(node(b, idname), prop)
        got = diffs(a, b)
        assert got and {d.cls for d in got} <= {"setting-changed", "setting-lost"} and \
            {d.prop for d in got} == {prop}, f"{idname}.{prop}: " + "\n".join(map(str, got))
        print(f"   {idname}.{prop}: {got[0]}")


def main():
    tests = [v for k, v in sorted(globals().items(), key=lambda kv: kv[1].__code__.co_firstlineno
                                  if callable(kv[1]) and hasattr(kv[1], "__code__") else 0)
             if k.startswith("test_") and callable(v)]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"   ✓ {t.__name__}")
        except Exception:
            failed += 1
            print(f"   ✗ {t.__name__}")
            traceback.print_exc()
    clear()
    if failed:
        print(f"\n❌ FAILED: {failed}/{len(tests)}")
        sys.exit(1)
    print(f"\n✅ SUCCESS: {len(tests)} tests")
    sys.exit(0)


if __name__ == "__main__":
    main()
