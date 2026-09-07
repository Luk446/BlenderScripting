"""Draw YOLO-OBB labels over rendered images.

Examples:
    python view_yolo_obb.py "C:\\path\\to\\run_20260907_123456"
    python view_yolo_obb.py "C:\\path\\to\\run_20260907_123456" --show
"""
import argparse
import json
from pathlib import Path

import cv2
import numpy as np


def overlay_image(image_path, label_path, report_path=None):
    image = cv2.imread(str(image_path))
    if image is None:
        raise RuntimeError(f"Could not read image: {image_path}")
    height, width = image.shape[:2]
    report = json.loads(report_path.read_text(encoding='utf-8')) if report_path and report_path.exists() else {}
    if not label_path.exists():
        raise FileNotFoundError(f'Missing labels: {label_path}')
    if label_path.exists():
        for index, line in enumerate(label_path.read_text(encoding="utf-8").splitlines()):
            values = line.split()
            if len(values) != 9:
                raise ValueError(f'{label_path}:{index+1}: expected class and 8 coordinates')
            class_id = values[0]
            coordinates = np.array([float(value) for value in values[1:]])
            if not np.all(np.isfinite(coordinates)) or np.any(coordinates < 0) or np.any(coordinates > 1):
                raise ValueError(f'{label_path}:{index+1}: coordinates must be finite and within 0..1')
            points = np.array(
                [[round(float(values[i]) * width),
                  round(float(values[i + 1]) * height)]
                 for i in range(1, 9, 2)],
                dtype=np.int32,
            )
            cv2.polylines(image, [points], True, (0, 255, 0), 2, cv2.LINE_AA)
            centre = tuple(np.mean(points, axis=0).astype(int))
            record = next((r for r in report.get('links', []) if r['label_index'] == index), {})
            cv2.putText(image, record.get('name', class_id), centre, cv2.FONT_HERSHEY_SIMPLEX,
                        0.5, (0, 255, 0), 1, cv2.LINE_AA)
    # Red candidates are NOT exported labels. They identify unresolved boundary
    # or visibility cases so a missing label cannot silently pass visual review.
    for record in report.get('links', []):
        if record.get('candidate_box') and record.get('label_index') is None:
            points = np.rint(record['candidate_box']).astype(np.int32)
            cv2.polylines(image, [points], True, (0, 0, 255), 1, cv2.LINE_AA)
            centre = tuple(np.clip(np.mean(points, axis=0), (0, 15), (width-1, height-1)).astype(int))
            cv2.putText(image, record['name']+' REVIEW', centre, cv2.FONT_HERSHEY_SIMPLEX,
                        0.4, (0, 0, 255), 1, cv2.LINE_AA)
    if report.get('status') == 'needs_review':
        cv2.putText(image, 'REVIEW: green=labels red=unresolved', (8, 18),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 190, 255), 1, cv2.LINE_AA)
    return image


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_folder", type=Path, help="A generated run_... folder")
    parser.add_argument("--show", action="store_true", help="Open each overlay in a window")
    parser.add_argument("--output", type=Path, help="Overlay output folder; defaults to run_folder/overlays")
    args = parser.parse_args()

    image_paths = sorted((args.run_folder/'images').rglob('chain_*.png'))
    image_paths += sorted((args.run_folder/'review'/'images').rglob('chain_*.png'))
    if not image_paths:
        raise SystemExit(f"No images found in images/ or review/images/ in {args.run_folder}. "
                         "Old bottom-origin labels must be regenerated; this viewer expects YOLO coordinates.")
    output_folder = args.output or args.run_folder / "overlays"
    output_folder.mkdir(parents=True, exist_ok=True)

    for image_path in image_paths:
        relative = image_path.relative_to(args.run_folder)
        label_parts = list(relative.parts)
        label_parts[label_parts.index('images')] = 'labels'
        label_path = (args.run_folder / Path(*label_parts)).with_suffix('.txt')
        overlay = overlay_image(image_path, label_path, args.run_folder/'annotations'/f'{image_path.stem}.json')
        output_path = output_folder / relative
        output_path.parent.mkdir(parents=True, exist_ok=True)
        if not cv2.imwrite(str(output_path), overlay):
            raise RuntimeError(f'Could not write overlay: {output_path}')
        if args.show:
            cv2.imshow("YOLO-OBB labels", overlay)
            if cv2.waitKey(0) & 0xFF == 27:
                break
    cv2.destroyAllWindows()
    print(f"Overlays written to: {output_folder}")


if __name__ == "__main__":
    main()
