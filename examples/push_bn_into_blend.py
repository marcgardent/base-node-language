"""Build every .bn file of a folder into a .blend laid out as a gallery, with the installed
Base Node extension.

  blender -b --python examples/push_bn_into_blend.py -- examples/suite/ gallery.blend
  blender -b gallery.blend --python examples/push_bn_into_blend.py -- examples/suite/

The files are imported as *File > Import > Base Node (.bn)* would: a group that already
exists is rebuilt in place, a `use` finds the modules next to the files, and the frames
(`"Wave" #teal { … }`) and `//` comments of the text are kept in the node trees.

Then each geometry group of the files gets an object of its own in the collection
"Gallery", side by side along x with its name above it: a group that takes a geometry
works on a grid, the others make their own. The .blend is saved: the one opened, or the
one named. A material a file defines (`shader(material: true) graph Sand()`, in sand.bn)
can be set by the groups of the other files, whatever their order. A file that fails is
reported with its line and column, and the others are still built; nothing is saved when
none builds.
"""

import os
import sys

import bpy

SPACING = 6.0  # between two objects of the gallery, along x

args = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
if not args:
    sys.exit(__doc__)
folder = os.path.abspath(args[0])
out = os.path.abspath(args[1]) if len(args) > 1 else bpy.data.filepath
if not out:
    sys.exit("no .blend to save: open one, or name it after the folder")
if not hasattr(bpy.ops.base_node, "import_bn"):
    sys.exit("the Base Node extension is not enabled: install it, and run without --factory-startup")

names = sorted(f for f in os.listdir(folder) if f.endswith(".bn"))
if not names:
    sys.exit(f"no .bn file in {folder}")
try:
    bpy.ops.base_node.import_bn(directory=folder + os.sep, files=[{"name": n} for n in names])
except RuntimeError as e:
    print(e)  # in the background, what the operator reports comes back as one exception

# The groups the files define; those a `use` brings are marked as coming from a module
groups = sorted((g for g in bpy.data.node_groups
                 if g.bl_idname == "GeometryNodeTree" and not g.name.startswith(".")
                 and "base_node_module" not in g),
                key=lambda g: g.name)
if not groups:
    sys.exit("nothing was built")

def takes_geometry(group):
    return any(i.item_type == "SOCKET" and i.in_out == "INPUT" and i.socket_type == "NodeSocketGeometry"
               for i in group.interface.items_tree)


gallery = bpy.data.collections.get("Gallery") or bpy.data.collections.new("Gallery")
if gallery.name not in bpy.context.scene.collection.children:
    bpy.context.scene.collection.children.link(gallery)
for i, group in enumerate(groups):
    name = f"Gallery {group.name}"
    obj = bpy.data.objects.get(name)
    if obj is None:  # run again, the gallery keeps its objects and their places
        mesh = bpy.data.meshes.new(name)
        if takes_geometry(group):
            import bmesh
            bm = bmesh.new()
            bmesh.ops.create_grid(bm, x_segments=64, y_segments=64, size=2.0)
            bm.to_mesh(mesh)
            bm.free()
        obj = bpy.data.objects.new(name, mesh)
        gallery.objects.link(obj)
        obj.location.x = i * SPACING
        label = bpy.data.objects.new(f"{name} label", bpy.data.curves.new(f"{name} label", "FONT"))
        label.data.body = group.name
        label.data.align_x = "CENTER"
        label.location = (obj.location.x, -3.0, 0.0)
        gallery.objects.link(label)
    mod = next((m for m in obj.modifiers if m.type == "NODES"), None) or obj.modifiers.new("GN", "NODES")
    mod.node_group = group
    print(f"  {group.name}: {obj.name}")

bpy.ops.wm.save_as_mainfile(filepath=out)
print(f"{len(names)} file(s), {len(groups)} group(s) in the gallery; saved {out}")
