# Targets

A **target** is what one destination accepts: the kinds of tree, the types, the zones and the nodes
a text may use there. Blender is a target, with a catalog per version and variants (the part of its
shaders that survives a glTF export is one); so is Blade. There is one file per target,
[`targets/<name>.json`](../targets/), and no target is defined from another: no `extends`, no
hierarchy.

The language speaks Blender. Its node names are Blender's (the UI name in one word,
[reference](reference.md)), and its formulas (`a + b`, `n ⋅ up`, `h > 0.5`) are Math, Vector Math,
Compare and Boolean Math nodes. A destination that is not Blender does not get a dialect of its
own: it declares **translators** from Blender's target to itself.

## What a text says, what the tool says

- `// @target blender gltf` at the head of a text is a promise, and it is optional. Several targets
  are separated by commas (`// @target blender gltf, blade`): each graph then fits one of them. The editor points at
  everything the text uses outside that target, and `base-node check` fails on it.
- Without `@target` there is nothing to respect. The tool **infers** the targets that accept the
  text and shows them:

  ```text
  Compatible: blender, blender cycles, blender eevee
  Outside blade: kind shader (line 1) and 3 more
  Outside blender gltf: node NoiseTexture (line 2) and 1 more
  ```

  A variant of `blender` is about shaders: it is tried for a text that holds a shader graph, and
  not shown for another (a compositor text says `Compatible: blender, blade (translated from blender)`
  and nothing of `gltf`).

  An inference holds the targets the text fits (by name, with the target each translated one comes
  from), those it does not with their issues (by name), and for each graph, in the order of the
  text, the targets it fits as it is. What it shows names the targets fitted as they are first.

A text fits a target when every graph it holds fits it: its kind is one of the target's kinds, the
types of its sockets, its zones and every node it calls are the target's. A formula counts as the
node it writes (`+` is Math or Vector Math, `<` is Compare, or Math in a tree that has no Compare,
`and` is Boolean Math). A call to a
graph of the text or of a module it uses is not a node: the graph it calls must fit the target too,
and its first issue is one of the text, of kind `graph` (`with_alpha (node SetAlpha)`). The module
of a `use` is found among the target's [bridges](#the-file-of-a-target), then in the standard
library (`stdlib/`). A module found nowhere is not followed: its calls are taken on trust, and a
`use` of every graph of it (`use mine`) lets any call be one of its graphs.

