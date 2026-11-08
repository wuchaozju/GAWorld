# Identity cue result checks implementation plan

**Goal:** Continue the approved result-check roadmap with opt-in matched identity cues in the existing replication workbench, preserving main outcomes and reporting per-result evidence.

**Architecture:** A focused `gaworld/research/identity_checks.py` owns normalization, A/B variant construction and paired measurement. Existing replication execution, ownership, export and cards carry those variants. The UI exposes one shared template, two cue values, previews, independent item tolerances and the added call budget.

**Tech stack:** Python, existing SciPy interval helper, pytest and browser JavaScript.

## Design decisions

Choose target/context identity cue substitution over rewriting resident profiles (which risks contradictory biographies) or comparing different demographic cohorts (which confounds identity with other attributes). The shared template contains exactly one `{{identity}}`; A/B replace only that token. The template and values are authored before running. Main stimuli must not already contradict these cues; the researcher verifies relevance. Default off, no automatic demographic category selection, no live model calls during development.

A and B are independent calls from the same resident with unchanged persona, item order and base condition. Add exactly two calls per resident-condition; preserve ordinary main and presentation probes. Seeded counterbalancing assigns A-first/B-first within each condition, records actual probe order, and uses no shared conversation or memory writes. The main answer remains first to preserve the existing main protocol. This checks target/context cues, not actor identity or group dynamics.

Only level cells and subgroup level cells receive numeric identity decisions; treatment effects, group gaps and unrelated workbenches remain untested. Compute B minus A in original units over unique complete resident pairs, with an independent `identity_margin` per numeric item. Use the existing corrected t interval and a prespecified family size based on items/conditions/groups. Duplicates prohibit inference; missing pairs prohibit whole-sample equivalence, and detection among complete pairs is labeled conditional. Nominal items expose all option shifts and switch rate descriptively. Zero variance stays insufficient. A significant difference is sensitivity to these cues, not proof of unfair treatment or a real-world population effect.

## Steps

- [x] Write failing `tests/test_identity_checks.py` cases: default-off/no extra calls; reject invalid enabled settings before any call; only cue changes in variant prompts; balanced seeded execution order; main sample unchanged; B-minus-A direction and separate margin; failure/duplicate/nominal handling; metadata and exports.
- [x] Add identity helper and integrate spec normalization, `replication_checks.variants/attach`, execution order and protocol provenance. Run `python -m pytest tests/test_identity_checks.py tests/test_result_checks.py tests/test_replication.py -q`.
- [x] Add shared browser helper for validation/preview/budget; Node tests verify escaped preview and variant count. Wire the existing replication form, both locales and interpretation caveats. No new API or root Python module.
- [x] Verify real browser interaction on fixture data: default opt-out, previews, invalid settings, budget, payload, per-row result, download, light/dark and 390px layout.
- [x] Run related Python/Node tests, core suite, lint ratchet and diff check. Request scoped independent review if available, resolve concrete findings. Update tutorial and record verification. Preserve unrelated checkout edits and do not commit or run paid research.

## Scope boundary

The user authorized continuation of the staged measurement work. This step implements identity cue checks in replication; group interaction/memory amplification remains a separate study protocol. Statistical evidence is conditional on the recorded model, sample, material, and missing-data pattern. Model endpoint aliases do not guarantee immutable remote weights.


## Completion evidence (2026-11-04)

- Failing regression tests first exposed the absent normalization, opt-in calls, paired measurement and UI helper; implemented and verified. Independent review identified subgroups without human references being skipped; added a failing subgroup regression, included those level cells only when identity checks are enabled, and preserved the original reported-human contrast baselines. Reviewer confirmed the fix with 59 focused tests passing and no remaining actionable findings in scope.
- Core suite: 515 passed, 1 skipped (optional OpenAPI validator unavailable), 944 subtests. Related final suite: 189 passed, 2 skipped (same validator and pre-existing cosmetic locale sort check), 966 subtests. Browser helper/rendering tests: 11 passed. Locale checks after final display labels: 38 passed, 1 cosmetic skip.
- Scoped Ruff check and format check passed for all five Python files changed in this identity step; JavaScript syntax and `git diff --check` passed. The full repository lint ratchet is not clean because concurrently edited organization-intelligence API/comparison files and tests have findings/format issues. Those unrelated changes were preserved; no global clean-lint claim.
- Real-browser fixture check: identity defaults off; enabled incomplete template blocks starting; shared material previews match submitted A/B cues; 10 residents show 31 estimated calls including optional interpretation; submitted independent tolerance 0.4 persists. Download has 30 planned answer calls, 10 pairs, five AB/five BA orders, raw answers, prompt hashes and B-A evidence.
- Desktop light and 390px mobile dark screenshots inspected; no horizontal document overflow; console had no errors/warnings. Screenshots and JSON fixtures are in ignored `output/playwright/identity-*`. Identity cue values and B-A direction appear before expanding raw evidence and are HTML-escaped.
- Development uses deterministic answers only. No real model experiment or account changes, no commits, no actor-profile rewriting, no interaction/memory inference.
