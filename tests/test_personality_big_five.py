"""Big Five (OCEAN) — the contracts the rest of the codebase relies on.

The first class is the important one. Everything else in this subsystem is a
tuning question that a run can answer; "an agent with no traits behaves exactly
as it did before" is the property that makes the feature safe to leave on, and
the one that makes every ablation arm in the design proposal meaningful.
"""

from __future__ import annotations

import random
import unittest
from copy import deepcopy

from gaworld.personality import anchor_block, personality_line, style_fit, trait_modifier
from gaworld.personality.plugin import (
    BigFivePlugin,
    cholesky,
    correlation_matrix,
    rescale,
    sample_traits,
)
from gaworld.personality.traits import (
    DIMENSIONS,
    MODIFIERS,
    PROMPT_DEFAULTS,
    prompt_knobs_of,
    residual,
    traits_of,
)
from gaworld.settings import CONFIG


def _agent(agent_id=1, traits=None, channels=("rules", "prompt", "voice"), **tuning):
    agent = {
        "id": agent_id,
        "name": f"agent{agent_id}",
        "personality": "性格偏内向理性，情绪整体稳定。",
        "state": {
            "stress": 0.5, "emotion": 0.55, "econ_security": 0.5, "energy": 0.7,
            "hunger": 0.3, "social_need": 0.4, "fatigue_debt": 0.2,
            "self_control": 0.6, "time_pressure": 0.3,
        },
    }
    if traits is not None:
        record = {"v": 1, "source": "test", "channels": list(channels)}
        record.update(dict.fromkeys(DIMENSIONS, 0.0))
        record.update(traits)
        if tuning:
            record["tuning"] = tuning
        agent["ext"] = {"big_five": record}
    return agent


class TestNeutralFallback(unittest.TestCase):
    """No record, or a record with the channel gated off, must be the identity."""

    def test_absent_record_is_identity(self):
        agent = _agent()
        self.assertEqual(traits_of(agent), dict.fromkeys(DIMENSIONS, 0.0))
        self.assertEqual(style_fit(agent, ["social", "progress"]), 0.0)
        for name in MODIFIERS:
            self.assertEqual(trait_modifier(agent, name), 1.0, name)
        self.assertEqual(anchor_block(agent, "routine"), "")

    def test_all_zero_record_is_identity(self):
        # A seeded-but-perfectly-average agent must not be treated differently
        # from an unseeded one, or the population mean would get a free nudge.
        agent = _agent(traits={})
        self.assertEqual(style_fit(agent, ["social"]), 0.0)
        self.assertEqual(trait_modifier(agent, "social_encounter"), 1.0)

    def test_personality_line_unchanged_without_traits(self):
        agent = _agent()
        self.assertEqual(
            personality_line(agent, "routine"),
            f"性格与情绪特征：{agent['personality']}",
        )

    def test_gated_channel_is_identity(self):
        loud = {"e": 2.0, "c": -2.0, "n": 1.8}
        rules_only = _agent(traits=loud, channels=("rules",))
        prompt_only = _agent(traits=loud, channels=("prompt",))
        self.assertNotEqual(style_fit(rules_only, ["social"]), 0.0)
        self.assertEqual(anchor_block(rules_only, "routine"), "")
        self.assertEqual(style_fit(prompt_only, ["social"]), 0.0)
        self.assertNotEqual(anchor_block(prompt_only, "routine"), "")

    def test_choose_action_sequence_matches_untraited_agent(self):
        """The real decision loop, not a stand-in: same seed, same picks."""
        from gaworld.sim._action import choose_action

        CONFIG.setdefault("human_realism", {})["enabled"] = True
        options = ["推进手头的任务", "刷手机拖延一会", "联系朋友聊天", "回家休息"]
        picks = []
        for agent in (_agent(), _agent(traits={}), _agent(traits={"e": 2.0}, channels=("prompt",))):
            random.seed(4242)
            picks.append([choose_action(agent, "个人时间", {"个人时间": options}) for _ in range(40)])
        self.assertEqual(picks[0], picks[1])
        self.assertEqual(picks[0], picks[2])


class TestDeterminism(unittest.TestCase):
    def test_residual_is_stable_and_agent_specific(self):
        agent = _agent(7, traits={"e": 1.0})
        self.assertEqual(residual(agent, "mod:x"), residual(agent, "mod:x"))
        self.assertNotEqual(residual(agent, "mod:x"), residual(_agent(8), "mod:x"))
        self.assertNotEqual(residual(agent, "mod:x"), residual(agent, "mod:y"))

    def test_residual_does_not_consume_the_global_rng(self):
        # If it did, turning personality on would silently reshuffle every
        # other stochastic subsystem downstream of it.
        random.seed(11)
        expected = [random.random() for _ in range(3)]
        random.seed(11)
        agent = _agent(3, traits={"c": 1.5})
        for name in MODIFIERS:
            trait_modifier(agent, name)
        style_fit(agent, ["social", "progress"])
        self.assertEqual([random.random() for _ in range(3)], expected)


