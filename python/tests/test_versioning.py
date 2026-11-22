"""Tests for language, stdlib, targets, and package versioning."""

from __future__ import annotations

import io
import json
import re
from pathlib import Path
from unittest.mock import patch

import pytest

import base_node
from base_node_blender import EDITION, STDLIB_VERSION, __version__, check_targets, load_target, parse
from base_node_cli.cli import main as cli_main
from base_node.manifest import manifest as stdlib_manifest

REPO_ROOT = Path(__file__).resolve().parents[2]
STDLIB_DIR = REPO_ROOT / "stdlib"
TARGETS_DIR = REPO_ROOT / "targets"
MANIFEST_PATH = STDLIB_DIR / "manifest.json"


def pep440(semver: str) -> str:
    """The form Python gives a SemVer version: `1.0.0-rc.1` is `1.0.0rc1`."""
    m = re.fullmatch(r"(\d+\.\d+\.\d+)(?:-(alpha|beta|rc)\.(\d+))?", semver)
    assert m, f"{semver!r} is not x.y.z or x.y.z-rc.n"
    return m[1] + ({"alpha": "a", "beta": "b", "rc": "rc"}[m[2]] + m[3] if m[2] else "")


def said(path: str, pattern: str) -> str:
    """The version `path` says, read by the text around it."""
    found = re.search(pattern, (REPO_ROOT / path).read_text(encoding="utf-8"), re.MULTILINE)
    assert found, f"{path} says no version"
    return found[1]


def test_the_versions_agree():
    """One version: the stdlib, the Python package, the crates and the add-on.

    stdlib/manifest.json says it in SemVer; Python takes its PEP 440 form."""
    version = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))["stdlib_version"]
    assert EDITION == "2026"
    assert STDLIB_VERSION == version
    assert __version__ == pep440(version)
    assert said("python/pyproject.toml", r'^version = "([^"]+)"') == __version__
    for path in ("rust/Cargo.toml", "web/Cargo.toml", "base-node-for-blender/blender_manifest.toml"):
        assert said(path, r'^version = "([^"]+)"') == version, path
    for entry in stdlib_manifest(STDLIB_DIR)["modules"].values():
        assert entry["version"] == version, entry["file"]




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
    assert {f.stem for f in files} >= {"blender", "blade"}
    variants = [TARGETS_DIR / "blender" / f"{v}.json" for v in ("cycles", "eevee", "gltf")]
    for f in files + variants:
        data = json.loads(f.read_text(encoding="utf-8"))
        assert data["name"] == f.stem
        assert "extends" not in data, f"{f.name}: a target is not defined from another"
        if f.stem == "blender":
            # Blender's has a catalog per version, blender/<x.y>.json: the lists are there, by kind of tree
            assert set(data) == {"name", "description", "lts", "promised", "variants"}
            for version in data["promised"]:
                trees = json.loads((TARGETS_DIR / "blender" / f"{version}.json").read_text(encoding="utf-8"))["trees"]
                assert all(isinstance(t[k], list) for t in trees.values() for k in ("types", "zones", "nodes"))
            continue
        assert isinstance(data["kinds"], list), f"{f.name}: kinds"
        if "without" in data:
            # A variant that only leaves nodes out says which, each with where that is said
            assert all(isinstance(source, str) and source for source in data["without"].values())
            continue
        for k in ("types", "zones", "nodes"):
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
        r"^//\s*@version\s+(?P<version>\S+)\s*\n"
        r"^//\s*@target\s+(?P<target>[\w, @.-]+?)\s*\n"
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
    """The modules of base-node-for-blender/lang/ and blender/ are relative links to those of python/base_node
    (the core) and python/base_node_blender (what is Blender's)."""
    for folder, source, expected in (("lang", "base_node", "parser.py"), ("blender", "base_node_blender", "targets.py")):
        embedded = REPO_ROOT / "base-node-for-blender" / folder
        package = REPO_ROOT / "python" / source
        linked = sorted(p.name for p in embedded.iterdir() if p.is_symlink() and p.name != "_targets")
        assert expected in linked and "cli.py" not in linked
        for name in linked:
            assert not (embedded / name).readlink().is_absolute(), f"{folder}/{name} is a relative link"
            assert (embedded / name).resolve() == (package / name).resolve(), f"{folder}/{name} links to python/{source}/{name}"
        for p in embedded.iterdir():
            if not p.is_symlink() and (package / p.name).is_file():
                assert p.read_bytes() != (package / p.name).read_bytes(), f"{folder}/{p.name}: link it to python/{source}/{p.name}"


