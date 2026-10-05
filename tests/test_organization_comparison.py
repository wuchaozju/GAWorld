"""Offline comparisons use completed, real organization metric exports."""

from __future__ import annotations

import copy
import csv
import hashlib
import importlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from tests.test_economy_conservation import _build_agent
from tests.test_organization_end_to_end import boot


def module():
    assert importlib.util.find_spec("gaworld.organizations.comparison") is not None
    return importlib.import_module("gaworld.organizations.comparison")


def make_export(root, rule="equal_split", hiring="lottery", *, requests=True, day=1, community_budget=10000):
    people = [_build_agent(1, age=28), _build_agent(2, age=70), _build_agent(3, age=45)]
    people[0]["gender"], people[1]["gender"] = "男", "女"
    svc, context = boot(root, people)
    try:
        for person, cash, skill in zip(people, [100, 10, 50], [0.2, 0.9, 0.5], strict=True):
            person["economy"]["accounts"].update(checking=cash, savings=0)
            person["economy"]["income_skill"] = skill
        for oid, kind, decision_rule, budget in (
            ("care", "community", rule, community_budget),
            ("firm", "company", hiring, 100000),
        ):
            svc.store.enqueue(
                {
                    "type": "create",
                    "organization_id": oid,
                    "name": oid,
                    "kind": kind,
                    "leader_id": 3,
                    "member_ids": [1, 2, 3],
                    "rule": decision_rule,
                    "initial_balance_cents": budget,
                }
            )
        svc.store.enqueue(
            {
                "type": "publish_job",
                "organization_id": "firm",
                "job_id": "job",
                "occupation": "工程师",
                "vacancies": 1,
                "monthly_salary_cents": 400000,
            }
        )
        if requests:
            for number in [1, 2]:
                svc.store.enqueue(
                    {
                        "type": "apply_aid",
                        "organization_id": "care",
                        "agent_id": number,
                        "amount_cents": 10000,
                    }
                )
                svc.store.enqueue(
                    {
                        "type": "apply_job",
                        "organization_id": "firm",
                        "agent_id": number,
                        "job_id": "job",
                    }
                )
        svc.process_day(day)
        if requests:
            hired = next(person for person in people if person["ext"]["organizations"]["employer_id"])
            svc.pay_wage(hired, 1100, context, "wage")
        svc.finish_day(day)
    finally:
        svc.close()
    path = root / "organizations" / "metrics.json"
    return path, json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture
def exports(tmp_path):
    left_path, left = make_export(tmp_path / "left")
    right_path, right = make_export(tmp_path / "right", "need_first", "skill_first")
    return left_path, left, right_path, right


def organization(report, oid):
    return next(row for row in report["organizations"] if row["organization_id"] == oid)


def metric(rows, name, **filters):
    return next(
        row for row in rows if row["metric"] == name and all(row.get(k) == v for k, v in filters.items())
    )


def test_real_exports_compare_coverage_groups_and_finite_payroll_without_mutating_inputs(exports):
    _, left, _, right = exports
    originals = copy.deepcopy((left, right))
    report = module().compare_metrics(left, right, left_label="等额分配", right_label="困难优先")
    assert report["direction"] == "right_minus_left"
    assert report["mode"] == "descriptive_cumulative_snapshot_comparison"
    assert report["sources"]["left"]["generation_id"] != report["sources"]["right"]["generation_id"]
    care = organization(report, "care")
    coverage = metric(care["metrics"], "coverage")
    assert (coverage["left"], coverage["right"], coverage["difference"]) == (1, 0.5, -0.5)
    assert metric(care["metrics"], "coverage_denominator")["left"] == 2
    assert metric(care["metrics"], "aid_paid_cents")["difference"] == 0
    older = metric(care["groups"], "aid_paid_cents", dimension="age_band", group="65_plus")
    assert (older["left"], older["right"], older["difference"]) == (5000, 10000, 5000)
    firm = organization(report, "firm")
    assert metric(firm["metrics"], "hires")["left"] == 1
    assert metric(firm["metrics"], "wage_owed_cents")["right"] == 110000
    assert metric(firm["metrics"], "wage_paid_cents")["left"] == 100000
    assert metric(firm["metrics"], "arrears_cents")["right"] == 10000
    assert (left, right) == originals


def test_zero_denominators_remain_undefined_and_unknown_groups_are_retained(tmp_path):
    _, left = make_export(tmp_path / "left", requests=False)
    _, right = make_export(tmp_path / "right", requests=False)
    report = module().compare_metrics(left, right)
    care = organization(report, "care")
    for name in ["coverage", "mean_waiting_days"]:
        row = metric(care["metrics"], name)
        assert row["left"] is row["right"] is row["difference"] is None
    unknown = metric(care["groups"], "coverage", dimension="gender", group="unknown")
    assert unknown["difference"] is None


