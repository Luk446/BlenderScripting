"""Pure Python regressions: python -m unittest test_yolo_obb -v."""
import math
from pathlib import Path
import tempfile
import unittest
import copy

import yolo_obb as obb


def rectangle(cx, cy, length, width, angle):
    c, s = math.cos(angle), math.sin(angle)
    return [(cx+x*c-y*s, cy+x*s+y*c) for x, y in
            [(-length/2, -width/2), (length/2, -width/2),
             (length/2, width/2), (-length/2, width/2)]]


class LabelGeometryTests(unittest.TestCase):
    def assert_rectangle(self, box):
        edges = [(box[(i+1)%4][0]-box[i][0], box[(i+1)%4][1]-box[i][1]) for i in range(4)]
        for i, edge in enumerate(edges):
            other = edges[(i+1)%4]
            cosine = sum(a*b for a, b in zip(edge, other))/(math.hypot(*edge)*math.hypot(*other))
            self.assertAlmostEqual(cosine, 0, places=6)

    def test_non_square_image_preserves_rectangle_and_angle(self):
        angle = math.radians(30)
        points = rectangle(640, 320, 300, 80, angle)
        result = obb.fit_link_box(points, (640, 320), (math.cos(angle), math.sin(angle)), 1280, 640)
        values = list(map(float, obb.label_line(result['box'], 1280, 640).split()[1:]))
        pixels = [(values[i]*1280, values[i+1]*640) for i in range(0, 8, 2)]
        self.assert_rectangle(pixels)
        self.assertAlmostEqual(result['angle_deg'], 30)
        self.assertAlmostEqual(result['length_px'], 300)
        self.assertAlmostEqual(result['width_px'], 80)

    def test_axis_aligned_crop_is_valid_rectangle(self):
        result = obb.fit_link_box(rectangle(10, 50, 40, 20, 0), (10, 50), (1, 0), 100, 100)
        self.assertIsNotNone(result['box'])
        self.assertIn('cropped_link', result['reasons'])
        self.assert_rectangle(result['box'])
        self.assertEqual(min(p[0] for p in result['box']), 0)

    def test_oblique_crop_is_quarantined_without_corner_clamping(self):
        points = [(-15, 35), (25, 75), (45, 55), (5, 15)]
        result = obb.fit_link_box(points, (15, 45), (1, 1), 100, 100)
        self.assertIsNone(result['box'])
        self.assertIn('boundary_box_requires_manual_resolution', result['reasons'])
        self.assert_rectangle(result['candidate_box'])

    def test_vertex_density_does_not_change_center_policy(self):
        points = [(-20, 30), (10, 30), (10, 70), (-20, 70)]
        for vertices in (points, points+[(10, 30)]*20):
            result = obb.fit_link_box(vertices, (-5, 50), (0, 1), 100, 100)
            self.assertEqual(result['excluded'], 'center_outside_image')
            self.assertIsNone(result['box'])

    def test_top_left_y_is_written_without_flip(self):
        points = [(10, 10), (30, 10), (30, 30), (10, 30)]
        values = list(map(float, obb.label_line(points, 100, 100).split()[1:]))
        self.assertEqual(values[1::2], [.1, .1, .3, .3])

    def test_degenerate_projection_has_no_label(self):
        result = obb.fit_link_box([(5, 5), (10, 10)], (7, 7), (1, 1), 100, 100)
        self.assertIsNone(result['box'])

    def test_ready_and_review_pairs_use_yolo_paths(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            (folder/'_pending').mkdir()
            (folder/'train_ready.txt').write_text('')
            for status in ('ready', 'needs_review'):
                filename = status+'.png'
                (folder/'_pending'/filename).write_bytes(b'file-pair routing test')
                report = {'status': status, 'label_lines': ['0 .1 .1 .3 .1 .3 .3 .1 .3']}
                obb.write_annotation(folder, filename, report, True)
                image_path = folder/report['image_path']
                self.assertTrue(image_path.exists())
                expected_label = Path(str(image_path).replace('images', 'labels')).with_suffix('.txt')
                self.assertTrue(expected_label.exists())
            manifest = (folder/'train_ready.txt').read_text()
            self.assertIn('ready.png', manifest)
            self.assertNotIn('needs_review.png', manifest)

    def test_dry_run_has_reports_but_no_label_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            obb.write_annotation(folder, 'dry.png', {'status': 'needs_review', 'label_lines': []}, False)
            self.assertTrue((folder/'annotations'/'dry.json').exists())
            self.assertFalse(list(folder.rglob('*.txt')))

    def test_approved_boundary_rectangles_get_padding_not_clamping(self):
        points = [(-15, 35), (25, 75), (45, 55), (5, 15)]
        record = obb.fit_link_box(points, (15, 45), (1, 1), 100, 100)
        record.update(name='link_test', visible_samples=20, label_index=None)
        report = dict(image_width=100, image_height=100, links=[record], reasons=['pilot_manual_review'],
                      status='needs_review', label_lines=[])
        original = copy.deepcopy(report)
        approved = obb.include_review_boxes(report, approve_all=True)
        self.assertEqual(report, original)
        self.assertEqual(approved['status'], 'ready')
        self.assertGreater(approved['padding']['left'], 0)
        self.assertEqual(approved['links'][0]['label_index'], 0)
        self.assert_rectangle(approved['links'][0]['box'])
        for x, y in approved['links'][0]['box']:
            self.assertTrue(0 <= x <= approved['image_width'])
            self.assertTrue(0 <= y <= approved['image_height'])

    def test_automatic_boundary_acceptance_does_not_approve_hidden_candidates(self):
        record = dict(name='hidden', box=None, candidate_box=rectangle(20, 20, 10, 5, 0),
                      excluded=None, visible_samples=0, label_index=None,
                      reasons=['no_visible_samples_check_occlusion'])
        report = dict(image_width=100, image_height=100, links=[record], reasons=['hidden'],
                      status='needs_review', label_lines=[])
        result = obb.include_review_boxes(report)
        self.assertEqual(result['label_lines'], [])
        self.assertEqual(result['status'], 'needs_review')
        # Explicit manual approval can accept a displayed candidate missed by the sampler.
        approved = obb.include_review_boxes(report, approve_all=True)
        self.assertEqual(len(approved['label_lines']), 1)

    def test_padding_keeps_original_pixels_exactly(self):
        from PIL import Image
        with tempfile.TemporaryDirectory() as temporary:
            source, output = Path(temporary)/'source.png', Path(temporary)/'padded.png'
            image = Image.new('RGBA', (20, 10), (37, 86, 149, 255))
            image.putpixel((4, 5), (201, 111, 67, 128))
            image.save(source)
            before = source.read_bytes()
            report = dict(source_image_width=20, source_image_height=10, image_width=27, image_height=19,
                          padding=dict(left=3, right=4, top=5, bottom=4))
            obb.save_padded_image(source, output, report)
            with Image.open(output) as padded:
                self.assertEqual(padded.size, (27, 19))
                self.assertEqual(padded.crop((3, 5, 23, 15)).tobytes(), image.tobytes())
            self.assertEqual(source.read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
