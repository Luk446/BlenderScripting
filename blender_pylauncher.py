"""Copy this whole file into Blender's Text Editor and press Run Script."""
from pathlib import Path
import runpy

SCRIPT_PATH = Path(r"C:\Users\Luke\Documents\Blends\generate_dataset.py")
if not SCRIPT_PATH.is_file():
    raise FileNotFoundError(f"Dataset generator not found: {SCRIPT_PATH}")

# A fresh namespace and a fresh disk read on every click; no import cache.
runpy.run_path(str(SCRIPT_PATH), run_name="__main__")
