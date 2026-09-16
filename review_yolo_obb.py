"""Review generated YOLO-OBB images sequentially in an OpenCV window.

The source dataset is never modified. Decisions are written after every
keypress so a long review can be stopped and resumed safely.

Example:
    python3 review_yolo_obb.py /path/to/chains_001
"""

import argparse
import json
from pathlib import Path

import cv2
import numpy as np
from acceptance_policy import requires_review

from view_yolo_obb import overlay_image


KEY_KEEP = {ord("k"), ord("K"), 13, 32}
KEY_REJECT = {ord("r"), ord("R")}
KEY_BACK = {ord("b"), ord("B"), 81, 2424832}
KEY_SKIP = {ord("s"), ord("S"), 83, 2555904}
KEY_QUIT = {ord("q"), ord("Q"), 27}


def find_review_items(job_folder):
    """Return image, label and report paths in batch/run/image order."""
    job_folder = Path(job_folder).resolve()
    items = []
    for run_folder in sorted(job_folder.glob("batch_*/run_*")):
        image_paths = sorted((run_folder / "images").rglob("chain_*.png"))
        image_paths += sorted((run_folder / "review" / "images").rglob("chain_*.png"))
        for image_path in image_paths:
            relative_to_run = image_path.relative_to(run_folder)
            label_parts = list(relative_to_run.parts)
            label_parts[label_parts.index("images")] = "labels"
            items.append(
                {
                    "id": image_path.relative_to(job_folder).as_posix(),
                    "image": image_path,
                    "label": (run_folder / Path(*label_parts)).with_suffix(".txt"),
                    "report": run_folder / "annotations" / f"{image_path.stem}.json",
                    "batch": run_folder.parent.name,
                    "filename": image_path.name,
                }
            )
    return items


def load_state(path, job_folder):
    if not path.exists():
        return {"dataset": str(job_folder.resolve()), "decisions": {}}
    state = json.loads(path.read_text(encoding="utf-8"))
    if Path(state["dataset"]).resolve() != job_folder.resolve():
        raise ValueError(f"Decision file belongs to another dataset: {state['dataset']}")
    return state


def save_state(path, state):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def first_unreviewed(items, decisions):
    return next((index for index, item in enumerate(items) if item["id"] not in decisions), len(items))


def draw_header(image, item, index, total, decision):
    display = image.copy()
    colour = (0, 200, 0) if decision == "keep" else (0, 0, 255) if decision == "reject" else (0, 190, 255)
    lines = [
        f"{index + 1}/{total}  {item['batch']}/{item['filename']}  decision: {decision or ('default accept' if item.get('default_accept') else 'REVIEW REQUIRED')}",
        "K/Enter/Space keep | R reject | B back | S skip | Q/Esc save and quit",
    ]
    for row, line in enumerate(lines):
        y = 24 + row * 24
        cv2.putText(display, line, (9, y), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 0), 3, cv2.LINE_AA)
        cv2.putText(display, line, (9, y), cv2.FONT_HERSHEY_SIMPLEX, 0.55, colour, 1, cv2.LINE_AA)
    return display


def print_summary(items, decisions, decisions_path):
    kept = sum(value == "keep" for value in decisions.values())
    rejected = sum(value == "reject" for value in decisions.values())
    print(f"Saved decisions: {decisions_path}")
    print(f"Saved decisions across dataset: {kept + rejected}; kept: {kept}; rejected: {rejected}. Current queue: {len(items)}")
    if rejected:
        print("Rejected images by batch:")
        for batch in sorted({item["batch"] for item in items}):
            names = [item["filename"] for item in items if item["batch"] == batch and decisions.get(item["id"]) == "reject"]
            if names:
                print(f"  {batch}: {' '.join(names)}")


