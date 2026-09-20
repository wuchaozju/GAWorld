# GAWorld arXiv System Paper Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce an English, single-column, arXiv-ready system paper titled *GAWorld: Building Persistent and Situated LLM Agent Societies* using only existing repository code, documentation, and result artifacts.

**Architecture:** The paper package separates manuscript sections, verified bibliography, vector figures, evidence provenance, and arXiv packaging notes. The narrative moves from persistent agents to the situated urban and societal substrate, then to experimental interfaces and existing capability cases. Every architecture claim is checked against current code, and every quantitative example is linked to a pre-existing artifact with an explicit evidence status.

**Tech Stack:** PDFLaTeX, BibTeX/natbib, standard `article` class, TikZ/PGF, Ghostscript, `pypdf`, repository Python/Markdown/CSV/JSON/JSONL artifacts, and official arXiv submission guidance.

---

## File Structure

Create the following package without modifying simulator or experiment code:

```text
paper/arxiv_gaworld_system/
├── .gitignore                     # LaTeX build debris only
├── README.md                      # package map and build commands
├── ARXIV_SUBMISSION.md            # metadata, category, archive, and upload checklist
├── artifact_ledger.md             # implementation and result provenance
├── main.tex                       # preamble, title page, abstract, section assembly
├── references.bib                 # verified primary-source bibliography
├── sections/
│   ├── 01_introduction.tex
│   ├── 02_design_goals.tex
│   ├── 03_related_work.tex
│   ├── 04_agent_lifecycle.tex
│   ├── 05_execution_architecture.tex
│   ├── 06_memory_cognition.tex
│   ├── 07_societal_substrate.tex
│   ├── 08_experiment_workflow.tex
│   ├── 09_interfaces_deployment.tex
│   ├── 10_capability_cases.tex
│   ├── 11_validation_boundaries.tex
│   └── 12_limitations_ethics_roadmap.tex
├── figures/
│   ├── gaworld_at_a_glance.tex/.pdf
│   ├── system_architecture.tex/.pdf
│   ├── agent_lifecycle.tex/.pdf
│   ├── memory_growth.tex/.pdf
│   ├── experiment_flow.tex/.pdf
│   └── capability_matrix.tex/.pdf
└── arxiv-source/                  # generated clean upload tree, not working sources
```

`main.pdf` and `gaworld-arxiv-source.tar.gz` are generated deliverables. Auxiliary files remain ignored.

### Task 1: Freeze the Audit Scope and Evidence Ledger

**Files:**
- Create: `paper/arxiv_gaworld_system/.gitignore`
- Create: `paper/arxiv_gaworld_system/README.md`
- Create: `paper/arxiv_gaworld_system/artifact_ledger.md`
- Read: `README.md`
- Read: `README.zh-CN.md`
- Read: `docs/EXPERIMENTS_REPORT.md`
- Read: `docs/proposals/2026-07-11-microkernel-plugin-architecture.md`
- Read: `paper/aaai27_gaworld_bench/README.md`

- [ ] **Step 1: Record the starting repository state**

Run from the repository root:

```bash
git rev-parse HEAD
git branch --show-current
git status --short
```

Expected: record the exact commit and dirty paths in a private work note. Do not clean, reset, stage, or
modify pre-existing paths. The manuscript must not claim the commit alone identifies result artifacts when
the tree is dirty.

- [ ] **Step 2: Create the paper directory tree**

Run:

```bash
mkdir -p paper/arxiv_gaworld_system/{sections,figures,arxiv-source}
```

Expected: all four directories exist. Do not add a new root-level Python module.

- [ ] **Step 3: Add the LaTeX ignore policy**

Create `.gitignore` with exactly:

```gitignore
*.aux
*.bbl
*.blg
*.fdb_latexmk
*.fls
*.log
*.out
*.toc
*.synctex.gz
arxiv-source/
gaworld-arxiv-source.tar.gz
```

Do not ignore `main.pdf` or figure PDFs because both are deliverables.

- [ ] **Step 4: Define implementation-status semantics in the ledger**

Add this table to `artifact_ledger.md`:

```markdown
| Status | Meaning | Permitted manuscript wording |
|---|---|---|
| IMPLEMENTED | Connected to the current runtime and inspectable in source | "GAWorld implements/provides..." |
| PARTIALLY_INTEGRATED | Code exists and at least one dispatch path is connected, but compatibility paths remain | "GAWorld has begun integrating..." |
| DESIGNED | Proposal or dormant code exists without a verified current runtime path | "The design specifies..." |
| EVIDENCE_INCOMPLETE | A result artifact is missing, interrupted, unreplicated, or insufficient | "The current archive does not assess..." |
```

