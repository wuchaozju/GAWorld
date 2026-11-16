"""Shared AI Scientist service types."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class TemplateSuggestion:
    id: str
    name: str
    category: str
    description: str
    score: float
    reason: str
