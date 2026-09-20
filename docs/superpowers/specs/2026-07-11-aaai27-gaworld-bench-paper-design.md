# AAAI-27 GAWorld-Bench Paper Design

**Date:** 2026-07-11
**Target venue:** AAAI-27 Main Technical Track (Multiagent Systems)
**Working title:** *GAWorld-Bench: A Layered Validation Framework for LLM-Based Artificial Societies*

## 1. Objective

Produce an anonymous, submission-ready AAAI-27 paper that presents GAWorld-Bench as a validation
framework for LLM-based artificial societies. The paper will use GAWorld as an audit case study. It will
not claim that GAWorld is a validated predictor of real societies, and it will not rely on new simulation
runs or new API calls.

The central research question is:

> When does an LLM-based artificial society qualify as a scientific instrument rather than a system that
> merely generates plausible narratives?

The central thesis is that credibility cannot be established by a single realism score or a small set of
plausible examples. Validation must be decomposed into independent evidential layers, while
reproducibility acts as a gate on every higher-level claim.

## 2. Scope and Constraints

- Use only results and artifacts already present in the repository.
- Do not modify the simulator, benchmark implementation, experiment code, or recorded outputs.
- Do not launch local or API-backed simulations.
- Target the AAAI-27 Main Technical Track, with Multiagent Systems as the primary area.
- Follow the AAAI-27 limit of seven pages of main content and nine pages total, with pages after page seven
  reserved for references.
- Produce an anonymous review manuscript.
- Treat synthetic fixtures exclusively as software-path tests, never as empirical evidence about GAWorld.
- Describe single-seed and incomplete experiments as diagnostics or case studies, not statistically
  supported causal findings.

## 3. Claimed Contributions

The paper will make three contributions.

### 3.1 Layered validation framework

The framework separates four scientific claims that are often collapsed in evaluations of generative
societies, plus a cross-cutting reproducibility/cost gate:

1. macro-level empirical fit;
2. emergent or stylized-fact validity;
3. causal and counterfactual validity;
4. individual, persona, and memory consistency;
5. cross-cutting gate: reproducibility, robustness, and cost.

Each scientific layer returns pass, fail, or unassessed; the gate separately returns OK, unverified, or
untrustworthy under a declared deterministic or stochastic reproducibility protocol.

### 3.2 Executable GAWorld-Bench protocol

The benchmark operationalizes provenance, Track A/C checks, coverage reporting, and a deterministic-mode
subtest, while the remaining tracks are protocol specifications. It reports a vector scorecard rather than
allowing a composite average to hide failed or unassessed dimensions.

### 3.3 Evidence audit using GAWorld

The case study demonstrates how the framework identifies overclaiming risks:

- fitting outputs to mechanisms that were already parameterized can create circular validation;
- averaging over pre-event and post-event periods can dilute or reverse an estimated treatment effect;
- single-seed results and synthetic benchmark fixtures cannot establish causal validity;
- explicitly reporting unassessed layers produces a more useful scientific record than imputing favorable
  scores.

The paper's empirical conclusion is that GAWorld-Bench exposes evidence gaps and calibrates claims, not
that GAWorld has already achieved comprehensive real-world validity.

## 4. Evidence Policy and Result Selection

Every quantitative statement will be traceable to a repository artifact and assigned one of four labels:

- **Real observational output:** produced by an actual GAWorld run.
- **Diagnostic re-analysis:** derived from existing real outputs using a different measurement window or
  evaluation rule.
- **Synthetic software fixture:** generated to test the benchmark implementation and excluded from model
  performance claims.
- **Unavailable or incomplete:** reported as `N/A` and excluded from aggregates.

The principal evidence will be:

1. The current macroeconomic snapshot contains one agent with an Engel coefficient of 0.48 and a savings
   rate of 0.05, while an earlier real benchmark report recorded 0.30 and 0.25 for another one-agent
   snapshot. These divergent values are presented as evidence of sample and version sensitivity. The
   apparently favorable values near 0.290 and 0.328 belong to the synthetic fixture and are excluded from
   empirical claims.
2. The traffic-restriction diagnostic in which the mobility-intent difference is approximately +0.0068
   under a whole-run mean and +0.3368 at the post-event endpoint. This illustrates severe temporal
   dilution rather than proving policy predictiveness.
3. Existing tax-cut results in which the sign changes with the evaluation window, illustrating that the
   measurement choice can alter a headline conclusion.
