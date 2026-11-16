# Locked tests for the R1LP logprob profile (TASK-1545).
#
# WHY THESE TESTS EXIST: R1LP is the second version of the 5-model
# experiment. Instead of sampling N draws per prompt with a one-token GBNF
# grammar, it asks the model for its OWN probability of "purchase" vs "not
# purchase" through logprobs, with NO grammar, and makes ONE scoring pass
# per prompt (bare 40 x 11 x 2 = 880 + personas 20 x 40 x 11 x 2 = 17,600
# = 18,480 per model, 92,400 across the queue). These tests lock the
# offline contract of that profile:
#
#   (a) every scoring request asks for logprobs and NEVER sends a grammar;
#   (b) the p(buy) mass is read correctly from synthetic top-logprobs,
#       including the case where neither branch appears in the top-k;
#   (c) candidate scoring sums exactly the candidate's tokens, tolerating
#       llama-server's response variants;
#   (d) the record schema carries every logprob field and stays
#       JSON-serialisable (parsed_purchase may be null, succeeded = the
#       scoring call succeeded);
#   (e) the queue leg still resumes at cell granularity in logprob mode
#       (reusing the same durable-cells planner the sampling legs use);
#   (f) --dry-run prints 18,480 per model and 92,400 total;
#   (g) all of it runs offline: the injected fake HTTP poster IS the only
#       transport, so no test can reach a real server.
#
# The task-ordered tests are additive: no existing test file is touched.
import json
import math
import sys
import tempfile
from dataclasses import replace
from pathlib import Path

import pytest

# The launch scripts live in scripts/ and are not on pytest's pythonpath.
_SCRIPTS = str(Path(__file__).resolve().parent.parent / "scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

PRODUCTS = [
    {"category": "Soft Drinks", "product": "Cola 12 oz", "regular_price": 1.99},
    {"category": "Chips", "product": "Potato Chips", "regular_price": 2.99},
]
LEVELS = [0.0, 100.0]


class _FakePost:
    """A fake HTTP poster: records every (url, payload) and returns a body."""

    def __init__(self, body: str) -> None:
        self.body = body
        self.calls: list[tuple[str, dict]] = []

    def __call__(self, url: str, payload: dict, timeout: float) -> tuple[int, str]:
        self.calls.append((url, payload))
        return 200, self.body


def _first_token_body() -> str:
    """One OpenAI-style first-token reply with a purchase top-logprob list."""
    return json.dumps(
        {
            "choices": [
                {
                    "message": {"content": " purchase"},
                    "logprobs": {
                        "content": [
                            {
                                "token": " purchase",
                                "logprob": math.log(0.6),
                                "top_logprobs": [
                                    {"token": " purchase", "logprob": math.log(0.6)},
                                    {"token": " not", "logprob": math.log(0.3)},
                                    {"token": " The", "logprob": math.log(0.1)},
                                ],
                            }
                        ]
                    },
                }
            ]
        }
    )


def _candidate_body(*entries: dict) -> str:
    """One llama-server /completions reply carrying per-token entries."""
    return json.dumps({"completion_probabilities": list(entries)})


# ---------------------------------------------------------------------------
# (a) + (g) Request shape: no grammar, yes logprobs, mock is the transport
# ---------------------------------------------------------------------------


def test_first_token_request_asks_for_logprobs_and_never_sends_grammar():
    """The first_token scorer posts to /v1/chat/completions with max_tokens=1,
    temperature 1.0, logprobs and top_logprobs=20 - and no grammar field."""
    from logprob_scoring import make_first_token_scorer

    post = _FakePost(_first_token_body())
    scorer = make_first_token_scorer("http://127.0.0.1:9", "vendor/model", post=post)
    result = scorer([{"role": "user", "content": "buy?"}])

    assert len(post.calls) == 1  # the injected fake IS the transport
    url, payload = post.calls[0]
    assert url.endswith("/v1/chat/completions")
    assert payload["max_tokens"] == 1
    assert payload["temperature"] == 1.0
    assert payload["logprobs"] is True
    assert payload["top_logprobs"] == 20
    assert "grammar" not in payload
    assert result["logprob_mode"] == "first_token"
    assert result["succeeded"] is True
    assert result["raw_content"] == " purchase"


def test_candidate_request_asks_for_logprobs_and_never_sends_grammar():
    """candidate_scoring posts twice (one per candidate) to /completions with
    n_predict=0, logprobs, n_probs=20 and temperature 1.0 - no grammar."""
    from logprob_scoring import make_candidate_scorer

    body = _candidate_body(
        {"token": " The", "logprob": -0.5},
        {"token": " not", "logprob": -0.3},
        {"token": " purchase", "logprob": -0.7},
    )
    post = _FakePost(body)
    scorer = make_candidate_scorer("http://127.0.0.1:9", "vendor/model", post=post)
    result = scorer(
        [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "buy?"},
        ]
    )

    assert len(post.calls) == 2  # exactly one request per candidate
    for url, payload in post.calls:
        assert url.endswith("/completions")
        assert payload["n_predict"] == 0
        assert payload["logprobs"] is True
        assert payload["n_probs"] == 20
        assert payload["temperature"] == 1.0
        assert "grammar" not in payload
        assert isinstance(payload["prompt"], str) and payload["prompt"]
    assert result["logprob_mode"] == "candidate_scoring"
    assert result["succeeded"] is True
    # Two candidates were appended to the templated prompt.
    prompts = [payload["prompt"] for _url, payload in post.calls]
    assert any(p.endswith("purchase") for p in prompts)
    assert any(p.endswith("not purchase") for p in prompts)


