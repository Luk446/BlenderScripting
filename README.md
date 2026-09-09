# Mooring chain dataset

## Remote GPU rendering from this VM

The VM checkout is `/home/Luke/BlenderScripting`. The GPU machine is
`luke_admin@iris`, with the remote project at `/home/luke_admin/BlenderScripting`.
Blender **5.2.1 LTS** is installed at
`/home/luke_admin/apps/blender-5.2.1-linux-x64/blender`; its bundled Python has
Pillow **12.3.0** for padded annotation exports. The scene was saved with Blender
5.2, and its textures are packed. No display or X forwarding is needed.

From a terminal in this VM:

```bash
cd /home/Luke/BlenderScripting
bash remote_render.sh check

# After changing local scripts or the scene, sync before starting a new job.
# Wait for active render jobs to finish before replacing the scene.
bash remote_render.sh sync

# Example production job: 1,000 images in batches of 100.
bash remote_render.sh start chains_001 1000 --batch-size 100 --seed 10000
bash remote_render.sh status chains_001

# Download the job into this checkout's outputs/chains_001 directory.
bash remote_render.sh fetch chains_001
```

`start` runs in a detached **tmux** session on iris, so rendering continues when
SSH disconnects or the VM shuts down. A reboot of iris stops the job; resume it
afterward. Choose a new job name for each dataset and a nonoverlapping seed range
for different batches. `--seed 10000` with 1,000 images uses seeds 10000–10999.
The helper supports `RENDER_HOST`, `RENDER_ROOT` and `RENDER_BLENDER` environment
variables if the host or installation paths change.

Defaults are **640 × 640**, the **saved render engine**, and its saved sample
count. This scene uses **Eevee at 64 samples**. Eevee uses the graphics driver's
default GPU. To render with Cycles on the RTX 5090 using OptiX instead:

```bash
bash remote_render.sh start cycles_001 1000 \
  --engine cycles --samples 128 --batch-size 100 --seed 20000
```

Switching engines changes appearance and timing. Set `--width 1280 --height 1280`
for larger images. `--samples` overrides render samples for the chosen engine;
otherwise they remain as authored. `--backend CUDA` and `--device N` select a
Cycles backend/device; they do not select Eevee's graphics device. The run fails
if the requested Cycles GPU is unavailable. Start one render job at a time on
this single-GPU machine.

The initial ten-image Eevee pilot at 640 × 640 completed in approximately 14
seconds, including two Blender startups, placement, annotations and export.
This is a small setup benchmark, not a guaranteed rate for larger jobs or Cycles.
Test runs are under `outputs/smoke_20260909` and `outputs/pilot_setup_20260909`.
An additional 128-sample Cycles/OptiX test completed in approximately 3 seconds
for one image, with NVIDIA's process monitor confirming Blender on the RTX 5090.
It is under `outputs/cycles_smoke_20260909`. The ten-image pilot was fetched to
the VM and has overlays inside each completed run's `overlays/` directory.

### Progress, interruption and resume

The main log is `logs/JOB.log` on iris. Detailed Blender logs, including errors,
are inside `outputs/JOB/batch_*/render_*.log`. `progress.json` records completed
images; the job's top-level `complete.json` appears only after all batches finish.
To inspect a running terminal:

```bash
ssh -t luke_admin@iris 'tmux attach -t blend-chains_001'
```

Detach with **Ctrl+B**, then **D**. **Ctrl+C** stops the job. To resume a stopped
or failed job, repeat its original arguments using `resume`:

```bash
bash remote_render.sh resume chains_001 1000 --batch-size 100 --seed 10000
```

Completed batches are checked and skipped. The interrupted batch restarts into
a new `run_...` folder using the same seeds; its earlier incomplete attempt is
retained for diagnosis. Use the `completed_runs` list in `progress.json` or
`complete.json` to identify successful runs. Do not combine failed attempts with
their replacements. Smaller batches lose less work after interruption; larger
batches reduce Blender startup overhead.

Each job snapshots the generator/helper/entry-point scripts and records scene
and Blender executable SHA-256 hashes. Resume rejects changed settings or a
changed scene/executable. Script edits affect new jobs; resumed jobs use their
saved scripts. Keep the scene and any unpacked external assets unchanged while
a job runs. A lock prevents two workers from running the same job. The runner
checks for at least 20 GiB free before each batch and stops if below that level;
this is a reserve check, not a prediction of the next batch's disk usage.

### Outputs and review

Render to iris's local disk, then fetch results to the VM or copy them to the
NAS. The command-line entry point overrides the generator's Windows/NAS output
path without editing its desktop defaults. Native Linux mounts are required to
write to a NAS directly; Windows UNC paths are not Linux mount paths.

Every successful batch contains the existing `run_...` layout with image/label
pairs, metadata, settings, annotation reports and an additional
`render_runtime.json`. All generated annotations remain pending human review.
For example, after fetching a job:

```bash
python3 view_yolo_obb.py outputs/chains_001/batch_00000000/run_...
```

Use the approval workflow below after inspecting the overlays. Retain each run
folder's identity: filenames restart at `chain_00000.png` in each batch, so
flattening batches into one folder would overwrite images. Padded image/label
pairs must remain together. Outputs and logs are ignored by Git.

### Installation and checks

The installed Linux archive was downloaded from the
[official Blender 5.2 release directory](https://download.blender.org/release/Blender5.2/)
and verified against `blender-5.2.1.sha256`. The archive and checksum are retained
in `/home/luke_admin/apps/downloads`. No system Blender or driver was replaced.
For a replacement installation, extract the verified archive under `apps`, then
install Pillow into that Blender's Python:

```bash
ssh -o BatchMode=yes luke_admin@iris \
  '/home/luke_admin/apps/blender-5.2.1-linux-x64/5.2/python/bin/python3.13 -m pip install Pillow==12.3.0'
```

`render_headless.py --check-only` verifies render-asset paths, Pillow and GPU
discovery; an actual test render is still needed to check rendering itself.
The low-level Blender command is:

```bash
ssh -o BatchMode=yes luke_admin@iris \
  '/home/luke_admin/apps/blender-5.2.1-linux-x64/blender \
    --background --factory-startup --disable-autoexec \
    /home/luke_admin/BlenderScripting/ChainLinkScene.blend \
    --python-exit-code 1 \
    --python /home/luke_admin/BlenderScripting/render_headless.py -- --check-only'
```

`--disable-autoexec` prevents saved embedded scripts from running; the explicit
headless script controls generation. See Blender's
[command-line documentation](https://docs.blender.org/manual/en/5.2/advanced/command_line/arguments.html).
Local regression checks: `python3 -m unittest test_yolo_obb test_render_batches -v`.
The existing `validate_yolo_obb.py` and `validate_dataset.py` checks also pass in
Blender 5.2.1 on iris, covering geometry, occlusion, repeatability and restoration.

## Desktop Blender launcher

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
