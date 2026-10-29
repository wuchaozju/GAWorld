# Contract tests for the persona_depth experiment axis and three audit-trail
# fixes on the Gui & Toubia (2025) unblinding kit. The persona axis has the
# paper's TWO depth levels {1, 2} — none (bare survey) and demographics (the
# 11 Appendix D fields) — after the paper-fidelity drift fix (TASK-1483);
# the invented behavioural tiers tightwad/time_preference/risk_preference of
# the five-tier ladder are gone everywhere. Locked in:
#   1. RandomizationDesign gains persona_depth ("none"|"demographics"; the
#      removed behavioural tiers and anything else — the superseded
#      "extended" included — raise ValueError) and covariate_count int, both
#      round-tripped through to_json/from_json; a "none" depth leaves
#      render_unblinding unchanged.
#   2. run_sweep records fix the design-blinding bug (the stored design JSON
#      carries the blinding the run actually used, both directions) and add
#      persona_depth, covariate_count, the exact system/user prompts sent and
#      prompt_sha256 = sha256(system + "\x1e" + user).
#   3. write_manifest on a both-conditions run stores blinding_scope and a
#      per-condition designs dict whose blinding field matches its key.
#   4. run_diagnostic records name the product and category being probed.
#   5. run_persona_sweep: one chat call per (product x price level x persona)
#      at temperature 0.0; records carry the persona dict, persona_index,
#      persona_depth, covariate_count and the same design-blinding fix; the
#      user prompt contains the rendered persona fields. CONTRACT CHOICE
#      (mine): it returns (records, skipped_empty) where skipped_empty counts
#      empty-dict personas that got no chat call.
#   6. covariate_count_for_depth maps none->0, demographics->11 (the two
#      paper levels only); tightwad/time_preference/risk_preference raise
#      ValueError; canonical home randomization.py.
#   7. scripts/unblinding_sweep.py accepts --persona-depth {none,demographics}
#      (default none), --personas-dir, --personas-per-product (default 500);
#      importing the script stays socket-free.
#
# The two new functions (run_persona_sweep, covariate_count_for_depth) are
# reached through their module objects so each test fails on its own instead
# of the whole file stopping at import time.

import hashlib
import importlib.util
import json
import socket
import sys
from pathlib import Path

import pytest

from fos.experiments import randomization as randomization_mod
from fos.experiments import sweep_kit as sweep_kit_mod
from fos.experiments.randomization import RandomizationDesign
from fos.experiments.sweep_kit import run_diagnostic, run_sweep, write_manifest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO_ROOT / "scripts" / "unblinding_sweep.py"

# Persona fixtures: each dict is one embodied customer whose fields must show
# up inside the user prompt of the run.
_ALICE = {"age": 35, "city": "Hangzhou", "occupation": "teacher"}
_BOB = {"age": 52, "city": "Shanghai", "occupation": "engineer"}


def _price_design(**overrides):
    """Cheap paper-style price design: 3 grid levels by default."""
    return RandomizationDesign(
        variable="price",
        label="the price of the product",
        min_value=0.0,
        max_value=200.0,
        unit="% of regular price",
        distribution=overrides.pop("distribution", "grid"),
        grid_points=3,
        **overrides,
    )


def _products():
    """Two fixture products in the exact shape run_sweep expects."""
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


def _personas_by_product(per_index):
    """{product: {"category", "personas"}} from fixture products; per_index maps 0/1 to a list."""
    return {
        product["product"]: {
            "category": product["category"],
            "personas": per_index[index],
        }
        for index, product in enumerate(_products())
    }


class _FakeChat:
    """Injected chat function: records every call, never touches a network."""

    def __init__(self, answer="purchase"):
        self.answer = answer
        self.calls = []

    def __call__(self, messages, temperature):
        self.calls.append((messages, temperature))
        return self.answer


# 1. RandomizationDesign persona_depth and covariate_count fields


