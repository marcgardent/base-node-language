"""Build and render the Base Node (.bn) animated showcases in Blender.

Usage:
  blender -b --factory-startup --python examples/render_showcases.py -- --still
  blender -b --factory-startup --python examples/render_showcases.py -- --anim
  blender -b --factory-startup --python examples/render_showcases.py -- --anim --only showcase-reaction-diffusion

A showcase is animated by its `phase` input, from 0 to 1, or, when it is a simulation (`frames`), by the
frames of the scene, one after the other. The still of a simulation is not made here: its poster is the
still of its check script (reaction_diffusion_check.py for showcase-reaction-diffusion,
differential_growth_check.py for showcase-differential-growth).
"""

import math
import os
import subprocess
import sys

import bpy

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "python"))

# Load the base_node Blender extension package
import importlib.util

EXT_DIR = os.path.join(ROOT, "base-node-for-blender")
spec = importlib.util.spec_from_file_location(
    "base_node_ext",
    os.path.join(EXT_DIR, "__init__.py"),
    submodule_search_locations=[EXT_DIR],
)
ext_mod = importlib.util.module_from_spec(spec)
sys.modules["base_node_ext"] = ext_mod
spec.loader.exec_module(ext_mod)
from base_node_ext.host import build_source  # noqa: E402

OUT_DIR = os.path.join(ROOT, "site", "images")


def make_pbr(name, color, metallic=0.0, roughness=0.35, emission=None, emission_strength=0.0):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = (*color, 1.0)
    bsdf.inputs["Metallic"].default_value = metallic
    bsdf.inputs["Roughness"].default_value = roughness
    if emission and emission_strength > 0.0:
        bsdf.inputs["Emission Color"].default_value = (*emission, 1.0)
        bsdf.inputs["Emission Strength"].default_value = emission_strength
    return mat


def setup_materials():
    make_pbr("DarkSlate", (0.11, 0.13, 0.17), metallic=0.65, roughness=0.38)
    make_pbr("SteelRing", (0.52, 0.57, 0.65), metallic=0.85, roughness=0.25)
    make_pbr("BrassGear", (0.92, 0.64, 0.24), metallic=0.88, roughness=0.22)
    make_pbr(
        "NeonCyan",
        (0.15, 0.85, 0.96),
        metallic=0.1,
        roughness=0.15,
        emission=(0.15, 0.85, 0.96),
        emission_strength=2.8,
    )
    make_pbr(
        "NeonAmber",
        (1.0, 0.52, 0.14),
        metallic=0.1,
        roughness=0.18,
        emission=(1.0, 0.52, 0.14),
        emission_strength=2.6,
    )
    make_pbr("WarmTerrain", (0.76, 0.54, 0.36), metallic=0.08, roughness=0.55)
    make_pattern("ReactionPattern")
    make_coral("GrowthCoral")
    make_tint("TupleTiles")
    make_pbr(
        "OceanTeal",
        (0.10, 0.52, 0.68),
        metallic=0.25,
        roughness=0.14,
        emission=(0.08, 0.42, 0.58),
        emission_strength=0.35,
    )
    make_pbr("EmeraldPine", (0.18, 0.66, 0.42), metallic=0.05, roughness=0.42)
    make_pbr(
        "IridescentCore",
        (0.46, 0.56, 0.94),
        metallic=0.78,
        roughness=0.18,
        emission=(0.24, 0.32, 0.85),
        emission_strength=0.45,
    )


def make_pattern(name):
    """Deep blue where the attribute "v" of a reaction-diffusion is low, warm where it is high."""
    mat = bpy.data.materials.new(name)
    nt = mat.node_tree
    bsdf = nt.nodes["Principled BSDF"]
    bsdf.inputs["Roughness"].default_value = 0.4
    attribute = nt.nodes.new("ShaderNodeAttribute")
    attribute.attribute_name = "v"
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    stops = ramp.color_ramp.elements
    stops[0].position, stops[0].color = 0.0, (0.02, 0.05, 0.16, 1.0)
    stops[1].position, stops[1].color = 0.35, (1.0, 0.55, 0.16, 1.0)
    stops.new(0.15).color = (0.10, 0.45, 0.60, 1.0)
    nt.links.new(attribute.outputs["Fac"], ramp.inputs["Fac"])
    nt.links.new(ramp.outputs["Color"], bsdf.inputs["Base Color"])
    return mat


