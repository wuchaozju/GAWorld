# Project Structure

GAWorld runs on a society-centric microkernel architecture (K1–K5
migration completed 2026-07-12 — design doc:
`docs/proposals/2026-07-11-microkernel-plugin-architecture.md`). Keep
active cross-cutting code in `gaworld/`; keep root modules as stable
CLI/backward-compat entrypoints until their callers have been migrated.

## Kernel & Plugin Surface

- `gaworld/kernel/`: the domain-free microkernel — `clock.py`, `bus.py`
  (EventBus: observe/collect/filter hooks), `registry.py` (Plugin base +
  assembly from `CONFIG["plugins"]` and `gaworld.plugins` entry points),
  `controller.py` (action validation gate + audited interventions),
  `recorder.py` (unified JSONL event stream under `output/records/`),
  `context.py` (SimContext + `build_kernel`), `interventions.py`
  (standard interventions: `set_agent_state`, `update_config`,
  `remove_agent`).
- `gaworld/sim/pipeline.py`: the agent step as a configurable sequence of
  12 named stages (`CONFIG["pipeline"]["agent_step"]`).
- `gaworld/sim/_fastforward.py`: the *other* driver — long-horizon
  fast-forward, which compresses one step into a single per-agent brief
  instead of running the 12 stages per tick. `long_run.unit` picks how much
  wall-time a step covers (`day` / `month` / `year`), which is what makes
  decade-scale runs affordable; `Period` + `plan_horizon` turn a run length
  into the list of steps the main loop iterates, and `plan_hook_chunks`
  splits each step into the ≤30-day day-boundary hook emissions that keep
  the economy's monthly settlement cadence landing. A `day`-unit horizon is
  one period per day, so the classic day loop and the coarse loop are the
  same loop.
- `gaworld/plugins/`: built-in plugin assembly — `builtin_plugins()` is
  the one place that may import built-in plugin classes.
- Built-in plugins (one per subsystem): `gaworld/policy/plugin.py`
  (intervention), `gaworld/skills/plugin.py`, `gaworld/interests_plugin.py`,
  `gaworld/events/plugin.py` (life events), `gaworld/economy/plugin.py`,
  `gaworld/world/plugin.py` (local physical + spatial preferences),
  `gaworld/work/plugin.py` (real work), `gaworld/behavior/plugin.py`
  (dynamic behavior), `gaworld/moltbook/plugin.py` (moltbook: a connected
  resident's day becomes a post on the agent social network; every call is
  recorded under `output/moltbook/`).
- Authoring guide + event catalog: [`PLUGIN_AUTHORING.md`](PLUGIN_AUTHORING.md).

## Active Runtime

- `generative_city_sim.py`: CLI entrypoint and simulator loop — pipeline
  scaffolding only; subsystem logic lives in the plugins above.
- `config.py`: compatibility shim that exposes `CONFIG`.
- `environment.py`: compatibility shim re-exporting `EnvironmentSystem` /
  `RemoteEnvironmentClient` from `gaworld/env/system.py`. It was a full copy
  until 2026-08-29; the two drifted in both directions and the simulator
  imported the *root* one, which is why `_annotate_anomaly` never ran. Keep
  it a re-export — `tests/test_environment_shim.py` fails if anything is
  defined here again.
- `data/`: tracked seed data and local baseline inputs.
- `gaworld/settings/`: focused configuration fragments assembled into the legacy `CONFIG` dict.
- `gaworld/core/`: typed core abstractions used by new code.
- `gaworld/io/`: IO helpers such as HTTP guards and web scraping.
- `gaworld/infosources/`: what residents read from outside the city, typed.
  `schema.py` (`Source` = news / social / professional × a fetch channel × domain
  tags; `InfoItem`), `registry.py` (`data/info_sources.json`), `channels.py`
  (RSS/Atom incl. the arXiv API, Reddit JSON, Hacker News, the Weibo / Baidu /
  Bilibili hot lists, plain page — pure parsers plus one guarded fetch),
  `feed.py` (the real-time-TTL cache under `output/infosources/` and the
  process-wide runtime the news pipeline reads), `diet.py` (deterministic
  per-resident media diet from job → domain tags, interest keywords,
  `platform_dependence` and Big Five openness; item picking), `search.py`
  (DuckDuckGo / Brave / Tavily providers for the `web_search` engine chain),
  `plugin.py` (`InfoSourcesPlugin`: refresh + diets on `agents.built` /
  `on_day_start`). `gaworld/sim/_news.py` reads the diet through
  `agent["ext"]["infosources"]` and the feed through `feed.runtime()`, so the
  simulator's call sites are unchanged. CLI: `python -m gaworld.infosources`.
  Design: `docs/proposals/2026-09-19-agent-information-sources.md`.