class TestModulationShape(unittest.TestCase):
    def test_style_fit_is_bounded_by_amplitude(self):
        for z in (-2.5, -1.0, 0.5, 2.5):
            agent = _agent(traits={"e": z, "a": z}, amplitude=0.30)
            self.assertLessEqual(abs(style_fit(agent, ["social"])), 0.30 + 1e-9)

    def test_style_fit_sign_follows_the_loading(self):
        high = _agent(1, traits={"e": 2.0})
        low = _agent(1, traits={"e": -2.0})
        self.assertGreater(style_fit(high, ["social"]), style_fit(low, ["social"]))

    def test_modifier_is_bounded_by_band(self):
        for z in (-2.5, 0.0, 2.5):
            agent = _agent(traits={"c": z, "n": z}, band=0.25)
            for name in MODIFIERS:
                self.assertLessEqual(abs(trait_modifier(agent, name) - 1.0), 0.25 + 1e-9)

    def test_unknown_modifier_is_the_identity(self):
        agent = _agent(traits={"c": 2.0})
        self.assertEqual(trait_modifier(agent, "no_such_knob"), 1.0)

    def test_strength_zero_disables_every_channel_but_keeps_the_data(self):
        agent = _agent(traits={"e": 2.0, "c": -2.0}, strength=0.0)
        self.assertEqual(style_fit(agent, ["social"]), 0.0)
        self.assertEqual(trait_modifier(agent, "spontaneity_chance"), 1.0)
        self.assertEqual(traits_of(agent)["e"], 2.0)


class TestAnchors(unittest.TestCase):
    def test_extreme_traits_render_and_average_ones_mostly_do_not(self):
        loud = sum(bool(anchor_block(_agent(i, traits={"c": 2.4, "e": 2.4}), "routine"))
                   for i in range(60))
        quiet = sum(bool(anchor_block(_agent(i, traits={"c": 0.05, "e": 0.05}), "routine"))
                    for i in range(60))
        self.assertGreater(loud, 50)
        self.assertLess(quiet, 25)

    def test_rendering_is_stable_for_one_agent(self):
        agent = _agent(21, traits={"c": 1.9, "e": -1.9})
        first = anchor_block(agent, "routine")
        self.assertEqual(first, anchor_block(deepcopy(agent), "routine"))

    def test_scene_selects_its_own_dimensions(self):
        # Only N and A can reach the diary; C must not, however extreme.
        agent = _agent(traits={"c": 2.5, "n": 0.0, "a": 0.0})
        self.assertEqual(anchor_block(agent, "diary"), "")

    def test_never_writes_the_number(self):
        agent = _agent(traits={"n": 2.4, "a": -2.4})
        block = anchor_block(agent, "diary")
        self.assertTrue(block)
        for token in ("z", "2.4", "0.", "神经质", "宜人性"):
            self.assertNotIn(token, block)

    def test_at_most_max_dims_lines(self):
        agent = _agent(traits=dict.fromkeys(DIMENSIONS, 2.5))
        self.assertLessEqual(len(anchor_block(agent, "goals").splitlines()), 2)

    def test_personality_line_keeps_the_narrative_text_first(self):
        agent = _agent(traits={"c": 2.4, "e": 2.4})
        line = personality_line(agent, "routine")
        self.assertTrue(line.startswith(f"性格与情绪特征：{agent['personality']}"))


