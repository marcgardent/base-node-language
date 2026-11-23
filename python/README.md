# base-node

Python reference implementation of Base Node (`.bn`), a text format for node graphs: the core of the
language (parser, formatter) and its command line, with no dependency. It knows no destination: a host
library gives a text its meaning for one, and adds its commands to `base-node`.

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
base-node parse file.bn
base-node ast file.bn
```

A host library installed adds its commands: its distribution declares a module with
`extend(subparsers, commands)` as an entry point of the group `base_node.cli`.

## Library

```python
import base_node as bn  # the core: the text, knowing no destination

ast = bn.parse(source)
formatted = bn.format_source(source)
```

The language is described in the repository: <https://github.com/marcgardent/base-node-language>.

License: MIT OR Apache-2.0.
