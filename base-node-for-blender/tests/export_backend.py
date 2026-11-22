"""Write what the reference needs from Blender: its nodes, and where each stdlib graph builds.

Run in Blender:
    blender --background --factory-startup --python-exit-code 1 \
      --python base-node-for-blender/tests/export_backend.py            # write targets/backends/blender-<x.y>*
    ... --python base-node-for-blender/tests/export_backend.py -- --check   # fail when it is not what Blender says

For each kind of tree (geometry, shader, compositor), every node the text can write: its text name,
bl_idname, Blender's label and tooltip, its settings with their values, and the sockets of a new
node (the ones a setting shows or hides aside). For each graph of the stdlib, the kinds of tree it
builds in, called from a graph of that kind, or the reason it is refused there. A module the
Blender that runs refuses (it uses a node that Blender has not) says so for each of its graphs.
The nodes go to targets/backends/blender-<x.y>.json, the graphs of each module to
targets/backends/blender-<x.y>/<module>.json: a new module adds its own file, and two branches that
each add one merge without a conflict. `python/base_node_cli/refdoc.py` reads them to write the
reference pages, without Blender.
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
from base_node.blender import BnError, compile_source, parse
from base_node.lang import ast as A
from base_node.blender.schema import key


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


def reason(error):
    """Why Blender refuses a text: its first diagnostic, the files of stdlib/ named by their name."""
    message = str(error.diagnostics[0]) if getattr(error, "diagnostics", None) else str(error)
    return message.replace(f"{STDLIB_DIR}/", "")


def builds(schema, module, graph, kind, refused=None):
    """"ok" when `graph` of `module` builds called from a `kind` graph, else why not.

    Every input is given a value of its type, so that the call needs nothing from the context.
    `refused` is why this Blender refuses the module itself, None when it builds."""
    if graph.kind == kind:
        return refused or "ok"
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
        message = message.split(": ", 1)[-1].split(" (/")[0].split(f" ({STDLIB_DIR}")[0]
        return message.replace(f"{STDLIB_DIR}/", "")
    return "ok"


def stdlib_entries(schema):
    out = {}
    for path in sorted(STDLIB_DIR.glob("*.bn")):
        module = path.stem
        source = path.read_text(encoding="utf-8")
        tree = parse(source, path.name)
        refused = None
        try:
            compile_source(source, schema, str(path), load)
        except BnError as e:
            refused = reason(e)
        out[module] = {g.name: {kind: builds(schema, module, g, kind, refused) for kind in TREE_TYPES}
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
        }
        stdlib = stdlib_entries(schema)
    version = ".".join(str(v) for v in bpy.app.version[:2])
    files = {OUT_DIR / f"blender-{version}.json": data}
    files.update({OUT_DIR / f"blender-{version}" / f"{m}.json": graphs for m, graphs in stdlib.items()})
    return files


def text(data):
    return json.dumps(data, indent=1, ensure_ascii=False, sort_keys=False) + "\n"


def main():
    check = "--check" in sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else False
    files = export()
    main_file = next(iter(files))
    modules_dir = main_file.with_suffix("")
    stale = sorted(set(modules_dir.glob("*.json")) - set(files))
    if check:
        wrong = [p for p, data in files.items() if not p.exists() or p.read_text(encoding="utf-8") != text(data)]
        if wrong or stale:
            for p in wrong:
                print(f"{p.relative_to(LIB_ROOT)} is not what Blender {bpy.app.version_string} says")
            for p in stale:
                print(f"{p.relative_to(LIB_ROOT)} is of no module of stdlib/")
            print("run `make backend` and commit what it writes")
            sys.exit(1)
        print(f"{main_file.relative_to(LIB_ROOT)} and {len(files) - 1} modules in "
              f"{modules_dir.relative_to(LIB_ROOT)}/ are up to date")
        return
    modules_dir.mkdir(parents=True, exist_ok=True)
    for p in stale:
        p.unlink()
    for p, data in files.items():
        p.write_text(text(data), encoding="utf-8")
    print(f"wrote {main_file.relative_to(LIB_ROOT)} and {len(files) - 1} modules in {modules_dir.relative_to(LIB_ROOT)}/")


main()