class TestBehaviourParagraph(unittest.TestCase):
    """The 人格与行为倾向 field written by scripts/author_personality.py."""

    def test_absent_field_renders_the_original_line(self):
        # The pre-rewrite corpus has no such field; prompts must not change.
        agent = _agent()
        self.assertEqual(
            personality_line(agent, "routine"),
            f"性格与情绪特征：{agent['personality']}",
        )

    def test_present_field_replaces_the_old_line(self):
        # The two descriptions come from different sources and contradict each
        # other for 9 of 51 residents; printing both would put the
        # contradiction on consecutive lines of every prompt.
        agent = _agent()
        agent["behavior_tendencies"] = "他收到没走流程的会议通知会反复点开链接确认时间。"
        rendered = personality_line(agent, "routine")
        self.assertEqual(rendered, f"人格与行为倾向：{agent['behavior_tendencies']}")
        self.assertNotIn("性格与情绪特征", rendered)

    def test_the_raw_field_is_still_there_for_keyword_matching(self):
        # dynamic.py / finance.py / _heuristic_schedule read agent["personality"]
        # directly; dropping it from the *prompt* must not touch them.
        agent = _agent()
        agent["behavior_tendencies"] = "他开会习惯沿自己思路往下讲。"
        self.assertTrue(agent["personality"])

    def test_blank_field_changes_nothing(self):
        agent = _agent()
        agent["behavior_tendencies"] = "   "
        self.assertEqual(
            personality_line(agent, "routine"),
            f"性格与情绪特征：{agent['personality']}",
        )

    def test_paragraph_and_anchors_coexist(self):
        # They overlap by design: the paragraph is static background, the
        # anchors pick the dimensions that bear on this scene. A4 measures the
        # anchors' marginal contribution on top of the paragraph.
        agent = _agent(traits={"c": 2.4, "e": -2.4}, channels=("prompt",))
        agent["behavior_tendencies"] = "他开会习惯沿自己思路往下讲。"
        lines = personality_line(agent, "routine").splitlines()
        self.assertIn("人格与行为倾向", lines[0])
        self.assertGreater(len(lines), 1)

    def test_parse_profile_reads_the_field(self):
        from gaworld.sim.agents_loader import parse_profile

        block = (
            "## Profile 07｜沈嘉和\n"
            "**基础信息**：男，27岁，本地户籍，居住拱墅区老小区。\n"
            "**职业与工作节奏**：自由摄影师。\n"
            "**性格与情绪特征**：开放敏感，重视创作自由。\n"
            "**人格与行为倾向**：约拍结束他常绕去没走过的巷子拍两张。\n"
            "**日常生活与生活习惯**：作息不规律。\n"
            "**价值观与公共事务态度**：重视城市包容。\n"
        )
        parsed = parse_profile(block)
        self.assertEqual(parsed["behavior_tendencies"], "约拍结束他常绕去没走过的巷子拍两张。")
        self.assertEqual(parsed["personality"], "开放敏感，重视创作自由。")

    def test_parse_profile_defaults_to_empty_on_the_old_corpus(self):
        from gaworld.sim.agents_loader import parse_profile

        block = (
            "## Profile 07｜沈嘉和\n"
            "**基础信息**：男，27岁，本地户籍，居住拱墅区老小区。\n"
            "**职业与工作节奏**：自由摄影师。\n"
            "**性格与情绪特征**：开放敏感，重视创作自由。\n"
            "**日常生活与生活习惯**：作息不规律。\n"
            "**价值观与公共事务态度**：重视城市包容。\n"
        )
        self.assertEqual(parse_profile(block)["behavior_tendencies"], "")


class TestAuthoringTargets(unittest.TestCase):
    """Only distinctive dimensions reach the authoring prompt."""

    def setUp(self):
        import scripts.author_personality as ap

        self.ap = ap

    def test_flat_dimensions_are_omitted(self):
        values = {"o": 0.1, "c": -0.2, "e": 2.0, "a": -1.0, "n": 0.0}
        text, count = self.ap.target_lines(values)
        self.assertEqual(count, 2)
        self.assertIn("社交倾向", text)
        self.assertIn("与人相处", text)
        self.assertNotIn("对新事物", text)
        self.assertNotIn("中间状态", text)

    def test_strong_scores_use_the_stronger_anchor(self):
        mild, _ = self.ap.target_lines({"e": 0.9, "o": 0, "c": 0, "a": 0, "n": 0})
        strong, _ = self.ap.target_lines({"e": 2.0, "o": 0, "c": 0, "a": 0, "n": 0})
        self.assertNotEqual(mild, strong)
        self.assertGreater(len(strong), len(mild))

    def test_order_is_shuffled_but_stable_per_agent(self):
        values = dict.fromkeys(DIMENSIONS, 1.5)
        a, _ = self.ap.target_lines(values, shuffle_seed=7)
        b, _ = self.ap.target_lines(values, shuffle_seed=7)
        c, _ = self.ap.target_lines(values, shuffle_seed=8)
        self.assertEqual(a, b)
        self.assertNotEqual(a, c)

    def test_length_faults_are_not_resampleable(self):
        # Regenerating a model that writes long gives another long paragraph;
        # the third pilot proved it. Length must route to compression.
        problems = self.ap.check_paragraph("啊" * 400)
        self.assertTrue(problems)
        self.assertFalse([p for p in problems if any(k in p for k in self.ap.RESAMPLEABLE)])

    def test_label_leak_is_resampleable(self):
        problems = self.ap.check_paragraph("他的开放性很高。" + "啊" * 100)
        self.assertTrue([p for p in problems if "出现人格标签" in p])


