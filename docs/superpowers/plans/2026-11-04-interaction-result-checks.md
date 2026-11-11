# Interaction and short-context memory checks

**Goal:** Continue the approved result-check roadmap with optional synchronous peer-answer feedback and own-answer context controls in replication.

**Architecture:** `interaction_probe.py` executes isolated four-arm rounds after the main answers. `interaction_checks.py` validates settings, partitions nonoverlapping groups, and measures final-round group contrasts. Existing cards, API ownership, protocol hashes and exports carry the evidence. No new API or simulation entry logic.

## Fixed design

Default off. Researcher selects rounds 1–3 and maximum group size 2–8, default 1 round / size 4. Each condition partitions its assigned residents into seeded, balanced groups (no singleton; reject impossible partitions, including odd counts with maximum size 2). Reject an enabled check with any condition below two residents before any call. One group may run but cannot support inferential claims.

All arms start from the same main answers: fresh (neither history), self (own previous answer), peers (other group members' previous answers), both. From round 2 onward, each arm reads only its own previous-round state. A barrier completes every round before the next. Prompt scaffold and persona/items/condition are identical; structured answer visibility differs, own answer is excluded from peers. Only the last round is used for interval decisions; earlier rounds are descriptive trajectory evidence. Fixed seeded rotations counterbalance within-resident arm call positions. No long-term memory writes or identity-probe answers enter feedback.

Budget adds `4 * rounds * assigned resident-condition pairs` answer calls. Failures are recorded and never repaired with another respondent. Persist group membership, round/arm/call order, source round, visible structured answers, raw output and prompt hashes. The existing selected provider remains pinned with fallback disabled.

Numeric checks use equally weighted complete group means: peer effect = both − self, own-context effect = both − peers, interaction = both − self − peers + fresh. Correct final-round intervals across all numeric comparisons using predeclared item/condition/three-contrast family size. Independent unit is group, not resident or round. A per-item `interaction_margin` is separate from human and identity tolerances. Any missing baseline or arm answer in any round excludes that group for that item; missing groups prevent overall equivalence. Duplicates/unknown groups prohibit inference. Zero variance or fewer than two independent groups is insufficient. Any detected contrast flags sensitivity; all three must be within margin to mark stability for these checks only.

Nominal choices report all option shifts descriptively, never means of option codes. Per-arm within-group pairwise disagreement and baseline disagreement describe convergence (numeric in original units, nominal mismatch fraction); agreement alone is not correctness or bias. Checks attach only to item/condition level cells. Treatment effects and demographic subgroup rows remain untested for interaction because arbitrary slices are not independent experimental groups. No automatic human, fairness, consensus-emergence or long-term memory claims.

## Tasks

- [x] Failing tests for normalization, budget/default off, group partition/preflight, synchronous arm isolation, own-peer exclusion, missing/error propagation, group-unit inference, nominal descriptions and scope.
- [x] Implement isolated runner and deterministic measurement; integrate protocol, execution, cards, exports and interpretation.
- [x] Add UI opt-in, rounds/group-size settings, independent tolerances and budget; locale/render tests and fixture browser verification.
- [x] Run targeted and core tests, scoped lint and repository ratchet. Obtain independent review and fix concrete findings. Update tutorial and record actual validation; no real model calls or commits.

## Validation completed

- Related Python suites: 126 passed, 1 skipped (optional OpenAPI validator unavailable), 889 subtests passed. Focused result/identity/interaction/replication set: 80 passed.
- Core suite: 515 passed, 1 skipped for the same optional validator, 950 subtests passed. Existing font warnings remain.
- Three result-check Node suites: 12 passed; JavaScript syntax and both locale key sets checked.
- New/changed Python scope passes Ruff and format checks. Repository lint ratchet passed with no regression (tool reports version mismatch, so repository totals are advisory).
- Independent read-only review found no confirmed must-fix issue.
- Real browser with fixture-only local server: 20 residents / 2 rounds / one condition shows 181 calls including interpretation; invalid rounds disable submission; settings reach the run endpoint. Downloaded JSON confirms 180 answer calls, 5 groups, 2 rounds, all four arms, exposures, raw output, and prompt hashes. Desktop light and 390px dark mobile checked with no horizontal overflow.
- Local evidence: `output/playwright/interaction-desktop.png`, `interaction-mobile-settings.png`, `interaction-mobile-result.png`, `interaction-download.json`. These are simulated fixture artifacts, not scientific model results.
- No real model calls, commits, deployment, or edits to other ongoing feature work.
