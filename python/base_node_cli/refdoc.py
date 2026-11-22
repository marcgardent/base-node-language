"""The reference pages of the site: the language, the targets, the nodes of Blender, the stdlib, the idioms.

    base-node docs [--root .] [--out site/reference]

Everything is read from the repository: `spec/*.md` for the language and the idioms, `targets/*.json`
for the targets (and `targets/blender/` for the versions and the variants of `blender`), `targets/backends/blender-<x.y>.json` for the nodes of each kind of tree and
`targets/backends/blender-<x.y>/<module>.json` where each stdlib graph builds (written in Blender by
`base-node-for-blender/tests/export_backend.py`), and `stdlib/*.bn` with their heads for the modules. No dependency, no Blender: the Pages workflow runs it.
"""

from __future__ import annotations

import dataclasses
import html
import json
import re
from pathlib import Path

from base_node.ast import flatten
from base_node.lexer import tokenize, width
from base_node.manifest import manifest as stdlib_manifest
from base_node.names import key
from base_node.parser import parse
from base_node_blender.targets import ALIASES, BLENDER, NOT_JSON, Blender, Target, catalog

REPO = "https://github.com/marcgardent/base-node-language"
KINDS = ("geometry", "shader", "compositor")

# The spec's pages, by the name of their source
PAGES = {"reference.md": "language.html", "versioning.md": "versioning.html", "idioms.md": "idioms.html",
         "targets.md": "targets.html"}

NAV = (("index.html", "Reference"), ("language.html", "Language"), ("targets.html", "Targets"),
       ("nodes-geometry.html", "Nodes"), ("stdlib.html", "Stdlib"), ("idioms.html", "Idioms"))

CSS = """
:root { color-scheme: dark light; --bg: #0f1115; --panel: #161920; --border: #262b36; --text: #e6e9ef;
  --muted: #939ab0; --accent: #4f9cf9; --kw: #ff7b72; --ty: #79c0ff; --fn: #d2a8ff; --str: #a5d6ff;
  --num: #f2cc60; --cmt: #6e7681; --ok: #3fb950; --ko: #f85149;
  --mono: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", monospace;
  --sans: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; }
@media (prefers-color-scheme: light) { :root { --bg: #ffffff; --panel: #f6f8fa; --border: #d0d7de;
  --text: #1f2328; --muted: #59636e; --accent: #0969da; --kw: #cf222e; --ty: #0550ae; --fn: #8250df;
  --str: #0a3069; --num: #953800; --cmt: #6e7781; --ok: #1a7f37; --ko: #cf222e; } }
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--text); font-family: var(--sans); font-size: 15px;
  line-height: 1.55; }
.wrap { max-width: 1040px; margin: 0 auto; padding: 2rem 1rem 4rem; }
header { display: flex; flex-wrap: wrap; align-items: baseline; justify-content: space-between; gap: 0.75rem;
  border-bottom: 1px solid var(--border); padding-bottom: 0.75rem; }
header .home { font-family: var(--mono); font-size: 1.2rem; font-weight: 700; color: var(--text); }
header .home span { color: var(--muted); font-weight: 400; }
nav { display: flex; flex-wrap: wrap; gap: 1rem; font-family: var(--mono); font-size: 0.85rem; }
nav a[aria-current] { color: var(--text); font-weight: 700; }
a { color: var(--accent); text-decoration: none; } a:hover { text-decoration: underline; }
h1 { font-family: var(--mono); font-size: 1.5rem; margin: 1.5rem 0 0.75rem; }
h2 { margin: 2.25rem 0 0.75rem; font-size: 1.15rem; font-family: var(--mono);
  border-bottom: 1px solid var(--border); padding-bottom: 0.35rem; }
h3 { font-family: var(--mono); font-size: 1rem; margin: 1.75rem 0 0.4rem; }
h4 { font-size: 0.95rem; margin: 1.25rem 0 0.4rem; }
h2 a.anchor, h3 a.anchor { color: var(--muted); margin-left: 0.4rem; font-weight: 400; visibility: hidden; }
h2:hover a.anchor, h3:hover a.anchor { visibility: visible; }
code, pre { font-family: var(--mono); font-size: 0.86rem; }
p code, td code, li code, dd code { background: var(--panel); border: 1px solid var(--border);
  border-radius: 4px; padding: 0.05rem 0.3rem; }
pre { margin: 0.75rem 0; padding: 0.9rem 1rem; background: var(--panel); border: 1px solid var(--border);
  border-radius: 6px; overflow-x: auto; line-height: 1.45; }
.kw { color: var(--kw); } .ty { color: var(--ty); } .fn { color: var(--fn); } .str { color: var(--str); }
.num { color: var(--num); } .cmt { color: var(--cmt); font-style: italic; }
table { width: 100%; border-collapse: collapse; margin: 0.75rem 0; font-size: 0.88rem; display: block;
  overflow-x: auto; }
th, td { text-align: left; padding: 0.4rem 0.6rem; border: 1px solid var(--border); vertical-align: top; }
th { background: var(--panel); font-family: var(--mono); font-weight: 600; font-size: 0.8rem; }
.muted { color: var(--muted); }
details.node { border-bottom: 1px solid var(--border); padding: 0.35rem 0; }
details.node summary { cursor: pointer; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
details.node[open] summary { white-space: normal; }
details.node summary code { font-weight: 700; }
input[type=search] { font: inherit; font-size: 0.9rem; padding: 0.4rem 0.6rem; width: min(26rem, 100%);
  background: var(--panel); color: var(--text); border: 1px solid var(--border); border-radius: 6px; }
pre.sig { white-space: pre-wrap; overflow-wrap: anywhere; padding-left: 2.2rem; text-indent: -1.2rem; }
.lead { font-size: 1.05rem; }
.grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 1rem; margin: 1rem 0; }
.box { background: var(--panel); border: 1px solid var(--border); border-radius: 6px; padding: 0.9rem 1rem; }
.box h3 { margin: 0 0 0.4rem; }
.tags { display: flex; flex-wrap: wrap; gap: 0.35rem; margin: 0.4rem 0; }
.tag { white-space: nowrap; font-family: var(--mono); font-size: 0.75rem; border: 1px solid var(--border); border-radius: 999px;
  padding: 0.05rem 0.55rem; background: var(--panel); }
.tag.ok { border-color: var(--ok); color: var(--ok); } .tag.ko { border-color: var(--ko); color: var(--ko); }
.index { columns: 4 12rem; font-family: var(--mono); font-size: 0.82rem; margin: 1rem 0; }
.index a { display: block; }
.kinds { display: flex; gap: 0.75rem; font-family: var(--mono); font-size: 0.85rem; margin: 0.5rem 0 1rem; }
img.figure { max-width: 100%; border: 1px solid var(--border); border-radius: 6px; margin: 0.5rem 0; }
.toc { font-size: 0.88rem; } .toc ul { margin: 0.2rem 0; }
footer { margin-top: 3rem; padding-top: 1rem; border-top: 1px solid var(--border); color: var(--muted);
  font-size: 0.8rem; font-family: var(--mono); }
"""


