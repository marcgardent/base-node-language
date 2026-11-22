"""How a name is written in code: what a bare identifier is, the reserved words, and the key of a
name that is not an identifier.

One rule for the lexer, which reads a name, and for the printer, which writes one bare or quoted:
an identifier starts with `_` or a letter and goes on with letters, digits and `_`, as Unicode's
XID_Start and XID_Continue say (`·`, the dot product, aside), from the tables of identifiers.py,
which the Rust core holds too (rust/src/ast.rs).
"""

import functools
from bisect import bisect_right

from .identifiers import CONTINUE, START

RESERVED = {"graph", "return", "true", "false", "and", "or", "xor", "not", "dot", "cross", "inf", "nan"}

ASCII_START = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz_")
ASCII_CONTINUE = ASCII_START | frozenset("0123456789")


def starts_name(c):
    """Whether an identifier may start with the character `c`."""
    if c < "\x80":
        return c in ASCII_START
    return bisect_right(START, ord(c)) % 2 == 1


def goes_on_name(c):
    """Whether an identifier may go on with the character `c`."""
    if c < "\x80":
        return c in ASCII_CONTINUE
    return bisect_right(CONTINUE, ord(c)) % 2 == 1


def is_identifier(s):
    """What the lexer reads as one name: `height`, `_2`, `ρ_θ_φ`; not `2d`, `a b`, `a·b`, `x²`."""
    return bool(s) and starts_name(s[0]) and all(goes_on_name(c) for c in s[1:])


def is_bare(s):
    """A name the printer writes as it is: an identifier, not a reserved word. Any other is quoted
    where the grammar takes a quoted name, or written by its key."""
    return s not in RESERVED and is_identifier(s)


def is_word(s):
    """A name written bare where a value goes, an enum value or a material: bare, and not `_`,
    which is no value there. Any other is a string."""
    return s != "_" and is_bare(s)


@functools.lru_cache(maxsize=4096)  # asked for every key, on each check while typing
def snake(name):
    """A name as written in text: `Base Color` -> `base_color`. Lowercase, each run of characters
    an identifier does not hold one `_`, a `_` before a first character no identifier starts with,
    and after a reserved word: always a bare identifier."""
    words, gap = [], False
    for c in name.lower():
        if goes_on_name(c):
            if gap and words:
                words.append("_")
            words.append(c)
            gap = False
        else:
            gap = True
    s = "".join(words).strip("_")
    if not s or not starts_name(s[0]):
        s = "_" + s
    return s + "_" if s in RESERVED else s


def key(name):
    """How a parameter or graph is named in code: itself when it can be, else snake_case.

    A name that is not its own key is written quoted where it is declared:
    `"Fur Density": Float`, then used as `fur_density`.
    """
    return name if is_bare(name) else snake(name)
