import pytest; pytest.importorskip("torch", reason="torch not installed (required for RAG e2e tests)")
"""
End-to-end tests for the text RAG pipeline in FOS.

Tests the full RAG flow from document processing through semantic retrieval,
global knowledge integration, keyword fallback, and prompt injection --- all
with REAL embeddings from sentence-transformers (all-MiniLM-L6-v2 / CPU).

No mocks. The embedding model is loaded once as a module-level singleton.

Contains: 11 E2E tests across 5 scenarios:
- Document pipeline (3 tests)
- Global knowledge integration (2 tests)
- Keyword fallback (2 tests)
- Prompt injection (2 tests)
- Edge cases (2 tests)
"""

import os
import math

import pytest

from fos.core.experiment.agent import ExperimentAgent
from fos.core.experiment.prompt_builder import build_prompt
from fos.core.experiment.game_configs import GameConfig
from fos.core.llm_config import LLMConfig

# --- Embedding environment ------------------------------------------------
# CPU-only for test reproducibility; no CUDA dependency.
os.environ.setdefault("FOS_EMBEDDING_DEVICE", "cpu")


# --- Module-level helpers -------------------------------------------------


def _make_agent(**overrides):
    """Create an ExperimentAgent with sensible defaults."""
    defaults = dict(name="test", properties={}, llm_config=LLMConfig(dialect="mock"))
    defaults.update(overrides)
    return ExperimentAgent(**defaults)


def _make_game_config(**overrides):
    """Create a GameConfig with sensible defaults for testing."""
    defaults = dict(
        name="test_game",
        description="A test scenario.",
        action_type="discrete",
        actions=["speak"],
    )
    defaults.update(overrides)
    return GameConfig(**defaults)


# ===================================================================
# 1. Document Pipeline
# ===================================================================


class TestDocumentPipeline:
    """E2E tests for real document processing + retrieval."""

    def test_chunk_text_splits_correctly(self):
        """chunk_text splits long text into overlapping chunks."""
        from fos.backend.services.documents import chunk_text

        text = "The quick brown fox jumps over the lazy dog. " * 100
        chunks = chunk_text(text, chunk_size=750, overlap=0.2)
        assert len(chunks) >= 3
        for c in chunks:
            assert "chunk_id" in c
            assert "text" in c
            assert len(c["text"]) <= 750
        assert chunks[0]["end_index"] > chunks[1]["start_index"]

    def test_retrieve_ranks_relevant_text_highest(self):
        """Real doc process + real embed + query matching terms returns
        relevant chunk ranked first."""
        from fos.backend.services.documents import (
            process_document,
            composite_rag_retrieval,
        )

        doc_text = (
            "Economics: inflation rose 3%% this quarter. "
            "Central banks raised interest rates to cool demand. "
            "Bond yields followed suit.\n\n"
            "Sports: the local football team won the championship. "
            "The star player scored a hat trick in the final match."
        )
        doc = process_document(doc_text.encode("utf-8"), "report.txt", len(doc_text))
        results = composite_rag_retrieval(
            query="inflation interest rates bonds",
            agent_documents={"report": doc},
            global_knowledge=None,
            top_k=3,
        )
        assert len(results) > 0
        top_text = results[0]["text"]
        assert any(term in top_text for term in ["inflation", "interest", "bond"])

    def test_unrelated_query_returns_low_similarity(self):
        """Physics document queried with food topic - low similarity."""
        from fos.backend.services.documents import (
            process_document,
            composite_rag_retrieval,
        )

        doc_text = "Quantum chromodynamics describes the strong force binding quarks."
        doc = process_document(doc_text.encode("utf-8"), "physics.txt", len(doc_text))
        results = composite_rag_retrieval(
            query="recipe for chocolate cake",
            agent_documents={"physics": doc},
            global_knowledge=None,
            top_k=3,
        )
        if results:
            assert all(r["similarity"] < 0.5 for r in results)


# ===================================================================
# 2. Global Knowledge Integration
# ===================================================================


