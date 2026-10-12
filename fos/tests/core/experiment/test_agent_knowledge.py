"""
Tests for ExperimentAgent knowledge context assembly.

Covers lines 54-83: get_knowledge_context with and without query,
keyword matching, max_items limit, and empty knowledge base.

Contains: TestKnowledgeContextNoQuery, TestKnowledgeContextWithQuery,
          TestKnowledgeContextEdgeCases
"""


from fos.core.experiment.agent import ExperimentAgent
from fos.core.llm_config import LLMConfig


def _agent(kb=None, **kw):
    """Create an ExperimentAgent with optional knowledge base."""
    defaults = dict(
        name="TestAgent",
        properties={},
        llm_config=LLMConfig(dialect="mock"),
    )
    defaults.update(kw)
    if kb is not None:
        defaults["knowledge_base"] = kb
    return ExperimentAgent(**defaults)


# ---------------------------------------------------------------------------
# Knowledge Context Without Query
# ---------------------------------------------------------------------------


class TestKnowledgeContextNoQuery:
    """get_knowledge_context with no query returns first max_items."""

    def test_returns_first_items_by_default(self):
        """Without query, returns first 3 enabled items."""
        kb = [
            {"title": f"Item {i}", "content": f"Content {i}", "enabled": True}
            for i in range(5)
        ]
        a = _agent(kb=kb)
        ctx = a.get_knowledge_context()
        assert "Item 0" in ctx
        assert "Item 2" in ctx
        assert "Item 3" not in ctx

    def test_max_items_respected(self):
        """max_items parameter limits returned items."""
        kb = [
            {"title": f"Item {i}", "content": f"Content {i}", "enabled": True}
            for i in range(5)
        ]
        a = _agent(kb=kb)
        ctx = a.get_knowledge_context(max_items=1)
        assert "Item 0" in ctx
        assert "Item 1" not in ctx

    def test_disabled_items_excluded(self):
        """Disabled items are filtered out."""
        kb = [
            {"title": "Enabled", "content": "Yes", "enabled": True},
            {"title": "Disabled", "content": "No", "enabled": False},
        ]
        a = _agent(kb=kb)
        ctx = a.get_knowledge_context()
        assert "Enabled" in ctx
        assert "Disabled" not in ctx


# ---------------------------------------------------------------------------
# Knowledge Context With Query
# ---------------------------------------------------------------------------


class TestKnowledgeContextWithQuery:
    """get_knowledge_context with query returns keyword-matched items."""

    def test_matching_query_returns_items(self):
        """Items matching query keywords are returned."""
        kb = [
            {"title": "Climate Policy", "content": "Environmental regulations", "enabled": True},
            {"title": "Tax Reform", "content": "Economic policy changes", "enabled": True},
        ]
        a = _agent(kb=kb)
        ctx = a.get_knowledge_context(query="climate environment")
        assert "Climate Policy" in ctx
        assert "Tax Reform" not in ctx

    def test_no_matching_query_returns_empty(self):
        """When no items match the query, returns empty string."""
        kb = [
            {"title": "Sports", "content": "Football and basketball", "enabled": True},
        ]
        a = _agent(kb=kb)
        ctx = a.get_knowledge_context(query="quantum physics")
        assert ctx == ""

    def test_query_matching_is_case_insensitive(self):
        """Query matching works regardless of case."""
        kb = [
            {"title": "Big Data", "content": "Data analysis techniques", "enabled": True},
        ]
        a = _agent(kb=kb)
        ctx = a.get_knowledge_context(query="BIG DATA")
        assert "Big Data" in ctx

    def test_query_ranks_by_word_overlap(self):
        """Items with more matching words are ranked higher."""
        kb = [
            {"title": "AI Ethics", "content": "Ethics in artificial intelligence", "enabled": True},
            {"title": "AI Safety", "content": "Safety protocols", "enabled": True},
        ]
        a = _agent(kb=kb)
        ctx = a.get_knowledge_context(query="AI ethics artificial")
        lines = ctx.split("\n")
        # AI Ethics should appear before AI Safety
        ethics_idx = next(i for i, line in enumerate(lines) if "AI Ethics" in line)
        safety_idx = next((i for i, line in enumerate(lines) if "AI Safety" in line), -1)
        assert ethics_idx < safety_idx


# ---------------------------------------------------------------------------
# Edge Cases
# ---------------------------------------------------------------------------


class TestKnowledgeContextEdgeCases:
    """Edge cases for get_knowledge_context."""

    def test_empty_knowledge_base(self):
        """Empty knowledge base returns empty string."""
        a = _agent(kb=[])
        assert a.get_knowledge_context() == ""

    def test_all_disabled(self):
        """All items disabled returns empty string."""
        kb = [
            {"title": "X", "content": "Y", "enabled": False},
        ]
        a = _agent(kb=kb)
        assert a.get_knowledge_context() == ""

    def test_output_format(self):
        """Output includes 'Your Knowledge Base:' header and numbered items."""
        kb = [
            {"title": "Rules", "content": "Follow the rules", "enabled": True},
        ]
        a = _agent(kb=kb)
        ctx = a.get_knowledge_context()
        assert ctx.startswith("Your Knowledge Base:")
        assert "[1] Rules: Follow the rules" in ctx

    def test_untitled_item(self):
        """Items without title use 'Untitled'."""
        kb = [
            {"content": "Some info", "enabled": True},
        ]
        a = _agent(kb=kb)
        ctx = a.get_knowledge_context()
        assert "Untitled: Some info" in ctx
