# GAWorld arXiv System Paper Design

**Date:** 2026-07-11  
**Working title:** *GAWorld: Building Persistent and Situated LLM Agent Societies*  
**Target:** arXiv system paper  
**Language and format:** English, single-column long-form article  
**Primary audience:** AI/multi-agent researchers and computational social science researchers

## 1. Objective

Produce the standard project-reference paper for GAWorld. The paper will introduce GAWorld as modular
research infrastructure for constructing persistent, situated, and inspectable LLM-based artificial
societies. It will explain the implemented system, its incremental architecture migration, its research
interfaces, and the kinds of experiments it supports.

The paper will not describe GAWorld as a validated digital twin or as a predictor of real cities. Existing
experiments will demonstrate system affordances and current evidence boundaries, not establish real policy
effects, population-level regularities, or causal conclusions.

No new simulation, benchmark run, or LLM API call is permitted. All system descriptions and quantitative
examples must be derived from repository code, documentation, and artifacts that existed before drafting.

## 2. Central Thesis and Contributions

The central thesis is:

> GAWorld connects persistent agent cognition to an urban environment, social relations, economic
> processes, work, and controlled interventions through an inspectable and increasingly composable
> execution architecture.

The system is organized around the persistent loop:

```text
profile -> perception -> memory/recall -> planning/action
        -> environment and social feedback -> state update -> persistent trace
```

The paper will claim four contributions at system level:

1. **Persistent situated agents.** Profiles, multidimensional state, episodic and consolidated memory,
   intentions, habits, relationships, interests, skills, and growth participate in a cross-day cognition
   loop.
2. **Composable urban society substrate.** A shared substrate connects city maps, local physical
   conditions, mobility, weather and events, social networks, economy and finance, life events, work, and
   policy or information interventions.
3. **Extensible execution architecture.** The paper describes the implemented microkernel skeleton,
   event dispatch points, cognition pipeline, and initial plugin migration. It explicitly separates these
   implemented elements from the still-in-progress domain-plugin migration.
4. **Inspectable experimentation workflow.** Scenario comparison, structured logs, trace playback,
   interviews, Dashboard, Agent Studio, and GAWorld-Bench support examination of agent and society
   behavior. Existing experiments are capability cases, not headline causal findings.

## 3. Narrative Strategy

The paper uses a **Scientific Instrument** argument with a **Generative City** visual narrative.

- The scientific argument defines GAWorld as infrastructure for constructing and inspecting artificial
  societies.
- The visual organization moves from the persistent agent, through the situated world and societal
  mechanisms, to experimental controls and observable artifacts.
- Architecture occupies the center of the paper. Experiments demonstrate what the architecture makes
  possible and where evidence is incomplete.

The paper must consistently distinguish:

- `Implemented`
- `Partially integrated`
- `Designed / planned`
- `Evidence incomplete`

## 4. Manuscript Structure

The target is an 18--25 page single-column article with twelve sections grouped into three parts.

### Part I: Why GAWorld

1. **Introduction** -- research problem, system thesis, contributions, and scope.
2. **Design Goals** -- persistence, situatedness, composability, controllability, inspectability, and
   compatibility.
3. **Related Systems** -- generative agents, LLM-agent benchmarks, agent-based social simulation,
   artificial societies, and agent execution architectures.

### Part II: How GAWorld Works

4. **Agent Lifecycle** -- profile construction, state, perception, recall, planning, action, reflection,
   and persistence.
5. **Execution Architecture** -- current runtime, microkernel skeleton, EventBus, Controller, Recorder,
   cognition pipeline, compatibility paths, and partial plugin migration.
6. **Memory and Cognition** -- episodic records, consolidation and decay, intentions, habits, relationship
   context, RAG, curiosity, interests, and skill formation.
7. **Urban, Social, and Economic Substrate** -- map and local physical environment, mobility, weather,
   social network, life events, economy, finance, work market, and real artifacts.
8. **Intervention and Experiment Workflow** -- environment and policy events, information exposure,
   matched scenario comparison, metrics, trace alignment, and benchmark audit.

### Part III: What GAWorld Supports

9. **Interfaces and Deployment** -- CLI, Dashboard, Agent Studio, visualization, interviews, provider
   routing, external environment, and distributed relay.
10. **Existing Capability Cases** -- evidence matrix plus four representative cases.
11. **Validation Boundaries** -- evidence classes, incomplete tracks, provenance, comparability, and what
    current artifacts do not establish.
12. **Limitations, Ethics, and Roadmap** -- small and incomplete runs, model/provider dependence,
    representational risk, policy-use restrictions, plugin migration, and future evaluation.

The abstract and conclusion will be written after the core sections to ensure they match the final paper.

## 5. Architecture Representation

The primary architecture figure will use three implemented layers and one explicit migration overlay:

1. **Research interfaces:** CLI, Dashboard, Agent Studio, trace playback, and GAWorld-Bench.
2. **Execution core:** `SimContext`, `Clock`, `EventBus`, `PluginRegistry`, `Controller`, and `Recorder`.
3. **Domain substrate:** persistent agents, situated world, and societal mechanisms.
4. **Incremental migration overlay:** solid boundaries for connected implementations and dashed boundaries
   for compatibility paths or incomplete domain-plugin migration.