def make_coral(name):
    """Coral red to gold by the attribute "origin" of a differential growth: where its points come from."""
    mat = bpy.data.materials.new(name)
    nt = mat.node_tree
    bsdf = nt.nodes["Principled BSDF"]
    bsdf.inputs["Roughness"].default_value = 0.35
    attribute = nt.nodes.new("ShaderNodeAttribute")
    attribute.attribute_name = "origin"
    xyz = nt.nodes.new("ShaderNodeSeparateXYZ")
    remap = nt.nodes.new("ShaderNodeMapRange")
    remap.inputs["From Min"].default_value = -1.0
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    ramp.color_ramp.interpolation = "EASE"
    stops = ramp.color_ramp.elements
    stops[0].position, stops[0].color = 0.0, (0.95, 0.30, 0.18, 1.0)
    stops[1].position, stops[1].color = 1.0, (1.0, 0.78, 0.35, 1.0)
    stops.new(0.5).color = (0.85, 0.20, 0.38, 1.0)
    nt.links.new(attribute.outputs["Vector"], xyz.inputs["Vector"])
    nt.links.new(xyz.outputs["Y"], remap.inputs["Value"])
    nt.links.new(remap.outputs["Result"], ramp.inputs["Fac"])
    nt.links.new(ramp.outputs["Color"], bsdf.inputs["Base Color"])
    return mat


def make_tint(name):
    """The colour each tile of tuple_tiles.bn stores in its attribute "tint"."""
    mat = bpy.data.materials.new(name)
    nt = mat.node_tree
    bsdf = nt.nodes["Principled BSDF"]
    bsdf.inputs["Roughness"].default_value = 0.32
    attribute = nt.nodes.new("ShaderNodeAttribute")
    attribute.attribute_name = "tint"
    nt.links.new(attribute.outputs["Color"], bsdf.inputs["Base Color"])
    return mat


def setup_world_and_lights():
    scene = bpy.context.scene
    world = bpy.data.worlds.new("ShowcaseWorld")
    world.use_nodes = True
    bg = world.node_tree.nodes["Background"]
    bg.inputs["Color"].default_value = (0.045, 0.052, 0.068, 1.0)
    bg.inputs["Strength"].default_value = 1.0
    scene.world = world

    # Key sun light
    sun_data = bpy.data.lights.new("KeySun", "SUN")
    sun_data.energy = 4.2
    sun_data.color = (1.0, 0.96, 0.90)
    sun = bpy.data.objects.new("KeySun", sun_data)
    sun.rotation_euler = (math.radians(42), math.radians(-18), math.radians(32))
    scene.collection.objects.link(sun)

    # Cool fill light
    fill_data = bpy.data.lights.new("CoolFill", "AREA")
    fill_data.energy = 140.0
    fill_data.size = 5.0
    fill_data.color = (0.55, 0.78, 1.0)
    fill = bpy.data.objects.new("CoolFill", fill_data)
    fill.location = (-3.5, -2.5, 4.2)
    fill.rotation_euler = (math.radians(35), math.radians(-30), math.radians(-25))
    scene.collection.objects.link(fill)

    # Warm rim light
    rim_data = bpy.data.lights.new("WarmRim", "AREA")
    rim_data.energy = 180.0
    rim_data.size = 4.0
    rim_data.color = (1.0, 0.68, 0.40)
    rim = bpy.data.objects.new("WarmRim", rim_data)
    rim.location = (3.2, 3.2, 3.5)
    rim.rotation_euler = (math.radians(-45), math.radians(35), math.radians(135))
    scene.collection.objects.link(rim)


def make_camera(name, location, rotation_deg, lens=48, ortho_scale=None):
    cam_data = bpy.data.cameras.new(name)
    if ortho_scale:
        cam_data.type = "ORTHO"
        cam_data.ortho_scale = ortho_scale
    else:
        cam_data.lens = lens
    cam = bpy.data.objects.new(name, cam_data)
    cam.location = location
    cam.rotation_euler = tuple(math.radians(a) for a in rotation_deg)
    bpy.context.scene.collection.objects.link(cam)
    return cam


