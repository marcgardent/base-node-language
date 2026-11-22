<!--
Listing of Base Node 1.0.0 on extensions.blender.org: one section per field of the site, ready to paste.
Not part of the extension package: excluded by blender_manifest.toml, as is listing/.

Fields read from the manifest at upload (not typed on the site): name, tagline, version, tags,
license, copyright, permissions, website, Blender version.
Fields typed on the site: description, support URL, featured image, icon, previews and their
captions, release notes.

Rules checked on 2026-11-22, in the site's source (projects.blender.org/infrastructure/extensions-website,
extensions/models.py, constants/base.py, files/validators.py) and its documentation:
- tagline and each permission reason: at most 64 characters, no ending . ! or ?
- featured image: JPEG, PNG or WebP, at least 1920 x 1080, 16:9
- icon: PNG, 256 x 256
- previews: JPEG, PNG, WebP or MP4 (no GIF), shown in a 16:9 frame, at least one, caption at most 255 characters
- description and release notes: Markdown
- uploads under 200 MB
-->

# Name

Base Node

# Tagline

Nodes as text (.bn): read and write node trees as functions

# Tags

Node, Geometry Nodes, Material, Compositing, Text Editor, Import-Export

# License

GPL-3.0-or-later

# Website

https://basenode.ludopant.com/

# Support

https://github.com/marcgardent/base-node-language/issues

# Blender version

5.2 LTS and later (tested on 5.2 LTS and 5.3)

# Permissions (from the manifest)

- Files: Import .bn files and the modules they use from disk
- Clipboard: Copy node trees as .bn text and paste .bn text as nodes

# Description

Base Node writes Geometry Nodes, Shader and Compositor node trees as text, and builds the text back into nodes. A tree becomes a `.bn` file of small functions. You can edit nodes as code, review them in diffs and share them as plain text.

## Nodes and text in the same area

- **Alt+Z** in the Node Editor shows the edited tree as `.bn` text in the same area. Press it again to write the text into the tree and go back to the nodes.
- While you type, the tree follows the text as soon as the text is valid. A text with errors changes nothing and lists its errors in the sidebar. **Alt+P** applies the text by hand when *Apply while typing* is off.
- The tree stays the only data. The text is a temporary view, removed when you go back to the nodes. An unchanged text leaves the tree and its layout as they were.
- Comments are kept in the tree: each `//` comment is stored on the node of its statement and comes back the next time the text opens. The Node Editor draws them above their nodes.
- **Ctrl+Shift+C** copies the edited tree as `.bn` text, with the groups it calls, to paste in a forum post or a chat. **Ctrl+Shift+V** builds the `.bn` text of the clipboard in the current file. *Copy Selected as .bn* copies only the selected nodes.
- **Ctrl+Shift+A** arranges the selected nodes, or the whole tree: links go left to right, in line with their sockets, and each frame keeps its nodes together. It works in every node editor.

## Writing `.bn`

- Suggestions for nodes, sockets and the graphs of used modules with **Ctrl+Space** (in `.bn` texts only; **Ctrl+Alt+Space** still maximizes the area). Alt+Space or Shift+Space can be chosen in the preferences.
- Syntax highlighting, errors underlined as you type and listed in the sidebar, with a suggestion when one is close.
- Target checks: a text that declares its targets (`// @target blender gltf`) has what they do not accept pointed out. Targets include the `gltf` variant (the shader nodes a glTF export keeps) and, as experimental variants, `eevee` and `cycles`.
- Color Ramps and curves (RGB Curves, Float Curve, Vector Curves, Hue Correct) are written in the text, stop by stop and point by point.
- **Format** rewrites a text in the canonical layout and keeps its comments.

## Modules and standard library

- `use math` reuses the graphs of another `.bn` file as node groups.
- Eleven modules are bundled: `math` (shaping curves, waves, vectors, noise), `sdf2d` (2D signed distance fields), `curves2d` (resampling, curvature, path operations), `patterns2d` (tilings, grids, radial arrays), `planar2d` (planar maps: intersections, faces, region boundaries), `fillet2d` (fillets, chamfers and bevels of 2D corners), and for the compositor `mask2d` (masks from signed distance fields), `merge` (over, under, in, out, atop, screen, multiply), `grade` (grade, color correct, saturation, hue shift, soft clip, log to lin), `stmap` (STMap remapping) and `qc` (test patterns and image checks: false color, clipping, NaN, zebra, difference).
- A `use` looks in the texts of the .blend, next to the imported file, in a *Module Folder* you choose, then in the bundled library.

## Import

- **File > Import > Base Node (.bn)** builds the graphs of one or more `.bn` files.
- **Drop a `.bn` file** on the 3D Viewport, the Node Editor or the Text Editor. A dialog shows its title, author and license and the choices it offers: install it as a library in the *Module Folder*, import its graphs, add an object with its example, or add its modifier to an object. Only files are read: a dropped link or text is ignored.
- A shader graph also becomes a material of its name. A compositor graph becomes the scene's compositor when the scene has none. A material's own tree opens as text too (Alt+Z).

## Files, clipboard and network

- Files: the add-on reads the `.bn` files you import or drop and the modules they use. The only file it writes outside the .blend is a dropped file you choose to install as a library, copied into the *Module Folder* you set.
- Clipboard: written only by Copy as .bn, read only by Paste .bn.
- Network: none.

## Links

- Language reference, tutorials and examples: https://basenode.ludopant.com/
- Source and issues: https://github.com/marcgardent/base-node-language

# Release notes (1.0.0)

First release on Blender Extensions.

- Geometry Nodes, Shader and Compositor trees to `.bn` text and back, in the same area (Alt+Z).
- Live apply while typing, errors in the sidebar, suggestions, formatting.
- Copy and paste trees as `.bn` text, node arrangement, comments kept in the tree.
- Import and drag and drop of `.bn` files, Module Folder for your own modules.
- Standard library of eleven modules: math, sdf2d, curves2d, patterns2d, planar2d, fillet2d, mask2d, merge, grade, stmap, qc.
- Blender 5.2 LTS and 5.3.

# Featured image

`listing/featured.png`, 1920 x 1080 PNG (source: `listing/cover.vectorcraft`, artboard 1).

# Icon

`listing/icon.png`, 256 x 256 PNG (source: `listing/cover.vectorcraft`, artboard "Icon").

# Previews (in this order, with their captions)

Built from `site/images` by `listing/build_previews.py` into `listing/previews/`: each picture padded to 16:9 at its own resolution, the videos kept as MP4.

1. `01-cover.png`: Alt+Z switches a node tree between nodes and its .bn text
2. `02-chrono-hud.mp4`: chrono_hud.bn, an animated HUD built from the bundled modules sdf2d, curves2d, patterns2d and math
3. `03-metaball-symphony.mp4`: metaball_symphony.bn, built from the bundled modules
4. `04-differential-growth.mp4`: differential_growth.bn, a simulation written as a .bn file
5. `05-reaction-diffusion.mp4`: reaction_diffusion.bn, a simulation written as a .bn file
6. `06-tuple-tiles-nodes.png`: tuple_tiles.bn built as Geometry Nodes, with its comments
7. `07-tuple-tiles.png`: The render of tuple_tiles.bn
8. `08-sdf2d.png`: sdf2d: 2D signed distance fields and their boolean operations
9. `09-curves2d.png`: curves2d: 2D curve operations
10. `10-patterns2d.png`: patterns2d: tilings, grids and radial arrays
11. `11-qc.png`: qc: test patterns and image checks in the compositor
12. `12-stmap.png`: stmap: image remapping by STMaps in the compositor
