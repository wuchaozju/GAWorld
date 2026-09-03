# GAWorld

[English](./README.md) | [中文](./README.zh-CN.md)

GAWorld is a generative multi-agent simulator for urban social behavior experiments.
It combines agent profiles, memory, social influence, environment events, policy shocks,
economy, map-based movement, lightweight platform-intervention evaluation, and LLM-driven
decision making into a replayable simulation workflow.

## Overview

GAWorld is designed as a controllable social experiment sandbox rather than a simple agent demo.
You can:

- run the same agents under different events or policies
- compare counterfactual scenarios in parallel
- preserve memory, habits, and relationships across days
- inspect traces, logs, interviews, and per-agent memory artifacts
- evaluate PolicySim-style recommendation / exposure interventions without extra APIs
- edit runtime parameters and profiles through a local dashboard

Typical use cases:

- urban governance and policy simulation
- agent memory and behavior-consistency experiments
- social behavior and risk propagation studies
- teaching demos for complex systems or agent-based simulation

## Core Loop

Each agent repeatedly goes through:

1. perception
2. planning
3. routine / action generation
4. action execution
5. reflection and memory update

Across days, the simulator accumulates:

- episodic memories
- long-term summaries
- habits by context
- intentions
- relationship shifts
- financial state changes

## Main Features

- Microkernel plugin architecture: every subsystem is a swappable plugin; extend via `CONFIG["plugins"]` or pip entry points without touching the core; configurable 12-stage cognition pipeline; audited runtime interventions (state edits, config changes, agent removal, event injection)
- Seed agents from CSV state values and Markdown profiles
- Create new agents from social media pages or extracted text
- Multi-backend LLM routing: Ollama, OpenAI-compatible, Anthropic-compatible
- External RAG injection from CLI or files
- Policy events and environment events
- PolicySim-inspired recommendation / exposure intervention metrics
- Closed-loop economy simulation with money conservation: sector pools (firms/government/bank), real tax & social-insurance withholding, cash-constrained consumption with credit, common-market-factor investment, agent-to-agent payment routing and friend loans, macro cycles
- Big Five (OCEAN) personality: every resident carries a set of O/C/E/A/N z scores that modulate behaviour through three independently switchable channels — `rules` (deterministic and zero-token: an additive style-fit component in action choice, bounded multipliers on interrupt threshold, spontaneity, social encounter probability, decision noise, impulse bypass and wealth drive, plus a personal emotion set point), `prompt` (anchor sentences injected into the daily-routine, activity-adjustment, goals and news prompts) and `voice` (anchor sentences in the diary only). Keeping the channels separate is what lets an experiment tell "the decisions changed" apart from "the prose changed". Traits are seeded once per run — authored offline into `data/agents_big5.csv` by sampling the five scores first and *then* rewriting each resident's profile prose from them (rather than scoring OCEAN out of prose that was written alongside the person-level state variables), or sampled from a correlated population prior when that file is absent — and never drift, since adult OCEAN change is ~0.1-0.2 SD per decade. An agent with no traits, or a channel switched off, behaves bit-identically to the pre-personality build
- Households and family life: marital status sampled by age band x gender (never married / married / divorced / widowed); residents who match are married *inside the simulation* and **share one home node**, and everyone else gets off-screen family. Children, co-resident elders and flatmates follow. Household type (living alone / flatshare / with parents / cohabiting / couple / nuclear / single-parent / multigenerational) is a **read-out** of the assignment rather than a quota chosen up front. The household then drives the schedule (school runs, homework, elder care, being home for dinner), the ledger (childcare and elder support split by income, partners covering each other's cash shortfalls — all money-conserving), shared family events (one child's fever lands on both parents in the same tick) and in-household emotional contagion. Adjust the population-level distribution from the config panel, or pin one resident's family in Agent Studio so it survives across runs
- Realistic location system with category-based spatial matching, transport cost calculation, rush-hour and weather effects, and commute memory
- Dynamic behavior system: mood-driven spontaneous urges, social encounter chains, need-based interrupts, environment event cascades, and commitment-aware schedule interruption
- Physical environment perception and reactive replanning: per-node crowding / opening-hours awareness, anomaly detection, same-day interval replanning, and learned location-avoidance preferences
- Interest and skill-growth system: per-agent hobbies, planned skills, practice time, growth progress, and schedule/work-choice influence — with power-law learning gains, streak momentum, milestone events, day-end forgetting decay, four-phase interest development, and social interest contagion
- Reusable Skill library: Markdown-based global and per-agent private skills, auto-distilled from experience and injected into cognition and work briefs
- Real-work task system: agents browse a mock job market and produce real artifacts (HTML, Python, articles, lesson plans, research notes) matched to their job and skills
- City map generation and route playback
- Visualization trace export
- Agent interview CLI
- Local dashboard for config editing, profile editing, run control, memory inspection, and interview
- Agent Studio: a 7-step visual builder/inspector for a single agent — identity, the nine [0,1] state variables (editable radar), skills, tiered memory, Dunbar social circles, behavior dials, and review/deploy; writes back to the state CSV and profile Markdown and can create new agents
- Parameterised population synthesis: turn panel-level knobs (size, age pyramid, employment, income Gini, household structure, social-graph shape) into a full town — IPF-fitted joint attributes with structural zeros, exact marginals via largest-remainder integerisation, a rank-transform so the requested income median and Gini hold while income still correlates with education and industry, child-first household formation, and power-law workplaces. Outputs the state CSV + profile Markdown formats the simulator already reads, so `build_agent` needs no changes
- Group (cohort) simulation for large populations: partitions residents into cohorts that carry both mean **and** dispersion, spends one LLM call per cohort per day, materialises a budgeted set of individuals at full fidelity (focal / event / tail / audit), and keeps a mean-zero social-graph coupling term so network-mediated co-movement survives aggregation. ~25× cheaper than per-agent simulation at a 20-person daily materialisation budget
- Group-mode validation gate (L1–L4): a paired experiment that measures what the cohort approximation costs — distributional distance, network co-movement, tail retention, and causal response to a policy shock — with thresholds set relative to the reference tier's own cross-seed noise rather than arbitrary constants. Exits non-zero when a dividing-line layer fails, so it can gate CI
- Population Studio: a 5-step dashboard panel for generating a population, running group mode over it, and reading the validation verdict, with live feasibility prechecks that name the conflicting knob
- External Systems panel: observe and edit the world itself — the money system (macro cycle, sector pools, the daily money-conservation audit, wealth distribution and Gini), the external-environment generator, and the outward service connections. Config forms are generated from the config's own JSON shape (~150 knobs, and adding a knob needs no panel code), and a monetary intervention can be queued against a **running** simulation for it to consume at the next day boundary; injecting into a sector pool moves the conservation baseline with it, so the audit records a deliberate injection as an injection rather than as a leak
- Parallel Worlds: fork one city into N histories that share the cohort, the seed, the horizon and the model, and differ only in what happens — each world carries its own event list (and optionally its own config patch, for a policy rather than an incident) and runs in a fully isolated memory / state / log tree. The report measures each world's distance from the baseline at every step, so it answers *when* two histories split rather than only how far apart they ended, and names the individual residents an intervention actually landed on. Designed and read interactively in the console's 平行世界 tab; every world's trace stays replayable frame by frame, and existing `compare-event` runs are adapted into the same view without being rewritten on disk
- Distributed multi-machine mode with relay-based communication

