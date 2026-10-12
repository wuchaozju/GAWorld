# Prompt Engineering v2

Three-layer architecture for LLM agent prompts in social simulations.

## Overview

This module implements an improved prompt engineering architecture based on empirical testing of 3-4B parameter LLMs across 5 game scenarios. It addresses 7 common failure modes through a three-layer defense approach.

## Architecture

### Layer 1: Constrained Decoding
Uses Ollama's JSON schema format parameter to enforce syntactically valid output at the token level.

### Layer 2: Improved Prompts
Game-agnostic prompt builder with:
- Payoff information included
- Round state with history (last 3 rounds)
- `<YOUR_CHOICE>` placeholder (not ambiguous "name")
- "reasoning" field for think-then-constrain
- Explicit markdown prohibition

### Layer 3: Validation + Retry + Fallback
- Fuzzy matching for morphed actions ("listening" -> "listen")
- Integer clamping for out-of-range values
- Markdown fence and think tag stripping
- Random fallback on complete failure

## Quick Start

```python
from tests.llm_prompt_testing.prompt_v2 import (
    get_agent_action,
)
from tests.llm_prompt_testing.prompt_v2.game_configs import PRISONERS_DILEMMA
from tests.llm_prompt_testing.ollama_client import OllamaClient

# Create client
client = OllamaClient()

# Get agent action
action = get_agent_action(
    client=client,
    model="gemma3:4b-it-qat",
    game_config=PRISONERS_DILEMMA,
    round_info={"round": 1, "total_rounds": 10},
    agent_id=1,
)

print(f"Action: {action['action']}")
print(f"Reasoning: {action.get('reasoning', '')}")
```

### Using Comprehension Check (Optional)

```python
from tests.llm_prompt_testing.prompt_v2.comprehension import verify_comprehension
from tests.llm_prompt_testing.prompt_v2.game_configs import PRISONERS_DILEMMA
from tests.llm_prompt_testing.ollama_client import OllamaClient

client = OllamaClient()

# Check model comprehension before running simulation
if verify_comprehension(client, "gemma3:4b-it-qat", PRISONERS_DILEMMA):
    print("Model understands the game!")
else:
    print("Model failed comprehension check - consider using a different model")
```

## Defining New Games

Create a `GameConfig` for any social science scenario:

```python
from tests.llm_prompt_testing.prompt_v2.game_configs import GameConfig

MY_GAME = GameConfig(
    name="My Custom Game",
    description="Full rules and payoff information...",
    action_type="discrete",
    actions=["option_a", "option_b", "option_c"],
    payoff_summary="A=10, B=5, C=2",
)

# Use with get_agent_action
action = get_agent_action(client, model, MY_GAME, round_info)
```

### GameConfig Parameters

- **name**: Display name for the game
- **description**: Full rules and payoff information (included in prompts)
- **action_type**: Either "discrete" (categorical actions) or "continuous" (numeric)
- **actions**: List of valid action names (for discrete games)
- **payoff_summary**: Concise payoff description (e.g., "CC=3, CD=0, DC=5, DD=1")
- **min_value**: Minimum value for continuous games (optional)
- **max_value**: Maximum value for continuous games (optional)

## Available Games

The module includes pre-configured game scenarios:

- **PRISONERS_DILEMMA**: Classic 2x2 cooperation/defection game
- **STAG_HUNT**: Coordination game with risk/reward tradeoff
- **MINIMUM_EFFORT**: Weak link game with threshold dynamics
- **CONSENSUS_GAME**: Group decision making with costly disagreement
- **SPATIAL_COOPERATION**: Network-based public goods game
- **ULTIMATUM_PROPOSER**: Proposer role in ultimatum bargaining
- **ULTIMATUM_RESPONDER**: Responder role in ultimatum bargaining
- **PUBLIC_GOODS**: Multi-player contribution game

## API Reference

### Main Functions

#### `get_agent_action(client, model, game_config, round_info, agent_id, history, ...)`

Get an agent's action using the three-layer architecture.

**Parameters:**
- `client`: OllamaClient instance
- `model`: Model name (e.g., "gemma3:4b-it-qat")
- `game_config`: GameConfig defining the game
- `round_info`: Dict with "round" and "total_rounds" keys
- `agent_id`: Integer ID for this agent
- `history`: List of previous round results (optional)
- `schema`: JSON schema for constrained decoding (optional, auto-generated)
- `suppress_reasoning`: Set True for models that emit thinking in responses (e.g., Qwen)

**Returns:**
Dict with "action" key and optional "reasoning" key.

#### `build_schema(game_config)`

Generate Ollama-compatible JSON schema from GameConfig.

#### `build_system_prompt(game_config)`

Generate system prompt with game rules.

#### `build_user_message(game_config, round_info, agent_id, history)`

Generate user message with current round state and history.

#### `validate_and_clamp(response, game_config)`

Validate and fix LLM response with fuzzy matching and clamping.

### Validation Functions

#### `strip_think_tags(content)`

Remove `<think>...</think>` tags that some models emit.

#### `strip_markdown_fences(content)`

Remove markdown code fences (```) from responses.

## Running Tests

```bash
# Unit tests
pytest tests/llm_prompt_testing/test_*.py -v

# Integration tests (requires Ollama)
python tests/llm_prompt_testing/run_prompt_v2_tests.py
```

## Model Recommendations

Based on empirical testing:

| Model | Success | Notes |
|-------|---------|-------|
| Gemma3 4B IT QAT | 100% | Best overall |
| Qwen3 4B | 100% | Set `suppress_reasoning=True` |
| Ministral 3B | 87% | Usable with constrained decoding |

## Module Structure

```
prompt_v2/
├── __init__.py           # Public API exports
├── agent_caller.py       # Main get_agent_action function
├── game_configs.py       # GameConfig class and pre-defined games
├── prompt_builder.py     # System and user prompt generation
├── schema_builder.py     # JSON schema generation
├── validation.py         # Response validation and cleaning
├── comprehension.py      # Pre-game comprehension checking
└── README.md            # This file
```

## Design Philosophy

1. **Game-agnostic**: Works with any social science game scenario
2. **Empirically grounded**: Design based on actual test results with 3-4B models
3. **Layered defense**: Three independent layers to handle different failure modes
4. **Graceful degradation**: Random fallback ensures simulations never crash
5. **Observable**: Optional reasoning field for debugging and analysis

## Common Failure Modes Addressed

1. **JSON syntax errors** -> Layer 1 (constrained decoding)
2. **Invalid action names** -> Layer 3 (fuzzy matching)
3. **Out-of-range integers** -> Layer 3 (clamping)
4. **Markdown code fences** -> Layer 3 (stripping)
5. **Think tag emissions** -> Layer 3 (stripping) or `suppress_reasoning`
6. **Ambiguous field names** -> Layer 2 (explicit `<YOUR_CHOICE>` placeholder)
7. **No payoff context** -> Layer 2 (payoff_summary in prompt)
