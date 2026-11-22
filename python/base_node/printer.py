"""AST -> text, in the one canonical layout.

Printing a parsed canonical file gives it back unchanged. Comments are
not in the AST: `format.py` puts them back.
"""

from . import ast, colors
from .names import RESERVED, key

INDENT = "  "
WIDTH = 100

# Binding strength, for parentheses: unary minus is 4, `.socket` is 9. `cond ? a : b` binds loosest:
# it takes parentheses wherever the strength around it is 1 or more
PRECEDENCE = {"|>": 1, "or": 2, "xor": 2, "and": 3, "not": 4, "<": 5, "<=": 5, ">": 5, ">=": 5, "==": 5, "!=": 5,
              "+": 6, "-": 6, "*": 7, "/": 7, "⋅": 7, "×": 7}


def to_source(file):
    head = render(line for u in sorted_uses(file.uses) for line in use(u))
    return (head + "\n" if head else "") + "\n".join(render(graph(g)) for g in file.graphs)


def sorted_uses(uses):
    return sorted(uses, key=lambda u: (u.name, u.source or ""))


def use(u):
    """`use name as alias (a, b) from "source"`, one name per line when too long."""
    tail = f' from {quote(u.source)}' if u.source is not None else ""
    alias = f" as {u.alias}" if getattr(u, "alias", None) else ""
    line = f"use {u.name}{alias}" + (f" ({', '.join(u.names)})" if u.names else "") + tail
    if len(line) <= WIDTH or not u.names:
        return [(u.line, line)]
    return [(u.line, f"use {u.name}{alias} (")] + [(u.line, f"{INDENT}{n},") for n in u.names] + [(u.line, ")" + tail)]


def render(lines):
    return "".join(text + "\n" for _origin, text in lines)


def name(n):
    """A declared name: bare when it is its own key, else quoted."""
    return n if key(n) == n else quote(n)


def label(n):
    """An argument or socket name: bare when the lexer reads it as one identifier."""
    return n if n.isidentifier() and n not in RESERVED else quote(n)


def quote(s):
    r"""A string of the text, any string read back as it is: `"` and `\` escaped, the line breaks,
    the tabs and the other control characters by their escape, `\n` or `\u{1b}`."""
    return '"' + "".join(ESCAPED.get(c) or (f"\\u{{{ord(c):x}}}" if c < " " or c == "\x7f" else c) for c in s) + '"'


ESCAPED = {'"': '\\"', "\\": "\\\\", "\n": "\\n", "\t": "\\t", "\r": "\\r"}


def call_name(n):
    """A call's name: `m::"Big Blend"` when what follows the module is not a chain of identifiers."""
    module, sep, rest = n.partition("::")
    if not sep or all(part.isidentifier() and part not in RESERVED for part in rest.split("::")):
        return n
    return f"{module}::{quote(rest)}"


def graph(g):
    """A graph as (origin, text) lines; origin is the source line the printed line's code starts on."""
    lines = header(g) + description(g)
    for s in g.body:
        lines += statement(s)
    return lines + [(g.end, "}")]


def header(g):
    lead = f"{g.kind}{f'({args(g.settings)})' if g.settings else ''} graph {name(g.name)}{type_params(g)}"
    params = [param(p) for p in g.params]
    if g.single_output:
        outputs = g.outputs[0].type
    else:
        outputs = "(" + ", ".join(param(o) for o in g.outputs) + ")"
    head = f"{lead}({', '.join(params)}) -> {outputs} {{"
    # Panels always take one line per item, their contents one step further in
    paneled = g.param_tree is not None, g.output_tree is not None
    if len(head) <= WIDTH and not any(paneled):
        return [(g.line, head)]
    if params or paneled[0]:
        ins = g.tree("INPUT")
        lines = [(g.line, f"{lead}(")] + one_per_line(ins) + [(last_line(ins), f") -> {outputs} {{")]
    else:
        lines = [(g.line, f"{lead}() -> {outputs} {{")]
    if (len(lines[-1][1]) <= WIDTH and not paneled[1]) or g.single_output:
        return lines
    # Outputs too long for the closing line: one per line as well
    close = ") -> (" if len(lines) > 1 else f"{lead}() -> ("
    outs = g.tree("OUTPUT")
    return lines[:-1] + [(lines[-1][0], close)] + one_per_line(outs) + [(last_line(outs), ") {")]


