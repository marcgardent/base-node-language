"""Blender's nodes for the .bn language: a text checked into a resolved node graph, and the targets
a text fits. Without bpy: the add-on answers for Blender itself (its host/schema.py)."""

from __future__ import annotations

from ._core import (EDITION, MAX_HEIGHT, MAX_NESTING, MAX_SOURCE_BYTES, STDLIB_VERSION, BnError, Diagnostic,
                    __version__, format_source, parse, to_source, tokenize, too_deep)
from .header import Header, header
from .targets import (Inference, Issue, Target, check_target, check_targets, infer, load_target, promise_names,
                      target_names, translate, variant_names)
from .typecheck import check, deprecations


def compile_source(source, schema, filename="<text>", load=None, warnings=None):
    """Parse and check a .bn source. Returns the graphs, raises BnError.

    `load(name, source)` finds the modules of its `use` lines, and `warnings` is a list the warnings
    of a valid source are added to: see typecheck.check.
    """
    try:
        return check(parse(source, filename), schema, filename, load, warnings)
    except RecursionError:
        # The parser's limits keep the checker far from it; a caller deep in its own stack may not be
        raise too_deep(filename) from None


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
    "deprecations",
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
    "promise_names",
    "variant_names",
    "check_target",
    "check_targets",
    "infer",
    "translate",
]
