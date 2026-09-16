import json
from pathlib import Path
import tempfile
import unittest

import cv2
import numpy as np

from approve_audited_job import approve_job, release_plan
from qa_yolo_obb import scan
from review_yolo_obb import qa_items


def fixture(root, count=20):
    run = root / 'batch_00000000' / 'run_test'
    for folder in ('annotations', 'review/images/train', 'review/labels/train'):
        (run / folder).mkdir(parents=True)
    for n in range(count):
        name = f'chain_{n:05d}'
        frame = np.random.default_rng(n).integers(40, 210, (64, 64, 3), dtype=np.uint8)
        cv2.imwrite(str(run / 'review/images/train' / (name + '.png')), frame)
        line = '0 0.25 0.25 0.75 0.25 0.75 0.5 0.25 0.5'
        (run / 'review/labels/train' / (name + '.txt')).write_text(line + '\n')
        report = dict(coordinate_origin='top_left', rendered=True, image_width=64, image_height=64,
                      filename=name+'.png', image_path=f'review/images/train/{name}.png',
                      label_path=f'review/labels/train/{name}.txt', label_lines=[line],
                      status='needs_review', reasons=['pilot_manual_review', 'world_volume_requires_visual_review'],
                      links=[dict(name='link', box=[[16,16],[48,16],[48,32],[16,32]],
                                  candidate_box=None, label_index=0, reasons=[], excluded=None)])
        (run / 'annotations' / (name+'.json')).write_text(json.dumps(report))
    (root / 'complete.json').write_text(json.dumps(dict(images=count, completed_runs=[
        dict(run_directory='/remote/job/batch_00000000/run_test', images=count)])))
    return run


def reviewed(qa):
    return dict(dataset=qa['dataset'], qa_fingerprint=qa['fingerprint'], decisions={
        i['id']: 'keep' for i in qa['items'] if i['selection'] != 'audit_eligible'})