The paper must not reproduce the aspirational architecture in the microkernel proposal as if it were the
current implementation. Claims will be checked against current source files and recent commits.

## 6. Figure and Table Plan

The planned visual suite is:

1. **GAWorld at a glance:** research questions, system loop, and observable outputs.
2. **System architecture:** interfaces, execution core, agents, world, societal mechanisms, and migration
   boundary.
3. **Agent lifecycle:** perceive, recall, plan, select/validate action, execute, reflect, update state, and
   record memory.
4. **Memory and growth model:** episodes, summaries, decay, habits, intentions, relationships, interests,
   and skills.
5. **Experiment flow:** scenario specification, matched runs, event injection, traces, metrics, and audit.
6. **Capability evidence matrix:** complete, partial, designed, and diagnostic-fixture status.

Optional visuals, included only if they materially improve understanding, are an interface montage and a
timeline for one existing matched scenario. Figures should be vector-first and readable in grayscale.

## 7. Existing Evidence Design

The complete capability matrix will cover:

- misinformation propagation and exposure intervention;
- polarization and echo-chamber experiments;
- memory consistency;
- macro-economy and wellbeing trajectories;
- matched policy-event comparisons;
- social-network evolution;
- transport, emotion-contagion, and ABM-validation designs or incomplete runs.

Four cases receive limited narrative treatment:

1. **Persistent memory case:** demonstrates cross-phase state and memory artifacts while stating that only
   one treatment completed both phases.
2. **Policy counterfactual workflow:** demonstrates event/baseline pairing, time-series recording, and
   metric extraction without interpreting differences as real policy effects.
3. **Information intervention case:** demonstrates stance, exposure, and risk pipelines while disclosing
   inactive or zero-valued metrics.
4. **Economy--wellbeing trajectory:** demonstrates continuous multivariate recording and cross-day
   trajectories as descriptive system output.

Evidence records use four statuses:

- `complete`: sufficient to demonstrate a specific system capability;
- `partial`: an artifact exists, but the run, treatment, or metric is incomplete;
- `designed`: implementation or proposal exists without sufficient result artifacts;
- `diagnostic fixture`: verifies a software path but is not simulation evidence.

Every number in the manuscript must map to a CSV, JSON, JSONL, Markdown report, or other archived source.
Legacy prose claims such as “significant,” “determines,” or “validates a real-world regularity” will not be
reused unless supported by appropriate replicated evidence, which the current audit does not establish.

## 8. Literature and Citation Policy

The bibliography will prioritize primary sources:

- original generative-agent and synthetic-population papers;
- primary social-agent and LLM-agent benchmark papers;
- foundational agent-based model and artificial-society methodology;
- primary work on memory, planning, embodied or situated agents, social simulation, and agent
  architectures;
- official documentation only when needed for implementation or submission facts.

All bibliographic metadata will be verified against publisher, proceedings, DOI, arXiv, or official project
records. The existing AAAI paper bibliography may be reused only after checking that each entry supports
the new claim in context.

## 9. Deliverables

Create `paper/arxiv_gaworld_system/` containing:

- `main.tex` -- English single-column manuscript with explicit author placeholders;
- `main.pdf` -- compiled review artifact;
- `references.bib` -- verified bibliography;
- `figures/` -- original vector figure sources and PDFs;
- `artifact_ledger.md` -- claim-to-repository-source mapping and implementation-state ledger;
- `ARXIV_SUBMISSION.md` -- author placeholders, category guidance, source-package instructions, and final
  submission checklist;
- `README.md` -- package contents and offline build instructions;
- an arXiv-ready source archive created only after source and PDF verification.

The arXiv package will not contain build debris, user-specific paths, Git history, credentials, cached API
content, or unrelated repository files. Uploading the package remains the user's action.

## 10. Quality Gates

Before handoff:

1. verify that no new simulation or LLM API call was made;
2. trace every quantitative statement to a pre-existing artifact;
3. scan for causal, statistical, realism, and prediction overclaims;
4. verify every `Implemented`, `Partially integrated`, and `Designed / planned` architecture statement
   against current code;
5. compile from a clean source package and check citations, references, fonts, figures, and PDF metadata;
6. visually inspect every page of the single-column PDF;
7. test the manuscript with a fresh reader and an adversarial reviewer;
8. preserve unrelated working-tree changes and commit only paper-specific files.

## 11. Success Criteria

The paper succeeds if a first-time reader can accurately explain:

- what scientific and engineering problem GAWorld addresses;
- how a persistent agent moves through the system;
- how individual cognition connects to spatial, social, and economic mechanisms;
- what the current microkernel and plugin migration do and do not implement;
- how researchers configure, observe, compare, and audit simulations;
- which existing artifacts demonstrate system capabilities;
- why those artifacts do not yet establish real-world predictive or causal validity.
