r"""Approve all displayed boxes in a saved batch, preserving the source batch.

Example:
    python approve_yolo_obb.py C:\path\to\run_... --exclude chain_00001.png

Writes a derived training dataset to ./approved_datasets/<source run name> unless
--output is supplied. Refuses existing destinations. Rectangles crossing source
edges are retained using neutral canvas padding; every label is shifted with it.
"""
import argparse
import csv
import json
from pathlib import Path
import shutil

from yolo_obb import include_review_boxes, save_padded_image


def approve_batch(source, output, excluded=()):
    source, output = Path(source).resolve(), Path(output).resolve()
    if output.exists():
        raise FileExistsError(f'Destination already exists: {output}')
    if output == source or source in output.parents:
        raise ValueError('Use a separate output directory so the original batch stays unchanged')
    reports = sorted((source/'annotations').glob('*.json'))
    if not reports:
        raise ValueError(f'No annotation reports in {source}')
    excluded = set(excluded)
    filenames = {p.stem+'.png' for p in reports}
    if excluded-filenames:
        raise ValueError(f'Unknown excluded filenames: {sorted(excluded-filenames)}')
    # Resolve every input and validate geometry before creating the destination.
    planned = []
    for path in reports:
        filename = path.stem+'.png'
        if filename in excluded:
            continue
        report = json.loads(path.read_text(encoding='utf-8'))
        if report.get('coordinate_origin') != 'top_left' or not report.get('rendered'):
            raise ValueError(f'{path.name}: requires rendered top-origin annotations')
        image = (source/report['image_path']).resolve()
        if source not in image.parents or not image.is_file():
            raise ValueError(f'Invalid or missing source image: {image}')
        approved = include_review_boxes(report, approve_all=True)
        if not approved['label_lines']:
            raise ValueError(f'{filename}: no boxes to approve; exclude this image explicitly')
        approved.update(filename=filename, source_batch=str(source), source_image_path=report['image_path'],
                        group_id=report.get('group_id', source.name), intended_split='train',
                        image_path=f'images/train/{filename}', label_path=f'labels/train/{path.stem}.txt')
        planned.append((image, approved))
    if not planned:
        raise ValueError('No images remain after exclusions')
    images, labels, annotations = output/'images'/'train', output/'labels'/'train', output/'annotations'
    images.mkdir(parents=True)
    labels.mkdir(parents=True)
    annotations.mkdir()
    rows = []
    for image, report in planned:
        filename = report['filename']
        save_padded_image(image, images/filename, report)
        (output/report['label_path']).write_text(''.join(line+'\n' for line in report['label_lines']), encoding='utf-8')
        (annotations/f'{Path(filename).stem}.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
        rows.append(dict(filename=filename, group_id=report['group_id'], image_path=report['image_path'],
                         label_path=report['label_path'], labels=len(report['label_lines']), status='ready',
                         image_width=report['image_width'], image_height=report['image_height']))
    with (output/'metadata.csv').open('w', newline='', encoding='utf-8') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    (output/'train_ready.txt').write_text(''.join('./'+r['image_path']+'\n' for r in rows), encoding='utf-8')
    (output/'approval.json').write_text(json.dumps(dict(source_batch=str(source), excluded=sorted(excluded),
        approved_images=len(rows), approved_links=sum(r['labels'] for r in rows),
        policy='User-approved displayed boxes; neutral padding preserves rectangles'), indent=2), encoding='utf-8')
    for name in ('settings.json', 'metadata.csv'):
        if (source/name).exists():
            shutil.copy2(source/name, output/('source_'+name))
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run_folder', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--exclude', action='append', default=[], help='PNG filename to omit; repeat for multiple images')
    args = parser.parse_args()
    output = args.output or Path.cwd()/'approved_datasets'/args.run_folder.name
    print('Approved dataset:', approve_batch(args.run_folder, output, args.exclude))


if __name__ == '__main__':
    main()