## Architecture: Microkernel + Plugins

Since 2026-07, GAWorld runs on a society-centric microkernel architecture
(inspired by [Agent-Kernel](https://arxiv.org/abs/2512.01610)):

- **Kernel** (`gaworld/kernel/`, domain-free): `Clock`, `EventBus`
  (observe/collect/filter hook semantics), `PluginRegistry`, `Controller`
  (action validation + audited runtime interventions), `Recorder`
  (unified JSONL event stream), `SimContext`.
- **Cognition pipeline** (`gaworld/sim/pipeline.py`): each agent step is a
  configurable sequence of 12 named stages
  (`prepare → perceive → interrupts → plan → adjust_activity → move →
  select_action → reflect → update_state → broadcast → memorize → record`).
  Ablating, replacing, or inserting a stage is a `CONFIG["pipeline"]` change.
- **Plugins**: all nine built-in subsystems (intervention, skills, interests,
  life events, economy, local physical perception, real work, dynamic
  behavior, spatial preferences) ride the same plugin surface third parties
  use — a `Plugin` subclass plus one `CONFIG["plugins"]` entry (or a pip
  `gaworld.plugins` entry point). The main loop contains zero
  subsystem-private logic.
- **Runtime intervention**: `Controller.intervene` ships `set_agent_state`,
  `update_config`, `remove_agent` (applied at day boundaries), and
  `inject_life_event` out of the box; every call is audited.

See the [Plugin Authoring Guide](./docs/PLUGIN_AUTHORING.md) for the event
catalog and worked examples.

## Project Structure

Runtime code lives under the `gaworld/` package. Eleven legacy
top-level modules are now thin `sys.modules` aliases pointing at their
canonical home — `from memory_store import X` keeps working unchanged
but `from gaworld.memory.store import X` is the preferred path for new
code.

- `generative_city_sim.py`: main simulator + CLI entrypoint (pipeline scaffolding; subsystem logic lives in plugins)
- `config.py`: CONFIG compat shim — re-exports `gaworld.settings.CONFIG`
- `gaworld/kernel/`: the microkernel — clock, event bus, plugin registry, controller, recorder, sim context, standard interventions
- `gaworld/plugins/`: built-in plugin assembly (`builtin_plugins()`)
- `gaworld/sim/pipeline.py`: the configurable agent-step stage pipeline
- `gaworld/{policy,skills,events,economy,world,work,behavior}/plugin.py` + `gaworld/interests_plugin.py`: the nine built-in plugins
- `gaworld/settings/`: layered config fragments (LLM, runtime, behavior, economy, environment, integrations, overrides)
- `gaworld/core/`: typed `Agent` dataclass adapter and concurrent `parallel_map` runner
- `gaworld/llm/providers.py`: provider wrappers (Ollama / OpenAI-compatible / Anthropic-compatible) and the `LLM_ROUTER` dispatcher
- `gaworld/memory/store.py`: agent memory, vector DB, schedule/action/location caches, log persistence
- `gaworld/world/city_map.py`: graph, routes, transport costs, weather/rush-hour effects, category-based spatial queries
- `gaworld/world/local_physical.py`: per-node occupancy / opening-hours snapshots, crowd-surge anomaly detection, perception injection
- `gaworld/memory/spatial_preferences.py`: learned location-avoidance preferences with recency decay and redirection
- `gaworld/skills/`: reusable Skill library (registry, Markdown schemas, prompt injection, experience-to-skill consolidation)
- `gaworld/env/system.py`: in-sim `EnvironmentSystem` (weather, events, intervention feed, anomaly tagging) and `RemoteEnvironmentClient`
- `gaworld/cognition/realism.py`: realism helpers — intentions, habits, relationship update/weight, memory consolidation
- `gaworld/behavior/dynamic.py`: dynamic behavior system (InterruptEngine, SpontaneityEngine, social chains, environment-event cascades)
- `gaworld/social/network.py`: schema migration, off-screen ghosts, role-aware decay, Dunbar tiers
- `gaworld/economy/finance.py`: personal finance + macro cycles (tax, social insurance, Engel spending, investment, shock events)
- `gaworld/policy/intervention.py`: PolicySim-style recommendation / exposure intervention metrics, stance, risk
- `gaworld/events/life.py`: scheduled life events (birthday, illness, job change, off-screen ghost-event queue)
- `gaworld/personality/`: Big Five (OCEAN) personality — `traits` (the single read entry point: z scores at `agent["ext"]["big_five"]`, additive `style_fit`, bounded `trait_modifier`), `anchors` (traits to second-person behaviour sentences for prompts), `plugin` (`BigFivePlugin`, seeds traits on `agents.built` from `data/agents_big5.csv` or a correlated population prior)
- `gaworld/family/`: households — marital-status sampling, in-sim pairing, co-residence, family duties, conserving household spending, shared family events, and the operator-pinned override layer
- `gaworld/distributed/comm.py`: multi-machine relay client
- `gaworld/interests.py`: per-agent interest and skill-growth profile derivation, persistence, matching, progress updates
- `gaworld/work/`: real-work task system (runtime, worker pool, queue, market, router, adapters)
- `gaworld/population/`: parameterised population synthesis — `schema` (knob contract + feasibility precheck), `synth` (IPF + conditional sampling + income rank-transform), `network` (households, workplaces, homophily social graph), `report` (validation gate + review charts), `writer` (state CSV + profile Markdown + manifest)
- `gaworld/group/`: cohort (group) simulation — `cohort` (partition, centroid **and** dispersion, mean-zero network coupling), `cohort_day` (one LLM call per cohort per day), `materialize` (focal / event / tail / audit selection, audit residual), `driver` (day loop + cost accounting), `metrics` + `validate` (the L1–L4 gate), `plugin` (observational cohort telemetry)
- `gaworld/apps/`: local servers (dashboard, external-environment, distributed-comm) and the delegated panel backends `population_api` (Population Studio) and `external_systems_api` (External Systems)
- `gaworld/io/`: HTTP guard with retry/backoff and HTML extraction
- `gaworld/sim/`: extracted simulator sub-modules — `_utils`, `agents_loader`, `_schedule`, `_location`, `_cognition`, `_rag`, `_diary` (more slices coming as the legacy file shrinks)
- `simulation_visualizer.py`, `avatar_generator.py`, `generate_agent_rag_seed.py`, `analyze_wellbeing.py`: standalone CLI tools (not imported by the runtime)
- `data/hangzhou_agents_state_init.csv`: seed state values
- `data/hangzhou_profiles_with_names.md`: agent profiles
- `data/citymap.md`: city map data
- `scripts/`: launch and developer utilities
- `docs/`: tutorials, integration notes, design docs, refactor history (`REFACTOR_PLAN.md`, `REFACTOR_BASELINE.md`, `PROJECT_STRUCTURE.md`)
- `gaworld/parallel/`: parallel-world experiments — `spec` (world/event validation + per-world isolation overrides), `runner` (forks N worlds through a small pool, tracks progress), `analysis` (per-step divergence, split points, per-agent movers)
- `site/dashboard/`: local dashboard frontend (console `index.html` + Agent Studio `studio.html` + Population Studio `population.html` + External Systems `external.html` + Parallel Worlds `worlds.html`)
- `site/simviz/`: playback viewer
- `output/`: generated artifacts

## Quickstart

Install dependencies:

```bash
pip install -r requirements.txt
```

Run the simulator:

```bash
python generative_city_sim.py run
```

Run a **long-horizon fast-forward** (compress each day into one per-agent daily brief — one LLM call/agent/day — instead of the intra-day tick loop; state/goals/relationships still evolve approximately). Pairs with a large `--sim-days`, or toggle it from the dashboard toolbar («Long-run Fast-forward»):

```bash
python generative_city_sim.py run --sim-days 600 --fast-forward
```

Go **multi-year** by making one step a whole month or year — one "period brief" per agent per month/year, with a list of milestones folded into memory. This is what makes decade-scale runs affordable: 10 years x 50 residents is ~500 LLM calls at `--time-unit year` versus ~182,500 at day granularity. The sim calendar still advances day by day underneath (real month lengths and leap years), and the day-boundary hooks — economy settlement, interest decay, household spending — are replayed in <=30-day chunks, so a simulated year books a year of rent and twelve monthly settlements rather than one day's worth:

```bash
python generative_city_sim.py run --sim-years 10              # one step per year
python generative_city_sim.py run --sim-months 24             # one step per month
python generative_city_sim.py run --sim-years 10 --time-unit month
```

Any of `--sim-months` / `--sim-years` / `--time-unit` turns fast-forward on. The trade is total: intra-day and day-to-day detail is gone — a step leaves one narrative brief plus a set of cumulative deltas. Use it for long-run evolution (life trajectories, multi-year policy after-effects), not for behaviour within a day.

Reset stateful artifacts:

```bash
python generative_city_sim.py reset
```

Start the dashboard:

```bash
python generative_city_sim.py dashboard --port 8766
```

Then open:

```text
http://127.0.0.1:8766/dashboard
```

Serve the visualization viewer directly:

```bash
python generative_city_sim.py serve-viz --port 8000
```

Then open:

```text
http://127.0.0.1:8000/site/simviz/index.html
```

## CLI

Show help:

```bash
python generative_city_sim.py --help
```

Run simulation:

```bash
python generative_city_sim.py run
```

Reset simulation:

```bash
python generative_city_sim.py reset
```

Interview an agent:

```bash
python generative_city_sim.py interview --agent-id 31 --question "Why did you choose this action today?"
python generative_city_sim.py interview --agent-id 31 --questions-file questions.txt
```

Create an agent from social content:

```bash
python generative_city_sim.py create-agent-from-social --url "https://weibo.com/..."
python generative_city_sim.py create-agent-from-social --file output/source_page.txt --name "New Agent"
```

Add external RAG info:

```bash
python generative_city_sim.py rag-add \
  --agent-id 31 \
  --text "Prefers cycling and bookstores on weekends" \
  --timestamp "2026-02-18 09:30" \
  --source "manual"
```

Import external RAG info:

```bash
python generative_city_sim.py rag-import \
  --agent-id 31 \
  --file output/test_extra_info.txt \
  --source "profile_notes"
```

Compare an event against a no-event baseline:

```bash
python generative_city_sim.py compare-event \
  --event-name "Temporary Traffic Restriction" \
  --event-description "Travel time increases on arterial roads and affects commuting decisions" \
  --event-day 2 \
  --event-time 09:00 \
  --sim-days 3 \
  --llm-provider minimax \
  --seed 42
```

The comparison report includes regular city-state metrics and intervention metrics such as
`stance_score`, `toxicity_score`, `misinformation_risk`, `cross_viewpoint_exposure`, and
`intervention_reward`.

Run more than two branches — a baseline, several intervention strengths, a placebo — from one spec:

```bash
cat > worlds.json <<'JSON'
{
  "name": "Traffic restriction dosage",
  "sim_days": 3,
  "worlds": [
    {"label": "Baseline", "events": []},
    {"label": "Mild", "events": [
      {"day": 2, "time": "07:00", "name": "Traffic restriction",
       "description": "Odd-even plates at peak hours; commutes get slightly longer."}]},
    {"label": "Severe", "events": [
      {"day": 2, "time": "07:00", "name": "Full traffic control",
       "description": "Arterial roads closed; some residents cannot reach work at all."}]}
  ]
}
JSON

python generative_city_sim.py parallel-worlds --spec worlds.json --seed 42 --fast
```

Every world shares the cohort, the seed, the horizon and the model, and runs in its own isolated
memory / state / log tree. The report (`output/parallel_worlds/<id>/`) measures each world's
distance from the baseline at *every* step, so it reports when the histories split, not only how
far apart they ended, plus which individual residents the event actually landed on. A world may
also carry a `config` patch instead of (or alongside) events, which is how you model a policy
rather than an incident. The same experiments are designed and read interactively in the console's
**平行世界 / Parallel Worlds** tab. Full walkthrough: [Parallel Worlds Tutorial](./docs/PARALLEL_WORLDS_TUTORIAL.md) (in Chinese).

Generate a city map:

```bash
python scripts/generate_citymap.py --description "a small city with about 1000 residents, in east china"
```

Run the distributed relay:

```bash
python generative_city_sim.py serve-distributed --host 0.0.0.0 --port 8877
```

### Population synthesis and group simulation

Generate a parameterised town, simulate it as cohorts, and check what the approximation costs.
All three run at zero LLM cost. Full walkthrough: [Group Simulation Tutorial](./docs/GROUP_SIMULATION_TUTORIAL.md).

```bash
# Preview a 500-person town without writing anything
python -m gaworld.population --preset cn_county_town --size 500 --seed 42 --check

# Write it out (state CSV + profile Markdown + reproducibility manifest)
python -m gaworld.population --size 500 --seed 42 --name my_town --out data/town

# Simulate it as cohorts for 7 days
python -m gaworld.group --size 500 --days 7 --no-llm

# Run the L1-L4 validation gate (exits 1 when a dividing-line layer fails)
python -m gaworld.group.validate --size 100 --days 14 --network-coupling 0.7
```

The generated files match the formats the simulator already reads, so they can be dropped straight
into `CONFIG["csv_path"]` / `CONFIG["md_path"]`.

## Dashboard

The local dashboard provides:

- runtime config editing
- LLM routing selection
- profile editing
- simulation start / stop
- trace playback
- per-agent memory inspection
- interview execution
- run log viewing

The dashboard stores local overrides in `dashboard_config.json`.
Those values override `config.py` at runtime.

### Agent Studio

Agent Studio is a focused, single-agent builder and inspector reachable from the
console toolbar (**Agent Studio ↗**) or directly at
`http://127.0.0.1:8766/site/dashboard/studio.html`. It presents one agent across
seven steps, all bound to GAWorld's real seed model:

1. **Identity** — name, gender, age, hukou, residence, and the narrative profile
2. **State & Personality** — the nine normalized `[0,1]` state variables (`emotion`, `stress`, `econ_security`, `city_identity`, `policy_sensitivity`, `platform_dependence`, `risk_preference`, `voice_propensity`, `mobility_intent`) as live sliders + an editable radar
3. **Abilities & Skills** — the global Skill library
4. **Memory** — episodic / habit / intention / schedule counts and a memory graph
5. **Social & Relationships** — real Dunbar tiers (`inner`/`close`/`acquaintance`/`weak`) and a closeness-ranked relationship list once a run has produced them
6. **Behavior & Goals** — the behavior-driving state dials
7. **Review & Deploy** — a full summary, an optional LLM interview, save, and "run simulation with this agent"

Edits are written back to the real seed files: state variables and identity go to
the state CSV (`data/hangzhou_agents_state_init.csv`) and are mirrored into the
profile Markdown's state lines; narrative edits go to the profile block; and
"create" appends both a CSV row and a profile block. Social and finance panels
read post-run artifacts from `output/memory` and `output/economy` and degrade
gracefully before a run.

Backend API (added to `dashboard_server.py`):

| Method | Endpoint | Purpose |
|--------|----------|---------|
| GET | `/api/agents/{id}/state` | identity + nine state variables |
| GET | `/api/agents/{id}/detail` | aggregate: state, profile, memory counts, finance, social, skills |
| GET | `/api/skills` | global Skill library |
| POST | `/api/agents/{id}/state` | write state/identity to the CSV (+ profile sync) |
| POST | `/api/agents` | create a new agent (CSV row + profile block) |

### Population Studio

Population Studio is the group-mode counterpart to Agent Studio: where Agent Studio builds one
resident, Population Studio builds a whole town and simulates it as cohorts. Reachable from the
console tab (**人口与群体 / Population**) or directly at
`http://127.0.0.1:8766/site/dashboard/population.html`. Five steps:

1. **选模板** — preset, size, seed; the chosen preset is described in plain language rather than left as a bare identifier
2. **人口结构** — age / household / work / income knobs, a target-vs-achieved table, and age pyramid, Lorenz curve and degree-distribution charts
3. **心理状态** — the nine state variables, with a group-mean radar and a P25–P75 envelope (a cohort is a distribution, so a bare mean polygon would misreport it)
4. **跑模拟** — days, materialisation budget, audit fraction, network coupling, and which LLM provider to use; daily cohort briefs and measured LLM cost
5. **检查结果** — the L1–L4 verdict in plain language, plus the written population files as clickable links

Every metric is labelled bilingually (`压力 stress`), with the labels served from the schema
endpoint so the panel never keeps a second copy of the names.

The verdict card leads with a one-line conclusion and a can-use / cannot-use checklist derived
from which layers passed — the question a reader actually has is "what may I conclude from this
run?", not "what is the z-score". The full technical output stays available behind a disclosure.

Written files (state CSV, profiles, manifest) are listed with an open-in-new-tab link, a download
link and an inline preview: the dashboard already serves the repo statically, so a repo-relative
URL is directly openable.

A live feasibility precheck runs alongside every slider: it generates nobody, answers instantly,
and names the conflicting knob plus the reachable range when parameters contradict each other.

Backend API (delegated from `dashboard_server.py` to `gaworld/apps/population_api.py`):

| Method | Endpoint | Purpose |
|--------|----------|---------|
| GET | `/api/population/schema` | the knob contract — served, not duplicated in JS |
| POST | `/api/population/preview` | pure-maths feasibility precheck |
| POST | `/api/population/generate` | start generation → `job_id` |
| GET | `/api/population/jobs/{id}` | poll progress / result |
| POST | `/api/population/group-run` | run group mode over the last generated population |
| POST | `/api/population/validate` | run the L1–L4 validation gate |

Generation and simulation are asynchronous jobs, so a 500-person town does not block the browser.

### External Systems

The first two panels face the agents; this one faces **the world itself**. Console tab
(**外部系统 / External**) or directly at `http://127.0.0.1:8766/site/dashboard/external.html`.
Three sub-panels, each pairing observation on the left with editing on the right:

- **Money system** — cycle phase, inflation, unemployment, the cumulative price index, the
  firms / government / bank sector pools, the money-conservation curve and its drift, wealth
  distribution and Gini, and aggregate daily income vs expense. Edits the whole
  `CONFIG["economy"]` tree, and can also queue an intervention against a **running** simulation
- **External environment** — the recent days of generated natural / economic / political /
  technology events from `timeline.jsonl`, with severity bars and impact tags. Edits the
  generator's parameters, the weather pool, and the `policy_events` shock schedule
- **Outward services** — an on-demand health probe of the external-environment service and the
  distributed relay, plus LLM routing and the news cache. The provider list is read-only
  (credentials are never exposed); the routing table is editable

**The config forms are grown from the config itself.** The `economy` subtree alone has ~120
leaves; the panel renders controls from the JSON shape and the backend coerces an incoming patch
against the type already in the effective config (`"0.09"` → `0.09`), dropping unknown keys and
reporting them. ~150 knobs are editable, and adding a knob needs no panel code.

**Two kinds of "edit", and the difference matters.** Config is written to
`dashboard_config.json` and takes effect on the **next** run — that is the one to use for
controlled experiments. An intervention is written to `output/economy/interventions.json` and the
running simulation consumes it at the **next day boundary**. Interventions deliberately do *not*
write `macro_state.json`: that file is an *output*, rebuilt from config at
`on_simulation_start` and never read back, so editing it would look like it worked and change
nothing. Injecting into a sector pool moves the conservation baseline by the same amount, so the
daily audit records a deliberate injection as an injection rather than as money leaking.

| Method | Endpoint | Purpose |
|--------|----------|---------|
| GET | `/api/external-systems/overview` | config + runtime for all three subsystems |
| GET | `/api/external-systems/health` | probe the outward service endpoints |
| GET/POST | `/api/external-systems/interventions` | read / queue a monetary intervention |
| POST | `/api/external-systems/config` | save a config patch (whitelisted subtrees, type-coerced) |

Full walkthrough: [External Systems Tutorial](./docs/EXTERNAL_SYSTEMS_TUTORIAL.md) (in Chinese).

### Parallel Worlds

Where the other panels look at one world, this one looks at several at once. Console tab
(**平行世界 / Parallel Worlds**) or directly at
`http://127.0.0.1:8766/site/dashboard/worlds.html`. The page is **design on the left, read on the
right**.

The left column defines what the worlds differ by: shared settings (days, seed, cohort, model,
concurrency — deliberately *not* per-world, because holding them fixed is what makes the
comparison attributable), then one card per world with its label, a baseline radio, and its event
list (day / time / name / description). Three presets — layoff shock, traffic-restriction dosage,
placebo control — fill the form in one click. A world can be duplicated with its events, and can
also carry a `config` patch, which is how you model a policy rather than an incident.

The right column reads one experiment back:

- **Branch diagram** — each world's distance from the trunk *is* its divergence; a hollow node
  marks the step its history split, a solid dot marks an event
- **Trajectory comparison** — one metric's population mean per world, with the event days marked
  and a hover readout; "只看与基准的差" subtracts the baseline so a small effect is still legible
- **Divergence from baseline** — the per-step distance curves and the split threshold
- **End-state deltas** and **who was changed** — the per-metric table, and the per-resident table
  that a population mean would have averaged away

Legend chips toggle a world out of all four charts at once. Every world is a full simulation, so
each one links out to the frame-by-frame replay page.

| Method | Endpoint | Purpose |
|--------|----------|---------|
| GET | `/api/parallel-worlds/overview` | defaults, providers, presets, past experiments, current job |
| GET | `/api/parallel-worlds/experiment?root=…` | the full divergence report for one experiment |
| GET | `/api/parallel-worlds/job` | job status, with a live per-world snapshot while running |
| POST | `/api/parallel-worlds/preview` | validate a spec and echo the plan without running anything |
| POST | `/api/parallel-worlds/start` / `/stop` | fork the worlds / stop them |

One experiment runs at a time — a second start is a `409` rather than an oversubscribed machine —
and a world that fails does not take the others down: the report is still written, and the reason
(quota, unreachable model) is shown verbatim with its log path.

⚠️ Run a **placebo world** before drawing conclusions. Cognition is LLM-driven, so two identically
configured worlds do not produce identical histories; the placebo's divergence is your noise
floor, and a real effect has to clear it.

Full walkthrough: [Parallel Worlds Tutorial](./docs/PARALLEL_WORLDS_TUTORIAL.md) (in Chinese).

## Configuration

All base settings live in `config.py`.

Important fields:

- `agent_ids`: agents included in the run
- `sim_days`: number of simulated days
- `seconds_per_day`: wall-clock seconds per simulated day
- `time_step_minutes`: optional fixed timeline step
- `time_grid_snap`: align every agent's schedule onto that grid (default `False`). Setting `time_step_minutes` alone does **not** bound the tick count — the master timeline is the *union* of the grid and every agent's LLM-authored `HH:MM` times, so ticks (and therefore LLM cost) grow super-linearly with the agent count. Snapping pins them at `1440 / step` regardless of population size. Off by default because it changes intra-day timing
- `llm.providers`: provider registry
- `llm.routing.default`: default provider
- `llm.routing.tasks`: task-specific provider overrides
- `memory_dir`, `log_dir`, `vector_db_path`: persistence locations
- `visualization.output_dir`: trace output folder
- `economy`: personal finance settings (tax brackets, social insurance rates, Engel curve, investment incl. `market_correlation`, macro cycle, shocks, sector pools `sectors`, credit line `credit`, payment routing `routing`, friend loans `friend_loans`)
- `interests`: per-agent hobby and skill-growth settings (enable switch, item cap, insert tendency, progress persistence, day-end forgetting `decay`, interest-set `evolution`)
- `dynamic_behavior`: dynamic behavior system settings (enabled flag)
- `environment.local_physical` / `environment.anomaly` / `environment.replan` / `environment.spatial_preferences`: physical-perception and reactive-replanning switches and thresholds
- `skills`: reusable Skill library settings (global dir, cognition/work-brief injection, per-prompt cap)
- `memory.skill_consolidation`: experience-to-Skill distillation settings (enabled, cadence, lookback, min episodes)
- `real_work`: real-work task system (enable switch, market, concurrency, timeouts, adapters)
- `intervention`: lightweight recommendation / exposure control and evaluation settings
- `policy_events`: scheduled policy shocks
- `distributed`: multi-machine communication settings
- `plugins`: third-party plugin declarations (`[{"class": "pkg.mod:Class", "enabled": true}, ...]`)
- `pipeline.agent_step`: cognition-stage order (omit a stage to ablate it; insert `"module:function"` paths for custom stages)
- `controller.validators`: action-validator switches (`location_exists` default on, `venue_open` default off)
- `extensions.hooks`: user extension hooks (`{event: ["module:function", ...]}`)

### Log Output Mode

Terminal output verbosity is controlled by the `GAWORLD_LOG_MODE` environment variable:

| Mode | How to set | Behaviour |
|------|-----------|-----------|
| `simple` | default | ~4 lines per tick (header, location, action, reflection); LLM call details hidden; repeated WARNINGs (e.g. env-server unreachable) deduplicated to once per 60 s |
| `verbose` | `GAWORLD_LOG_MODE=verbose` | Full fields — perception, plan, memory recall, needs state, etc. Useful for debugging |

```bash
# Default simple mode
python generative_city_sim.py

# Switch to verbose mode
GAWORLD_LOG_MODE=verbose python generative_city_sim.py
```

Example simple-mode output:

```
── [王思远 @ 10:41] 上午工作 ──
Loc: 货运站
Act: 推进最重要的一项任务
Refl: 感受：情绪有一点波动；教训：下次要更早判断状态和代价；后续倾向：接下来会更偏向省力或稳妥的做法
```

All output is also written to `output/logs/run.log` in full structured format regardless of `LOG_MODE`.
Set `GAWORLD_LOG_LEVEL=DEBUG` to include per-call LLM latency and token counts.

### PolicySim-Style Intervention Evaluation

`CONFIG["intervention"]` enables a deterministic, no-network intervention layer inspired by
PolicySim. At each agent step, the simulator builds a small feed from relational, personalized,
and headline-like sources, applies local exposure-control heuristics, injects the feed into
perception, and records stance / toxicity / misinformation / cross-viewpoint reward metrics.

This feature does not perform SFT/DPO model training and does not call external moderation APIs.

### Family / Households

Before this feature every resident was, in effect, single: the profiles barely
mention marriage or children, `build_agent()` had no family fields, and the
`spouse` / `child` roles in the social module existed only inside each agent's
own LLM-generated off-screen roster — whose deterministic fallback **never
produced a spouse or a child**, and where A's spouse had no relationship to B.

Households are now a first-class entity, assigned *status first, structure
second*: marital status is sampled by age band x gender, whoever matches is
paired in-sim (everyone else gets an off-screen spouse), and only then are
children and co-resident elders derived. **Household type is a read-out, never
a quota** — planning household counts from type shares and then filling them is
the failure mode where the type knobs and the age pyramid disagree and one of
them silently loses.

| Layer | What it does |
|---|---|
| Ties | Family edges are written in the shape the social module already understands, so kin roles inherit its decay, obligation floor and Dunbar protection; LLM-invented spouses that contradict the assignment are pruned |
| Co-residence | Members of one household share a single `home` node — the line between a family and two strangers with matching addresses |
| Schedule | School runs, homework, elder care, calling your parents, being home for dinner; weekday and weekend differ |
| Ledger | Childcare and elder support are split by **income** through the economy's own expense path (conserving); partners top each other up when one runs short (a pure transfer) |
| Events | A child's fever is **one** event that lands on both parents in the same tick |
| Emotion | Co-resident family members' mood and stress converge; a household where everyone is calm produces no drift at all |

`family.pairing.in_sim_pair_share` (default `0.6`) is a **modelling knob, not a
demographic fact**: two people drawn from a 12-million-person city are almost
never married to each other, and pairing them buys in-sim family interaction.
Set it to `0.0` for a demographically pure run.

Population-level distributions live in the dashboard's 配置 → 家庭与户 section;
a single resident's family can be pinned in Agent Studio step 5, which writes
`data/family_overrides.json` — consulted *during* assignment, so a pinned family
survives the re-assignment that happens at the start of every run. See
[Family Design](./docs/FAMILY_DESIGN.md) (in Chinese).

### Economy Module

`CONFIG["economy"]` drives a realistic personal finance simulation modeled on the Chinese
economic system. Every agent maintains a full financial profile that evolves across simulation
days through four interlocking subsystems:

**Tax & Social Insurance (个税 + 五险一金)**

Each agent has a gross monthly salary derived from their job band and income skill. The module
calculates individual social insurance contributions (pension 8%, medical 2%, unemployment 0.5%,
housing fund 8%) with a base salary floor of 4,462 CNY and cap of 36,000 CNY. Personal income
tax uses China's 7-bracket progressive rate table (3%–45%, monthly exemption 5,000 CNY, with
configurable special deductions). The full pipeline `gross → SI deduction → tax → net salary`
runs at initialization and recalculates monthly when salary changes.

**Engel-Coefficient Spending**

Instead of flat random expense ranges, agents allocate their consumption budget according to an
income-indexed Engel coefficient curve. Low-income agents spend ~48% of consumption on food
with a ~5% savings rate; high-income agents spend ~15% on food with a ~40% savings rate. Eight
spending categories (food, housing, transport, clothing, leisure, education, healthcare, misc)
are weighted by income elasticity of demand: necessities (food 0.5, healthcare 0.6) grow slowly
with income while luxuries (leisure 1.5, clothing 1.2) scale up. Monthly budgets are
automatically recalculated whenever salary changes.

**Multi-Account System & Investment**

Agents hold four separate accounts: checking (活期), savings (储蓄), investment (投资), and
housing fund (公积金). Risk preference maps to three portfolio profiles — conservative
(deposits 70% / funds 25% / stocks 5%), moderate (40/40/20), and aggressive (15/35/50).
Monthly investment returns combine a **common market factor** (drawn once per month and shared
by all agents, so market-wide booms and crashes hit everyone together) with idiosyncratic
noise; `investment.market_correlation` (default 0.7) controls the systematic share. Excess
checking balance is automatically transferred to savings and investment accounts based on a
configurable buffer threshold.

**Money Conservation & Sector Pools**

Every agent money flow has a counterparty in one of three aggregate sector pools — **firms**,
**government**, and **bank** — so total money in the system is conserved to the cent after
initialization. Wages are paid out of the firms pool; consumption flows back to firms; taxes
and social insurance are withheld monthly on *realized* gross wages and routed to government;
investment gains/losses settle against the bank pool; medical reimbursements are paid by
government to firms. Pools may go negative (e.g. firms financing net household savings — the
stock-flow-consistent mirror image). A daily audit is exported to
`output/economy/conservation_audit.csv` (drift must stay ≤ 0.01 CNY) alongside
`sectors.json`, and GAWorld-Bench Track A treats conservation as a hard gate.

**Cash Constraint, Credit & Friend Loans**

Spending is funded in strict order: checking → savings drawdown → bank credit line (default
2× net monthly salary, 18% APR, interest capitalized monthly, auto-repaid from surplus) →
truncation. When liquidity falls below one month of expenses, discretionary categories are cut
harder than necessities via income elasticity. Agents whose spending was truncated are in
*financial distress*: their stress rises, and at day end they can borrow interest-free from
close, liquid friends over the social network (ranked by closeness × trust); friend debts are
tracked bilaterally and repaid before bank debt at monthly settlement.

**Payment Routing to Agents**

A share of local consumption (`routing.merchant_labor_share`, default 35%) is passed on — via
the firms pool — to service/trade agents whose workplace matches the spend location, and rent
is routed to landlord agents (profile keyword match) when any exist. Money therefore
circulates *between agents*, letting wealth distribution emerge instead of being a set of
independent random walks.

**Macro-Economic Cycles & Shock Events**

A simulation-level macro cycle rotates through four phases — expansion, peak, contraction, and
trough — each lasting 60–180 days. Each phase applies multipliers to income, expenses, layoff
risk, and raise probability. Industry-specific conditions (tech, finance, medical, education,
service, trade) shift independently. Inflation accumulates daily and erodes purchasing power.
At the individual level, agents face random economic shocks: layoffs (income cut 50–85% with
the monthly tax base reduced accordingly, recovery 30–90 days), raises/promotions, medical
emergencies (with social insurance reimbursement at 50–85%), and annual year-end bonuses
(13th-month salary). The economy runs on its own seeded RNG stream (`random_seed`-derived), so
trajectories stay reproducible regardless of what other modules draw from the global RNG.

Economy outputs include `output/economy/daily_ledger.csv` (now with a `debt` column),
per-agent ledgers, wealth snapshots, `macro_state.json`, `sectors.json`, and
`conservation_audit.csv`.

### Location System

`city_map_system.py` provides a realistic spatial layer for agent movement decisions.
Instead of hardcoded location names, the system uses category-based spatial matching
to resolve where agents should go for any activity.

**Transport Cost Calculation**

Each transport mode has a fare structure calibrated to Chinese urban transit: bus flat
fare (2 CNY), metro distance-based (base 2 + 0.45/km beyond 4 km free), taxi with
base fare and per-km rate (13 + 2.5/km beyond 3 km free), car with per-km fuel cost
and optional parking. Rush-hour detection (7:00–9:00, 17:00–19:00) applies a 1.45×
time multiplier and 1.3× taxi surcharge. Travel costs are deducted from the agent's
transport expense category in the economy module.

**Weather-Aware Mode Selection**

When weather conditions are active, the transport mode selector re-evaluates choices
using weather adjustment weights. In rain or snow, open-air modes (walk, bike, e-bike)
are heavily penalised and agents switch to sheltered alternatives (bus, metro, taxi).

**Category-Based Location Resolution**

Activities and job titles are mapped to location categories (education, medical,
commerce, leisure, transit, etc.) through keyword dictionaries. The spatial resolver
finds the nearest matching nodes from the agent's current position, weighted by time-
of-day bias, agent profile, and habitual preference. This replaces the previous
approach of hardcoded location name lists, making the system work with any city map.

**Commute Memory**

Agents track frequent places, preferred transport modes, and commute route statistics
(average travel time, trip count). These accumulate over simulation days and feed back
into location decisions — agents develop habitual patterns and prefer familiar places.

**Area Price Levels**

Different area categories carry price-level multipliers (commerce 1.35×, industry
0.80×, education 0.85×, etc.) that influence spending behavior when agents are in
those areas.

### Dynamic Behavior System

`dynamic_behavior.py` makes agent daily routines feel more human by injecting
context-aware schedule changes. The system is opt-in via `CONFIG["dynamic_behavior"]["enabled"]`
and runs once per agent per time-step, before the LLM-based activity adjustment.

### Interest And Skill Growth

`gaworld/interests.py` derives a persistent `growth_profile` for each agent from
their job, personality, daily life, and values. The profile contains hobbies and
planned skills with motivation, priority, current level, weekly target minutes,
preferred time blocks, career relevance, and activity templates.

The simulator uses this profile in four places:

- daily schedules and daily routines can replace low-commitment personal time with
  concrete activities such as reading, running, creation, professional study, or
  communication practice;
- daily intentions may include `growth_focus`, so reflection and next-day planning
  can carry growth goals forward;
- action choice gives matched hobby/skill actions extra weight without overriding
  high-commitment work, school, medical, or sleep activities;
- episodes record `growth_matches` and `growth_progress`, then update level,
  total minutes, last practiced day, and streak counters.

Practice follows a power-law learning curve — the higher an item's level, the
smaller each gain — while an unbroken streak adds momentum. Crossing level
0.35 / 0.60 / 0.85 emits a milestone event (入门/熟练/精通) into
`growth_progress`, so diaries and reflections can reference tangible progress.
Each item also carries a derived development phase after Hidi & Renninger
(触发期 → 维持期 → 浮现期 → 成熟期) that is shown in prompt context, so an
agent's self-image matures with practice.

At day end the profile itself evolves (config: `CONFIG["interests"]["decay"]`
and `CONFIG["interests"]["evolution"]`): items unpracticed past a grace period
lose level — retention rises with accumulated practice, and decay is
phase-aware (fragile triggered-phase items fade faster, well-developed ones
barely decay) — and idle gaps break streaks. Stale barely-started items are
eventually retired, while new interests can be adopted from the day's social
partners (interest contagion), so the interest set turns over instead of
staying frozen at bootstrap. All of this is pure rules — no extra LLM calls —
and the on-disk schema is unchanged.

Growth data is runtime state, not source profile data. It is cached globally in
`output/memory/growth_profiles.json` and persisted per agent as
`output/memory/agent_<id>_growth.json`.

**Commitment-Aware Interruption**

Every activity carries a commitment level (0.95 for exams and surgery, 0.70 for work, 0.15 for
browsing the phone). Interrupt candidates must overcome this commitment barrier plus a
personality-dependent threshold (self-control, risk preference) to change the scheduled activity.
Even net-positive interrupts pass through a stochastic acceptance gate.

**Mood-Driven Spontaneous Urges**

The agent's emotional state is classified into one of six mood categories (happy, stressed, tired,
bored, anxious, lonely). Each mood maps to a pool of context-appropriate urges — a stressed agent
might want to take a walk alone, while a bored agent might pick up their phone. Time-of-day
filters prevent unrealistic urges (no shopping at midnight), and personality scaling adjusts
probabilities (extroverts get more social urges).

