"""
Internationalization (i18n) support for FOS (Future of Society).

Provides translation utilities for backend code using JSON-based locale files.
Supports English and Chinese languages with fallback to English.

Contains: T() translation function, get_locale() language detector
"""

import contextvars
import json
from pathlib import Path
from typing import Any, Dict, Optional

# Supported languages
SUPPORTED_LANGUAGES = ['en', 'zh']
DEFAULT_LANGUAGE = 'en'

# Request-scoped locale via contextvars.
# Note: values are NOT propagated into asyncio.to_thread / ThreadPoolExecutor.
# Code calling T() from a thread worker must pass locale= explicitly.
_request_locale: contextvars.ContextVar[str] = contextvars.ContextVar(
    '_request_locale', default=DEFAULT_LANGUAGE
)

# Cache for loaded translations
_translation_cache: Dict[str, Dict[str, Any]] = {}


def _get_locale_file(locale: str) -> Path:
    """Get the path to the locale file for the given language."""
    module_dir = Path(__file__).parent
    return module_dir / 'locales' / f'{locale}.json'


def _load_translations(locale: str) -> Dict[str, Any]:
    """
    Load translations from JSON file for the specified locale.

    Args:
        locale: Language code (e.g., 'en', 'zh')

    Returns:
        Dictionary of translation key-value pairs
    """
    if locale in _translation_cache:
        return _translation_cache[locale]

    locale_file = _get_locale_file(locale)

    if locale_file.exists():
        try:
            with open(locale_file, 'r', encoding='utf-8') as f:
                translations = json.load(f)
                _translation_cache[locale] = translations
                return translations
        except (json.JSONDecodeError, IOError):
            pass

    # Return empty dict if file doesn't exist or can't be loaded
    _translation_cache[locale] = {}
    return _translation_cache[locale]


def _get_nested_key(data: Dict[str, Any], key: str) -> Any:
    """
    Get a value from nested dictionary using dot notation key.

    Args:
        data: Dictionary to search
        key: Dot notation key (e.g., 'error.simulation.not_found')

    Returns:
        Value at the key path or None if not found.
        Can return str, list, dict, or other JSON-compatible types.
    """
    keys = key.split('.')
    value = data

    for k in keys:
        if isinstance(value, dict):
            value = value.get(k)
            if value is None:
                return None
        else:
            return None

    return value


def get_locale(locale: Optional[str] = None) -> str:
    """
    Get the current locale from explicit param, request context, or default.

    Priority: explicit param > contextvar > DEFAULT_LANGUAGE.

    Args:
        locale: Language code (e.g., 'en', 'zh')

    Returns:
        Valid language code from SUPPORTED_LANGUAGES
    """
    if locale and locale in SUPPORTED_LANGUAGES:
        return locale
    ctx_locale = _request_locale.get()
    if ctx_locale in SUPPORTED_LANGUAGES:
        return ctx_locale
    return DEFAULT_LANGUAGE


def T(key: str, locale: Optional[str] = None, **kwargs: Any) -> Any:
    """
    Translate a key using the specified or default locale.

    Usage:
        T('error.simulation.not_found')
        T('agent.joined', locale='zh', name=agent_name)
        T('welcome.user', name=user_name, count=user_count)
        roles = T('prompts.archetype.fallback_roles')  # Returns list

    Args:
        key: Translation key (dot.notation for nested keys)
        locale: Language code (uses DEFAULT_LANGUAGE if not specified)
        **kwargs: Variables for string interpolation (only for string values)

    Returns:
        Translated value (str, list, dict, or other JSON-compatible type)
        String values have variables interpolated.
    """
    # Determine which locale to use
    target_locale = get_locale(locale)

    # Load translations for the target locale
    translations = _load_translations(target_locale)

    # Try to get the translation value
    value = _get_nested_key(translations, key)

    # Fallback to key if translation not found
    if value is None:
        value = key

    # For string values, interpolate variables if provided
    if isinstance(value, str) and kwargs:
        try:
            value = value.format(**kwargs)
        except (KeyError, ValueError, AttributeError):
            # If formatting fails, return the key with variables appended
            vars_str = ', '.join(f'{k}={v}' for k, v in kwargs.items())
            return f"{key} ({vars_str})"

    # For non-string values (lists, dicts, etc.), return directly
    return value


def set_request_locale(locale: str) -> None:
    """
    Set the locale for the current async request context.

    Args:
        locale: Language code to use
    """
    if locale in SUPPORTED_LANGUAGES:
        _request_locale.set(locale)
    else:
        _request_locale.set(DEFAULT_LANGUAGE)


def get_request_locale() -> str:
    """Get the current request context locale."""
    return _request_locale.get()


# Export main translation function
__all__ = ['T', 'get_locale', 'get_request_locale', 'set_request_locale', 'SUPPORTED_LANGUAGES', 'DEFAULT_LANGUAGE']
