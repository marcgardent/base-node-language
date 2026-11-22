from dataclasses import dataclass

from .errors import BnError, Diagnostic

KEYWORDS = {"graph", "return", "true", "false", "and", "or", "xor", "not"}
# The numbers written as words: floats no digits write
WORD_NUMBERS = {"inf", "nan"}
# What follows a `\` in a string, and the character it stands for; `\u{…}` is any other
ESCAPES = {'"': '"', "\\": "\\", "n": "\n", "t": "\t", "r": "\r"}
ESCAPES_TOLD = "a string's escapes are \\\", \\\\, \\n, \\t, \\r and \\u{…}, a character's code in 1 to 6 hex digits"

# Longest first, so "->" wins over "-", "==" over "=" and ".." over "."
PUNCT = ("::", "|>", "|", "->", "<=", ">=", "==", "!=", "<", ">", "(", ")", "[", "]", "{", "}", ",", ":", "..", ".", "=", "+", "-", "*", "/",
         "⋅", "·", "×", "@", "?")
STARTING = {c: tuple(p for p in PUNCT if p[0] == c) for c in {p[0] for p in PUNCT}}  # in PUNCT's order


@dataclass(frozen=True)
class Token:
    kind: str  # IDENT, NUMBER, STRING, KEYWORD, COLOR, COMMENT, a PUNCT string, or EOF
    text: str  # of a string, its value: the escapes read
    line: int
    col: int
    width: int = 0  # the characters of the source it takes: a string's quotes and escapes too


def tokenize(source, filename="<text>", strict=True):
    """Tokens of the source. Not strict, for the editor: half-typed text never
    fails, comments are kept as tokens, an unclosed string runs to the line's end and an
    unknown escape stays in its value as written."""
    tokens = []
    i, line, col = 0, 1, 1
    n = len(source)

    def fail(message):
        raise BnError([Diagnostic(filename, line, col, message)])

    while i < n:
        c = source[i]
        if c == "\n":
            i, line, col = i + 1, line + 1, 1
            continue
        if c in " \t\r":
            i, col = i + 1, col + 1
            continue
        if source.startswith("//", i):
            start = i
            while i < n and source[i] != "\n":
                i += 1
            if not strict:
                tokens.append(Token("COMMENT", source[start:i], line, col, i - start))
                col += i - start
            continue

        start = i
        if c.isalpha() or c == "_":
            while i < n and (source[i].isalnum() or source[i] == "_"):
                i += 1
            text = source[start:i]
            kind = "KEYWORD" if text in KEYWORDS else "NUMBER" if text in WORD_NUMBERS else "IDENT"
        elif c.isdigit():
            while i < n and source[i].isdigit():
                i += 1
            if i + 1 < n and source[i] == "." and source[i + 1].isdigit():
                i += 1
                while i < n and source[i].isdigit():
                    i += 1
            if i < n and source[i] in "eE":
                j = i + 1
                if j < n and source[j] in "+-":
                    j += 1
                if j < n and source[j].isdigit():
                    i = j
                    while i < n and source[i].isdigit():
                        i += 1
            text, kind = source[start:i], "NUMBER"
        elif c == "#":
            # A frame color, its text with the `#`: checked later, so `#nope` gets a clear error
            i += 1
            while i < n and (source[i].isalnum() or source[i] == "_"):
                i += 1
            text, kind = source[start:i], "COLOR"
        elif c == '"':
            i += 1
            value = []
            while i < n and source[i] not in '"\n':
                if source[i] == "\\" and i + 1 < n and source[i + 1] != "\n":
                    char, end = escape(source, i)
                    if char is None:
                        if strict:
                            raise BnError([Diagnostic(filename, line, col + i - start,
                                                      f"unknown escape '{source[i:end]}': {ESCAPES_TOLD}")])
                        char = source[i:end]
                    value.append(char)
                    i = end
                else:
                    value.append(source[i])
                    i += 1
            if i < n and source[i] == '"':
                i += 1
                kind = "STRING"
            elif strict:
                fail("unclosed string")
            else:
                kind = "OPEN_STRING"
            text = "".join(value)
        else:
            for p in STARTING.get(c, ()):
                if source.startswith(p, i):
                    i += len(p)
                    text = kind = p
                    break
            else:
                if strict:
                    fail(f"unexpected character '{c}'")
                i, col = i + 1, col + 1
                continue

        tokens.append(Token(kind, text, line, col, i - start))
        col += i - start

    tokens.append(Token("EOF", "", line, col))
    return tokens


def string_literal(text):
    r"""The value of `text` when it is one string literal and nothing else, its escapes read as
    in any string (`"a \"b\""` is `a "b"`), else None: what a quoted value outside the grammar
    (a directive of the head) reads by."""
    try:
        tokens = tokenize(text)
    except BnError:
        return None
    t = tokens[0]
    return t.text if len(tokens) == 2 and t.kind == "STRING" and t.width == len(text) else None


def escape(source, i):
    r"""The escape at `source[i]`, a `\`: (the character it stands for, or None when it is none
    the language knows, the index after it). An unknown one ends after its letter, or after
    the hex digits and the `}` of a `\u{…}`."""
    c = source[i + 1]
    if c in ESCAPES:
        return ESCAPES[c], i + 2
    if c != "u" or not source.startswith("{", i + 2):
        return None, i + 2
    j = i + 3
    while j < len(source) and source[j] in HEX:
        j += 1
    digits = source[i + 3:j]
    if not source.startswith("}", j):
        return None, j
    code = int(digits, 16) if 1 <= len(digits) <= 6 else -1
    if not 0 <= code <= 0x10FFFF or 0xD800 <= code <= 0xDFFF:
        return None, j + 1
    return chr(code), j + 1


HEX = set("0123456789abcdefABCDEF")


def width(t):
    """How many characters of its line a token takes: a string's quotes and escapes too."""
    return t.width


def span_at(line, col):
    """0-based [start, end) of what a diagnostic at a 1-based column points to in one line:
    the token there, else one character. Past the line's end, its last character."""
    start = max(0, min(col - 1, len(line) - 1))
    for t in tokenize(line, strict=False)[:-1]:
        if t.col - 1 <= start < t.col - 1 + width(t):
            return t.col - 1, t.col - 1 + width(t)
    return start, start + 1
