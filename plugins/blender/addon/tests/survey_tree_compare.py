"""Survey: compare each group of the third-party libraries with the group built back from its text,
on Blender's own data (`tree_compare.py`), and write what differs. Not a test: it fails on nothing.

The round trip is `test_libraries.round_trip`, its evaluations and renders left out (the comparison
is of the data, and they take most of the time): each group is read as text, its original renamed
`original <name>`, the text built back beside it. Then every original is compared with its rebuilt
tree, the groups their group nodes call once each. Hand-made trees follow, for cases the libraries
may not hold (`CASES`).

    BASE_NODE_CACHE=<dir> blender --background --factory-startup --python-exit-code 1 \
      --python addon/tests/survey_tree_compare.py -- --out <dir> [<library> ...] [--no-cases]

writes <dir>/report.md and <dir>/differences.jsonl (one difference a line).
"""

from __future__ import annotations

import collections
import json
import math
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_libraries as TL  # noqa: E402  (loads base_node)
import tree_compare as TC  # noqa: E402

import bpy  # noqa: E402

ORIGINAL = "original "


def known_as(id):
    """The name an ID is known by on both sides: the round trip renames the originals."""
    return id.name.removeprefix(ORIGINAL)


class NoStage:
    """Stands in for test_libraries.Stage: no render."""

    def differs(self, *_args):
        return []

    def remove(self):
        pass


def round_trip_only(blend, trees):
    """test_libraries.round_trip without its evaluations nor renders: {key: record}."""
    evaluations, stage = TL.T.evaluations, TL.Stage
    TL.T.evaluations, TL.Stage = (lambda group, kinds: ()), NoStage
    try:
        records, _texts = TL.round_trip(blend, trees=trees)
    finally:
        TL.T.evaluations, TL.Stage = evaluations, stage
    return records


def pairs(records):
    """(key, original tree, rebuilt tree) of each record built back."""
    for key, r in sorted(records.items()):
        if r["status"] in ("export_error", "build_error"):
            continue
        if key.startswith(TL.MATERIAL):
            name = key.removeprefix(TL.MATERIAL)
            a, b = bpy.data.materials.get(ORIGINAL + name), bpy.data.materials.get(name)
            a, b = a and a.node_tree, b and b.node_tree
        else:
            a, b = bpy.data.node_groups.get(ORIGINAL + key), bpy.data.node_groups.get(key)
        if a is not None and b is not None:
            yield key, a, b


def jsonable(v):
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        return repr(v)
    if isinstance(v, (tuple, list)):
        return [jsonable(x) for x in v]
    if isinstance(v, (str, int, float, bool)) or v is None:
        return v
    return repr(v)


def survey_library(manifest):
    lib = TL.read_manifest(manifest)
    t0 = time.time()
    records = round_trip_only(TL.fetch(lib), lib.get("trees", ("geometry",)))
    t1 = time.time()
    c = TC.Comparator(known_as)
    found = []
    compared = 0
    try:
        for key, a, b in pairs(records):
            if (a.as_pointer(), b.as_pointer()) in c.seen:
                continue
            compared += 1
            for d in c.compare(a, b):
                found.append(dict(library=manifest.stem, group=key, **{k: jsonable(v) for k, v in vars(d).items()}))
    finally:
        c.close()
    t2 = time.time()
    statuses = collections.Counter(r["status"] for r in records.values())
    return found, {"library": manifest.stem, "groups": len(records), "compared": compared,
                   "statuses": dict(statuses), "round_trip_s": round(t1 - t0, 1), "compare_s": round(t2 - t1, 1)}


# --- Hand-made cases ---------------------------------------------------------------------------

