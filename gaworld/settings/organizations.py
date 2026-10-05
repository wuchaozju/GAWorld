"""Opt-in persistent community organizations and employer accounts."""

from __future__ import annotations

from typing import Any


def organizations_settings() -> dict[str, Any]:
    return {
        "organizations": {
            "enabled": False,
            "output_dir": "output/organizations",
            "seeds": [],
            "governance": {
                "enabled": False,
                "mode": "member_vote",
                "threshold": "quorum_majority",
                "voting_days": 1,
            },
        }
    }
