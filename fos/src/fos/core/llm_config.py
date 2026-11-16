"""LLM provider configuration structures."""

from dataclasses import dataclass


@dataclass
class LLMConfig:
    dialect: str
    api_key: str = ""
    model: str = ""
    base_url: str | None = None
    temperature: float = 0.7
    top_p: float = 1.0
    frequency_penalty: float = 0.0
    presence_penalty: float = 0.0
    max_tokens: int = 1024
    # 是否支持 vision（多模态）能力；默认为 False，调用侧根据模型名或显式配置开启
    supports_vision: bool = False


def guess_supports_vision(model: str | None) -> bool:
    """Best-effort 判断模型是否支持多模态 vision 能力。

    规则尽量宽松，仅做便捷推断，不作为严格校验。
    """
    if not model:
        return False
    m = model.lower()
    return any(
        token in m
        for token in (
            "vision",
            "gpt-4o",
            "gpt-4-vision",
            "gpt-4.1",
            "gemini-pro-vision",
            "gemini-1.5",
            "gemini-2",
            "llava",
            "llama-3.2-vision",
            "llama-3.1-vision",
            "llama3.2",
            "llama3.1",
            "qwen2-vl",
            "qwen-vl",
            "minicpm-v",
            "moondream",
            "pixtral",
        )
    )
