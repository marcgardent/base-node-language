"""Highlighting of .bn texts: translucent boxes over keywords, calls, types and values.

The Text Editor colors only the languages it knows, in C; this draws over
the text instead of recoloring it. Types take the color of their socket.
"""

import bpy

from ..lang.colors import rgb
from ..lang.lexer import span_at, tokenize, width
from ..blender.schema import TREE_KINDS, TYPES
from ..blender.sugar import FUNCS
from . import actions, draw, prefs, targets

ALPHA = 0.22
SWATCH = 0.6  # a frame color shows itself, more opaque
ERROR = (1.0, 0.25, 0.25, 0.95)  # the bar under an error
WARNING = (1.0, 0.7, 0.2, 0.95)  # the bar under a warning: the text is valid with it

COLORS = {
    "keyword": (0.65, 0.40, 0.95),
    "node": (0.30, 0.55, 1.00),
    "function": (0.20, 0.80, 0.80),
    "literal": (1.00, 0.60, 0.20),
    "comment": (0.50, 0.50, 0.50),
    "namespace": (0.00, 0.78, 0.65),
    "stdlib_func": (0.00, 0.78, 0.65),
    "local_func": (0.95, 0.75, 0.20),
    "warning": (0.95, 0.30, 0.25),
}

# Blender's default socket colors
SOCKETS = {
    "Float": (0.63, 0.63, 0.63), "Int": (0.35, 0.55, 0.36), "Bool": (0.80, 0.65, 0.84),
    "Vector": (0.39, 0.39, 0.78), "Color": (0.78, 0.78, 0.16), "Rotation": (0.65, 0.39, 0.78),
    "Matrix": (0.72, 0.20, 0.52), "String": (0.44, 0.70, 1.00), "Menu": (0.40, 0.40, 0.40),
    "Geometry": (0.00, 0.84, 0.64), "Shader": (0.39, 0.78, 0.39), "Object": (0.93, 0.62, 0.36),
    "Collection": (0.96, 0.96, 0.96), "Material": (0.92, 0.46, 0.51), "Image": (0.39, 0.22, 0.39),
    "Texture": (0.62, 0.31, 0.64), "Font": (0.82, 0.71, 0.55), "Sound": (0.55, 0.71, 0.82),
    "Scene": (0.80, 0.80, 0.80), "Mask": (0.60, 0.60, 0.30), "Text": (0.70, 0.70, 0.70), "Bundle": (0.50, 0.50, 0.50), "Closure": (0.50, 0.50, 0.50),
}


def classify(tokens, context=None):
    """(token, color key) for the tokens worth a box, from one line's tokens."""
    ctx = context or {}
    declared = ctx.get("declared", set())
    mode = ctx.get("mode", "standard")
    allowed_nodes = ctx.get("allowed_nodes")
    allowed_types = ctx.get("allowed_types")

    out = []
    settings = 0  # depth of the brackets of a call's settings the token is in, on this line
    for i, t in enumerate(tokens):
        prev = tokens[i - 1].kind if i else None
        nxt = tokens[i + 1] if i + 1 < len(tokens) else None
        if t.kind == "[":
            settings += 1
        elif t.kind == "]" and settings:
            settings -= 1
        if t.kind == "KEYWORD":
            out.append((t, "literal" if t.text in ("true", "false") else "keyword"))
        elif t.kind in ("NUMBER", "STRING", "OPEN_STRING"):
            out.append((t, "literal"))
        elif t.kind == "COMMENT":
            out.append((t, "comment"))
        elif t.kind == "COLOR" and rgb(t.text[1:]):
            out.append((t, rgb(t.text[1:])))
        elif t.kind == "::":
            out.append((t, "namespace"))
        elif t.kind == "IDENT":
            # `use`, `as`, and `from` are keywords on a use line: `use curves2d as c2 from "…"`
            is_use_line = tokens[0].text == "use"
            if is_use_line:
                if t.text in ("use", "as", "from"):
                    out.append((t, "keyword"))
                else:
                    out.append((t, "namespace"))
            elif nxt is not None and nxt.kind == "::":
                out.append((t, "namespace"))
            elif prev == "::":
                out.append((t, "stdlib_func"))
            elif t.text in TREE_KINDS and nxt is not None and nxt.text == "graph":
                out.append((t, "keyword"))
            elif t.text in TYPES and prev in (":", "->"):
                if allowed_types is not None and t.text not in allowed_types:
                    out.append((t, "warning"))
                else:
                    out.append((t, t.text))
            elif nxt is not None and nxt.kind in ("(", "["):
                if t.text in declared:
                    out.append((t, "local_func" if mode == "origin" else "function"))
                elif t.text in FUNCS:
                    out.append((t, "function"))
                else:
                    if allowed_nodes is not None and t.text not in allowed_nodes:
                        out.append((t, "warning"))
                    else:
                        out.append((t, "node"))
            elif prev == "KEYWORD" and tokens[i - 1].text == "graph":
                out.append((t, "local_func" if mode == "origin" else "node"))
            elif settings and (nxt is None or nxt.kind != ":"):
                # An enum value in a call's settings: `Math[ADD]`
                out.append((t, "literal"))
    return out