def test_scorers_only_use_the_injected_poster_not_the_network(monkeypatch):
    """When a fake poster is injected, the scorers must never touch urllib
    (test (g): assert the mock was used and the network was not)."""
    import urllib.request

    from logprob_scoring import make_first_token_scorer

    def forbidden(*_args, **_kwargs):
        raise AssertionError("a test scorer must never open a real connection")

    monkeypatch.setattr(urllib.request, "urlopen", forbidden)
    post = _FakePost(_first_token_body())
    scorer = make_first_token_scorer("http://127.0.0.1:9", "vendor/model", post=post)
    scorer([{"role": "user", "content": "buy?"}])
    assert len(post.calls) == 1


# ---------------------------------------------------------------------------
# (b) p(buy) mass from synthetic top-logprobs
# ---------------------------------------------------------------------------


def test_p_buy_math_from_synthetic_top_logprobs():
    """p_buy sums the purchase-branch probabilities, p_nobuy sums the 'not'
    branch, and branch_mass is their sum."""
    from logprob_scoring import purchase_branch_mass

    mass = purchase_branch_mass(
        [
            {"token": " purchase", "logprob": math.log(0.6)},
            {"token": " not", "logprob": math.log(0.3)},
            {"token": " The", "logprob": math.log(0.1)},
        ]
    )
    assert mass["p_buy"] == pytest.approx(0.6)
    assert mass["p_nobuy"] == pytest.approx(0.3)
    assert mass["branch_mass"] == pytest.approx(0.9)
    assert mass["neither_branch"] is False


def test_neither_branch_in_top_k_is_flagged_and_zero():
    """When neither branch is in the top-k, the mass is zero and the record
    is flagged instead of silently guessed."""
    from logprob_scoring import purchase_branch_mass

    mass = purchase_branch_mass(
        [
            {"token": " The", "logprob": math.log(0.9)},
            {"token": " maybe", "logprob": math.log(0.1)},
        ]
    )
    assert mass["p_buy"] == 0.0
    assert mass["p_nobuy"] == 0.0
    assert mass["branch_mass"] == 0.0
    assert mass["neither_branch"] is True


# ---------------------------------------------------------------------------
# (c) candidate scoring sums exactly the candidate tokens
# ---------------------------------------------------------------------------


