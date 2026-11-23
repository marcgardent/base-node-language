// <bn-view>: a .bn text, read-only — its code and its node graph, drawn
// by base-node compiled to wasm (web/), with the backends it runs on.
//
//   <script type="module" src="view/bn-view.js"></script>
//   <bn-view src="examples/chrono_hud.bn"></bn-view>
//   <bn-view view="both" graph="2" height="480"><script type="text/bn">
//     geometry graph g() -> Geometry { return MeshCube() }
//   </script></bn-view>
//
// Attributes: src (a .bn file) or the text inside (a <script type="text/bn">
// keeps `<` safe); view = code | both | nodes, the view shown first (default:
// both when wide, else nodes; split is both);
// graph = the tab shown first, a graph's name or its number from 1 (default:
// the last); height (px, default 440);
// theme = dark | light (default: the page's color scheme).

import { DownloadedFile, FILE_ICON, THEME, escape, offer, readSource, wasm } from "./bn-shared.js";

const STYLE = `${THEME}
:host {
  display: block; position: relative; height: var(--bn-height, 440px);
  color: var(--bn-text); background: var(--bn-bg);
  border: 1px solid var(--bn-border); border-radius: 8px; overflow: hidden;
  font: 13px/1.45 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
  margin: 1rem 0;
}
:host([expanded]) {
  position: fixed; inset: 0; z-index: 2147483000; height: auto; margin: 0; border-radius: 0; border: 0;
}
* { box-sizing: border-box; }
.root { display: flex; flex-direction: column; height: 100%; container-type: inline-size; }
.bar { display: flex; align-items: center; gap: .4rem .75rem; padding: .45rem .6rem; }
/* One line each: what overflows scrolls sideways (the wheel too), as a Blender header. */
.strip { overflow-x: auto; overflow-y: hidden; scrollbar-width: none; overscroll-behavior-x: contain; }
.strip::-webkit-scrollbar { display: none; }
.head {
  display: block; padding: .5rem .7rem .45rem; border-bottom: 1px solid var(--bn-border); white-space: nowrap;
}
.foot { border-top: 1px solid var(--bn-border); padding: .3rem .6rem; }
.title {
  font-weight: 600; font-size: 17px; line-height: 1.3; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.title .kind { color: var(--bn-muted); font-weight: 400; font-size: 13px; margin-right: .35em; }
/* Under the title, the targets it runs on, on one line. */
.tags { display: flex; flex-wrap: nowrap; gap: .3rem; margin-top: .3rem; }
.tags:empty { display: none; }
.tabs {
  display: flex; align-items: flex-end; gap: 2px; padding: .3rem .5rem 0;
  background: color-mix(in srgb, var(--bn-text) 4%, var(--bn-bg)); border-bottom: 1px solid var(--bn-border);
}
.tabs[hidden] { display: none; }
.tab {
  flex: none; height: 26px; border: 1px solid transparent; border-bottom: 0; border-radius: 6px 6px 0 0;
  padding: 0 .75rem; color: var(--bn-muted); white-space: nowrap; margin-bottom: -1px;
}
.tab .kind { opacity: .7; margin-right: .3em; font-size: 11px; }
.tab:hover { color: var(--bn-text); border-color: transparent; background: color-mix(in srgb, var(--bn-text) 6%, transparent); }
.tab[aria-selected="true"] { color: var(--bn-text); background: var(--bn-bg); border-color: var(--bn-border); }
.tag {
  display: inline-flex; align-items: center; gap: .3em; padding: .05rem .5rem; border-radius: 999px;
  font-size: 11.5px; border: 1px solid var(--bn-border); color: var(--bn-muted); white-space: nowrap; cursor: default;
}
.tag.ok { color: var(--bn-ok); border-color: color-mix(in srgb, var(--bn-ok) 45%, transparent); background: var(--bn-ok-bg); }
.tag.no { opacity: .55; text-decoration: line-through; text-decoration-color: color-mix(in srgb, var(--bn-muted) 60%, transparent); }
.tag.target { color: var(--bn-accent); border-color: color-mix(in srgb, var(--bn-accent) 40%, transparent); }
.tag b { font-weight: 600; }
.tools { display: flex; align-items: center; gap: .35rem; margin-left: auto; }
.foot .seg { flex: none; }
button {
  font: inherit; font-size: 12px; color: var(--bn-text); background: transparent;
  border: 1px solid var(--bn-border); border-radius: 6px; padding: .2rem .55rem; cursor: pointer; height: 26px;
}
button:hover { border-color: var(--bn-accent); }
button:focus-visible { outline: 2px solid var(--bn-accent); outline-offset: 1px; }
.seg { display: inline-flex; }
.seg button { border-radius: 0; margin-left: -1px; }
.seg button:first-child { border-radius: 6px 0 0 6px; margin-left: 0; }
.seg button:last-child { border-radius: 0 6px 6px 0; }
.seg button[aria-pressed="true"] { background: var(--bn-accent); border-color: var(--bn-accent); color: #fff; }
.icon { width: 30px; padding: 0; display: inline-grid; place-items: center; }
.icon svg { width: 15px; height: 15px; fill: none; stroke: currentColor; stroke-width: 1.8; stroke-linecap: round; stroke-linejoin: round; }
.copy.done { color: var(--bn-ok); border-color: var(--bn-ok); }
a.icon { color: var(--bn-text); border: 1px solid var(--bn-border); border-radius: 6px; height: 26px; text-decoration: none; }
a.icon:hover { border-color: var(--bn-accent); }
.download[hidden] { display: none; }
.tag.offer { color: var(--bn-accent); border-style: dashed; }
.tag.offer.refused { color: #f85149; border-color: color-mix(in srgb, #f85149 45%, transparent); }
.desc { padding: .3rem .7rem; color: var(--bn-muted); font-size: 12.5px; border-bottom: 1px solid var(--bn-border); }
.desc:empty { display: none; }
.panes { flex: 1; display: flex; min-height: 0; }
.code, .graph { min-width: 0; min-height: 0; }
.code {
  margin: 0; overflow: hidden; padding: .6rem 0; flex: 0 0 44%;
  font: 12.5px/1.55 ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", monospace;
  counter-reset: line; tab-size: 2; border-right: 1px solid var(--bn-border);
}
.code .line { display: block; padding: 0 .9rem 0 3.4rem; position: relative; white-space: pre; }
.code .line::before {
  counter-increment: line; content: counter(line); position: absolute; left: 0; width: 2.6rem;
  text-align: right; color: var(--bn-cmt); opacity: .7; user-select: none;
}
.code .line.mark { background: var(--bn-mark); }
.code .line.err { background: rgba(248,81,73,.16); }
/* Focused (clicked), the code takes the wheel and the touch: else the page scrolls. */
.code { outline: none; }
.code.active, :host([expanded]) .code { overflow: auto; }
.code.active { box-shadow: inset 0 0 0 2px color-mix(in srgb, var(--bn-accent) 70%, transparent); }
.code .hint {
  display: none; position: sticky; bottom: .4rem; width: max-content; margin: -1.4em .5rem 0 auto;
  font: 11px/1.4 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
  color: var(--bn-text); background: color-mix(in srgb, var(--bn-bg) 85%, transparent);
  border: 1px solid var(--bn-border); padding: .1rem .4rem; border-radius: 4px; white-space: nowrap;
}
.code .hint.ask { display: block; }
.k { color: var(--bn-kw); } .t { color: var(--bn-ty); } .f { color: var(--bn-fn); }
.s { color: var(--bn-str); } .n { color: var(--bn-num); } .c { color: var(--bn-cmt); font-style: italic; }
.p { color: var(--bn-muted); }
.graph {
  flex: 1; position: relative; overflow: hidden; cursor: grab; touch-action: pan-x pan-y; outline: none;
  background-color: var(--ne-bg);
  background-image: linear-gradient(var(--ne-grid) 1px, transparent 1px), linear-gradient(90deg, var(--ne-grid) 1px, transparent 1px);
  background-size: 24px 24px;
}
.graph.dragging { cursor: grabbing; }
/* Focused (clicked), the graph takes the wheel and the touch: else the page scrolls. */
.graph.active, :host([expanded]) .graph { touch-action: none; }
.graph.active { box-shadow: inset 0 0 0 2px color-mix(in srgb, var(--bn-accent) 70%, transparent); }
.hint.ask { opacity: .95; background: color-mix(in srgb, var(--ne-bg) 80%, transparent); padding: .1rem .4rem; border-radius: 4px; }
.graph > svg { width: 100%; height: 100%; display: block; user-select: none; }
.hint { position: absolute; right: .5rem; bottom: .4rem; font-size: 11px; color: var(--ne-text); opacity: .55; pointer-events: none; }
.error { padding: .8rem 1rem; color: #f85149; font-size: 12.5px; }
.root[data-view="code"] .graph { display: none; }
.root[data-view="code"] .code { flex: 1; border-right: 0; }
.root[data-view="nodes"] .code { display: none; }
@container (max-width: 680px) {
  .root[data-view="split"] .panes { flex-direction: column; }
  .root[data-view="split"] .code { flex: 0 0 45%; border-right: 0; border-bottom: 1px solid var(--bn-border); }
}
/* The node editor, drawn by base-node (web/src/svg.rs). */
.frame rect { fill: var(--ne-frame); }
/* The comments of the text, as the Base Node add-on shows them in Blender. */
.note-box { fill: var(--ne-note); fill-opacity: .94; stroke: var(--ne-note-bar); stroke-opacity: .35; }
.note-bar { fill: var(--ne-note-bar); }
.note-text { fill: var(--ne-note-text); font: 11px -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; white-space: pre; }
.frame.zone rect { fill: var(--ne-zone); stroke: var(--ne-zone-h); stroke-width: 1.5; stroke-dasharray: 5 4; }
.frame-label { fill: var(--ne-text); opacity: .8; font-size: 13px; font-weight: 600; }
.link { fill: none; stroke-width: 2; opacity: .85; }
.node-body { fill: var(--ne-node); stroke: var(--ne-outline); stroke-width: 1; }
.node:hover .node-body, .node.mark .node-body { stroke: #ffffff; stroke-width: 1.6; }
.node-header { fill: var(--ne-converter); }
.cat-input .node-header { fill: var(--ne-input); }
.cat-output .node-header { fill: var(--ne-output); }
.cat-vector .node-header { fill: var(--ne-vector); }
.cat-texture .node-header { fill: var(--ne-texture); }
.cat-geometry .node-header { fill: var(--ne-geometry); }
.cat-shader .node-header { fill: var(--ne-shader); }
.cat-group .node-header { fill: var(--ne-group); }
.cat-zone .node-header { fill: var(--ne-zone-h); }
.node-title { fill: #fff; font-size: 12px; font-weight: 600; }
.socket-label, .field-value { fill: var(--ne-text); font-size: 11px; }
.socket-label.out, .field-value { text-anchor: end; }
.field { fill: var(--ne-field); }
.menu { fill: var(--ne-menu); stroke: var(--ne-outline); stroke-width: .5; }
.menu-label { fill: var(--ne-text); font-size: 11px; }
.menu-arrow { fill: none; stroke: var(--ne-text); stroke-width: 1.2; opacity: .8; }
.socket { stroke: #000; stroke-width: 1; fill: #7a7a7a; }
.graph text { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; }
.node { cursor: pointer; }
${Object.entries({
  float: "#a1a1a1", int: "#598c5c", bool: "#cca6d6", vector: "#6363c7", color: "#c7c729",
  rotation: "#a663c7", matrix: "#6a4a8c", string: "#70b2ff", geometry: "#00d6a3", material: "#eb7582",
  object: "#ed9e5c", collection: "#f5f5f5", image: "#633863", texture: "#9e4fa3", menu: "#4d4d4d",
  shader: "#63c763", closure: "#8a8a8a", bundle: "#8a8a8a", any: "#7a7a7a",
}).map(([t, c]) => `.socket.ty-${t} { fill: ${c}; } .link.ty-${t} { stroke: ${c}; }`).join("\n")}
.link.ty-any { stroke: #9a9a9a; }
`;

