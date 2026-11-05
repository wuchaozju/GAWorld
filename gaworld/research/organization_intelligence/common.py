"""Shared pieces of the organization-intelligence feature.

The comparison workbench, the historical studies and the model-free team
simulation all need the same three things: who the residents are, what a
model provider looks like, and how a frozen model is called. They used to
live in the API module of the older implementation, which made every other
module depend on a module called "legacy". They live here instead.
"""

from __future__ import annotations

import copy
import csv
import re
from pathlib import Path

from gaworld.accounts import usage
from gaworld.apps import research_api, world_paths
from gaworld.collaboration.organization_methods import digest

#: Provider settings that are hashed into a study's fingerprint. Credentials
#: and headers are never part of it.
_SAFE_PROVIDER_KEYS = {
    "type",
    "model",
    "base_url",
    "url",
    "temperature",
    "top_p",
    "top_k",
    "seed",
    "max_tokens",
    "num_ctx",
    "think",
    "thinking",
    "reasoning_effort",
    "system",
    "stream",
    "timeout",
}

_PROFILE_FIELDS = (
    "**基础信息**",
    "**职业与工作节奏**",
    "**性格与情绪特征**",
    "**人格与行为倾向**",
    "**价值观与公共事务态度**",
)


def _big5_by_id():
    """The Big Five table of the active world, keyed by resident id."""
    path = Path(world_paths.big5_csv_path())
    if not path.exists():
        return {}
    values = {}
    try:
        with path.open(encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                try:
                    identifier = int(row.get("id") or "")
                except ValueError:
                    continue
                traits = {}
                for key, label in (
                    ("o", "开放性"),
                    ("c", "尽责性"),
                    ("e", "外向性"),
                    ("a", "宜人性"),
                    ("n", "神经质"),
                ):
                    try:
                        traits[label] = round(float(row.get(key)), 3)
                    except (TypeError, ValueError):
                        continue
                if traits:
                    values[identifier] = traits
    except OSError:
        return {}
    return values


def _profile_excerpts():
    """Each resident's own paragraph, so a member is more than a name.

    Only the sentences that describe how the person behaves are kept; the
    long research tables in the same file are not part of a resident.
    """
    path = Path(world_paths.profile_path())
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return {}
    excerpts = {}
    matches = list(re.compile(r"^##\s*Profile\s*(\d+)\s*[｜|]", re.MULTILINE).finditer(text))
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        block = text[match.end() : end]
        parts = []
        for label in _PROFILE_FIELDS:
            found = re.search(re.escape(label) + r"\s*[:：]\s*(.+)", block)
            if found:
                parts.append(found.group(1).strip())
        if parts:
            excerpts[int(match.group(1))] = "；".join(parts)[:600]
    return excerpts


def population():
    """The residents of the active world, with the traits a member is chosen by."""
    from gaworld.interview.roster import _jobs_by_id

    jobs = _jobs_by_id(Path(world_paths.profile_path()))
    big5 = _big5_by_id()
    excerpts = _profile_excerpts()
    people = []
    with open(world_paths.state_csv_path(), encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            try:
                identifier = int(row.get("id") or row.get("agent_id") or "")
                age = int(float(row.get("age") or 0))
            except ValueError:
                continue
            people.append(
                {
                    "id": identifier,
                    "name": row.get("name", ""),
                    "age": age,
                    "gender": row.get("gender", ""),
                    "job": jobs.get(identifier, "")[:500],
                    "big5": big5.get(identifier, {}),
                    "profile": excerpts.get(identifier, ""),
                }
            )
    return people


def model_info(name=""):
    """The provider settings a study freezes. Credentials stay out of it."""
    config = research_api._base_config()
    llm = config.get("llm") or {}
    name = name or (llm.get("routing") or {}).get("default", "")
    settings = (llm.get("providers") or {}).get(name)
    if not isinstance(settings, dict) or not settings.get("model"):
        raise ValueError("选择的模型不存在或未配置；不会自动切换模型")
    safe = {k: v for k, v in settings.items() if k in _SAFE_PROVIDER_KEYS}
    return {
        "name": name,
        "type": settings.get("type"),
        "model": settings["model"],
        "fingerprint": digest(safe),
    }


def make_caller(spec):
    """Call the model a study froze, counted against the asking user's quota."""
    from gaworld.llm.providers import LLMRouter

    name = spec["model"]["name"]
    if model_info(name) != spec["model"]:
        raise ValueError("模型配置与冻结协议不同，请创建新研究")
    settings = copy.deepcopy(research_api._base_config()["llm"]["providers"][name])
    settings["authorization_retry_schemes"] = []
    router = LLMRouter({"llm": {"providers": {name: settings}, "routing": {"default": name}}})
    router.providers[name].attempts = 1

    def call(prompt, agent_id=None):
        try:
            return router.call(
                prompt,
                task="research.organization_intelligence",
                provider=name,
                allow_fallback=False,
                temperature=spec["temperature"],
                max_tokens=spec["max_tokens"],
                agent_id=agent_id,
            )
        finally:
            usage.record("research.organization_intelligence")

    return call
