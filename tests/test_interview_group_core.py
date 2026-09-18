"""Core group-interview engine: schema, prompts, parsing, fan-out, tallies.

No model and no simulator here — the engine takes ``persona_fn`` / ``ask_fn``
precisely so its behaviour can be pinned without either.
"""

from __future__ import annotations

import json

import pytest

from gaworld.interview.aggregate import aggregate, breakdown, tally
from gaworld.interview.attachments import ResolvedAttachment, ResolvedMaterial
from gaworld.interview.prompt import build_turn_prompt, parse_answer
from gaworld.interview.report import render_markdown
from gaworld.interview.runner import run_round
from gaworld.interview.schema import (
    Answer,
    InterviewSpecError,
    Question,
    Respondent,
    SessionSpec,
    Transcript,
    normalize_questions,
    normalize_respondents,
    normalize_spec,
)

# ---------------------------------------------------------------------------
# Schema / validation
# ---------------------------------------------------------------------------


def test_questions_get_stable_sequential_ids():
    questions = normalize_questions([{"text": "A"}, {"text": "B"}])
    assert [q.id for q in questions] == ["q1", "q2"]


def test_followup_round_continues_numbering():
    """A second round must not reuse ids — that would merge two tallies."""
    later = normalize_questions([{"text": "C"}], start_index=2, round_no=2)
    assert later[0].id == "q3"
    assert later[0].round == 2


def test_duplicate_caller_ids_are_replaced_not_honoured():
    questions = normalize_questions([{"id": "dup", "text": "A"}, {"id": "dup", "text": "B"}])
    assert len({q.id for q in questions}) == 2


def test_choice_question_needs_at_least_two_options():
    with pytest.raises(InterviewSpecError):
        normalize_questions([{"text": "选一个", "kind": "choice", "options": ["只有一个"]}])


def test_options_are_deduplicated_in_author_order():
    question = normalize_questions([{"text": "q", "kind": "choice", "options": ["支持", "反对", "支持"]}])[0]
    assert question.options == ["支持", "反对"]


def test_non_choice_questions_drop_stray_options():
    question = normalize_questions([{"text": "q", "kind": "open", "options": ["x", "y"]}])[0]
    assert question.options == []


def test_respondents_deduplicate_by_uid():
    rows = [
        {"kind": "agent", "city": "a", "ref": "1"},
        {"kind": "agent", "city": "a", "ref": "1"},
        {"kind": "agent", "city": "b", "ref": "1"},
    ]
    assert len(normalize_respondents(rows)) == 2


def test_respondent_mirrors_city_into_demographics():
    respondent = Respondent.from_dict({"kind": "agent", "city": "绍兴", "ref": "7"})
    assert respondent.demographics["city"] == "绍兴"


def test_cohort_size_defaults_to_member_count():
    respondent = Respondent.from_dict({"kind": "cohort", "city": "x", "ref": "c001", "members": [1, 2, 3]})
    assert respondent.size == 3


def test_spec_rejects_empty_respondents():
    with pytest.raises(InterviewSpecError):
        normalize_spec({"questions": [{"text": "q"}], "respondents": []})


# ---------------------------------------------------------------------------
# Answer parsing
# ---------------------------------------------------------------------------


def _choice_question(**kwargs):
    return Question(id="q1", text="你支持吗", kind="choice", options=["支持", "不支持", "说不清"], **kwargs)


def test_choice_answer_matches_declared_option():
    answer = parse_answer('{"choice": ["支持"], "reason": "对我有利"}', _choice_question())
    assert answer.choice == ["支持"]
    assert not answer.unparsed


def test_choice_answer_survives_prose_and_fences():
    raw = '好的，我的选择是：\n```json\n{"choice": ["不支持"], "reason": "太贵"}\n```'
    answer = parse_answer(raw, _choice_question())
    assert answer.choice == ["不支持"]


def test_choice_answer_strips_enumerator_prefix():
    answer = parse_answer('{"choice": ["B. 不支持"]}', _choice_question())
    assert answer.choice == ["不支持"]


def test_negation_is_not_swallowed_by_its_positive_prefix():
    """ "不支持" must never be matched as "支持" — longest option wins."""
    answer = parse_answer('{"choice": ["我不支持"]}', _choice_question())
    assert answer.choice == ["不支持"]


def test_single_choice_keeps_only_first_match():
    answer = parse_answer('{"choice": ["支持", "说不清"]}', _choice_question())
    assert answer.choice == ["支持"]


def test_multi_choice_keeps_several_and_splits_strings():
    answer = parse_answer('{"choice": "支持、说不清"}', _choice_question(multi=True))
    assert answer.choice == ["支持", "说不清"]