def test_coverage_is_recomputed_and_unfunded_budget_ratio_is_undefined(exports, tmp_path):
    _, left, _, right = exports
    right = copy.deepcopy(right)
    right["organizations"][0]["coverage"] += 1e-10
    report = module().compare_metrics(left, right)
    assert metric(organization(report, "care")["metrics"], "coverage")["right"] == 0.5
    _, empty = make_export(tmp_path / "unfunded", requests=False, community_budget=0)
    report = module().compare_metrics(empty, empty, organization_id="care")
    assert metric(organization(report, "care")["metrics"], "budget_utilization")["difference"] is None


@pytest.mark.parametrize(
    "problem",
    [
        "day",
        "scope",
        "kind",
        "organization_ids",
        "duplicate",
        "negative_count",
        "boolean_count",
        "fractional_cents",
        "nan_ratio",
        "coverage_mismatch",
        "group_totals",
        "missing_group",
    ],
)
def test_incompatible_or_corrupt_exports_are_rejected(exports, problem):
    _, left, _, right = exports
    right = copy.deepcopy(right)
    row = right["organizations"][0]
    if problem == "day":
        right["day"] += 1
    elif problem == "scope":
        right["scope"] = "daily_increment"
    elif problem == "kind":
        row["kind"] = "company"
    elif problem == "organization_ids":
        row["organization_id"] = "different"
    elif problem == "duplicate":
        right["organizations"].append(copy.deepcopy(row))
    elif problem == "negative_count":
        row["applications"] = -1
    elif problem == "boolean_count":
        row["applications"] = True
    elif problem == "fractional_cents":
        row["balance_cents"] = 1.5
    elif problem == "nan_ratio":
        row["budget_utilization"] = float("nan")
    elif problem == "coverage_mismatch":
        row["coverage"] = 0.9
    elif problem == "group_totals":
        row["groups"]["gender"]["unknown"]["applications"] += 1
    elif problem == "missing_group":
        del row["groups"]["gender"]
    with pytest.raises(module().ComparisonError):
        module().compare_metrics(left, right)


def test_selected_organization_can_be_compared_when_other_organization_sets_differ(exports):
    _, left, _, right = exports
    right = copy.deepcopy(right)
    right["organizations"] = right["organizations"][:1]
    report = module().compare_metrics(left, right, organization_id="care")
    assert [row["organization_id"] for row in report["organizations"]] == ["care"]


def test_arrears_must_match_unpaid_labor_obligations(exports):
    _, left, _, right = exports
    right = copy.deepcopy(right)
    right["organizations"][1]["arrears_cents"] = 0
    with pytest.raises(module().ComparisonError, match="arrears"):
        module().compare_metrics(left, right)


@pytest.mark.parametrize("oid", ["care", "firm"])
@pytest.mark.parametrize("scope", ["organization", "group"])
def test_decided_applications_cannot_have_conflicting_outcomes(exports, oid, scope):
    _, left, _, right = exports
    right = copy.deepcopy(right)
    row = organization(right, oid)
    covered = "paid_aid_applications" if oid == "care" else "hires"
    if scope == "organization":
        row["rejections"] += 1
        row["rejection_reasons"]["corrupt_duplicate_outcome"] = 1
        for distribution in row["groups"].values():
            next(group for group in distribution.values() if group[covered])["rejections"] += 1
    else:
        distribution = row["groups"]["gender"]
        next(group for group in distribution.values() if group[covered])["rejections"] += 1
        next(group for group in distribution.values() if group["rejections"] and not group[covered])[
            "rejections"
        ] -= 1
    with pytest.raises(module().ComparisonError, match="outcomes"):
        module().compare_metrics(left, right)


@pytest.mark.parametrize("field", ["coverage", "budget_utilization"])
def test_huge_ratios_are_cli_input_errors_without_partial_report(exports, tmp_path, capsys, field):
    left_path, _, right_path, right = exports
    right["organizations"][0][field] = 10**500
    right_path.write_text(json.dumps(right), encoding="utf-8")
    cli = importlib.import_module("gaworld.organizations.__main__")
    output = tmp_path / "unwritten"
    assert cli.main(["compare", str(left_path), str(right_path), "--output-dir", str(output)]) == 2
    assert "error" in json.loads(capsys.readouterr().err)
    assert not output.exists()


