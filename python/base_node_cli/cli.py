"""Command-line interface (CLI) for base-node.

Supported commands:
  base-node fmt [--check] <files.bn>
  base-node parse <files.bn>
  base-node check [--target <name>[,<name>]] <files.bn>
  base-node ast <file.bn>
  base-node docs [--root .] [--out site/reference]
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

from base_node import EDITION, STDLIB_VERSION, BnError, __version__, format_source, parse
from base_node_blender import check_targets, deprecations, infer, load_target, old_spellings


def _serialize_ast(obj: Any) -> Any:
    """Convert AST dataclasses into serializable JSON structures."""
    if is_dataclass(obj):
        d = asdict(obj)
        d["__class__"] = obj.__class__.__name__
        return d
    if isinstance(obj, (list, tuple)):
        return [_serialize_ast(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _serialize_ast(v) for k, v in obj.items()}
    return obj


def cmd_fmt(args: argparse.Namespace) -> int:
    """Format .bn files or verify canonical formatting."""
    exit_code = 0
    for path_str in args.files:
        p = Path(path_str)
        if not p.is_file():
            print(f"Error: file not found '{path_str}'", file=sys.stderr)
            exit_code = 1
            continue
        try:
            content = p.read_text(encoding="utf-8")
            formatted = format_source(content, p.name)
            if args.check:
                if content != formatted:
                    print(f"Not formatted: {path_str}", file=sys.stderr)
                    exit_code = 1
                else:
                    print(f"OK (formatted): {path_str}")
            else:
                if content != formatted:
                    p.write_text(formatted, encoding="utf-8")
                    print(f"Formatted: {path_str}")
                else:
                    print(f"Unchanged: {path_str}")
        except BnError as err:
            print(f"Syntax error in '{path_str}':\n{err}", file=sys.stderr)
            exit_code = 1
        except Exception as ex:
            print(f"Error processing '{path_str}': {ex}", file=sys.stderr)
            exit_code = 1
    return exit_code


def cmd_parse(args: argparse.Namespace) -> int:
    """Parse .bn files syntax."""
    exit_code = 0
    for path_str in args.files:
        p = Path(path_str)
        if not p.is_file():
            print(f"Error: file not found '{path_str}'", file=sys.stderr)
            exit_code = 1
            continue
        try:
            content = p.read_text(encoding="utf-8")
            file_ast = parse(content, p.name)
            count = len(file_ast.graphs)
            print(f"Valid syntax: {path_str} ({count} graph{'s' if count > 1 else ''})")
        except BnError as err:
            print(f"Syntax error in '{path_str}':\n{err}", file=sys.stderr)
            exit_code = 1
        except Exception as ex:
            print(f"Unexpected error in '{path_str}': {ex}", file=sys.stderr)
            exit_code = 1
    return exit_code


def cmd_check(args: argparse.Namespace) -> int:
    """Check each .bn file against the targets it promises (`@target`, or --target).

    --target takes what a text may promise (`blender`, `blender@5.3 gltf`), and the aliases a text may
    not: `blender@latest`, `blender@lts`, the version each names in this version of the tool.

    A file that promises no target fits whatever accepts it: the targets that do are printed.
    The calls of a graph marked deprecated are warned of, and fail nothing. A zone written as it
    was before (`repeat(…) {`) is an error that says what to write: no target has a node of that name."""
    from base_node_blender import header

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
            for warning in deprecations(file_ast, p.name):
                print(warning, file=sys.stderr)
            old = old_spellings(file_ast, p.name)
            if old:
                print(f"Error in '{path_str}':\n{BnError(old)}", file=sys.stderr)
                exit_code = 1
                continue
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


def cmd_ast(args: argparse.Namespace) -> int:
    """Export the AST of a .bn file as JSON."""
    p = Path(args.file)
    if not p.is_file():
        print(f"Error: file not found '{args.file}'", file=sys.stderr)
        return 1
    try:
        content = p.read_text(encoding="utf-8")
        file_ast = parse(content, p.name)
        data = _serialize_ast(file_ast)
        print(json.dumps(data, indent=2, ensure_ascii=False))
        return 0
    except BnError as err:
        print(f"Syntax error in '{args.file}':\n{err}", file=sys.stderr)
        return 1
    except Exception as ex:
        print(f"Unexpected error in '{args.file}': {ex}", file=sys.stderr)
        return 1


def cmd_docs(args: argparse.Namespace) -> int:
    """Write the reference pages of the site from the repository."""
    from .refdoc import build

    root = Path(args.root)
    out = Path(args.out) if args.out else root / "site" / "reference"
    try:
        written = build(root, out)
    except (FileNotFoundError, BnError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    print(f"wrote {len(written)} pages to {out}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="base-node",
        description="Base Node (.bn) — CLI tool for node graph manipulation",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__} (Language Edition {EDITION}, Stdlib {STDLIB_VERSION})",
    )
    subparsers = parser.add_subparsers(dest="subcommand", required=True)

    # fmt
    parser_fmt = subparsers.add_parser("fmt", help="Format .bn files")
    parser_fmt.add_argument("--check", action="store_true", help="Check formatting without modifying files")
    parser_fmt.add_argument("files", nargs="+", help=".bn files to format")
    parser_fmt.set_defaults(func=cmd_fmt)

    # parse
    parser_parse = subparsers.add_parser("parse", help="Check syntax of .bn files")
    parser_parse.add_argument("files", nargs="+", help=".bn files to parse")
    parser_parse.set_defaults(func=cmd_parse)

    # check
    parser_check = subparsers.add_parser("check", help="Check syntax and the targets a file promises")
    parser_check.add_argument(
        "--target", default=None,
        help="Targets to check against, comma separated, as 'blender@latest' or 'blender gltf' "
             "(default: the file's @target; none: list those it fits)"
    )
    parser_check.add_argument("files", nargs="+", help=".bn files to check")
    parser_check.set_defaults(func=cmd_check)

    # ast
    parser_ast = subparsers.add_parser("ast", help="Export AST as JSON")
    parser_ast.add_argument("file", help=".bn file to export")
    parser_ast.set_defaults(func=cmd_ast)

    # docs
    parser_docs = subparsers.add_parser("docs", help="Write the reference pages of the site")
    parser_docs.add_argument("--root", default=".", help="The repository (default: .)")
    parser_docs.add_argument("--out", help="Where to write them (default: <root>/site/reference)")
    parser_docs.set_defaults(func=cmd_docs)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
