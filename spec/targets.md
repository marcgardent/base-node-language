# Targets

A **target** is what one destination accepts: the kinds of tree, the types, the zones and the nodes
a text may use there. Blender's Geometry Nodes is a target, so is the part of Blender's shaders that
survives a glTF export, so is Blade. There is one file per target, [`targets/<name>.json`](../targets/),
and no target is defined from another: no `extends`, no hierarchy.

The language speaks Blender. Its node names are Blender's (the UI name in one word,
[reference](reference.md)), and its formulas (`a + b`, `n ⋅ up`, `h > 0.5`) are Math, Vector Math,
Compare and Boolean Math nodes. A destination that is not Blender does not get a dialect of its
own: it declares **translators** from a Blender target to itself.

## What a text says, what the tool says

- `// @target gltf` at the head of a text is a promise, and it is optional. The editor points at
  everything the text uses outside that target, and `base-node check` fails on it.
- Without `@target` there is nothing to respect. The tool **infers** the targets that accept the
  text and shows them:

  ```text
  Compatible: blender-compositor
              blade (translated from blender-compositor)
  Outside:    gltf — Glare (line 12)
  ```

  An inference holds the targets the text fits (by name, with the target each translated one comes
  from), those it does not with their issues (by name), and for each graph, in the order of the
  text, the targets it fits as it is. What it shows names the targets fitted as they are first.

A text fits a target when every graph it holds fits it: its kind is one of the target's kinds, the
types of its sockets, its zones and every node it calls are the target's. A formula counts as the
node it writes (`+` is Math or Vector Math, `<` is Compare, or Math in a target that has no Compare,
`and` is Boolean Math). A call to a
graph of the text or of a module it uses is not a node: the graph it calls must fit the target too,
and its first issue is one of the text, of kind `graph` (`with_alpha (node SetAlpha)`). The module
of a `use` is found among the target's [bridges](#the-file-of-a-target), then in the standard
library (`stdlib/`). A module found nowhere is not followed: its calls are taken on trust, and a
`use` of every graph of it (`use mine`) lets any call be one of its graphs.

A target is named by its name only. A name that is not a target's is an error: Python raises
`ValueError`, Rust returns `Err(UnknownTarget)`, with the same message.

## The file of a target

```json
{
  "name": "blade",
  "description": "Blade's Pixel Nodes",
  "kinds": ["pixel"],
  "types": ["Float", "Int", "Bool", "Vector", "Color", "Image"],
  "zones": [],
  "nodes": ["Math", "Mix", "Blur", "Flatten", "Classifier"],
  "translators": {
    "blender-compositor": {
      "kinds": {"compositor": "pixel"},
      "nodes": {
        "Blur": "Blur",
        "RGBCurves": "Curves",
        "MixRGB": {"node": "Mix", "inputs": {"fac": "factor"}, "settings": {"blend_type": "mode"}},
        "Kuwahara": "blender_interop::kuwahara"
      }
    }
  },
  "bridges": ["blade/blender_interop.bn"]
}
```

