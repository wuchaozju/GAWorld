"""The API must preserve source provenance across upload and background jobs."""

import base64
import hashlib
import json
import sys
from types import SimpleNamespace

from gaworld.apps import research_api
from gaworld.research import workbench


def test_pdf_keeps_page_boundaries_and_reports_textless_pages(monkeypatch):
    reader = SimpleNamespace()
    reader.pages = [
        SimpleNamespace(extract_text=lambda: "First page"),
        SimpleNamespace(extract_text=lambda: ""),
        SimpleNamespace(extract_text=lambda: "Third page"),
    ]
    monkeypatch.setitem(sys.modules, "pypdf", SimpleNamespace(PdfReader=lambda _: reader))
    result = research_api.extract_text({"name": "paper.pdf", "data": base64.b64encode(b"%PDF-mock").decode()})
    assert "[Page 1]" in result["text"] and "[Page 3]" in result["text"]
    assert result["text_pages"] == 2
    assert result["empty_pages"] == [2]
    assert result["warnings"]


def test_digest_job_keeps_original_text_after_long_input(tmp_path, monkeypatch):
    monkeypatch.setattr(workbench, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(research_api, "_JOBS", {})
    monkeypatch.setattr(
        research_api, "_llm", lambda *_: lambda _: json.dumps({"paper_digest": {"method": "test"}})
    )

    def run(job_id, work):
        research_api._update_job(job_id, status="done", result=work(lambda *_: None))

    monkeypatch.setattr(research_api, "_run_in_background", run)
    original = "start\n\n" + "x" * 80_001 + "\n\nend"
    created = research_api.start_digest({"text": original, "request_id": "long-material-123"})
    result = research_api.job_status(created["job_id"])["result"]
    assert result["source"]["text"] == original
    assert result["material_source"]["sha256"] == hashlib.sha256(original.encode()).hexdigest()
    assert result["material_source"]["truncated"]
