"""
LLM Prompt Testing Framework.

This framework provides comprehensive testing of LLM prompts across all FOS
interaction patterns, with support for multiple models, scenarios, and iterative
prompt improvement.

Main components:
- config: Configuration management
- ollama_client: Ollama API wrapper
- agents: Test agent profile definitions
- scenarios: Scenario configurations for each pattern
- evaluators: Output evaluation logic
- prompt_tuner: Automated prompt improvement
- cross_llm_analyzer: Cross-model comparison and analysis
- csv_reporter: CSV result generation
- run_pattern_test: Single pattern test runner
- run_all_tests: Main entry point for full test suite
- senior_reviewer: Final results reviewer
"""

__version__ = "1.0.0"
