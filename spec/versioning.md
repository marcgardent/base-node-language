# Base Node (`.bn`) Versioning & Evolution Specification

This document defines the versioning scheme, stability guarantees, and lifecycle management of the Base Node (`.bn`) language and of its core: the grammar and the reference implementations, in Python and in Rust. A host versions what is its own (its library, its targets, its modules) in its own documents.

---

## 1. The Versioning Tiers

The core separates two tiers:

```
┌────────────────────────────────────────────────────────┐
│ Tier 1: Language Edition (Syntax & Grammar)            │
│         e.g., Edition 2026                             │
└──────────────────────────┬─────────────────────────────┘
                           │
┌──────────────────────────▼─────────────────────────────┐
│ Tier 2: Toolchain & Reference Packages                 │
│         Python: base-node 1.0.0rc7                     │
│         Rust:   base-node 1.0.0-rc.7                   │
└────────────────────────────────────────────────────────┘
```

### The core and its hosts

The **core** is the language and nothing of a destination: it reads a text, prints it and formats
it, in Python and in Rust. It names no node, no socket, no kind of tree and no target.

A **host library** gives a text its meaning somewhere: its types, its formulas (`a + b` is a node of
the host), its zones, its checker, its targets and its converters. It is code as much as data: each
host writes it as it suits it, on the core.

| Part | Where | Holds |
|---|---|---|
| Core | `python/base_node`, `rust/` (crate `base-node`) | Lexer, parser, tree of the text, printer, formatter, head of a file, errors |
| `base-node` command line | `python/base_node_cli` | The core's commands, `fmt [--check]`, `parse` and `ast`; a host library installed adds its own, by an entry point of the group `base_node.cli` |

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

The parser does it, in Python (`base_node.parse`) and in Rust (`base_node::parse`), and so does everything that reads a text through it: the formatter, the commands `fmt`, `parse` and `ast`, and every host. `header` says it with the other errors of the head. The editions a reader knows are `base_node.EDITIONS` (`base_node::EDITIONS`), the latest last.

---

## 3. Lifecycle & Stability Policy (Pre-LTS vs LTS)

### Phase 1: Pre-LTS (`0.x.y`) — Active Rapid Iteration
- **Current status**: Version `1.0.0-rc.7`.
- **Policy**: **No backwards compatibility guarantee prior to LTS 1.0**.
  - Breaking changes to the grammar, the syntax tree or the interface of the core may occur between minor versions (`0.7` $\to$ `0.8`).
  - No deprecated alias shims or legacy wrappers are retained in the repository.

### Phase 2: Long-Term Support (`1.0.0 LTS`)

One number, `1.0.0`, for the specification and the Python and Rust packages of the core. A host
library released with the core takes the same number, and says what it promises. What the number
promises is not the same for each part of the core:

| Part | Under the promise | Outside it |
|---|---|---|
| Language | The grammar of Edition 2026 and the limits of the [reference](reference.md) | — |
| Tools | The interface of the core, in Python and in Rust, and the `base-node` command line | The interface a host library gives: its host says |

- **Strict Semantic Versioning (SemVer 2.0.0)** on what is under the promise:
  - **`MAJOR`**: a text that was read is refused, or reads as another syntax tree.
  - **`MINOR`**: new syntax every older text ignores, new functions of the core.
  - **`PATCH`**: fixes, optimizations, documentation.
- **An edition only grows.** After 1.0.0 nothing is taken out of Edition 2026; a change that breaks a text is a new edition. A reader refuses a text whose `@edition` it does not know.
- **Deprecation Cycle**: what is under the promise and planned for removal remains deprecated for at least one minor release cycle.

### Before 1.0.0

- [x] The core apart from every host library, in Python and in Rust: it names no destination, and a checkout of the core alone builds and passes its tests.
- [x] A call takes a body (`repeat(…) -> { … }`) and a graph may have no name (`graph(…) -> … { … }`): no zone is a word of the language.
- [x] A reader refuses an edition it does not know.
- [x] A changelog, and one command that writes the version everywhere it is written (`make bump`).

---

## 4. Tier 2: Toolchain & Implementation Synchronicity

The packages of the core share a synchronized version number:

| Component | Path | Version Scheme |
|---|---|---|
| Python reference package | [`python/pyproject.toml`](../python/pyproject.toml) | PEP 440 (`1.0.0rc7`) |
| Rust WASM crate, the core | [`rust/Cargo.toml`](../rust/Cargo.toml) | SemVer (`1.0.0-rc.7`) |

A pre-release is written in SemVer (`1.0.0-rc.1`) everywhere but in the Python package, whose `version` and
`__version__` take the PEP 440 form of the same version (`1.0.0rc1`): Cargo refuses that form.

### CLI Version Reporting

Running `base-node --version` reports:
```text
base-node 1.0.0rc7 (Language Edition 2026, Stdlib 1.0.0-rc.7)
```

---

## 5. Glossary

| Term | Meaning |
|---|---|
| **Edition** | The grammar: tokens, keywords, syntax. Named by a year (`2026`). It only grows after 1.0.0 |
| **Specification** | The [reference](reference.md) and this document, at one version |
| **Core** | The language as a library, in Python and in Rust: it reads, prints and formats a text, and knows nothing of a destination |
| **Host library** | What gives a text its meaning for one destination: types, formulas, checker, targets, converters |
| **Host** | A program that uses the core and a host library: the command line with a host library installed, an editor, an exporter |
| **Target** | What one destination accepts: kinds of tree, types, zones, nodes. Its host library defines it; a text promises some with `@target` |
| **Module** | A `.bn` file a `use` names, by the `@module` of its head |
| **Toolchain** | The Python and Rust packages of the core, and the command line |
| **Stable / experimental** | Under the promise of 1.0.0, or not yet |
| **Deprecated** | Still there and working, with a warning, for at least one minor version before it is removed |
| **LTS** | The 1.x line: what is under the promise does not break before 2.0.0 |
