# Base Node (`.bn`) Language Reference

Language Edition 2026 · Specification Version 1.0.0-rc.5 (release candidate of the LTS).  
See [Versioning Specification](versioning.md) for stability policies and release lifecycles.

## 1. File Structure

A `.bn` file is UTF-8 text containing:

1. Optional `use` imports at the top of the file:
   - `use curves2d` imports the module into the `curves2d::` namespace.
   - `use curves2d as c2` imports with an alias namespace (`c2::ring_2d(...)`).
   - `use curves2d (ring_2d)` imports selected symbols into local scope (`ring_2d(...)`).
   - `use math from "//lib/math.bn"` imports from an external or relative file. A source is a file, never a URL: reading a `.bn` makes no network request.
   - Without `from`, the host finds the module. Blender looks for the text `math.bn` of the .blend, then `math.bn` next to the imported file, then in the *Module Folder* of the add-on preferences, then in the standard library bundled with the add-on.
   - Tree → Text writes a `use` and a call for a group a module built while the group reads as the module builds it now: its text against the text of the module's graph built afresh, for the same kind of tree and types, both read as any tree is. A group edited in the file since, or whose module changed or is not found, is a graph of the text, written as it is.
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

The comment lines before the first `use` or graph may hold directives, `// @name value`, one per line. They are comments: every reader keeps them as written, and a directive a tool does not know is left for others. The Python package reads and checks the known ones (`base_node.header(source)`); the Blender add-on uses them when a `.bn` file is dropped on it.

```bn
// @module waves
// @title Ripples and waves
// @author Base Node
// @license MIT
// @offer library, groups, example, modifier
// @example ripple_field
// @modifier "wave modifier"
// @mesh grid
```

| Directive | Value |
|---|---|
| `@module` | The module's name, an identifier: its file is `<name>.bn`, found by `use <name>` |
| `@version`, `@edition` | See [versioning](versioning.md) |
| `@target` | The targets the file promises to fit, separated by commas; optional: see [targets](targets.md) |
| `@title`, `@author`, `@license` | Free text (an SPDX identifier for the license), shown to whoever opens the file |
| `@offer` | What the file offers, separated by commas: `library` (install it as a module), `groups` (build its graphs into the file), `example` (an object carrying a graph that makes its own geometry), `modifier` (a modifier graph on an object) |
| `@example`, `@modifier` | The graph each uses, by its name quoted or as an identifier, when several could |
| `@mesh` | The mesh `modifier` makes when no object takes it: `cube` (default), `plane`, `sphere`, `cylinder`, `grid` |

