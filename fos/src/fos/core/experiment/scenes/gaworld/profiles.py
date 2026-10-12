"""This file defines GAWorld agent profile data and helper functions.
Each function does one simple job:
- GAWorldAgentProfile stores one agent's profile values.
- _float_from_row reads one decimal value from a CSV row.
- _profile_from_csv_row turns one CSV row into a profile object.
- _profile_summary turns one profile into readable card text.
- _default_profiles_path finds the bundled JSON or local GAWorld CSV data.
- load_profiles reads a JSON file and turns rows into profile objects.
- profiles_to_fos_agents turns profile objects into FOS agent dictionaries.
- export_profiles_csv writes selected profile fields to a CSV file.

hangzhou_50.json was converted from GAWorld source data on 2026-05-25. Re-run conversion if GAWorld agent data is updated upstream.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import csv
import json
import os
from pathlib import Path
from typing import Iterable


@dataclass(slots=True)
class GAWorldAgentProfile:
    """Stores one GAWorld agent profile with demographic, behavior, and state fields."""

    id: str
    name: str
    gender: str
    age: int
    hukou: str
    residence: str
    occupation: str
    income: str
    education: str
    personality_traits: str
    daily_routine: str
    social_network: str
    values: str
    policy_sensitivity: float
    platform_dependence: float
    risk_preference: float
    voice_propensity: float
    mobility_intent: float
    emotion: float
    stress: float
    econ_security: float
    city_identity: float


def _float_from_row(row: dict[str, str], field_name: str) -> float:
    """Reads one decimal number from a CSV row."""

    return float(row.get(field_name, 0.0) or 0.0)


def _profile_from_csv_row(row: dict[str, str]) -> GAWorldAgentProfile:
    """Turns one GAWorld CSV row into a profile object."""

    residence = row.get("residence", "")
    return GAWorldAgentProfile(
        id=str(row.get("id", "")).strip(),
        name=str(row.get("name", "")).strip(),
        gender=str(row.get("gender", "")).strip(),
        age=int(row.get("age", 0) or 0),
        hukou=str(row.get("hukou", "")).strip(),
        residence=residence,
        occupation="",
        income="",
        education="",
        personality_traits="",
        daily_routine=f"Lives in {residence}." if residence else "",
        social_network="",
        values="",
        policy_sensitivity=_float_from_row(row, "policy_sensitivity"),
        platform_dependence=_float_from_row(row, "platform_dependence"),
        risk_preference=_float_from_row(row, "risk_preference"),
        voice_propensity=_float_from_row(row, "voice_propensity"),
        mobility_intent=_float_from_row(row, "mobility_intent"),
        emotion=_float_from_row(row, "emotion"),
        stress=_float_from_row(row, "stress"),
        econ_security=_float_from_row(row, "econ_security"),
        city_identity=_float_from_row(row, "city_identity"),
    )


def _profile_summary(profile: GAWorldAgentProfile) -> str:
    """Turns one profile into readable card text."""

    return "\n".join(
        [
            f"Gender: {profile.gender}",
            f"Age: {profile.age}",
            f"Hukou: {profile.hukou}",
            f"Residence: {profile.residence}",
            f"Occupation: {profile.occupation}",
            f"Income: {profile.income}",
            f"Education: {profile.education}",
            f"Emotion: {profile.emotion}",
            f"Stress: {profile.stress}",
            f"Economic security: {profile.econ_security}",
            f"City identity: {profile.city_identity}",
        ]
    )


def _default_profiles_path() -> Path:
    """Finds the bundled profile JSON, or local GAWorld CSV data."""

    json_path = Path(__file__).with_name("profiles").joinpath("hangzhou_50.json")
    if json_path.exists():
        return json_path

    gaworld_path = os.environ.get("GAWORLD_PATH", "").strip()
    if gaworld_path:
        csv_path = Path(gaworld_path) / "data" / "hangzhou_agents_state_init.csv"
        if csv_path.exists():
            return csv_path
    return json_path


def load_profiles(path: Path | None = None) -> list[GAWorldAgentProfile]:
    """Reads profile JSON and returns profile objects, or an empty list when missing."""

    source_path = path or _default_profiles_path()
    if not source_path.exists():
        return []

    if source_path.suffix.lower() == ".csv":
        with source_path.open("r", encoding="utf-8-sig", newline="") as file_obj:
            return [_profile_from_csv_row(row) for row in csv.DictReader(file_obj)]

    with source_path.open("r", encoding="utf-8") as file_obj:
        rows = json.load(file_obj)

    return [GAWorldAgentProfile(**row) for row in rows]


def profiles_to_fos_agents(
    profiles: Iterable[GAWorldAgentProfile],
    agent_ids: list[str] | None = None,
) -> list[dict[str, object]]:
    """Converts GAWorld profiles into basic FOS agent dictionaries."""

    generated_agents: list[dict[str, object]] = []
    selected_ids = set(agent_ids) if agent_ids else None

    for profile in profiles:
        if selected_ids and profile.id not in selected_ids:
            continue

        role_prompt = (
            f"Personality: {profile.personality_traits}. "
            f"Daily routine: {profile.daily_routine}. "
            f"Social network: {profile.social_network}. "
            f"Values: {profile.values}."
        )
        profile_data = asdict(profile)
        profile_properties = dict(profile_data)
        profile_properties.pop("id", None)
        profile_properties.pop("name", None)
        profile_text = _profile_summary(profile)
        profile_properties["profile"] = profile_text

        generated_agents.append(
            {
                "id": profile.id,
                "name": profile.name,
                "profile": profile_text,
                "properties": profile_properties,
                "role_prompt": role_prompt,
                # GAWorld controls its own LLM selection; FOS-side config stays empty.
                "llm_config": {},
            }
        )

    return generated_agents


def export_profiles_csv(profiles: Iterable[GAWorldAgentProfile], output_path: Path) -> None:
    """Writes selected profile fields to a CSV file."""

    fieldnames = [
        "id",
        "name",
        "gender",
        "age",
        "hukou",
        "residence",
        "emotion",
        "stress",
        "econ_security",
        "city_identity",
        "policy_sensitivity",
        "platform_dependence",
        "risk_preference",
        "voice_propensity",
        "mobility_intent",
    ]
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as file_obj:
        writer = csv.DictWriter(file_obj, fieldnames=fieldnames)
        writer.writeheader()
        for profile in profiles:
            row = asdict(profile)
            writer.writerow({name: row[name] for name in fieldnames})
