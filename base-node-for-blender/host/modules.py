"""Where a `use` finds its module: a text datablock of the .blend, or a .bn file.

`use math` reads the text datablock math.bn, else math.bn in a module folder: the one
of the preferences, then the stdlib bundled with the add-on;
`use math from "//lib/math.bn"` a file relative to the .blend, and
`use math from "{project_root}/lib/math.bn"` relative to the Blender 5.3 project
root (the nearest parent of the .blend holding `.blender_project`), as elsewhere
in Blender. Like Python's own imports, a module resolves only inside these roots:
absolute paths are refused, and a `//…` or `{project_root}` path may not escape
its root with `..`. The one absolute path a `use` may name is that of a module found
next to a file the user imported in this session: see `pick`. A URL is refused:
opening a .bn never makes a network request. Asset libraries come later.
What is read is a regular file no larger than a source may be: see `read`. A file
dropped on Blender may be installed as a module of the module folder: see `install`.
"""

import json
import os
import stat

import bpy

from ..lang import MAX_SOURCE_BYTES
from ..lang.names import is_bare

# Custom properties of a group built by a `use`, for Tree → Text to write the use back
MODULE = "base_node_module"
SOURCE = "base_node_source"
# …and, of a module's graph built for another kind of tree (`bias (Compositor)`), the graph it is
GRAPH = "base_node_graph"
# …and, of a template's group (`attribute_or (Vector)`), its types and the positions of the inputs of
# each type parameter, as JSON: {"types": ["Vector"], "inputs": [[1]]}
TYPES = "base_node_types"


# The standard library shipped with the add-on: a link to the repository's stdlib/, files in the .zip
STDLIB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "stdlib")

# Folders where `use name` looks for name.bn after the texts of the .blend: the preferences set it
FOLDERS = [STDLIB]


# Real paths of the modules found next to a file the user imported: see `pick`
PICKED = set()


def pick(path):
    """Let a `use` name this file by its absolute path, until Blender quits.

    File > Import finds a module next to the file the user chose, and the groups built from it
    keep its path to be built again. A text names that path like any other, so the path alone
    says nothing of who wrote it: only those the import itself found are read, and only while
    they still resolve to the same file. In another session, the file is imported again.
    """
    PICKED.add(os.path.realpath(path))


def _within(root, path):
    """Whether `path` resolves to a location inside directory `root`.

    Resolves symlinks on both sides, so a link cannot be used to escape `root`.
    """
    root = os.path.realpath(root)
    path = os.path.realpath(path)
    try:
        return os.path.commonpath([root, path]) == root
    except ValueError:
        # Different drives (Windows) or a mix of absolute/relative: not inside.
        return False


def _project_root(start):
    """The Blender project root of `start`: the nearest parent holding `.blender_project`.

    Mirrors how Blender 5.3 finds a project — walking up from the .blend folder —
    since there is no Python call that returns it. None when `start` is in no project.
    """
    cur = os.path.realpath(start)
    while True:
        if os.path.isdir(os.path.join(cur, ".blender_project")):
            return cur
        parent = os.path.dirname(cur)
        if parent == cur:
            return None
        cur = parent


def read(path):
    """The text of a .bn file. Raises OSError, with a `strerror` to show.

    A path of a `use` is written by whoever made the text: it may name a pipe or a
    device, that would hold Blender for ever, or a file larger than its memory. Only
    a regular file is read, and no more of it than a source may hold.
    """
    # Not to wait: opening a pipe that nobody writes to would already never return
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_BINARY", 0))
    with os.fdopen(fd, "rb") as f:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise OSError(0, "not a regular file")
        data = f.read(MAX_SOURCE_BYTES + 1)
    if len(data) > MAX_SOURCE_BYTES:
        raise OSError(0, f"larger than {MAX_SOURCE_BYTES // 2 ** 20} MiB")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        raise OSError(0, "not a UTF-8 text") from None


def find(name, folders):
    """Path of name.bn in the first folder that has it, or None.

    The resolved file must stay inside its folder (`name` is a bare identifier,
    but this keeps the guarantee local to the lookup).
    """
    for folder in folders:
        if not folder:
            continue
        base = bpy.path.abspath(folder)
        path = os.path.normpath(os.path.join(base, name + ".bn"))
        if os.path.isfile(path) and _within(base, path):
            return path
    return None


