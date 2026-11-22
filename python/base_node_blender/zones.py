"""Blender's zones, as the text writes them.

The language has calls that take a body, `name(arguments) -> { … }`, and graphs with no name,
`graph(x: Float) -> Float { … }`: what they are is a host's to say. Here, `repeat`, `simulate` and
`foreach` are the calls that take a body, a Repeat, a Simulation and a For Each Geometry Element
zone, and a graph with no name is a Closure zone. What each body sees and returns, the checker says
(typecheck.py).
"""

from dataclasses import dataclass

from ._core import ast


@dataclass
class Repeat:
    """`repeat(count, state: start, …) -> { … return (state: next, …) }`: a Repeat zone.

    In the body the states are names, and `iteration` is the number of the current turn, from 0.
    """
    count: object
    states: list  # of Arg, all named
    body: list
    line: int
    col: int
    end: int = 0  # line of the closing brace


@dataclass
class Simulate:
    """`simulate(state: start, …) -> { … return (state: next, …, skip: c) }`: a Simulation zone.

    In the body the states are names, and `delta_time` is the time since the last step.
    """
    states: list  # of Arg, all named
    body: list
    line: int
    col: int
    end: int = 0  # line of the closing brace


@dataclass
class Foreach:
    """`foreach(geometry, domain: FACE, item: field, …) -> { … return (main: v, …, mesh: g, attribute: a, …) }`:
    a zone run for each element of its first argument.

    The named arguments are the domain, the selection and the input items; in the body `index`,
    `element` and the input items are names. What each returned field is, the checker says.
    """
    geometry: object
    args: list  # of Arg, all named
    body: list
    line: int
    col: int
    end: int = 0  # line of the closing brace


@dataclass
class Closure:
    """`graph(x: Float, …) -> Float { … return … }`, a graph with no name: a Closure zone.

    In the body the inputs are names, and the names outside are seen too: their values are captured.
    """
    params: list   # of Param
    outputs: list  # of Param
    single_output: bool
    body: list
    line: int
    col: int
    end: int = 0  # line of the closing brace


# The word of each zone, as a target lists it (targets/*.json, "zones")
WORDS = {Repeat: "repeat", Simulate: "simulate", Foreach: "foreach", Closure: "closure"}
# The calls that take a body
BODY_CALLS = ("repeat", "simulate", "foreach")
# How each is written, in the messages
WRITTEN = {"repeat": "r = repeat(10, state: start) -> { … }",
           "simulate": "s = simulate(state: start) -> { … }",
           "foreach": "f = foreach(geometry, domain: FACE, item: field) -> { … }",
           "closure": "f = graph(x: Float) -> Float { … }"}


def word(value):
    """The zone word of the value of an assignment, as the tree of the text holds it, or None."""
    if isinstance(value, ast.NamelessGraph):
        return "closure"
    if isinstance(value, ast.BodyCall) and value.name in BODY_CALLS:
        return value.name
    return None


def read(value):
    """The zone a call with a body or a graph with no name writes: (zone, None), or
    (None, (where, message)) when the call is not one of a zone, or not of its shape."""
    if isinstance(value, ast.NamelessGraph):
        return Closure(value.params, value.outputs, value.single_output, value.body,
                       value.line, value.col, value.end), None
    name, args = value.name, value.args
    if name not in BODY_CALLS:
        return None, (value, f"'{name}' takes no body: {', '.join(BODY_CALLS[:-1])} and {BODY_CALLS[-1]} do")
    where = value.body, value.line, value.col, value.end
    if name == "repeat":
        if not args or args[0].name is not None:
            return None, (value, "repeat expects iteration count first: repeat(10, state: start, …) -> { … }")
        if len(args) < 2:
            return None, (value, "repeat expects at least one state: repeat(10, state: start) -> { … }")
        if any(a.options for a in args):
            return None, (value, "repeat state does not take options")
        return Repeat(args[0].value, args[1:], *where), None
    if name == "simulate":
        if any(a.name is None for a in args):
            return None, (value, "simulate expects named states: simulate(state: start, …) -> { … }")
        return Simulate(args, *where), None
    # A state of repeat or simulate may take a key of its own; a foreach item not yet
    for a in args:
        if a.alias:
            return None, (a, f"'{a.name} as {a.alias}': 'as' only aliases an item of an item node")
    if not args or args[0].name is not None or any(a.name is None for a in args[1:]):
        return None, (value, "foreach expects geometry first, then named items: "
                             "foreach(geometry, domain: FACE, item: field, …) -> { … }")
    return Foreach(args[0].value, args[1:], *where), None


def old_spelling(name):
    """What to write in place of a call of that name with no body, as zones were written before
    the edition's last grammar: `repeat(…) {`, `closure(…) -> … {`. None for any other name."""
    if name in BODY_CALLS:
        return f"{name} takes a body after '->': {WRITTEN[name]}"
    if name == "closure":
        return f"closure(…) is now written as a graph with no name: {WRITTEN['closure']}"
    return None
