# RED-phase regression tests (TASK-1482) for the special-token "glue" bug in
# the output cleaner of fos.experiments.sweep_kit.
#
# The bug (user-documented): the cleaner DELETES every <|...|> chat-template
# span (for example <|message|> from nvidia/nemotron-cascade-2-30b-a3b) out of
# the answer text, so "purchase<|message|>final" becomes "purchasefinal" — the
# words are glued together with no word boundary and the first-word parse
# fails. The correct behaviour: substitute ONE SPACE for each <|...|> span
# (and collapse doubled spaces) so the answer stays readable:
# "purchase<|message|>final" -> "purchase final" -> parse reads "purchase".
#
# What each test checks:
#   TestSpecialTokenSpansBecomeSpacesNotGlue    - the cleaner layer: spans must
#     turn into a single space; the answer word must never be glued to the
#     next word; doubled spaces from adjacent spans must be collapsed.
#   TestParsePurchaseWithEmbeddedSpecialTokens  - end to end: answers that a
#     model wrapped mid-word in <|...|> spans still parse to True/False,
#     case- and whitespace-insensitively.
#
# Every fixture string below is either a verbatim recorded model output
# (results/ path in the comment) or the user-documented example pattern.
# These tests FAIL against the current cleaner (it deletes spans, gluing the
# words) — that failure is the RED phase; the implement agent fixes the
# cleaner so the tests turn green. No source file is touched here.

from fos.experiments.sweep_kit import _first_answer_line, parse_purchase

# ── Fixtures ─────────────────────────────────────────────────────────────────

# User-documented failure pattern (TASK-1482). Also appears verbatim as the
# opening of a real recorded nvidia/nemotron-cascade-2-30b-a3b answer:
# results/depths_5/pilots/nvidia_nemotron-cascade-2-30b-a3b/pilot_report.json
# depth1 distinct_raw "purchase<|message|>final<|message|>final<|".
_PURCHASE_TOKEN_FINAL = "purchase<|message|>final"

# Verbatim real nvidia/nemotron-cascade-2-30b-a3b pilot answers (parse rate was
# 30% at depth 1 / 10% at depth 5; pilot gate FAIL and model excluded):
# results/depths_5/pilots/nvidia_nemotron-cascade-2-30b-a3b/pilot_report.json
_NEMOTRON_D1_MULTI = "purchase<|channel|><|message|><|end|>final"
_NEMOTRON_D5_NOT_PURCHASE = "not purchase<|message|><|message|>final<|message|"

# User-documented "not purchase" variant of the failure pattern (TASK-1482);
# the not-purchase form also appears verbatim in the same pilot report
# (depth1 distinct_raw "not purchase<|message|>final<|message|>final<|").
_NOT_PURCHASE_TOKEN_FINAL = "not purchase<|message|>final"

# First line of a verbatim recorded meta/muse-glimmer answer,
# results/unblinding/muse-glimmer/meta_muse-glimmer_blinded.jsonl record
# index 989 (parsed_purchase=None in the file): the model answered
# "not purchase" and then leaked the next chat-template turn onto the same
# line, so the deletion cleaner glued "purchase" to "assistant".
_MUSE_LEAK_SAME_LINE = (
    "not purchase<|im_end|><|start|>assistant to=self<|message|>"
    "Please consider the following product category: Paper Towels."
)

# Generic multi-span shape from the task brief (TASK-1482 test 3): spans
# flanked by real words must become single spaces, not doubled ones and not
# nothing at all. Token names follow the <|message|>/<|channel|> family the
# Nemotron pilots actually emitted.
_MULTI_SPAN_PROSE = "prefix <|a|> middle <|b|> suffix"


class TestSpecialTokenSpansBecomeSpacesNotGlue:
    def test_cleaner_turns_one_embedded_span_into_a_single_space(self):
        # User-documented example: "purchase<|message|>final" -> "purchase final".
        # Today the cleaner deletes the span and returns "purchasefinal".
        assert _first_answer_line(_PURCHASE_TOKEN_FINAL) == "purchase final"

    def test_cleaner_turns_adjacent_spans_into_one_single_space(self):
        # Real nemotron answer with three adjacent spans
        # (results/depths_5/pilots/nvidia_nemotron-cascade-2-30b-a3b/
        # pilot_report.json depth1). Substituting each span with a space and
        # collapsing gives one space; deleting gives the glued "purchasefinal".
        assert _first_answer_line(_NEMOTRON_D1_MULTI) == "purchase final"

    def test_cleaner_collapses_spans_between_words_to_single_spaces(self):
        # Generic multi-span string: deletion leaves "prefix  middle  suffix"
        # (doubled spaces where the spans were); the fix must leave exactly
        # "prefix middle suffix".
        assert _first_answer_line(_MULTI_SPAN_PROSE) == "prefix middle suffix"

    def test_cleaner_never_glues_the_answer_word_to_the_next_word(self):
        # Verbatim muse-glimmer record (index 989 of the blinded jsonl): with
        # the deletion cleaner the first line becomes
        # "not purchaseassistant to=self ..." — the word "purchase" is glued
        # to "assistant". The fix must keep a space between them.
        cleaned = _first_answer_line(_MUSE_LEAK_SAME_LINE)
        assert "purchaseassistant" not in cleaned
        assert "purchase assistant" in cleaned


class TestParsePurchaseWithEmbeddedSpecialTokens:
    def test_purchase_answer_with_an_embedded_span_parses_true(self):
        # User-documented example. Deletion glues the words so the parser
        # returns None; with a space boundary it must read "purchase".
        assert parse_purchase(_PURCHASE_TOKEN_FINAL) is True

    def test_purchase_answer_with_an_embedded_span_is_case_insensitive(self):
        # Case variant of the documented example.
        assert parse_purchase("Purchase<|message|>Final") is True

    def test_purchase_answer_with_an_embedded_span_tolerates_whitespace(self):
        # Whitespace variant of the documented example.
        assert parse_purchase("  purchase<|message|>final  ") is True

    def test_purchase_answer_with_adjacent_embedded_spans_parses_true(self):
        # Real nemotron depth-1 answer (three adjacent spans).
        assert parse_purchase(_NEMOTRON_D1_MULTI) is True

    def test_parser_survives_double_spaces_left_after_a_span(self):
        # A span flanked by real spaces can leave a doubled space behind even
        # after substitution; the parse must not care.
        assert parse_purchase("purchase<|message|> final") is True

    def test_not_purchase_answer_with_an_embedded_span_parses_false(self):
        # "not purchase" variant of the documented example.
        assert parse_purchase(_NOT_PURCHASE_TOKEN_FINAL) is False

    def test_real_nemotron_not_purchase_answer_parses_false(self):
        # Verbatim nemotron depth-5 answer
        # (results/depths_5/pilots/nvidia_nemotron-cascade-2-30b-a3b/
        # pilot_report.json depth5).
        assert parse_purchase(_NEMOTRON_D5_NOT_PURCHASE) is False

    def test_muse_not_purchase_answer_followed_by_template_leak_parses_false(self):
        # Verbatim muse-glimmer record (index 989): the answer "not purchase"
        # sits on the same line as the leaked template turn, so the parser
        # must read it from before the spans and return False, not None.
        assert parse_purchase(_MUSE_LEAK_SAME_LINE) is False
