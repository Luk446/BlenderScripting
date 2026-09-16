"""Require render destinations to live on the mounted Frontier NAS."""
import json
import os
from pathlib import Path
import subprocess
import sys

NAS_MOUNT = Path(os.environ.get('RENDER_NAS_MOUNT',
                 '/mnt/frontier-home' if Path('/mnt/frontier-home').exists()
                 else str(Path.home() / 'nas/frontier-home')))
NAS_ROOT = NAS_MOUNT / 'BlenderSimDatasetNAS'


def require_nas(destination):
    destination = Path(destination).resolve()
    if not destination.is_relative_to(NAS_ROOT):
        raise RuntimeError(f'Render output must be under {NAS_ROOT}: {destination}')
    # Access first to trigger systemd automount before checking its filesystem.
    NAS_ROOT.parent.stat()
    probe = destination
    while not probe.exists():
        probe = probe.parent
    result = subprocess.run(['findmnt', '--json', '--target', str(probe),
                             '--output', 'SOURCE,FSTYPE,OPTIONS'],
                            check=True, capture_output=True, text=True)
    mounts = json.loads(result.stdout)['filesystems']
    if not any(((m['fstype'] == 'cifs' and m['source'] in
                ('//192.168.67.251/home', '//100.95.237.42/home', '//frontier-nas-1/home'))
                or (m['fstype'] == 'fuse.rclone' and m['source'] == 'frontier:home'))
               and 'rw' in m['options'].split(',') for m in mounts):
        raise RuntimeError('Frontier NAS is not mounted read/write; refusing local fallback')
    return destination


if __name__ == '__main__':
    print(require_nas(sys.argv[1]))