def set_phase(mod, value):
    for item in mod.node_group.interface.items_tree:
        if item.item_type == "SOCKET" and item.in_out == "INPUT" and item.name == "phase":
            if hasattr(mod, "properties") and hasattr(mod.properties, "inputs"):
                getattr(mod.properties.inputs, item.identifier).value = float(value)
            else:
                mod[item.identifier] = float(value)
            break
    mod.id_data.update_tag()


# What a simulation is grown on, added to its file: its graph is the last one
SIMULATIONS = {
    "reaction_diffusion.bn": """
geometry graph "growing tile"() -> Geometry {
  return Grid(4.0, 4.0, 256, 256)
    |> growing_reaction_diffusion(steps_per_frame: 100)
    |> SetShadeSmooth()
    |> SetMaterial(material: "ReactionPattern")
}
""",
    "differential_growth.bn": """
geometry graph "growing coral"() -> Geometry {
  grown = growth_seed(0.4, 0.02, 0.3, 0) |> growing_differential_growth(steps_per_frame: 8)
  return CurveToMesh(grown, profile_curve: CurveCircle(resolution: 8, radius: 0.006))
    |> SetShadeSmooth()
    |> SetMaterial(material: "GrowthCoral")
}
""",
}


def find_showcases():
    """Every examples/*.bn whose head has a line `// @showcase camera=x,y,z rotation=x,y,z lens=mm
    [frames]`, by file name: found by that line, so that adding a showcase edits nothing here.

    Its slug, the name of its pictures, is <module with - for _> for examples/<module>_showcase.bn
    and showcase-<name with - for _> for another; it is rendered through its last geometry graph
    (SIMULATIONS adds one to a simulation); `frames` animates it by the frames of the scene.
    """
    from base_node_ext.lang import parse
    from base_node_ext.lang.header import directives

    found = []
    for name in sorted(os.listdir(os.path.join(ROOT, "examples"))):
        if not name.endswith(".bn"):
            continue
        with open(os.path.join(ROOT, "examples", name), encoding="utf-8") as f:
            source = f.read()
        said = [value for key, value, _line, _col in directives(source) if key == "showcase"]
        if not said or "camera=" not in said[0]:
            continue
        words = said[0].split()
        say = dict(w.split("=", 1) for w in words if "=" in w)
        stem = name[: -len(".bn")]
        slug = stem[: -len("_showcase")] if stem.endswith("_showcase") else f"showcase-{stem}"
        extra = SIMULATIONS.get(name, "")
        graphs = parse(source + extra, name).graphs
        found.append({
            "slug": slug.replace("_", "-"),
            "file": name,
            "group": [g.name for g in graphs if g.kind == "geometry"][-1],
            "extra": extra,
            "frames": "frames" in words,
            "cam_loc": tuple(float(v) for v in say["camera"].split(",")),
            "cam_rot": tuple(float(v) for v in say["rotation"].split(",")),
            "lens": float(say["lens"]),
        })
    return found


def stdlib_used(paths):
    """The stdlib modules the files at `paths` use, and the ones these use, by name."""
    seen, todo = set(), list(paths)
    while todo:
        with open(todo.pop(), encoding="utf-8") as f:
            for line in f:
                words = line.split()
                if len(words) >= 2 and words[0] == "use" and words[1] not in seen:
                    module = words[1]
                    path = os.path.join(ROOT, "stdlib", f"{module}.bn")
                    if os.path.exists(path):
                        seen.add(module)
                        todo.append(path)
    return sorted(seen)