const ICONS = {
  copy: '<svg viewBox="0 0 24 24"><rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15V5a2 2 0 0 1 2-2h8"/></svg>',
  done: '<svg viewBox="0 0 24 24"><path d="M5 12.5l4.5 4.5L19 7.5"/></svg>',
  expand: '<svg viewBox="0 0 24 24"><path d="M14 4h6v6M10 20H4v-6M20 4l-7 7M4 20l7-7"/></svg>',
  shrink: '<svg viewBox="0 0 24 24"><path d="M20 10h-6V4M4 14h6v6M14 10l7-7M10 14l-7 7"/></svg>',
  file: FILE_ICON,
  fit: '<svg viewBox="0 0 24 24"><path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5"/></svg>',
};

class BnView extends HTMLElement {
  static observedAttributes = ["src", "view", "height", "graph"];

  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this.source = "";
    this.data = null;
    this.box = null;
    this.outside = [];
    this.onKey = (e) => {
      if (e.key === "Escape" && this.hasAttribute("expanded")) this.toggleExpanded(false);
    };
  }

  connectedCallback() {
    if (!this.shadowRoot.firstChild) this.build();
    for (const f of this.outside) document.addEventListener("pointerdown", f, true);
    this.applyHeight();
    this.load();
  }

  disconnectedCallback() {
    for (const f of this.outside) document.removeEventListener("pointerdown", f, true);
    this.toggleExpanded(false);
  }

  attributeChangedCallback(name, old, value) {
    if (!this.isConnected || old === value || !this.shadowRoot.firstChild) return;
    if (name === "src") this.load();
    if (name === "height") this.applyHeight();
    if (name === "view") this.setView(value);
    if (name === "graph" && this.data) this.showGraph(this.graphOf(value));
  }

  /** The text shown, set from script. */
  set value(text) {
    this.loads = (this.loads ?? 0) + 1; // a load still reading src or the text inside gives way
    this.source = text;
    this.show();
  }

  get value() {
    return this.source;
  }

  applyHeight() {
    const h = this.getAttribute("height");
    if (h) this.style.setProperty("--bn-height", /^\d+$/.test(h) ? `${h}px` : h);
  }

  build() {
    const root = this.shadowRoot;
    root.innerHTML = `<style>${STYLE}</style>
      <div class="root" part="root">
        <div class="head" part="head">
          <div class="title" part="title"></div>
          <div class="tags strip" part="tags" aria-label="Where it runs"></div>
        </div>
        <div class="tabs strip" part="tabs" role="tablist" aria-label="Graphs" hidden></div>
        <div class="desc" part="description"></div>
        <div class="panes">
          <pre class="code" part="code" tabindex="0" aria-label="Code: click to scroll it with the wheel"></pre>
          <div class="graph" part="graph" tabindex="0" aria-label="Node graph: click to zoom with the wheel"></div>
        </div>
        <div class="bar foot strip" part="tools">
          <div class="seg" role="group" aria-label="View">
            <button data-v="code" aria-pressed="false">Code</button>
            <button data-v="split" aria-pressed="false">Both</button>
            <button data-v="nodes" aria-pressed="false">Nodes</button>
          </div>
          <div class="tools">
            <a class="icon download" draggable="false" hidden aria-label="Download the .bn file">${ICONS.file}</a>
            <button class="icon copy" title="Copy the code" aria-label="Copy the code">${ICONS.copy}</button>
            <button class="icon expand" title="Enlarge" aria-label="Enlarge">${ICONS.expand}</button>
          </div>
        </div>
      </div>`;
    const $ = (s) => root.querySelector(s);
    this.$ = { root: $(".root"), title: $(".title"), tags: $(".tags"), tabs: $(".tabs"), desc: $(".desc"),
      code: $(".code"), graph: $(".graph"), copy: $(".copy"), expand: $(".expand"),
      download: $(".download") };
    root.querySelectorAll(".seg button").forEach((b) =>
      b.addEventListener("click", () => this.setView(b.dataset.v)));
    this.$.copy.addEventListener("click", () => this.copy());
    this.$.expand.addEventListener("click", () => this.toggleExpanded());
    this.$.tabs.addEventListener("click", (e) => {
      const tab = e.target.closest(".tab");
      if (tab) this.showGraph(tab.dataset.name);
    });
    this.$.tabs.addEventListener("keydown", (e) => {
      const tabs = [...this.$.tabs.children];
      const at = tabs.indexOf(e.target.closest(".tab"));
      const to = { ArrowRight: at + 1, ArrowLeft: at - 1, Home: 0, End: tabs.length - 1 }[e.key];
      if (at < 0 || to === undefined || !tabs[to]) return;
      e.preventDefault();
      this.showGraph(tabs[to].dataset.name);
      tabs[to].focus();
    });
    root.querySelectorAll(".strip").forEach((el) => this.sideways(el));
    this.panZoom();
    this.scrolls();
    this.setView(this.getAttribute("view") || (this.clientWidth && this.clientWidth < 680 ? "nodes" : "split"));
  }

  async load() {
    const at = (this.loads = (this.loads ?? 0) + 1);
    let source;
    try {
      source = await readSource(this);
    } catch (e) {
      if (at === this.loads) this.$.graph.innerHTML = `<div class="error">${escape(e.message)}</div>`;
      return;
    }
    if (at !== this.loads) return; // a later load, or a value set meanwhile, wins
    this.source = source;
    this.show();
  }

  async show() {
    const { render } = await wasm();
    this.data = JSON.parse(render(this.source));
    const { code, error, graphs, backends, targets, drop } = this.data;
    this.$.code.innerHTML = code + `<span class="hint">click the code to scroll it with the wheel</span>`;
    this.$.tags.replaceChildren(...this.tags(backends, targets), ...this.offerTag(drop));
    this.setFile(drop);
    if (error) {
      this.$.code.querySelector(`.line[data-line="${error.line}"]`)?.classList.add("err");
      this.$.graph.innerHTML = `<div class="error">Line ${error.line}, column ${error.col}: ${escape(error.message)}</div>`;
      this.$.title.textContent = "";
      this.$.desc.textContent = "";
      return;
    }
    const tabs = this.$.tabs;
    tabs.replaceChildren(...graphs.map((g) => {
      const tab = document.createElement("button");
      tab.className = "tab";
      tab.setAttribute("role", "tab");
      tab.dataset.name = g.name;
      tab.title = `${g.kind} graph ${g.name}`;
      tab.innerHTML = `<span class="kind">${escape(g.kind)}</span>${escape(g.name)}`;
      return tab;
    }));
    tabs.hidden = graphs.length < 2;
    this.showGraph(this.graphOf(this.getAttribute("graph")) ?? graphs[graphs.length - 1]?.name);
  }

  /** The text as a .bn file to download, for File > Import in Blender. */
  setFile(drop) {
    const link = this.$.download;
    this.file?.dispose();
    this.file = drop ? new DownloadedFile(this.source, this.getAttribute("src"), drop) : null;
    link.hidden = !drop;
    if (!drop) return;
    link.href = this.file.href;
    link.download = this.file.name;
    link.title = `Download ${this.file.name}, then File > Import it in Blender`;
  }

  /** What the file offers the Blender add-on that imports it, or why its head is refused. */
  offerTag(drop) {
    const o = offer(drop);
    if (!o) return [];
    const el = document.createElement("span");
    el.className = o.refused ? "tag offer refused" : "tag offer";
    el.textContent = o.refused ? o.text : `⇣ Blender: ${o.text}`;
    el.title = o.title;
    return [el];
  }

  /** A chip per backend (those it runs on first), then one per target the text fits. */
  tags(backends, targets) {
    const chips = [...backends].sort((a, b) => b.ok - a.ok).map((b) => {
      const el = document.createElement("span");
      el.className = `tag ${b.ok ? "ok" : "no"}`;
      el.title = b.ok ? `Runs on ${b.host} ${b.label}` : `Not on ${b.host} ${b.label}: ${b.why}`;
      el.innerHTML = `${b.ok ? "✓" : "✕"} <b>${b.host}</b> ${b.label}`;
      return el;
    });
    for (const t of targets || []) {
      const el = document.createElement("span");
      el.className = "tag target";
      el.title = t.from ? `Fits ${t.name} once translated from ${t.from}` : `Fits the target ${t.name}`;
      el.textContent = t.from ? `${t.name} ← ${t.from}` : t.name;
      chips.push(el);
    }
    return chips;
  }

  /** The graph `wanted` names: by its name (or its key, `chrono_hud`), else by its tab's number from 1. */
  graphOf(wanted) {
    const graphs = this.data?.graphs ?? [];
    if (wanted == null || wanted === "") return null;
    const key = (s) => String(s).trim().toLowerCase().replace(/[\s-]+/g, "_");
    const g = graphs.find((x) => x.name === wanted) ?? graphs.find((x) => key(x.name) === key(wanted)) ??
      (/^\d+$/.test(wanted.trim()) ? graphs[+wanted - 1] : undefined);
    return g?.name ?? null;
  }

  /**
   * A one-line strip scrolls sideways with the wheel while it overflows, as
   * a Blender header; at its end, the wheel goes back to the page.
   */
  sideways(el) {
    el.addEventListener("wheel", (e) => {
      const d = Math.abs(e.deltaX) > Math.abs(e.deltaY) ? e.deltaX : e.deltaY;
      const room = el.scrollWidth - el.clientWidth;
      if (e.ctrlKey || room <= 1 || (d < 0 && el.scrollLeft <= 0) || (d > 0 && el.scrollLeft >= room - 1)) return;
      e.preventDefault();
      el.scrollLeft += e.deltaMode === 1 ? d * 16 : d;
    }, { passive: false });
  }

  /** `item` scrolled into view in its strip, without scrolling the page. */
  reach(strip, item) {
    const a = item.offsetLeft - strip.offsetLeft;
    if (a < strip.scrollLeft) strip.scrollLeft = a - 8;
    else if (a + item.offsetWidth > strip.scrollLeft + strip.clientWidth) {
      strip.scrollLeft = a + item.offsetWidth - strip.clientWidth + 8;
    }
  }

  showGraph(name) {
    const g = this.data?.graphs.find((x) => x.name === name);
    if (!g) return;
    for (const tab of this.$.tabs.children) {
      const on = tab.dataset.name === name;
      tab.setAttribute("aria-selected", on);
      tab.tabIndex = on ? 0 : -1;
      if (on) this.reach(this.$.tabs, tab);
    }
    this.$.title.innerHTML = `<span class="kind">${escape(g.kind)} graph</span>${escape(g.name)}`;
    this.$.title.title = `${g.kind} graph ${g.name}`;
    this.$.desc.textContent = g.description || "";
    this.$.graph.innerHTML = g.svg + `<div class="hint"></div>`;
    this.hint();
    const svg = this.$.graph.querySelector("svg");
    const d = svg.dataset;
    this.home = { x: +d.x, y: +d.y, w: +d.w, h: +d.h };
    this.fit();
    svg.querySelectorAll(".node").forEach((node) => {
      node.addEventListener("pointerenter", () => this.mark(+node.dataset.line, true));
      node.addEventListener("pointerleave", () => this.mark(+node.dataset.line, false));
      node.addEventListener("click", () => this.reveal(+node.dataset.line));
    });
    this.scrollToGraph(g.name);
  }

  /** The code scrolled to the declaration of the graph shown: a file of several opens on the one picked. */
  scrollToGraph(name) {
    const re = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    const decl = new RegExp(`\\bgraph\\s+(?:${re(name)}|${re(JSON.stringify(name))})\\s*\\(`);
    const at = this.source.split("\n").findIndex((l) => decl.test(l));
    const el = this.$.code.querySelector(`.line[data-line="${at + 1}"]`);
    if (at < 0 || !el) return;
    // From the top of the pane, not of the element: offsetTop would count the bar above it
    const pre = this.$.code;
    pre.scrollTo({ top: pre.scrollTop + el.getBoundingClientRect().top - pre.getBoundingClientRect().top - 8 });
  }

  /** The code line of a node marked while the pointer is on it. */
  mark(line, on) {
    this.$.code.querySelector(`.line[data-line="${line}"]`)?.classList.toggle("mark", on);
  }

  reveal(line) {
    const el = this.$.code.querySelector(`.line[data-line="${line}"]`);
    if (!el || this.$.root.dataset.view === "nodes") return;
    const pre = this.$.code;
    pre.scrollTo({ top: el.offsetTop - pre.clientHeight / 2, behavior: "smooth" });
  }

  setView(v) {
    if (v === "both") v = "split";
    if (!["code", "nodes", "split"].includes(v)) v = "split";
    this.$.root.dataset.view = v;
    this.shadowRoot.querySelectorAll(".seg button").forEach((b) =>
      b.setAttribute("aria-pressed", String(b.dataset.v === v)));
    if (this.home) requestAnimationFrame(() => this.fit());
  }

  async copy() {
    const btn = this.$.copy;
    try {
      await navigator.clipboard.writeText(this.source);
    } catch {
      const t = document.createElement("textarea");
      t.value = this.source;
      t.style.cssText = "position:fixed;opacity:0";
      document.body.append(t);
      t.select();
      document.execCommand("copy");
      t.remove();
    }
    btn.classList.add("done");
    btn.innerHTML = ICONS.done;
    btn.title = "Copied";
    clearTimeout(this.copied);
    this.copied = setTimeout(() => {
      btn.classList.remove("done");
      btn.innerHTML = ICONS.copy;
      btn.title = "Copy the code";
    }, 1500);
  }

  toggleExpanded(on = !this.hasAttribute("expanded")) {
    this.toggleAttribute("expanded", on);
    const btn = this.$?.expand;
    if (btn) {
      btn.innerHTML = on ? ICONS.shrink : ICONS.expand;
      btn.title = btn.ariaLabel = on ? "Reduce (Esc)" : "Enlarge";
    }
    document.documentElement.style.overflow = on ? "hidden" : "";
    if (on) document.addEventListener("keydown", this.onKey);
    else document.removeEventListener("keydown", this.onKey);
    this.hint();
    if (this.home) requestAnimationFrame(() => this.fit());
  }

  /** The whole graph in view, not enlarged past its size. */
  fit() {
    const h = this.home;
    const el = this.$.graph;
    if (!h || !el.clientWidth) return;
    const scale = Math.max(h.w / el.clientWidth, h.h / el.clientHeight, 1);
    const w = el.clientWidth * scale;
    const hh = el.clientHeight * scale;
    this.setBox({ x: h.x - (w - h.w) / 2, y: h.y - (hh - h.h) / 2, w, h: hh });
  }

  setBox(b) {
    this.box = b;
    const svg = this.$.graph.querySelector("svg");
    svg?.setAttribute("viewBox", `${b.x} ${b.y} ${b.w} ${b.h}`);
    // The grid follows the view.
    let step = 24 * (this.$.graph.clientWidth / b.w);
    while (step < 12) step *= 4;
    this.$.graph.style.backgroundSize = `${step}px ${step}px`;
    this.$.graph.style.backgroundPosition = `${-b.x * (this.$.graph.clientWidth / b.w)}px ${-b.y * (this.$.graph.clientWidth / b.w)}px`;
  }

  /** The graph takes the wheel when it has the focus (a click), or the window (enlarged). */
  zooms() {
    return this.$.graph.classList.contains("active") || this.hasAttribute("expanded");
  }

  /** What the pointer does now; `ask` says the wheel was refused. */
  hint(ask = false) {
    const el = this.$.graph.querySelector(".hint");
    if (!el) return;
    el.classList.toggle("ask", ask);
    el.textContent = this.zooms()
      ? "drag to pan · wheel to zoom · double-click to fit"
      : ask
        ? "click the graph to zoom with the wheel, or Ctrl + wheel"
        : "click to zoom and pan · double-click to fit";
    clearTimeout(this.asked);
    if (ask) this.asked = setTimeout(() => this.hint(), 1600);
  }

  /**
   * `el` active (class `active`) from a click or the keyboard's focus until
   * Esc, a click elsewhere or the focus leaving: only then it takes the wheel,
   * so that the page scrolls over it. `changed` runs on each change.
   */
  holdFocus(el, changed) {
    const activate = (on) => {
      if (el.classList.contains("active") === on) return;
      el.classList.toggle("active", on);
      changed();
    };
    el.addEventListener("focus", () => activate(true));
    el.addEventListener("blur", () => activate(false));
    el.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && !this.hasAttribute("expanded")) {
        activate(false);
        el.blur();
      }
    });
    el.addEventListener("pointerdown", () => {
      activate(true);
      el.focus({ preventScroll: true });
    });
    this.outside.push((e) => {
      if (!e.composedPath().includes(el)) activate(false);
    });
  }

  /** The code scrolls with the wheel once clicked (or enlarged); before, the page does. */
  scrolls() {
    const el = this.$.code;
    const ask = (on) => {
      el.querySelector(".hint")?.classList.toggle("ask", on);
      clearTimeout(this.codeAsked);
      if (on) this.codeAsked = setTimeout(() => ask(false), 1600);
    };
    this.holdFocus(el, () => ask(false));
    el.addEventListener("wheel", () => {
      if (el.classList.contains("active") || this.hasAttribute("expanded")) return;
      if (el.scrollHeight > el.clientHeight || el.scrollWidth > el.clientWidth) ask(true);
    }, { passive: true });
  }

  panZoom() {
    const el = this.$.graph;
    let drag = null;
    this.holdFocus(el, () => this.hint());
    el.addEventListener("pointerdown", (e) => {
      if (e.button !== 0 || !this.box) return;
      drag = { x: e.clientX, y: e.clientY, box: { ...this.box }, moved: false };
      el.setPointerCapture(e.pointerId);
    });
    el.addEventListener("pointermove", (e) => {
      if (!drag) return;
      const k = drag.box.w / el.clientWidth;
      const dx = e.clientX - drag.x;
      const dy = e.clientY - drag.y;
      if (!drag.moved && Math.hypot(dx, dy) < 3) return;
      drag.moved = true;
      el.classList.add("dragging");
      this.setBox({ ...drag.box, x: drag.box.x - dx * k, y: drag.box.y - dy * k });
    });
    const end = () => {
      drag = null;
      el.classList.remove("dragging");
    };
    el.addEventListener("pointerup", end);
    el.addEventListener("pointercancel", end);
    el.addEventListener("wheel", (e) => {
      if (!this.box) return;
      // Not focused, the wheel scrolls the page; Ctrl (a pinch on a touchpad) still zooms.
      if (!this.zooms() && !e.ctrlKey && !e.metaKey) return this.hint(true);
      e.preventDefault();
      const r = el.getBoundingClientRect();
      const b = this.box;
      const f = Math.exp(Math.sign(e.deltaY) * Math.min(Math.abs(e.deltaY), 100) / 400);
      const w = Math.min(Math.max(b.w * f, 80), this.home.w * 8 + 2000);
      const k = w / b.w;
      const px = b.x + ((e.clientX - r.left) / r.width) * b.w;
      const py = b.y + ((e.clientY - r.top) / r.height) * b.h;
      this.setBox({ x: px - (px - b.x) * k, y: py - (py - b.y) * k, w, h: b.h * k });
    }, { passive: false });
    el.addEventListener("dblclick", () => this.fit());
    new ResizeObserver(() => this.home && this.fit()).observe(el);
  }
}

customElements.define("bn-view", BnView);
