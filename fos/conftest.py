import sys
from pathlib import Path

target = str(Path(__file__).parent / "tests" / "llm_prompt_testing")
sys.path.insert(0, target)
