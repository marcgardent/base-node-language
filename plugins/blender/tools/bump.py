#!/usr/bin/env python3
"""Write the version of Base Node for Blender everywhere it is written, or check that those places agree.

    python3 tools/bump.py 1.0.0-rc.1                   write it (make bump VERSION=1.0.0-rc.1)
    python3 tools/bump.py 1.0.0-rc.1 --core 1.0.0-rc.1 and the version of the core it needs
    python3 tools/bump.py --check                      fail unless every place holds the version of stdlib/manifest.json
    python3 tools/bump.py --check --core-dir ../..     and the core it needs is that checkout's
    python3 tools/bump.py 1.0.0-rc.1 --archive         write it, then build site/extensions/ again with Blender

Run in this folder. The version is SemVer, `x.y.z` or `x.y.z-alpha.n`, `x.y.z-beta.n`, `x.y.z-rc.n`. It
is written as it is but where Python reads it (`version` of pyproject.toml), which takes its PEP 440
form: `1.0.0-rc.1` is `1.0.0rc1` there. Cargo and Blender's manifest take SemVer and refuse the PEP 440
form.

This folder has its own version, and needs a version of the core of the language (base-node): the
places of PLACES hold the one, those of CORE_PLACES the other. Without --core, a version written is
needed of the core too. A place that must hold its version and does not stops the run, so a file
moved or reworded is seen and not skipped. Versions of anything else (dependencies, the third-party
libraries of the tests) match none of these texts and are left alone. The Cargo.lock of the
workspace is not tracked; when there is one, the entries of its crates are written too.

Without --archive the add-on zip of site/extensions/ is only renamed: it still holds the add-on of
the version before, and --check says so until it is built again.
"""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
import re
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SEMVER = re.compile(r"(\d+)\.(\d+)\.(\d+)(?:-(alpha|beta|rc)\.(\d+))?")
PEP_LETTERS = {"alpha": "a", "beta": "b", "rc": "rc"}
# A version in either form, as the places hold it
V = r"(?P<v>\d+\.\d+\.\d+(?:-(?:alpha|beta|rc)\.\d+|(?:a|b|rc)\d+)?)"
EACH, ONE, ANY = "each", "one", "any"

# (files, text around the version with {V} for it, form, need)
#   files: a pattern over the tracked paths of this folder (`*` crosses `/`), links left out
#   need:  EACH, every file holds it; ONE, a file at least does; ANY, no file has to
PLACES = [
    ("stdlib/manifest.json", r'"stdlib_version": "{V}"', "semver", EACH),
    ("stdlib/*.bn", r"^// @version {V}$", "semver", EACH),
    ("python/pyproject.toml", r'^version = "{V}"', "pep440", EACH),
    ("python/*.py", r"^    // @version {V}$", "semver", ANY),
    # Rust: the crates' own version (a dependency's is not at the start of a line)
    ("*/Cargo.toml", r'^version = "{V}"', "semver", EACH),
    # Blender
    ("addon/blender_manifest.toml", r'^version = "{V}"', "semver", EACH),
    ("site/extensions/index.json", r'"version": "{V}"', "semver", EACH),
    ("site/extensions/index.json", r'"archive_url": "\./base_node-{V}\.zip"', "semver", EACH),
    # Site and documents
    ("site/index.html", r"<span>\(\.bn\) v{V}</span>", "semver", EACH),
    ("site/*.html", r"<span>\(\.bn\) v{V}</span>", "semver", ANY),
    ("README.md", r"dist/base_node-{V}\.zip", "semver", EACH),
    ("spec/blender.md", r"\b\w+@{V}", "semver", EACH),
    ("spec/blender.md", r"Python: base-node-blender {V} ", "pep440", EACH),
    ("spec/blender.md", r"Rust:   base-node-blender {V} ", "semver", EACH),
    ("spec/blender.md", r"Blender Extension: {V} ", "semver", EACH),
    ("spec/blender.md", r'"stdlib_version": "{V}"', "semver", EACH),
    ("spec/blender.md", r'^  "version": "{V}"', "semver", EACH),
    ("spec/blender.md", r"^// @version {V}$", "semver", EACH),
    ("spec/blender.md", r"\| PEP 440 \(`{V}`\)", "pep440", EACH),
    ("spec/blender.md", r"\| SemVer \(`{V}`\)", "semver", EACH),
]
# The version of the core this folder needs: the dependency of each build, the one place each names it
CORE_PLACES = [
    ("python/pyproject.toml", r'"base-node=={V}"', "pep440", EACH),
    ("Cargo.toml", r'^base-node = \{ path = "[^"]*", version = "={V}" \}', "semver", EACH),
]
# Never read: versions of others
SKIP = ("addon/tests/libraries/",)
EXTENSIONS = "site/extensions"