- [ ] **Step 5: Add the architecture claim map**

Map each paper subsystem to current source before drafting:

```markdown
| Claim ID | Status | Current sources | Allowed claim |
|---|---|---|---|
| S-KERNEL | PARTIALLY_INTEGRATED | `gaworld/kernel/*.py`, `gaworld/sim/pipeline.py` | Microkernel skeleton and cognition dispatch points are connected; migration is incomplete |
| S-PLUGIN-POLICY | IMPLEMENTED | `gaworld/policy/plugin.py`, `gaworld/policy/intervention.py` | Intervention subsystem has a plugin adapter |
| S-AGENT | IMPLEMENTED | `gaworld/core/agent.py`, `gaworld/sim/agents_loader.py` | Typed adapter and seeded persistent profiles/states |
| S-MEMORY | IMPLEMENTED | `gaworld/memory/`, `gaworld/sim/_memory_recall.py` | Episodic persistence, recall, lifecycle, consolidation, and decay paths exist |
| S-WORLD | IMPLEMENTED | `gaworld/world/`, `gaworld/env/system.py` | Graph-based city, local physical state, weather, and events |
| S-SOCIETY | IMPLEMENTED | `gaworld/social/network.py`, `gaworld/economy/finance.py`, `gaworld/events/life.py` | Social, finance, and life-event mechanisms exist |
| S-WORK | IMPLEMENTED | `gaworld/work/` | Agents can route work tasks and persist generated artifacts |
| S-INTERFACE | IMPLEMENTED | `gaworld/apps/`, `site/dashboard/`, `site/simviz/` | Dashboard, Agent Studio, services, and trace replay are present |
| S-DISTRIBUTED | IMPLEMENTED | `gaworld/distributed/comm.py`, `gaworld/apps/distributed_comm_server.py` | Relay-based distributed communication mode exists |
```

Verify each row by opening the named files. Downgrade status whenever the source does not show a current
call path.

- [ ] **Step 6: Add the result-artifact map**

Add rows for the four narrative cases and the complete capability matrix:

```markdown
| Evidence ID | Status | Repository source | Allowed use |
|---|---|---|---|
| E-MEM | EVIDENCE_INCOMPLETE | `docs/proposals/results/exp_memory_consistency/COMPARISON_REPORT.md` | Show cross-phase artifacts and disclose that only one treatment completed both phases |
| E-POLICY | EVIDENCE_INCOMPLETE | `docs/proposals/results/exp_policy_framework/*/comparison_summary.md` and `comparison_metrics.csv` | Demonstrate matched event/baseline workflow; no real policy-effect claim |
| E-INFO | EVIDENCE_INCOMPLETE | `docs/proposals/results/exp_misinfo_spread/comparison_results.json` | Demonstrate information-intervention metrics and inactive fields |
| E-ECON | COMPLETE | `docs/proposals/results/exp_macro_economy/run_42/state/agent_state_history.csv` and `wellbeing_report.md` | Demonstrate multivariate trace production; descriptive values only |
| E-NET | EVIDENCE_INCOMPLETE | network-evolution result report | Report initialization and missing interactions, not emergent network laws |
| E-BENCH | DIAGNOSTIC_FIXTURE | `benchmark/gaworld_bench.py`, `benchmark/results/scorecard.json` | Verify benchmark software path only |
```

If an exact wildcard resolves to no file, replace the source with the actual existing artifact or mark it
missing; never invent a path.

- [ ] **Step 7: Hash every quantitative source**

Run `shasum -a 256` on every artifact cited in the ledger and paste the complete hash beside its path.

Expected: every number later included in the paper can be tied to an exact byte sequence. The ledger notes
that hashes identify the audited snapshot, not a universally reproducible simulator release.

- [ ] **Step 8: Write README scope and build policy**

State that the paper uses no new simulation or LLM API calls, is separate from the AAAI validation paper,
uses author placeholders, and is built with:

```bash
latexmk -pdf -interaction=nonstopmode -halt-on-error main.tex
```

- [ ] **Step 9: Verify ledger completeness**

Run:

```bash
rg -n 'IMPLEMENTED|PARTIALLY_INTEGRATED|DESIGNED|EVIDENCE_INCOMPLETE|DIAGNOSTIC_FIXTURE' \
  paper/arxiv_gaworld_system/artifact_ledger.md
rg -n 'T[B]D|T[O]DO|unknown path|fill later' \
  paper/arxiv_gaworld_system/artifact_ledger.md
```