**Social Encounter Chains**

When agents share the same location, encounter probability is computed from relationship closeness
and social need. Close friends may invite each other for meals (time-aware: lunch vs dinner),
acquaintances exchange brief greetings, and strangers may exhibit behaviour contagion — joining a
queue or watching a street event.

**Environment Event Cascades**

Weather, traffic, commercial, news, and emergency events are classified and converted into
interrupt candidates with personality-differentiated priority. Primary events can trigger cascade
chains: rain leads to taxi queues and slippery roads, traffic congestion leads to potential
lateness and mood drops. Cascade events fire probabilistically and accumulate mood effects.

**Need-Based Interrupts**

Physiological needs (hunger, fatigue) and task pressure generate interrupt candidates. Hunger
interrupts receive a bonus near meal times. Low energy triggers rest urges. High time pressure
pushes agents to handle urgent tasks.

**Schedule Insertion**

When an interrupt wins, the system can insert the new activity into the schedule with resumable
support — the original activity resumes after the interruption if there's room in the schedule.

### Physical Environment Perception And Reactive Replanning

`gaworld/world/local_physical.py` and `gaworld/memory/spatial_preferences.py` connect the city
map's previously-unused per-node `occupancy` and `is_open` state to the cognition loop, so agents
perceive and react to their *current* surroundings. The system is fully config-gated, purely
rule-based (no extra LLM calls), and backward compatible — each layer degrades to a no-op when its
data is absent. All switches live under `CONFIG["environment"]`.

