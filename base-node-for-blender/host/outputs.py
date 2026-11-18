"""Where the return of a shader or compositor graph goes beyond its group.

A shader graph is a shader node group. When no other graph of the text calls it and its
first output is a Shader, it is also a material of the same name: the material's tree is
the group's node, its outputs linked to the Material Output by name (Surface, Volume,
Displacement, Thickness; the first Shader output goes to Surface when none is named so).
The group's inputs are the material's settings, as a modifier's are a geometry group's:
they stay as set when the text is built again.

A compositor graph is a compositor node group: in Blender 5, its Group Output is the
Composite, and its first Color input receives the render. When no other graph calls it,
its first output is a Color and the scene has no compositor effect yet, it becomes the
scene's compositor: an effect of its name. A scene that already has one keeps it as it is.

A `shader(material: true)` graph is not a group but a material's own tree, its return
the Material Output's inputs: none of this applies to it.
"""

import bpy

from ..lang.schema import is_material

# On a material the builder made: the shader group it shows
MATERIAL_GROUP = "base_node_group"

MATERIAL_OUTPUT = "ShaderNodeOutputMaterial"
MATERIAL_SOCKETS = ("Surface", "Volume", "Displacement", "Thickness")


def offered(g, called):
    """True when the graph's return also feeds a material or the scene's Composite."""
    if g.module is not None or g.name in called or not g.outputs or is_material(g.settings):
        return False
    return (g.kind, g.outputs[0][1]) in (("shader", "Shader"), ("compositor", "Color"))


def offer(tree, g, called):
    """Give the graph's return the place Blender reads it from. Returns the material, the
    scene, or None when nothing was offered."""
    if not offered(g, called):
        return None
    if g.kind == "shader":
        return material(tree)
    return compositor(bpy.context.scene, tree)


def compositor(scene, tree):
    """Make the group the scene's compositor when the scene has none yet. Returns the scene, or None."""
    if scene is None:
        return None
    effects = getattr(scene, "compositor_effects", None)
    if effects is None:
        # Before the effect stack, a scene has one compositing group
        if scene.compositing_node_group is not None:
            return None
        scene.compositing_node_group = tree
        return scene
    if len(effects):
        return None
    effects.new(name=tree.name).node_group = tree
    return scene


def owner(tree):
    """The material whose own tree this is, else None: a group, a world's or a light's tree."""
    if tree is None or not tree.is_embedded_data:
        return None
    return next((m for m in bpy.data.materials if m.node_tree == tree), None)


def tree_ref(tree):
    """("MATERIAL", its name) for a material's own tree, else ("GROUP", the group's name): how a
    tree is found again later, a material's tree having the name every material's has."""
    mat = owner(tree)
    return ("MATERIAL", mat.name) if mat is not None else ("GROUP", tree.name)


def find_tree(ref):
    """The tree of a tree_ref, or None when it is gone."""
    kind, name = ref
    if kind == "MATERIAL":
        mat = bpy.data.materials.get(name)
        return mat.node_tree if mat is not None else None
    return bpy.data.node_groups.get(name)


def is_material_of(mat, tree):
    return mat is not None and mat.get(MATERIAL_GROUP) == tree


def reserve(tree):
    """The material of a shader group, made empty when there is none yet, so that the graphs
    of the text can set it before the group is built. None for a material of that name the
    builder did not make, left as it is."""
    mat = bpy.data.materials.get(tree.name)
    if mat is not None and (mat.library is not None or not is_material_of(mat, tree)):
        return None
    if mat is None:
        mat = bpy.data.materials.new(tree.name)
        mat[MATERIAL_GROUP] = tree
        mat.node_tree.nodes.clear()
    return mat


def material(tree):
    """The material of a shader group: made, or brought up to date when the builder made it.
    A material of that name the builder did not make is left as it is: None."""
    mat = reserve(tree)
    if mat is None:
        return None
    # The group's node is made once the group has its inputs: it takes their defaults
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    group = next((n for n in nodes if n.bl_idname == "ShaderNodeGroup" and n.node_tree == tree), None)
    if group is None:
        group = nodes.new("ShaderNodeGroup")
        group.node_tree = tree
        group.location = (-200.0, 0.0)
    out = next((n for n in nodes if n.bl_idname == MATERIAL_OUTPUT and n.is_active_output), None) \
        or next((n for n in nodes if n.bl_idname == MATERIAL_OUTPUT), None)
    if out is None:
        out = nodes.new(MATERIAL_OUTPUT)
        out.location = (100.0, 0.0)
    for src, dst in material_links(group, out):
        for old in list(dst.links):
            links.remove(old)
        links.new(src, dst)
    return mat


def material_links(group, out):
    """[(group output, Material Output input)]: by name, else the first Shader to Surface."""
    outputs = [s for s in group.outputs if s.type != "CUSTOM"]
    targets = {s.name.lower(): s for s in out.inputs if s.name in MATERIAL_SOCKETS}
    named = {}
    for s in outputs:
        # Two outputs of one name: the first feeds the Material Output
        named.setdefault(s.name.lower(), s)
    pairs = [(s, targets[k]) for k, s in named.items() if k in targets]
    if not pairs:
        shader = next((s for s in outputs if s.type == "SHADER"), None)
        if shader is not None:
            pairs = [(shader, targets["surface"])]
    return pairs