def type_params(g):
    """`<T: Float | Vector, U: Int | Float>` of a template, nothing for a graph."""
    if not g.type_params:
        return ""
    return "<" + ", ".join(f"{t.name}: {' | '.join(t.types)}" for t in g.type_params) + ">"


def typed(e):
    """A call's name, with the types it is called with when written: `attribute_or<Vector>`."""
    type_args = getattr(e, "type_args", None)
    name = call_name(e.name)
    return f"{name}<{', '.join(type_args)}>" if type_args else name


def callee(e):
    """A call's name, its types and its settings, all before `(`: `Math[ADD]`, `f<Vector>`."""
    return typed(e) + (f"[{settings(e.settings)}]" if e.settings else "")


def settings(items):
    return ", ".join(setting(s) for s in items)


def setting(s):
    return f"{s.name}: {expr(s.value)}" if s.name is not None else expr(s.value)


def setting_lines(s, pad, tail):
    """A setting on a line of its own at `pad`, laid out like any value."""
    return layout(s.value, pad + (f"{s.name}: " if s.name is not None else ""), pad, tail, 0, s.line)


def call_lines(lead, e, origin, pad, close):
    """A call too long for its line, after `lead`, `close` after its last argument.

    Its arguments spread, one per line. Its settings stay with its name while that first line
    fits, else they spread first, one per line, the last one ending with `](`; the arguments then
    follow on that line while they fit there, else they spread in turn."""
    if not e.settings:
        return spread(f"{lead}{typed(e)}(", e.args, origin, pad, close)
    head = f"{lead}{callee(e)}("
    if e.args and len(head) <= WIDTH:
        return spread(head, e.args, origin, pad, close)
    lines = spread(f"{lead}{typed(e)}[", e.settings, origin, pad, "](", setting_lines)
    at, last = lines.pop()
    flat = last + args(e.args) + close
    if len(flat) <= WIDTH or not e.args:
        return lines + [(at, flat)]
    return lines + spread(last, e.args, at, pad, close)


def one_per_line(items, pad=INDENT * 2):
    """Params and panels one per line, separated by commas."""
    lines = []
    for i in items:
        if isinstance(i, ast.Panel):
            close = " {}," if not i.items else " {"
            head = f"{pad}{quote(i.name)}{f'({args(i.options)})' if i.options else ''}{close}"
            if len(head) > WIDTH and i.options:
                lines += spread(f"{pad}{quote(i.name)}(", i.options, i.line, pad, ")" + close)
            else:
                lines.append((i.line, head))
            if i.items:
                lines += one_per_line(i.items, pad + INDENT * 2) + [(i.end, pad + "},")]
        else:
            lines += param_lines(i, pad, ",")
    if lines:
        lines[-1] = (lines[-1][0], lines[-1][1][:-1])
    return lines


def last_line(items):
    """Source line of the end of a list: its last param, or the brace closing its last panel."""
    if not items:
        return 0
    last = items[-1]
    return last.end if isinstance(last, ast.Panel) else last.line


def description(g):
    return [(g.description_line, INDENT + quote(g.description))] if g.description is not None else []


def param(p):
    return param_head(p) + (f"({args(p.options)})" if p.options else "") + param_rest(p)


def param_head(p):
    return name(p.name) + (f" as {p.alias}" if p.alias is not None else "") + f": {p.type}"


def param_lines(p, pad, tail=""):
    """A param on a line of its own at `pad`; its options one per line when it is too long."""
    flat = pad + param(p) + tail
    if len(flat) <= WIDTH or not p.options:
        return [(p.line, flat)]
    return spread(f"{pad}{param_head(p)}(", p.options, p.line, pad, ")" + param_rest(p) + tail)


def param_rest(p):
    """What follows a param's type and options: its default and its range."""
    text = ""
    if p.default is not None:
        text += f" = {expr(p.default)}"
    if p.range is not None:
        lo, hi = (expr(b) if b is not None else "" for b in p.range)
        text += f" in {lo}..{hi}"
    return text


