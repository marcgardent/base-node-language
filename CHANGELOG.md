# Changelog

What changed for a user of Base Node, by version. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); the versions follow
[Semantic Versioning](https://semver.org/) as [`spec/versioning.md`](spec/versioning.md) says.
Versions below 1.0.0 are pre-releases: the text format can change between them.

## [Unreleased]

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

### Blender add-on

- Fixed: Tree → Text writes an enum value, a menu's item or a material that is no bare name as a
  string: `inf`, `nan`, `true` were written bare and read back as a number or a boolean, `_` as no
  value. An enum value named like a name that holds a value in the text is a string too
  (`AlignEulerToVector["X"](…)` beside an input `X`), which the parser refused bare. The editor's
  suggestions quote such a value, its escapes written, and take a word of any script.

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

### Blender add-on

- Changed, a text needs an edit: the checker refuses a value by position where the canonical form
  names the input, at the value, with the name to write: `Math: input 1 is 'Value'; write it by name,
  Math[ADD](Value: a, …)`. The texts of the standard library, the examples, the conformance cases and
  the tests give their inputs by name.
- Added: *Format* writes the inputs of the text's nodes by name, as Blender's sockets go, and *Name
  Inputs* (the text's context menu, and the button beside such an error in the sidebar) those of the
  call under the cursor, the rest of the text as it is. In a node's parentheses the suggestions are
  its inputs, `name: `, and the values only where one may go by position.
- Fixed: Tree → Text writes a value unless it is, bit for bit, the one it leaves out: a float within
  1e-6 of a default was dropped (`0.79999995` read back `0.8`, `5e-07` read back `0.0`), `-0.0` became
  `0.0`, a bound of ±3.40282e38 became the largest float, a ramp or a curve within 1e-5 of a new node's
  was left out. A value past the largest float32 is infinity, no longer an export error.
- Fixed: a flag-set setting (`mode` of Handle Type Selection and Set Handle Type) is written and built:
  `{LEFT}` read back `{LEFT, RIGHT}`.
- Fixed: the value of a Group Output's input nothing feeds is written when a new output holds another
  (Material Library VX's Ceramic: a colour of alpha 0 read back with alpha 1).
- Fixed: an unconnected Math of two numbers (`0.5 × -1`) stays a Math, where it was read `-0.5`, a Value
  node; a second Separate XYZ of one vector stays a call, where `v.x` merged it into the first.
- Fixed: a tree with no Group Output node reads with no return, and builds without one.
- Fixed: a group a module built and edited in the file since is written as a graph of the text: the
  `use` rebuilt it from the module, the edit lost. A `use` is written while the group reads as the
  module's graph built afresh.

### Tools

- Added: `base-node fmt --names` writes the inputs by name without Blender, from the sockets of the
  Blender the text promises (`@target blender@5.2-lts`), else of the newest; `make names FILES=…`
  runs it. The backends `targets/backends/blender-<x.y>.json` list, for each node, the sockets each
  setting makes, alone or with another, and Blender's identifier of a socket where it is not its key:
  `base_node_blender.backend.BackendSchema` reads them, and the checker runs without Blender on every
  text of `corpus/v1`.
- Added: the library tests compare each tree with the tree built back on Blender's data
  (`tests/tree_compare.py`) and fail on any difference but those the reference lists in "What the
  text does not carry". The corpus and the baselines are written again: strings with escapes, the
  values no longer dropped, the flag sets.

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
- Added: `corpus/v1/`, the node groups of the 17 third-party libraries of the tests read as `.bn` text
  by Blender 5.3, each folder under its library's license: a later version of the language must read them.

### Blender add-on

- Changed, every text needs an edit: the checker reads a node's settings from its brackets only. A
  setting by position is an enum value, which goes to the first enum setting of the node, in
  Blender's order, that holds it (`Compare[INT, EQUAL]`, `AlignEulerToVector[X, pivot_axis: Z]`);
  a template's type by position goes to the first setting that has a value for it
  (`NamedAttribute[T](name: n)`, `Switch[T](…)`). An argument in parentheses is always an input:
  `Math(a, b, operation: ADD)` is refused as any unknown input (`Math has no input 'operation'`),
  where rc.3 guessed a setting from the kind of value. The domain of a For Each zone is its setting,
  `foreach[FACE](geometry, item: f) -> { … }`; so are ramps and curves
  (`ColorRamp[color_ramp: Ramp(…)](factor: f)`), datablocks (`Object[object: "Thing"]()`), `_` and
  the values of the input nodes no literal makes (`Rotation[rotation_euler: (0.1, 0.0, 0.0)]()`).
  Errors: an unknown setting, a value no enum setting of the node holds, a setting given twice, a
  value of the wrong kind, settings on a graph, a group, a function, `repeat` or `simulate`.
- Changed: Tree → Text writes the settings in brackets, those by position first: an enum value by
  position when no other enum setting of that node holds it, else by name.
- Fixed: the Normal node of a shader or a compositor tree keeps its vector, which it holds on its
  output: `Normal[normal: (0.0, 0.7071, 0.7071)]()`. rc.3 read it back as `Normal()`, at (0, 0, 1).
- Changed: a datablock the file does not have no longer stops the build: the input or the setting
  stays empty and a warning says `missing datablock: Font "Title"`, once per datablock.
- Removed: the messages that told of a former spelling or name: a node's name of before
  (`it is now written Grid`), a zone with no arrow or `closure(…)` (`repeat takes a body after
  '->'`), a target's name of before (`'gltf' is now 'blender gltf'`). An unknown name is unknown,
  with the names it looks like. Removed too: rc.3's warning on a font of the file named
  `Bfont Regular`.
- Targets: a rule reads a setting from the brackets, by name or by position, and a translator
  renames the settings given by name; the catalogs `targets/blender/<x.y>.json` list each node's
  enum settings (`enums`) for that. The web viewer draws a node's settings from its brackets.
- Completion offers a node's settings inside its brackets (its enum values, then the names of its
  settings) and its inputs inside its parentheses; the editor colors a call and its enum values.

## [1.0.0-rc.3] - 2026-11-22

### Blender add-on

- Changed, a text of 1.0.0-rc.2 may need an edit: a datablock's input node is a call, linked or
  not, holding a datablock or none: `o = Object(object: "Thing")`,
  `ObjectInfo(object: Object(object: "Thing"))`, `Font(font: _)`. A named string is a String node,
  whatever reads it: rc.2 made `o = "Thing"` an Object node when an Object input read it first, a
  type the text did not show, and read the same node as `Object(object: "Thing")` once it fed
  nothing or held nothing.
- Changed: a named string given to a datablock input is an error that says what to write, the name
  in place or the input node: `font: "Bfont Regular", or name a Font node: t = Font(font: "Bfont
  Regular")`. Before rc.2 the input took its value and the String node stayed, linked to nothing. A
  Sound, which has no input node, comes from a graph input or its name in place.
- Added: a font of the file named `Bfont Regular` that is not Blender's own reads with a warning: the
  text names Blender's own so, and builds it back so.

## [1.0.0-rc.2] - 2026-11-22

### Blender add-on

- Fixed: Blender's own font reads as `"Bfont Regular"` whatever the file names it. A library
  appended in a session that had loaded the font brings its copy as `Bfont Regular.001`, which a
  String to Curves then wrote as `font: "Bfont Regular.001"`: the text depended on what the
  session had done before (T3D GN Presets, 2 groups, on the CI).
- Fixed: a String to Curves without a font, and a Font node without one, read as `font: _`;
  they were written as the built-in font, or as `Font(font: "None")`, which did not build.
- Fixed: a named string that a datablock input reads first, `title = "Bfont Regular"` then
  `StringToCurves(font: title)`, is a Font node named `title` (Object, Collection, Material and
  Image alike); it was a String node linked to nothing, and the name was lost. A Font, Object,
  Collection, Material or Image node made in Blender reads to such a constant.
- Fixed: a Rotation node, a 4D Vector node and an Integer Vector node keep their value:
  `Rotation(rotation_euler: (0.1, 0.0, 0.0))`, `Vector(vector: (1.0, 2.0, 3.0, 4.0))`,
  `IntegerVector(vector: (1, 2, 3))`. They were written without it (`Rotation()`) and built at zero.
- Fixed: a Menu node builds with the item it picks (`Menu(value: B)`), set once it is linked.

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

### Targets

- Changed, a text needs an edit: one target `blender`, named by the version of Blender, in place
  of `blender-geometry`, `blender-shader`, `blender-compositor` and `blender-gp`: `blender`,
  `blender@5.3`, `blender@5.2-lts`. `gltf` is a variant of it, `blender gltf`, beside two
  experimental ones, `blender eevee` and `blender cycles`. `blender@lts` and `blender@latest` are
  aliases for a command line. The names of before are unknown targets; the message says what to write.
- Changed: a variant of `blender` is tried by the inference only for a text that holds a shader.
- Added: the catalog of Blender 5.2 LTS. `blender` is now Blender 5.2 LTS and Blender 5.3: a text
  that says `blender` fits both, `blender@5.2-lts` and `blender@lts` name the LTS.
  [`spec/targets.md`](spec/targets.md#what-blender-53-has-that-blender-52-lts-has-not) lists what
  5.3 has that 5.2 has not; a text that uses it says `// @target blender@5.3`.

### Standard library

- Changed: the modules are written as a tree reads back to them now: 205 Switch calls are
  ternaries, and Mix Shader's inputs are `a` and `b`.
- Changed: `planar2d`, shape builder pick: each seed picks the region it is in, or the nearest
  within `pick_radius`; the regions no seed picks are deleted, the picked ones stay in place. It
  read the first seed only and moved the picked region away.
- Fixed: `stmap`, canvas: an odd size is no longer rounded up to an even one (65 × 33 gave
  66 × 34), which lost the first column and row of what was built on it.

### Tools

- Changed, an import needs an edit: the Python package is three. `base_node` is the core (read,
  print, format a text) and names nothing of Blender; `base_node_blender` holds the checker and the
  targets, and exports the core's names too, so `from base_node_blender import …` replaces
  `from base_node import check, load_target, …`; `base_node_cli` holds the command line. In Rust,
  the crate `base-node` is the core and `base-node-blender` the targets.
- Fixed: `<bn-view>` no longer leaves a node over a frame in a graph of many frames.
- Added: `make test-promised BLENDERS="…"` runs the Blender tests and the third-party libraries
  with each promised version of Blender; the CI runs Blender 5.2.4 LTS and 5.3.0.

### Blender extension

- Changed: the extension holds the targets of Blender only.
- Added: the warnings of a text (a deprecated graph called) are listed under its errors and
  underlined, without blocking the tree.

### Site and documents

- Changed: the repository is named `base-node-language`; its site and the extension repository are
  at `basenode.ludopant.com`, hosted and sponsored by Ludopant. The old addresses redirect, and
  keep serving the extension index.
- Added: the tutorial "SRT subtitles": a Geometry Nodes group that reads a SubRip file (`.srt`)
  and draws the cue of the scene's time (`make srt-check` builds it in Blender).
- Changed: every tutorial text names each input, as a tree reads back.
- Changed: the home page is about the open source project; what developers read (examples with
  their code, targets, the web component, Python and Rust) is on a page of its own.
- Added: a State of the Art page on node graphs as text, a sitemap and `robots.txt`.
- Added: this changelog.

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

### Standard library

- Changed: the standard library is split. Eleven modules stay open source: `curves2d`, `fillet2d`,
  `grade`, `mask2d`, `math`, `merge`, `patterns2d`, `planar2d`, `qc`, `sdf2d`, `stmap`. Eleven
  modules of 0.12.0 leave it and are sold by the author as packs: `deform2d`, `hachures2d`,
  `ink2d`, `generators`, `mesh_effects`, `mesh_maps`, `grain`, `keying`, `light`, `passes`,
  `vr360`.
- Changed: each module says its manifest entry in the head of its `.bn`; `stdlib/manifest.json`
  no longer lists the modules.

### Tools

- Added: a Makefile: `make test`, `make extension`, `make docs`; `make help` lists the targets.
- Changed: `<bn-view>` shows the graphs of a text as tabs and its comments in the graph; its code
  scrolls only once clicked; a page chooses the tab and the view it opens on.
- Changed: the CI runs on version tags or by hand.

## [0.12.0] - 2026-11-17

### Language

- Changed: profiles become targets: what a destination accepts, inferred from the text, promised
  with `@target`. The targets are `blender-geometry`, `blender-shader`, `blender-compositor`,
  `blender-gp`, `gltf` (checked against Blender's glTF exporter) and `blade`, with bridges between
  them. A text no longer starts with `@profile`.
- Added: templates, graphs generic over a value's type, built as one group per use.
- Added: a tuple chooses the type of a Switch, Mix or Compare.
- Added: a shader graph that is a material is set by its bare name from a geometry graph of the
  same text: `SetMaterial(material: rusty)`.
- Added: a node is written and read by its UI name in one word.
- Changed: the formatter breaks every structure at 100 columns and prints each step of a pipe on
  its own line.
- Changed: a module given by a URL is refused.

### Standard library

- Added: compositor modules after Nuke: `merge`, `passes`, `grade`, `keying`, `light`, `stmap`,
  `vr360`, `mask2d`, `grain`, `qc`.
- Added: smart materials: `mesh_maps` (curvature, ambient occlusion, thickness, position, island
  and sky maps computed in Geometry Nodes), `generators` (masks from those maps), `mesh_effects`
  (chipped edges, dents, rivets, stitches, rust streaks, drips, dust).

### Blender extension

- Added: a `.bn` file dropped onto Blender offers, from the directives at its head, to install it
  as a module, import its groups, add its example, or make a mesh with its modifier.
- Added: Copy as .bn and Paste .bn: nodes copied as text, text pasted as nodes.
- Changed: the suggestions are found as Blender's Add menu search finds nodes.
- Fixed: the order of the links into a multi-input socket; a zone state with no name gives an
  error, not a crash; the size of a 2D Vector output is kept.

### Tools

- Added: `<bn-view>` shows a `.bn` text in the browser, its code and its node graph; `<bn-file>`
  shows it as a card to download.
- Added: `base-node docs` writes the reference pages of the site from the repository.

### Site and documents

- Added: a Tutorials section: Lunar ground and Mini moon.
- Added: examples written in Base Node: hydraulic erosion, Gray-Scott reaction-diffusion,
  differential growth of a closed curve.

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

### Blender extension

- Added: errors are underlined while the text is typed and listed in the sidebar.
- Added: errors suggest the likely fix: `did you mean sin?`.
- Changed: building a large text is about 25 % faster.

### Tools

- Added: 567 node groups of 8 third-party libraries are read, rebuilt and evaluated in the CI.

## [0.10.0] - 2026-11-14

### Blender extension

- Added: the tree follows its text while it is typed, half a second after the last key once the
  text is valid ("Apply while typing", on by default).
- Added: the pipe `|>` shows as ▷, except on the lines being edited ("Show |> as ▷").
- Added: Arrange Nodes: links left to right, in line with their sockets, frames kept together.
- Changed: the keys follow Blender's: Alt+Z switches between a tree and its text (was Ctrl+`),
  Alt+P applies a text to its tree (was Ctrl+Enter), Ctrl+Space opens the suggestions,
  Ctrl+Shift+A formats a text and arranges the nodes. The panels show each shortcut.
- Changed: the suggestions open by themselves only when turned on.

## [0.9.0] - 2026-11-14

### Language

- Changed: a tree reads back with every input named:
  `MeshCube(size: CombineXYZ(x: 1.0, y: 2.0, z: 3.0), vertices_x: 4)`. Positional values are still
  read.
- Added: a literal bound to a name builds an input node of that name, `size = 10`, and an input
  node reads back as a named constant.
- Added: two numbers build a 2D Vector node: `p = (0.5, 0.25)`.

### Blender extension

- Added: inside a call, the prototype shows under the line, the input being written lit.
- Changed: the suggestions are coloured by kind, the call's inputs first.

## [0.8.2] - 2026-11-13

### Language

- Added: a repeat or simulate state takes a key of its own with `as`:
  `simulate(mesh: geometry, "Delta Time" as delta_time_2: 0.0)`.
- Fixed: a frame around nodes inside a zone and outside it reads back as one frame; a zone output
  whose key is shared is written by its name.
- Fixed: an argument that fails no longer gives type errors on the arguments after it.

### Tools

- Added: the 17 Geometry Nodes assets of Cartesian Caramel's Everyday Nodes (CC0) are read, built
  back and evaluated by the tests.

## [0.8.1] - 2026-11-13

### Blender extension

- Changed: the extension is named "Base Node" and declares the files permission.
- Added: the standard library is bundled: `use math` works with no setup. The Module Folder of the
  preferences still comes first.

## [0.8.0] - 2026-11-13

### Blender extension

- Changed: the node tree is the only data in Blender. Ctrl+` switches a Node Editor to the tree's
  `.bn` text and back; Ctrl+Enter applies the text without leaving it. The persistent text beside
  a tree, and the sync between text and nodes, are removed.
- Added: File > Import > Base Node (.bn) builds the graphs of one or more files.
- Added: `use name` also finds `name.bn` beside the imported file and in the Module Folder of the
  preferences.

### Standard library

- Added: `planar2d`, `fillet2d`, `hachures2d`, `deform2d`.

0.8.0 is the first tagged version; what came before is not listed.
