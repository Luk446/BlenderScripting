import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from nas_storage import NAS_ROOT, require_nas


class NasStorageTests(unittest.TestCase):
    def test_local_destination_rejected(self):
        with self.assertRaisesRegex(RuntimeError, 'must be under'):
            require_nas('/tmp/render')

    def check_mount(self, source, filesystem, options):
        result = SimpleNamespace(stdout=json.dumps({'filesystems': [
            dict(source=source, fstype=filesystem, options=options)]}))
        with patch.object(Path, 'resolve', lambda path: path), \
                patch.object(Path, 'stat'), patch.object(Path, 'exists', return_value=True), \
                patch('nas_storage.subprocess.run', return_value=result):
            return require_nas(NAS_ROOT / 'animations/test')

    def test_writable_frontier_mounts_accepted(self):
        for source, filesystem in [('//192.168.67.251/home', 'cifs'),
                                    ('frontier:home', 'fuse.rclone')]:
            self.assertEqual(self.check_mount(source, filesystem, 'rw,relatime'),
                             NAS_ROOT / 'animations/test')

    def test_local_readonly_and_wrong_share_rejected(self):
        for source, filesystem, options in [('/dev/sda1', 'ext4', 'rw'),
                                            ('//192.168.67.251/home', 'cifs', 'ro'),
                                            ('//other/share', 'cifs', 'rw'),
                                            ('other:home', 'fuse.rclone', 'rw')]:
            with self.subTest(source=source, options=options), self.assertRaises(RuntimeError):
                self.check_mount(source, filesystem, options)


if __name__ == '__main__':
    unittest.main()
