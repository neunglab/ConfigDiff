"""Build the multi-resolution macOS icon from the generated source artwork."""

from pathlib import Path
from PIL import Image

root = Path(__file__).resolve().parent.parent
source = root / "assets" / "ConfigDiff-icon.png"
output = root / "assets" / "ConfigDiff.icns"
with Image.open(source) as image:
    image.convert("RGBA").resize((1024, 1024), Image.Resampling.LANCZOS).save(output, format="ICNS")
