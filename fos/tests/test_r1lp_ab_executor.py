# Locked tests for the R1LP A/B label-order EXECUTOR (TASK-1552, RED phase).
#
# WHY THESE TESTS EXIST: TASK-1551 wired the A/B PLANNING (AB_LABEL_ORDERS,
# build_logprob_plan(ab_orders=True) doubling, --ab-labels, average_ab_p_buy)
# but nothing EXECUTES it: a leg that actually runs with ab_orders=True still
# scores one pass per cell. These tests lock the executor behaviour, all
# offline (the injected fake HTTP poster IS the only transport; no real server):
#
#   (1) BOTH ORDERS EXECUTED: with ab_orders=True the executor scores every
#       cell with BOTH label orders - forward ("purchase" first) and the
#       reversal ("not purchase" first) - so both orders reach the mock.
#   (2) MERGED OUTPUT: the result (and so the durable record, via the
#       existing extra-merge in build_record) stores the A/B-averaged p(buy)
#       == average_ab_p_buy(forward, reversed) and carries both raw order
#       values under their individual label_order stamps (0.8 / 0.2 -> 0.5).
#   (3) ab_orders=False UNCHANGED (regression guard): single order, no merge.
#   (4) RESUME SAFETY: with ab_orders=True a resumed leg finishes ONLY the
#       missing cells (both orders each); durable cells - both halves done -
#       are never re-executed; exactly one merged record per cell on disk.
#   (5) IMPOSSIBLE MODE REFUSED (TASK-1555, review F2 lock): first_token
#       has no A/B form, so make_scorer("first_token", ..., ab_orders=True)
#       must raise ValueError naming the conflict BEFORE any transport
#       call - never silently score a single order.
#
# INTERFACE CHOICES where the current code is silent (minimal natural
# extension of what exists, same style as the TASK-1550 wiring contract):
#   - make_scorer(...) grows ab_orders: bool = False; with ab_orders=True
#     (candidate_scoring mode) it returns the A/B executor: per prompt it
#     scores BOTH AB_LABEL_ORDERS and returns ONE merged result;
#   - the merged result keeps the unified key "p_buy_logprob" (the key the
#     record merge already stores) holding the average, and carries
#     "ab_results": the two per-order results as make_candidate_scorer
#     returned them, each stamped with the "label_order" it scored;
#   - a merged result succeeds only when BOTH order halves succeeded (a
#     failed half must fail the cell, never merge one order alone);
#   - launch_sweep._make_logprob_scorer grows ab_orders: bool = False and
#     post=None (threaded into make_scorer) so the leg wrapper can build
#     the executor and tests can stay offline;
#   - the leg runner (run_queue_leg) keeps its existing cell/record
#     durability semantics: one merged record per cell, resume counts cells.
#
# The 25 locked offline tests in test_logprob_profile.py / test_r1lp_wiring.py
# must stay green. No existing test file is touched.
import json
import math
import sys
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
FORWARD_ORDER = ("purchase", "not purchase")
REVERSED_ORDER = ("not purchase", "purchase")
MESSAGES = [{"role": "user", "content": "Would you buy Cola at $2.00?"}]


class _AbFakePost:
    """Fake /completions transport giving the two A/B passes different
    p(buy) values so the merge is observable.

    Both passes send the same two candidate prompts, so the fake tells the
    passes apart by counting the calls PER CANDIDATE: the first call for a
    candidate carries the forward-run logprobs (p(buy) = 0.8), the second
    the reversed-run ones (p(buy) = 0.2). Whichever execution order the
    executor picks, one pass sees 0.8 and the other 0.2, so the merged
    p(buy) must average to 0.5. fail_second_pass fails the second
    purchase-candidate call with HTTP 500 (one broken order half).
    """

    def __init__(self, fail_second_pass: bool = False) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.fail_second_pass = fail_second_pass
        self._purchase_calls = 0
        self._nobuy_calls = 0

    def __call__(self, url: str, payload: dict, timeout: float) -> tuple[int, str]:
        self.calls.append((url, payload))
        prompt = payload["prompt"]
        # "purchase" is a suffix of "not purchase", so match the reversal first.
        if prompt.endswith("not purchase"):
            self._nobuy_calls += 1
            logprob = math.log(0.2) if self._nobuy_calls % 2 == 1 else math.log(0.8)
            entries = [
                {"token": "not", "logprob": logprob},
                {"token": " purchase", "logprob": 0.0},
            ]
        else:
            self._purchase_calls += 1
            if self.fail_second_pass and self._purchase_calls == 2:
                return 500, "{}"
            logprob = math.log(0.8) if self._purchase_calls % 2 == 1 else math.log(0.2)
            entries = [{"token": "purchase", "logprob": logprob}]
        return 200, json.dumps({"completion_probabilities": entries})