**Local Physical Perception (P0)**

Each tick, node occupancy is recomputed from where agents actually are, and simulation time is
written so opening-hours logic takes effect. Before each agent perceives, a snapshot of the current
location (crowding level, open/closed, local weather, anomaly flag) is generated and optionally
injected into the perception context as a "surrounding physical environment" line.

**Structured Event Reaction (P1)**

The dynamic-behavior classifier prefers structured signals (`type` / `topic` / `impact_tags`) over
keyword guessing, and consumes `impact_tags` (mobility, stress, public_service, …) as interrupt-
priority boosts. Local physical state becomes interrupt candidates too: crowding → "move somewhere
less crowded", a closed venue → "go to another open place" (non-resumable, forces a relocation).

**Anomaly As A First-Class Signal (P2)**

`env/system.py` tags each event with `anomaly` / `anomaly_score`, representing a deviation from the
norm — ordinary weather and small fluctuations are not anomalies; extreme, shock, emergency, and
high-severity events are. Anomalies raise interrupt priority, can force non-resumable reactions, and
have stronger mood effects. A local "crowd surge" (high occupancy that jumped sharply versus the
previous tick) emerges as a `crowd_anomaly` interrupt.

**Same-Day Replanning (P3)**

`sim/_schedule.py` adds `replan_affected_interval`, which re-arranges only the affected contiguous
window of the schedule (relocate / defer / drop) and leaves everything outside it untouched. When
the winning interrupt is a persistent anomaly (a non-resumable physical/emergency reaction), the
disrupted activities in the window are deferred past it, rather than only patching the single
current step.

