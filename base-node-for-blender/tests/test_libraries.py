"""Non-regression tests on third-party libraries of node groups.

Each `tests/libraries/<name>.toml` names a .blend: in the repository (`file`), or fetched at a fixed
version (`url`, and `member` when it lies in a .zip), checked by its `sha256`; or, with a `[generate]`
table, made by an extension's Python (`url` and `sha256` of its .zip; see `generate_library.py`, run in
another Blender with a throwaway user profile); or it is one Blender ships (`bundled`). Every Geometry
Nodes group of it (its shader groups, materials and compositor groups too, when its `trees` say so) is
read as .bn text, built back from that text, read again and evaluated (a shader tree: rendered, a
compositor group: applied to a render, see `Stage`) beside the original,
(a difference in a kind its `[blender_quirks]` table names for a group is kept, not failed: Blender
itself evaluates the rebuilt tree otherwise), except in the kinds of evaluation its manifest's
`[nondeterministic]` table names for a group: there
the original itself does not give twice the same geometry.
What happens to each group is kept in `tests/libraries/<name>.baseline.json`: its status, the first
error, the warnings and a hash of its text. The test fails when that changes, for better or worse.

Each promised version of Blender runs the libraries. The baseline is that of the Blender it names
(`"blender"`); where another version reads a library otherwise, its own record is beside it,
`<name>.baseline-<x.y>.json`, and that Blender is compared with it. A manifest may say what differs
for one version in a `[blender."<x.y>"]` table (the `sha256` of a file Blender ships), and the oldest
Blender that opens the library, `blender_min = "5.3"`: an older one skips it, and says so.

Run in Blender via:
    blender --background --factory-startup --python-exit-code 1 \
      --python base-node-for-blender/tests/test_libraries.py [-- <name> ...]

When the change is wanted (a fix, a reader that writes otherwise), write the baselines again and review
their diff: BASE_NODE_UPDATE_FIXTURES=1. The texts of the last run are kept in the cache
($BASE_NODE_CACHE, ~/.cache/base-node by default) under texts/<name>, those of the run before under
texts/<name>.previous: `diff -r` them to read what changed. Run with the Blender of `<name>.baseline.json`,
that writes the library's texts in the repository too, corpus/v1/<name>/ (see `library_corpus.py`).
"""

from __future__ import annotations

import collections
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
import traceback
import urllib.request
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import library_corpus  # noqa: E402
import test_extension as T  # noqa: E402  (loads base_node)
import tree_compare  # noqa: E402

import bpy  # noqa: E402

LIBRARIES = T.EXT_DIR / "tests" / "libraries"
CACHE = Path(os.environ.get("BASE_NODE_CACHE") or Path.home() / ".cache" / "base-node")
KINDS = ("mesh", "curves", "mesh caller", "mesh caller fed")
TREES = ("geometry", "shader", "material", "compositor")
# The version of Base Node that reads the libraries, as its corpus names it
VERSION = tomllib.loads((T.EXT_DIR / "blender_manifest.toml").read_text(encoding="utf-8"))["version"]
MATERIAL = "material:"  # the key of a material's record, beside those of the groups
RENDERS = ("render", "render fed")  # a material is rendered as it is, a shader group also fed
COMPOSITES = ("composite",)  # a compositor group, applied to the stage's render
ORIGINAL = "original "  # the originals keep their trees under this prefix, beside those built back
NOT_CARRIED_SEEN = collections.Counter()  # class -> the differences of it the text does not carry, in this run

class RangeFile(io.RawIOBase):
    """A remote file read by HTTP ranges: zipfile reads only the directory and the member it needs."""

    def __init__(self, url):
        self.url, self.pos = url, 0
        with urllib.request.urlopen(urllib.request.Request(url, method="HEAD")) as r:
            self.url, self.size = r.url, int(r.headers["Content-Length"])

    def seekable(self):
        return True

    def readable(self):
        return True

    def tell(self):
        return self.pos

    def seek(self, offset, whence=0):
        self.pos = (offset, self.pos + offset, self.size + offset)[whence]
        return self.pos

    def read(self, n=-1):
        end = self.size if n is None or n < 0 else min(self.size, self.pos + n)
        if end <= self.pos:
            return b""
        req = urllib.request.Request(self.url, headers={"Range": f"bytes={self.pos}-{end - 1}"})
        with urllib.request.urlopen(req) as r:
            data = r.read()
        self.pos += len(data)
        return data

    def readinto(self, b):
        data = self.read(len(b))
        b[:len(data)] = data
        return len(data)


