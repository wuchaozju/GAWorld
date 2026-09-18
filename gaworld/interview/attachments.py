"""Turn a question's material into something a prompt can carry.

Two kinds, two fates:

``url``    fetched once per session and reduced to article text by the
           existing news extractor. Every respondent then reads the *same*
           extract — refetching per respondent would put N requests on
           somebody's server and, worse, let respondent #1 and respondent
           #40 answer about different versions of the page.

``image``  base64 for the provider's image block when the routed model can
           see, and its caption otherwise. The degradation is recorded on
           the answer rather than smoothed over: "这张图说明了什么" answered
           from a one-line caption is a different measurement from the same
           question answered from the picture, and only one of them is what
           the user thinks they asked.

Resolution happens once, in the parent, before the fan-out.
"""

from __future__ import annotations

import base64
import binascii
import os
import re
from dataclasses import dataclass, field
from typing import Any

from gaworld.interview.schema import Attachment
from gaworld.logging_setup import get_logger

_LOG = get_logger("gaworld.interview.attachments")

#: Characters of extracted page text kept per URL. Long enough for a news
#: article's substance, short enough that five attachments do not crowd the
#: persona and the question out of a small model's context.
URL_MAX_CHARS = 1800

#: Bytes of decoded image data accepted. Providers reject much larger
#: payloads anyway, and the panel downscales before upload.
IMAGE_MAX_BYTES = 5 * 1024 * 1024

_DATA_URL_RE = re.compile(r"^data:(?P<media>[\w.+/-]+)?;base64,(?P<data>.*)$", re.DOTALL)

_MEDIA_BY_EXT = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
}


@dataclass
class ResolvedAttachment:
    """An attachment after fetching / decoding, ready for a prompt."""

    kind: str
    caption: str = ""
    #: Text to put in the prompt: the page extract, or the image caption.
    text: str = ""
    #: Source label shown in the prompt and the report ("图片" / the URL).
    source: str = ""
    #: Image payload for the provider, when usable.
    media_type: str = ""
    data: str = ""
    #: Why this attachment is less than it should be, if it is.
    note: str = ""

    @property
    def has_image(self) -> bool:
        return bool(self.data)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "caption": self.caption,
            "text": self.text,
            "source": self.source,
            "media_type": self.media_type,
            "has_image": self.has_image,
            "note": self.note,
        }

    @classmethod
    def from_dict(cls, payload: Any) -> ResolvedAttachment:
        payload = payload if isinstance(payload, dict) else {}
        return cls(
            kind=str(payload.get("kind") or ""),
            caption=str(payload.get("caption") or ""),
            text=str(payload.get("text") or ""),
            source=str(payload.get("source") or ""),
            media_type=str(payload.get("media_type") or ""),
            data=str(payload.get("data") or ""),
            note=str(payload.get("note") or ""),
        )


@dataclass
class ResolvedMaterial:
    """All resolved attachments for one question."""

    items: list[ResolvedAttachment] = field(default_factory=list)

    @property
    def images(self) -> list[dict[str, str]]:
        """Provider-shaped image list for :func:`gaworld.llm.call_llm`."""
        return [{"media_type": item.media_type, "data": item.data} for item in self.items if item.has_image]

    @property
    def degradation(self) -> str:
        """One line naming everything that did not arrive intact, or ``""``."""
        notes = [item.note for item in self.items if item.note]
        return "；".join(notes)

    def to_dict(self) -> dict[str, Any]:
        return {"items": [item.to_dict() for item in self.items]}


