"""Run sequential Blender batches on Linux, resuming only completed batches."""
import argparse
import csv
from datetime import datetime, timezone
import fcntl
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time

from render_headless import positive

SOURCE = Path(__file__).resolve().parent
SCRIPTS = ('generate_dataset.py', 'yolo_obb.py', 'render_headless.py')


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def write_json(path, value):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, indent=2)+'\n', encoding='utf-8')
    temporary.replace(path)


def completed_batch(marker, count, seed):
    """Check actual pairs before accepting a completion marker on resume."""
    result = json.loads(marker.read_text())
    if result['images'] != count or result['seed'] != seed or result['dry_run']:
        raise RuntimeError(f'Unexpected batch result: {marker}')
    run = Path(result['run_directory'])
    with (run / 'metadata.csv').open(newline='', encoding='utf-8') as stream:
        rows = list(csv.DictReader(stream))
    if len(rows) != count:
        raise RuntimeError(f'Incomplete metadata: {run}')
    for index, row in enumerate(rows):
        if row['rendered'] != 'True' or int(row['seed']) != (seed+index) % 2**31:
            raise RuntimeError(f'Unexpected image seed or render status: {run}')
        for key in ('image_path', 'label_path'):
            if not row[key] or not (run / row[key]).is_file():
                raise RuntimeError(f'Missing {key} in {run}')
        if not (run / 'annotations' / Path(row['filename']).with_suffix('.json')).is_file():
            raise RuntimeError(f'Missing annotation report in {run}')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--blender', type=Path, required=True)
    parser.add_argument('--blend', type=Path, default=SOURCE / 'ChainLinkScene.blend')
    parser.add_argument('--output', type=Path, required=True, help='unique job directory')
    parser.add_argument('--images', type=positive, required=True)
    parser.add_argument('--batch-size', type=positive, default=100)
    parser.add_argument('--width', type=positive, default=640)
    parser.add_argument('--height', type=positive, default=640)
    parser.add_argument('--seed', type=int, default=42)
    parser.add_argument('--samples', type=positive)
    parser.add_argument('--engine', choices=['scene', 'cycles', 'eevee'], default='scene')
    parser.add_argument('--backend', choices=['OPTIX', 'CUDA'], default='OPTIX')
    parser.add_argument('--device', type=int, default=0)
    parser.add_argument('--min-free-gb', type=positive, default=20)
    parser.add_argument('--resume', action='store_true')
    args = parser.parse_args()
    if args.images > 2**31 or not 0 <= args.seed < 2**31 or args.device < 0:
        parser.error('use a nonnegative device, seed in [0, 2**31), and at most 2**31 images')
    args.blender = args.blender.resolve(strict=True)
    args.blend = args.blend.resolve(strict=True)
    output = args.output.resolve()
    existed = output.exists()
    if existed and not args.resume:
        parser.error('output exists; choose a new job directory or use --resume')
    if args.resume and not (output / 'job.json').is_file():
        parser.error('--resume requires an existing job.json')
    output.mkdir(parents=True, exist_ok=args.resume)
    # Keep the descriptor open throughout the run; the kernel releases on exit/crash.
    with (output / '.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            parser.error('this job is already running')
        settings = {name: getattr(args, name) for name in
                    ('images', 'batch_size', 'width', 'height', 'seed', 'samples', 'engine', 'backend', 'device')}
        settings['blender'] = str(args.blender)
        settings['blender_sha256'] = digest(args.blender)
        if args.resume:
            job = json.loads((output / 'job.json').read_text())
            if job['settings'] != settings:
                parser.error('resume settings differ from job.json; use the original arguments')
            for filename, expected in job['input_sha256'].items():
                if digest(output / 'inputs' / filename) != expected:
                    raise RuntimeError(f'Job input changed: {filename}')
        else:
            inputs = output / 'inputs'
            inputs.mkdir()
            # Snapshot source code; keep the blend in its original directory so
            # relative external assets retain their meaning. Its hash is checked
            # again on resume and before each new batch.
            for filename in SCRIPTS:
                shutil.copy2(SOURCE / filename, inputs / filename)
            job = dict(settings=settings, blend=str(args.blend),
                       blend_sha256=digest(args.blend),
                       input_sha256={name: digest(inputs / name) for name in SCRIPTS},
                       created_utc=datetime.now(timezone.utc).isoformat())
            write_json(output / 'job.json', job)
        if str(args.blend) != job['blend'] or digest(args.blend) != job['blend_sha256']:
            raise RuntimeError('Scene changed since job creation; use a new job directory')
        results = []
        for start in range(0, args.images, args.batch_size):
            count = min(args.batch_size, args.images-start)
            seed = (args.seed+start) % 2**31
            batch = output / f'batch_{start:08d}'
            batch.mkdir(exist_ok=True)
            marker = batch / 'complete.json'
            if not marker.exists():
                if digest(args.blend) != job['blend_sha256']:
                    raise RuntimeError('Scene changed while this job was running')
                free = shutil.disk_usage(output).free / 1024**3
                if free < args.min_free_gb:
                    raise RuntimeError(f'Only {free:.1f} GiB free; stopped before the next batch')
                attempt = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_%f')
                log = batch / f'render_{attempt}.log'
                command = [str(args.blender), '--background', '--factory-startup',
                           '--disable-autoexec', str(args.blend), '--python-exit-code', '1',
                           '--python', str(output / 'inputs' / 'render_headless.py'), '--',
                           '--output', str(batch), '--images', str(count), '--width', str(args.width),
                           '--height', str(args.height), '--seed', str(seed), '--backend', args.backend,
                           '--device', str(args.device), '--engine', args.engine, '--result', str(marker)]
                if args.samples is not None:
                    command += ['--samples', str(args.samples)]
                print(f'Rendering images {start+1}–{start+count}: {log}', flush=True)
                started = time.monotonic()
                with log.open('w') as stream:
                    process = subprocess.run(command, stdout=stream, stderr=subprocess.STDOUT)
                if process.returncode != 0:
                    raise RuntimeError(f'Blender exited {process.returncode}; inspect {log}. '
                                       'Resume with the same arguments plus --resume.')
                print(f'Batch finished in {time.monotonic()-started:.1f}s', flush=True)
            results.append(completed_batch(marker, count, seed))
            write_json(output / 'progress.json', dict(completed_images=start+count,
                       total_images=args.images, completed_runs=results))
            print(f'Complete: {start+count}/{args.images}', flush=True)
        write_json(output / 'complete.json', dict(images=args.images, completed_runs=results))
        print(f'Job complete: {output}', flush=True)


if __name__ == '__main__':
    main()
