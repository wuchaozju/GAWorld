# AAAI-27 GAWorld-Bench Paper Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce an anonymous, evidence-audited, seven-page AAAI-27 Main Technical Track paper and supplementary package for GAWorld-Bench without running new simulations.

**Architecture:** The paper package separates venue assets, manuscript text, bibliography, vector figures, supplementary material, and author-facing submission notes. Every empirical statement is tied to an existing repository artifact and one of four provenance classes; synthetic fixtures are isolated from real-model results. Build and review gates check template provenance, citation integrity, page limits, visual legibility, and overclaiming.

**Tech Stack:** AAAI-27 LaTeX author kit, pdfLaTeX, BibTeX, TikZ/PGF, Ghostscript, `pypdf`, repository Markdown/CSV/JSON artifacts, official proceedings and primary-source literature.

---

## File Structure

- Create `paper/aaai27_gaworld_bench/main.tex`: anonymous seven-page manuscript and all paper tables.
- Create `paper/aaai27_gaworld_bench/references.bib`: primary-source, verified bibliography.
- Create `paper/aaai27_gaworld_bench/supplementary.tex`: protocol definitions, provenance ledger, and expanded results.
- Create `paper/aaai27_gaworld_bench/figures/validation_layers.tex`: TikZ four-layer plus gate validation figure.
- Create `paper/aaai27_gaworld_bench/figures/evidence_pipeline.tex`: TikZ evidence-to-scorecard flow figure.
- Create `paper/aaai27_gaworld_bench/README.md`: build instructions, template provenance, and artifact-to-claim map.
- Create `paper/aaai27_gaworld_bench/SUBMISSION_NOTES.zh-CN.md`: Chinese handoff, risk register, and author checklist.
- Copy the official AAAI-27 `.sty` and `.bst` files, using the exact names supplied in the author kit, into `paper/aaai27_gaworld_bench/`.
- Generate `paper/aaai27_gaworld_bench/main.pdf` and `paper/aaai27_gaworld_bench/supplementary.pdf`; do not stage LaTeX auxiliary files.

### Task 1: Establish the Evidence Ledger

**Files:**
- Create: `paper/aaai27_gaworld_bench/README.md`
- Read: `benchmark/GAWORLD_BENCH_DESIGN.md`
- Read: `benchmark/results/scorecard.json`
- Read: `benchmark/results/reports/report_20260615T005429.md`
- Read: `benchmark/results/reports/report_20260620T133943.md`
- Read: `benchmark/results/reports/report_20260709T075428.md`
- Read: `benchmark/gaworld_bench.py`
- Read: `output/economy/wealth_snapshot.csv`
- Read: `output/economy/conservation_audit.csv`
- Read: `output/comparisons/*/comparison_metrics.csv`

- [ ] **Step 1: Create the paper directories**

Run:

```bash
mkdir -p paper/aaai27_gaworld_bench/figures
```

Expected: the two directories exist and contain no manuscript files yet.

- [ ] **Step 2: Record four provenance classes in the README**

Add an `Evidence policy` section with exactly these classes and uses:

```markdown
| Class | Meaning | Permitted use |
|---|---|---|
| REAL | Existing GAWorld run artifact | Descriptive case-study evidence only unless replicated |
| DIAGNOSTIC | Re-analysis of a REAL artifact | Measurement-sensitivity and failure-analysis claims |
| SYNTHETIC | Fixture produced by `--synthetic` | Benchmark software-path verification only |
| INCOMPLETE | Missing, interrupted, or insufficient output | Report as N/A; exclude from aggregate claims |
```

- [ ] **Step 3: Add the artifact-to-claim map**

Record these IDs and paths in the README:

```markdown
| ID | Class | Repository source | Allowed claim |
|---|---|---|---|
| E-A1 | REAL | `output/economy/wealth_snapshot.csv` | The current one-agent snapshot diverges from selected anchors and cannot establish macro fit |
| E-A2 | REAL | `output/economy/conservation_audit.csv` | Whether the recorded run conserves money within the configured tolerance |
| E-C1 | DIAGNOSTIC | `benchmark/results/reports/report_20260615T005429.md` | Whole-run and post-event windows can produce materially different effects |
| E-C2 | REAL | `benchmark/results/reports/report_20260620T133943.md` | One historical single-seed run produced the listed directions; no significance claim |
| E-C3 | REAL | `benchmark/results/reports/report_20260709T075428.md` | A later single-seed batch produced different directions; no significance claim |
| E-S1 | SYNTHETIC | `benchmark/gaworld_bench.py` synthetic fixture and matching `benchmark/results/scorecard.json` | Harness path executes as designed; no model-validity claim |
| E-B1 | INCOMPLETE | `docs/proposals/results/exp_emotion_contagion/comparison_results.json` | Stylized-fact validity is unassessed |
| E-D1 | INCOMPLETE | `docs/proposals/results/exp_memory_consistency/COMPARISON_REPORT.md` | Persona/memory validity is unassessed because only one treatment completed both phases |
```

- [ ] **Step 4: Verify the synthetic numeric fingerprint**

Run:

```bash
rg -n '0\.08|-0\.12|0\.09|0\.06' benchmark/gaworld_bench.py benchmark/results/scorecard.json
```

Expected: the four exact deltas appear both in the synthetic fixture and the current scorecard.

- [ ] **Step 5: Verify the diagnostic values**

Run:

```bash
rg -n '0\.3368|0\.0068|0\.0201|-0\.0086|-0\.0498|0\.1717|0\.0826|0\.0279' \
  benchmark/results/reports/report_20260615T005429.md \
  benchmark/results/reports/report_20260620T133943.md \
  benchmark/results/reports/report_20260709T075428.md
```

Expected: every number used in the planned audit table is found in one of the three reports.

- [ ] **Step 6: Commit the evidence ledger**

```bash
git add paper/aaai27_gaworld_bench/README.md
git commit -m "document paper evidence provenance"
```

### Task 2: Install and Verify the Official AAAI-27 Author Kit

**Files:**
- Modify: `paper/aaai27_gaworld_bench/README.md`
- Create: official `.sty` file from the AAAI-27 author kit
- Create: official `.bst` file from the AAAI-27 author kit

- [ ] **Step 1: Obtain the kit only from the official conference page**

Open `https://aaai.org/conference/aaai/aaai-27/`, follow `AAAI-27 Author Kit`, and save the archive under
`/tmp/aaai27-author-kit/`. Do not reuse an AAAI-26 style file and do not infer filenames from prior years.

- [ ] **Step 2: Inspect the archive before copying files**

Run:

```bash
find /tmp/aaai27-author-kit -type f | sort
```

Expected: the output includes the official sample `.tex`, one AAAI style `.sty`, and one bibliography
style `.bst`. Record their exact basenames.

- [ ] **Step 3: Copy the style assets without changing them**

Run:

```bash
find /tmp/aaai27-author-kit -type f \( -name '*.sty' -o -name '*.bst' \) \
  -exec cp {} paper/aaai27_gaworld_bench/ \;
```

Expected: exactly one `.sty` and one `.bst` are present in the paper directory.

- [ ] **Step 4: Record template provenance and hashes**

Run:

```bash
shasum -a 256 paper/aaai27_gaworld_bench/*.sty paper/aaai27_gaworld_bench/*.bst
```

Add the official source URL, retrieval date `2026-07-11`, exact filenames, and SHA-256 values to the
README.

- [ ] **Step 5: Verify that the assets were not edited**

Run the same `shasum -a 256` command against the extracted originals and copied files.

Expected: each original/copy pair has an identical hash.

- [ ] **Step 6: Commit the venue assets**

```bash
git add paper/aaai27_gaworld_bench/README.md paper/aaai27_gaworld_bench/*.sty \
  paper/aaai27_gaworld_bench/*.bst
git commit -m "add official aaai27 paper template"
```

### Task 3: Build and Verify the Primary-Source Bibliography

**Files:**
- Create: `paper/aaai27_gaworld_bench/references.bib`
- Modify: `paper/aaai27_gaworld_bench/README.md`

- [ ] **Step 1: Verify venue and policy sources**

Use the official AAAI-27 main-track call and author kit as the only authorities for page limits,
anonymity, supplementary material, and generative-AI policy. Record the URLs in the README.

- [ ] **Step 2: Verify generative-society sources from primary publications**

