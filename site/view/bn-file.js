// <bn-file>: a .bn file as a card to download, for File > Import in Blender
// (or a drop from the file manager) — its title, its file name, what its
// head offers the Base Node add-on.
// Its head is read by base-node compiled to wasm (web/), as <bn-view> reads it.
//
//   <script type="module" src="view/bn-file.js"></script>
//   <bn-file src="drop_example.bn"></bn-file>
//   <bn-file><script type="text/bn">
//     // @title Ripples
//     geometry graph ripples() -> Geometry { return Grid() }
//   </script></bn-file>
//
// Attributes: src (a .bn file) or the text inside (a <script type="text/bn">
// keeps `<` safe); theme = dark | light (default: the page's color scheme).

import { DownloadedFile, FILE_ICON, THEME, escape, offer, readSource, wasm } from "./bn-shared.js";

const STYLE = `${THEME}
:host {
  display: inline-block; max-width: 100%; vertical-align: middle; margin: .25rem 0;
  font: 13px/1.4 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
}
* { box-sizing: border-box; }
.card {
  display: flex; align-items: center; gap: .75rem; min-width: 0; max-width: 28rem;
  padding: .6rem .85rem .6rem .7rem; border-radius: 10px;
  color: var(--bn-text); background: var(--bn-bg); text-decoration: none;
  border: 1.5px dashed color-mix(in srgb, var(--bn-accent) 55%, var(--bn-border));
  cursor: pointer; user-select: none; transition: border-color .15s, background-color .15s;
}
.card:hover { border-style: solid; border-color: var(--bn-accent); }
.card:focus-visible { outline: 2px solid var(--bn-accent); outline-offset: 2px; }
.card:active { background: color-mix(in srgb, var(--bn-accent) 10%, var(--bn-bg)); }
.icon {
  flex: none; width: 36px; height: 36px; border-radius: 8px; display: grid; place-items: center;
  color: var(--bn-accent); background: color-mix(in srgb, var(--bn-accent) 14%, transparent);
}
.icon svg { width: 20px; height: 20px; fill: none; stroke: currentColor; stroke-width: 1.8; stroke-linecap: round; stroke-linejoin: round; }
.text { min-width: 0; display: grid; gap: .1rem; }
.title { font-weight: 600; font-size: 14px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.meta { color: var(--bn-muted); font-size: 12px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.meta .name { font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", monospace; }
.offer { color: var(--bn-accent); font-size: 11.5px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.offer.refused { color: #f85149; }
.card.error { cursor: default; border-color: #f85149; border-style: solid; }
.card.error .icon { color: #f85149; background: rgba(248,81,73,.12); }
`;

class BnFile extends HTMLElement {
  static observedAttributes = ["src"];

  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this.file = null;
  }

  connectedCallback() {
    if (!this.shadowRoot.firstChild) this.build();
    this.load();
  }

  disconnectedCallback() {
    this.file?.dispose();
    this.file = null;
  }

  attributeChangedCallback(name, old, value) {
    if (name === "src" && old !== value && this.isConnected && this.shadowRoot.firstChild) this.load();
  }

  build() {
    this.shadowRoot.innerHTML = `<style>${STYLE}</style>
      <a class="card" part="card" draggable="false">
        <span class="icon" aria-hidden="true">${FILE_ICON}</span>
        <span class="text">
          <span class="title" part="title">…</span>
          <span class="meta" part="meta"></span>
          <span class="offer" part="offer"></span>
        </span>
      </a>`;
    const $ = (s) => this.shadowRoot.querySelector(s);
    this.$ = { card: $(".card"), title: $(".title"), meta: $(".meta"), offer: $(".offer") };
  }

  async load() {
    try {
      this.show(await readSource(this));
    } catch (e) {
      this.fail(e.message);
    }
  }

  /** The card of `source`: its title (its head's, else its file's name), its file, what it offers. */
  async show(source) {
    const { file } = await wasm();
    const { error, drop } = JSON.parse(file(source));
    if (error) return this.fail(`Line ${error.line}, column ${error.col}: ${error.message}`);
    this.file?.dispose();
    this.file = new DownloadedFile(source, this.getAttribute("src"), drop);
    const { card, title, meta } = this.$;
    card.classList.remove("error");
    card.href = this.file.href;
    card.download = this.file.name;
    card.title = `Download ${this.file.name}, then File > Import it in Blender (or drop it from the file manager)`;
    title.textContent = drop.title || this.file.name.replace(/\.bn$/i, "");
    const by = [drop.author && `by ${drop.author}`, drop.license].filter(Boolean).map(escape).join(" · ");
    meta.innerHTML = `<span class="name">${escape(this.file.name)}</span>${by ? ` · ${by}` : ""}`;
    this.showOffer(drop);
  }

  showOffer(drop) {
    const el = this.$.offer;
    const o = offer(drop);
    el.hidden = !o;
    if (!o) return;
    el.className = o.refused ? "offer refused" : "offer";
    el.textContent = o.refused ? `${o.text}: Blender refuses it` : `⇣ Blender: ${o.text}`;
    el.title = o.title;
  }

  fail(message) {
    this.file?.dispose();
    this.file = null;
    const { card, title, meta, offer: el } = this.$;
    card.classList.add("error");
    card.removeAttribute("href");
    card.title = message;
    title.textContent = "Cannot read this .bn";
    meta.textContent = message;
    el.hidden = true;
  }
}

customElements.define("bn-file", BnFile);
