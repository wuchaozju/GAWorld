"""
Test that backend locale files have matching keys between English and Chinese.

Ensures that en.json and zh.json stay in sync as new translations are added.
If a key exists in one file but not the other, the test fails with details.

Contains: test_backend_locale_parity
"""
import json
from pathlib import Path


def _get_all_keys(data: dict, prefix: str = "") -> set:
    """Recursively collect all leaf key paths from a nested dict."""
    keys = set()
    for key, value in data.items():
        full_key = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            keys.update(_get_all_keys(value, full_key))
        else:
            keys.add(full_key)
    return keys


def test_backend_locale_parity():
    """en.json and zh.json must have exactly the same keys."""
    locales_dir = Path(__file__).parent.parent / "src" / "fos" / "locales"
    with open(locales_dir / "en.json", encoding="utf-8") as f:
        en = json.load(f)
    with open(locales_dir / "zh.json", encoding="utf-8") as f:
        zh = json.load(f)

    en_keys = _get_all_keys(en)
    zh_keys = _get_all_keys(zh)

    missing_in_zh = en_keys - zh_keys
    missing_in_en = zh_keys - en_keys

    assert not missing_in_zh, (
        "Keys in en.json missing from zh.json:\n"
        + "\n".join(sorted(missing_in_zh))
    )
    assert not missing_in_en, (
        "Keys in zh.json missing from en.json:\n"
        + "\n".join(sorted(missing_in_en))
    )