def test_candidate_scoring_sums_exactly_the_candidate_tokens():
    """The candidate sum takes only the trailing candidate tokens (not the
    prompt tokens), reports the token count and the length-normalized mean,
    and the two candidates give a 2-way softmax."""
    from logprob_scoring import (
        candidate_softmax,
        parse_candidate_response,
        sum_candidate_logprobs,
    )

    parsed = parse_candidate_response(
        _candidate_body(
            {"token": " The", "logprob": -0.5},  # prompt token, not a candidate
            {"token": " not", "logprob": -0.3},
            {"token": " purchase", "logprob": -0.7},
        )
    )
    entries = parsed["token_logprobs"]
    assert [entry["token"] for entry in entries] == [" The", " not", " purchase"]

    buy = sum_candidate_logprobs(entries, candidate_token_count=1)
    assert buy["lp_sum"] == pytest.approx(-0.7)
    assert buy["lp_tokens"] == 1
    assert buy["lp_mean"] == pytest.approx(-0.7)

    nobuy = sum_candidate_logprobs(entries, candidate_token_count=2)
    assert nobuy["lp_sum"] == pytest.approx(-1.0)
    assert nobuy["lp_tokens"] == 2
    assert nobuy["lp_mean"] == pytest.approx(-0.5)

    soft = candidate_softmax(buy["lp_sum"], nobuy["lp_sum"])
    assert soft["p_buy"] + soft["p_nobuy"] == pytest.approx(1.0)
    # the higher (less negative) logprob gets the larger probability
    assert soft["p_buy"] > soft["p_nobuy"]


def test_candidate_parser_tolerates_llama_server_variants():
    """The parser reads per-token `logprob`, a `probs` list, per-token
    `top_logprobs`, and `prompt_logprobs`, and truncates the audit copy."""
    from logprob_scoring import parse_candidate_response

    direct = parse_candidate_response(_candidate_body({"token": "purchase", "logprob": -0.2}))
    assert direct["token_logprobs"][0]["logprob"] == pytest.approx(-0.2)

    probs = parse_candidate_response(
        _candidate_body(
            {
                "content": " not",
                "probs": [{"tok_str": " not", "prob": 0.8}, {"tok_str": " yes", "prob": 0.2}],
            }
        )
    )
    assert probs["token_logprobs"][0]["token"] == " not"
    assert probs["token_logprobs"][0]["logprob"] == pytest.approx(math.log(0.8))

    top = parse_candidate_response(
        _candidate_body(
            {
                "token": " purchase",
                "top_logprobs": [
                    {"token": " purchase", "logprob": -0.4},
                    {"token": " not", "logprob": -1.1},
                ],
            }
        )
    )
    assert top["token_logprobs"][0]["logprob"] == pytest.approx(-0.4)

    prompt = parse_candidate_response(
        json.dumps({"prompt_logprobs": [{"token": "purchase", "logprob": -0.9}]})
    )
    assert prompt["token_logprobs"][0]["logprob"] == pytest.approx(-0.9)

    long_body = json.dumps(
        {"prompt_logprobs": [{"token": "purchase", "logprob": -0.1, "note": "x" * 5000}]}
    )
    truncated = parse_candidate_response(long_body)
    assert len(truncated["raw_logprob_response"]) <= 2048


# ---------------------------------------------------------------------------
# (d) the record schema, JSON-serialisable
# ---------------------------------------------------------------------------


def _fake_scorer_result(succeeded: bool = True) -> dict:
    """A synthetic scorer result in the exact shape the sweeps expect."""
    return {
        "logprob_mode": "first_token",
        "p_buy_logprob": 0.7,
        "p_nobuy_logprob": 0.2,
        "branch_mass": 0.9,
        "top_logprobs": [
            {"token": " purchase", "logprob": math.log(0.7)},
            {"token": " not", "logprob": math.log(0.2)},
        ],
        "lp_buy_sum": None,
        "lp_nobuy_sum": None,
        "lp_buy_tokens": None,
        "lp_nobuy_tokens": None,
        "raw_logprob_response": "{}",
        "neither_branch_in_top_k": False,
        "raw_content": " purchase",
        "succeeded": succeeded,
    }


