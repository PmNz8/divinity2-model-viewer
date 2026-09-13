# Resource compatibility matrix

Applies to Model Viewer **0.2.0**, Blender addon **0.1.12** (visual-only), and
DKS Patch Builder **0.2.8**. Evidence reviewed: **2026-09-13**.

## The practical rule

**Edit the resource that owns the data, not a filename that merely looks related.**

For the tested player dragon, change geometry inside the selected CAT and
replace its existing external texture resources separately. Do not try to
redirect its normal map by adding a new CAT texture binding. Keep SM external
as a conservative workflow rule, but its runtime selection has not been
independently confirmed by the NM tests.

A NIF can contain a mesh **or a texture**. Replacing a texture NIF does not
replace the model. A path stored in CAT/ITEM does not prove that the game loads
that external file, or uses it as a fallback.

## Where edits belong

**Runtime:** observed in a bounded game test.
**Structural:** parsed data or offline roundtrip, not proof of engine behavior.
**Unknown:** not isolated by the tests.

| Resource / case | What we established | Where to edit / what belongs in DKS |
| --- | --- | --- |
| Player dragon geometry | **Runtime:** ordinary `Player_DragonMale.cat` supplied the visible mesh. Removing `_50.cat` and both external mesh NIFs left the dragon visible. Disconnecting the ordinary CAT's embedded geometry made it invisible, with or without those external meshes. No visible external-mesh fallback occurred. | Edit the embedded model; output the **whole changed CAT**. Editing the external mesh NIF or `_50.cat` was ineffective for this tested player form. |
| Player dragon DM (base color) | **Structural:** CAT explicitly names `Dragon_A_DM.tga`. **Runtime:** replacing `Win32/Textures/Dragon_A_DM.nif` changed the displayed texture. | Replace that external texture NIF. A texture-only edit need not change CAT bytes. Other assets sharing the texture may also change. |
| Player dragon NM (normal map) | **Runtime:** diagnostic changes to existing `Win32/Textures/Dragon_A_NM.nif` produced visible bands even though CAT's standard normal-source slot was unbound. | Edit the existing external NM resource through a supported texture workflow. Do not embed or redirect NM inside CAT as the expected solution. |
| Adding a CAT normal-map binding | **Runtime:** pointing a newly added source record to a new diagnostic NM name, then to an existing brick NM, produced no visible change. **Important:** these tests added references, **not embedded pixel payloads**. | Not an established editing route. Fully embedding NM pixels and its priority against external textures remain **untested**, not universally proven ignored. |
| CAT SM (gloss/specular convention) | **Structural:** inspected standalone dragon mesh NIFs have SM bindings; the original CAT census had no bound standard gloss sources. **Unknown:** an isolated SM runtime test and its selection mechanism. | Preserve/edit the identified external SM resource where supported; do not assume CAT insertion will redirect it. NM success does **not** prove SM use or priority. |
| Other CAT textures | **Structural:** CAT is not universally “DM only”: glow sources are bound in many CATs, with rare additional shader texture entries. | Follow actual source ownership and bindings. Do not manufacture missing maps solely by swapping filename suffixes. |
| CAT skeleton / animations | **Structural:** the ordinary player CAT contains a skeleton and clips as well as external skeleton/KF/KFM path labels. External skeleton/KF/KFM removal was **not** tested by the mesh-fallback experiment. | Keep the package's recorded owner for supported edits. Do not assume every external animation/skeleton file is unused or interchangeable. |
| Farm B ITEM geometry | **Runtime:** an explicitly placed Farm B instance displayed the edited ITEM geometry. **Structural:** the template has 13 components across LOW/MED/MAX. | Edit supported geometry inside the template and output the **whole changed ITEM**. Preserve all three LOD branches; edit LODs manually. |
| Farm B external textures | **Structural:** 19 external texture sources, including DM/SM/NM and other material maps. Shared textures can affect multiple consumers. | Replace the selected external texture NIFs as separate DKS entries. Do not copy their pixels into ITEM merely to make the package “self-contained”. |
| Farm B embedded DrkM | **Structural:** the dark-map source owns pixel data **inside ITEM**, despite a filename resembling an external `Farm_B_DrkM.nif`. **Runtime:** disabling the affected dark slot resolved the added cube's pattern distortion; disabling parallax alone did not. | Edit the embedded texture or supported material binding, producing a whole ITEM. A same-named external DrkM is not automatically the owner. Do not remove dark slots from every asset. |

