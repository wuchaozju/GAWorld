"""Downscale the handbook images to the resolution a printed page can use.

Figures are placed 16 cm wide in the document, i.e. about 6.3 inches. At
300 dpi that is ~1900 px, so anything wider is wasted weight (and Word needs
that weight to open the file). Diagrams (flat colour) stay PNG; screenshots
(photographic) become JPEG at quality 86.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image

IMAGES = Path(__file__).resolve().parents[1] / "images"
MAX_WIDTH = 1900
SCREENSHOT_JPEG_QUALITY = 86


def main() -> int:
    before = after = 0
    for path in sorted(IMAGES.glob("*.png")):
        image = Image.open(path)
        original_bytes = path.stat().st_size
        before += original_bytes
        if image.width > MAX_WIDTH:
            ratio = MAX_WIDTH / image.width
            image = image.resize((MAX_WIDTH, round(image.height * ratio)), Image.LANCZOS)
        if path.name.startswith("d-"):
            # flat-colour diagram: PNG keeps the text crisp
            image.save(path, optimize=True)
        else:
            target = path.with_suffix(".jpg")
            image.convert("RGB").save(target, "JPEG", quality=SCREENSHOT_JPEG_QUALITY, optimize=True)
            path.unlink()
            path = target
        after += path.stat().st_size
        print(f"{path.name:34s} {original_bytes // 1024:>5} KB -> {path.stat().st_size // 1024:>4} KB")
    print(f"total {before // 1024} KB -> {after // 1024} KB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
