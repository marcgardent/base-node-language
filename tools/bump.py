#!/usr/bin/env python3
"""Write the version of the core of Base Node everywhere it is written, or check that those places agree.

    python3 tools/bump.py 1.0.0-rc.1            write it (make bump VERSION=1.0.0-rc.1)
    python3 tools/bump.py --check               fail unless every place holds the version of rust/Cargo.toml
    python3 tools/bump.py --check 1.0.0-rc.1    fail unless every place holds that version

The version is SemVer, `x.y.z` or `x.y.z-alpha.n`, `x.y.z-beta.n`, `x.y.z-rc.n`. It is written as it is
but where Python reads it (`version` of pyproject.toml, `__version__`), which takes its PEP 440
form: `1.0.0-rc.1` is `1.0.0rc1` there. Cargo refuses the PEP 440 form.

The places are PLACES below: a set of tracked files of the core, and the text around the version in
them. A place that must hold the version and does not stops the run, so a file moved or reworded is
seen and not skipped. Versions of anything else (dependencies) match none of these texts and are left
alone. A Cargo.lock beside a Cargo.toml is not tracked; when there is one, the entries of the core's
own crate are written too.

A host library has its own version, and says the version of the core it needs: its own tools write
both.
"""

from __future__ import annotations

import argparse
import fnmatch
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SEMVER = re.compile(r"(\d+)\.(\d+)\.(\d+)(?:-(alpha|beta|rc)\.(\d+))?")
PEP_LETTERS = {"alpha": "a", "beta": "b", "rc": "rc"}
# A version in either form, as the places hold it
V = r"(?P<v>\d+\.\d+\.\d+(?:-(?:alpha|beta|rc)\.\d+|(?:a|b|rc)\d+)?)"
EACH, ONE, ANY = "each", "one", "any"

# (files, text around the version with {V} for it, form, need)
#   files: a pattern over the tracked paths (`*` crosses `/`), links left out
#   need:  EACH, every file holds it; ONE, a file at least does; ANY, no file has to
PLACES = [
    # Python: wherever a package says its version, so that a package split in several is followed
    ("python/*.py", r'^__version__ = "{V}"', "pep440", ONE),
    ("python/pyproject.toml", r'^version = "{V}"', "pep440", EACH),
    # Rust: the crate's own version (a dependency's is not at the start of a line); VERSION of
    # rust/src/lib.rs is read from Cargo.toml
    ("rust/Cargo.toml", r'^version = "{V}"', "semver", EACH),
    # Documents
    ("spec/reference.md", r"Specification Version {V} ", "semver", EACH),
    ("spec/versioning.md", r"Python: base-node {V} ", "pep440", EACH),
    ("spec/versioning.md", r"Rust:   base-node {V} ", "semver", EACH),
    ("spec/versioning.md", r"\*\*Current status\*\*: Version `{V}`", "semver", EACH),
    ("spec/versioning.md", r"\| PEP 440 \(`{V}`\)", "pep440", EACH),
    ("spec/versioning.md", r"\| SemVer \(`{V}`\)", "semver", EACH),
    ("spec/versioning.md", r"^base-node {V} \(Language Edition", "pep440", EACH),
]


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
    paths = [p for p in out.decode().split("\0") if p]
    return [p for p in paths if not (root / p).is_symlink() and (root / p).is_file()]


def current(root: Path) -> str:
    """The version the core is at: that of its crate, rust/Cargo.toml."""
    return re.search(r'(?m)^version = "([^"]+)"', (root / "rust" / "Cargo.toml").read_text(encoding="utf-8"))[1]


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
    """The entries of the repository's own crates in the Cargo.lock files there are (untracked)."""
    manifests = [p for p in paths if fnmatch.fnmatch(p, "*/Cargo.toml")]
    names = []
    for p in manifests:
        m = re.search(r'(?m)^\[package\]\n(?:.*\n)*?name = "([^"]+)"', (root / p).read_text(encoding="utf-8"))
        if m:
            names.append(re.escape(m.group(1)))
    if not names:
        return []
    text = r'^name = "(?:%s)"\nversion = "{V}"' % "|".join(names)
    locks = [str(Path(p).with_name("Cargo.lock")) for p in manifests]
    return [(lock, text, "semver", EACH) for lock in locks if (root / lock).is_file()]


def scan(root: Path, version: str, write: bool) -> tuple[list[str], list[str]]:
    """(problems, files written): the places that do not hold `version`, written if `write`."""
    want = forms(version)
    paths = tracked(root)
    texts: dict[str, str] = {}
    problems: list[str] = []
    for pattern, around, form, need in PLACES + lock_places(root, paths):
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


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("version", nargs="?", help="x.y.z or x.y.z-rc.n (with --check: default, the core's)")
    ap.add_argument("--check", action="store_true", help="write nothing; fail if a place holds another version")
    ap.add_argument("--root", type=Path, default=ROOT, help=argparse.SUPPRESS)
    a = ap.parse_args(argv)
    root = a.root.resolve()
    if a.check:
        version = a.version or current(root)
        problems = scan(root, version, write=False)[0]
        if problems:
            print(f"Not at {version} everywhere:", *problems, sep="\n  ", file=sys.stderr)
            return 1
        print(f"{version} everywhere")
        return 0
    if not a.version:
        ap.error("a version is needed: python3 tools/bump.py x.y.z")
    problems, written = scan(root, a.version, write=True)
    if problems:
        print("Nothing written:", *problems, sep="\n  ", file=sys.stderr)
        return 1
    for line in written:
        print(f"  {line}")
    want = forms(a.version)
    python = "" if want["pep440"] == want["semver"] else f" ({want['pep440']} for Python)"
    print(f"{want['semver']}{python}: {len(written)} files written" if written
          else f"{want['semver']}: already there")
    return 0


if __name__ == "__main__":
    sys.exit(main())
