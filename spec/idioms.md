# Idioms

Ways of writing a graph that come back in most libraries of node groups. Each is a paragraph and a
graph you can build as it is.

## Name what goes into a node

A node's inputs go by name; only what the node works on comes first without one, the mesh here. A name
stays right when a setting or another version of Blender moves the sockets: with `MULTIPLY_ADD`, Math
has a third value, and the first two keep theirs. In Blender, *Format* writes the names of a text
whose values go by position, as `base-node fmt --names` does.

```bn
geometry graph "lift by noise"(mesh: Geometry, height: Float = 0.3, scale: Float = 4.0) -> Geometry {
  n = NoiseTexture(vector: Position(), scale: scale).factor
  h = Math[MULTIPLY_ADD](Value: n, Value_001: height, Value_002: -height * 0.5)
  return mesh |> SetPosition(offset: CombineXYZ(z: h))
}
```

## Read an attribute that may be missing

A named attribute does not exist on every geometry. `NamedAttribute` says whether it found it: switch to
a value of your own when it did not, rather than reading zero.

```bn
geometry graph "weight or"(name: String = "weight", fallback: Float = 1.0) -> Float {
  a = NamedAttribute(name: name)
  return a.exists ? a.attribute : fallback
}
```

## Offer a choice with a menu

A `Menu` input and a `MenuSwitch` give the user named choices instead of an integer to remember. One menu
often chooses where the geometry comes from: the modifier's own, or an object's.

```bn
geometry graph source(mode: Menu = Input, geometry: Geometry, object: Object) -> Geometry {
  return MenuSwitch(menu: mode, Input: geometry, Object: ObjectInfo(object: object).geometry).output
}
```

## Keep a value across a change of the geometry

A field is read on the geometry of the node that uses it. To use a value of the geometry as it was before
a change (here, the height of each point before the mesh is subdivided), capture it first; this is also
shorter than storing a named attribute and reading it back.

```bn
geometry graph "lift by height"(mesh: Geometry, amount: Float = 0.2) -> Geometry {
  c = CaptureAttribute(mesh, height: Position().z)
  return SubdivideMesh(c.geometry, level: 2)
    |> SetPosition(offset: CombineXYZ(z: c.height * amount))
}
```

## Change one part, keep the rest

`SeparateGeometry` gives both the part it selects and the rest. Change the first, then join them again.

```bn
geometry graph "raise tops"(mesh: Geometry, height: Float = 0.5) -> Geometry {
  parts = SeparateGeometry[FACE](mesh, selection: Normal().z > 0.9)
  raised = SetPosition(parts.selection, offset: CombineXYZ(z: height))
  return JoinGeometry(raised, parts.inverted)
}
```

## One seed, several random values

Two `RandomValue` nodes with the same seed give the same numbers. Add a different constant to the user's
seed for each, so that one seed still changes them all.

```bn
geometry graph jitter(geometry: Geometry, amount: Float = 0.1, seed: Int) -> Geometry {
  x = RandomValue(min: -1.0, max: 1.0, seed: seed)
  y = RandomValue(min: -1.0, max: 1.0, seed: seed + 1)
  return SetPosition(geometry, offset: CombineXYZ(x: x, y: y) * amount)
}
```

## A lighter preview in the viewport

`IsViewport` is true while Blender draws the viewport and false when it renders: use it to keep the
viewport fast and the render detailed.

```bn
geometry graph scatter(mesh: Geometry, preview: Float = 10.0, render: Float = 200.0) -> Geometry {
  density = IsViewport() ? preview : render
  return DistributePointsOnFaces(mesh, density: density).points
}
```

## Say what is wrong

A `Warning` node shows its message on the modifier when its condition is true, and passes the condition
on: the graph can tell the user and fall back in the same step.

```bn
geometry graph "faces only"(mesh: Geometry) -> Geometry {
  empty = DomainSize(mesh).face_count == 0
  warned = Warning(show: empty, message: "The input has no faces")
  return warned ? Cube() : mesh
}
```

## Repeat a step on its own result

In a `repeat` zone each turn reads its fields on the geometry the turn before made: here the normals are
those of the inflated mesh, not of the first one.

```bn
geometry graph inflate(mesh: Geometry, distance: Float = 0.5, steps: Int = 10 in 1..) -> Geometry {
  r = repeat(steps, g: mesh) -> {
    return (g: SetPosition(g, offset: Normal() * (distance / steps)))
  }
  return r.g
}
```

## A factor goes from 0 to 1

An input that weighs or mixes is a factor: say so, and give its range. The modifier then shows a slider
that stops at the ends.

```bn
geometry graph blend(a: Float, b: Float, amount: Float(subtype: FACTOR) = 0.5 in 0.0..1.0) -> Float {
  return Mix(factor: amount, a: a, b: b)
}
```

## Share constants and helpers through a module

A value used by many graphs (a scale, a unit) is a graph without input; graphs shared by a library go in a
module. `use` brings them by name, and the module's name keeps them apart from the user's own graphs,
which prefixes in group names (`.MN_`, `O `) only imitate.

```bn
use math (bias)

geometry graph "world scale"() -> Float {
  return 0.01
}

geometry graph shaped(x: Float) -> Float {
  return bias(x * world_scale(), 0.3)
}
```
