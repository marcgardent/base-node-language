"""The head of a .bn file: `// @module`, `// @offer`… and what a dropped file offers."""

from pathlib import Path

import pytest

from base_node import STDLIB_VERSION
from base_node_blender import BnError, header
from base_node.header import directives

ROOT = Path(__file__).resolve().parents[2]

MAKER = 'geometry graph field() -> Geometry {\n  return Grid(size_x: 1.0, size_y: 1.0, vertices_x: 2, vertices_y: 2)\n}\n'
MODIFIER = 'geometry graph lift(geometry: Geometry) -> Geometry {\n  return SetPosition(geometry)\n}\n'
HELPER = 'geometry graph half(x: Float) -> Float {\n  return x / 2.0\n}\n'


def errors(source):
    with pytest.raises(BnError) as e:
        header(source, "f.bn")
    return [(d.line, d.col, d.message) for d in e.value.diagnostics]


def test_the_stdlib_head_is_read():
    h = header((ROOT / "stdlib" / "curves2d.bn").read_text(encoding="utf-8"), "curves2d.bn")
    assert (h.module, h.version, h.edition) == ("curves2d", STDLIB_VERSION, "2026")
    assert h.target == ["blender"]
    # A module offers itself as a library; its graphs are helpers, and a modifier or two
    assert h.offer[:2] == ["library", "groups"]


def test_text_directives_and_quotes():
    h = header('// @title "Waves"\n// @author Marc G.\n// @license MIT OR Apache-2.0\n// @target "blender@5.3  gltf", blade\n\n'
               + MAKER)
    assert (h.title, h.author, h.license, h.target) == ("Waves", "Marc G.", "MIT OR Apache-2.0", ["blender@5.3 gltf", "blade"])
    assert h.module is None and h.mesh == "cube"


def test_only_the_head_holds_directives():
    source = "// a comment\n\n// @module first\nuse math\n// @module later\n" + MAKER
    assert [d[:2] for d in directives(source)] == [("module", "first")]
    # Nor is a comment that only looks like one a directive
    assert directives('// @target"x"\n// see @module\n' + MAKER) == []


def test_inference_of_the_offers():
    assert header(MAKER).offer == ["groups", "example"]
    assert header(MODIFIER).offer == ["groups", "modifier"]
    assert header(HELPER).offer == ["groups"]
    assert header("// @module waves\n" + MAKER + MODIFIER).offer == ["library", "groups", "example", "modifier"]


def test_a_called_graph_is_neither_example_nor_modifier():
    source = MAKER + 'geometry graph both() -> Geometry {\n  return field()\n}\n'
    h = header(source)
    assert (h.examples, h.example) == (["both"], "both")
    called = MODIFIER + 'geometry graph twice(geometry: Geometry) -> Geometry {\n  return lift(lift(geometry))\n}\n'
    assert header(called).modifiers == ["twice"]


def test_the_written_setting_decides_the_modifier():
    source = 'geometry(is_modifier: false) graph lift(geometry: Geometry) -> Geometry {\n  return geometry\n}\n'
    assert header(source).modifiers == []


def test_the_last_graph_is_used_unless_named():
    two = MAKER + MAKER.replace("field", "meadow")
    assert header(two).example == "meadow"
    assert header("// @example field\n" + two).example == "field"
    named = '// @modifier "the lift"\n' + MODIFIER.replace("graph lift", 'graph "the lift"') + MODIFIER
    assert header(named).modifier == "the lift"
    # A quoted name is matched by its key too
    assert header('// @modifier "lift"\n' + MODIFIER).modifier == "lift"


def test_written_offers_are_kept_in_order():
    h = header("// @offer modifier, groups\n" + MODIFIER)
    assert h.offer_written and h.offer == ["groups", "modifier"]
    assert header("// @offer groups\n" + MODIFIER).modifier is None


def test_the_mesh():
    assert header("// @mesh sphere\n" + MODIFIER).mesh == "sphere"
    assert errors("// @mesh torus\n" + MODIFIER) == [(1, 10, "@mesh 'torus': one of cube, plane, sphere, cylinder, grid")]


def test_unknown_directives_are_ignored():
    assert header("// @gallery-id 42\n// @thumbnail x.png\n" + MAKER).offer == ["groups", "example"]


def test_an_unknown_offer():
    assert errors("// @offer groups, instance\n" + MAKER) == [(1, 19, "@offer 'instance': one of library, groups, "
                                                                     "example, modifier")]


def test_an_offer_no_graph_allows():
    assert errors("// @offer modifier\n" + MAKER) == [
        (1, 11, "@offer modifier: no geometry graph nobody calls has Geometry as first input and output")]
    assert errors("// @offer example\n" + MODIFIER)[0][2].startswith("@offer example: no geometry graph")
    assert errors("// @offer library\n" + MAKER) == [(1, 11, "@offer library: there is no @module to install "
                                                             "the file as")]


def test_a_graph_named_that_is_not_of_the_file():
    assert errors("// @example meadow\n" + MAKER) == [(1, 13, "@example 'meadow': no graph of that name in this file")]


def test_a_graph_named_of_the_wrong_shape():
    (line, col, message), = errors("// @modifier field\n" + MAKER + MODIFIER)
    assert (line, col) == (1, 14) and message.startswith("@modifier 'field': not a modifier")
    (_, _, message), = errors("// @example half\n" + HELPER + MAKER)
    assert message.startswith("@example 'half': not a geometry graph nobody calls that makes its own geometry")
    (_, _, message), = errors('// @example "a b\n' + MAKER)
    assert "a graph's name, quoted, or a bare identifier" in message


