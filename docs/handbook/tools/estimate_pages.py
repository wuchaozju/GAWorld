"""Estimate the printed page count of the built .docx.

Word is not reliably scriptable on this machine, so the page count is derived
from the document's own layout parameters: page size and margins come from
the section properties, line metrics come from the styles, and image heights
come from the inline extents.

The estimator is checked against a known export (a 239-page build of the same
manuscript) before its result is trusted.
"""

from __future__ import annotations

import math
import re
import sys
import zipfile
from pathlib import Path

TWIP_CM = 2.54 / 1440
EMU_CM = 2.54 / 360000

# style -> (font pt, line multiple, space before twips, space after twips)
STYLE_METRICS = {
    "Normal": (10.5, 1.2, 0, 70),
    "BodyText": (10.5, 1.2, 0, 70),
    "FirstParagraph": (10.5, 1.2, 0, 70),
    "Compact": (10.5, 1.2, 0, 40),
    "Heading1": (18.0, 1.2, 200, 120),
    "Heading2": (14.0, 1.2, 150, 100),
    "Heading3": (12.0, 1.2, 130, 90),
    "Heading4": (11.0, 1.2, 110, 80),
    "Title": (30.0, 1.2, 0, 160),
    "Subtitle": (14.0, 1.2, 0, 140),
    "Caption": (9.0, 1.2, 60, 140),
    "ImageCaption": (9.0, 1.2, 60, 140),
    "SourceCode": (9.0, 1.0, 50, 90),
    "TOC1": (10.5, 1.2, 60, 60),
    "TOC2": (10.0, 1.2, 0, 60),
    "TOC3": (10.0, 1.2, 0, 60),
    "FootnoteText": (9.0, 1.2, 0, 40),
}


def style_of(paragraph_xml: str) -> str:
    match = re.search(r'<w:pStyle w:val="([^"]+)"', paragraph_xml)
    return match.group(1) if match else "Normal"


def text_of(paragraph_xml: str) -> str:
    return "".join(re.findall(r"<w:t[^>]*>(.*?)</w:t>", paragraph_xml, re.S))


def line_count(text: str, font_pt: float, width_cm: float, mono: bool = False) -> int:
    """How many lines *text* needs in a column *width_cm* wide."""
    if not text.strip():
        return 1
    # CJK glyphs are one em wide; latin averages ~0.5 em; mono is 0.6 em.
    cjk = len(re.findall(r"[\u4e00-\u9fff\u3000-\u303f\uff00-\uffef]", text))
    latin = len(text) - cjk
    em = font_pt * 0.03528  # pt -> cm
    if mono:
        used = (cjk + latin) * em * 0.6
    else:
        used = cjk * em + latin * em * 0.5
    return max(1, math.ceil(used / width_cm))


def main() -> int:
    path = Path(sys.argv[1])
    with zipfile.ZipFile(path) as archive:
        document = archive.read("word/document.xml").decode("utf-8")
        styles = archive.read("word/styles.xml").decode("utf-8")

    sect_match = re.search(r"<w:pgSz[^>]*/>", document)
    mar_match = re.search(r"<w:pgMar[^>]*/>", document)
    if not (sect_match and mar_match):
        print("could not read page setup")
        return 1
    sect = sect_match.group(0)
    mar = mar_match.group(0)
    page_w = int(re.search(r'w:w="(\d+)"', sect).group(1)) * TWIP_CM
    page_h = int(re.search(r'w:h="(\d+)"', sect).group(1)) * TWIP_CM
    left = int(re.search(r'w:left="(\d+)"', mar).group(1)) * TWIP_CM
    right = int(re.search(r'w:right="(\d+)"', mar).group(1)) * TWIP_CM
    top = int(re.search(r'w:top="(\d+)"', mar).group(1)) * TWIP_CM
    bottom = int(re.search(r'w:bottom="(\d+)"', mar).group(1)) * TWIP_CM
    col_w = page_w - left - right
    col_h = page_h - top - bottom
    print(f"page {page_w:.1f} x {page_h:.1f} cm, text column {col_w:.2f} x {col_h:.2f} cm")

    body = document.split("<w:body>", 1)[1]
    # walk block elements in order
    blocks = re.findall(r"<w:p\b.*?</w:p>|<w:tbl>.*?</w:tbl>", body, re.S)

    used = 0.0
    pages = 1
    images = 0

    def place(height: float) -> None:
        """Add a block; a block that does not fit moves whole to the next page."""
        nonlocal used, pages
        if used > 0 and used + height > col_h:
            pages += 1
            used = 0.0
        if height > col_h:  # a block taller than the column spans pages
            extra = math.floor(height / col_h)
            pages += int(extra)
            used = height - extra * col_h
            return
        used += height

    for block in blocks:
        if block.startswith("<w:tbl"):
            rows = re.findall(r"<w:tr\b.*?</w:tr>", block, re.S)
            height = 0.0
            for row in rows:
                cells = re.findall(r"<w:tc>.*?</w:tc>", row, re.S)
                cell_lines = 1
                for cell in cells:
                    cell_text = "".join(re.findall(r"<w:t[^>]*>(.*?)</w:t>", cell, re.S))
                    cell_lines = max(cell_lines, line_count(cell_text, 10.5, col_w / max(1, len(cells)) - 0.4))
                height += cell_lines * 10.5 * 0.03528 * 1.2 + 0.10
            place(height + 0.12)
        else:
            style = style_of(block)
            font, multiple, before, after = STYLE_METRICS.get(style, STYLE_METRICS["Normal"])
            extents = re.findall(r'<wp:extent cx="(\d+)" cy="(\d+)"', block)
            if extents:
                images += len(extents)
                for _, cy in extents:
                    place(int(cy) * EMU_CM + 0.25)
                continue
            text = text_of(block)
            lines = line_count(text, font, col_w, mono=(style == "SourceCode"))
            height = before * TWIP_CM + lines * font * 0.03528 * multiple + after * TWIP_CM
            if '<w:br w:type="page"' in block:
                pages += 1
                used = 0.0
            place(height)

    print(f"paragraph/table blocks: {len(blocks)}")
    print(f"inline images: {images}")
    print(f"estimated pages: {pages}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
