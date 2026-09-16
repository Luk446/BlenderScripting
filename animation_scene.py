"""Configure or render an authored camera animation using background Blender."""
import argparse
import json
from pathlib import Path
import sys

import bpy
from mathutils import Vector

sys.path.insert(0, str(Path(__file__).resolve().parent))
from nas_storage import NAS_ROOT, require_nas


def animate_path(owner, constraint):
    owner.animation_data_clear()
    constraint.use_fixed_location = True
    for frame, offset in ((1, 0.0), (200, 1.0)):
        constraint.offset_factor = offset
        constraint.keyframe_insert('offset_factor', frame=frame)
    for layer in owner.animation_data.action.layers:
        for strip in layer.strips:
            for bag in strip.channelbags:
                for fcurve in bag.fcurves:
                    for key in fcurve.keyframe_points:
                        key.interpolation = 'LINEAR'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('inspect', 'configure', 'render'))
    parser.add_argument('--save', type=Path)
    parser.add_argument('--path', help='Existing curve object to follow')
    parser.add_argument('--distance', type=float, default=5.0,
                        help='New straight path length in scene units, camera local X')
    parser.add_argument('--output', type=Path)
    parser.add_argument('--start', type=int, default=1)
    parser.add_argument('--end', type=int, default=200)
    parser.add_argument('--samples', type=int, default=64)
    parser.add_argument('--percentage', type=int, default=100)
    parser.add_argument('--backend', choices=('OPTIX', 'CUDA'), default='OPTIX')
    args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:])
    scene = bpy.context.scene
    if args.mode == 'inspect':
        print(json.dumps(dict(camera=scene.camera.name if scene.camera else None,
                              frames=[scene.frame_start, scene.frame_end],
                              resolution=[scene.render.resolution_x, scene.render.resolution_y],
                              objects=[dict(name=o.name, type=o.type,
                                            location=list(o.matrix_world.translation),
                                            constraints=[dict(type=c.type, name=c.name)
                                                         for c in o.constraints])
                                       for o in scene.objects if o.type in ('CAMERA', 'CURVE')]), indent=2))
        return
    if not scene.camera:
        parser.error('Scene has no active camera')
    if args.mode == 'configure':
        if not args.save or args.save.exists():
            parser.error('--save must name a new .blend file')
        if args.save.suffix != '.blend':
            parser.error('--save must end in .blend')
        scene.frame_set(1)
        camera = scene.camera
        world = camera.matrix_world.copy()
        rig = camera.parent
        follow = next((c for c in rig.constraints if c.type == 'FOLLOW_PATH'), None) if rig else None
        if follow and not args.path:
            animate_path(rig, follow)
            for track in camera.constraints:
                if track.type in ('TRACK_TO', 'DAMPED_TRACK') and track.target:
                    for target_follow in track.target.constraints:
                        if target_follow.type == 'FOLLOW_PATH':
                            animate_path(track.target, target_follow)
            scene.frame_start, scene.frame_end, scene.frame_step = 1, 200, 1
            scene.render.image_settings.file_format = 'PNG'
            scene.render.filepath = str(NAS_ROOT / 'animations' / args.save.stem / 'frame_')
            positions = []
            for frame in (1, 100, 200):
                scene.frame_set(frame)
                positions.append(list(camera.evaluated_get(bpy.context.evaluated_depsgraph_get()).matrix_world.translation))
            if (Vector(positions[-1]) - Vector(positions[0])).length < 1e-6:
                raise RuntimeError('Camera endpoints coincide')
            scene.frame_set(1)
            args.save.parent.mkdir(parents=True, exist_ok=True)
            bpy.ops.wm.save_as_mainfile(filepath=str(args.save.resolve()))
            print(json.dumps(dict(saved=str(args.save), path=follow.target.name,
                                  camera=camera.name, positions_1_100_200=positions), indent=2))
            return
        if args.path:
            path = scene.objects.get(args.path)
            if path is None or path.type != 'CURVE' or len(path.data.splines) != 1:
                parser.error('--path must name a curve with exactly one spline')
        else:
            if args.distance <= 0:
                parser.error('--distance must be positive')
            curve = bpy.data.curves.new('CameraTravelLine', 'CURVE')
            curve.dimensions = '3D'
            spline = curve.splines.new('POLY')
            spline.points.add(1)
            start = world.translation
            end = start + world.to_quaternion() @ Vector((args.distance, 0, 0))
            for point, position in zip(spline.points, (start, end)):
                point.co = (*position, 1)
            path = bpy.data.objects.new('CameraTravelLine', curve)
            scene.collection.objects.link(path)
        path.data.use_path = True
        path.data.path_duration = 199
        path.hide_render = True
        path.hide_viewport = False
        path.hide_set(False)
        # Give the new camera independent animation and retain the authored camera.
        animated = camera.copy()
        animated.data = camera.data.copy()
        animated.name = 'AnimationCamera'
        scene.collection.objects.link(animated)
        animated.animation_data_clear()
        animated.parent = None
        animated.constraints.clear()
        animated.matrix_world = world
        animated.location = (0, 0, 0)
        constraint = animated.constraints.new('FOLLOW_PATH')
        constraint.name = 'Camera travel: frames 1-200'
        constraint.target = path
        constraint.use_fixed_location = True
        constraint.use_curve_follow = False
        animate_path(animated, constraint)
        scene.camera = animated
        scene.frame_start, scene.frame_end, scene.frame_step = 1, 200, 1
        scene.render.image_settings.file_format = 'PNG'
        scene.render.filepath = str(NAS_ROOT / 'animations' / args.save.stem / 'frame_')
        positions = []
        for frame in (1, 100, 200):
            scene.frame_set(frame)
            positions.append(list(animated.evaluated_get(bpy.context.evaluated_depsgraph_get()).matrix_world.translation))
        if (Vector(positions[-1]) - Vector(positions[0])).length < 1e-6:
            raise RuntimeError('Camera endpoints coincide; choose an open travel path')
        scene.frame_set(1)
        args.save.parent.mkdir(parents=True, exist_ok=True)
        bpy.ops.wm.save_as_mainfile(filepath=str(args.save.resolve()))
        print(json.dumps(dict(saved=str(args.save), path=path.name, camera=animated.name,
                              positions_1_100_200=positions), indent=2))
        return
    if not args.output or not 1 <= args.start <= args.end <= 200:
        parser.error('Supply --output and a frame range within 1..200')
    require_nas(args.output)
    if args.samples < 1 or not 1 <= args.percentage <= 100:
        parser.error('Samples must be positive; percentage must be 1..100')
    prefs = bpy.context.preferences.addons['cycles'].preferences
    prefs.compute_device_type = args.backend
    prefs.get_devices()
    devices = [d for d in prefs.devices if d.type == args.backend]
    if not devices:
        raise RuntimeError(f'No {args.backend} GPU available')
    for device in prefs.devices:
        device.use = device in devices
    print('Rendering on:', [d.name for d in devices], flush=True)
    scene.render.engine = 'CYCLES'
    scene.cycles.device = 'GPU'
    scene.cycles.samples = args.samples
    for layer in scene.view_layers:
        layer.samples = 0
    scene.frame_start, scene.frame_end, scene.frame_step = args.start, args.end, 1
    scene.render.resolution_percentage = args.percentage
    scene.render.image_settings.file_format = 'PNG'
    scene.render.use_file_extension = True
    args.output.mkdir(parents=True, exist_ok=True)
    scene.render.filepath = str(args.output.resolve() / 'frame_')
    if any(args.output.glob('frame_*.png')):
        parser.error('Output already contains frames; use a new directory')
    bpy.ops.render.render(animation=True)
    expected = [args.output / f'frame_{frame:04d}.png' for frame in range(args.start, args.end + 1)]
    if not all(p.is_file() and p.stat().st_size > 0 for p in expected):
        raise RuntimeError('Render did not produce all expected PNG frames')
    print(f'COMPLETE: {len(expected)} frames in {args.output}', flush=True)


if __name__ == '__main__':
    main()
