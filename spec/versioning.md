# Base Node (`.bn`) Versioning & Evolution Specification

This document defines the versioning scheme, stability guarantees, and lifecycle management for the Base Node (`.bn`) ecosystem: the language grammar, the standard library (`stdlib/`), the targets, and the reference implementations (Python, Rust, Blender extension).

---

## 1. The Four Versioning Tiers

The `.bn` ecosystem separates concerns across four distinct tiers:

```
┌────────────────────────────────────────────────────────┐
│ Tier 1: Language Edition (Syntax & Grammar)            │
│         e.g., Edition 2026                             │
└──────────────────────────┬─────────────────────────────┘
                           │
┌──────────────────────────▼─────────────────────────────┐
│ Tier 2: Targets (what each destination accepts)        │
│         e.g., blender, blender@5.3 gltf, blade         │
└──────────────────────────┬─────────────────────────────┘
                           │
┌──────────────────────────▼─────────────────────────────┐
│ Tier 3: Standard Library Modules (stdlib/)             │
│         e.g., math@1.0.0-rc.4, curves2d@1.0.0-rc.4          │
│         Manifest: stdlib/manifest.json                 │
└──────────────────────────┬─────────────────────────────┘
                           │
┌──────────────────────────▼─────────────────────────────┐
│ Tier 4: Toolchain & Reference Packages                 │
│         Python: base-node 1.0.0rc4                      │
│         Rust:   base-node, base-node-blender 1.0.0-rc.4 │
│         Blender Extension: 1.0.0-rc.4                   │
└────────────────────────────────────────────────────────┘
```

---

## 2. Tier 1: Language Edition (`edition`)

To balance rapid language innovation with long-term code preservation, `.bn` uses **Language Editions** (inspired by Rust and WGSL epochs):

- **Edition Identifier**: A calendar year string, starting with `"2026"`.
- **Scope**: Lexical tokens, parsing rules, reserved keywords, and AST representation.
- **Backwards Compatibility**: A modern `.bn` compiler supporting Edition `2026` will always parse `2026` source code identically, even when future editions (e.g. `2028`) introduce new keywords or syntactic forms.

### Source Annotation (Pragma)

Source files can optionally declare their target edition in the file header:

```bn
// @edition 2026
```

When omitted, the text is read as the latest edition the reader knows.

A reader refuses a text whose edition it does not know, at the line of the directive, and reads none of it:

```text
later.bn:1:13  @edition '2028': not an edition this reader knows (2026)
```

The parser does it, in Python (`base_node.parse`) and in Rust (`base_node::parse`), and so does everything that reads a text through it: the formatter, `base-node check`, `fmt`, `parse` and `ast`, the Blender add-on when a text is imported, pasted, checked or applied. `header` says it with the other errors of the head. The editions a reader knows are `base_node.EDITIONS` (`base_node::EDITIONS`), the latest last.

---

## 3. Tier 2: Targets (`targets/`)

A target is what one destination accepts: one file per destination, `targets/<name>.json`, and no
target defined from another. Its fields and the way a text is checked against it are in
[targets](targets.md).

- `blender` is a picture of Blender's catalog, so it is named by Blender's version and not designed
  here. Each version has a catalog, `targets/blender/<x.y>.json`, written from
  `targets/backends/blender-<x.y>.json`, what that Blender reports for each kind of tree:

  | Name | Means |
  |---|---|
  | `blender@5.3` | The catalog of Blender 5.3 |
  | `blender@5.2-lts` | The catalog of Blender 5.2 LTS. An LTS of Blender says so in its name, as a reminder |
  | `blender` | Every version this version of Base Node promises: a text fits `blender` when it fits each of them. The modules of `stdlib/` promise it |
  | `blender@lts`, `blender@latest` | Aliases for a command line and a CI (`base-node check --target blender@latest`): the newest LTS and the newest version there is a catalog of. Refused in the `// @target` of a text: its promise would change with each release of Blender |
  | `blender@5.3 gltf`, `… eevee`, `… cycles` | A variant: the shader nodes one consumer accepts, after the target, a space apart. `blender gltf` is every promised version with that variant. `eevee` and `cycles` are experimental |

