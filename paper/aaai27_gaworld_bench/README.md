# GAWorld-Bench AAAI-27 Paper Package

This directory contains the anonymous review manuscript and supporting material for:

> *GAWorld-Bench: A Layered Validation Framework for LLM-Based Artificial Societies*

The paper targets the AAAI-27 Main Technical Track (Multiagent Systems). It uses only artifacts that
already existed in the repository; no new simulations or LLM API calls are required to reproduce the
audit.

## Venue and Template

- Official conference page: <https://aaai.org/conference/aaai/aaai-27/>
- Official main-track call: <https://aaai.org/conference/aaai/aaai-27/main-technical-track-call/>
- Official Author Kit redirect: <https://aaai.org/authorkit27/>
- Resolved official archive: <https://aaai.org/wp-content/uploads/2026/05/AuthorKit27.zip>
- Retrieved: 2026-07-11
- Archive SHA-256: `e28c6ac9bc6eb3b4e2d849547d2cefb5162610ee39d0a12e0dc62d1126b44a7d`
- `aaai2027.sty` SHA-256: `391bce82815bf698b8e382dd3ae7e30c75d7ab46df140cb295b1266016bc8623`
- `aaai2027.bst` SHA-256: `5db7765ba99de5c1e4686f9b3940a0add9c5e702f2164514462bec130ccb6e3c`

The copied `.sty` and `.bst` files are byte-identical to the official archive. The manuscript uses
`\usepackage[submission]{aaai2027}` and does not modify the style. AAAI-27 permits seven pages of main
content and at most nine pages total; pages after page seven are reserved for references.

## Evidence Policy

| Class | Meaning | Permitted use |
|---|---|---|
| REAL | Existing GAWorld run artifact | Descriptive case-study evidence only unless replicated |
| DIAGNOSTIC | Re-analysis of a REAL artifact | Measurement-sensitivity and failure-analysis claims |
| SYNTHETIC | Fixture produced by `--synthetic` | Benchmark software-path verification only |
| INCOMPLETE | Missing, interrupted, or insufficient output | Report as N/A; exclude from aggregate claims |

`DIAGNOSTIC` describes a declared derivative of a source artifact, not an alternative origin label. A
real report may therefore support both a descriptive `REAL` record and a `DIAGNOSTIC` statistic when the
transformation and permitted claim are explicit.

## Audit Snapshot and Selection Protocol

The audit was assembled on 2026-07-11 from repository HEAD
`424cd46ae5c73bf7cb45ee8c41e1eb6c46c26d38`, but the working tree contained changes. The commit alone
does not identify the audited bytes; the hashes below are controlling identifiers. The search covered the
configured benchmark reports and scorecard, current economy outputs, and known emotion, network, and
memory result directories needed by the five tracks. It is a purposive audit of benchmark-relevant
evidence, not a repository-wide exhaustive log inventory.

| Artifact | SHA-256 |
|---|---|
| `output/economy/wealth_snapshot.csv` | `5461464ea7797d570e3770f869431d546d49c78c011f56c42c02bef708346326` |
| `output/economy/conservation_audit.csv` | `d318ef3478aca9af54aea1c12e20421a3c2bb2e3c90d07273fa6c23f9b3bf92d` |
| `benchmark/results/reports/report_20260615T005429.md` | `fc3bf1840f42f349e0fe23574eb270da18627a2de7959b377590ada76c4ab9ef` |
| `benchmark/results/reports/report_20260620T133943.md` | `6d934e230e11045888b80f7370d69d2cc9499fea269c5d1136b69121a358fa23` |
| `benchmark/results/reports/report_20260709T075428.md` | `56f729dd29aa3ab4208105ef0d2acb573f775c1447882ffa658768b1927376cc` |
| `benchmark/results/scorecard.json` | `fcee85b15dc3aa21473ebaf449467a591d1707dbe5bed59847be9ccb6af5e449` |
| `benchmark/gaworld_bench.py` | `d181ad8d68cca7f9e3f64089c51135f70a68d3d0b5082b766465434f52ceb07e` |
| `docs/proposals/results/exp_emotion_contagion/comparison_results.json` | `e8856de8d5f9bf2af2601a9c2a96f1d059e4400199d0078d98aa7076ee7b99de` |
| `docs/proposals/results/exp_memory_consistency/COMPARISON_REPORT.md` | `473ab06368ad7c775d605a689588a807cad5a87aebb6db960cab80371117e49c` |

## Artifact-to-Claim Map

Paths are relative to the repository root.

