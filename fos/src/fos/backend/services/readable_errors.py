"""User-readable runtime error formatting."""

from __future__ import annotations


_ERROR_HINTS: tuple[tuple[str, str, str], ...] = (
    (
        "gaworld.error.path_not_set",
        "GAWorld path is not configured. Set GAWORLD_PATH on the server.",
        "GAWorld 路径未配置，请在服务器设置 GAWORLD_PATH。",
    ),
    (
        "gaworld.error.script_not_found",
        "GAWorld launch script was not found under the configured path.",
        "在配置的路径下没有找到 GAWorld 启动脚本。",
    ),
    (
        "provider_not_configured",
        "No LLM provider is configured. Add or activate a provider first.",
        "未配置 LLM 提供商，请先添加或启用一个提供商。",
    ),
    (
        "provider_model_required",
        "The selected LLM provider has no model configured.",
        "当前 LLM 提供商没有配置模型。",
    ),
    (
        "provider_api_key_required",
        "The selected provider requires an API key.",
        "当前提供商需要配置 API Key。",
    ),
    (
        "provider_invalid",
        "The selected provider type is not supported.",
        "当前提供商类型不受支持。",
    ),
    (
        "model not found",
        "The configured model was not found by the provider.",
        "提供商找不到当前配置的模型。",
    ),
)


def make_readable_error(message: object, locale: str = "en") -> dict[str, str]:
    """Return raw and human-readable versions of an error message."""
    raw = str(message or "").strip()
    lower = raw.lower()
    is_zh = str(locale or "").lower().startswith("zh")
    readable = raw
    category = "runtime"
    for marker, en_text, zh_text in _ERROR_HINTS:
        if marker.lower() in lower:
            readable = zh_text if is_zh else en_text
            if "gaworld" in marker:
                category = "path"
            elif "provider" in marker or "model" in marker:
                category = "provider"
            break
    return {
        "raw": raw,
        "message": readable,
        "category": category,
    }