def statement(s, pad=INDENT):
    """A statement indented by `pad`; a frame with its body one step further in."""
    if isinstance(s, ast.Frame):
        head = frame_head(s)
        if not s.body:
            return [(s.line, f"{pad}{head}}}")]
        lines = [(s.line, pad + head)]
        for inner in s.body:
            lines += statement(inner, pad + INDENT)
        return lines + [(s.end, pad + "}")]
    if isinstance(s, ast.Assign) and isinstance(s.value, ast.BODIES):
        lines = body_head(s, pad)
        for inner in s.value.body:
            lines += statement(inner, pad + INDENT)
        return lines + [(s.value.end, pad + "}")]
    tail = f" {look_text(s.look)}" if s.look is not None else ""
    if isinstance(s, ast.Assign):
        return value(f"{pad}{s.name} = ", s.value, s.line, pad, tail)
    if isinstance(s.value, ast.Record):
        line = f"{pad}return ({args(s.value.fields)}){tail}"
        if len(line) <= WIDTH or not s.value.fields:
            return [(s.line, line)]
        return spread(f"{pad}return (", s.value.fields, s.line, pad, ")" + tail)
    return value(f"{pad}return ", s.value, s.line, pad, tail)


def look_text(look):
    """`@ "Label" #color hide mute`, each part only when there is one."""
    color = look.color if look.color is None or isinstance(look.color, str) else "#" + colors.spell(look.color)
    return " ".join(["@"] + [part for part in (look.label is not None and quote(look.label), color) if part]
                    + look.flags)


def body_head(s, pad):
    """`name = call(argument, item: value, …) -> {`, one argument per line when too long."""
    z = s.value
    if isinstance(z, ast.NamelessGraph):
        return nameless_head(s, pad)
    line = f"{pad}{s.name} = {callee(z)}({args(z.args)}) -> {{"
    if len(line) <= WIDTH or not z.args and not z.settings:
        return [(s.line, line)]
    return call_lines(f"{pad}{s.name} = ", z, s.line, pad, ") -> {")


def nameless_head(s, pad):
    """`name = graph(x: Float, …) -> Float {`, one input per line when too long."""
    c = s.value
    outs = signature_outputs(c.outputs, c.single_output)
    line = f"{pad}{s.name} = graph({', '.join(param(p) for p in c.params)}) -> {outs} {{"
    if len(line) <= WIDTH or not c.params:
        return [(s.line, line)]
    lines = [(s.line, f"{pad}{s.name} = graph(")]
    for p in c.params:
        lines += param_lines(p, pad + INDENT, ",")
    lines[-1] = (lines[-1][0], lines[-1][1][:-1])
    return lines + [(c.params[-1].line, f"{pad}) -> {outs} {{")]


def signature_outputs(outputs, single):
    return outputs[0].type if single else "(" + ", ".join(param(o) for o in outputs) + ")"


def frame_head(f):
    """`"Title" #color {`, each part only when there is one; `"Title" .. {` for more of a frame."""
    color = f.color if f.color is None or isinstance(f.color, str) else "#" + colors.spell(f.color)
    if f.continued:
        color = ".."
    return "".join(part + " " for part in (f.label is not None and quote(f.label), color) if part) + "{"


def value(lead, e, origin, pad, tail=""):
    """A statement's value after `lead`, `tail` (its look) at the end. A pipe always puts each
    step on a line of its own; anything else stays on one line while it fits (`layout`)."""
    if isinstance(e, ast.Pipe):
        return piped(e, lead, pad, tail, origin)
    return layout(e, lead, pad, tail, 0, origin)


