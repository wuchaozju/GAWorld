# GAWorld - FOS integration How-To Guide

## 1. GAWorld + FOS AI Scientist

The FOS bridge generates a structured research observation prompt from
simulation output, ready to paste into FOS → AI Scientist → "Analyze
Research Text".

### Quick Start (CLI)

```bash
# Auto mode — read simulation output and generate prompt
python scripts/gaworld-to-fos-prompt.py --output-dir output/

# With a focus hint
python scripts/gaworld-to-fos-prompt.py --output-dir output/ \
    --hint "Look for social withdrawal"

# Include an English summary of Chinese simulation data
python scripts/gaworld-to-fos-prompt.py --output-dir output/ --english

# Manual mode — wrap a researcher observation instead
python scripts/gaworld-to-fos-prompt.py --manual "Agent X showed reduced interaction after policy Y"

# Manual mode from a file
python scripts/gaworld-to-fos-prompt.py --manual-file observations.txt
```

### Quick Start (Dashboard)

1. Run a simulation.
2. Open the **FOS Export** panel.
3. (Optional) Enter an "Analyst Hint" to focus the LLM analysis.
4. (Optional) Check "English summary" to also get a translated summary.
5. Click **Generate FOS Prompt**.
6. Click **Copy to Clipboard** and paste into FOS → AI Scientist →
   "Analyze Research Text".

### Python API

```python
from pathlib import Path
from gaworld.integrations.fos_prompt import (
    generate_fos_prompt,
    generate_manual_fos_prompt,
)

# Auto mode
result = generate_fos_prompt(
    output_dir=Path("output/"),
    hint="Look for economic anxiety",
    english=True,
)
print(result["prompt"])   # FOS-ready prompt string
print(result["summary"])  # English summary (None if english=False)

# Manual mode
prompt = generate_manual_fos_prompt(
    observation="Agent X showed reduced social interaction after policy Y",
    hint="Social withdrawal patterns",
)
print(prompt)
```

### What FOS Does

The generated prompt contains simulation data (agent profiles, actions,
diaries, memory, state trajectories) wrapped for FOS's AI Scientist. FOS
then suggests experimental designs, hypotheses, and follow-up studies based
on the observation.



## 2. Language (English / Chinese)

### Dashboard (Web UI)

The dashboard has EN/CN toggle buttons in the masthead. Click to switch. The
choice persists in `localStorage` under key `gaworld-lang`.

Locale JSON files live at `site/dashboard/locales/en.json` and
`site/dashboard/locales/zh-CN.json`. The i18n system (`site/dashboard/i18n.js`)
is vanilla JS — no build step. Any element with a `data-i18n` attribute is
translated automatically when the locale changes.

### Simulation Output (Python)

```python
from gaworld.i18n import t, eng

t("sim.running")   # → "运行中" (Chinese, default)
eng("sim.running") # → "Running"  (English)
```

- `t(key)` — returns Chinese translation, falls back to English, then the key.
- `eng(key)` — returns English, falls back to the key.
- `available_locales()` — lists `{"code": ..., "label": ...}` for all
  discovered locale files in `site/dashboard/locales/`.

The CLI script `scripts/gaworld-to-fos-prompt.py` accepts `--english` to
produce an English summary of (typically Chinese) simulation output.

### Adding a New Language

1. Create `site/dashboard/locales/{code}.json` (e.g. `ja.json` for Japanese).
   Copy the key structure from `en.json` or `zh-CN.json`.
2. The Python module (`gaworld/i18n.py`) auto-discovers it via
   `available_locales()`. The dashboard JS loads it at runtime at
   `/site/dashboard/locales/{code}.json`.


