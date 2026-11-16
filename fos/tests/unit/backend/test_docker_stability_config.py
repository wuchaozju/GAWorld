"""
This file checks the Docker settings that keep the demo server steady.

Each test verifies one thing:
- test_entrypoint_uses_configurable_single_worker_default checks the app starts with one worker unless changed.
- test_compose_healthcheck_uses_readiness_endpoint checks Docker watches the useful health endpoint.
- test_compose_uses_conservative_llm_defaults checks presentation defaults avoid overloading Ollama.
"""

from __future__ import annotations

from pathlib import Path


def test_entrypoint_uses_configurable_single_worker_default() -> None:
    entrypoint = Path("docker/backend-entrypoint.sh").read_text(encoding="utf-8")

    assert "FOS_UVICORN_WORKERS:-1" in entrypoint
    assert "--workers ${FOS_UVICORN_WORKERS:-1}" in entrypoint


def test_compose_healthcheck_uses_readiness_endpoint() -> None:
    compose = Path("docker-compose.yml").read_text(encoding="utf-8")

    assert "/api/health/ready" in compose


def test_compose_uses_conservative_llm_defaults() -> None:
    compose = Path("docker-compose.yml").read_text(encoding="utf-8")

    assert "LLM_MAX_CONCURRENT_PER_CLIENT:-2" in compose
    assert "FOS_LLM_CONCURRENCY:-2" in compose
    assert 'OLLAMA_NUM_PARALLEL: "${OLLAMA_NUM_PARALLEL:-2}"' in compose