class _SingleOrderFakePost:
    """Fake /completions transport for the unchanged single-order path:
    p(buy) = 0.8 on every call, whichever candidate it asks for."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def __call__(self, url: str, payload: dict, timeout: float) -> tuple[int, str]:
        self.calls.append((url, payload))
        if payload["prompt"].endswith("not purchase"):
            entries = [
                {"token": "not", "logprob": math.log(0.2)},
                {"token": " purchase", "logprob": 0.0},
            ]
        else:
            entries = [{"token": "purchase", "logprob": math.log(0.8)}]
        return 200, json.dumps({"completion_probabilities": entries})


def _candidate_prompts(post: _AbFakePost) -> list[str]:
    """The prompts the fake transport saw (one per candidate call)."""
    return [payload["prompt"] for _url, payload in post.calls]


def _ab_settings(tmp_path: Path, model: str):
    """Settings for one offline R1LP leg (candidate_scoring, no grammar)."""
    from launch_support import Settings

    return Settings(
        model=model,
        port=8080,
        manager_url="http://127.0.0.1:9",
        base_url="http://127.0.0.1:9",
        out=tmp_path,
        run_name="ab-executor-probe",
        pool_seed=42,
        pool_overdraw=1.2,
        seed=7,
        draws=1,
        progress_every=10,
        products_path="data/configs/unblinding_products.json",
        grammar=None,
        logprob_mode="candidate_scoring",
    )


def _merged_ab_record(model: str, product: str, level: float) -> dict:
    """One durable A/B cell record as the executor would have written it:
    the averaged p(buy) plus both raw order values under their stamps."""
    return {
        "model": model,
        "product": product,
        "treatment_value": level,
        "blinding": "blinded",
        "persona_depth": "none",
        "succeeded": True,
        "parsed_purchase": None,
        "p_buy_logprob": 0.5,
        "ab_results": [
            {"label_order": list(FORWARD_ORDER), "p_buy_logprob": 0.8},
            {"label_order": list(REVERSED_ORDER), "p_buy_logprob": 0.2},
        ],
        "elapsed_seconds": 0.1,
    }


def _run_leg(settings, plan, target, scorer_fn, results: list) -> None:
    """Run one offline queue leg through the real leg runner."""
    from launch_queue_leg import run_queue_leg

    run_dir = settings.out / settings.run_name
    run_dir.mkdir(parents=True, exist_ok=True)
    run_queue_leg(
        settings,
        plan,
        PRODUCTS,
        None,
        run_dir,
        None,
        target,
        results,
        results.append,
        None,
        None,
        scorer_fn=scorer_fn,
    )


# ---------------------------------------------------------------------------
# (1) + (2) The executor: both orders per cell, merged and stamped output
# ---------------------------------------------------------------------------


def test_ab_scorer_executes_both_label_orders_for_one_cell():
    """With ab_orders=True one cell is scored with BOTH label orders: the
    transport sees both candidate prompts, once per order pass (4 calls)."""
    from logprob_scoring import make_scorer

    post = _AbFakePost()
    scorer = make_scorer(
        "candidate_scoring",
        "http://127.0.0.1:9",
        "vendor/model",
        post=post,
        ab_orders=True,
    )
    scorer(MESSAGES)

    assert len(post.calls) == 4, (
        "an A/B cell must issue both label orders (2 passes x 2 candidates), "
        f"got {len(post.calls)} calls"
    )
    assert all(url.endswith("/completions") for url, _payload in post.calls)
    prompts = _candidate_prompts(post)
    distinct = set(prompts)
    buy = [
        p for p in distinct if p.endswith("purchase") and not p.endswith("not purchase")
    ]
    nobuy = [p for p in distinct if p.endswith("not purchase")]
    assert len(buy) == 1 and len(nobuy) == 1, (
        "the two A/B passes must ask the same two candidate prompts"
    )
    for prompt in distinct:
        assert prompts.count(prompt) == 2, (
            "each candidate prompt must be asked once per label order"
        )


def test_ab_scorer_stores_the_averaged_pbuy_and_both_order_stamps():
    """The executor's result stores the A/B-averaged p(buy) under the same
    unified key the record merge already reads (forward 0.8 / reversed 0.2
    -> 0.5) and carries both raw order values under their label_order
    stamps."""
    from logprob_scoring import average_ab_p_buy, make_scorer

    post = _AbFakePost()
    scorer = make_scorer(
        "candidate_scoring",
        "http://127.0.0.1:9",
        "vendor/model",
        post=post,
        ab_orders=True,
    )
    result = scorer(MESSAGES)

    assert result["succeeded"] is True
    assert result["p_buy_logprob"] == pytest.approx(0.5), (
        "the stored p(buy) of an A/B cell is the mean of the two orders "
        "(forward 0.8 / reversed 0.2 -> 0.5)"
    )
    stamped = {tuple(entry["label_order"]): entry for entry in result["ab_results"]}
    assert set(stamped) == {FORWARD_ORDER, REVERSED_ORDER}, (
        "the result must carry both raw order values under their "
        "individual label_order stamps"
    )
    forward = stamped[FORWARD_ORDER]["p_buy_logprob"]
    reversed_ = stamped[REVERSED_ORDER]["p_buy_logprob"]
    assert {round(forward, 6), round(reversed_, 6)} == {0.8, 0.2}, (
        "the stamped raw values must be the two orders' actual p(buy)"
    )
    assert result["p_buy_logprob"] == pytest.approx(
        average_ab_p_buy(forward, reversed_)
    ), "the merged p(buy) must be average_ab_p_buy of the two stamped values"


def test_ab_scorer_fails_the_cell_when_either_order_half_fails():
    """One broken order half fails the whole A/B cell: a cell must never
    silently store an average of one order alone."""
    from logprob_scoring import make_scorer

    post = _AbFakePost(fail_second_pass=True)
    scorer = make_scorer(
        "candidate_scoring",
        "http://127.0.0.1:9",
        "vendor/model",
        post=post,
        ab_orders=True,
    )
    result = scorer(MESSAGES)

    assert result["succeeded"] is False, (
        "a failed order half must fail the A/B cell (never average the "
        "surviving order alone)"
    )


# ---------------------------------------------------------------------------
# The leg wrapper builds the executor only when A/B is on
# ---------------------------------------------------------------------------


def test_leg_scorer_wrapper_executes_both_orders_only_when_ab_is_on(tmp_path):
    """launch_sweep._make_logprob_scorer grows ab_orders/post: with
    ab_orders=True the leg's scorer executes both orders per cell; without
    it the wrapper is unchanged (one forward-order pass, no merging)."""
    from launch_sweep import _make_logprob_scorer

    settings = _ab_settings(tmp_path, "vendor/model")
    progress = lambda *args: None  # noqa: E731

    ab_post = _AbFakePost()
    ab_fn, _state, _abort = _make_logprob_scorer(
        settings, 1, progress, ab_orders=True, post=ab_post
    )
    ab_result = ab_fn(MESSAGES)
    assert len(ab_post.calls) == 4, (
        "an A/B leg's scorer must issue both label orders per cell"
    )
    assert ab_result["p_buy_logprob"] == pytest.approx(0.5)

    single_post = _AbFakePost()
    single_fn, _state, _abort = _make_logprob_scorer(
        settings, 1, progress, post=single_post
    )
    single_result = single_fn(MESSAGES)
    assert len(single_post.calls) == 2, (
        "without ab_orders the leg scorer stays single-order (2 candidates)"
    )
    assert tuple(single_result["label_order"]) == FORWARD_ORDER
    assert "ab_results" not in single_result, (
        "the default path must not grow A/B merge fields"
    )


# ---------------------------------------------------------------------------
# (2) + (4) The leg: one merged record per cell, resume never re-executes
# ---------------------------------------------------------------------------


def test_ab_leg_writes_one_merged_record_per_cell(tmp_path):
    """A leg run under an ab_orders=True plan stores ONE durable record per
    cell (not one per order): the averaged p(buy) plus both order stamps,
    with both orders actually executed at the transport."""
    from launch_cells import scan_leg_jsonl
    from launch_queue import build_logprob_plan, queue_leg_dir, queue_leg_jsonl
    from logprob_scoring import make_scorer

    plan = build_logprob_plan(len(PRODUCTS), len(LEVELS), levels=LEVELS, ab_orders=True)
    target = plan["legs"][0]
    assert target["calls"] == 2 * len(PRODUCTS) * len(LEVELS), (
        "precondition: the A/B plan doubles the leg's scoring passes"
    )
    post = _AbFakePost()
    scorer_fn = make_scorer(
        "candidate_scoring",
        "http://127.0.0.1:9",
        target["model"],
        post=post,
        ab_orders=True,
    )
    settings = _ab_settings(tmp_path, target["model"])
    results: list[dict] = []
    _run_leg(settings, plan, target, scorer_fn, results)

    assert results[0]["ok"] is True
    assert len(post.calls) == 4 * len(PRODUCTS) * len(LEVELS), (
        "both orders must be executed for every cell of the leg"
    )
    jsonl = queue_leg_jsonl(queue_leg_dir(settings.out / settings.run_name, target))
    records, torn = scan_leg_jsonl(jsonl)
    assert torn == 0
    assert len(records) == len(PRODUCTS) * len(LEVELS), (
        "an A/B leg stores ONE merged record per cell (not one per order)"
    )
    for record in records:
        assert record["succeeded"] is True
        assert record["p_buy_logprob"] == pytest.approx(0.5), (
            "the durable record stores the A/B-averaged p(buy)"
        )
        stamps = {tuple(entry["label_order"]) for entry in record["ab_results"]}
        assert stamps == {FORWARD_ORDER, REVERSED_ORDER}, (
            "the durable record carries both raw order values under their "
            "label_order stamps"
        )


def test_ab_leg_resume_finishes_only_the_missing_cells(tmp_path):
    """A/B resume safety: with one cell already durable (both its order
    halves done), a resumed leg executes ONLY the missing cells' both-order
    passes and never duplicates the completed cell."""
    from launch_cells import duplicate_cells, scan_leg_jsonl
    from launch_queue import build_logprob_plan, queue_leg_dir, queue_leg_jsonl
    from logprob_scoring import make_scorer

    plan = build_logprob_plan(len(PRODUCTS), len(LEVELS), levels=LEVELS, ab_orders=True)
    target = plan["legs"][0]
    post = _AbFakePost()
    scorer_fn = make_scorer(
        "candidate_scoring",
        "http://127.0.0.1:9",
        target["model"],
        post=post,
        ab_orders=True,
    )
    settings = _ab_settings(tmp_path, target["model"])
    jsonl = queue_leg_jsonl(queue_leg_dir(settings.out / settings.run_name, target))
    jsonl.parent.mkdir(parents=True)
    durable = _merged_ab_record(target["model"], PRODUCTS[0]["product"], LEVELS[0])
    jsonl.write_text(json.dumps(durable) + "\n", encoding="utf-8")
    results: list[dict] = []
    _run_leg(settings, plan, target, scorer_fn, results)

    assert results[0]["ok"] is True
    assert len(post.calls) == 4 * (len(PRODUCTS) * len(LEVELS) - 1), (
        "resume must execute only the missing cells, both orders each - the "
        "completed cell's order halves are never re-executed"
    )
    records, torn = scan_leg_jsonl(jsonl)
    assert torn == 0
    assert len(records) == len(PRODUCTS) * len(LEVELS)
    assert duplicate_cells(records, persona=False, expected_per_group=1) == [], (
        "a resumed A/B leg must not duplicate any cell"
    )


def test_ab_leg_resume_with_every_cell_durable_makes_no_llm_calls(tmp_path):
    """A/B resume safety: when every cell of the leg is already durable, the
    resumed leg finalizes without a single model call (no order half of any
    cell runs twice)."""
    from launch_cells import scan_leg_jsonl
    from launch_queue import build_logprob_plan, queue_leg_dir, queue_leg_jsonl
    from logprob_scoring import make_scorer

    plan = build_logprob_plan(len(PRODUCTS), len(LEVELS), levels=LEVELS, ab_orders=True)
    target = plan["legs"][0]
    post = _AbFakePost()
    scorer_fn = make_scorer(
        "candidate_scoring",
        "http://127.0.0.1:9",
        target["model"],
        post=post,
        ab_orders=True,
    )
    settings = _ab_settings(tmp_path, target["model"])
    jsonl = queue_leg_jsonl(queue_leg_dir(settings.out / settings.run_name, target))
    jsonl.parent.mkdir(parents=True)
    durable = [
        _merged_ab_record(target["model"], product["product"], level)
        for product in PRODUCTS
        for level in LEVELS
    ]
    jsonl.write_text(
        "\n".join(json.dumps(record) for record in durable) + "\n", encoding="utf-8"
    )
    results: list[dict] = []
    _run_leg(settings, plan, target, scorer_fn, results)

    assert results[0]["ok"] is True
    assert post.calls == [], (
        "a fully durable A/B leg must finalize without re-executing any "
        "cell or order half"
    )
    records, _torn = scan_leg_jsonl(jsonl)
    assert len(records) == len(PRODUCTS) * len(LEVELS)


# ---------------------------------------------------------------------------
# (3) ab_orders=False regression guard: single order, no merging
# ---------------------------------------------------------------------------


def test_leg_without_ab_keeps_the_single_order_record_unchanged(tmp_path):
    """Without the A/B switch the leg behaves exactly as before: one
    single-order pass per cell, the plain p(buy) stored, and no A/B merge
    fields anywhere in the durable record."""
    from launch_cells import scan_leg_jsonl
    from launch_queue import build_logprob_plan, queue_leg_dir, queue_leg_jsonl
    from logprob_scoring import make_scorer

    plan = build_logprob_plan(len(PRODUCTS), len(LEVELS), levels=LEVELS)
    assert not plan.get("ab_orders")
    target = plan["legs"][0]
    assert target["calls"] == len(PRODUCTS) * len(LEVELS)
    post = _SingleOrderFakePost()
    scorer_fn = make_scorer(
        "candidate_scoring",
        "http://127.0.0.1:9",
        target["model"],
        post=post,
    )
    settings = _ab_settings(tmp_path, target["model"])
    results: list[dict] = []
    _run_leg(settings, plan, target, scorer_fn, results)

    assert results[0]["ok"] is True
    assert len(post.calls) == 2 * len(PRODUCTS) * len(LEVELS), (
        "the default path stays one single-order scoring pass per cell"
    )
    run_dir = settings.out / settings.run_name
    records, _torn = scan_leg_jsonl(queue_leg_jsonl(queue_leg_dir(run_dir, target)))
    assert len(records) == len(PRODUCTS) * len(LEVELS)
    for record in records:
        assert record["succeeded"] is True
        assert record["p_buy_logprob"] == pytest.approx(0.8), (
            "the default path stores the single order's plain p(buy)"
        )
        assert tuple(record["label_order"]) == FORWARD_ORDER
        assert "ab_results" not in record, (
            "the default record must not grow A/B merge fields"
        )


# ---------------------------------------------------------------------------
# (5) TASK-1555, review F2 lock: first_token + ab_orders refuses loudly
# ---------------------------------------------------------------------------


def test_first_token_with_ab_orders_refuses_before_any_transport_call():
    """first_token has no A/B form: make_scorer("first_token", ...,
    ab_orders=True) must raise ValueError naming the conflict at scorer
    build time, with the transport never invoked (no order silently
    scored)."""
    from logprob_scoring import make_scorer

    post = _AbFakePost()
    with pytest.raises(ValueError) as excinfo:
        make_scorer(
            "first_token",
            "http://127.0.0.1:9",
            "vendor/model",
            post=post,
            ab_orders=True,
        )
    message = str(excinfo.value)
    assert "ab_orders" in message and "first_token" in message, (
        "the refusal must name both the ab_orders switch and the "
        f"first_token mode it cannot serve; got: {message!r}"
    )
    assert post.calls == [], (
        "the refusal must fire at scorer build - no transport call may "
        "happen for an impossible mode combination"
    )
