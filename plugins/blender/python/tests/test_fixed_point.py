"""The printer and the formatter of the core are a fixed point on every text of this library: the
standard library, the examples and the fixtures."""

from pathlib import Path

import pytest

from base_node import parse
from base_node.format import format_source
from base_node.printer import to_source

ROOT = Path(__file__).resolve().parents[2]


def corpus():
    return sorted((ROOT / "stdlib").glob("*.bn")) + sorted((ROOT / "examples").rglob("*.bn")) \
        + sorted((ROOT / "python" / "tests" / "fixtures").glob("*.bn"))


@pytest.mark.parametrize("path", corpus(), ids=lambda p: str(p.relative_to(ROOT)))
def test_printing_is_a_fixed_point(path):
    once = to_source(parse(path.read_text(encoding="utf-8"), str(path)))
    assert to_source(parse(once, str(path))) == once
    formatted = format_source(path.read_text(encoding="utf-8"), str(path))
    assert format_source(formatted, str(path)) == formatted
