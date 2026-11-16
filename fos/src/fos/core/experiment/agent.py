"""
Experiment Agent - lightweight agent for experiment scenarios.

Unlike legacy agents, ExperimentAgent has no Plan/Thoughts/Emotion.
It only carries properties (demographics), LLM configuration, and
optional RAG documents with embeddings for semantic retrieval.

Contains: ExperimentAgent
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List

from fos.core.llm_config import LLMConfig


@dataclass
class ExperimentAgent:
    """Lightweight agent for experiment scenarios.

    Experiment agents are simpler than legacy agents:
    - No Plan/Thoughts/Emotion tracking
    - Properties come from demographic builder
    - LLM configuration specifies which model to use

    Attributes:
        name: Agent's display name
        properties: Demographic properties (age, profession, traits, etc.)
        llm_config: Which LLM provider/model to use for this agent
        role_prompt: Optional role-specific prompt (Bug C fix)
        action_history: List of actions taken by this agent
        score: Cumulative score for this agent
        knowledge_base: List of knowledge items for KB-based prompting
    """

    name: str
    properties: Dict[str, Any]
    llm_config: LLMConfig
    role_prompt: str | None = None
    provider_id: int | None = None
    action_history: List[Dict[str, Any]] = field(default_factory=list)
    score: int = 0
    knowledge_base: List[Dict[str, Any]] = field(default_factory=list)
    documents: Dict[str, Any] = field(default_factory=dict)
    feedback_buffer: List[str] = field(default_factory=list)

    def add_env_feedback(self, msg: str) -> None:
        """Add environmental feedback to be injected into next prompt.

        Replaces Pipeline B's agent.add_env_feedback().
        The buffer is read by the runner when building the next prompt
        and cleared after each turn.
        """
        self.feedback_buffer.append(msg)

    def clear_feedback_buffer(self) -> None:
        """Clear feedback after it has been injected into a prompt."""
        self.feedback_buffer.clear()

    def get_feedback_text(self) -> str:
        """Return accumulated feedback as a single string."""
        if not self.feedback_buffer:
            return ""
        return "\n".join(self.feedback_buffer)

    def get_properties_dict(self) -> Dict[str, Any]:
        """Return properties as dict for prompt builder."""
        return self.properties

    def get_property(self, key: str, default: Any = None) -> Any:
        """Get a single property value."""
        return self.properties.get(key, default)

    def has_property(self, key: str) -> bool:
        """Check if agent has a property."""
        return key in self.properties

    def get_knowledge_context(self, query: str = "", max_items: int = 3) -> str:
        """Get formatted knowledge context for prompt injection.

        If query is provided, returns top matching items by keyword overlap.
        Otherwise returns first max_items enabled items.
        """
        enabled = [k for k in self.knowledge_base if k.get("enabled", True)]
        if not enabled:
            return ""

        if query:
            query_words = set(query.lower().split())
            scored = []
            for item in enabled:
                combined = f"{item.get('title', '')} {item.get('content', '')}".lower()
                score = sum(1 for w in query_words if w in combined)
                if score > 0:
                    scored.append((score, item))
            scored.sort(key=lambda x: x[0], reverse=True)
            items = [item for _, item in scored[:max_items]]
        else:
            items = enabled[:max_items]

        if not items:
            return ""

        lines = ["Your Knowledge Base:"]
        for i, item in enumerate(items, 1):
            lines.append(f"[{i}] {item.get('title', 'Untitled')}: {item.get('content', '')}")
        return "\n".join(lines)

    def get_rag_context(
        self,
        query: str,
        global_knowledge: Dict[str, Any] | None = None,
        top_k: int = 3,
    ) -> str:
        """Retrieve relevant context using semantic search.

        Uses composite_rag_retrieval() when documents are present
        (semantic search over embeddings). Falls back to keyword-based
        get_knowledge_context() when only knowledge_base items exist.

        Args:
            query: The search query (usually recent context/prompt)
            global_knowledge: Shared knowledge accessible to all agents
            top_k: Maximum number of results to return

        Returns:
            Formatted string ready for prompt injection, or "" if
            no relevant context found.
        """
        global_knowledge = global_knowledge or {}

        # Use semantic search if any documents are available
        has_documents = bool(self.documents)
        has_global = bool(global_knowledge)

        if has_documents or has_global:
            from fos.backend.services.documents import (
                composite_rag_retrieval,
                format_rag_context,
            )
            results = composite_rag_retrieval(
                query=query,
                agent_documents=self.documents,
                global_knowledge=global_knowledge,
                top_k=top_k,
            )
            if results:
                return format_rag_context(results)

        # Fall back to keyword matching for plain knowledge_base items
        if self.knowledge_base:
            return self.get_knowledge_context(
                query=query,
                max_items=top_k,
            )

        return ""