def test_core_knows_no_destination():
    """python/base_node, the core, names nothing of Blender and imports neither its library nor the CLI."""
    import subprocess
    import sys

    core = REPO_ROOT / "python" / "base_node"
    words = re.compile(r"blender|NodeSocket|ShaderNode|GeometryNode|CompositorNode|base_node_|_targets"
                       r"|geometry|shader|compositor|modifier", re.IGNORECASE)
    for p in sorted(core.glob("*.py")):
        for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            assert not words.search(line), f"{p.name}:{n}: {line.strip()}"
    code = "import sys, base_node, base_node.manifest; print([m for m in sys.modules if m.startswith('base_node_')])"
    out = subprocess.run([sys.executable, "-c", code], cwd=REPO_ROOT / "python", capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "[]"


def test_stdlib_tiers():
    """Every module is free or pro; a pro module names its pack; a free module uses only free ones.

    This repository holds the free modules alone, so a free module that used a pro one would not
    build here.
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


def test_check_warns_of_deprecated_calls_and_passes(tmp_path, capsys):
    """`base-node check`: a call of a deprecated graph is a warning, and the file is still what it is."""
    from base_node_cli.cli import main

    old = ('geometry(deprecated: "use Grid") graph plane(size: Float) -> Geometry {\n'
           "  return Grid(size, size, 2, 2)\n}\n\n")
    path = tmp_path / "old.bn"
    path.write_text("// @target blender\n\n" + old
                    + "geometry graph field() -> Geometry {\n  return plane(1.0)\n}\n", encoding="utf-8")
    assert main(["check", str(path)]) == 0
    captured = capsys.readouterr()
    assert captured.err == "old.bn:8:10  warning: 'plane' is deprecated: use Grid\n"
    assert captured.out == f"OK (blender): {path}\n"
    # With no target promised too, and a warning does not hide an error
    path.write_text(old + "geometry graph field() -> Geometry {\n  return plane(1.0)\n}\n", encoding="utf-8")
    assert main(["check", str(path)]) == 0
    assert capsys.readouterr().err == "old.bn:6:10  warning: 'plane' is deprecated: use Grid\n"
    assert main(["check", "--target", "blender gltf", str(path)]) == 1
    assert "warning: 'plane' is deprecated: use Grid" in capsys.readouterr().err
    # The other commands read and write the mark as any setting
    assert main(["fmt", "--check", str(path)]) == 0 and main(["parse", str(path)]) == 0


def test_check_says_how_a_zone_of_before_is_written(tmp_path, capsys):
    """`base-node check`: a zone in the spelling of before is an error that says what to write, when
    the name is the zone's (nothing else in the text has it)."""
    from base_node_cli.cli import main

    def text(body, before=""):
        return before + "geometry graph g(n: Int) -> Float {\n" + body + "  return 1.0\n}\n"

    path = tmp_path / "old.bn"
    cases = [
        ("  r = repeat(n, v: 1.0) {\n    return (v: v * 2.0)\n  }\n",
         "old.bn:2:7  repeat takes a body after '->': r = repeat(10, state: start) -> { … }"),
        ("  s = simulate(v: 1.0) {\n    return (v: v)\n  }\n",
         "old.bn:2:7  simulate takes a body after '->': s = simulate(state: start) -> { … }"),
        ("  f = closure(x: Float) -> Float {\n    return x\n  }\n",
         "old.bn:2:7  closure(…) is now written as a graph with no name: f = graph(x: Float) -> Float { … }"),
    ]
    for body, message in cases:
        for target in ([], ["--target", "blender"]):
            path.write_text(text(body), encoding="utf-8")
            assert main(["check", *target, str(path)]) == 1
            captured = capsys.readouterr()
            assert captured.err == f"Error in '{path}':\n{message}\n" and captured.out == ""
    # A graph of the text of that name is what the call calls: the targets answer
    mine = "geometry graph repeat(n: Int, v: Float) -> Float {\n  return v\n}\n\n"
    path.write_text(text("  r = repeat(n, v: 1.0)\n", mine), encoding="utf-8")
    assert main(["check", "--target", "blender", str(path)]) == 0
    # The new spelling passes
    path.write_text(text("  r = repeat(n, v: 1.0) -> {\n    return (v: v * 2.0)\n  }\n"), encoding="utf-8")
    assert main(["check", "--target", "blender", str(path)]) == 0