The dark-slot result establishes an influence on this material, **not** a
complete shader formula or proof that UV coordinates themselves were corrupted.
Farm B uses different UV sets for some slots: base UV0, dark UV1 and detail UV2.
A correct base-texture preview is not a guarantee that all native material
layers will look correct in the game.

## What each tool actually supports

| Operation | Model Viewer 0.2.0 | Blender addon 0.1.12 | Patch Builder 0.2.8 |
| --- | --- | --- | --- |
| Embedded CAT/ITEM mesh | Export the recorded container owner. | Edit within the supported layout and identity restrictions. | Import the whole changed container, not the external mesh label. |
| Declared external textures | Resolve/select sources; missing or ambiguous associations need attention. | Edit supported imported images; preserve their identities, formats and dimensions. | Write changed texture resources at their recorded paths. |
| Undeclared CAT NM/SM | No complete runtime dependency discovery; filename hints are not authoritative. | No promise that these maps are imported just because the CAT is imported. CAT/skinned NM pixel export remains blocked. | Does not discover, infer or rebind missing runtime textures. Separate supported texture import is not the same as a CAT-package edit. |
| Static ITEM NM pixels | Preserve the selected source and preview interpretation separately. | Supported with explicit **Raw NM channels (static ITEM)** opt-in; raw mip filtering, not sRGB. | Accept the supported changed external/embedded owner; no shader-correctness guarantee. |
| Embedded ITEM texture | Preserve its internal source association. | Edit supported embedded pixels without moving them outside the owner. | Write the containing ITEM. |
| Collision | No import/preview/export in visual-only viewer. | No collision editing/export in this addon. | Opaque import of supported prepared carriers; does not cook or validate native physics semantics. |

**External NM is the correct runtime target for the tested dragon, but that
does not mean the current Blender CAT workflow permits editing it.**
Do not bypass an export restriction by renaming a map, changing its declared
role or forcing it into another container.

## Priority and dependency traps

- **Archive entry replacement is not field merging.** A DKS CAT/ITEM entry must
  be the complete rebuilt resource, retaining unrelated content; not a fragment
  containing only the changed mesh.
- **A changed texture does not prove the intended model is loaded.** The
  original farmhouse location in DZ1 used a static-map representation sharing
  a patched texture; it was not an established consumer of the edited ITEM.
  A separately added ITEM instance displayed the geometry change.
- **Do not assume a universal archive order.** DKS replacement worked for the
  tested CAT, texture and placement paths. Same-path source variants in Builder
  are warnings, not proof of which original variant the engine would select.
- **No general embedded-versus-external priority exists in our evidence.**
  The dragon mesh, external DM/NM and embedded Farm B dark map have different
  ownership patterns.
- **Preview completeness is not runtime completeness.** Explicitly selected
  preview dependencies do not describe every engine material lookup. Normal-map
  preview channel/Y settings are not an export conversion or proof of native
  shader interpretation.

## Evidence boundary

The original CAT material census inspected **330 physical occurrences / 324
logical paths** and **1,113 texturing-property blocks**: base sources were bound
in 329 CAT occurrences, normal and gloss in zero, and glow in 256. This is a
structural census, not 330 runtime tests. Indirect references in opaque data,
engine-side material resolution and filename-based lookup remain possible;
the actual NM/SM selection algorithm is unknown.

Runtime anchors are the ordinary player dragon and the Farm B experiments.
The mesh-disconnection test detached geometry from its hierarchy; it did not
delete every geometry byte. Results do not establish universal fallback rules,
all asset variants, complete animation correctness or all map-loading paths.

Before editing: identify the actual asset, inspect ownership and missing
dependencies, retain the original package, review Builder's changed-resource
list, and test the resulting patch in the game. **Preserve uncertain bindings
instead of “repairing” them by guesswork.**

