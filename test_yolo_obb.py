"""Pure Python regressions: python -m unittest test_yolo_obb -v."""
import math
from pathlib import Path
import tempfile
import unittest

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


if __name__ == '__main__':
    unittest.main()
