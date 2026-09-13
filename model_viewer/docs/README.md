# Divinity II Model Viewer 0.1.10 — visual-only

Preview supported NIF models and embedded CAT/ITEM models, textures, skeletons
and animations. Export source-preserving visual .d2model v1/v2 packages for
Blender editing. This branch intentionally omits collision functionality.

Open a supported game archive corpus or a visual .d2model package. Select the
model/components and associated textures/clips; export to a NEW file. Known
normalization rules remain visible before export. This is not a map editor or
automatic repair of every asset. See LIMITATIONS.md.

Old v3/v4 attachments are rejected, not silently discarded. Re-export a visual
package from the game using this version. Existing saves/packages stay unchanged.

Windows, Python3.12.6 x64; portable EXE requires no separate Python installation.
Own code is AGPL-3.0-only. Full dependency notices are retained in LICENSES.
Experimental local candidate; no public release or complete legal clearance.

Source build from the extracted source root:

    python -m pip install -r requirements.txt
    python tools/build_model_viewer.py --output C:/new-viewer-build

Use a new output directory. Runtime ZIP must contain the complete application
folder; source ZIP includes the build script and applicable synthetic tests.
