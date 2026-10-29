"""Core configuration constants for FOS (Future of Society).

Prototype-stage: minimal globals toggled at simulation build time.
"""

import os

# LLM retry attempts per action parse (1 + MAX_REPEAT total attempts)
MAX_REPEAT = 3

# Emotion tracking toggle. When true, agents include an Emotion Update block
# each turn and the system records `emotion_update` events.
EMOTION_ENABLED = False

# RAG Auto-Inject Configuration
RAG_AUTO_INJECT = os.getenv("RAG_AUTO_INJECT", "true").lower() == "true"
RAG_SUMMARY_THRESHOLD = int(os.getenv("RAG_SUMMARY_THRESHOLD", "1000"))
RAG_TOP_K_DEFAULT = int(os.getenv("RAG_TOP_K_DEFAULT", "3"))
