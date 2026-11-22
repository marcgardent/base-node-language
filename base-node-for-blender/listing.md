<!--
Description for the extensions.blender.org page (paste below the line into the submission form).
Not part of the extension package: excluded by blender_manifest.toml.
-->

Base Node writes and reads Geometry Nodes, Shader and Compositor node groups as text. A tree becomes a `.bn` file of small functions; the file becomes a tree again. Edit nodes as code, review them in diffs, share them as plain text.

## Nodes ⇄ Text in the same area

- **Alt+Z** in the Node Editor shows the edited tree as `.bn` text, in the same area. Press it again to write the text back into the tree and return to the nodes.
- While you type, the tree follows its text as soon as the text is valid; an invalid text changes nothing and lists its errors in the sidebar. **Alt+P** applies the text by hand, when *Apply while typing* is turned off.
- The tree stays the only data: the text is a temporary view, removed when you go back to the nodes. An unchanged text leaves the tree and its layout untouched; a text with errors stays open with its diagnostics until it builds.
- Comments live in the tree too: each `//` comment is kept on the node of the statement it goes with (the frame of a block, the Group Output for `return`), so the text shows them again the next time it opens. The Node Editor draws them above their nodes, zooming with them, and Arrange Nodes leaves them room; *Edit Comment* (right-click menu) writes one from the nodes, and *Comments* in the sidebar hides them.
- **Ctrl+Shift+C** copies the edited tree as `.bn` text, with the groups it calls: paste it in a forum post or a chat instead of a screenshot of nodes. **Ctrl+Shift+V** builds the `.bn` text of the clipboard in the current file and shows it; a text with an error changes nothing and says its line. *Copy Selected as .bn* copies only the selected nodes.
- **Ctrl+Shift+A** arranges the selected nodes, or the whole tree: links go left to right, in line with their sockets, and each frame keeps its nodes together. It works in every node editor.

## Writing `.bn`

- Suggestions for nodes, sockets and the graphs of used modules: **Ctrl+Space**, the developers' standard. In `.bn` texts only, it takes the place of Blender's *Maximize Area*: **Ctrl+Alt+Space** still shows the area full screen. Alt+Space or Shift+Space can be chosen instead in the preferences. After `//`, they offer the targets: `// @target blender gltf`. They can also open by themselves after `(`, `.` and `:`, if turned on in the preferences.
- Syntax highlighting, with a mode that tells the standard library from your own graphs; a text that promises targets (`// @target blender gltf`) has what it uses outside them pointed out, and the panel tells which targets it fits.
- The pipe `|>` is shown as one symbol, ▷, except on the lines you are editing (can be turned off in the preferences). The text keeps `|>`.
- Color Ramps and curves (RGB Curves, Float Curve, Vector Curves, Hue Correct) are in the text, stop by stop and point by point: `color_ramp: Ramp((0.0, (0.0, 0.0, 0.0, 1.0)), (1.0, (1.0, 0.5, 0.0, 1.0)))`.
- **Format** (**Ctrl+Shift+A**) rewrites a text in the canonical layout, keeping its comments.
- Errors are underlined as you type and listed in the sidebar, with a suggestion when one is close; a click selects the error.
- A Group node whose node group is missing from the file reads as `Group()` and is built again as an empty Group node.

## Modules and standard library

- `use math` reuses graphs from another `.bn` file, as node groups.
- The standard library is bundled, eleven modules: `math` (shaping curves, waves, vectors, noise), `sdf2d` (2D signed distance fields and their boolean operations), `curves2d` (2D curves: resampling, curvature, path operations), `patterns2d` (tilings, grids, radial arrays, motifs), `planar2d` (planar maps: splitting at intersections, faces, region boundaries), `fillet2d` (fillets, chamfers and bevels of 2D corners), and for the compositor `mask2d` (masks drawn by signed distance fields), `merge` (the Merge operations of compositing: over, under, in, out, atop, screen, multiply…), `grade` (colour tools: grade, color correct, saturation, hue shift, soft clip, Cineon log2lin…), `stmap` (image remapping by STMaps: UV ramp, tile, mirror, reformat) and `qc` (quality control: test patterns such as SMPTE colour bars, and the checks of an image: false colour, clip, NaN, zebra, difference as heat).
- A `use` looks in the texts of the .blend, next to the imported file, in a *Module Folder* you choose, then in the bundled standard library.

## Import

- **File > Import > Base Node (.bn)** builds the graphs of one or more `.bn` files.
- **Add as Modifier** puts a built tree on the active object.
- **Drop a `.bn` file** on the 3D Viewport, the Node Editor or the Text Editor, from a file manager or a web page that offers it as a file: a dialog shows its title, author and license, and the choices its head offers (`// @offer library, groups, example, modifier`): install it as a library in the *Module Folder*, so that `use <module>` finds it in every .blend; import its graphs; add an object carrying its example; or add its modifier to the object it fell on, else to the selected objects, else to a new mesh (`// @mesh grid`). A dropped link or text is not read: only a file.
- A shader graph is also a material of its name, its return linked to the Material Output; a compositor graph becomes the scene's compositor when the scene has none.
- A material's own tree shows as text too (`Alt+Z` on it): a `shader(material: true)` graph, written back into the material.

## Permissions

- **Files**: reads the `.bn` files you import or drop, and the modules they use, from disk. The only file written outside the .blend is a dropped file you choose to install as a library, copied into the *Module Folder* you set; nothing is sent over the network.

## Links

- Language reference, examples and the Python/Rust parsers: https://basenode.ludopant.com/
- Source and issues: https://github.com/marcgardent/base-node-language
