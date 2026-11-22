"""The inputs of Blender's nodes, written by name: a tool for writing a text.

A node's inputs go by name in a text, but those the canonical form leaves unnamed (the geometry a
node works on, the items of a switch, the values of a multi-input: typecheck.GraphChecker.unnamed).
`name_inputs` gives each value written by position the name of the input it goes to, as the checker
finds it for the node and its settings, and prints the text as the formatter does: comments and
blank lines kept. A text whose inputs are named is printed as it is, formatted.
"""

from dataclasses import fields, is_dataclass

from ._core import BnError, ast, format_source, tokenize
from .typecheck import Modules


def input_names(file, schema, filename="<text>", load=None):
    """{("arg" or "pipe", line, col): (name, call line, call col)} of the values by position of
    `file` (an ast.File) that go by name: an argument by its place, a piped value by its call's."""
    modules = Modules(schema, load)
    modules.fixes = {}
    try:
        modules.check(file, filename)
    except BnError:
        pass  # the other errors of the text name nothing
    return {k[1:]: v for k, v in modules.fixes.items() if k[0] == filename}


def name_inputs(source, schema, filename="<text>", load=None, at=None):
    """`source` with the inputs of its node calls named, formatted. Raises BnError when it does not parse.

    `at`, a 1-based (line, column), names only the inputs of the call under it: the innermost call
    whose parentheses hold it, or whose name it is on."""
    def edit(file):
        found = input_names(file, schema, filename, load)
        if at is not None:
            call = call_at(source, *at)
            found = {k: v for k, v in found.items() if v[1:] == call}
        if found:
            _rewrite(file, found)
    return format_source(source, filename, edit)


def call_at(source, line, col):
    """(line, col) of the name of the call under a 1-based cursor, or None."""
    tokens = [t for t in tokenize(source, strict=False) if t.kind != "COMMENT"]
    stack = []  # (index of the token that opens, index of the call's name or None)
    on = None
    for i, t in enumerate(tokens):
        if (t.line, t.col) > (line, col):
            break
        if t.kind == "IDENT" and t.line == line and t.col <= col <= t.col + len(t.text):
            on = i
        if t.kind in ("(", "[", "{"):
            stack.append((i, _name_before(tokens, i) if t.kind == "(" else None))
        elif t.kind in (")", "]", "}") and stack:
            stack.pop()
    if on is not None and on + 1 < len(tokens) and tokens[on + 1].kind in ("(", "[", "<"):
        return tokens[on].line, tokens[on].col
    for _opener, name in reversed(stack):
        if name is not None:
            return tokens[name].line, tokens[name].col
    return None


def _name_before(tokens, at):
    """The index of a call's name before its `(` at `at`, past its settings and its types, or None."""
    i = at - 1
    for opener, closer in (("[", "]"), ("<", ">")):
        if i >= 0 and tokens[i].kind == closer:
            depth = 0
            while i >= 0:
                depth += {closer: 1, opener: -1}.get(tokens[i].kind, 0)
                if depth == 0:
                    break
                i -= 1
            i -= 1
    return i if i >= 0 and tokens[i].kind == "IDENT" else None


def _rewrite(o, found):
    """Name in place the arguments of `found`; a piped value that goes by name becomes the call's
    first argument. Returns `o`, or what replaces it."""
    if isinstance(o, list):
        for i, x in enumerate(o):
            o[i] = _rewrite(x, found)
        return o
    if not is_dataclass(o) or isinstance(o, type):
        return o
    for f in fields(o):
        setattr(o, f.name, _rewrite(getattr(o, f.name), found))
    if isinstance(o, ast.Call):
        for a in o.args:
            if a.name is None and ("arg", a.line, a.col) in found:
                a.name = found[("arg", a.line, a.col)][0]
    if isinstance(o, ast.Pipe):
        call = o.call.target if isinstance(o.call, ast.Member) else o.call
        if isinstance(call, ast.Call) and ("pipe", call.line, call.col) in found:
            name = found[("pipe", call.line, call.col)][0]
            call.args.insert(0, ast.Arg(name, o.left, o.line, o.col))
            return o.call
    return o
