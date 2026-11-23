"""The reference corpus, corpus/v1/: the groups of the third-party libraries as the reader of Blender
writes them (addon/tests/library_corpus.py). Each text parses, fits the target of
the Blender it was read with, and is the text its library's baseline hashes; each folder's README and
LICENSE are what its manifest says. No Blender."""

import importlib.util
import json
import re
from pathlib import Path

import pytest

from base_node_blender import check_target, parse

pytest.importorskip("tomllib")  # The manifests are TOML, which Python reads from 3.11 as Blender's does

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "library_corpus", ROOT / "addon" / "tests" / "library_corpus.py")
corpus = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(corpus)

LIBRARIES = sorted(m.stem for m in corpus.LIBRARIES.glob("*.toml"))


def test_a_folder_per_library():
    assert sorted(p.name for p in corpus.V1.iterdir() if p.is_dir()) == LIBRARIES


def test_index_is_the_manifests():
    assert (corpus.CORPUS / "README.md").read_text(encoding="utf-8") == corpus.index()


@pytest.mark.parametrize("name", LIBRARIES)
def test_library(name):
    folder = corpus.V1 / name
    records = {g: r for g, r in corpus.baseline_groups(name).items() if "text" in r}
    names = corpus.file_names(records)
    assert sorted(p.name for p in folder.glob("*.bn")) == sorted(names.values())

    blender = json.loads((corpus.LIBRARIES / f"{name}.baseline.json").read_text(encoding="utf-8"))["blender"]
    target = "blender@" + ".".join(blender.split(".")[:2])
    wrong = []
    for group, file in names.items():
        text = (folder / file).read_bytes().decode()
        if corpus.text_hash(text) != records[group]["text"]:
            wrong.append(f"{file}: not the text {name}.baseline.json hashes")
            continue
        issues = check_target(parse(text, file), target)
        wrong += [f"{file}: {i}" for i in issues]
    assert not wrong, "\n".join(wrong)

    readme = (folder / "README.md").read_text(encoding="utf-8")
    base_node = re.search(r"by Base Node (\S+) on Blender", readme)
    assert base_node, readme
    lib = corpus.manifest_of(name)
    assert readme == corpus.readme(lib, list(records), base_node[1], blender)
    assert (folder / "LICENSE").read_bytes() == corpus.license_file(lib["license"]).read_bytes()
