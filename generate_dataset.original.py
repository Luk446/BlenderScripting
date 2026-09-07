import bpy
import random
import os
from mathutils import Vector

# --------------------------------------------------
# SETTINGS
# --------------------------------------------------

NUMBER_OF_IMAGES = 20

OUTPUT_FOLDER = r"C:\Users\Luke\Pictures\MooringChainWorkImages\BlenderSimDataset"

IMAGE_WIDTH = 640
IMAGE_HEIGHT = 640

# Light power settings
MIN_BASE_POWER = 300
MAX_BASE_POWER = 375

MIN_LIGHT_MULTIPLIER = 0.9
MAX_LIGHT_MULTIPLIER = 1.1

# Light placement relative to camera
LIGHT_SIDE_OFFSET = 0.35
LIGHT_UP_OFFSET = 0.0
LIGHT_FORWARD_OFFSET = 0.15

# Camera randomisation around chain
CAMERA_X_RANGE = 4
CAMERA_Y_RANGE = 4
CAMERA_Z_MIN = 1
CAMERA_Z_MAX = 5

# Environment variation
NO_SEABED_PROBABILITY = 0.15
USE_STRUCTURES_PROBABILITY = 0.40

# Structure variation
MIN_STRUCTURES_VISIBLE = 1
MAX_STRUCTURES_VISIBLE = 5

STRUCTURE_X_JITTER = 0.30
STRUCTURE_Y_JITTER = 0.30
STRUCTURE_Z_JITTER = 0.10
STRUCTURE_ROT_Z_JITTER_DEG = 8.0

SEABED_PREFIX = "Seabed_"
CHAIN_COLLECTION_NAME = "Chain_Links"
STRUCTURE_COLLECTION_NAME = "Background_Structures"

STRUCTURE_NAMES = [
    "Old_Industrial_Pipe",
    "Steel_Pillar_01",
    "Steel_Pillar_02",
    "Steel_Pillar_03",
    "Steel_Pipe",
]

# --------------------------------------------------
# GET SCENE OBJECTS
# --------------------------------------------------

scene = bpy.context.scene
camera = scene.camera

if camera is None:
    raise Exception("No active camera found in the scene.")

chain_collection = bpy.data.collections.get(CHAIN_COLLECTION_NAME)
if chain_collection is None:
    raise Exception(f"Collection '{CHAIN_COLLECTION_NAME}' not found.")

links = [
    obj for obj in chain_collection.objects
    if obj.name.startswith("link_")
]

if not links:
    raise Exception("No chain link objects found with names starting 'link_'.")

light_left = bpy.data.objects.get("Light_Left")
light_right = bpy.data.objects.get("Light_Right")

if light_left is None or light_right is None:
    raise Exception("Could not find 'Light_Left' and/or 'Light_Right'.")

# Get all seabeds from scene by name
seabeds = [
    obj for obj in bpy.data.objects
    if obj.name.startswith(SEABED_PREFIX)
]

if not seabeds:
    raise Exception("No seabed objects found starting with 'Seabed_'.")

# Get structures from collection
structure_collection = bpy.data.collections.get(STRUCTURE_COLLECTION_NAME)
if structure_collection is None:
    raise Exception(f"Collection '{STRUCTURE_COLLECTION_NAME}' not found.")

structures = []
for name in STRUCTURE_NAMES:
    obj = bpy.data.objects.get(name)
    if obj is None:
        print(f"Warning: structure object '{name}' not found.")
    else:
        structures.append(obj)

if not structures:
    raise Exception("No structure objects found.")

# Store original transforms so jitter does not accumulate
original_structure_transforms = {}
for obj in structures:
    original_structure_transforms[obj.name] = {
        "location": obj.location.copy(),
        "rotation": obj.rotation_euler.copy(),
    }

# --------------------------------------------------
# FIND CHAIN CENTRE
# --------------------------------------------------

centre = Vector((0, 0, 0))
for obj in links:
    centre += obj.location
centre /= len(links)

print("Chain centre:", centre)

# --------------------------------------------------
# HELPER FUNCTIONS
# --------------------------------------------------

def set_object_visible(obj, visible):
    obj.hide_render = not visible
    obj.hide_set(not visible)

def point_object_at(obj, target):
    direction = target - obj.location
    obj.rotation_euler = direction.to_track_quat('-Z', 'Y').to_euler()

# --------------------------------------------------
# CAMERA FUNCTIONS
# --------------------------------------------------

def randomise_camera(camera, target):
    camera.location.x = target.x + random.uniform(-CAMERA_X_RANGE, CAMERA_X_RANGE)
    camera.location.y = target.y + random.uniform(-CAMERA_Y_RANGE, CAMERA_Y_RANGE)
    camera.location.z = target.z + random.uniform(CAMERA_Z_MIN, CAMERA_Z_MAX)

    point_object_at(camera, target)

# --------------------------------------------------
# LIGHT FUNCTIONS
# --------------------------------------------------