- `gaworld/interests.py`: per-agent interest and skill-growth profile derivation, persistence, matching, progress updates, day-end forgetting decay, and interest-set evolution (retirement + social contagion).
- `gaworld/work/`: real-work task routing, queueing, adapters, and market data.
- `gaworld/family/`: households as a first-class entity. `schema.py` owns the
  data model and config resolution; `assign.py` samples a marital status per
  agent (age x gender), pairs whoever matches in-sim, and derives children,
  co-resident elders and flatmates — household *type* is a read-out of the
  result, never a quota chosen up front. `overrides.py` is the operator-pinned
  layer (`data/family_overrides.json`) consulted *during* assignment, so a
  family pinned in Agent Studio survives the re-assignment that happens at the
  start of every run. `ties.py` writes kin edges in the shape
  `social/network.py` already expects and prunes LLM-invented spouses that
  contradict them; `duties.py`, `finance.py` and `events.py` turn the household
  into schedule pressure, conserving household spending, and shared family
  events plus in-household emotional contagion. `plugin.py` wires all of it.
- `gaworld/personality/`: Big Five (OCEAN) traits as a person-level
  modulation layer. `traits.py` is the single read entry point — a stdlib-only
  leaf that stores z scores at `agent["ext"]["big_five"]` and exposes
  `traits_of`, `style_fit` (additive) and `trait_modifier` (multiplicative and
  bounded); `anchors.py`, also stdlib-only, turns those z scores into
  second-person Chinese behaviour sentences for LLM prompts; `plugin.py`
  (`BigFivePlugin`, id `big_five`) owns the single `agents.built` hook, seeding
  traits from `data/agents_big5.csv` when that file is present and sampling
  from a correlated population prior otherwise. It is registered *first* in
  `builtin_plugins()`, because personality is a read-only prerequisite layer
  every later `agents.built` handler may want to consult. Three independent
  channels (`CONFIG["personality"]["channels"]`, all on by default) keep the
  effects attributable: `rules` is deterministic and zero-token (an additive
  `trait_style_fit` component in `choose_action`, bounded multipliers on
  interrupt threshold, spontaneity, social encounter probability, decision
  noise, impulse bypass and wealth drive, plus a personal emotion set point),
  `prompt` injects anchor sentences into the daily-routine,
  activity-adjustment, goals and news prompts, and `voice` injects them into
  the diary prompt only — so an experiment can tell "the decisions changed"
  apart from "the prose changed". Traits never drift during a run (adult OCEAN
  change is ~0.1-0.2 SD per decade), and an agent with no traits, or a
  gated-off channel, behaves bit-identically to the pre-personality build.
  `scripts/author_personality.py` produces the CSV offline, sampling the five
  scores first and authoring each resident's profile prose from them — the
  inverse of the old pass, which scored OCEAN out of prose written alongside
  the person-level state variables and so recovered those variables instead
  (worst collinearity R² 0.77, now 0.05; coverage now 51/51 on all five
  dimensions). It adds a `人格与行为倾向` field to every profile, which
  `personality_line` renders in place of the old `性格与情绪特征` line, and
  backs the previous corpus up to `data/hangzhou_profiles_with_names.v1.md`.
  `scripts/calibrate_big5.py` remains, now for scoring externally imported
  agents and as a control arm that re-scores the authored corpus against the
  sampled ground truth. `scripts/big5_effect_ceiling.py` (effect size) and
  `scripts/big5_collinearity.py` (redundancy against the existing person-level
  state variables) are the merge gates. Design docs:
  `docs/proposals/2026-08-20-big-five-personality.md` and
  `docs/proposals/2026-08-21-personality-corpus-rewrite.md`.
- `gaworld/population/`: parameterised population synthesis. `schema.py` owns the
  knob contract (`PopulationSpec`, presets) and the pure-maths feasibility
  precheck; `synth.py` IPF-fits a joint attribute table with structural zeros and
  samples individuals; `network.py` builds households (child-first), power-law
  workplaces and a homophily/geography social graph emitted in the existing
  `ensure_relationship_schema` shape; `report.py` validates and produces the
  review charts; `writer.py` serialises to the state CSV + profile Markdown
  formats `build_agent` already reads. CLI: `python -m gaworld.population`.
  See [`GROUP_SIMULATION_TUTORIAL.md`](GROUP_SIMULATION_TUTORIAL.md).
