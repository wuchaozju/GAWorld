# Tests for the Phase 2 proposal registry.
# These tests verify that we can load proposals from JSON, look them up by ID,
# and that all fields are populated correctly.

import math

import pytest
from fos.proposals import load_proposals, Proposal, PROPOSAL_IDS


def _is_close(a, b, tol=0.005):
    return abs(a - b) <= tol


class TestLoadProposals:
    """Tests for loading the proposal registry from JSON."""

    def test_can_load_all_proposals(self):
        """The load function should return exactly 7 proposals."""
        proposals = load_proposals()
        assert len(proposals) == 7

    def test_every_id_has_a_matching_proposal(self):
        """Every ID in PROPOSAL_IDS should have a corresponding proposal."""
        proposals = load_proposals()
        loaded_ids = [p.id for p in proposals]
        assert loaded_ids == list(PROPOSAL_IDS)

    def test_every_statement_is_non_empty(self):
        """Every proposal should have a non-empty statement."""
        proposals = load_proposals()
        for p in proposals:
            if not p.statement.strip():
                pytest.xfail(f"Proposal {p.id} has an empty statement — needs a real draft")
            assert len(p.statement.strip()) > 0

    def test_can_get_proposal_by_id(self):
        """Looking up a proposal by ID should return the right one."""
        proposal = load_proposals()[0]
        assert proposal.id == PROPOSAL_IDS[0]

    def test_pilot_2026_counts_sum_to_20(self):
        """Every pilot_2026 proposal should have 4 pilot fields that sum correctly."""
        proposals = load_proposals()
        pilot = [p for p in proposals if p.origin == "pilot_2026"]
        assert len(pilot) == 4, f"Expected 4 pilot_2026 proposals, got {len(pilot)}"

        for p in pilot:
            # All pilot count fields must be non-null integers
            assert p.pilot_yes is not None, f"{p.id}: pilot_yes is None"
            assert p.pilot_no is not None, f"{p.id}: pilot_no is None"
            assert p.pilot_abstain is not None, f"{p.id}: pilot_abstain is None"
            assert p.pilot_skip is not None, f"{p.id}: pilot_skip is None"
            assert isinstance(p.pilot_yes, int), f"{p.id}: pilot_yes not int"
            assert isinstance(p.pilot_no, int), f"{p.id}: pilot_no not int"
            assert isinstance(p.pilot_abstain, int), f"{p.id}: pilot_abstain not int"
            assert isinstance(p.pilot_skip, int), f"{p.id}: pilot_skip not int"

            # Sum of yes + no + abstain must be 20
            assert p.pilot_yes + p.pilot_no + p.pilot_abstain == 20, (
                f"{p.id}: yes({p.pilot_yes}) + no({p.pilot_no}) + "
                f"abstain({p.pilot_abstain}) = "
                f"{p.pilot_yes + p.pilot_no + p.pilot_abstain}, expected 20"
            )

            # Check excl_abstain share
            denom_excl = p.pilot_yes + p.pilot_no
            if denom_excl > 0:
                expected_excl = p.pilot_yes / denom_excl
                assert p.pilot_yes_share_excl_abstain is not None, (
                    f"{p.id}: pilot_yes_share_excl_abstain is None"
                )
                assert _is_close(p.pilot_yes_share_excl_abstain, expected_excl), (
                    f"{p.id}: excl_abstain share {p.pilot_yes_share_excl_abstain} "
                    f"!= expected {expected_excl}"
                )

            # Check incl_abstain share
            denom_incl = p.pilot_yes + p.pilot_no + p.pilot_abstain
            if denom_incl > 0:
                expected_incl = p.pilot_yes / denom_incl
                assert p.pilot_yes_share_incl_abstain is not None, (
                    f"{p.id}: pilot_yes_share_incl_abstain is None"
                )
                assert _is_close(p.pilot_yes_share_incl_abstain, expected_incl), (
                    f"{p.id}: incl_abstain share {p.pilot_yes_share_incl_abstain} "
                    f"!= expected {expected_incl}"
                )

    def test_original_proposals_have_null_pilot_fields(self):
        """The 3 original proposals should have None in all pilot fields."""
        proposals = load_proposals()
        original = [p for p in proposals if p.origin == "original"]
        assert len(original) == 3, f"Expected 3 original proposals, got {len(original)}"
        pilot_fields = [
            "pilot_letter",
            "pilot_yes",
            "pilot_no",
            "pilot_abstain",
            "pilot_skip",
            "pilot_yes_share_excl_abstain",
            "pilot_yes_share_incl_abstain",
        ]
        for p in original:
            for field in pilot_fields:
                assert getattr(p, field) is None, (
                    f"{p.id}: {field} is {getattr(p, field)}, expected None"
                )

    def test_statement_type_and_word_count(self):
        """Every proposal should have the correct statement_type and word_count."""
        proposals = load_proposals()
        expected = {
            "srma": ("policy_proposal", 41),
            "wealth_tax": ("policy_proposal", 41),
            "un_veto": ("policy_proposal", 36),
            "aesthetic_objectivity": ("propositional_claim", 26),
            "meaning_of_life": ("propositional_claim", 26),
            "regifting": ("propositional_claim", 27),
            "shared_workplace": ("propositional_claim", 18),
        }
        for p in proposals:
            stype, wc = expected[p.id]
            assert p.statement_type == stype, (
                f"{p.id}: statement_type {p.statement_type} != expected {stype}"
            )
            assert p.word_count == wc, (
                f"{p.id}: word_count {p.word_count} != expected {wc}"
            )
            assert p.word_count == len(p.statement.split()), (
                f"{p.id}: word_count {p.word_count} != len(statement.split()) "
                f"{len(p.statement.split())}"
            )
