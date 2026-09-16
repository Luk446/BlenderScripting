"""Audit a rendered run/job without changing source data (normal Python, no Blender)."""
import argparse
import hashlib
import json
from pathlib import Path
import random

import cv2
import numpy as np
from acceptance_policy import POLICY as ACCEPTANCE_POLICY, critical_reasons

POLICY = {'version': 1, 'dark_mean': 25, 'low_contrast_std': 12,
          'large_padding_fraction': .25, 'high_risk_score': 3}
BROAD_FLAGS = {'pilot_manual_review', 'world_volume_requires_visual_review',
               'particles_require_visual_review'}


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def discover_runs(root):
    root = Path(root).resolve()
    if (root / 'annotations').is_dir():
        return [root], [], None
    marker = root / 'complete.json'
    if not marker.exists():
        raise ValueError('Job has no complete.json; finish/resume rendering before auditing')
    manifest = json.loads(marker.read_text())
    runs, errors = [], []
    for entry in manifest['completed_runs']:
        # Render paths refer to iris; resolve only batch/run names beneath this copy.
        parts = entry['run_directory'].replace('\\', '/').split('/')
        run = root / parts[-2] / parts[-1]
        if not parts[-2].startswith('batch_') or not parts[-1].startswith('run_'):
            raise ValueError('Invalid completed run path')
        if run in runs:
            errors.append(f'Duplicate completed run: {run.name}')
            continue
        runs.append(run)
        actual = len(list((run / 'annotations').glob('*.json')))
        if actual != entry['images']:
            errors.append(f'{run.relative_to(root)}: expected {entry["images"]} reports, found {actual}')
    if sum(e['images'] for e in manifest['completed_runs']) != manifest['images']:
        errors.append('Job image count does not match completed runs')
    return runs, errors, digest(marker)


def contained(root, relative):
    path = (root / relative).resolve()
    if root not in path.parents:
        raise ValueError('Path escapes run directory')
    return path


def inspect_item(root, run, report_path):
    item = {'id': report_path.relative_to(root).as_posix(),
            'run': run.relative_to(root).as_posix(), 'filename': report_path.stem + '.png',
            'report': report_path.relative_to(root).as_posix(), 'errors': [],
            'reasons': [], 'score': 0, 'hashes': {}}
    try:
        item['hashes']['report'] = digest(report_path)
        report = json.loads(report_path.read_text())
        if report.get('coordinate_origin') != 'top_left' or not report.get('rendered'):
            raise ValueError('Requires rendered top-left annotations')
        for key in ('image', 'label'):
            path = contained(run, report[key + '_path'])
            item[key] = path.relative_to(root).as_posix()
            item['hashes'][key] = digest(path)
        frame = cv2.imread(str(root / item['image']))
        if frame is None:
            raise ValueError('Unreadable image')
        height, width = frame.shape[:2]
        if (width, height) != (report['image_width'], report['image_height']):
            raise ValueError('Image/report dimensions differ')
        lines = (root / item['label']).read_text().splitlines()
        if lines != report['label_lines']:
            raise ValueError('TXT labels differ from annotation report')
        for index, line in enumerate(lines):
            values = line.split()
            if len(values) != 9 or values[0] != '0':
                raise ValueError('Expected class 0 and eight OBB coordinates')
            points = np.array([float(v) for v in values[1:]]).reshape(4, 2)
            if not np.isfinite(points).all() or (points < 0).any() or (points > 1).any():
                raise ValueError('Nonfinite or out-of-range OBB coordinates')
            points *= [width, height]
            edges = np.roll(points, -1, axis=0) - points
            lengths = np.linalg.norm(edges, axis=1)
            if min(lengths) < 1e-5 or not np.allclose(edges[:2], -edges[2:], atol=.002):
                raise ValueError('Degenerate or nonrectangular OBB')
            if abs(np.dot(edges[0], edges[1])) / (lengths[0] * lengths[1]) > .001:
                raise ValueError('Nonrectangular OBB')
            records = [r for r in report['links'] if r.get('label_index') == index]
            if len(records) != 1 or not np.allclose(points, records[0]['box'], atol=.002):
                raise ValueError('OBB/report pixel alignment differs')
        padding = report.get('padding', dict(left=0, right=0, top=0, bottom=0))
        left, right, top, bottom = [padding[k] for k in ('left', 'right', 'top', 'bottom')]
        if any(not isinstance(v, int) or v < 0 for v in (left, right, top, bottom)):
            raise ValueError('Invalid padding')
        sw, sh = report.get('source_image_width', width), report.get('source_image_height', height)
        if sw + left + right != width or sh + top + bottom != height or min(sw, sh) <= 0:
            raise ValueError('Padding dimensions do not match image')
        colour = np.asarray(report.get('padding_colour', [114, 114, 114]))[::-1]
        borders = [frame[:top], frame[top+sh:], frame[:, :left], frame[:, left+sw:]]
        if any(border.size and not np.all(border == colour) for border in borders):
            raise ValueError('Padding pixels do not match the recorded neutral border')
        gray = cv2.cvtColor(frame[top:top+sh, left:left+sw], cv2.COLOR_BGR2GRAY)
        item['metrics'] = {'brightness': float(gray.mean()), 'contrast': float(gray.std()),
                           'padding_fraction': 1 - sw * sh / (width * height), 'labels': len(lines)}
        item['flags'] = report.get('reasons', [])
        specific = [r for r in item['flags'] if r not in BROAD_FLAGS]
        item['reasons'].extend(specific)
        # Cropping alone is intentional. Other geometry/visibility flags need inspection.
        tokens = {t.strip() for r in specific for t in r.split(': ', 1)[-1].split(',')}
        item['score'] += 3 if tokens - {'cropped_link'} else (1 if tokens else 0)
        links = [r for r in report['links'] if r.get('label_index') is not None]
        item['metrics']['min_link_width'] = min((r.get('width_px', 0) for r in links), default=0)
        item['metrics']['orientation'] = float(np.median([r.get('angle_deg', 0) for r in links])) if links else 0
        item['metrics']['cropped_links'] = sum('cropped_link' in r.get('reasons', []) for r in links)
        if not lines:
            item['reasons'].append('no_exported_labels')
            item['score'] += 3
        if any(r.get('candidate_box') and r.get('label_index') is None and not r.get('excluded') for r in report['links']):
            item['reasons'].append('unresolved_candidate_boxes')
            item['score'] += 3
        for metric, threshold, below in [('brightness', POLICY['dark_mean'], True),
                                         ('contrast', POLICY['low_contrast_std'], True),
                                         ('padding_fraction', POLICY['large_padding_fraction'], False)]:
            if (below and item['metrics'][metric] < threshold) or (not below and item['metrics'][metric] > threshold):
                item['reasons'].append(metric)
                item['score'] += 3
    except (OSError, ValueError, KeyError, TypeError, IndexError) as error:
        item['errors'].append(str(error))
    return item