**Structured Spatial Learning (P4)**

`spatial_preferences.py` accumulates location-bound anomaly experiences (crowding, closures — not
city-wide macro anomalies) into a per-location avoidance score, time-weighted and recency-decayed.
Once a location's score crosses the threshold, `redirect_for_aversion` biases the agent toward a
same-category alternative with a lower avoidance score. Preferences are persisted per agent to
`output/memory/agent_<id>_env_preferences.json` (only when `stateful=True`) and survive across runs.

Config blocks (`gaworld/settings/environment.py`): `local_physical`, `anomaly`, `replan`,
`spatial_preferences`. Setting any block's `enabled` to `False` reverts that layer; the four
switches are independent. See [`docs/physical_env_perception_changelog.md`](docs/physical_env_perception_changelog.md)
for the full design and parameter table.

### Reusable Skill Library

Parallel to the interest/skill-growth system, `gaworld/skills/` gives agents reusable, well-formatted
*skills* — an idea close to Claude Code's Skills. Each skill is a Markdown file with YAML
frontmatter (`name` / `description` / `triggers` / body), from one of two sources:

- **Global library** `data/skills/*.md` — hand-authored, attachable to any agent;
- **Private library** `output/memory/agent_<id>_skills/*.md` — auto-distilled by an agent from its
  own recent episodes. Off by default; enable with
  `CONFIG["memory"]["skill_consolidation"]["enabled"] = True`, triggered every `every_days`
  simulation days inside `run_daily_memory_lifecycle`.

