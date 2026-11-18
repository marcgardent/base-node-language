"""Write what the reference needs from Blender: its nodes, and where each stdlib graph builds.

Run in Blender:
    blender --background --factory-startup --python-exit-code 1 \
      --python base-node-for-blender/tests/export_backend.py            # write targets/backends/blender-<x.y>.json
    ... --python base-node-for-blender/tests/export_backend.py -- --check   # fail when it is not what Blender says

For each kind of tree (geometry, shader, compositor), every node the text can write: its text name,
bl_idname, Blender's label and tooltip, its settings with their values, and the sockets of a new
node (the ones a setting shows or hides aside). For each graph of the stdlib, the kinds of tree it
builds in, called from a graph of that kind, or the reason it is refused there.
`python/base_node/refdoc.py` reads it to write the reference pages, without Blender.
"""

from __future__ import annotations

import importlib.util
import json
import math
import sys
from pathlib import Path

EXT_DIR = Path(__file__).resolve().parents[1]
LIB_ROOT = EXT_DIR.parent
STDLIB_DIR = LIB_ROOT / "stdlib"
OUT_DIR = LIB_ROOT / "targets" / "backends"

_spec = importlib.util.spec_from_file_location(
    "base_node", EXT_DIR / "__init__.py", submodule_search_locations=[str(EXT_DIR)]
)
base_node = importlib.util.module_from_spec(_spec)
sys.modules["base_node"] = base_node
_spec.loader.exec_module(base_node)

import bpy
from base_node.host.schema import TREE_TYPES, BlenderSchema
from base_node.lang import BnError, compile_source, parse
from base_node.lang import ast as A
from base_node.lang.schema import key


def plain(value):
    """A default value as JSON: rounded floats, lists for vectors and colors."""
    if isinstance(value, float):
        return None if math.isinf(value) or math.isnan(value) else round(value, 6)
    if isinstance(value, (tuple, list)):
        return [plain(v) for v in value]
    if isinstance(value, (bool, int, str)) or value is None:
        return value
    return str(value)


def socket_list(sockets, values=None):
    """[{name, key, type, …}] of a node's sockets, keyed as the text names them."""
    keys = [s.key for s in sockets]
    out = []
    for s, k in zip(sockets, keys):
        item = {"name": s.name, "key": k if keys.count(k) == 1 else s.identifier, "type": s.type}
        if s.multi_input:
            item["multi_input"] = True
        if values is not None and s.identifier in values and values[s.identifier] is not None:
            item["default"] = plain(values[s.identifier])
        out.append(item)
    return out


def node_entry(schema, kind, spec):
    cls = getattr(bpy.types, spec.bl_idname)
    rna = cls.bl_rna
    inputs, outputs, values, prop_values = schema.fresh(kind, spec, {})
    settings = []
    for name, prop in spec.props.items():
        rp = rna.properties.get(name)
        item = {"name": name, "kind": prop.kind}
        if rp is not None and rp.description:
            item["description"] = rp.description
        if prop.items:
            labels = {i.identifier: i.name for i in rp.enum_items} if rp is not None else {}
            item["items"] = [{"value": v, "label": labels.get(v, v)} for v in prop.items]
        if prop.datablock:
            item["datablock"] = prop.datablock
        if prop_values.get(name) is not None:
            item["default"] = plain(prop_values[name])
        settings.append(item)
    entry = {
        "name": spec.name,
        "bl_idname": spec.bl_idname,
        "label": rna.name,
        "description": rna.description,
        "settings": settings,
        "inputs": socket_list(inputs, values),
        "outputs": socket_list(outputs),
    }
    if spec.data:
        entry["data"] = [{"name": n, "kind": p.kind, **({"channels": list(p.items)} if p.items else {})}
                         for n, p in spec.data.items()]
    return entry


LIT = {"Float": "0.5", "Int": "1", "Bool": "true", "Vector": "(0.1, 0.2, 0.3)",
       "Color": "(0.5, 0.5, 0.5, 1.0)", "String": '"a"'}


def load(name, source):
    path = STDLIB_DIR / f"{name}.bn"
    if not path.exists():
        raise LookupError(f"no module '{name}'")
    return path.read_text(encoding="utf-8"), str(path)


def builds(schema, module, graph, kind):
    """"ok" when `graph` of `module` builds called from a `kind` graph, else why not.

    Every input is given a value of its type, so that the call needs nothing from the context."""
    if graph.kind == kind:
        return "ok"
    args = []
    for p in A.flatten(graph.params):
        if p.type not in LIT:
            return f"an input of type {p.type}"
        args.append(f"{p.key}: {LIT[p.type]}")
    out = graph.outputs[0]
    call = f"{key(graph.name)}({', '.join(args)})" + ("" if graph.single_output else f".{out.key}")
    src = f"use {module} ({key(graph.name)})\n\n{kind} graph probe() -> (v: {out.type}) {{\n  return (v: {call})\n}}\n"
    try:
        compile_source(src, schema, "probe.bn", load)
    except BnError as e:
        message = str(e.diagnostics[0]) if getattr(e, "diagnostics", None) else str(e)
        message = message.split("  ", 1)[-1]
        # The reason only: the graph and the tree are said by the table
        return message.split(": ", 1)[-1].split(" (/")[0].split(f" ({STDLIB_DIR}")[0]
    return "ok"


def stdlib_entries(schema):
    manifest = json.loads((STDLIB_DIR / "manifest.json").read_text(encoding="utf-8"))
    out = {}
    for module, info in manifest["modules"].items():
        tree = parse((STDLIB_DIR / info["file"]).read_text(encoding="utf-8"), info["file"])
        out[module] = {g.name: {kind: builds(schema, module, g, kind) for kind in TREE_TYPES}
                       for g in tree.graphs}
    return out


def export():
    with BlenderSchema() as schema:
        kinds = {}
        for kind in TREE_TYPES:
            specs = schema.specs(kind)[0]
            kinds[kind] = [node_entry(schema, kind, specs[name]) for name in sorted(specs)]
        data = {
            "blender": bpy.app.version_string,
            "generated_by": "base-node-for-blender/tests/export_backend.py",
            "kinds": kinds,
            "stdlib": stdlib_entries(schema),
        }
    version = ".".join(str(v) for v in bpy.app.version[:2])
    return OUT_DIR / f"blender-{version}.json", json.dumps(data, indent=1, ensure_ascii=False, sort_keys=False) + "\n"


def main():
    check = "--check" in sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else False
    path, text = export()
    if check:
        if not path.exists() or path.read_text(encoding="utf-8") != text:
            print(f"{path.relative_to(LIB_ROOT)} is not what Blender {bpy.app.version_string} says: "
                  "run base-node-for-blender/tests/export_backend.py in Blender and commit it")
            sys.exit(1)
        print(f"{path.relative_to(LIB_ROOT)} is up to date")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    print(f"wrote {path.relative_to(LIB_ROOT)}")


main()