def generate(lib, zip_path):
    """The .blend of the node groups an add-on's Python builds (the manifest's `[generate]`), made once.

    The pinned extension is installed and called in another Blender, `--factory-startup` with a throwaway
    user profile, so that neither this process nor the real profile ever runs or keeps it."""
    spec = json.dumps(lib["generate"], sort_keys=True)
    tag = hashlib.sha256(f"{lib['sha256']} {spec} {bpy.app.version_string}".encode()).hexdigest()[:16]
    path = CACHE / "libraries" / "generated" / f"{tag}.blend"
    if path.exists():
        return path
    print(f"   generating with {lib['generate']}")
    with tempfile.TemporaryDirectory(prefix="base-node-profile-") as profile:
        env = dict(os.environ, BLENDER_USER_RESOURCES=profile,
                   **{f"BLENDER_USER_{k}": str(Path(profile) / k.lower())
                      for k in ("CONFIG", "SCRIPTS", "EXTENSIONS", "DATAFILES")})
        run = subprocess.run([bpy.app.binary_path, "--background", "--factory-startup", "--python-exit-code", "1",
                              "--python", str(Path(__file__).with_name("generate_library.py")),
                              "--", str(zip_path), str(path), spec],
                             env=env, capture_output=True, text=True)
    if run.returncode or not path.exists():
        raise RuntimeError(f"generating {lib['name']} failed:\n{run.stdout[-3000:]}\n{run.stderr[-3000:]}")
    print("\n".join(line for line in run.stdout.splitlines() if line.startswith("   ")))
    return path


def fetch(lib):
    """The path of the library's .blend, fetched once into the cache and checked by its hash.

    With `[generate]`, `url` and `sha256` are those of an extension .zip whose Python builds the groups."""
    if "file" in lib:
        path = LIBRARIES / lib["file"]
    elif "bundled" in lib:
        # A file Blender ships, under its datafiles: the hash says it is the version the baseline was for
        path = Path(bpy.utils.system_resource("DATAFILES")) / lib["bundled"]
    else:
        path = CACHE / "libraries" / f"{lib['sha256']}.{'zip' if 'generate' in lib else 'blend'}"
        if not path.exists():
            # No other scheme: urllib would also open a file:// url, and http can be rewritten on the way
            assert lib["url"].startswith("https://"), f"{lib['url']}: a library is fetched by https"
            print(f"   fetching {lib['url']}" + (f" :: {lib['member']}" if "member" in lib else ""))
            if "member" in lib:
                with zipfile.ZipFile(RangeFile(lib["url"])) as z:
                    data = z.read(lib["member"])
            else:
                # extensions.blender.org refuses urllib's default User-Agent
                req = urllib.request.Request(lib["url"], headers={"User-Agent": "base-node-tests"})
                with urllib.request.urlopen(req) as r:
                    data = r.read()
            # Checked before it is kept: what does not match never enters the cache
            digest = hashlib.sha256(data).hexdigest()
            assert digest == lib["sha256"], f"{lib['url']}: sha256 {digest}, expected {lib['sha256']}"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.with_suffix(".part").write_bytes(data)
            path.with_suffix(".part").rename(path)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    assert digest == lib["sha256"], f"{path}: sha256 {digest}, expected {lib['sha256']}"
    return generate(lib, path) if "generate" in lib else path


def first_error(e):
    """The first line of an error, without its file:line:col, which move with the text."""
    line = (str(e).strip().splitlines() or [type(e).__name__])[0]
    return re.sub(r"^\S+\.bn:\d+:\d+\s+", "", line)


def warning_kind(w):
    """A warning without the group it is about nor its counts: what kind of loss it is."""
    return re.sub(r"\s*\(\d+\)$", "", w.split(": ", 1)[-1])


def outputs_named(node):
    """The names of the outputs of a group node, by which their renders are told apart: a name two
    outputs share is followed by the output's place (`Lvl 1 #2`)."""
    names = [s.name for s in node.outputs if s.enabled]
    return [n if names.count(n) == 1 else f"{n} #{i + 1}" for i, n in enumerate(names)]


