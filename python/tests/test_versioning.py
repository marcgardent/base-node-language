"""Tests for the versions of the core: its edition, its packages, and that it names no destination."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

from base_node import EDITION, STDLIB_VERSION, __version__
from base_node_cli.cli import main as cli_main

REPO_ROOT = Path(__file__).resolve().parents[2]


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
    """One version: the crate says it in SemVer, the Python package in its PEP 440 form."""
    version = said("rust/Cargo.toml", r'^version = "([^"]+)"')
    assert EDITION == "2026"
    assert STDLIB_VERSION == version
    assert __version__ == pep440(version)
    assert said("python/pyproject.toml", r'^version = "([^"]+)"') == __version__


def test_cli_version_flag(capsys):
    """Verify base-node --version outputs formatted edition and versions."""
    with pytest.raises(SystemExit) as exc_info:
        cli_main(["--version"], plugins=[])
    assert exc_info.value.code == 0
    captured = capsys.readouterr()
    expected = f"base-node {__version__} (Language Edition {EDITION}, Stdlib {STDLIB_VERSION})"
    assert expected in captured.out or expected in captured.err


# Words of a destination, whatever their case: the same as rust/tests/no_destination.rs
WORDS = re.compile(r"blender|NodeSocket|ShaderNode|GeometryNode|CompositorNode|base_node_|_targets"
                   r"|geometry|shader|compositor|modifier", re.IGNORECASE)


def test_core_knows_no_destination():
    """python/base_node, the core, and base_node_cli, its command line, name nothing of Blender and
    import no host library: a host adds its commands through the entry points of base_node.cli."""
    for package in ("base_node", "base_node_cli"):
        for p in sorted((REPO_ROOT / "python" / package).glob("*.py")):
            for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
                assert not WORDS.search(line.replace("base_node_cli", "")), f"{package}/{p.name}:{n}: {line.strip()}"
    code = ("import sys, base_node, base_node.manifest, base_node_cli.cli; "
            "print([m for m in sys.modules if m.startswith('base_node_') and m.split('.')[0] != 'base_node_cli'])")
    out = subprocess.run([sys.executable, "-c", code], cwd=REPO_ROOT / "python", capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "[]"


def test_the_core_names_no_plugin():
    """The core (python/, rust/, conformance/, spec/) reads and names no file of a host under plugins/:
    a checkout without plugins/ builds and passes these tests. The glue (Makefile, tools/bump.py, the CI)
    runs a plugin when the checkout has it."""
    found = []
    for folder in ("python", "rust", "conformance", "spec"):
        for p in sorted((REPO_ROOT / folder).rglob("*")):
            if p.is_file() and "target" not in p.relative_to(REPO_ROOT).parts and p.suffix in (
                    ".py", ".rs", ".toml", ".md", ".json", ".bn", ".txt"):
                for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
                    if "plugins/" in line and p.name != "test_versioning.py":
                        found.append(f"{p.relative_to(REPO_ROOT)}:{n}: {line.strip()}")
    assert not found, "\n".join(found)


def test_the_command_line_runs_without_a_plugin(tmp_path, capsys):
    """fmt, parse and ast are the core's; a command of a host is not there without its library."""
    path = tmp_path / "g.bn"
    path.write_text("geometry graph g(x: Float) -> Float {\n  return x\n}\n", encoding="utf-8")
    assert cli_main(["fmt", "--check", str(path)], plugins=[]) == 0
    assert cli_main(["parse", str(path)], plugins=[]) == 0
    assert cli_main(["ast", str(path)], plugins=[]) == 0
    capsys.readouterr()
    with pytest.raises(SystemExit):
        cli_main(["check", str(path)], plugins=[])


def test_a_plugin_adds_commands_and_options(tmp_path, capsys):
    """A plugin's extend(subparsers, commands) adds a command, and an option to fmt that writes the text."""

    class Plugin:
        @staticmethod
        def extend(subparsers, commands):
            commands["fmt"].add_argument("--upper", dest="rewrite", action="store_const",
                                         const=lambda content, p: content.upper())
            hello = subparsers.add_parser("hello")
            hello.set_defaults(func=lambda args: print("hello") or 0)

    path = tmp_path / "g.bn"
    path.write_text("x", encoding="utf-8")
    assert cli_main(["hello"], plugins=[Plugin]) == 0
    assert capsys.readouterr().out == "hello\n"
    assert cli_main(["fmt", "--upper", str(path)], plugins=[Plugin]) == 0
    assert path.read_text(encoding="utf-8") == "X"