Expected: all five status terms appear; the placeholder scan prints nothing.

- [ ] **Step 10: Commit the evidence foundation**

```bash
git add paper/arxiv_gaworld_system/.gitignore \
  paper/arxiv_gaworld_system/README.md \
  paper/arxiv_gaworld_system/artifact_ledger.md
git commit -m "document arxiv paper evidence"
```

### Task 2: Build and Verify the Primary-Source Bibliography

**Files:**
- Create: `paper/arxiv_gaworld_system/references.bib`
- Modify: `paper/arxiv_gaworld_system/README.md`
- Read: `paper/aaai27_gaworld_bench/references.bib`

- [ ] **Step 1: Define the literature buckets**

Add a bibliography checklist to the README with these buckets:

```markdown
- Generative agents and grounded/synthetic populations
- LLM-agent architecture, memory, planning, and tool use
- Social-agent and general agent evaluation
- Agent-based models, artificial societies, and empirical validation
- Urban, economic, and network simulation when directly relevant
- Reproducibility, negative controls, and simulation methodology
```

- [ ] **Step 2: Re-verify reusable AAAI references**

For each reused entry, open the publisher, proceedings, DOI, OpenReview, or arXiv author page and verify
title, author order, year, venue, pages, DOI, and arXiv identifier. Reuse at minimum the primary sources for
Generative Agents, grounded individual simulation, SOTOPIA, AgentBench, AgentBoard, ODD, empirical ABM
validation, generative social science, and negative controls.

- [ ] **Step 3: Add architecture and memory sources**

Add only primary publications that directly support the system comparison. Candidate claims requiring a
source are persistent memory, reflection/planning loops, situated or embodied action, modular agent
execution, and multi-agent social simulation. Do not cite a survey when the original system paper is
available.

- [ ] **Step 4: Verify every BibTeX key with a temporary all-citations document**

Create `bibcheck.tex` temporarily:

```tex
\documentclass{article}
\begin{document}
\nocite{*}
\bibliographystyle{plainnat}
\bibliography{references}
\end{document}
```

Run:

```bash
pdflatex -interaction=nonstopmode -halt-on-error bibcheck.tex
bibtex bibcheck
pdflatex -interaction=nonstopmode -halt-on-error bibcheck.tex
pdflatex -interaction=nonstopmode -halt-on-error bibcheck.tex
rg -n 'undefined citations|Warning--' bibcheck.log bibcheck.blg
```

Expected: all commands succeed and `rg` prints nothing. Remove `bibcheck.*` afterward.

- [ ] **Step 5: Commit the bibliography**

```bash
git add paper/arxiv_gaworld_system/references.bib paper/arxiv_gaworld_system/README.md
git commit -m "add verified arxiv paper references"
```

### Task 3: Scaffold the Single-Column Manuscript

**Files:**
- Create: `paper/arxiv_gaworld_system/main.tex`
- Create: all twelve files under `paper/arxiv_gaworld_system/sections/`

- [ ] **Step 1: Create the arXiv-compatible preamble**

Use this dependency-minimal structure in `main.tex`:

```tex
\documentclass[11pt]{article}
\usepackage[margin=1in]{geometry}
\usepackage[T1]{fontenc}
\usepackage{lmodern}
\usepackage{microtype}
\usepackage{graphicx}
\usepackage{booktabs}
\usepackage{array}
\usepackage{amsmath,amssymb}
\usepackage{enumitem}
\usepackage[dvipsnames]{xcolor}
\usepackage[round,authoryear]{natbib}
\usepackage[colorlinks=true,allcolors=MidnightBlue]{hyperref}
\usepackage[nameinlink,noabbrev]{cleveref}
\setlist{nosep}
\title{GAWorld: Building Persistent and Situated LLM Agent Societies}
\author{Author Name(s)\\Affiliation(s)\\\texttt{email@example.org}}
\date{2026}
```

Do not use `\today`; arXiv warns that rebuilds can change its displayed value.

- [ ] **Step 2: Assemble all section files explicitly**

After the abstract, add `\input{sections/01_introduction}` through
`\input{sections/12_limitations_ethics_roadmap}` in numeric order, then:

```tex
\bibliographystyle{plainnat}
\bibliography{references}
```

- [ ] **Step 3: Seed each section with its final heading and scope sentence**