def test_invented_option_is_unparsed_not_guessed():
    answer = parse_answer('{"choice": ["完全不相干的东西"]}', _choice_question())
    assert answer.choice == []
    assert answer.unparsed is True


def test_boolean_true_from_json_bool():
    question = Question(id="q1", text="你会搬走吗", kind="boolean")
    assert parse_answer('{"yes": true, "reason": "房租太高"}', question).boolean is True


def test_boolean_false_from_chinese_negation():
    question = Question(id="q1", text="你会搬走吗", kind="boolean")
    answer = parse_answer('{"yes": "不会，我在这儿有家"}', question)
    assert answer.boolean is False


def test_boolean_without_commitment_is_unparsed():
    question = Question(id="q1", text="你会搬走吗", kind="boolean")
    answer = parse_answer('{"reason": "很难讲，要看情况"}', question)
    assert answer.boolean is None
    assert answer.unparsed is True


def test_open_answer_falls_back_to_raw_text():
    question = Question(id="q1", text="说说你的感受")
    answer = parse_answer("房租涨了，我睡不好。", question)
    assert "房租涨了" in answer.text
    assert not answer.unparsed


def test_open_answer_keeps_prose_when_json_present():
    question = Question(id="q1", text="说说你的感受")
    answer = parse_answer('{"answer": "还行吧，就是通勤累"}', question)
    assert answer.text == "还行吧，就是通勤累"


# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------


def test_prompt_replays_prior_answers_for_continuity():
    prior_q = Question(id="q1", text="你住哪儿")
    prior_a = Answer(question_id="q1", text="我住城西")
    prompt = build_turn_prompt(
        persona="你是张三。",
        context="",
        question=Question(id="q2", text="通勤远吗"),
        history=[(prior_q, prior_a)],
        turn_no=2,
        total=2,
    )
    assert "你住哪儿" in prompt
    assert "我住城西" in prompt


def test_prompt_lists_choice_options_verbatim():
    prompt = build_turn_prompt(persona="你是张三。", context="", question=_choice_question())
    for option in ("支持", "不支持", "说不清"):
        assert option in prompt


def test_prompt_mentions_an_attached_image_that_really_went_along():
    material = ResolvedMaterial(
        items=[ResolvedAttachment(kind="image", data="AAAA", media_type="image/png", caption="工地")]
    )
    prompt = build_turn_prompt(
        persona="你是张三。",
        context="",
        question=Question(id="q1", text="你怎么看这张图"),
        material=material,
    )
    assert "见本次附带的图像" in prompt


def test_prompt_says_caption_only_when_image_was_degraded():
    material = ResolvedMaterial(
        items=[ResolvedAttachment(kind="image", text="工地照片", note="模型不支持图片")]
    )
    prompt = build_turn_prompt(
        persona="你是张三。",
        context="",
        question=Question(id="q1", text="你怎么看这张图"),
        material=material,
    )
    assert "仅有文字说明" in prompt


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


def _spec(questions, respondents, **kwargs):
    return SessionSpec(questions=questions, respondents=respondents, **kwargs)


def test_runner_asks_every_question_of_every_respondent():
    questions = normalize_questions([{"text": "A"}, {"text": "B"}])
    respondents = normalize_respondents(
        [{"kind": "agent", "city": "", "ref": "1"}, {"kind": "agent", "city": "", "ref": "2"}]
    )
    calls = []

    def ask(respondent, question, prompt, images):
        calls.append((respondent.ref, question.id))
        return json.dumps({"answer": f"{respondent.ref}-{question.id}"})

    transcripts = run_round(_spec(questions, respondents), persona_fn=lambda r: "你是某人。", ask_fn=ask)
    assert len(transcripts) == 2
    assert sorted(calls) == [("1", "q1"), ("1", "q2"), ("2", "q1"), ("2", "q2")]


def test_runner_feeds_each_answer_into_the_next_prompt():
    """The continuity requirement, asserted where it can actually break."""
    questions = normalize_questions([{"text": "A"}, {"text": "B"}, {"text": "C"}])
    respondents = normalize_respondents([{"kind": "agent", "city": "", "ref": "1"}])
    prompts = []

    def ask(respondent, question, prompt, images):
        prompts.append(prompt)
        return json.dumps({"answer": f"回答{question.id}"})

    run_round(_spec(questions, respondents), persona_fn=lambda r: "你是某人。", ask_fn=ask)
    assert "回答q1" not in prompts[0]
    assert "回答q1" in prompts[1]
    assert "回答q1" in prompts[2] and "回答q2" in prompts[2]


