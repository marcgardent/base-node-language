import sys
from pathlib import Path

# This library from its checkout; the core (base_node) and Blender's library (base_node_blender) are
# its dependencies: installed, or on the PYTHONPATH the Makefile gives
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import base_node_blade  # noqa: E402

base_node_blade.add()
