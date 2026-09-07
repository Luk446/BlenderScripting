# Mooring chain dataset

Copy the entire contents of `blender_pylauncher.py` into Blender's Text Editor,
replacing the old embedded generator. Press **Run Script**. The launcher reads
`C:\Users\Luke\Documents\Blends\generate_dataset.py` from disk on every run.
Save external edits before running. Save the `.blend` after replacing its text
if you want the launcher retained in the project.

Edit settings at the top of `generate_dataset.py`. Defaults generate 10 images
at 640 × 640 in the existing Pictures output location. Each batch creates a
unique `run_...` subfolder containing image/label pairs, `metadata.csv`,
`settings.json`, and copies of the generator and annotation helper.
`MASTER_SEED` repeats scene choices when starting with
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
to the original frame. Existing World Volume Scatter density is selected between
0.04 and 0.20 without adding a new volume. The current particles are visually prominent; reduce
`PARTICLE_SIZE_MULTIPLIERS` if needed after reviewing previews.

Transforms, visibility, lights, world, particle settings and render settings are
restored after completion or a Python error. The generator does not save the
blend. Avoid editing the scene while it runs. Blender may be busy during renders.
The generator also produces **YOLO OBB labels**, with class `0: link`.

`generate_dataset.original.py` preserves the original external script.
`validate_dataset.py` checks seeded repeatability, visibility metadata and scene
restoration, including a deliberate failure. Test outputs are in `validation/`.

## YOLO OBB annotations and review

The unchanged Blender launcher loads the latest generator and `yolo_obb.py` on
every run. Keep these files together. Blender needs no additional Python packages
for labels. The external viewer needs OpenCV and NumPy in the Python environment
used to run it; `yoloinstall.py` is not needed by the generator.

Annotation controls have their own comment block near the top of the generator.
The initial setting `REVIEW_ALL_ANNOTATIONS = True` keeps all pilot images out of
training until reviewed. Output layout:

```text
run_.../
  review/images/train/chain_00000.png  # Pilot and flagged images
  review/labels/train/chain_00000.txt  # Candidate YOLO labels for review
  images/train/                      # Only pairs with no review flags
  labels/train/
  annotations/chain_00000.json        # Every link, visibility and exclusion reason
  train_ready.txt                    # Only unflagged, complete image/label pairs
  metadata.csv
  settings.json
```

The run directory name is the synthetic group ID, recorded in each annotation
report. The intended split is training only. Keep independent real capture runs
for validation and test; no random frame split or synthetic validation set is
created. `train_ready.txt` can be used as the training image list in your pipeline
configuration once there are reviewed/ready pairs. No dataset YAML is created
because the real validation paths belong to that pipeline.

Box geometry uses evaluated mesh vertices in **pixel coordinates**, with Y=0 at
the top. The centre is the projected local mesh-bounds midpoint, independent of
vertex density. The longest scaled local mesh dimension defines the physical
link axis; the tight enclosing rectangle follows its projection. This assumes
the link meshes' local axes follow their shape, as in the supplied scene. A
foreshortened axis shorter than the transverse box side is flagged. Final corners
are normalised by width and height separately; angle metadata is clockwise from
image-right, modulo 180 degrees.

For cropped links, the centre must be inside the image. The projected hull is
clipped to the image and fitted at the same axis angle. A rotated rectangle around
that polygon can still cross the image boundary. Such cases are **unresolved**:
the full candidate rectangle stays in JSON, no malformed/clamped box is written,
and the entire image is quarantined for review. Resolve the boundary annotation
or leave the image out of training; do not approve a pair with missing labels.

Visibility is estimated using deterministic surface rays, comparing the link's
own surface against scene occluders. No visible samples means no candidate label
and a whole-image review flag, rather than a confident hidden-object target.
Low sample visibility, small projections, fog, particles and render/viewport
visibility mismatches also flag the image. These are geometric estimates, **not
mask area fractions or proof of recognisability**. Materials, transparency and
fog require visual judgement. Numerical thresholds are provisional pilot controls.
Turning off pilot review does not bypass these other flags.

Generate review overlays from normal Python:

```powershell
python view_yolo_obb.py "C:\path\to\run_..."
```

Green rectangles are candidate labels present in the TXT; red rectangles are
unresolved candidates present only in JSON. A yellow header marks review images.
Review each PNG with its JSON reasons. Correct incomplete labels before moving
approved image/label pairs together from `review/` into the main `images/train/`
and `labels/train/` directories and adding `./images/train/<name>.png` to
`train_ready.txt`. Record that approval/correction in its annotation JSON. Images
that cannot be labelled consistently should remain outside training.

Old exports used bottom-origin Y values and clamped corners; regenerate them with
the corrected generator. The new viewer expects top-origin YOLO coordinates and
does not compensate for the old export error. Malformed or missing labels now
raise errors instead of silently producing reassuring empty previews.

`DRY_RUN = True` produces reports and metadata only, with no orphan TXT files.
Interrupted renders/annotation failures leave images under `_pending/`, outside
the training image folders. Existing batches and the `.blend` are not rewritten.

Validation: `python -m unittest test_yolo_obb -v` checks geometry and pair routing.
Run `validate_yolo_obb.py` in background Blender with `--factory-startup` for
projection, stable centre and occlusion checks. Run `validate_dataset.py` with
`ChainLinkScene.blend` for generator state restoration and reproducibility.
