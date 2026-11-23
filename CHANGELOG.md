# Changelog

What changed for a user of the Base Node language and its core, by version. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); the versions follow
[Semantic Versioning](https://semver.org/) as [`spec/versioning.md`](spec/versioning.md) says.
Versions below 1.0.0 are pre-releases: the text format can change between them.

## [Unreleased]

### Repository

- Changed: this repository is the language, for developers: its specification (`spec/`), its core in
  Python (`python/`, the distribution `base-node`: `base_node` and the command line `base_node_cli`)
  and in Rust (`rust/`, the crate `base-node`), its conformance cases (`conformance/`) and `tools/`.
- Changed: Base Node for Blender (the add-on, `base-node-blender` in Python and in Rust, `<bn-view>`,
  the targets, the standard library, the corpus, the examples and the tutorials) lives in its own
  repository, https://github.com/marcgardent/base-node-for-blender, with its own version and
  changelog. Its site is https://blender.basenode.ludopant.com/, and so is its extension index,
  https://blender.basenode.ludopant.com/extensions/index.json. Blade lives in its own sources too.
- Changed: https://basenode.ludopant.com/ is the site of the language: one page, `site/`.

### Core

- Changed: `base-node` has the commands of the language, `fmt [--check]`, `parse` and `ast`. A host
  library adds its own through an entry point of the group `base_node.cli`, a module with
  `extend(subparsers, commands)`.
- Changed: the distribution `base-node` holds `base_node` and `base_node_cli` only.
- Removed: `STDLIB_VERSION` (Python and Rust) and `base_node.manifest`: a standard library is a
  host's. `base-node --version` says the version and the edition: `base-node 1.0.0rc8 (Language
  Edition 2026)`.

### Tools

- Changed: `tools/bump.py` writes and checks the version of the core only; `make test` runs
  `python-min`, `test-python`, `test-rust`, `wasm` and `bump-check`.
- Changed: the CI tests the core (Python, Rust, wasm32, versions); Pages publishes `site/`.

## [1.0.0-rc.7] - 2026-11-22

### Tests

- Fixed: the test of the identifier tables passes on a Python of an older Unicode (3.10 to 3.12), which
  does not have the four characters Unicode 15.1 let into its identifiers; the corpus test is skipped
  on Python 3.10, which reads no TOML.

## [1.0.0-rc.6] - 2026-11-22

### Language

- Fixed: the names a zone gives its body hold a value there, as its items do, so `<` after them
  compares: `iteration < n, m > (k)` in a `repeat`, `delta_time` in a `simulate`, `index` and
  `element` in a `foreach` are comparisons, no longer a call with types. The parsers of Python and
  Rust know these names (`conformance/chevron-cases.json`).
- Fixed, in the reference: a color is written as its tuple, `(1.0, 0.5, 0.0, 1.0)`. The reference
  told of a `#rrggbb` color value that no parser reads: `#` writes the color of a frame or of a look
  alone, and a value written so is refused (`expression expected, found '#ff8800'`), by the parsers
  of Python and Rust alike, whose messages now agree.
- Fixed: a quoted value of the head is a string of the language, its escapes read: a graph named
  with a `"` is named in `// @example` and `// @modifier` (`@modifier "the \"lift\""`), and so are
  `@title`, `@author`, `@license`, `@target`, `@module`, `@edition` and `@mesh` read. The quotes were
  cut off as written, and a name holding a `"` was refused.
- Changed, a text may need an edit: an identifier is Unicode's (UAX #31, XID_Start then
  XID_Continue, of Unicode 16.0), but for `·`, the dot product: one rule, from one table
  (`python/base_node/identifiers.py`, `rust/src/identifiers.rs`), for the lexers and the printers of
  Python and Rust, which each followed rules of their own. A name the printer wrote bare is now one
  every lexer reads back as that name: `é` written with a combining accent, a Devanagari or Bengali
  word, `a‿b` were printed bare and refused by the Python lexer; `Ⅻ`, `Ⓐ` were read by Rust and not
  by Python; `x²` and `½` are no names (written `"x²"`, key `x`). The digits of a number are ASCII's:
  `²` stopped the Python parser with a crash and `٣` read as the number 3, both are now refused as
  Rust refused them (`unexpected character '²'`). A key is always a bare identifier, the same in
  both languages (`conformance/name-cases.json`); a directive's name, `@module` and `@example`,
  follows the same rule.

## [1.0.0-rc.5] - 2026-11-22

### Language

