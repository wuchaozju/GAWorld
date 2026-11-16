"""This file exposes backend endpoints for the AI scientist experiment setup flow.

Each function has a direct purpose:
- _select_provider_optional: picks a user model config if available.
- prompt builders: run the multi-pass LLM extraction and repair flow.
- analyze_research_text: returns structured scene, settings, actions, agents, and template suggestions.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Literal

from litestar import Router, post
from litestar.connection import Request
from litestar.exceptions import HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from fos.i18n import T

from fos.core.llm import create_llm_client
from fos.core.llm_config import LLMConfig, guess_supports_vision
from fos.core.scenarios import get_all_scenarios

from ...core.database import get_session
from ...dependencies import extract_bearer_token, resolve_current_user
from ...models.user import ProviderConfig
from ...services.ai_scientist.draft_analysis import (
    collect_analysis_quality_issues,
    heuristic_analysis,
    normalize_llm_analysis_output,
)
from ...services.ai_scientist.json_repair import (
    parse_llm_json,
    repair_llm_json,
)
from ...services.ai_scientist.localization import (
    localize_analysis_output,
)
from ...services.ai_scientist.semantic_schema import (
    build_llm_analysis_scaffold,
)
from ...services.ai_scientist.template_matching import (
    TemplateSuggestion,
)
from ...services.default_providers import get_default_ollama_base_url
from ...services.provider_dialect import normalize_provider_runtime
from ...services.runtime_tasks import RUNTIME_TASKS

logger = logging.getLogger(__name__)


class AnalyzeRequest(BaseModel):
    """Request body for AI scientist text analysis."""

    text: str = Field(..., min_length=8, max_length=200000)
    recognition_mode: Literal["deterministic", "provider"] = "deterministic"
    provider_id: int | None = None
    language: str | None = None
    top_k_templates: int = Field(default=3, ge=1, le=5)
    source_file_name: str | None = None
    source_sections: list[dict[str, Any]] | None = None


class SettingItem(BaseModel):
    """One setup key-value pair for the scenario configuration."""

    key: str
    value: str
    reason: str = ""


class ActionItem(BaseModel):
    """One candidate action for each round."""

    name: str
    description: str


class AgentItem(BaseModel):
    """One candidate agent role with count."""

    label: str
    description: str
    count: int = 1


class TemplateSuggestionItem(BaseModel):
    """One matching preset template candidate."""

    id: str
    name: str
    category: str
    description: str
    score: float
    reason: str


class EvidenceItem(BaseModel):
    label: str
    snippet: str
    section: str | None = None


class SourceSectionItem(BaseModel):
    id: str
    title: str
    excerpt: str
    page: int | None = None


class AnalyzeResponse(BaseModel):
    """Structured analysis result consumed by the custom experiment page."""

    scenario_description: str
    settings: list[SettingItem]
    actions: list[ActionItem]
    agents: list[AgentItem]
    key_variables: list[str]
    template_suggestions: list[TemplateSuggestionItem]
    used_llm: bool
    warnings: list[str]
    assumptions: list[str]
    missing_information: list[str]
    evidence: list[EvidenceItem]
    evidence_by_field: dict[str, list[str]]
    recommended_scenario_id: str
    recommended_scenario_reason: str
    recommendation_confidence: float
    review_required: bool
    recommended_params: dict[str, Any]
    source_sections: list[SourceSectionItem]
    semantic_schema: dict[str, Any]
    model_used: str | None = None


class ReextractFieldRequest(BaseModel):
    text: str = Field(..., min_length=8, max_length=200000)
    field: Literal["scenario", "settings", "actions", "agents", "variables"]
    language: str | None = None
    source_sections: list[dict[str, Any]] | None = None


class ReextractFieldResponse(BaseModel):
    field: Literal["scenario", "settings", "actions", "agents", "variables"]
    scenario_description: str | None = None
    settings: list[SettingItem] = Field(default_factory=list)
    actions: list[ActionItem] = Field(default_factory=list)
    agents: list[AgentItem] = Field(default_factory=list)
    key_variables: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


async def _select_provider_optional(
    session: AsyncSession,
    user_id: int,
    provider_id: int | None,
) -> ProviderConfig | None:
    """Return selected provider, active provider, or None when not configured."""
    if provider_id is not None:
        result = await session.execute(
            select(ProviderConfig).where(
                ProviderConfig.user_id == user_id,
                ProviderConfig.id == provider_id,
            )
        )
        provider = result.scalars().first()
        if provider is None:
            raise HTTPException(status_code=400, detail=T("api.errors.ai_scientist_selected_provider_not_found"))
        return provider

    result = await session.execute(
        select(ProviderConfig).where(ProviderConfig.user_id == user_id)
    )
    providers = result.scalars().all()
    if not providers:
        return None

    active = [item for item in providers if (item.config or {}).get("active")]
    return active[0] if active else providers[0]


def _template_suggestion_lines(template_suggestions: list[TemplateSuggestion]) -> str:
    return "\n".join(
        f"- {item.id}: {item.name} ({item.category}) -> {item.description} [score={item.score:.2f}]"
        for item in template_suggestions[:5]
    ) or "- custom: Use when no preset scenario fits."


def _build_pass_a_prompt(
    language: str,
    template_suggestions: list[TemplateSuggestion],
    scaffold: dict[str, Any],
) -> list[dict[str, str]]:
    """Build the first-pass prompt for document understanding and evidence extraction."""
    locale_hint = "Chinese" if language.lower().startswith("zh") else "English"
    suggestion_lines = _template_suggestion_lines(template_suggestions)
    evidence_packet = scaffold["evidence_packet"]
    semantic_schema = scaffold["semantic_schema"]
    source_outline = scaffold["source_outline"]
    helper_hints = scaffold["helper_hints"]
    system_prompt = (
        "You are an AI social scientist assistant. "
        "Read the structured evidence packet from a research document and reconstruct the underlying experimental design. "
        "Treat heuristic hints as weak clues only. They may be wrong. "
        "Preserve explicit role names and decision terms when the source provides them. "
        "Do not guess missing rules. If information is absent, say so. "
        "Return ONLY valid JSON with this schema: "
        "{"
        '"scenario_summary": string, '
        '"participants": [{"label": string, "description": string, "count": number}], '
        '"actions": [{"name": string, "description": string}], '
        '"setting_candidates": [{"key": string, "value": string, "reason": string}], '
        '"key_variables": [string], '
        '"interaction_structure_hint": string, '
        '"payoff_rules": [string], '
        '"constraints": [string], '
        '"information_structure": [string], '
        '"interaction_topology": [string], '
        '"assumptions": [string], '
        '"missing_information": [string], '
        '"evidence_by_field": {'
        '"scenario_summary": [string], '
        '"participants": [string], '
        '"actions": [string], '
        '"payoff_rules": [string], '
        '"constraints": [string], '
        '"information_structure": [string], '
        '"interaction_topology": [string]'
        "}, "
        '"candidate_template_judgment": [{"id": string, "fit": number, "reason": string}]'
        "}. "
        "Use concise field evidence quotes or paraphrases from the source packet. "
        "Do not wrap JSON in markdown. Keep the response language in "
        f"{locale_hint}."
    )
    user_prompt = (
        "Use the packet below to understand the experiment before attempting any preset match.\n\n"
        "Candidate preset scenarios for reference only:\n"
        f"{suggestion_lines}\n\n"
        "Evidence packet:\n"
        f"{json.dumps(evidence_packet, ensure_ascii=False, indent=2)}\n\n"
        "Semantic schema scaffold:\n"
        f"{json.dumps(semantic_schema, ensure_ascii=False, indent=2)}\n\n"
        "Structured source outline:\n"
        f"{json.dumps(source_outline, ensure_ascii=False, indent=2)}\n\n"
        "Weak heuristic helper hints (may be noisy, use carefully):\n"
        f"{json.dumps(helper_hints, ensure_ascii=False, indent=2)}\n\n"
        "Rules:\n"
        "1. Do not copy reference titles, section headers, or citations as participants or actions.\n"
        "2. If you see role names, preserve them instead of flattening them into generic participants.\n"
        "3. If the document is theoretical or methodological, still extract the interaction pattern if present.\n"
        "4. Only use candidate templates as comparison anchors; do not force a preset match.\n"
        "5. If evidence is weak, keep that uncertainty explicit."
    )
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


def _build_pass_b_prompt(
    language: str,
    template_suggestions: list[TemplateSuggestion],
    scaffold: dict[str, Any],
    pass_a: dict[str, Any],
) -> list[dict[str, str]]:
    locale_hint = "Chinese" if language.lower().startswith("zh") else "English"
    suggestion_lines = _template_suggestion_lines(template_suggestions)
    system_prompt = (
        "You are an AI social scientist assistant. "
        "Convert the document understanding draft into the final FOS experiment draft. "
        "The final recommendation must come from the model's judgment, not from heuristics. "
        "Choose a preset template only if the interaction structure, actions, and incentive logic clearly match a real candidate. "
        "Otherwise return recommended_scenario_id='custom'. "
        "Return ONLY valid JSON with this schema: "
        "{"
        '"scenario_description": string, '
        '"settings": [{"key": string, "value": string, "reason": string}], '
        '"actions": [{"name": string, "description": string}], '
        '"agents": [{"label": string, "description": string, "count": number}], '
        '"key_variables": [string], '
        '"assumptions": [string], '
        '"missing_information": [string], '
        '"evidence": [{"label": string, "snippet": string, "section": string | null}], '
        '"evidence_by_field": object, '
        '"recommended_scenario_id": string, '
        '"recommended_scenario_reason": string, '
        '"recommendation_confidence": number, '
        '"review_required": boolean, '
        '"recommended_params": object, '
        '"source_sections": [{"id": string, "title": string, "excerpt": string, "page": number | null}]'
        "}. "
        f"Keep the response language in {locale_hint}."
    )
    user_prompt = (
        "Build the final experiment draft.\n\n"
        "Real preset candidates:\n"
        f"{suggestion_lines}\n\n"
        "Structured document understanding:\n"
        f"{json.dumps(pass_a, ensure_ascii=False, indent=2)}\n\n"
        "Supporting scaffold:\n"
        f"{json.dumps({'semantic_schema': scaffold['semantic_schema'], 'helper_hints': scaffold['helper_hints'], 'source_sections': scaffold['source_sections'][:6]}, ensure_ascii=False, indent=2)}\n\n"
        "Rules:\n"
        "1. Prefer the document's own role and action vocabulary when available.\n"
        "2. Never recommend a preset template id that is not in the candidate list.\n"
        "3. If the mapping is incomplete or risky, keep recommended_scenario_id='custom' and set review_required=true.\n"
        "4. Use recommended_params only for concrete, source-supported parameters.\n"
        "5. Include field evidence and evidence cards that would help a human review the draft."
    )
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


def _build_repair_prompt(
    language: str,
    scaffold: dict[str, Any],
    analysis: dict[str, Any],
    issues: list[str],
) -> list[dict[str, str]]:
    locale_hint = "Chinese" if language.lower().startswith("zh") else "English"
    system_prompt = (
        "You are repairing a structured experiment draft extracted from a research document. "
        "Fix only the problems listed. Keep supported fields, remove noisy roles/actions, and preserve evidence grounding. "
        "Return ONLY valid JSON using the same schema as the final experiment draft. "
        f"Keep the response language in {locale_hint}."
    )
    user_prompt = (
        "Repair this draft using the source scaffold.\n\n"
        f"Issues to fix: {json.dumps(issues, ensure_ascii=False)}\n\n"
        "Current draft:\n"
        f"{json.dumps(analysis, ensure_ascii=False, indent=2)}\n\n"
        "Source scaffold:\n"
        f"{json.dumps({'semantic_schema': scaffold['semantic_schema'], 'source_sections': scaffold['source_sections'][:6], 'helper_hints': scaffold['helper_hints']}, ensure_ascii=False, indent=2)}\n\n"
        "Rules:\n"
        "1. Remove participants or actions that look like section headers, references, formulas, URLs, or citations.\n"
        "2. Preserve the current draft when it is already supported.\n"
        "3. Do not invent a preset mapping if the source evidence is weak.\n"
        "4. Keep evidence_by_field aligned with the repaired fields."
    )
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


def _parse_model_payload(raw: str) -> dict[str, Any]:
    try:
        return parse_llm_json(raw)
    except Exception:
        return repair_llm_json(raw)


def _field_evidence(analysis: dict[str, Any], field: str) -> list[str]:
    evidence_by_field = analysis.get("evidence_by_field") or {}
    mapping = {
        "scenario": ["research_goal", "setting", "decision_context"],
        "settings": ["payoff_rules", "constraints", "information_structure", "interaction_topology", "interaction_structure"],
        "actions": ["actions", "decision_context"],
        "agents": ["participants"],
        "variables": ["key_variables", "outcomes"],
    }
    collected: list[str] = []
    for key in mapping.get(field, []):
        collected.extend(str(item).strip() for item in evidence_by_field.get(key, []) if str(item).strip())
    if not collected:
        collected = [
            str(item.get("snippet", "")).strip()
            for item in analysis.get("evidence", [])
            if isinstance(item, dict) and str(item.get("snippet", "")).strip()
        ]
    seen: set[str] = set()
    deduped: list[str] = []
    for item in collected:
        lowered = item.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        deduped.append(item)
    return deduped[:6]


def _build_field_reextract_response(
    *,
    field: Literal["scenario", "settings", "actions", "agents", "variables"],
    analysis: dict[str, Any],
) -> ReextractFieldResponse:
    payload: dict[str, Any] = {
        "field": field,
        "evidence": _field_evidence(analysis, field),
        "warnings": [
            "Field re-extraction uses the deterministic backend path to refresh only the selected field.",
        ],
    }
    if field == "scenario":
        payload["scenario_description"] = str(analysis.get("scenario_description", "")).strip()
    elif field == "settings":
        payload["settings"] = analysis.get("settings", []) or []
    elif field == "actions":
        payload["actions"] = analysis.get("actions", []) or []
    elif field == "agents":
        payload["agents"] = analysis.get("agents", []) or []
    elif field == "variables":
        payload["key_variables"] = [str(item).strip() for item in analysis.get("key_variables", []) if str(item).strip()]
    return ReextractFieldResponse(**payload)


@post("/analyze", tags=["ai_scientist"])
async def analyze_research_text(request: Request, data: AnalyzeRequest) -> AnalyzeResponse:
    """Analyze research text into structured experiment setup fields."""
    token = extract_bearer_token(request)
    warnings: list[str] = []
    language = data.language or request.headers.get("X-Language") or "en"
    runtime_task = RUNTIME_TASKS.start(
        "ai_scientist_analysis",
        "AI Scientist analysis",
        metadata={
            "recognition_mode": data.recognition_mode,
            "provider_id": data.provider_id,
            "language": language,
            "source_file_name": data.source_file_name,
        },
    )

    scenarios = get_all_scenarios()
    scaffold = build_llm_analysis_scaffold(
        data.text,
        scenarios,
        language=language,
        top_k=data.top_k_templates,
        source_sections=data.source_sections,
    )
    template_suggestions = scaffold["template_suggestions"]
    semantic_schema = scaffold["semantic_schema"]
    deterministic = heuristic_analysis(
        data.text,
        template_suggestions,
        language=language,
        source_sections=scaffold["source_sections"],
    )

    normalized: dict[str, Any] = deterministic
    used_llm = False
    model_used: str | None = None

    if data.recognition_mode == "provider":
        async with get_session() as session:
            current_user = await resolve_current_user(session, token)
            provider = await _select_provider_optional(session, current_user.id, data.provider_id)
            if provider is None:
                error = T("api.errors.ai_scientist_no_active_provider")
                RUNTIME_TASKS.fail(runtime_task.id, error)
                raise HTTPException(
                    status_code=400,
                    detail=error,
                )

            try:
                dialect, base_url = normalize_provider_runtime(provider.provider, provider.base_url)
                cfg = LLMConfig(
                    dialect=dialect,
                    api_key=provider.api_key or "",
                    model=provider.model,
                    base_url=base_url or (get_default_ollama_base_url() if dialect == "ollama" else None),
                    temperature=0.15,
                    top_p=1.0,
                    frequency_penalty=0.0,
                    presence_penalty=0.0,
                    max_tokens=16384,
                    supports_vision=guess_supports_vision(provider.model),
                )
                llm = create_llm_client(cfg)
                model_used = provider.model

                pass_a = _parse_model_payload(
                    llm.chat(
                        _build_pass_a_prompt(language, template_suggestions, scaffold),
                        json_mode=True,
                    )
                )
                llm_result = _parse_model_payload(
                    llm.chat(
                        _build_pass_b_prompt(language, template_suggestions, scaffold, pass_a),
                        json_mode=True,
                    )
                )
                normalized = normalize_llm_analysis_output(
                    llm_result,
                    semantic_schema=semantic_schema,
                    source_sections=scaffold["source_sections"],
                    template_suggestions=template_suggestions,
                )
                issues = collect_analysis_quality_issues(normalized, template_suggestions=template_suggestions)
                if issues:
                    warnings.append(f"Triggered repair pass for: {', '.join(issues)}")
                    repaired = _parse_model_payload(
                        llm.chat(
                            _build_repair_prompt(language, scaffold, normalized, issues),
                            json_mode=True,
                        )
                    )
                    normalized = normalize_llm_analysis_output(
                        repaired,
                        semantic_schema=semantic_schema,
                        source_sections=scaffold["source_sections"],
                        template_suggestions=template_suggestions,
                    )
                    issues = collect_analysis_quality_issues(normalized, template_suggestions=template_suggestions)
                    if issues:
                        warnings.append(f"Remaining review issues after repair: {', '.join(issues)}")
                        normalized["review_required"] = True
                        normalized["missing_information"] = list(
                            dict.fromkeys(
                                [
                                    *normalized.get("missing_information", []),
                                    "Model output still needs human review because some fields remained noisy or incomplete.",
                                ]
                            )
                        )[:8]
                used_llm = True
            except HTTPException:
                raise
            except Exception as exc:  # noqa: BLE001
                logger.warning("AI scientist LLM extraction failed: %s", exc)
                RUNTIME_TASKS.fail(runtime_task.id, exc)
                raise HTTPException(
                    status_code=502,
                    detail=T("api.errors.ai_scientist_llm_recognition_failed", error=str(exc)),
                ) from exc
    else:
        warnings.append("Ran deterministic recognition mode without provider assistance.")

    merged = localize_analysis_output(normalized, language)

    suggestion_models = [
        TemplateSuggestionItem(
            id=item.id,
            name=item.name,
            category=item.category,
            description=item.description,
            score=item.score,
            reason=item.reason,
        )
        for item in template_suggestions
    ]

    response = AnalyzeResponse(
        scenario_description=merged["scenario_description"],
        settings=[SettingItem(**item) for item in merged["settings"]],
        actions=[ActionItem(**item) for item in merged["actions"]],
        agents=[AgentItem(**item) for item in merged["agents"]],
        key_variables=merged["key_variables"],
        template_suggestions=suggestion_models,
        used_llm=used_llm,
        warnings=warnings,
        assumptions=merged["assumptions"],
        missing_information=merged["missing_information"],
        evidence=[EvidenceItem(**item) for item in merged["evidence"]],
        evidence_by_field=merged.get("evidence_by_field", {}),
        recommended_scenario_id=merged["recommended_scenario_id"],
        recommended_scenario_reason=merged["recommended_scenario_reason"],
        recommendation_confidence=merged.get("recommendation_confidence", 0.0),
        review_required=merged.get("review_required", True),
        recommended_params=merged["recommended_params"],
        source_sections=[SourceSectionItem(**item) for item in merged["source_sections"]],
        semantic_schema=semantic_schema,
        model_used=model_used,
    )
    RUNTIME_TASKS.finish(
        runtime_task.id,
        metadata={
            "used_llm": used_llm,
            "model_used": model_used,
            "recommended_scenario_id": response.recommended_scenario_id,
        },
    )
    return response

@post("/reextract-field", tags=["ai_scientist"])
async def reextract_research_field(request: Request, data: ReextractFieldRequest) -> ReextractFieldResponse:
    """Refresh one field using the deterministic extraction path."""
    _ = extract_bearer_token(request)
    language = data.language or request.headers.get("X-Language") or "en"
    scaffold = build_llm_analysis_scaffold(
        data.text,
        get_all_scenarios(),
        language=language,
        top_k=5,
        source_sections=data.source_sections,
    )
    analysis = heuristic_analysis(
        data.text,
        scaffold["template_suggestions"],
        language=language,
        source_sections=scaffold["source_sections"],
    )
    localized = localize_analysis_output(analysis, language)
    return _build_field_reextract_response(field=data.field, analysis=localized)


router = Router(path="/llm/ai_scientist", route_handlers=[analyze_research_text, reextract_research_field])
