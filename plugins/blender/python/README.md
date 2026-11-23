# base-node-blender

Base Node (`.bn`) for Blender, in Python and with no dependency but the core (`base-node`): Blender's
nodes, the checker of a text against them, the targets (`blender`, its versions and its variants), and
the commands they add to `base-node`.

```bn
geometry graph relief(geometry: Geometry, height: Float = 0.4 in 0.0..2.0) -> Geometry {
  h = length(Position()) * height
  return SetPosition(geometry, offset: CombineXYZ(z: h))
}
```

## Install

```bash
pip install "base-node @ git+https://github.com/marcgardent/base-node-language.git#subdirectory=python" \
  "base-node-blender @ git+https://github.com/marcgardent/base-node-language.git#subdirectory=plugins/blender/python"
```

## CLI

Installed, `base-node` has the commands of this library too:

```bash
base-node fmt --names file.bn          # the inputs of Blender's nodes by name, without Blender
base-node check file.bn                # its @target, or the targets it fits
base-node check --target "blender gltf" file.bn
base-node check --target blender@latest file.bn   # the newest Blender this version knows
base-node docs --core ../..            # the site's reference pages, from a checkout
```

From a checkout, `python -m base_node_blender.cli` is the same `base-node`.

## Library

```python
import base_node as bn              # the core: the text, knowing no destination
import base_node_blender as blender  # Blender's nodes, the checker, the targets

ast = bn.parse(source)
formatted = bn.format_source(source)
issues = blender.check_target(ast, "blender gltf")  # [] when it fits
fits = blender.infer(ast).fits             # target -> None, or the target it translates from
```

The targets, the standard library and the Blender extension are described in the repository:
<https://github.com/marcgardent/base-node-language/tree/main/plugins/blender>.

License: MIT OR Apache-2.0.
