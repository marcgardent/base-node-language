"""Build examples/tutorials/srt_subtitles/srt_subtitles.bn in Blender and check that it reads an .srt file.

  blender -b --factory-startup --python-exit-code 1 --python examples/srt_subtitles_check.py

1. The groups go through the regression tests' round trip (tests/test_libraries.py).
2. An .srt written with Unix line ends, then with Windows ones and a byte order mark: at each
   time, the cue read must be the one of the file (its start, its end and its text), or none.
3. "srt subtitles" draws a text while a cue shows and nothing between two cues.
4. Its material is the text's, and another font draws other shapes.
"""

import sys
import tempfile
from pathlib import Path

import bpy

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "addon" / "tests"))
import test_libraries  # noqa: E402  (loads the extension as `base_node`)

import base_node  # noqa: E402

SOURCE = (ROOT / "examples" / "tutorials" / "srt_subtitles" / "srt_subtitles.bn").read_text(encoding="utf-8")
# The cue as a point: x its start, y its end, z the length of its text
PROBE = """
geometry graph probe(file: String, time: Float) -> Geometry {
  cue = srt_cue(ImportText(path: file), time)
  return Points(position: CombineXYZ(x: cue.start, y: cue.end, z: StringLength(string: cue.text)))
}
"""

CUES = [
    (1.0, 4.2, "Bonjour, bienvenue dans ce tutoriel."),
    (4.5, 7.8, "Aujourd'hui : Geometry Nodes.\nSur deux lignes, c'est permis."),
    (3725.25, 3726.0, "<i>Été, à une heure passée.</i>"),
]


def srt(cues, eol="\n"):
    def stamp(t):
        ms = round(t * 1000)
        return f"{ms // 3600000:02}:{ms // 60000 % 60:02}:{ms // 1000 % 60:02},{ms % 1000:03}"
    blocks = [f"{i}\n{stamp(a)} --> {stamp(b)}\n{text}" for i, (a, b, text) in enumerate(cues, 1)]
    return ("\n\n".join(blocks) + "\n\n\n").replace("\n", eol)


def check_round_trip():
    blend = Path(tempfile.mkdtemp()) / "srt.blend"
    bpy.data.libraries.write(str(blend), {g for g in bpy.data.node_groups})
    records, _ = test_libraries.round_trip(blend)
    for name, record in sorted(records.items()):
        print(f"round trip {name}: {record['status']}{' ' + str(record.get('on', '')) if 'on' in record else ''}")
    assert all(r["status"] == "ok" for r in records.values()), records


def set_input(mod, name, value):
    for item in mod.node_group.interface.items_tree:
        if item.item_type == "SOCKET" and item.in_out == "INPUT" and item.name == name:
            getattr(mod.properties.inputs, item.identifier).value = value


def new_object(group):
    obj = bpy.data.objects.new(group, bpy.data.meshes.new(group))
    bpy.context.scene.collection.objects.link(obj)
    obj.modifiers.new("GN", "NODES").node_group = bpy.data.node_groups[group]
    return obj


def evaluated(obj):
    obj.update_tag()
    return obj.evaluated_get(bpy.context.evaluated_depsgraph_get()).evaluated_geometry()


def check_cues(path):
    obj = new_object("probe")
    set_input(obj.modifiers[0], "file", str(path))
    for time in (0.0, 1.0, 2.5, 4.3, 4.5, 7.79, 7.8, 100.0, 3725.5):
        set_input(obj.modifiers[0], "time", time)
        geometry = evaluated(obj)
        x, y, z = geometry.pointcloud.attributes["position"].data[0].vector
        want = next(((a, b, len(t)) for a, b, t in CUES if a <= time < b), (0.0, 0.0, 0))
        print(f"  {time:8.2f} s: start {x:.3f}, end {y:.3f}, {int(z)} characters; want {want}")
        assert abs(x - want[0]) < 1e-3 and abs(y - want[1]) < 1e-3 and round(z) == want[2], (time, want)
    bpy.data.objects.remove(obj)


def check_drawing(path):
    scene = bpy.context.scene
    obj = new_object("srt subtitles")
    set_input(obj.modifiers[0], "file", str(path))
    for seconds, shown in ((2.0, True), (4.3, False), (5.0, True)):
        scene.frame_set(round(seconds * scene.render.fps / scene.render.fps_base))
        geometry = evaluated(obj)  # kept: its mesh lives as long as it does
        faces = len(geometry.mesh.polygons) if geometry.mesh else 0
        print(f"  frame {scene.frame_current}: {faces} faces")
        assert (faces > 0) == shown, (seconds, faces)
    bpy.data.objects.remove(obj)


def check_material_and_font(path):
    scene = bpy.context.scene
    obj = new_object("srt subtitles")
    set_input(obj.modifiers[0], "file", str(path))
    scene.frame_set(round(2.0 * scene.render.fps / scene.render.fps_base))
    mono = bpy.data.fonts.load(str(Path(bpy.utils.system_resource("DATAFILES")) / "fonts" / "DejaVuSansMono.woff2"))
    paint = bpy.data.materials.new("Subtitle paint")
    first = evaluated(obj)  # kept: its mesh lives as long as it does
    faces = len(first.mesh.polygons)
    set_input(obj.modifiers[0], "material", paint)
    set_input(obj.modifiers[0], "font", mono)
    geometry = evaluated(obj)
    print(f"  {paint.name}, {mono.name}: {len(geometry.mesh.polygons)} faces, Blender's font {faces}")
    assert [m.name for m in geometry.mesh.materials] == [paint.name], list(geometry.mesh.materials)
    assert len(geometry.mesh.polygons) not in (0, faces), faces
    bpy.data.objects.remove(obj)


def main():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    base_node.register()
    base_node.host.build_source(SOURCE, "srt_subtitles.bn")
    check_round_trip()  # it clears the groups and the objects: built again below
    base_node.host.build_source(SOURCE + PROBE, "srt_subtitles.bn")
    folder = Path(tempfile.mkdtemp())
    unix, windows = folder / "unix.srt", folder / "windows.srt"
    unix.write_text(srt(CUES), encoding="utf-8", newline="")
    windows.write_text("﻿" + srt(CUES, "\r\n"), encoding="utf-8", newline="")
    for path in (unix, windows):
        print(path.name)
        check_cues(path)
    check_drawing(unix)
    check_material_and_font(unix)
    print("srt subtitles: ok")


main()