At minimum, verify and enter BibTeX for Park et al.'s *Generative Agents*, the original SOTOPIA paper,
and the primary publication for any large-scale generative-agent simulation discussed. Use ACM,
conference proceedings, arXiv author records, or project repositories maintained by the authors.

- [ ] **Step 3: Verify agent-based-model validation sources**

At minimum, include primary sources for the ODD protocol, empirical validation of agent-based models,
and generative social science. Verify title, author order, year, venue, volume/pages, DOI, and URL.

- [ ] **Step 4: Verify LLM-agent evaluation sources**

Include primary publications for at least two general LLM-agent benchmarks and one social-agent
benchmark. Select sources that directly support claims about evaluation dimensions, reproducibility, or
social interaction rather than assembling a broad survey.

- [ ] **Step 5: Verify causal and simulation-testing sources**

Add primary sources that justify placebo/negative-control testing, counterfactual simulation, and
sensitivity analysis. Do not cite a source unless its text directly supports the associated claim.

- [ ] **Step 6: Run a bibliography syntax test**

Create a temporary LaTeX file that cites every BibTeX key, then run:

```bash
cd paper/aaai27_gaworld_bench
pdflatex -interaction=nonstopmode bibcheck.tex
bibtex bibcheck
pdflatex -interaction=nonstopmode bibcheck.tex
pdflatex -interaction=nonstopmode bibcheck.tex
```

Expected: BibTeX exits successfully, every entry resolves, and the log contains no `undefined citations`.
Remove `bibcheck.*` after the check.

- [ ] **Step 7: Commit the verified bibliography**

```bash
git add paper/aaai27_gaworld_bench/references.bib paper/aaai27_gaworld_bench/README.md
git commit -m "add verified gaworld bench references"
```

### Task 4: Create the Vector Framework Figures

**Files:**
- Create: `paper/aaai27_gaworld_bench/figures/validation_layers.tex`
- Create: `paper/aaai27_gaworld_bench/figures/evidence_pipeline.tex`

- [ ] **Step 1: Draw the validation hierarchy**

Create a compact TikZ figure with four scientific claim columns: `Macro Fit`, `Emergent Dynamics`,
`Counterfactual Validity`, and `Individual Consistency`. Show `Reproducibility / Cost` as a gate spanning
all four columns. Use shapes and labels, not color alone, to distinguish pass, fail, and unassessed states.

- [ ] **Step 2: Draw the evidence pipeline**

Create a left-to-right TikZ flow:

```text
Run artifacts -> Provenance labels -> Layer-specific checks -> Trust gate -> Scorecard
```

Under `Provenance labels`, show `REAL`, `DIAGNOSTIC`, `SYNTHETIC`, and `INCOMPLETE`. Route synthetic
evidence to `software verification` rather than `model validity`.

- [ ] **Step 3: Compile each figure in a minimal two-column-width harness**

Run a temporary LaTeX harness with each figure inside `\resizebox{\columnwidth}{!}{...}`.

Expected: compilation succeeds without overfull boxes or missing TikZ libraries.

- [ ] **Step 4: Render and inspect the figures**

Render the temporary PDF pages at 150 DPI and confirm that all labels remain readable in grayscale and
that no arrow crosses text.

- [ ] **Step 5: Commit the figures**

```bash
git add paper/aaai27_gaworld_bench/figures
git commit -m "add gaworld bench framework figures"
```

### Task 5: Draft the Anonymous Seven-Page Manuscript

**Files:**
- Create: `paper/aaai27_gaworld_bench/main.tex`
- Modify: `paper/aaai27_gaworld_bench/README.md`

- [ ] **Step 1: Create the official anonymous manuscript scaffold**

Use the exact document class, style import, bibliography style, author-anonymization syntax, and required
packages from the official AAAI-27 sample. Add sections in this order:

```latex
\section{Introduction}
\section{Related Work}
\section{A Layered Validation Framework}
\section{GAWorld-Bench}
\section{Auditing GAWorld}
\section{Limitations, Ethics, and Reproducibility}
\section{Conclusion}
```

- [ ] **Step 2: Draft the introduction around the scientific-instrument question**

