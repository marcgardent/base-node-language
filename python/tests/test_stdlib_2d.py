"""Tests for the 2D standard library modules."""

from __future__ import annotations

from pathlib import Path

import pytest

from base_node import check_target, format_source, infer, parse
from base_node.manifest import manifest

REPO_ROOT = Path(__file__).resolve().parents[2]
STDLIB_DIR = REPO_ROOT / "stdlib"


MODULES_2D = ["planar2d", "fillet2d"]


def test_2d_modules_manifest_registration():
    """Verify the 2D modules are in the stdlib manifest."""
    modules = manifest(STDLIB_DIR)["modules"]

    for mod_name in MODULES_2D:
        assert mod_name in modules, f"Module {mod_name} must be in stdlib manifest"
        entry = modules[mod_name]
        assert entry["name"] == mod_name
        assert "blender-geometry" in entry["targets"]
        assert entry["version"] == "0.13.1"
        assert entry["edition"] == "2026"
        assert (STDLIB_DIR / entry["file"]).exists()


@pytest.mark.parametrize("mod_name", MODULES_2D)
def test_2d_modules_parse_and_fit_geometry_nodes(mod_name):
    """Each 2D module parses and fits blender-geometry."""
    file_path = STDLIB_DIR / f"{mod_name}.bn"
    text = file_path.read_text(encoding="utf-8")

    ast = parse(text, file_path.name)
    assert len(ast.graphs) == 4, f"{mod_name} must contain exactly 4 canonical graphs"

    # Every 2D module fits Geometry Nodes, and only Blender's targets
    assert check_target(ast, "blender-geometry") == []
    fits = infer(ast).fits
    assert "blender-geometry" in fits
    assert "gltf" not in fits and "blade" not in fits


def test_planar2d_graphs_signatures():
    """Verify graph signatures in planar2d.bn."""
    ast = parse((STDLIB_DIR / "planar2d.bn").read_text(encoding="utf-8"), "planar2d.bn")
    names = [g.name for g in ast.graphs]
    assert names == [
        "planar faces",
        "planar split intersections",
        "shape builder pick",
        "contour outer boundary",
    ]

    # Verify planar faces takes curves: Geometry and returns Geometry
    g_faces = ast.graphs[0]
    assert [p.name for p in g_faces.params] == ["curves", "tolerance"]
    assert len(g_faces.outputs) == 1
    assert g_faces.outputs[0].type == "Geometry"


def test_fillet2d_graphs_signatures():
    """Verify graph signatures in fillet2d.bn."""
    ast = parse((STDLIB_DIR / "fillet2d.bn").read_text(encoding="utf-8"), "fillet2d.bn")
    names = [g.name for g in ast.graphs]
    assert names == [
        "fillet corner",
        "fillet polygon",
        "chamfer polygon",
        "fillet bezier handles",
    ]

    # Verify fillet corner returns (p1: Vector, p2: Vector, center: Vector)
    g_corner = ast.graphs[0]
    ret_types = [(p.name, p.type) for p in g_corner.outputs]
    assert ret_types == [("p1", "Vector"), ("p2", "Vector"), ("center", "Vector")]






