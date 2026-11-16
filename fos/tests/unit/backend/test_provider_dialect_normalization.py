"""
This file checks how the provider type and base URL get turned into a dialect.

The dialect decides which code path talks to the model. Getting this wrong sends
a request shaped for the wrong server (for example, sending an Ollama-style
/api/tags request to LM Studio), so it must be correct.

Each test verifies one thing:
- test_explicit_ollama_provider_stays_ollama: a provider marked "ollama" stays ollama.
- test_openai_with_ollama_port_becomes_ollama: "openai" on port 11434 is treated as ollama.
- test_openai_with_ollama_port_strips_v1_suffix: the /v1 suffix is removed for ollama.
- test_openai_with_ollama_port_on_loopback_ip_becomes_ollama: 127.0.0.1:11434 is ollama too.
- test_openai_with_lm_studio_port_stays_openai: "openai" on a non-11434 localhost port
  (like LM Studio on 1235) must stay the openai dialect, NOT become ollama.
- test_openai_with_lm_studio_port_keeps_v1_suffix: the /v1 suffix must be preserved for
  LM Studio, because the OpenAI client needs it.
- test_lmstudio_provider_type_stays_openai: an explicit "lmstudio" type stays openai.
"""

from __future__ import annotations

from fos.backend.api.routes.providers import _normalize_dialect


def test_explicit_ollama_provider_stays_ollama() -> None:
    dialect, _ = _normalize_dialect("ollama", "http://localhost:11434")
    assert dialect == "ollama"


def test_openai_with_ollama_port_becomes_ollama() -> None:
    dialect, base_url = _normalize_dialect("openai", "http://localhost:11434")
    assert dialect == "ollama"
    assert base_url == "http://localhost:11434"


def test_openai_with_ollama_port_strips_v1_suffix() -> None:
    dialect, base_url = _normalize_dialect("openai", "http://localhost:11434/v1")
    assert dialect == "ollama"
    assert base_url == "http://localhost:11434"


def test_openai_with_ollama_port_on_loopback_ip_becomes_ollama() -> None:
    dialect, base_url = _normalize_dialect("openai", "http://127.0.0.1:11434")
    assert dialect == "ollama"
    assert base_url == "http://127.0.0.1:11434"


def test_openai_with_lm_studio_port_stays_openai() -> None:
    # LM Studio runs on localhost but speaks the OpenAI dialect, not Ollama.
    # Only port 11434 is a reliable Ollama signal.
    dialect, _ = _normalize_dialect("openai", "http://localhost:1235/v1")
    assert dialect == "openai"


def test_openai_with_lm_studio_port_keeps_v1_suffix() -> None:
    # The OpenAI client appends /chat/completions to the base URL, so the /v1
    # suffix must be preserved. Stripping it would break the request.
    _, base_url = _normalize_dialect("openai", "http://localhost:1235/v1")
    assert base_url == "http://localhost:1235/v1"
    assert base_url.endswith("/v1")


def test_lmstudio_provider_type_stays_openai() -> None:
    dialect, base_url = _normalize_dialect("lmstudio", "http://localhost:1235/v1")
    assert dialect == "openai"
    assert base_url == "http://localhost:1235/v1"
