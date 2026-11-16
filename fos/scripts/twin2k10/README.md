# twin2k10 — the 10-experiment Twin-2K logprob study

This folder runs the TWIN2K_UNBLINDING_LOGPROBS_10TASKS study: the ten
Twin-2K survey experiments (23 questions, 19 arms) are put to the same 15
local language models the twin2k6 study used. Every (model, persona,
experiment, arm, blinding) cell is ONE record — 100 personas × 19 arms ×
2 blinding arms = 3,800 records per model, 57,000 records in total.
Choice questions are scored from the first answer token's letter
probabilities (exactly the twin2k6 method); numeric questions are
sampled K=20 times at temperature 1.0 and every sample is parsed and
stored; multi-row questions get one numbered answer per row, also
sampled K=20 times.

## Launch (one command)

```bash
python -m scripts.twin2k10.runner
```

The single command does everything, in order:

1. Creates the run folder `results/unblinding/T2K10-<UTC stamp>/`.
2. Generates the shared 100-persona pool (skipped when the run folder
   already holds one).
3. AUTO-PREFLIGHT: every model answers persona 0 once per experiment arm
   and blinding. Each model is then judged by the pure
   `preflight.decide()` verdict (technical failures only: empty
   top-logprobs, unreadable answer letters, unparseable numeric
   samples). Failed models go into `skipped_models.json`; the full grid
   runs only for the surviving models. If EVERY model fails, the run
   stops and says so.
4. Full grid: for each surviving model — load through the model manager,
   answer all 3,800 cells (19 legs: experiment × blinding), unload.
5. Finalizes `manifest.json` with per-leg record counts.

Useful options: `--models qwen3-4b,glm-4.7-flash` (a comma-separated
subset), `--dry-run` (offline: prints cell counts and checks every
rendered prompt, writes nothing, needs no server), `--smoke` (the live
pre-launch smoke test, below).

## Smoke test (live pre-launch check, --smoke)

Before committing days of hardware to the 57,000-cell launch, run the
smoke test: the smallest model (`qwen3-4b`) answers ONE persona on all
19 arms × 2 blinding arms — 38 cells, every question kind (choice,
numeric K-samples, multi-row) through the real execution path — in
clock-time minutes, not days:

```bash
python -m scripts.twin2k10.runner --smoke
```

A smoke run writes ONLY into its own
`results/unblinding/T2K10-SMOKE-<UTC stamp>/` folder. It never appends
to or creates a production `T2K10-<stamp>` folder, and the production
launch never reads a smoke folder — so smoke records can never pollute
the real grid. (An offline rehearsal of the smoke grid's shape:
`--smoke --dry-run`.)

What to check in the smoke run's records before launching:

1. `PREFLIGHT_REPORT.md` says PROCEED and no `skipped_models.json` was
   written. The built-in verdict already stops on the failure
   signatures: empty `top_logprobs` at the decision token, unparseable
   numeric samples, and multi-row samples that fall short of their
   item's `expected_rows`.
2. Spot-check the records themselves:

   ```bash
   # a. every record saw a decision token (non-empty top_logprobs)
   grep -rc '"top_logprobs": \[\]' results/unblinding/T2K10-SMOKE-<stamp>/
   #    → every count must be 0

   # b. every numeric sample parsed into a number
   grep -rc '"numeric_parse_failures": 0' results/unblinding/T2K10-SMOKE-<stamp>/

   # c. multi-row answers are complete — each record's
   #    multi_numeric_values rows == its expected_rows (10/10 for
   #    false_consensus and prob_matching problem1, 6/6 for problem2)
   python - <<'EOF'
   import json, pathlib
   root = pathlib.Path("results/unblinding/T2K10-SMOKE-<stamp>")
   for path in sorted(root.rglob("records.jsonl")):
       for line in path.read_text().splitlines():
           r = json.loads(line)
           if "expected_rows" in r:
               assert all(len(v) == r["expected_rows"]
                          for v in r["multi_numeric_values"]), path
   print("all multi-row samples complete")
   EOF
   ```

Then launch the full study (without `--smoke`): it starts a fresh
production folder and the two never interact.

## How long will it take

Per model, the grid makes:

- 2,400 choice calls (12 choice arms × 100 personas × 2 blindings), one
  first-token call each;
- 24,000 numeric sample calls (6 numeric arms × 100 × 2 blindings ×
  K=20), each a short generation (≤ 128 tokens);
- 20,000 multi-row sample calls (5 multi-row arms × 100 × 2 blindings ×
  K=20), likewise short.

That is 46,400 calls per model, ≈ 696,000 calls for all 15 models.
Expect multi-day runtime — roughly 2 days on fast hardware with the
small models dominating wall time is optimistic; plan for 2–4+ days.
The run is fully resumable (below), so stopping never wastes finished
work.

## Checking progress

Each leg appends one JSON line per finished record to its
`records.jsonl`, flushed and force-synced as the records land:

```bash
# one leg's record count (100 = complete for a 100-persona pool)
wc -l results/unblinding/T2K10-<stamp>/<model>/allais_blinded/records.jsonl

# records so far, per leg, for one model
find results/unblinding/T2K10-<stamp>/<model> -name records.jsonl \
    -exec wc -l {} +

# the run's rolling progress snapshot
cat results/unblinding/T2K10-<stamp>/progress.json
```

A complete model has 38 leg files × 100 records = 3,800 lines; the whole
study 57,000.

## Resuming after a crash or reboot

Rerun the same command, passing the existing run folder:

```bash
python -m scripts.twin2k10.runner --run-dir results/unblinding/T2K10-<stamp>
```

Every cell already durable in a leg's `records.jsonl` is skipped (a torn
last line from a hard kill is repaired automatically), the finished
preflight verdict is reused, and only the missing cells are called. A
resumed run never duplicates or re-hides a completed record.

## Stopping safely

Ctrl-C (SIGINT) or `kill <pid>` at any moment. Each record is written
and flushed the instant its calls finish (force-synced to disk at least
every 50 records), so the worst case loses only the single cell that was
in flight. Resume as above to continue.

## Outputs

- `<model>/<experiment>_<blinding>/records.jsonl` — one record per cell:
  identity (model, persona_id, experiment, arm, blind), the exact
  prompts + sha256, choice scoring (p_raw / p_norm / branch_mass /
  low_branch_mass, audit top-logprobs), numeric samples (raw text,
  parsed values, parse-failure counts) and multi-row samples likewise.
- `PREFLIGHT_REPORT.md`, `skipped_models.json` — the auto-preflight's
  technical verdicts.
- `manifest.json`, `progress.json` — run facts and a rolling snapshot.

## Layout (for readers of the code)

- `config.py` — every fixed knob (models, files, K=20, thresholds).
- `registry.py` — study model id → manager id / GGUF path mapping.
- `experiments.py` — the ten experiments, arms and their question ids.
- `prompts.py` — the exact system and user prompt texts.
- `scoring.py` — letter folding, score_labels, parse_numeric,
  parse_multi_numeric.
- `cells.py` — the 57,000-cell grid, resume and durable writing.
- `numerics.py` — the K=20 temperature-sample calls.
- `legexec.py` — one cell end to end into its record.
- `preflight.py` — the pure stop-or-proceed verdict + report writer.
- `serving.py` — pool generation and model load/unload plumbing.
- `runner.py` — the launch command itself.