| Field | Meaning |
|---|---|
| `kinds` | The words a graph may start with: `geometry`, `shader`, `compositor`, `pixel`… |
| `types` | The socket types its graphs may have |
| `zones` | `repeat`, `foreach`, `simulate`, `closure` |
| `nodes` | The node names it accepts, implicit inputs (`Position`, `Index`…) among them |
| `translators` | For each target it translates from: its kinds, and for each node of that target the node it becomes, or the graph of a bridge (`module::graph`) |
| `bridges` | Modules shipped with the target, whose graphs stand for the nodes it has no node for: `.bn` files, by their path relative to the target's file; the module is the file's name (`blade/blender_interop.bn` is `blender_interop`) |
| `rules` | For an input of a node, what may feed it (see [Rules](#rules)) |
| `inputs` | The inputs of the nodes the rules name, in order: a positional argument takes the input of its place. For a pattern, its placeholders |
| `outputs` | The outputs of the nodes the rules name, in order: a call taken whole is its first |
| `settings` | The settings the rules name, with their defaults: a call that does not write one has its default |
| `vectors` | The sockets, `Node.socket`, that hold a color or a vector: a multiply on such an input is a Mix, a `*` with such a value a Vector Math |
| `patterns` | Expressions a rule names as a feed, whose placeholders are the pattern's `inputs` |
| `folded` | The nodes the destination computes when their inputs are values: a call of one on values is a constant |
| `groups` | Node groups the destination reads as nodes: the start of the group's name, and the node the rules name it |
| `once` | The nodes the destination reads one of: the last the material reaches, its inputs walked in order |

A translator only renames. A node becomes one node: its new name, and the inputs and settings whose
names change. What is more than a rename, one node of the source made of several nodes of the
target, is a **bridge**: a graph of one of the target's bridge modules, which the translator names
by its module, `"Kuwahara": "blender_interop::kuwahara"`, or with its renames,
`{"node": "blender_interop::kuwahara", "inputs": {"size": "radius"}}`. The translator stays a
table, and a bridge is just a module: a text may `use` it, and the tools check it as any other.

- A node sent to a bridge is translated when the target has that graph and the graph fits the
  target. One that does not is an issue of kind `graph` at the call: `blender_interop::kuwahara
  (node Median)`.
- `translate` makes the call a call of the module, `Kuwahara(image, size: 8.0)` becoming
  `blender_interop::kuwahara(image, size: 8.0)`, and the text gets `use blender_interop`, once.
- A check against the target finds its bridges as modules: the translated text fits `blade`, its
  calls of `blender_interop` followed into the bridge.

`blade` ships one bridge, [`targets/blade/blender_interop.bn`](../targets/blade/blender_interop.bn):
`kuwahara`, the compositor's Kuwahara made of a Median and a Bilateral.

A text fits a target **through a translator** from target `S` when it fits `S`, each of its kinds
has a translation and each node it calls is a key of the translator's `nodes` (and, for a bridge,
the bridge's graph fits the target). A node the
translator does not list is not translated, even when the target has a node of that name: listing
it (`"Blur": "Blur"`) is the promise that the two are the same.

## The targets

| Target | Kinds | Nodes |
|---|---|---|
| `blender-geometry` | geometry | Every Geometry Nodes node of Blender |
| `blender-gp` | geometry | Every Geometry Nodes node of Blender, on a Grease Pencil object |
| `blender-shader` | shader | Every shader node of Blender |
| `blender-compositor` | compositor | Every compositor node of Blender |
| `gltf` | shader | The shader nodes Blender's glTF exporter reads: Principled BSDF, Emission, image textures and their channels, normal maps, UVs, unlit, alpha clip, anisotropy, and [rules](#rules) on what feeds what, checked against the exporter |
| `blade` | pixel | Blade's Pixel Nodes, a translator from `blender-compositor`, and a bridge, `blender_interop` |

The node lists of `blender-geometry`, `blender-gp`, `blender-shader` and `blender-compositor` are
written from `targets/backends/blender-<x.y>.json`, the nodes Blender reports for each kind of tree
(`python -m base_node.targets` rewrites them; a test checks they agree). A graph of math only fits
all of them: Blender builds it in any kind of tree. `blender-gp` is what Blender accepts in Geometry
Nodes on a Grease Pencil object, which is every Geometry Nodes node: Grease Pencil is not 2D only,
and the target does not filter what Blender takes. The others are written by hand.

## A target and its destination

A target says what a text may use; it does not run it. The destination keeps its own reasons to
refuse a text that fits (a socket Blender links nowhere, a value out of range): the target only
narrows what reaches it.

## Rules

Some destinations read patterns rather than nodes. Blender's glTF exporter exports a Math that
multiplies a texture by a constant; the same Math between two textures is lost. A list of nodes
cannot say that. The `rules` of a target can: for an input of a node, the feeds it accepts.

```json
"rules": {
  "PrincipledBSDF.roughness": ["constant", "ImageTexture", "SeparateColor", "ImageTexture × constant"],
  "PrincipledBSDF.normal": ["constant", "NormalMap"],
  "PrincipledBSDF.*": ["constant"],
  "NormalMap.color": ["ImageTexture"],
  "ImageTexture.vector": ["UVMap", "TextureCoordinate.uv", "Attribute.vector", "Mapping"]
}
```

The key is `Node.input`, the input by its key (`base_color`, `Value_001`); `Node.*` is every other
input of the node. A feed is one of:

| Feed | What it takes |
|---|---|
| `constant` | A value rather than a link: a literal, a tuple of them, a parameter of the graph, a setting's value (`MULTIPLY`), or a call of a `folded` node on values (`0.5 * 0.4`, the destination computes it). An input the call does not give keeps its default, a constant |
| `Node` | Any output of a call to `Node`, the call itself among them (`t`, `t.color`, `t.alpha`) |
| `Node.output` | That output of a call to `Node`, named (`TextureCoordinate().uv`); the call taken whole is its first output (`t` is `t.color`) |
| `a × b × c` | A multiply of `a` by the others, as the input's type has it: on an input of `vectors`, a Mix whose `blend_type` is `MULTIPLY`, factor 1 and `data_type` `RGBA` (written, or taken from a tuple of 4 among its inputs); on another input a Math whose operation is `MULTIPLY`, the node or the `*` formula of two numbers. The others are peeled off one at a time from the outside, in any order: `ImageTexture × ColorAttribute × constant` takes `Mix(a: (0.8, 0.8, 0.8, 1.0), b: Mix(a: ColorAttribute().color, b: t.color, …), …)`, not a Mix of three |
| `(0.0, 0.0, constant)` | A tuple of these items: numbers, or `constant` for any value. An input left to its default is taken |
| `Pattern` | A value of the shape of one of the expressions of `patterns[Pattern]` (see below) |
| `any` | Anything: the destination does not read it, and the calls in it are not checked |
| `0.0`, `true` | That value, or an input left to its default: a rule writes a number only for an input whose default it is (a test checks it against Blender's) |
| `≠ 0.0` | A constant other than that number; an input left to its default is not |
| `named` | A name bound to a number (`lo = 150.0`): a named constant is a node of its own, a Value |

A rule on a setting (`ImageTexture.extension`, one of `settings`) lists the values it takes:
`["REPEAT", "EXTEND", "MIRROR"]`, or `any` for any value written. A setting without a default
(`null`, as an image) that the call does not write is `none`. A call that does not write the setting has its default, which the
rule takes or refuses as any value: `Tangent()` is `RADIAL`.

A **pattern** is a `.bn` expression whose free names, its `inputs`, are placeholders:

```json
"patterns": {"AlphaClip": ["round(value)", "Math(value, threshold, operation: GREATER_THAN)"]},
"inputs": {"AlphaClip": ["value", "threshold"]},
"rules": {"AlphaClip.value": ["ImageTexture", "SeparateColor"], "AlphaClip.threshold": ["constant"]}
```

A value has its shape when its nodes are the ones written, with the settings written (a formula
writes its own: `1.0 - x` is a Math `SUBTRACT`, `round(x)` a Math `ROUND`) and their inputs in turn
of the shape written there; an input or a setting the pattern does not write may be anything. A
placeholder takes any value its rule `Pattern.placeholder` takes, anything without one, and the
same value wherever it appears in the patterns of one call: `s` in `s.z * strength` and
`atan2(s.y, s.x)` is one Separate XYZ. A pattern speaks for the calls it writes: they are not
checked on their own, as the destination reads them as part of it.

Two more kinds of key:

- `Node.a+b`, rules on several inputs together: their values, as a tuple, have the shape of one of
  the patterns listed, written as tuples. It takes inputs the rules of each refuse: the exporter
  reads the alpha of a color attribute only with its color, `"PrincipledBSDF.base_color+alpha":
  ["VertexColor"]`. An input written `Other.input` is that input of the first call to `Other` in
  the graph, and nothing a feed takes without one: `"MaterialOutput.volume+glTFMaterialOutput.Thickness"`.
- `Node`, a rule on the call as a whole: the call has the shape of one of the patterns listed, or
  it is refused. `"TransparentBSDF": []` refuses any Transparent BSDF no pattern writes.

A name follows what it holds: `t = ImageTexture(…)` then `base_color: t` is a texture. A rule
reads one link, and the node at its end has rules of its own: `"PrincipledBSDF.normal": ["NormalMap"]`
and `"NormalMap.color": ["ImageTexture.color"]` make a normal map of an image, and nothing else. An
input without a rule, of a node without `Node.*`, takes what the node lists allow.

A call to a graph of the text, or of a module it uses, is read through, as Blender reads a group:
its return is the value, its parameters the values the call gives (or their defaults), and the
calls in its body are checked there, at the line of the call. A graph alone takes its parameters
as constants. A graph whose name starts as one of `groups` is not read through: its call is a call
to the node `groups` names, every input given by the name of its parameter, the value of the call
or the parameter's default (0 without one). A parameter whose name is not, to the letter, one of the
node's `inputs` is written `name (not read)`: the destination reads its inputs by name. The return of a material, a `shader(material: true)` graph or a shader graph of the
text no other graph calls whose first output is a Shader, feeds a call to `MaterialOutput`, at the
line of the return: its rules read the surface, the volume, the displacement and the thickness.
Of a node of `once`, the calls the material reaches before the last are refused: `PrincipledBSDF
(not the one read)`.

A link the rules refuse is an issue of kind `link`, at the line of the call, named by the input and
what feeds it: `PrincipledBSDF.roughness ← Math(NoiseTexture)`, `PrincipledBSDF.base_color ←
Mix(ImageTexture, ImageTexture)`, a setting by its value: `ImageTexture.extension ← CLIP`; a call
refused as a whole by itself: `MixShader(ImageTexture, TransparentBSDF, PrincipledBSDF)`. A target
without `rules` refuses no link.

### What `gltf` accepts

Read from the exporter (`io_scene_gltf2/blender/exp/material`) of Blender 5.3, and checked against
it: `base-node-for-blender/tests/test_gltf_export.py` builds each case of
[`conformance/gltf-cases.json`](../conformance/gltf-cases.json) into a material, exports it to a
`.glb` and reads it back. A case the rules accept shows its texture, factor, extension or alpha
mode in the glTF; a case they refuse shows what is lost. The Python and Rust tests check the
rules on the same cases.

| Input | Feeds |
|---|---|
| `MaterialOutput.surface` | A `PrincipledBSDF`, an `Emission`, a `Background` (unlit), or a `MixShader` of an unlit pattern |
| `MaterialOutput.volume` | A `VolumeAbsorption` of constant color and density, with a glTF Material Output whose `Thickness` is not 0 (`KHR_materials_volume`); else nothing linked |
| `MaterialOutput.displacement`, `thickness` | Nothing linked: the exporter reads neither |
| `PrincipledBSDF.base_color`, `Background.color` | A constant, a texture's color, a color attribute's (`ColorAttribute`, `Attribute`), the texture times a color attribute, either times a constant |
| `PrincipledBSDF.alpha` | A constant, a texture or a channel of one, either times a constant; an alpha clip of one of them; a color attribute's alpha as above, when `base_color` has a color attribute too |
| `metallic`, `roughness`, `specular_ior_level`, `transmission_weight`, `coat_weight`, `coat_roughness`, `sheen_roughness` | A constant, a texture or a channel of one, either times a constant |
| `thin_film_thickness`, `thin_film_ior` | Their defaults (0, 1.33); with a glTF Material Output that has `Iridescence Factor` and `Iridescence Thickness Minimum` inputs, constants, or a thickness `Mix(SeparateColor(t.color).red, lo, hi)` of two named constants, `lo` given to `Iridescence Thickness Minimum` too (`KHR_materials_iridescence`) |
| `thin_wall`, `diffuse_roughness`, `subsurface_weight`, `transmission_dispersion_scale` | Their defaults: the exporter reads none of them |
| `coat_tint`, `coat_ior` | Their defaults, or any constant when `coat_weight` is 0: glTF's clearcoat has neither |
| `emission_color`, `specular_tint`, `sheen_tint`, `Emission.color` | A constant, a texture's color, either times a constant |
| `normal`, `coat_normal` | A constant, or a `NormalMap` of an image texture's color, tangent space and OpenGL convention, with a constant strength |
| `anisotropic`, `anisotropic_rotation`, `tangent` | Constants; or a texture's color, either times a constant (read as a gray texture); or the pattern the exporter writes: `s = SeparateXYZ(VectorMath(t.color, (2.0, 2.0, 1.0), (-1.0, -1.0, 0.0), operation: MULTIPLY_ADD))`, `anisotropic: s.z * strength`, `anisotropic_rotation: (atan2(s.y, s.x) + rotation) / 6.283185`, `tangent: Tangent(direction_type: UV_MAP)` |
| `Background.strength` | 1: the exporter reads a Background as unlit, without its strength |
| Every other input of `PrincipledBSDF`, `Emission`, `Background`, `VolumeAbsorption` | A constant: the exporter reads its value, or it changes nothing the glTF shows (the radius of a subsurface of weight 0) |
| `glTFMaterialOutput` | A group named `glTF Material Output` (or `glTF Settings`): `Occlusion` 1, a texture or a channel of one, or `Mix(strength, (1.0, 1.0, 1.0, 1.0), it)` (an `occlusionTexture` and its strength); `Thickness`, `Iridescence Factor` a constant, a texture or a channel, either times a constant; `Iridescence Thickness Minimum` a constant; `Dispersion` 0, or a constant with a `Thickness` that is not 0 (`KHR_materials_dispersion` needs the volume); any other input a constant |
| `MixShader` | An unlit pattern: `MixShader(LightPath().is_camera_ray, TransparentBSDF(), Emission(color: c))`, the color as a base color, or a `Background` for the Emission; and `MixShader(alpha, TransparentBSDF(), <that unlit Emission>)`, the alpha as above (alpha `BLEND`, or `MASK` with a clip). The Emission's strength is 1 and the Transparent BSDFs are white: the exporter reads neither, nor the shader other rays see |
| `TransparentBSDF`, `LightPath` | Only in those patterns |
| `ImageTexture.vector` | `UVMap`, `TextureCoordinate().uv`, an `Attribute`'s vector (a named UV map), or a `Mapping` of one of them with constant location and scale, a rotation around Z alone, of type Point, Texture or Vector |
| `ImageTexture` settings | An `image`; `projection` Flat, `interpolation` Linear or Closest, `extension` Repeat, Extend or Mirror: Cubic is written Linear, Clip as Extend, a Box projection as Flat, no image as no texture |
| `PrincipledBSDF`, once | The exporter reads the last Principled BSDF the surface reaches, its inputs walked in order (in `MixShader(0.5, a, b)`, `b`); a Principled BSDF no link reaches is not in the material |
| `Attribute.attribute_type`, `Tangent.direction_type`, `NormalMap.space`, `NormalMap.convention` | Geometry; UV Map; Tangent; OpenGL |

An **alpha clip** is `round(a)`, `a > cutoff` (`Math(a, cutoff, operation: GREATER_THAN)`), `cutoff < a`
(`Math(cutoff, a, operation: LESS_THAN)`), or `1.0 - ` the other two, which is `a >= cutoff` and
`cutoff <= a` (a shader tree has no Compare node: a comparison is these Math nodes there, and a rule
reads it as them): alpha mode `MASK`, the cutoff a constant. `folded` is
Math, Vector Math and Mix: Blender computes them on constants before the exporter reads the
material, a Separate Color it does not.