class Stage:
    """A small fixed scene in which a material, or a shader group wrapped in one, is rendered.

    Cycles on the CPU: EEVEE needs a GPU context that `--background` on a CI runner may not have, and
    Cycles gives the same pixels for the same shader at a fixed seed, samples and resolution, whatever
    the number of threads. A smooth UV sphere (it has UVs and generated coordinates), lit by a sun and
    a grey world, seen by an orthographic camera: 32 x 32 pixels, 16 samples, no denoising, no
    adaptive sampling, written as 32-bit float EXR in the Standard view.

    A material is rendered as it is, through its active Material Output. A shader group is wrapped in a
    throwaway material, rendered once per output: a Shader output feeds the Surface, any other output
    the color of an Emission (a Float as grey). In "render" its inputs keep their defaults; in "render
    fed" its Vector inputs take the object's coordinates, so that a texture's pattern is drawn rather
    than its value at the origin.

    A compositor group is applied to the render of the sphere in a plain grey material, in the
    scene's own compositor, once per output: its Color inputs take the render, the others keep
    their defaults ("composite")."""

    SIZE, SAMPLES, TOLERANCE = 32, 16, 1e-4

    def __init__(self):
        import bmesh

        self.dir = Path(tempfile.mkdtemp(prefix="base-node-render-"))
        scene = self.scene = bpy.data.scenes.new(".base_node render")
        scene.render.engine = "CYCLES"
        c = scene.cycles
        c.device, c.samples, c.seed, c.use_animated_seed = "CPU", self.SAMPLES, 0, False
        c.use_adaptive_sampling, c.use_denoising = False, False
        c.max_bounces, c.diffuse_bounces, c.glossy_bounces, c.transmission_bounces = 4, 2, 2, 4
        c.volume_bounces, c.transparent_max_bounces = 1, 4
        r = scene.render
        r.resolution_x = r.resolution_y = self.SIZE
        r.resolution_percentage = 100
        r.use_persistent_data = False
        r.image_settings.file_format = "OPEN_EXR"
        r.image_settings.color_depth = "32"
        r.image_settings.exr_codec = "NONE"
        scene.view_settings.view_transform = "Standard"
        scene.view_settings.look = "None"

        world = self.world = bpy.data.worlds.new(".base_node render")
        world.color = (0.2, 0.2, 0.2)
        scene.world = world

        mesh = self.mesh = bpy.data.meshes.new(".base_node render")
        bm = bmesh.new()
        bmesh.ops.create_uvsphere(bm, u_segments=32, v_segments=16, radius=1.0, calc_uvs=True)
        bm.to_mesh(mesh)
        bm.free()
        for f in mesh.polygons:
            f.use_smooth = True
        self.obj = bpy.data.objects.new(".base_node render", mesh)
        self.obj.rotation_euler = (0.3, 0.0, 0.5)  # neither pole nor seam faces the camera
        camera = bpy.data.cameras.new(".base_node render")
        camera.type, camera.ortho_scale = "ORTHO", 2.4
        self.camera = bpy.data.objects.new(".base_node render camera", camera)
        self.camera.location, self.camera.rotation_euler = (0.0, -4.0, 0.0), (1.5707963, 0.0, 0.0)
        sun = bpy.data.lights.new(".base_node render", "SUN")
        sun.energy = 3.0
        self.sun = bpy.data.objects.new(".base_node render sun", sun)
        self.sun.rotation_euler = (0.8, 0.2, -0.6)
        for o in (self.obj, self.camera, self.sun):
            scene.collection.objects.link(o)
        scene.camera = self.camera
        self.wrapper = bpy.data.materials.new(".base_node render")
        self.plain = bpy.data.materials.new(".base_node render plain")
        self.compositor = bpy.data.node_groups.new(".base_node render", "CompositorNodeTree")
        self.compositor.interface.new_socket("Image", in_out="OUTPUT", socket_type="NodeSocketColor")

    def render(self, material, compositor=None):
        """The pixels of `material` on the sphere, through `compositor` if given: a flat list of RGBA
        floats."""
        import numpy as np

        self.mesh.materials.clear()
        self.mesh.materials.append(material)
        # The scene's stack of effects since Blender 5.3, its one compositing group before
        effects = getattr(self.scene, "compositor_effects", None)
        if effects is None:
            self.scene.compositing_node_group = compositor
        else:
            for effect in list(effects):
                effects.remove(effect)
            if compositor is not None:
                effects.new(name=compositor.name).node_group = compositor
        path = self.dir / "render.exr"
        self.scene.render.filepath = str(path)
        bpy.ops.render.render(write_still=True, scene=self.scene.name)
        image = bpy.data.images.load(str(path))
        try:
            pixels = np.empty(len(image.pixels), dtype=np.float32)
            image.pixels.foreach_get(pixels)
        finally:
            bpy.data.images.remove(image)
        return pixels

    def wrap(self, group, output, fed):
        """The throwaway material showing `output` of a node of `group`."""
        tree = self.wrapper.node_tree
        tree.nodes.clear()
        out = tree.nodes.new("ShaderNodeOutputMaterial")
        node = tree.nodes.new("ShaderNodeGroup")
        node.node_tree = group
        if fed:
            coords = tree.nodes.new("ShaderNodeTexCoord")
            for s in node.inputs:
                if s.type == "VECTOR" and s.enabled:
                    tree.links.new(coords.outputs["Object"], s)
        socket = node.outputs[output]
        if socket.type == "SHADER":
            tree.links.new(socket, out.inputs["Surface"])
        else:
            emission = tree.nodes.new("ShaderNodeEmission")
            tree.links.new(socket, emission.inputs["Color"])
            tree.links.new(emission.outputs["Emission"], out.inputs["Surface"])
        return self.wrapper

    def composite(self, group, output):
        """The pixels of `output` of a node of the compositor `group` applied to the render."""
        tree = self.compositor
        tree.nodes.clear()
        layers = tree.nodes.new("CompositorNodeRLayers")
        layers.scene = self.scene
        node = tree.nodes.new("CompositorNodeGroup")
        node.node_tree = group
        for s in node.inputs:
            if s.type == "RGBA" and s.enabled:
                tree.links.new(layers.outputs["Image"], s)
        out = tree.nodes.new("NodeGroupOutput")
        tree.links.new(node.outputs[output], out.inputs[0])
        return self.render(self.plain, tree)

    def fingerprints(self, what, kind):
        """{output: pixels} of a material (its one output: ""), or of each output of a shader or
        compositor group."""
        if isinstance(what, bpy.types.Material):
            return {"": self.render(what)}
        if what.bl_idname == "CompositorNodeTree":
            probe = self.compositor.nodes.new("CompositorNodeGroup")
            probe.node_tree = what
            names = outputs_named(probe)
            self.compositor.nodes.remove(probe)
            return {n: self.composite(what, i) for i, n in enumerate(names)}
        probe = self.wrapper.node_tree.nodes.new("ShaderNodeGroup")
        probe.node_tree = what
        names = outputs_named(probe)
        self.wrapper.node_tree.nodes.remove(probe)
        return {n: self.render(self.wrap(what, i, kind.endswith("fed"))) for i, n in enumerate(names)}

    def differs(self, original, rebuilt, kind):
        """The kinds (with the outputs) in which `rebuilt` renders otherwise than `original`."""
        import numpy as np

        a, b = self.fingerprints(original, kind), self.fingerprints(rebuilt, kind)
        if list(a) != list(b):
            return [f"{kind}: outputs {list(b)}, not {list(a)}"]
        bad = [n for n in a if a[n].shape != b[n].shape or float(np.abs(a[n] - b[n]).max()) > self.TOLERANCE]
        return [f"{kind} {', '.join(bad)}" if any(bad) else kind] if bad else []

    def remove(self):
        bpy.data.scenes.remove(self.scene)
        for o in (self.obj, self.camera, self.sun):
            bpy.data.objects.remove(o)
        bpy.data.meshes.remove(self.mesh)
        bpy.data.materials.remove(self.wrapper)
        bpy.data.materials.remove(self.plain)
        bpy.data.node_groups.remove(self.compositor)
        bpy.data.worlds.remove(self.world)
        shutil.rmtree(self.dir, ignore_errors=True)


