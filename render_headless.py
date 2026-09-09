"""Blender entry point for GPU rendering; arguments follow Blender's -- separator."""
import argparse
import csv
import json
from pathlib import Path
import sys
import time


def positive(value):
    value = int(value)
    if value < 1:
        raise argparse.ArgumentTypeError('must be positive')
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--images', type=positive, default=1)
    parser.add_argument('--width', type=positive, default=640)
    parser.add_argument('--height', type=positive, default=640)
    parser.add_argument('--seed', type=int, default=42)
    parser.add_argument('--samples', type=positive, help='default: saved scene setting')
    parser.add_argument('--engine', choices=['scene', 'cycles', 'eevee'], default='scene')
    parser.add_argument('--backend', choices=['OPTIX', 'CUDA'], default='OPTIX')
    parser.add_argument('--device', type=int, default=0, help='index among backend GPUs')
    parser.add_argument('--check-only', action='store_true')
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--result', type=Path, help='completion JSON, written only on success')
    args = parser.parse_args(sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else [])
    if not args.check_only and args.output is None:
        parser.error('--output is required for generation')
    if args.result and args.result.exists():
        parser.error('--result already exists; choose a new path')

    import bpy
    from PIL import Image  # Required for padded OBB image/label pairs.

    if not bpy.data.filepath:
        raise RuntimeError('Load ChainLinkScene.blend before --python render_headless.py')
    # blend_paths also lists optional text-editor files, generated caches and
    # asset provenance (e.g. an old copybuffer.blend). Check render assets instead.
    external = []
    for collection in ('libraries', 'images', 'movieclips', 'sounds', 'fonts', 'volumes', 'cache_files'):
        for asset in getattr(bpy.data, collection):
            path = getattr(asset, 'filepath', '')
            if not path or path == '<builtin>' or not asset.users:
                continue
            if getattr(asset, 'packed_file', None) or getattr(asset, 'packed_files', None):
                continue
            if collection == 'images' and asset.source in ('GENERATED', 'VIEWER'):
                continue
            external.append(bpy.path.abspath(path, library=asset.library))
    missing = sorted({path for path in external if not Path(path).exists()})
    if missing:
        raise RuntimeError('Missing external scene assets; pack or transfer them first:\n'
                           + '\n'.join(missing))
    preferences = bpy.context.preferences.addons['cycles'].preferences
    preferences.compute_device_type = args.backend
    preferences.get_devices()
    devices = [device for device in preferences.devices if device.type == args.backend]
    if not 0 <= args.device < len(devices):
        raise RuntimeError(f'{args.backend} GPU {args.device} unavailable: '
                           f'{[(d.name, d.type) for d in preferences.devices]}')
    selected = devices[args.device]
    for device in preferences.devices:
        device.use = device == selected
    scene = bpy.context.scene
    if args.engine != 'scene':
        scene.render.engine = {'cycles': 'CYCLES', 'eevee': 'BLENDER_EEVEE'}[args.engine]
    if scene.render.engine not in ('CYCLES', 'BLENDER_EEVEE'):
        raise RuntimeError(f'Unsupported render engine: {scene.render.engine}')
    if scene.render.engine == 'BLENDER_EEVEE' and args.device != 0:
        raise RuntimeError('--device selects Cycles GPUs only; Eevee uses the graphics driver default')
    scene.cycles.device = 'GPU'
    if args.samples is not None:
        if scene.render.engine == 'CYCLES':
            scene.cycles.samples = args.samples
        else:
            scene.eevee.taa_render_samples = args.samples
    # Saved view-layer sample overrides must not defeat an explicit CLI value.
    if args.samples is not None:
        for layer in scene.view_layers:
            layer.samples = 0
    details = dict(blender_version=bpy.app.version_string, blend_file=bpy.data.filepath,
                   engine=scene.render.engine,
                   backend=args.backend if scene.render.engine == 'CYCLES' else 'EEVEE',
                   detected_gpu=selected.name, cycles_device_id=selected.id,
                   samples=(scene.cycles.samples if scene.render.engine == 'CYCLES'
                            else scene.eevee.taa_render_samples),
                   adaptive_sampling=(scene.cycles.use_adaptive_sampling if scene.render.engine == 'CYCLES' else None),
                   adaptive_threshold=(scene.cycles.adaptive_threshold if scene.render.engine == 'CYCLES' else None),
                   denoising=scene.cycles.use_denoising if scene.render.engine == 'CYCLES' else None,
                   pillow_version=Image.__version__,
                   external_assets=len(external))
    print(json.dumps(details, indent=2), flush=True)
    if args.check_only:
        print('PASS: scene assets, Pillow and GPU discovery', flush=True)
        return

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import generate_dataset as generator
    generator.OUTPUT_FOLDER = str(args.output.resolve())
    generator.USE_NAS = False
    generator.NUMBER_OF_IMAGES = args.images
    generator.IMAGE_WIDTH = args.width
    generator.IMAGE_HEIGHT = args.height
    generator.MASTER_SEED = args.seed
    generator.DRY_RUN = args.dry_run
    generator.WRITE_YOLO_ANNOTATIONS = True
    generator.REVIEW_ALL_ANNOTATIONS = True
    started = time.monotonic()
    folder = generator.main()
    with (folder / 'metadata.csv').open(newline='', encoding='utf-8') as stream:
        rows = list(csv.DictReader(stream))
    if len(rows) != args.images:
        raise RuntimeError(f'Expected {args.images} metadata rows, found {len(rows)}')
    if not args.dry_run:
        for row in rows:
            for key in ('image_path', 'label_path'):
                if not row[key] or not (folder / row[key]).is_file():
                    raise RuntimeError(f'Incomplete pair: {row}')
            with Image.open(folder / row['image_path']) as rendered:
                rendered.verify()
    details.update(run_directory=str(folder.resolve()), images=len(rows), seed=args.seed,
                   width=args.width, height=args.height, dry_run=args.dry_run,
                   elapsed_seconds=time.monotonic()-started)
    (folder / 'render_runtime.json').write_text(json.dumps(details, indent=2)+'\n')
    if args.result:
        args.result.parent.mkdir(parents=True, exist_ok=True)
        temporary = args.result.with_suffix('.tmp')
        temporary.write_text(json.dumps(details, indent=2)+'\n')
        temporary.replace(args.result)
    print(json.dumps(details, indent=2), flush=True)


if __name__ == '__main__':
    main()
