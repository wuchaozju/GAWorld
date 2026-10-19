import copy

import pytest

from gaworld.research import batch_compare, batches


def record():
    batch = batches.new(
        {"title": "Test", "hypotheses": [], "execution_mode": "tick"},
        {"providers": ["a", "b"], "cities": ["c"], "repeats": 3},
    )
    for cell, effect in zip(batch["cells"], [-1.0, -2.0, -3.0, 1.0, 2.0, 3.0], strict=True):
        cell.update(
            status="done",
            result={
                "protocol_hash": batch["protocol_hash"],
                "model": cell["provider"],
                "mode": "tick",
                "provider": cell["provider"],
                "sample_hash": "population",
                "epoch": 1,
                "model_config_hash": "params",
                "valid": True,
                "hypotheses": [
                    {"id": "H1", "mean_effect": effect, "direction": "decrease", "verdict": "inconclusive"}
                ],
                "telemetry": {"requests": 10, "requests_failed": 1},
            },
        )
    return batch


def test_run_level_statistics_and_model_comparison():
    compared = batch_compare.compare(record())
    a, b = compared["groups"]
    assert (a["mean"], a["sd"], a["n"], a["direction_rate"]) == (-2.0, 1.0, 3, 1.0)
    assert a["ci95"][0] < -2 < a["ci95"][1]
    assert b["direction_rate"] == 0
    assert compared["contrasts"][0]["difference"] == pytest.approx(4)
    assert compared["contrasts"][0]["paired_seeds"] == 3
    assert compared["counts"]["planned"] == 6


def test_missing_tasks_and_selected_subset_have_explicit_denominators():
    data = record()
    data["cells"][1].update(status="failed", error="provider unavailable")
    out = batch_compare.compare(data, [c["id"] for c in data["cells"][:3]])
    assert out["counts"] == {"planned": 6, "selected": 3, "done": 2, "failed": 1, "pending": 0}
    assert out["groups"][0]["n"] == 2
    assert out["issues"][0]["cell_id"] == data["cells"][1]["id"]
    with pytest.raises(ValueError):
        batch_compare.compare(data, ["missing"])


def test_mixed_epochs_are_split_and_wrong_actual_provider_is_excluded():
    data = record()
    data["cells"][1]["result"]["epoch"] = 2
    data["cells"][2]["result"]["provider"] = "fallback"
    out = batch_compare.compare(data)
    assert len([g for g in out["groups"] if g["provider"] == "a"]) == 2
    assert any("模型" in issue["reason"] for issue in out["issues"])
    assert not out["contrasts"]  # no complete matched repeat sets across epochs


def test_fixed_seeds_report_variation_without_claiming_seed_robustness():
    data = record()
    data["matrix"]["seed_strategy"] = "fixed"
    for cell in data["cells"]:
        cell["seed"] = 42
    group = batch_compare.compare(data)["groups"][0]
    assert group["unique_seeds"] == 1
    assert group["ci95"] is None
    assert group["seed_robustness"] is False
    assert group["sd"] == 1


def test_single_repeat_has_no_interval_and_unknown_provenance_does_not_pool():
    data = record()
    data["cells"][1]["result"]["sample_hash"] = "other sample"
    data["cells"][2]["result"]["epoch"] = None
    groups = batch_compare.compare(copy.deepcopy(data))["groups"]
    assert all(g["n"] == 1 for g in groups if g["provider"] == "a")
    assert all(g["ci95"] is None for g in groups if g["n"] == 1)


def test_actual_model_drift_is_excluded_even_when_provider_alias_matches():
    data = record()
    data["models"] = {"a": {"model": "a"}, "b": {"model": "b"}}
    data["cells"][0]["result"]["model"] = "different-model"
    result = batch_compare.compare(data)
    assert any("模型" in item["reason"] for item in result["issues"])
    assert next(g for g in result["groups"] if g["provider"] == "a")["n"] == 2


def test_model_failure_and_measured_calls_include_unsuccessful_cells():
    data = record()
    data["cells"][0]["status"] = "failed"
    output = batch_compare.compare(data)
    metric = next(m for m in output["runtime_metrics"] if m["provider"] == "a")
    assert metric["planned"] == 3
    assert metric["failed"] == 1
    assert metric["task_failure_rate"] == pytest.approx(1 / 3)
    assert metric["requests"] == 30
    assert metric["request_failure_rate"] == pytest.approx(0.1)
