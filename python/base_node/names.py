"""How a name is written in code: the reserved words, and the key of a name that is not an identifier."""

import functools
import re

RESERVED = {"graph", "return", "true", "false", "and", "or", "xor", "not", "dot", "cross", "inf", "nan"}


@functools.lru_cache(maxsize=4096)  # asked for every key, on each check while typing
def snake(name):
    """A name as written in text: `Base Color` -> `base_color`."""
    s = re.sub(r"\W+", "_", name.lower()).strip("_")
    if not s or s[0].isdigit():
        s = "_" + s
    return s + "_" if s in RESERVED else s


def key(name):
    """How a parameter or graph is named in code: itself when it can be, else snake_case.

    A name that is not its own key is written quoted where it is declared:
    `"Fur Density": Float`, then used as `fur_density`.
    """
    return name if name.isidentifier() and name not in RESERVED else snake(name)