def test_a_graph_named_with_escapes():
    # The string of a directive is a string of the language: a graph named with a `"` is named there
    lift = MODIFIER.replace("graph lift", r'graph "the \"lift\""')
    assert header(r'// @modifier "the \"lift\""' + "\n" + lift).modifier == 'the "lift"'
    field = MAKER.replace("graph field", r'graph "C:\\field \u{1F600}"')
    assert header(r'// @example "C:\\field \u{1F600}"' + "\n" + field).example == "C:\\field \U0001F600"
    # An unknown escape, or quotes that are not one string, name no graph
    for written in (r'"the \qlift"', '"the" "lift"', '""'):
        (_, _, message), = errors(f"// @modifier {written}\n" + lift)
        assert message == f"@modifier {written}: a graph's name, quoted, or a bare identifier"
    assert header('// @mesh "grid"\n' + MODIFIER).mesh == "grid"
    assert errors('// @mesh "grid\n' + MODIFIER) == [(1, 10, "@mesh '\"grid': one of cube, plane, sphere, cylinder, grid")]


def test_text_directives_read_escapes():
    from base_node.header import header as core_header
    h = core_header(r'// @title "Say \"hi\" \u{1F600}"' + "\n" + r'// @author "A\\B"' + "\n"
                    + r'// @target "blender@5.3", "bl\u{61}de"' + "\n" + r'// @module "waves"' + "\n" + MAKER)
    assert (h.title, h.author, h.target, h.module) == ('Say "hi" \U0001F600', "A\\B", ["blender@5.3", "blade"], "waves")
    # Free text that is not one string stays as written
    assert core_header('// @title "Waves" and "Ripples"\n' + MAKER).title == '"Waves" and "Ripples"'
    assert core_header('// @title "Waves\n' + MAKER).title == '"Waves'


def test_a_malformed_module_name():
    assert errors("// @module mesh-maps\n" + MAKER) == [
        (1, 12, "@module 'mesh-maps': a module is named by an identifier (letters, digits, _), "
                "its file being <name>.bn")]
    # Said once, not again by an @offer library that needs it
    assert len(errors("// @module ../evil\n// @offer library\n" + MAKER)) == 1


def test_a_directive_twice_or_empty():
    assert errors("// @title A\n// @title B\n" + MAKER) == [(2, 11, "@title is already set on line 1")]
    assert errors("// @author\n" + MAKER) == [(1, 11, "@author needs a value")]


UNKNOWN_EDITION = "@edition '2028': not an edition this reader knows (2026)"


def test_an_edition_this_reader_does_not_know():
    """rust/tests/header.rs holds the same cases."""
    from base_node import EDITION, EDITIONS, format_source, parse
    from base_node import header as core_header

    assert EDITIONS == ("2026",) and EDITION == "2026"
    source = "// A text of later\n// @edition 2028\n" + MAKER
    for read in (core_header, header, parse, format_source):
        with pytest.raises(BnError) as e:
            read(source, "f.bn")
        assert [(d.file, d.line, d.col, d.message) for d in e.value.diagnostics] == [("f.bn", 2, 13, UNKNOWN_EDITION)]
    assert errors('// @edition "2028"\n' + MAKER) == [(1, 13, UNKNOWN_EDITION)]
    # The one it knows, quoted or not, and none at all: the latest
    for head in ("// @edition 2026\n", '// @edition "2026"\n', ""):
        assert parse(head + MAKER, "f.bn").graphs and format_source(head + MAKER, "f.bn") == head + MAKER
    assert header("// @edition 2026\n" + MAKER).edition == "2026" and header(MAKER).edition is None
    # Only the head names the edition: a comment under the first graph is a comment
    assert parse(MAKER + "// @edition 2028\n", "f.bn").graphs
    # Written twice, the first is the file's; with no value, the head says so
    assert errors("// @edition 2026\n// @edition 2028\n" + MAKER) == [(2, 13, "@edition is already set on line 1")]
    assert parse("// @edition\n" + MAKER, "f.bn").graphs


def test_the_command_line_refuses_an_unknown_edition(tmp_path, capsys):
    from base_node_cli.cli import main

    path = tmp_path / "later.bn"
    source = "// @edition 2028\n" + MAKER
    path.write_text(source, encoding="utf-8")
    for command in (["check"], ["fmt"], ["fmt", "--check"], ["parse"], ["ast"]):
        assert main(command + [str(path)]) == 1
        assert f"later.bn:1:13  {UNKNOWN_EDITION}" in capsys.readouterr().err, command
    assert path.read_text(encoding="utf-8") == source, "fmt leaves it as written"


def test_a_syntax_error_is_the_parser_s():
    with pytest.raises(BnError, match="f.bn:2"):
        header("// @title x\ngeometry graph (", "f.bn")


def test_the_formatter_keeps_the_head():
    from base_node import format_source
    source = (ROOT / "examples" / "drop_example.bn").read_text(encoding="utf-8")
    assert directives(format_source(source, "drop_example.bn")) == directives(source)


def test_the_drop_example():
    h = header((ROOT / "examples" / "drop_example.bn").read_text(encoding="utf-8"), "drop_example.bn")
    assert (h.module, h.title, h.license, h.mesh) == ("drop_example", "Ripples and waves", "MIT", "grid")
    assert h.offer == ["library", "groups", "example", "modifier"]
    assert (h.example, h.modifier) == ("ripple_field", "wave modifier")


def test_the_drop_test_page_offers_the_example():
    """site/ is what the pages publish: the drop test page offers a copy of the example."""
    site = (ROOT / "site" / "drop_example.bn").read_text(encoding="utf-8")
    assert site == (ROOT / "examples" / "drop_example.bn").read_text(encoding="utf-8")
    assert 'href="drop_example.bn"' in (ROOT / "site" / "drop-test.html").read_text(encoding="utf-8")