Each section file must contain its exact `\section{...}` heading and one factual scope sentence. Do not use
unfinished drafting markers or bracketed drafting notes. The abstract may initially state only the approved thesis and
four system contributions; it will be rewritten in Task 9.

- [ ] **Step 4: Compile the scaffold**

```bash
cd paper/arxiv_gaworld_system
latexmk -pdf -interaction=nonstopmode -halt-on-error main.tex
```

Expected: `main.pdf` exists; no missing `\input` file; author placeholders are visible.

- [ ] **Step 5: Commit the scaffold**

```bash
git add paper/arxiv_gaworld_system/main.tex paper/arxiv_gaworld_system/sections
git commit -m "scaffold gaworld arxiv manuscript"
```

### Task 4: Create the Six Core Vector Figures

**Files:**
- Create: the six `.tex` and six `.pdf` files under `paper/arxiv_gaworld_system/figures/`
- Modify: relevant section files to include figures and captions

- [ ] **Step 1: Draw `gaworld_at_a_glance`**

Show three left-to-right blocks:

```text
Research configuration
profiles + city + mechanisms + interventions
        -> persistent situated society
        -> traces + memories + artifacts + comparisons
```

The caption must state that outputs are inspectable simulation artifacts, not observations of a real city.

- [ ] **Step 2: Draw `system_architecture` from verified implementation states**

Use solid boxes for research interfaces, kernel components present in `gaworld/kernel/`, persistent-agent
modules, world modules, and societal mechanisms. Use one dashed overlay labeled `Incremental plugin
migration` around only the partial migration paths. Include the implemented `InterventionPlugin` as the
concrete plugin example.

- [ ] **Step 3: Draw `agent_lifecycle`**

Use this cycle and annotate storage boundaries:

```text
profile/state -> perceive -> recall -> plan -> select/validate action
              -> execute -> reflect -> update state -> record memory -> next tick
```

Show environment, social, economy, interests/skills, and intervention contributions as inputs rather than
hard-coded sequential stages when their integration is event-driven.

- [ ] **Step 4: Draw `memory_growth`**

Show episodic records feeding consolidation and summaries, decay affecting retained memory, and recalled
context influencing habits, intentions, relationships, interests, skills, and later actions. Do not imply
that every link has been causally evaluated.

- [ ] **Step 5: Draw `experiment_flow`**

Show scenario specification, baseline/event branches, event injection, aligned traces, metric extraction,
provenance classification, and human-readable reports. Mark multi-seed inference as required evidence, not
an achieved property of all archived experiments.

- [ ] **Step 6: Draw `capability_matrix`**

Use the ledger statuses rather than performance colors. Rows are the registered experiment families;
columns are scenario setup, completed run artifact, metric activation, replication, and allowed paper use.

- [ ] **Step 7: Compile every figure**

```bash
cd paper/arxiv_gaworld_system/figures
for f in *.tex; do latexmk -pdf -interaction=nonstopmode -halt-on-error "$f"; done
```

Expected: six one-page PDFs and no undefined control sequence or overfull content outside the standalone
bounding box.

- [ ] **Step 8: Render figures for visual inspection**

Render each PDF with Ghostscript `png16m` at 180 dpi and inspect it. Verify that text is legible at the
width used by the single-column manuscript, arrows do not cross labels, grayscale differences are visible,
and implemented/partial status is not encoded by color alone.

- [ ] **Step 9: Commit the figure suite**

```bash
git add paper/arxiv_gaworld_system/figures paper/arxiv_gaworld_system/sections
git commit -m "add gaworld system paper figures"
```

### Task 5: Draft the Agent and Execution Architecture Core

**Files:**
- Modify: `sections/02_design_goals.tex`
- Modify: `sections/04_agent_lifecycle.tex`
- Modify: `sections/05_execution_architecture.tex`
- Read: `gaworld/core/agent.py`
- Read: `gaworld/kernel/*.py`
- Read: `gaworld/sim/pipeline.py`
- Read: `gaworld/hooks.py`
- Read: `gaworld/policy/plugin.py`
- Read: relevant recent commits and migration proposal

- [ ] **Step 1: Write six design goals as testable system properties**

Define persistence, situatedness, composability, controllability, inspectability, and backward-compatible
migration. For each, name one current mechanism and one limitation; avoid generic aspirations.

- [ ] **Step 2: Explain the runtime agent representation**

Describe seed CSV and Markdown profiles, the typed adapter, core state vector, persistent per-agent files,
and compatibility with dictionary-based runtime state. Use exact field names only after checking source.