- Changed, a text needs an edit: a node's inputs are given by name, the key of their socket:
  `Math[ADD](Value: a, Value_001: b)`, `CombineXYZ(x: p.x, y: p.y)`. A position depends on Blender's
  order of the sockets, which a setting or another version of Blender changes; a name does not. By
  position go only the values a name cannot tell, as a tree reads them back: the geometry a node works
  on (its first input, linked: the pipe's; the image a compositor node works on), the items of a
  switch (`IndexSwitch(0, a, b)`), the values of a multi-input with the inputs before them
  (`MeshBoolean[DIFFERENCE](a, b, c)`), and the fixed inputs of Separate Bundle, Evaluate Closure and
  Closure to List. A pipe into a node gives the input that goes first unnamed. Graphs, groups and
  functions take their values by position or by name.
- Changed, a text needs an edit: a string has escapes, `\"`, `\\`, `\n`, `\t`, `\r` and `\u{…}`, and any
  string reads back as it was; a backslash in a string starts one (`"C:\\Users"`), an unknown one is an
  error (`unknown escape '\q': …`). Tree → Text no longer turns a `"` into `'` nor a line break into a
  space, in a string, a name, a description, a label or a frame's title.
- Changed, a text needs an edit: `inf` and `nan` are numbers, infinity and not a number (`-inf`), and
  reserved words: a name `inf` or `nan` is refused (`'inf' is a reserved word: choose another name`).
- Added: a setting that holds a set of enum values takes a tuple of them, `SetHandleType[mode: (LEFT,)]`,
  `mode: ()` for none; a one-item tuple takes a comma. Tree → Text writes them, which it left out.
- Fixed: a module's graph whose name is no identifier is printed quoted, `m::"Big Blend"(a)`.
- Changed: a graph that leaves its return out has no Group Output node; with outputs, the checker warns
  (`no return in 'g': …`). A field of the return may be a literal, the value of an output nothing feeds.

## [1.0.0-rc.4] - 2026-11-22

### Language

- Changed, a text needs an edit: a node's settings leave the parentheses for square brackets
  between its name and its inputs, `Math[ADD, use_clamp: true](a, b)`, `Object[object: "Thing"]()`,
  `r = foreach[FACE](mesh, item: f) -> { … }`, and after a call's types in the syntax,
  `f<Vector>[…](…)`. Three delimiters, three meanings: `<>` the types of a template, `[]` what no wire can feed,
  `()` what a wire can feed. A setting takes a literal, an enum value, `_`, a template's type, a
  tuple or a call of them (`Ramp(…)`), never a name that holds a value, which is refused where it
  is written; empty brackets are refused. The parsers and formatters of Python and Rust read and
  print them alike (`conformance/bracket-cases.json`).
- Fixed: a name that holds a value takes no types, so `Math(a < b, c > (d))` compares `a`, an input or a
  bound name, instead of calling it as a template `a<b, c>(d)`.
- Changed: a number Blender cannot keep as written is a warning where it is written:
  `precision lost: 16777217.0 is stored as 16777216.0 (IEEE 754 single precision)`. Every number
  with a point or an exponent lands in a 32-bit float; the warning comes when the shortest decimal
  that reads back as that float is another number (`0.1`, `1e-7`, `3.141593` read back as written).
  The tree holds Blender's value. `base-node check` and the add-on show it. Tree → Text writes each
  number as that shortest decimal, so a text read back is never warned of (rc.3 wrote 7 digits at
  least: `0.0009908871` for `0.000990887`).

## [1.0.0-rc.1] - 2026-11-22

The release candidate of 1.0.0 LTS. A text written for 0.13.1 needs an edit where it writes a zone,
a closure or a target; [`spec/versioning.md`](spec/versioning.md) says what 1.0.0 promises.

### Language

- Changed, a text needs an edit: a zone is a call that takes a body after an arrow,
  `r = repeat(8, v: 1.0) -> { … }`, and likewise `simulate(…) -> { … }` and `foreach(…) -> { … }`.
  `repeat`, `simulate` and `foreach` are no longer words of the language, and `repeat` is no longer
  reserved. The spelling of before is refused, with what to write.
- Changed, a text needs an edit: a closure is a graph with no name,
  `f = graph(x: Float) -> (y: Float) { … }`. `closure(…)` is refused, with what to write.
- Added: a reader refuses a text whose `// @edition` it does not know, at the line of the directive.
- Added: a graph marked `deprecated` still works and warns whoever calls it:
  `geometry(deprecated: "use Grid") graph plane(…)`. `base-node check` prints the warning and
  exits 0.
- Added: the ternary `c ? a : b`. In a geometry tree it is a Switch of the type of its branches;
  in a shader or a compositor tree, where a Switch takes one value for the whole image, a Mix by
  the condition (a Mix Shader for shaders), whose condition is a `Bool` or a comparison. It binds
  looser than `|>`. A tree reads back to it.
- Added: `smooth_min(a, b, k)` and `smooth_max(a, b, k)`, Math's Smooth Minimum and Smooth Maximum.
- Added: Mix Shader and Add Shader name their two Shader inputs `a` and `b`; `Shader` and
  `Shader_001` are still read.
- Changed: a comparison (`a > b`, `==`, …) builds in a tree with no Compare node, a shader tree
  and the compositor of Blender 5.2 LTS: Math nodes that give a Float, 0 or 1; `==` writes
  Compare's Epsilon, 0.001. Such a tree reads these nodes back as the comparison.

### Tools

- Changed, an import needs an edit: the Python package is three. `base_node` is the core (read,
  print, format a text) and names nothing of Blender; `base_node_blender` holds the checker and the
  targets, and exports the core's names too, so `from base_node_blender import …` replaces
  `from base_node import check, load_target, …`; `base_node_cli` holds the command line. In Rust,
  the crate `base-node` is the core and `base-node-blender` the targets.

## [0.13.1] - 2026-11-19

### Fixed

- The Python tests could not be collected before Python 3.12: a script used f-string syntax of
  3.12. `make python-min` parses every `.py` with Python 3.10.

## [0.13.0] - 2026-11-19

### Language

- Changed: a Switch takes the type of its values when the text writes none (it was RGBA in the
  compositor and shaders, Float in geometry).
- Changed: formulas take 2D and colour tuples and integer vectors; a graph named like a function
  is refused.
- Fixed: the formatter keeps comments and blank lines when it sorts the `use` lines.
- Fixed: `Ramp(...)` and `Curve(...)` no longer count as nodes for the targets.

### Tools

- Added: a Makefile: `make test`, `make extension`, `make docs`; `make help` lists the targets.
- Changed: the CI runs on version tags or by hand.

## [0.12.0] - 2026-11-17

### Language

- Changed: profiles become targets: what a destination accepts, inferred from the text, promised
  with `@target`. The targets are `blender-geometry`, `blender-shader`, `blender-compositor`,
  `blender-gp`, `gltf` (checked against Blender's glTF exporter) and a target of another
  destination, with bridges between them. A text no longer starts with `@profile`.
- Added: templates, graphs generic over a value's type, built as one group per use.
- Added: a tuple chooses the type of a Switch, Mix or Compare.
- Added: a shader graph that is a material is set by its bare name from a geometry graph of the
  same text: `SetMaterial(material: rusty)`.
- Added: a node is written and read by its UI name in one word.
- Changed: the formatter breaks every structure at 100 columns and prints each step of a pipe on
  its own line.
- Changed: a module given by a URL is refused.

## [0.11.0] - 2026-11-15

### Language

- Added: Shader and Compositor node groups, and a material's own tree as a shader graph.
- Added: Color Ramps and curves are written in the text and built back.
- Changed: a node with several outputs passes the one it picks through a pipe, in every kind of
  tree: `mesh |> TransferAttributes(…).target |> …`. Some geometry texts are written differently.
- Added: the comments of a text stay on their nodes and show above them in the Node Editor.
- Fixed: a Repeat or Simulation state named like the zone's own socket, two inputs of one name, a
  tree with no Group Output, a Group node with no tree, the components of a Color, the outer
  iteration a nested zone uses.
- Changed: a malformed or hostile `.bn` text gives an error, never a crash or a hang; modules and
  profiles are looked up only inside their own folders.

## [0.9.0] - 2026-11-14

### Language

- Changed: a tree reads back with every input named:
  `MeshCube(size: CombineXYZ(x: 1.0, y: 2.0, z: 3.0), vertices_x: 4)`. Positional values are still
  read.
- Added: a literal bound to a name builds an input node of that name, `size = 10`, and an input
  node reads back as a named constant.
- Added: two numbers build a 2D Vector node: `p = (0.5, 0.25)`.

## [0.8.2] - 2026-11-13

### Language

- Added: a repeat or simulate state takes a key of its own with `as`:
  `simulate(mesh: geometry, "Delta Time" as delta_time_2: 0.0)`.
- Fixed: a frame around nodes inside a zone and outside it reads back as one frame; a zone output
  whose key is shared is written by its name.
- Fixed: an argument that fails no longer gives type errors on the arguments after it.

0.8.0 is the first tagged version; what came before is not listed.