def layout(e, lead, pad, tail="", outer=0, origin=0):
    """`lead`, `e` and `tail` as lines no wider than WIDTH where they can be.

    On one line when it fits; else the outermost structure spreads, one item per line one
    indent further in than `pad` (the indent of the line it starts on), and each of those
    lines follows the same rule. `outer` is the binding strength around `e`, as in `expr`."""
    flat = lead + expr(e, outer) + tail
    if len(flat) <= WIDTH:
        return [(origin, flat)]
    if parenthesized(e, outer):
        return layout(e, lead + "(", pad, ")" + tail, 0, origin)
    inner = pad + INDENT
    if isinstance(e, ast.Call) and (e.args or e.settings):
        outputs = f" -> {signature_outputs(e.outputs, e.single_output)}" if e.outputs is not None else ""
        lines = call_lines(lead, e, origin, pad, ")" + outputs + tail)
        if len(lines[-1][1]) > WIDTH and e.outputs and not e.single_output:
            # Declared outputs too long for the closing line: one per line as well
            lines = call_lines(lead, e, origin, pad, ") -> (")
            for i, o in enumerate(e.outputs):
                lines += param_lines(o, inner, ")" + tail if i == len(e.outputs) - 1 else ",")
        return lines
    if isinstance(e, ast.Tuple) and e.items:
        lines = [(origin, lead + "(")]
        for i, item in enumerate(e.items):
            last = i == len(e.items) - 1
            close = ("," if len(e.items) == 1 else "") + ")" + tail
            lines += layout(item, inner, inner, close if last else ",", 0, item.line)
        return lines
    if isinstance(e, ast.Member):
        return layout(e.target, lead, pad, f".{label(e.socket)}{tail}", 9, origin)
    if isinstance(e, ast.Pipe):
        return piped(e, lead, pad, tail, origin)
    if isinstance(e, ast.BinOp):
        return chained(e, lead, pad, tail, origin)
    if isinstance(e, ast.Neg):
        return layout(e.value, lead + "-", pad, tail, 9, origin)
    if isinstance(e, ast.Not):
        return layout(e.value, lead + "not ", pad, tail, PRECEDENCE["not"], origin)
    if isinstance(e, ast.Cond):
        # The condition after `lead`, then `? a` and `: b` each on a line of its own, like operators
        lines = layout(e.cond, lead, inner, "", 1, origin)
        lines += layout(e.then, f"{inner}? ", inner, "", 1, e.line)
        return lines + layout(e.orelse, f"{inner}: ", inner, tail, 0, e.orelse.line)
    return [(origin, flat)]


def parenthesized(e, outer):
    """Whether `expr(e, outer)` puts `e` in parentheses."""
    if isinstance(e, ast.Call):
        return e.outputs is not None and outer >= 9
    if isinstance(e, ast.Neg):
        return outer > 8
    if isinstance(e, ast.Not):
        return outer > PRECEDENCE["not"]
    if isinstance(e, ast.BinOp):
        return PRECEDENCE[e.op] < outer
    if isinstance(e, ast.Pipe):
        return PRECEDENCE["|>"] < outer
    if isinstance(e, ast.Cond):
        return outer > 0
    return False


def piped(e, lead, pad, tail, origin):
    """The head of a pipe after `lead`, then each step on a line of its own, one indent further in;
    a head too long for its line spreads one indent further in than the steps."""
    pipes = []
    while isinstance(e, ast.Pipe):
        pipes.append(e)
        e = e.left
    p = PRECEDENCE["|>"]
    # A head spread over lines goes one indent further in than the steps, which are not its own
    lines = layout(e, lead, pad + INDENT, "", p, origin)
    for i, step in enumerate(reversed(pipes)):
        last = i == len(pipes) - 1
        lines += layout(step.call, f"{pad}{INDENT}|> ", pad + INDENT, tail if last else "", p + 1, step.line)
    return lines


def left_outer(e):
    """The binding strength `expr` prints a BinOp's left operand with."""
    p = PRECEDENCE[e.op]
    mixed = isinstance(e.left, ast.BinOp) and e.left.op != e.op and {e.op, e.left.op} & {"⋅", "×", "xor"}
    return p + 1 if p == PRECEDENCE["=="] or mixed else p


def chained(e, lead, pad, tail, origin):
    """A chain of operators of one strength: its first operand after `lead`, then each operator
    with its operand on a line of its own, one indent further in (`+ b`); a first operand too long
    for its line spreads one indent further in than the operators."""
    p = PRECEDENCE[e.op]
    rest = []
    while True:
        rest.append(e)
        if not (isinstance(e.left, ast.BinOp) and PRECEDENCE[e.left.op] == p and left_outer(e) == p):
            break
        e = e.left
    lines = layout(e.left, lead, pad + INDENT, "", left_outer(e), origin)
    for i, op in enumerate(reversed(rest)):
        last = i == len(rest) - 1
        lines += layout(op.right, f"{pad}{INDENT}{op.op} ", pad + INDENT, tail if last else "", p + 1, op.line)
    return lines