Without `@offer`, a file offers `library` when it has a `@module`, `groups` always, `example` when a geometry graph nobody calls has a `Geometry` output and no `Geometry` input, and `modifier` when a geometry graph nobody calls has `Geometry` as its first input and first output (as Blender decides `is_modifier`, unless the graph's settings write it). With several such graphs and no `@example` or `@modifier`, the last one is used. A directive written twice or without a value, a `@module` that is not an identifier, an unknown `@offer` or `@mesh` value, a choice offered that no graph allows, and an `@example` or `@modifier` naming no graph of the file, or one of the wrong shape, are errors at their line and column. So is an `@edition` the reader does not know (`@edition '2028': not an edition this reader knows (2026)`): the parser and the formatter refuse the text too, a later edition being another language to them.

## 2. Identifiers and Keywords

- **Identifier**: Unicode letters, digits, and `_`, not starting with a digit (`height`, `frequency_2`, `p`).
- **Quoted name**: `"Point Count"`. Referenced in expressions by its `snake_case` key (`point_count`), or given an explicit key via `as`: `"Scale" as random_scale: Float`. A graph of a module is called by its name quoted after the module when that name is not identifiers joined by `::`: `c2::"parallel contour 2d"(…)`; `m::"a::b"` is the name `m::a::b`, written so.
- **String**: `"…"` on one line, its characters as written but for `\`, which starts an escape: `\"`, `\\`, `\n` (a line feed), `\t`, `\r`, and `\u{…}`, any character by its code in 1 to 6 hex digits (`\u{1F600}`), a Unicode scalar value (at most `10ffff`, no surrogate). Another escape is an error at its `\` (`unknown escape '\q': a string's escapes are \", \\, \n, \t, \r and \u{…}, a character's code in 1 to 6 hex digits`), and so is a line break inside a string (`unclosed string`), written `\n`. A quoted name, a description, a frame's title, a look's label and the file of a `use` are strings. Tree → Text writes `\"`, `\\`, `\n`, `\t`, `\r`, every other control character (U+0000 to U+001F, U+007F) as `\u{…}` in lowercase hex without leading zeros (`\u{1b}`), and any other character as itself: any string reads back as it was.
- **Reserved words**: `graph`, `return`, `true`, `false`, `and`, `or`, `xor`, `not`, `dot`, `cross`, `inf`, `nan`. `inf` and `nan` are floats, infinity and not a number, written so wherever a number is ([5](#5-expressions)): `-inf` is the negation of `inf` as `-1.0` is of `1.0`, a NaN of any sign is written `nan`, and `inf_x`, `Inf` are names. A reserved word names nothing: `inf = 1.0`, an input, an item or a type parameter of that name is refused at the word (`'inf' is a reserved word: choose another name`). Host sockets matching a reserved word take a trailing `_` (`not_`, `inf_`), and a label or a name that is one is written quoted (`."inf"`).
- **Contextual keywords**: `use`, `from`, `_`. The zones are no words of the language: `repeat`, `simulate` and `foreach` are names a host gives to calls that take a body ([6](#6-calls-with-a-body-and-nameless-graphs)), and may name a state, a local or a graph.
- **Enum values**: an identifier in a call's settings is an enum value, or a template's type: `Math[POWER]`, `StoreNamedAttribute[domain: FACE]` ([5](#5-expressions)).

## 3. Graph Declaration

```bn
[kind][(options)] graph name(inputs...) -> outputs {
  body...
}
```

A graph with a name is declared at the top of a file. Inside a body, `graph(inputs...) -> outputs { body... }`, with no name and no kind, is a value: a nameless graph ([6](#6-calls-with-a-body-and-nameless-graphs)).

- **Kind**: `geometry`, `shader`, `compositor`, `vector`, `pixel`.
- **Options**: `geometry(is_tool: true, is_mode_edit: true) graph ...`.
- **Outputs**: Single type `-> Geometry` or named tuple `-> (Mesh: Geometry, Centers: Geometry)`.
- **Vector size**: an input's is the size of its default (`uv: Vector = (0.5, 0.5)` is a 2D vector); an output, having no default, says it as an option (`-> (UV: Vector(dimensions: 2))`).
- **Docstring**: An optional string literal as the first statement of the body.
- **Deprecated**: the option `deprecated` marks a graph on its way out, with what to use instead in quotes, or `true` to say nothing more. It is no setting of the tree: the graph is built and called as before, and each call of it, from the same text or through a `use` of its module, is a **warning** at the call (`old.bn:9:10  warning: 'plane' is deprecated: use Grid`). A warning is not an error: `base-node check` prints it and its result is unchanged, the add-on lists it under the errors and builds the tree. A graph that is deprecated itself calls deprecated graphs without a warning, and a text is not told of the calls inside the modules it uses. Tree → Text writes the mark back. Any other value (`deprecated: SOON`) is an error; `deprecated: false` is a graph that stays.
- **Precision**: a number written with a point or an exponent lands in a 32-bit float (a Float socket or setting, a component of a vector, a color or a rotation, a default or a bound of a Float input), which Blender keeps as its nearest IEEE 754 single precision number. When the shortest decimal that reads back as that number is another number than the one written, the checker warns where it is written, and the tree holds Blender's value, the one it reads back to: `t.bn:2:20  warning: precision lost: 16777217.0 is stored as 16777216.0 (IEEE 754 single precision)`. `0.1`, `1e-7` and `3.141593` read back as written: no warning. `base-node check` and the add-on show it as any warning. Tree → Text writes a value unless it is, bit for bit, the one the text leaves out (a new node's, a new socket's): `0.79999995` beside a default of `0.8`, `5e-07` beside `0.0`, `-0.0` beside `0.0`, a bound of `3.40282e+38` beside the largest float are written, each as that shortest decimal, so that the tree built back holds the same float32.

  ```bn
  geometry(deprecated: "use Grid") graph plane(size: Float) -> Geometry {
    "A square of that size"
    return Grid(size_x: size, size_y: size, vertices_x: 2, vertices_y: 2)
  }

  geometry graph field() -> Geometry {
    return plane(1.0)  // warning: 'plane' is deprecated: use Grid
  }
  ```

### 3.0 Shader and Compositor Graphs

A `shader` or `compositor` graph is a node group of that tree type, called from the graphs of the same kind like any other. Interface types are the tree's own: a shader tree has no `Geometry`, a compositor tree no `Shader`; zones too (`simulate` and `foreach` are Geometry Nodes', a compositor has no `repeat`). Implicit defaults (`p: Vector = Position()`) are for geometry trees only.

```bn
shader graph rust(uv: Vector) -> Shader {
  n = NoiseTexture(vector: uv, scale: 8.0)
  return PrincipledBSDF(
    base_color: ColorRamp(factor: n.factor).color,
    roughness: n.factor * 0.5 + 0.4)
}

compositor graph look(image: Color) -> Color {
  return image
    |> Glare(type: "Fog Glow").image
    |> ColorBalance("Base Lift": 0.95)
}
```

- **Material Output**: a shader graph no other graph calls, whose first output is a `Shader`, is also a material of its name. The material holds the group's node, linked to the Material Output by output name (`surface`, `volume`, `displacement`, `thickness`), else its first `Shader` output to Surface. The group's inputs are the material's settings, kept when the text is built again. A material of that name the add-on did not make is left alone. A graph of the same text, before or after it, sets it by name (`SetMaterial(material: rust)`).
- **A material's own tree**: `shader(material: true) graph Clay() -> (surface: Shader, displacement: Vector)` is not a node group but the tree of the material `Clay`, built in place (made when the file has none of that name). It takes no input; its outputs are the Material Output's sockets by key, with their types (`surface: Shader`, `volume: Shader`, `displacement: Vector`, `thickness: Float`), and its return is the Material Output, which renders for every engine unless `target` says otherwise (`shader(material: true, target: EEVEE)`). Another Material Output is a node of the text (`MaterialOutput(…)`). No graph calls a material, and `use` does not bring one: a module shares node groups. A graph of the same text, before or after it, sets it by name (`SetMaterial(material: Clay)`), and so do the graphs of files imported together, whatever their order.
- **Composite**: in Blender 5 the Group Output of a compositor group is the Composite, and its first `Color` input receives the render. A compositor graph no other graph calls, whose first output is a `Color`, becomes the scene's compositor effect when the scene has none.
- **A module's graph in another kind of tree**: a graph that a `use` brings can be called from a graph of any kind. It is built again for the caller's kind of tree, in a group of its own (Blender names node groups once for every kind of tree): `gain`, called from a compositor graph, is built into `gain (Compositor)`, and so are the graphs it calls (`bias (Compositor)`). The calls and the `use` are written back as they were (`use math (gain)`, `gain(…)`). Its body must work in that tree: a graph of math nodes alone (Math, Vector Math, Map Range, Mix…) does, one with a node that tree lacks is refused with the reason (`'random_direction' is a geometry graph that cannot be built in a shader tree: unknown node 'RandomValue' in a shader tree`). A comparison is not such a node: it is written as each tree can ([5](#5-expressions)). An input that takes a field from the context (`p: Vector = Position()`) has none there: the call gives it. A graph of the text itself is called from its own kind of tree only.

  ```bn
  use math (gain, luminance)

  compositor graph contrast(image: Color, amount: Float = 0.3) -> Color {
    return Mix[RGBA](factor: gain(luminance(image), amount), a: image, b: (1.0, 1.0, 1.0, 1.0))
  }
  ```
- **Pipes**: the image a filter works on is written first and passed on with `|>`, through the output it picks when the filter has several (`Glare(…).image`), as a geometry is in a geometry tree.
- **Datablocks**: a datablock is written by its name, in the input or the setting that holds it: `ObjectInfo(object: "Thing")` (an input), `ImageTexture[image: "Bricks"](vector: uv)` (a setting); a datablock's input node is a call like any other, `o = Object[object: "Thing"]()`, linked or not, and a named string is a String node, which a datablock input refuses with what to write. A datablock the file does not have leaves its input or its setting empty: the tree is built, with one warning per datablock missing (`t.bn:4:7  warning: missing datablock: Font "Title"`). Blender's own font is `"Bfont Regular"`, whatever the file names it (a library appended beside it brings its copy as `Bfont Regular.001`): Tree → Text writes it by that name, and Text → Tree finds it under any name, loading it when the file has none. `_` is no datablock at all, where a new node holds one: `StringToCurves(string: s, font: _)`, `Font[font: _]()`. A Sound has no input node: a graph input (`sound: Sound`) or its name in place gives it.
- **Materials by name**: a material is written by its bare name, as a graph is called: `SetMaterial(material: Clay)`, `m: Material = Clay`. It is the material a graph of the text defines, else the file's. A name bound in the graph is that value, not a material: a material named like a binding of the graph, or whose name makes no identifier (`"Old Brick"`), is written in quotes, as is any other datablock (object, collection, image).

### 3.1 Types

| Type | Default | Description |
|---|---|---|
| `Float` | `0.0` | Scalar float |
| `Int` | `0` | Signed integer |
| `Bool` | `false` | Boolean |
| `Vector` | `(0.0, 0.0, 0.0)` | 2D/3D/4D vector (a 2D or 4D tuple in a formula: [5](#5-expressions)) |
| `Color` | `(0.0, 0.0, 0.0, 1.0)` | RGBA color (`#rrggbb`, `#rgb`, or tuple) |
| `Rotation` | `(0.0, 0.0, 0.0)` | Euler / quaternion rotation |
| `Matrix` | Identity | 4×4 transform matrix |
| `String` | `""` | UTF-8 string |
| `Menu` | — | Enum selector |
| `Geometry` | — | Mesh, curve, points, instances, or volume |
| `Image` | — | 2D pixel buffer |
| `Material` | — | Material reference |
| `Bundle` | — | Composite socket container |
| `Closure` | — | Deferred subgraph |

### 3.2 Parameters

```bn
name as key: Type(subtype: DISTANCE) = default_value in min..max
```

- `= default_value`: Default literal or implicit input (`Position()`, `Normal()`, `Index()`, `ID()`).
- `in min..max`: Numeric bounds (`in 0.0..1.0`, `in 0.0..`, `in ..1.0`).

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

*Since the specification version 0.12.0. The Python and Rust parsers read and print it, the
Python checker checks it, and the Blender add-on builds and reads back its groups. The Rust crates
have no checker: they build no template.*

A Blender node group has one type per socket: a graph that reads an attribute with a fallback is
written once for a `Float`, again for a `Vector`, again for a `Color`. A **template** is a graph
generic over the type of a value, written once and built into a node group of its own for each type
it is called with, as a module's graph is built again for each kind of tree that calls it
([3.0](#30-shader-and-compositor-graphs)).

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
  template is built for, each a type of [3.1](#31-types). A type parameter is named like a type
  (a capital first letter), not like a type of 3.1 (`<Float: …>` is refused), and not like an input
  or an output of the graph.
- **In the body**, `T` stands for the type wherever a type or a node's type setting goes:
  - an input's or an output's type: `fallback: T`, `-> (value: T)`;
  - an item's type in a zone or an item node: `repeat(n, v: T = fallback)`, `CaptureAttribute(g, v: T)`;
  - a node's setting that picks a type (`data_type`, `input_type`, `domain` aside), in its brackets:
    `NamedAttribute[T](name: n)` by position, `Mix[data_type: T](…)` by name, is the value of that
    setting for the type. By position, `T` goes to the first setting of the node, in Blender's order,
    that has a value for its type. A setting names a type in its own words, so `T` takes
    the first of the setting's values that is that type: `Vector` is `VECTOR` for a Switch and a Mix,
    `FLOAT_VECTOR` for a Named Attribute and an Evaluate at Index; `Color` is `RGBA` or `FLOAT_COLOR`;
    `Rotation` is `ROTATION` or `QUATERNION`; `Matrix` is `MATRIX` or `FLOAT4X4`; `Float`, `Int`,
    `Bool`, `String` are `FLOAT`, `INT`, `BOOLEAN`, `STRING`.
  - the call of another template: `index_mix(value, i)` infers its own type from `value`, or
    `index_mix<T>(value, i)` passes it on.
- **A default** of an input of type `T` must suit every type of the constraint: `= (1.0, 1.0, 1.0)`
  in `<T: Vector | Color>`. A field from the context (`= Position()`) has one type and is refused.
- **Checked for every type**: a module's template is checked once for each type of its constraint,
  so that the author, not the caller, meets the error: `attribute_or<Matrix>: NamedAttribute has no
  data_type for Matrix` (a made-up example). Its groups are built only for the types it is called with.

**The type of a call** is inferred from its arguments, or written:

1. `attribute_or<Vector>("rest", p)` writes it: the arguments are then linked as to any group,
   converted when Blender converts them (an `Int` to a `Float` input). A name that holds a value
   where it is written takes no types: an input of the graph, a name an earlier statement bound
   (in a frame too), an item of the body it is in, an input of the graph with no name it is in.
   There `<` compares: `max(a < b, c > (d))` is two comparisons when `a` is one of them.
2. Else each argument given to an input of type `T` that is linked (a name, a node's output, an
   input of the calling graph) gives its type, and all must give the same: `T` is that type.
3. Else, with no linked argument, a literal gives its own type: `2.0` a `Float`, `2` an `Int`, `true`
   a `Bool`, `(x, y, z)` a `Vector`, `(r, g, b, a)` and `#rrggbb` a `Color`, `"text"` a `String`.
4. Else the call is refused: no default type is chosen.

The type found must be one of the constraint; there is no conversion while inferring (a `Vector` linked
to `<T: Float | Color>` is refused, not converted). An output gives no type: a call is typed by what goes
in, never by where its value goes.

**The group** of a type is named after the template and its types, in parentheses as for a kind of tree:
`attribute_or (Vector)`, `blend (Float, Color)` for two type parameters. Built for another kind of tree
too, it is `attribute_or (Vector) (Compositor)`: the types first, then the kind, so a type `Geometry` is
never taken for the kind `geometry`. Each group says the template and the types it was built from, as a
variant says its graph and module, and is built once whoever calls it.

**Tree → Text** writes the `use` and the call, not the group: a call to `attribute_or (Vector)` reads back
`attribute_or(name, p)`, and the type is written (`attribute_or<Vector>(…)`) only when the arguments as
read back do not infer it, by the rules above. A group the add-on did not build from a template stays the
group it is: Molecular Nodes' `Fallback Vector` reads back as a graph of its own, never folded into a template.

**Where**: a template is a module's graph, brought by a `use`, as a graph built for another kind of tree
is; a text calling its own template is refused (`'attribute_or' is a template: a template is a module's
graph, brought by a use`). A text may still define a template, which is checked for each of its types and
builds no group. Tree → Text can then write back every call from the group's tags alone. A
template in the text itself is left for later: Tree → Text would have to write the template back from one
of its groups.

**Kinds of tree and targets.** Types and kinds of tree combine: a call from a compositor graph builds the
template for the caller's tree and for the type, and each type is checked in that tree
(`'attribute_or<Vector>' is a geometry graph that cannot be built in a compositor tree: no
NamedAttribute in a compositor tree`). A module that promises a target (`@target`) must have every
type of its templates' constraints in it: a template that is a `compositor graph`, held to `blender`, cannot list `Geometry`.

**Errors**

| Case | Message |
|---|---|
| Nothing infers the type | `attribute_or: write the type of T, as attribute_or<Float>(…); no argument gives it` |
| Arguments disagree | `attribute_or: T is Vector by 'fallback' and Color by 'other'; write the type, as attribute_or<Vector>(…)` |
| A type out of the constraint | `attribute_or: T cannot be String; T is one of Float, Int, Bool, Vector, Color, Rotation, Matrix` |
| Too many or too few types | `blend takes 2 type(s) (T, U), not 1` |
| Types given to a graph or a node | `'double' is not a template: it takes no type` |
| A constraint's unknown type | `unknown type 'Flot' in the constraint of T; expected: Float, Int, …` |
| A parameter named like a type | `'Float' is a type: name a type parameter otherwise, such as T` |
| A parameter twice | `type parameter 'T' defined twice` |
| A parameter named like an input | `'T' is a type parameter and an input or output of 'attribute_or'` |
| A template that calls itself | `recursive call: 'attribute_or<Float>' calls itself` |
| A setting without the type | `T is Matrix: Mix has no data_type for Matrix; values: FLOAT, VECTOR, RGBA, ROTATION` |
| One type's check fails | the error of that type, after the template and its type: `attribute_or<Matrix>: …`; an error of every type is written once, as it is |
| A text's own template | `'attribute_or' is a template: a template is a module's graph, brought by a use` |

**What templates do not do.** A template varies a type, not a value or a setting. T3D's `easeQuad` to
`easeQuint` have one body but for the exponent (2 to 5) and a factor of 2ⁿ⁻¹: one graph with an input
`power: Float = 2.0` and `pow(2.0, power - 1.0)` makes them one today, without templates. Molecular Nodes'
`Sample Mix Float` and `Sample Mix Angle` differ by a subtype (`ANGLE`), which is not a type either.

**Against the corpus.**

| Groups | One template? |
|---|---|
| Molecular Nodes' `Fallback Float`, `… Integer`, `… Boolean`, `… Vector`, `… Color`, `… Rotation`, `… Matrix` (7) | Yes: `attribute_or` above. Their outputs are named after the type (`Value`, `Output`, `Boolean`, `Color`, `Matrix`): the template has one name. `Fallback Geometry` is another graph (a test of an empty geometry) |
| `Index Mix Float`, `… Vector`, `… Color`, `… Rotation` (4) | Yes, `<T: Float \| Vector \| Color \| Rotation>`, the types Mix takes: `Mix[T]` and both `EvaluateAtIndex[T]`. The Color one alone clamps (`clamp_result: true`) and has a default (1, 1, 1): a template has one of each |
| `Sample Mixed Vector`, `… Color`, `… Rotation` | Yes, calling `index_mix(value, index)`, which infers its type from the template's own `T` |
| `Sample Mix Float`, `… Vector`, `… Angle` | In part: Float and Vector are one template, but the Vector one takes `Position()` by default, a field of one type, so its callers give it. Angle differs from Float by its subtype, not its type, and stays a graph of its own |
| T3D's `easeQuad`, `easeCubic`, `easeQuart`, `easeQuint` | No, and no need: one graph with a `power` input (above) |

**Edition and versions.** The syntax is added to Edition 2026: every text valid before reads as before,
as a `<` after a graph's name was a syntax error, and `f<Vector>(x)` two comparisons in a row, which the grammar refuses. Before LTS this is a minor version of the
specification (0.11.0 → 0.12.0), of the Python, Rust and Blender packages with it
([versioning, 5](versioning.md#5-lifecycle--stability-policy-pre-lts-vs-lts)), and of the modules of
the standard library that turn their graphs into templates. A text using templates is not read by a
toolchain before 0.12.0: it is refused there at the `<`.

## 4. Statements

| Syntax | Meaning |
|---|---|
| `x = expr` | Bind expression output |
| `size = 10` | Named constant: an input node of its own (`Value`, `Integer`, `Boolean`, `Vector`, `Color`, `String`) named `size`; a tuple or a menu takes its value. A setting takes no name: no wire feeds it, so its value is written in its brackets. A datablock is no literal: its input node is a call, `title = Font[font: "Bfont Regular"]()` ([Datablocks](#30-shader-and-compositor-graphs)) |
| `return expr` | Single output return |
| `return (A: e1, B: e2)` | Multi-output return |
| no `return` | A graph that leaves its return out has no Group Output node: its outputs, if it has any, give nothing, and the checker warns of them (`warning: no return in 'g': its tree has no Group Output node, its outputs give nothing`). A material's own tree returns |
| `"Title" #color { ... }` | Visual frame (`#e73` or named color `#teal`) |
| `"Title" .. { ... }` | Continuation of a previously opened frame |
| `"Note" #color {}` | Standalone frame note |

A field of the return may be a literal: the value of that output when nothing feeds it, which a shader group gives (`return (color: (0.0, 0.0, 0.0, 0.0))`). Tree → Text writes it when it is not the value of a new output.

An input node whose value no literal makes is a call that gives it in its settings, a tuple of as many
numbers as it holds: `Rotation[rotation_euler: (0.1, 0.0, 0.0)]()`, `Vector[vector: (1.0, 2.0, 3.0, 4.0)]()`
(its `vector_dimensions` follow the tuple unless written), `IntegerVector[vector: (1, 2, 3)]()` (whole
numbers). The Normal node of a shader or a compositor tree holds its vector on its output, a setting too:
`Normal[normal: (0.0, 0.7071, 0.7071)]()`, three numbers, the vector of a new node (0, 0, 1) when not written.
The Value and RGB nodes, which also hold their value on their output, are named constants (`size = 0.5`).
Tree → Text writes them so, and a Menu node by the item it picks (`Menu[value: B]()`), set once it is linked
to the menu it feeds.

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
- **Node call**: `NodeName[SETTING, setting: value](geometry, socket: value)`, the node by its UI name in one word ([5.1](#51-node-names)).
- **Settings**: what no wire can feed, in the brackets: an enum, a boolean, a number, a string, a datablock, a ramp or curves, the value an input node holds. A setting that holds a set of enum values (a flag set, as `mode` of Set Handle Type) takes a tuple of them, in any order, each once, as an array setting takes its numbers: `SetHandleType[mode: (LEFT, RIGHT)](curve)`, `mode: (LEFT,)` for one, `mode: ()` for none; Tree → Text writes them in Blender's order. A bare value is refused there (`mode is a set of values, in parentheses: mode: (LEFT,)`), and so is a value it does not hold (`mode: unknown UP; values: LEFT, RIGHT`) or one given twice (`mode: a value given twice`). A setting by position is an enum value: it goes to the first enum setting of the node, in Blender's order, that holds that value (`Compare[INT, EQUAL]`, either order; `AlignEulerToVector[X, pivot_axis: Z]`, as both `axis` and `pivot_axis` hold `X`), and a template's type parameter to the first that has a value for its type (`NamedAttribute[T]`). Every other setting is named. Tree → Text writes an enum value by position when no other enum setting of the node holds it, else by name, the settings by position first, each in Blender's order, and only those that differ from a new node's (a Math's `operation` always). An argument in parentheses is always an input: `Math(Value: a, Value_001: b, operation: ADD)` is refused as any unknown input is (`Math has no input 'operation'; inputs: …`). The errors: `Math has no setting 'clamp'; did you mean use_clamp?; settings: operation, use_clamp`, `no setting of Math takes ADDD; did you mean ADD?`, `setting 'operation' given twice`, `Math: a setting by position is an enum value; name the others, Math[operation: …]`, `use_clamp expects a boolean value`; a graph, a group or a function has none (`double has no settings`).
- **Inputs**: a node's inputs are given by name, the key of their socket: `SetPosition(geometry, offset: o)`, `Math[ADD](Value: a, Value_001: b)`. A position depends on Blender's order of the sockets, which a setting or another version of Blender changes; a name does not. By position go only the values a name cannot tell, first and in the order of the sockets: the geometry the node works on, its first input when linked (the pipe's; the image a node works on in a compositor tree, none in a shader tree), the items of a switch (`IndexSwitch(0, a, b)`), and the values of a multi-input, joined in the order written, the first one at the top of the socket in Blender, with the inputs before them (`MeshBoolean[DIFFERENCE](a, b, c)`). This is the canonical form, the one a tree reads back to. Any other value by position is an error at the value, which says the name to write: `Math: input 1 is 'Value'; write it by name, Math[ADD](Value: a, …)`. The fixed inputs of Separate Bundle, Evaluate Closure and Closure to List go first by position too (`SeparateBundle(b) -> (…)`, [6.1](#61-blenders-zones)). A graph, a group of the file and a function take their values by position or by name: their signature is in the text or the language, not in Blender. The add-on's editor writes the names (its suggestions after `(` are the inputs to name, and *Format* and *Name Inputs* name the values by position), and so does `base-node fmt --names`, without Blender
- **Inputs of one name**: a socket's key is its UI name in snake case (`Base Color` is `base_color`). When two inputs of a node share a name, text tells them apart by Blender's identifier: `Math[PINGPONG](Value: a, Value_001: b)`. The two `Shader` inputs of Mix Shader and Add Shader have keys of their own instead, `a` and `b`, as the Mix node names its inputs A and B: `MixShader(factor: f, a: metal, b: paint)`, `AddShader(a: glow, b: coat)`. Their identifiers (`Shader`, `Shader_001`) are still read; a tree reads back to `a` and `b`
- **A tuple chooses the type**: a tuple only fits a `Vector` (`Rotation`) or a `Color` socket, of as many numbers as it holds (a `Color` also takes `(r, g, b)`, its alpha 1). A node whose socket types follow a setting the call does not write (`input_type` of `Switch`, `data_type` of `Mix`, `Compare`, `StoreNamedAttribute`…) takes the type of its tuples when one would reach a number input: `Switch(switch: b, false_: (1.0, 0.0, 0.0), true_: Position())` is a Vector switch, a `Color` one when a tuple has 4 numbers. The items of `IndexSwitch` and `MenuSwitch` take the type of their first item, or of their tuples when it cannot hold them. A linked value, a named constant among them, chooses nothing: `Switch(switch: b, false_: Position(), true_: Position())` stays a Float switch. A tuple no socket of the node can hold is an error. Example: [`examples/tuple_tiles.bn`](../examples/tuple_tiles.bn), its [render](../site/images/showcase-tuple-tiles.png) and the [nodes it builds](../site/images/tuple-tiles-nodes.png)
- **Group with no tree**: `Group()` is a Group node that calls no node group (its group is missing from the file). It has no sockets: it takes no input and gives no output
- **Ramps and curves**: the stops of a Color Ramp and the points of a curve (RGB Curves, Float Curve, Vector Curves, Hue Correct, Time Curve) are the value of their property, a setting, written only when they differ from a new node's: `ColorRamp[color_ramp: Ramp(…)](factor: f)`, `FloatCurve[mapping: Curve(…)](value: v)`.
  - `color_ramp: Ramp((0.0, (0.0, 0.0, 0.0, 1.0)), (0.5, (1.0, 0.5, 0.0)), interpolation: EASE)`: a stop is `(position, color)`, its position from 0 to 1, its color RGB or RGBA; the settings `interpolation`, `color_mode` and `hue_interpolation` take Blender's values. The stops read back in the order of their positions.
  - `mapping: Curve((0.0, 0.0), (0.4, 0.9, VECTOR), (1.0, 1.0))` for a node of one curve: a point is `(x, y)`, or `(x, y, handle)` with a handle `AUTO_CLAMPED` or `VECTOR` (`AUTO` by default); two points at least.
  - `mapping: Curves(c: Curve(…), r: Curve(…))` for a node of several: each curve by its channel, the others as a new node's: `r`, `g`, `b`, `c` (RGB Curves, `c` for all three), `x`, `y`, `z` (Vector Curves), `h`, `s`, `v` (Hue Correct).
  - The curve mapping's settings go in the `Curve` of one curve, or in `Curves`: `extend` (`EXTRAPOLATED`, `HORIZONTAL`), `tone` (`STANDARD`, `FILMLIKE`), `use_clip`, `clip_min_x`, `clip_min_y`, `clip_max_x`, `clip_max_y`, `black_level` and `white_level` (`(r, g, b)`).
- **Output access**: `node.output_name`
- **Vector swizzle**: `v.x`, `v.y`, `v.z`, of a vector, a color or an integer vector (one Separate XYZ, which leaves the alpha out)
- **Pipe**: `a |> f(b)` is `f(a, b)`: into a node, `a` is the input that goes first unnamed (the geometry it works on, see Inputs), into a graph or a function its first input. The value passed on may be one output of a node of several, in every kind of tree: `mesh |> SeparateGeometry(selection: s).selection |> SetPosition(…)` is `SetPosition(SeparateGeometry(mesh, selection: s).selection)`; a tree reads back to the pipe. Its canonical layout is in [5.2](#52-canonical-layout)
- **Math operators**: `+`, `-`, `*`, `/`, `<`, `<=`, `>`, `>=`, `==`, `!=`, `and`, `or`, `xor`, `not`
- **Comparisons**: `<`, `<=`, `>`, `>=`, `==`, `!=` are a Compare node where the tree has one (a geometry tree, and a compositor tree of Blender 5.3), which gives a `Bool` and compares numbers, vectors, colors and strings. A shader tree has no Compare node, nor has the compositor of Blender 5.2 LTS ([targets](targets.md#what-blender-53-has-that-blender-52-lts-has-not)): there they compare numbers only, with Math nodes that give a `Float`, 0.0 or 1.0, so `height > 0.5` is written the same in every tree and a module's graph that compares builds in a shader tree too. `a > b` and `a < b` are Math's Greater Than and Less Than; `a >= b` is `1.0 - (a < b)` and `a <= b` is `1.0 - (a > b)`, two nodes; `a == b` is Math's Compare, its Epsilon 0.001 as that of a new Compare node (Math's own default, 0.5, is not written by `==`), and `a != b` is `1.0 - (a == b)`. Such a tree reads these nodes back as the operator, those written by hand too: `Math[GREATER_THAN](Value: a, Value_001: b)` reads `a > b` and `1.0 - (a < b)` reads `a >= b`; a Math Compare of another Epsilon stays a call. In a tree that has Compare, Math's comparisons stay calls (`Math[GREATER_THAN](Value: a, Value_001: b)`). Example, in a shader graph: `mask = (height > 0.5) * (slope <= 0.2)` is three Math nodes for the comparisons and one for the product
- **Ternary**: `cond ? a : b` is `a` where the condition holds, `b` elsewhere. It binds loosest, looser than `|>`: its branches are whole expressions (`big ? mesh |> SubdivideMesh() : mesh`), the last one may be a ternary again (`a > b ? 1.0 : a < 0.0 ? 2.0 : 3.0` reads `a > b ? 1.0 : (a < 0.0 ? 2.0 : 3.0)`), and it takes parentheses as a condition, as the first branch, as an operand (`(on ? a : b) * 2.0`) and before a pipe (`(on ? fine : coarse) |> SetShadeSmooth()`). The node it writes depends on the kind of tree:
  - in a **geometry** tree, a Switch (`Switch(switch: cond, false_: b, true_: a)`) of the type of its branches, every type Switch takes: `shape = dense ? SubdivideMesh(mesh) : mesh` is a Geometry switch, `radius = index > 4 ? 0.1 : 0.2` a Float one, chosen for each element when the condition is a field;
  - in a **shader** tree, where a Switch takes one value for the whole surface, a Mix by the condition (`Mix(factor: cond, a: b, b: a)`, the value when false being its A) for `Float`, `Vector`, `Color` and `Rotation` branches, and a Mix Shader for `Shader` branches: `color = height > 0.5 ? snow : rock`, `surface = facing > 0.5 ? DiffuseBSDF() : GlossyBSDF()`;
  - in a **compositor** tree, where a Switch takes one value for the whole image too (given an image as condition it gives its False input everywhere), the same Mix: `image = mask > 0.8 ? glow : image`.

  The type is the one its branches give, by the rule of `Switch`: with a tuple, a Color when one has 4 numbers, else a Vector; else the type of the first linked value, the one when false first, else of the first literal. The other branch must be of that type or one Blender converts to it. A Mix carries no `Int` and no `Bool`: such branches go in as `Float`. A type no node of the tree carries is refused with those it takes: `'? :' chooses between Float, Vector, Color, Rotation and Shader in a shader tree, not String`. Where it is a Mix or a Mix Shader the condition must be one, a `Bool` or a comparison (by its name too: `hot = t > 0.5`, then `hot ? a : b`), as a Mix by any number blends and does not choose: `f ? a : b` on a `Float` is refused, to be written `f > 0.5 ? a : b`, or `Mix(factor: f, …)` to blend. **Outside a geometry tree's Switch both branches are always computed**: a Mix evaluates its two inputs for every pixel; a geometry Switch whose condition is a single value evaluates only the branch it gives.

  A tree reads back to a ternary the nodes one writes, and only those. In a geometry tree, a Switch whose condition is linked, whose two branches the text can write (a link or a literal, written even at the socket's default: `on ? x : 0.0`) and whose type is the one they give; any other stays a call (`Switch[GEOMETRY](switch: on, true_: mesh)` has no geometry to write when false). In a shader or a compositor tree, a Mix whose settings but `data_type` are a new node's and whose factor comes from a `Bool` or a comparison, and a Mix Shader of such a factor; a Mix by any other number stays `Mix(factor: f, …)`, and a Switch there stays `Switch(…)`. In a geometry tree a Mix is never a ternary
- **Vector products**: `u ⋅ v` (`u dot v`), `u × v` (`u cross v`)
- **Math functions**: `sin`, `cos`, `tan`, `asin`, `acos`, `atan`, `atan2`, `sqrt`, `pow`, `exp`, `log`, `abs`, `min`, `max`, `smooth_min`, `smooth_max`, `clamp`, `floor`, `ceil`, `fract`, `mod`, `length`, `normalize`, `distance`. `smooth_min(a, b, k)` and `smooth_max(a, b, k)` are Math's Smooth Minimum and Smooth Maximum, of numbers only, `k` the distance over which the two blend: `smooth_min(d1, d2, 0.1)` joins two distance fields without a crease
- **Operands of a formula**: a number, a vector, a color, or an integer vector (Image Info's `dimensions`, Image Coordinates' `pixel`), which Vector Math takes as floats as Blender converts it: `length(ImageInfo(image).dimensions * 0.5)`. A tuple operand of Vector Math is converted the same way: `(x, y)` is `(x, y, 0.0)` and `(r, g, b, a)` leaves its alpha out, so `center + (0.1, 0.0)` and `(1.0, 0.4, 0.1, 1.0) * m` are written as an author of 2D images writes them; they read back with three numbers (`center + (0.1, 0.0, 0.0)`). Into a node's input a tuple has the socket's size, and one of another size is refused with the tuple to write: `Switch.false_ expects a Vector of 3 numbers, receives 2; write (1.0, 0.0, 0.0)`
- **A graph is not named like a function**: a call of `max(…)` is always the function, so a graph named like one of the functions above, or like `xnor`, `nand`, `nor`, `imply`, `nimply`, is refused where it is declared: `graph 'max' has the name of the function max: max(…) is a Math or Vector Math node; give the graph another name` (the stdlib's are `maximum`, `minimum`). A node group of Blender of such a name reads back to a text that is refused the same way: rename the group

### 5.1 Node Names

A node is written by its **UI name in one word**, as Blender's *Add* menu shows it in English: *Principled BSDF* is `PrincipledBSDF`, *Noise Texture* `NoiseTexture`, *Set Position* `SetPosition`. It is the only name a text is read by, and the one a tree reads back to. The name is the label the node type defines (`bl_rna.name`), never its translation: a text reads the same whatever the interface language.

The label becomes one word by one rule:

- accents are dropped: *Bézier Segment* → `BezierSegment`;
- `&` reads `And`: *Field Min & Max* → `FieldMinAndMax`;
- every other sign that is not a letter or a digit (space, `/`, `-`, `(`, `)`) splits words, and each word keeps its letters as the label writes them, its first one in capital: *Separate XYZ* → `SeparateXYZ`, *Evaluate at Index* → `EvaluateAtIndex`, *Hue/Saturation/Value* → `HueSaturationValue`, *Mix (Legacy)* → `MixLegacy`, *Stabilize 2D* → `Stabilize2D`.

Two exceptions keep the name a node had before (its `bl_idname` without the prefix `GeometryNode`, `FunctionNode`, `ShaderNode`, `CompositorNode`, `TextureNode` or `Node`):

- a label that starts with a digit makes no identifier: *3D Cursor* is `Tool3DCursor`;
- when two nodes of one tree kind have the same UI name, the one that tree's *Add* menu offers takes it and the other keeps its former name. In Blender 5.3 this happens twice, both in a compositor tree: *RGB Curves* is `RGBCurves` for the compositor's own node (`CompositorNodeCurveRGB`) and `RGBCurve` for the shader one (`ShaderNodeRGBCurve`); *Switch* is `Switch` for the one of every tree (`GeometryNodeSwitch`) and `CompositorNodeSwitch` for the compositor's older one.

An unknown name is compared with the node names case, spaces and underscores aside, so `noise_texture` suggests `NoiseTexture`.

### 5.2 Canonical Layout

The formatter and a tree read back print one layout, set by a width of 100 characters per line, indentation included (rustfmt's default):

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

- **A call with a body**: a call, its name qualified or not, its settings in brackets if any and its arguments as any call's, then `->` and the body in braces. The arrow makes the body: `x = f(a)` followed by `{ … }` on the next line is a call, then a frame with no title ([4](#4-statements)). Which names take a body, what their arguments are, what the body sees beside the names outside and what it returns, the host says; a body given to any other name is an error at the call (`'Grid' takes no body: repeat, simulate and foreach do`).
- **A nameless graph**: `graph` followed by `(`. It writes no tree kind: it has the kind of the graph that holds it. Its inputs and outputs are written as a graph's (`-> Float` or `-> (name: Type, …)`, quoted names, options), without panels or `as` keys. In the body the inputs are names; the names outside are seen too, and their values are captured. The value is called by the name it is assigned to, its inputs by name: `shape(t: 0.25)`.

Elsewhere than as the value of an assignment, both are errors: `a call with a body is the value of an assignment: r = repeat(…) -> { … }`, `a graph with no name is the value of an assignment: f = graph(x: Float) -> Float { … }`.

### 6.1 Blender's Zones

In Blender, the calls that take a body are its zones, and a nameless graph is a Closure zone, a value of type `Closure`:

```bn
// Repeat zone
r = repeat(iterations, val: initial) -> {
  return (val: val * 0.5)
}

// For Each Element zone
out = foreach[FACE](geometry, p: Position()) -> {
  return (geometry: Points(position: p))
}

// Simulation zone
s = simulate(mesh: geometry) -> {
  return (mesh: SetPosition(mesh, offset: (0.0, 0.0, delta_time)))
}

// Closure zone & Bundle
shape = graph(t: Float) -> (h: Float) {
  return (h: sin(t * 6.28) * amount)
}
low = shape(t: 0.25)
b = CombineBundle(factor: 0.5, shape: shape)
```

| Call | Arguments | The body sees | The body returns |
|---|---|---|---|
| `repeat(count, state: start, …)` | The iteration count first, then one state at least, each named | `iteration`, the states | The next value of each state by name, or the value alone for a single state; a state left out goes on unchanged |
| `simulate(state: start, …)` | Named states | `delta_time`, the states | The same, and `skip` |
| `foreach[FACE](geometry, selection: s, item: field, …)` | Its domain in brackets; the geometry first, then `selection` and the input items, each named | `index`, `element`, the input items | Its items by name: the main items, then from the first geometry on, the generated geometry and its attributes |

A call of another shape is an error at the call, which says the shape (`repeat expects iteration count first: repeat(10, state: start, …) -> { … }`, `foreach expects geometry first, then named items: foreach[FACE](geometry, item: field, …) -> { … }`). `repeat` and `simulate` have no settings (`repeat has no settings`); the one setting of `foreach` is its domain, by position or named (`foreach[domain: FACE]`), `POINT` when not written. A call of `repeat`, `simulate` or `foreach` with no body is a call of a node of that name, which no tree has: the brace after it opens a frame.

The inputs and outputs of a Closure zone are items: they take no default value and no range (`a closure item has no default value or range`).

A state cannot go by the names of its zone: `iteration` in a `repeat`, `delta_time` and `skip` in a `simulate`; an input item of `foreach` cannot be `index` or `element`. Names are case-sensitive: a state `Iteration` is its own name, beside `iteration` (`repeat(n, Iteration: 0) -> { return (Iteration: Iteration + iteration) }`). A state named like them in Blender takes a key of its own with `as`, used by the body, the return and the users of the zone:

```bn
s = simulate(mesh: geometry, "Delta Time" as dt: 0.0) -> {
  return (mesh: mesh, dt: dt + delta_time)
}
t = s.dt
```

## 7. Targets

A target is what one destination accepts: kinds of tree, types, zones, implicit inputs and nodes. A
text fits the targets that accept everything it uses; it may promise some with `// @target`, and is
then held to them. See [targets](targets.md).

| Target | Accepts |
|---|---|
| `blender` | Every node of Blender, by kind of tree: a `geometry graph` may use the Geometry Nodes, a `shader graph` the shader nodes, a `compositor graph` the compositor's. In every version of Blender this version of Base Node promises |
| `blender@5.3` | The same in one version of Blender. An LTS says so in its name: `blender@5.2-lts` |
| `blender gltf` | A variant, a word after the target or one of its versions: the shader nodes Blender's glTF exporter turns into a material |
| `blender eevee`, `blender cycles` | Variants, experimental: the shader nodes Blender says each render engine takes |
| `blade` | Blade's Pixel Nodes, and what its translator carries from the compositor graphs of `blender` |

`blender@latest` and `blender@lts` are aliases for a command line; a `// @target` that names one is
an error.

## 8. Limits

A `.bn` text may come from anyone. Reading one ends with a tree or an error, never a crash or a hang: every reader refuses, with an error at the place it happens, a text past one of these limits.

| Limit | Value | What counts |
|---|---|---|
| Source size | 4 MiB | The bytes of the text, in UTF-8 |
| Nesting | 32 | What is open at once: `(…)`, the arguments or options of a call, a `{…}` block (frame, panel, the body of a call or of a nameless graph), each prefix `-` or `not`, and the branches of each `? :` (a chain `a ? x : b ? y : …` opens one per `?`) |
| Expression height | 256 | The nodes one inside another in an expression: a name or a literal is 1, and each operator, call, tuple or `.socket` is one more than the tallest of what it holds. A chain counts for its length: `a + b + c` is 3, and so is a pipe of two steps |
| Integer | 2⁶³ − 1 | The digits of an integer literal; a float literal written with digits must be finite (`1e999` is refused), infinity is written `inf` |

A host that reads the file a `use` names reads a regular file no larger than a source, inside the roots the modules resolve in (§1).

## 9. What the Text Does Not Carry

The promise is that Tree → Text → Tree is exact within one version of Blender: a tree read as text and built back from that text, in the Blender that read it, holds every node, link, setting and value it held, bit for bit, but what this section lists. It holds across versions only as far as Blender does: a value the text leaves out because it is a new node's or a new socket's is the default of the Blender that builds the text, so a default that differs between two versions of Blender is out of the promise. The add-on's tests compare each tree of the third-party libraries with the tree built back, on Blender's data, and fail on any difference but these, by decision:

- **How the editor draws the tree**: the names of the nodes, their locations, sizes and colours (a colour a node holds without showing it too), their colour tags; the frames, their places and which nodes they hold, but for the blocks the text writes ([4](#4-statements)); reroutes, a link through them being one link; what is selected or active (the active item of a list, an interface item selected), a node's panels open or closed, its options or its texture shown, a String node's text box, the view's centre, the default width of a group's node; the label, colour and collapsed state of the nodes the text has no statement for, the Group Input nodes and the input nodes of zones. Of the other nodes, the label, colour, collapsed and muted state are written ([4.1](#41-node-presentation-)).
- **A muted link**: it carries nothing, so it is dropped.
- **Several Group Input nodes**: they are read as one, which gives the interface. Geometry Nodes and shader trees evaluate them alike; the compositor may evaluate a tree of several otherwise, as the `[blender_quirks]` table of a library's manifest records (Compositing Essentials' Film Grain).
- **What a node does not show**: the value of an input its node does not show in its present mode (the third value of a Math that adds), a link into or out of such a socket, which Blender does not follow, and the value of an input that an implicit field feeds (`Normal: Vector = Normal()`).
- **Whether a socket shows**: a socket hidden, its value hidden, a socket unfolded.
- **The default, minimum and maximum of an interface output**: no evaluation reads them. The value of an output nothing feeds is written in the return ([4](#4-statements)).
- **What only the editor reads of a node**: where its warnings go (`warning_propagation`), the iteration of a zone the editor inspects (`inspection_index`), a gizmo pinned on the socket of a group's node (`pin_gizmo`).
- **The tree as a datablock**: its asset mark and asset data (catalog, tags, description, preview), its fake user, the id-name of its node tool (`node_tool_idname`), where the compositor offers it (`allow_usage_in_scene_compositor_effect`, `is_strip_modifier`), and the file a group linked from another .blend comes from: a linked group is read as a graph of the text, and built in the file.
- **The custom properties of add-ons**, on the tree and on its nodes.
- **The identifiers Blender gives and renumbers**: those of the interface items, of the items of a node (Index Switch, Menu Switch, Capture Attribute, bundles, closures, zones) and of the sockets they make.
