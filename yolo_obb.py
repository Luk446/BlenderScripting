"""YOLO OBB geometry and review reports. Blender imports are local to scene helpers.

All 2-D calculations use pixels, origin at the image top left. Only final YOLO
coordinates are normalised. No OpenCV, Ultralytics or pip installation is needed
by the generator. Run settings live in generate_dataset.py.
"""
import json
import math
from pathlib import Path


# -----------------------------------------------------------------------------
# PIXEL GEOMETRY - hulls, image clipping and axis-aligned-in-angle rectangles
# -----------------------------------------------------------------------------
def convex_hull(points):
    points = sorted(set(map(tuple, points)))
    if len(points) < 3:
        return points

    def half(sequence):
        result = []
        for p in sequence:
            while len(result) >= 2:
                a, b = result[-2:]
                if (b[0]-a[0])*(p[1]-a[1]) - (b[1]-a[1])*(p[0]-a[0]) > 0:
                    break
                result.pop()
            result.append(p)
        return result

    return half(points)[:-1] + half(reversed(points))[:-1]


def clip_to_image(polygon, width, height):
    """Clip the polygon, not individual rectangle corners (Sutherland-Hodgman)."""
    polygon = list(polygon)
    for axis, limit, lower in [(0, 0, True), (0, width, False),
                               (1, 0, True), (1, height, False)]:
        output = []
        if not polygon:
            break
        previous = polygon[-1]
        inside_previous = previous[axis] >= limit if lower else previous[axis] <= limit
        for current in polygon:
            inside = current[axis] >= limit if lower else current[axis] <= limit
            if inside != inside_previous:
                fraction = (limit-previous[axis]) / (current[axis]-previous[axis])
                output.append(tuple(previous[i]+fraction*(current[i]-previous[i]) for i in (0, 1)))
            if inside:
                output.append(current)
            previous, inside_previous = current, inside
        polygon = output
    return polygon


def rectangle_at_angle(points, angle):
    """Tight bounding rectangle with its first edge parallel to the link axis."""
    c, s = math.cos(angle), math.sin(angle)
    rotated = [(x*c+y*s, -x*s+y*c) for x, y in points]
    left, right = min(p[0] for p in rotated), max(p[0] for p in rotated)
    top, bottom = min(p[1] for p in rotated), max(p[1] for p in rotated)
    box = [(x*c-y*s, x*s+y*c) for x, y in
           [(left, top), (right, top), (right, bottom), (left, bottom)]]
    return box, right-left, bottom-top


def fit_link_box(points, center, axis, width, height):
    """Return a label candidate and reasons for human review.

    Center is the projected local-bounds midpoint, NOT the vertex average.
    If a cropped, fixed-angle rectangle cannot fit the image, keep it only in
    the review report. Never squeeze a rotated rectangle into a quadrilateral.
    """
    result = {'box': None, 'candidate_box': None, 'reasons': [], 'excluded': None}
    if not (0 <= center[0] < width and 0 <= center[1] < height):
        result['excluded'] = 'center_outside_image'
        return result
    hull = convex_hull(points)
    if len(hull) < 3 or math.hypot(*axis) < 1e-6:
        result['reasons'].append('degenerate_projection')
        return result
    angle = math.atan2(axis[1], axis[0])
    cropped = any(x < 0 or x > width or y < 0 or y > height for x, y in hull)
    clipped = clip_to_image(hull, width, height)
    if len(clipped) < 3:
        result['reasons'].append('no_projected_area_in_image')
        return result
    box, length, breadth = rectangle_at_angle(clipped if cropped else hull, angle)
    result.update(candidate_box=box, angle_deg=math.degrees(angle) % 180,
                  length_px=length, width_px=breadth, cropped=cropped)
    if cropped:
        result['reasons'].append('cropped_link')
    if length < breadth:
        result['reasons'].append('projected_axis_shorter_than_box_width')
    if min(length, breadth) < 1e-6:
        result['reasons'].append('degenerate_box')
        return result
    if any(x < -1e-7 or x > width+1e-7 or y < -1e-7 or y > height+1e-7 for x, y in box):
        result['reasons'].append('boundary_box_requires_manual_resolution')
        return result
    # Only remove floating-point spill below 1e-7 pixels, not geometric overflow.
    result['box'] = [(min(width, max(0, x)), min(height, max(0, y))) for x, y in box]
    return result