def spread(head, items, origin, pad, close=")", item=None):
    """`head` then one argument (or what `item` lays out) per line one indent further in, the
    last one ending with `close`."""
    inner = pad + INDENT
    lines = [(origin, head)]
    for i, a in enumerate(items):
        lines += (item or argument)(a, inner, close if i == len(items) - 1 else ",")
    return lines


def argument(a, pad, tail):
    """An argument on a line of its own at `pad`, laid out like any value."""
    if a.name is None:
        return layout(a.value, pad, pad, tail, 0, a.line)
    options = (f" as {a.alias}" if a.alias else "") + (f"({args(a.options)})" if a.options else "")
    typed = f"{a.type.type} = " if a.type is not None else ""
    lead = f"{pad}{label(a.name)}{options}: {typed}"
    if len(lead + expr(a.value) + tail) > WIDTH and a.options:
        # Options first, one per line; the value after them, laid out from the line they end on
        alias = f" as {a.alias}" if a.alias else ""
        lines = spread(f"{pad}{label(a.name)}{alias}(", a.options, a.line, pad, f"): {typed}")
        origin, last = lines.pop()
        return lines + layout(a.value, last, pad + INDENT, tail, 0, origin)
    return layout(a.value, lead, pad, tail, 0, a.line)


def args(items):
    return ", ".join(arg(a) for a in items)


def arg(a):
    if a.name is None:
        return expr(a.value)
    options = (f" as {a.alias}" if a.alias else "") + (f"({args(a.options)})" if a.options else "")
    if a.type is not None:
        return f"{label(a.name)}{options}: {a.type.type} = {expr(a.value)}"
    return f"{label(a.name)}{options}: {expr(a.value)}"


def expr(e, outer=0):
    if isinstance(e, ast.Number):
        return str(int(e.value)) if e.is_int else repr(float(e.value))
    if isinstance(e, ast.String):
        return quote(e.value)
    if isinstance(e, ast.Bool):
        return "true" if e.value else "false"
    if isinstance(e, ast.Tuple):
        # One item takes a comma, else it reads as the item alone: `(LEFT,)`
        return "(" + ", ".join(expr(i) for i in e.items) + ("," if len(e.items) == 1 else "") + ")"
    if isinstance(e, ast.Ref):
        return e.name
    if isinstance(e, ast.Member):
        return f"{expr(e.target, 9)}.{label(e.socket)}"
    if isinstance(e, ast.Call):
        if e.outputs is None:
            return f"{callee(e)}({args(e.args)})"
        text = f"{callee(e)}({args(e.args)}) -> {signature_outputs(e.outputs, e.single_output)}"
        # Declared outputs end a call: picking one of them takes parentheses
        return f"({text})" if outer >= 9 else text
    if isinstance(e, ast.Neg):
        text = "-" + expr(e.value, 9)
        return f"({text})" if outer > 8 else text
    if isinstance(e, ast.Not):
        text = "not " + expr(e.value, PRECEDENCE["not"])
        return f"({text})" if outer > PRECEDENCE["not"] else text
    if isinstance(e, ast.Cond):
        # A ternary as condition or as the first branch takes parentheses; as the last one it chains
        text = f"{expr(e.cond, 1)} ? {expr(e.then, 1)} : {expr(e.orelse)}"
        return f"({text})" if outer > 0 else text
    if isinstance(e, (ast.BinOp, ast.Pipe)):
        op = e.op if isinstance(e, ast.BinOp) else "|>"
        p = PRECEDENCE[op]
        right = e.right if isinstance(e, ast.BinOp) else e.call
        # Comparisons do not chain: a comparison on the left takes parentheses. Neither do
        # `⋅ ×` beside `* /` nor `xor` beside `or`, which would be hard to read: `(n ⋅ u) * 2.0`
        mixed = isinstance(e.left, ast.BinOp) and e.left.op != op and {op, e.left.op} & {"⋅", "×", "xor"}
        left = expr(e.left, p + 1 if p == PRECEDENCE["=="] or mixed else p)
        text = f"{left} {op} {expr(right, p + 1)}"
        return f"({text})" if p < outer else text
    raise TypeError(e)
