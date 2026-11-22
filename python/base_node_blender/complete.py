"""Suggestions at the text cursor, from the schema and the graph being written.

The text around the cursor is half typed, so only tokens are read, never
the parse tree: what comes just before the cursor says what may follow.
"""

import re
from dataclasses import dataclass

from ._core import colors, tokenize
from .targets import load_target, promise_names
from .schema import TREE_KINDS, TYPES, key, snake
from .sugar import COMPONENTS, FUNCS, VECTOR, WORDS

# Typing one of these opens the suggestions by itself
OPENERS = ("(", "[", ",", ".", ":", "#")

# Keywords that a value follows
KEYWORDS = ("return", "and", "or", "xor", "not")
OPERATORS = ("=", "+", "-", "*", "/", "<", "<=", ">", ">=", "==", "!=", "⋅", "·", "×", "?")


@dataclass(frozen=True)
class Item:
    label: str
    insert: str     # replaces the word being typed
    detail: str = ""
    kind: str = ""  # node, graph, function, input, setting, enum, output, local, param, type, keyword, color


@dataclass
class Outline:
    """A graph as far as its header can be read: enough to suggest its inputs."""
    kind: str
    name: str
    params: list   # (name, type), as declared
    outputs: list  # (name, type)
    body: int      # index of `{` in the token list, or None


@dataclass(frozen=True)
class Signature:
    """The prototype of the call the cursor is in: its inputs in parentheses, its settings in brackets."""
    name: str
    inputs: tuple   # (key, type, state): state is "given", "current" or "". In brackets: the settings
    outputs: tuple  # (key, type)
    col: int = 0    # 1-based column of the call's name


def complete(source, line, col, schema, load=None, asked=False):
    """(start column, items) at a 1-based cursor; an item replaces line[start:col].

    With `load` (see typecheck.check), the graphs of the `use` lines are suggested too.
    `asked` is a request of the user, not a key that opens the suggestions by itself:
    after a value in a call, the inputs left come with their comma."""
    lines = source.split("\n")
    if not 1 <= line <= len(lines):
        return col, []
    typed = lines[line - 1][:col - 1]
    prefix = typed[len(typed.rstrip("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_")):]
    start = col - len(prefix)
    if prefix[:1].isdigit():
        if not asked:
            return start, []
        prefix, start = "", col  # the number is a value: what may follow it
    header = targets_line(typed, col)
    if header is not None:
        return header
    tokens = tokenize("\n".join(lines[:line - 1] + [typed[:len(typed) - len(prefix)]]), strict=False)[:-1]
    if tokens and tokens[-1].kind in ("COMMENT", "OPEN_STRING"):
        return start, []
    if tokens and tokens[-1].kind == "COLOR":
        return start, matching([Item(name, name, "#" + code, "color") for name, code in colors.CSS.items()], prefix)
    items = context(source, line, tokens, schema, load).items(asked)
    return start, matching(items, prefix)


# A comment line so far: `//`, `// @tar`, `// @target gl`
# The name being typed may have a version and a variant: `blender@5.3 gltf`
TARGET_LINE = re.compile(r'\s*//(\s*(?:@\w*(?:\s+"?[\w@.-]*(?: [\w-]*)?)?)?)')


def targets_line(typed, col):
    """(start, items) for the line `// @target name`, or None when the line is not one."""
    m = TARGET_LINE.fullmatch(typed)
    if m is None:
        return None
    rest = m.group(1).strip().replace('"', "")
    items = [Item(f"@target {name}", f" @target {name}", load_target(name).description, "keyword")
             for name in promise_names()]
    return col - len(m.group(1)), [i for i in items if i.label.startswith(rest)]


def signature(source, line, col, schema, load=None):
    """The Signature of the innermost call open at a 1-based cursor, or None."""
    lines = source.split("\n")
    if not 1 <= line <= len(lines):
        return None
    tokens = tokenize("\n".join(lines[:line - 1] + [lines[line - 1][:col - 1]]), strict=False)[:-1]
    if not tokens or tokens[-1].kind in ("COMMENT", "OPEN_STRING"):
        return None
    return context(source, line, tokens, schema, load).signature()