def _decode_image(value: str) -> tuple[str, str, str]:
    """Return ``(media_type, base64_data, note)`` for an image attachment.

    Accepts a data URL, bare base64, or a path to a local file. A local path
    is read here rather than passed along because the child process running
    a different city may not share the parent's working directory.
    """
    raw = value.strip()
    match = _DATA_URL_RE.match(raw)
    if match:
        media_type = match.group("media") or "image/png"
        payload = re.sub(r"\s+", "", match.group("data") or "")
    elif os.path.isfile(raw):
        ext = os.path.splitext(raw)[1].lower()
        media_type = _MEDIA_BY_EXT.get(ext, "image/png")
        try:
            with open(raw, "rb") as handle:
                payload = base64.b64encode(handle.read()).decode("ascii")
        except OSError as exc:
            return "", "", f"图片读取失败（{exc.strerror or exc}）"
    else:
        media_type = "image/png"
        payload = re.sub(r"\s+", "", raw)

    if not payload:
        return "", "", "图片内容为空"
    try:
        size = len(base64.b64decode(payload, validate=True))
    except (binascii.Error, ValueError):
        return "", "", "图片不是有效的 base64"
    if size > IMAGE_MAX_BYTES:
        return "", "", f"图片过大（{size // 1024}KB，上限 {IMAGE_MAX_BYTES // 1024}KB）"
    return media_type, payload, ""


def _resolve_url(attachment: Attachment) -> ResolvedAttachment:
    from gaworld.io.web_scrape import fetch_news_excerpt

    url = attachment.value
    try:
        text, title = fetch_news_excerpt(url, max_chars=URL_MAX_CHARS, return_title=True)
    except Exception as exc:  # the guarded session can still raise on odd URLs
        _LOG.warning("interview attachment fetch failed for %s: %s", url, exc)
        text, title = "", ""
    resolved = ResolvedAttachment(kind="url", caption=attachment.caption, source=url)
    if text:
        resolved.text = f"{title}\n{text}".strip() if title else text
        return resolved
    # A dead link is not a reason to abandon the question — the caption may
    # carry enough. But the answer must not read as if the page was seen.
    resolved.text = attachment.caption
    resolved.note = f"网址抓取失败或无正文（{url}）"
    return resolved


def _resolve_image(attachment: Attachment, *, vision: bool) -> ResolvedAttachment:
    resolved = ResolvedAttachment(kind="image", caption=attachment.caption, source="图片")
    media_type, data, note = _decode_image(attachment.value)
    if not data:
        resolved.text = attachment.caption
        resolved.note = note or "图片无法解析"
        return resolved
    if not vision:
        resolved.text = attachment.caption
        resolved.note = (
            "当前模型不支持图片输入，已改用图片说明文字"
            if attachment.caption
            else "当前模型不支持图片输入，且未提供图片说明"
        )
        return resolved
    resolved.media_type = media_type
    resolved.data = data
    resolved.text = attachment.caption
    return resolved


def resolve_material(attachments: list[Attachment], *, vision: bool) -> ResolvedMaterial:
    """Fetch and decode ``attachments`` once, for all respondents.

    ``vision`` is the answer from :func:`gaworld.llm.provider_supports_images`
    for the provider this session routes to — passed in rather than probed
    here so the same resolution can be reused by a child process that has a
    different config loaded.
    """
    items: list[ResolvedAttachment] = []
    for attachment in attachments or []:
        if attachment.kind == "url":
            items.append(_resolve_url(attachment))
        elif attachment.kind == "image":
            items.append(_resolve_image(attachment, vision=vision))
    return ResolvedMaterial(items=items)


def material_from_dict(payload: Any) -> ResolvedMaterial:
    """Rebuild material from its serialized form (parent → child process)."""
    payload = payload if isinstance(payload, dict) else {}
    return ResolvedMaterial(
        items=[ResolvedAttachment.from_dict(item) for item in (payload.get("items") or [])]
    )


def material_to_dict(material: ResolvedMaterial) -> dict[str, Any]:
    """Serialize material *including* image payloads, for the child process."""
    return {"items": [{**item.to_dict(), "data": item.data} for item in material.items]}


__all__ = [
    "IMAGE_MAX_BYTES",
    "URL_MAX_CHARS",
    "ResolvedAttachment",
    "ResolvedMaterial",
    "material_from_dict",
    "material_to_dict",
    "resolve_material",
]
