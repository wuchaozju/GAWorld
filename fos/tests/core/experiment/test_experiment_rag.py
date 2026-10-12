"""
Tests for RAG integration on ExperimentAgent, ExperimentConfig, and ExperimentScene.

Covers: documents field, get_rag_context(), global_knowledge propagation,
semantic search delegation, keyword fallback, and no-call guarantees.

Contains: test_experiment_rag_* (8 tests)
"""

from unittest.mock import patch


from fos.core.experiment.agent import ExperimentAgent
from fos.core.experiment.config import ExperimentConfig
from fos.core.experiment.scene import ExperimentScene
from fos.core.llm_config import LLMConfig


def _make_agent(**overrides):
    defaults = dict(name="test", properties={}, llm_config=LLMConfig(dialect="mock"))
    defaults.update(overrides)
    return ExperimentAgent(**defaults)


# --- Test 1: documents field exists and defaults to empty dict ---

def test_experiment_agent_has_documents_field():
    agent = _make_agent()
    assert hasattr(agent, "documents")
    assert agent.documents == {}


# --- Test 2: get_rag_context returns "" when no knowledge ---

def test_rag_context_empty_when_no_knowledge():
    agent = _make_agent()
    result = agent.get_rag_context("any query")
    assert result == ""


# --- Test 3: get_rag_context falls back to keyword matching ---

def test_rag_context_keyword_fallback():
    agent = _make_agent(
        knowledge_base=[
            {"title": "Tax policy", "content": "Tax rates affect behavior", "enabled": True},
        ],
    )
    result = agent.get_rag_context("tax")
    assert "Tax policy" in result or "Tax rates" in result


# --- Test 4: get_rag_context uses semantic search when documents present ---

@patch("fos.backend.services.documents.composite_rag_retrieval")
def test_rag_context_uses_semantic_search(mock_retrieval):
    mock_retrieval.return_value = [
        {"source": "private", "text": "result text", "similarity": 0.9, "filename": ""},
    ]
    agent = _make_agent(documents={"doc1": {"chunks": [{"text": "x"}]}})
    result = agent.get_rag_context("test query")
    mock_retrieval.assert_called_once_with(
        query="test query",
        agent_documents=agent.documents,
        global_knowledge={},
        top_k=3,
    )
    assert "result text" in result


# --- Test 5: get_rag_context passes global_knowledge ---

@patch("fos.backend.services.documents.composite_rag_retrieval")
def test_rag_context_passes_global_knowledge(mock_retrieval):
    mock_retrieval.return_value = [
        {"source": "global", "text": "shared info", "similarity": 0.8, "filename": ""},
    ]
    gk = {"doc_g": {"chunks": [{"text": "shared"}]}}
    agent = _make_agent(documents={"doc1": {"chunks": []}})
    agent.get_rag_context("query", global_knowledge=gk, top_k=5)
    mock_retrieval.assert_called_once_with(
        query="query",
        agent_documents=agent.documents,
        global_knowledge=gk,
        top_k=5,
    )


# --- Test 6: ExperimentConfig accepts global_knowledge ---

def test_config_accepts_global_knowledge():
    config = ExperimentConfig(
        agents=[],
        actions=[],
        global_knowledge={"doc1": {"chunks": [{"text": "shared info"}]}},
    )
    assert config.global_knowledge["doc1"]["chunks"][0]["text"] == "shared info"


# --- Test 7: ExperimentScene exposes global_knowledge ---

def test_scene_exposes_global_knowledge():
    config = ExperimentConfig(
        agents=[],
        actions=[],
        global_knowledge={"doc1": {"chunks": [{"text": "shared"}]}},
    )
    scene = ExperimentScene(config)
    assert scene.global_knowledge == config.global_knowledge


# --- Test 8: get_rag_context does NOT call semantic search when empty ---

@patch("fos.backend.services.documents.composite_rag_retrieval")
def test_rag_context_no_semantic_when_empty(mock_retrieval):
    agent = _make_agent()
    result = agent.get_rag_context("query")
    mock_retrieval.assert_not_called()
    assert result == ""