- [ ] **Step 3: Explain the per-tick cognition lifecycle**

Trace one agent through the current pipeline. Distinguish configured stage order, EventBus contribution
points, legacy direct calls, controller validation, and output recording. Do not claim every planned stage
is replaceable unless current registry/config code demonstrates it.

- [ ] **Step 4: Explain the microkernel skeleton component by component**

For `SimContext`, `Clock`, `EventBus`, `PluginRegistry`, `Controller`, and `Recorder`, state:

1. its current public responsibility;
2. its current runtime connection;
3. what remains on a compatibility path.

Use the concrete policy-plugin migration to demonstrate the architecture; do not list future economy,
memory, or world plugins as completed.

- [ ] **Step 5: Add a migration-state table**

The table columns are `Surface`, `Current implementation`, `Integration status`, `Compatibility path`, and
`Research consequence`. Its rows must be derived from the ledger and current commits.

- [ ] **Step 6: Verify architecture wording against code**

```bash
rg -n -i 'fully plugin|all modules|complete migration|hot swap|deterministic' \
  paper/arxiv_gaworld_system/sections/02_design_goals.tex \
  paper/arxiv_gaworld_system/sections/04_agent_lifecycle.tex \
  paper/arxiv_gaworld_system/sections/05_execution_architecture.tex
```

Expected: each occurrence, if any, is either removed or paired with a precise limitation supported by code.

- [ ] **Step 7: Compile and commit the architecture core**

```bash
cd paper/arxiv_gaworld_system
latexmk -pdf -interaction=nonstopmode -halt-on-error main.tex
cd ../..
git add paper/arxiv_gaworld_system/sections/{02_design_goals,04_agent_lifecycle,05_execution_architecture}.tex
git commit -m "draft gaworld execution architecture"
```

### Task 6: Draft Memory, Cognition, and the Societal Substrate

**Files:**
- Modify: `sections/06_memory_cognition.tex`
- Modify: `sections/07_societal_substrate.tex`
- Read: `gaworld/memory/`
- Read: `gaworld/cognition/realism.py`
- Read: `gaworld/behavior/dynamic.py`
- Read: `gaworld/interests.py`
- Read: `gaworld/skills/`
- Read: `gaworld/world/`
- Read: `gaworld/env/system.py`
- Read: `gaworld/social/network.py`
- Read: `gaworld/economy/finance.py`
- Read: `gaworld/events/life.py`
- Read: `gaworld/work/`

- [ ] **Step 1: Describe the memory lifecycle from storage to recall**

Cover episodic recording, retrieval, consolidation, summaries, decay, spatial preferences, and external RAG.
Separate persistence mechanisms from claims of human-like memory. Cite implementation files in the ledger,
not in the paper prose.

- [ ] **Step 2: Describe behavioral continuity mechanisms**

Explain intentions, habits, relationship context, dynamic interrupts, mood/state updates, curiosity, and
reactive replanning. State which components use deterministic rules and which invoke an LLM.

- [ ] **Step 3: Describe learning and productive capability**

Explain interests, skill progression, experience-to-skill consolidation, mock work market, routing, worker
pool, and persisted artifacts. Do not describe generated artifacts as verified professional work quality.

- [ ] **Step 4: Describe the situated world**

Explain city graph, category-based destination matching, route and transport costs, weather/rush-hour
effects, local occupancy/opening snapshots, anomalies, and learned avoidance preferences.

- [ ] **Step 5: Describe societal mechanisms as coupled state transitions**

Cover the social network, Dunbar tiers/decay, life events, finance/economy, sector pools, tax/social
insurance, cash constraints, credit, investment, and agent payments. Clearly separate accounting invariants
from empirically validated economic behavior.

- [ ] **Step 6: Add a component coupling table**

Use columns `Subsystem`, `Reads`, `Writes`, `Agent-visible consequence`, `Evidence status`. This table must
make implicit shared-state coupling and current plugin boundaries visible.

- [ ] **Step 7: Compile and commit**

```bash
cd paper/arxiv_gaworld_system
latexmk -pdf -interaction=nonstopmode -halt-on-error main.tex
cd ../..
git add paper/arxiv_gaworld_system/sections/{06_memory_cognition,07_societal_substrate}.tex
git commit -m "draft gaworld society substrate"
```

### Task 7: Draft Intervention, Interfaces, and Experiment Workflow