def get_camera_axes(camera):
    quat = camera.matrix_world.to_quaternion()

    right = quat @ Vector((1, 0, 0))
    up = quat @ Vector((0, 1, 0))
    forward = quat @ Vector((0, 0, -1))

    return right, up, forward

def place_lights_around_camera(camera, light_left, light_right):
    right, up, forward = get_camera_axes(camera)

    light_left.location = (
        camera.location
        - right * LIGHT_SIDE_OFFSET
        + up * LIGHT_UP_OFFSET
        + forward * LIGHT_FORWARD_OFFSET
    )

    light_right.location = (
        camera.location
        + right * LIGHT_SIDE_OFFSET
        + up * LIGHT_UP_OFFSET
        + forward * LIGHT_FORWARD_OFFSET
    )

    light_left.rotation_euler = camera.rotation_euler.copy()
    light_right.rotation_euler = camera.rotation_euler.copy()

def randomise_lights(light_left, light_right):
    base_power = random.uniform(MIN_BASE_POWER, MAX_BASE_POWER)

    left_multiplier = random.uniform(MIN_LIGHT_MULTIPLIER, MAX_LIGHT_MULTIPLIER)
    right_multiplier = random.uniform(MIN_LIGHT_MULTIPLIER, MAX_LIGHT_MULTIPLIER)

    light_left.data.energy = base_power * left_multiplier
    light_right.data.energy = base_power * right_multiplier

    print(
        f"Base: {base_power:.1f} W | "
        f"Left: {light_left.data.energy:.1f} W | "
        f"Right: {light_right.data.energy:.1f} W"
    )

# --------------------------------------------------
# SEABED FUNCTIONS
# --------------------------------------------------

def randomise_seabed():
    for seabed in seabeds:
        set_object_visible(seabed, False)

    if random.random() < NO_SEABED_PROBABILITY:
        print("Seabed: NONE")
        return None

    chosen_seabed = random.choice(seabeds)
    set_object_visible(chosen_seabed, True)

    print(f"Seabed: {chosen_seabed.name}")
    return chosen_seabed

# --------------------------------------------------
# STRUCTURE FUNCTIONS
# --------------------------------------------------

def reset_structure_transforms():
    for obj in structures:
        data = original_structure_transforms[obj.name]
        obj.location = data["location"].copy()
        obj.rotation_euler = data["rotation"].copy()

def jitter_structure(obj):
    data = original_structure_transforms[obj.name]

    obj.location.x = data["location"].x + random.uniform(-STRUCTURE_X_JITTER, STRUCTURE_X_JITTER)
    obj.location.y = data["location"].y + random.uniform(-STRUCTURE_Y_JITTER, STRUCTURE_Y_JITTER)
    obj.location.z = data["location"].z + random.uniform(-STRUCTURE_Z_JITTER, STRUCTURE_Z_JITTER)

    obj.rotation_euler.x = data["rotation"].x
    obj.rotation_euler.y = data["rotation"].y
    obj.rotation_euler.z = data["rotation"].z + random.uniform(
        -STRUCTURE_ROT_Z_JITTER_DEG, STRUCTURE_ROT_Z_JITTER_DEG
    ) * 3.141592653589793 / 180.0

def randomise_structures():
    for obj in structures:
        set_object_visible(obj, False)

    reset_structure_transforms()

    if random.random() >= USE_STRUCTURES_PROBABILITY:
        print("Background structures: OFF")
        return []

    max_count = min(MAX_STRUCTURES_VISIBLE, len(structures))
    min_count = min(MIN_STRUCTURES_VISIBLE, max_count)

    count = random.randint(min_count, max_count)
    visible_structures = random.sample(structures, count)

    for obj in visible_structures:
        set_object_visible(obj, True)
        jitter_structure(obj)

    print("Background structures: ON")
    print("Visible structures:", [obj.name for obj in visible_structures])

    return visible_structures

# --------------------------------------------------
# OUTPUT SETTINGS
# --------------------------------------------------

os.makedirs(OUTPUT_FOLDER, exist_ok=True)

scene.render.resolution_x = IMAGE_WIDTH
scene.render.resolution_y = IMAGE_HEIGHT
scene.render.resolution_percentage = 100
scene.render.image_settings.file_format = 'PNG'

# --------------------------------------------------
# GENERATE IMAGES
# --------------------------------------------------

for i in range(NUMBER_OF_IMAGES):
    print()
    print("----------------------------------------")
    print(f"Generating image {i + 1}/{NUMBER_OF_IMAGES}")

    # 1. Random seabed / no seabed
    randomise_seabed()

    # 2. Random background structures
    randomise_structures()

    # 3. Move camera
    randomise_camera(camera, centre)

    # 4. Put lights beside camera
    place_lights_around_camera(camera, light_left, light_right)

    # 5. Randomise light powers
    randomise_lights(light_left, light_right)

    filename = f"chain_{i:05d}.png"
    scene.render.filepath = os.path.join(OUTPUT_FOLDER, filename)

    bpy.ops.render.render(write_still=True)

    print("Rendered:", filename)

print()
print("Finished generating dataset!")
print("Output folder:", OUTPUT_FOLDER)