def round_trip(blend, nondeterministic=None, trees=("geometry",), quirks=None, serious=None):
    """{key: record} and {key: text} for the trees of `blend` that `trees` names; `serious`, when given, is
    filled with the (key, difference) of the data of each tree built back from its original that the text
    should carry (`tree_compare.NOT_CARRIED`).

    `trees` is the manifest's: "geometry" (its Geometry Nodes groups, the default), "shader" (its shader
    node groups), "material" (its materials' own trees, keyed `material:<name>`), "compositor" (its
    compositor node groups). A Geometry Nodes group is compared by evaluating it as a modifier
    (`T.evaluate`), a shader group or a material by rendering it, a compositor group by applying it to a
    render (`Stage`). `nondeterministic` is {key: [kind, ...]}: the kinds of evaluation in which the original
    itself does not give twice the same result, which are not compared (the manifest's `[nondeterministic]`).
    `quirks` is {key: [kind, ...]}: the kinds in which Blender itself evaluates the rebuilt tree otherwise
    than its original, the text being the same (the manifest's `[blender_quirks]`); they are compared, and
    a difference there is kept as `blender_quirk` rather than failing the record."""
    nondeterministic = nondeterministic or {}
    quirks = quirks or {}
    serious = [] if serious is None else serious
    unknown = set(trees) - set(TREES)
    assert not unknown, f"unknown trees {sorted(unknown)}; trees: {TREES}"
    from base_node.host import build_source, export_tree
    from base_node.blender.schema import key

    for g in list(bpy.data.node_groups):
        bpy.data.node_groups.remove(g)
    for m in list(bpy.data.materials):
        bpy.data.materials.remove(m)
    with bpy.data.libraries.load(str(blend), link=False) as (src, dst):
        dst.node_groups = list(src.node_groups)
        if "material" in trees:
            dst.materials = list(src.materials)
    loaded = list(dst.node_groups)
    kinds = {"geometry": "GeometryNodeTree", "shader": "ShaderNodeTree", "compositor": "CompositorNodeTree"}
    wanted = {kinds[t]: t for t in trees if t in kinds}
    # (key, what is compared, its tree): a group is found again by its name, a material by `material:`
    items = [(g.name, wanted[g.bl_idname], g)
             for g in sorted(loaded, key=lambda g: g.name) if g.bl_idname in wanted]
    mats = [m for m in (dst.materials if "material" in trees else []) if m is not None]
    # A grease pencil material has no node tree to read
    items += [(f"{MATERIAL}{m.name}", "material", m.node_tree) for m in sorted(mats, key=lambda m: m.name)
              if m.node_tree is not None and not m.is_grease_pencil]

    records, texts, what = {}, {}, {}
    for name, kind, tree in items:
        what[name] = kind
        r = records[name] = {"status": "ok"}
        try:
            text, warnings = export_tree(tree)
        except Exception as e:
            r.update(status="export_error", error=first_error(e))
            continue
        texts[name] = text
        r["text"] = library_corpus.text_hash(text)
        found = sorted({warning_kind(w) for w in warnings})
        if found:
            r["warnings"] = found

    # The originals keep their trees, under other names: what is built is made anew beside them
    originals = {}
    for g in loaded:
        name = g.name
        g.name = f"{ORIGINAL}{name}"
        originals[name] = g
    for m in mats:
        name = m.name
        m.name = f"{ORIGINAL}{name}"
        originals[f"{MATERIAL}{name}"] = m

    def rebuilt(name):
        if what[name] == "material":
            return bpy.data.materials[name.removeprefix(MATERIAL)]
        return bpy.data.node_groups[name]

    stage = None
    # The geometry first: its evaluation clears the scene's objects, which the stage's are not to be
    for name, text in sorted(texts.items(), key=lambda t: what[t[0]] != "geometry"):
        r = records[name]
        kind = what[name]
        try:
            tree = build_source(text, filename=f"{key(name.removeprefix(MATERIAL))}.bn")[-1]
            if kind == "material":
                mat = bpy.data.materials.get(name.removeprefix(MATERIAL))
                assert mat is not None and tree == mat.node_tree, f"builds {tree.name!r}, not the material's tree"
            else:
                assert tree.name == name, f"builds a group named {tree.name!r}"
            again, _ = export_tree(tree)
        except Exception as e:
            r.update(status="build_error", error=first_error(e))
            continue
        if again != text:
            r["status"] = "unstable"
            continue
        compared = {"geometry": T.evaluations(originals[name], KINDS) if kind == "geometry" else KINDS,
                    "shader": RENDERS, "compositor": COMPOSITES}.get(kind, RENDERS[:1])
        if kind != "geometry" and stage is None:
            stage = Stage()
        differs = []
        skipped = [k for k in compared if k in nondeterministic.get(name, ())]
        if skipped:
            r["not_compared"] = skipped
        for k in compared:
            if k in skipped:
                continue
            found = []
            try:
                if kind == "geometry":
                    if T.evaluate(originals[name], k) != T.evaluate(rebuilt(name), k):
                        found.append(k)
                else:
                    found += stage.differs(originals[name], rebuilt(name), k)
            except Exception as e:
                found.append(f"{k}: {first_error(e)}")
            if found and k in quirks.get(name, ()):
                r.setdefault("blender_quirk", []).extend(found)
            else:
                differs += found
        if differs:
            r.update(status="evaluates_otherwise", on=differs)
    if stage is not None:
        stage.remove()
    for o in [o for o in bpy.data.objects if o.users_scene]:
        bpy.data.objects.remove(o)
    # On Blender's data: each original beside the tree built back, the groups they call once each
    comparator = tree_compare.Comparator(lambda id: id.name.removeprefix(ORIGINAL))
    try:
        for name in sorted(texts):
            if records[name]["status"] == "build_error":
                continue
            a = originals[name].node_tree if what[name] == "material" else originals[name]
            b = rebuilt(name).node_tree if what[name] == "material" else rebuilt(name)
            if (a.as_pointer(), b.as_pointer()) in comparator.seen:
                continue
            for d in comparator.compare(a, b):
                if tree_compare.not_carried(d):
                    NOT_CARRIED_SEEN[d.cls.split(":")[0]] += 1
                else:
                    serious.append((name, d))
    finally:
        comparator.close()
    return records, texts


