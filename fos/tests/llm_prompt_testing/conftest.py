"""Tell pytest to skip collecting CLI runner scripts, and ensure bare imports work."""
import sys
from pathlib import Path

# Allow bare imports like `from llm_prompt_testing.prompt_v2.x import ...`
sys.path.insert(0, str(Path(__file__).parent))

collect_ignore = [
    "run_pattern_test.py",
    "test_all_platform_actions.py",
]