def forms(version: str) -> dict[str, str]:
    """{"semver": …, "pep440": …} of a SemVer `version`, or stop: it is not one this project writes."""
    m = SEMVER.fullmatch(version)
    if not m:
        raise SystemExit(f"{version!r} is not x.y.z, x.y.z-alpha.n, x.y.z-beta.n or x.y.z-rc.n")
    core = ".".join(str(int(n)) for n in m.group(1, 2, 3))
    if m.group(4) is None:
        return {"semver": core, "pep440": core}
    n = int(m.group(5))
    return {"semver": f"{core}-{m.group(4)}.{n}", "pep440": f"{core}{PEP_LETTERS[m.group(4)]}{n}"}


def tracked(root: Path) -> list[str]:
    out = subprocess.run(["git", "ls-files", "-z"], cwd=root, check=True, capture_output=True).stdout
    paths = [p for p in out.decode().split("\0") if p and not p.startswith(SKIP)]
    return [p for p in paths if not (root / p).is_symlink() and (root / p).is_file()]


def current(root: Path) -> str:
    """The version this folder is at: `stdlib_version` of stdlib/manifest.json."""
    return json.loads((root / "stdlib" / "manifest.json").read_text(encoding="utf-8"))["stdlib_version"]


def pad_boxes(before: str, after: str) -> str:
    """Keep the right edge of a drawn box (`│ … │`) where it was when a version changed length."""
    lines = []
    for old, new in zip(before.split("\n"), after.split("\n")):
        if new != old and new.endswith("│"):
            body = new[:-1].rstrip(" ")
            new = body + " " * max(1, len(old) - 1 - len(body)) + "│"
        lines.append(new)
    return "\n".join(lines)


def lock_places(root: Path, paths: list[str]) -> list[tuple[str, str, str, str]]:
    """The entries of this folder's own crates in the Cargo.lock of its workspace (untracked)."""
    names = []
    for p in (p for p in paths if fnmatch.fnmatch(p, "*/Cargo.toml")):
        m = re.search(r'(?m)^\[package\]\n(?:.*\n)*?name = "([^"]+)"', (root / p).read_text(encoding="utf-8"))
        if m:
            names.append(re.escape(m.group(1)))
    if not names or not (root / "Cargo.lock").is_file():
        return []
    return [("Cargo.lock", r'^name = "(?:%s)"\nversion = "{V}"' % "|".join(names), "semver", EACH)]


def scan(root: Path, version: str, write: bool, core: str | None = None) -> tuple[list[str], list[str]]:
    """(problems, files written): the places that do not hold `version`, or the places of the core
    that do not hold `core` (default: `version`), written if `write`."""
    paths = tracked(root)
    texts: dict[str, str] = {}
    problems: list[str] = []
    places = [(p, version) for p in PLACES + lock_places(root, paths)] + [(p, core or version) for p in CORE_PLACES]
    for (pattern, around, form, need), wanted in places:
        want = forms(wanted)
        rx = re.compile(around.replace("{V}", V), re.MULTILINE)
        files = [p for p in paths if fnmatch.fnmatch(p, pattern)] or ([pattern] if (root / pattern).is_file() else [])
        hits = 0
        for path in files:
            try:
                text = texts.setdefault(path, (root / path).read_text(encoding="utf-8"))
            except UnicodeDecodeError:
                continue
            found = list(rx.finditer(text))
            hits += len(found)
            if not found and need == EACH:
                problems.append(f"{path}: no version found (expected the text /{around}/)")
            for m in reversed(found):
                if m.group("v") == want[form]:
                    continue
                if write:
                    text = text[:m.start("v")] + want[form] + text[m.end("v"):]
                else:
                    line = text.count("\n", 0, m.start("v")) + 1
                    problems.append(f"{path}:{line}: {m.group('v')}, expected {want[form]}")
            texts[path] = text
        if not files and need != ANY:
            problems.append(f"{pattern}: no such tracked file")
        elif not hits and need == ONE:
            problems.append(f"{pattern}: no file holds a version (expected the text /{around}/)")
    written = []
    if write and not problems:
        for path, text in texts.items():
            before = (root / path).read_text(encoding="utf-8")
            if text != before:
                (root / path).write_text(pad_boxes(before, text), encoding="utf-8")
                written.append(path)
    return problems, written


