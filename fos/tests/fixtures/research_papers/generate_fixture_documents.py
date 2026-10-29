from __future__ import annotations

import argparse
import json
from pathlib import Path
import textwrap


def _load_manifest(path: Path) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))


def _find_fixture(manifest: list[dict], fixture_id: str) -> dict:
    for item in manifest:
        if item.get("id") == fixture_id:
            return item
    raise SystemExit(f"Unknown fixture id: {fixture_id}")


def _write_text_file(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def _write_text_pdf(path: Path, text: str, title: str) -> None:
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas

    page_width, page_height = letter
    pdf = canvas.Canvas(str(path), pagesize=letter)
    pdf.setTitle(title)
    pdf.setFont("Helvetica", 11)

    lines: list[str] = []
    for paragraph in text.splitlines():
        if not paragraph.strip():
            lines.append("")
            continue
        lines.extend(textwrap.wrap(paragraph, width=92))

    y = page_height - 72
    for line in lines:
        if y < 72:
            pdf.showPage()
            pdf.setFont("Helvetica", 11)
            y = page_height - 72
        pdf.drawString(72, y, line)
        y -= 15

    pdf.save()


def _write_scanned_pdf(path: Path, text: str, title: str) -> None:
    from PIL import Image, ImageDraw, ImageFont
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas

    image = Image.new("RGB", (1700, 2200), color="white")
    draw = ImageDraw.Draw(image)
    font_candidates = [
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/System/Library/Fonts/Supplemental/Helvetica.ttc",
        "/System/Library/Fonts/Menlo.ttc",
    ]
    font = None
    for candidate in font_candidates:
        candidate_path = Path(candidate)
        if candidate_path.exists():
            font = ImageFont.truetype(str(candidate_path), 28)
            break
    if font is None:
        font = ImageFont.load_default()

    wrapped_lines: list[str] = []
    for paragraph in text.splitlines():
        if not paragraph.strip():
            wrapped_lines.append("")
            continue
        wrapped_lines.extend(textwrap.wrap(paragraph, width=95))

    y = 80
    for line in wrapped_lines:
        draw.text((80, y), line, fill="black", font=font)
        y += 40

    image_path = path.with_suffix(".png")
    image.save(image_path)

    page_width, page_height = letter
    pdf = canvas.Canvas(str(path), pagesize=letter)
    pdf.setTitle(title)
    pdf.drawImage(ImageReader(str(image_path)), 0, 0, width=page_width, height=page_height)
    pdf.save()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--fixture-id", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()

    manifest = _load_manifest(Path(args.manifest))
    fixture = _find_fixture(manifest, args.fixture_id)

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    stem = fixture["id"]
    title = fixture["title"]
    text = fixture["text"]

    _write_text_file(output_dir / f"{stem}.txt", text)
    _write_text_pdf(output_dir / f"{stem}.pdf", text, title)
    _write_scanned_pdf(output_dir / f"{stem}-scanned.pdf", text, title)

    metadata = {
        "id": fixture["id"],
        "title": fixture["title"],
        "expected_scenario_id": fixture["expected_scenario_id"],
        "citation": fixture["citation"],
        "doi": fixture["doi"],
        "text_path": str(output_dir / f"{stem}.txt"),
        "pdf_path": str(output_dir / f"{stem}.pdf"),
        "scanned_pdf_path": str(output_dir / f"{stem}-scanned.pdf"),
    }
    (output_dir / f"{stem}.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
