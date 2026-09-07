# Mooring chain dataset

Copy the entire contents of `blender_pylauncher.py` into Blender's Text Editor,
replacing the old embedded generator. Press **Run Script**. The launcher reads
`C:\Users\Luke\Documents\Blends\generate_dataset.py` from disk on every run.
Save external edits before running. Save the `.blend` after replacing its text
if you want the launcher retained in the project.

Edit settings at the top of `generate_dataset.py`. Defaults generate 20 images
at 640 × 640 in the existing Pictures output location. Each batch creates a
unique `run_...` subfolder containing PNGs, `metadata.csv`, `settings.json`, and
a copy of the generator. `MASTER_SEED` repeats scene choices when starting with
the same scene and settings; it does not promise bit-identical GPU renders.
`DRY_RUN = True` performs placement and writes metadata without rendering.

The generator treats a structure and its child meshes as one asset. It uses
evaluated geometry bounds for conservative clearance checks, places the whole
asset beyond the chain along the viewing direction, and samples surface rays
to reject off-screen or occluded placements. Camera positions avoid chain
bounds and stay above the selected seabed surface. At least three link centres
must be in frame; close-ups with cropped links are intentional.

Large structures may be skipped, even with `FORCE_STRUCTURES_FOR_TEST = True`.
The CSV records selected, skipped and ray-visible structures. These visibility
checks do not guarantee sufficient brightness or contrast. Structures can
intersect terrain; terrain contact/grounding is not solved by this generator.
The conservative bounds can reject physically valid placements of long pipes.

Link poses remain as authored to preserve their connection. Particle count and
size vary around the existing ParticleCube settings, with simulation advanced
to the original frame. Existing world volume density is varied without adding
a new volume. The current particles are visually prominent; reduce
`PARTICLE_SIZE_MULTIPLIERS` if needed after reviewing previews.

Transforms, visibility, lights, world, particle settings and render settings are
restored after completion or a Python error. The generator does not save the
blend. Avoid editing the scene while it runs. Blender may be busy during renders.
This generates images and metadata, **not YOLO OBB labels**.

`generate_dataset.original.py` preserves the original external script.
`validate_dataset.py` checks seeded repeatability, visibility metadata and scene
restoration, including a deliberate failure. Test outputs are in `validation/`.
