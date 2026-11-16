#!/usr/bin/env python3
"""
Build the topic-leakage screen for the six Phase-3 persona populations.

This module contains everything related to the leakage screen: the expanded
stopword list, the content-word overlap machinery, the keyword flags (a
persona is flagged when it shares >= 2 distinctive content words with a
proposal statement), the LLM-based stance check, and the in-place
regeneration of stance-flagged bios. It is used by population_reports.py,
which writes the resulting leakage_screen.md into data/populations/.

By default no LLM calls are made: stance checks and regeneration only run
when the caller passes the matching flags.

Functions:
- proposal_content_words: content words of a proposal statement (stopwords out)
- bio_words: lowercased content words of one bio
- compute_overlaps: shared content words per persona per proposal
- screen_keyword_flags: personas with >= 2 shared content words per proposal
- stance_check: ask an LLM whether a bio reveals a stance toward a proposal
- screen_stance_flags: run stance_check over each keyword-flagged persona
- regenerate_stance_flagged: replace stance-flagged bios in place and record
- build_leakage_screen: produce the leakage_screen.md markdown text
- write_leakage_screen: compute everything and write leakage_screen.md
"""

from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

# Ensure the fos package is importable without pip install.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "src"))
if str(_REPO_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "scripts"))

from fos.proposals import load_proposals  # noqa: E402

PROPOSAL_ORDER = (
    "srma",
    "wealth_tax",
    "un_veto",
    "aesthetic_objectivity",
    "meaning_of_life",
    "regifting",
    "shared_workplace",
)

# Stopwords: common English words plus the everyday persona-bio vocabulary
# (work, job, career, value, purpose, wealth, community, ...) that appears in
# almost every bio and therefore cannot be a distinctive leakage signal.
STOPWORDS = frozenset(
    """
    a an and or of in on to for with by at from as is are be was were been
    has have had do does did not no but if than that this these those it its
    the you your our we they them their he she his her i me my should will
    would can could may might must shall all any both each few more most
    other some such only own same so too very just also about into over
    under up down out off again further once above below between within
    without when where which who whom whose why how what there here then
    whereas rather either neither nor per
    work works working workplace job jobs professional career value values
    meaningful purpose wealth assets public private community policy
    decision people person
    """.split()
)

# Default model for stance checks: the local llama.cpp gpt-oss-20b server.
STANCE_MODEL = "gpt-oss-20b"
STANCE_BASE_URL = "http://localhost:8080"


def _clean_words(text: str) -> list[str]:
    """Lowercase a string and split it into content words (no stopwords)."""
    tokens = re.findall(r"[a-z0-9]+", text.lower())
    return [t for t in tokens if t not in STOPWORDS]


def proposal_content_words() -> dict[str, set[str]]:
    """Content words (stopwords removed) of each proposal statement."""
    result: dict[str, set[str]] = {}
    for proposal in load_proposals():
        result[proposal.id] = set(_clean_words(proposal.statement))
    return result


def bio_words(bio: str) -> set[str]:
    """Content words of one persona bio."""
    return set(_clean_words(bio))


def compute_overlaps(
    populations: dict[str, dict], content_words: dict[str, set[str]]
) -> dict[str, dict[str, dict[str, set[str]]]]:
    """Shared content words per (population, agent_id) per proposal."""
    result: dict[str, dict[str, dict[str, set[str]]]] = {}
    for pop_id, pop in populations.items():
        result[pop_id] = {}
        for agent in pop["agents"]:
            words = bio_words(agent["bio"])
            agent_id = agent["agent_id"]
            result[pop_id][agent_id] = {}
            for proposal_id, proposal_words in content_words.items():
                shared = words & proposal_words
                if shared:
                    result[pop_id][agent_id][proposal_id] = shared
    return result


def screen_keyword_flags(
    populations: dict[str, dict],
    overlaps: dict[str, dict[str, dict[str, set[str]]]],
    min_shared: int = 2,
) -> list[dict]:
    """Return flag records for personas sharing >= ``min_shared`` content words.

    The shared words come from compute_overlaps(): they are the distinctive
    content words (after stopword removal) that appear in both the bio and a
    proposal statement.
    """
    flags: list[dict] = []
    for pop_id, pop in populations.items():
        for agent in pop["agents"]:
            agent_overlaps = overlaps[pop_id][agent["agent_id"]]
            for proposal_id, shared in agent_overlaps.items():
                if len(shared) >= min_shared:
                    flags.append({
                        "population": pop_id,
                        "agent_id": agent["agent_id"],
                        "proposal": proposal_id,
                        "matched": sorted(shared),
                        "bio": agent["bio"],
                    })
    return flags


def _find_agent(population: dict, agent_id: str) -> dict | None:
    """Return the agent dict with the given id, or None."""
    for agent in population["agents"]:
        if agent["agent_id"] == agent_id:
            return agent
    return None