At runtime, skills are injected into the `perception` prompt and into the work brief's
`【可用技能】` (available skills) block, shaping cognition and work artifacts. Attach a global skill
to an agent:

```python
from gaworld.skills import SkillRegistry
SkillRegistry().attach_to_agent(agent, "poster-layout-grid")
```

Full design and API: [`docs/SKILL_SYSTEM.md`](docs/SKILL_SYSTEM.md).

### Real Work

`gaworld/work/` lets residents do *real* work matched to their job / skills / interests — producing
HTML pages, Python scripts (with optional pytest), Markdown articles, lesson plans, and research
notes — and browse, claim, and settle jobs on a mock job-opportunity market. Capabilities are
LLM-derived per occupation and cached; tasks run on a background `WorkerPool`; artifacts land under
`output/work/agent_<id>/<task_id>/`.

It is config-gated via `CONFIG["real_work"]["enabled"]` and integrates with the interest/skill-growth
and Skill systems (planned skills widen capability matching; relevant skills are appended to each
work brief). See [`docs/REAL_WORK_USAGE.md`](docs/REAL_WORK_USAGE.md) and
[`docs/REAL_WORK_DESIGN.md`](docs/REAL_WORK_DESIGN.md).

### LLM Backends

The project supports:

- `ollama`
- OpenAI-compatible endpoints
- Anthropic-compatible endpoints

