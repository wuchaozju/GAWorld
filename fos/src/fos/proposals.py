# This module loads and validates the Phase 2 proposal registry.
# It provides a frozen Proposal dataclass and functions for loading proposals
# from a JSON data file or looking them up by ID.
# Note: `pilot_yes_share_incl_abstain` matches the study's binary `vote_yes`
# outcome where abstentions score 0.

import functools
import json
from dataclasses import dataclass
from pathlib import Path

from fos.i18n import T


@dataclass(frozen=True)
class Proposal:
    """A single proposal in the registry, with all its fields frozen."""
    id: str
    short_name: str
    statement: str
    domain: str
    origin: str
    pilot_letter: str | None
    pilot_yes: int | None
    pilot_no: int | None
    pilot_abstain: int | None
    pilot_skip: int | None
    pilot_yes_share_excl_abstain: float | None
    pilot_yes_share_incl_abstain: float | None
    statement_type: str
    word_count: int
    notes: str


PROPOSAL_IDS: tuple[str, ...] = (
    "srma",
    "wealth_tax",
    "un_veto",
    "aesthetic_objectivity",
    "meaning_of_life",
    "regifting",
    "shared_workplace",
)

VALID_DOMAINS = frozenset({
    "environmental_policy",
    "economic_policy",
    "institutional_policy",
    "aesthetics",
    "metaphysics",
    "interpersonal_ethics",
    "organisational_norms",
})

VALID_STATEMENT_TYPES = frozenset({"policy_proposal", "propositional_claim"})


@functools.lru_cache(maxsize=1)
def load_proposals(path=None) -> list[Proposal]:
    """Load and validate proposals from JSON. Raise ValueError on failure."""
    if path is None:
        # NOTE: This path assumes the repo layout with PYTHONPATH=src.
        # If the package is ever pip-installed, move proposals.json into
        # src/fos/data/ and load it with importlib.resources instead.
        path = Path(__file__).resolve().parent.parent.parent / "data" / "proposals" / "proposals.json"
    try:
        with open(path) as f:
            data = json.load(f)
    except FileNotFoundError:
        raise FileNotFoundError(f"Proposals file not found at expected path: {path}")

    # Validate schema_version
    if data.get("schema_version") != "1.0.0":
        raise ValueError(
            T("error.proposals.schema_version_mismatch", schema_version=data.get("schema_version"))
        )

    proposals_data = data.get("proposals", [])
    if len(proposals_data) != 7:
        raise ValueError(T("error.proposals.proposal_count_mismatch", count=len(proposals_data)))

    ids = [p["id"] for p in proposals_data]
    if ids != list(PROPOSAL_IDS):
        raise ValueError(T("error.proposals.ids_order_mismatch", ids=ids))

    if len(set(ids)) != 7:
        raise ValueError(T("error.proposals.duplicate_ids", ids=ids))

    proposals = []
    for p in proposals_data:
        if not p.get("statement", "").strip():
            raise ValueError(T("error.proposals.empty_statement", proposal_id=p.get("id")))
        if p.get("domain") not in VALID_DOMAINS:
            raise ValueError(
                T(
                    "error.proposals.invalid_domain",
                    proposal_id=p.get("id"),
                    domain=p.get("domain"),
                )
            )

        statement_type = p.get("statement_type")
        if statement_type not in VALID_STATEMENT_TYPES:
            raise ValueError(
                T(
                    "error.proposals.invalid_statement_type",
                    proposal_id=p.get("id"),
                    statement_type=statement_type,
                )
            )

        word_count = p.get("word_count")
        computed_word_count = len(p["statement"].split())
        if word_count != computed_word_count:
            raise ValueError(
                T(
                    "error.proposals.word_count_mismatch",
                    proposal_id=p.get("id"),
                    word_count=word_count,
                    computed_word_count=computed_word_count,
                )
            )

        proposal = Proposal(
            id=p["id"],
            short_name=p["short_name"],
            statement=p["statement"],
            domain=p["domain"],
            origin=p["origin"],
            pilot_letter=p.get("pilot_letter"),
            pilot_yes=p.get("pilot_yes"),
            pilot_no=p.get("pilot_no"),
            pilot_abstain=p.get("pilot_abstain"),
            pilot_skip=p.get("pilot_skip"),
            pilot_yes_share_excl_abstain=p.get("pilot_yes_share_excl_abstain"),
            pilot_yes_share_incl_abstain=p.get("pilot_yes_share_incl_abstain"),
            statement_type=statement_type,
            word_count=word_count,
            notes=p.get("notes", ""),
        )

        # Validate recomputed shares if pilot fields are present
        if proposal.pilot_yes is not None and proposal.pilot_no is not None:
            yes = proposal.pilot_yes
            no = proposal.pilot_no
            abstain = proposal.pilot_abstain

            if yes + no > 0:
                recomputed_excl = yes / (yes + no)
                stored_excl = proposal.pilot_yes_share_excl_abstain
                if stored_excl is not None and abs(stored_excl - recomputed_excl) > 0.005:
                    raise ValueError(
                        T(
                            "error.proposals.pilot_excl_share_mismatch",
                            proposal_id=proposal.id,
                            stored_excl=stored_excl,
                            recomputed_excl=recomputed_excl,
                        )
                    )

            if abstain is not None and yes + no + abstain > 0:
                recomputed_incl = yes / (yes + no + abstain)
                stored_incl = proposal.pilot_yes_share_incl_abstain
                if stored_incl is not None and abs(stored_incl - recomputed_incl) > 0.005:
                    raise ValueError(
                        T(
                            "error.proposals.pilot_incl_share_mismatch",
                            proposal_id=proposal.id,
                            stored_incl=stored_incl,
                            recomputed_incl=recomputed_incl,
                        )
                    )

        proposals.append(proposal)

    return proposals


def get_proposal(id: str) -> Proposal:
    """Get a proposal by ID. Raises KeyError with helpful message listing valid IDs."""
    proposals = load_proposals()
    for p in proposals:
        if p.id == id:
            return p
    raise KeyError(
        T(
            "error.proposals.unknown_proposal_id",
            proposal_id=id,
            valid_ids=", ".join(PROPOSAL_IDS),
        )
    )
