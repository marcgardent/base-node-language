"""A text's targets in the editor: the ones its `// @target` promises, the ones it fits.

A text promises nothing unless it says so: the panel then only tells which targets accept it.
With a promise, the highlight colors what it uses outside and the panel lists where.
"""

from ..lang.header import directives, unquoted
from ..blender.targets import promise_refusal

# text name -> (source, Inference or None, issues of the promise)
_cache = {}


def promised(text):
    """The targets the head of `text` promises (`// @target blender@5.3 gltf`), those a text
    may not promise left out: the unknown ones, and the aliases of a command line."""
    for name, value, _line, _col in directives(text.as_string()):
        if name == "target":
            words = (" ".join(unquoted(p.strip()).split()) for p in value.split(","))
            return [w for w in words if promise_refusal(w) is None]
    return []


def state(text):
    """(Inference, issues of the promise) of `text`; None and [] when it does not parse."""
    source = text.as_string()
    cached = _cache.get(text.name)
    if cached is not None and cached[0] == source:
        return cached[1], cached[2]
    from ..lang.errors import BnError
    from ..lang.parser import parse
    from ..blender.targets import check_targets, infer

    try:
        file = parse(source, text.name)
    except (BnError, RecursionError):
        _cache[text.name] = (source, None, [])
        return None, []
    promise = promised(text)
    result = (infer(file), check_targets(file, promise) if promise else [])
    _cache[text.name] = (source, *result)
    return result