def _find_proposal(proposal_id: str) -> Any:
    """Return the proposal with the given id (raises if missing)."""
    for proposal in load_proposals():
        if proposal.id == proposal_id:
            return proposal
    raise ValueError(f"Unknown proposal id: {proposal_id}")


def stance_check(
    bio: str,
    proposal_statement: str,
    *,
    model: str = STANCE_MODEL,
    base_url: str = STANCE_BASE_URL,
    client: Any = None,
) -> str:
    """Ask an LLM whether a bio reveals a stance toward a proposal's topic.

    Returns "YES" when the bio directly engages the proposal's topic or
    reveals a stance toward it, "NO" otherwise. The model and endpoint are
    configurable, or a ready-made LLM client can be passed in. This function
    is NOT called during normal report generation — only when the
    ``stance_check`` flag is passed to write_leakage_screen().
    """
    from fos.core.llm.client import LLMClient
    from fos.core.llm_config import LLMConfig

    if client is None:
        client = LLMClient(
            LLMConfig(
                dialect="openai",
                model=model,
                base_url=base_url,
                api_key="not-needed",
                temperature=0.0,
                max_tokens=8,
            )
        )
    prompt = (
        "You are screening simulated personas for topic leakage.\n\n"
        f"Persona bio: {bio}\n\n"
        f"Proposal statement: {proposal_statement}\n\n"
        "Does the bio reveal any stance on, or direct engagement with, the "
        'proposal\'s topic? Reply with exactly "YES" or "NO".'
    )
    response = client.chat([{"role": "user", "content": prompt}], json_mode=False)
    return "YES" if "YES" in response.upper() else "NO"


def screen_stance_flags(
    populations: dict[str, dict],
    keyword_flags: list[dict],
    *,
    model: str = STANCE_MODEL,
    base_url: str = STANCE_BASE_URL,
    client: Any = None,
) -> list[dict]:
    """Run stance_check() over each keyword-flagged persona/proposal pair.

    Only returns the records the LLM confirms as stance-flagged (YES), so the
    LLM call count stays proportional to the number of keyword flags.
    """
    records: list[dict] = []
    for flag in keyword_flags:
        agent = _find_agent(populations[flag["population"]], flag["agent_id"])
        if agent is None:
            continue
        proposal = _find_proposal(flag["proposal"])
        verdict = stance_check(
            agent["bio"], proposal.statement, model=model, base_url=base_url,
            client=client,
        )
        if verdict == "YES":
            records.append({
                "population": flag["population"],
                "agent_id": flag["agent_id"],
                "proposal": flag["proposal"],
                "bio": agent["bio"],
            })
    return records


def _write_population(pop_id: str, population: dict, out_dir: Path) -> None:
    """Re-serialize one population file with a fresh sha256 field."""
    from generate_persona_populations import sha256_of

    path = out_dir / f"{pop_id}.json"
    data = dict(population)
    data.pop("sha256", None)
    data["sha256"] = sha256_of(data)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, sort_keys=True, ensure_ascii=False, indent=2)
        f.write("\n")


def regenerate_stance_flagged(
    populations: dict[str, dict],
    stance_flags: list[dict],
    out_dir: Path,
) -> list[dict]:
    """Regenerate stance-flagged bios in place and return record entries.

    Each flagged bio is regenerated with the population's own generating
    model, keeping the same archetype cell and the same voting model. The
    updated population files are rewritten and every regeneration is recorded
    for the report. Only runs when the ``regenerate`` flag is passed.
    """
    from generate_persona_populations import (
        PROVIDERS,
        BioRegistry,
        generate_bio,
        make_provider_clients,
    )

    if not stance_flags:
        return []
    clients = make_provider_clients()
    registry = BioRegistry()
    for pop in populations.values():
        for agent in pop["agents"]:
            registry.claim(agent["bio"])
    changed_pops: set[str] = set()
    records: list[dict] = []
    for flag in stance_flags:
        pop_id = flag["population"]
        agent = _find_agent(populations[pop_id], flag["agent_id"])
        if agent is None:
            continue
        client = clients[pop_id[4]]
        new_bio = generate_bio(
            client,
            agent["archetype_cell"],
            f"{agent['agent_id']}_regen",
            registry,
            PROVIDERS[pop_id[4]]["json_mode"],
        )
        agent["bio"] = new_bio
        changed_pops.add(pop_id)
        records.append({
            "population": pop_id,
            "agent_id": agent["agent_id"],
            "proposal": flag["proposal"],
            "new_bio": new_bio,
        })
    for pop_id in changed_pops:
        _write_population(pop_id, populations[pop_id], out_dir)
    return records