def keep_texts(name, texts):
    """The texts of this run in the cache, those of the run before beside them."""
    from base_node.blender.schema import key

    here = CACHE / "texts" / name
    previous = here.with_name(f"{name}.previous")
    if here.exists():
        shutil.rmtree(previous, ignore_errors=True)
        here.rename(previous)
    here.mkdir(parents=True)
    for group, text in texts.items():
        (here / f"{key(group)}.bn").write_text(text, encoding="utf-8")
    return here


def compare(want, got):
    """Lines saying what changed from the baseline `want` to the run `got`."""
    lines = []
    for name in sorted(want.keys() | got.keys()):
        a, b = want.get(name), got.get(name)
        if a == b:
            continue
        if a is None:
            lines.append(f"+ {name}: new group, {b['status']}")
        elif b is None:
            lines.append(f"- {name}: group gone")
        elif a["status"] != b["status"]:
            better = b["status"] == "ok"
            lines.append(f"{'↑' if better else '↓'} {name}: {a['status']} -> {b['status']}"
                         + (f" ({b.get('error') or b.get('on')})" if not better else ""))
        else:
            what = [k for k in sorted(a.keys() | b.keys()) if a.get(k) != b.get(k)]
            lines.append(f"~ {name}: {', '.join(what)} changed"
                         + (f": {b.get('error')}" if "error" in what else ""))
    return lines