def scan(root, sample_size=100, seed=42):
    root = Path(root).resolve()
    if sample_size < 1:
        raise ValueError('Sample size must be positive')
    runs, errors, manifest_hash = discover_runs(root)
    items = []
    for run in runs:
        current = [inspect_item(root, run, p) for p in sorted((run / 'annotations').glob('*.json'))]
        items.extend(current)
        for kind, suffix in [('images', '*.png'), ('labels', '*.txt')]:
            expected = {i.get('image' if kind == 'images' else 'label') for i in current}
            actual = list((run / kind).rglob(suffix)) + list((run / 'review' / kind).rglob(suffix))
            errors.extend(f'Orphan {kind}: {p.relative_to(root)}' for p in actual if p.relative_to(root).as_posix() not in expected)
    if not items:
        errors.append('No annotation reports found')
    seen = {}
    for item in items:
        if item['errors']:
            item['selection'] = 'integrity_failure'
            continue
        image_hash = item['hashes']['image']
        if image_hash in seen:
            item['reasons'].append('exact_duplicate_of:' + seen[image_hash])
            item['score'] += 3
        seen.setdefault(image_hash, item['id'])
        item['selection'] = 'high_risk' if item['score'] >= POLICY['high_risk_score'] else 'audit_eligible'
    rng = random.Random(seed)
    eligible = [i for i in items if i['selection'] == 'audit_eligible']
    # A random component plus batch coverage and extremes; recorded explicitly.
    random_ids = {i['id'] for i in rng.sample(eligible, min(sample_size, len(eligible)))}
    coverage_ids = set()
    for run in sorted({i['run'] for i in eligible}):
        group = [i for i in eligible if i['run'] == run]
        coverage_ids.add(rng.choice(group)['id'])
    for metric in ('brightness', 'contrast', 'padding_fraction', 'labels', 'min_link_width', 'orientation', 'cropped_links'):
        ordered = sorted(eligible, key=lambda i: i['metrics'][metric])
        if ordered:
            coverage_ids.update([ordered[0]['id'], ordered[-1]['id']])
    for flag in sorted({f for i in eligible for f in i['flags'] if f in BROAD_FLAGS}):
        coverage_ids.add(rng.choice([i for i in eligible if flag in i['flags']])['id'])
    for item in eligible:
        if item['id'] in random_ids:
            item['selection'] = 'random_sample'
        elif item['id'] in coverage_ids:
            item['selection'] = 'coverage_sample'
    for item in items:
        item['critical_reasons'] = critical_reasons(item)
        item['acceptance'] = 'very_high_risk' if item['critical_reasons'] else 'default_accept'
    inventory = [{'id': i['id'], 'hashes': i['hashes']} for i in items]
    fingerprint = hashlib.sha256(json.dumps([manifest_hash, inventory, errors], sort_keys=True).encode()).hexdigest()
    return {'schema_version': 1, 'dataset': str(root), 'fingerprint': fingerprint, 'policy': POLICY,
            'acceptance_policy': ACCEPTANCE_POLICY, 'sample_size': sample_size, 'seed': seed, 'errors': errors, 'items': items,
            'sampling': 'Seeded random sample of low-risk pool, plus per-run and metric-extreme coverage'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('dataset', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--sample-size', type=int, default=100)
    parser.add_argument('--seed', type=int, default=42)
    args = parser.parse_args()
    result = scan(args.dataset, args.sample_size, args.seed)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + '\n')
    counts = {key: sum(i['selection'] == key for i in result['items']) for key in
              ('integrity_failure', 'high_risk', 'random_sample', 'coverage_sample', 'audit_eligible')}
    print(json.dumps({'images': len(result['items']), 'counts': counts, 'job_errors': result['errors']}, indent=2))
    print('Acceptance:', {key: sum(i['acceptance'] == key for i in result['items'])
                          for key in ('very_high_risk', 'default_accept')})
    print('QA report:', args.output)
    if result['errors'] or counts['integrity_failure']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