class TestRandomizationDesignPersonaDepth:
    def test_design_defaults_persona_depth_to_none_and_covariate_count_to_zero(self):
        design = RandomizationDesign(
            variable="price", label="the price", min_value=0.0, max_value=200.0
        )
        assert design.persona_depth == "none"
        assert design.covariate_count == 0 and isinstance(design.covariate_count, int)
        deep = _price_design(persona_depth="demographics", covariate_count=11)
        assert isinstance(deep.covariate_count, int)
        assert deep.covariate_count == 11

    def test_design_accepts_every_valid_persona_depth(self):
        # The paper depth ladder has exactly the two levels {1, 2}: the bare
        # survey ("none") and the 11-field demographic persona.
        for depth in ("none", "demographics"):
            assert _price_design(persona_depth=depth).persona_depth == depth

    def test_design_rejects_an_unknown_persona_depth(self):
        # "extended" was the superseded third tier, and the behavioural tiers
        # of the five-tier ladder are removed; none of them may parse.
        for depth in (
            "extended",
            "deep",
            "occluded",
            "tightwad",
            "time_preference",
            "risk_preference",
        ):
            with pytest.raises(ValueError):
                _price_design(persona_depth=depth)

    def test_to_json_and_from_json_round_trip_persona_depth_and_count(self):
        design = _price_design(persona_depth="demographics", covariate_count=11, seed=5)
        assert RandomizationDesign.from_json(design.to_json()) == design
        restored = RandomizationDesign.from_json(
            json.loads(json.dumps(design.to_json()))
        )
        assert restored == design

    def test_to_json_always_writes_both_persona_keys_even_at_defaults(self):
        payload = _price_design().to_json()
        assert payload["persona_depth"] == "none"
        assert payload["covariate_count"] == 0

    def test_old_stored_designs_without_persona_keys_still_load_with_defaults(self):
        legacy = {
            key: value
            for key, value in _price_design(seed=3).to_json().items()
            if key not in ("persona_depth", "covariate_count")
        }
        restored = RandomizationDesign.from_json(legacy)
        assert restored.persona_depth == "none"
        assert restored.covariate_count == 0
        assert restored.seed == 3

    def test_render_unblinding_is_unchanged_for_a_none_persona_depth(self):
        design = _price_design(persona_depth="none")
        text = design.render_unblinding()
        assert "uniform" in text.lower()
        assert "blind" in text.lower()
        assert design.label in text
        blinded = _price_design(blinding="blinded", persona_depth="none")
        assert blinded.render_unblinding() == ""


# 2. run_sweep: the design-blinding fix, persona metadata, prompt persistence


class TestRunSweepPersonaDepth:
    def _run(self, design, chat, draws=1, blinding="blinded", seed=7, **kwargs):
        return run_sweep(
            design,
            _products(),
            "qwen3-8b",
            chat,
            draws=draws,
            blinding=blinding,
            seed=seed,
            **kwargs,
        )

    def test_run_sweep_records_carry_the_run_blinding_inside_the_design(self):
        chat = _FakeChat()  # bug (a): run "blinded" used to store an "unblinded" design
        records = self._run(_price_design(blinding="unblinded"), chat, draws=2)
        assert records
        assert chat.calls
        for record in records:
            assert record["design"]["blinding"] == "blinded"

    def test_run_sweep_blinded_design_run_unblinded_also_fixes_the_design(self):
        chat = _FakeChat()
        records = self._run(
            _price_design(blinding="blinded"), chat, blinding="unblinded"
        )
        for record in records:
            assert record["design"]["blinding"] == "unblinded"

    def test_run_sweep_records_stamp_persona_depth_and_its_covariate_count(self):
        # The record must carry the depth actually used (default "none" too),
        # with the covariate count of the two-level paper ladder.
        for kwargs, depth, count in (
            ({}, "none", 0),
            ({"persona_depth": "demographics"}, "demographics", 11),
        ):
            chat = _FakeChat()
            records = self._run(_price_design(), chat, draws=2, **kwargs)
            assert records
            assert all(r["persona_depth"] == depth for r in records)
            assert all(isinstance(r["covariate_count"], int) for r in records)
            assert all(r["covariate_count"] == count for r in records)

    def test_run_sweep_rejects_the_removed_behavioural_tiers(self):
        # The record stamping goes through covariate_count_for_depth, so the
        # removed behavioural tiers must be refused at run time too.
        for depth in ("tightwad", "time_preference", "risk_preference"):
            with pytest.raises(ValueError):
                self._run(_price_design(), _FakeChat(), draws=1, persona_depth=depth)

    def test_run_sweep_records_persist_the_exact_prompts_sent_and_their_hash(self):
        # Bug (c): the stored prompts must equal what chat_fn actually received.
        design = _price_design(blinding="unblinded")
        chat = _FakeChat(answer="not purchase")
        records = run_sweep(
            design,
            _products()[:1],
            "qwen3-8b",
            chat,
            draws=1,
            blinding="blinded",
            seed=7,
        )
        assert len(records) == len(chat.calls) == len(design.grid())
        for record, (messages, _temperature) in zip(records, chat.calls):
            system, user = messages[0]["content"], messages[1]["content"]
            assert record["system_prompt"] == system
            assert record["user_prompt"] == user
            assert isinstance(record["system_prompt"], str) and record["system_prompt"]
            assert isinstance(record["user_prompt"], str) and record["user_prompt"]
            expected_sha = hashlib.sha256(
                (system + "\x1e" + user).encode("utf-8")
            ).hexdigest()
            assert record["prompt_sha256"] == expected_sha

    def test_run_sweep_records_keep_every_existing_key(self):
        chat = _FakeChat()
        records = self._run(
            _price_design(blinding="unblinded"),
            chat,
            draws=2,
            persona_depth="demographics",
        )
        required = {
            "design",
            "treatment_value",
            "raw_content",
            "parsed_purchase",
            "succeeded",
            "seed",
        }
        for record in records:
            assert required <= set(record)
            assert record["succeeded"] is True
            assert record["parsed_purchase"] is True
            assert record["seed"] == 7


