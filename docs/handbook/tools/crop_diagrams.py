"""Trim uniform white margins off the generated diagram PNGs.

The diagram renderer screenshots a full 900px-tall viewport, so short
diagrams carry a large empty band at the bottom. Cropping to the content
bounding box makes them denser on the page and removes wasted space.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageChops

IMAGES = Path(__file__).resolve().parents[1] / "images"
PAD = 24


def content_bbox(image: Image.Image, threshold: int = 248) -> tuple[int, int, int, int] | None:
    """Bounding box of everything darker than *threshold* on white."""
    rgb = image.convert("RGB")
    background = Image.new("RGB", rgb.size, (255, 255, 255))
    diff = ImageChops.difference(rgb, background).convert("L")
    mask = diff.point(lambda px: 255 if px > (255 - threshold) else 0)
    return mask.getbbox()


def main() -> int:
    changed = 0
    for path in sorted(IMAGES.glob("d-*.png")):
        image = Image.open(path)
        box = content_bbox(image)
        if box is None:
            print(f"skip (blank): {path.name}")
            continue
        left, top, right, bottom = box
        cropped = image.crop(
            (
                max(0, left - PAD),
                max(0, top - PAD),
                min(image.width, right + PAD),
                min(image.height, bottom + PAD),
            )
        )
        if cropped.size == image.size:
            continue
        before = image.size
        cropped.save(path, optimize=True)
        changed += 1
        print(f"{path.name}: {before} -> {cropped.size}")
    print(f"cropped {changed} diagrams")
    return 0


if __name__ == "__main__":
    sys.exit(main())
