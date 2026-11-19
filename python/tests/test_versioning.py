"""Tests for language, stdlib, targets, and package versioning."""

from __future__ import annotations

import io
import json
import re
from pathlib import Path
from unittest.mock import patch

import pytest

import base_node
from base_node import EDITION, STDLIB_VERSION, __version__, check_targets, load_target, parse
from base_node.cli import main as cli_main
from base_node.manifest import manifest as stdlib_manifest

REPO_ROOT = Path(__file__).resolve().parents[2]
STDLIB_DIR = REPO_ROOT / "stdlib"
TARGETS_DIR = REPO_ROOT / "targets"
MANIFEST_PATH = STDLIB_DIR / "manifest.json"


def test_package_version_constants():
    """Verify package version constants are defined and follow expected formats."""
    assert __version__ == "0.12.0"
    assert EDITION == "2026"
    assert STDLIB_VERSION == "0.12.0"


def test_cli_version_flag(capsys):
    """Verify base-node --version outputs formatted edition and versions."""
    with pytest.raises(SystemExit) as exc_info:
        cli_main(["--version"])
    assert exc_info.value.code == 0
    captured = capsys.readouterr()
    expected = f"base-node {__version__} (Language Edition {EDITION}, Stdlib {STDLIB_VERSION})"
    assert expected in captured.out or expected in captured.err


def test_targets_have_their_fields():
    """Every target file names itself and lists what it accepts; none extends another."""
    files = list(TARGETS_DIR.glob("*.json"))
    assert {f.stem for f in files} >= {"blender-geometry", "blender-gp", "blender-shader", "blender-compositor",
                                       "gltf", "blade"}
    for f in files:
        data = json.loads(f.read_text(encoding="utf-8"))
        assert data["name"] == f.stem
        assert "extends" not in data, f"{f.name}: a target is not defined from another"
        for k in ("kinds", "types", "zones", "nodes"):
            assert isinstance(data[k], list), f"{f.name}: {k}"


def test_stdlib_manifest_structure():
    """Verify stdlib/manifest.json conforms to the manifest contract.

    The file holds what is the library's; its modules are read from their heads (base_node.manifest),
    so that adding a module edits no shared list.
    """
    assert MANIFEST_PATH.exists(), f"Missing {MANIFEST_PATH}"
    written = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    assert "modules" not in written, "a module says its entry in its own head, not in stdlib/manifest.json"

    manifest = stdlib_manifest(STDLIB_DIR)
    assert manifest.get("stdlib_version") == STDLIB_VERSION
    assert manifest.get("edition") == EDITION
    assert len(manifest["modules"]) >= 5
    for name, entry in manifest["modules"].items():
        assert entry["description"], f"{name}: its head has no @description"


def test_stdlib_modules_match_manifest_and_headers():
    """Verify that every stdlib file has matching manifest entries and header annotations."""
    modules = stdlib_manifest(STDLIB_DIR)["modules"]

    bn_files = {p.stem: p for p in STDLIB_DIR.glob("*.bn")}

    # 1. Manifest and files on disk are 1:1
    assert set(modules.keys()) == set(bn_files.keys()), (
        f"Manifest modules {set(modules.keys())} do not match files on disk {set(bn_files.keys())}"
    )

    header_re = re.compile(
        r"^//\s*@module\s+(?P<module>\w+)\s*\n"
        r"^//\s*@version\s+(?P<version>[\d\.]+)\s*\n"
        r"^//\s*@target\s+(?P<target>[\w, -]+?)\s*\n"
        r"^//\s*@edition\s+(?P<edition>\w+)",
        re.MULTILINE,
    )

    for mod_name, entry in modules.items():
        file_path = bn_files[mod_name]
        text = file_path.read_text(encoding="utf-8")

        # 2. Header annotations match manifest entry
        match = header_re.search(text)
        assert match is not None, f"Module {mod_name} ({file_path}) is missing required header annotations"

        header_data = match.groupdict()
        assert header_data["module"] == mod_name, f"{mod_name}: header module mismatch"
        assert header_data["version"] == entry["version"], f"{mod_name}: header version mismatch"
        promised = [t.strip() for t in header_data["target"].split(",")]
        assert promised == entry["targets"], f"{mod_name}: header targets mismatch"
        assert header_data["edition"] == entry["edition"], f"{mod_name}: header edition mismatch"

        # 3. The targets promised exist, and the module keeps its promise
        for t in entry["targets"]:
            assert load_target(t).name == t
        ast = parse(text, file_path.name)
        assert len(ast.graphs) > 0
        issues = check_targets(ast, entry["targets"])
        assert issues == [], f"{mod_name} is outside {entry['targets']}: {[str(i) for i in issues]}"


def test_blender_extension_bundles_the_stdlib():
    """The Blender extension's stdlib/ is a relative link in git to the repository's."""
    bundled = REPO_ROOT / "base-node-for-blender" / "stdlib"
    assert bundled.is_symlink() and not bundled.readlink().is_absolute(), "link base-node-for-blender/stdlib to ../stdlib"
    assert bundled.resolve() == STDLIB_DIR.resolve()


def test_blender_extension_links_the_identical_modules():
    """The modules of base-node-for-blender/lang/ that are python/base_node's are relative links to them."""
    lang = REPO_ROOT / "base-node-for-blender" / "lang"
    package = REPO_ROOT / "python" / "base_node"
    linked = sorted(p.name for p in lang.iterdir() if p.is_symlink() and p.name != "_targets")
    assert "targets.py" in linked and "cli.py" not in linked
    for name in linked:
        assert not (lang / name).readlink().is_absolute(), f"lang/{name} is a relative link"
        assert (lang / name).resolve() == (package / name).resolve(), f"lang/{name} links to python/base_node/{name}"
    for p in lang.iterdir():
        if not p.is_symlink() and (package / p.name).is_file():
            assert p.read_bytes() != (package / p.name).read_bytes(), f"lang/{p.name}: link it to python/base_node/{p.name}"


def test_stdlib_tiers():
    """Every module is free or pro; a pro module names its pack; a free module uses only free ones.

    The public mirror (studio/export_public.py) keeps the free modules alone, so a free module that
    used a pro one would not build there.
    """
    modules = stdlib_manifest(STDLIB_DIR)["modules"]
    for name, entry in modules.items():
        assert entry.get("tier") in ("free", "pro"), f"{name}: tier"
        if entry["tier"] == "pro":
            assert entry.get("pack"), f"{name}: a pro module names its pack"
        else:
            assert "pack" not in entry, f"{name}: a free module is in no pack"
            for dep in entry["dependencies"]:
                assert modules[dep]["tier"] == "free", f"free module {name} uses pro module {dep}"
