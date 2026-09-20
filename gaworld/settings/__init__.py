"""Mutable legacy settings assembled from focused configuration modules."""

from __future__ import annotations

from typing import Any

from .defaults import build_default_config
from .overrides import apply_runtime_overrides


def build_config() -> dict[str, Any]:
    """Build the active legacy CONFIG dict with runtime overrides applied."""
    return apply_runtime_overrides(build_default_config())


CONFIG = build_config()


__all__ = ["CONFIG", "build_config", "build_default_config"]
