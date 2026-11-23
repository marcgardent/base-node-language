"""Command-line interface (CLI) for base-node.

The commands of the language:
  base-node fmt [--check] <files.bn>
  base-node parse <files.bn>
  base-node ast <file.bn>

A host library adds its own commands, and options to these: it is a module with
`extend(subparsers, commands)`, declared by its distribution as an entry point of the group
`base_node.cli` (see PLUGINS). `main(argv, plugins)` takes the modules themselves, for a host
library run from a checkout rather than installed.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

from base_node import EDITION, BnError, __version__, format_source, parse

# The entry points of the host libraries installed: each names a module with
# extend(subparsers, commands), `commands` the parsers of the commands above by name
PLUGINS = "base_node.cli"


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
    """Format .bn files or verify canonical formatting.

    `args.rewrite(content, path)`, when a host library's option sets it, writes the text instead of
    the formatter alone."""
    exit_code = 0
    for path_str in args.files:
        p = Path(path_str)
        if not p.is_file():
            print(f"Error: file not found '{path_str}'", file=sys.stderr)
            exit_code = 1
            continue
        try:
            content = p.read_text(encoding="utf-8")
            if args.rewrite is not None:
                formatted = args.rewrite(content, p)
            else:
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


def installed_plugins() -> list:
    """The modules of the host libraries installed that add to the command line, by entry point name."""
    from importlib.metadata import entry_points

    return [ep.load() for ep in sorted(entry_points(group=PLUGINS), key=lambda ep: ep.name)]


def main(argv: list[str] | None = None, plugins: list | None = None) -> int:
    """Run base-node with the commands of the language and those `plugins` add (default: the
    host libraries installed)."""
    parser = argparse.ArgumentParser(
        prog="base-node",
        description="Base Node (.bn) — CLI tool for node graph manipulation",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__} (Language Edition {EDITION})",
    )
    subparsers = parser.add_subparsers(dest="subcommand", required=True)

    # fmt
    parser_fmt = subparsers.add_parser("fmt", help="Format .bn files")
    parser_fmt.add_argument("--check", action="store_true", help="Check formatting without modifying files")
    parser_fmt.add_argument("files", nargs="+", help=".bn files to format")
    parser_fmt.set_defaults(func=cmd_fmt, rewrite=None)

    # parse
    parser_parse = subparsers.add_parser("parse", help="Check syntax of .bn files")
    parser_parse.add_argument("files", nargs="+", help=".bn files to parse")
    parser_parse.set_defaults(func=cmd_parse)

    # ast
    parser_ast = subparsers.add_parser("ast", help="Export AST as JSON")
    parser_ast.add_argument("file", help=".bn file to export")
    parser_ast.set_defaults(func=cmd_ast)

    commands = {"fmt": parser_fmt, "parse": parser_parse, "ast": parser_ast}
    for plugin in installed_plugins() if plugins is None else plugins:
        plugin.extend(subparsers, commands)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
