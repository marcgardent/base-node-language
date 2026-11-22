"""Write the characters of an identifier, past ASCII, for the Python and the Rust cores alike.

    make identifiers

An identifier is Unicode's (UAX #31, Default Identifiers): it starts with `_` or a character of
XID_Start and goes on with characters of XID_Continue, but for `·` (U+00B7), which is the dot
product. Python's `str.isidentifier` and Rust's `char` know other versions of Unicode, or other
properties: both cores read the tables written here, of the Unicode this Python knows, so that a
name the printer of one writes bare the lexer of the other reads as that name. The tables are
written again only to move to another version of Unicode, which is a change of the language.
"""

import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / "python" / "base_node" / "identifiers.py"
RUST = ROOT / "rust" / "src" / "identifiers.rs"

# What XID_Continue holds that a name may not: the language's own signs
NOT_IN_NAMES = {"·"}


def bounds(holds):
    """The characters past ASCII `holds` accepts, as sorted bounds: a range starts at an even index,
    and ends, excluded, at the odd one after it."""
    out, inside = [], False
    for code in range(0x80, 0x110000):
        c = chr(code)
        if holds(c) != inside:
            out.append(code)
            inside = not inside
    if inside:
        out.append(0x110000)
    return out


def start(c):
    return c.isidentifier() and c not in NOT_IN_NAMES


def goes_on(c):
    return ("a" + c).isidentifier() and c not in NOT_IN_NAMES


def rows(numbers, indent, per_line=8):
    lines = []
    for i in range(0, len(numbers), per_line):
        lines.append(indent + " ".join(f"0x{n:05x}," for n in numbers[i:i + per_line]))
    return "\n".join(lines)


def main():
    version = unicodedata.unidata_version
    starts, continues = bounds(start), bounds(goes_on)
    head = f"of Unicode {version}, written by tools/identifiers.py (make identifiers): do not edit"
    PYTHON.write_text(f'''"""The characters of an identifier past ASCII, {head}.

Each table is sorted bounds: a range starts at an even index and ends, excluded, at the odd one
after it. `START` holds the characters an identifier starts with (XID_Start), `CONTINUE` those it
goes on with (XID_Continue), `·` (U+00B7) left out of both: rust/src/identifiers.rs holds the same.
"""

UNICODE_VERSION = "{version}"

START = (
{rows(starts, "    ")}
)

CONTINUE = (
{rows(continues, "    ")}
)
''', encoding="utf-8")
    RUST.write_text(f'''//! The characters of an identifier past ASCII, {head}.
//!
//! Each table is sorted bounds: a range starts at an even index and ends, excluded, at the odd one
//! after it. `START` holds the characters an identifier starts with (XID_Start), `CONTINUE` those
//! it goes on with (XID_Continue), `·` (U+00B7) left out of both: python/base_node/identifiers.py
//! holds the same.

pub const UNICODE_VERSION: &str = "{version}";

#[rustfmt::skip]
pub(crate) const START: &[u32] = &[
{rows(starts, "    ")}
];

#[rustfmt::skip]
pub(crate) const CONTINUE: &[u32] = &[
{rows(continues, "    ")}
];
''', encoding="utf-8")
    print(f"Unicode {version}: {len(starts) // 2} ranges to start, {len(continues) // 2} to go on", file=sys.stderr)


if __name__ == "__main__":
    main()
