"""AI Scientist backend service facade.

Keep this package-level surface stable for existing route and test imports.
New code should prefer the smaller modules in this package.
"""

from .core import (
    build_llm_analysis_scaffold,
    build_semantic_schema,
    build_source_outline,
    collect_analysis_quality_issues,
    heuristic_analysis,
    localize_analysis_output,
    merge_analysis,
    normalize_llm_analysis_output,
    suggest_templates,
)
from .json_repair import parse_llm_json, repair_llm_json
from .types import TemplateSuggestion

__all__ = [
    "TemplateSuggestion",
    "build_llm_analysis_scaffold",
    "build_semantic_schema",
    "build_source_outline",
    "collect_analysis_quality_issues",
    "heuristic_analysis",
    "localize_analysis_output",
    "merge_analysis",
    "normalize_llm_analysis_output",
    "parse_llm_json",
    "repair_llm_json",
    "suggest_templates",
]
