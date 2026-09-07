"""Run using Blender --background --factory-startup --python this_file."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent))
import bpy
from mathutils import Vector
import yolo_obb as obb

# -----------------------------------------------------------------------------
# CONTROLLED SCENE - an off-centre link, then a complete foreground occluder
# -----------------------------------------------------------------------------
bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete(use_global=False)
scene = bpy.context.scene
scene.render.resolution_x = 1280
scene.render.resolution_y = 640
scene.render.resolution_percentage = 100
bpy.ops.object.camera_add(location=(0, 0, 10))
camera = bpy.context.object
scene.camera = camera
camera.data.type = 'ORTHO'
camera.data.ortho_scale = 10
bpy.ops.mesh.primitive_uv_sphere_add(segments=32, ring_count=16, location=(0, 1, 0))
link = bpy.context.object
link.name = 'link_test'
link.scale = (1.4, 0.25, 0.25)
bpy.context.view_layer.update()
dg = bpy.context.evaluated_depsgraph_get()
config = dict(review_all=False, samples=256, min_samples=1, min_fraction=.1, min_width=1, class_id=0)
report = obb.annotate(scene, camera, [link], dg, 1280, 640, config)
record = report['links'][0]
assert len(report['label_lines']) == 1, record
assert record['visible_samples'] > 0, record
assert record['center_px'][1] < 320, record
assert all(y < 320 for _, y in record['box']), 'Y axis was flipped'
assert abs(record['angle_deg']) < 1e-5

# Adding repeated vertices must not change the projected geometric centre.
before = record['center_px']
mesh = link.data
old_vertices = [v.co.copy() for v in mesh.vertices]
old_faces = [list(p.vertices) for p in mesh.polygons]
new_mesh = bpy.data.meshes.new('different_tessellation')
new_mesh.from_pydata(old_vertices+[old_vertices[10]]*100, [], old_faces)
link.data = new_mesh
bpy.context.view_layer.update()
after, _ = obb.link_projection(scene, camera, link, dg, 1280, 640)
assert (Vector(before)-Vector(after['center_px'])).length < 1e-6

bpy.ops.mesh.primitive_cube_add(size=2, location=(0, 1, 2))
blocker = bpy.context.object
blocker.scale = (2, 1, .2)
bpy.context.view_layer.update()
report = obb.annotate(scene, camera, [link], dg, 1280, 640, config)
assert report['links'][0]['visible_samples'] == 0, report
assert report['label_lines'] == [], report
assert report['status'] == 'needs_review', report

# Same occlusion test with perspective rays.
camera.data.type = 'PERSP'
bpy.context.view_layer.update()
report = obb.annotate(scene, camera, [link], dg, 1280, 640, config)
assert not report['label_lines'], report
blocker.hide_render = True
blocker.hide_set(True)
bpy.context.view_layer.update()
report = obb.annotate(scene, camera, [link], dg, 1280, 640, config)
assert len(report['label_lines']) == 1, report

scene.world.use_nodes = True
scene.world.node_tree.nodes.new('ShaderNodeVolumeScatter')
report = obb.annotate(scene, camera, [link], dg, 1280, 640, config)
assert 'world_volume_requires_visual_review' in report['reasons']
print('PASS: top-origin projection, physical axis, stable centre, occlusion in both cameras and fog review')