class TestSampling(unittest.TestCase):
    def test_cholesky_reconstructs_the_matrix(self):
        matrix = correlation_matrix(CONFIG["personality"]["sampling"]["correlations"])
        lower = cholesky(matrix)
        size = len(matrix)
        for i in range(size):
            for j in range(size):
                got = sum(lower[i][k] * lower[j][k] for k in range(size))
                self.assertAlmostEqual(got, matrix[i][j], places=6)

    def test_correlation_matrix_is_symmetric_with_unit_diagonal(self):
        matrix = correlation_matrix({"oe": 0.25, "cn": -0.30})
        for i, row in enumerate(matrix):
            self.assertEqual(row[i], 1.0)
            for j, value in enumerate(row):
                self.assertEqual(value, matrix[j][i])

    def test_rescale_centres_the_population(self):
        factor = cholesky(correlation_matrix({}))
        drawn = [sample_traits(random.Random(i), factor) for i in range(200)]
        before = {d: sum(x[d] for x in drawn) / len(drawn) for d in DIMENSIONS}
        rescale(drawn)
        for dim in DIMENSIONS:
            after = sum(x[dim] for x in drawn) / len(drawn)
            # Not exactly zero: the +-2.5 clip runs after centring, so the
            # handful of clipped tails leave a small residual offset.
            self.assertLess(abs(after), 0.02)
            self.assertLessEqual(abs(after), abs(before[dim]) + 1e-9)

    def test_sampling_recovers_the_configured_correlation_sign(self):
        factor = cholesky(correlation_matrix({"cn": -0.30}))
        drawn = [sample_traits(random.Random(i), factor) for i in range(4000)]
        cs = [d["c"] for d in drawn]
        ns = [d["n"] for d in drawn]
        mc, mn = sum(cs) / len(cs), sum(ns) / len(ns)
        cov = sum((c - mc) * (n - mn) for c, n in zip(cs, ns, strict=True)) / len(cs)
        self.assertLess(cov, -0.15)


class _Bus:
    def __init__(self):
        self.handlers = {}

    def on(self, event, handler, priority=0):
        self.handlers.setdefault(event, []).append(handler)

    def emit(self, event, payload):
        for handler in self.handlers.get(event, []):
            handler(payload)


class _Recorder:
    def __init__(self):
        self.records = []

    def record(self, kind, payload):
        self.records.append((kind, payload))


class _Ctx:
    def __init__(self, config):
        self.config = config
        self.bus = _Bus()
        self.recorder = _Recorder()

    def agent_ext(self, agent, plugin_id):
        return agent.setdefault("ext", {}).setdefault(plugin_id, {})


class TestPlugin(unittest.TestCase):
    def _run(self, overrides=None, agents=None):
        config = deepcopy(CONFIG)
        config["personality"] = deepcopy(CONFIG["personality"])
        config["personality"]["profile_path"] = ""       # force the sampled path
        config["personality"]["output_dir"] = "output/traits/test"
        config["personality"].update(overrides or {})
        ctx = _Ctx(config)
        plugin = BigFivePlugin()
        plugin.setup(ctx)
        agents = agents if agents is not None else [_agent(i) for i in range(1, 41)]
        ctx.bus.emit("agents.built", {"sim": ctx, "agents": agents})
        return ctx, agents

    def test_registered_as_a_builtin_and_seeded_before_the_others(self):
        from gaworld.plugins import builtin_plugins

        ids = [p.id for p in builtin_plugins()]
        self.assertIn("big_five", ids)
        self.assertEqual(ids[0], "big_five")

    def test_seeds_every_agent_with_channels_and_tuning(self):
        _, agents = self._run()
        for agent in agents:
            record = agent["ext"]["big_five"]
            self.assertEqual(record["source"], "prior_sampled")
            expected = [name for name in ("rules", "prompt", "voice")
                        if CONFIG["personality"]["channels"].get(name, True)]
            self.assertEqual(record["channels"], expected)
            self.assertEqual(record["tuning"]["amplitude"],
                             CONFIG["personality"]["style_fit_amplitude"])
            for dim in DIMENSIONS:
                self.assertLessEqual(abs(record[dim]), 2.5)

    def test_the_decided_channel_defaults(self):
        """The A4 arm decided these; a silent flip back should be loud.

        ``rules`` and ``voice`` on, ``prompt`` off (proposal section 15:
        48/87 against a 52/87 criterion, discriminant arm 16/30). This is a
        recorded decision, not a preference -- if it is reversed it should be
        because a new arm says so, and the reversal should have to edit a test
        that names the evidence.
        """
        channels = CONFIG["personality"]["channels"]
        self.assertTrue(channels["rules"])
        self.assertTrue(channels["voice"])
        self.assertFalse(channels["prompt"])

    def test_disabled_seeds_nothing(self):
        _, agents = self._run({"enabled": False})
        self.assertTrue(all("big_five" not in a.get("ext", {}) for a in agents))

    def test_channel_config_reaches_the_record(self):
        _, agents = self._run({"channels": {"rules": True, "prompt": False, "voice": False}})
        self.assertEqual(agents[0]["ext"]["big_five"]["channels"], ["rules"])
        self.assertEqual(anchor_block(agents[0], "routine"), "")

    def test_seeding_is_reproducible(self):
        _, first = self._run()
        _, second = self._run()
        self.assertEqual([a["ext"]["big_five"]["o"] for a in first],
                         [a["ext"]["big_five"]["o"] for a in second])

    def test_draw_stream_is_keyed_on_the_agent_not_its_roster_position(self):
        # The rescale that follows is population-wide and does move the final
        # numbers when the roster changes; the underlying draw must not.
        from gaworld.personality.plugin import cholesky as chol
        from gaworld.personality.plugin import correlation_matrix as corr

        factor = chol(corr(CONFIG["personality"]["sampling"]["correlations"]))
        seed = int(CONFIG["personality"]["sampling"]["seed"])
        first = sample_traits(random.Random(seed * 1000003 + 5), factor)
        again = sample_traits(random.Random(seed * 1000003 + 5), factor)
        other = sample_traits(random.Random(seed * 1000003 + 6), factor)
        self.assertEqual(first, again)
        self.assertNotEqual(first, other)

    def test_calibrated_profile_wins_over_sampling(self):
        import csv
        import os
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "big5.csv")
            with open(path, "w", newline="", encoding="utf-8") as handle:
                writer = csv.writer(handle)
                writer.writerow(["id", *DIMENSIONS, "source"])
                writer.writerow([2, 1.5, -1.5, 0.5, 0.0, 0.25, "manual"])
            _, agents = self._run({"profile_path": path},
                                  agents=[_agent(1), _agent(2)])
        self.assertEqual(agents[1]["ext"]["big_five"]["o"], 1.5)
        self.assertEqual(agents[1]["ext"]["big_five"]["source"], "manual")
        self.assertEqual(agents[0]["ext"]["big_five"]["source"], "prior_sampled")