def chip(text):
    """`text` as code, nothing when it is empty."""
    return f"<code>{esc(text)}</code>" if text else ""


def esc(s):
    return html.escape(str(s), quote=True)


# ---- .bn code ----

def highlight(code):
    """HTML of .bn code with its keywords, types, calls, strings, numbers and comments marked."""
    starts = [0]
    for line in code.split("\n"):
        starts.append(starts[-1] + len(line) + 1)
    tokens = [t for t in tokenize(code, strict=False) if t.kind != "EOF"]
    out, pos = [], 0
    for i, t in enumerate(tokens):
        at = starts[t.line - 1] + t.col - 1
        if at < pos:
            continue
        out.append(esc(code[pos:at]))
        end = at + width(t)
        text = code[at:end]
        nxt = tokens[i + 1].text if i + 1 < len(tokens) else ""
        cls = {"KEYWORD": "kw", "NUMBER": "num", "STRING": "str", "OPEN_STRING": "str", "COMMENT": "cmt",
               "COLOR": "num"}.get(t.kind)
        if t.kind == "IDENT":
            cls = "fn" if nxt in ("(", "[") else "ty" if t.text[:1].isupper() else None
        out.append(f'<span class="{cls}">{esc(text)}</span>' if cls else esc(text))
        pos = end
    out.append(esc(code[pos:]))
    return "".join(out)


def bn_view(code):
    """A `<bn-view>` of a whole .bn text: its code beside its nodes, to copy or download for Blender."""
    lines = code.strip("\n").count("\n") + 1
    height = min(max(300, 24 * lines + 160), 560)
    code = code.replace("</script", "<\\/script")
    return f'<bn-view height="{height}"><script type="text/bn">\n{code}\n</script></bn-view>'


def code_block(code, lang="bn", wrap=False):
    body = highlight(code) if lang == "bn" else esc(code)
    cls = ' class="sig"' if wrap else ""
    return f"<pre{cls}><code>{body}</code></pre>"



# ---- Markdown, the part of it the spec uses ----

def slug(text):
    """The anchor GitHub gives a heading: `3.0 Shader and Compositor Graphs` -> `30-shader-and-compositor-graphs`."""
    text = re.sub(r"[`*_]|\[([^\]]*)\]\([^)]*\)", lambda m: m.group(1) or "", text).strip().lower()
    return re.sub(r"\s", "-", re.sub(r"[^\w\s-]", "", text))