**Files:**
- Modify: `sections/08_experiment_workflow.tex`
- Modify: `sections/09_interfaces_deployment.tex`
- Read: `generative_city_sim.py`
- Read: `gaworld/policy/intervention.py`
- Read: `benchmark/gaworld_bench.py`
- Read: `gaworld/apps/`
- Read: `site/dashboard/`
- Read: `site/simviz/`
- Read: `gaworld/llm/providers.py`
- Read: `gaworld/distributed/comm.py`

- [ ] **Step 1: Document scenario and counterfactual setup**

Explain `run`, `compare-event`, event day/time injection, baseline/event outputs, seed handling, configuration
overrides, and aligned metrics. State that matching a seed does not alone establish causal identification.

- [ ] **Step 2: Document intervention metrics and their activation boundary**

Describe stance, toxicity, misinformation risk, cross-viewpoint exposure, and intervention reward as
implemented metrics. Disclose existing archives in which some fields remain zero or inactive.

- [ ] **Step 3: Explain observability and audit flow**

Describe state histories, timeline JSONL, per-agent memory, diaries/logs, economy ledgers, comparison CSVs,
human-readable reports, and the layered benchmark. State that output formats are currently plural and the
Recorder migration is incomplete.

- [ ] **Step 4: Document user interfaces without turning the paper into a manual**

Give one paragraph each for CLI, Dashboard, Agent Studio, trace visualizer, and interview. For Agent Studio,
state the seven-step structure only if current frontend/server code confirms each step and write-back path.

- [ ] **Step 5: Document deployment boundaries**

Cover LLM provider routing, local/offline possibilities, external-environment service, HTTP retry guard,
and relay-based distributed mode. Do not claim fault tolerance or linear scaling without evidence.

- [ ] **Step 6: Compile and commit**

```bash
cd paper/arxiv_gaworld_system
latexmk -pdf -interaction=nonstopmode -halt-on-error main.tex
cd ../..
git add paper/arxiv_gaworld_system/sections/{08_experiment_workflow,09_interfaces_deployment}.tex
git commit -m "draft gaworld research workflow"
```

### Task 8: Write the Existing Capability Cases and Validation Boundary

**Files:**
- Modify: `sections/10_capability_cases.tex`
- Modify: `sections/11_validation_boundaries.tex`
- Modify: `artifact_ledger.md`
- Read: every evidence source recorded in Task 1

- [ ] **Step 1: Build the complete experiment-status table from artifacts**

Rows are misinformation, polarization, memory consistency, macro economy, policy comparisons, network
evolution, transport behavior, emotion contagion, and ABM validation. Columns are configured horizon,
observed horizon, treatments completed, activated metrics, replication, status, and permitted claim.

Use `---` for unavailable values and explain it as unavailable, not zero.

- [ ] **Step 2: Draft the memory case**

Report only values found in the hashed comparison report. Lead with the system capability: the archive
contains cross-phase memory and state artifacts. Follow immediately with the boundary: only one treatment
completed both phases, so no treatment comparison is supported.

- [ ] **Step 3: Draft the matched policy-workflow case**

Use one example to show branch creation, event timing, trace alignment, and metric extraction. Present
differences as archived contrasts. Explicitly state sample count, missing uncertainty, and version/metadata
comparability limitations.

- [ ] **Step 4: Draft the information-intervention case**

Show which records and fields the system emits. Include the zero/inactive misinformation or toxicity field
as a diagnostic limitation, not as evidence that the simulated society is safe or misinformation-free.

- [ ] **Step 5: Draft the economy--wellbeing trajectory case**

Extract descriptive per-day or per-phase summaries directly from the hashed state history. If an existing
Markdown report supplies derived means, independently recompute them from the CSV with a read-only script
and report any discrepancy. Running such analysis is allowed; invoking the simulator is not.

- [ ] **Step 6: State the validation boundary as a claim-evidence matrix**

Use rows `individual continuity`, `macro fit`, `emergent dynamics`, `counterfactual validity`, and
`reproducibility/cost`. State what the architecture can record, what current artifacts assess, and what
additional evidence would be required. Reuse conclusions from the AAAI audit only after checking current
artifact hashes.

- [ ] **Step 7: Run the overclaim scan**

```bash
rg -n -i 'statistically significant|proves that|demonstrates that the policy|accurately predicts|digital twin|validated population|realistic society|causal effect' \
  paper/arxiv_gaworld_system/sections/10_capability_cases.tex \
  paper/arxiv_gaworld_system/sections/11_validation_boundaries.tex
```

Expected: no unsupported occurrence. Qualified phrases in a limitation sentence must be manually reviewed.

