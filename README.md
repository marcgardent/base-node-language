# Base Node Language

Base Node (`.bn`) is a text format for node graphs: a graph is a function, a node a call. This
repository is its core: it reads a text into a syntax tree, prints it and formats it, in Python and in
Rust. The core knows no destination: a host library says what a kind of tree, a type or a node means,
and checks a text against it.

```bn
use math (bump)

geometry graph relief(geometry: Geometry, height: Float = 0.4 in 0.0..2.0) -> Geometry {
  "Displaces vertices along Z using a radial bump"
  h = bump(length(Position()) / 3.0, 0.5, 0.2) * height
  return SetPosition(geometry, offset: CombineXYZ(z: h))
}
```

To the core, `geometry`, `SetPosition` and `Geometry` are names. Base Node for Blender, the host of
Blender's node trees, is in [`plugins/blender/`](plugins/blender/).

## Layout

| Path | Holds |
|---|---|
| [`python/`](python/) | The Python package `base-node`: `base_node` (lexer, parser, printer, formatter, head of a file), `base_node_cli` (the `base-node` command line) |
| [`rust/`](rust/) | The crate `base-node`, `wasm32`-compatible: the same parser, printer and formatter |
| [`conformance/`](conformance/) | `.bn` cases and their expected syntax trees, read by the Python and the Rust tests |
| [`spec/`](spec/) | The language: [`reference.md`](spec/reference.md), [`versioning.md`](spec/versioning.md) |
| [`tools/`](tools/) | `bump.py` (writes the version everywhere it is written), `identifiers.py` (the characters of an identifier, from Unicode) |
| `plugins/` | Hosts, each with its own Makefile, packages and documents |

## Make

`make help` lists the targets. Those of the core:

| Target | Does |
|---|---|
| `make test` | `python-min`, `test-python`, `test-rust` |
| `make python-min` | Every tracked `.py` parses with the oldest Python `pyproject.toml` accepts (3.10, fetched by `uv`) |
| `make test-python` | The Python package (pytest) |
| `make test-rust` | The crate: `cargo fmt --check`, clippy, tests |
| `make identifiers` | Writes `python/base_node/identifiers.py` and `rust/src/identifiers.rs` from the Unicode of this Python |
| `make bump VERSION=x.y.z` | Writes the version everywhere it is written, in the core and each plugin |
| `make release` | Tags the head of `main` `vVERSION` and pushes the tag: the CI runs on it |
| `make ci` | Runs the CI on the pushed head of the current branch (`BRANCH=…`) |

When the checkout has `plugins/blender`, its targets run from here too (`test-web`, `test-blender`,
`test-promised`, `test-libraries`, `srt-check`, `extension`, `backend`, `names`, `docs`), and
`make test`, `test-python` and `test-rust` run its tests after the core's. Without it, these three run
the core's alone, and its targets stop with `make <target> needs plugins/blender`.

## Python (`python/`)

No dependency; Python 3.10 or later.

```bash
# From GitHub (pip / uv)
pip install "base-node @ git+https://github.com/marcgardent/base-node-language.git#subdirectory=python"

# From a local checkout
pip install -e ./python
```

```python
import base_node as bn

ast = bn.parse(source)                  # raises bn.BnError, its .diagnostics at their line and column
formatted = bn.format_source(source)    # the canonical layout, comments kept
head = bn.header(source)                # @module, @version, @edition, @target, @title, @author, @license
```

```bash
base-node fmt file.bn
base-node fmt --check file.bn
base-node parse file.bn
base-node ast file.bn
base-node --version
```

## Rust (`rust/`)

```toml
[dependencies]
# From GitHub
base-node = { git = "https://github.com/marcgardent/base-node-language.git", branch = "main" }

# Or from a local checkout
# base-node = { path = "../base-node-language/rust" }
```

```rust
use base_node::{format_source, parse};

let file = parse(src, "example.bn")?;
let formatted = format_source(src, "example.bn")?;
```

## A host

A host library depends on the core and gives a text its meaning for one destination.

- **Python**: its distribution depends on `base-node`, and adds its commands to `base-node` by an
  entry point of the group `base_node.cli`: a module with `extend(subparsers, commands)`, which adds
  its own subcommands to `subparsers` and its options to the core's (`commands["fmt"]`).

  ```toml
  [project]
  dependencies = ["base-node"]

  [project.entry-points."base_node.cli"]
  myhost = "myhost.cli"
  ```

- **Rust**: its crate depends on `base-node`, by git or by path.

A host reads its own directives from the head of a file with `read_head`
([reference, 1.1](spec/reference.md#11-file-head)).

## Conformance

[`conformance/manifest.json`](conformance/manifest.json) lists `.bn` files, each with its graphs and
its expected syntax tree (`<name>.json`); the `*-cases.json` files hold texts, each with how it prints
back or the error that refuses it, at its line and column. The Python tests
(`python/tests/test_conformance.py`) and the Rust tests (`rust/tests/conformance.rs`) read the same
files: both implementations agree on every case.

## License

The core (`python/`, `rust/`, `conformance/`, `spec/`, `tools/`): [MIT](LICENSE-MIT) OR
[Apache-2.0](LICENSE-APACHE). A plugin says its own in its folder.
