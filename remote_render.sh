#!/usr/bin/env bash
# Run from the VM. Override RENDER_HOST, RENDER_ROOT or RENDER_BLENDER if needed.
set -euo pipefail
local_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
host="${RENDER_HOST:-luke_admin@iris}"
remote_root="${RENDER_ROOT:-/home/luke_admin/BlenderScripting}"
blender="${RENDER_BLENDER:-/home/luke_admin/apps/blender-5.2.1-linux-x64/blender}"
ssh_command=(ssh -o BatchMode=yes -o ConnectTimeout=15 "$host")

remote() {
    local command
    printf -v command '%q ' "$@"
    "${ssh_command[@]}" "$command"
}

usage() {
    cat <<'EOF'
Usage: bash remote_render.sh sync
       bash remote_render.sh check
       bash remote_render.sh start JOB IMAGES [render_batches.py options]
       bash remote_render.sh resume JOB IMAGES [same options as start]
       bash remote_render.sh status JOB
       bash remote_render.sh fetch JOB

Example: bash remote_render.sh start pilot_001 1000 --batch-size 100 --seed 10000
Default: 640x640, saved scene engine/samples. Add --engine cycles --samples 128
for Cycles/OptiX. Each start runs in a detached tmux session named blend-JOB.
EOF
}

action="${1:-help}"
if [[ "$action" == help || "$action" == --help ]]; then usage; exit 0; fi
shift
case "$action" in
    sync)
        # A new rsync file replaces the destination only after transfer completes.
        remote mkdir -p "$remote_root"
        rsync -a --partial -e 'ssh -o BatchMode=yes' \
            "$local_root/ChainLinkScene.blend" "$local_root/"*.py \
            "$local_root/README.md" "$local_root/remote_render.sh" \
            "$host:$remote_root/"
        ;;
    check)
        remote "$blender" --background --factory-startup --disable-autoexec \
            "$remote_root/ChainLinkScene.blend" --python-exit-code 1 \
            --python "$remote_root/render_headless.py" -- --check-only
        ;;
    start|resume|status|fetch)
        job="${1:?Supply a job name}"
        shift
        if [[ ! "$job" =~ ^[a-zA-Z0-9][a-zA-Z0-9_-]*$ ]]; then
            echo 'Job names must contain only letters, digits, underscores and hyphens.' >&2
            exit 2
        fi
        if [[ "$action" == fetch ]]; then
            mkdir -p "$local_root/outputs/$job"
            rsync -a --partial -e 'ssh -o BatchMode=yes' \
                "$host:$remote_root/outputs/$job/" "$local_root/outputs/$job/"
        elif [[ "$action" == status ]]; then
            if remote tmux has-session -t "=blend-$job" 2>/dev/null; then
                echo 'Session: running'
            else
                echo 'Session: stopped (check completion marker and log below)'
            fi
            remote cat "$remote_root/outputs/$job/progress.json" || true
            if remote test -f "$remote_root/outputs/$job/complete.json"; then echo 'Job: complete'; fi
            remote tail -n 15 "$remote_root/logs/$job.log"
        else
            count="${1:?Supply the total image count}"
            shift
            if [[ ! "$count" =~ ^[1-9][0-9]*$ ]]; then echo 'Image count must be positive.' >&2; exit 2; fi
            # Fail synchronously before opening tmux for accidental output reuse.
            if [[ "$action" == start ]]; then
                if remote test -e "$remote_root/outputs/$job"; then
                    echo 'Job exists. Use resume with the original settings, or choose a new name.' >&2
                    exit 2
                fi
            else
                remote test -f "$remote_root/outputs/$job/job.json"
            fi
            remote mkdir -p "$remote_root/logs"
            resume_args=()
            if [[ "$action" == resume ]]; then resume_args=(--resume); fi
            printf -v command '%q ' python3 -u "$remote_root/render_batches.py" \
                --blender "$blender" --blend "$remote_root/ChainLinkScene.blend" \
                --output "$remote_root/outputs/$job" --images "$count" "${resume_args[@]}" "$@"
            printf -v log_path '%q' "$remote_root/logs/$job.log"
            remote tmux new-session -d -s "blend-$job" "$command >> $log_path 2>&1"
            echo "Started blend-$job on $host. Use: bash remote_render.sh status $job"
        fi
        ;;
    *) usage >&2; exit 2 ;;
esac