- `gaworld/group/`: the cohort (group) simulation tier — a *parallel driver*, not
  a modification of the tick loop, so individual runs are unaffected by
  construction. `cohort.py` (partition; cohorts carry mean **and** dispersion;
  `NetworkCoupling` adds a within-cohort mean-zero graph term), `cohort_day.py`
  (one LLM call per cohort per day), `materialize.py` (focal / event / tail /
  audit selection and the audit residual), `driver.py` (day loop + measured cost
  accounting), `metrics.py` + `validate.py` (the L1–L4 validation gate),
  `plugin.py` (`GroupPlugin`, observational cohort telemetry).
  CLIs: `python -m gaworld.group`, `python -m gaworld.group.validate`.
  Design + measured results: [`GROUP_AGENT_DESIGN.md`](GROUP_AGENT_DESIGN.md).
- `gaworld/interview/`: the group interview — one question set asked of many
  respondents at once, where a respondent is an individual resident *or* a
  `gaworld.group` cohort, possibly in another city. `schema.py` is the whole
  data model and the only place that trusts raw input; `roster.py` enumerates
  respondents by reading city bundles directly (a *catalogue*, so it needs no
  map, memory store or vector DB, and `industry` is deliberately absent because
  it is never written to disk); `prompt.py` builds one turn and parses the
  answer back into countable form; `attachments.py` resolves URLs and images
  once, in the parent, and records any degradation; `runner.py` builds personas
  serially (the memory store holds a *process-global* SQLite connection) and
  fans the model calls out over a thread pool; `aggregate.py` tallies and
  cross-tabs; `report.py` renders the self-contained Markdown document;
  `store.py` owns `output/interviews/<session_id>/`; `session.py` orchestrates a
  round across cities; `local.py` is the only module that touches the simulator.
  Cross-city work runs as one child process per city — `build_agent` and the
  memory store read module-level paths, so switching cities inside one process
  would mean mutating global config under a thread pool. CLI (one city's share):
  `python -m gaworld.interview`.
  See [`GROUP_INTERVIEW_TUTORIAL.md`](GROUP_INTERVIEW_TUTORIAL.md).
- `gaworld/parallel/`: parallel-world (multi-branch counterfactual) experiments —
  a *fork* of the existing run, not a change to it, so single runs are
  unaffected by construction. `spec.py` validates an experiment (2–8 worlds,
  each with its own events and optional config patch) and builds the per-world
  overrides that isolate every path a run writes to; `runner.py` forks the
  worlds as subprocesses through a bounded pool, samples progress out of each
  world's `run.log`, and persists the manifest and report; `analysis.py`
  reconstructs per-step trajectories, measures each world's distance from the
  baseline at every step (with a "crosses and stays" split-point rule) and the
  same distance per agent at the end. CLI: `python generative_city_sim.py
  parallel-worlds --spec worlds.json`. Panel backend:
  `gaworld/apps/parallel_worlds_api.py`, which also adapts legacy
  `output/comparisons/` trees into the same view.
  See [`PARALLEL_WORLDS_TUTORIAL.md`](PARALLEL_WORLDS_TUTORIAL.md).
- `gaworld/skills/`: per-agent Skill subsystem — global library at `data/skills/`, private skills under `output/memory/agent_<id>_skills/`, and experience-to-skill consolidation. See [`SKILL_SYSTEM.md`](SKILL_SYSTEM.md).
- `gaworld/world/local_physical.py`: per-node occupancy / opening-hours snapshots and crowd-surge anomaly detection injected into perception. See [`physical_env_perception_changelog.md`](physical_env_perception_changelog.md).
- `gaworld/memory/spatial_preferences.py`: learned location-avoidance preferences (recency-decayed), persisted to `output/memory/agent_<id>_env_preferences.json`.
- `gaworld/world/away.py`: the single definition of what "异地" means. Both a
  real GPS fix outside the map (`gaworld/twin`) and a simulated trip
  (`gaworld/travel`) write the same marker into `locations["current"]`,
  because every downstream reader of that field needs one answer to "is this
  a place on the map?". Only the simulated kind carries an itinerary, and
  that asymmetry is load-bearing: a real position is the user's fact, so
  nothing may send them home. The label is display text — never route from it.
- `gaworld/travel/`: residents leave the city for a few days and come back.
  `destination.py` (real distances: the twin's province-centre table and
  `haversine_km` against the map's own centre node; rail/air legs and fares),
  `trigger.py` (who goes and why — job for a business trip, relationship
  obligation for a family visit, weekend + cash + openness + stress for a
  holiday; pure, seeded, no LLM), `itinerary.py` (the day away, per purpose),
  `plugin.py` (`TravelPlugin`: rewrite the day on `on_day_start`, blank the
  destination on `location.resolve`, say so on `perception.compose`). Off by
  default — it changes who is present in the city, so earlier runs are not
  comparable. Design:
  `docs/proposals/2026-09-19-agents-leaving-the-city.md`.
- `gaworld/collaboration/`: Dashboard agent collaboration subsystem —
  reciprocal friendship persistence (`relationships.py`), independently
  runnable and observable discussions (`discussion.py`), cooperation
  planning/execution/review/synthesis (`cooperation.py`), durable session
  and event storage (`store.py`), and the lifecycle facade (`service.py`).
  Sessions support pause/resume/cancel; a service restart marks unfinished
  `running` sessions as `interrupted` without discarding their transcript or
  artifacts.
- `gaworld/apps/`: runnable local servers and dashboard backend entrypoints.
  `family_api.py` is the family backend — the dashboard card reads the
  *recorded* run while the Studio editor deliberately re-derives the
  assignment, because those answer different questions ("what is this run
  living in?" vs "what will next run look like if I save this?").
  `population_api.py` is the Population Studio backend — a *delegate* module, so
  `dashboard_server.py` only gains a prefix-forwarding branch for
  `/api/population/*` rather than another subsystem's routes. It reads path
  constants from `dashboard_server` at call time, because the dashboard tests
  monkeypatch those constants onto a temp directory. `city_api.py` is the Cities
  backend — create / populate / select a city, plus the **read-only cross-city
  resident reads** (`/api/city/catalogue`, `/api/city/agents`,
  `/api/city/agent`) that let the panel and Agent Studio browse a city the
  simulator is not currently pointed at. Those reads go through
  `gaworld.interview.roster` rather than a second population parser, and they
  are read-only on purpose: agent ids restart at 1 per city while memory, Big
  Five, social and finance are one flat per-id namespace owned by the running
  city. `interview_api.py` is the
  group-interview backend, another delegate: its routes all live under
  `/api/interview/` **with a trailing segment**, which leaves the older
  single-agent `POST /api/interview` (Agent Studio's interview box) untouched. A
  round is a job rather than a request handler, because 80 respondents × 5
  questions is 400 model calls and no browser waits for that. `arena_api.py`,
  `games_api.py`, `disaster_api.py` and `rumor_api.py` back the playground: the
  arena keeps its older `/api/arena/*` namespace (moving it would break existing
  callers), while every other game hangs off `/api/games/<game>/*` —
  `games_api.py` implements persuasion and forwards the `disaster` and `rumor`
  prefixes to their own modules, which are big enough to want their own files. It
  also owns what they share: `persona_block()` (the profile preamble every game
  prompts with) and `first_json_object()` (pulling a structured reply out of
  whatever the model actually said). All of them keep their state in memory and
  never write to a city bundle — a game is an evaluation sandbox, not a run — and
  all take their LLM entry points as injectable parameters so the tests are
  network-free. The arena, disaster mode and the rumor game run a round as a job
  (contestants × tasks, residents × stages, residents × 2); persuasion answers
  each request inline, because one chat turn is a single round trip. `replay_runs.py` enumerates
  every replayable trace on disk (live, `<visualization>/runs/<run_id>/` archives,
  scenario output trees) for the replay page's run picker; it reads only the head
  of each trace, because a listing must not parse a hundred multi-megabyte files.
- `scripts/`: developer and launch utilities that are not imported by runtime modules.
- `examples/`: sample external-agent inputs and integration examples.

## Configuration Layout

- `gaworld/settings/llm.py`: LLM provider and routing defaults.
- `gaworld/settings/runtime.py`: core simulation, paths, memory, planning, and concurrency defaults.
- `gaworld/settings/environment.py`: external environment, physical perception (`local_physical`, `anomaly`, `replan`, `spatial_preferences`), distributed simulation, and OpenClaw defaults.
- `gaworld/settings/behavior.py`: news, intervention, interests, human-realism, and dynamic-behavior defaults.
- `gaworld/settings/personality.py`: Big Five personality defaults — the three channel gates, the style-fit amplitude and modifier band, prompt rendering, the emotion set point, and the population sampling prior.
- `gaworld/settings/economy.py`: personal finance and macro-economy defaults.
- `gaworld/settings/integrations.py`: extension hooks and real-work execution defaults.
- `gaworld/settings/overrides.py`: dashboard, environment file, and `GAWORLD_CONFIG_OVERRIDES` merge logic.

## Data Layout

- `data/hangzhou_agents_state_init.csv`: seed state values.
- `data/hangzhou_profiles_with_names.md`: seed agent profiles.
- `data/citymap.md`: default city map.
- `data/news_source.md` and `data/news_cache.json`: news/RAG seed material (the legacy homepage list).
- `data/info_sources.json`: the typed information-source registry (news / social / professional) residents' media diets are drawn from.
- `data/environment_config.json`: environment-server override input.
- `data/skills/*.md`: global Skill library — Markdown + YAML frontmatter, shared by every agent.

Root-level imports like `from config import CONFIG` remain supported.
New code that needs config assembly should prefer `gaworld.settings`.

## Generated Or Auxiliary Content

- `output/`: generated simulation artifacts, logs, memory, plots, CSVs.
  - `output/memory/agent_<id>_growth.json`: per-agent hobby/skill progress state.
  - `output/memory/growth_profiles.json`: cached LLM-derived growth profiles.
  - `output/memory/agent_<id>_skills/*.md`: per-agent private Skills, generated by experience-to-skill consolidation.
  - `output/memory/agent_<id>_env_preferences.json`: per-agent learned location-avoidance preferences (stateful runs only).
  - `output/collaboration/sessions/<session_id>/`: durable Dashboard
    discussion/cooperation state (`session.json`), observable event stream
    (`events.jsonl`), and cooperation Markdown under `artifacts/`; the root
    is configurable through `CONFIG["collaboration"]["sessions_dir"]`.
  - `output/work/`: real-work artifacts, capability cache, queue/market event logs.
  - `output/infosources/feed.json`: recent items per registered information source
    (refreshed on real time); `output/infosources/diets.json`: every resident's
    media diet for the current run.
  - `output/records/travel.depart.jsonl` / `travel.return.jsonl`: one row per
    trip out of the city and back, with the whole itinerary (purpose,
    destination, distance, mode, fare, home node, dates). The only
    externally visible quantity this subsystem produces — without it "who is
    out of town today" is a number nothing can see.
  - `output/economy/interventions.json`: the External Systems panel's queue of
    macro/sector changes. Consumed by `gaworld/economy/finance.py` at each
    simulated day boundary — the one channel available for mid-run monetary
    intervention, since economy runtime state lives in the simulator subprocess
    and `macro_state.json` is an output the simulator never reads back.
- `site/`: dashboard and visualization frontends.
  - `site/dashboard/`: Dashboard (`index.html`) with reciprocal friendship
    and independent discussion controls; Agent Studio (`studio.html` —
    single-agent 7-step builder/inspector, wired to the state CSV + profile
    Markdown via the Studio endpoints in `dashboard_server.py`); Population
    Studio (`population.html` — 5-step population generation, group-mode run
    and validation verdict, backed by `gaworld/apps/population_api.py`, with two
    node headless render tests — `population.test.js` for the input steps and
    `population-verdict.test.js`, which drives the verdict card with a verbatim
    validator payload so a renamed field in Python cannot silently blank it);
    Cities (`city.html`, whose resident list lives in `city-agents.js` with the
    `city-agents.test.js` node test, shared with Agent Studio's city picker);
    the cooperation
    lifecycle/artifact page (`collaboration.html`); Group Interview
    (`survey.html` — 3-step respondent picking / question authoring / results,
    backed by `gaworld/apps/interview_api.py`; its renderers live in
    `survey-charts.js` as pure DOM-free functions with the
    `survey-charts.test.js` node test, and every display string is injected by
    the host page so the bilingual UI never prints Chinese chrome into an
    English locale); and External Systems
    (`external.html` — observe/edit the money system, the external-environment
    generator and the outward service connections, backed by
    `gaworld/apps/external_systems_api.py`, with the `external.test.js` node
    headless render test); and the playground (`games.html` — a static hub of
    game cards, so adding a game is a card plus a page rather than another
    backend registry — leading to the arena (`arena.html`) and the persuasion
    game (`persuade.html`), which share `games.css`). Charts are hand-written SVG:
    this tree has no build step and vendors no chart library, and a CDN
    dependency would cost the dashboard its offline usability.
  - `site/console/`: unified console whose exact `合作任务` tab opens
    `/site/dashboard/collaboration.html`, whose `人口与群体` tab opens
    `/site/dashboard/population.html`, whose `群体采访` tab opens
    `/site/dashboard/survey.html`, whose `游戏场` tab opens
    `/site/dashboard/games.html` and whose `外部系统` tab opens
    `/site/dashboard/external.html`.
- `video/`: Remotion video project.
- `tmp/`: local temporary/generated scratch content.
- `backup/`: historical scripts, not active runtime.
