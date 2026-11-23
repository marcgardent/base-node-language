# Blade

`blade` is the target of Blade's Pixel Nodes: the graphs of the kind `pixel`, their types, and the
nodes Blade has. It is a target of the format Blender's library reads
([targets](../../blender/spec/targets.md#the-file-of-a-target)), with a translator from `blender`
and a bridge. This library makes it known to Blender's.

## The target

[`targets/blade.json`](../targets/blade.json) is the target:

| Field | Holds |
|---|---|
| `kinds` | `pixel`: a `pixel graph` |
| `types` | `Bool`, `Classes`, `Color`, `Float`, `Image`, `Int`, `Vector` |
| `zones`, `implicit` | None |
| `nodes` | Blade's nodes: filters (`Blur`, `Bilateral`, `Median`…), color, classes (`Classifier`, `FillClasses`…), detections (`DetectText`, `DetectLines`…) |
| `translators` | From `blender` (below) |
| `bridges` | `blade/blender_interop.bn` (below) |

## The translator from `blender`

A compositor graph of `blender` becomes a `pixel graph`: `"kinds": {"compositor": "pixel"}`. Each
node the translator lists becomes one node of Blade, renamed with its inputs and settings
([translators](../../blender/spec/targets.md#the-file-of-a-target)): `Blur` keeps its name and its
`size` is `radius`; `RGBCurves` is `Curves`; `InvertColor` is `Invert`, its `color` an `image`;
`MixLegacy` is `Mix`, `color1` and `color2` are `a` and `b`, `blend_type` is `blend`. A node it does not
list is not translated, even when Blade has a node of that name.

`translate` gives the text for Blade, and raises `ValueError` with the issues when the text does not
reach `blade` that way:

```python
import base_node as bn
from base_node_blender.targets import translate

pixel = bn.to_source(translate(bn.parse(source), "blender", "blade"))
```

## The bridge `blender_interop`

[`targets/blade/blender_interop.bn`](../targets/blade/blender_interop.bn) holds the compositor nodes
Blade has no node for, made of Blade's: `kuwahara`, the Kuwahara of the compositor, a `Median` then a
`Bilateral`. The translator names it, `"Kuwahara": "blender_interop::kuwahara"`:
`Kuwahara(image, size: 6.0)` becomes `blender_interop::kuwahara(image, size: 6.0)`, and the text gets
`use blender_interop`, once. A check against `blade` finds the bridge as a module, and follows the
calls into it.

## What the tools say

Without `@target`, the targets a text fits are inferred
([what a text says](../../blender/spec/targets.md#what-a-text-says-what-the-tool-says)). A compositor
text that Blade's translator carries says:

```text
Compatible: blender, blade (translated from blender)
```

A text promises one target per graph, the targets separated by commas: `// @target blender gltf,
blade` holds a shader graph to `blender gltf` and a pixel graph to `blade`.

## Making the target known

Blender's library reads its own targets; this library adds `blade` to them, after Blender's.

- **Python**: `base_node_blender.targets.add_targets(folder)` adds the targets of a folder, a
  `<name>.json` each and their bridges beside them. An installed library declares that folder instead,
  as an entry point of the group `base_node_blender.targets`, read at the first check: the package
  `base_node_blade` declares `blade = "base_node_blade:TARGETS"`, `TARGETS` being its folder of
  targets.
- **Rust**: `base_node_blender::targets::add_targets(files, bridges)`, before the first check, takes
  the `(name, JSON)` of each target and the `(path, text)` of each bridge. The crate
  `base-node-blade` does it in `add()`.

A target of a name Blender's library has already is refused.
