"""The .bn language: text to a resolved node graph, without bpy."""

from __future__ import annotations

import sys

__version__ = "0.13.0"
EDITION = "2026"
STDLIB_VERSION = "0.13.0"

from .errors import BnError, Diagnostic
from .format import format_source
from .header import Header, header
from .lexer import tokenize
from .parser import MAX_HEIGHT, MAX_NESTING, MAX_SOURCE_BYTES, parse, too_deep
from .printer import to_source
from .targets import Inference, Issue, Target, check_target, check_targets, infer, load_target, target_names, translate
from .typecheck import check


def compile_source(source, schema, filename="<text>", load=None):
    """Parse and check a .bn source. Returns the graphs, raises BnError.

    `load(name, source)` finds the modules of its `use` lines: see typecheck.check.
    """
    try:
        return check(parse(source, filename), schema, filename, load)
    except RecursionError:
        # The parser's limits keep the checker far from it; a caller deep in its own stack may not be
        raise too_deep(filename) from None


# Register internal alias base_node.lang pointing to base_node
if __name__ + ".lang" not in sys.modules:
    sys.modules[__name__ + ".lang"] = sys.modules[__name__]

__all__ = [
    "__version__",
    "EDITION",
    "STDLIB_VERSION",
    "BnError",
    "MAX_SOURCE_BYTES",
    "MAX_NESTING",
    "MAX_HEIGHT",
    "Diagnostic",
    "parse",
    "check",
    "compile_source",
    "tokenize",
    "to_source",
    "format_source",
    "Header",
    "header",
    "Target",
    "Issue",
    "Inference",
    "load_target",
    "target_names",
    "check_target",
    "check_targets",
    "infer",
    "translate",
]
