"""Exercise interruption/resume using a small subprocess stand-in for Blender."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import unittest

SOURCE = Path(__file__).resolve().parent


class BatchResumeTests(unittest.TestCase):
    def test_resume_skips_completed_batches_and_rejects_missing_pairs(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fake = root / 'blender'
            fake.write_text('#!'+sys.executable+'\n'+textwrap.dedent('''\
                import csv, json, pathlib, sys
                args = sys.argv[sys.argv.index('--')+1:]
                options = dict(zip(args[::2], args[1::2]))
                output = pathlib.Path(options['--output'])
                count, seed = int(options['--images']), int(options['--seed'])
                with (output.parent/'calls.txt').open('a') as log:
                    log.write(str(seed)+'\\n')
                fail = output.parent/'fail_once'
                if seed == 44 and not fail.exists():
                    fail.touch()
                    sys.exit(1)
                run = output/'run_test'
                run.mkdir()
                (run/'annotations').mkdir()
                with (run/'metadata.csv').open('w') as stream:
                    writer = csv.DictWriter(stream, fieldnames=[
                        'filename', 'seed', 'rendered', 'image_path', 'label_path'])
                    writer.writeheader()
                    for index in range(count):
                        name = f'chain_{index:05d}'
                        (run/(name+'.png')).write_bytes(b'fake image')
                        (run/(name+'.txt')).write_text('0 .1 .1 .2 .1 .2 .2 .1 .2')
                        (run/'annotations'/(name+'.json')).write_text('{}')
                        writer.writerow(dict(filename=name+'.png', seed=seed+index,
                            rendered=True, image_path=name+'.png', label_path=name+'.txt'))
                pathlib.Path(options['--result']).write_text(json.dumps(dict(
                    run_directory=str(run), images=count, seed=seed, dry_run=False)))
                '''))
            fake.chmod(0o755)
            scene = root / 'scene.blend'
            scene.write_bytes(b'test scene')
            job = root / 'job'
            command = [sys.executable, str(SOURCE/'render_batches.py'), '--blender', str(fake),
                       '--blend', str(scene), '--output', str(job), '--images', '5',
                       '--batch-size', '2', '--seed', '42', '--min-free-gb', '1']
            def run(extra=()):
                return subprocess.run(command+list(extra), capture_output=True, text=True)
            first = run()
            self.assertNotEqual(first.returncode, 0)
            self.assertIn('Blender exited 1', first.stderr)
            self.assertEqual(json.loads((job/'progress.json').read_text())['completed_images'], 2)
            resumed = run(['--resume'])
            self.assertEqual(resumed.returncode, 0, resumed.stderr)
            self.assertEqual((job/'calls.txt').read_text().splitlines(), ['42', '44', '44', '46'])
            self.assertEqual(json.loads((job/'complete.json').read_text())['images'], 5)
            again = run(['--resume'])
            self.assertEqual(again.returncode, 0, again.stderr)
            self.assertEqual(len((job/'calls.txt').read_text().splitlines()), 4)
            self.assertNotEqual(run().returncode, 0, 'An existing job must not be overwritten')
            mismatch = run(['--resume', '--width', '1280'])
            self.assertNotEqual(mismatch.returncode, 0)
            self.assertIn('settings differ', mismatch.stderr)
            (job/'batch_00000000'/'run_test'/'chain_00000.txt').unlink()
            missing = run(['--resume'])
            self.assertNotEqual(missing.returncode, 0)
            self.assertIn('Missing label_path', missing.stderr)


if __name__ == '__main__':
    unittest.main()