State that plausible behavior is not equivalent to validated inference. End with the three approved
contributions: layered framework, executable protocol, and evidence audit. Do not claim state of the art,
real-world prediction, or comprehensive validation.

- [ ] **Step 3: Draft a focused related-work section**

Organize it into generative societies, ABM validation, and LLM-agent evaluation. For each group, state the
specific gap GAWorld-Bench addresses: separation of claim types, provenance-aware scoring, and a
cross-layer trust gate.

- [ ] **Step 4: Define the four scientific layers and cross-cutting gate**

For each layer, define the scientific claim, admissible evidence, pass/fail/unassessed outcome, and failure
mode. Include the validation hierarchy figure and explicitly distinguish parameter recovery from emergent
validation.

- [ ] **Step 5: Specify GAWorld-Bench**

Define the macro relative-error score, known-sign intervention checks, post-event effect window,
placebo threshold, deterministic-mode check, coverage reporting, and trust gate. Present the scorecard as a vector
of layer outcomes; if a composite trend hint is mentioned, label it non-decisional.

- [ ] **Step 6: Create the provenance table**

Include rows for real outputs, diagnostic re-analysis, synthetic fixtures, and incomplete evidence. Each
row must state what claim strength is permitted and give one repository example.

- [ ] **Step 7: Draft the GAWorld audit with only approved evidence**

Report:

- current one-agent Engel coefficient `0.48` versus anchor `0.288` and savings rate `0.05` versus anchor
  `0.35`, alongside the earlier one-agent report values `0.30` and `0.25`, as evidence of sample/version
  sensitivity rather than macro fit;
- traffic-restriction mobility-intent `delta_mean=+0.0068` versus `delta_final=+0.3368`, described as
  approximately 49-fold temporal dilution;
- tax-cut economic-security `delta_mean=-0.0086` versus `delta_final=+0.0201`, described as a sign change
  under the selected window;
- historical single-seed layoff values `econ_security=-0.0498` and `stress=+0.1717` alongside a later
  single-observation batch with `econ_security=+0.0826` and `stress=+0.0078`, described as non-comparable
  to earlier archives because common run metadata are missing;
- Track B, D, and full Track E evidence as unassessed.

Never present the exact synthetic deltas `+0.08`, `-0.12`, `+0.09`, or `+0.06` as real results.

- [ ] **Step 8: Draft limitations, ethics, and reproducibility**

State the lack of multi-seed significance, small populations, incomplete tracks, model/version sensitivity,
and absence of external-validity evidence. Warn against treating generated populations as substitutes for
affected communities. Document artifact paths, seeds when known, aggregation windows, and the boundary
between real and synthetic outputs.

- [ ] **Step 9: Draft the abstract and conclusion last**

The abstract must include the problem, framework, diagnostic findings, and bounded conclusion. The
conclusion must say that the benchmark calibrates evidence and exposes missing validation, not that
GAWorld predicts policy outcomes.

- [ ] **Step 10: Run a prohibited-claim scan**

Run:

```bash
rg -n -i 'statistically significant|proves that|accurately predicts|validated society|state-of-the-art|realistic population' \
  paper/aaai27_gaworld_bench/main.tex
```

Expected: no unsupported occurrence. Any necessary occurrence must be inside an explicit negation or
limitation and reviewed manually.

- [ ] **Step 11: Run a numerical provenance scan**

Run:

```bash
rg -n '0\.48|0\.288|0\.05|0\.35|0\.30|0\.25|0\.0068|0\.3368|-0\.0086|0\.0201|-0\.0498|0\.1717|0\.0826|0\.0078' \
  paper/aaai27_gaworld_bench/main.tex paper/aaai27_gaworld_bench/README.md
```

Expected: each manuscript number has a matching entry in the README artifact map.

- [ ] **Step 12: Commit the complete first draft**

```bash
git add paper/aaai27_gaworld_bench/main.tex paper/aaai27_gaworld_bench/README.md
git commit -m "draft aaai27 gaworld bench paper"
```

### Task 6: Write the Supplement and Chinese Submission Note

**Files:**
- Create: `paper/aaai27_gaworld_bench/supplementary.tex`
- Create: `paper/aaai27_gaworld_bench/SUBMISSION_NOTES.zh-CN.md`

