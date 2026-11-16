"""
Main entry point for the LLM prompt testing framework.

Usage:
    python -m tests.llm_prompt_testing --help
    python -m tests.llm_prompt_testing --pattern "Strategic Decisions"
    python -m tests.llm_prompt_testing --test-connection
"""

from .run_all_tests import main

if __name__ == "__main__":
    main()