def test_logprob_sweep_records_carry_the_full_schema_and_serialise():
    """run_logprob_sweep writes one record per prompt with every existing
    field plus the logprob fields; parsed_purchase stays null and succeeded
    is the scoring call's success."""
    from fos.experiments.sweep_kit import run_logprob_sweep
    from unblinding_sweep import _build_design

    design = _build_design(LEVELS, ["blinded"], 7, [], "none")
    scorer = lambda _messages: _fake_scorer_result()  # noqa: E731
    records = run_logprob_sweep(
        design,
        PRODUCTS,
        "vendor/model",
        scorer,
        draws=1,
        blinding="blinded",
        seed=7,
        persona_depth="none",
    )
    assert len(records) == len(PRODUCTS) * len(LEVELS)
    required = {
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
        "logprob_mode",
        "p_buy_logprob",
        "p_nobuy_logprob",
        "branch_mass",
        "top_logprobs",
        "lp_buy_sum",
        "lp_nobuy_sum",
        "lp_buy_tokens",
        "lp_nobuy_tokens",
        "raw_logprob_response",
    }
    for record in records:
        assert required <= set(record)
        assert record["parsed_purchase"] is None
        assert record["succeeded"] is True
        assert record["logprob_mode"] == "first_token"
        assert record["p_buy_logprob"] == pytest.approx(0.7)
        json.dumps(record)  # must be JSON-serialisable


def test_logprob_persona_sweep_records_personas_and_mean_pbuy():
    """The persona logprob sweep runs one pass per (product x persona x
    level) and stamps the persona index so per-cell p(buy) can average over
    the model's 20 personas."""
    from fos.experiments.sweep_kit import run_logprob_persona_sweep
    from unblinding_sweep import _build_design

    design = _build_design(LEVELS, ["blinded"], 7, [], "demographics")
    personas_by_product = {
        "Cola 12 oz": {
            "category": "Soft Drinks",
            "regular_price": 1.99,
            "personas": [{"pid": index} for index in range(3)],
        }
    }
    scorer = lambda _messages: _fake_scorer_result()  # noqa: E731
    records, skipped = run_logprob_persona_sweep(
        design,
        personas_by_product,
        "vendor/model",
        scorer,
        blinding="blinded",
        persona_depth="demographics",
        seed=7,
    )
    assert skipped == 0
    assert len(records) == 3 * len(LEVELS)
    assert {record["persona_index"] for record in records} == {0, 1, 2}
    assert all(record["parsed_purchase"] is None for record in records)


# ---------------------------------------------------------------------------
# (e) cell-granular resume still holds in logprob mode
# ---------------------------------------------------------------------------


class _CountingScorer:
    """A fake logprob scorer that counts how many prompts it scored."""

    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, _messages):
        self.calls += 1
        return _fake_scorer_result()


def _logprob_settings(tmp_path: Path, model: str):
    from launch_support import Settings

    return Settings(
        model=model,
        port=8080,
        manager_url="http://127.0.0.1:9",
        base_url="http://127.0.0.1:9",
        out=tmp_path,
        run_name="logprob-probe",
        pool_seed=42,
        pool_overdraw=1.2,
        seed=7,
        draws=1,
        progress_every=10,
        products_path="data/configs/unblinding_products.json",
        grammar=None,
        logprob_mode="first_token",
    )


def test_logprob_leg_resumes_partial_plain_leg_skipping_done_cells():
    """A partial R1LP plain leg (4 cells: 2 products x 2 levels x 1 pass)
    resumes and scores only the missing cells, keeping the finished leg
    exactly-once."""
    from launch_cells import duplicate_cells, scan_leg_jsonl
    from launch_queue import build_logprob_plan, queue_leg_dir, queue_leg_jsonl
    from launch_queue_leg import run_queue_leg

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        plan = build_logprob_plan(len(PRODUCTS), len(LEVELS), levels=LEVELS)
        target = plan["legs"][0]  # model 0, none, blinded (2 products x 2 levels)
        settings = _logprob_settings(tmp_path, target["model"])
        run_dir = settings.out / settings.run_name
        run_dir.mkdir(parents=True)
        jsonl = queue_leg_jsonl(queue_leg_dir(run_dir, target))
        jsonl.parent.mkdir(parents=True)
        durable = [
            {
                "model": target["model"],
                "product": PRODUCTS[0]["product"],
                "treatment_value": level,
                "blinding": "blinded",
                "persona_depth": "none",
                "succeeded": True,
                "parsed_purchase": None,
                "p_buy_logprob": 0.6,
                "elapsed_seconds": 0.1,
            }
            for level in LEVELS
        ]
        jsonl.write_text(
            "\n".join(json.dumps(record) for record in durable) + "\n", encoding="utf-8"
        )
        scorer = _CountingScorer()
        results: list[dict] = []
        log: list[str] = []
        run_queue_leg(
            settings,
            {**plan, "legs": [target]},
            PRODUCTS,
            None,
            run_dir,
            None,
            target,
            results,
            log.append,
            None,
            None,
            scorer_fn=scorer,
        )
        assert scorer.calls == 2  # only the 2 missing cells (product 2 x 2 levels)
        assert len(results) == 1 and results[0]["ok"] is True
        assert results[0]["records"] == 4
        records, torn = scan_leg_jsonl(jsonl)
        assert len(records) == 4 and torn == 0
        assert duplicate_cells(records, persona=False, expected_per_group=1) == []


