"""Configure and mount Frontier NAS using only the current user's account."""
import configparser
import argparse
import getpass
import os
from pathlib import Path
import subprocess

arguments = argparse.ArgumentParser(description=__doc__)
arguments.add_argument('--host', default='192.168.67.251',
                       choices=('192.168.67.251', '100.95.237.42', 'frontier-nas-1'))
args = arguments.parse_args()
home = Path.home()
binary = home / '.local/bin/rclone'
config = home / '.config/rclone/frontier.conf'
mount = home / 'nas/frontier-home'
config.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
mount.mkdir(parents=True, exist_ok=True)
if not config.exists():
    host = args.host
    print(f'Connecting to Frontier NAS at {host}')
    user = input('NAS username [luke]: ').strip() or 'luke'
    password = getpass.getpass('NAS password (hidden): ')
    if not password or any(c in password + user for c in '\r\n\0'):
        raise SystemExit('Credentials must be nonempty, single-line values')
    obscured = subprocess.run([str(binary), 'obscure', '-'], input=password + '\n',
                              capture_output=True, text=True, check=True).stdout.strip()
    del password
    parser = configparser.ConfigParser(interpolation=None)
    parser['frontier'] = dict(type='smb', host=host, user=user, **{'pass': obscured})
    descriptor = os.open(config, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, 'w') as stream:
        parser.write(stream)
    del obscured
if config.is_symlink() or config.stat().st_uid != os.getuid() or config.stat().st_mode & 0o077:
    raise SystemExit('Config must be owned by this user with mode 0600, without a symlink')
subprocess.run([str(binary), '--config', str(config), 'lsf', 'frontier:home',
                '--max-depth', '1'], check=True, stdout=subprocess.DEVNULL)
if not os.path.ismount(mount):
    if any(mount.iterdir()):
        raise SystemExit('Mount directory is not empty')
    subprocess.run([str(binary), '--config', str(config), 'mount', 'frontier:home',
                    str(mount), '--daemon', '--daemon-wait', '30s',
                    '--vfs-cache-mode', 'writes', '--vfs-write-back', '5s',
                    '--vfs-cache-max-age', '1m', '--vfs-cache-poll-interval', '30s',
                    '--cache-dir', str(home / '.cache/rclone-frontier'),
                    '--log-file', str(home / '.cache/rclone-frontier-mount.log')], check=True,
                   stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                   stderr=subprocess.DEVNULL)
print(f'NAS mounted at {mount}; no sudo used')
print('Closed files upload automatically. Keep the mount running until uploads finish.')
