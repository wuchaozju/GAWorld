# Contract tests for `fos.experiments.sweep_kit` — the runnable layer of the
# Gui & Toubia (2025) unblinding comparison (design doc §2.2-2.8).
# Specifies: the blinded system prompt (the paper Prompt 2 / Prompt 10
# system line VERBATIM — the Prompt-5 shortening is drift), the unblinded
# system prompt (design paragraph + fill task), the Prompt-2 purchase
# survey, covariate fill-in probes (paper Prompts 1/7/8 wording and order,
# plus the income probe), tolerant parsers, demand aggregation,
# self-describing records, the injected-chat sweep/diagnostic runners, the
# confounding summary over randomization.check_confounding, a JSON manifest
# writer, and the import-safe CLI script scripts/unblinding_sweep.py. The
# paper-fidelity contract (tests/test_paper_fidelity.py, TASK-1483) is the
# shared source of truth for the system line, probe wording and probe
# sentence order pinned here (pre-GREEN re-spec, TASK-1487).

import importlib.util
import inspect
import json
import socket
import sys
from datetime import datetime
from pathlib import Path

import pytest

from fos.experiments import sweep_kit as sweep_kit_mod
from fos.experiments.randomization import RandomizationDesign, check_confounding
from fos.experiments.sweep_kit import (
    aggregate_demand,
    build_blinded_system_prompt,
    build_covariate_fillin_prompt,
    build_purchase_user_prompt,
    build_record,
    build_unblinded_system_prompt,
    parse_fillin_number,
    parse_purchase,
    run_diagnostic,
    run_sweep,
    summarize_confounding,
    write_manifest,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO_ROOT / "scripts" / "unblinding_sweep.py"

# The paper's verbatim Prompt 2 / Prompt 10 system line (RESULT-1474 §1):
# the customer fills in the blanks and returns comma-separated values. The
# blinded purchase condition must use exactly this line, never the Prompt-5
# shortening ("fill in the blank ... without extra text").
PROMPT2_SYSTEM = (
    "You, AI, are a customer. Your task is to fill in the blanks. "
    "Return the completed information in comma-separated values, without any "
    "extra text."
)


def _price_design(**overrides):
    base = RandomizationDesign(
        variable="price",
        label="the price of the product",
        min_value=0.0,
        max_value=200.0,
        unit="% of regular price",
        distribution="grid",
        grid_points=3,
        blinding="unblinded",
        seed=None,
        blind_to_randomization=True,
        covariates_specified=[],
    )
    return RandomizationDesign.from_json({**base.to_json(), **overrides})


def _products():
    return [
        {
            "category": "Soft Drinks - Carbonated",
            "product": "Coca-Cola Soda Pop, 12 fl oz, 12 Pack Cans",
            "regular_price": 8.26,
        },
        {
            "category": "Snacks",
            "product": "Lay's Classic Potato Chips",
            "regular_price": 4.50,
        },
    ]


def _record(design, value, raw, parsed, seed=1):
    return build_record(design, "blinded", "m", "p", "c", value, raw, parsed, 1.0, seed)


class _FakeChat:
    """Injected chat function: records every call, never touches a network."""

    def __init__(self, answer="purchase"):
        self.answer = answer
        self.calls = []

    def __call__(self, messages, temperature):
        self.calls.append((messages, temperature))
        return self.answer


# 1-2. System prompts (blinded = paper Prompt 2 system line; unblinded = Prompt 6)


class TestSystemPrompts:
    def test_blinded_system_prompt_is_the_verbatim_prompt2_system(self):
        # Pre-drift the blinded condition used the Prompt-5 shortening
        # ("fill in the blank ... without extra text"); the paper-fidelity
        # contract demands the full Prompt 2 / Prompt 10 system line.
        prompt = build_blinded_system_prompt()
        assert prompt == PROMPT2_SYSTEM, (
            f"blinded system prompt must equal paper Prompt 2's system line, "
            f"got {prompt!r}"
        )
        assert "customer" in prompt.lower()
        assert "fill in the blanks" in prompt
        assert "comma-separated values" in prompt

    def test_unblinded_prompt_composes_paragraph_and_fillin_task(self):
        design = _price_design(blinding="unblinded")
        prompt = build_unblinded_system_prompt(design)
        assert design.render_unblinding() in prompt
        assert "fill in the blank" in prompt.lower()
        assert "without extra text" in prompt.lower()

    def test_blinded_design_returns_exactly_the_blinded_prompt(self):
        design = _price_design(blinding="blinded")
        assert build_unblinded_system_prompt(design) == build_blinded_system_prompt()


# 3. Purchase survey (paper Prompt 2)


class TestBuildPurchaseUserPrompt:
    def test_purchase_prompt_has_the_survey_shape(self):
        prompt = build_purchase_user_prompt(
            "Soft Drinks - Carbonated", "Coca-Cola", 8.26
        )
        assert "Soft Drinks - Carbonated" in prompt
        assert "Coca-Cola" in prompt
        assert "$8.26" in prompt
        assert "purchase" in prompt
        assert "not purchase" in prompt
        assert "Return example" in prompt

    def test_purchase_prompt_keeps_the_price_when_above_one_dollar(self):
        prompt = build_purchase_user_prompt("Snacks", "Lay's Chips", 19.99)
        assert "$19.99" in prompt


# 4. Covariate fill-in probes (paper Prompt 1 / 7 / 8, plus the income probe)


class TestBuildCovariateFillinPrompt:
    def test_every_kind_prompt_shows_the_current_price_line(self):
        for kind in ("last_price", "competing_price", "expiry_days"):
            prompt = build_covariate_fillin_prompt(kind, "Snacks", "Lay's Chips", 4.50)
            assert "currently priced" in prompt, kind
            assert "4.50" in prompt, kind

    def test_last_price_prompt_asks_for_the_past_purchase_price(self):
        prompt = build_covariate_fillin_prompt(
            "last_price", "Snacks", "Lay's Chips", 4.50
        )
        assert "last time you purchased" in prompt
        assert "[a number" in prompt

    def test_competing_price_prompt_states_the_focal_price_first(self):
        # Paper Prompt 7: the current-price sentence comes first, then the
        # competing-product fill-in. The pre-drift probe reversed the order.
        prompt = build_covariate_fillin_prompt(
            "competing_price", "Snacks", "Lay's Chips", 4.50
        )
        assert "competing product" in prompt
        assert "[a number" in prompt
        price_index = prompt.index("The product is currently priced at")
        fill_index = prompt.index(
            "The price of a similar competing product from a different brand is"
        )
        assert price_index < fill_index, (
            "competing-price probe must state the focal price before the "
            "competing-price fill-in (paper Prompt 7 order)"
        )

    def test_expiry_days_probe_uses_the_paper_sentence_in_the_paper_order(self):
        # Paper Prompt 8 wording and order, with no added premise sentence.
        prompt = build_covariate_fillin_prompt(
            "expiry_days", "Snacks", "Lay's Chips", 4.50
        )
        assert (
            "The expiration date of the product is [a whole number] days from now."
            in prompt
        ), "expiry probe must use the paper's sentence verbatim (Prompt 8)"
        price_index = prompt.index("The product is currently priced at")
        expiry_index = prompt.index("The expiration date of the product is")
        assert price_index < expiry_index, (
            "expiry probe must state the focal price before the expiration "
            "fill-in (paper Prompt 8 order)"
        )
        assert "Suppose you purchase this product today." not in prompt, (
            "the invented 'Suppose you purchase this product today.' preamble "
            "must be gone"
        )
        assert "It will expire" not in prompt, (
            "the rephrased 'It will expire' fill-in must be gone"
        )

    def test_unknown_kind_raises_value_error(self):
        with pytest.raises(ValueError):
            build_covariate_fillin_prompt(
                "brand_loyalty_score", "Snacks", "Lay's Chips", 4.50
            )

    def test_an_income_kind_is_registered_and_names_total_family_income(self):
        # The paper-fidelity contract (spec item 5): a diagnostic fill-in
        # probe whose machine name mentions "income" must be registered in
        # the kit and must ask for the total family income as a whole number.
        probes = getattr(sweep_kit_mod, "_COVARIATE_PROBES", {})
        kinds = [kind for kind in probes if "income" in kind.lower()]
        assert kinds, "no income probe kind registered in the sweep kit"
        prompt = build_covariate_fillin_prompt(kinds[0], "Snacks", "Lay's Chips", 4.50)
        assert "total family income" in prompt.lower(), (
            f"income probe {kinds[0]!r} must ask for the total family income"
        )
        assert "[a whole number]" in prompt, (
            f"income probe {kinds[0]!r} must use a whole-number blank"
        )


# 5. parse_purchase()


class TestParsePurchase:
    def test_parse_purchase_reads_purchase_and_not_purchase_case_insensitively(self):
        assert parse_purchase("purchase") is True
        assert parse_purchase("Purchase") is True
        assert parse_purchase("PURCHASE") is True
        assert parse_purchase("not purchase") is False
        assert parse_purchase("Not Purchase") is False
        assert parse_purchase("NOT PURCHASE") is False

    def test_parse_purchase_tolerates_whitespace_and_punctuation(self):
        assert parse_purchase("  purchase  ") is True
        assert parse_purchase("purchase.") is True
        assert parse_purchase('"purchase"') is True
        assert parse_purchase(" not purchase? ") is False
        assert parse_purchase('"not purchase"') is False

    def test_parse_purchase_returns_none_for_garbage_and_empty(self):
        assert parse_purchase("") is None
        assert parse_purchase("   ") is None
        assert parse_purchase("maybe") is None
        assert parse_purchase("I would purchase it") is None


# 6. parse_fillin_number()


class TestParseFillinNumber:
    def test_parse_fillin_number_reads_decimal_and_whole_amounts(self):
        assert parse_fillin_number("8.26") == pytest.approx(8.26)
        assert parse_fillin_number("10") == pytest.approx(10.0)

    def test_parse_fillin_number_tolerates_dollar_sign_and_whitespace(self):
        assert parse_fillin_number("$8.26") == pytest.approx(8.26)
        assert parse_fillin_number(" $ 8.26 ") == pytest.approx(8.26)

    def test_parse_fillin_number_returns_none_for_garbage(self):
        assert parse_fillin_number("") is None
        assert parse_fillin_number("abc") is None
        assert parse_fillin_number("about 5 dollars") is None
        assert parse_fillin_number("8.2.6") is None


# 7. aggregate_demand()


class TestAggregateDemand:
    def test_aggregate_demand_builds_one_sorted_bucket_per_level(self):
        design = _price_design()
        records = [
            _record(design, 0.0, "purchase", True),
            _record(design, 100.0, "purchase", True),
            _record(design, 200.0, "not purchase", False),
        ]
        buckets = aggregate_demand(records, [200.0, 0.0, 100.0])
        assert [bucket["level"] for bucket in buckets] == [0.0, 100.0, 200.0]
        assert set(buckets[0]) == {"level", "p_buy", "n"}

    def test_aggregate_demand_computes_the_purchase_fraction_per_level(self):
        design = _price_design()
        records = [
            _record(design, 0.0, "purchase", True),
            _record(design, 0.0, "not purchase", False),
            _record(design, 100.0, "purchase", True),
            _record(design, 200.0, "not purchase", False),
            _record(design, 200.0, "not purchase", False),
        ]
        buckets = {
            b["level"]: b for b in aggregate_demand(records, [0.0, 100.0, 200.0])
        }
        assert buckets[0.0]["p_buy"] == pytest.approx(0.5)
        assert buckets[100.0]["p_buy"] == pytest.approx(1.0)
        assert buckets[200.0]["p_buy"] == pytest.approx(0.0)

    def test_aggregate_demand_excludes_unparsed_records_from_both_counts(self):
        design = _price_design()
        records = [
            _record(design, 0.0, "purchase", True),
            _record(design, 0.0, "purchase", True),
            _record(design, 0.0, "garbage", None),
        ]
        bucket = aggregate_demand(records, [0.0])[0]
        assert bucket["n"] == 2
        assert bucket["p_buy"] == pytest.approx(1.0)


# 8. build_record()


class TestBuildRecord:
    def test_build_record_carries_the_full_required_schema(self):
        design = _price_design(seed=5)
        record = build_record(
            design,
            "unblinded",
            "qwen3-8b",
            "Coca-Cola",
            "Soft Drinks - Carbonated",
            80.0,
            "purchase",
            True,
            2.5,
            7,
        )
        assert {
            "design",
            "treatment_value",
            "blinding",
            "model",
            "product",
            "category",
            "raw_content",
            "parsed_purchase",
            "elapsed_seconds",
            "succeeded",
            "seed",
        } <= set(record)
        assert record["design"] == design.to_json()
        expected = {
            "treatment_value": 80.0,
            "blinding": "unblinded",
            "model": "qwen3-8b",
            "product": "Coca-Cola",
            "category": "Soft Drinks - Carbonated",
            "raw_content": "purchase",
            "parsed_purchase": True,
            "elapsed_seconds": 2.5,
            "seed": 7,
            "succeeded": True,
        }
        for key, value in expected.items():
            assert record[key] == value, key

    def test_unparsed_answer_is_not_succeeded_and_false_answer_is(self):
        missing = build_record(
            _price_design(), "blinded", "m", "p", "c", 40.0, "garbage", None, 1.0, 1
        )
        assert missing["succeeded"] is False
        assert missing["parsed_purchase"] is None
        refused = build_record(
            _price_design(),
            "blinded",
            "m",
            "p",
            "c",
            40.0,
            "not purchase",
            False,
            1.0,
            1,
        )
        assert refused["succeeded"] is True
        assert refused["parsed_purchase"] is False


# 9. run_sweep()


class TestRunSweep:
    def _run(self, design, chat, draws, blinding, seed=7, products=None):
        return run_sweep(
            design,
            products if products is not None else _products(),
            "qwen3-8b",
            chat,
            draws=draws,
            blinding=blinding,
            seed=seed,
        )

    def test_run_sweep_calls_chat_once_per_product_level_and_draw(self):
        design = _price_design()
        chat = _FakeChat()
        records = self._run(design, chat, draws=2, blinding="blinded")
        expected = len(_products()) * len(design.grid()) * 2
        assert len(chat.calls) == expected
        assert len(records) == expected

    def test_run_sweep_sends_the_right_system_prompt_per_blinding(self):
        blinded = _price_design(blinding="blinded")
        chat = _FakeChat()
        self._run(blinded, chat, draws=1, blinding="blinded")
        for messages, _temperature in chat.calls:
            assert [m["role"] for m in messages] == ["system", "user"]
            assert messages[0]["content"] == build_blinded_system_prompt()
        unblinded = _price_design(blinding="unblinded")
        chat2 = _FakeChat()
        # One product (Coca-Cola) is enough to check the per-blinding system
        # prompt and that the survey names the product. Sweeping a second
        # product here would send Lay's surveys, which never mention
        # "Coca-Cola" and so cannot satisfy the assertion below.
        self._run(
            unblinded,
            chat2,
            draws=1,
            blinding="unblinded",
            products=_products()[:1],
        )
        for messages, _temperature in chat2.calls:
            assert messages[0]["content"] == build_unblinded_system_prompt(unblinded)
            assert messages[-1]["content"] and "Coca-Cola" in messages[-1]["content"]

    def test_run_sweep_forwards_the_paper_temperature_of_one(self):
        design = _price_design()
        chat = _FakeChat()
        self._run(design, chat, draws=2, blinding="blinded")
        assert chat.calls
        assert {t for _messages, t in chat.calls} == {1.0}

    def test_run_sweep_records_keep_metadata_and_stay_in_support(self):
        design = _price_design()
        chat = _FakeChat(answer="not purchase")
        records = self._run(design, chat, draws=2, blinding="blinded")
        assert records
        for record in records:
            assert design.min_value <= record["treatment_value"] <= design.max_value
            assert record["model"] == "qwen3-8b"
            assert record["blinding"] == "blinded"
            assert record["succeeded"] is True
            assert record["parsed_purchase"] is False
            assert record["raw_content"] == "not purchase"
        assert {r["product"] for r in records} == {p["product"] for p in _products()}

    def test_run_sweep_grid_design_visits_every_level_evenly(self):
        design = _price_design()
        products = _products()
        chat = _FakeChat()
        records = self._run(
            design, chat, draws=3, blinding="blinded", products=products
        )
        actual = sorted(r["treatment_value"] for r in records)
        expected = sorted(v for p in products for _ in range(3) for v in design.grid())
        assert actual == expected

    def test_run_sweep_is_deterministic_for_the_same_seed(self):
        design = _price_design(distribution="uniform", seed=42)
        first = self._run(
            design,
            _FakeChat(),
            draws=5,
            blinding="blinded",
            seed=11,
            products=_products()[:1],
        )
        second = self._run(
            design,
            _FakeChat(),
            draws=5,
            blinding="blinded",
            seed=11,
            products=_products()[:1],
        )
        first_values = [r["treatment_value"] for r in first]
        assert first_values == [r["treatment_value"] for r in second]
        assert len(first_values) == len(design.grid()) * 5
        for value in first_values:
            assert design.min_value <= value <= design.max_value


# 10. run_diagnostic()


class TestRunDiagnostic:
    def test_run_diagnostic_calls_chat_once_per_product_level_kind_and_draw(self):
        design = _price_design()
        kinds = ["last_price", "competing_price", "expiry_days"]
        chat = _FakeChat(answer="$12.50")
        records = run_diagnostic(
            design, _products(), kinds, chat, draws=2, blinding="blinded"
        )
        expected = len(_products()) * len(design.grid()) * len(kinds) * 2
        assert len(chat.calls) == expected
        assert len(records) == expected

    def test_run_diagnostic_records_pair_level_and_covariate_under_blinded_prompt(self):
        design = _price_design(blinding="blinded")
        kinds = ["last_price", "competing_price", "expiry_days"]
        chat = _FakeChat(answer="$12.50")
        records = run_diagnostic(
            design, _products()[:1], kinds, chat, draws=2, blinding="blinded"
        )
        assert chat.calls
        assert {r[design.variable] for r in records} == set(design.grid())
        for messages, _t in chat.calls:
            assert messages[0]["content"] == build_blinded_system_prompt()
        for record in records:
            assert design.min_value <= record[design.variable] <= design.max_value
            present = [kind for kind in kinds if kind in record]
            assert len(present) == 1
            assert record[present[0]] == pytest.approx(12.5)


# 11. summarize_confounding()


def _confounded_records():
    records = []
    for level in (0.0, 100.0, 200.0):
        for offset in (-0.1, 0.1):
            records.append({"price": level, "last_price": level + offset})
            records.append({"price": level, "competing_price": 5.0})
    return records


class TestSummarizeConfounding:
    def test_summarize_confounding_reports_each_kind_with_rho_and_ci(self):
        design = _price_design()
        result = summarize_confounding(_confounded_records(), design)
        assert set(result) == {"last_price", "competing_price"}
        for stats in result.values():
            assert set(stats) == {"rho", "ci_lo", "ci_hi", "flag"}

    def test_summarize_confounding_matches_check_confounding_flag_logic(self):
        design = _price_design()
        records = _confounded_records()
        result = summarize_confounding(records, design)
        expected_severe = check_confounding(
            [r for r in records if "last_price" in r], "price", "last_price"
        )
        expected_ok = check_confounding(
            [r for r in records if "competing_price" in r], "price", "competing_price"
        )
        assert result["last_price"] == expected_severe
        assert result["competing_price"] == expected_ok
        assert result["last_price"]["flag"] == "severe"
        assert result["competing_price"]["flag"] == "ok"


# 12. write_manifest()


def _is_iso_timestamp(text):
    try:
        datetime.fromisoformat(text)
    except ValueError:
        return False
    return True


class TestWriteManifest:
    def _write(self, path, **overrides):
        args = dict(
            model="qwen3-8b",
            draws=5,
            blinding="unblinded",
            products=_products(),
            base_url="http://localhost:1234/v1",
            extra={"note": "smoke test", "temperature": 1.0},
        )
        args.update(overrides)
        return write_manifest(path, _price_design(distribution="grid", seed=42), **args)

    def test_write_manifest_writes_json_with_design_args_extra_and_timestamp(
        self, tmp_path
    ):
        path = tmp_path / "manifest.json"
        self._write(path)
        loaded = json.loads(path.read_text())
        assert loaded["design"] == _price_design(distribution="grid", seed=42).to_json()
        assert loaded["model"] == "qwen3-8b"
        assert loaded["draws"] == 5
        assert loaded["blinding"] == "unblinded"
        assert loaded["products"] == _products()
        assert loaded["base_url"] == "http://localhost:1234/v1"
        assert loaded["note"] == "smoke test"
        assert loaded["temperature"] == 1.0
        assert any(
            isinstance(v, str) and _is_iso_timestamp(v) for v in loaded.values()
        ), "manifest should carry an ISO-8601 timestamp"

    def test_write_manifest_never_shells_out_for_git_or_network(self, tmp_path):
        import subprocess

        def _forbid(*_args, **_kwargs):
            raise AssertionError(
                "write_manifest must not shell out (no git, no network)"
            )

        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr(subprocess, "run", _forbid)
        try:
            self._write(tmp_path / "offline.json", extra={})
        finally:
            monkeypatch.undo()
        assert json.loads((tmp_path / "offline.json").read_text())["design"] is not None


# 13. scripts/unblinding_sweep.py


def _load_sweep_script():
    spec = importlib.util.spec_from_file_location("unblinding_sweep", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None, f"no loader for {SCRIPT_PATH}"
    module = importlib.util.module_from_spec(spec)
    sys.modules[module.__name__] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(module.__name__, None)
    return module


class TestUnblindingSweepScript:
    def test_script_defines_main_behind_a_main_guard(self):
        module = _load_sweep_script()
        assert callable(module.main)
        assert "argv" in inspect.signature(module.main).parameters
        assert inspect.signature(module.main).parameters["argv"].default is None
        assert 'if __name__ == "__main__":' in SCRIPT_PATH.read_text()

    def test_importing_the_script_never_opens_a_connection(self):
        def _forbid_socket(*_args, **_kwargs):
            raise AssertionError("importing unblinding_sweep must not open a socket")

        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr(socket, "socket", _forbid_socket)
        try:
            module = _load_sweep_script()
        finally:
            monkeypatch.undo()
        assert callable(module.main)

    def test_script_help_exits_zero_and_lists_every_sweep_option(self, capsys):
        module = _load_sweep_script()
        with pytest.raises(SystemExit) as excinfo:
            module.main(["--help"])
        assert excinfo.value.code == 0
        help_text = capsys.readouterr().out
        for option in (
            "--model",
            "--blinding",
            "--draws",
            "--out",
            "--base-url",
            "--products",
            "--diagnose",
            "--seed",
        ):
            assert option in help_text, f"missing option {option} in --help"
