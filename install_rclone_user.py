"""Install checksum-verified rclone under the current user's home."""
import hashlib
from pathlib import Path
import re
import urllib.request
import zipfile
import io

base = 'https://downloads.rclone.org/'
version = urllib.request.urlopen(base + 'version.txt', timeout=30).read().decode().strip()
if not re.fullmatch(r'rclone v\d+\.\d+\.\d+', version):
    raise RuntimeError('Unexpected rclone version response')
version = version.split()[1]
name = f'rclone-{version}-linux-amd64.zip'
checksums = urllib.request.urlopen(f'{base}{version}/SHA256SUMS', timeout=30).read().decode()
expected = next(line.split()[0] for line in checksums.splitlines()
                if len(line.split()) == 2 and line.split()[-1].lstrip('*') == name)
archive = urllib.request.urlopen(f'{base}{version}/{name}', timeout=120).read()
if hashlib.sha256(archive).hexdigest() != expected:
    raise RuntimeError('rclone checksum mismatch')
target = Path.home() / '.local/bin/rclone'
target.parent.mkdir(parents=True, exist_ok=True)
if target.exists():
    raise RuntimeError(f'Refusing to replace existing {target}')
with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
    target.write_bytes(bundle.read(f'rclone-{version}-linux-amd64/rclone'))
target.chmod(0o755)
print(f'Installed {version} at {target}; SHA256 verified')
