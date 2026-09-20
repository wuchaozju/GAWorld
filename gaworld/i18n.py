"""GAWorld i18n — lightweight Python internationalization module.

Reads the same JSON locale files as the dashboard JS.
Provides ``t()`` for Chinese (default) and ``eng()`` for English lookup.
"""

from __future__ import annotations

import json
import os
from typing import Any

_LOCALE_DIR = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "site", "dashboard", "locales")
)


def _load_locale(locale: str) -> dict[str, str]:
    path = os.path.join(_LOCALE_DIR, f"{locale}.json")
    if not os.path.isfile(path):
        return {}
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


_zh: dict[str, str] | None = None
_en: dict[str, str] | None = None


def _get_zh() -> dict[str, str]:
    global _zh
    if _zh is None:
        _zh = _load_locale("zh-CN")
    return _zh


def _get_en() -> dict[str, str]:
    global _en
    if _en is None:
        _en = _load_locale("en")
    return _en


def t(key: str) -> str:
    """Translate *key* to Chinese. Falls back to English, then the key itself."""
    data = _get_zh()
    if key in data:
        return data[key]
    fallback = _get_en()
    return fallback.get(key, key)


def eng(key: str) -> str:
    """Translate *key* to English. Falls back to the key itself."""
    data = _get_en()
    return data.get(key, key)


def available_locales() -> list[dict[str, str]]:
    """Return a list of ``{"code": ..., "label": ...}`` for discovered locale files."""
    results: list[dict[str, str]] = []
    if not os.path.isdir(_LOCALE_DIR):
        return results
    for name in sorted(os.listdir(_LOCALE_DIR)):
        if name.endswith(".json"):
            code = name[: -len(".json")]
            label = code.replace("-", " ").title()
            results.append({"code": code, "label": label})
    return results


def reload() -> None:
    """Clear cached locale data so the next call re-reads from disk."""
    global _zh, _en
    _zh = None
    _en = None