- The promised versions are one list, `promised` in [`targets/blender.json`](../targets/blender.json).
  The policy is Blender's LTS (5.2) and its latest version (5.3 today). This version of Base Node
  has the catalogs of both, written from Blender 5.2.4 LTS and Blender 5.3.0, and promises both:
  `blender@lts` is `blender@5.2-lts`, `blender@latest` is `blender@5.3`. Adding a version is its
  catalog (`make backend` run with that Blender) and its number in `promised`.
  [What 5.3 has that 5.2 has not](targets.md#what-blender-53-has-that-blender-52-lts-has-not) is
  outside `blender`: a text that uses it promises `blender@5.3`.
- The variants (`gltf`) and the other targets (`blade`) are written by hand, and change with their destination.
- `blade` and `materialx` belong to other projects: they leave this repository before 1.0.0, each for
  the repository of its destination.
- A target added, or a node added to one, changes no text that fits it; a node taken out of one may.

### The core and its hosts

The **core** is the language and nothing of a destination: it reads a text, prints it and formats
it, in Python and in Rust. It names no node, no socket, no kind of tree and no target.

A **host library** gives a text its meaning somewhere: its types, its formulas (`a + b` is a Math
node in Blender), its zones, its checker, its targets and its converters. It is code as much as
data: each host writes it as it suits it.

| Part | Where | Holds |
|---|---|---|
| Core | `python/base_node`, `rust/` (crate `base-node`) | Lexer, parser, tree of the text, printer, formatter, head of a file, errors |
| Blender library | `python/base_node_blender`, without `bpy`; `rust-blender/` for the targets | The schema of Blender's nodes, the formulas, the zones, the type checker, the graph it resolves, the targets of Blender by version and their variants, completion |
| Blender extension | `base-node-for-blender/`, with `bpy` | The builder and the reader of trees, the editor |
| `base-node` command line | `python/base_node_cli` | The commands; it uses the host libraries installed |
| Blade | Its repository, in Rust | Its own formulas, checker, target, and its translator from Blender's compositor |
| MaterialX exporter | Its repository | Its target and its writer, on the Blender library |
| `<bn-view>` | `web/`, Rust to wasm | The view of a text, on the core and the Blender library |

---

## 4. Tier 3: Standard Library (`stdlib/`)

The standard library modules provide reusable computational geometry, math, and stylization functions.

### The manifest: `stdlib/manifest.json` and the heads of the modules

[`stdlib/manifest.json`](../stdlib/manifest.json) holds what is the library's:

```json
{
  "stdlib_version": "1.0.0-rc.4",
  "edition": "2026",
  "description": "Standard Library for the Base Node (.bn) language"
}
```

Each module says the rest in the head of its `.bn` (below), so that adding a module adds its file
and edits no shared list. `base_node.manifest.manifest("stdlib")` reads them into one manifest, the
modules by name:

```json
"curves2d": {
  "name": "curves2d",
  "version": "1.0.0-rc.4",
  "edition": "2026",
  "tier": "free",
  "targets": ["blender"],
  "file": "curves2d.bn",
  "dependencies": ["math"],
  "description": "2D curves, resampling, curvature analysis, and path operations"
}
```

`tier` is `free` or `pro`. A free module is in this repository under MIT OR Apache-2.0 and uses free
modules only. A pro module belongs to a paid pack (`// @pack smart-materials`, `"pack"` in its
entry), installed in the *Module Folder* of the add-on preferences; it may use free modules. Its
`dependencies` are the modules its `use` lines name.

### Module Header Metadata

Every official `.bn` standard library file must include standardized metadata comments before its `use` imports:

```bn
// Base Node Standard Library — Module curves2d
// @module curves2d
// @version 1.0.0-rc.4
// @target blender
// @edition 2026
// @description 2D curves, resampling, curvature analysis, and path operations

use math (bump, fbm)
...
```

- `@module`: Canonical module identifier (matches filename without `.bn`).
- `@version`: Module SemVer version string.
- `@target`: The targets the module promises to fit: `blender` for every module, each graph checked against the nodes of its kind of tree (a text may promise several targets, one per graph). The CI holds it to them.
- `@edition`: Target language edition.
- `@description`: One line on what the module does, the `description` of its manifest entry.
- `@pack`: The paid pack of a pro module; a free module has none.

---

## 5. Lifecycle & Stability Policy (Pre-LTS vs LTS)

### Phase 1: Pre-LTS (`0.x.y`) — Active Rapid Iteration
- **Current status**: Version `1.0.0-rc.4`.
- **Policy**: **No backwards compatibility guarantee prior to LTS 1.0**.
  - Breaking changes to node names, signatures, or module structure may occur between minor versions (`0.7` $\to$ `0.8`).
  - No deprecated alias shims or legacy wrappers are retained in the repository (`stdlib/gp_tools2d.bn` was purged).
  - Canonical naming (`curves2d::`) is enforced strictly.

### Phase 2: Long-Term Support (`1.0.0 LTS`)

One number, `1.0.0`, for the specification, the standard library, the Python and Rust packages, the
web component and the Blender extension. What the number promises is not the same for each:

| Part | Under the promise | Outside it |
|---|---|---|
| Language | The grammar of Edition 2026 and the limits of the [reference](reference.md) | — |
| Standard library | The graphs of the free modules: their names, their inputs and outputs, in order, with their defaults | The packs: their versions and their stability are their own, not this document's |
| Tools | The interface of the core, in Python and in Rust, and the `base-node` command line | The interface of the Blender library: it may move while hosts are written against it |
| Blender | The versions named below, tested at each release | Any other version: best effort |

- **Strict Semantic Versioning (SemVer 2.0.0)** on what is under the promise:
  - **`MAJOR`**: a text that was read is refused or builds another tree; a graph, an input or an output of a free module is removed or renamed.
  - **`MINOR`**: new syntax every older text ignores, new graphs, new inputs with defaults, a new version of Blender, a version of Blender that Blender no longer maintains taken out.
  - **`PATCH`**: numerical fixes, optimizations, documentation.
- **An edition only grows.** After 1.0.0 nothing is taken out of Edition 2026; a change that breaks a text is a new edition. A reader refuses a text whose `@edition` it does not know.
- **How long.** The 1.x line is maintained as long as Blender maintains 5.2 LTS.
- **Deprecation Cycle**: Functions planned for removal must remain deprecated for at least one minor release cycle. A graph is marked with the option `deprecated`, with what to use instead: `geometry(deprecated: "use curl2") graph curl(…)`. It works as before, and every call of it is a warning, in `base-node check` and in the add-on's editor ([reference, 3](reference.md#3-graph-declaration)).

#### The versions of Blender

Promised by 1.0.0, and tested by the CI at each release:

- Blender **5.2 LTS**;
- the **latest** stable version of Blender (5.3 today).

The rule after that: the LTS versions Blender still maintains, and its latest stable version. A new
version of Blender is taken on a best effort: its catalog is written again (`make backend`), the
nodes it adds and removes are the changelog, and `blender@latest` moves with a minor version.

### Before 1.0.0

- [x] The core apart from the Blender library, in Python and in Rust: nothing of Blender in the core.
- [x] A call takes a body (`repeat(…) -> { … }`) and a graph may have no name (`graph(…) -> … { … }`): no zone is a word of the language.
- [x] One `blender` target by version, its variants `eevee`, `cycles`, `gltf`, its aliases.
- [x] A reader refuses an edition it does not know.
- [x] A graph marked `deprecated` warns whoever calls it.
- [x] A changelog, and one command that writes the version everywhere it is written (`make bump`).
- [ ] Blender 5.2 LTS: its catalog, its baselines, the CI. The catalog and the baselines are in,
  and the tests of the add-on and the third-party libraries pass with Blender 5.2.4; the CI has a
  job per version, which has not run yet. One module of `stdlib/`, of a pack, promises
  `blender@5.3` alone: it writes a Switch in a shader tree, which Blender 5.2 has not. A
  comparison in the compositor of Blender 5.2, which has no Compare node, is Math nodes, as in a
  shader tree.
- [ ] `blade` and `materialx` out of this repository.

### After 1.0.0

- Blender 4.5 LTS (maintained by Blender until July 2027).

---

## 6. Tier 4: Toolchain & Implementation Synchronicity

All tools and packages maintained within the repository share a synchronized version number:

| Component | Path | Version Scheme |
|---|---|---|
| Python reference package | [`python/pyproject.toml`](../python/pyproject.toml) | PEP 440 (`1.0.0rc4`) |
| Rust WASM crate, the core | [`rust/Cargo.toml`](../rust/Cargo.toml) | SemVer (`1.0.0-rc.4`) |
| Rust WASM crate, the Blender library | [`rust-blender/Cargo.toml`](../rust-blender/Cargo.toml) | SemVer (`1.0.0-rc.4`) |
| Blender Extension | [`base-node-for-blender/blender_manifest.toml`](../base-node-for-blender/blender_manifest.toml) | SemVer (`1.0.0-rc.4`) |
| Extension Repository Index | [`site/extensions/index.json`](../site/extensions/index.json) | SemVer (`1.0.0-rc.4`) |

A pre-release is written in SemVer (`1.0.0-rc.1`) everywhere but in the Python package, whose `version` and
`__version__` take the PEP 440 form of the same version (`1.0.0rc1`): Cargo and Blender's manifest refuse that form.

### CLI Version Reporting

Running `base-node --version` reports:
```text
base-node 1.0.0rc4 (Language Edition 2026, Stdlib 1.0.0-rc.4)
```

---

## 7. Glossary

| Term | Meaning |
|---|---|
| **Edition** | The grammar: tokens, keywords, syntax. Named by a year (`2026`). It only grows after 1.0.0 |
| **Specification** | The [reference](reference.md) and this document, at one version |
| **Target** | What one destination accepts: kinds of tree, types, zones, nodes. A file, `targets/<name>.json` |
| **Core** | The language as a library, in Python and in Rust: it reads, prints and formats a text, and knows nothing of a destination |
| **Host library** | What gives a text its meaning for one destination: types, formulas, checker, targets, converters. Blender's is in Python; Blade writes its own |
| **Host** | A program that uses the core and a host library: the command line, the Blender extension, Blade, an exporter, the web component |
| **Variant** | A part of a host's shader nodes that one consumer accepts: `eevee`, `cycles`, `gltf` |
| **Exporter** | A tool that writes a text as another format (MaterialX). It lives with its format, not here |
| **Standard library** | The modules of `stdlib/`, at one version, the specification's |
| **Module** | One `.bn` file of the standard library, free or pro |
| **Pack** | The pro modules sold together, with their showcases |
| **Toolchain** | The Python and Rust packages, the web component and the command line |
| **Extension** | The Blender add-on, *Base Node* |
| **Stable / experimental** | Under the promise of 1.0.0, or not yet |
| **Deprecated** | Still there and working, with a warning, for at least one minor version before it is removed |
| **LTS** | The 1.x line: what is under the promise does not break before 2.0.0 |
| **Promised Blender** | A version of Blender the CI tests at each release |