class Links:
    """Rewrites the links of a Markdown file: a spec page to its HTML page, a file of the repository to GitHub."""

    def __init__(self, root, source):
        self.root, self.source = root, source

    def __call__(self, url):
        if re.match(r"[a-z]+:|#", url):
            return url
        path, _, anchor = url.partition("#")
        target = (self.source.parent / path).resolve()
        if target.name in PAGES and target.parent == (self.root / "spec").resolve():
            return PAGES[target.name] + (f"#{anchor}" if anchor else "")
        try:
            rel = target.relative_to(self.root.resolve()).as_posix()
        except ValueError:
            return url
        kind = "tree" if target.is_dir() else "blob"
        return f"{REPO}/{kind}/main/{rel}" + (f"#{anchor}" if anchor else "")


def inline(text, link=lambda u: u):
    """Inline Markdown: code, links, images, bold, italic."""
    parts = re.split(r"(`+)(.+?)\1", text)
    out = []
    for i in range(0, len(parts), 3):
        s = esc(parts[i])
        s = re.sub(r"!\[([^\]]*)\]\(([^)\s]+)\)", lambda m: f'<img class="figure" alt="{m.group(1)}" src="{esc(link(html.unescape(m.group(2))))}">', s)
        s = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", lambda m: f'<a href="{esc(link(html.unescape(m.group(2))))}">{m.group(1)}</a>', s)
        s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
        s = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"<em>\1</em>", s)
        out.append(s)
        if i + 2 < len(parts):
            out.append(f"<code>{esc(parts[i + 2])}</code>")
    return "".join(out)


def cells(row):
    """The cells of a table row, a `|` in code aside (`a |> f`)."""
    row = row.strip()
    row = row.removeprefix("|")
    row = row[:-1] if row.endswith("|") and not row.endswith("\\|") else row
    out, cur, tick = [], "", False
    for c in row:
        if c == "`":
            tick = not tick
        if c == "|" and not tick:
            out.append(cur.strip())
            cur = ""
        else:
            cur += c
    out.append(cur.strip())
    return out


LIST = re.compile(r"^(\s*)([-*]|\d+\.)\s+(.*)$")


def markdown(text, link=lambda u: u, toc=None, views=False):
    """HTML of Markdown text. `toc` collects (level, id, title) of its headings; with `views`, each .bn
    example is a `<bn-view>`, its nodes beside its code."""
    lines = text.split("\n")
    out, i = [], 0

    def starts_block(s):
        return (not s.strip() or s.startswith(("#", "```", "|", ">")) or LIST.match(s) is not None)

    while i < len(lines):
        line = lines[i]
        if not line.strip():
            i += 1
        elif line.startswith("```"):
            lang = line[3:].strip()
            j = i + 1
            while j < len(lines) and not lines[j].startswith("```"):
                j += 1
            code = "\n".join(lines[i + 1:j])
            out.append(bn_view(code) if views and lang == "bn" else code_block(code, lang))
            i = j + 1
        elif m := re.match(r"^(#{1,6})\s+(.*)$", line):
            level, title = len(m.group(1)), m.group(2).strip()
            ident = slug(title)
            if toc is not None:
                toc.append((level, ident, title))
            anchor = f'<a class="anchor" href="#{ident}">#</a>' if level > 1 else ""
            out.append(f'<h{level} id="{ident}">{inline(title, link)}{anchor}</h{level}>')
            i += 1
        elif line.lstrip().startswith("|") and i + 1 < len(lines) and re.match(r"^\s*\|?[\s:|-]+$", lines[i + 1]) and "-" in lines[i + 1]:
            head = cells(line)
            j = i + 2
            rows = []
            while j < len(lines) and lines[j].lstrip().startswith("|"):
                rows.append(cells(lines[j]))
                j += 1
            out.append("<table><thead><tr>" + "".join(f"<th>{inline(c, link)}</th>" for c in head) + "</tr></thead><tbody>"
                       + "".join("<tr>" + "".join(f"<td>{inline(c, link)}</td>" for c in r) + "</tr>" for r in rows)
                       + "</tbody></table>")
            i = j
        elif line.startswith(">"):
            j = i
            while j < len(lines) and lines[j].startswith(">"):
                j += 1
            out.append("<blockquote>" + markdown("\n".join(l[1:].lstrip() for l in lines[i:j]), link) + "</blockquote>")
            i = j
        elif m := LIST.match(line):
            indent = len(m.group(1))
            ordered = m.group(2)[0].isdigit()
            items = []
            j = i
            while j < len(lines):
                mm = LIST.match(lines[j])
                if mm and len(mm.group(1)) == indent and mm.group(2)[0].isdigit() == ordered:
                    content_at = len(lines[j]) - len(mm.group(3))
                    body = [mm.group(3)]
                    j += 1
                    while j < len(lines):
                        s = lines[j]
                        if not s.strip():
                            # A blank line ends the item, unless the item goes on indented
                            if j + 1 < len(lines) and len(lines[j + 1]) - len(lines[j + 1].lstrip()) > indent and lines[j + 1].strip():
                                body.append("")
                                j += 1
                                continue
                            break
                        lead = len(s) - len(s.lstrip())
                        if lead <= indent and (LIST.match(s) or starts_block(s.lstrip())):
                            break
                        if lead <= indent and not body:
                            break
                        body.append(s[min(lead, content_at):] if lead > indent else s.strip())
                        j += 1
                    items.append(body)
                else:
                    break
            tag = "ol" if ordered else "ul"
            html_items = []
            for body in items:
                # The first lines are the item's text, what follows a block of its own
                first = []
                k = 0
                while k < len(body) and body[k].strip() and not starts_block(body[k]) or (k == 0 and k < len(body)):
                    first.append(body[k])
                    k += 1
                rest = "\n".join(body[k:])
                html_items.append("<li>" + inline(" ".join(s.strip() for s in first), link)
                                  + (markdown(rest, link) if rest.strip() else "") + "</li>")
            out.append(f"<{tag}>" + "".join(html_items) + f"</{tag}>")
            i = j
        elif line.lstrip().startswith("<"):
            out.append(line)
            i += 1
        else:
            j = i
            para = []
            while j < len(lines) and (j == i or not starts_block(lines[j])):
                para.append(lines[j].strip())
                j += 1
            out.append("<p>" + inline(" ".join(para), link) + "</p>")
            i = j
    return "\n".join(out)