def load(name, source, folders=None):
    """(text, filename) of a module. Raises LookupError with the reason.

    A `use` with no source looks in `folders` after the texts, the module folders when not given.
    """
    if source is None:
        text = bpy.data.texts.get(name + ".bn")
        if text is not None:
            return text.as_string(), text.name
        path = find(name, FOLDERS if folders is None else folders)
        if path is None:
            raise LookupError(f"no text '{name}.bn' in this file, nor {name}.bn in a module folder; "
                              f"for an external file: use {name} from \"//path/{name}.bn\"")
        try:
            return read(path), path
        except OSError as e:
            raise LookupError(f"cannot read '{path}': {e.strerror}") from None
    if source.startswith(("http://", "https://")):
        # A shared .bn must not reach the network: download the module and use it as a file
        raise LookupError(f"a module is a file, not a URL: download it and use {name} from \"//path/{name}.bn\"")
    if source.startswith(("./", "../")):
        raise LookupError(f"a path relative to the .blend starts with '//', as elsewhere in Blender: "
                          f"'//{source.removeprefix('./')}'")
    if "{project_root}" in source:
        if not bpy.data.filepath:
            raise LookupError("'{project_root}' resolves from the project of the .blend: save the file first")
        root = _project_root(os.path.dirname(bpy.data.filepath))
        if root is None:
            raise LookupError("'{project_root}': this .blend is in no Blender project "
                              "(no '.blender_project' folder in any parent)")
        path = os.path.normpath(source.replace("{project_root}", root))
        if "{" in path:
            raise LookupError(f"'{source}': only '{{project_root}}' is supported in a module path")
        if not _within(root, path):
            raise LookupError(f"'{source}': a module stays inside the project; '..' may not escape it")
    elif source.startswith("//"):
        if not bpy.data.filepath:
            raise LookupError("'//' resolves from the .blend folder: save the file first")
        root = os.path.dirname(bpy.data.filepath)
        path = os.path.normpath(bpy.path.abspath(source))
        if not _within(root, path):
            raise LookupError(f"'{source}': a module stays inside the .blend folder; "
                              "'..' may not escape it")
    elif os.path.isabs(source) and os.path.realpath(source) in PICKED:
        path = source
    elif os.path.isabs(source):
        raise LookupError(f"'{source}': absolute paths are not allowed; use a '//…' path "
                          "relative to the .blend, or place the module in a module folder")
    else:
        raise LookupError(f"'{source}': expected a '//…' path relative to the .blend; "
                          "asset libraries are not yet supported")
    try:
        return read(path), source
    except OSError as e:
        raise LookupError(f"cannot read '{source}': {e.strerror}") from None


def install_path(name, folder):
    """Where `install` writes the module `name`: name.bn in the module folder. Raises LookupError.

    `name` comes from the `// @module` line of a file anyone may have written: it must be an
    identifier, and the path it makes must stay in the folder, as `find` would read it.
    """
    if not is_bare(name):
        raise LookupError(f"'{name}' is not a module name: an identifier (letters, digits, _)")
    if not folder:
        raise LookupError("no Module Folder: set one in Edit > Preferences > Add-ons > Base Node, "
                          "where `use name` finds name.bn")
    base = bpy.path.abspath(folder)
    if not os.path.isdir(base):
        raise LookupError(f"the Module Folder '{base}' is not a folder: create it, or choose another "
                          "in the preferences of Base Node")
    path = os.path.normpath(os.path.join(base, name + ".bn"))
    if os.path.islink(path) or (os.path.lexists(path) and not os.path.isfile(path)):
        raise LookupError(f"'{path}' is not a regular file: it is left as it is")
    if not _within(base, path):
        raise LookupError(f"'{path}' is not inside the Module Folder")
    return path


def installed(name, folder, source):
    """(path, state) of the module `name` in the folder: state is "new" when no file has that
    name, "same" when it holds this source, "other" when it holds another text. Raises LookupError."""
    path = install_path(name, folder)
    if not os.path.lexists(path):
        return path, "new"
    try:
        return path, "same" if read(path) == source else "other"
    except OSError:
        return path, "other"


def install(name, folder, source, overwrite=False):
    """Write `source` as name.bn in the module folder, for `use name` to find it in every file.

    Returns (path, written): written is False when the file already holds this source. A file
    of that name that holds another text is replaced only with `overwrite`. Raises LookupError.
    """
    path, state = installed(name, folder, source)
    if state == "same":
        return path, False
    if state == "other" and not overwrite:
        raise LookupError(f"'{path}' already exists, with another text: tick Overwrite to replace it")
    # Written beside it, then moved over it: a failed write leaves the old module whole
    temp = os.path.join(os.path.dirname(path), f".{name}.bn.part")
    try:
        with open(temp, "w", encoding="utf-8", newline="") as f:
            f.write(source)
        os.replace(temp, path)
    except OSError as e:
        if os.path.lexists(temp):
            os.remove(temp)
        raise LookupError(f"cannot write '{path}': {e.strerror}") from None
    return path, True


def shared(module):
    """The (name, source) by which another file finds this module too, or None.

    Only the standard library bundled with the add-on is found in every file: a text of the
    .blend, a module folder of the preferences or a file next to the .blend is this user's alone.
    """
    name, source = module
    stdlib = os.path.join(STDLIB, name + ".bn")
    if not os.path.isfile(stdlib):
        return None
    if source is None:
        # The texts of the .blend come first: a text of that name is not the stdlib's module
        path = None if bpy.data.texts.get(name + ".bn") is not None else find(name, FOLDERS)
    else:
        # File > Import keeps the path of a module found next to the imported file
        path = source if os.path.isabs(source) else None
    try:
        return (name, None) if path is not None and os.path.samefile(path, stdlib) else None
    except OSError:
        return None


def graph_name(tree):
    """The name a text calls a group by: its own, or that of the module's graph it was built from."""
    return tree.get(GRAPH) or tree.name


def template_of(tree):
    """(types, positions of the inputs of each type parameter) of a template's group, or None."""
    raw = tree.get(TYPES)
    if not raw:
        return None
    try:
        tags = json.loads(raw)
        return list(tags["types"]), [list(i) for i in tags["inputs"]]
    except (ValueError, KeyError, TypeError):
        return None


def module_of(tree):
    """(name, source) of the module a group was built from by a `use`, or None."""
    name = tree.get(MODULE)
    return (name, tree.get(SOURCE) or None) if name else None
