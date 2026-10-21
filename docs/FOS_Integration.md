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



## 3. Current architecture (GAWorldScene integration)

How a FOS simulation tree (SimTree) launches and drives a GAWorld run:

```
Browser ──> GAWorld dashboard (:8766)  ──serves──>  /fos/  (FOS React app)
            │  forwards /fos/api/* and /fos/uploads/*
            ▼
        FOS backend (:8000)  <── public entry via Caddy :8780 (deployment/public/Caddyfile)
            │
        SimTree ──> GAWorldScene ──> worldrun ──> GAWorld subprocess
        Parallel Worlds (PW) ──> worldrun ──> GAWorld subprocess
```

Ownership split:

- **GAWorld** owns populations, checkpoints and the LLM router runtime
  (`gaworld/llm/` — `LLMRouter` / `call_llm`); the child process resolves
  providers itself at run time.
- **FOS** owns provider/model configuration (Settings → LLM Providers),
  per-agent model assignments, and the failure policy for GAWorld runs.
- **Routing precedence** for every model call in a GAWorld child:
  `explicit override > per-agent > per-task > default` — resolved by one
  function (`tests/test_llm_routing_phase4.py`); there is **no silent
  fallback** to another provider.
- A GAWorld checkpoint is written **after a completed day only**; the FOS
  lifecycle actions **Retry / Fix / Substitute** restore the **last completed
  checkpoint** (`fos/src/fos/backend/services/simtree_lifecycle.py`,
  status `attention_required` on provider failure).
- Per-day agent **state history is an analysis output**, not the checkpoint
  truth; backups are the FOS database plus the GAWorld `output/` tree.

Environment variables (all optional, placeholders — no secrets here):

| Variable | Default | Purpose |
|---|---|---|
| `FOS_SINGLE_USER_MODE` | `false` | single-user mode (no login) |
| `FOS_SINGLE_USER_USERNAME` | `local` | local user name in single-user mode |
| `FOS_SINGLE_USER_ALLOW_REMOTE_BIND` | `false` | allow non-loopback bind in single-user mode |
| `GAWORLD_API_URL` | `http://127.0.0.1:8766` | dashboard API used by FOS |
| `GAWORLD_API_TIMEOUT_S` | `30` | dashboard API call timeout |
| `FRONTEND_BASE_URL` | — | frontend base for links (e.g. `/fos/`) |
| `FOS_GAWORLD_MAX_SUBPROCESSES` | `2` | bounded concurrent GAWorld subprocesses |
| `FOS_GAWORLD_DAY_TIMEOUT_S` | built-in default | per-day wait timeout |
| `GAWORLD_CONFIG_OVERRIDES` | — | JSON config overrides passed to the child |
| `GAWORLD_PATH` / `GAWORLD_LLM_SECRETS_PATH` / `OLLAMA_BASE_URL` | — | child-run locations and local provider |

The branch-day budget is **not** an env var — it is the settings field
`fos_branch_day_budget` (default 200, `fos/src/fos/backend/core/config.py`).

## 4. Integrated deployment (FOS UI + backend under GAWorld)

The built FOS frontend is served by the GAWorld dashboard at `/fos/`; API and
upload requests under `/fos/api/*` and `/fos/uploads/*` are forwarded to the
FOS backend, a **separate process** (default `http://127.0.0.1:8000`, override
with `FOS_BACKEND_URL`). The `/fos` prefix is kept end-to-end — the backend
natively answers `/fos/api` and `/fos/uploads`, so development, GAWorld-direct
and the Caddy `/fos/*` proxy all behave identically.

### Development startup (recommended: the integrated launcher)

The supported integrated startup is `scripts/start_fos_integrated.sh`. It
launches the FOS backend in the background with `FOS_SINGLE_USER_MODE=true`
(only in that backend process's env — standalone FOS deployments keep normal
authentication), binds it to `127.0.0.1` only, then runs the GAWorld dashboard
in the foreground and cleans up the backend on exit.

```bash
scripts/start_fos_integrated.sh
```

Equivalent manual startup (two terminals):

```bash
# Terminal 1 — FOS backend (single-user mode, loopback only)
cd fos && ../.venv-fos-integration/bin/python -m uvicorn fos.backend.main:app \
    --host 127.0.0.1 --port 8000
# single-user mode via normal config (env or fos/.env):
#   FOS_SINGLE_USER_MODE=true
#   FOS_SINGLE_USER_USERNAME=local        # optional, default "local"
#
# Safety: with single-user mode on, the backend refuses to bind a non-loopback
# host unless FOS_SINGLE_USER_ALLOW_REMOTE_BIND=true is also set.

# Terminal 2 — GAWorld dashboard (serves /fos/ and forwards /fos/api, /fos/uploads)
python gaworld/apps/dashboard_server.py
```

Open `http://127.0.0.1:8766/fos/` — in the GAWorld-integrated runtime, FOS
automatically uses the local persisted single user (a local user is
provisioned automatically on first startup, so no FOS login is required);
GAWorld console pages under `/` are unaffected. Standalone FOS deployments
(fos/README.md, fos/docker-compose.yml) keep `FOS_SINGLE_USER_MODE=false`
(default) and therefore normal authentication. Single-user mode is not
intended for broad-network exposure: the backend refuses to bind a
non-loopback host unless `FOS_SINGLE_USER_ALLOW_REMOTE_BIND=true` is also set.