# 3. write_manifest on a both-conditions run


class TestWriteManifestBothConditions:
    def _write(self, path, blinding, **overrides):
        args = dict(
            model="qwen3-8b",
            draws=5,
            products=_products(),
            base_url="http://localhost:1234/v1",
            extra={},
        )
        args.update(overrides)
        return write_manifest(
            path, _price_design(distribution="grid", seed=42), blinding=blinding, **args
        )

    def test_both_conditions_manifest_stores_the_scope_and_per_condition_designs(
        self, tmp_path
    ):
        # Bug (a) on manifests: a "both" run used to store ONE design (blinding
        # "unblinded") that described both conditions.
        path = tmp_path / "manifest.json"
        self._write(path, blinding=["blinded", "unblinded"])
        loaded = json.loads(path.read_text())
        assert loaded["blinding_scope"] == ["blinded", "unblinded"]
        assert set(loaded["designs"]) == {"blinded", "unblinded"}
        for condition, entry in loaded["designs"].items():
            assert entry["blinding"] == condition
            assert entry["variable"] == "price"
        # The run metadata must survive the both-conditions layout too.
        assert loaded["model"] == "qwen3-8b"
        assert loaded["draws"] == 5
        assert loaded["base_url"] == "http://localhost:1234/v1"


# 4. run_diagnostic records name the product and category being probed


class TestRunDiagnosticProductCategory:
    def test_run_diagnostic_records_carry_the_product_and_category(self):
        # Bug (b): rows were anonymous, so within-product correlation was impossible.
        design = _price_design()
        kinds = ["last_price", "competing_price", "expiry_days"]
        chat = _FakeChat(answer="$12.50")
        records = run_diagnostic(
            design, _products(), kinds, chat, draws=1, blinding="blinded", seed=7
        )
        assert records
        expected_pairs = {(p["product"], p["category"]) for p in _products()}
        actual_pairs = {(r["product"], r["category"]) for r in records}
        assert actual_pairs == expected_pairs
        for record in records:
            assert record[design.variable] in set(design.grid())
            present = [kind for kind in kinds if kind in record]
            assert len(present) == 1
            assert record[present[0]] == pytest.approx(12.5)


# 5. covariate_count_for_depth helper


class TestCovariateCountForDepth:
    def test_covariate_count_for_depth_maps_each_valid_depth_to_its_count(self):
        # Paper depth ladder {1, 2}: none pins no covariates (0) and
        # demographics pins the 11 Appendix D fields (11). The behavioural
        # tiers of the five-tier ladder no longer have counts.
        assert randomization_mod.covariate_count_for_depth("none") == 0
        assert randomization_mod.covariate_count_for_depth("demographics") == 11

    def test_covariate_count_for_depth_rejects_an_unknown_depth(self):
        # "extended" was the superseded third tier, and tightwad/
        # time_preference/risk_preference are the removed behavioural tiers;
        # none of them may map to a count any longer.
        for depth in (
            "mystery",
            "deep",
            "extended",
            "tightwad",
            "time_preference",
            "risk_preference",
        ):
            with pytest.raises(ValueError):
                randomization_mod.covariate_count_for_depth(depth)


