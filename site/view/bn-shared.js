// What <bn-view> and <bn-file> share: base-node's wasm, the text of an
// element (its src file, or the text inside it), and that text as a .bn file
// to download, with what its head offers the Blender add-on.

import init, { render, file } from "./pkg/base_node_web.js";

// The colors of <bn-view> and <bn-file>: dark, light for the page's color
// scheme and for theme="light", dark again for theme="dark".
const LIGHT = `
  color-scheme: light;
  --bn-bg: #f6f8fa; --bn-border: #d0d7de; --bn-text: #1f2328; --bn-muted: #59636e;
  --bn-accent: #0969da; --bn-ok: #1a7f37; --bn-ok-bg: rgba(26,127,55,.1);
  --bn-kw: #cf222e; --bn-ty: #0550ae; --bn-fn: #8250df; --bn-str: #0a3069; --bn-num: #953800; --bn-cmt: #6e7781;
  --bn-mark: rgba(9,105,218,.12);
  --ne-bg: #c8c8c8; --ne-grid: rgba(50,50,50,.18); --ne-node: #e6e6e6; --ne-outline: #6b6b6b;
  --ne-text: #1a1a1a; --ne-field: #fafafa; --ne-menu: #d4d4d4; --ne-frame: rgba(80,80,80,.14); --ne-zone: rgba(184,138,90,.28);
  --ne-note: #f3f3ef; --ne-note-text: #262626; --ne-note-bar: #8c8c8c;
  --ne-input: #cb3d4a; --ne-output: #cb3d4a; --ne-converter: #3d8fbf; --ne-vector: #6c6cc9;
  --ne-texture: #e08a3c; --ne-geometry: #3fad8d; --ne-shader: #4cae4c; --ne-group: #5fa0a0; --ne-zone-h: #b88a5a;
`;

export const THEME = `
:host {
  color-scheme: dark;
  --bn-bg: #161920; --bn-border: #262b36; --bn-text: #e6e9ef; --bn-muted: #939ab0;
  --bn-accent: #4f9cf9; --bn-ok: #3fb950; --bn-ok-bg: rgba(63,185,80,.14);
  --bn-kw: #ff7b72; --bn-ty: #79c0ff; --bn-fn: #d2a8ff; --bn-str: #a5d6ff; --bn-num: #f2cc60; --bn-cmt: #6e7681;
  --bn-mark: rgba(79,156,249,.18);
  --ne-bg: #1d1d1d; --ne-grid: rgba(84,84,84,.35); --ne-node: #303030; --ne-outline: #000;
  --ne-text: #e5e5e5; --ne-field: #545454; --ne-menu: #282828; --ne-frame: rgba(155,155,155,.18); --ne-zone: rgba(118,81,47,.28);
  --ne-note: #191919; --ne-note-text: #d6d6d6; --ne-note-bar: #808080;
  --ne-input: #83314a; --ne-output: #4d0017; --ne-converter: #246283; --ne-vector: #3c3c83;
  --ne-texture: #79461d; --ne-geometry: #1d725e; --ne-shader: #2b652b; --ne-group: #3b5959; --ne-zone-h: #6b4c2e;
}
@media (prefers-color-scheme: light) {
  :host(:not([theme="dark"])) {
${LIGHT}
  }
}
:host([theme="light"]) {
${LIGHT}
}
`;

export const FILE_ICON =
  '<svg viewBox="0 0 24 24"><path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5M12 11v6M9 14l3 3 3-3"/></svg>';

let ready = null;

/** The wasm's functions, once it is loaded: render (code, graphs, tags) and file (the head alone). */
export async function wasm() {
  await (ready ??= init());
  return { render, file };
}

/** Its common indentation and the blank lines around it removed. */
export function dedent(text) {
  const lines = text.replace(/\t/g, "  ").split("\n");
  while (lines.length && !lines[0].trim()) lines.shift();
  while (lines.length && !lines[lines.length - 1].trim()) lines.pop();
  const indent = Math.min(...lines.filter((l) => l.trim()).map((l) => l.match(/^ */)[0].length));
  return lines.map((l) => l.slice(Number.isFinite(indent) ? indent : 0)).join("\n") + "\n";
}

export function escape(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
}

/**
 * The text of `el`: its src file, else the <script type="text/bn"> inside it
 * (which keeps `<` safe), else its text, dedented. Throws when src cannot be read.
 */
export async function readSource(el) {
  const src = el.getAttribute("src");
  if (src) {
    const r = await fetch(new URL(src, document.baseURI));
    if (!r.ok) throw new Error(`Cannot load ${src}: ${r.status} ${r.statusText}`);
    return r.text();
  }
  const script = el.querySelector('script[type="text/bn"]');
  return dedent(script ? script.textContent : el.textContent);
}

/**
 * A text as a .bn file to download, for File > Import in Blender (or a drop
 * from the file manager): named after `src` when it is a .bn file, else as
 * its head says (`drop.file`). A browser cannot drag a file onto Blender:
 * Blender reads only a file on disk, and a dragged link or text is a string
 * no add-on can catch.
 */
export class DownloadedFile {
  constructor(source, src, drop) {
    const at = src ? new URL(src, document.baseURI) : null;
    this.name = at && /\.bn$/i.test(at.pathname) ? at.pathname.split("/").pop() : drop.file;
    this.href = URL.createObjectURL(new Blob([source], { type: "text/plain" }));
  }

  dispose() {
    URL.revokeObjectURL(this.href);
  }
}

/**
 * What the file offers the Blender add-on that imports it: {text, title},
 * `refused` when its head is in error; null when the add-on does not read it.
 */
export function offer(drop) {
  if (!drop?.blender) return null;
  if (drop.problems.length) {
    return {
      refused: true,
      text: "✕ head",
      title: "Blender refuses the file: " +
        drop.problems.map((p) => `line ${p.line}: ${p.message}`).join("; "),
    };
  }
  const about = [drop.title, drop.author && `by ${drop.author}`, drop.license].filter(Boolean).join(", ");
  const uses = [drop.example && `example ${drop.example}`, drop.modifier && `modifier ${drop.modifier}`]
    .filter(Boolean).join(", ");
  return {
    refused: false,
    text: drop.offer.join(" · "),
    title: `Imported into Blender (File > Import, or dropped from the file manager), ${drop.file} offers: ${drop.offer.join(", ")}` +
      (uses ? ` (${uses})` : "") + (about ? `. ${about}` : ""),
  };
}
