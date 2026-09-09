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

## Network storage

For the current NAS workflow, set the generator output to a UNC path before
rendering:

```python
OUTPUT_FOLDER = r"\\frontier-nas-1\home\BlenderSimDatasetNAS"
```

Keep review overlays separate from the approved dataset:

```powershell
python view_yolo_obb.py "\\frontier-nas-1\home\BlenderSimDatasetNAS\run_..." `
  --output "\\frontier-nas-1\home\BlenderSimDatasetNAS\review_overlays\run_..."
```

Approve into a separate NAS destination, using `--exclude` once per rejected
image:

```powershell
python approve_yolo_obb.py "\\frontier-nas-1\home\BlenderSimDatasetNAS\run_..." `
  --output "\\frontier-nas-1\home\Approved_BlenderSimDatasetNAS\run_..." `
  --exclude chain_00003.png
```

The source run is not modified, and approval refuses to overwrite an existing
destination. Keep the `.blend`, scripts and Blender installation local. Verify
the share is writable before starting a large render.

`generate_dataset.original.py` preserves the original external script.
`validate_dataset.py` checks seeded repeatability, visibility metadata and scene
restoration, including a deliberate failure. Test outputs are in `validation/`.

## YOLO OBB annotations and review

**Detection requirement:** recognise individual links when approximately **70% of
their projected appearance is visible**, including cropped and occluded links,
provided identity and long-axis direction remain clear. A complete link is not
required. This is a 2-D visibility target, not a measurement of visible 3-D volume.
See [Partial-link annotation policy](docs/PARTIAL_LINK_POLICY.md) for definitions,
padding effects, review rules and the evaluation requirement.

The unchanged Blender launcher loads the latest generator and `yolo_obb.py` on
every run. Keep these files together. Blender needs no additional Python packages
for geometry calculations. Exporting boundary boxes with padded image canvases
uses Pillow, already installed in the current Blender Python environment. The
external viewer needs OpenCV and NumPy in its Python environment;
`yoloinstall.py` is not needed by the generator.

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

For cropped links, the centre must be inside the original image. The projected
hull is clipped to that image and fitted at the same axis angle. A rotated
rectangle around that polygon can still cross the image boundary.
`EXPORT_BOUNDARY_BOXES = True` now includes these visible-link boxes, adding only
enough neutral grey padding to contain their corners. All image coordinates and
labels shift together; rectangles retain their shape, angle and original size.
The exported canvas can be larger than the configured render size. Original
pixels are preserved, and unpadded renders are kept in `originals/`. JSON records
source/output dimensions and padding. Set the option to False to restore the
previous behaviour of withholding out-of-frame boxes as red review candidates.

Padding is an export accommodation, not a simulation of underwater occlusion.
It preserves the original pixels but adds visible grey borders. Resizing a larger
padded canvas to a fixed training size makes the link smaller; artificial borders
may also become a learned cue. The effect on accuracy has not been measured.
Include real partial-link examples and natural occlusion within the image, and
evaluate on real source images without this custom boundary padding. Do not treat
approved padded boxes as proof that the detector recognises 70%-visible links.

Visibility is estimated using deterministic surface rays, comparing the link's
own surface against scene occluders. No visible samples means no candidate label
and a whole-image review flag, rather than a confident hidden-object target.
Low sample visibility, small projections, fog, particles and render/viewport
visibility mismatches also flag the image. These are geometric estimates, **not
mask area fractions or proof of recognisability**. Materials, transparency and
fog require visual judgement. Numerical thresholds are provisional pilot controls.
Turning off pilot review does not bypass these other flags.

The current `visible_fraction` is conditional on sampled surface points already
inside the source frame and not self-hidden. It does not measure the fraction of
the full link lost to cropping. Neither that value nor
`LABEL_MIN_VISIBLE_FRACTION = 0.35` enforces the approximately 70% visibility
requirement. This remains a manual annotation/evaluation target until full-link
reference masks and visible masks are measured. Do not change the threshold to
0.70 and interpret it as a calibrated partial-link percentage.

Generate review overlays from normal Python:

```powershell
python view_yolo_obb.py "C:\path\to\run_..."
```

Green rectangles are labels present in the TXT; red rectangles are candidates
present only in JSON. A yellow header marks review images. Boundary candidates
with visible surface samples are now exported green by default. Fog/identity
checks still flag whole images independently of that geometric acceptance.

After visually approving all displayed boxes in an existing batch, use:

```powershell
python approve_yolo_obb.py "C:\path\to\run_..." --exclude chain_00001.png
```

Repeat `--exclude` for any other bad images; omit it if all images are approved.
This is an explicit human approval: even a displayed candidate missed by the
visibility sampler is included. Objects with no candidate rectangle or with
centres outside the original image are not invented or added. It writes a separate
dataset under `approved_datasets/<run name>/` in the current working directory;
`--output` can select another new destination. Existing destinations are refused.
The source batch is not modified. The derived dataset contains complete image/label
pairs, updated annotation reports, `train_ready.txt`, and `approval.json` recording
the source batch and excluded images. Any necessary padding is also applied to
old red boundary boxes so they become valid normalised YOLO rectangles.

Run the viewer on that approved dataset to regenerate all-green overlays. Use its
image/label pairs together; padded labels must not be paired with original,
unpadded images. The exported dataset remains training-only, with real capture
runs used for validation/test. Leave unidentifiable images out of the approval.

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