| ID | Class | Repository source | Allowed claim |
|---|---|---|---|
| E-A1 | REAL | `output/economy/wealth_snapshot.csv` | The current snapshot has one agent (`engel_coefficient=0.48`, `savings_rate=0.05`) and cannot establish macro fit |
| E-A2 | REAL | `output/economy/conservation_audit.csv` | The recorded one-row audit has zero drift; this is an implementation invariant, not external validity |
| E-A3 | REAL | `benchmark/results/reports/report_20260615T005429.md` | An earlier one-agent snapshot reported `0.30` and `0.25`, showing snapshot/version sensitivity |
| E-C1 | DIAGNOSTIC | `benchmark/results/reports/report_20260615T005429.md` | Whole-run and post-event windows can yield materially different effects |
| E-C2 | REAL | `benchmark/results/reports/report_20260620T133943.md` | One historical single-seed run produced the listed directions; no significance claim |
| E-C3 | REAL | `benchmark/results/reports/report_20260709T075428.md` | A later one-observation-per-intervention batch produced different directions; no significance claim |
| E-S1 | SYNTHETIC | `benchmark/gaworld_bench.py:make_synthetic` and matching `benchmark/results/scorecard.json` | Harness paths execute as designed; no GAWorld-validity claim |
| E-S2 | SYNTHETIC | `benchmark/gaworld_bench.py:make_synthetic_multiseed` | Multi-seed statistics code accepts structured fixtures; no robustness claim |
| E-B1 | INCOMPLETE | `docs/proposals/results/exp_emotion_contagion/comparison_results.json` | Stylized-fact validity is unassessed because state files are absent |
| E-D1 | INCOMPLETE | `docs/proposals/results/exp_memory_consistency/COMPARISON_REPORT.md` | Memory validity is unassessed because only one treatment completed both phases |
| E-E1 | INCOMPLETE | `benchmark/GAWORLD_BENCH_DESIGN.md` | Cost, parse-failure rate, and cross-seed robustness are not implemented or complete |

## Quantitative Audit Ledger

| Claim | Value(s) | Evidence ID | Interpretation |
|---|---:|---|---|
| Current macro snapshot | Engel `0.48`; savings `0.05`; `n=1` | E-A1 | `0.288` has an external Engel source; `0.35` is an internal savings target; insufficient sample |
| Earlier macro snapshot | Engel `0.30`; savings `0.25`; `n=1` | E-A3 | Different run/version; insufficient sample |
| Money-conservation row | max absolute drift `0.0`; `n=1` | E-A2 | Invariant passes for the recorded row only |
| Traffic temporal window | `delta_mean=+0.0068`; `delta_final=+0.3368` | E-C1 | Endpoint magnitude is about 49 times the whole-run mean |
| Tax temporal window | `delta_mean=-0.0086`; `delta_final=+0.0201` | E-C1 | Headline sign changes with aggregation window |
| Historical layoff run | econ security `-0.0498`; stress `+0.1717` | E-C2 | Expected directions in one unreplicated run |
| Later layoff batch | econ security `+0.0826`; stress `+0.0078`; `n=1` | E-C3 | Not comparable to earlier archives; insufficient for a confidence interval |
| Later traffic/tax batch | traffic `+0.0000`; tax econ security `+0.0279`; `n=1` | E-C3 | No statistical inference is possible |

The current `benchmark/results/scorecard.json` is numerically identical to the synthetic fixture on four
contrasts (`+0.08`, `-0.12`, `+0.09`, `+0.06`), placebo, and determinism. This is strong fixture-like
evidence but does not prove lineage without a generation log or input manifest. It must not be cited as
real GAWorld performance.

## Build

From this directory:

```bash
latexmk -pdf -interaction=nonstopmode -halt-on-error main.tex
latexmk -pdf -interaction=nonstopmode -halt-on-error supplementary.tex
```

The official template requires PDFLaTeX, a single manuscript source file, `aaai2027.sty`,
`aaai2027.bst`, and the BibTeX database. Vector figures are compiled separately to PDF and included from
`main.tex`; the review manuscript does not use `\input` for its prose.

## Verify Selected Extractions Without Running GAWorld

These commands inspect existing artifacts only. They verify selected values; they do not regenerate a
complete audit scorecard from a frozen simulation lineage.

```bash
rg -n '0\.3368|0\.0068|0\.0201|-0\.0086' \
  ../../benchmark/results/reports/report_20260615T005429.md

rg -n '0\.08|-0\.12|0\.09|0\.06' \
  ../../benchmark/gaworld_bench.py ../../benchmark/results/scorecard.json

python - <<'PY'
import csv
from pathlib import Path

rows = list(csv.DictReader(Path('../../output/economy/wealth_snapshot.csv').open()))
print(len(rows), rows[0]['engel_coefficient'], rows[0]['savings_rate'])
PY
```

Expected outputs are documented in the quantitative audit ledger above.

## Author Responsibilities Before Submission

Human authors must verify every citation and claim, supply author metadata only in the camera-ready
version, complete OpenReview profiles and conflict information, review the AAAI reproducibility checklist,
and confirm compliance with AAAI's policy on generative-AI assistance.