class TestGlobalKnowledgeIntegration:
    """E2E tests for global + private knowledge merging."""

    def test_global_and_private_merged_in_results(self):
        """composite_rag_retrieval includes both private and global."""
        from fos.backend.services.documents import (
            process_document,
            composite_rag_retrieval,
            generate_embedding,
        )

        doc_text = "Project Alpha budget is 500k for Q3."
        doc = process_document(doc_text.encode("utf-8"), "budget.txt", len(doc_text))
        global_kw = {
            "policy": {
                "embedding": generate_embedding("Company policy is 9-to-5 work hours"),
                "content": "Company policy is 9-to-5 work hours",
            },
        }
        results = composite_rag_retrieval(
            query="budget and policy",
            agent_documents={"budget": doc},
            global_knowledge=global_kw,
            top_k=5,
        )
        sources = {r["source"] for r in results}
        assert "private" in sources
        assert "global" in sources

    def test_global_only_with_no_agent_docs(self):
        """Only global knowledge - retrieval works from global alone."""
        from fos.backend.services.documents import (
            composite_rag_retrieval,
            generate_embedding,
        )

        global_kw = {
            "rule": {
                "embedding": generate_embedding("Dress code requires formal attire"),
                "content": "Dress code requires formal attire",
            },
        }
        results = composite_rag_retrieval(
            query="dress code",
            agent_documents=None,
            global_knowledge=global_kw,
            top_k=3,
        )
        assert len(results) > 0
        assert all(r["source"] == "global" for r in results)
        assert any("dress" in r["text"].lower() for r in results)


# ===================================================================
# 3. Keyword Fallback
# ===================================================================


class TestKeywordFallback:
    """E2E tests for keyword fallback when no documents exist."""

    def test_knowledge_base_fallback_without_documents(self):
        """Agent with knowledge_base but empty documents - keyword fallback."""
        agent = _make_agent(
            documents={},
            knowledge_base=[
                {"title": "Policy", "content": "Company policy on remote work", "enabled": True},
            ],
        )
        result = agent.get_rag_context("remote work policy")
        assert "Policy" in result
        assert "Company policy" in result

    def test_disabled_knowledge_items_excluded(self):
        """Disabled items excluded from keyword fallback."""
        agent = _make_agent(
            documents={},
            knowledge_base=[
                {"title": "Active", "content": "Active rule", "enabled": True},
                {"title": "Inactive", "content": "Inactive rule", "enabled": False},
            ],
        )
        result = agent.get_rag_context("rule")
        assert "Active rule" in result
        assert "Inactive rule" not in result


# ===================================================================
# 4. Prompt Injection
# ===================================================================


class TestPromptInjection:
    """RAG context injection into agent prompts via build_prompt()."""

    def test_prompt_with_kb_context_includes_rag_section(self):
        """build_prompt with kb_context -- RAG content in Section 3.6."""
        agent = _make_agent(name="Alice")
        game_config = _make_game_config()
        prompt = build_prompt(
            agent=agent,
            game_config=game_config,
            context_summary="",
            kb_context="[1] Personal knowledge:\nApples are fruits",
        )
        assert "Apples are fruits" in prompt
        scenario_idx = prompt.find("Scenario")
        kb_idx = prompt.find("Apples are fruits")
        assert kb_idx > scenario_idx

    def test_prompt_without_kb_context_omits_rag(self):
        """build_prompt without kb_context -- no Knowledge Base section."""
        agent = _make_agent(name="Bob")
        game_config = _make_game_config()
        prompt = build_prompt(
            agent=agent,
            game_config=game_config,
            context_summary="Some context",
        )
        assert "Knowledge Base" not in prompt


# ===================================================================
# 5. Edge Cases
# ===================================================================


class TestEdgeCases:
    """Edge cases - no mocks."""

    def test_empty_documents_returns_empty(self):
        """No documents and no knowledge_base returns empty."""
        agent = _make_agent(documents={})
        result = agent.get_rag_context("anything")
        assert result == ""

    def test_real_semantic_search_preferred_over_keyword(self):
        """Agent with real documents + knowledge_base -- semantic search
        takes priority, keyword-only content excluded."""
        from fos.backend.services.documents import process_document

        doc_text = "semantic search result from processed document"
        doc = process_document(doc_text.encode("utf-8"), "semantic.txt", len(doc_text))
        agent = _make_agent(
            documents={"doc1": doc},
            knowledge_base=[
                {"title": "KB", "content": "keyword only", "enabled": True},
            ],
        )
        result = agent.get_rag_context("semantic search")
        assert "semantic search result" in result
        assert "keyword only" not in result
