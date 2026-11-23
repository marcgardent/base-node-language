# `<bn-view>`

A Web Component that shows a `.bn` text read-only: its highlighted code beside its node graph, drawn
like Blender's (and Blade's) Node Editor, with a **copy** button, an **enlarge** button (Esc reduces),
a **download** button to import it into Blender, and a tag per backend that runs the text. Its head shows the graph in large type, with the targets it runs on on a line below, a tab per
graph when the text has several, and a band under it holds the view (Code, Both, Nodes) and the buttons; what
overflows a line scrolls sideways, with the wheel too, as a Blender header.

All the work is Rust compiled to wasm (this crate, over [`base-node`](../../../rust), the core of the language, and [`base-node-blender`](../rust), its targets and stdlib): it parses the text,
builds a graph per `graph` (a node per call or operator, a link per argument, its settings in brackets
shown as its menus and fields, `Math[MULTIPLY, use_clamp: true](Value: a, Value_001: b)` as Multiply and Clamp, a frame per frame, a
zone's input and output nodes, the text's comments in boxes on the nodes and frames they go with, as the
Base Node add-on shows them in Blender), lays it out in columns, with nothing over a frame and its title but what
it holds, and draws it as SVG. The page only pans and zooms it, once the graph is clicked: until then the wheel and a finger scroll the page (Ctrl + wheel zooms; Esc or a click elsewhere lets the graph go). The code pane too scrolls only once clicked (or enlarged).

```html
<script type="module" src="view/bn-view.js"></script>

<bn-view src="relief.bn"></bn-view>

<bn-view view="nodes" graph="1" height="480"><script type="text/bn">
  geometry graph g() -> Geometry { return MeshCube() }
</script></bn-view>
```

| Attribute | |
|---|---|
| `src` | A `.bn` file; else the text inside (a `<script type="text/bn">` keeps `<` safe), dedented |
| `view` | The view shown first: `code`, `both` (code and nodes; `split` too) or `nodes`; `both` by default when wide enough, else `nodes` |
| `graph` | The tab shown first, when the text has several graphs: a graph's name (`chrono hud` or `chrono_hud`) or its number from 1 (default: the last) |
| `height` | In px (default 440) |
| `theme` | `dark` or `light` (default: the page's color scheme) |

The `value` property sets the text from script.

## Download for Blender

The file button in the bar downloads the text as a `.bn` file, to open in Blender with *File > Import* or to drop
from the file manager. It is named after `src`, else its `// @module`, else its last graph.

A page cannot drag it onto Blender instead: Blender reads a dropped file only from disk (`file://` on Linux,
`CF_HDROP` on Windows, a file URL on macOS). Chrome's `DownloadURL` is a virtual file Blender does not read, and
Blender keeps only the `file://` URIs of a `text/uri-list`. A dragged link or text then reaches it as a string,
which no Python add-on can catch (see `ui/drop.py` and [`site/drop-test.html`](../site/drop-test.html)).

Its head (`// @offer`, `@example`, `@modifier`…) is read by `base_node_blender::header`, the Rust twin of the Python
package's `base_node_blender/header.py`: a dashed tag says what the Base Node add-on will offer when the file is imported (library,
groups, example, modifier), or why it refuses the head. It shows only for a text the add-on reads.

## `<bn-file>`: just the file

A card to click to download the file for Blender, without code or graph: the title of the `.bn` (its
`// @title`, else its file's name), its file name, author and license, and what it offers the add-on. Its head is
read by the wasm's `file()` (the head alone, no graph drawn). `src` or the text inside, as `<bn-view>`; `theme` too.

```html
<script type="module" src="view/bn-file.js"></script>

<bn-file src="drop_example.bn"></bn-file>
```

Both components share `site/view/bn-shared.js`: the wasm, the reading of the text, the downloaded file and the theme.

## Backend tags

What base-node can tell from the text, not a run in the host:

| Tag | Runs when |
|---|---|
| Blender · Geometry Nodes | Every graph is a `geometry`, `shader` or `compositor` graph; its `geometry` graphs fit `blender`, which checks them against the Geometry Nodes of Blender |
| Blender · Shader | Same; its `shader` graphs fit `blender`, against its shader nodes |
| Blender · Compositor | Same; its `compositor` graphs fit `blender`, against its compositor nodes |
| Blade · Pixel Nodes | One `pixel graph`, within `blade` with the graphs it calls; its `use`s are modules `blade` follows: its bridges (`blender_interop`) and the stdlib |
| target … | A target the text fits ([spec/targets.md](../spec/targets.md)); `← source` when through its translator |

A crossed-out tag says why in its tooltip.

A graph that calls a graph of a stdlib module the text `use`s brings that graph's nodes: `use merge (with_alpha)`
called from a `geometry` graph does not fit `blender`, since `with_alpha` uses `SetAlpha`, a compositor
node. The wasm holds the `stdlib/*.bn` texts (base-node-blender's, built into the crate: about 160 KB of its size) and parses a
module the first time a text uses it. A module outside the stdlib is not read: its calls are not followed.

## Build

Needs the `wasm32-unknown-unknown` target and `wasm-bindgen-cli` at the version `Cargo.toml` pins:

```bash
cargo install wasm-bindgen-cli --version 0.2.130 --locked
./web/build.sh          # → site/view/pkg
cargo test              # in web/
```

The Pages workflow builds it before deploying `site/`; `site/view/` has a demo.