def main():
    args = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else ["--still"]
    mode = "anim" if "--anim" in args else "still"

    bpy.ops.wm.read_factory_settings(use_empty=True)
    ext_mod.register()
    setup_materials()
    setup_world_and_lights()

    showcases = find_showcases()
    # The stdlib modules they use, into bpy.data.texts so that `use ...` resolves them
    for module in stdlib_used([os.path.join(ROOT, "examples", cfg["file"]) for cfg in showcases]):
        with open(os.path.join(ROOT, "stdlib", f"{module}.bn"), encoding="utf-8") as f:
            bpy.data.texts.new(f"{module}.bn").write(f.read())

    if "--only" in args:
        only = args[args.index("--only") + 1]
        showcases = [cfg for cfg in showcases if cfg["slug"] == only]

    scene = bpy.context.scene
    scene.render.engine = "BLENDER_EEVEE"
    scene.render.resolution_x = 960
    scene.render.resolution_y = 640
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGB"
    scene.view_settings.view_transform = "AgX" if "AgX" in ("Standard", "AgX") else "Standard"
    try:
        scene.view_settings.look = "AgX - Medium High Contrast"
    except Exception:
        scene.view_settings.view_transform = "Standard"

    os.makedirs(OUT_DIR, exist_ok=True)

    # Build all showcase objects
    built_items = []
    for cfg in showcases:
        with open(os.path.join(ROOT, "examples", cfg["file"]), encoding="utf-8") as f:
            src = f.read()
        build_source(src + cfg.get("extra", ""), cfg["file"])
        coll = bpy.data.collections.new(cfg["slug"])
        scene.collection.children.link(coll)
        obj = bpy.data.objects.new(cfg["slug"], bpy.data.meshes.new(cfg["slug"]))
        coll.objects.link(obj)
        mod = obj.modifiers.new("BaseNode", "NODES")
        mod.node_group = bpy.data.node_groups[cfg["group"]]
        cam = make_camera(
            f"Cam_{cfg['slug']}",
            cfg["cam_loc"],
            cfg["cam_rot"],
            lens=cfg["lens"],
        )
        built_items.append((cfg, coll, obj, mod, cam))

    if mode == "still":
        for cfg, coll, obj, mod, cam in built_items:
            if cfg.get("frames"):
                continue
            for _, c, _, _, _ in built_items:
                c.hide_render = c is not coll
            scene.camera = cam
            set_phase(mod, 0.22)
            bpy.context.view_layer.update()
            out_png = os.path.join(OUT_DIR, f"{cfg['slug']}.png")
            scene.render.filepath = out_png
            bpy.ops.render.render(write_still=True)
            print("Rendered still:", out_png)
    else:
        num_frames = 48
        fps = 24
        for cfg, coll, obj, mod, cam in built_items:
            for _, c, _, _, _ in built_items:
                c.hide_render = c is not coll
            scene.camera = cam
            tmp_dir = os.path.join("/tmp", f"bn_{cfg['slug']}")
            os.makedirs(tmp_dir, exist_ok=True)
            for frame_idx in range(num_frames):
                if cfg.get("frames"):
                    scene.frame_set(frame_idx + 1)
                else:
                    set_phase(mod, frame_idx / float(num_frames))
                bpy.context.view_layer.update()
                frame_path = os.path.join(tmp_dir, f"frame_{frame_idx:04d}.png")
                scene.render.filepath = frame_path
                bpy.ops.render.render(write_still=True)
                if frame_idx == 10 and not cfg.get("frames"):
                    poster_path = os.path.join(OUT_DIR, f"{cfg['slug']}.png")
                    with open(frame_path, "rb") as fin, open(poster_path, "wb") as fout:
                        fout.write(fin.read())

            mp4_path = os.path.join(OUT_DIR, f"{cfg['slug']}.mp4")
            gif_path = os.path.join(OUT_DIR, f"{cfg['slug']}.gif")
            subprocess.run(
                [
                    "ffmpeg",
                    "-y",
                    "-framerate",
                    str(fps),
                    "-i",
                    os.path.join(tmp_dir, "frame_%04d.png"),
                    "-c:v",
                    "libx264",
                    "-pix_fmt",
                    "yuv420p",
                    "-crf",
                    "21",
                    "-preset",
                    "slow",
                    "-movflags",
                    "+faststart",
                    mp4_path,
                ],
                check=True,
            )
            subprocess.run(
                [
                    "ffmpeg",
                    "-y",
                    "-framerate",
                    str(fps),
                    "-i",
                    os.path.join(tmp_dir, "frame_%04d.png"),
                    "-vf",
                    "scale=640:-1:flags=lanczos,split[s0][s1];[s0]palettegen=max_colors=128[p];[s1][p]paletteuse=dither=bayer:bayer_scale=3",
                    gif_path,
                ],
                check=True,
            )
            print("Encoded MP4 & GIF:", mp4_path, gif_path)


if __name__ == "__main__":
    main()
