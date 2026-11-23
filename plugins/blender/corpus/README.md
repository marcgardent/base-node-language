# Corpus

The node groups of third-party libraries, read as `.bn` text: a reference corpus of version 1 of the
language. Each `v1/<library>/` holds a library's groups (and materials), one `<group>.bn` per group,
as the reader of Blender 5.3 writes them (the latest Blender that Base Node promises), with a
`README.md` naming the library and the `LICENSE` of the library.

These texts are derived works of their libraries. The MIT and Apache-2.0 licenses of this repository
do not cover them: each folder is under the license of its library, in its `LICENSE` file
(`licenses/` holds those texts once).

The `.blend` files of the libraries stay the source of the non-regression tests
(`base-node-for-blender/tests/test_libraries.py`): the texts are kept for what they are, the groups
of real libraries written in the language. `test_libraries.py` writes them with the baselines
(`BASE_NODE_UPDATE_FIXTURES=1` on the Blender of the baselines); `python/tests/test_corpus.py` checks
that each one parses, fits the target `blender@5.3` and has the hash its baseline records, and
`rust/tests/corpus.rs` that the Rust parser reads it and the formatter prints it unchanged
(`rust-blender/tests/corpus.rs`: that it fits `blender@5.3` in Rust too).

`v1/` is frozen at the final 1.0.0. A later version of the language must still read every text of it.

| Folder | Library | Author | Version | License | Groups |
|---|---|---|---|---|---|
| [`bioxelnodes/`](v1/bioxelnodes/) | [Bioxel Nodes](https://github.com/OmooLab/BioxelNodes) | OmooLab | v2.0.4 | GPL-3.0-or-later | 34 |
| [`compositingessentials/`](v1/compositingessentials/) | [Compositing Nodes Essentials](https://projects.blender.org/blender/blender-assets) | Blender Foundation | Blender 5.3.0 | CC0-1.0 | 25 |
| [`geometrydynamics/`](v1/geometrydynamics/) | [Geometry Nodes Dynamics Assets](https://projects.blender.org/blender/blender-assets) | Blender Foundation | Blender 5.3.0 | CC0-1.0 | 55 |
| [`geometryessentials/`](v1/geometryessentials/) | [Geometry Nodes Essentials](https://projects.blender.org/blender/blender-assets) | Blender Foundation | Blender 5.3.0 | CC0-1.0 | 33 |
| [`hstylerbd/`](v1/hstylerbd/) | [H-Style RBD Nodes](https://github.com/excifroge/H-Style-RBD-Nodes) | Excifroge | d9a22d0 | GPL-3.0-or-later | 8 |
| [`hstylerbd_bricks/`](v1/hstylerbd_bricks/) | [H-Style RBD Nodes](https://github.com/excifroge/H-Style-RBD-Nodes) | Excifroge | d9a22d0 | GPL-3.0-or-later | 7 |
| [`mandelbrot/`](v1/mandelbrot/) | [i32 the Mandelbrot Set](https://extensions.blender.org/add-ons/i32-the-mandelbrot-set/) | Osipenkov \| Art | 1.0.3 | GPL-3.0-or-later | 9 |
| [`materiallibraryvx/`](v1/materiallibraryvx/) | [Material Library VX](https://github.com/blender/blender-addons/tree/main/materials_library_vx) | Mackraken, Blender Foundation | b42d686 | GPL-2.0-or-later | 66 |
| [`molecularnodes/`](v1/molecularnodes/) | [Molecular Nodes](https://github.com/BradyAJohnston/MolecularNodes) | Brady Johnston and contributors | v520.2.0 | GPL-3.0-or-later | 403 |
| [`openvat/`](v1/openvat/) | [OpenVAT](https://github.com/sharpen3d/openvat) | Luke Stilson | 43b5196 | GPL-3.0-or-later | 6 |
| [`principalcomponents/`](v1/principalcomponents/) | [Principal Components](https://projects.blender.org/blender/blender-assets) | Blender Foundation | Blender 5.3.0 | CC0-1.0 | 2 |
| [`proceduralhair/`](v1/proceduralhair/) | [Procedural Hair Node Assets](https://projects.blender.org/blender/blender-assets) | Blender Foundation | Blender 5.3.0 | CC0-1.0 | 32 |
| [`proceduraltiles/`](v1/proceduraltiles/) | [Procedural Tiles](https://github.com/AisunTang/Procedural-Tiles) | Aisun Tang | a2f21a0 (0.0.4) | GPL-3.0-or-later | 105 |
| [`shadingessentials/`](v1/shadingessentials/) | [Shading Nodes Essentials](https://projects.blender.org/blender/blender-assets) | Blender Foundation | Blender 5.3.0 | CC0-1.0 | 4 |
| [`t3d/`](v1/t3d/) | [T3D GN Presets](https://github.com/Tams3d/T3D-GN-Presets) | Tamil Selvan | v1.6.0 | GPL-3.0-or-later | 88 |
| [`tessera/`](v1/tessera/) | [Tessera – Mosaic & Tile Studio](https://extensions.blender.org/add-ons/tessera-mosaic/) | Tessera | 1.0.0 | GPL-3.0-or-later | 8 |
| [`unravel/`](v1/unravel/) | [Unravel](https://github.com/paraminder-dhiman/unravel) | Paraminder Dhiman | v1.0.0 | GPL-3.0-or-later | 4 |

889 groups. Thanks to the authors of these libraries for publishing them.