def test_runner_replays_history_from_a_previous_round():
    prior = Question(id="q1", text="你住哪儿")
    questions = normalize_questions([{"text": "通勤远吗"}], start_index=1, round_no=2)
    respondents = normalize_respondents([{"kind": "agent", "city": "", "ref": "1"}])
    prompts = []

    def ask(respondent, question, prompt, images):
        prompts.append(prompt)
        return json.dumps({"answer": "还好"})

    spec = _spec(
        questions,
        respondents,
        history={"agent::1": [Answer(question_id="q1", text="我住城西").to_dict()]},
        history_questions=[prior],
    )
    run_round(spec, persona_fn=lambda r: "你是某人。", ask_fn=ask)
    assert "我住城西" in prompts[0]


def test_one_failing_respondent_does_not_lose_the_others():
    questions = normalize_questions([{"text": "A"}])
    respondents = normalize_respondents(
        [{"kind": "agent", "city": "", "ref": "1"}, {"kind": "agent", "city": "", "ref": "2"}]
    )

    def persona(respondent):
        if respondent.ref == "1":
            raise RuntimeError("这个人的档案坏了")
        return "你是某人。"

    transcripts = run_round(
        _spec(questions, respondents),
        persona_fn=persona,
        ask_fn=lambda r, q, p, i: json.dumps({"answer": "好"}),
    )
    by_ref = {t.respondent.ref: t for t in transcripts}
    assert "档案坏了" in by_ref["1"].error
    assert by_ref["2"].answers[0].text == "好"


def test_a_failing_question_is_recorded_and_the_round_continues():
    questions = normalize_questions([{"text": "A"}, {"text": "B"}])
    respondents = normalize_respondents([{"kind": "agent", "city": "", "ref": "1"}])

    def ask(respondent, question, prompt, images):
        if question.id == "q1":
            raise RuntimeError("模型超时")
        return json.dumps({"answer": "第二问答上了"})

    transcript = run_round(_spec(questions, respondents), persona_fn=lambda r: "你是某人。", ask_fn=ask)[0]
    assert transcript.answers[0].error == "模型超时"
    assert transcript.answers[1].text == "第二问答上了"


def test_image_rejection_retries_without_the_image_and_says_so():
    questions = normalize_questions([{"text": "看图说话"}])
    respondents = normalize_respondents([{"kind": "agent", "city": "", "ref": "1"}])
    material = {
        "q1": ResolvedMaterial(items=[ResolvedAttachment(kind="image", data="AAAA", media_type="image/png")])
    }
    seen = []

    def ask(respondent, question, prompt, images):
        seen.append(bool(images))
        if images:
            raise RuntimeError("400 model does not support images")
        return json.dumps({"answer": "看不到图，只能猜"})

    transcript = run_round(
        _spec(questions, respondents),
        persona_fn=lambda r: "你是某人。",
        ask_fn=ask,
        material=material,
    )[0]
    assert seen == [True, False]
    assert "拒绝了图片" in transcript.answers[0].degraded
    assert transcript.answers[0].text == "看不到图，只能猜"


def test_personas_are_built_on_the_calling_thread():
    """Regression: the memory store holds a process-global SQLite connection.

    Building a resident seeds the vector store, so a persona built inside a
    worker thread raises "SQLite objects created in a thread can only be used
    in that same thread" and every respondent fails. The model calls may fan
    out; the persona build may not.
    """
    import threading as th

    questions = normalize_questions([{"text": "A"}])
    # An even count, so every ask pairs off at the barrier below and none is
    # left waiting for the timeout.
    respondents = normalize_respondents([{"kind": "agent", "city": "", "ref": str(i)} for i in range(1, 5)])
    main = th.get_ident()
    persona_threads = []
    # A barrier rather than counting thread ids: five instant calls can all
    # land on one pooled worker, which would make an id-counting assertion
    # flaky. Two calls can only meet here if two really run at once.
    rendezvous = th.Barrier(2, timeout=5)

    def persona(respondent):
        persona_threads.append(th.get_ident())
        return "你是某人。"

    def ask(respondent, question, prompt, images):
        rendezvous.wait()
        return json.dumps({"answer": "好"})

    transcripts = run_round(
        _spec(questions, respondents, concurrency=4),
        persona_fn=persona,
        ask_fn=ask,
    )
    assert persona_threads == [main] * 4
    # And the asking really did fan out, or the fix traded correctness for a
    # serial round: a serial run would time out at the first wait().
    assert all(not t.answers[0].error for t in transcripts)


