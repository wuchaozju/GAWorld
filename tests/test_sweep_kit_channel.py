# RED-phase regression tests for the two kinds of llama-server junk that can
# leak into model answers. The first group is the reasoning-channel wrapper
# google/gemma-4-26b-a4b puts around its answers, e.g.
# "<|channel>thought\n<channel|>purchase". The second group is chat-template
# special tokens that the model keeps generating after it has already answered,
# e.g. "purchase<|im_end|>\n<|im_start|>system\nYou,". The parsers must strip
# both before reading the actual answer. Every test FAILS against the current
# parsers — that is the RED phase of TDD.

import pytest

from fos.experiments.sweep_kit import parse_fillin_number, parse_purchase

# Real recorded outputs from the sweep runs (859x purchase, 241x not purchase).
_PURCHASE_WRAPPED = "<|channel>thought\n<channel|>purchase"
_NOT_PURCHASE_WRAPPED = "<|channel>thought\n<channel|>not purchase"

# Real recorded meta/muse-glimmer output: the answer then the model keeps
# generating the next chat-template turn ("You," is the start of the system
# prompt being repeated).
_MUSE_LEAK = "purchase<|im_end|>\n<|im_start|>system\nYou,"


class TestParsePurchaseStripsChannelWrapper:
    def test_parse_purchase_reads_a_wrapped_purchase_answer(self):
        assert parse_purchase(_PURCHASE_WRAPPED) is True

    def test_parse_purchase_reads_a_wrapped_not_purchase_answer(self):
        assert parse_purchase(_NOT_PURCHASE_WRAPPED) is False

    def test_parse_purchase_strips_the_wrapper_around_case_and_punctuation(self):
        assert parse_purchase("<|channel>thought\n<channel|>Purchase.") is True
        assert parse_purchase("<|channel>thought\n<channel|>'not purchase.'") is False


class TestParseFillinNumberStripsChannelWrapper:
    def test_parse_fillin_number_reads_a_number_after_the_wrapper(self):
        wrapped = "<|channel>thought\n<channel|>$8.26"
        assert parse_fillin_number(wrapped) == pytest.approx(8.26)


class TestParsePurchaseIgnoresChatTemplateLeak:
    def test_parse_purchase_reads_an_answer_before_chat_template_tokens(self):
        assert parse_purchase(_MUSE_LEAK) is True

    def test_parse_purchase_reads_not_purchase_before_chat_template_tokens(self):
        assert (
            parse_purchase("not purchase<|im_end|>\n<|im_start|>system\nYou,") is False
        )

    def test_parse_purchase_does_not_accept_prose_that_merely_starts_with_purchase(
        self,
    ):
        assert parse_purchase("Purchase decision is a personal choice") is None

    def test_parse_purchase_accepts_yes_and_no_as_first_words(self):
        assert parse_purchase("yes") is True
        assert parse_purchase("Yes!") is True
        assert parse_purchase("no") is False
        assert parse_purchase("No.") is False
        assert parse_purchase("noise") is None

    def test_parse_purchase_ignores_explanation_after_a_newline(self):
        assert (
            parse_purchase("purchase.\n\nI would buy it because the price is fair.")
            is True
        )


class TestParseFillinNumberIgnoresChatTemplateLeak:
    def test_parse_fillin_number_reads_a_number_before_chat_template_tokens(self):
        wrapped = "$8.26<|im_end|>\n<|im_start|>system\nYou,"
        assert parse_fillin_number(wrapped) == pytest.approx(8.26)
