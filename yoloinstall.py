import sys
import subprocess
import bpy

# Path to Blender's internal Python executable
python_exe = sys.executable

# Upgrade pip and install Ultralytics + OpenCV
subprocess.call([python_exe, "-m", "pip", "install", "--upgrade", "pip"])
subprocess.call([python_exe, "-m", "pip", "install", "ultralytics", "opencv-python"])

print("Installation Complete!")