def label_line(box, width, height, class_id=0):
    values = [value for x, y in box for value in (x/width, y/height)]
    if not all(math.isfinite(v) and 0 <= v <= 1 for v in values):
        raise ValueError('Invalid normalised OBB coordinates')
    return ' '.join([str(class_id), *(f'{v:.8f}' for v in values)])


# -----------------------------------------------------------------------------
# BLENDER PROJECTION - evaluated mesh, stable centre and projected physical axis
# -----------------------------------------------------------------------------
def link_projection(scene, camera, link, dg, width, height):
    from mathutils import Vector
    from bpy_extras.object_utils import world_to_camera_view

    evaluated = link.evaluated_get(dg)
    local = [v.co.copy() for v in evaluated.data.vertices]
    if not local:
        return {'box': None, 'reasons': ['empty_mesh'], 'excluded': None}, []
    low = Vector(tuple(min(p[i] for p in local) for i in range(3)))
    high = Vector(tuple(max(p[i] for p in local) for i in range(3)))
    center = (low+high)/2
    # For the authored link meshes, the longest local dimension is the long axis.
    # Mesh tessellation does not affect either the centre or the axis selection.
    basis = evaluated.matrix_world.to_3x3()
    axis_index = max(range(3), key=lambda i: (high[i]-low[i])*basis.col[i].length)
    offset = Vector()
    offset[axis_index] = (high[axis_index]-low[axis_index])/2
    world = [evaluated.matrix_world @ p for p in local]

    def project(p):
        v = world_to_camera_view(scene, camera, p)
        return (v.x*width, (1-v.y)*height), v.z

    projected = [project(p) for p in world]
    if any(not camera.data.clip_start < depth < camera.data.clip_end for _, depth in projected):
        return {'box': None, 'reasons': ['camera_depth_clipping'], 'excluded': None}, world
    center_pixel, _ = project(evaluated.matrix_world @ center)
    a, _ = project(evaluated.matrix_world @ (center-offset))
    b, _ = project(evaluated.matrix_world @ (center+offset))
    result = fit_link_box([p for p, _ in projected], center_pixel,
                          (b[0]-a[0], b[1]-a[1]), width, height)
    result['center_px'] = center_pixel
    return result, world


