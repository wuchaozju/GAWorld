"""
Unit tests for debug log format in ExperimentRunner.

Verifies that debug logs are written sequentially per agent (not interleaved)
when multiple agents are prompted in parallel.
"""
import asyncio
import tempfile
import re
from pathlib import Path
from unittest.mock import Mock, patch

from fos.core.experiment.agent import ExperimentAgent
from fos.core.experiment.game_configs import PRISONERS_DILEMMA
from fos.core.experiment.runner import ExperimentRunner
from fos.core.llm_config import LLMConfig


def run(coro):
    return asyncio.run(coro)


def make_agents(names):
    llm_config = LLMConfig(dialect="openai", api_key="test")
    return [ExperimentAgent(name=n, properties={}, llm_config=llm_config) for n in names]


def make_mock_llm():
    m = Mock()
    m.chat.return_value = '{"action": "cooperate"}'
    return m


def test_debug_log_sequential_format_per_agent():
    """Test that debug log shows PROMPT -> RESPONSE -> RESULT sequentially for each agent."""
    with tempfile.TemporaryDirectory() as tmpdir:
        debug_file = Path(tmpdir) / "debug.txt"

        agents = make_agents(["Alice", "Bob"])
        runner = ExperimentRunner(
            agents=agents,
            game_config=PRISONERS_DILEMMA,
            llm_client=make_mock_llm(),
            round_visibility="simultaneous",
        )

        # Patch the global _debug_file to use our temp file
        with patch('fos.core.experiment.debug_log._session_debug_file', debug_file):
            run(runner.run(max_rounds=1))

        # Read the debug log
        content = debug_file.read_text(encoding='utf-8')

        # Extract agent sections
        # Each agent should have a complete section: AGENT -> PROMPT -> RESPONSE -> RESULT
        agent_sections = re.findall(r'## AGENT: (\w+).*?--- PROCESSED RESULT ---', content, re.DOTALL)

        # Should have 2 complete sections (one per agent)
        assert len(agent_sections) == 2, f"Expected 2 agent sections, found {len(agent_sections)}"

        # Verify each section contains all required components
        for agent_name in ["Alice", "Bob"]:
            # Find the section for this agent
            pattern = rf'## AGENT: {agent_name}.*?(?=## AGENT: |$)'
            match = re.search(pattern, content, re.DOTALL)
            assert match, f"Could not find section for agent {agent_name}"

            section = match.group(0)

            # Verify sequential order within section
            prompt_pos = section.find("FULL PROMPT SENT TO LLM")
            response_pos = section.find("LLM RAW RESPONSE")
            result_pos = section.find("--- PROCESSED RESULT ---")

            assert prompt_pos != -1, f"Agent {agent_name} missing PROMPT section"
            assert response_pos != -1, f"Agent {agent_name} missing RESPONSE section"
            assert result_pos != -1, f"Agent {agent_name} missing RESULT section"

            # Verify order: PROMPT < RESPONSE < RESULT
            assert prompt_pos < response_pos, \
                f"Agent {agent_name}: PROMPT should come before RESPONSE"
            assert response_pos < result_pos, \
                f"Agent {agent_name}: RESPONSE should come before RESULT"


def test_debug_log_atomic_writes_no_interleaving():
    """Test that debug log entries don't interleave between agents."""
    with tempfile.TemporaryDirectory() as tmpdir:
        debug_file = Path(tmpdir) / "debug.txt"

        agents = make_agents(["Alice", "Bob"])
        runner = ExperimentRunner(
            agents=agents,
            game_config=PRISONERS_DILEMMA,
            llm_client=make_mock_llm(),
            round_visibility="simultaneous",
        )

        # Patch the global _debug_file to use our temp file
        with patch('fos.core.experiment.debug_log._session_debug_file', debug_file):
            run(runner.run(max_rounds=1))

        # Read the debug log
        content = debug_file.read_text(encoding='utf-8')

        # Split by agent sections
        alice_start = content.find("## AGENT: Alice")
        bob_start = content.find("## AGENT: Bob")

        assert alice_start != -1, "Alice section not found"
        assert bob_start != -1, "Bob section not found"

        # Extract each agent's section
        if alice_start < bob_start:
            alice_section = content[alice_start:bob_start]
            bob_section = content[bob_start:]
        else:
            bob_section = content[bob_start:alice_start]
            alice_section = content[alice_start:]

        # Verify Alice's section is complete (has all parts)
        assert "## AGENT: Alice" in alice_section
        assert "FULL PROMPT SENT TO LLM" in alice_section
        assert "LLM RAW RESPONSE" in alice_section
        assert "--- PROCESSED RESULT ---" in alice_section

        # Verify Bob's section is complete (has all parts)
        assert "## AGENT: Bob" in bob_section
        assert "FULL PROMPT SENT TO LLM" in bob_section
        assert "LLM RAW RESPONSE" in bob_section
        assert "--- PROCESSED RESULT ---" in bob_section

        # Verify no interleaving: Alice's section should NOT contain Bob's markers
        assert "## AGENT: Bob" not in alice_section
        # And Bob's section should NOT contain Alice's markers
        assert "## AGENT: Alice" not in bob_section


def test_debug_log_includes_all_components():
    """Test that debug log includes all expected components for each agent."""
    with tempfile.TemporaryDirectory() as tmpdir:
        debug_file = Path(tmpdir) / "debug.txt"

        agents = make_agents(["Alice"])
        runner = ExperimentRunner(
            agents=agents,
            game_config=PRISONERS_DILEMMA,
            llm_client=make_mock_llm(),
            round_visibility="simultaneous",
        )

        # Patch the global _debug_file to use our temp file
        with patch('fos.core.experiment.debug_log._session_debug_file', debug_file):
            run(runner.run(max_rounds=1))

        # Read the debug log
        content = debug_file.read_text(encoding='utf-8')

        # Verify all expected sections are present
        assert "## AGENT: Alice" in content
        assert "## ROUND:" in content
        assert "## VISIBILITY MODE:" in content
        assert "--- AGENT PROPERTIES ---" in content
        assert "--- GAME CONFIG ---" in content
        assert "--- CONTEXT (filtered for this agent) ---" in content
        assert "FULL PROMPT SENT TO LLM" in content
        assert "END OF PROMPT" in content
        assert "LLM RAW RESPONSE" in content
        assert "END OF RESPONSE" in content
        assert "--- PROCESSED RESULT ---" in content

        # Verify result contains expected fields
        result_section = content[content.find("--- PROCESSED RESULT ---"):]
        assert "action:" in result_section
        assert "success:" in result_section
        assert "skipped:" in result_section
        assert "summary:" in result_section
