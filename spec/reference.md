# Base Node (`.bn`) Language Reference

Language Edition 2026 · Specification Version 1.0.0-rc.7 (release candidate of the LTS).  
See [Versioning Specification](versioning.md) for stability policies and release lifecycles.

This reference is the language: how a text is read, printed and formatted. It names no destination.
What a kind of tree, a type, a node, a setting, a formula or a call with a body means is the host's:
a host library gives a text its meaning for one destination, and holds it to its own rules. The
examples call nodes by name; to the language they are names.

## 1. File Structure

A `.bn` file is UTF-8 text containing:

1. Optional `use` imports at the top of the file:
   - `use curves2d` imports the module into the `curves2d::` namespace.
   - `use curves2d as c2` imports with an alias namespace (`c2::ring_2d(...)`).
   - `use curves2d (ring_2d)` imports selected symbols into local scope (`ring_2d(...)`).
   - `use math from "lib/math.bn"` imports from a file, by a path the host resolves. A source is a file, never a URL: reading a `.bn` makes no network request.
   - Without `from`, the host finds the module, in an order of its own.
2. One or more `graph` declarations.

`//` starts a line comment. Whitespace and newlines are not significant outside literals; a statement ends when the next token cannot continue the current expression.

```bn
use curves2d as c2
use math (bump)

geometry graph relief(curve: Geometry, height: Float = 0.4) -> Geometry {
  "Lifts the middle of a curve, then draws its contour"
  h = bump(length(Position()) / 3.0, 0.5, 0.2) * height
  return curve
    |> SetPosition(offset: CombineXYZ(z: h))
    |> c2::"parallel contour 2d"(offset: 0.05)
}
```

### 1.1 File Head

The comment lines before the first `use` or graph may hold directives, `// @name value`, one per line. They are comments: every reader keeps them as written, and a directive a tool does not know is left for others. The core reads and checks those of the table (`base_node.header(source)` in Python, `base_node::header` in Rust). A host reads its own from the same head (`read_head`, in both), each written once and with a value, and says what they mean.

```bn
// @module waves
// @edition 2026
// @title Ripples and waves
// @author Base Node
// @license MIT
```