# ---- Pages ----

# The web component of site/view: the code of a .bn beside its node graph
VIEW_SCRIPT = '\n<script type="module" src="../view/bn-view.js"></script>'


def page(title, body, current, version):
    here = ' aria-current="page"'
    nav = "".join(f'<a href="{href}"{here if href == current else ""}>{label}</a>'
                  for href, label in NAV)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)} — base-node reference</title>
<style>{CSS}</style>{VIEW_SCRIPT if "<bn-view" in body else ""}
</head>
<body>
<div class="wrap">
<header><a class="home" href="../index.html">base-node <span>(.bn) v{esc(version)}</span></a>
<nav>{nav}<a href="{REPO}">GitHub</a></nav></header>
<main>
{body}
</main>
<footer>Generated from the repository by <code>base-node docs</code>. MIT OR Apache-2.0.</footer>
</div>
</body>
</html>
"""


def toc_html(toc):
    items = [f'<li><a href="#{ident}">{inline(title)}</a></li>' for level, ident, title in toc if level == 2]
    return f'<nav class="toc box"><strong>Contents</strong><ul>{"".join(items)}</ul></nav>' if items else ""


# The spec pages whose .bn examples are whole texts, shown with their nodes
VIEWS = {"idioms.md"}


def spec_page(root, name):
    source = root / "spec" / name
    text = source.read_text(encoding="utf-8")
    toc = []
    body = markdown(text, Links(root, source), toc, views=name in VIEWS)
    title = next((t for level, _i, t in toc if level == 1), name)
    # The contents after the title
    first = body.find("</h1>")
    body = body[:first + 5] + toc_html(toc) + body[first + 5:] if first >= 0 else toc_html(toc) + body
    return re.sub(r"[`*]", "", title), body


# ---- Targets ----

def read_targets(root):
    """{name: Target} of the targets of the repository at `root`, in the order of the page: `blender`
    as every version promised, each of its versions, each variant of both, then the others."""
    folder = root / "targets"
    out = {}
    b = Blender(folder) if (folder / f"{BLENDER}.json").is_file() else None
    if b is not None:
        for variant in [None] + b.variants:
            for version in [None] + b.versions:
                t = b.target(version, variant)
                out[t.name] = t
    for p in sorted(folder.glob("*.json")):
        if p.stem != BLENDER:
            data = json.loads(p.read_text(encoding="utf-8"))
            out[p.stem] = Target(**{f.name: data[f.name] for f in dataclasses.fields(Target)
                                    if f.name in data and f.name not in NOT_JSON}, path=p)
    return out, b


def anchor_of(name):
    """The id of a target on the page: `blender@5.3 gltf` is `blender-5.3-gltf`."""
    return re.sub(r"[^a-z0-9.]+", "-", name)


def node_link(name, backend):
    for kind in KINDS:
        if any(n["name"] == name for n in backend["kinds"][kind]):
            return f'<a href="nodes-{kind}.html#{esc(name)}"><code>{esc(name)}</code></a>'
    return f"<code>{esc(name)}</code>"


def targets_page(root, targets, backend):
    targets, b = targets
    title, spec = spec_page(root, "targets.md")
    body = [spec, '<h2 id="every-target">Every target<a class="anchor" href="#every-target">#</a></h2>']
    codes = lambda xs: ", ".join(f"<code>{esc(x)}</code>" for x in xs) or "—"
    link = lambda name: f'<a href="#{anchor_of(name)}">{esc(name)}</a>'
    for name, t in targets.items():
        rows = [("Kinds of graph", codes(t.kinds))]
        if t.members:
            rows.append(("Versions", ", ".join(link(m.name) for m in t.members)
                         + ": a text fits when it fits each of them"))
            if name == BLENDER:
                aliases = [f"<code>{BLENDER}@{word}</code> ({'no catalog of it here' if b.alias(word) not in b.versions else link(b.name(b.alias(word)))})"
                           for word in ALIASES]
                rows.append(("Aliases, on a command line", ", ".join(aliases)))
                rows.append(("Variants", ", ".join(link(f"{BLENDER} {v}") for v in b.variants)))
        elif t.trees:
            for kind, tree in t.trees.items():
                left = [n for n in t.without if n not in tree["nodes"]]
                nodes = f'every node of a <a href="nodes-{kind}.html">{kind} tree</a> ({len(tree["nodes"])})'
                if left:
                    nodes = (f'every node of a <a href="nodes-{kind}.html">{kind} tree</a> but {len(left)} '
                             f'({len(tree["nodes"])}):<ul>'
                             + "".join(f"<li>{node_link(n, backend)}: {esc(t.without[n])}</li>" for n in left) + "</ul>")
                rows.append((f"<code>{kind} graph</code>",
                             f'types {codes(tree["types"])}<br>zones {codes(tree["zones"])}<br>'
                             f'implicit inputs {codes(tree["implicit"])}<br>{nodes}'))
        else:
            rows += [("Types", codes(t.types)), ("Zones", codes(t.zones)), ("Implicit inputs", codes(t.implicit)),
                     ("Nodes", ", ".join(node_link(n, backend) for n in t.nodes) or "—")]
        for source, tr in t.translators.items():
            pairs = []
            for src, dst in tr.get("nodes", {}).items():
                dst = dst if isinstance(dst, str) else dst["node"]
                pairs.append(node_link(src, backend) + ("" if dst == src else f" → <code>{esc(dst)}</code>"))
            kinds = ", ".join(f"<code>{esc(k)}</code> → <code>{esc(v)}</code>" for k, v in tr.get("kinds", {}).items())
            rows.append((f"From {link(source)}", (kinds + "<br>" if kinds else "") + ", ".join(pairs)))
        if t.bridges:
            rows.append(("Bridges", codes(t.bridges)))
        note = ' <span class="tag">experimental</span>' if t.experimental else ""
        body.append(f'<h3 id="{anchor_of(name)}">{esc(name)}{note}<a class="anchor" href="#{anchor_of(name)}">#</a></h3>'
                    f'<p>{esc(t.description)}</p><table><tbody>'
                    + "".join(f"<tr><th>{k}</th><td>{v}</td></tr>" for k, v in rows) + "</tbody></table>")
    return title, "\n".join(body)


def nodes_taken(t, kind):
    """The nodes a target takes in a graph of that kind: of several versions, those each takes."""
    if t.members:
        return set.intersection(*(nodes_taken(m, kind) for m in t.members))
    return set(t.trees.get(kind, {}).get("nodes", [])) if t.trees else set(t.nodes)


def target_links(names):
    return ", ".join(f'<a href="targets.html#{anchor_of(t)}">{esc(t)}</a>' for t in names) or "—"


def value_text(v):
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, float):
        return repr(v)
    if isinstance(v, list):
        return "(" + ", ".join(value_text(x) for x in v) + ")"
    if isinstance(v, str):
        return v if re.fullmatch(r"[A-Z0-9_]+", v) else json.dumps(v)
    return str(v)


def node_signature(node):
    ins = [f"{s['key']}: {s['type']}" + (f" = {value_text(s['default'])}" if "default" in s else "") for s in node["inputs"]]
    outs = [f"{s['key']}: {s['type']}" for s in node["outputs"]]
    sets = [f"{p['name']}: {value_text(p['default'])}" for p in node["settings"] if "default" in p]

    def listed(items, open_, close):
        return open_ + (", ".join(items) if len(", ".join(items)) < 70 else "\n  " + ",\n  ".join(items) + "\n") + close

    # Its settings in brackets, what a wire can feed in parentheses
    head = node["name"] + (listed(sets, "[", "]") if sets else "") + listed(ins, "(", ")")
    return head + (" -> (" + ", ".join(outs) + ")" if outs else "")


def nodes_page(kind, backend, targets):
    nodes = backend["kinds"][kind]
    # The targets a graph of this kind may promise that take the node: of `blender`, every version
    # promised, whole and by variant
    allowed = {}
    for name, t in targets[0].items():
        if "@" in name or kind not in t.kinds:
            continue
        listed = nodes_taken(t, kind)
        for n in nodes:
            if n["name"] in listed:
                allowed.setdefault(n["name"], []).append(name)
    body = [f"<h1>Nodes of a {kind} tree</h1>",
            f'<p class="lead">The {len(nodes)} nodes a <code>{kind} graph</code> can write in Blender {esc(backend["blender"])}, '
            "by the name the text calls them. The signature is a new node's: a setting may show or hide inputs "
            "(<code>Math[SINE]()</code> has one). Keys repeat as Blender's identifiers (<code>Value_001</code>).</p>",
            '<div class="kinds">' + " ".join(f'<a href="nodes-{k}.html"{" aria-current=page" if k == kind else ""}>{k}</a>' for k in KINDS) + "</div>",
            '<p><input id="filter" type="search" placeholder="Filter by name, label or bl_idname" '
            'aria-label="Filter nodes"> <span class="muted" id="count"></span></p>']
    for n in nodes:
        words = f'{n["name"]} {n["label"]} {n["bl_idname"]}'.lower()
        part = [f'<details class="node" id="{esc(n["name"])}" data-words="{esc(words)}"><summary><code>{esc(n["name"])}</code> '
                f'<span class="muted">{esc(n.get("description") or n["label"])}</span></summary>',
                f'<p><span class="muted">{esc(n["label"])} · <code>{esc(n["bl_idname"])}</code> · '
                f'<a href="#{esc(n["name"])}">link</a></span></p>',
                code_block(node_signature(n), wrap=True)]
        if n["settings"]:
            rows = []
            for p in n["settings"]:
                values = ", ".join(f"<code>{esc(i['value'])}</code>" for i in p.get("items", [])) or esc(p["kind"].lower())
                if p.get("datablock"):
                    values = f"a {esc(p['datablock'])}, by name"
                rows.append(f"<tr><td><code>{esc(p['name'])}</code></td><td>{values}</td>"
                            f"<td>{esc(value_text(p['default'])) if 'default' in p else ''}</td><td>{esc(p.get('description', ''))}</td></tr>")
            part.append("<table><thead><tr><th>Setting</th><th>Values</th><th>Default</th><th></th></tr></thead><tbody>"
                        + "".join(rows) + "</tbody></table>")
        if n.get("data"):
            part.append("<p>Data: " + ", ".join(f"<code>{esc(d['name'])}</code> ({esc(d['kind'].lower())})" for d in n["data"]) + "</p>")
        part.append('<div class="tags">' + "".join(f'<a class="tag" href="targets.html#{anchor_of(t)}">{esc(t)}</a>'
                                                   for t in allowed.get(n["name"], [])) + "</div>")
        body.append("\n".join(part) + "</details>")
    body.append(NODES_SCRIPT)
    return "\n".join(body)


# Opens the node the address names, and filters the list as one types
NODES_SCRIPT = """<script>
(function () {
  function open() {
    var id = decodeURIComponent(location.hash.slice(1));
    var el = id && document.getElementById(id);
    if (el && el.tagName === "DETAILS") { el.open = true; el.scrollIntoView(); }
  }
  window.addEventListener("hashchange", open);
  open();
  var input = document.getElementById("filter"), count = document.getElementById("count");
  var nodes = Array.prototype.slice.call(document.querySelectorAll("details.node"));
  function filter() {
    var q = input.value.trim().toLowerCase(), shown = 0;
    nodes.forEach(function (d) {
      var hit = !q || d.getAttribute("data-words").indexOf(q) >= 0;
      d.hidden = !hit;
      if (hit) shown++;
    });
    count.textContent = shown + " / " + nodes.length;
  }
  input.addEventListener("input", filter);
  filter();
})();
</script>"""


# ---- Stdlib ----

def module_files(root, module):
    """Its pictures under site/images and its example, as the README shows them."""
    stem = module.replace("_", "-")
    images = sorted((root / "site" / "images").glob(f"{stem}.png")) + \
        sorted((root / "site" / "images").glob(f"{stem}-*.png"))
    examples = sorted((root / "examples").glob(f"{module}_showcase.bn")) + sorted((root / "examples").glob(f"{module}.bn"))
    return images, examples


def module_intro(source):
    """The comment at the head of a module, its `@` lines aside, as paragraphs."""
    lines = []
    for line in source.split("\n"):
        s = line.strip()
        if not s.startswith("//"):
            if s:
                break
            lines.append("")
            continue
        s = s[2:].strip()
        if s.startswith("@") or s.startswith("Base Node Standard Library") or s.startswith("----"):
            continue
        lines.append(s)
    return [p for p in " ".join(x if x else "\n" for x in lines).split("\n") if p.strip()]


def graph_header(source, graph):
    """The text of a graph's declaration, up to its body."""
    lines = source.split("\n")[graph.line - 1:]
    out, depth = [], 0
    for line in lines:
        cut = None
        for i, c in enumerate(line):
            if c in "([":
                depth += 1
            elif c in ")]":
                depth -= 1
            elif c == "{" and depth == 0:
                cut = i
                break
        out.append(line if cut is None else line[:cut].rstrip())
        if cut is not None:
            break
    return "\n".join(out)