def archive_problems(root: Path, version: str) -> list[str]:
    """What is wrong between site/extensions/index.json and the add-on zip it names."""
    semver = forms(version)["semver"]
    entry = json.loads((root / EXTENSIONS / "index.json").read_text(encoding="utf-8"))["data"][0]
    path = root / EXTENSIONS / entry["archive_url"]
    name = f"{EXTENSIONS}/{path.name}"
    if not path.is_file():
        return [f"{name}: named by {EXTENSIONS}/index.json, and missing"]
    problems = []
    data = path.read_bytes()
    if entry["archive_size"] != len(data) or entry["archive_hash"] != "sha256:" + hashlib.sha256(data).hexdigest():
        problems.append(f"{name}: not the size and hash {EXTENSIONS}/index.json says")
    with zipfile.ZipFile(path) as z:
        inside = re.search(r'(?m)^version = "([^"]+)"', z.read("blender_manifest.toml").decode("utf-8"))
    if not inside or inside.group(1) != semver:
        problems.append(f"{name}: holds the add-on of {inside.group(1) if inside else '?'}, expected {semver}: "
                        f"build it again (python3 tools/bump.py {semver} --archive)")
    return problems


def rename_archive(root: Path, version: str) -> list[str]:
    """Give the add-on zip the name index.json now says, when it is the only zip there."""
    target = root / EXTENSIONS / f"base_node-{forms(version)['semver']}.zip"
    zips = sorted((root / EXTENSIONS).glob("base_node-*.zip"))
    if target.exists() or len(zips) != 1:
        return []
    zips[0].rename(target)
    return [f"{EXTENSIONS}/{zips[0].name} -> {target.name}"]


def build_archive(root: Path) -> None:
    """Build the add-on zip and its index into site/extensions/ with Blender (BLENDER, default `blender`):
    `make extension`, which embeds the core of the Makefile's CORE."""
    blender = os.environ.get("BLENDER", "blender")
    out = root / EXTENSIONS
    for old in out.glob("base_node-*.zip"):
        old.unlink()
    subprocess.run(["make", "--no-print-directory", "-C", str(root), "extension", f"DIST={out}", f"BLENDER={blender}"],
                   check=True)
    subprocess.run([blender, "--command", "extension", "server-generate", f"--repo-dir={out}"], check=True)


def core_problems(core_dir: Path, version: str) -> list[str]:
    """What is wrong between the version of the core this folder needs and the checkout at `core_dir`."""
    cargo = core_dir / "rust" / "Cargo.toml"
    if not cargo.is_file():
        return [f"{core_dir}: no checkout of the core (rust/Cargo.toml)"]
    there = re.search(r'(?m)^version = "([^"]+)"', cargo.read_text(encoding="utf-8"))
    there = there.group(1) if there else "?"
    return [] if there == forms(version)["semver"] else [f"needs the core {version}, the checkout {core_dir} is {there}"]


def needed_core(root: Path) -> str:
    """The version of the core this folder needs, as its Cargo.toml says it."""
    m = re.search(r'(?m)^base-node = \{ path = "[^"]*", version = "=([^"]+)" \}', (root / "Cargo.toml").read_text(encoding="utf-8"))
    return m.group(1) if m else "?"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("version", nargs="?", help="x.y.z or x.y.z-rc.n (with --check: default, the stdlib's)")
    ap.add_argument("--core", help="the version of the core it needs (default: the version written; with "
                                   "--check: that of Cargo.toml)")
    ap.add_argument("--core-dir", type=Path, help="with --check: the checkout of the core, whose version it must be")
    ap.add_argument("--check", action="store_true", help="write nothing; fail if a place holds another version")
    ap.add_argument("--archive", action="store_true", help="build site/extensions/ again with Blender")
    ap.add_argument("--root", type=Path, default=ROOT, help=argparse.SUPPRESS)
    a = ap.parse_args(argv)
    root = a.root.resolve()
    if a.check:
        version = a.version or current(root)
        core = a.core or needed_core(root)
        problems = scan(root, version, write=False, core=core)[0]
        problems += archive_problems(root, version)
        if a.core_dir is not None:
            problems += core_problems(a.core_dir.resolve(), core)
        if problems:
            print(f"Not at {version} (core {core}) everywhere:", *problems, sep="\n  ", file=sys.stderr)
            return 1
        print(f"{version} everywhere, the core {core}")
        return 0
    if not a.version:
        ap.error("a version is needed: python3 tools/bump.py x.y.z")
    problems, written = scan(root, a.version, write=True, core=a.core)
    if problems:
        print("Nothing written:", *problems, sep="\n  ", file=sys.stderr)
        return 1
    written += rename_archive(root, a.version)
    if a.archive:
        build_archive(root)
    for line in written:
        print(f"  {line}")
    want = forms(a.version)
    python = "" if want["pep440"] == want["semver"] else f" ({want['pep440']} for Python)"
    print(f"{want['semver']}{python}, the core {a.core or a.version}: {len(written)} files written" if written
          else f"{want['semver']}: already there")
    for problem in archive_problems(root, a.version):
        print(f"To do: {problem}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
