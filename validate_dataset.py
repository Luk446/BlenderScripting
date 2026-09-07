"""Run in background Blender with ChainLinkScene.blend; no images are rendered."""
import csv
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent))
import bpy
import generate_dataset as g


def snapshot():
    return {o.name: (tuple(v for row in o.matrix_world for v in row), o.hide_render,
                     o.hide_viewport, o.hide_get()) for o in bpy.context.scene.objects}


original = snapshot()
world = bpy.context.scene.world
settings = bpy.context.scene.objects['ParticleCube'].particle_systems[0].settings
g.OUTPUT_FOLDER = str(Path(__file__).parent/'validation')
g.NUMBER_OF_IMAGES = 8
g.MASTER_SEED = 42
g.DRY_RUN = True
g.FORCE_STRUCTURES_FOR_TEST = True
folder = g.main()
assert snapshot() == original, 'Scene transforms/visibility were not restored'
assert bpy.context.scene.world == world
assert bpy.context.scene.objects['ParticleCube'].particle_systems[0].settings == settings
rows = list(csv.DictReader((folder/'metadata.csv').open(encoding='utf-8')))
assert len(rows) == 8
assert any(not r['seabed'] for r in rows)
assert any(r['seabed'] for r in rows)
assert all(int(r['seed']) == 42+i for i,r in enumerate(rows))
assert any(json.loads(r['structures']) for r in rows)
assert all(json.loads(r['visible_rays'])[n] >= g.MIN_STRUCTURE_VISIBLE_RAYS
           for r in rows for n in json.loads(r['structures']))
# Repeat from restored state: scene choices and transforms must reproduce.
g.NUMBER_OF_IMAGES = 2
repeat = g.main()
again = list(csv.DictReader((repeat/'metadata.csv').open(encoding='utf-8')))
assert again == rows[:2], 'Seeded rerun changed scene choices'
assert snapshot() == original
# Force a placement failure and verify finally restores the scene as well.
g.CAMERA_CHAIN_CLEARANCE = 100000
try:
    g.main()
except RuntimeError as error:
    assert 'no safe camera position' in str(error)
else:
    raise AssertionError('Expected impossible camera placement to fail')
assert snapshot() == original, 'Failure path did not restore scene'
print('PASS: visibility diagnostics, seabed modes, deterministic reruns, restoration and failure cleanup')