def test_stage_narration_is_emitted_while_personas_are_built():
    questions = normalize_questions([{"text": "A"}])
    respondents = normalize_respondents(
        [{"kind": "agent", "city": "", "ref": "1"}, {"kind": "agent", "city": "", "ref": "2"}]
    )
    stages = []
    run_round(
        _spec(questions, respondents),
        persona_fn=lambda r: "你是某人。",
        ask_fn=lambda r, q, p, i: json.dumps({"answer": "好"}),
        stage=stages.append,
    )
    assert len(stages) == 2
    assert "1/2" in stages[0]


def test_progress_reaches_the_total_even_when_a_respondent_fails():
    questions = normalize_questions([{"text": "A"}, {"text": "B"}])
    respondents = normalize_respondents(
        [{"kind": "agent", "city": "", "ref": "1"}, {"kind": "agent", "city": "", "ref": "2"}]
    )
    seen = []

    def persona(respondent):
        if respondent.ref == "1":
            raise RuntimeError("坏了")
        return "你是某人。"

    run_round(
        _spec(questions, respondents),
        persona_fn=persona,
        ask_fn=lambda r, q, p, i: json.dumps({"answer": "好"}),
        report=lambda done, total, msg: seen.append((done, total)),
    )
    assert max(done for done, _ in seen) == 4


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------


def _transcript(ref, city, answers, *, size=1, kind="agent", **demographics):
    # ``city`` is mirrored into demographics by ``Respondent.from_dict``, so
    # callers pass it once, positionally.
    respondent = Respondent.from_dict(
        {"kind": kind, "city": city, "ref": ref, "size": size, "demographics": demographics}
    )
    return Transcript(respondent=respondent, answers=answers)


def test_choice_tally_counts_respondents_and_people_separately():
    question = _choice_question()
    transcripts = [
        _transcript("1", "a", [Answer(question_id="q1", choice=["支持"])]),
        _transcript("c001", "a", [Answer(question_id="q1", choice=["支持"])], size=10, kind="cohort"),
        _transcript("2", "a", [Answer(question_id="q1", choice=["不支持"])]),
    ]
    stats = tally(question, transcripts)
    rows = {row["label"]: row for row in stats["rows"]}
    assert rows["支持"]["respondents"] == 2
    assert rows["支持"]["people"] == 11
    assert rows["不支持"]["people"] == 1
    assert stats["answered_people"] == 12
    assert rows["支持"]["share"] == pytest.approx(11 / 12)


def test_unparsed_answers_are_excluded_and_reported():
    question = _choice_question()
    transcripts = [
        _transcript("1", "a", [Answer(question_id="q1", choice=["支持"])]),
        _transcript("2", "a", [Answer(question_id="q1", text="随便吧", unparsed=True)]),
    ]
    stats = tally(question, transcripts)
    assert stats["answered"] == 1
    assert stats["unparsed"] == 1
    assert sum(row["respondents"] for row in stats["rows"]) == 1


def test_boolean_tally_buckets_yes_and_no():
    question = Question(id="q1", text="会搬吗", kind="boolean")
    transcripts = [
        _transcript("1", "a", [Answer(question_id="q1", boolean=True)]),
        _transcript("2", "a", [Answer(question_id="q1", boolean=False)]),
        _transcript("3", "a", [Answer(question_id="q1", boolean=True)]),
    ]
    rows = {row["label"]: row for row in tally(question, transcripts)["rows"]}
    assert rows["是"]["respondents"] == 2
    assert rows["否"]["respondents"] == 1


def test_breakdown_splits_by_city():
    question = _choice_question()
    transcripts = [
        _transcript("1", "甲", [Answer(question_id="q1", choice=["支持"])]),
        _transcript("2", "乙", [Answer(question_id="q1", choice=["不支持"])]),
    ]
    result = breakdown(question, transcripts, ["city"])
    values = {group["value"]: group for group in result["city"]}
    assert values["甲"]["counts"]["支持"] == 1
    assert values["乙"]["counts"]["不支持"] == 1


def test_breakdown_omits_an_axis_that_does_not_split_the_sample():
    """A one-bar chart implies a distribution that was never measured."""
    question = _choice_question()
    transcripts = [
        _transcript("1", "甲", [Answer(question_id="q1", choice=["支持"])]),
        _transcript("2", "甲", [Answer(question_id="q1", choice=["支持"])]),
    ]
    assert "city" not in breakdown(question, transcripts, ["city"])