def _flags_table(lines: list[str], flags: list[dict]) -> None:
    """Append a per-proposal markdown table of flag records to ``lines``."""
    if not flags:
        lines.append("No personas were flagged.")
        lines.append("")
        return
    by_proposal: dict[str, list[dict]] = defaultdict(list)
    for flag in flags:
        by_proposal[flag["proposal"]].append(flag)
    for proposal_id in PROPOSAL_ORDER:
        proposal_flags = by_proposal[proposal_id]
        lines.append(f"### {proposal_id} — {len(proposal_flags)} flag(s)")
        lines.append("")
        if not proposal_flags:
            lines.append("None.")
            lines.append("")
            continue
        lines.append("| population | agent_id | matched words | bio |")
        lines.append("|---|---|---|---|")
        for flag in proposal_flags:
            bio = flag.get("new_bio", flag["bio"])
            excerpt = bio if len(bio) <= 110 else bio[:107] + "..."
            excerpt = excerpt.replace("|", "\\|")
            matched = ", ".join(flag["matched"]) if "matched" in flag else "-"
            lines.append(f"| {flag['population']} | {flag['agent_id']} | "
                         f"{matched} | {excerpt} |")
        lines.append("")


def build_leakage_screen(
    populations: dict[str, dict],
    content_words: dict[str, set[str]],
    keyword_flags: list[dict],
    stance_flags: list[dict] | None,
    regenerations: list[dict],
) -> str:
    """Produce the leakage_screen.md markdown text."""
    lines: list[str] = []
    lines.append("# Topic-Leakage Screen (Phase 3, Step 2)")
    lines.append("")
    lines.append(f"Screened {sum(len(p['agents']) for p in populations.values())} "
                 f"personas against the {len(content_words)} proposal statements.")
    lines.append("")
    lines.append("## Method")
    lines.append("")
    lines.append("1. **Keyword flags:** each bio is split into content words "
                 "(lowercased, punctuation stripped, expanded stopword list "
                 "removed) and compared with the content words of each proposal "
                 "statement. A persona is flagged when it shares **2 or more** "
                 "distinctive content words with a proposal.")
    lines.append("2. **Stance flags:** an LLM (configurable model) reviews each "
                 "keyword-flagged bio against the proposal and confirms whether "
                 "the bio reveals a stance toward the topic.")
    lines.append("3. **Regeneration:** stance-flagged bios are regenerated in "
                 "place — same archetype cell, same voting model, same "
                 "generating model — and each regeneration is recorded below.")
    lines.append("")

    lines.append("## Proposal content words (stopwords removed)")
    lines.append("")
    for proposal_id in PROPOSAL_ORDER:
        words = sorted(content_words[proposal_id])
        lines.append(f"- **{proposal_id}**: {', '.join(words)}")
    lines.append("")

    lines.append("## Keyword flags (>= 2 shared distinctive content words)")
    lines.append("")
    _flags_table(lines, keyword_flags)

    lines.append("## Stance flags (LLM-based)")
    lines.append("")
    if stance_flags is None:
        lines.append("Stance checks were not run. Run them with "
                     "`python3 scripts/population_reports.py --stance-check`.")
        lines.append("")
    else:
        _flags_table(lines, stance_flags)

    lines.append("## Regenerated personas")
    lines.append("")
    if not regenerations:
        lines.append("No bios were regenerated. Run "
                     "`python3 scripts/population_reports.py "
                     "--stance-check --regenerate-stance-flagged` to do so.")
        lines.append("")
    else:
        _flags_table(lines, regenerations)

    lines.append("## Summary")
    lines.append("")
    lines.append("| screen | flagged personas |")
    lines.append("|---|---|")
    lines.append(f"| keyword (>= 2 shared words) | {len(keyword_flags)} |")
    if stance_flags is None:
        lines.append("| stance (LLM) | not run |")
    else:
        lines.append(f"| stance (LLM) | {len(stance_flags)} |")
    lines.append(f"| regenerated | {len(regenerations)} |")
    lines.append("")
    return "\n".join(lines) + "\n"


def write_leakage_screen(
    populations: dict[str, dict],
    out_dir: Path,
    *,
    stance_check: bool = False,
    regenerate: bool = False,
) -> dict[str, Any]:
    """Compute the leakage screen, write leakage_screen.md, and return stats.

    ``stance_check`` enables the LLM stance screen (makes LLM calls);
    ``regenerate`` additionally regenerates stance-flagged bios in place.
    """
    content_words = proposal_content_words()
    overlaps = compute_overlaps(populations, content_words)
    keyword_flags = screen_keyword_flags(populations, overlaps)

    stance_flags: list[dict] | None = None
    if stance_check:
        stance_flags = screen_stance_flags(populations, keyword_flags)

    regenerations: list[dict] = []
    if regenerate:
        regenerations = regenerate_stance_flagged(
            populations, stance_flags or [], out_dir
        )

    markdown = build_leakage_screen(
        populations, content_words, keyword_flags, stance_flags, regenerations
    )
    (out_dir / "leakage_screen.md").write_text(markdown, encoding="utf-8")
    return {
        "keyword_flags": len(keyword_flags),
        "stance_flags": None if stance_flags is None else len(stance_flags),
        "regenerations": len(regenerations),
    }
