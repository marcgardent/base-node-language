"""Recursive descent parser.

Precedence, loosest first: `|>`, `or xor`, `and`, `not`, comparisons, `+ -`,
`* / ⋅ ×`, unary `-`, then `.socket`. Statements need no separator: an
expression ends where the next token cannot continue it.
"""

import math

from . import ast
from .errors import BnError, Diagnostic
from .lexer import tokenize
from .sugar import COMPARE, WORDS

# Zones whose keyword is one only before `(…) {`
ZONE_WORDS = ("simulate", "foreach")


# The words of a node's look after `@`, in the order they are printed
LOOK_FLAGS = ("hide", "mute")


# What a reader accepts, the same in every implementation (spec/reference.md, "Limits"): a .bn text
# may come from anyone, and reading it must end with a tree or an error, never a crash or a hang
MAX_SOURCE_BYTES = 4 * 1024 * 1024  # of a source, in UTF-8
# Each bracket costs a parser its whole descent through the precedences: 32 of them stay under
# 400 kB of stack in the Rust crate (1 MiB is all a wasm32 module has); the deepest text of the
# third-party corpora opens 13
MAX_NESTING = 32  # brackets, blocks and prefix operators open at once
MAX_HEIGHT = 256  # of an expression: operators, calls and `.socket`s one inside another
MAX_INT = 2 ** 63 - 1


def too_deep(filename, line=1, col=1, limit=MAX_NESTING):
    return BnError([Diagnostic(filename, line, col, f"nested too deeply: at most {limit} levels")])


def parse(source, filename="<text>"):
    if len(source) > MAX_SOURCE_BYTES or len(source.encode("utf-8", "surrogatepass")) > MAX_SOURCE_BYTES:
        raise BnError([Diagnostic(filename, 1, 1, f"source too large: at most {MAX_SOURCE_BYTES // 2 ** 20} MiB")])
    try:
        return Parser(tokenize(source, filename), filename).file()
    except RecursionError:
        # The limits keep the parser far from it; a caller already deep in its own stack may not be
        raise too_deep(filename) from None