def qa_items(job_folder, qa_path, state, review_all=False, strict_review=False):
    from qa_yolo_obb import scan
    qa = json.loads(qa_path.read_text())
    fresh = scan(job_folder, qa['sample_size'], qa['seed'])
    if fresh != qa:
        raise ValueError('QA report is stale or changed; rerun qa_yolo_obb.py')
    if state.get('qa_fingerprint') not in (None, qa['fingerprint']):
        raise ValueError('Decisions belong to different dataset contents; use a new decisions file')
    if state['decisions'] and 'qa_fingerprint' not in state:
        raise ValueError('Use a new decisions file for audited review; legacy decisions have no file hashes')
    state['qa_fingerprint'] = qa['fingerprint']
    state['strict_review'] = strict_review
    state['qa_selections'] = {i['id']: i['selection'] for i in qa['items']}
    items = []
    for entry in sorted(qa['items'], key=lambda i: (-bool(i['errors']), -requires_review(i), -i['score'], i['id'])):
        required = entry['selection'] != 'audit_eligible' if strict_review else requires_review(entry)
        if not required and not review_all:
            continue
        items.append(dict(entry, **{k: job_folder / entry[k] for k in ('image', 'label', 'report') if k in entry},
                          batch=entry['run'], default_accept=not required))
    return items


def safe_overlay(item):
    try:
        return overlay_image(item['image'], item['label'], item['report'])
    except (OSError, RuntimeError, ValueError, KeyError, TypeError) as error:
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        cv2.putText(frame, 'INTEGRITY FAILURE - reject or repair', (10, 70),
                    cv2.FONT_HERSHEY_SIMPLEX, .6, (0, 0, 255), 1)
        cv2.putText(frame, str(error)[:75], (10, 110), cv2.FONT_HERSHEY_SIMPLEX, .4, (255, 255, 255), 1)
        return frame