- [ ] **Step 8: Compile and commit**

```bash
cd paper/arxiv_gaworld_system
latexmk -pdf -interaction=nonstopmode -halt-on-error main.tex
cd ../..
git add paper/arxiv_gaworld_system/sections/{10_capability_cases,11_validation_boundaries}.tex \
  paper/arxiv_gaworld_system/artifact_ledger.md
git commit -m "add gaworld capability cases"
```

### Task 9: Complete Related Work, Framing, Abstract, and Discussion

**Files:**
- Modify: `main.tex`
- Modify: `sections/01_introduction.tex`
- Modify: `sections/03_related_work.tex`
- Modify: `sections/12_limitations_ethics_roadmap.tex`

- [ ] **Step 1: Write related work as a comparison, not a citation list**

Organize it around four questions: persistent cognition, situated action, society-level mechanisms, and
scientific evaluation. For each literature family, state what it contributes and the precise system-level
gap GAWorld addresses. Avoid claiming uniqueness when the bibliography does not support an exhaustive
comparison.

- [ ] **Step 2: Write the introduction around one problem statement**

The introduction must establish that LLM-agent research often evaluates individual behavior while
artificial-society work needs connected persistence, environment, societal mechanisms, interventions, and
inspectable evidence. End with the four approved contributions and an explicit non-prediction scope.

- [ ] **Step 3: Write limitations and ethics**

Cover small/incomplete archives, provider stochasticity, prompt and version drift, runtime cost, unfinished
plugin migration, output-schema plurality, representational flattening, lack of consent or lived experience
in synthetic agents, and the prohibition on replacing affected communities or empirical policy evidence.

- [ ] **Step 4: Write a concrete roadmap**

Separate near-term engineering work (domain-plugin migration, unified recorder, metadata manifests) from
research work (multi-seed studies, calibrated individual validation, emergent-network tests, external
anchors, cross-platform evaluation). Label all roadmap items as future work.

- [ ] **Step 5: Rewrite the abstract from the completed manuscript**

The abstract must contain: problem, GAWorld system definition, persistent/situated architecture, interfaces,
existing capability-case scope, and validation boundary. It must not include a performance number unless
that number is essential and fully qualified.

- [ ] **Step 6: Add author placeholders and PDF metadata intentionally**

Keep the visible placeholders exactly until the user supplies authors. Set PDF title and keywords, but do
not put a guessed author into metadata.

- [ ] **Step 7: Run coherence and citation checks**

```bash
cd paper/arxiv_gaworld_system
latexmk -pdf -interaction=nonstopmode -halt-on-error main.tex
rg -n 'undefined citations|undefined references|multiply defined' main.log
python - <<'PY'
import re
from pathlib import Path
tex = Path('main.tex').read_text() + ''.join(p.read_text() for p in sorted(Path('sections').glob('*.tex')))
bib = Path('references.bib').read_text()
cited = {k.strip() for block in re.findall(r'\\cite\w*\{([^}]+)\}', tex) for k in block.split(',')}
keys = set(re.findall(r'@\w+\{([^,]+),', bib))
print('missing:', sorted(cited - keys))
print('unused:', sorted(keys - cited))
PY
```

Expected: log scan is empty; `missing` is empty; every unused entry is removed or intentionally documented.

- [ ] **Step 8: Commit the complete manuscript**

```bash
git add paper/arxiv_gaworld_system/main.tex \
  paper/arxiv_gaworld_system/sections/{01_introduction,03_related_work,12_limitations_ethics_roadmap}.tex
git commit -m "complete gaworld arxiv manuscript"
```

### Task 10: Perform Reader Testing, Visual QA, and Build the arXiv Source Archive

**Files:**
- Modify: any paper source receiving review fixes
- Create: `paper/arxiv_gaworld_system/ARXIV_SUBMISSION.md`
- Create: `paper/arxiv_gaworld_system/gaworld-arxiv-source.tar.gz`

- [ ] **Step 1: Render every manuscript page**

```bash
cd paper/arxiv_gaworld_system
rm -rf /tmp/gaworld-arxiv-pages
mkdir -p /tmp/gaworld-arxiv-pages
gs -q -dSAFER -dBATCH -dNOPAUSE -sDEVICE=png16m -r150 \
  -sOutputFile=/tmp/gaworld-arxiv-pages/page-%03d.png main.pdf
```

Inspect every page. Fix orphan headings, stranded captions, overfull tables, unreadable figure labels,
excess whitespace, broken URLs, and inconsistent status terminology. Recompile after every fix.