def sections(source):
    """{line: title} of the `// ---- Title ----` comments of a module."""
    return {i + 1: m.group(1) for i, line in enumerate(source.split("\n"))
            if (m := re.match(r"^\s*//\s*-{2,}\s*(.+?)\s*-{2,}\s*$", line))}


def range_text(r):
    if not r:
        return ""
    lo, hi = r
    return f"{value_text(_lit(lo)) if lo is not None else ''}..{value_text(_lit(hi)) if hi is not None else ''}"


def _lit(node):
    v = getattr(node, "value", node)
    return v


def default_text(p):
    d = p.default
    if d is None:
        return ""
    if hasattr(d, "name") and hasattr(d, "args"):
        return f"{d.name}()"
    if hasattr(d, "items"):
        return "(" + ", ".join(value_text(_lit(x)) for x in d.items) + ")"
    v = _lit(d)
    if getattr(d, "is_int", False):
        return str(int(v))
    return value_text(v)


def module_page(root, module, info, manifest, backend):
    source = (root / "stdlib" / info["file"]).read_text(encoding="utf-8")
    tree = parse(source, info["file"])
    builds = backend["stdlib"].get(module, {})
    images, examples = module_files(root, module)
    heads = sections(source)
    body = [f"<h1>{esc(module)}</h1>", f'<p class="lead">{esc(info.get("description", ""))}</p>']
    deps = ", ".join(f'<a href="stdlib-{d}.html">{d}</a>' for d in info.get("dependencies", [])) or "—"
    body.append("<table><tbody>"
                f'<tr><th>Targets</th><td>{target_links(info.get("targets", []))}</td></tr>'
                f'<tr><th>Version</th><td>{esc(info.get("version", ""))} (edition {esc(info.get("edition", ""))})</td></tr>'
                f"<tr><th>Depends on</th><td>{deps}</td></tr>"
                f'<tr><th>Import</th><td><code>use {esc(module)}</code> or <code>use {esc(module)} (name, …)</code></td></tr>'
                f'<tr><th>Source</th><td><a href="{REPO}/blob/main/stdlib/{info["file"]}"><code>stdlib/{info["file"]}</code></a>'
                + "".join(f' · example <a href="{REPO}/blob/main/{e.relative_to(root).as_posix()}"><code>{e.relative_to(root).as_posix()}</code></a>' for e in examples)
                + "</td></tr></tbody></table>")
    for p in module_intro(source):
        body.append(f"<p>{inline(p)}</p>")
    for img in images:
        body.append(f'<img class="figure" alt="{esc(img.stem)}" src="../images/{img.name}">')
    # The graphs, under the sections of the module
    index, parts = [], []
    marks = sorted(heads)
    for g in tree.graphs:
        title = next((heads[m] for m in reversed(marks) if m < g.line), None)
        if title and (not parts or parts[-1][0] != title):
            parts.append((title, []))
        elif not parts:
            parts.append((None, []))
        parts[-1][1].append(g)
    for title, graphs in parts:
        if title:
            ident = slug(title)
            body.append(f'<h2 id="{ident}">{esc(title)}<a class="anchor" href="#{ident}">#</a></h2>')
            index.append(f'<li><a href="#{ident}">{esc(title)}</a></li>')
        for g in graphs:
            k = key(g.name)
            part = [f'<h3 id="{k}">{esc(g.name)}<a class="anchor" href="#{k}">#</a></h3>']
            if g.description:
                part.append(f"<p>{inline(g.description)}</p>")
            part.append(code_block(graph_header(source, g), wrap=True))
            params = flatten(g.params)
            if params:
                part.append("<table><thead><tr><th>Input</th><th>Type</th><th>Default</th><th>Range</th></tr></thead><tbody>"
                            + "".join(f"<tr><td><code>{esc(p.key)}</code></td><td><code>{esc(p.type)}</code></td>"
                                      f"<td>{chip(default_text(p))}</td><td>{chip(range_text(p.range))}</td></tr>"
                                      for p in params) + "</tbody></table>")
            where = builds.get(g.name, {})
            if where:
                tags = []
                for kind in KINDS:
                    v = where.get(kind)
                    ok = v == "ok"
                    tip = "" if ok else f' title="{esc(v)}"'
                    tags.append(f'<span class="tag {"ok" if ok else "ko"}"{tip}>{kind} {"✓" if ok else "✗"}</span>')
                part.append('<div class="tags">' + "".join(tags) + "</div>")
                refused = [(kind, where[kind]) for kind in KINDS if where.get(kind) not in (None, "ok")]
                if refused and any(where.get(kind) == "ok" for kind in KINDS if kind != g.kind):
                    part.append("<p class=\"muted\">" + "; ".join(f"not in a {k} tree: {esc(v)}" for k, v in refused) + "</p>")
            body.append("\n".join(part))
    if index:
        first = 3 + len(module_intro(source)) + len(images)
        body.insert(first, f'<nav class="toc box"><strong>Sections</strong><ul>{"".join(index)}</ul></nav>')
    return "\n".join(body)