def summary(records):
    counts = {}
    for r in records.values():
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    return ", ".join(f"{n} {s}" for s, n in sorted(counts.items(), key=lambda x: -x[1]))


class Skipped(Exception):
    """A library the Blender that runs is too old for: its manifest says so."""


def read_manifest(manifest):
    """The manifest as the Blender that runs reads it: its `[blender."<x.y>"]` table, if any, over
    the rest."""
    lib = tomllib.loads(manifest.read_text(encoding="utf-8"))
    lib.update(lib.pop("blender", {}).get(T.BLENDER_VERSION, {}))
    return lib


def baseline_file(manifest):
    """(the baseline this Blender is compared with, the one it writes).

    `<name>.baseline.json` is the record of one Blender, which it names. Another version is compared
    with `<name>.baseline-<x.y>.json` when there is one, with that same record otherwise; it writes
    its own file only, never the record of the other Blender."""
    main = manifest.with_suffix(".baseline.json")
    own = manifest.with_name(f"{manifest.stem}.baseline-{T.BLENDER_VERSION}.json")
    if main.exists():
        made_with = ".".join(json.loads(main.read_text(encoding="utf-8")).get("blender", "").split(".")[:2])
        if made_with != T.BLENDER_VERSION:
            return (own if own.exists() else main), own
    return main, main