def trip(tree, before_build=None):
    """tree -> text -> rebuilt tree: (text, rebuilt, differences, error). `before_build()` runs once
    the text is read, before it is built."""
    from base_node.host import build_source, export_tree
    from base_node.blender.schema import key

    name = tree.name
    try:
        text, _warnings = export_tree(tree)
    except Exception as e:
        return None, None, [], f"export: {TL.first_error(e)}"
    tree.name = ORIGINAL + name
    if before_build is not None:
        before_build()
    try:
        rebuilt = build_source(text, filename=f"{key(name)}.bn")[-1]
    except Exception as e:
        return text, None, [], f"build: {TL.first_error(e)}"
    return text, rebuilt, TC.compare_trees(tree, rebuilt, name=known_as), None


def geometry(name):
    t = bpy.data.node_groups.new(name, "GeometryNodeTree")
    t.interface.new_socket("Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
    t.interface.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    gi, go = t.nodes.new("NodeGroupInput"), t.nodes.new("NodeGroupOutput")
    gi.location, go.location = (-400, 0), (400, 0)
    return t, gi, go


def string_tree(name, value, node_name=None, socket_name=None):
    t, gi, go = geometry(name)
    s = t.nodes.new("GeometryNodeStoreNamedAttribute")
    s.data_type = "FLOAT"
    s.inputs["Name"].default_value = value
    if node_name is not None:
        s.name = s.label = node_name
    t.links.new(gi.outputs[0], s.inputs[0])
    t.links.new(s.outputs[0], go.inputs[0])
    if socket_name is not None:
        t.interface.new_socket(socket_name, in_out="INPUT", socket_type="NodeSocketFloat")
        t.links.new(gi.outputs[1], s.inputs["Value"])
    return t


def float_tree(name, value):
    t, gi, go = geometry(name)
    m = t.nodes.new("GeometryNodeSetPosition")
    c = t.nodes.new("ShaderNodeCombineXYZ")
    c.inputs[0].default_value = value
    t.links.new(gi.outputs[0], m.inputs[0])
    t.links.new(c.outputs[0], m.inputs["Offset"])
    t.links.new(m.outputs[0], go.inputs[0])
    return t


def two_group_inputs(name):
    t, gi, go = geometry(name)
    t.interface.new_socket("Offset", in_out="INPUT", socket_type="NodeSocketVector")
    gi2 = t.nodes.new("NodeGroupInput")
    m = t.nodes.new("GeometryNodeSetPosition")
    t.links.new(gi.outputs[0], m.inputs[0])
    t.links.new(gi2.outputs[1], m.inputs["Offset"])
    t.links.new(m.outputs[0], go.inputs[0])
    return t


def scan_settings():
    """(node with an array setting, its property), (node with a flag-set setting, its property) of a
    Geometry Nodes tree, by scanning RNA."""
    t = bpy.data.node_groups.new(".scan", "GeometryNodeTree")
    array, flags = [], []
    skip = TC.NODE_PRESENTATION | TC.NODE_FILTERED | TC.CONSTANTS | {"rna_type"}
    for name in dir(bpy.types):
        cls = getattr(bpy.types, name)
        if not (isinstance(cls, type) and issubclass(cls, bpy.types.Node)) or cls is bpy.types.Node:
            continue
        try:
            n = t.nodes.new(name)
        except RuntimeError:
            continue
        for p in n.bl_rna.properties:
            if p.identifier in skip or p.is_readonly:
                continue
            if getattr(p, "is_array", False):
                array.append((name, p.identifier))
            if p.type == "ENUM" and p.is_enum_flag:
                flags.append((name, p.identifier))
        t.nodes.remove(n)
    bpy.data.node_groups.remove(t)
    return array, flags


def setting_tree(name, idname, prop, value):
    t, gi, go = geometry(name)
    n = t.nodes.new(idname)
    setattr(n, prop, value)
    # Fed into the output when it can be, else left unconnected (the reader keeps unconnected nodes)
    geo_in = next((s for s in n.inputs if s.type == "GEOMETRY"), None)
    geo_out = next((s for s in n.outputs if s.type == "GEOMETRY"), None)
    if geo_in is not None and geo_out is not None:
        t.links.new(gi.outputs[0], geo_in)
        t.links.new(geo_out, go.inputs[0])
    else:
        t.links.new(gi.outputs[0], go.inputs[0])
    return t


def int_vector_tree(name):
    """An interface input of type Int Vector 3D. Blender 5.3 does not list it among the types of
    `new_socket`: an Int socket made one by its `bl_socket_idname`."""
    t, gi, go = geometry(name)
    item = t.interface.new_socket("Cells", in_out="INPUT", socket_type="NodeSocketInt")
    item.bl_socket_idname = "NodeSocketIntVector3D"
    item = next(i for i in t.interface.items_tree if i.item_type == "SOCKET" and i.name == "Cells")
    if hasattr(item, "default_value"):
        item.default_value = (2, 3, 4)
    t.links.new(gi.outputs[0], go.inputs[0])
    return t


def int_vector_case():
    """The integer-vector case, in another Blender: the half-made socket may bring Blender down."""
    import subprocess

    if not hasattr(bpy.types, "NodeTreeInterfaceSocketIntVector3D"):
        return {"skipped": "Blender has no integer vector socket"}
    run = subprocess.run([bpy.app.binary_path, "--background", "--factory-startup", "--python", __file__,
                          "--", "--int-vector-case"], capture_output=True, text=True)
    lines = [l for l in run.stdout.splitlines() if l.startswith("INT_VECTOR ")]
    found = json.loads(lines[-1].removeprefix("INT_VECTOR ")) if lines else {}
    crashed = run.returncode != 0 or "Writing: " in run.stdout + run.stderr
    found["note"] = (f"Blender {'crashed' if crashed else 'exited'} (code {run.returncode})"
                     + ("; " + "; ".join(sorted({l.strip() for l in (run.stdout + run.stderr).splitlines()
                                                 if "unreachable" in l or "node.cc" in l})) if crashed else ""))
    return found


def int_vector_main():
    TL.T.base_node.register()
    t = int_vector_tree("IntVector")
    item = next(i for i in t.interface.items_tree if i.item_type == "SOCKET" and i.name == "Cells")
    made = {"made": f"{item.bl_rna.identifier}, default {tuple(item.default_value)}"}
    print("INT_VECTOR " + json.dumps(made), flush=True)
    text, rebuilt, diffs, error = trip(t)
    made.update(error=error, text=text, differences=[str(d) for d in diffs],
                classes=dict(collections.Counter(d.cls for d in diffs)))
    print("INT_VECTOR " + json.dumps(made, default=repr), flush=True)


def muted_link_tree(name):
    t, gi, go = geometry(name)
    m = t.nodes.new("GeometryNodeSetPosition")
    t.links.new(gi.outputs[0], m.inputs[0])
    t.links.new(m.outputs[0], go.inputs[0])
    pos = t.nodes.new("GeometryNodeInputPosition")
    t.links.new(pos.outputs[0], m.inputs["Offset"]).is_muted = True
    return t


def muted_node_tree(name):
    t, gi, go = geometry(name)
    m = t.nodes.new("GeometryNodeSubdivideMesh")
    m.mute = True
    t.links.new(gi.outputs[0], m.inputs[0])
    t.links.new(m.outputs[0], go.inputs[0])
    return t


def unconnected_tree(name):
    t, gi, go = geometry(name)
    t.links.new(gi.outputs[0], go.inputs[0])
    v = t.nodes.new("ShaderNodeValue")
    v.outputs[0].default_value = 0.25
    m = t.nodes.new("ShaderNodeMath")
    m.operation = "POWER"
    m.inputs[1].default_value = 3.0
    t.links.new(v.outputs[0], m.inputs[0])
    return t


def stdlib_caller(name):
    """A tree calling `bias` of stdlib/math.bn, built from the module, whose group is then edited in the
    file (a Math node's operation). (caller, before_build, what was edited) or (None, None, why not).

    The round trip builds the module's group again in its place: `before_build` keeps the edited group
    aside, under the original's name, for the original caller to call."""
    from base_node.host import build_source

    src = f"use math (bias)\n\ngeometry graph {name}(x: Float) -> Float {{\n  return bias(x, 0.3)\n}}\n"
    try:
        caller = build_source(src, filename=f"{name}.bn")[-1]
    except Exception as e:
        return None, None, f"cannot build a caller of stdlib/math.bn: {TL.first_error(e)}"
    group = next(n for n in caller.nodes if n.bl_idname == "GeometryNodeGroup")
    module = group.node_tree
    math = next((n for n in module.nodes if n.bl_idname == "ShaderNodeMath"), None)
    if math is None:
        return None, None, f"no Math node in {module.name}"
    before = math.operation
    math.operation = "MAXIMUM" if before != "MAXIMUM" else "MINIMUM"

    def keep():
        kept = module.copy()
        kept.name = ORIGINAL + module.name
        group.node_tree = kept

    return caller, keep, (f"{module.name} (module {module.get('base_node_module')!r}): "
                          f"{math.name}.operation {before} -> {math.operation}")


def cases():
    """[(case, what the comparator says)]."""
    out = []

    def run(case, tree, note="", before_build=None):
        if tree is None:
            out.append((case, {"skipped": note}))
            return
        text, rebuilt, diffs, error = trip(tree, before_build)
        out.append((case, {"error": error, "differences": [str(d) for d in diffs],
                           "classes": dict(collections.Counter(d.cls for d in diffs)), "note": note,
                           "text": text}))

    run('string with " in a String input', string_tree("Quote", 'say "hi"'))
    run("string with a newline in a String input", string_tree("Newline", "two\nlines"))
    run('node name with " and a newline', string_tree("NodeName", "a", node_name='my "node"\nsecond'))
    run('interface socket name with " and a newline', string_tree("SocketName", "a", socket_name='Size "x"\nline'))
    run("float input at its default + 5e-7", float_tree("Plus5e7", 0.0 + 5e-7))
    run("float input at 1 + 5e-7", float_tree("One5e7", 1.0 + 5e-7))
    run("inf in a Float input", float_tree("Inf", math.inf))
    run("-inf in a Float input", float_tree("MinusInf", -math.inf))
    run("nan in a Float input", float_tree("NaN", math.nan))
    run("-0.0 in a Float input", float_tree("MinusZero", -0.0))
    run("two Group Input nodes", two_group_inputs("TwoInputs"))
    array, flags = scan_settings()
    for idname, prop in array:
        n = bpy.data.node_groups.new(".probe", "GeometryNodeTree").nodes.new(idname)
        current = tuple(getattr(n, prop))
        bpy.data.node_groups.remove(n.id_data)
        value = tuple(not v if isinstance(v, bool) else v + 1 for v in current)
        run(f"array setting {idname}.{prop} = {value}", setting_tree(f"Array {idname}", idname, prop, value))
    for idname, prop in flags:
        n = bpy.data.node_groups.new(".probe", "GeometryNodeTree").nodes.new(idname)
        items = [i.identifier for i in n.bl_rna.properties[prop].enum_items]
        current = set(getattr(n, prop))
        bpy.data.node_groups.remove(n.id_data)
        value = set(items) - current or {items[0]}
        run(f"flag-set setting {idname}.{prop} = {sorted(value)}", setting_tree(f"Flags {idname}", idname, prop, value))
    if not array:
        out.append(("array setting", {"skipped": "no Geometry Nodes node has an array setting in this Blender"}))
    if not flags:
        out.append(("flag-set setting", {"skipped": "no Geometry Nodes node has a flag-set setting in this Blender"}))
    out.append(("interface socket of integer-vector type (3D)", int_vector_case()))
    run("a muted link", muted_link_tree("MutedLink"))
    run("a muted node", muted_node_tree("MutedNode"))
    run("an unconnected node (Value -> Math, fed nowhere)", unconnected_tree("Unconnected"))
    caller, keep, note = stdlib_caller("UsesMath")
    run("a stdlib module group edited in the file, its caller round-tripped", caller, note, keep)
    return out


# --- Report -----------------------------------------------------------------------------------

def norm(prop):
    """A property without its indices: the place a kind of difference is at."""
    return re.sub(r"\[\d+\]", "[]", prop)


FILTERS = f"""Not compared, each for its reason (see the comments in `tree_compare.py`):

- of every struct: `rna_type`, and the constants of the class (`{', '.join(sorted(TC.CONSTANTS))}`);
- of a node: `dimensions` (the size it was drawn at, 0 in the background), `internal_links` (made by
  Blender from the type and sockets of a muted node; `mute` is compared), `active_item` (the item
  `active_index` points to);
- of a socket: `{', '.join(sorted(TC.SOCKET_FILTERED))}` (its node; whether it is linked, which the links
  say; what Blender infers at each update and does not store), the `identifier` of the sockets of a
  Group Input, Group Output or group node (made from the interface's, compared as
  `interface-identifier`), the value of a linked input (not read), the value of an output but of
  `{', '.join(sorted(TC.VALUE_OUTPUTS))}` (never read);
- of an interface item: `{', '.join(sorted(TC.INTERFACE_FILTERED))}` (its place: the items are aligned in
  order, with the path of their panel);
- of the tree: `{', '.join(sorted(TC.TREE_FILTERED))}` (runtime state of any ID, a hash of the whole,
  what is compared on its own, the add-on's own pointer to its text);
- custom properties whose key starts with `{TC.OWN_IDPROPS}` (the builder's bookkeeping: source line,
  module, aliases…);
- Blender's own font under another name (`Bfont Regular.001` and `Bfont Regular` are one font);
  animation data that animates nothing (no action, driver nor NLA track) counts as none.

Matching: frames and reroutes are out of the graph (a link through reroutes is one link), every Group
Input is one node (their number is compared: `node-merged`), and a node is matched by its type and its
place among the links (Weisfeiler-Lehman colours on both trees at once, then from matched neighbours,
then the most alike in settings). Blind spots: two nodes nothing tells apart (same type, links and
settings) may be paired crosswise, which shows only as presentation; a merge is seen between nodes of
the same settings only; a node made into another type (an unconnected Math made a Value) is a node
missing and a node extra; nothing below RNA is compared (driver expressions beyond their paths, image
pixels, the contents of a text datablock).
"""


def report(found, libraries, case_results, seconds, out):
    by_class = collections.defaultdict(list)
    for d in found:
        by_class[d["cls"]].append(d)
    lines = [f"# Tree comparison survey (Blender {bpy.app.version_string})", "",
             "Original tree vs tree rebuilt from its text, on Blender's data (`tests/tree_compare.py`).", ""]
    total_groups = sum(x["groups"] for x in libraries)
    lines += [f"{total_groups} groups in {len(libraries)} libraries, {sum(x['compared'] for x in libraries)} "
              f"compared at the top (the groups they call, once each); {len(found)} differences; "
              f"{seconds:.0f} s in all.", "",
              "| Library | Groups | Statuses | Round trip (s) | Compare (s) |", "|---|---|---|---|---|"]
    for x in libraries:
        lines.append(f"| {x['library']} | {x['groups']} | {x['statuses']} | {x['round_trip_s']} | {x['compare_s']} |")
    lines += ["", "## Classes, the most serious first", "",
              "Groups: the trees the differences are in (a group called by another is compared once).", "",
              "| Class | Differences | Groups | Libraries |", "|---|---|---|---|"]
    order = sorted(by_class, key=lambda c: (TC.severity(c), c))
    for cls in order:
        ds = by_class[cls]
        lines.append(f"| `{cls}` | {len(ds)} | {len({(d['library'], d['tree']) for d in ds})} | "
                     f"{len({d['library'] for d in ds})} |")
    for cls in order:
        ds = by_class[cls]
        lines += ["", f"### `{cls}` ({len(ds)})", ""]
        where = collections.Counter((d["node_type"], norm(d["prop"])) for d in ds)
        lines.append("| Node type | Property | Count |")
        lines.append("|---|---|---|")
        for (t, p), n in where.most_common(25):
            lines.append(f"| {t or '(tree)'} | `{p}` | {n} |")
        if len(where) > 25:
            lines.append(f"| … | {len(where) - 25} more | |")
        lines += ["", "Examples:", ""]
        # Two examples, of two places when there are two, of two libraries when there are two
        picked = []
        for d in ds:
            if len(picked) == 2:
                break
            if picked and len(where) > 1 and (d["node_type"], norm(d["prop"])) == \
                    (picked[0]["node_type"], norm(picked[0]["prop"])):
                continue
            picked.append(d)
        for d in ds:
            if len(picked) == 2:
                break
            if d not in picked:
                picked.append(d)
        for d in picked:
            a, b = (repr(v) if len(repr(v)) <= 300 else repr(v)[:300] + "…" for v in (d["a"], d["b"]))
            lines.append(f"- {d['library']} / {d['tree']} / {d['node'] or '(tree)'} / `{d['prop']}`: "
                         f"`{a}` -> `{b}`")
    if case_results:
        lines += ["", "## Hand-made cases", ""]
        for case, r in case_results:
            lines.append(f"### {case}")
            lines.append("")
            if "skipped" in r:
                lines.append(f"Skipped: {r['skipped']}")
            else:
                if r.get("made"):
                    lines.append(f"Made: {r['made']}")
                if r.get("note"):
                    lines.append(r["note"])
                if r.get("error"):
                    lines.append(f"Error: `{r['error']}`")
                classes = r.get("classes") or {}
                serious = {c: n for c, n in classes.items() if not c.startswith("presentation")}
                look = sum(n for c, n in classes.items() if c.startswith("presentation"))
                lines.append(f"Classes: {serious or 'none'}" + (f", and {look} of presentation" if look else ""))
                for d in [d for d in r.get("differences", []) if not d.startswith("[presentation")][:12]:
                    lines.append(f"- `{d}`")
            lines.append("")
    lines += ["## What the comparator leaves out", "", FILTERS]
    (out / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    args = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    if "--int-vector-case" in args:
        int_vector_main()
        return
    out = Path(args[args.index("--out") + 1]) if "--out" in args else Path.cwd()
    names = [a for i, a in enumerate(args) if not a.startswith("--") and (i == 0 or args[i - 1] != "--out")]
    out.mkdir(parents=True, exist_ok=True)
    TL.T.base_node.register()
    start = time.time()
    manifests = sorted(TL.LIBRARIES.glob("*.toml"))
    if names:
        manifests = [m for m in manifests if m.stem in names]
    found, libraries = [], []
    for m in manifests:
        print(f"-> {m.stem}", flush=True)
        f, info = survey_library(m)
        print(f"   {info}; {len(f)} differences", flush=True)
        found += f
        libraries.append(info)
    with open(out / "differences.jsonl", "w", encoding="utf-8") as fh:
        for d in found:
            fh.write(json.dumps(d, ensure_ascii=False) + "\n")
    case_results = []
    if "--no-cases" not in args:
        for g in list(bpy.data.node_groups):
            bpy.data.node_groups.remove(g)
        case_results = cases()
        (out / "cases.json").write_text(json.dumps(case_results, indent=1, ensure_ascii=False, default=repr),
                                        encoding="utf-8")
    seconds = time.time() - start
    report(found, libraries, case_results, seconds, out)
    print(f"report: {out / 'report.md'} ({seconds:.0f} s)")


if __name__ == "__main__":
    main()
