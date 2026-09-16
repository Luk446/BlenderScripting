# Rendering to the NAS without sudo

All new headless animation and dataset outputs must be on the Frontier NAS.
On iris use `/home/luke_admin/nas/frontier-home/BlenderSimDatasetNAS`; on the
VM the same files are at `/mnt/frontier-home/BlenderSimDatasetNAS`.

## User-owned mount on iris

Rclone is installed at `/home/luke_admin/.local/bin/rclone` (v1.75.1, official
archive SHA-256 verified). No sudo, system packages or fstab changes are needed.
From your terminal:

```bash
ssh -t luke_admin@iris 'python3 /home/luke_admin/BlenderScripting/setup_nas_user.py'
```

Enter your NAS username and password only at the terminal prompts. The script
uses the LAN host `192.168.67.251` automatically; add `--host 100.95.237.42` when
only Tailscale access is available. It stores the obscured password in your own
`~/.config/rclone/frontier.conf` with permissions 0600. Obscuring is reversible,
so treat this file as a credential. Do not commit or share it.

The FUSE mount runs as your account in the background. Repeat the same command
after an iris reboot; existing credentials are reused. Do not use the earlier
`setup_nas_mount.py` sudo installer on iris.

Rclone uses `--vfs-cache-mode writes --vfs-write-back 5s` for Blender-compatible
seeking, renames and append operations. Files temporarily occupy
`~/.cache/rclone-frontier` and upload when closed. Closed uploaded cache files
expire after about a minute. Mount diagnostics stay in
`~/.cache/rclone-frontier-mount.log`. Never delete the cache with pending writes;
restart the mount with the same settings to retry interrupted uploads.

Sources: [rclone SMB](https://rclone.org/smb/),
[mount and write cache](https://rclone.org/commands/rclone_mount/).

## Render an animation

On iris:

```bash
cd /home/luke_admin/BlenderScripting/animation_20260916
BLENDER=/home/luke_admin/apps/blender-5.2.1-linux-x64/blender
NAS=/home/luke_admin/nas/frontier-home/BlenderSimDatasetNAS
python3 nas_storage.py "$NAS/animations/animation_002"
mkdir -p "$NAS/animations/animation_002"
"$BLENDER" -b --factory-startup --disable-autoexec ChainLinkScene_camera_path.blend \
  --python-exit-code 1 --python animation_scene.py -- render \
  --start 1 --end 1 --samples 16 --percentage 25 \
  --output "$NAS/animations/animation_002/preview"
```

The camera and its target follow the existing `Camera_Path` and `Target_Path`
from frames 1 through 200. The saved resolution is 640 x 640 at 24 fps.
The entry point refuses local output paths and missing/read-only NAS mounts.

For all 200 frames in detached tmux, after the directory/preflight commands above:

```bash
tmux new-session -d -s blend-animation-002 \
  'cd /home/luke_admin/BlenderScripting/animation_20260916 && /home/luke_admin/apps/blender-5.2.1-linux-x64/blender -b --factory-startup --disable-autoexec ChainLinkScene_camera_path.blend --python-exit-code 1 --python animation_scene.py -- render --samples 64 --output /home/luke_admin/nas/frontier-home/BlenderSimDatasetNAS/animations/animation_002/frames > /home/luke_admin/nas/frontier-home/BlenderSimDatasetNAS/animations/animation_002/render.log 2>&1; result=$?; printf "%s\n" "$result" > /home/luke_admin/nas/frontier-home/BlenderSimDatasetNAS/animations/animation_002/render.exit'
tail -n 20 "$NAS/animations/animation_002/render.log"
cat "$NAS/animations/animation_002/render.exit"
```

The render requires exit code 0 and `COMPLETE: 200 frames`. Completion of Blender
alone does not prove queued writes have reached the NAS. Before shutting down
iris or unmounting, verify the closed job against the actual SMB backend:

```bash
~/.local/bin/rclone --config ~/.config/rclone/frontier.conf check --download \
  "$NAS/animations/animation_002" \
  frontier:home/BlenderSimDatasetNAS/animations/animation_002
```

If uploads are still pending, wait and rerun until the check succeeds. Read
the mount log if transfers stall. Use a new job/output name on each rerun.
For an interrupted render, use `--start N --end 200` and a new NAS output folder
after checking the last complete frame. SSH disconnection does not stop tmux.

Encode on iris with the MP4 also on the NAS, then repeat the backend check:

```bash
ffmpeg -nostdin -n -framerate 24 -start_number 1 \
  -i "$NAS/animations/animation_002/frames/frame_%04d.png" \
  -frames:v 200 -c:v libx264 -crf 18 -pix_fmt yuv420p \
  "$NAS/animations/animation_002/animation.mp4"
```

## Dataset jobs

`remote_render.sh start JOB ...` now writes to NAS `render_jobs/JOB` and
`render_logs/JOB.log`. `fetch JOB` reports the corresponding VM NAS path without
creating a local download. Verify closed jobs with the same `rclone check
--download` pattern, excluding `--exclude .lock` because the lock is a worker
coordination file. Use one render worker on iris. On the user FUSE mount,
the existing flock guards only workers using that same mount, not another host.
Historical archived jobs contain their original absolute paths and are not
new resumable NAS jobs. Do not change those manifests to bypass resume checks.

Do not use dataset `sync` while the local `ChainLinkScene.blend` is empty;
it would overwrite the valid remote source. Scripts have been deployed separately.

## Existing outputs

The NAS archive contains existing rendered outputs; local originals are retained.
Source scenes and existing top-level logs were excluded from migration.

```text
/mnt/frontier-home/BlenderSimDatasetNAS/RenderArchive/
  iris_20260916/animation_20260916/animation_001.mp4
  iris_20260916/animation_20260916/frames_001/frame_0001.png ... frame_0200.png
  iris_20260916/animation_20260916/preview_first/
  iris_20260916/animation_20260916/preview_last/
  iris_20260916/outputs/
  vm_20260916/outputs/
```

The original animation completed at 640 x 640, 64 samples, Cycles/OptiX on the
RTX 5090 in about 5 minutes 18 seconds. It is approximately 8.33 seconds at 24 fps.

## Verified on 2026-09-16

The user mount is active as `fuse.rclone`, source `frontier:home`, uid/gid 1006.
A new OptiX animation test wrote `animations/nas_smoke_20260916/frame_0001.png`;
the VM opened the PNG through its independent CIFS mount, and a direct SMB
`rclone check --download` reported zero differences. A one-image Cycles dataset
job also completed successfully under `render_jobs/nas_smoke_20260916`, including
annotations, script snapshots, batch log and completion markers. A second job,
`render_jobs/nas_verified_20260916`, passed direct SMB verification with 21
matching files and zero differences. Use the configured 5-second write-back
delay: zero-delay uploading caused temporary-file rename races in the first
dataset probe; its completion files were subsequently recovered to the NAS.
Guard and
batch-resume regression tests pass. The archive's animation and VM output
contents match their sources by checksum; CIFS timestamps/permissions differ.
