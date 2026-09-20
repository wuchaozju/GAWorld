# GAWorld system-paper artifact ledger

Audited on 2026-07-12 (Asia/Shanghai). This ledger freezes the evidence used by
the paper; it does not assert that every archived experiment is complete or
that the current working tree is a released simulator version.

## Repository snapshot

- Architecture/runtime baseline: `35a551e` (includes completed K1--K5 scope)
- Branch: `Dev`
- A final read-only refresh verified the nine built-ins, scoped Controller
  wiring, standard interventions, and Recorder lifecycle. Unrelated
  untracked `website/` content and generated paper files are outside the
  architecture snapshot.
- Consequence: hashes below remain the controlling byte identifiers for every
  source and result artifact used by the manuscript.

## Status semantics

| Status | Meaning | Permitted manuscript wording |
|---|---|---|
| IMPLEMENTED | Connected to the current runtime and inspectable in source | "GAWorld implements/provides..." |
| PARTIALLY_INTEGRATED | Code exists and at least one dispatch path is connected, but compatibility paths remain | "GAWorld has begun integrating..." |
| DESIGNED | Proposal or dormant code exists without a verified current runtime path | "The design specifies..." |
| EVIDENCE_INCOMPLETE | A result artifact is missing, interrupted, unreplicated, or insufficient | "The current archive does not assess..." |
| DIAGNOSTIC_FIXTURE | Synthetic or fixture data exercises a software path but is not simulation evidence | "The fixture verifies the analysis path..." |

`COMPLETE` below is an evidence label, not an implementation status: the cited
artifact is adequate for its narrowly stated descriptive use.

## Architecture claim map

| Claim ID | Status | Current sources | Allowed claim and audit note |
|---|---|---|---|
| S-KERNEL | IMPLEMENTED | `gaworld/kernel/{context,registry,bus,clock,controller,recorder,interventions}.py`; `gaworld/sim/pipeline.py`; `generative_city_sim.py` | The scoped K1--K5 migration is complete: six services, nine built-ins, stage dispatch, movement validation, and standard interventions are connected. Direct compatibility paths remain. |
| S-PLUGIN-POLICY | IMPLEMENTED | `gaworld/policy/plugin.py`; `gaworld/policy/intervention.py`; current `gaworld/plugins/__init__.py` | The intervention adapter registers runtime bus hooks and delegates feed/metric persistence to the existing intervention implementation. |
| S-PLUGINS | IMPLEMENTED | `gaworld/plugins/__init__.py`; domain `plugin.py` adapters | Nine built-ins cover Intervention, Skills, Interests, Life Events, Economy, Local Physical, Real Work, Dynamic Behavior, and Spatial Preferences. Archived experiments predate the completed migration. |
| S-AGENT | PARTIALLY_INTEGRATED | `gaworld/core/agent.py`; `gaworld/sim/agents_loader.py`; `generative_city_sim.py` | A typed dictionary-compatible adapter and profile parsing exist, but agent construction and many call sites still use legacy dictionaries in the entrypoint. |
| S-MEMORY | IMPLEMENTED | `gaworld/memory/`; `gaworld/sim/_memory_recall.py` | File-backed episodic storage, recall, lifecycle maintenance, consolidation, and decay paths exist. This is an implementation claim, not evidence of human memory validity. |
| S-WORLD | IMPLEMENTED | `gaworld/world/city_map.py`; `gaworld/world/local_physical.py`; `gaworld/env/system.py` | Graph-based city locations, local physical state, weather, and environmental event mechanisms are implemented. |
| S-SOCIETY | IMPLEMENTED | `gaworld/social/network.py`; `gaworld/economy/finance.py`; `gaworld/events/life.py` | Social-network, finance, and life-event mechanisms exist; their empirical validity must be assessed separately. |
| S-WORK | IMPLEMENTED | `gaworld/work/{runtime,router,queue,market,worker}.py`; `gaworld/work/adapters/` | Work briefs can be routed through capability adapters and artifacts persisted; successful task quality is outside this source audit. |
| S-INTERFACE | IMPLEMENTED | `gaworld/apps/dashboard_server.py`; `site/dashboard/{index,studio}.html`; `site/simviz/index.html` | Dashboard control, Agent Studio editing, and trace-viewer front ends are present and have serving/API paths. |
| S-DISTRIBUTED | IMPLEMENTED | `gaworld/distributed/comm.py`; `gaworld/apps/distributed_comm_server.py` | An HTTP relay client/server mode for agent registration, directory discovery, and message transfer exists; no scalability result is claimed. |
| S-UNIVERSAL-ISOLATION | DESIGNED | `docs/proposals/2026-07-11-microkernel-plugin-architecture.md` plus current compatibility paths | K1--K5 completion must not be described as universal plugin ownership, unified recording, or mediation of every action. |