# 6. run_persona_sweep


class TestRunPersonaSweep:
    # Returns (records, skipped_empty) — my documented contract choice.
    def _run(
        self,
        design,
        chat,
        blinding="blinded",
        persona_depth="demographics",
        seed=7,
        personas_by_product=None,
    ):
        return sweep_kit_mod.run_persona_sweep(
            design,
            personas_by_product
            if personas_by_product is not None
            else _personas_by_product({0: [_ALICE], 1: [_BOB, _ALICE]}),
            "qwen3-8b",
            chat,
            blinding=blinding,
            persona_depth=persona_depth,
            seed=seed,
        )

    def test_run_persona_sweep_calls_chat_once_per_product_level_and_persona(self):
        design = _price_design()
        chat = _FakeChat()
        records, skipped = self._run(design, chat)
        assert skipped == 0
        assert len(chat.calls) == len(records) == 3 * 1 + 3 * 2  # 3 levels x personas
        assert len(records) == len(design.grid()) * sum(
            len(p["personas"])
            for p in _personas_by_product({0: [_ALICE], 1: [_BOB, _ALICE]}).values()
        )

    def test_run_persona_sweep_forwards_temperature_zero_for_every_call(self):
        # Paper step B: heterogeneity from personas, not sampling -> 0.0 always.
        design = _price_design()
        chat = _FakeChat()
        self._run(design, chat)
        assert chat.calls
        assert {temperature for _messages, temperature in chat.calls} == {0.0}

    def test_run_persona_sweep_visits_every_level_for_every_persona_of_a_product(self):
        design = _price_design()
        chat = _FakeChat()
        records, skipped = self._run(design, chat)
        assert skipped == 0
        chips = _products()[1]["product"]
        chips_combos = {
            (r["persona_index"], r["treatment_value"])
            for r in records
            if r["product"] == chips
        }
        assert chips_combos == {(i, level) for i in (0, 1) for level in design.grid()}

    def test_run_persona_sweep_user_prompt_renders_the_persona_fields(self):
        design = _price_design()
        chat = _FakeChat()
        records, _skipped = self._run(design, chat)
        assert records
        for record, (messages, _temperature) in zip(records, chat.calls):
            user = messages[-1]["content"]
            persona = record["persona"]
            assert str(persona["age"]) in user
            assert persona["city"] in user
            assert persona["occupation"] in user

    def test_run_persona_sweep_records_carry_persona_index_and_depth_metadata(self):
        # The one non-none tier (demographics, 11 Appendix D fields) is
        # accepted end-to-end and stamps each record with the depth used and
        # the covariate count its field set pins. Partial personas (three
        # fields, no measures) must keep rendering at that tier too.
        for depth, count in (("demographics", 11),):
            design = _price_design()
            chat = _FakeChat()
            records, _skipped = self._run(design, chat, persona_depth=depth)
            per_product = {}
            for record in records:
                per_product.setdefault(record["product"], []).append(record)
            cola = _products()[0]["product"]
            chips = _products()[1]["product"]
            for record in per_product[cola]:
                assert record["persona"] == _ALICE
                assert record["persona_index"] == 0
            by_index = {
                r["persona_index"]: r["persona"] for r in per_product[chips]
            }
            assert by_index == {0: _BOB, 1: _ALICE}
            assert all(r["persona_depth"] == depth for r in records)
            assert all(isinstance(r["covariate_count"], int) for r in records)
            assert all(r["covariate_count"] == count for r in records)

    def test_run_persona_sweep_rejects_the_removed_behavioural_tiers(self):
        # run_persona_sweep stamps covariate_count through the depth map, so
        # the removed behavioural tiers must be refused exactly like run_sweep.
        for depth in ("tightwad", "time_preference", "risk_preference"):
            with pytest.raises(ValueError):
                self._run(_price_design(), _FakeChat(), persona_depth=depth)

    def test_run_persona_sweep_fixes_the_design_blinding_like_run_sweep(self):
        design = _price_design(blinding="unblinded")
        chat = _FakeChat()
        records, _skipped = self._run(design, chat, blinding="blinded")
        assert records
        for record in records:
            assert record["design"]["blinding"] == "blinded"

    def test_run_persona_sweep_records_keep_the_standard_sweep_keys(self):
        design = _price_design(blinding="unblinded")
        chat = _FakeChat(answer="not purchase")
        records, _skipped = self._run(design, chat)
        required = {
            "design",
            "treatment_value",
            "raw_content",
            "parsed_purchase",
            "succeeded",
            "seed",
        }
        for record in records:
            assert required <= set(record)
            assert record["raw_content"] == "not purchase"
            assert record["parsed_purchase"] is False
            assert record["succeeded"] is True
            assert record["seed"] == 7
            assert design.min_value <= record["treatment_value"] <= design.max_value

    def test_run_persona_sweep_skips_empty_personas_and_reports_how_many(self):
        design = _price_design()
        chat = _FakeChat()
        by_product = _personas_by_product({0: [_ALICE, {}], 1: [_BOB]})
        records, skipped = self._run(design, chat, personas_by_product=by_product)
        non_empty = [p for p in by_product.values() for p in p["personas"] if p]
        assert skipped == 1
        assert len(chat.calls) == len(records) == len(non_empty) * len(design.grid())

    def test_run_persona_sweep_is_deterministic_for_the_same_seed(self):
        design = _price_design(distribution="uniform")
        first_chat, second_chat = _FakeChat(), _FakeChat()
        first_records, _ = self._run(design, first_chat)
        second_records, _ = self._run(design, second_chat)
        first_prompts = [m[-1]["content"] for m, _t in first_chat.calls]
        second_prompts = [m[-1]["content"] for m, _t in second_chat.calls]
        assert [r["treatment_value"] for r in first_records] == [
            r["treatment_value"] for r in second_records
        ]
        assert first_prompts == second_prompts
        assert first_records and len(first_records) == len(first_prompts)