def context(source, line, tokens, schema, load):
    tokens = [t for t in tokens if t.kind != "COMMENT"]
    everything = [t for t in tokenize(source, strict=False) if t.kind != "COMMENT"]
    # The file's own graphs last: they win over a group or a module graph of the same key
    graphs = existing(schema) + imported(everything, load) + outlines(everything)
    return Context(tokens, line, graphs, schema)


def product_sign(typed):
    """(start, end, sign) when `typed`, a line up to the cursor, ends with `dot ` or `cross ` used as a product.

    Only after an operand: `dot(a, b)` and a comment stay as they are.
    """
    if not typed.endswith(" "):
        return None
    tokens = tokenize(typed, strict=False)[:-1]
    if len(tokens) < 2:
        return None
    before, word = tokens[-2:]
    start, end = word.col - 1, word.col - 1 + len(word.text)
    operand = before.kind in ("IDENT", "NUMBER", "STRING", ")") or before.text in ("true", "false")
    if word.kind == "IDENT" and word.text in WORDS and operand and end == len(typed) - 1:
        return start, end, WORDS[word.text]
    return None


def matching(items, prefix):
    """Items found by `prefix` as Blender's Add menu search (Shift+A) finds nodes, best first.

    The label starting with what is typed comes first (`setpos`), then each piece of it the start of
    a word of the label, in any order (`texnoise`, `NoiTex`, `instpoint`, `noise_tex`), then the
    label containing it, then a word with one typo (`nosie`). Within each tier the items keep their
    order, the inputs of the call first; found by words, the labels with the fewest words come first
    (`posset`: SetPosition before SetHandlePositions)."""
    p = prefix.lower()
    if not p:
        return list(items)
    tiers = (
        (lambda s: s.lower().startswith(p), False),
        (lambda s: by_words(p, words(s)), True),
        (lambda s: p in s.lower(), False),
        (lambda s: by_typo(p, words(s)), True),
    )
    seen, out = set(), []
    for test, fewest_words in tiers:
        found = [item for item in items if item.label not in seen and test(item.label)]
        if fewest_words:
            found.sort(key=lambda item: len(words(item.label)))  # stable: ties keep their order
        for item in found:
            if item.label not in seen:
                seen.add(item.label)
                out.append(item)
    return out