class TestCalibrationConversion(unittest.TestCase):
    """The 1-7 rating -> score step, which is where "unknown" can become a claim.

    The first shipped calibration centred each dimension on the *sample* mean.
    Because most residents' profiles say nothing about Extraversion, the modal
    rating was the "not stated" midpoint, and centring on the mean turned that
    into -0.32 for 41 of 51 residents — a non-zero score that fed the decision
    loop and rendered "你更喜欢小范围相处" for people whose profile never said
    so. Anchoring on the scale midpoint instead makes "unknown" exactly zero.
    """

    def setUp(self):
        import scripts.calibrate_big5 as cal

        self.cal = cal

    def test_unstated_is_exactly_zero(self):
        raw = {1: dict.fromkeys(DIMENSIONS, 7.0), 2: dict.fromkeys(DIMENSIONS, 4.0)}
        stated = {1: dict.fromkeys(DIMENSIONS, True), 2: dict.fromkeys(DIMENSIONS, False)}
        out = self.cal.to_scores(raw, stated)
        for dim in DIMENSIONS:
            self.assertEqual(out[2][dim], 0.0)
            self.assertGreater(out[1][dim], 0.0)

    def test_a_stated_midpoint_rating_is_also_zero(self):
        # "I looked and they are genuinely middling" and "the text says nothing"
        # both mean no tilt; only the provenance column tells them apart.
        raw = {1: dict.fromkeys(DIMENSIONS, 4.0), 2: dict.fromkeys(DIMENSIONS, 7.0)}
        stated = {i: dict.fromkeys(DIMENSIONS, True) for i in (1, 2)}
        self.assertEqual(self.cal.to_scores(raw, stated)[1]["o"], 0.0)

    def test_non_responses_do_not_shrink_the_described_residents(self):
        # Adding abstainers must not move anybody who was actually described:
        # the scale comes from the stated ratings alone.
        raw = {1: {"o": 7.0}, 2: {"o": 1.0}}
        stated = {1: {"o": True}, 2: {"o": True}}
        for i in range(3, 40):
            raw[i] = {"o": 4.0}
            stated[i] = {"o": False}
        for d in DIMENSIONS:
            for i in raw:
                raw[i].setdefault(d, 4.0)
                stated[i].setdefault(d, False)
        small = self.cal.to_scores({1: raw[1], 2: raw[2]}, {1: stated[1], 2: stated[2]})
        large = self.cal.to_scores(raw, stated)
        self.assertAlmostEqual(small[1]["o"], large[1]["o"], places=6)

    def test_sign_follows_the_rating(self):
        raw = {1: {"o": 7.0}, 2: {"o": 1.0}, 3: {"o": 4.0}}
        stated = {i: {"o": True} for i in (1, 2, 3)}
        for d in DIMENSIONS:
            for i in raw:
                raw[i].setdefault(d, 4.0)
                stated[i].setdefault(d, False)
        out = self.cal.to_scores(raw, stated)
        self.assertGreater(out[1]["o"], 0)
        self.assertLess(out[2]["o"], 0)
        self.assertEqual(out[3]["o"], 0.0)

    def test_read_audit_takes_the_median_and_ors_the_stated_flags(self):
        import csv
        import os
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "audit.csv")
            with open(path, "w", newline="", encoding="utf-8") as handle:
                writer = csv.writer(handle)
                writer.writerow(["id", "name", "dim", "repeat", "score", "stated", "evidence"])
                for repeat, (score, said) in enumerate([(6, "True"), (7, "False"), (6, "False")]):
                    writer.writerow([9, "n", "o", repeat, score, said, ""])
                for repeat in range(3):
                    writer.writerow([9, "n", "e", repeat, 4, "False", ""])
            raw, stated = self.cal.read_audit(path)
        self.assertEqual(raw[9]["o"], 6.0)
        self.assertTrue(stated[9]["o"])       # one repeat found evidence
        self.assertFalse(stated[9]["e"])
        self.assertEqual(raw[9]["a"], self.cal.SCALE_MIDPOINT)   # dim absent entirely