- [ ] **Step 1: Write the supplementary protocol**

Include complete formulas and decision rules for every layer, the full evidence ledger, exact artifact
paths, benchmark version information, and an expanded table of all selected real single-seed runs.

- [ ] **Step 2: Add reproduction commands without launching simulations**

Document commands that re-score existing outputs and inspect provenance. Label live `--run` commands as
future work requiring provider configuration; do not execute them.

- [ ] **Step 3: Add the Chinese contribution summary**

Summarize the research question, three contributions, main diagnostic findings, and why the paper avoids
policy-effect claims.

- [ ] **Step 4: Add the author risk register**

List at least these risks:

```markdown
- Main-track empirical depth is limited by single-seed and incomplete runs.
- The current headline scorecard matches synthetic fixtures and must not be uploaded as real evidence.
- External validity and affected-community consultation are absent.
- All citations and AI-assisted prose require final human-author verification.
- Author names, affiliations, conflict domains, and OpenReview profiles remain to be supplied outside the anonymous draft.
```

- [ ] **Step 5: Commit the supplement and handoff note**

```bash
git add paper/aaai27_gaworld_bench/supplementary.tex \
  paper/aaai27_gaworld_bench/SUBMISSION_NOTES.zh-CN.md
git commit -m "add paper supplement and submission notes"
```

### Task 7: Compile, Enforce Page Limits, and Perform Visual QA

**Files:**
- Modify: `paper/aaai27_gaworld_bench/main.tex`
- Modify: `paper/aaai27_gaworld_bench/supplementary.tex`
- Generate: `paper/aaai27_gaworld_bench/main.pdf`
- Generate: `paper/aaai27_gaworld_bench/supplementary.pdf`

- [ ] **Step 1: Compile the main paper from a clean state**

Run:

```bash
cd paper/aaai27_gaworld_bench
latexmk -C
latexmk -pdf -interaction=nonstopmode -halt-on-error main.tex
```

Expected: exit code 0 and `main.pdf` exists.

- [ ] **Step 2: Compile the supplement**

Run:

```bash
latexmk -pdf -interaction=nonstopmode -halt-on-error supplementary.tex
```

Expected: exit code 0 and `supplementary.pdf` exists.

- [ ] **Step 3: Check citation and layout warnings**

Run:

```bash
rg -n 'Undefined|Citation.*undefined|Reference.*undefined|Overfull|Underfull' main.log supplementary.log
```

Expected: no undefined citations/references and no material overfull boxes. Fix text or layout rather than
shrinking fonts or margins.

- [ ] **Step 4: Enforce the page limit**

Run:

```bash
python - <<'PY'
from pypdf import PdfReader
print(f"Pages: {len(PdfReader('main.pdf').pages)}")
PY
```

Expected: at most nine pages total. Inspect page eight and confirm that all main content ends on page seven
and every later page contains references only.

- [ ] **Step 5: Render all pages for visual inspection**

Run:

```bash
mkdir -p /tmp/gaworld-paper-render
gs -dSAFER -dBATCH -dNOPAUSE -sDEVICE=pngalpha -r150 \
  -sOutputFile=/tmp/gaworld-paper-render/main-%02d.png main.pdf
```

Expected: one PNG per PDF page.

- [ ] **Step 6: Inspect every rendered page**

Check title anonymity, two-column flow, figure readability, table clipping, heading spacing, widows/orphans,
reference formatting, and whether pages eight and nine contain references only. Iterate until no visual
defect remains.

- [ ] **Step 7: Check PDF metadata for deanonymization**

Run:

```bash
python - <<'PY'
from pypdf import PdfReader
for key, value in (PdfReader('main.pdf').metadata or {}).items():
    print(f"{key}: {value}")
PY
```

Expected: `/Author` is empty or anonymous, and no local username or personal identity appears.

- [ ] **Step 8: Commit the compiled artifacts**

```bash
git add paper/aaai27_gaworld_bench/main.tex \
  paper/aaai27_gaworld_bench/supplementary.tex \
  paper/aaai27_gaworld_bench/main.pdf \
  paper/aaai27_gaworld_bench/supplementary.pdf
git commit -m "compile aaai27 gaworld bench submission"
```

### Task 8: Fresh-Reader and Adversarial Review