WORD = re.compile(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+|\d+")


def words(label):
    """The words of a label, lower case: `PrincipledBSDF` -> principled, bsdf; `set_position` too."""
    return [w.lower() for part in re.split(r"[_\W]+", label) for w in WORD.findall(part)]


def by_words(typed, label_words):
    """True when every piece of `typed` (cut at `_`) is read as starts of distinct words, in any order."""
    pieces = [p for p in typed.split("_") if p]
    return bool(pieces) and _cover(pieces, tuple(label_words), frozenset())


def _cover(pieces, label_words, used):
    if not pieces:
        return True
    piece, rest = pieces[0], pieces[1:]
    for i, w in enumerate(label_words):
        if i in used:
            continue
        # The longest start first: `noitex` reads noi + tex before n + oitex
        for n in range(min(len(piece), len(w)), 0, -1):
            if piece[:n] != w[:n]:
                continue
            after = [piece[n:]] + rest if n < len(piece) else rest
            if _cover(after, label_words, used | {i}):
                return True
    return False


def by_typo(typed, label_words):
    """True when `typed`, four letters or more, is a word of the label (or its start) with one typo."""
    if len(typed) < 4:
        return False
    return any(edits(typed, w[:len(typed)]) <= 1 or edits(typed, w) <= 1 for w in label_words)


def edits(a, b):
    """Letters to change, add, remove or swap to turn `a` into `b` (Damerau–Levenshtein)."""
    if abs(len(a) - len(b)) > 1:
        return 2
    d = [[i + j if not i or not j else 0 for j in range(len(b) + 1)] for i in range(len(a) + 1)]
    for i in range(1, len(a) + 1):
        for j in range(1, len(b) + 1):
            d[i][j] = min(d[i - 1][j] + 1, d[i][j - 1] + 1, d[i - 1][j - 1] + (a[i - 1] != b[j - 1]))
            if i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                d[i][j] = min(d[i][j], d[i - 2][j - 2] + 1)
    return d[-1][-1]


def outlines(tokens):
    """Every graph of the file, from its header tokens."""
    found = []
    for i, t in enumerate(tokens):
        if t.kind != "KEYWORD" or t.text != "graph" or i + 1 >= len(tokens):
            continue
        kind = tree_kind(tokens, i)
        name = tokens[i + 1].text if tokens[i + 1].kind in ("IDENT", "STRING") else ""
        params, outputs, body = header(tokens, i)
        found.append(Outline(kind, name, params, outputs, body))
    return found


def tree_kind(tokens, i):
    """The tree kind before the `graph` at i, its settings `geometry(is_tool: true)` passed over."""
    j = i - 1
    if j >= 0 and tokens[j].kind == ")":
        depth = 0
        while j >= 0:
            depth += {")": 1, "(": -1}.get(tokens[j].kind, 0)
            if depth == 0:
                break
            j -= 1
        j -= 1
    return tokens[j].text if j >= 0 and tokens[j].kind == "IDENT" else ""


def header(tokens, i):
    """(params, outputs, index of the body's `{` or None) of the graph whose `graph` is at i."""
    params, outputs, body = [], [], None
    j = i + 2
    if j < len(tokens) and tokens[j].kind == "(":
        j, params = typed_names(tokens, j)
    if j < len(tokens) and tokens[j].kind == "->":
        j += 1
        if j < len(tokens) and tokens[j].kind == "(":
            j, outputs = typed_names(tokens, j)
        elif j < len(tokens) and tokens[j].kind == "IDENT":
            outputs = [(tokens[j].text, tokens[j].text)]
            j += 1
    if j < len(tokens) and tokens[j].kind == "{":
        body = j
    return params, outputs, body


def imported(tokens, load):
    """Outlines of the graphs that the `use` lines at the head of the file bring."""
    found = []
    i = 0
    while load and i + 1 < len(tokens) and tokens[i].text == "use" and tokens[i + 1].kind == "IDENT":
        name, names, source = tokens[i + 1].text, None, None
        i += 2
        if i < len(tokens) and tokens[i].kind == "(":
            names = set()
            while i < len(tokens) and tokens[i].kind != ")":
                if tokens[i].kind == "IDENT":
                    names.add(tokens[i].text)
                i += 1
            i += 1
        if i + 1 < len(tokens) and tokens[i].text == "from" and tokens[i + 1].kind == "STRING":
            source = tokens[i + 1].text
            i += 2
        try:
            text, _filename = load(name, source)
        except LookupError:
            continue
        module = [t for t in tokenize(text, strict=False) if t.kind != "COMMENT"]
        found += [g for g in outlines(module) if names is None or key(g.name) in names]
    return found


def existing(schema):
    """Outlines of the node groups already in the file, from the schema when it has them."""
    groups = getattr(schema, "groups", None)
    if groups is None:
        return []
    # By key: two sockets of one name are told apart as in a call
    return [Outline(kind, g.name, [(k, t) for _n, k, t in g.keys("INPUT")],
                    [(k, t) for _n, k, t in g.keys("OUTPUT")], None)
            for kind in TREE_KINDS for g in groups(kind).values() if not isinstance(g, list)]


def typed_names(tokens, j):
    """`(name: Type, ...)` from the `(` at j: (index after `)`, [(name, type)]).

    Panels are opened: `"Title" { … }` gives its sockets. A socket named with
    `"Seed" as seed_2: Int` gives its key, seed_2."""
    pairs = []
    j += 1
    braces = 0  # panels open
    while j < len(tokens) and (braces or tokens[j].kind not in (")", "{")):
        t = tokens[j]
        if t.kind == "STRING" and j + 1 < len(tokens) and tokens[j + 1].kind in ("{", "("):
            # A panel, its settings passed over
            j += 1
            if tokens[j].kind == "(":
                while j < len(tokens) and tokens[j].kind not in (")", "{"):
                    j += 1
                j += tokens[j].kind == ")" if j < len(tokens) else 0
            if j < len(tokens) and tokens[j].kind == "{":
                braces += 1
                j += 1
            continue
        if t.kind == "}":
            braces -= 1
            j += 1
            continue
        named = t.kind in ("IDENT", "STRING") and j + 2 < len(tokens)
        if named and tokens[j + 1].text == "as" and j + 4 < len(tokens) and tokens[j + 2].kind == "IDENT" \
                and tokens[j + 3].kind == ":" and tokens[j + 4].kind == "IDENT":
            pairs.append((tokens[j + 2].text, tokens[j + 4].text))
            j += 5
        elif named and tokens[j + 1].kind == ":" and tokens[j + 2].kind == "IDENT":
            pairs.append((t.text, tokens[j + 2].text))
            j += 3
        else:
            j += 1
    return (j + 1 if j < len(tokens) and tokens[j].kind == ")" else j), pairs


class Context:
    def __init__(self, tokens, line, graphs, schema):
        self.t = tokens
        self.line = line
        self.schema = schema
        self.graphs = {key(g.name): g for g in graphs if g.name}
        starts = [i for i, t in enumerate(tokens) if t.kind == "KEYWORD" and t.text == "graph"]
        self.g = None
        if starts:
            self.g = next((g for g in reversed(graphs) if g.name == tokens[starts[-1] + 1].text), None) \
                if starts[-1] + 1 < len(tokens) else None
        self.head = starts[-1] if starts else None
        self.kind = self.g.kind if self.g else "geometry"

    # Where the cursor is

    def body(self):
        """Index of the `{` of the graph body the cursor is in, or None."""
        if self.head is None:
            return None
        _params, _outputs, body = header(self.t, self.head)
        if body is None:
            return None
        depth = 0
        for tok in self.t[body:]:
            depth += {"{": 1, "}": -1}.get(tok.kind, 0)
        return body if depth > 0 else None

    def items(self, asked=False):
        t = self.t
        if self.head is None:
            return self.top_level()
        if header(t, self.head)[2] is None:
            # In the header: only types are ours to suggest
            return self.types() if t[-1].kind in (":", "->") else []
        body = self.body()
        if body is None:
            return self.top_level()
        return self.in_body(body, asked)

    def top_level(self):
        t = self.t
        if t and t[-1].kind == "IDENT" and t[-1].text in TREE_KINDS and (len(t) == 1 or t[-2].kind == "}"):
            return [Item("graph", "graph ", kind="keyword")]
        if t and t[-1].kind not in ("}",):
            return []
        return [Item(k, k + " graph ", "tree", "keyword") for k in TREE_KINDS]

    def in_body(self, body, asked=False):
        t = self.t
        last = t[-1]
        new_line = last.line < self.line
        call, opener = self.open_at(body)

        if opener == "[":
            # In a call's settings: no wire feeds them, only literals and enum values
            if last.kind == ":" and len(t) >= 3 and t[-2].kind == "IDENT" and t[-3].kind in ("[", ","):
                return self.setting_values(call, t[-2].text)
            if last.kind in ("[", ","):
                return self.settings(call)
            return []
        if last.kind == ".":
            return self.members(len(t) - 2, body)
        if last.kind == "|>":
            return [i for i in self.values(body) if i.kind in ("node", "graph", "function")]
        if call is not None and last.kind == ":" and len(t) >= 3 and t[-2].kind == "IDENT" \
                and t[-3].kind in ("(", ","):
            return self.values(body)
        if last.kind in ("(", ","):
            return (self.args(call) if call is not None else []) + self.values(body)
        if last.kind in OPERATORS or last.kind == ":" or (last.kind == "KEYWORD" and last.text in KEYWORDS):
            return self.values(body)
        if (new_line or last.kind == "{") and self.depth(body) == 0:
            return self.values(body) + [Item("return", "return ", kind="keyword")]
        if asked and call is not None and ends_value(last):
            # After a value: the next input, its comma written
            return [Item(i.label, ", " + i.insert, i.detail, i.kind) for i in self.args(call)]
        return []

    def signature(self):
        body = self.body()
        call, opener = self.open_at(body) if body is not None else (None, None)
        if call is None:
            return None
        t, name = self.t, self.t[call].text
        if opener == "[":
            return self.settings_signature(call)
        # What the call says so far: its named inputs, how many by position, the one being written
        named, current, positional = set(), None, 1 if call and t[call - 1].kind == "|>" else 0
        depth, starts = 0, True
        for i in range(self.inputs_at(call) or call + 1, len(t)):
            k = t[i].kind
            if k in ("(", "{", "["):
                depth += 1
            elif k in (")", "}", "]"):
                depth -= 1
            if depth != 1 or k == "(":
                continue
            if k == ",":
                current, starts = None, True
            elif starts and k == "IDENT" and i + 1 < len(t) and t[i + 1].kind == ":":
                named.add(t[i].text)
                current, starts = t[i].text, False
            elif starts and k != ":":
                positional, starts = positional + 1, False
        if key(name) in self.graphs:
            graph = self.graphs[key(name)]
            inputs = [(snake(n), ty) for n, ty in graph.params]
            outputs = [(snake(n), ty) for n, ty in graph.outputs]
        else:
            spec, props, _ = self.call_props(call)
            if spec is None:
                return None
            ins, outs = self.schema.sockets(self.kind, spec, props)
            inputs = [(k, s.type) for k, s in keyed(ins)]
            outputs = [(k, s.type) for k, s in keyed(outs)]
        by_position = [k for k, _ty in inputs if k not in named][:positional]
        state = lambda k: "current" if k == current else "given" if k in named or k in by_position else ""
        return Signature(name, tuple((k, ty, state(k)) for k, ty in inputs), tuple(outputs), t[call].col)

    def depth(self, body):
        d = 0
        for tok in self.t[body + 1:]:
            d += {"(": 1, ")": -1}.get(tok.kind, 0)
        return d

    def open_call(self, body):
        """Index of the name of the innermost unclosed call, or None."""
        return self.open_at(body)[0]

    def open_at(self, body):
        """(index of the name of the innermost unclosed call, "(" or "[": in its inputs or its settings),
        or (None, the bracket open there)."""
        stack = []
        for i in range(body + 1, len(self.t)):
            k = self.t[i].kind
            if k in ("(", "["):
                stack.append(i)
            elif k in (")", "]") and stack:
                stack.pop()
        if not stack:
            return None, None
        at = stack[-1]
        return self.name_before(at), self.t[at].kind

    def name_before(self, at):
        """The index of the call's name before its `(` or `[` at `at`: past its settings and its types."""
        t = self.t
        i = at - 1
        if t[at].kind == "(" and i >= 0 and t[i].kind == "]":
            depth = 0
            while i >= 0:
                depth += {"]": 1, "[": -1}.get(t[i].kind, 0)
                if depth == 0:
                    break
                i -= 1
            i -= 1
        if i >= 0 and t[i].kind == ">":
            while i >= 0 and t[i].kind != "<":
                i -= 1
            i -= 1
        return i if i >= 0 and t[i].kind == "IDENT" else None

    def inputs_at(self, name_at):
        """The index of the `(` of the call whose name is at `name_at`, past its types and settings, or None."""
        t = self.t
        i = name_at + 1
        for opener, closer in (("<", ">"), ("[", "]")):
            if i < len(t) and t[i].kind == opener:
                depth = 0
                while i < len(t):
                    depth += {opener: 1, closer: -1}.get(t[i].kind, 0)
                    if depth == 0:
                        break
                    i += 1
                i += 1
        return i if i < len(t) and t[i].kind == "(" else None

    # What may come there

    def values(self, body):
        out = [Item(name, name, self.t[call].text if call is not None else "", "local")
               for name, call in self.locals(body)]
        out += [Item(key(n), key(n), ty, "param") for n, ty in (self.g.params if self.g else [])]
        current = key(self.g.name) if self.g else None
        out += [Item(k, k + "(", "group", "graph") for k in sorted(self.graphs) if k != current]
        out += [Item(f, f + "(", "function", "function") for f in sorted(FUNCS)]
        out += [Item(n, n + "(", "node", "node") for n in self.schema.node_names(self.kind)]
        out += [Item(b, b, kind="keyword") for b in ("true", "false")]
        out += [Item("not", "not ", kind="keyword")]
        return out

    def locals(self, body):
        """(name, index of the call it is bound to or None) of each binding before the cursor."""
        t = self.t
        out = []
        for i in range(body + 1, len(t) - 1):
            # The binding being written is not a name yet
            if t[i].kind == "IDENT" and t[i + 1].kind == "=" and t[i].line < self.line \
                    and (t[i - 1].kind == "{" or t[i - 1].line < t[i].line):
                out.append((t[i].text, self.bound_call(i + 2)))
        return out

    def bound_call(self, i):
        """Index of the call a binding's value ends with, None for a formula or a plain name."""
        t = self.t
        depth, name = 0, None
        start_line = t[i - 1].line
        while i < len(t):
            tok = t[i]
            if depth == 0 and tok.line > start_line and tok.kind != "|>" and t[i - 1].kind not in ("|>", ","):
                break
            if tok.kind == "(":
                if depth == 0 and t[i - 1].kind == "IDENT":
                    name = i - 1
                depth += 1
            elif tok.kind == ")":
                depth -= 1
            elif depth == 0 and tok.kind in ("+", "-", "*", "/"):
                return None
            i += 1
        return name

    def call_props(self, name_at):
        """(spec, the settings its brackets write, for the sockets they make available, the inputs given
        by name in its parentheses)."""
        spec = self.schema.node(self.kind, self.t[name_at].text)
        props = self.written_settings(name_at, spec)[0] if spec else {}
        return spec, props, self.named_in(self.inputs_at(name_at))

    def named_in(self, at, closer=")"):
        """The names given `name: value` in the parentheses or brackets opened at `at`."""
        t, given = self.t, set()
        if at is None:
            return given
        depth = 0
        for i in range(at, len(t)):
            k = t[i].kind
            depth += {"(": 1, "[": 1, ")": -1, "]": -1}.get(k, 0)
            if depth == 0:
                break
            if depth == 1 and k == "IDENT" and i + 1 < len(t) and t[i + 1].kind == ":" and t[i - 1].kind in ("(", "[", ","):
                given.add(t[i].text)
        return given

    def written_settings(self, name_at, spec):
        """({setting: value} of the enum and boolean settings the call's brackets write, the settings given),
        a value by position going to the first enum setting that holds it."""
        t = self.t
        props, given = {}, set()
        at = name_at + 1
        if at < len(t) and t[at].kind == "<":
            while at < len(t) and t[at].kind != ">":
                at += 1
            at += 1
        if at >= len(t) or t[at].kind != "[":
            return props, given
        depth = 0
        for i in range(at, len(t)):
            k = t[i].kind
            depth += {"(": 1, "[": 1, ")": -1, "]": -1}.get(k, 0)
            if depth == 0:
                break
            if depth != 1 or t[i - 1].kind not in ("[", ","):
                continue
            if k == "IDENT" and i + 2 < len(t) and t[i + 1].kind == ":":
                given.add(t[i].text)
                prop, v = spec.props.get(t[i].text), t[i + 2]
            elif k in ("IDENT", "STRING"):
                prop = next((p for p in spec.props.values() if p.kind == "ENUM" and t[i].text in p.items), None)
                v = t[i]
                if prop is not None:
                    given.add(prop.name)
            else:
                continue
            if prop and prop.kind == "ENUM" and v.kind in ("IDENT", "STRING") and (not prop.items or v.text in prop.items):
                props[prop.name] = v.text
            elif prop and prop.kind == "BOOLEAN" and v.text in ("true", "false"):
                props[prop.name] = v.text == "true"
        return props, given

    def args(self, call):
        name = self.t[call].text
        if key(name) in self.graphs:
            # A group's sockets are named like a node's: snake_case
            return [Item(snake(n), snake(n) + ": ", ty, "input") for n, ty in self.graphs[key(name)].params]
        spec, props, given = self.call_props(call)
        if spec is None:
            return []
        inputs, _ = self.schema.sockets(self.kind, spec, props)
        return [Item(k, k + ": ", s.type, "input") for k, s in keyed(inputs) if k not in given]

    def settings(self, call):
        """In a call's brackets: the values of its enum settings not written yet, by position, then the
        names of its other settings."""
        spec = self.schema.node(self.kind, self.t[call].text) if call is not None else None
        if spec is None:
            return []
        _props, given = self.written_settings(call, spec)
        out = [Item(v, v if v.isidentifier() else f'"{v}"', p.name, "enum")
               for p in spec.props.values() if p.kind == "ENUM" and p.name not in given for v in p.items]
        out += [Item(p.name, p.name + ": ", p.kind.lower(), "setting")
                for p in [*spec.props.values(), *spec.data.values()] if p.name not in given]
        return out

    def setting_values(self, call, name):
        spec = self.schema.node(self.kind, self.t[call].text) if call is not None else None
        prop = spec.props.get(name) if spec else None
        if prop and prop.kind == "ENUM" and prop.items:
            return [Item(v, v if v.isidentifier() else f'"{v}"', prop.name, "enum") for v in prop.items]
        if prop and prop.kind == "BOOLEAN":
            return [Item(b, b, kind="keyword") for b in ("true", "false")]
        return []

    def settings_signature(self, call):
        """The settings of the node whose brackets the cursor is in, as a Signature."""
        spec = self.schema.node(self.kind, self.t[call].text)
        if spec is None:
            return None
        _props, given = self.written_settings(call, spec)
        settings = [*spec.props.values(), *spec.data.values()]
        return Signature(spec.name, tuple((p.name, p.kind.lower(), "given" if p.name in given else "")
                                          for p in settings), (), self.t[call].col)

    def members(self, at, body):
        t = self.t
        if at < 0:
            return []
        target = t[at]
        if target.kind == ")":
            depth = 0
            for i in range(at, body, -1):
                depth += {")": 1, "(": -1}.get(t[i].kind, 0)
                if depth == 0:
                    return self.outputs(i - 1) if t[i - 1].kind == "IDENT" else []
            return []
        if target.kind != "IDENT":
            return []
        for name, call in reversed(self.locals(body)):
            if name == target.text:
                return self.outputs(call) if call is not None else []
        for n, ty in self.g.params if self.g else []:
            if key(n) == target.text and ty in VECTOR:
                return components()
        return []

    def outputs(self, call):
        name = self.t[call].text
        if key(name) in self.graphs:
            outs = self.graphs[key(name)].outputs
            out = [Item(snake(n), snake(n), ty, "output") for n, ty in outs]
            return out + (components() if len(outs) == 1 and outs[0][1] in VECTOR else [])
        if name in FUNCS:
            return components() if name in ("normalize", "cross") else []
        spec, props, _ = self.call_props(call)
        if spec is None:
            return []
        _, outs = self.schema.sockets(self.kind, spec, props)
        out = [Item(k, k, s.type, "output") for k, s in keyed(outs)]
        return out + (components() if len(outs) == 1 and outs[0].type in VECTOR else [])

    def types(self):
        return [Item(ty, ty, kind="type") for ty in TYPES]


def ends_value(tok):
    """True when a value may end with the token: a name, a literal, a closed call."""
    return tok.kind in ("IDENT", "NUMBER", "STRING", ")") or tok.text in ("true", "false")


def keyed(sockets):
    """(text name, socket): the key, or the identifier when the key repeats."""
    keys = [s.key for s in sockets]
    return [(k if keys.count(k) == 1 else s.identifier, s) for k, s in zip(keys, sockets)]


def components():
    return [Item(c, c, "Float", "output") for c in COMPONENTS]