For Minimax China-region Anthropic compatibility, the project supports:

- `ANTHROPIC_BASE_URL=https://api.minimaxi.com/anthropic`
- `MINIMAX_API_KEY` or `ANTHROPIC_AUTH_TOKEN`

## Outputs

Generated artifacts are written under `output/`, including:

- `output/logs/agent_<id>.log`
- `output/memory/agent_<id>.json`
- `output/memory/agent_<id>_episodes.jsonl`
- `output/memory/agent_<id>_growth.json`
- `output/memory/growth_profiles.json`
- `output/memory/agent_<id>_env_preferences.json`
- `output/memory/agent_<id>_skills/*.md`
- `output/memory/vector_db.sqlite`
- `output/economy/daily_ledger.csv`, `wealth_snapshot.csv`, `macro_state.json`
- `output/economy/sectors.json`, `conservation_audit.csv` (sector pools + daily money-conservation audit)
- `output/economy/agents/agent_<id>_ledger.csv`, `agent_<id>_snapshot.json`
- `output/environment/timeline.jsonl`
- `output/intervention/intervention_metrics.csv`
- `output/work/capabilities.json`, `queue.jsonl`, `market.jsonl`, `agent_<id>/<task_id>/`
- `output/visualization/simulation_trace.json`
- `output/visualization/latest_frame.json`
- `output/network/`
- `output/state/`