# -----------------------------------------------------------------------------
# GEOMETRIC VISIBILITY - deterministic surface rays, separate from fog/contrast
# -----------------------------------------------------------------------------
def surface_visibility(scene, camera, link, dg, world_points, max_samples):
    """Estimate visible surface samples with link-only and scene ray casts.

    Self-hidden vertices are removed from the denominator. Camera rays account
    for perspective/orthographic projection. This is a sampled diagnostic, not
    an instance mask or proof that a foggy/transparent object is identifiable.
    """
    from mathutils import Vector
    from bpy_extras.object_utils import world_to_camera_view
    evaluated = link.evaluated_get(dg)
    inverse = evaluated.matrix_world.inverted()
    front = camera.matrix_world.to_quaternion() @ Vector((0, 0, -1))
    camera_position = camera.matrix_world.translation
    eligible = visible = 0
    count = min(max_samples, len(world_points))
    for i in range(count):
        point = world_points[i*len(world_points)//count]
        ndc = world_to_camera_view(scene, camera, point)
        if not (0 <= ndc.x <= 1 and 0 <= ndc.y <= 1 and
                camera.data.clip_start < ndc.z < camera.data.clip_end):
            continue
        origin = camera_position if camera.data.type == 'PERSP' else point-front*ndc.z
        direction = (point-origin).normalized()
        distance = (point-origin).length
        local_origin = inverse @ origin
        local_direction = inverse.to_3x3() @ direction
        hit, location, _, _ = evaluated.ray_cast(local_origin, local_direction)
        if not hit or (evaluated.matrix_world @ location-point).length > 0.01:
            continue
        eligible += 1
        hit, _, _, _, hit_object, _ = scene.ray_cast(
            dg, origin, direction, distance=distance+0.01)
        if hit and hit_object.original == link.original:
            visible += 1
    return {'eligible_samples': eligible, 'visible_samples': visible,
            'visible_fraction': visible/eligible if eligible else 0.0}


# -----------------------------------------------------------------------------
# REVIEW REPORT - candidate labels, exclusion reasons and whole-image flags
# -----------------------------------------------------------------------------
def annotate(scene, camera, links, dg, width, height, settings):
    reasons = ['pilot_manual_review'] if settings['review_all'] else []
    # Fog colour, lighting, particles, materials and the compositor all influence
    # recognisability. Do not infer it solely from a numeric density threshold.
    if scene.world and scene.world.use_nodes:
        if any(n.type in {'VOLUME_SCATTER', 'VOLUME_PRINCIPLED', 'VOLUME_ABSORPTION', 'GROUP'}
               for n in scene.world.node_tree.nodes):
            reasons.append('world_volume_requires_visual_review')
    if any(o.particle_systems and not o.hide_render for o in scene.objects):
        reasons.append('particles_require_visual_review')
    # The scene-ray graph is viewport evaluated. Mark render/viewport differences
    # instead of silently claiming a render-accurate visibility result.
    if any(o.hide_render != (o.hide_viewport or o.hide_get()) for o in scene.objects if o.type == 'MESH'):
        reasons.append('render_viewport_visibility_mismatch')
    if scene.render.use_compositing and (
        getattr(scene, 'compositing_node_group', None) or getattr(scene, 'node_tree', None)
    ):
        reasons.append('compositor_requires_alignment_review')
    records, lines = [], []
    for link in links:
        record, points = link_projection(scene, camera, link, dg, width, height)
        record['name'] = link.name
        record['label_index'] = None
        if not record['excluded'] and points:
            visibility = surface_visibility(scene, camera, link, dg, points, settings['samples'])
            record.update(visibility)
            if visibility['visible_samples'] == 0:
                record['box'] = None
                record['reasons'].append('no_visible_samples_check_occlusion')
            elif visibility['visible_samples'] < settings['min_samples'] or visibility['visible_fraction'] < settings['min_fraction']:
                record['reasons'].append('low_visibility_check_identity')
            if record.get('width_px', 0) < settings['min_width']:
                record['reasons'].append('small_link_check_identity')
        if record['box'] is not None and not record['excluded']:
            record['label_index'] = len(lines)
            lines.append(label_line(record['box'], width, height, settings['class_id']))
        if record['reasons']:
            reasons.append(f"{link.name}: " + ', '.join(record['reasons']))
        records.append(record)
    if not lines:
        reasons.append('no_labels_check_image')
    return {'schema_version': 1, 'class_names': {0: 'link'},
            'coordinate_origin': 'top_left', 'image_width': width, 'image_height': height,
            'status': 'needs_review' if reasons else 'ready', 'reasons': reasons,
            'visibility_method': 'sampled_surface_rays', 'links': records, 'label_lines': lines}


def write_annotation(folder, filename, report, rendered):
    """Only complete image/label pairs enter ready or review directories."""
    folder = Path(folder)
    report.update(filename=filename, group_id=folder.name, intended_split='train', rendered=rendered)
    report_dir = folder/'annotations'
    report_dir.mkdir(exist_ok=True)
    stem = Path(filename).stem
    if rendered:
        base = folder/'review' if report['status'] == 'needs_review' else folder
        images, labels = base/'images'/'train', base/'labels'/'train'
        images.mkdir(parents=True, exist_ok=True)
        labels.mkdir(parents=True, exist_ok=True)
        source = folder/'_pending'/filename
        destination = images/filename
        (labels/f'{stem}.txt').write_text(''.join(line+'\n' for line in report['label_lines']), encoding='utf-8')
        source.replace(destination)
        report['image_path'] = destination.relative_to(folder).as_posix()
        report['label_path'] = (labels/f'{stem}.txt').relative_to(folder).as_posix()
        if report['status'] == 'ready':
            with (folder/'train_ready.txt').open('a', encoding='utf-8') as stream:
                stream.write('./'+report['image_path']+'\n')
    (report_dir/f'{stem}.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    return report
