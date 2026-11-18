"""The reference pages of the site: `base-node docs`."""

import re
from html.parser import HTMLParser
from pathlib import Path

from base_node.cli import main
from base_node.refdoc import cells, highlight, markdown, slug

ROOT = Path(__file__).resolve().parents[2]


class Anchors(HTMLParser):
    """The ids of a page and the links it makes."""

    def __init__(self):
        super().__init__()
        self.ids, self.links = set(), []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if "id" in attrs:
            self.ids.add(attrs["id"])
        for name in ("href", "src"):
            if attrs.get(name):
                self.links.append(attrs[name])


def test_every_page_is_written_and_every_link_lands(tmp_path):
    assert main(["docs", "--root", str(ROOT), "--out", str(tmp_path)]) == 0
    pages = {p.name: p for p in tmp_path.glob("*.html")}
    expected = {"index.html", "language.html", "versioning.html", "idioms.html", "targets.html", "stdlib.html",
                "nodes-geometry.html", "nodes-shader.html", "nodes-compositor.html"}
    assert expected <= set(pages)
    import json
    modules = json.loads((ROOT / "stdlib" / "manifest.json").read_text())["modules"]
    assert {f"stdlib-{m}.html" for m in modules} <= set(pages)

    parsed = {}
    for name, path in pages.items():
        a = Anchors()
        a.feed(path.read_text(encoding="utf-8"))
        parsed[name] = a
    broken = []
    for name, a in parsed.items():
        for link in a.links:
            if re.match(r"[a-z]+:", link):
                continue
            target, _, anchor = link.partition("#")
            if target.startswith("../"):
                # The site around the reference: the home page and its images
                if not (ROOT / "site" / target[3:]).exists():
                    broken.append(f"{name}: {link}")
                continue
            page = target or name
            if page not in parsed or anchor and anchor not in parsed[page].ids:
                broken.append(f"{name}: {link}")
    assert not broken, "\n".join(broken[:20])


def test_a_stdlib_page_says_where_each_graph_builds(tmp_path):
    main(["docs", "--root", str(ROOT), "--out", str(tmp_path)])
    math = (tmp_path / "stdlib-math.html").read_text(encoding="utf-8")
    assert 'id="gain"' in math
    assert "not in a shader tree: no Compare in a shader tree" in math


def test_the_idioms_show_their_nodes(tmp_path):
    main(["docs", "--root", str(ROOT), "--out", str(tmp_path)])
    idioms = (tmp_path / "idioms.html").read_text(encoding="utf-8")
    assert '<script type="module" src="../view/bn-view.js"></script>' in idioms
    assert idioms.count("<bn-view") >= 10
    # The language's fragments stay highlighted code: they are not whole texts
    assert "<bn-view" not in (tmp_path / "language.html").read_text(encoding="utf-8")


def test_markdown_tables_keep_a_pipe_in_code():
    assert cells("| `a |> f` | b |") == ["`a |> f`", "b"]


def test_markdown_lists_hold_their_tables():
    out = markdown("1. **One**: text\n   goes on.\n\n   | A | B |\n   |---|---|\n   | 1 | 2 |\n2. Two")
    assert out.startswith("<ol><li><strong>One</strong>: text goes on.<table>")
    assert "<li>Two</li></ol>" in out


def test_headings_have_the_anchors_github_gives_them():
    assert slug("3.0 Shader and Compositor Graphs") == "30-shader-and-compositor-graphs"
    assert slug("C. What they ask of the language") == "c-what-they-ask-of-the-language"
    assert slug("`use` and modules") == "use-and-modules"


def test_bn_code_is_highlighted():
    out = highlight('geometry graph f(x: Float = 1.0) -> Float {\n  return Mix(x, "a") // why\n}')
    assert '<span class="kw">graph</span>' in out
    assert '<span class="fn">Mix</span>' in out
    assert '<span class="ty">Float</span>' in out
    assert '<span class="str">&quot;a&quot;</span>' in out
    assert '<span class="cmt">// why</span>' in out