- [ ] **Step 2: Run PDF and source diagnostics**

```bash
python - <<'PY'
from pypdf import PdfReader
r = PdfReader('main.pdf')
print('pages:', len(r.pages))
print('metadata:', dict(r.metadata or {}))
print('empty_pages:', [i + 1 for i, p in enumerate(r.pages) if not (p.extract_text() or '').strip()])
PY
rg -n 'Overfull|undefined citations|undefined references|LaTeX Warning' main.log
rg -n -i 'T[B]D|T[O]DO|Author Name\(s\)' main.tex sections README.md ARXIV_SUBMISSION.md
```

Expected: no empty pages or LaTeX errors. The author placeholder may appear only in `main.tex` and the
submission checklist; all other placeholder markers are absent.

- [ ] **Step 3: Perform fresh-reader testing**

Give a fresh reader only `main.pdf` and ask it to state:

1. the system problem and four contributions;
2. the current agent lifecycle;
3. which microkernel/plugin elements are implemented versus partial;
4. what each capability case establishes;
5. what the paper explicitly does not claim.

Any wrong or uncertain answer indicates a manuscript clarity defect. Fix the relevant source rather than
explaining it outside the paper.

- [ ] **Step 4: Perform adversarial review**

Ask a separate reviewer to search for architecture overstatement, result/provenance mismatch, causal or
statistical overclaim, unsupported novelty, citation mismatch, arXiv source leakage, and ethical omissions.
Classify findings P0/P1/P2 and resolve all P0/P1 findings before packaging.

- [ ] **Step 5: Write the arXiv submission guide**

Record:

- title and author/affiliation/email/ORCID fields still requiring user input;
- recommended primary category `cs.MA` and possible cross-list `cs.AI`, explicitly marked as an author
  decision;
- abstract and keyword metadata copied from the final source;
- license as an author decision;
- official source guidance: <https://info.arxiv.org/help/submit_tex.html>;
- the requirement to inspect arXiv's generated PDF before completing submission.

Note that arXiv currently compiles from the archive root, accepts PDFLaTeX-compatible PDF/PNG/JPG figures,
requires needed `.bib` or matching `.bbl`, and warns against auxiliary, hidden, backup, and unused files.

- [ ] **Step 6: Build a clean source tree**

Copy only compilation inputs:

```bash
rm -rf arxiv-source
mkdir -p arxiv-source/sections arxiv-source/figures
cp main.tex references.bib main.bbl arxiv-source/
cp sections/*.tex arxiv-source/sections/
cp figures/*.pdf arxiv-source/figures/
```

Do not include figure `.tex` sources because `main.tex` uses only compiled figure PDFs. Do not include
`main.pdf`, logs, auxiliary files, Git metadata, hidden files, README drafts, or artifact source data.

- [ ] **Step 7: Test the archive in isolation**

```bash
cd arxiv-source
latexmk -pdf -interaction=nonstopmode -halt-on-error main.tex
rg -n 'Overfull|undefined citations|undefined references|LaTeX Warning' main.log
cd ..
tar -czf gaworld-arxiv-source.tar.gz -C arxiv-source \
  main.tex references.bib main.bbl sections figures
tar -tzf gaworld-arxiv-source.tar.gz | sort
```

Expected: isolated compilation succeeds. The archive listing contains only `main.tex`, `references.bib`,
`main.bbl`, twelve section files, and six figure PDFs.

- [ ] **Step 8: Run a secret and path leakage scan**

```bash
rg -n -i 'OPENAI_API_KEY|ANTHROPIC_API_KEY|MINIMAX|/Users/|cw@|localhost|BEGIN.*PRIVATE KEY|token=' \
  arxiv-source
find arxiv-source -name '.*' -o -name '*.log' -o -name '*.aux' -o -name '*.pdf'
```

Expected: the secret/path scan is empty. The `find` command may list only the six intended figure PDFs;
it must not list hidden or auxiliary files.

- [ ] **Step 9: Final commit**

```bash
git add paper/arxiv_gaworld_system
git commit -m "prepare gaworld arxiv system paper"
```

- [ ] **Step 10: Handoff**

Provide clickable links to `main.pdf`, `main.tex`, `artifact_ledger.md`, `ARXIV_SUBMISSION.md`, and
`gaworld-arxiv-source.tar.gz`. Report page count, build result, review fixes, remaining author decisions,
and the exact commit. Do not claim that the paper has been uploaded.
