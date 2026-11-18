"""The gltf target against Blender's glTF exporter.

Each case of conformance/gltf-cases.json is built into a material with the add-on, exported to a
.glb with `bpy.ops.export_scene.gltf`, and its glTF read back: what the rules accept must reach
the material (a texture, a factor, an extension, an alpha mode), what they refuse must not.
test_extension.py runs it too; alone:

    blender --background --factory-startup --python-exit-code 1 --python base-node-for-blender/tests/test_gltf_export.py
"""

from __future__ import annotations

import importlib.util
import json
import struct
import sys
import tempfile
import traceback
from pathlib import Path

EXT_DIR = Path(__file__).resolve().parents[1]
CASES = EXT_DIR.parent / "conformance" / "gltf-cases.json"

if "base_node" not in sys.modules:
    _spec = importlib.util.spec_from_file_location(
        "base_node", EXT_DIR / "__init__.py", submodule_search_locations=[str(EXT_DIR)]
    )
    _module = importlib.util.module_from_spec(_spec)
    sys.modules["base_node"] = _module
    _spec.loader.exec_module(_module)

import bpy


def case_text(case):
    """The text of a case: a whole text, or the body of a material of its name."""
    if "text" in case:
        return case["text"].replace("NAME", case["name"])
    body = "".join(f"  {line}\n" for line in case["body"].split("\n"))
    return f"shader(material: true) graph {case['name']}() -> ({case.get('outputs', 'surface: Shader')}) {{\n{body}}}\n"


def read_glb(path):
    """The JSON chunk of a .glb."""
    data = Path(path).read_bytes()
    size = struct.unpack_from("<I", data, 12)[0]
    return json.loads(data[20:20 + size])


def export(name, folder):
    """The glTF of a plane with a color attribute and the material `name`: (file, material, attributes)."""
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj)
    bpy.ops.mesh.primitive_plane_add()
    plane = bpy.context.active_object
    plane.data.materials.append(bpy.data.materials[name])
    plane.data.color_attributes.new("Col", "FLOAT_COLOR", "POINT")
    path = Path(folder) / f"{name}.glb"
    bpy.ops.export_scene.gltf(filepath=str(path), export_format="GLB", use_selection=True,
                              export_all_vertex_colors=False)
    gltf = read_glb(path)
    return gltf, gltf["materials"][0], gltf["meshes"][0]["primitives"][0]["attributes"]


def close(a, b):
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(close(x, y) for x, y in zip(a, b))
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(a - b) <= 1e-4
    return a == b


def holds(check, gltf, material, attributes):
    """Whether the exported glTF shows `check`: `path`, `!path` or `path=value`."""
    absent = check.startswith("!")
    path, _, want = check.lstrip("!").partition("=")
    head, _, rest = path.partition(".")
    if head == "mesh":
        here = attributes
    elif head == "sampler":
        here = (gltf.get("samplers") or [{}])[0]
    elif head == "json":
        here = gltf
    else:
        here, rest = material, path
    for step in rest.split("."):
        if isinstance(here, list) and step.isdigit() and int(step) < len(here):
            here = here[int(step)]
        elif isinstance(here, dict) and step in here:
            here = here[step]
        else:
            return absent
    if absent:
        return False
    if not want:
        return True
    try:
        want = json.loads(want)
    except ValueError:  # a word: MASK, BLEND
        pass
    return close(here, want)


def test_gltf_export():
    """Every case of conformance/gltf-cases.json: the rules' verdict, and what the exporter writes."""
    print("-> Test: the gltf target against Blender's glTF exporter...")
    from base_node.host import build_source
    from base_node.lang import parse
    from base_node.lang.targets import check_target

    corpus = json.loads(CASES.read_text(encoding="utf-8"))
    for name in corpus["images"]:
        if name not in bpy.data.images:
            image = bpy.data.images.new(name, 8, 8)
            image.pixels = [0.5] * (8 * 8 * 4)
            image.pack()
    wrong = []
    with tempfile.TemporaryDirectory() as folder:
        for case in corpus["cases"]:
            text = case_text(case)
            issues = [i.name for i in check_target(parse(text, f"{case['name']}.bn"), "gltf")]
            if issues != case["issues"]:
                wrong.append(f"{case['name']}: the rules say {issues}, the case {case['issues']}")
            if not case.get("gltf"):
                continue
            build_source(text, f"{case['name']}.bn")
            gltf, material, attributes = export(case["name"], folder)
            verdict = "accepted" if not case["issues"] else "refused"
            for check in case["gltf"]:
                if not holds(check, gltf, material, attributes):
                    wrong.append(f"{case['name']} ({verdict}): the glTF does not show {check}: "
                                 f"{json.dumps(material)} {list(attributes)} {gltf.get('samplers')}")
    assert not wrong, "\n".join(wrong)
    print(f"   ✓ {len(corpus['cases'])} cases: the rules take what the exporter reads, and refuse what it loses")


def main():
    sys.modules["base_node"].register()
    try:
        test_gltf_export()
    except Exception:
        traceback.print_exc()
        print("\n❌ FAILED: the gltf export")
        sys.exit(1)
    print("\n✅ The gltf export passed")


if __name__ == "__main__":
    main()
