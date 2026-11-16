"""
Unit tests for truncate_context_to_budget() and information_model param in build_prompt.
"""
from fos.core.experiment.agent import ExperimentAgent
from fos.core.experiment.game_configs import PRISONERS_DILEMMA
from fos.core.experiment.prompt_builder import build_prompt, truncate_context_to_budget
from fos.core.experiment.information_model import InformationModel
from fos.core.llm_config import LLMConfig


def test_truncate_no_limit_returns_unchanged():
    s = "x" * 2000
    assert truncate_context_to_budget(s, 0) == s


def test_truncate_within_limit_returns_unchanged():
    s = "hello\nworld"
    assert truncate_context_to_budget(s, 500) == s


def test_truncate_over_limit_shortens_and_notes_omission():
    lines = [f"Round {i}: cooperate" for i in range(1, 30)]
    ctx = "\n".join(lines)
    result = truncate_context_to_budget(ctx, 60)
    assert len(result) < len(ctx)
    assert "omitted" in result


def test_build_prompt_backward_compat_no_info_model():
    llm_config = LLMConfig(dialect="openai", api_key="test")
    agent = ExperimentAgent(name="Alice", properties={}, llm_config=llm_config)
    prompt = build_prompt(agent, PRISONERS_DILEMMA, "Round 1: cooperate.")
    assert "cooperate" in prompt


def test_build_prompt_applies_budget_via_info_model():
    llm_config = LLMConfig(dialect="openai", api_key="test")
    agent = ExperimentAgent(name="Alice", properties={}, llm_config=llm_config)
    long_ctx = "\n".join(f"Round {i}: cooperate cooperate cooperate" for i in range(1, 50))
    info_model = InformationModel(scope_type="all", context_budget_chars=80)

    prompt = build_prompt(
        agent, PRISONERS_DILEMMA, long_ctx,
        include_section_markers=True,
        information_model=info_model,
    )

    # Section 4 context should be truncated
    start = prompt.find("## Context\n") + len("## Context\n")
    end = prompt.find("\n## ", start)
    if end == -1:
        end = prompt.find("\n===", start)
    section4 = prompt[start:end] if end > start else prompt[start:]
    assert len(section4) < len(long_ctx)


def test_build_prompt_no_budget_keeps_full_context():
    llm_config = LLMConfig(dialect="openai", api_key="test")
    agent = ExperimentAgent(name="Alice", properties={}, llm_config=llm_config)
    ctx = "Round 1: cooperate.\nRound 2: defect."
    info_model = InformationModel(scope_type="all", context_budget_chars=0)
    prompt = build_prompt(agent, PRISONERS_DILEMMA, ctx, information_model=info_model)
    assert "Round 1" in prompt
    assert "Round 2" in prompt
