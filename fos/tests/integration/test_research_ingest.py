from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys
import importlib.util

import pytest

from fos.backend.services.ai_scientist import build_semantic_schema, build_source_outline, heuristic_analysis
from fos.backend.services.research_ingest import extract_document_payload


FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "research_papers"
FIXTURE_MANIFEST = FIXTURE_DIR / "fixture_manifest.json"
FIXTURES = json.loads(FIXTURE_MANIFEST.read_text(encoding="utf-8"))


def _resolve_fixture_python() -> Path | None:
    candidates = [
        Path(path)
        for path in [
            shutil.which("python"),
            shutil.which("python3"),
            sys.executable,
        ]
        if path
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def _require_fixture_runtime() -> None:
    if _resolve_fixture_python() is None:
        pytest.skip("No Python runtime is available for generating research fixture documents.")
    missing = [
        package
        for package in ("reportlab", "PIL")
        if importlib.util.find_spec(package) is None
    ]
    if missing:
        pytest.skip(
            "Research fixture generation requires optional packages that are not installed: "
            + ", ".join(missing)
        )


def _generate_fixture_docs(tmp_path: Path, fixture_id: str) -> dict[str, Path]:
    _require_fixture_runtime()
    runtime = _resolve_fixture_python()
    assert runtime is not None
    subprocess.run(
        [
            str(runtime),
            str(FIXTURE_DIR / "generate_fixture_documents.py"),
            "--manifest",
            str(FIXTURE_MANIFEST),
            "--fixture-id",
            fixture_id,
            "--output-dir",
            str(tmp_path),
        ],
        check=True,
    )
    stem = fixture_id
    return {
        "txt": tmp_path / f"{stem}.txt",
        "pdf": tmp_path / f"{stem}.pdf",
        "scanned_pdf": tmp_path / f"{stem}-scanned.pdf",
    }


def test_extract_document_payload_reads_text_pdf(tmp_path: Path) -> None:
    paths = _generate_fixture_docs(tmp_path, "fehr_gaechter_public_goods_2000")

    payload = extract_document_payload(
        paths["pdf"],
        "application/pdf",
        enable_ocr=True,
        ocr_lang="eng",
        source_language="en",
    )

    assert "20 tokens" in payload["text"].lower()
    assert "shared" in payload["text"].lower()
    assert "account" in payload["text"].lower()
    assert payload["page_count"] >= 1
    assert payload["sections"]
    assert any(section["title"].lower() == "abstract" for section in payload["sections"])
    assert payload["extraction_method"] != "none"
    assert payload["title"]
    assert payload["abstract"]
    assert isinstance(payload["references_text"], str)
    assert isinstance(payload["figure_captions"], list)
    assert isinstance(payload["table_captions"], list)
    assert payload["document_quality"]["section_count"] >= 1
    assert payload["document_quality"]["has_abstract"] is True


def test_extract_document_payload_uses_ocr_for_scanned_pdf(tmp_path: Path) -> None:
    if not shutil.which("tesseract") or not shutil.which("gs"):
        pytest.skip("OCR integration test requires Ghostscript and Tesseract.")

    paths = _generate_fixture_docs(tmp_path, "fehr_gaechter_public_goods_2000")

    payload = extract_document_payload(
        paths["scanned_pdf"],
        "application/pdf",
        enable_ocr=True,
        ocr_lang="eng",
        source_language="en",
    )

    assert "public goods" in payload["text"].lower()
    assert "20 tokens" in payload["text"].lower()
    assert "ocr" in payload["extraction_method"]
    assert any("ocr fallback" in warning.lower() for warning in payload["warnings"])
    assert payload["page_count"] >= 1


def test_extract_document_payload_recovers_escalating_bidding_structure(tmp_path: Path) -> None:
    if not shutil.which("tesseract") or not shutil.which("gs"):
        pytest.skip("OCR integration test requires Ghostscript and Tesseract.")
    paths = _generate_fixture_docs(tmp_path, "synthetic_escalating_bidding")

    payload = extract_document_payload(
        paths["scanned_pdf"],
        "application/pdf",
        enable_ocr=True,
        ocr_lang="eng",
        source_language="en",
    )

    assert "highest bidder" in payload["text"].lower()
    assert "second-highest bidder" in payload["text"].lower() or "second highest bidder" in payload["text"].lower()
    assert "increase the bid" in payload["text"].lower() or "raising the bid" in payload["text"].lower()
    assert "highest bidder" in payload["text"].lower()
    assert "ocr" in payload["extraction_method"]

    schema = build_semantic_schema(
        payload["text"],
        sections=payload.get("sections", []),
        outline=build_source_outline(payload["text"]),
        language="en",
    )
    result = heuristic_analysis(payload["text"], [], language="en")

    assert any(choice["name"] == "Increase bid" for choice in schema["choices"])
    assert any(
        "second highest bidder" in rule.lower() or "second-highest bidder" in rule.lower()
        for rule in schema["payoff_rules"]
    )
    assert "auctioneer" in {participant["label"] for participant in schema["participants"]}
    assert "bidders" in {participant["label"] for participant in schema["participants"]}
    assert schema["interaction_structure"]["family"] == "auction_escalation"
    assert "报价" in schema["ontology"]["action_primitives"]
    assert "auction_escalation" in schema["ontology"]["structure_candidates"]
    assert result["recommended_params"]["pay_top_two"] is True
    assert result["recommended_params"]["bid_increment_cents"] == 5
