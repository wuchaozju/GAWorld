# GAWorld v2 arXiv system paper

This directory contains the long-form system paper **GAWorld v2: A
Configurable Research Stack for LLM-Based Artificial Societies**, an
extension of the v1 system paper (`../arxiv_gaworld_system/`) that
covers the K6--K8 migrations completed between 2026-07 and 2026-10.

The v1 paper described GAWorld as research infrastructure for building
persistent and situated LLM agent societies, audited at a single
repository commit (`35a551e`) with nine built-in plugins.  This v2 paper
extends the audit to fourteen built-in plugins, multi-tenant world
isolation (K6), hub-and-node distributed execution (K7), and the
parallel-worlds counterfactual engine (K8).  It also adds the Agent
Playground of fourteen game-based probes, the Agent Arena benchmark, the
Research Workbench that compiles a paper or idea into a pre-registered
protocol, the persona-distillation module, and the evidence-class
taxonomy that binds every reported number to a hash, an evidence class,
and the producing code path.

The v1 system paper is independent of this v2 paper: the v1 audit is
preserved in `../arxiv_gaworld_system/`; the v2 audit starts from a
newer commit and explicitly attributes every claim to a v1 archive, a
v2 archive, a synthetic fixture, or a designed protocol.

## Evidence policy

- No new simulation is run and no LLM API is called to prepare this
  paper.
- Architecture claims are checked against current source paths and
  assigned an implementation status (`IMPLEMENTED`,
  `PARTIALLY_INTEGRATED`, `DESIGNED`, `EVIDENCE_INCOMPLETE`,
  `DIAGNOSTIC_FIXTURE`).
- Every reported number cites a byte-level SHA-256 snapshot in
  `artifact_ledger.md` (to be filled in by the authors at submission
  time) and an evidence class (`REAL`, `DIAGNOSTIC`, `SYNTHETIC`,
  `INCOMPLETE`, `DESIGNED`, `FIXTURE`).
- A single run, incomplete treatment, or diagnostic fixture is not
  presented as statistical, causal, population-valid, or real-policy
  evidence.
- The five claim levels from v1 (individual consistency, macro
  correspondence, emergent dynamics, counterfactual response,
  reproducibility) are extended with a sixth, *participant evaluation*,
  to cover the Agent Playground and the Agent Arena.
- Author names, affiliations, email addresses, and ORCIDs remain
  explicit placeholders until supplied by the authors.

## Package map

- `main.tex`: manuscript assembly and author placeholders.
- `sections/01_introduction.tex` through
  `sections/15_conclusion.tex`: fifteen independently reviewable
  manuscript sections.
- `supplementary/K_migrations.tex`, `supplementary/deployment.tex`,
  `supplementary/ethics.tex`: three supplementary sections.
- `figures/`: ten TikZ-rendered vector PDFs (the four new figures for
  v2 are `hub_node.pdf`, `multi_tenant.pdf`, `plugin_assembly.pdf`, and
  `parallel_worlds.pdf`) plus eight dashboard screenshots captured
  against the running GAWorld instance (English UI mode):
  `en_01_console.png`, `en_02_studio.png`, `en_03_research.png`,
  `en_04_parallel.png`, `en_05_games.png`, `en_06_arena.png`,
  `en_07_citymap.png`, `en_09_analytics.png`.
- `references.bib`: verified primary-source bibliography.
- `main.pdf`: the compiled manuscript (48 pages, journal-quality,
  3.0 MB).
- `gaworld-v2-arxiv-source.tar.gz`: the arXiv upload tree (manuscript
  sources, sections, supplementary, figure PDFs and PNGs,
  references).
- `arxiv-source/`: the unpacked arXiv upload tree.
- `ARXIV_SUBMISSION.md`: metadata, source packaging, and upload
  checklist.

## Build

From this directory:

```bash
latexmk -pdf -interaction=nonstopmode -halt-on-error main.tex
```

The command is offline once the TeX dependencies are installed.
`main.pdf` and figure PDFs are deliverables and are intentionally not
ignored.  Auxiliary TeX files and the generated arXiv source tree are
ignored.

The four new v2 vector figures compile in isolation:

```bash
cd figures
for f in hub_node multi_tenant plugin_assembly parallel_worlds; do
  pdflatex -interaction=nonstopmode -halt-on-error $f.tex
done
```

The eight dashboard screenshots were captured against a running
GAWorld instance on port 8766 with the bundled Keqiao (Shaoxing) city
bundle.  Reproduce them with:

```bash
export CODEX_HOME="${CODEX_HOME:-$HOME/.codex}"
export PWCLI="$CODEX_HOME/skills/playwright/scripts/playwright_cli.sh"

for path in console studio research games arena city; do
  "$PWCLI" open "http://127.0.0.1:8766/site/dashboard/${path}.html"
  sleep 1
  "$PWCLI" eval "window.setLocale && window.setLocale('en')"
  sleep 1
  "$PWCLI" screenshot --full-page --filename="screenshots/en_${path}.png"
done

# parallel worlds lives in the console under #worlds
"$PWCLI" open "http://127.0.0.1:8766/console#worlds"
"$PWCLI" eval "window.setLocale && window.setLocale('en')"
"$PWCLI" screenshot --full-page --filename="screenshots/en_04_parallel.png"

# analytics
"$PWCLI" open "http://127.0.0.1:8766/site/dashboard/analytics.html"
"$PWCLI" eval "window.setLocale && window.setLocale('en')"
"$PWCLI" screenshot --full-page --filename="screenshots/en_09_analytics.png"
```

## Bibliography coverage

The verified bibliography is organized around:

- generative agents and grounded or synthetic populations;
- LLM-agent memory, planning, reflection, and situated action;
- social-agent and general agent evaluation;
- agent-based models, artificial societies, and empirical validation;
- parallel and distributed simulation;
- causal inference, multiple testing, and the pre-registration
  literature;
- LLM-based social simulation platforms and benchmarks (Concordia,
  OASIS, AgentSociety, RecSim, SOTOPIA, AgentBench, AgentBoard);
- GAWorld internal proposals and tutorials (multi-tenant, distributed,
  parallel worlds, research workbench, agent playground, agent arena,
  policy simulation, serious games, persona distillation).

Primary papers, proceedings, publishers, DOI records, and official
project pages are preferred over surveys.  A citation is included only
when it supports the specific sentence in which it appears.

## arXiv packaging

The final upload tree is generated under `arxiv-source/` and tested
in isolation.  It contains the manuscript sources, bibliography
inputs, the fifteen section files, the three supplementary files, the
ten figure PDFs required by `main.tex`; it excludes the compiled
manuscript, figure-generation sources, logs, caches, hidden files,
repository data, and unrelated project material.  See
`ARXIV_SUBMISSION.md` for the author-facing checklist.

## Audit utilities

Verify the tarball builds in isolation:

```bash
mkdir -p /tmp/arxiv-test
tar -xzf gaworld-v2-arxiv-source.tar.gz -C /tmp/arxiv-test
cd /tmp/arxiv-test
latexmk -pdf -interaction=nonstopmode -halt-on-error main.tex
```

Verify the manuscript has no unresolved citations or references:

```bash
pdflatex -interaction=nonstopmode main.tex 2>&1 | grep -E 'undefined|Citation|Reference' | head
```

Verify the figures match the v1 reused figures by SHA-256:

```bash
shasum -a 256 figures/*.pdf
```
