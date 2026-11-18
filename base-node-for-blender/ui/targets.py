"""A text's targets in the editor: the ones its `// @target` promises, the ones it fits.

A text promises nothing unless it says so: the panel then only tells which targets accept it.
With a promise, the highlight colors what it uses outside and the panel lists where.
"""

from ..lang.header import directives
from ..lang.targets import target_names

# text name -> (source, Inference or None, issues of the promise)
_cache = {}


def promised(text):
    """The targets the head of `text` promises (`// @target a, b`), the unknown ones left out."""
    known = set(target_names())
    for name, value, _line, _col in directives(text.as_string()):
        if name == "target":
            return [w for w in (p.strip().strip('"') for p in value.split(",")) if w in known]
    return []


def state(text):
    """(Inference, issues of the promise) of `text`; None and [] when it does not parse."""
    source = text.as_string()
    cached = _cache.get(text.name)
    if cached is not None and cached[0] == source:
        return cached[1], cached[2]
    from ..lang.errors import BnError
    from ..lang.parser import parse
    from ..lang.targets import check_targets, infer

    try:
        file = parse(source, text.name)
    except (BnError, RecursionError):
        _cache[text.name] = (source, None, [])
        return None, []
    promise = promised(text)
    result = (infer(file), check_targets(file, promise) if promise else [])
    _cache[text.name] = (source, *result)
    return result