def test_aggregate_reports_mix_of_individuals_and_cohorts():
    questions = [_choice_question()]
    transcripts = [
        _transcript("1", "甲", [Answer(question_id="q1", choice=["支持"])]),
        _transcript("c001", "乙", [Answer(question_id="q1", choice=["支持"])], size=12, kind="cohort"),
    ]
    result = aggregate(questions, transcripts)
    assert result["individuals"] == 1
    assert result["cohorts"] == 1
    assert result["people"] == 13
    assert sorted(result["cities"]) == sorted(["甲", "乙"])


def test_open_question_still_reports_its_denominator():
    """A summary from 1 usable answer out of 3 must not read like 3."""
    question = Question(id="q1", text="说说你的感受")
    transcripts = [
        _transcript("1", "甲", [Answer(question_id="q1", text="有话说")]),
        _transcript("2", "甲", [Answer(question_id="q1", text="", unparsed=True)]),
        _transcript("3", "甲", [Answer(question_id="q1", error="模型超时")]),
    ]
    stats = aggregate([question], transcripts)["questions"][0]["stats"]
    assert stats["kind"] == "open"
    assert stats["rows"] == []
    assert stats["answered"] == 1
    assert stats["missing"] == 2


def test_aggregate_summary_failure_does_not_lose_the_counts():
    questions = [_choice_question()]
    transcripts = [_transcript("1", "甲", [Answer(question_id="q1", choice=["支持"])])]

    def broken(prompt):
        raise RuntimeError("模型挂了")

    result = aggregate(questions, transcripts, ask=broken)
    assert result["questions"][0]["summary"] == ""
    assert result["questions"][0]["stats"]["answered"] == 1


# ---------------------------------------------------------------------------
# Markdown report
# ---------------------------------------------------------------------------


def test_markdown_contains_summary_stats_and_every_answer():
    questions = [_choice_question(), Question(id="q2", text="还有什么想说的")]
    transcripts = [
        _transcript(
            "1",
            "甲",
            [
                Answer(question_id="q1", choice=["支持"], reason="对我有利"),
                Answer(question_id="q2", text="希望通勤能快点"),
            ],
        )
    ]
    analysis = aggregate(questions, transcripts)
    markdown = render_markdown(
        title="通勤调查",
        context="关于地铁延伸线",
        questions=questions,
        transcripts=transcripts,
        analysis=analysis,
    )
    assert "# 通勤调查" in markdown
    assert "关于地铁延伸线" in markdown
    assert "希望通勤能快点" in markdown
    assert "对我有利" in markdown
    assert "附录 B：问题清单" in markdown


def test_markdown_flags_unparsed_answers_rather_than_hiding_them():
    questions = [_choice_question()]
    transcripts = [_transcript("1", "甲", [Answer(question_id="q1", text="不好说", unparsed=True)])]
    markdown = render_markdown(
        title="t",
        context="",
        questions=questions,
        transcripts=transcripts,
        analysis=aggregate(questions, transcripts),
    )
    assert "未按题型作答" in markdown
    assert "不好说" in markdown


def test_markdown_lists_respondents_that_could_not_answer():
    questions = [Question(id="q1", text="q")]
    respondent = Respondent.from_dict({"kind": "agent", "city": "甲", "ref": "9", "label": "王五"})
    transcripts = [Transcript(respondent=respondent, error="档案缺失")]
    markdown = render_markdown(
        title="t",
        context="",
        questions=questions,
        transcripts=transcripts,
        analysis=aggregate(questions, transcripts),
    )
    assert "王五" in markdown
    assert "档案缺失" in markdown


def test_markdown_names_the_default_world_instead_of_its_slug():
    """The empty slug becomes "default" internally; a reader should not see it."""
    question = _choice_question()
    transcripts = [
        _transcript("1", "", [Answer(question_id="q1", choice=["支持"])]),
        _transcript("2", "绍兴柯桥", [Answer(question_id="q1", choice=["不支持"])]),
    ]
    analysis = aggregate(questions := [question], transcripts)
    markdown = render_markdown(
        title="t", context="", questions=questions, transcripts=transcripts, analysis=analysis
    )
    assert "默认世界" in markdown
    assert "city=default" not in markdown
    assert "| default |" not in markdown


def test_markdown_escapes_pipes_so_tables_survive():
    question = Question(id="q1", text="q", kind="choice", options=["a|b", "c"])
    transcripts = [_transcript("1", "甲", [Answer(question_id="q1", choice=["a|b"])])]
    markdown = render_markdown(
        title="t",
        context="",
        questions=[question],
        transcripts=transcripts,
        analysis=aggregate([question], transcripts),
    )
    assert "a\\|b" in markdown