# ---------------------------------------------------------------------------
# (f) the plan numbers and the dry run
# ---------------------------------------------------------------------------


def test_logprob_plan_counts_per_model_and_total():
    """Per model: none 2 x 40 x 11 x 1 = 880 + demographics 2 x 40 x 20 x 11
    = 17,600 = 18,480; the five models = 92,400. draws == 1 and grammar is
    not used."""
    from launch_queue import LOGP_PROFILE, build_logprob_plan

    plan = build_logprob_plan(40, 11, levels=[float(x) for x in range(0, 220, 20)])
    assert plan["profile"] == LOGP_PROFILE == "R1LP"
    assert plan["draws"] == 1
    assert len(plan["legs"]) == 20
    per_model_none = {}
    per_model_persona = {}
    for leg in plan["legs"]:
        bucket = per_model_none if leg["depth"] == "none" else per_model_persona
        bucket[leg["model"]] = bucket.get(leg["model"], 0) + leg["calls"]
    for meta in plan["models"]:
        assert per_model_none[meta["model"]] == 880
        assert per_model_persona[meta["model"]] == 17_600
        assert meta["total_calls"] == 18_480
    assert plan["sweep_calls"] == 92_400


def test_logprob_dry_run_prints_per_model_and_total(capsys):
    """launch_grid --profile R1LP --dry-run prints 18,480 per model and the
    92,400 total, with no grammar, offline."""
    from launch_grid import main

    assert main(["--profile", "R1LP", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "R1LP launch plan (dry run)" in out
    assert "18,480" in out
    assert "92,400" in out
    assert "grammar" in out.lower()
    assert "none" in out.lower()


# ---------------------------------------------------------------------------
# Analysis: MAE vs the human benchmark, 0% level excluded as primary
# ---------------------------------------------------------------------------


def test_logprob_analysis_mae_excludes_zero_level_primary():
    """cell_mae drops the 0% level for the primary number and keeps it for
    the robustness number, matching the sampling report's convention."""
    from r1_logprob_analysis import cell_mae

    human = {"Cola": {0.0: 0.9, 20.0: 0.5, 100.0: 0.1}}
    model = {"Cola": {0.0: 0.2, 20.0: 0.4, 100.0: 0.1}}
    assert cell_mae(model, human, exclude_levels=(0.0,)) == pytest.approx(0.05)
    assert cell_mae(model, human, exclude_levels=()) == pytest.approx(0.8 / 3)


def test_logprob_analysis_loads_the_human_csv_shape(tmp_path):
    """load_human_benchmark reads the per-product x level CSV the benchmark
    ships (/home/justin/work/research/TASK-1496/pbuy_product_level.csv)."""
    from r1_logprob_analysis import load_human_benchmark

    path = tmp_path / "pbuy_product_level.csv"
    path.write_text(
        "product,0,20,100\n"
        "Cola,0.9,0.5,0.1\n"
        '"Potato Chips",0.8,0.4,0.05\n',
        encoding="utf-8",
    )
    table, levels = load_human_benchmark(path)
    assert levels == [0.0, 20.0, 100.0]
    assert table["Cola"][20.0] == pytest.approx(0.5)
    assert table["Potato Chips"][100.0] == pytest.approx(0.05)
