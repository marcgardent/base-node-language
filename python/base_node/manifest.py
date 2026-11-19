"""The manifest of the standard library, read from its modules.

`stdlib/manifest.json` holds what is the library's (`stdlib_version`, `edition`, `description`);
each module says the rest in the head of its `.bn`:

    // @module keying
    // @version 0.12.0
    // @target blender-compositor
    // @edition 2026
    // @pack compositing-pro
    // @description Compositor keying tools after Nuke: ...

A module with a `@pack` is pro and in that paid pack, one without is free; its dependencies are
the modules its `use` lines name. So adding a module adds its file and edits no shared list.
`manifest(stdlib_dir)` gives the manifest as one object, the modules by name.
"""

from __future__ import annotations

import json
from pathlib import Path

from .header import directives
from .parser import parse


def module_entry(path):
    """The manifest entry of the module at `path`, from its head and its `use` lines."""
    path = Path(path)
    source = path.read_text(encoding="utf-8")
    head = {name: value for name, value, _line, _col in directives(source)}
    entry = {
        "name": head.get("module", path.stem),
        "version": head.get("version", ""),
        "edition": head.get("edition", ""),
        "tier": "pro" if head.get("pack") else "free",
    }
    if head.get("pack"):
        entry["pack"] = head["pack"]
    entry["targets"] = [t.strip() for t in head.get("target", "").split(",") if t.strip()]
    entry["file"] = path.name
    entry["dependencies"] = sorted({u.name for u in parse(source, path.name).uses})
    entry["description"] = head.get("description", "")
    return entry


def manifest(stdlib_dir):
    """stdlib/manifest.json with its `modules`: one entry per `.bn` of `stdlib_dir`, by name."""
    stdlib_dir = Path(stdlib_dir)
    data = json.loads((stdlib_dir / "manifest.json").read_text(encoding="utf-8"))
    data["modules"] = {p.stem: module_entry(p) for p in sorted(stdlib_dir.glob("*.bn"))}
    return data