## Result-artifact map

| Evidence ID | Status | Repository source | Allowed use and prohibited inference |
|---|---|---|---|
| E-MEM | EVIDENCE_INCOMPLETE | `docs/proposals/results/exp_memory_consistency/COMPARISON_REPORT.md` | Show that the archive contains cross-phase diaries/state/memory artifacts. Only `memory_intact` completed both phases; the other three treatments stopped after phase 1, so no treatment-effect conclusion is allowed. |
| E-POLICY | EVIDENCE_INCOMPLETE | Four `comparison_summary.md` and `comparison_metrics.csv` pairs listed below | Demonstrate event/baseline pairing and metric extraction. These are single archived comparisons with repeated inactive intervention metrics; deltas are not real policy effects. |
| E-INFO | EVIDENCE_INCOMPLETE | `docs/proposals/results/exp_misinfo_spread/comparison_results.json` | Demonstrate a treatment-oriented information-metric schema. Runs have unequal duration (control/treatment B 2 days; treatment A 1 day), misinformation risk is zero throughout, and cross-viewpoint exposure is only descriptive. |
| E-ECON | COMPLETE | `docs/proposals/results/exp_macro_economy/run_42/state/agent_state_history.csv`; `wellbeing_report.md` | Demonstrate a 5-agent, 3-day, 11,600-row long-format state trace (20 metrics × 116 steps per agent) and derived descriptive summaries. The Markdown report's “580 timesteps per agent” conflates the 116 steps across five agents; the CSV is controlling. It is one seeded run, not evidence about people, economies, or policies. |
| E-NET | EVIDENCE_INCOMPLETE | `docs/proposals/results/exp_network_evolution/natural_evolution/analysis_summary.json` | Report the archived 5-node/2-edge initialization snapshot and explicitly disclose zero recorded interactions on all 14 days; do not claim emergent network laws or homophily. |
| E-POLARIZATION | EVIDENCE_INCOMPLETE | `docs/proposals/results/exp_polarization/comparison_results.json` | Show availability of a polarization comparison artifact only; use numbers descriptively and retain its archived-run limitations. |
| E-EMOTION | EVIDENCE_INCOMPLETE | `docs/proposals/results/exp_emotion_contagion/comparison_results.json` | Document a failed/incomplete evaluation: all four entries report missing state-history files. No contagion result is available. |
| E-BENCH | DIAGNOSTIC_FIXTURE | `benchmark/gaworld_bench.py`; `benchmark/results/scorecard.json` | Verify the benchmark analysis path only. The scorecard matches the built-in synthetic fixture and must not be presented as a GAWorld simulation result. |

## Quantitative-source hashes

Hashes identify the audited bytes, not a universally reproducible simulator
release. Relative paths are from the repository root.

