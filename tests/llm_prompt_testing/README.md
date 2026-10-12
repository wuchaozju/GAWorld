# LLM Prompt Testing Framework

Comprehensive testing framework for validating LLM prompts across all FOS interaction patterns.

## Quick Start

```bash
# Activate virtual environment
.\venv\Scripts\Activate.ps1
$env:PYTHONPATH = "."

# Test Ollama connection
python -m tests.llm_prompt_testing --test-connection

# Run all tests
python -m tests.llm_prompt_testing

# Test a specific pattern
python -m tests.llm_prompt_testing --pattern "Strategic Decisions"

# Test specific scenarios and models
python -m tests.llm_prompt_testing \
    --scenario prisoners_dilemma \
    --model qwen3:4b \
    --model gemma3:4b-it-qat

# Generate final report only
python -m tests.llm_prompt_testing --report-only
```

## Architecture

```
tests/llm_prompt_testing/
├── __init__.py              # Package initialization
├── __main__.py              # Main entry point
├── config.py                # Configuration management
├── ollama_client.py         # Ollama API wrapper
├── agents.py                # Test agent profiles (archetypal + domain)
├── scenarios.py             # Scenario definitions (18 scenarios)
├── evaluators.py            # Output evaluation (4 criteria)
├── prompt_tuner.py          # Automated prompt improvement
├── cross_llm_analyzer.py    # Cross-model comparison
├── csv_reporter.py          # CSV result generation
├── run_pattern_test.py      # Single pattern test runner
├── run_all_tests.py         # Main test orchestrator
└── senior_reviewer.py       # Final results reviewer
```

## Test Matrix

- **6 Interaction Patterns**: Strategic Decisions, Opinions & Influence, Network & Spread, Markets & Exchange, Spatial & Movement, Open Conversation
- **18 Scenarios**: 3 scenarios per pattern
- **3 Models**: qwen3:4b, gemma3:4b-it-qat, ministral-3:3b
- **54 Base Combinations**: 6 × 3 × 3
- **Up to 810 Total Runs**: With 5 iterations of 3 runs each

## Success Criteria

1. **XML Format Valid**: Output matches required format (Thoughts, Plan, Action)
2. **Action Correct**: Agent uses appropriate actions for the scenario
3. **Role Aligned**: Behavior matches agent's role/personality
4. **No Errors**: No hallucinations, incorrect parameters, or API errors

## Cross-LLM Portability Rule

A prompt is considered "good" only if it works on **2 out of 3 LLMs**.

- **3/3 Pass**: Excellent - fully portable
- **2/3 Pass**: Acceptable - note why 3rd failed
- **1/3 Pass**: Needs improvement - not portable
- **0/3 Pass**: Failed completely - redesign needed

## Agent Profiles

### Archetypal Agents
- **Authority**: Leadership, directive, maintains order
- **Dissenter**: Challenges norms, questions decisions
- **Follower**: Adopts consensus, supportive
- **Analyst**: Data-driven, logical, methodical
- **Mediator**: Seeks compromise, bridges conflicts

### Domain-Specific Agents
- **Farmer**: Resource-focused, territorial, practical
- **Merchant**: Trade-oriented, profit-motivated
- **Guard**: Rule-enforcing, protective
- **CouncilMember**: Decision-focused, deliberative
- **Trader**: Exchange-focused, opportunistic

## Output

Results are written to `test_results/`:

```
test_results/
├── strategic_decisions/
│   ├── prisoners_dilemma.csv
│   ├── stag_hunt.csv
│   └── minimum_effort.csv
├── opinions_influence/
├── network_spread/
├── markets_exchange/
├── spatial_movement/
├── open_conversation/
├── final_report.md          # Overall results with capability matrix
├── senior_review_report.md   # Senior reviewer analysis
└── test.log                # Execution log
```

## CSV Format

Each CSV contains detailed results:

```csv
pattern,scenario,model,iteration,run_number,agent_type,agent_role,
input_prompt,output_raw,xml_valid,action_correct,role_aligned,
no_errors,overall_score,parsed_action,parsed_thoughts,parsed_plan,
token_count,time_ms,error_message,failure_reasons,prompt_version,
cross_llm_status,model_failure_reason,timestamp
```

## Senior Reviewer

The senior reviewer agent:
1. Reviews all CSV outputs from all patterns
2. Generates model capability matrix
3. Identifies critical issues
4. Provides actionable recommendations

## Requirements

- Python 3.12
- Ollama running at http://localhost:11434/v1
- Models installed: gemma3:4b-it-qat, ministral-3:3b

## Model Compatibility

| Model | Status | Notes |
|-------|--------|-------|
| **gemma3:4b-it-qat** | ✅ Compatible | Correctly outputs Action/XML format |
| **ministral-3:3b** | ✅ Compatible | Correctly outputs Action/XML format |
| **qwen3:4b** | ❌ Not Compatible | Cannot reliably output structured Action/XML format. Outputs conversational text instead. |

**Note**: qwen3:4b appears to have a training/alignment limitation that makes it unsuitable for structured agent output requirements. Alternative qwen models (qwen3:7b, qwen2.5:14b) may work better for this use case.

## Dependencies

Install required packages:

```bash
pip install requests pandas
```

## Troubleshooting

**Ollama connection fails:**
- Ensure Ollama is running: `ollama list`
- Check the API URL is correct: `http://localhost:11434/v1`

**Models not found:**
- Pull models: `ollama pull qwen3:4b`

**Tests take too long:**
- Test specific patterns: `--pattern "Strategic Decisions"`
- Test specific scenarios: `--scenario prisoners_dilemma`
- Reduce max_iterations in config.py