def stdlib_page(manifest, backend):
    rows = []
    for module, info in manifest["modules"].items():
        graphs = backend["stdlib"].get(module, {})
        counts = " ".join(f'<span class="tag">{k} {sum(1 for g in graphs.values() if g.get(k) == "ok")}</span>' for k in KINDS)
        rows.append(f'<tr><td><a href="stdlib-{module}.html"><code>{module}</code></a></td>'
                    f'<td>{target_links(info.get("targets", []))}</td>'
                    f"<td>{len(graphs)}</td><td>{counts}</td><td>{esc(info.get('description', ''))}</td></tr>")
    return ("<h1>Standard library</h1>"
            f'<p class="lead">Version {esc(manifest.get("stdlib_version", ""))}, edition {esc(manifest.get("edition", ""))}. '
            "A module's graph is built again for the caller's kind of tree when that tree has its nodes: "
            "the last column counts, for each kind, the graphs that build there "
            f"(checked in Blender {esc(backend['blender'])}).</p>"
            "<table><thead><tr><th>Module</th><th>Targets</th><th>Graphs</th><th>Builds in</th><th></th></tr></thead><tbody>"
            + "".join(rows) + "</tbody></table>")


def index_page(manifest, backend, targets):
    boxes = [
        ("language.html", "Language", "The <code>.bn</code> grammar and semantics: graphs, types, statements, expressions, zones, limits. "
         '<a href="versioning.html">Versioning</a>: editions, stdlib and lifecycle.'),
        ("targets.html", "Targets", f"{len([t for t in targets[0] if '@' not in t and ' ' not in t])} targets, what each destination accepts, and the nodes of each kind of tree in "
         f"Blender {esc(backend['blender'])}: "
         + ", ".join(f'<a href="nodes-{k}.html">{k}</a>' for k in KINDS) + "."),
        ("stdlib.html", "Standard library", f"{len(manifest['modules'])} modules, each graph with its signature, inputs and the kinds of tree it builds in."),
        ("idioms.html", "Idioms", "Ways of writing a graph that come back in most libraries, each with an example."),
    ]
    return ("<h1>Reference</h1><div class=\"grid\">"
            + "".join(f'<div class="box"><h3><a href="{h}">{t}</a></h3><p>{d}</p></div>' for h, t, d in boxes)
            + "</div>")