A target is written as a name, an optional version after `@`, and optional words after a space:
`blade`, `blender@5.3`, `blender gltf`, `blender@5.2-lts gltf`. What a version and a word mean is
the target's to say; only [`blender`](#blender-by-version) has them. A name that is not a target's
is an error: Python raises `ValueError`, Rust returns `Err(UnknownTarget)`, with the same message,
`unknown target 'nope'; targets: blade, blender, blender@5.3; variants of blender, written after
it: cycles, eevee, gltf`. A name of before the one `blender` target gets what to write:
`…; 'gltf' is now 'blender gltf'`.

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
    "blender": {
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
| `zones` | `repeat`, `foreach`, `simulate`, the calls that take a body, and `closure`, a nameless graph ([reference, 6](reference.md#6-calls-with-a-body-and-nameless-graphs)) |
| `nodes` | The node names it accepts, implicit inputs (`Position`, `Index`…) among them |
| `translators` | For each target it translates from, by its name without a version: its kinds, and for each node of that target the node it becomes, or the graph of a bridge (`module::graph`) |
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
| `blender` | geometry, shader, compositor | Every node of Blender, by kind of tree, in every version promised ([below](#blender-by-version)) |
| `blender@5.3` | geometry, shader, compositor | The same in one version of Blender |
| `blender gltf`, `blender@5.3 gltf` | shader | A variant: the shader nodes Blender's glTF exporter reads: Principled BSDF, Emission, image textures and their channels, normal maps, UVs, unlit, alpha clip, anisotropy, and [rules](#rules) on what feeds what, checked against the exporter |
| `blender eevee`, `blender cycles` | shader | Variants, **experimental**: the shader nodes but those Blender says the engine does not take |
| `blade` | pixel | Blade's Pixel Nodes, a translator from `blender`, and a bridge, `blender_interop` |

The others are written by hand.

## `blender`, by version

Blender's target is a picture of Blender's catalog, so it is named by Blender's version.

| Name | Means |
|---|---|
| `blender@5.3` | The catalog of Blender 5.3 |
| `blender@5.2-lts` | The catalog of Blender 5.2 LTS. An LTS of Blender says so in its name, as a reminder: `blender@5.2` is refused, with what to write |
| `blender` | Every version this version of Base Node promises: a text fits `blender` when it fits each of them. The modules of `stdlib/` promise it |
| `blender@lts`, `blender@latest` | Aliases for a command line and a CI (`base-node check --target blender@latest`): the newest LTS, and the newest version there is a catalog of. A `// @target` that names one is an error, which says why (the promise would change with each release of Blender) and the version to write |
| `blender@5.3 gltf`, `blender eevee` | A variant, a word after the target, a space apart: the shader nodes one consumer accepts. Without a version it is every promised version with that variant. One variant at most |

**The files.** [`targets/blender.json`](../targets/blender.json) is the declaration, the one place
that lists the versions:

```json
{
  "name": "blender",
  "lts": ["5.2"],
  "promised": ["5.2", "5.3"],
  "variants": ["cycles", "eevee", "gltf"]
}
```

| Field | Meaning |
|---|---|
| `promised` | The versions a text that says `blender` has to fit. Each has a catalog (a test checks it) |
| `lts` | The versions Blender names LTS: their name ends in `-lts`, and `blender@lts` is the newest |
| `variants` | The files of `targets/blender/` that are variants |

`targets/blender/<x.y>.json` is the catalog of one version: `"blender"`, the version as Blender
says it, and `"trees"`, for each kind of tree (`geometry`, `shader`, `compositor`) its `types`,
`zones`, `implicit` inputs and `nodes`. It is written from `targets/backends/blender-<x.y>.json`,
the nodes that Blender reports (`make backend`, run with that Blender, writes both; a test checks
they agree). Every catalog found is a version: `blender@latest` is the newest.

The policy is Blender's LTS and its latest version. This version of Base Node has the catalogs of
Blender 5.2 LTS and of Blender 5.3, and promises both: `blender` means the two, `blender@lts` is
`blender@5.2-lts` and `blender@latest` is `blender@5.3`. A version without a catalog is the error
`target 'blender@4.5-lts': no catalog for Blender 4.5 in this version of Base Node (catalogs: 5.2, 5.3)`.
Adding a version is its catalog (`make backend`, run with that Blender) and its number in
`promised`; the tests of the add-on and the third-party libraries then run with that Blender too
(`make test-promised`).

**The kind of tree** is the first word of a graph, so the target does not repeat it. A graph is
checked against the tree of its kind: a `geometry graph` against the Geometry Nodes, their types
and zones, a `shader graph` against the shader nodes. A graph it calls is checked against that same
tree, whatever its own kind: Blender builds it there (a `geometry graph` of math called from a
`compositor graph` is built in the compositor). A text whose graphs are of several kinds fits
`blender` when each fits its tree. A graph of another kind (`pixel graph`) is outside, by its kind.
Geometry Nodes on a Grease Pencil object take every Geometry Nodes node: there is no target of
their own.

**Against several versions**, an issue every promised version has is `blender`'s; one that some
have names the version: `node 'Kuwahara' outside target 'blender@5.2-lts'`.

**A variant** is a file `targets/blender/<variant>.json`, of one of two shapes:

- A list of its own, with [rules](#rules): `gltf` has the `kinds`, `types`, `nodes` and rules of a
  target. In a version it keeps the nodes of its list that version has.
- The catalog less some nodes: `eevee` and `cycles` have `kinds` (`shader`) and `without`, the
  nodes the variant does not take, each with where Blender says so. The rest is the catalog's.

A variant takes the graphs of its `kinds` only: a `geometry graph` is outside `blender eevee`. In
`eevee` and `cycles`, a graph of another kind that a shader graph calls is built in the shader
tree, as in `blender`; in `gltf`, a called graph is of its kinds too.

### What Blender 5.3 has that Blender 5.2 LTS has not

The two catalogs, compared (`targets/blender/5.2.json` is Blender 5.2.4 LTS, `5.3.json` Blender
5.3.0). Blender 5.2 has no node, type, zone or implicit input that 5.3 has not: a text that fits
`blender@5.2-lts` fits `blender`. The zones and the implicit inputs are the same in both. What 5.3
adds is outside `blender`, and a text that uses it promises `blender@5.3`:

| Tree | Nodes of 5.3 alone | Types of 5.3 alone |
|---|---|---|
| `geometry` | `CombineList`, `Comment`, `ConstructCurves`, `DeactivateVoxels`, `GeometryMaterials`, `GetGridNames`, `GetVectorComponent`, `GreasePencilColor`, `GreasePencilDrawTime`, `GreasePencilFillID`, `GreasePencilOpacity`, `GreasePencilStrokeSoftness`, `GreasePencilStrokeVisibility`, `GridSolvePoisson`, `GridTopologyBoolean`, `ImportSPZ`, `NURBSOrder`, `NURBSWeight`, `RasterizePoints`, `SetPointCloudType` | |
| `shader` | `BooleanMath`, `Comment`, `EnableOutput`, `FindInString`, `FormatString`, `GetVectorComponent`, `IndexSwitch`, `IntegerMath`, `LightAccumulation`, `LightEvaluation`, `LightInfo`, `LightIterInternalInput`, `LightIterInternalOutput`, `MatchString`, `ReplaceString`, `ReverseString`, `SetStringCase`, `ShadowRaycast`, `SliceString`, `SpecialCharacters`, `String`, `StringLength`, `StringToValue`, `Switch`, `TrimString`, `ValueToString`, `Warning` | |
| `compositor` | `BitMath`, `BoneInfo`, `BooleanMath`, `CombineBundle`, `CombineTransform`, `Comment`, `Compare`, `FloatToInteger`, `GetBundleItem`, `GetVectorComponent`, `HashValue`, `ImportText`, `IntegerMath`, `IsViewport`, `MatrixSVD`, `RandomValue`, `SeparateBundle`, `SeparateTransform`, `StoreBundleItem` | `Bundle` |

Two of them reach further than their name:

- **`Compare` in the compositor.** A comparison (`a > b`, `==`, …) writes a Compare node where the
  tree has one, and a logical operator (`and`, `or`, `not`) a Boolean Math: the compositor of
  Blender 5.2 has neither. There a comparison of numbers is Math nodes that give a Float, 0 or 1,
  as in a shader tree ([reference, 5](reference.md#5-expressions)), and the same text builds in
  both versions; a comparison of vectors, colors or strings, and a logical operator, are outside
  `blender@5.2-lts`, and so is a graph of `math` that has one, called from a compositor graph
  (built in the compositor tree).
- **`Switch` in a shader tree**, and with it `IndexSwitch`: Blender 5.2 has `MenuSwitch` there alone.
  A ternary (`c ? a : b`) is no Switch there but a Mix, which both versions have.

The catalog lists the nodes by name; a node both versions have may still differ (the backends,
`targets/backends/blender-<x.y>.json`, say how). In 5.3 and not in 5.2:

| Tree | Node | In 5.3 alone |
|---|---|---|
| `geometry` | `BoneInfo` | outputs `envelope_distance`, `radius_head`, `radius_tail` |
| `geometry` | `CurveToMesh` | inputs `miter_scale`, `miter_scale_limit` |
| `geometry` | `ImportPLY` | its output is `geometry` (`mesh` in 5.2) |
| `geometry` | `MergeLayers` | inputs `mode`, `group_id` |
| `geometry` | `RealizeInstances` | input `preserve_normals` |
| `geometry` | `SetGreasePencilColor` | input `mode`, and its value `BOTH` |
| `geometry` | `SetGreasePencilDepth` | input `depth_order` |
| `shader` | `Attribute` | `attribute_type: LIGHT` |
| `shader` | `GlassBSDF` | inputs `anisotropy`, `rotation`, `tangent` |
| `shader` | `PrincipledBSDF` | inputs `transmission_dispersion_scale`, `transmission_dispersion_abbe_number` |
| `shader` | `VectorTransform` | `convert_from` and `convert_to`: `LIGHT` |
| `compositor` | `ConvertColorspace` | settings `from_interop_id`, `to_interop_id`; the color space `Rec.709-A` |
| `compositor` | `Switch` | a new one is a Color switch (`input_type: RGBA`); a Float one in 5.2 |

The `types` of a catalog are those of the sockets of its nodes. The interface of a shader group
is narrower in Blender 5.2: a `shader graph` takes no `String` input or output there, though a
shader node has one.

The target does not check these: a text that fits `blender` and writes one of them is refused by
Blender 5.2 when it is built ([a target and its destination](#a-target-and-its-destination)).

A module that is used is checked whole by the add-on: a `use` of a module one graph of which
writes a Switch in a shader tree is refused by Blender 5.2, whichever graph the text calls. The
modules of `stdlib/` that Blender 5.2 does not build promise `blender@5.3`, and so do the texts
that use them.

### `eevee` and `cycles` (experimental)

Blender does not report which engine renders a node. The two lists hold what Blender itself says,
and nothing else. They are one list for every version: Blender 5.2.4 and 5.3.0 say the same of the
nodes both have, and the four nodes of `cycles` that 5.2 has not (`LightAccumulation`,
`LightEvaluation`, `LightInfo`, `ShadowRaycast`) are out of its catalog already. The add-on's
tests read the list against the Blender that runs:

| Variant | Leaves out | Said by |
|---|---|---|
| `eevee` | `HairBSDF`, `PrincipledHairBSDF`, `RayPortalBSDF`, `SheenBSDF`, `ToonBSDF`, `LightOutput` | The Add menu, `scripts/startup/bl_ui/node_add_menu_shader.py`: offered when the engine is not EEVEE |
| `eevee` | `Script` | The same menu: offered only when the engine is Cycles |
| `eevee` | `Bevel` | Its tooltip: "only supported in Cycles" |
| `cycles` | `LightAccumulation`, `LightEvaluation`, `LightInfo`, `ShadowRaycast`, `SpecularBSDF`, `ShaderToRGB` | The same menu: offered only when the engine is EEVEE; and the tooltip of `ShaderToRGB`: "only supported in EEVEE" |

They are experimental: a node an engine ignores without Blender saying so in its menu or its
tooltip (an input, a setting or an output one engine does not read) is not in them, the manual has
not been read into them. A text that fits
`blender eevee` uses no node Blender says is not EEVEE's; it may still render differently.

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

### What the variant `gltf` accepts

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