**Files:**
- Modify: `paper/aaai27_gaworld_bench/main.tex`
- Modify: `paper/aaai27_gaworld_bench/supplementary.tex`
- Modify: `paper/aaai27_gaworld_bench/SUBMISSION_NOTES.zh-CN.md`

- [ ] **Step 1: Predict reader questions**

Prepare questions including:

1. What exactly is new beyond existing ABM validation practice?
2. Which reported results are real runs and which are synthetic fixtures?
3. Does the paper claim GAWorld predicts real policy outcomes?
4. Why is `delta_final` preferable to `delta_mean`, and when could it also mislead?
5. What evidence is missing before causal validity can pass?
6. How does the trust gate differ from a weighted benchmark score?
7. Can another researcher reproduce the audit without calling an LLM?

- [ ] **Step 2: Run a fresh-reader test**

Give a fresh reader only the compiled paper and the questions above. Require answers with page/section
citations and ask it to identify ambiguous or unsupported statements.

Expected: the reader correctly distinguishes REAL, DIAGNOSTIC, SYNTHETIC, and INCOMPLETE evidence and
does not infer a policy-prediction claim.

- [ ] **Step 3: Run an adversarial AAAI review**

Ask a separate fresh reviewer to score novelty, soundness, significance, clarity, reproducibility, ethics,
and fit for the Multiagent Systems area. Require the three strongest rejection arguments and concrete
repairs possible without new experiments.

- [ ] **Step 4: Repair all valid issues**

Prioritize unclear novelty, hidden provenance, unsupported generalization, missing baselines in the
discussion, figure readability, and incomplete reproducibility details. Do not answer an evidence gap by
strengthening prose.

- [ ] **Step 5: Recompile and re-run page checks**

Repeat Task 7 Steps 1--7.

Expected: the final paper remains within the page limit and introduces no undefined references or visual
regressions.

- [ ] **Step 6: Commit reader-tested revisions**

```bash
git add paper/aaai27_gaworld_bench
git commit -m "revise paper after adversarial review"
```

### Task 9: Final Submission Audit

**Files:**
- Modify: `paper/aaai27_gaworld_bench/README.md`
- Modify: `paper/aaai27_gaworld_bench/SUBMISSION_NOTES.zh-CN.md`

- [ ] **Step 1: Verify spec coverage**

Check every acceptance criterion in
`docs/superpowers/specs/2026-07-11-aaai27-gaworld-bench-paper-design.md` and mark it pass/fail in the
Chinese submission note.

- [ ] **Step 2: Check repository scope**

Run:

```bash
git status --short
git diff --stat HEAD~6..HEAD -- paper/aaai27_gaworld_bench docs/superpowers
```

Expected: paper commits touch only the approved paper package and planning documents; unrelated user
changes remain unstaged and unmodified.

- [ ] **Step 3: Remove build debris**

Run:

```bash
find paper/aaai27_gaworld_bench -maxdepth 1 -type f \
  \( -name '*.aux' -o -name '*.bbl' -o -name '*.blg' -o -name '*.fdb_latexmk' \
     -o -name '*.fls' -o -name '*.log' -o -name '*.out' \) -delete
```

Expected: source files, official style assets, PDFs, README, and submission note remain.

- [ ] **Step 4: Verify the final package**

Run:

```bash
find paper/aaai27_gaworld_bench -maxdepth 2 -type f | sort
python - <<'PY'
from pypdf import PdfReader
print(f"Pages: {len(PdfReader('paper/aaai27_gaworld_bench/main.pdf').pages)}")
PY
git status --short
```

Expected: all promised artifacts exist, the main PDF respects the page limit, and no paper file is left
untracked.

- [ ] **Step 5: Record the author-only remaining actions**

The Chinese submission note must end with an unchecked list for author names/affiliations, conflict
domains, OpenReview profile completion, author-review obligations, final human verification of AI-assisted
text, and upload before the AAAI-27 deadlines.

- [ ] **Step 6: Commit the final audit**

```bash
git add paper/aaai27_gaworld_bench/README.md \
  paper/aaai27_gaworld_bench/SUBMISSION_NOTES.zh-CN.md
git commit -m "finalize aaai27 submission audit"
```