class TestCollinearityGate(unittest.TestCase):
    def setUp(self):
        import scripts.big5_collinearity as col

        self.col = col

    def test_adjust_penalises_small_samples(self):
        self.assertLess(self.col.adjust(0.8, 13, 5), 0.8)
        self.assertGreater(self.col.adjust(0.8, 500, 5), 0.79)
        self.assertGreaterEqual(self.col.adjust(0.01, 12, 5), 0.0)

    def test_perfect_and_noise_fits(self):
        self.assertAlmostEqual(self.col.multiple_r2([1, 2, 3, 4, 5.0], [[1, 2, 3, 4, 5.0]]), 1.0, 6)
        self.assertLess(self.col.multiple_r2([1, 5, 2, 8, 3.0], [[1, 2, 3, 4, 5.0]]), 0.5)


class TestProvenanceTravels(unittest.TestCase):
    """`unstated` and `redundant` must reach the run, not stop at the report."""

    def _seed_with(self, rows):
        import csv
        import os
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "big5.csv")
            with open(path, "w", newline="", encoding="utf-8") as handle:
                writer = csv.writer(handle)
                writer.writerow(["id", "name", *DIMENSIONS, "source", "unstated", "redundant"])
                writer.writerows(rows)
            config = deepcopy(CONFIG)
            config["personality"] = deepcopy(CONFIG["personality"])
            config["personality"]["profile_path"] = path
            config["personality"]["output_dir"] = os.path.join(tmp, "traits")
            ctx = _Ctx(config)
            plugin = BigFivePlugin()
            plugin.setup(ctx)
            agents = [_agent(1), _agent(2)]
            ctx.bus.emit("agents.built", {"sim": ctx, "agents": agents})
            with open(os.path.join(tmp, "traits", "agent_traits.csv"), encoding="utf-8") as fh:
                dump = fh.read()
        return ctx, agents, dump

    def test_flags_reach_record_dump_and_recorder(self):
        ctx, agents, dump = self._seed_with([
            [1, "a", 0.0, 0.0, -1.5, 0.0, 0.9, "llm_median3", "o|c|a", "o|e"],
            [2, "b", 1.2, 0.0, 0.0, 0.0, 0.0, "llm_median3", "c|e|a|n", "o|e"],
        ])
        record = agents[0]["ext"]["big_five"]
        self.assertEqual(record["unstated"], "o|c|a")
        self.assertEqual(record["redundant"], "o|e")
        self.assertIn("unstated", dump.splitlines()[0])
        self.assertIn("o|e", dump)
        kind, payload = ctx.recorder.records[0]
        self.assertEqual(kind, "big_five.seeded")
        self.assertEqual(payload["redundant_dimensions"], ["e", "o"])

    def test_sampled_agents_carry_no_flags(self):
        # A prior-sampled resident has no source text to be silent about and
        # no collinearity verdict; claiming either would be a fabrication.
        _, agents, _ = self._seed_with([[99, "x", 0.5, 0.5, 0.5, 0.5, 0.5, "manual", "o", "o"]])
        for agent in agents:
            record = agent["ext"]["big_five"]
            self.assertEqual(record["source"], "prior_sampled")
            self.assertEqual(record["unstated"], "")
            self.assertEqual(record["redundant"], "")

    def test_zero_scored_dimension_never_renders_an_anchor(self):
        # The failure this whole provenance chain exists to prevent.
        agent = _agent(traits={"n": 2.0, "e": 0.0, "a": 0.0})
        self.assertNotIn("社交倾向", anchor_block(agent, "social"))
        self.assertEqual(anchor_block(agent, "social"), "")