4. Variation across existing single-seed runs for layoffs, tax changes, and traffic restrictions. This is
   evidence that stronger causal claims require multi-seed analysis, not evidence for or against the
   substantive policies.
5. Missing or incomplete evidence for stylized facts, persona consistency, cost, and cross-seed robustness,
   all shown explicitly as unassessed.

The scorecard containing exact deltas of +0.08, -0.12, +0.09, and +0.06, together with perfect placebo and
determinism scores, matches the benchmark's synthetic fixture. It may be shown only in a software
verification example that is visually and textually separated from the real-results table.

## 5. Paper Structure and Page Budget

| Section | Target length | Purpose |
|---|---:|---|
| Introduction | 0.8 page | Motivate validation as the bottleneck and state contributions. |
| Related Work | 0.8 page | Position against generative agents, agent-based model validation, simulation evaluation, and counterfactual testing. |
| Layered Validation Framework | 1.5 pages | Define four scientific layers, evidence hierarchy, scorecard, and cross-cutting gate. |
| GAWorld-Bench Implementation | 1.2 pages | Specify metrics, provenance labels, known-sign tests, placebo, determinism, coverage, and aggregation rules. |
| Audit of GAWorld | 1.5 pages | Present real-output diagnostics, temporal-window sensitivity, non-comparable archives, and missing evidence. |
| Limitations, Ethics, and Reproducibility | 0.8 page | Bound claims, discuss LLM and social-simulation risks, and document reproducibility. |
| Conclusion | 0.3 page | Restate the methodological result and future evaluation requirements. |

References may occupy pages eight and nine. Detailed metric definitions, expanded provenance tables, and
configuration records belong in supplementary material, while every fact required to assess the core
claims remains in the main paper.

## 6. Figures and Tables

The main paper will contain four compact visual elements:

1. **Layered framework figure:** four scientific claim layers with reproducibility as a cross-cutting gate.
2. **Benchmark data-flow figure:** simulation artifacts, provenance classification, layer-specific checks,
   trust gate, and scorecard.
3. **Evidence provenance table:** real, diagnostic, synthetic, and incomplete artifacts with allowed claim
   strength.
4. **Audit results table:** whole-run versus post-event contrasts and non-comparable archived results.

Figures should use vector graphics and remain legible in the AAAI two-column layout and in grayscale.

## 7. Artifact Layout

The manuscript package will be created under `paper/aaai27_gaworld_bench/` and will contain:

- `main.tex`: anonymous AAAI-27 manuscript;
- `references.bib`: verified BibTeX entries;
- `supplementary.tex`: detailed protocols and provenance;
- `figures/`: vector or publication-resolution figures;
- `README.md`: build instructions and artifact-to-claim map;
- a compiled review PDF;
- a Chinese submission note listing contributions, known risks, and author checks required before upload.

## 8. Literature and Citation Policy

Related work will cover four areas: generative-agent societies, validation of agent-based models,
evaluation of LLM agents, and causal or counterfactual simulation. References must be verified against
primary sources or official proceedings. No citation will be invented or copied from an unverified draft.
Repository drafts may guide search terms but are not authoritative bibliographic sources.

## 9. Ethics and Reproducibility

The paper will discuss the danger of treating generated populations as substitutes for real communities,
especially in policy settings. It will state that synthetic agents do not establish external validity and that
profiles, prompts, LLM providers, model versions, seeds, failure rates, and aggregation windows affect the
results.

The anonymous manuscript will include an artifact and reproducibility statement consistent with the
AAAI checklist. Human authors must verify all claims and references and remain responsible for the final
submission and for compliance with AAAI's policy on generative-AI assistance.

## 10. Acceptance Criteria

The deliverable is complete when:

- the manuscript compiles with the official AAAI-27 template;
- the main content fits within seven pages and the full PDF within nine pages;
- every numerical claim maps to a repository artifact and provenance class;
- synthetic fixtures are never described as real GAWorld performance;
- unsupported causal, statistical-significance, and real-world-prediction claims are absent;
- all references have been verified against authoritative sources;
- figures are legible in two-column print layout;
- the supplementary material documents the evaluation protocol and known missing evidence;
- the final package passes a fresh-reader review for ambiguity, contradiction, and overclaiming.

## 11. Out of Scope

- New simulation runs, API calls, or experiment repair.
- New benchmark tracks or changes to benchmark scoring code.
- Claims of policy effectiveness or population-level predictive accuracy.
- Author identification or final OpenReview submission.
- Fabrication or imputation of missing experimental results.