def test_library(manifest):
    lib = read_manifest(manifest)
    name = manifest.stem
    print(f"-> {lib['name']} {lib.get('version', '')} ({lib['license']})")
    oldest = lib.get("blender_min")
    if oldest and bpy.app.version[:2] < tuple(int(x) for x in oldest.split(".")):
        raise Skipped(f"{lib['name']} needs Blender {oldest}, this is {bpy.app.version_string}")
    serious = []
    records, texts = round_trip(fetch(lib), lib.get("nondeterministic"), lib.get("trees", ("geometry",)),
                                lib.get("blender_quirks"), serious)
    kept = keep_texts(name, texts)
    print(f"   {len(records)} groups: {summary(records)}; texts in {kept}")
    assert not serious, (f"{lib['name']}: {len(serious)} differences of the data the text should carry\n"
                         + "\n".join(f"{key}: {d}" for key, d in serious[:80]))
    baseline_path, written = baseline_file(manifest)
    if os.environ.get("BASE_NODE_UPDATE_FIXTURES") or not baseline_path.exists():
        main = manifest.with_suffix(".baseline.json")
        if written != main and json.loads(main.read_text(encoding="utf-8"))["groups"] == records:
            # This Blender reads the library as the other does: one record for both
            written.unlink(missing_ok=True)
            print(f"   ✓ as in {main.name}: no {written.name}")
            return
        baseline = {"library": lib["name"], "version": lib.get("version"), "sha256": lib["sha256"],
                    "blender": bpy.app.version_string, "summary": summary(records), "groups": records}
        written.write_text(json.dumps(baseline, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"   baseline written: {written.name}")
        if written == main:
            # The texts of the Blender of the baseline are the corpus: those of another are not kept
            folder = library_corpus.write_library(name, texts, VERSION, bpy.app.version_string)
            print(f"   corpus written: {folder.relative_to(library_corpus.ROOT)} ({len(texts)} texts)")
            return True
        return
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    if baseline.get("blender") != bpy.app.version_string:
        print(f"   note: baseline made with Blender {baseline.get('blender')}, this is {bpy.app.version_string}")
    changes = compare(baseline["groups"], records)
    assert not changes, (f"{lib['name']} reads otherwise than {baseline_path.name} "
                         f"({len(changes)} groups); if that is wanted, rerun with BASE_NODE_UPDATE_FIXTURES=1\n"
                         + "\n".join(changes[:80]))
    print(f"   ✓ as in {baseline_path.name}")


def main():
    names = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    manifests = sorted(LIBRARIES.glob("*.toml"))
    if names:
        manifests = [m for m in manifests if m.stem in names]
        assert manifests, f"no library named {names} in {LIBRARIES}"
    print("=== Base Node non-regression on third-party libraries ===")
    T.base_node.register()
    failed, skipped, corpus = 0, 0, False
    for m in manifests:
        try:
            corpus = test_library(m) or corpus
        except Skipped as e:
            skipped += 1
            print(f"   - skipped: {e}")
        except Exception:
            failed += 1
            traceback.print_exc()
    print("   not carried by the text, by decision: "
          + ", ".join(f"{c} {n}" for c, n in sorted(NOT_CARRIED_SEEN.items())))
    if os.environ.get("BASE_NODE_UPDATE_FIXTURES"):
        import regression_badges
        print(f"   badges written: {regression_badges.write()}")
    if corpus:
        print(f"   corpus index written: {library_corpus.write_index().relative_to(library_corpus.ROOT)}")
    if failed:
        print(f"\n❌ FAILED: {failed}/{len(manifests)} libraries changed")
        sys.exit(1)
    print(f"\n✅ SUCCESS: {len(manifests) - skipped} libraries as in their baselines"
          + (f", {skipped} skipped on Blender {bpy.app.version_string}" if skipped else ""))
    sys.exit(0)


if __name__ == "__main__":
    main()
