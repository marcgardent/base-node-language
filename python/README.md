# base-node

Python reference implementation of Base Node (`.bn`), a text format for node graphs: parser, formatter, target checker and CLI, with no dependency.

```bn
geometry graph relief(geometry: Geometry, height: Float = 0.4 in 0.0..2.0) -> Geometry {
  h = length(Position()) * height
  return SetPosition(geometry, offset: CombineXYZ(z: h))
}
```

## Install

```bash
pip install "base-node @ git+https://github.com/marcgardent/base-node-language.git#subdirectory=python"
```

## CLI

```bash
base-node fmt file.bn
base-node fmt --check file.bn
base-node check file.bn                # its @target, or the targets it fits
base-node check --target gltf file.bn
base-node ast file.bn
base-node docs                 # the site's reference pages, from a checkout of the repository
```

## Library

```python
import base_node as bn

ast = bn.parse(source)
formatted = bn.format_source(source)
issues = bn.check_target(ast, "gltf")  # [] when it fits
fits = bn.infer(ast).fits             # target -> None, or the target it translates from
```

The language, the targets, the standard library and the Blender extension are described in the repository: <https://github.com/marcgardent/base-node-language>.

License: MIT OR Apache-2.0.
