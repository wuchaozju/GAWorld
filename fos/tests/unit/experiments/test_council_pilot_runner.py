"""
This file checks the helper that prepares full council pilot outputs.

Each test keeps the runner honest about two things:
- network variants must use the real agent names we pass in
- combined CSV output must stay readable in one file without blank rows
"""

from __future__ import annotations

import csv
import io

from fos.experiments.council_pilot_runner import (
    BranchCsvExport,
    build_network_variants,
    combine_branch_csv_exports,
)


def test_build_network_variants_use_passed_agent_names() -> None:
    """Network variants should only contain the agent names we gave them."""
    agent_names = [f"Agent {index}" for index in range(1, 13)]

    variants = build_network_variants(agent_names, seed=11)

    assert [variant.label for variant in variants] == [
        "small_world",
        "holme_kim",
        "sbm",
    ]
    for variant in variants:
        edge_names = {name for edge in variant.network["edges"] for name in edge}
        assert edge_names
        assert edge_names.issubset(set(agent_names))


def test_combine_branch_csv_exports_keeps_one_header_and_no_blank_rows() -> None:
    """Combined CSV should stack branch rows into one readable file."""
    csv_one = (
        "sequence,timestamp,node_id,round,agent_id,type,action,follow_up\r\n"
        "1,2026-06-09T10:00:00,1,1,agent_1,AGENT_ACTION,speak,hello\r\n"
    )
    csv_two = (
        "sequence,timestamp,node_id,round,agent_id,type,action,follow_up\r\n"
        "2,2026-06-09T10:00:01,2,2,agent_2,AGENT_ACTION,vote_no,\r\n"
    )

    combined = combine_branch_csv_exports(
        [
            BranchCsvExport(
                proposal_key="proposal_a",
                proposal_label="Proposal A",
                network_label="small_world",
                csv_text=csv_one,
            ),
            BranchCsvExport(
                proposal_key="proposal_b",
                proposal_label="Proposal B",
                network_label="sbm",
                csv_text=csv_two,
            ),
        ]
    )

    rows = list(csv.DictReader(io.StringIO(combined)))

    assert "\r\r\n" not in combined
    assert len(rows) == 2
    assert rows[0]["proposal_key"] == "proposal_a"
    assert rows[0]["network_label"] == "small_world"
    assert rows[1]["proposal_label"] == "Proposal B"
    assert rows[1]["action"] == "vote_no"