| Directive | Value |
|---|---|
| `@module` | The module's name, an identifier: its file is `<name>.bn`, found by `use <name>` |
| `@version` | The version of the file, as its author numbers it |
| `@edition` | The edition of the language the file is written in ([versioning, 2](versioning.md#2-tier-1-language-edition-edition)) |
| `@target` | The targets the file promises to fit, separated by commas; optional. A target is written `name`, `name@version`, or either with words after it, spaces apart: which targets there are, and what a version and a word mean, are the host's |
| `@title`, `@author`, `@license` | Free text (an SPDX identifier for the license), shown to whoever opens the file |

A value written in quotes is a string ([2](#2-identifiers-and-keywords)), its escapes read as in any string, wherever a directive is read: a name, a title, a target. Free text that is not one string (`"a" and "b"`) is read as written.

A directive written twice or without a value, a `@module` that is not an identifier, and a target the host refuses, with its reason, are errors at their line and column. So is an `@edition` the reader does not know (`@edition '2028': not an edition this reader knows (2026)`): the parser and the formatter refuse the text too, a later edition being another language to them.

## 2. Identifiers and Keywords

- **Identifier**: `_` or a letter, then letters, digits and `_` (`height`, `frequency_2`, `p`, `ρ_θ_φ`, `Größe`): an identifier as Unicode defines it (UAX #31: `_` or a character of XID_Start, then characters of XID_Continue), of Unicode 16.0, but for `·` (U+00B7), the dot product (`a·b` is `a ⋅ b`). The digits of a number are ASCII's: `²` and `٣` are neither a number nor a name (`unexpected character '²'`). Every reader and printer holds this rule in one table (`python/base_node/identifiers.py`, `rust/src/identifiers.rs`): a name is printed bare only when it is an identifier and no reserved word, so that it reads back as that name; any other is quoted where the grammar takes a quoted name (a graph, an input, an output, a panel, an input given by name, an output picked with `.`, a graph after `::`), else written by its key (a binding, an `as` key, a name a `use` imports).
- **Quoted name**: `"Point Count"`. Referenced in expressions by its `snake_case` key (`point_count`), or given an explicit key via `as`: `"Scale" as random_scale: Float`. The key of a name that is not a bare identifier is the name lowercased, each run of characters an identifier does not hold made one `_` and those at its ends dropped, a `_` before it when it does not start as an identifier and after it when it is a reserved word: `"x²"` is `x`, `"2D"` is `_2d`, `"Rotation °"` is `rotation`, `"not"` is `not_`. A key is always a bare identifier, its own key. A graph of a module is called by its name quoted after the module when that name is not identifiers joined by `::`: `c2::"parallel contour 2d"(…)`; `m::"a::b"` is the name `m::a::b`, written so.
- **String**: `"…"` on one line, its characters as written but for `\`, which starts an escape: `\"`, `\\`, `\n` (a line feed), `\t`, `\r`, and `\u{…}`, any character by its code in 1 to 6 hex digits (`\u{1F600}`), a Unicode scalar value (at most `10ffff`, no surrogate). Another escape is an error at its `\` (`unknown escape '\q': a string's escapes are \", \\, \n, \t, \r and \u{…}, a character's code in 1 to 6 hex digits`), and so is a line break inside a string (`unclosed string`), written `\n`. A quoted name, a description, a frame's title, a look's label and the file of a `use` are strings. The printer writes `\"`, `\\`, `\n`, `\t`, `\r`, every other control character (U+0000 to U+001F, U+007F) as `\u{…}` in lowercase hex without leading zeros (`\u{1b}`), and any other character as itself: any string reads back as it was.
- **Reserved words**: `graph`, `return`, `true`, `false`, `and`, `or`, `xor`, `not`, `dot`, `cross`, `inf`, `nan`. `inf` and `nan` are floats, infinity and not a number, written so wherever a number is ([5](#5-expressions)): `-inf` is the negation of `inf` as `-1.0` is of `1.0`, a NaN of any sign is written `nan`, and `inf_x`, `Inf` are names. A reserved word names nothing: `inf = 1.0`, an input, an item or a type parameter of that name is refused at the word (`'inf' is a reserved word: choose another name`). A socket a host names like a reserved word takes a trailing `_` as its key (`not_`, `inf_`), and a label or a name that is one is written quoted (`."inf"`).
- **Contextual keywords**: `use`, `from`, `_`. The calls that take a body are no words of the language: `repeat`, `simulate` and `foreach` are names a host gives to such calls ([6](#6-calls-with-a-body-and-nameless-graphs)), and may name a state, a local or a graph. The parser knows the names each of them gives its body, which hold a value there: `iteration` in a `repeat`, `delta_time` in a `simulate`, `index` and `element` in a `foreach`, whatever the host's version and the call's settings ([3.4](#34-templates)).
- **Enum values**: an identifier in a call's settings is an enum value, or a template's type: `Math[POWER]`, `StoreNamedAttribute[domain: FACE]` ([5](#5-expressions)). A value that is no bare identifier, `_`, or a name that holds a value there is written as a string: `NoiseTexture[noise_dimensions: "3D"]`, `AlignEulerToVector["X"](…)` in a graph with an input `X`; so is a value named like a reserved word (`"inf"`).

## 3. Graph Declaration

```bn
[kind][(options)] graph name(inputs...) -> outputs {
  body...
}
```

A graph with a name is declared at the top of a file. Inside a body, `graph(inputs...) -> outputs { body... }`, with no name and no kind, is a value: a nameless graph ([6](#6-calls-with-a-body-and-nameless-graphs)).

- **Kind**: an identifier, the kind of tree: `geometry graph`, `shader graph`. The parser takes any word there; which kinds there are is the host's.
- **Options**: named values in parentheses after the kind, the settings of the graph, which the host defines: `geometry(is_tool: true, is_mode_edit: true) graph ...`.
- **Outputs**: Single type `-> Geometry` or named tuple `-> (Mesh: Geometry, Centers: Geometry)`.
- **Options of an input or an output**: named values in parentheses after its type, which the host defines: `distance: Float(subtype: DISTANCE)`, `-> (UV: Vector(dimensions: 2))`.
- **Docstring**: An optional string literal as the first statement of the body.

### 3.1 Types

A type is an identifier: `Float`, `Vector`, `Geometry`. Which types there are, their defaults, and which literals each takes, are the host's. A type parameter of a template ([3.4](#34-templates)) stands for a type.

### 3.2 Parameters

```bn
name as key: Type(subtype: DISTANCE) = default_value in min..max
```

- `= default_value`: a literal, or an expression the host takes as a default (an implicit input: `Position()`).
- `in min..max`: Numeric bounds (`in 0.0..1.0`, `in 0.0..`, `in ..1.0`); either side may be left open, not both (`empty range: specify at least min or max`).

### 3.3 Interface Panels

Parameters and outputs can be grouped into nested panels:

```bn
geometry graph scatter(
    geometry: Geometry,
    "Size"(description: "Scale controls") {
      scale: Float = 1.0,
      "Random"(default_closed: true) {
        enable: Bool(is_panel_toggle: true),
        scale as random_scale: Float = 0.2 in 0.0..1.0
      }
    }
) -> Geometry { ... }
```

### 3.4 Templates

*Since the specification version 0.12.0. The Python and Rust parsers read and print it; what a
template builds, and the type a call takes when it writes none, are the host's.*

A **template** is a graph generic over the type of a value, written once: a host builds it for each
type it is called with.

```bn
geometry graph attribute_or<T: Float | Int | Bool | Vector | Color | Rotation | Matrix>(
    name: String,
    fallback: T
) -> (value: T) {
  a = NamedAttribute[T](name: name)
  return (value: Switch[T](switch: a.exists, false_: fallback, true_: a.attribute))
}

geometry graph tint(geometry: Geometry, color: Color) -> Geometry {
  c = attribute_or("Col", color)
  return geometry |> StoreNamedAttribute[FLOAT_COLOR](name: "tint", value: c)
}
```

- **Type parameters**: `<T: Float | Vector | Color>` after the graph's name, one or more, separated by
  commas (`<T: Float | Vector, U: Float | Int>`). The constraint is required: it lists every type the
  template is built for (`<T>` is refused: `a type parameter lists its types: <T: Float | Vector>`).
- **In the body**, `T` stands for the type wherever a type goes: an input's or an output's type
  (`fallback: T`, `-> (value: T)`), an item's type (`repeat(n, v: T = fallback)`), and a value in a
  call's settings, by position or by name (`NamedAttribute[T](name: n)`, `Mix[data_type: T](…)`),
  which the host reads as that type.
- **The types of a call** follow its name, in chevrons, before its settings and its arguments:
  `attribute_or<Vector>("rest", p)`, `blend<Float, Color>(…)`, `index_mix<T>(value, i)` in a template.
  A name that holds a value where it is written takes no types: an input of the graph, a name an
  earlier statement bound (in a frame too), an item of the body it is in, a name a call gives its body
  (`iteration`, `delta_time`, `index`, `element`: [2](#2-identifiers-and-keywords)), an input of the
  graph with no name it is in. There `<` compares: `max(a < b, c > (d))` is two comparisons when `a` is
  one of them.

**Edition and versions.** The syntax is added to Edition 2026: every text valid before reads as before,
as a `<` after a graph's name was a syntax error, and `f<Vector>(x)` two comparisons in a row, which the
grammar refuses. Before LTS this is a minor version of the specification (0.11.0 → 0.12.0) and of the
Python and Rust packages with it ([versioning, 3](versioning.md#3-lifecycle--stability-policy-pre-lts-vs-lts)).
A text using templates is not read by a toolchain before 0.12.0: it is refused there at the `<`.

## 4. Statements

| Syntax | Meaning |
|---|---|
| `x = expr` | Bind expression output |
| `size = 10` | Named constant: a literal bound to a name, which the host makes a value of its own; a tuple too. A setting takes no name: no wire feeds it, so its value is written in its brackets |
| `return expr` | Single output return |
| `return (A: e1, B: e2)` | Multi-output return |
| no `return` | A graph may leave its return out: its outputs, if it has any, give nothing |
| `"Title" #color { ... }` | Visual frame (`#e73` or named color `#teal`): a frame's or a look's color, never a value, which is a tuple |
| `"Title" .. { ... }` | Continuation of a previously opened frame |
| `"Note" #color {}` | Standalone frame note |

A field of the return may be a literal: the value of that output when nothing feeds it (`return (color: (0.0, 0.0, 0.0, 0.0))`).

### 4.1 Node Presentation (`@`)

```bn
p = Position() @ hide
h = sin(p.x) @ "Height" #e07030
out = SetPosition(g, offset: o) @ #orange hide mute
```

Flags: `"Label"`, `#color`, `hide` (collapsed), `mute` (bypassed).

## 5. Expressions

A call writes up to three lists after its name, each in its own delimiters: `<>` the types of a
template ([3.4](#34-templates)), `[]` the node's settings, what no wire can feed, and `()` what a
wire can feed.

```
call      := name type_args? settings? '(' args ')' ('->' outputs)?
body_call := name settings? '(' args ')' '->' block          (6)
name      := IDENT ('::' (IDENT | STRING))*
settings  := '[' setting (',' setting)* ','? ']'
setting   := IDENT ':' value | value                          positional ones first
value     := NUMBER | '-' NUMBER | STRING | 'true' | 'false'
           | IDENT                                            an enum value, a template's type, `_`
           | '(' ')' | '(' value ',' ')'                      a tuple of none, of one: (LEFT,)
           | '(' value (',' value)+ ','? ')'                  a tuple
           | '(' value ')'                                    the value alone
           | IDENT '(' (value | IDENT ':' value) (',' …)* ')'  a call of values: Ramp(…), Curve(…)
NUMBER    := digits ('.' digits)? (('e' | 'E') ('+' | '-')? digits)? | 'inf' | 'nan'
```

```bn
x = Math[WRAP](Value: angle, Value_001: 3.141593, Value_002: -3.141593)
y = Math[ADD, use_clamp: true](Value: a, Value_001: b)
o = Object[object: "Thing"]()
c = ColorRamp[color_ramp: Ramp((0.0, (0.0, 0.0, 0.0)), (1.0, (1.0, 0.5, 0.0)))](factor: f)
r = foreach[FACE](geometry, selection: s, item: f) -> { … }
g |> StoreNamedAttribute[INT, CURVE](name: "i", value: Index())
a = NamedAttribute[T](name: name)        // T, a template's type, as a setting's value
```

- A `[` right after a call's name, or after its types, always opens its settings; brackets
  anywhere else are an error (`expression expected, found '['`). The parentheses follow the
  settings, empty when the node takes no input: `Object[object: "Thing"]()`. Empty brackets are
  refused: a call with no settings writes none.
- A setting holds no wire: a name in brackets is an enum value or a template's type parameter,
  never a name that holds a value. A graph's input, a name a statement before bound or an item of
  the body around, as a setting, in a tuple or in a call there, is refused where it is written:
  `'a' holds a value, and no wire feeds a setting: give it in the parentheses`. Nor does a setting
  take an operator: `Math[1.0 + 2.0]` is refused at the `+`.
- The language does not know which names are settings: the brackets keep them apart in the syntax
  tree (the call's `settings`, in source order, each with its key or none), and the host says what
  each node has.
- **Call**: `Name[SETTING, setting: value](geometry, socket: value)`. What a name calls, a node, a graph of the text or of a module, a function, is the host's.
- **Settings**: what no wire can feed, in the brackets: an enum value, a boolean, a number, a string, a tuple of them (`mode: (LEFT, RIGHT)`, `(LEFT,)` for one, `()` for none), a call of values (`Ramp(…)`, `Curve(…)`). The settings by position go first (`positional setting after named setting`).
- **Inputs**: in parentheses, by position or by name (`socket: value`, the key of the socket), those by position first (`positional argument after named argument`). Which values go by position in the canonical form is the host's.
- **Output access**: `node.output_name`, and `v.x`, `v.y`, `v.z` as any name after the dot.
- **Pipe**: `a |> f(b)` is `f(a, b)`: `a` is the value that goes first unnamed. The value passed on may be one output of a call of several: `mesh |> SeparateGeometry(selection: s).selection |> SetPosition(…)` is `SetPosition(SeparateGeometry(mesh, selection: s).selection)`. Its canonical layout is in [5.1](#51-canonical-layout)
- **Operators**: `+`, `-`, `*`, `/`, the comparisons `<`, `<=`, `>`, `>=`, `==`, `!=`, the logical `and`, `or`, `xor`, `not`, and the products of two vectors, `u ⋅ v` (`u dot v`, `u·v`) and `u × v` (`u cross v`). Loosest first: `? :`, `|>`, `or xor`, `and`, `not`, comparisons, `+ -`, `* / ⋅ ×`, unary `-`, then `.socket`. What each builds is the host's.
- **Ternary**: `cond ? a : b` is `a` where the condition holds, `b` elsewhere. It binds loosest, looser than `|>`: its branches are whole expressions (`big ? mesh |> SubdivideMesh() : mesh`), the last one may be a ternary again (`a > b ? 1.0 : a < 0.0 ? 2.0 : 3.0` reads `a > b ? 1.0 : (a < 0.0 ? 2.0 : 3.0)`), and it takes parentheses as a condition, as the first branch, as an operand (`(on ? a : b) * 2.0`) and before a pipe (`(on ? fine : coarse) |> SetShadeSmooth()`). What it builds is the host's.
- **Functions**: a call of a name the host gives a meaning of its own, as `sin(x)`, `max(a, b)`, `smooth_min(d1, d2, 0.1)`, is written as any call.

### 5.1 Canonical Layout

The formatter and the printer print one layout, set by a width of 100 characters per line, indentation included (rustfmt's default):

- **What fits stays on its line.** A statement, an argument, a parameter is printed on one line when that line, with the commas, parentheses and look (`@ …`) that end it, is at most 100 characters: `CombineXYZ(x: 1.0, y: 1.0, z: 1.0)` stays whole.
- **Else the outermost structure spreads**, one item per line, one indent (two spaces) further in than the line it starts on, and each of these lines follows the same rule in turn:
  - the arguments of a call, the closing parenthesis at the end of the last one; a call ending with a chosen output keeps it after that parenthesis (`F(` … `last: x).curve`), and declared outputs too long for that line go one per line after `) -> (`;
  - the items of a tuple, and the fields of `return (x: …, y: …)`;
  - the steps of a pipe inside an expression (an argument, an operand, the target of `.output`), each on a line of its own starting with `|>`; the parentheses its precedence asks for stay around it;
  - a chain of operators of one strength (`a + b - c`, `a * b / c`, `a and b`): the first operand stays on the line, each operator starts a line of its own with its operand (`+ b`);
  - a ternary: the condition stays on the line, `? a` and `: b` each start a line of their own; a branch too long for its line follows the same rule in turn, one indent further in;
  - the options of a parameter, of a panel or of a named argument (`description: …`).
  - the settings of a call (`Name[…]`) stay with its name while that first line fits, and its
    arguments spread. When they make that line too long, they spread first, one per line, the last
    one ending with `](`; the arguments follow on that line while they fit there, else they spread
    in turn, one per line at the same indent.
- **The first item stays apart.** When the head of a pipe or the first operand of a chain spreads too, its own lines go one indent further in than the `|>` and operators that follow it, so they never line up with them.
- **A pipe that is the whole value of a statement** (`x = …`, `return …`) always puts each step, the first one included, on a line of its own, short or not.
- A line stays longer than 100 only where nothing is left to spread: a single string or name longer than the room it has.

```bn
  transform = Cube(size: CombineXYZ(x: 2.0))
    |> TransformGeometry(translation: CombineXYZ(), scale: CombineXYZ(x: 1.0, y: 1.0, z: 1.0))
  hair = Switch[GEOMETRY](
      switch: Hairs > 0.0,
      true_: (points |> SetMaterial(material: Hair)) + (lint |> SetMaterial(material: Lint)))
    + Switch[GEOMETRY](
      switch: Cobwebs > 0.0,
      true_: cobweb
        |> InstanceOnPoints(instance: strand, rotation: align, scale: CombineXYZ(x: s, y: s, z: s))
        |> RealizeInstances())
  return hair
    |> TransformGeometry(
      translation: CombineXYZ(x: 1.0, y: 1.0, z: 1.0),
      rotation: CombineXYZ(x: 1.0, y: 1.0, z: 1.0),
      scale: CombineXYZ(x: 1.0, y: 1.0, z: 1.0))
    |> SetShadeSmooth()
```

The layout depends on the syntax tree alone: printing the parse of a printed text gives the same text.

## 6. Calls with a Body, and Nameless Graphs

Two forms hold a body of statements. Both are written only as the value of an assignment (`name = …`), and their body sees the names outside it.

```bn
name = call[settings...](arguments...) -> {
  body...
}

name = graph(inputs...) -> outputs {
  body...
}
```

- **A call with a body**: a call, its name qualified or not, its settings in brackets if any and its arguments as any call's, then `->` and the body in braces. The arrow makes the body: `x = f(a)` followed by `{ … }` on the next line is a call, then a frame with no title ([4](#4-statements)). Which names take a body, what their arguments are, what the body sees beside the names outside and what it returns, the host says, and it refuses a body given to any other name. The parser knows the names `repeat`, `simulate` and `foreach` give their body ([2](#2-identifiers-and-keywords)).
- **A nameless graph**: `graph` followed by `(`. It writes no tree kind: it has the kind of the graph that holds it. Its inputs and outputs are written as a graph's (`-> Float` or `-> (name: Type, …)`, quoted names, options), without panels or `as` keys. In the body the inputs are names; the names outside are seen too, and their values are captured. The value is called by the name it is assigned to, its inputs by name: `shape(t: 0.25)`.

Elsewhere than as the value of an assignment, both are errors: `a call with a body is the value of an assignment: r = repeat(…) -> { … }`, `a graph with no name is the value of an assignment: f = graph(x: Float) -> Float { … }`.

## 7. Limits

A `.bn` text may come from anyone. Reading one ends with a tree or an error, never a crash or a hang: every reader refuses, with an error at the place it happens, a text past one of these limits.

| Limit | Value | What counts |
|---|---|---|
| Source size | 4 MiB | The bytes of the text, in UTF-8 |
| Nesting | 32 | What is open at once: `(…)`, the arguments or options of a call, a `{…}` block (frame, panel, the body of a call or of a nameless graph), each prefix `-` or `not`, and the branches of each `? :` (a chain `a ? x : b ? y : …` opens one per `?`) |
| Expression height | 256 | The nodes one inside another in an expression: a name or a literal is 1, and each operator, call, tuple or `.socket` is one more than the tallest of what it holds. A chain counts for its length: `a + b + c` is 3, and so is a pipe of two steps |
| Integer | 2⁶³ − 1 | The digits of an integer literal; a float literal written with digits must be finite (`1e999` is refused), infinity is written `inf` |

A host that reads the file a `use` names reads a regular file no larger than a source, inside the roots the modules resolve in (§1).
