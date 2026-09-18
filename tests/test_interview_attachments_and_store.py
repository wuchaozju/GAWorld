"""Attachment resolution and session persistence.

No network: the URL fetcher is stubbed. No model: nothing here calls one.
"""

from __future__ import annotations

import base64
import json

import pytest

from gaworld.interview import attachments as att
from gaworld.interview import store
from gaworld.interview.schema import Attachment, InterviewSpecError, Question, Respondent

PNG = base64.b64encode(b"fake-png-bytes").decode("ascii")


# ---------------------------------------------------------------------------
# Images
# ---------------------------------------------------------------------------


def test_data_url_image_is_decoded_for_the_provider():
    material = att.resolve_material(
        [Attachment(kind="image", value=f"data:image/jpeg;base64,{PNG}", caption="工地")],
        vision=True,
    )
    item = material.items[0]
    assert item.has_image
    assert item.media_type == "image/jpeg"
    assert material.images == [{"media_type": "image/jpeg", "data": PNG}]
    assert material.degradation == ""


def test_local_file_image_is_read_in_the_parent(tmp_path):
    path = tmp_path / "shot.png"
    path.write_bytes(b"fake-png-bytes")
    material = att.resolve_material([Attachment(kind="image", value=str(path))], vision=True)
    assert material.items[0].data == PNG


def test_image_degrades_to_its_caption_without_vision():
    material = att.resolve_material(
        [Attachment(kind="image", value=f"data:image/png;base64,{PNG}", caption="一张工地照片")],
        vision=False,
    )
    item = material.items[0]
    assert not item.has_image
    assert item.text == "一张工地照片"
    assert "不支持图片" in item.note
    assert material.images == []
    assert "不支持图片" in material.degradation


def test_missing_caption_is_called_out_in_the_degradation_note():
    material = att.resolve_material(
        [Attachment(kind="image", value=f"data:image/png;base64,{PNG}")], vision=False
    )
    assert "未提供图片说明" in material.items[0].note


def test_invalid_base64_is_reported_rather_than_sent():
    material = att.resolve_material(
        [Attachment(kind="image", value="data:image/png;base64,!!!not-base64!!!")], vision=True
    )
    assert not material.items[0].has_image
    assert "base64" in material.items[0].note


def test_oversized_image_is_rejected(monkeypatch):
    monkeypatch.setattr(att, "IMAGE_MAX_BYTES", 4)
    material = att.resolve_material(
        [Attachment(kind="image", value=f"data:image/png;base64,{PNG}")], vision=True
    )
    assert "过大" in material.items[0].note


# ---------------------------------------------------------------------------
# URLs
# ---------------------------------------------------------------------------


def test_url_is_reduced_to_article_text(monkeypatch):
    import gaworld.io.web_scrape as scrape

    monkeypatch.setattr(
        scrape, "fetch_news_excerpt", lambda *a, **k: ("地铁延伸线将于明年开工。", "地铁新闻")
    )
    material = att.resolve_material([Attachment(kind="url", value="http://example.com/a")], vision=False)
    item = material.items[0]
    assert "地铁新闻" in item.text
    assert "明年开工" in item.text
    assert item.note == ""


def test_dead_url_falls_back_to_the_caption_and_says_so(monkeypatch):
    import gaworld.io.web_scrape as scrape

    monkeypatch.setattr(scrape, "fetch_news_excerpt", lambda *a, **k: ("", ""))
    material = att.resolve_material(
        [Attachment(kind="url", value="http://example.com/gone", caption="一条地铁新闻")],
        vision=False,
    )
    assert material.items[0].text == "一条地铁新闻"
    assert "抓取失败" in material.items[0].note


def test_fetch_exception_does_not_abort_the_question(monkeypatch):
    import gaworld.io.web_scrape as scrape

    def boom(*args, **kwargs):
        raise RuntimeError("DNS 挂了")

    monkeypatch.setattr(scrape, "fetch_news_excerpt", boom)
    material = att.resolve_material([Attachment(kind="url", value="http://example.com/x")], vision=False)
    assert "抓取失败" in material.items[0].note


def test_material_round_trips_through_serialization_with_image_data():
    material = att.resolve_material(
        [Attachment(kind="image", value=f"data:image/png;base64,{PNG}")], vision=True
    )
    restored = att.material_from_dict(att.material_to_dict(material))
    assert restored.images == material.images


def test_attachment_rejects_an_unknown_kind():
    with pytest.raises(InterviewSpecError):
        Attachment.from_dict({"kind": "video", "value": "x"})


def test_attachment_rejects_empty_content():
    with pytest.raises(InterviewSpecError):
        Attachment.from_dict({"kind": "url", "value": "   "})


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------


@pytest.fixture
def isolated_root(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "PROJECT_ROOT", tmp_path)
    return tmp_path


def _session(session_id="20260101-000000-abcdef"):
    return {
        "id": session_id,
        "title": "通勤调查",
        "context": "",
        "created_at": 1.0,
        "questions": [Question(id="q1", text="q", round=1).to_dict()],
        "respondents": [
            Respondent(kind="agent", city="甲", ref="1", label="张三").to_dict(),
            Respondent(kind="agent", city="乙", ref="2", label="李四").to_dict(),
        ],
        "transcripts": {},
        "cities": ["甲", "乙"],
        "rounds": [],
    }


def test_session_round_trips(isolated_root):
    saved = store.save_session(_session())
    assert saved.exists()
    loaded = store.load_session("20260101-000000-abcdef")
    assert loaded["title"] == "通勤调查"


def test_unknown_session_is_none_not_an_error(isolated_root):
    assert store.load_session("20260101-000000-zzzzzz") is None


@pytest.mark.parametrize("bad", ["../../etc", "a/b", "..", "x", ""])
def test_session_id_path_traversal_is_refused(isolated_root, bad):
    with pytest.raises(ValueError):
        store.session_dir(bad)


def test_transcripts_are_returned_in_respondent_order(isolated_root):
    session = _session()
    # Stored out of order on purpose: the document must follow the picker.
    session["transcripts"] = {
        "agent:乙:2": {"respondent": session["respondents"][1], "answers": [], "error": ""},
        "agent:甲:1": {"respondent": session["respondents"][0], "answers": [], "error": ""},
    }
    store.save_session(session)
    loaded = store.load_session(session["id"])
    order = [t.respondent.ref for t in store.session_transcripts(loaded)]
    assert order == ["1", "2"]


def test_report_is_saved_and_read_back(isolated_root):
    store.save_session(_session())
    store.save_report("20260101-000000-abcdef", "# 报告\n")
    assert store.load_report("20260101-000000-abcdef") == "# 报告\n"


def test_list_sessions_is_newest_first(isolated_root):
    first = _session("20260101-000000-aaaaaa")
    second = _session("20260102-000000-bbbbbb")
    store.save_session(first)
    store.save_session(second)
    # save_session stamps updated_at itself, so force a known order.
    path = store.session_dir("20260101-000000-aaaaaa") / "session.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["updated_at"] = 1.0
    path.write_text(json.dumps(payload), encoding="utf-8")

    rows = store.list_sessions()
    assert rows[0]["id"] == "20260102-000000-bbbbbb"
    assert rows[0]["respondents"] == 2


def test_delete_session_removes_the_directory(isolated_root):
    store.save_session(_session())
    assert store.delete_session("20260101-000000-abcdef") is True
    assert store.load_session("20260101-000000-abcdef") is None
    assert store.delete_session("20260101-000000-abcdef") is False
