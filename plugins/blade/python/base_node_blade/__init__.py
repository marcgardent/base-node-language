"""Blade's Pixel Nodes for Base Node (.bn): the target `blade`, its translator from `blender` and its
bridge module, made known to Blender's library (base_node_blender).

Installed, Blender's library finds TARGETS by the entry point this distribution declares (group
`base_node_blender.targets`); from a checkout, `add()` makes them known.
"""

from pathlib import Path

__version__ = "1.0.0rc7"

# The folder of the targets: blade.json, and its bridge blade/blender_interop.bn
TARGETS = Path(__file__).resolve().parent / "_targets"


def add():
    """Make the target `blade` known to Blender's library, before its first check."""
    from base_node_blender.targets import add_targets

    add_targets(TARGETS)
