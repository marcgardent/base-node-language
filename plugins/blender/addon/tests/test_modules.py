"""Security tests for `use … from "…"` module resolution, without Blender.

A `.bn` file is untrusted input: its `use … from` source must not read files
outside the module roots, nor what is not a text of a source's size (a pipe, a
device, a huge file). host/modules.py is loaded against a minimal fake `bpy`,
so this runs in plain Python.

    python3 addon/tests/test_modules.py
"""

from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
import types
from pathlib import Path

_EXTENSION = Path(__file__).resolve().parents[1]
_MODULES_PY = _EXTENSION / "host" / "modules.py"
_PACKAGE = "_bn_extension_under_test"


def _fake_bpy(blend_filepath):
    """A `bpy` stub covering what modules.py touches: data.texts, data.filepath, path.abspath."""
    bpy = types.ModuleType("bpy")

    class _Texts:
        def get(self, _key):  # no in-file text datablocks in these tests
            return None

    def abspath(p):
        # Mimic Blender: '//' is relative to the .blend folder; else returned unchanged.
        if isinstance(p, str) and p.startswith("//"):
            return os.path.join(os.path.dirname(blend_filepath), p[2:])
        return p

    bpy.data = types.SimpleNamespace(filepath=blend_filepath, texts=_Texts())
    bpy.path = types.SimpleNamespace(abspath=abspath)
    return bpy