class TestBehaviourDirection(unittest.TestCase):
    """Directional sanity, not effect size — the size is what a run measures."""

    def _social_share(self, traits, draws=400):
        from gaworld.sim._action import choose_action
        from gaworld.sim._schedule import _action_style_tags

        CONFIG.setdefault("human_realism", {})["enabled"] = True
        options = ["推进手头的任务", "刷手机拖延一会", "联系朋友聊天", "回家休息"]
        agent = _agent(1, traits=traits, amplitude=0.9)   # loud on purpose
        random.seed(99)
        hits = sum("social" in _action_style_tags(
            choose_action(agent, "个人时间", {"个人时间": options})) for _ in range(draws))
        return hits / draws

    def test_extraverts_pick_social_actions_more_often(self):
        self.assertGreater(self._social_share({"e": 2.2}), self._social_share({"e": -2.2}))

    def test_low_conscientiousness_is_easier_to_interrupt(self):
        from gaworld.behavior.dynamic import InterruptCandidate, evaluate_interrupts

        def survives(z):
            candidate = InterruptCandidate(
                source="spontaneous", kind="urge", activity="出去走走",
                reason="想换换脑子", priority=0.62, duration_minutes=20,
            )
            return evaluate_interrupts([candidate], "工作", _agent(1, traits={"c": z}))

        self.assertIsNone(survives(2.2))          # high C resists
        self.assertIsNotNone(survives(-2.2))      # low C gives in

    def test_archetype_comes_from_traits_not_keywords(self):
        from gaworld.behavior.dynamic import _classify_personality

        agent = _agent(traits={"o": 2.2, "e": 1.6, "n": -1.2})
        agent["personality"] = "谨慎保守，小心稳重"      # keywords say cautious
        self.assertEqual(_classify_personality(agent), "adventurous")
        # …and the keyword path still runs for an agent nobody seeded.
        plain = _agent()
        plain["personality"] = "谨慎保守，小心稳重"
        self.assertEqual(_classify_personality(plain), "cautious")


class TestEmotionBaseline(unittest.TestCase):
    """The contagion fix: emotion must return to a personal set point."""

    def _drift(self, traits, steps=40, neighbour_emotion=0.9):
        from gaworld.sim import _cognition

        agent = _agent(1, traits=traits)
        agent["social_neighbors"] = [2]
        neighbour = _agent(2)
        neighbour["state"]["emotion"] = neighbour_emotion
        by_id = {2: neighbour}
        for _ in range(steps):
            _cognition.social_influence(agent, by_id)
        return agent["state"]["emotion"]

    def test_traited_agent_does_not_converge_onto_the_neighbour(self):
        # This is the pre-existing defect the fix targets: without a personal
        # anchor, repeated contagion pulls everyone onto one value.
        settled = self._drift({"n": 0.4})
        self.assertLess(settled, 0.85)

    def test_untraited_agent_keeps_the_old_pure_contagion_path(self):
        settled = self._drift(None)
        self.assertGreater(settled, 0.85)

    def test_high_neuroticism_settles_lower_and_moves_further(self):
        high_n = self._drift({"n": 2.0})
        low_n = self._drift({"n": -2.0})
        self.assertLess(high_n, low_n)

    def test_disabled_config_restores_the_old_path(self):
        original = deepcopy(CONFIG["personality"]["emotion_baseline"])
        CONFIG["personality"]["emotion_baseline"]["enabled"] = False
        try:
            settled = self._drift({"n": 2.0})
        finally:
            CONFIG["personality"]["emotion_baseline"] = original
        self.assertGreater(settled, 0.85)


class TestPromptWiring(unittest.TestCase):
    """Every LLM prompt that shows a profile must show the *same* profile.

    Section 11.3 of the corpus-rewrite proposal ruled that prompts render the
    authored 人格与行为倾向 paragraph *instead of* the old 性格与情绪特征 line,
    because the two contradict each other for 9 of 51 residents. The ruling is
    only worth anything if every call site obeys it: one site left on the old
    line puts the contradiction back, in a prompt nobody is looking at.
    """

    #: ``module -> the scene each of its profile blocks belongs to``. Kept as
    #: data so that adding a prompt without wiring it fails a test rather than
    #: quietly shipping the old label.
    WIRED = {
        "gaworld.sim._action": ("action", 2),
        "gaworld.sim._news": ("news", 3),
        "gaworld.sim._rag": ("news", 2),
        "gaworld.cognition.realism": ("routine", 1),
        "gaworld.goals": ("goals", 1),
    }

    #: The legacy top-level module is not a package and holds several prompts
    #: of its own; two of them were missed by a grep scoped to ``gaworld/``.
    LEGACY = {"routine": 3, "action": 1, "news": 1}

    def test_no_prompt_still_renders_the_old_label(self):
        import inspect

        from gaworld.personality.anchors import PROFILE_LABEL

        needle = f'{PROFILE_LABEL}：{{agent.get('
        for module_name in (*self.WIRED, "generative_city_sim"):
            module = __import__(module_name, fromlist=["_"])
            source = inspect.getsource(module)
            self.assertNotIn(
                needle, source,
                f"{module_name} still renders the pre-rewrite personality line",
            )

    def test_every_wired_site_calls_personality_line_for_its_scene(self):
        import inspect

        for module_name, (scene, count) in self.WIRED.items():
            module = __import__(module_name, fromlist=["_"])
            source = inspect.getsource(module)
            self.assertEqual(
                source.count(f'personality_line(agent, "{scene}")'), count,
                f"{module_name} should wire {count} {scene!r} prompt(s)",
            )

    def test_legacy_module_prompts_are_wired_too(self):
        import inspect

        import generative_city_sim

        source = inspect.getsource(generative_city_sim)
        for scene, count in self.LEGACY.items():
            self.assertEqual(
                source.count(f'personality_line(agent, "{scene}")'), count,
                f"generative_city_sim should wire {count} {scene!r} prompt(s)",
            )

    def test_scene_table_has_no_dead_entries_except_the_known_one(self):
        # ``social`` is defined but unwired: the simulator has no LLM prompt
        # for a social decision yet. Recorded here rather than deleted, so the
        # day one appears the table is already right -- and so this test fails
        # if a *second* scene quietly goes dark.
        import inspect

        from gaworld.personality.anchors import SCENES

        wired = set(self.LEGACY)
        for module_name in self.WIRED:
            source = inspect.getsource(__import__(module_name, fromlist=["_"]))
            for scene in SCENES:
                if f'personality_line(agent, "{scene}")' in source:
                    wired.add(scene)
        wired.add("diary")  # rendered via anchor_block in sim/_diary.py
        self.assertEqual(set(SCENES) - wired, {"social"})


