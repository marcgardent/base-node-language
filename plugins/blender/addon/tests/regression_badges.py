"""The badges of the third-party non-regression tests, one per kind of tree, from the baselines.

Each badge counts, over every `tests/libraries/<name>.baseline.json`, the trees of its kind that round-trip
`ok` (read as text, built back, read again the same, and evaluated or rendered as the original), out of all
of them: Geometry Nodes groups, shader groups and materials, compositor groups. A manifest's `trees` say
which kind its groups are (`geometry` by default); a material's record (`material:<name>`) is a shader one.

Written to `site/badges/regression-<kind>.svg`, shown in the README. Needs no Blender:
    python3 addon/tests/regression_badges.py           # write them again
    python3 addon/tests/regression_badges.py --check   # fail when one is not as its baselines say
`test_libraries.py` writes them again with the baselines (BASE_NODE_UPDATE_FIXTURES=1).
"""

from __future__ import annotations

import json
import sys
import tomllib
from pathlib import Path

HERE = Path(__file__).resolve().parent
LIBRARIES = HERE / "libraries"
BADGES = HERE.parents[1] / "site" / "badges"
MATERIAL = "material:"

# kind: (file name, label)
KINDS = {
    "geometry": ("regression-geometry.svg", "Geometry Nodes regression"),
    "shader": ("regression-shader.svg", "Shader regression"),
    "compositor": ("regression-compositor.svg", "Compositor regression"),
}
GROUP_TREES = ("geometry", "shader", "compositor")


def counts(libraries=LIBRARIES):
    """{kind: (ok, total, number of libraries)} over the baselines."""
    found = {k: [0, 0, 0] for k in KINDS}
    for manifest in sorted(libraries.glob("*.toml")):
        baseline = manifest.with_suffix(".baseline.json")
        if not baseline.exists():
            continue
        trees = tomllib.loads(manifest.read_text(encoding="utf-8")).get("trees", ["geometry"])
        groups = [t for t in trees if t in GROUP_TREES]
        assert len(groups) <= 1, f"{manifest.name}: groups of more than one kind of tree ({groups}) cannot be told apart"
        group_kind = groups[0] if groups else None
        seen = set()
        for name, record in json.loads(baseline.read_text(encoding="utf-8"))["groups"].items():
            kind = "shader" if name.startswith(MATERIAL) else group_kind
            assert kind is not None, f"{manifest.name}: record {name!r} of no kind its trees name"
            found[kind][0] += record["status"] == "ok"
            found[kind][1] += 1
            seen.add(kind)
        for kind in seen:
            found[kind][2] += 1
    return {k: tuple(v) for k, v in found.items()}


def color(ok, total):
    if total == 0:
        return "#9f9f9f"
    share = ok / total
    return "#4c1" if share == 1 else "#97ca00" if share >= 0.95 else "#dfb317" if share >= 0.8 else "#e05d44"


def width(text):
    """About the width of `text` in Verdana 11px, as the flat badges are drawn."""
    narrow, wide = set("fijlrt .,:;!|()/'-1"), set("mwMW%@")
    return sum(4 if c in narrow else 10 if c in wide else 8 if c.isupper() else 7 for c in text) + 12


def badge(label, ok, total, libraries):
    value = f"{ok}/{total} ok" if total else "none"
    title = f"{label}: {value}, over {libraries} {'library' if libraries == 1 else 'libraries'}"
    lw, vw = width(label), width(value)
    w = lw + vw
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="20" role="img" aria-label="{title}">
  <title>{title}</title>
  <linearGradient id="s" x2="0" y2="100%"><stop offset="0" stop-color="#bbb" stop-opacity=".1"/><stop offset="1" stop-opacity=".1"/></linearGradient>
  <clipPath id="r"><rect width="{w}" height="20" rx="3" fill="#fff"/></clipPath>
  <g clip-path="url(#r)">
    <rect width="{lw}" height="20" fill="#555"/>
    <rect x="{lw}" width="{vw}" height="20" fill="{color(ok, total)}"/>
    <rect width="{w}" height="20" fill="url(#s)"/>
  </g>
  <g fill="#fff" text-anchor="middle" font-family="Verdana,Geneva,DejaVu Sans,sans-serif" font-size="11">
    <text x="{lw / 2}" y="15" fill="#010101" fill-opacity=".3">{label}</text>
    <text x="{lw / 2}" y="14">{label}</text>
    <text x="{lw + vw / 2}" y="15" fill="#010101" fill-opacity=".3">{value}</text>
    <text x="{lw + vw / 2}" y="14">{value}</text>
  </g>
</svg>
'''


def badges(libraries=LIBRARIES):
    """{file name: svg text} of every badge."""
    found = counts(libraries)
    return {file: badge(label, *found[kind]) for kind, (file, label) in KINDS.items()}


def write(out=BADGES):
    out.mkdir(parents=True, exist_ok=True)
    for file, svg in badges().items():
        (out / file).write_text(svg, encoding="utf-8")
    return out


def check(out=BADGES):
    """The badges that are not as the baselines say."""
    return [file for file, svg in badges().items()
            if not (out / file).exists() or (out / file).read_text(encoding="utf-8") != svg]


if __name__ == "__main__":
    if "--check" in sys.argv:
        stale = check()
        if stale:
            sys.exit(f"badges not as the baselines say: {', '.join(stale)}; "
                     "write them again: python3 addon/tests/regression_badges.py")
        print("Regression badges as the baselines say")
    else:
        print(f"Regression badges written to {write()}")
        for kind, (ok, total, libs) in counts().items():
            print(f"  {kind}: {ok}/{total} ok over {libs} {'library' if libs == 1 else 'libraries'}")