def build(root, out):
    """Write the reference pages of the repository at `root` into `out`. Returns the paths written."""
    root, out = Path(root), Path(out)
    manifest = stdlib_manifest(root / "stdlib")
    backend = catalog(root)
    targets = read_targets(root)
    version = manifest.get("stdlib_version", "")
    pages = {"index.html": ("Reference", index_page(manifest, backend, targets)),
             "targets.html": targets_page(root, targets, backend),
             "stdlib.html": ("Standard library", stdlib_page(manifest, backend))}
    for name, target in PAGES.items():
        if target not in pages:  # targets.html is its spec and the targets
            pages[target] = spec_page(root, name)
    for kind in KINDS:
        pages[f"nodes-{kind}.html"] = (f"{kind} nodes", nodes_page(kind, backend, targets))
    for module, info in manifest["modules"].items():
        pages[f"stdlib-{module}.html"] = (module, module_page(root, module, info, manifest, backend))
    out.mkdir(parents=True, exist_ok=True)
    written = []
    for name, (title, body) in pages.items():
        current = "nodes-geometry.html" if name.startswith("nodes-") else "stdlib.html" if name.startswith("stdlib") else \
            "language.html" if name == "versioning.html" else name
        path = out / name
        path.write_text(page(title, body, current, version), encoding="utf-8")
        written.append(path)
    return written