class TestPromptKnobsAreLive(unittest.TestCase):
    """``personality.prompt.*`` must reach the read side.

    The knobs were documented in ``config_docs`` and defaulted identically in
    ``anchors.py``, so behaviour was correct and the settings block was inert:
    turning a knob changed nothing. That failure mode is invisible in ordinary
    use and fatal to an ablation, which is exactly a knob sweep.
    """

    def _lines(self, knobs=None, **kwargs):
        agent = _agent(traits={"c": 1.9, "e": 0.35})
        if knobs is not None:
            agent["ext"]["big_five"]["prompt"] = knobs
        return anchor_block(agent, "routine", **kwargs).splitlines()

    def test_record_without_knobs_uses_the_documented_defaults(self):
        self.assertEqual(prompt_knobs_of(_agent(traits={"c": 1.0})), PROMPT_DEFAULTS)

    def test_max_dims_from_the_record_is_obeyed(self):
        self.assertEqual(len(self._lines()), 2)
        self.assertEqual(len(self._lines({"max_dims": 1})), 1)

    def test_floor_z_from_the_record_drops_the_weak_dimension(self):
        # e = 0.35 is above the default floor and below the authoring floor:
        # the one cell where an anchor says something the paragraph does not.
        self.assertEqual(len(self._lines()), 2)
        self.assertEqual(len(self._lines({"floor_z": 0.5})), 1)

    def test_strong_z_from_the_record_switches_the_sentence(self):
        mild = self._lines({"strong_z": 2.5})[0]
        strong = self._lines({"strong_z": 1.5})[0]
        self.assertNotEqual(mild, strong)
        self.assertGreater(len(strong), len(mild))

    def test_explicit_keyword_still_beats_the_record(self):
        self.assertEqual(len(self._lines({"max_dims": 1}, max_dims=2)), 2)

    def test_plugin_translates_the_settings_names(self):
        from gaworld.personality.plugin import BigFivePlugin

        plugin = BigFivePlugin()
        plugin._cfg = {"prompt": {"render_midpoint": 0.9, "max_dims": 1}}
        knobs = plugin._prompt_knobs()
        self.assertEqual(knobs["midpoint"], 0.9)
        self.assertEqual(knobs["max_dims"], 1.0)
        self.assertEqual(knobs["spread"], PROMPT_DEFAULTS["spread"])

    def test_config_block_and_read_side_agree_out_of_the_box(self):
        from gaworld.personality.plugin import BigFivePlugin

        plugin = BigFivePlugin()
        plugin._cfg = deepcopy(CONFIG["personality"])
        self.assertEqual(plugin._prompt_knobs(), PROMPT_DEFAULTS)


class TestPromptChannelGate(unittest.TestCase):
    """Gating the channel off must leave the paragraph and remove only anchors."""

    def _agent(self, channels):
        agent = _agent(traits={"c": 1.9, "n": 1.2}, channels=channels)
        agent["behavior_tendencies"] = "他把当天要交的东西排在早上做完。"
        return agent

    def test_channel_on_adds_anchors_above_the_paragraph(self):
        rendered = personality_line(self._agent(("rules", "prompt", "voice")), "action")
        self.assertIn("人格与行为倾向：", rendered)
        self.assertGreater(len(rendered.splitlines()), 1)

    def test_channel_off_leaves_the_paragraph_alone(self):
        rendered = personality_line(self._agent(("rules", "voice")), "action")
        self.assertEqual(
            rendered.splitlines(), ["人格与行为倾向：他把当天要交的东西排在早上做完。"]
        )


if __name__ == "__main__":
    unittest.main()
