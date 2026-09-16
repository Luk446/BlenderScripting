"""Default acceptance rules; ranking flags alone do not require human review."""
POLICY = {'version': 1, 'mode': 'default_accept_except_very_high_risk',
          'minimum_brightness': 10, 'minimum_contrast': 5,
          'maximum_padding_fraction': 0.5}


def critical_reasons(item):
    reasons = []
    if item.get('errors'):
        reasons.append('integrity_failure')
    metrics = item.get('metrics', {})
    if metrics.get('labels', 0) == 0:
        reasons.append('no_exported_labels')
    if 'unresolved_candidate_boxes' in item.get('reasons', []):
        reasons.append('unresolved_candidate_boxes')
    if metrics.get('brightness', 255) < POLICY['minimum_brightness']:
        reasons.append('extreme_darkness')
    if metrics.get('contrast', 255) < POLICY['minimum_contrast']:
        reasons.append('extreme_low_contrast')
    if metrics.get('padding_fraction', 0) > POLICY['maximum_padding_fraction']:
        reasons.append('excessive_padding')
    if 'compositor_requires_alignment_review' in item.get('flags', []):
        reasons.append('compositor_alignment')
    return reasons


def requires_review(item):
    return bool(critical_reasons(item))
