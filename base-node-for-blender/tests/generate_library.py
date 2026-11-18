"""Build the node groups of an add-on whose Python makes them, and save them in a .blend.

Run by `test_libraries.py` for a manifest with a `[generate]` table, in its own Blender process:
    blender --background --factory-startup --python-exit-code 1 \
      --python base-node-for-blender/tests/generate_library.py -- <extension.zip> <out.blend> <generate json>

That process must be given a throwaway user profile (BLENDER_USER_RESOURCES and the BLENDER_USER_* it
overrides pointing to a temporary directory): the extension is installed into that profile's
`user_default` repository, never into the real one, and this script refuses to install it elsewhere.
Then it makes the one call the manifest names, `operator` (run with an empty mesh object active, as an
"add modifier" operator expects) or `function` (a dotted name inside the extension's package), and writes
every node group then in the file, with what they use, to <out.blend>.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import bpy


def install(zip_path):
    """The package of the extension at `zip_path`, installed and enabled in the throwaway profile only."""
    profile = Path(os.environ["BLENDER_USER_RESOURCES"]).resolve()
    extensions = Path(bpy.utils.user_resource('EXTENSIONS')).resolve()
    assert extensions.is_relative_to(profile), f"user extensions in {extensions}, not in the throwaway {profile}"
    before = set(bpy.context.preferences.addons.keys())
    result = bpy.ops.extensions.package_install_files(filepath=zip_path, repo="user_default",
                                                       enable_on_install=True)
    assert result == {"FINISHED"}, f"installing {zip_path}: {result}"
    added = sorted(set(bpy.context.preferences.addons.keys()) - before)
    assert len(added) == 1, f"installing {zip_path} enabled {added}"
    package = added[0]
    assert Path(sys.modules[package].__file__).resolve().is_relative_to(profile), package
    print(f"   installed {package} in {extensions}")
    return package


def make(spec, package):
    """The manifest's one call: an operator with an empty mesh object active, or a function of `package`."""
    if "operator" in spec:
        obj = bpy.data.objects.new("Generate", bpy.data.meshes.new("Generate"))
        bpy.context.scene.collection.objects.link(obj)
        bpy.context.view_layer.objects.active = obj
        area, op = spec["operator"].split(".")
        with bpy.context.temp_override(object=obj, active_object=obj):
            result = getattr(getattr(bpy.ops, area), op)()
        assert result == {"FINISHED"}, f"{spec['operator']}: {result}"
    else:
        module, function = spec["function"].rsplit(".", 1)
        __import__(f"{package}.{module}")
        getattr(sys.modules[f"{package}.{module}"], function)()


def save(out):
    """Every node group of the file, with what they use, written to `out`."""
    groups = set(bpy.data.node_groups)
    assert groups, "the call made no node group"
    part = Path(out).with_suffix(".part")
    part.parent.mkdir(parents=True, exist_ok=True)
    bpy.data.libraries.write(str(part), groups, fake_user=True)
    part.rename(out)
    print(f"   {len(groups)} node groups written to {out}")


def main():
    zip_path, out, spec = sys.argv[sys.argv.index("--") + 1:][:3]
    for g in list(bpy.data.node_groups):
        bpy.data.node_groups.remove(g)
    make(json.loads(spec), install(zip_path))
    save(out)


if __name__ == "__main__":
    main()
