# Repeated-answer calibration and live acceptance

User authorized roadmap items 1 and 2. Extend replication with default-off `sampling_probe` (`enabled`, `repeats` 2–5). Repeats are EXTRA independent draws per main/active variant; original main and one-shot probes remain unchanged. Extra draws are seed-shuffled within each resident. All inputs/model/personas fixed, no memory writes. Budget `(1 + variants) * (1 + repeats)` per assigned resident-condition pair when enabled. Interaction rounds are separate and not repeated by this setting.

New sampling card uses only repeated draws (not the always-first original answer), so original fixed position cannot bias calibrated contrasts. Numeric per-resident mean repeated variant minus mean repeated main; identity contrast uses repeated B minus A. Independent unit resident, never draw. Within-person per-variant SD and nominal disagreement are descriptive; contrasts use existing Bonferroni intervals across all predeclared item/condition/contrasts. Separate sampling_margin. Any missing draw excludes resident for that contrast; missing residents block equivalence, duplicates/malformed records block inference. Effects/group gaps remain untested. No claim of proven causation or subtracting random noise from observed bias.

Tasks: failing tests; sampling module + runner/cards; UI + budget/locales; mocked regression/browser/scoped lint/core; independent review; live acceptance with pinned default provider, 8 fixed real residents, 1 condition, numeric + nominal item, order contrast, 3 extra repeats. 8 * 2 * 4 = 64 application answer calls, no model interpretation; bounded attempts, no fallback/switching; store protocol before calls and append raw per-call journal for interruption safety. No fabricated human data: use explicitly synthetic engineering reference, no human-validity claims. Report outputs/failures and limits. No commits.


## Completed validation

- 105 targeted Python tests passed, 1 optional OpenAPI validator skipped, 889 subtests passed. Core 515 passed, 1 same skip, 950 subtests passed. Node result-card suites: 13 passed.
- Ruff scoped checks/format and repository lint ratchet passed; repository Ruff version mismatch means global totals advisory. git diff --check passed.
- Independent review found malformed-input audit bug; added regression tests (red then green) and finite nonbool/range/structure checks. Reviewer reproduced stable valid input and insufficient corrupt inputs; P2 closed.
- Fixture browser checked 20-person/order/3-repeat budget161 including interpretation, invalid repeat count blocking, submitted settings, 390px dark and desktop light layouts. No real calls from browser fixture.
- Real MiniMax-M3 experiment executed 64 application calls (hard budget), 50 parsed successes, 14 service quota failures. 8 main answers valid, only 4 residents complete for repeated contrasts. Evidence insufficient; complete-sample acceptance remains limited by provider quota. See output/research/sampling_acceptance/2026-11-05-minimax-m3/acceptance.md and original journal/protocol. No fallback, added budget, substituted residents or commits.

## Recovery completed (2026-11-05)

User authorized continuation. Pinned original provider provenance and exact prompts; 14 extra calls, 14 parsed successes. Parent protocol/run/journal hashes unchanged, all 50 original successful slots unchanged, all 14 original failed snapshots retained. Final 64 valid slots / 8 complete residents. Numeric repeated-mean contrast -0.229, adjusted CI [-0.551, 0.093], within predeclared ±1. Recovery is a separate child run with manifest/journal/checkpoints and verification.json; cross-time recovery is not an independent replication. No production code changes in this recovery turn.