## Notes

- `dashboard_config.json` can override `config.py`
- stateful runs may reuse memory and schedules from earlier runs
- after changing memory schema settings, run `reset`
- if a provider appears wrong at runtime, check both `config.py` and `dashboard_config.json`

## Additional Docs

- [中文 README](./README.zh-CN.md)
- [Full Tutorial](./docs/TUTORIAL.v2.md) (complete — covers all features)
- [Quickstart](./docs/TUTORIAL.md)
- [Plugin Authoring Guide](./docs/PLUGIN_AUTHORING.md) (extend GAWorld without touching the core)
- [Microkernel Architecture Design](./docs/proposals/2026-07-11-microkernel-plugin-architecture.md)
- [Skill System](./docs/SKILL_SYSTEM.md)
- [Real Work — Usage](./docs/REAL_WORK_USAGE.md) · [Design](./docs/REAL_WORK_DESIGN.md)
- [Physical Environment Perception & Reactive Replanning](./docs/physical_env_perception_changelog.md)
- [Social Network — Design](./docs/SOCIAL_NETWORK_DESIGN.md) · [Tutorial](./docs/SOCIAL_NETWORK_TUTORIAL.md)
- [Family / Households — Design](./docs/FAMILY_DESIGN.md) (in Chinese; marital sampling, co-residence, family duties and spending, the override layer and the Studio editor)
- [Group Simulation — Tutorial](./docs/GROUP_SIMULATION_TUTORIAL.md) · [Design](./docs/GROUP_AGENT_DESIGN.md) (population synthesis, cohort mode, the L1–L4 validation gate)
- [External Systems — Tutorial](./docs/EXTERNAL_SYSTEMS_TUTORIAL.md) (in Chinese; observing and editing the money system, the external environment and outward services, plus runtime intervention)
- [Parallel Worlds — Tutorial](./docs/PARALLEL_WORLDS_TUTORIAL.md) (in Chinese; multi-branch counterfactuals — designing an experiment, reading the divergence charts, dose-response designs, and why to run a placebo world first)
- [Big Five (OCEAN) Personality — Design](./docs/proposals/2026-08-20-big-five-personality.md) (the three independent channels, the effect-size and collinearity merge gates, and the offline trait calibration pass)
- [Project Structure](./docs/PROJECT_STRUCTURE.md)
- [Repository Guidelines](./AGENTS.md)
- [Changelog](./CHANGELOG.md)