class AuditTests(unittest.TestCase):
    def test_deterministic_sampling_and_failed_attempt_ignored(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            fixture(root)
            (root / 'batch_00000000/run_failed/annotations').mkdir(parents=True)
            qa = scan(root, 3, 7)
            self.assertEqual(qa, scan(root, 3, 7))
            self.assertEqual(len(qa['items']), 20)
            self.assertFalse(qa['errors'])
            self.assertEqual(sum(i['selection'] == 'random_sample' for i in qa['items']), 3)
            self.assertTrue(any(i['selection'] == 'audit_eligible' for i in qa['items']))
            self.assertFalse(any(i['selection'] == 'high_risk' for i in qa['items']))

    def test_bad_geometry_missing_pair_and_orphans(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            run = fixture(root, 3)
            (run / 'review/labels/train/chain_00000.txt').unlink()
            path = run / 'annotations/chain_00001.json'
            report = json.loads(path.read_text())
            report['label_lines'] = ['0 0.1 0.1 0.9 0.1 0.8 0.8 0.1 0.8']
            path.write_text(json.dumps(report))
            (run / report['label_path']).write_text(report['label_lines'][0]+'\n')
            (run / 'review/labels/train/orphan.txt').write_text('')
            qa = scan(root, 1)
            self.assertTrue(qa['items'][0]['errors'])
            self.assertTrue(qa['items'][1]['errors'])
            self.assertTrue(qa['errors'])

    def test_review_required_sample_failure_and_explicit_acceptance(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            fixture(root)
            qa = scan(root, 2)
            state = reviewed(qa)
            with self.assertRaisesRegex(ValueError, 'accept-batch-audit'):
                release_plan(qa, state, False, strict_review=True)
            plan = release_plan(qa, state, True, strict_review=True)
            self.assertIn('batch_audit', plan.values())
            sample = next(i for i in qa['items'] if i['selection'] == 'random_sample')
            state['decisions'][sample['id']] = 'reject'
            with self.assertRaisesRegex(ValueError, 'sample contains a rejection'):
                release_plan(qa, state, True, strict_review=True)
            for item in qa['items']:
                state['decisions'].setdefault(item['id'], 'keep')
            self.assertNotIn('batch_audit', release_plan(qa, state, False, strict_review=True).values())

    def test_export_provenance_pixels_and_stale_data(self):
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            root = folder / 'job'
            run = fixture(root)
            qa = scan(root, 2)
            state = reviewed(qa)
            qp, dp = folder/'qa.json', folder/'decisions.json'
            qp.write_text(json.dumps(qa))
            dp.write_text(json.dumps(state))
            items = qa_items(root, qp, state, strict_review=True)
            self.assertEqual(len(items), len(state['decisions']))
            output = approve_job(qp, dp, folder/'approved', True, strict_review=True)
            manifest = json.loads((output/'approval.json').read_text())
            self.assertGreater(manifest['counts']['batch_audit'], 0)
            for item in qa['items']:
                exported = output/item['run']/'images/train'/item['filename']
                np.testing.assert_array_equal(cv2.imread(str(root/item['image'])), cv2.imread(str(exported)))
                report = json.loads((output/item['run']/'annotations'/Path(item['report']).name).read_text())
                self.assertEqual(report['approval_mode'], manifest['decisions'][item['id']])
            (run/'review/labels/train/chain_00000.txt').write_text('')
            with self.assertRaisesRegex(ValueError, 'changed'):
                approve_job(qp, dp, folder/'stale', True)
            self.assertFalse((folder/'stale').exists())

    def test_padding_and_exact_duplicates(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            run = fixture(root, 3)
            first = run/'review/images/train/chain_00000.png'
            second = run/'review/images/train/chain_00001.png'
            second.write_bytes(first.read_bytes())
            qa = scan(root, 1)
            self.assertEqual(qa['items'][1]['selection'], 'high_risk')
            self.assertTrue(any(r.startswith('exact_duplicate_of:') for r in qa['items'][1]['reasons']))
            path = run/'annotations/chain_00002.json'
            report = json.loads(path.read_text())
            report.update(source_image_width=60, source_image_height=64,
                          padding=dict(left=4, right=0, top=0, bottom=0))
            path.write_text(json.dumps(report))
            qa = scan(root, 1)
            self.assertIn('Padding pixels', qa['items'][2]['errors'][0])

    def test_grid_click_saves_individual_decision(self):
        from unittest.mock import patch
        from review_yolo_obb import grid_review
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            fixture(root, 1)
            qa = scan(root, 1)
            qp = root/'qa.json'
            qp.write_text(json.dumps(qa))
            state = dict(dataset=str(root), decisions={})
            items = qa_items(root, qp, state, strict_review=True)
            callback = []
            keys = iter([-1, ord('k'), ord('q')])
            def wait(delay):
                key = next(keys)
                if key == -1:
                    callback[0](cv2.EVENT_LBUTTONDOWN, 20, 80, 0, None)
                return key
            with patch('review_yolo_obb.cv2.setMouseCallback', side_effect=lambda w, fn: callback.append(fn)), \
                 patch('review_yolo_obb.cv2.imshow'), patch('review_yolo_obb.cv2.namedWindow'), \
                 patch('review_yolo_obb.cv2.destroyWindow'), \
                 patch('review_yolo_obb.cv2.getWindowProperty', return_value=1), \
                 patch('review_yolo_obb.cv2.waitKeyEx', side_effect=wait):
                grid_review(items, state, root/'decisions.json', 'test')
            self.assertEqual(json.loads((root/'decisions.json').read_text())['decisions'], {items[0]['id']: 'keep'})

    def test_missing_completion_and_unresolved_candidate(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with self.assertRaisesRegex(ValueError, 'complete.json'):
                scan(root)
            run = fixture(root, 1)
            path = run/'annotations/chain_00000.json'
            report = json.loads(path.read_text())
            report['links'].append(dict(name='candidate', box=None, candidate_box=[[1,1],[9,1],[9,5],[1,5]],
                                        label_index=None, excluded=None, reasons=[]))
            path.write_text(json.dumps(report))
            qa = scan(root, 1)
            self.assertEqual(qa['items'][0]['selection'], 'high_risk')
            state = reviewed(qa)
            state['decisions'].clear()
            with self.assertRaisesRegex(ValueError, 'unfinished'):
                release_plan(qa, state, True, strict_review=True)


if __name__ == '__main__':
    unittest.main()