# 7. scripts/unblinding_sweep.py persona flags


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


class TestUnblindingSweepPersonaFlags:
    def test_script_help_lists_the_persona_depth_and_personas_flags(self, capsys):
        module = _load_sweep_script()
        with pytest.raises(SystemExit) as excinfo:
            module.main(["--help"])
        assert excinfo.value.code == 0
        help_text = capsys.readouterr().out
        for option in ("--persona-depth", "--personas-dir", "--personas-per-product"):
            assert option in help_text, f"missing option {option} in --help"

    def test_parser_accepts_the_persona_flags_with_values_and_defaults(self):
        module = _load_sweep_script()
        # Every one of the two paper depth tiers parses (default "none" too).
        for depth in ("none", "demographics"):
            args = module._parse_args(
                [
                    "--model",
                    "qwen3-8b",
                    "--persona-depth",
                    depth,
                    "--personas-dir",
                    "personas/2026-09",
                    "--personas-per-product",
                    "100",
                ]
            )
            assert args.persona_depth == depth
            assert args.personas_dir == "personas/2026-09"
            assert args.personas_per_product == 100
        defaults = module._parse_args(["--model", "qwen3-8b"])
        assert defaults.persona_depth == "none"
        assert defaults.personas_per_product == 500

    def test_parser_rejects_an_unknown_persona_depth_value(self):
        module = _load_sweep_script()
        # "extended" was the superseded third tier and the behavioural tiers
        # are removed; the CLI must reject all of them too.
        for depth in (
            "bananas",
            "deep",
            "extended",
            "tightwad",
            "time_preference",
            "risk_preference",
        ):
            with pytest.raises(SystemExit):
                module._parse_args(["--model", "x", "--persona-depth", depth])

    def test_importing_the_script_with_persona_flags_never_opens_a_socket(self):
        def _forbid_socket(*_args, **_kwargs):
            raise AssertionError("importing unblinding_sweep must not open a socket")

        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr(socket, "socket", _forbid_socket)
        try:
            module = _load_sweep_script()
        finally:
            monkeypatch.undo()
        assert callable(module.main)
