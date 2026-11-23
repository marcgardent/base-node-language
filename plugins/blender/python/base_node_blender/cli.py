"""What Blender's library adds to the command line of base-node (base_node_cli.cli).

  base-node fmt --names <files.bn>
  base-node check [--target <name>[,<name>]] <files.bn>
  base-node docs [--core <checkout of the core>] [--root .] [--out <root>/site/reference]

Installed, base-node finds this module by the entry point its distribution declares (group
`base_node.cli`). From a checkout, `python -m base_node_blender.cli` runs base-node with it.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from base_node_cli.cli import main as core_main

from . import BnError, check_targets, deprecations, header, infer, load_target, parse, precision_warnings


def module_loader(folder: Path):
    """load(name, source) of the modules a text in `folder` uses: a `from` path relative to it, else
    `<name>.bn` beside it, else the standard library."""
    from .targets import STDLIB_DIRS

    def load(name: str, source: str | None) -> tuple[str, str]:
        if source is not None:
            found = [folder / source.removeprefix("//")]
        else:
            found = [folder / f"{name}.bn"] + [d / f"{name}.bn" for d in STDLIB_DIRS]
        for path in found:
            if path.is_file():
                return path.read_text(encoding="utf-8"), str(path)
        raise LookupError(f"no module '{name}'")
    return load


def blender_version(content: str, filename: str) -> str | None:
    """The version of Blender a text promises in its `@target` (`blender@5.2-lts` is 5.2), else None."""
    for t in header(content, filename).target or ():
        m = re.fullmatch(r"blender@(\d+\.\d+)(?:-lts)?(?: \S+)?", t)
        if m:
            return m.group(1)
    return None


def names(content: str, path: Path) -> str:
    """The text with the inputs of Blender's nodes by name, as the canonical form has them: each value by
    position goes to the input Blender's sockets give it, read from the backend of the Blender the text
    promises (`@target blender@5.2-lts`), else of the newest. No Blender is needed."""
    from .backend import BackendSchema, versions
    from .naming import name_inputs

    version = blender_version(content, path.name)
    schema = BackendSchema(version if version in versions() else None)
    return name_inputs(content, schema, path.name, module_loader(path.resolve().parent))


def cmd_check(args: argparse.Namespace) -> int:
    """Check each .bn file against the targets it promises (`@target`, or --target).

    --target takes what a text may promise (`blender`, `blender@5.3 gltf`), and the aliases a text may
    not: `blender@latest`, `blender@lts`, the version each names in this version of the tool.

    A file that promises no target fits whatever accepts it: the targets that do are printed.
    The calls of a graph marked deprecated are warned of, and so is a number Blender cannot keep as
    written (a 32-bit float): warnings fail nothing."""
    exit_code = 0
    given = [" ".join(t.split()) for t in args.target.split(",")] if args.target else None
    try:
        for t in given or ():
            load_target(t)
    except ValueError as ex:
        print(f"Error: {ex}", file=sys.stderr)
        return 1

    for path_str in args.files:
        p = Path(path_str)
        if not p.is_file():
            print(f"Error: file not found '{path_str}'", file=sys.stderr)
            exit_code = 1
            continue
        try:
            content = p.read_text(encoding="utf-8")
            file_ast = parse(content, p.name)
            promised = given or header(content, p.name, file_ast).target
            # A warning stops nothing: the file is still what the lines below say of it
            said = deprecations(file_ast, p.name) + precision_warnings(file_ast, p.name)
            for warning in sorted(said, key=lambda d: (d.line, d.col)):
                print(warning, file=sys.stderr)
            if not promised:
                print(f"{path_str}:")
                for line in infer(file_ast).lines():
                    print(f"  {line}")
                continue
            issues = check_targets(file_ast, promised)
            if issues:
                print(f"Outside {', '.join(promised)} in '{path_str}':", file=sys.stderr)
                for i in issues:
                    print(f"  - {i}", file=sys.stderr)
                exit_code = 1
            else:
                print(f"OK ({', '.join(promised)}): {path_str}")
        except BnError as err:
            print(f"Syntax error in '{path_str}':\n{err}", file=sys.stderr)
            exit_code = 1
        except Exception as ex:
            print(f"Unexpected error in '{path_str}': {ex}", file=sys.stderr)
            exit_code = 1
    return exit_code


def core_checkout() -> Path:
    """The checkout the core (base_node) is imported from: its python/ folder's parent."""
    import base_node

    return Path(base_node.__file__).resolve().parents[2]


def cmd_docs(args: argparse.Namespace) -> int:
    """Write the reference pages of the site from the checkouts of the core and of this library."""
    from .refdoc import build

    root = Path(args.root)
    out = Path(args.out) if args.out else root / "site" / "reference"
    try:
        written = build(root, out, Path(args.core) if args.core else core_checkout())
    except (FileNotFoundError, BnError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    print(f"wrote {len(written)} pages to {out}")
    return 0


def extend(subparsers, commands: dict) -> None:
    """Add Blender's commands and options to base-node (base_node_cli.cli.main)."""
    commands["fmt"].add_argument(
        "--names", dest="rewrite", action="store_const", const=names,
        help="Write the inputs of Blender's nodes by name, as Blender's sockets go (no Blender needed)")

    parser_check = subparsers.add_parser("check", help="Check syntax and the targets a file promises")
    parser_check.add_argument(
        "--target", default=None,
        help="Targets to check against, comma separated, as 'blender@latest' or 'blender gltf' "
             "(default: the file's @target; none: list those it fits)"
    )
    parser_check.add_argument("files", nargs="+", help=".bn files to check")
    parser_check.set_defaults(func=cmd_check)

    parser_docs = subparsers.add_parser("docs", help="Write the reference pages of the site")
    parser_docs.add_argument("--core", help="The checkout of the core, whose spec/ holds the language's pages "
                                            "(default: the one base_node is imported from)")
    parser_docs.add_argument("--root", default=".", help="The checkout of this library (default: .)")
    parser_docs.add_argument("--out", help="Where to write them (default: <root>/site/reference)")
    parser_docs.set_defaults(func=cmd_docs)


def main(argv: list[str] | None = None) -> int:
    """base-node with Blender's commands, whatever is installed."""
    return core_main(argv, plugins=[sys.modules[__name__]])


if __name__ == "__main__":
    sys.exit(main())