def test_file_report_preserves_sources_and_writes_hashes_unicode_csv_and_markdown(exports, tmp_path):
    left_path, _, right_path, _ = exports
    before = {path: path.read_bytes() for path in [left_path, right_path]}
    output = tmp_path / "report"
    paths = module().compare_files(
        left_path, right_path, output, left_label="等额|分配", right_label="困难优先"
    )
    report = json.loads(Path(paths["json"]).read_text(encoding="utf-8"))
    for key, path in [("left", left_path), ("right", right_path)]:
        assert report["sources"][key]["sha256"] == hashlib.sha256(before[path]).hexdigest()
        assert report["sources"][key]["path"] == str(path.resolve())
        assert path.read_bytes() == before[path]
    text = Path(paths["markdown"]).read_text(encoding="utf-8")
    assert "等额\\|分配" in text and "-50.00" in text
    assert "累计" in text and "申请" in text and "因果" in text
    assert "gender" in Path(paths["csv"]).read_text(encoding="utf-8")
    assert "rule_history" in report["definitions"]


def test_cli_compare_succeeds_without_opening_or_creating_database(exports, tmp_path):
    left_path, _, right_path, _ = exports
    isolated = tmp_path / "empty-working-directory"
    isolated.mkdir()
    root = Path(__file__).resolve().parents[1]
    program = (
        "import sys;sys.path.insert(0, sys.argv.pop(1));"
        "from gaworld.organizations.__main__ import main;raise SystemExit(main(sys.argv[1:]))"
    )
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            program,
            str(root),
            "compare",
            str(left_path),
            str(right_path),
            "--output-dir",
            str(tmp_path / "cli-report"),
            "--organization-id",
            "care",
        ],
        cwd=isolated,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr
    assert Path(json.loads(result.stdout)["json"]).is_file()
    assert not list(isolated.rglob("*.sqlite"))


def test_output_cannot_replace_an_input_even_via_symlink(exports, tmp_path):
    left_path, _, right_path, _ = exports
    output = tmp_path / "collision"
    output.mkdir()
    (output / "comparison.json").symlink_to(left_path)
    original = left_path.read_bytes()
    with pytest.raises(module().ComparisonError, match="input"):
        module().compare_files(left_path, right_path, output)
    assert left_path.read_bytes() == original
    assert not (output / "comparison.csv").exists()


@pytest.mark.parametrize("content", [None, "{broken", "[]", '{"day": NaN}'])
def test_bad_source_file_fails_before_creating_report(exports, tmp_path, content):
    _, _, right_path, _ = exports
    source = tmp_path / "bad.json"
    if content is not None:
        source.write_text(content, encoding="utf-8")
    output = tmp_path / "unwritten"
    with pytest.raises(module().ComparisonError):
        module().compare_files(source, right_path, output)
    assert not output.exists()


def test_cli_missing_source_reports_exit_two_without_database(exports, tmp_path, capsys):
    _, _, right_path, _ = exports
    cli = importlib.import_module("gaworld.organizations.__main__")
    result = cli.main(
        [
            "compare",
            str(tmp_path / "missing.json"),
            str(right_path),
            "--output-dir",
            str(tmp_path / "unwritten"),
        ]
    )
    assert result == 2
    assert "error" in json.loads(capsys.readouterr().err)
    assert not (tmp_path / "unwritten").exists()


def test_report_labels_are_safe_table_text_and_csv_formulas_stay_literal(exports, tmp_path):
    left_path, _, right_path, _ = exports
    paths = module().compare_files(
        left_path,
        right_path,
        tmp_path / "safe-report",
        left_label="\n =SUM(1,2)",
        right_label="[link](https://invalid.example)<script>",
    )
    with Path(paths["csv"]).open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert rows[0]["left_label"].startswith("'")
    assert any(row["difference"] == "-5000" for row in rows)
    text = Path(paths["markdown"]).read_text(encoding="utf-8")
    assert "\\[link\\]" in text and "&lt;script&gt;" in text
    assert "<script>" not in text


def test_rule_changes_are_identified_as_cumulative_history(exports, tmp_path):
    left_path, _, right_path, right = exports
    right["organizations"][0]["rule_version"] = 2
    right_path.write_text(json.dumps(right), encoding="utf-8")
    paths = module().compare_files(left_path, right_path, tmp_path / "history-report")
    text = Path(paths["markdown"]).read_text(encoding="utf-8")
    assert "存在规则版本变更" in text and "较早规则" in text


@pytest.mark.parametrize("flag", ["--world", "--generation"])
def test_explicit_files_cannot_be_mistaken_for_active_world_queries(exports, tmp_path, capsys, flag):
    left_path, _, right_path, _ = exports
    cli = importlib.import_module("gaworld.organizations.__main__")
    result = cli.main(
        [
            flag,
            "some-id",
            "compare",
            str(left_path),
            str(right_path),
            "--output-dir",
            str(tmp_path / "unwritten"),
        ]
    )
    assert result == 2
    assert "explicit file inputs" in json.loads(capsys.readouterr().err)["error"]
    assert not (tmp_path / "unwritten").exists()
