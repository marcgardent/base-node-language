"""The reference corpus of the language: the groups of the third-party libraries as `.bn` text.

`corpus/v1/<library>/` holds, for each `tests/libraries/<library>.toml`, the text of every group (and
material) the reader writes of it, as `<key>.bn`, with a `README.md` made from the manifest and the
`LICENSE` of the library (a copy of `corpus/licenses/<id>.txt`). `<key>` is the key of the group's
name in code (`base_node.names.key`: the name when it is an identifier, else its snake_case,
`material:Copper` -> `material_copper`); two groups whose keys are the same but for case are refused.
`corpus/README.md` lists the libraries.

`test_libraries.py` writes a library's folder with its baseline, when the Blender that runs is the one
of `<library>.baseline.json` (BASE_NODE_UPDATE_FIXTURES=1). `python/tests/test_corpus.py` reads it
without Blender. Needs no Blender.
"""

from __future__ import annotations

import hashlib
import json
import tomllib
from pathlib import Path

HERE = Path(__file__).resolve().parent
LIBRARIES = HERE / "libraries"
ROOT = HERE.parents[1]
CORPUS = ROOT / "corpus"
V1 = CORPUS / "v1"
LICENSES = CORPUS / "licenses"
MATERIAL = "material:"


def text_hash(text):
    """The hash of a text kept in a baseline (`text`)."""
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def _key(name):
    try:
        from base_node.lang.names import key  # the add-on, in Blender
    except ImportError:
        from base_node.names import key  # python/, without Blender
    return key(name)


def file_names(groups):
    """{group: its file name} for the names of `groups`; refuses two that a file system without case
    would take for one."""
    names = {g: f"{_key(g)}.bn" for g in groups}
    seen = {}
    for g, f in names.items():
        other = seen.setdefault(f.lower(), g)
        assert other == g, f"{g!r} and {other!r} would both be written {f}"
    return names


def license_file(spdx):
    """corpus/licenses/<id>.txt, the text of a license as a manifest names it (`GPL-3.0-or-later`:
    `GPL-3.0.txt`)."""
    path = LICENSES / f"{spdx.removesuffix('-or-later').removesuffix('-only')}.txt"
    assert path.exists(), f"no text of {spdx} in {path.parent}"
    return path


def manifest_of(name):
    return tomllib.loads((LIBRARIES / f"{name}.toml").read_text(encoding="utf-8"))


def readme(lib, groups, base_node, blender):
    """The README.md of a library's folder: `lib` its manifest, `groups` the keys of its records."""
    materials = sum(g.startswith(MATERIAL) for g in groups)
    count = f"{len(groups)}" + (f" ({len(groups) - materials} node groups, {materials} materials)" if materials else "")
    what = "node groups and materials" if materials else "node groups"
    return (f"# {lib['name']}\n\n"
            f"- Author: {lib['author']}\n"
            f"- Homepage: <{lib['homepage']}>\n"
            f"- Version: {lib['version']}\n"
            f"- License: {lib['license']} ([LICENSE](LICENSE))\n"
            f"- Groups: {count}\n\n"
            f"These texts are the {what} of {lib['name']} read as Base Node text by Base Node {base_node}"
            f" on Blender {blender}, a derived work of {lib['name']} under its license, {lib['license']}.\n")


def write_library(name, texts, base_node, blender):
    """Write corpus/v1/<name>/: `texts` is {group: text}. Files of groups no longer there go."""
    lib = manifest_of(name)
    here = V1 / name
    here.mkdir(parents=True, exist_ok=True)
    names = file_names(texts)
    for old in here.glob("*.bn"):
        if old.name not in names.values():
            old.unlink()
    for group, text in texts.items():
        (here / names[group]).write_bytes(text.encode())
    (here / "README.md").write_bytes(readme(lib, list(texts), base_node, blender).encode())
    (here / "LICENSE").write_bytes(license_file(lib["license"]).read_bytes())
    return here


def libraries():
    """[(name, manifest)] of the libraries the corpus has a folder of."""
    return [(m.stem, tomllib.loads(m.read_text(encoding="utf-8"))) for m in sorted(LIBRARIES.glob("*.toml"))
            if (V1 / m.stem).is_dir()]


def index():
    """corpus/README.md: what the corpus is, and its libraries."""
    rows = []
    total = 0
    for name, lib in libraries():
        n = len(list((V1 / name).glob("*.bn")))
        total += n
        cells = [f"[`{name}/`](v1/{name}/)", f"[{lib['name']}]({lib['homepage']})", lib["author"],
                 lib["version"], lib["license"], str(n)]
        rows.append("| " + " | ".join(c.replace("|", "\\|") for c in cells) + " |")
    return f"""# Corpus

The node groups of third-party libraries, read as `.bn` text: a reference corpus of version 1 of the
language. Each `v1/<library>/` holds a library's groups (and materials), one `<group>.bn` per group,
as the reader of Blender 5.3 writes them (the latest Blender that Base Node promises), with a
`README.md` naming the library and the `LICENSE` of the library.

These texts are derived works of their libraries. The MIT and Apache-2.0 licenses of this repository
do not cover them: each folder is under the license of its library, in its `LICENSE` file
(`licenses/` holds those texts once).

The `.blend` files of the libraries stay the source of the non-regression tests
(`addon/tests/test_libraries.py`): the texts are kept for what they are, the groups
of real libraries written in the language. `test_libraries.py` writes them with the baselines
(`BASE_NODE_UPDATE_FIXTURES=1` on the Blender of the baselines); `python/tests/test_corpus.py` checks
that each one parses, fits the target `blender@5.3` and has the hash its baseline records, and
`rust/tests/corpus.rs` that the Rust parser reads it and the formatter prints it unchanged
(`rust/tests/corpus.rs`: that it fits `blender@5.3` in Rust too).

`v1/` is frozen at the final 1.0.0. A later version of the language must still read every text of it.

| Folder | Library | Author | Version | License | Groups |
|---|---|---|---|---|---|
{chr(10).join(rows)}

{total} groups. Thanks to the authors of these libraries for publishing them.
"""


def write_index():
    (CORPUS / "README.md").write_bytes(index().encode())
    return CORPUS / "README.md"


def baseline_groups(name):
    """{group: record} of a library's main baseline."""
    return json.loads((LIBRARIES / f"{name}.baseline.json").read_text(encoding="utf-8"))["groups"]
