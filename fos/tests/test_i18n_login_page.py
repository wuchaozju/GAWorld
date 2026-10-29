"""
Test that LoginPage.tsx translation keys exist in both locale files.

Extracts every t("...") call from the login page component
and verifies each key is present in en.json and zh.json.

Contains: test_login_page_keys_in_en, test_login_page_keys_in_zh,
          test_login_page_uses_all_expected_keys
"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOGIN_PAGE = ROOT / "frontend" / "pages" / "LoginPage.tsx"
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


def _login_page_keys() -> list[str]:
    """Return deduplicated t() keys used in LoginPage.tsx."""
    source = LOGIN_PAGE.read_text(encoding="utf-8")
    keys = _extract_t_keys(source)
    return sorted(set(keys))


def _locale_keys(path: Path) -> set[str]:
    """Flatten a locale JSON file into a set of dotted key paths."""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return _flatten_keys(data)


EXPECTED_LOGIN_KEYS = {
    "auth.login.badge",
    "auth.login.welcome",
    "auth.login.subtitle",
    "auth.login.email",
    "auth.login.emailPlaceholder",
    "auth.login.password",
    "auth.login.passwordPlaceholder",
    "auth.login.invalid",
    "auth.login.noAccount",
    "auth.login.create",
    "auth.login.signin",
}


def test_login_page_keys_in_en():
    """Every t() key in LoginPage.tsx must exist in en.json."""
    locale_keys = _locale_keys(EN_LOCALE)
    used_keys = _login_page_keys()
    missing = [k for k in used_keys if k not in locale_keys]
    assert not missing, (
        f"{len(missing)} key(s) from LoginPage.tsx missing in en.json:\n"
        + "\n".join(f"  {k}" for k in missing)
    )


def test_login_page_keys_in_zh():
    """Every t() key in LoginPage.tsx must exist in zh.json."""
    locale_keys = _locale_keys(ZH_LOCALE)
    used_keys = _login_page_keys()
    missing = [k for k in used_keys if k not in locale_keys]
    assert not missing, (
        f"{len(missing)} key(s) from LoginPage.tsx missing in zh.json:\n"
        + "\n".join(f"  {k}" for k in missing)
    )


def test_login_page_uses_all_expected_keys():
    """LoginPage.tsx must use every key we planned for the login block."""
    used_keys = set(_login_page_keys())
    missing = EXPECTED_LOGIN_KEYS - used_keys
    extra = used_keys - EXPECTED_LOGIN_KEYS
    errors: list[str] = []
    if missing:
        errors.append(f"Planned keys not used in LoginPage.tsx: {sorted(missing)}")
    if extra:
        errors.append(f"Extra keys found in LoginPage.tsx: {sorted(extra)}")
    assert not errors, "\n".join(errors)
