"""Export a QA-reviewed run/job to a new destination, preserving batch identities."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import tempfile
import time

from approve_yolo_obb import approve_batch
from qa_yolo_obb import scan
from acceptance_policy import POLICY as ACCEPTANCE_POLICY, requires_review


def release_plan(qa, state, accept_batch_audit=False, strict_review=False):
    if state.get('dataset') != qa['dataset'] or state.get('qa_fingerprint') != qa['fingerprint']:
        raise ValueError('Review decisions do not match this QA dataset fingerprint')
    if qa['errors']:
        raise ValueError('Fix job integrity errors and rescan before approval')
    decisions = state['decisions']
    known = {i['id'] for i in qa['items']}
    if set(decisions) - known or any(v not in ('keep', 'reject') for v in decisions.values()):
        raise ValueError('Invalid or unknown review decisions')
    sample_failed = any(i['selection'] in ('random_sample', 'coverage_sample') and decisions.get(i['id']) == 'reject'
                        for i in qa['items'])
    plan = {}
    for item in qa['items']:
        decision = decisions.get(item['id'])
        if decision == 'reject':
            mode = 'excluded'
        elif item['errors']:
            raise ValueError(f"Reject or repair integrity failure: {item['id']}")
        elif decision == 'keep':
            mode = 'individual_review'
        elif not strict_review:
            if requires_review(item):
                raise ValueError(f"Very-high-risk review is unfinished: {item['id']}")
            mode = 'default_accept'
        elif item['selection'] != 'audit_eligible':
            raise ValueError(f"Required review is unfinished: {item['id']}")
        elif sample_failed:
            raise ValueError('Audit sample contains a rejection. Review all remaining images with --all, or repair and rescan.')
        elif not accept_batch_audit:
            raise ValueError('Unreviewed images remain; use --accept-batch-audit to explicitly accept the recorded audit')
        else:
            mode = 'batch_audit'
        plan[item['id']] = mode
    if not any(mode != 'excluded' for mode in plan.values()):
        raise ValueError('No images remain for export')
    return plan


def publish_staged_dataset(staging, output):
    """Allow briefly deferred SMB file handles to close before directory rename."""
    for attempt in range(5):
        if output.exists():
            raise FileExistsError(output)
        try:
            staging.rename(output)
            return
        except PermissionError:
            if attempt == 4:
                raise
            time.sleep(2 ** attempt)


def approve_job(qa_path, decisions_path, output, accept_batch_audit=False, strict_review=False):
    qa = json.loads(Path(qa_path).read_text())
    state = json.loads(Path(decisions_path).read_text())
    root, output = Path(qa['dataset']).resolve(), Path(output).resolve()
    if output.exists() or output == root or root in output.parents:
        raise ValueError('Use a new output destination outside the source dataset')
    # Recompute content hashes, checks and sampling; never trust an edited/stale report.
    fresh = scan(root, qa['sample_size'], qa['seed'])
    if fresh != qa:
        raise ValueError('Dataset or QA policy changed; rescan and review with a new decisions file')
    plan = release_plan(qa, state, accept_batch_audit, strict_review)
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix='.qa-export-', dir=output.parent))
    ready_to_publish = False
    try:
        training = []
        for run in sorted({i['run'] for i in qa['items']}):
            items = [i for i in qa['items'] if i['run'] == run]
            modes = {i['filename']: plan[i['id']] for i in items if plan[i['id']] != 'excluded'}
            if not modes:
                continue
            destination = staging / (root.name if run == '.' else run)
            approve_batch(root / run, destination,
                          [i['filename'] for i in items if plan[i['id']] == 'excluded'], modes)
            training.extend('./' + (destination / 'images' / 'train' / name).relative_to(staging).as_posix()
                            for name in modes)
        (staging / 'train_ready.txt').write_text(''.join(p + '\n' for p in training))
        (staging / 'qa.json').write_text(json.dumps(qa, indent=2) + '\n')
        (staging / 'review.json').write_text(json.dumps(state, indent=2) + '\n')
        manifest = {'schema_version': 1, 'source_dataset': str(root), 'intended_split': 'train',
                    'created_utc': datetime.now(timezone.utc).isoformat(), 'fingerprint': qa['fingerprint'],
                    'acceptance_policy': ACCEPTANCE_POLICY, 'strict_review': strict_review,
                    'accepted_batch_audit': accept_batch_audit, 'decisions': plan,
                    'counts': {mode: list(plan.values()).count(mode) for mode in
                               ('excluded', 'individual_review', 'batch_audit', 'default_accept')}}
        (staging / 'approval.json').write_text(json.dumps(manifest, indent=2) + '\n')
        ready_to_publish = True
        publish_staged_dataset(staging, output)
    except BaseException:
        if ready_to_publish:
            print(f'Completed export retained for recovery: {staging}', flush=True)
        else:
            shutil.rmtree(staging)
        raise
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--qa', type=Path, required=True)
    parser.add_argument('--decisions', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--accept-batch-audit', action='store_true',
                        help='Explicitly accept unsampled low-risk images after the required review passes')
    parser.add_argument('--strict-review', action='store_true', help='Restore mandatory high-risk and sample review')
    args = parser.parse_args()
    print('Approved dataset:', approve_job(args.qa, args.decisions, args.output, args.accept_batch_audit, args.strict_review))


if __name__ == '__main__':
    main()
