"""
Test that RegisterPage.tsx translation keys exist in both locale files.

Extracts every t("...") call from the registration page component
and verifies each key is present in en.json and zh.json.

Contains: test_register_page_keys_in_en, test_register_page_keys_in_zh
"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REGISTER_PAGE = ROOT / "frontend" / "pages" / "RegisterPage.tsx"
EN_LOCALE = ROOT / "frontend" / "locales" / "en.json"
ZH_LOCALE = ROOT / "frontend" / "locales" / "zh.json"


def _flatten_keys(data: dict, prefix: str = "") -> set[str]:
    """Recursively collect all leaf key paths from a nested dict."""
    keys: set[str] = set()
    for key, value in data.items():
        full_key = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            keys.update(_flatten_keys(value, full_key))
        else:
            keys.add(full_key)
    return keys


def _extract_t_keys(source: str) -> list[str]:
    """Extract all t('...') / t("...") keys from TypeScript source."""
    return re.findall(r'\bt\(\s*["\']([^"\']+)["\']', source)


def _register_page_keys() -> list[str]:
    """Return deduplicated t() keys used in RegisterPage.tsx."""
    source = REGISTER_PAGE.read_text(encoding="utf-8")
    keys = _extract_t_keys(source)
    return sorted(set(keys))


def _locale_keys(path: Path) -> set[str]:
    """Flatten a locale JSON file into a set of dotted key paths."""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return _flatten_keys(data)


EXPECTED_REGISTER_KEYS = {
    "auth.register.title",
    "auth.register.organization",
    "auth.register.email",
    "auth.register.username",
    "auth.register.fullName",
    "auth.register.phone",
    "auth.register.countryCode",
    "auth.register.phonePlaceholder",
    "auth.register.phoneHint",
    "auth.register.invalidPhone",
    "auth.register.invalidPhoneTitle",
    "auth.register.password",
    "auth.register.submit",
    "auth.register.success",
    "auth.register.failed",
    "auth.register.have",
    "auth.register.signin",
}


def test_register_page_keys_in_en():
    """Every t() key in RegisterPage.tsx must exist in en.json."""
    locale_keys = _locale_keys(EN_LOCALE)
    used_keys = _register_page_keys()
    missing = [k for k in used_keys if k not in locale_keys]
    assert not missing, (
        f"{len(missing)} key(s) from RegisterPage.tsx missing in en.json:\n"
        + "\n".join(f"  {k}" for k in missing)
    )


def test_register_page_keys_in_zh():
    """Every t() key in RegisterPage.tsx must exist in zh.json."""
    locale_keys = _locale_keys(ZH_LOCALE)
    used_keys = _register_page_keys()
    missing = [k for k in used_keys if k not in locale_keys]
    assert not missing, (
        f"{len(missing)} key(s) from RegisterPage.tsx missing in zh.json:\n"
        + "\n".join(f"  {k}" for k in missing)
    )


def test_register_page_uses_all_expected_keys():
    """RegisterPage.tsx must use every key we planned for the register block."""
    used_keys = set(_register_page_keys())
    missing = EXPECTED_REGISTER_KEYS - used_keys
    extra = used_keys - EXPECTED_REGISTER_KEYS
    errors: list[str] = []
    if missing:
        errors.append(f"Planned keys not used in RegisterPage.tsx: {sorted(missing)}")
    if extra:
        errors.append(f"Extra keys found in RegisterPage.tsx: {sorted(extra)}")
    assert not errors, "\n".join(errors)
