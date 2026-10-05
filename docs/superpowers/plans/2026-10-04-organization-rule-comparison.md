# Organization Rule Comparison Implementation Plan

> **For agentic workers:** Execute this plan in the current session, test first, then request a read-only code review. Preserve unrelated edits and leave changes uncommitted.

**Goal:** Complete the approved v1 design §9 by comparing two completed organization metric exports offline and writing auditable JSON, CSV and Chinese Markdown reports.

**Architecture:** A pure comparison module under `gaworld/organizations/` consumes the existing cumulative metric export format. File IO and readable report rendering are in `comparison_report.py`. The organization CLI accepts two explicit local `metrics.json` files and runs before opening any database. Reports describe right-minus-left differences at the same completed day; they retain denominators, unknown groups, explicit funding totals, current rule versions and input hashes. The existing simulation, APIs and financial behavior are unchanged.

**Tech Stack:** Python standard library (`json`, `csv`, `hashlib`, `pathlib`), existing organization exports, pytest; no model or network calls.

Approved basis: `docs/proposals/2026-10-03-persistent-organizations-v1-design.md` §9 and the user's repeated requests to continue. This is offline rule comparison within that scope. A research-workbench scoring backend or autonomous organization strategy would require a separate design.

## Contract and choices

Keep the comparison offline rather than adding a cross-world API or modifying research hypothesis scoring. The CLI reads explicitly named export files. Same organization IDs/kinds and the same completed day are mandatory; an optional organization ID selects one common organization. Generations remain separately labeled. The scope must be `cumulative_current_generation`, so daily snapshots are never summed as if they were incremental observations.

Coverage ratios and mean waiting days are recomputed from their exported numerators and denominators. Budget utilization uses the validated exported ratio and its explicit funding denominator, because the current metric format does not export an expense numerator. A zero denominator produces `null`, including the difference when either side is undefined. Group records are application weighted, include unknown categories and are checked against organization totals. Rejection reasons use the union of observed codes. A rule label means the current rule; version >1 is explicitly identified as potentially including earlier rules in the cumulative history. Reports do not estimate a causal effect or a significance level.

An input file cannot also be a report output target. Reports retain absolute source paths and SHA-256 hashes, and do not open/create an organization SQLite database. Invalid input is rejected before writing results.

## Task 1: Comparison and input validation

Files: create `gaworld/organizations/comparison.py`; create `tests/test_organization_comparison.py`.

- [x] Add tests for same-day community differences, finite company wages/arrears, `right_minus_left`, source labels, immutable inputs, zero denominators and unknown groups.
- [x] Add tests rejecting mismatched day/scope/kind/IDs, duplicate organizations, negative/non-integer counts, nonfinite ratios, inconsistent coverage and inconsistent group totals. Test a selected organization against extra organizations in either file.
- [x] Run `python -m pytest tests/test_organization_comparison.py -q`; verify missing comparison module is the observed failure.
- [x] Implement `ComparisonError(ValueError)` and `compare_metrics(left, right, *, organization_id=None, left_label="A", right_label="B")`. Its returned value must satisfy:
  ```python
  result = compare_metrics(left, right)
  assert result["direction"] == "right_minus_left"
  assert result["sources"]["left"]["generation_id"] == left["generation_id"]
  assert result["sources"]["right"]["day"] == right["day"]
  ```
  Each comparison row contains `metric`, `unit`, `left`, `right`, `difference`; group rows also contain `dimension` and `group`. Counts and cents stay integers in JSON/CSV. Percentage displays in Markdown show percentage points for differences.
- [x] Run the same tests to green, then format/check the new files.

## Task 2: Files, CLI and report rendering

Files: create `gaworld/organizations/comparison_report.py`; update `gaworld/organizations/comparison.py`, `gaworld/organizations/__main__.py`, and the new test module.

