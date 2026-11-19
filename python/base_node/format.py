"""Source -> canonical source, keeping the comments and the blank lines between statements."""

from . import ast, printer
from .lexer import tokenize
from .parser import parse, too_deep


def format_source(source, filename="<text>"):
    """The canonical text of `source`. Raises BnError when it does not parse."""
    try:
        return _format(source, filename)
    except RecursionError:
        raise too_deep(filename) from None


def _format(source, filename):
    file = parse(source, filename)
    rows = source.split("\n")

    comments = [c for c in tokenize(source, filename, strict=False) if c.kind == "COMMENT"]
    alone = {c.line for c in comments if not rows[c.line - 1][:c.col - 1].strip()}

    # (origin, text, starts): `starts` marks a line that may follow a kept blank line
    printed = []

    def walk(statements, pad):
        for s in statements:
            # An empty frame holding comments keeps its braces apart, around them
            if isinstance(s, ast.Frame) and (s.body or any(s.line < n < s.end for n in alone)):
                printed.append((s.line, pad + printer.frame_head(s), True))
                walk(s.body, pad + printer.INDENT)
                printed.append((s.end, pad + "}", False))
            elif isinstance(s, ast.Assign) and isinstance(s.value, ast.ZONES):
                printed.extend((o, t, k == 0) for k, (o, t) in enumerate(printer.zone_head(s, pad)))
                walk(s.value.body, pad + printer.INDENT)
                printed.append((s.value.end, pad + "}", False))
            else:
                printed.extend((o, t, k == 0) for k, (o, t) in enumerate(printer.statement(s, pad)))

    # Sorted, each use keeps its own line, and so its trailing comment. The comments on their own
    # lines between two uses go with the use under them; the ones above the first use stay at the
    # head of the file. The blank lines between uses stay where they were: the n-th use printed
    # follows a blank line when the n-th use of the source did, but comments brought up first
    # keep a blank line from the head comments of the file.
    gap = {}  # index into printed -> a blank line before it, in place of the source's
    moved = set()  # the lines of the comments printed with their use
    last_printed = {}  # use line -> index of the last printed line of that use
    in_order = sorted(file.uses, key=lambda u: u.line)
    above = {u.line: [] for u in in_order}
    for prev, u in zip(in_order, in_order[1:]):
        above[u.line] = [c for c in comments if c.line in alone and prev.line < c.line < u.line]
        moved.update(c.line for c in above[u.line])
    for n, u in enumerate(printer.sorted_uses(file.uses)):
        gap[len(printed)] = (n == 0 and bool(above[u.line])) or blank(
            rows, (above[in_order[n].line] or [in_order[n]])[0].line - 1)
        printed.extend((c.line, c.text.rstrip(), True) for c in above[u.line])
        printed.extend((o, t, k == 0) for k, (o, t) in enumerate(printer.use(u)))
        last_printed[u.line] = len(printed) - 1
    if file.uses:
        printed.append((max(u.line for u in file.uses), "", False))

    for i, g in enumerate(file.graphs):
        if i:
            printed.append((file.graphs[i - 1].end, "", False))
        printed.extend((o, t, k == 0) for k, (o, t) in enumerate(printer.header(g)))
        printed.extend((o, t, True) for o, t in printer.description(g))
        walk(g.body, printer.INDENT)
        printed.append((g.end, "}", False))

    own, trailing = [], {}
    uses_end = file.graphs[0].line if file.graphs else len(rows) + 1
    for c in comments:
        text = c.text.rstrip()
        if c.line in moved:
            continue
        if c.line not in alone:
            # After code: at the end of the printed line that code went to
            # (its own line first: sorted uses are printed out of order)
            on = [k for k, (o, t, _s) in enumerate(printed) if o == c.line and t]
            within = [u.line for u in file.uses if u.line <= c.line < uses_end]
            if on:
                at = max(on)
            elif within:
                # On a later line of a use split over several: at the end of that use
                at = last_printed[max(within)]
            else:
                at = max(k for k, (o, t, _s) in enumerate(printed) if o <= c.line and t)
            trailing.setdefault(at, []).append(text)
        else:
            own.append((c.line, text))

    out = []

    def emit(origin, text, starts, after_blank=None):
        if after_blank is None:
            after_blank = blank(rows, origin - 1)
        if starts and out and out[-1] and not out[-1].endswith("{") and after_blank:
            out.append("")
        out.append(text)

    j = 0
    for k, (origin, text, starts) in enumerate(printed):
        # A comment on its own line goes before the first line whose code came after it
        while j < len(own) and own[j][0] < origin:
            line, comment = own[j]
            emit(line, indent(text) + comment, True)
            j += 1
        emit(origin, "  ".join([text] + trailing.get(k, [])), starts, gap.get(k))
    for line, comment in own[j:]:
        emit(line, comment, True)
    return "\n".join(out) + "\n"


def indent(text):
    pad = text[:len(text) - len(text.lstrip())]
    # Before a closing brace, the comment belongs to the block it closes
    return pad + printer.INDENT if text.strip() == "}" else pad


def blank(rows, line):
    return 1 <= line <= len(rows) and not rows[line - 1].strip()