def grid_review(items, state, decisions_path, window):
    """Click a thumbnail for detailed review; grid navigation never approves images."""
    decisions = state['decisions']
    page = min(first_unreviewed(items, decisions) // 16, max(0, (len(items)-1)//16))
    selected = [None]
    def click(event, x, y, flags, param):
        if event == cv2.EVENT_LBUTTONDOWN and y >= 45:
            index = page * 16 + (y - 45) // 200 * 4 + x // 280
            if 0 <= index < len(items):
                selected[0] = index
    cv2.setMouseCallback(window, click)
    cached_page, cached_tiles = None, []
    while items:
        if page != cached_page:
            cached_tiles = []
            for item in items[page*16:page*16+16]:
                overlay = safe_overlay(item)
                scale = min(280 / overlay.shape[1], 150 / overlay.shape[0])
                thumb = cv2.resize(overlay, (max(1, round(overlay.shape[1]*scale)), max(1, round(overlay.shape[0]*scale))))
                tile = np.zeros((200, 280, 3), np.uint8)
                tile[:thumb.shape[0], :thumb.shape[1]] = thumb
                cached_tiles.append(tile)
            cached_page = page
        canvas = np.zeros((845, 1120, 3), np.uint8)
        cv2.putText(canvas, f'Page {page+1}/{(len(items)+15)//16} | click: inspect | N/P: pages | Q: save/quit',
                    (10, 28), cv2.FONT_HERSHEY_SIMPLEX, .6, (255, 255, 255), 1)
        for offset, base in enumerate(cached_tiles):
            item = items[page*16+offset]
            tile = base.copy()
            decision = decisions.get(item['id'], 'default accept' if item.get('default_accept') else 'REVIEW REQUIRED')
            colour = (0, 200, 0) if decision == 'keep' else (0, 0, 255) if decision == 'reject' else (0, 190, 255)
            cv2.putText(tile, f"{page*16+offset+1} {item['filename']} {decision}", (4, 168), cv2.FONT_HERSHEY_SIMPLEX, .38, colour, 1)
            cv2.putText(tile, item.get('acceptance', item.get('selection', ''))[:38], (4, 188), cv2.FONT_HERSHEY_SIMPLEX, .4, colour, 1)
            y, x = 45 + offset//4*200, offset%4*280
            canvas[y:y+200, x:x+280] = tile
        cv2.imshow(window, canvas)
        key = cv2.waitKeyEx(50)
        if key in KEY_QUIT or cv2.getWindowProperty(window, cv2.WND_PROP_VISIBLE) < 1:
            break
        if key in (ord('n'), ord('N')):
            page = min(page+1, (len(items)-1)//16)
        elif key in (ord('p'), ord('P')):
            page = max(0, page-1)
        if selected[0] is not None:
            index, selected[0] = selected[0], None
            item = items[index]
            detail = draw_header(safe_overlay(item), item, index, len(items), decisions.get(item['id']))
            print(item['id'], '\n  ', '; '.join(item.get('errors', []) + item.get('reasons', [])))
            detail_window = 'Full resolution annotation review (S/Esc returns to grid)'
            cv2.namedWindow(detail_window, cv2.WINDOW_NORMAL)
            cv2.imshow(detail_window, detail)
            key = cv2.waitKeyEx(0)
            if key in KEY_REJECT or (key in KEY_KEEP and not item.get('errors')):
                decisions[item['id']] = 'reject' if key in KEY_REJECT else 'keep'
                save_state(decisions_path, state)
            cv2.destroyWindow(detail_window)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("job_folder", type=Path, help="Job folder containing batch_*/run_* directories")
    parser.add_argument("--decisions", type=Path, help="JSON decision file (default: ./JOB_review.json)")
    parser.add_argument("--qa", type=Path, help="QA report; review high-risk cases and selected audit sample")
    parser.add_argument("--all", action="store_true", help="With --qa, inspect all images (e.g. after an audit sample fails)")
    parser.add_argument("--grid", action="store_true", help="Clickable 4 by 4 overlay grid")
    parser.add_argument("--strict-review", action="store_true", help="Show the legacy high-risk and sample queue")
    args = parser.parse_args()

    job_folder = args.job_folder.resolve()
    decisions_path = (args.decisions or Path.cwd() / f"{job_folder.name}_review.json").resolve()
    state = load_state(decisions_path, job_folder)
    items = qa_items(job_folder, args.qa, state, args.all, args.strict_review) if args.qa else find_review_items(job_folder)
    if not items and args.qa:
        save_state(decisions_path, state)
        print("No mandatory reviews remain. Default acceptance applies at export; use --all to inspect optional images.")
        return
    if not items:
        raise SystemExit(f"No review images found below {job_folder}/batch_*/run_*")

    decisions = state["decisions"]
    index = first_unreviewed(items, decisions)
    window = f"YOLO-OBB review: {job_folder.name}"
    cv2.namedWindow(window, cv2.WINDOW_NORMAL)

    try:
        if args.grid:
            grid_review(items, state, decisions_path, window)
            return
        while 0 <= index < len(items):
            item = items[index]
            overlay = safe_overlay(item)
            print(item["id"], "; ".join(item.get("errors", []) + item.get("reasons", [])))
            cv2.imshow(window, draw_header(overlay, item, index, len(items), decisions.get(item["id"])))
            key = cv2.waitKeyEx(0)
            if key in KEY_KEEP and not item.get("errors"):
                decisions[item["id"]] = "keep"
                save_state(decisions_path, state)
                index += 1
            elif key in KEY_REJECT:
                decisions[item["id"]] = "reject"
                save_state(decisions_path, state)
                index += 1
            elif key in KEY_BACK:
                index = max(0, index - 1)
            elif key in KEY_SKIP:
                index = min(len(items) - 1, index + 1)
            elif key in KEY_QUIT:
                break
        if index >= len(items):
            print("Review complete.")
    finally:
        save_state(decisions_path, state)
        cv2.destroyAllWindows()
        print_summary(items, decisions, decisions_path)


if __name__ == "__main__":
    main()
