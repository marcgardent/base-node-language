# Third-party libraries: non-regression

Each `<name>.toml` names a library of node groups made by someone else; `test_libraries.py` reads every
Geometry Nodes group of it (and, when its manifest says so, its shader groups, materials and compositor groups) as `.bn` text,
builds it back, reads it again and evaluates or renders it beside the original.
What happens to each group is kept in `<name>.baseline.json`; the test fails when it changes, for better or worse.

| Library | Version | Author | License | Groups |
|---|---|---|---|---|
| [Molecular Nodes](https://github.com/BradyAJohnston/MolecularNodes) | v520.2.0 | Brady Johnston and contributors | GPL-3.0-or-later | see `molecularnodes.baseline.json` |
| [Bioxel Nodes](https://github.com/OmooLab/BioxelNodes) | v2.0.4 | OmooLab | GPL-3.0-or-later | see `bioxelnodes.baseline.json` |
| [H-Style RBD Nodes](https://github.com/excifroge/H-Style-RBD-Nodes) | d9a22d0 (1.0.2) | Excifroge | GPL-3.0-or-later | see `hstylerbd.baseline.json`, `hstylerbd_bricks.baseline.json` |
| [OpenVAT](https://github.com/sharpen3d/openvat) | 43b5196 (1.1.2) | Luke Stilson | GPL-3.0-or-later | see `openvat.baseline.json` |
| [Unravel](https://github.com/paraminder-dhiman/unravel) | v1.0.0 | Paraminder Dhiman | GPL-3.0-or-later | see `unravel.baseline.json` |
| [T3D GN Presets](https://github.com/Tams3d/T3D-GN-Presets) | v1.6.0 | Tamil Selvan | GPL-3.0-or-later | see `t3d.baseline.json` |
| [i32 the Mandelbrot Set](https://extensions.blender.org/add-ons/i32-the-mandelbrot-set/) | 1.0.3 (generated) | Osipenkov, Art | GPL-3.0-or-later | see `mandelbrot.baseline.json` |
| [Material Library VX](https://github.com/blender/blender-addons/tree/main/materials_library_vx) | b42d686 | Mackraken, Blender Foundation | GPL-2.0-or-later | shader groups and materials, see `materiallibraryvx.baseline.json` |
| [Procedural Tiles](https://github.com/AisunTang/Procedural-Tiles) | a2f21a0 (0.0.4) | Aisun Tang | GPL-3.0-or-later | shader groups, see `proceduraltiles.baseline.json` |
| Shading Nodes Essentials (shipped with Blender) | Blender 5.3.0 | Blender Foundation | CC0-1.0 | shader groups, see `shadingessentials.baseline.json` |
| Compositing Nodes Essentials (shipped with Blender) | Blender 5.3.0 | Blender Foundation | CC0-1.0 | compositor groups, see `compositingessentials.baseline.json` |
| Geometry Nodes Essentials (shipped with Blender) | Blender 5.3.0 | Blender Foundation | CC0-1.0 | see `geometryessentials.baseline.json` |
| Procedural Hair Node Assets (shipped with Blender) | Blender 5.3.0 | Blender Foundation | CC0-1.0 | see `proceduralhair.baseline.json` |
| Geometry Nodes Dynamics Assets (shipped with Blender) | Blender 5.3.0 | Blender Foundation | CC0-1.0 | see `geometrydynamics.baseline.json` |
| Principal Components (shipped with Blender) | Blender 5.3.0 | Blender Foundation | CC0-1.0 | see `principalcomponents.baseline.json` |
| [Tessera – Mosaic & Tile Studio](https://extensions.blender.org/add-ons/tessera-mosaic/) | 1.0.0 (generated) | Tessera | GPL-3.0-or-later | see `tessera.baseline.json` |

The `.blend` files are not in this repository: each is fetched once at its fixed version, checked by its
`sha256` and kept in the cache (`$BASE_NODE_CACHE`, `~/.cache/base-node` by default). A library under a license
that lets it be copied here can also name a committed file with `file = "…"` instead of `url`.

## Manifest

```toml
name = "Molecular Nodes"
author = "Brady Johnston and contributors"
homepage = "https://github.com/BradyAJohnston/MolecularNodes"
license = "GPL-3.0-or-later"
version = "v520.2.0"
url = "https://github.com/…/molecularnodes-520.2.0-macos_arm64.zip"   # a .blend, or a .zip with…
member = "assets/nodes.blend"                                          # …the .blend inside it
sha256 = "905e…"                                                       # of the .blend
```

A group whose original does not give twice the same geometry in a kind of evaluation of the test (a sample on
overlapping UVs, say) names that kind in the manifest, which is then not compared for it:

```toml
[nondeterministic]
"UV Deform" = ["mesh caller fed"]   # kinds: "mesh", "curves", "mesh caller", "mesh caller fed"
```

A group that Blender itself evaluates otherwise once rebuilt, its text and every setting being the same,
names that kind under `[blender_quirks]`, with the reason in a comment. It is still compared: a difference
there is kept in the baseline as `blender_quirk` and the group stays `ok`; when Blender no longer differs,
the record changes and the test says so.

```toml
[blender_quirks]
"Film Grain" = ["composite"]   # the compositor depends on which Group Input node a link leaves
```

A file Blender ships is named by its path under Blender's `datafiles` (`bundled = "assets/nodes/…"`) instead of
`url`: nothing is fetched, and its `sha256` is that of the Blender the baseline was made with.

A `.blend` inside a `.zip` is read by HTTP ranges: only the zip's directory and that file are downloaded.

## Each promised version of Blender

The libraries run with each version of Blender Base Node promises (`make test-libraries BLENDER=…`,
`make test-promised`; a job per version in the CI). `<name>.baseline.json` is the record of the Blender
it names (`"blender"`), the latest. Another version is compared with that same record, and has a record
of its own only where it reads the library otherwise:

- `<name>.baseline-<x.y>.json` beside the baseline is what Blender x.y gives, and what it is compared
  with. `BASE_NODE_UPDATE_FIXTURES=1` run with that Blender writes it when it differs from the baseline
  and takes it away when it no longer does; it never writes the record of the other Blender.
- `[blender."<x.y>"]` in a manifest holds what differs for that version, over the rest of the manifest:
  the `sha256` and `version` of a file Blender ships, which is another file in each version.
- `blender_min = "5.3"` in a manifest names the oldest Blender that opens the library: an older one
  skips it and says so.

```toml
bundled = "assets/nodes/geometry_nodes_essentials.blend"
sha256 = "4271…"                 # Blender 5.3.0's file

[blender."5.2"]
version = "Blender 5.2.4"
sha256 = "4592…"                 # Blender 5.2.4's file: geometryessentials.baseline-5.2.json
```

With Blender 5.2.4 LTS, 13 of the 17 libraries read as their baseline does, two files Blender ships
unchanged among them (Principal Components, Shading Nodes Essentials). Three files Blender ships are
others in 5.2.4 and have their record: Compositing Nodes Essentials (24 groups, no Bloom), Geometry
Nodes Essentials (33) and Procedural Hair Node Assets (32), every group `ok`. Geometry Nodes Dynamics
Assets is the same file, but its Sample Surface Deformation does not evaluate twice the same in 5.2.4:
that kind is not compared there (`[blender."5.2".nondeterministic]`), which its record says.
No library needs `blender_min` today. The badges count the baselines of the latest.

## Shader groups and materials

A manifest reads only Geometry Nodes groups unless it names the trees it wants:

```toml
trees = ["shader", "material"]   # also "geometry", the default
```

`shader` reads its shader node groups, `material` its materials' own trees (written
`shader(material: true) graph …`), kept in the baseline as `material:<name>` beside the groups. Each is
compared by rendering it beside its original, there being no evaluator of shaders:

- **Engine**: Cycles on the CPU. EEVEE needs a GPU context that `--background` on a CI runner may not
  have; Cycles gives the same pixels for the same shader at a fixed seed whatever the number of threads.
- **Scene**: a smooth UV sphere (it has UVs and generated coordinates) lit by a sun and a grey world, seen
  by an orthographic camera, 32 × 32 pixels, 16 samples, seed 0, no denoising nor adaptive sampling,
  written as a 32-bit float EXR in the Standard view. Two renders differ when a pixel differs by more
  than 1e-4.
- **Materials**: rendered as they are, through their active Material Output (`render`).
- **Groups**: wrapped in a throwaway material, rendered once per output: a `Shader` output feeds the
  Surface, any other the color of an Emission. In `render` the group's inputs keep their defaults; in
  `render fed` its `Vector` inputs take the object's coordinates, so that a texture draws its pattern
  rather than its value at the origin. `on` names the kinds and outputs that differ (`render fed Color`).

A material or group that does not render twice the same names those kinds under `[nondeterministic]`
(`"material:Smoke" = ["render"]`).

## Compositor groups

`trees = ["compositor"]` reads a file's compositor node groups. Each is applied, in the stage scene's own
compositor, to the render of the sphere in a plain grey material, once per output: its `Color` inputs take
the render, the others keep their defaults (`composite`). Two outputs of one name are told apart by their
place (`composite Lvl 1 #2`).

## Badges

The README's badges (`site/badges/regression-<kind>.svg`) count the trees of each kind that are `ok` in the
baselines: Geometry Nodes groups, shader groups and materials, compositor groups. Writing the baselines
writes them too; otherwise, and in the CI's check (no Blender needed):

```bash
python3 addon/tests/regression_badges.py            # write them
python3 addon/tests/regression_badges.py --check    # fail when one is not as the baselines say
```

## Groups built by an add-on's Python

Some add-ons ship no `.blend`: their Python builds the node groups. Their manifest pins the extension's `.zip`
(`url` and `sha256` of the zip) and names, in a `[generate]` table, the one call that builds them:

```toml
url = "https://extensions.blender.org/download/sha256:db3a…/add-on-i32-the-mandelbrot-set-v1.0.3.zip"
sha256 = "db3a…"                                                   # of the .zip

[generate]
operator = "i32_the_mandelbrot_set.i32_the_mandelbrot_set_1"       # run with an empty mesh object active
# or: function = "nodes.ensure_engine"                             # a function of the extension's package
```

`test_libraries.py` then starts another Blender, `--background --factory-startup`, with a throwaway user
profile (`BLENDER_USER_RESOURCES` and every `BLENDER_USER_*` pointing to a temporary directory, deleted after):
`generate_library.py` installs the extension in that profile's `user_default` repository (and refuses to if
it would land anywhere else), makes the call, and writes every node group then in the file to
`libraries/generated/` in the cache, keyed by the zip, the call and the Blender version. The round trip then
reads that `.blend` like any other. The extension never runs in the test's own Blender nor in your profile.

Run an add-on's code only after reading all of it (see `.claude/skills/add-tnr`): the manifest's comment says
what it does.

## Baseline

For each group or material: `status` (`ok`, `export_error`, `build_error`, `unstable`: the rebuilt group does not read back
as the same text, `evaluates_otherwise`: it evaluates (or renders) otherwise than the original, `on` saying where), the first
`error` line, the kinds of `warnings` and a hash of its `text`.

```bash
blender --background --factory-startup --python-exit-code 1 \
  --python addon/tests/test_libraries.py -- molecularnodes
```

When a change is wanted (a fix, a reader that writes otherwise), write the baselines again and review their diff:

```bash
BASE_NODE_UPDATE_FIXTURES=1 blender --background --factory-startup --python-exit-code 1 \
  --python addon/tests/test_libraries.py
```

The texts of the last run are in the cache under `texts/<name>`, those of the run before under
`texts/<name>.previous`; `diff -r` them to read what a change of the reader changed.

The texts themselves are kept in the repository, in [`corpus/v1/<name>/`](../../../corpus/), one
`<group>.bn` per group (the key of its name in code, `material_<name>` for a material) with a
`README.md` made from the manifest and the library's `LICENSE`. The run that writes the baselines
writes them, with the Blender of `<name>.baseline.json` only (`library_corpus.py`);
`python/tests/test_corpus.py` checks them against the baselines without Blender.

Thanks to the authors of these libraries for publishing them.
