"""What a .bn file says of itself: the `// @name value` lines at its head.

    // @module mesh_maps
    // @title Mesh maps
    // @author Marc
    // @license MIT

The head is the comment and blank lines before the first `use` or graph. `@module`,
`@version` and `@edition` are those of the standard library, `@target` the targets the file
promises to fit, which the host says. A directive this module does not know is left alone, for
other tools to read; one it knows is checked. `@edition` is the language's: a text of an edition
this reader does not know is refused, here and by the parser (`edition_error`). A host has directives of its own, saying what it
may do with the file: `read_head` checks that each is written once, with a value, and gives them
back as written, for the host to judge.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .errors import BnError, Diagnostic
from .lexer import string_literal
from .names import is_bare

TEXT = ("title", "author", "license", "version", "edition")
KNOWN = {"module", "target", *TEXT}
# The editions of the language this reader knows, the latest last: a text that names none is of the latest
EDITIONS = ("2026",)

DIRECTIVE = re.compile(r"//\s*@(?P<name>[A-Za-z_][A-Za-z0-9_-]*)(?P<space>\s*)(?P<value>.*)$")


@dataclass
class Header:
    """The directives of a file. `lines` keeps the line of each directive written."""
    module: str | None = None
    version: str | None = None
    target: list = field(default_factory=list)  # the targets promised, none when not written
    edition: str | None = None
    title: str | None = None
    author: str | None = None
    license: str | None = None
    lines: dict = field(default_factory=dict)


def directives(source):
    """[(name, value, line, col of the value)] of the head of the source, as written."""
    out = []
    for number, raw in enumerate(source.splitlines(), 1):
        text = raw.strip()
        if not text:
            continue
        if not text.startswith("//"):
            break
        m = DIRECTIVE.match(text)
        if m is None or (m.group("value") and not m.group("space")):
            continue  # a comment, or `// @target"x"`: not a directive
        col = raw.index(text) + m.start("value") + 1
        out.append((m.group("name"), m.group("value").strip(), number, col))
    return out


def unquote(value):
    r"""A name written in a directive: a string, its escapes read as in any string
    (`"say \"hi\""` is `say "hi"`), or a bare one as written. None when it is neither, or empty."""
    if value.startswith('"'):
        return string_literal(value) or None
    return value if is_bare(value) else None


def unquoted(value):
    """A directive's free text: the string it is, its escapes read, when it is one, else as written."""
    text = string_literal(value) if value.startswith('"') else None
    return value if text is None else text


def unknown_edition(value):
    return f"@edition '{value}': not an edition this reader knows ({', '.join(EDITIONS)})"


def edition_error(source, filename="<text>"):
    """The Diagnostic of the `@edition` of a source when this reader does not know that edition, else None."""
    for name, value, line, col in directives(source):
        if name == "edition":
            if value and unquoted(value) not in EDITIONS:
                return Diagnostic(filename, line, col, unknown_edition(unquoted(value)))
            return None  # the first one written is the file's: a second is an error of the head
    return None


def read_head(source, filename="<text>", targets=(), extra=()):
    """(Header, get, diagnostics) of the head of a .bn source: nothing is raised.

    `targets` are the names the caller accepts after `@target`: with none, any name is read. A
    caller whose targets are more than a list of names gives a function instead: of a name as
    written, why it is refused (what follows `@target '<name>': `) or None. A name is written
    `name`, `name@version` or either with words after it, spaces apart: what the version and the
    words mean is the caller's.
    `extra` are the directives of the caller: `get(name)` gives (value, line, col) of a directive
    as written, the value being None when it is not written, and the caller adds to the
    diagnostics what it finds.
    """
    h = Header()
    diags = []

    def error(line, col, message):
        diags.append(Diagnostic(filename, line, col, message))

    written = {}
    for name, value, line, col in directives(source):
        if name not in KNOWN and name not in extra:
            continue
        if name in written:
            error(line, col, f"@{name} is already set on line {written[name][1]}")
            continue
        written[name] = (value, line, col)
        h.lines[name] = line
        if not value:
            error(line, col, f"@{name} needs a value")

    def get(name):
        value, line, col = written.get(name, ("", 0, 0))
        return (value, line, col) if value else (None, line, col)

    for name in TEXT:
        value = get(name)[0]
        setattr(h, name, unquoted(value) if value else value)
    _value, line, col = get("edition")
    if h.edition is not None and h.edition not in EDITIONS:
        error(line, col, unknown_edition(h.edition))
    value, line, col = get("target")
    if value is not None:
        known, at = targets, col
        for part in value.split(","):
            word = " ".join(unquoted(part.strip()).split())
            where = at + len(part) - len(part.lstrip())
            at += len(part) + 1
            if callable(known):
                why = known(word)
            else:
                why = f"one of {', '.join(known)}" if known and word not in known else None
            if why is not None:
                error(line, where, f"@target '{word}': {why}")
            elif word not in h.target:
                h.target.append(word)
    value, line, col = get("module")
    if value is not None:
        name = unquote(value)
        if name is None or not is_bare(name):
            error(line, col, f"@module '{value}': a module is named by an identifier "
                             "(letters, digits, _), its file being <name>.bn")
        else:
            h.module = name
    return h, get, diags


def header(source, filename="<text>", targets=()):
    """The checked Header of a .bn source. Raises BnError on a malformed directive."""
    h, _get, diags = read_head(source, filename, targets)
    if diags:
        raise BnError(diags)
    return h