- [x] Write failing CLI tests using real files: success without database creation, missing/corrupt files returning exit 2, same-file output collision rejection, Unicode content and Markdown table escaping.
- [x] Add the command shape:
  ```sh
  python -m gaworld.organizations compare LEFT/metrics.json RIGHT/metrics.json --output-dir REPORT --organization-id care --left-label 等额分配 --right-label 困难优先
  ```
  Reject `--world`/`--generation` with explicit-file comparison because the file inputs already define the sources. Emit report file paths on success.
- [x] Implement `compare_files(...)` to load and hash sources, validate through `compare_metrics`, then write `comparison.json`, `comparison.csv`, and `comparison.md`. Escape table cells, retain undefined ratios, and write atomically. Reject collisions with source files, including resolved symlinks.
- [x] Run comparison tests plus existing API/CLI tests; preserve all existing subcommand behavior.

## Task 3: Real-export example, review and verification

Files: update `docs/ORGANIZATIONS_TUTORIAL.md`, `docs/FEATURES.md`, and this plan.

- [x] Add an end-to-end test with actual `OrganizationService.finish_day` exports for both community rules and both company rules. Verify report differences and source preservation from actual exports.
- [x] Produce a clearly labeled synthetic-data example report in the task visualization directory using actual finance/services and no LLM calls. Inspect the generated Markdown and JSON; opening the report helps the user review it.
- [x] Document command syntax, same-day cumulative scope, application denominators, rule-version history and the descriptive interpretation boundary.
- [x] Request read-only review using the requesting-code-review skill; resolve important findings with reproducing tests.
- [x] Run new comparison tests, all organization suites, Ruff on changed/new Python files, `git diff --check`, and `python -m pytest --suite core -q`. Record exact results and any shared-worktree failures here.

## Self-review

The tool uses existing exports rather than inventing a second source of balances or outcomes. It writes only local reports requested by explicit CLI paths, stays outside live payments, and adds no public API or permissions. Its undefined-rate handling and current-rule labels prevent two common reporting mistakes. Full tests and a real synthetic report are required before completion.

## Completion evidence

- TDD: observed the absent comparison module and absent CLI parser command as failures before implementation. Added canonical coverage and whitespace-prefixed CSV formula tests, observed their failures, then fixed them.
- Review: read-only reviewer identified three P2 input-validation gaps. Seven reproducing tests initially failed for inconsistent arrears, conflicting organization/group terminal outcomes in both pilots, and huge ratio integers. All pass after the fixes; independent follow-up review found no important remaining issue.
- Comparison plus existing API/CLI tests: **60 passed**. All eight organization Python test modules: **156 passed**, with 12 existing plot font warnings.
- Core suite: **462 passed, 1 skipped, 667 subtests passed** (3060 deselected). The skipped OpenAPI validator test requires the uninstalled optional `openapi-spec-validator`; 96 existing plot warnings were reported.
- Ruff check and format check passed for the two new modules, CLI and new tests. `git diff --check` passed. No unrelated files were reformatted or staged.
- Real-service synthetic artifact: `/Users/cw/.codex/visualizations/2026/10/03/01a100d1-3c40-7c91-bb3e-bdfb8d5a4618/organization-rule-comparison/report/comparison.md`. Both three-resident worlds used actual organization/finance exports, with no model calls. The official CLI generated JSON, Markdown and 326 CSV rows. Source byte preservation and SHA-256 hashes were verified, and Markdown/JSON were inspected. The native file open request was queued by the app; the final artifact link remains usable.
- Synthetic example: community total aid is 100 yuan in each world, with coverage 100% versus 50%; age 65+ aid is 50 versus 100 yuan. Each company has one hire, 1100 yuan labor obligation, 1000 yuan paid and 100 yuan outstanding. These figures are a demonstration of deterministic rules under specified inputs, not a real-world policy conclusion.
- Documentation now covers command syntax, completed-day/cumulative scope, application-weighted groups, funding metadata limits and current-rule mixed history. No simulation, API or financial semantics were changed in this iteration; changes remain uncommitted in the shared working tree.
