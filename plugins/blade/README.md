# Base Node for Blade

Blade's Pixel Nodes for Base Node (`.bn`): the target `blade` (kind `pixel`), its translator from the
compositor graphs of `blender`, and its bridge module `blender_interop`, which stands for the nodes
Blade has not (Kuwahara). A text of Blender's compositor reaches `blade` through them:

```text
$ base-node check paint.bn
paint.bn:
  Compatible: blender, blade (translated from blender)
```

The chapter of the language is [spec/blade.md](spec/blade.md).

## Layout

| Path | Holds |
|---|---|
| [`targets/`](targets/) | `blade.json`, the target and its translator; `blade/blender_interop.bn`, its bridge |
| [`python/`](python/) | The package `base-node-blade` (`base_node_blade`): the folder of the targets, and `add()`; its tests |
| [`rust/`](rust/) | The crate `base-node-blade`: the targets built in, and `add()`; its tests |
| [`spec/`](spec/) | [`blade.md`](spec/blade.md) |

## What it needs

| Of | Version | For |
|---|---|---|
| The core, `base-node` (Python, Rust) | 1.0.0-rc.7 | Parsing and printing a text |
| Base Node for Blender, `base-node-blender` (Python, Rust) | 1.0.0-rc.7, with `add_targets` | The target format, the checker, `infer`, `translate`, the bridges |

Blender's library reads a target of another destination from that destination's library:

- Python: `base_node_blender.targets.add_targets(folder)`, or the entry point of the group
  `base_node_blender.targets` that `python/pyproject.toml` declares (`blade = "base_node_blade:TARGETS"`):
  installed, `base-node check` knows `blade`.
- Rust: `base_node_blender::targets::add_targets(files, bridges)` before the first check:
  `base_node_blade::add()` does it.

## Tests

`CORE` is a checkout of the core (`python/`, `rust/`), `BLENDER_LIB` one of Base Node for Blender
(`python/`, `rust/`); `rust/Cargo.toml` gives the same two paths to Cargo.

```bash
make test                          # make test-python test-rust
make test CORE=../.. BLENDER_LIB=../blender
```

License: [MIT](LICENSE-MIT) OR [Apache-2.0](LICENSE-APACHE).