class Parser:
    def __init__(self, tokens, filename):
        self.tokens = tokens
        self.filename = filename
        self.i = 0
        self.nest = 0    # brackets and blocks open around the current token
        self.height = 0  # of the expression just read: 1 for a name, one more for each node above it
        self.closing = None  # token index of a `(` -> that of its `)`, made when first asked

    # Token helpers

    @property
    def tok(self):
        return self.tokens[self.i]

    def peek(self, offset=1):
        return self.tokens[min(self.i + offset, len(self.tokens) - 1)]

    def at(self, kind, text=None):
        t = self.tok
        return t.kind == kind and (text is None or t.text == text)

    def advance(self):
        t = self.tok
        self.i += 1
        return t

    def accept(self, kind, text=None):
        if self.at(kind, text):
            return self.advance()
        return None

    def expect(self, kind, text=None, what=None):
        if self.at(kind, text):
            return self.advance()
        self.fail(f"expected {what or text or kind}, found {describe(self.tok)}")

    def fail(self, message, tok=None):
        tok = tok or self.tok
        raise BnError([Diagnostic(self.filename, tok.line, tok.col, message)])

    # Limits

    def enter(self):
        """Inside one more bracket, block or prefix operator: what the parser recurses on."""
        self.nest += 1
        if self.nest > MAX_NESTING:
            raise too_deep(self.filename, self.tok.line, self.tok.col)

    def leave(self):
        self.nest -= 1

    def tall(self, height, tok=None):
        """The height of the expression just made: what those who walk the tree recurse on."""
        if height > MAX_HEIGHT:
            tok = tok or self.tok
            raise too_deep(self.filename, tok.line, tok.col, MAX_HEIGHT)
        self.height = height
        return height

    # Grammar

    def file(self):
        f = ast.File()
        while self.at_use():
            f.uses.append(self.use())
        while not self.at("EOF"):
            if self.at_use():
                self.fail("use statements must be at the top of the file, before graphs")
            f.graphs.append(self.graph())
        if not f.graphs:
            self.fail("empty file: no graph found")
        return f

    def at_use(self):
        # `use` is a keyword only here, so that a socket or a name may still be called use
        return self.at("IDENT", "use") and self.peek().kind == "IDENT"

    def use(self):
        t = self.advance()
        name = self.advance()
        alias = None
        if self.accept("IDENT", "as"):
            alias = self.expect("IDENT", what="module alias").text
        names = None
        if self.accept("("):
            names = []
            while not self.accept(")"):
                names.append(self.expect("IDENT", what="graph name").text)
                if not self.accept(","):
                    self.expect(")")
                    break
            if not names:
                self.fail("empty list: write use " + name.text + " for the whole module", t)
        source = None
        if self.accept("IDENT", "from"):
            source = self.expect("STRING", what="quoted source").text
        return ast.Use(name.text, names, source, t.line, t.col, alias=alias)

    def graph(self):
        kind = self.expect("IDENT", what="tree kind (geometry, shader, compositor)")
        settings = self.args(named_only=True) if self.accept("(") else []
        self.expect("KEYWORD", "graph")
        name = self.accept("STRING") or self.expect("IDENT", what="graph name")
        type_params = self.type_params() if self.accept("<") else []
        self.expect("(")
        param_tree = self.typed_list(")", header=True)
        self.expect("->")
        if self.accept("("):
            output_tree, single = self.typed_list(")", header=True), False
        else:
            t = self.expect("IDENT", what="return type")
            output_tree, single = [ast.Param(t.text, t.text, t.line, t.col)], True
        params, outputs = ast.flatten(param_tree), ast.flatten(output_tree)
        self.expect("{")
        description = None
        if self.at_description():
            description = self.advance()
        body = []
        while not self.at("}"):
            if self.at("EOF"):
                self.fail("'}' expected before end of file")
            if self.at_description():
                self.fail("graph description must be on the first line of its body")
            body.append(self.statement())
        end = self.advance()
        g = ast.Graph(kind.text, name.text, params, outputs, single, body, kind.line, kind.col, end.line)
        g.settings = settings
        g.type_params = type_params
        if any(isinstance(i, ast.Panel) for i in param_tree):
            g.param_tree = param_tree
        if any(isinstance(i, ast.Panel) for i in output_tree):
            g.output_tree = output_tree
        if description is not None:
            g.description, g.description_line = description.text, description.line
        return g

    def type_params(self):
        """`T: Float | Vector, U: Int | Float>` after `<`, which is consumed: a template's types."""
        out = []
        while True:
            t = self.expect("IDENT", what="type parameter name, such as T")
            if not self.accept(":"):
                self.fail(f"a type parameter lists its types: <{t.text}: Float | Vector>")
            types = [self.expect("IDENT", what="type").text]
            while self.accept("|"):
                types.append(self.expect("IDENT", what="type after '|'").text)
            out.append(ast.TypeParam(t.text, types, t.line, t.col))
            if not self.accept(","):
                self.expect(">", what="'>' after the type parameters")
                return out

    def at_type_args(self):
        """`<Vector>(` or `<Float, Color>(` after a call's name: the types of a template."""
        if not self.at("<") or self.peek().kind != "IDENT":
            return False
        i = 2
        while self.peek(i).kind == ",":
            if self.peek(i + 1).kind != "IDENT":
                return False
            i += 2
        return self.peek(i).kind == ">" and self.peek(i + 1).kind == "("

    def at_description(self):
        # A string alone: `"Title" {` and `"Title" #color {` are frames
        return self.at("STRING") and self.peek().kind not in ("{", "COLOR", "..")

    def typed_list(self, close, header=False):
        """`name: Type = default in lo..hi, ...` up to `close`, which is consumed.

        In a graph's header, a `"Title" { … }` among them is a panel, its own list inside,
        and `name as key: Type` gives a socket a key of its own."""
        items = []
        while not self.accept(close):
            if self.at("STRING") and self.peek().kind in ("{", "("):
                if not header:
                    self.fail("panels can only be defined in a graph header")
                items.append(self.panel())
                if not self.accept(","):
                    self.expect(close)
                    break
                continue
            name = self.accept("STRING") or self.expect("IDENT", what="name")
            alias = None
            if self.at("IDENT", "as") and self.peek().kind == "IDENT":
                if not header:
                    self.fail("'as' can only be used in a graph header")
                self.advance()
                alias = self.advance().text
            self.expect(":")
            t = self.expect("IDENT", what="type")
            p = ast.Param(name.text, t.text, name.line, name.col, alias=alias)
            if self.accept("("):
                p.options = self.args(named_only=True)
            if self.accept("="):
                p.default = self.unary()
            if self.at("IDENT", "in") and self.peek().kind != ":":
                # Either side may be left open: `in 0.0..`, `in ..1.0`
                self.advance()
                lo = None if self.at("..") else self.unary()
                self.expect("..", what="'..' between min and max")
                hi = self.unary() if self.tok.kind in ("NUMBER", "-") else None
                if lo is None and hi is None:
                    self.fail("empty range: specify at least min or max")
                p.range = (lo, hi)
            items.append(p)
            if not self.accept(","):
                self.expect(close)
                break
        return items

    def panel(self):
        t = self.advance()
        options = self.args(named_only=True) if self.accept("(") else []
        self.expect("{", what="'{' after panel name")
        self.enter()
        items = self.typed_list("}", header=True)
        self.leave()
        # typed_list took the closing brace
        return ast.Panel(t.text, items, t.line, t.col, options, self.tokens[self.i - 1].line)

    def statement(self):
        t = self.tok
        if self.at("{") or self.at("COLOR") or self.at("..") or \
                self.at("STRING") and self.peek().kind in ("{", "COLOR", ".."):
            return self.frame()
        if self.accept("KEYWORD", "return"):
            if self.at("(") and (self.peek().kind == ")" or
                                 self.peek().kind in ("IDENT", "STRING") and self.peek(2).kind == ":"):
                self.advance()
                fields = self.args(named_only=True)
                return ast.Return(ast.Record(fields, t.line, t.col), t.line, t.col, self.look())
            return ast.Return(self.expr(), t.line, t.col, self.look())
        if self.at("IDENT") and self.peek().kind == "=":
            if t.text in WORDS:
                self.fail(f"'{t.text}' is reserved for {'dot' if t.text == 'dot' else 'cross'} product: "
                          "choose another name")
            self.advance()
            self.advance()
            if self.at("KEYWORD", "repeat"):
                value = self.repeat()
            elif self.at_closure():
                value = self.closure()
            elif self.at_zone():
                value = self.zone()
            else:
                # A zone's output shows its look on the return of its body
                return ast.Assign(t.text, self.expr(), t.line, t.col, self.look())
            return ast.Assign(t.text, value, t.line, t.col)
        self.fail(f"statement expected (name = …, return, or a frame \"title\" {{ … }}), found {describe(t)}")

    def look(self):
        """`@ "Label" #color hide mute` at the end of a statement, each part optional, or None.

        The parts are on the line of the `@`: what the next line starts is the next statement.
        """
        at = self.accept("@")
        if at is None:
            return None
        label = self.accept("STRING") if self.tok.line == at.line else None
        color = self.accept("COLOR") if self.tok.line == at.line else None
        flags = []
        while self.at("IDENT") and self.tok.text in LOOK_FLAGS and self.tok.line == at.line:
            if self.tok.text in flags:
                self.fail(f"'{self.tok.text}' given twice")
            flags.append(self.advance().text)
        if label is None and color is None and not flags:
            self.fail(f"after @ on the same line: a \"label\", a #color, {', '.join(LOOK_FLAGS)}")
        return ast.Look(flags, at.line, at.col, label and label.text, color and color.text)

    def frame(self):
        t = self.tok
        label = self.accept("STRING")
        continued = self.accept("..") is not None
        color = None if continued else self.accept("COLOR")
        if continued and self.at("COLOR"):
            self.fail("continued frame keeps its color: write only \"title\" .. {")
        self.expect("{")
        body, end = self.block()
        return ast.Frame(label and label.text, color and color.text, body, t.line, t.col, end.line, continued)

    def repeat(self):
        t = self.advance()
        self.expect("(", what="'(' after repeat")
        args = self.args()
        if not args or args[0].name is not None:
            self.fail("repeat expects iteration count first: repeat(10, state: start, …)", t)
        if len(args) < 2:
            self.fail("repeat expects at least one state: repeat(10, state: start)", t)
        if any(a.options for a in args):
            self.fail("repeat state does not take options", t)
        self.expect("{", what="'{' after repeat(…)")
        body, end = self.block()
        return ast.Repeat(args[0].value, args[1:], body, t.line, t.col, end.line)

    def at_zone(self):
        """`simulate(…) {` or `foreach(…) {`: contextual keywords, so that a name or a group
        may still be called simulate; only a block right after the parenthesis makes a zone."""
        if not (self.at("IDENT") and self.tok.text in ZONE_WORDS and self.peek().kind == "("):
            return False
        j = self.matching(self.i + 1)
        return j is not None and self.tokens[j + 1].kind == "{"

    def zone(self):
        t = self.advance()
        self.advance()
        args = self.args()
        if t.text != "simulate":
            # A state of repeat or simulate may take a key of its own; a foreach item not yet
            self.no_alias(args)
        if t.text == "simulate":
            if any(a.name is None for a in args):
                self.fail("simulate expects named states: simulate(state: start, …)", t)
        elif not args or args[0].name is not None or any(a.name is None for a in args[1:]):
            self.fail("foreach expects geometry first, then named items: "
                      "foreach(geometry, domain: FACE, item: field, …)", t)
        self.expect("{")
        body, end = self.block()
        if t.text == "simulate":
            return ast.Simulate(args, body, t.line, t.col, end.line)
        return ast.Foreach(args[0].value, args[1:], body, t.line, t.col, end.line)

    def block(self):
        """Statements up to `}`, which is consumed: (body, the closing token)."""
        self.enter()
        body = []
        while not self.at("}"):
            if self.at("EOF"):
                self.fail("'}' expected before end of file")
            body.append(self.statement())
        self.leave()
        return body, self.advance()

    def at_closure(self):
        # `closure` is a keyword only as `closure(…) -> … {`, so that a name, a socket
        # or a graph may still be called closure
        if not (self.at("IDENT", "closure") and self.peek().kind == "("):
            return False
        i = self.matching(self.i + 1)
        if i is None or self.tokens[i + 1].kind != "->":
            return False
        i += 2
        if self.tokens[i].kind == "(":
            i = self.matching(i)
            if i is None:
                return False
        # The text may end at the type: there is no token after the end of file
        return self.tokens[i].kind != "EOF" and self.tokens[i + 1].kind == "{"

    def matching(self, i):
        """Index of the `)` closing the `(` at token i, or None.

        All are paired in one pass: looking ahead from each `(` in turn would read a
        text of nested calls once per level."""
        if self.closing is None:
            self.closing, opened = {}, []
            for j, tok in enumerate(self.tokens):
                if tok.kind == "(":
                    opened.append(j)
                elif tok.kind == ")" and opened:
                    self.closing[opened.pop()] = j
        return self.closing.get(i)

    def closure(self):
        t = self.advance()
        self.expect("(")
        params = self.typed_list(")")
        self.expect("->")
        outputs, single = self.outputs()
        self.expect("{", what="'{' after closure(…) -> …")
        body, end = self.block()
        return ast.Closure(params, outputs, single, body, t.line, t.col, end.line)

    def outputs(self):
        """After `->`: `(name: Type, …)`, or one Type named as itself."""
        if self.accept("("):
            return self.typed_list(")"), False
        t = self.expect("IDENT", what="return type")
        return [ast.Param(t.text, t.text, t.line, t.col)], True

    def expr(self):
        left = self.disjunction()
        height = self.height
        while self.at("|>"):
            op = self.advance()
            rhs = self.postfix()
            height = self.tall(max(height, self.height) + 1, op)
            call = rhs.target if isinstance(rhs, ast.Member) else rhs
            if not isinstance(call, ast.Call):
                self.fail("node call expected after |>", op)
            left = ast.Pipe(left, rhs, op.line, op.col)
        return left

    def disjunction(self):
        left = self.conjunction()
        height = self.height
        while self.at("KEYWORD", "or") or self.at("KEYWORD", "xor"):
            op = self.advance()
            left = ast.BinOp(op.text, left, self.conjunction(), op.line, op.col)
            height = self.tall(max(height, self.height) + 1, op)
        return left

    def conjunction(self):
        left = self.negation()
        height = self.height
        while self.at("KEYWORD", "and"):
            op = self.advance()
            left = ast.BinOp("and", left, self.negation(), op.line, op.col)
            height = self.tall(max(height, self.height) + 1, op)
        return left

    def negation(self):
        if self.at("KEYWORD", "not"):
            op = self.advance()
            self.enter()
            value = self.negation()
            self.leave()
            self.tall(self.height + 1, op)
            return ast.Not(value, op.line, op.col)
        return self.comparison()

    def comparison(self):
        left = self.additive()
        if self.tok.kind in COMPARE:
            height = self.height
            op = self.advance()
            left = ast.BinOp(op.text, left, self.additive(), op.line, op.col)
            self.tall(max(height, self.height) + 1, op)
            if self.tok.kind in COMPARE:
                self.fail("only one comparison at a time; assign to a name for multiple")
        return left

    def additive(self):
        left = self.multiplicative()
        height = self.height
        while self.at("+") or self.at("-"):
            op = self.advance()
            left = ast.BinOp(op.text, left, self.multiplicative(), op.line, op.col)
            height = self.tall(max(height, self.height) + 1, op)
        return left

    def multiplicative(self):
        left = self.unary()
        height = self.height
        # After an operand, `dot` and `cross` can only be products: they are reserved names
        while self.tok.kind in ("*", "/", "⋅", "·", "×") or \
                self.at("IDENT") and self.tok.text in WORDS and self.peek().kind != "=":
            op = self.advance()
            left = ast.BinOp(WORDS.get(op.text, op.text), left, self.unary(), op.line, op.col)
            height = self.tall(max(height, self.height) + 1, op)
        return left

    def unary(self):
        if self.at("-"):
            op = self.advance()
            self.enter()
            value = self.unary()
            self.leave()
            if isinstance(value, ast.Number):
                return ast.Number(-value.value, value.is_int, op.line, op.col)
            self.tall(self.height + 1, op)
            return ast.Neg(value, op.line, op.col)
        return self.postfix()

    def postfix(self):
        node = self.primary()
        if isinstance(node, ast.Call) and self.at("->"):
            # The outputs a node declares end it: `(… -> (a: Float)).a` takes parentheses
            self.advance()
            node.outputs, node.single_output = self.outputs()
            return node
        while self.at("."):
            dot = self.advance()
            if self.at("IDENT") or self.at("STRING"):
                node = ast.Member(node, self.advance().text, dot.line, dot.col)
                self.tall(self.height + 1, dot)
            else:
                self.fail("output socket name expected after '.'")
        return node

    def primary(self):
        t = self.tok
        self.height = 1
        if self.accept("NUMBER"):
            is_int = not any(c in t.text for c in ".eE")
            # Digits are counted first: Python refuses to read an integer of thousands of them
            if is_int and (len(t.text) > 19 or int(t.text) > MAX_INT) or not is_int and math.isinf(float(t.text)):
                self.fail("number too large", t)
            return ast.Number(int(t.text) if is_int else float(t.text), is_int, t.line, t.col)
        if self.accept("STRING"):
            return ast.String(t.text, t.line, t.col)
        if self.accept("KEYWORD", "true") or self.accept("KEYWORD", "false"):
            return ast.Bool(t.text == "true", t.line, t.col)
        if self.at("KEYWORD", "repeat"):
            self.fail("repeat must be assigned to a name: r = repeat(10, state: start) { … }")
        if self.at("KEYWORD", "xor") and self.peek().kind == "(":
            # The function form, kept from before `xor` was an operator
            self.advance()
            self.advance()
            args = self.args()
            self.tall(self.height + 1, t)
            return ast.Call("xor", args, t.line, t.col)
        if self.accept("IDENT"):
            name = t.text
            while self.accept("::"):
                part = self.accept("STRING") or self.expect("IDENT", what="identifier or name after '::'")
                name = f"{name}::{part.text}"
            type_args = None
            if self.at_type_args():
                self.advance()
                type_args = [self.advance().text]
                while self.accept(","):
                    type_args.append(self.advance().text)
                self.expect(">")
            if self.accept("("):
                args = self.args()
                self.tall(self.height + 1, t)
                return ast.Call(name, args, t.line, t.col, type_args=type_args)
            return ast.Ref(name, t.line, t.col)
        if self.accept("("):
            self.enter()
            items = [self.expr()]
            height = self.height
            while self.accept(","):
                if self.at(")"):
                    break
                items.append(self.expr())
                height = max(height, self.height)
            self.expect(")")
            self.leave()
            if len(items) == 1:
                return items[0]
            self.tall(height + 1, t)
            return ast.Tuple(items, t.line, t.col)
        self.fail(f"expression expected, found {describe(t)}")

    def args(self, named_only=False):
        """Arguments up to `)`, which is consumed. Leaves the height of the tallest, 0 for none."""
        self.enter()
        args = []
        height = 0
        while not self.accept(")"):
            t = self.tok
            self.height = 0
            if t.kind in ("IDENT", "STRING") and self.peek().text == "as" and self.peek().kind == "IDENT" \
                    and self.peek(2).kind == "IDENT" and self.peek(3).kind in (":", "("):
                # `Selection as captured: m`, an item under a key of its own
                self.advance()
                self.advance()
                alias = self.advance()
                if named_only:
                    self.fail("'as' aliases an item in an item node call or an input in a graph header", alias)
                options = self.args(named_only=True) if self.accept("(") else []
                height = max(height, self.height)
                self.expect(":")
                args.append(self.item(t, options))
                args[-1].alias = alias.text
            elif t.kind in ("IDENT", "STRING") and self.peek().kind == ":":
                self.advance()
                self.advance()
                args.append(self.item(t, []))
            elif not named_only and self.at_item_options():
                # `Smooth(description: "…"): a`, an item and its options
                self.advance()
                self.advance()
                options = self.args(named_only=True)
                height = max(height, self.height)
                self.expect(":")
                args.append(self.item(t, options))
            elif named_only:
                self.fail("named field expected (name: value)")
            else:
                if any(a.name for a in args):
                    self.fail("positional argument after named argument")
                args.append(ast.Arg(None, self.expr(), t.line, t.col))
            height = max(height, self.height)
            if not self.accept(","):
                self.expect(")")
                break
        self.leave()
        self.height = height
        return args

    def no_alias(self, args):
        for a in args:
            if a.alias:
                self.fail(f"'{a.name} as {a.alias}': 'as' only aliases an item of an item node", a)

    def at_item_options(self):
        """`name(` … `):` ahead: an item with options, not a call given as a value."""
        if self.tok.kind not in ("IDENT", "STRING") or self.peek().kind != "(":
            return False
        j = self.matching(self.i + 1)
        return j is not None and self.tokens[j + 1].kind == ":"

    def item(self, t, options):
        """`name: value`, or `name: Type = value`, an item given its type, once `name:` and its options are read."""
        value = self.expr()
        arg = ast.Arg(t.text, value, t.line, t.col, options)
        if self.at("="):
            eq = self.advance()
            arg.type = self.item_type(t.text, value, eq)
            # `name: Type(option: …) = value` reads as `name(option: …): Type = value`
            arg.options = arg.options + arg.type.options
            arg.type.options = []
            height = self.height
            arg.value = self.expr()
            self.height = max(height, self.height)
        return arg

    def item_type(self, name, e, at):
        """The type written before `=`: `Float`, or `Float(structure_type: SINGLE)`."""
        if isinstance(e, ast.Ref):
            return ast.Param(name, e.name, e.line, e.col)
        if isinstance(e, ast.Call) and e.outputs is None and all(a.name and a.type is None for a in e.args):
            return ast.Param(name, e.name, e.line, e.col, options=e.args)
        self.fail("type expected before '=': name: Type = value", at)


def describe(tok):
    if tok.kind == "EOF":
        return "end of file"
    return f"'{tok.text}'"
