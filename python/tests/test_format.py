import pytest

from base_node import BnError
from base_node.format import format_source

MESSY = """// Two graphs

geometry graph "Smooth Mesh"(Mesh: Geometry, Level: Int) -> Geometry {
  // smooth the mesh
  return Mesh
    |> SubdivideMesh(level: Level)   // finer
    // then shade
    |> SetShadeSmooth()
}
// next one
geometry graph scatter(geometry: Geometry) -> Geometry {
  grid = Grid(size_x: 2.0,size_y: 2.0, vertices_x: 3, vertices_y: 3) // a grid


  smooth = smooth_mesh(grid.mesh, 2)
  return geometry+smooth
  // end of body
} // done
"""

FORMATTED = """// Two graphs

geometry graph "Smooth Mesh"(Mesh: Geometry, Level: Int) -> Geometry {
  // smooth the mesh
  return Mesh
    |> SubdivideMesh(level: Level)  // finer
    // then shade
    |> SetShadeSmooth()
}

// next one
geometry graph scatter(geometry: Geometry) -> Geometry {
  grid = Grid(size_x: 2.0, size_y: 2.0, vertices_x: 3, vertices_y: 3)  // a grid

  smooth = smooth_mesh(grid.mesh, 2)
  return geometry + smooth
  // end of body
}  // done
"""


def test_format_keeps_comments_and_one_blank_line():
    assert format_source(MESSY) == FORMATTED


def test_format_is_stable():
    assert format_source(FORMATTED) == FORMATTED


def test_comment_inside_a_spread_call_stays_on_its_argument():
    long = ", ".join(f"input_{i}: {i}.0" for i in range(12))
    text = format_source(f"geometry graph g() -> Geometry {{\n  return F(a: 1.0,  // first\n {long})\n}}")
    assert "    a: 1.0,  // first\n" in text
    assert format_source(text) == text


def test_format_refuses_broken_text():
    with pytest.raises(BnError):
        format_source("geometry graph g() -> Geometry {\n  return\n")


GRAPH = "geometry graph g() -> Float {\n  return 1.0\n}\n"

# (source, canonical text): the uses get sorted, the head comments of the module stay above them,
# a comment between two uses goes with the use under it, the blank lines stay where they were.
# The Rust formatter has the same cases (rust/tests/format_uses.rs).
USE_CASES = {
    "sorted after a head comment": (
        "// @module m\n\n// prose\n// more\nuse grade (a, b)\n\nuse merge (c, d)\n\n" + GRAPH,
        "// @module m\n\n// prose\n// more\nuse grade (a, b)\n\nuse merge (c, d)\n\n" + GRAPH,
    ),
    "unsorted after a head comment": (
        "// @module m\n\n// prose\nuse merge (c, d)\n\nuse grade (a, b)\n\n" + GRAPH,
        "// @module m\n\n// prose\nuse grade (a, b)\n\nuse merge (c, d)\n\n" + GRAPH,
    ),
    "unsorted after a head comment and a blank line": (
        "// head\n\nuse zeta (z)\nuse alpha (a)\n\n" + GRAPH,
        "// head\n\nuse alpha (a)\nuse zeta (z)\n\n" + GRAPH,
    ),
    "a comment between two uses": (
        "// head\nuse merge (c, d)\n// about grade\nuse grade (a, b)\n\n" + GRAPH,
        "// head\n\n// about grade\nuse grade (a, b)\nuse merge (c, d)\n\n" + GRAPH,
    ),
    "trailing comments": (
        "use merge (c, d)  // m\nuse grade (a, b)  // g\n\n" + GRAPH,
        "use grade (a, b)  // g\nuse merge (c, d)  // m\n\n" + GRAPH,
    ),
    "comment groups and blank lines": (
        "// @module m\n\n// prose\nuse zeta\n\n// about merge\n// still\nuse merge (c)  // tm\n\n"
        "// about alpha\n\nuse alpha\n\n" + GRAPH,
        "// @module m\n\n// prose\n\n// about alpha\n\nuse alpha\n\n// about merge\n// still\n"
        "use merge (c)  // tm\n\nuse zeta\n\n" + GRAPH,
    ),
    "a comment inside a split use": (
        "use zeta (\n  a,  // first\n  b,\n)\nuse alpha\n\n" + GRAPH,
        "use alpha\nuse zeta (a, b)  // first\n\n" + GRAPH,
    ),
}


@pytest.mark.parametrize("case", USE_CASES)
def test_format_sorts_the_uses_and_keeps_their_comments(case):
    source, expected = USE_CASES[case]
    assert format_source(source) == expected
    assert format_source(expected) == expected
