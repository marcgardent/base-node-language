"""The .bn language: its text read into a syntax tree, and written back. It knows no destination."""

from __future__ import annotations

import sys

__version__ = "1.0.0rc4"
STDLIB_VERSION = "1.0.0-rc.4"

from .errors import BnError, Diagnostic
from .format import format_source
from .header import EDITIONS, Header, header
from .lexer import tokenize
from .parser import MAX_HEIGHT, MAX_NESTING, MAX_SOURCE_BYTES, parse, too_deep
from .printer import to_source

EDITION = EDITIONS[-1]  # the latest edition: that of a text that names none

# Register internal alias base_node.lang pointing to base_node
if __name__ + ".lang" not in sys.modules:
    sys.modules[__name__ + ".lang"] = sys.modules[__name__]

__all__ = [
    "__version__",
    "EDITION",
    "EDITIONS",
    "STDLIB_VERSION",
    "BnError",
    "MAX_SOURCE_BYTES",
    "MAX_NESTING",
    "MAX_HEIGHT",
    "Diagnostic",
    "parse",
    "tokenize",
    "to_source",
    "format_source",
    "Header",
    "header",
]