| Evidence | Path | SHA-256 |
|---|---|---|
| E-MEM | `docs/proposals/results/exp_memory_consistency/COMPARISON_REPORT.md` | `473ab06368ad7c775d605a689588a807cad5a87aebb6db960cab80371117e49c` |
| E-INFO | `docs/proposals/results/exp_misinfo_spread/comparison_results.json` | `7dd82acb4944d1276886f1e3d26953ac598ae7fe6da9d671f751d9919623bcad` |
| E-ECON | `docs/proposals/results/exp_macro_economy/run_42/state/agent_state_history.csv` | `d2ee92a0c37ad3a0ac9b0541778b88af0bd502f7a94609eff8c28b3d847c70df` |
| E-ECON | `docs/proposals/results/exp_macro_economy/run_42/wellbeing_report.md` | `a4a0e1a2d636e9b68c33fe60589ab8f9ccc07ce6c8b5fb2022208e3cb799cb0e` |
| E-NET | `docs/proposals/results/exp_network_evolution/natural_evolution/analysis_summary.json` | `e6bc277bf0640022889ff79d6116c070f139092982e7c478a27ed00c7be2191c` |
| E-POLARIZATION | `docs/proposals/results/exp_polarization/comparison_results.json` | `96dea04e88d383847a12d61dbeb4b6baf62c3654f63c9cff5e5638dbcdc1292f` |
| E-EMOTION | `docs/proposals/results/exp_emotion_contagion/comparison_results.json` | `e8856de8d5f9bf2af2601a9c2a96f1d059e4400199d0078d98aa7076ee7b99de` |
| E-BENCH | `benchmark/gaworld_bench.py` | `d181ad8d68cca7f9e3f64089c51135f70a68d3d0b5082b766465434f52ceb07e` |
| E-BENCH | `benchmark/results/scorecard.json` | `afe5c0fac7bf47210c8bf8484dadf8f312a418ebdf63fc1cc4bd6d504364c131` |
| E-POLICY housing | `docs/proposals/results/exp_policy_framework/housing_subsidy/20260531_002817_住房补贴政策/comparison_summary.md` | `ec2b99bcee7e85b35561e690fef7b580dac64f9c6ead1a3a9dd35033cde853b4` |
| E-POLICY housing | `docs/proposals/results/exp_policy_framework/housing_subsidy/20260531_002817_住房补贴政策/comparison_metrics.csv` | `7c3b04fd713901ffd1907eba7131d62a97f6c16a630c8c309c40f107d040a957` |
| E-POLICY training | `docs/proposals/results/exp_policy_framework/job_training/20260531_005414_职业技能培训补贴/comparison_summary.md` | `1adbfc23f58c6e222c00445146454940314e0bb3722d7b6567a8b571c4b00885` |
| E-POLICY training | `docs/proposals/results/exp_policy_framework/job_training/20260531_005414_职业技能培训补贴/comparison_metrics.csv` | `b94f998831501fbb49bc1886ecb4cc39e080121c494b12175c31452477f727cb` |
| E-POLICY medical | `docs/proposals/results/exp_policy_framework/medical_reform/20260531_003818_医疗报销比例上调/comparison_summary.md` | `dc08dd8789a2aa5eb275b0bff4bb561a68007e286ac8718ea8f9432ce1652f20` |
| E-POLICY medical | `docs/proposals/results/exp_policy_framework/medical_reform/20260531_003818_医疗报销比例上调/comparison_metrics.csv` | `0d65fcb83c0c99c0d61d026b63a930603d0aeee4542014c6821270e79a660453` |
| E-POLICY traffic | `docs/proposals/results/exp_policy_framework/traffic_restriction/20260531_001140_临时交通限行/comparison_summary.md` | `f0cbf6f7ff5700f0e8d344b33394683e656fcecf0db31d1edc0180a31fda1e12` |
| E-POLICY traffic | `docs/proposals/results/exp_policy_framework/traffic_restriction/20260531_001140_临时交通限行/comparison_metrics.csv` | `47aa72756d85bd370285e3a00d3559dffcf377c925342fa325f2554c9dc8b868` |

## Architecture-source snapshot hashes

These hashes support implementation-status review. They are not quantitative
evidence and intentionally cover representative entry points rather than every
file in a directory.

