"""Robust document ingestion for AI-assisted experiment drafting.

This module provides one unified extraction path for research source files.
It prefers native text extraction when available, and falls back to OCR for
image-based PDFs or environments where Python parsing libraries are missing.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from typing import Any
from urllib import error as urllib_error
from urllib import request as urllib_request
import xml.etree.ElementTree as ET

from fos.i18n import T


_GS_CANDIDATES = ("/usr/local/bin/gs", shutil.which("gs"))
_TEXTUTIL_CANDIDATES = ("/usr/bin/textutil", shutil.which("textutil"))
_TESSERACT_CANDIDATES = ("/opt/homebrew/bin/tesseract", shutil.which("tesseract"))


@dataclass
class ExtractedPage:
    page_number: int
    text: str
    method: str


def _pick_existing(candidates: tuple[str | None, ...]) -> str | None:
    for item in candidates:
        if item and Path(item).exists():
            return item
    return None


def _run_command(cmd: list[str], *, timeout: int = 180, check: bool = True) -> str:
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    if check and result.returncode != 0:
        stderr = (result.stderr or "").strip()
        stdout = (result.stdout or "").strip()
        detail = stderr or stdout or f"exit code {result.returncode}"
        raise RuntimeError(T("error.research_ingest.command_failed", cmd=" ".join(cmd), detail=detail))
    return result.stdout or ""


def _normalize_text(text: str) -> str:
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"(?<=\w)-\n(?=\w)", "-", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _decode_text_bytes(raw: bytes) -> str:
    for encoding in ("utf-8", "utf-16", "utf-16le", "utf-16be", "latin-1"):
        try:
            return raw.decode(encoding).strip()
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="ignore").strip()


def _page_text_quality(text: str) -> float:
    cleaned = (text or "").strip()
    if not cleaned:
        return 0.0
    alnum = sum(1 for ch in cleaned if ch.isalnum())
    return (alnum / max(len(cleaned), 1)) * min(len(cleaned) / 400.0, 1.0)


def _is_strong_extraction(pages: list[ExtractedPage]) -> bool:
    if not pages:
        return False
    total_chars = sum(len(page.text.strip()) for page in pages)
    nonempty_pages = [page for page in pages if page.text.strip()]
    if not nonempty_pages:
        return False
    mean_quality = sum(_page_text_quality(page.text) for page in nonempty_pages) / len(nonempty_pages)
    return total_chars >= 500 and mean_quality >= 0.16


def _default_ocr_lang(source_language: str | None, configured_lang: str | None) -> str:
    if configured_lang:
        return configured_lang
    if source_language and source_language.startswith("zh"):
        return "chi_sim+eng"
    return "eng+chi_sim"


def _extract_pdf_text_with_pypdf(path: Path) -> list[ExtractedPage]:
    try:
        import pypdf  # type: ignore
    except Exception:
        return []

    pages: list[ExtractedPage] = []
    try:
        with path.open("rb") as fh:
            reader = pypdf.PdfReader(fh)
            for index, page in enumerate(reader.pages, start=1):
                pages.append(
                    ExtractedPage(
                        page_number=index,
                        text=_normalize_text(page.extract_text() or ""),
                        method="pypdf",
                    )
                )
    except Exception:
        return []
    return pages


def _extract_pdf_text_with_docling(path: Path) -> tuple[list[ExtractedPage], list[dict[str, Any]]]:
    try:
        from docling.document_converter import DocumentConverter  # type: ignore
    except Exception:
        return [], []

    try:
        converter = DocumentConverter()
        result = converter.convert(str(path))
        document = getattr(result, "document", None)
        if document is None:
            return [], []

        text = ""
        for attr in ("export_to_text", "export_to_markdown"):
            exporter = getattr(document, attr, None)
            if callable(exporter):
                text = _normalize_text(exporter() or "")
                if text:
                    break
        if not text:
            text = _normalize_text(str(document))
        if not text:
            return [], []

        sections = _split_into_sections(text, [ExtractedPage(page_number=1, text=text, method="docling")])
        return ([ExtractedPage(page_number=1, text=text, method="docling")], sections)
    except Exception:
        return [], []


def _extract_pdf_text_with_grobid(path: Path) -> tuple[list[ExtractedPage], list[dict[str, Any]]]:
    base_url = os.getenv("FOS_GROBID_URL", "").strip().rstrip("/")
    if not base_url:
        return [], []

    endpoint = f"{base_url}/api/processFulltextDocument"
    boundary = "----FOSGrobidBoundary"
    file_bytes = path.read_bytes()
    payload = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="input"; filename="{path.name}"\r\n'
        "Content-Type: application/pdf\r\n\r\n"
    ).encode("utf-8") + file_bytes + f"\r\n--{boundary}--\r\n".encode("utf-8")
    request = urllib_request.Request(
        endpoint,
        data=payload,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    try:
        with urllib_request.urlopen(request, timeout=180) as response:
            tei_xml = response.read().decode("utf-8", errors="ignore")
    except (urllib_error.URLError, TimeoutError, ValueError):
        return [], []

    try:
        root = ET.fromstring(tei_xml)
    except ET.ParseError:
        return [], []

    ns = {"tei": "http://www.tei-c.org/ns/1.0"}
    title_node = root.find(".//tei:titleStmt/tei:title", ns)
    title = _normalize_text("".join(title_node.itertext()) if title_node is not None else "")
    abstract = _normalize_text(" ".join("".join(node.itertext()) for node in root.findall(".//tei:profileDesc/tei:abstract", ns)))
    section_nodes = root.findall(".//tei:body/tei:div", ns)
    sections: list[dict[str, Any]] = []
    body_parts: list[str] = []

    if title:
        body_parts.append(title)
    if abstract:
        body_parts.append(f"Abstract\n{abstract}")
        sections.append({"id": "section-abstract", "title": "Abstract", "excerpt": abstract[:700], "page": None})

    for index, div in enumerate(section_nodes, start=1):
        head = _normalize_text("".join(div.findtext("tei:head", default="", namespaces=ns).split()))
        paragraph_text = _normalize_text("\n\n".join(_normalize_text("".join(node.itertext())) for node in div.findall("tei:p", ns)))
        if not paragraph_text:
            paragraph_text = _normalize_text("".join(div.itertext()))
        if not paragraph_text:
            continue
        body_parts.append(f"{head}\n{paragraph_text}" if head else paragraph_text)
        sections.append(
            {
                "id": f"section-{index}",
                "title": head or f"Excerpt {index}",
                "excerpt": paragraph_text[:700],
                "page": None,
            }
        )

    full_text = _normalize_text("\n\n".join(part for part in body_parts if part))
    if not full_text:
        return [], []
    return ([ExtractedPage(page_number=1, text=full_text, method="grobid")], sections[:12])


def _extract_pdf_text_with_ghostscript(path: Path) -> list[ExtractedPage]:
    gs = _pick_existing(_GS_CANDIDATES)
    if not gs:
        return []

    try:
        output = _run_command(
            [gs, "-q", "-dNOPAUSE", "-dBATCH", "-sDEVICE=txtwrite", "-sOutputFile=-", str(path)],
            timeout=180,
        )
    except Exception:
        return []

    chunks = [_normalize_text(chunk) for chunk in re.split(r"\f+", output) if _normalize_text(chunk)]
    return [
        ExtractedPage(page_number=index, text=chunk, method="ghostscript-text")
        for index, chunk in enumerate(chunks, start=1)
    ]


def _render_pdf_pages(path: Path) -> list[Path]:
    gs = _pick_existing(_GS_CANDIDATES)
    if not gs:
        raise RuntimeError(T("error.research_ingest.ghostscript_not_available"))

    tmpdir = Path(tempfile.mkdtemp(prefix="fos-pdf-ocr-"))
    output_pattern = tmpdir / "page-%03d.png"
    _run_command(
        [
            gs,
            "-q",
            "-dNOPAUSE",
            "-dBATCH",
            "-sDEVICE=png16m",
            "-r220",
            f"-sOutputFile={output_pattern}",
            str(path),
        ],
        timeout=300,
    )
    pages = sorted(tmpdir.glob("page-*.png"))
    if not pages:
        raise RuntimeError(T("error.research_ingest.ghostscript_no_pages"))
    return pages


def _ocr_image(path: Path, ocr_lang: str) -> str:
    tesseract = _pick_existing(_TESSERACT_CANDIDATES)
    if not tesseract:
        raise RuntimeError(T("error.research_ingest.tesseract_not_available"))
    return _normalize_text(
        _run_command([tesseract, str(path), "stdout", "-l", ocr_lang], timeout=180)
    )


def _extract_pdf_text_with_ocr(path: Path, ocr_lang: str) -> list[ExtractedPage]:
    rendered_pages = _render_pdf_pages(path)
    pages: list[ExtractedPage] = []
    try:
        for index, image_path in enumerate(rendered_pages, start=1):
            pages.append(
                ExtractedPage(
                    page_number=index,
                    text=_ocr_image(image_path, ocr_lang),
                    method="ocr",
                )
            )
    finally:
        shutil.rmtree(rendered_pages[0].parent, ignore_errors=True)
    return pages


def _extract_doc_text_with_textutil(path: Path) -> str:
    textutil = _pick_existing(_TEXTUTIL_CANDIDATES)
    if not textutil:
        return ""
    try:
        return _normalize_text(
            _run_command([textutil, "-convert", "txt", "-stdout", str(path)], timeout=120)
        )
    except Exception:
        return ""


def _extract_docx_text(path: Path) -> str:
    try:
        import docx  # type: ignore
    except Exception:
        return _extract_doc_text_with_textutil(path)

    try:
        document = docx.Document(path)
        paragraphs = [para.text.strip() for para in document.paragraphs if para.text and para.text.strip()]
        text = _normalize_text("\n\n".join(paragraphs))
        return text or _extract_doc_text_with_textutil(path)
    except Exception:
        return _extract_doc_text_with_textutil(path)


def _split_into_sections(text: str, pages: list[ExtractedPage]) -> list[dict[str, Any]]:
    if not text.strip():
        return []

    page_by_text: dict[str, int] = {}
    for page in pages:
        page_text = page.text.strip()
        if page_text:
            page_by_text[page_text[:160]] = page.page_number

    section_pattern = re.compile(
        r"(?im)^(abstract|摘要|introduction|引言|background|methods?|methodology|方法|materials and methods|results?|结果|discussion|讨论|conclusion|结论|limitations?)\s*$"
    )

    sections: list[dict[str, Any]] = []
    matches = list(section_pattern.finditer(text))
    if matches:
        for index, match in enumerate(matches):
            start = match.end()
            end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
            body = _normalize_text(text[start:end])
            if not body:
                continue
            section_excerpt = body[:700]
            page_number = None
            for key, candidate_page in page_by_text.items():
                if key and key in body:
                    page_number = candidate_page
                    break
            sections.append(
                {
                    "id": f"section-{index + 1}",
                    "title": match.group(1).strip(),
                    "excerpt": section_excerpt,
                    "page": page_number,
                }
            )

    if sections:
        return sections[:12]

    paragraphs = [chunk.strip() for chunk in re.split(r"\n{2,}", text) if chunk.strip()]
    if not paragraphs:
        paragraphs = [text]
    for index, paragraph in enumerate(paragraphs[:12], start=1):
        sections.append(
            {
                "id": f"excerpt-{index}",
                "title": f"Excerpt {index}",
                "excerpt": paragraph[:700],
                "page": None,
            }
        )
    return sections


def _extract_title(text: str) -> str:
    if not text.strip():
        return ""
    lines = [line.strip() for line in text.splitlines()[:15] if line.strip()]
    for line in lines:
        lowered = line.lower()
        if len(line) < 8 or len(line) > 220:
            continue
        if re.search(r"(copyright|doi|http|www\.|license|accepted|published online)", lowered):
            continue
        if re.fullmatch(r"[\W_]+", line):
            continue
        return line
    return lines[0] if lines else ""


def _extract_abstract(text: str, sections: list[dict[str, Any]]) -> str:
    for section in sections:
        title = str(section.get("title", "")).strip().lower()
        if title in {"abstract", "摘要"}:
            return _normalize_text(str(section.get("excerpt", "")))
    match = re.search(
        r"(?is)^(?:abstract|摘要)\s*(.+?)(?=\n\s*(?:introduction|背景|background|methods?|方法|materials and methods|results?|结论|discussion)\s*$)",
        text,
    )
    if match:
        return _normalize_text(match.group(1))
    return ""


def _extract_caption_blocks(text: str) -> tuple[list[str], list[str]]:
    figure_captions: list[str] = []
    table_captions: list[str] = []
    patterns = [
        (r"(?im)^(figure|fig\.?)\s*\d+[a-z]?\s*[:.-]?\s*(.+)$", figure_captions),
        (r"(?im)^table\s*\d+[a-z]?\s*[:.-]?\s*(.+)$", table_captions),
        (r"(?im)^(图)\s*\d+[a-z]?\s*[:：.-]?\s*(.+)$", figure_captions),
        (r"(?im)^(表)\s*\d+[a-z]?\s*[:：.-]?\s*(.+)$", table_captions),
    ]
    for pattern, bucket in patterns:
        for match in re.finditer(pattern, text):
            pieces = [piece for piece in match.groups() if piece]
            caption = _normalize_text(" ".join(pieces))
            if caption:
                bucket.append(caption[:320])
    return figure_captions[:12], table_captions[:12]


def _split_reference_text(text: str) -> tuple[str, str]:
    cleaned = _normalize_text(text)
    if not cleaned:
        return "", ""
    match = re.search(
        r"(?im)^\s*(references|reference|bibliography|参考文献|appendix|appendices)\s*$",
        cleaned,
    )
    if not match:
        return cleaned, ""
    return _normalize_text(cleaned[:match.start()]), _normalize_text(cleaned[match.start():])


def _build_document_quality(
    *,
    text: str,
    pages: list[ExtractedPage],
    sections: list[dict[str, Any]],
    extraction_method: str,
    warnings: list[str],
    title: str,
    abstract: str,
    references_text: str,
) -> dict[str, Any]:
    nonempty_pages = [page for page in pages if page.text.strip()]
    mean_quality = (
        sum(_page_text_quality(page.text) for page in nonempty_pages) / len(nonempty_pages)
        if nonempty_pages
        else 0.0
    )
    return {
        "section_count": len(sections),
        "has_title": bool(title),
        "has_abstract": bool(abstract),
        "has_references": bool(references_text),
        "ocr_used": "ocr" in extraction_method,
        "strong_extraction": _is_strong_extraction(pages),
        "average_page_quality": round(mean_quality, 3),
        "warnings": warnings[:6],
        "char_count": len(text),
    }


def extract_document_payload(
    path: Path,
    content_type: str,
    *,
    enable_ocr: bool,
    ocr_lang: str | None,
    source_language: str | None = None,
) -> dict[str, Any]:
    """Extract text and metadata from a research source document."""
    resolved_type = (content_type or "").lower()
    warnings: list[str] = []
    sections: list[dict[str, Any]] = []

    if resolved_type == "text/plain":
        text = _normalize_text(_decode_text_bytes(path.read_bytes()))
        pages = [ExtractedPage(page_number=1, text=text, method="plain-text")] if text else []
    elif resolved_type == "application/pdf":
        pages, sections = _extract_pdf_text_with_docling(path)
        if not _is_strong_extraction(pages):
            grobid_pages, grobid_sections = _extract_pdf_text_with_grobid(path)
            if _is_strong_extraction(grobid_pages):
                pages = grobid_pages
                sections = grobid_sections
        if not _is_strong_extraction(pages):
            pages = _extract_pdf_text_with_pypdf(path)
        if not _is_strong_extraction(pages):
            gs_pages = _extract_pdf_text_with_ghostscript(path)
            if _is_strong_extraction(gs_pages):
                pages = gs_pages
            elif enable_ocr:
                if not _pick_existing(_TESSERACT_CANDIDATES):
                    warnings.append("OCR fallback was requested but Tesseract is unavailable.")
                else:
                    pages = _extract_pdf_text_with_ocr(
                        path,
                        _default_ocr_lang(source_language, ocr_lang),
                    )
                    warnings.append("Used OCR fallback because direct PDF text extraction was weak.")
            else:
                warnings.append("Direct PDF text extraction was weak and OCR was disabled.")
        text = _normalize_text("\n\n".join(page.text for page in pages if page.text.strip()))
    elif resolved_type in {
        "application/msword",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    }:
        text = _extract_docx_text(path)
        if not text and resolved_type == "application/msword":
            warnings.append("Legacy .doc extraction is best-effort and may lose formatting.")
        pages = [ExtractedPage(page_number=1, text=text, method="textutil-doc")] if text else []
    else:
        text = ""
        pages = []

    if not sections:
        sections = _split_into_sections(text, pages)
    text_wo_references, references_text = _split_reference_text(text)
    if text_wo_references:
        text = text_wo_references
        if not sections:
            sections = _split_into_sections(text, pages)
    extraction_method = ",".join(sorted({page.method for page in pages if page.method})) if pages else "none"
    title = _extract_title(text)
    abstract = _extract_abstract(text, sections)
    figure_captions, table_captions = _extract_caption_blocks(text)
    document_quality = _build_document_quality(
        text=text,
        pages=pages,
        sections=sections,
        extraction_method=extraction_method,
        warnings=warnings,
        title=title,
        abstract=abstract,
        references_text=references_text,
    )

    return {
        "text": text,
        "title": title,
        "abstract": abstract,
        "figure_captions": figure_captions,
        "table_captions": table_captions,
        "references_text": references_text,
        "pages": [
            {
                "page_number": page.page_number,
                "text": page.text,
                "method": page.method,
                "char_count": len(page.text),
            }
            for page in pages
        ],
        "page_count": max(len(pages), 1 if text else 0),
        "extraction_method": extraction_method,
        "warnings": warnings,
        "sections": sections,
        "document_quality": document_quality,
    }