def _load_modules(blend_filepath):
    """Import host/modules.py with a fake bpy for the given .blend path.

    It stands in a package made of the extension's `lang` alone (the language, that needs no
    bpy) and an empty `host`: host/__init__.py would bring the builder, and Blender with it.
    """
    sys.modules["bpy"] = _fake_bpy(blend_filepath)
    if _PACKAGE not in sys.modules:
        for name in (_PACKAGE, _PACKAGE + ".host"):
            sys.modules[name] = types.ModuleType(name)
            sys.modules[name].__path__ = []
        spec = importlib.util.spec_from_file_location(
            _PACKAGE + ".lang", _EXTENSION / "lang" / "__init__.py",
            submodule_search_locations=[str(_EXTENSION / "lang")])
        lang = sys.modules[spec.name] = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(lang)
    spec = importlib.util.spec_from_file_location(_PACKAGE + ".host.modules", _MODULES_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _project(root):
    """A saved .blend with a sibling lib/ module and a secret file one level up."""
    proj = os.path.join(root, "project")
    os.makedirs(os.path.join(proj, "lib"))
    with open(os.path.join(proj, "lib", "math.bn"), "w") as f:
        f.write("geometry graph m(geometry: Geometry) -> Geometry { return geometry }")
    with open(os.path.join(root, "secret.bn"), "w") as f:
        f.write("SECRET")
    blend = os.path.join(proj, "scene.blend")
    with open(blend, "w") as f:
        f.write("")  # only its path matters
    return proj, blend


def _raises(fn, needle):
    try:
        fn()
    except LookupError as e:
        assert needle in str(e), f"wrong error: {e!r} (wanted {needle!r})"
        return
    raise AssertionError(f"expected LookupError containing {needle!r}, nothing raised")


def test_absolute_path_is_refused():
    """use x from "/abs/secret.bn" must not read an absolute path."""
    with tempfile.TemporaryDirectory() as root:
        _, blend = _project(root)
        mod = _load_modules(blend)
        _raises(lambda: mod.load("x", os.path.join(root, "secret.bn")),
                "absolute paths are not allowed")


def test_absolute_path_of_an_imported_module_is_read():
    """The module File > Import found next to the chosen file builds again by its path; no other does."""
    with tempfile.TemporaryDirectory() as root:
        proj, blend = _project(root)
        mod = _load_modules(blend)
        beside = os.path.join(proj, "lib", "math.bn")
        mod.pick(beside)
        assert "graph m" in mod.load("math", beside)[0]
        _raises(lambda: mod.load("x", os.path.join(root, "secret.bn")), "absolute paths are not allowed")
        # The path now leads elsewhere: it is no longer the file that was picked
        os.remove(beside)
        os.symlink(os.path.join(root, "secret.bn"), beside)
        _raises(lambda: mod.load("math", beside), "absolute paths are not allowed")


def test_a_url_is_refused():
    """use x from "https://…" must not reach the network."""
    with tempfile.TemporaryDirectory() as root:
        _, blend = _project(root)
        mod = _load_modules(blend)
        for url in ("https://example.com/math.bn", "http://192.168.0.1/math.bn"):
            _raises(lambda: mod.load("math", url), "not a URL")


def test_blend_relative_escape_is_refused():
    """A '//..' path may not climb out of the .blend folder."""
    with tempfile.TemporaryDirectory() as root:
        _, blend = _project(root)
        mod = _load_modules(blend)
        _raises(lambda: mod.load("x", "//../secret.bn"), "inside the .blend folder")


def test_legitimate_blend_relative_module_loads():
    """A '//lib/math.bn' under the .blend folder still resolves and reads."""
    with tempfile.TemporaryDirectory() as root:
        _, blend = _project(root)
        mod = _load_modules(blend)
        text, source = mod.load("math", "//lib/math.bn")
        assert "graph m" in text, text
        assert source == "//lib/math.bn"


def _project_with_root(root):
    """A project: <root>/.blender_project, a .blend in a subdir, a module under the project root."""
    os.makedirs(os.path.join(root, ".blender_project"))
    os.makedirs(os.path.join(root, "lib"))
    with open(os.path.join(root, "lib", "math.bn"), "w") as f:
        f.write("geometry graph m(geometry: Geometry) -> Geometry { return geometry }")
    scene_dir = os.path.join(root, "scenes")
    os.makedirs(scene_dir)
    with open(os.path.join(root, "secret.bn"), "w") as f:
        f.write("SECRET")  # under the project root but reachable only via the lib path, not '..'
    blend = os.path.join(scene_dir, "scene.blend")
    with open(blend, "w") as f:
        f.write("")
    return blend


def test_project_root_resolves_inside_a_blender_project():
    """{project_root}/lib/math.bn resolves from the nearest parent holding .blender_project."""
    with tempfile.TemporaryDirectory() as root:
        blend = _project_with_root(root)
        mod = _load_modules(blend)
        text, source = mod.load("math", "{project_root}/lib/math.bn")
        assert "graph m" in text, text
        assert source == "{project_root}/lib/math.bn"


def test_project_root_escape_is_refused():
    """{project_root}/../ may not climb out of the project."""
    with tempfile.TemporaryDirectory() as root:
        blend = _project_with_root(root)
        mod = _load_modules(blend)
        _raises(lambda: mod.load("x", "{project_root}/../secret.bn"), "inside the project")


def test_project_root_outside_any_project_errors_clearly():
    """A .blend in no project gives a clear error, not a traceback."""
    with tempfile.TemporaryDirectory() as root:
        _, blend = _project(root)  # no .blender_project anywhere
        mod = _load_modules(blend)
        _raises(lambda: mod.load("x", "{project_root}/lib/math.bn"), "no Blender project")


def test_find_stays_inside_its_folder():
    """find() only returns a file that lies inside one of the given folders."""
    with tempfile.TemporaryDirectory() as root:
        proj, blend = _project(root)
        mod = _load_modules(blend)
        folder = os.path.join(proj, "lib")
        assert mod.find("math", [folder]) == os.path.normpath(os.path.join(folder, "math.bn"))
        # A name absent from the folder is not found (and cannot reach the secret one level up).
        assert mod.find("secret", [folder]) is None


def test_a_pipe_is_not_read():
    """A `use` naming a pipe must not hold Blender waiting for its other end."""
    if not hasattr(os, "mkfifo"):
        return
    with tempfile.TemporaryDirectory() as root:
        proj, blend = _project(root)
        mod = _load_modules(blend)
        # Nobody writes to it: a plain open() would wait here for ever
        os.mkfifo(os.path.join(proj, "lib", "pipe.bn"))
        _raises(lambda: mod.load("pipe", "//lib/pipe.bn"), "not a regular file")
        assert mod.find("pipe", [os.path.join(proj, "lib")]) is None


def test_a_file_larger_than_a_source_is_not_read():
    """No more than a source may hold is read into memory."""
    with tempfile.TemporaryDirectory() as root:
        proj, blend = _project(root)
        mod = _load_modules(blend)
        path = os.path.join(proj, "lib", "huge.bn")
        with open(path, "wb") as f:
            f.truncate(mod.MAX_SOURCE_BYTES + 1)  # sparse: no disk is used
        _raises(lambda: mod.load("huge", "//lib/huge.bn"), "larger than 4 MiB")
        _raises(lambda: mod.load("huge", None, [os.path.join(proj, "lib")]), "larger than 4 MiB")
        with open(path, "wb") as f:
            f.truncate(mod.MAX_SOURCE_BYTES)
        assert len(mod.load("huge", "//lib/huge.bn")[0]) == mod.MAX_SOURCE_BYTES


def test_what_is_not_text_is_refused_clearly():
    """A binary file named by a `use` gives an error to show, not a traceback."""
    with tempfile.TemporaryDirectory() as root:
        proj, blend = _project(root)
        mod = _load_modules(blend)
        with open(os.path.join(proj, "lib", "binary.bn"), "wb") as f:
            f.write(b"\xff\xfe\x00BLENDER")
        _raises(lambda: mod.load("binary", "//lib/binary.bn"), "not a UTF-8 text")
        _raises(lambda: mod.load("binary", None, [os.path.join(proj, "lib")]), "not a UTF-8 text")


def test_install_writes_name_bn_in_the_module_folder():
    """A dropped file installed as a library goes to <module>.bn in the folder, and `find` reads it."""
    with tempfile.TemporaryDirectory() as root:
        proj, blend = _project(root)
        mod = _load_modules(blend)
        folder = os.path.join(root, "modules")
        os.mkdir(folder)
        path, written = mod.install("waves", folder, "// one\n")
        assert written and path == os.path.join(folder, "waves.bn")
        assert mod.find("waves", [folder]) == path and mod.read(path) == "// one\n"
        assert mod.install("waves", folder, "// one\n") == (path, False)  # the same text: nothing to do
        assert mod.installed("waves", folder, "// two\n") == (path, "other")
        _raises(lambda: mod.install("waves", folder, "// two\n"), "already exists, with another text")
        assert mod.read(path) == "// one\n"
        assert mod.install("waves", folder, "// two\n", overwrite=True) == (path, True)
        assert mod.read(path) == "// two\n" and os.listdir(folder) == ["waves.bn"]
        # A folder given relative to the .blend, as the preferences may hold it
        assert mod.install_path("waves", "//lib") == os.path.join(proj, "lib", "waves.bn")


def test_install_stays_in_the_module_folder():
    """The module name of a dropped file cannot write anywhere else, nor through a link."""
    with tempfile.TemporaryDirectory() as root:
        proj, blend = _project(root)
        mod = _load_modules(blend)
        folder = os.path.join(proj, "lib")
        for name in ("../secret", "/etc/passwd", "a/b", "", "mesh-maps", "x.bn"):
            _raises(lambda: mod.install(name, folder, "x"), "is not a module name")
        _raises(lambda: mod.install("waves", "", "x"), "no Module Folder: set one")
        _raises(lambda: mod.install("waves", os.path.join(root, "nowhere"), "x"), "is not a folder")
        # A link of that name, even to a file in the folder, is left alone
        os.symlink(os.path.join(root, "secret.bn"), os.path.join(folder, "evil.bn"))
        _raises(lambda: mod.install("evil", folder, "x", overwrite=True), "is not a regular file")
        os.mkdir(os.path.join(folder, "dir.bn"))
        _raises(lambda: mod.install("dir", folder, "x", overwrite=True), "is not a regular file")
        with open(os.path.join(root, "secret.bn")) as f:
            assert f.read() == "SECRET"


if __name__ == "__main__":
    tests = [v for k, v in dict(globals()).items() if k.startswith("test_")]
    for t in tests:
        t()
        print("ok", t.__name__)
    print(f"{len(tests)} passed")