| Claim | Path | SHA-256 |
|---|---|---|
| S-KERNEL | `gaworld/kernel/context.py` | `69e3ae4bfe002e444b57ac859c6ab5b62d69f25c255fa728017bd9046ce6953c` |
| S-KERNEL | `gaworld/kernel/registry.py` | `6fad8cabd1e3f59543e09d017f2cfda19d1b79d10052a0c5b8c9ed7be6c8e881` |
| S-KERNEL | `gaworld/sim/pipeline.py` | `a2e9651d922948240655d27a83c0da11ef063083dabc79164eb5a70e1521ed82` |
| S-KERNEL | `generative_city_sim.py` | `1c2b04c18e1cac67a223bc91451d067d033f76d5878e958730385bc7aedf3e1d` |
| S-PLUGIN-POLICY | `gaworld/policy/plugin.py` | `8d06e8786141813ef9e60352ded4835be4d5ed22c216593dbab7d2e1da7a68b2` |
| S-PLUGINS | `gaworld/plugins/__init__.py` | `e37c4a449c602c32bca73b22860ce1c94366b998d3eac1932fd81b47770b4d4f` |
| S-PLUGINS | `gaworld/events/plugin.py` | `3d5318e6da4a898a810af9c415d3cb9dbbe992475a342af136233a6c11dd977a` |
| S-PLUGINS | `gaworld/economy/plugin.py` | `47379d2e8de16dd03c9c5126732c46a528c4fbf7ff011a6618ea9f33055fb697` |
| S-PLUGINS | `gaworld/world/plugin.py` | `d58d2194412490e54eff39071951b08674c217c4e9a1d7dfd8095686306c3334` |
| S-PLUGINS | `gaworld/work/plugin.py` | `08ce7f96ac0d108f9c5482154cc2b96a86d1b8edb284028956d1a22fea550721` |
| S-PLUGINS | `gaworld/behavior/plugin.py` | `27df75551f4e305949633e00003cdfa2715d074f810be33966be72c4817b3dec` |
| S-KERNEL | `gaworld/kernel/interventions.py` | `c21dfe097006d8d0e39d30a67bfdcad87b3781d0fbeaa025322fd8c7a22d537d` |
| S-AGENT | `gaworld/core/agent.py` | `2ee145d9284675c0c53cb336935679b137c5c182bf78be1b4ef389962d1507ff` |
| S-AGENT | `gaworld/sim/agents_loader.py` | `69611a90380445dcc0042643c47f6022aac130dd8b31f2a75a05558943d8acd0` |
| S-MEMORY | `gaworld/memory/store.py` | `fc536ecb014118d5ccd7c23fb47287d14ce068f9d10184850fc2268058c3bc98` |
| S-MEMORY | `gaworld/sim/_memory_recall.py` | `f2a97c9311d00fb19b19980f20fea6f864fc662d05487198d8302f748c5baa8f` |
| S-WORLD | `gaworld/world/city_map.py` | `3849f3116f64b76e0ef686d962aa6ab7b2ee922741eb64c0ce9bebd5e25a91cb` |
| S-WORLD | `gaworld/env/system.py` | `892843c4cb258aa2be2d5ba179ccf2e4fd01770658ae18104e4e2cf617052cc3` |
| S-SOCIETY | `gaworld/social/network.py` | `b76f744571c7630ab529742f3a9fba2dd88c90f66f2ab2b28d74f838700dbb8d` |
| S-SOCIETY | `gaworld/economy/finance.py` | `f3f7ef779babe866216b18358a6c7ad992fd7d5c5f4d5f03269a2bb94edb8ad9` |
| S-SOCIETY | `gaworld/events/life.py` | `4b824e383452d689bd35c339d8bf4252bec57f3b06e9466bee2d1bde9c706465` |
| S-WORK | `gaworld/work/runtime.py` | `23582f83b2b72460e9ac50298932e93e2b3f99369f33f024d02563e818ab8c18` |
| S-INTERFACE | `gaworld/apps/dashboard_server.py` | `2b569c33406e35fde13aa16ec10ccd9506b948869e6fbaa4eb614a311c54deca` |
| S-INTERFACE | `site/dashboard/studio.html` | `33f2f1ddb7fbdfbb986a6ad946cd7e4fce30209da1d5c7929cba08c4186ba04c` |
| S-INTERFACE | `site/simviz/index.html` | `ec619680496331c742fb422a92dbd97ad1097e07efce78801b06d105f5296a56` |
| S-DISTRIBUTED | `gaworld/distributed/comm.py` | `504cac27b55869192506acecffa1f91d2024f1d929b4d0194adc9f41e30d75c4` |
| S-DISTRIBUTED | `gaworld/apps/distributed_comm_server.py` | `6817f215954784d14b2de18defe728f3a18ebfee3b51ef85af53816bb4ef6243` |
| S-UNIVERSAL-ISOLATION | `docs/proposals/2026-07-11-microkernel-plugin-architecture.md` | `4e4390c1b1d47de6d66c5ac65b9ee4e80ee2c93d5b685cebda2bf286f411868b` |

## Drafting rules derived from the audit

1. Keep implementation existence separate from scientific validation.
2. Use capability verbs (records, routes, exposes, persists) for source-backed
   mechanisms; reserve effect language for adequately replicated evaluations.
3. Label every archived case as descriptive and name its missing controls,
   treatments, durations, or replications.
4. Treat legacy report interpretations as commentary, not ground truth; compute
   any manuscript number directly from its hashed CSV/JSON where possible.
5. Re-run the hashes before arXiv packaging. Any mismatch requires updating the
   ledger and re-auditing the associated manuscript sentence.