def span_boxes(space, row, start, end, lh):
    """(x0, y0, x1, y1) boxes of the characters [start, end) of a 0-based line, one per screen row."""
    x0, y0 = draw.char_box(space, row, start)
    x1, y1 = draw.char_box(space, row, end)
    if y1 == y0:
        return [(x0, y0, x1, y0 + lh)]
    # Wrapped: one box per character keeps each on its row
    out = []
    for c in range(start, end):
        cx, cy = draw.char_box(space, row, c)
        nx, ny = draw.char_box(space, row, c + 1)
        if ny == cy:
            out.append((cx, cy, nx, cy + lh))
    return out


def boxes(space, row, tokens, context=None):
    """{color key: [(x0, y0, x1, y1)]} for one 0-based text line."""
    lh = draw.line_height(space)
    out = {}
    for t, color in classify(tokens, context):
        out.setdefault(color, []).extend(span_boxes(space, row, t.col - 1, t.col - 1 + width(t), lh))
    return out


def underlines(space, region, diagnostics):
    """(x0, y0, x1, y1) bars under what each diagnostic of the shown text points to."""
    text = space.text
    lh = draw.line_height(space)
    thick = max(1, round(2 * bpy.context.preferences.system.ui_scale))
    out = []
    for d in diagnostics:
        row = d.line - 1
        if d.file != text.name or not 0 <= row < len(text.lines):
            continue  # an error of a module it uses, or of a line gone since
        _, y = draw.char_box(space, row, 0)
        if not -lh <= y <= region.height + lh and not space.show_word_wrap:
            continue  # scrolled away
        start, end = span_at(text.lines[row].body, d.col)
        for x0, y0, x1, _y1 in span_boxes(space, row, start, end, lh):
            # A cell past the line's end has no width: give it half a line's height
            out.append((x0, y0 + 1, max(x1, x0 + lh // 2), y0 + 1 + thick))
    return out


def draw_highlight():
    space = bpy.context.space_data
    text = space.text
    if not actions.is_bn(text) or not prefs.get().highlight:
        return
    region = bpy.context.region
    found = {}

    p = prefs.get()
    mode = getattr(p, "highlight_mode", "standard")

    # Fast scan of text for declared local graphs: the name after `graph`, a string read as any
    declared = set()
    for line in text.lines:
        if " graph " in line.body:
            tokens = tokenize(line.body, strict=False)
            for t, after in zip(tokens, tokens[1:]):
                if t.kind == "KEYWORD" and t.text == "graph" and after.kind in ("IDENT", "STRING"):
                    declared.add(after.text)
                    break

    # What the text's `// @target` allows: what it uses outside is drawn as a warning
    allowed_nodes = allowed_types = None
    promised = targets.promised(text)
    if promised:
        from ..blender.schema import key
        from ..blender.targets import accepted

        allowed_nodes, allowed_types = set(FUNCS), set()
        for name in promised:
            allowed_nodes.update(accepted(name, "node"))
            allowed_types.update(accepted(name, "type"))
        # The graphs a text calls by their key are not nodes
        allowed_nodes.update(key(g) for g in declared)

    context = {
        "mode": mode,
        "declared": declared,
        "allowed_nodes": allowed_nodes,
        "allowed_types": allowed_types,
    }

    for row in draw.visible_rows(space, region):
        tokens = tokenize(text.lines[row].body, strict=False)[:-1]
        for color, rects in boxes(space, row, tokens, context).items():
            found.setdefault(color, []).extend(rects)

    active_colors = dict(COLORS)
    if hasattr(p, "color_stdlib"):
        active_colors["namespace"] = tuple(p.color_stdlib)
        active_colors["stdlib_func"] = tuple(p.color_stdlib)
    if hasattr(p, "color_local"):
        active_colors["local_func"] = tuple(p.color_local)
    if hasattr(p, "color_warning"):
        active_colors["warning"] = tuple(p.color_warning)

    for color, rects in found.items():
        if isinstance(color, tuple):
            draw.rects(rects, (*color, SWATCH))
        else:
            draw.rects(rects, (*(active_colors.get(color) or SOCKETS.get(color, active_colors["comment"])), ALPHA))


def draw_errors():
    space = bpy.context.space_data
    text = space.text
    diagnostics = actions.DIAGNOSTICS.get(text.name) if actions.is_bn(text) else None
    if diagnostics:
        draw.rects(underlines(space, bpy.context.region, diagnostics), ERROR)
    warnings = actions.LINT.get(text.name) if actions.is_bn(text) else None
    if warnings:
        draw.rects(underlines(space, bpy.context.region, warnings), WARNING)


def draw_overlay():
    draw_highlight()
    draw_errors()  # over the highlight


_handler = None


def register():
    global _handler
    _handler = bpy.types.SpaceTextEditor.draw_handler_add(draw_overlay, (), "WINDOW", "POST_PIXEL")


def unregister():
    global _handler
    if _handler is not None:
        bpy.types.SpaceTextEditor.draw_handler_remove(_handler, "WINDOW")
        _handler = None
