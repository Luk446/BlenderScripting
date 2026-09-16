import json
from pathlib import Path
import tempfile
import unittest

from review_yolo_obb import find_review_items, first_unreviewed, load_state, save_state


class ReviewToolTests(unittest.TestCase):
    def test_discovers_batches_in_order_and_maps_labels(self):
        with tempfile.TemporaryDirectory() as temporary:
            job = Path(temporary) / "chains_001"
            for batch in ("batch_00000100", "batch_00000000"):
                run = job / batch / "run_test"
                image = run / "review" / "images" / "train" / "chain_00000.png"
                image.parent.mkdir(parents=True)
                image.write_bytes(b"image")
            items = find_review_items(job)
            self.assertEqual([item["batch"] for item in items], ["batch_00000000", "batch_00000100"])
            self.assertEqual(items[0]["label"].relative_to(job).as_posix(),
                             "batch_00000000/run_test/review/labels/train/chain_00000.txt")

    def test_state_round_trip_and_resume(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            job = folder / "job"
            job.mkdir()
            path = folder / "review.json"
            state = load_state(path, job)
            state["decisions"]["first"] = "keep"
            save_state(path, state)
            loaded = load_state(path, job)
            self.assertEqual(loaded["decisions"], {"first": "keep"})
            self.assertEqual(first_unreviewed([{"id": "first"}, {"id": "second"}], loaded["decisions"]), 1)


if __name__ == "__main__":
    unittest.main()
