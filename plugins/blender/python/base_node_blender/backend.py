"""Blender's nodes without Blender: a Schema read from what Blender reported of them.

targets/backends/blender-<x.y>.json holds, for each node of each kind of tree, its settings, the inputs
and outputs of a new node, and the inputs each setting that changes them makes (`variants`), as
addon/tests/export_backend.py writes them from Blender. That is enough to find the
input a value goes to, and so to name the inputs of a text on a command line (naming.name_inputs);
the add-on asks Blender itself (host/schema.py).
"""

import json
import re

from .schema import NodeSpec, Prop, Socket, snake
from .targets import _dir


def versions():
    """The versions of Blender a backend was written for, the oldest first: ["5.2", "5.3"]."""
    root = _dir()
    found = root.glob("backends/blender-*.json") if root is not None else []
    names = [re.fullmatch(r"blender-(\d+\.\d+)", p.stem) for p in found]
    return sorted((m.group(1) for m in names if m), key=lambda v: tuple(int(x) for x in v.split(".")))


class BackendSchema:
    """The Schema of one version of Blender, the newest without one."""

    def __init__(self, version=None):
        known = versions()
        if not known:
            raise FileNotFoundError("no targets/backends/blender-<x.y>.json: run `make backend`")
        if version is None:
            version = known[-1]
        if version not in known:
            raise ValueError(f"no backend for Blender {version}; backends: {', '.join(known)}")
        self.version = version
        data = json.loads((_dir() / "backends" / f"blender-{version}.json").read_text(encoding="utf-8"))
        self.entries = {kind: {n["name"]: n for n in nodes} for kind, nodes in data["kinds"].items()}
        self.specs = {}

    def node(self, kind, name):
        entry = self.entries.get(kind, {}).get(name)
        if entry is None:
            return None
        if (kind, name) not in self.specs:
            props = {s["name"]: Prop(s["name"], s["kind"], tuple(i["value"] for i in s.get("items", ())),
                                     s.get("datablock", "")) for s in entry["settings"]}
            data = {d["name"]: Prop(d["name"], d["kind"], tuple(d.get("channels", ()))) for d in entry.get("data", ())}
            self.specs[(kind, name)] = NodeSpec(name, entry["bl_idname"], props, data)
        return self.specs[(kind, name)]

    def node_names(self, kind):
        return sorted(self.entries.get(kind, {}))

    def sockets(self, kind, spec, props):
        entry = self.entries[kind][spec.name]
        variant = _variant(entry, props) or {}
        return _sockets(variant.get("inputs", entry["inputs"])), _sockets(variant.get("outputs", entry["outputs"]))

    def groups(self, kind):
        return {}


def _variant(entry, props):
    """The variant of `entry` that `props` make, None for a new node's sockets.

    A variant is written for the settings that differ from a new node's, with the sockets that differ:
    every combination of the settings that change them, and none for those that give a new node's
    sockets. When the combinations were too many to list (`variants_each`), each setting alone was:
    the variant of the most settings among those given."""
    defaults = {s["name"]: s.get("default") for s in entry["settings"]}
    variants = entry.get("variants", ())
    relevant = {n for v in variants for n in v["when"]}
    given = {n: v for n, v in props.items() if n in relevant and v != defaults.get(n)}
    if not given:
        return None
    best = None
    for v in variants:
        when = v["when"]
        if when == given:
            return v
        if entry.get("variants_each") and all(given.get(n) == x for n, x in when.items()) and (best is None or len(when) > len(best["when"])):
            best = v
    return best


def _sockets(items):
    """Sockets from the JSON of a backend: its `key` is how text names each, its identifier when two
    share a name or a key of its own (Mix Shader's `a` and `b`); `identifier` Blender's, when another."""
    names = [i["name"] for i in items]
    out = []
    for i in items:
        k, identifier = i["key"], i.get("identifier", i["key"])
        default = i.get("default")
        size = len(default) if isinstance(default, list) else 0
        # Keyed by its identifier when its name repeats, else by a key of its own when not its name's
        alias = k if k != snake(i["name"]) and (k != identifier or names.count(i["name"]) == 1) else ""
        out.append(Socket(i["name"], identifier, i["type"], bool(i.get("multi_input")), size, alias))
    return out
