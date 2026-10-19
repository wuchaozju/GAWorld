"""Online skill market — find a skill on skills.sh and keep a local copy.

Opt-in (``skills.online.enabled``, default off): a run that uses it
depends on the network and on what the market lists that day.

Flow for one query:

1. ``GET {api_base}/api/search?q=…`` → ranked entries (``source`` =
   ``owner/repo``, ``skillId``, ``installs``); the answer is cached per
   query in ``{cache_dir}/_search_cache.json`` so a rerun asks no more.
2. Entries below ``min_installs`` are dropped.
3. The entry's ``SKILL.md`` is read from raw.githubusercontent.com: the
   usual layouts first, else the path is looked up in the repo's file
   tree (GitHub API, 60 unauthenticated calls an hour). It is capped in
   size and stored as ``{cache_dir}/<owner>__<repo>__<skill>/SKILL.md``;
   the registry scans that directory, so later work finds it offline.
4. A skill whose name/description shares fewer than two of the query's
   words (all of them, for a shorter query) is discarded — the market's
   semantic search also returns merely popular neighbours.

Only the Markdown text is ever fetched. Scripts or files a skill refers
to are not downloaded, and nothing is executed: the text is guidance
pasted into a work brief, nothing more.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
from collections.abc import Callable, Sequence
from typing import Any
from urllib.parse import quote

from gaworld.logging_setup import get_logger
from gaworld.skills.schemas import Skill, parse_skill_markdown

_LOG = get_logger("gaworld.skills.market")

# (url, timeout) -> (status, text)
HttpGet = Callable[[str, float], tuple[int, str]]

_MAX_RESPONSE_BYTES = 4 * 1024 * 1024  # a big repo's file tree
_MAX_SKILL_CHARS = 64 * 1024
_SAFE_PART = re.compile(r"^[A-Za-z0-9_.-]+$")
_RAW_BASE = "https://raw.githubusercontent.com"
_TREE_API = "https://api.github.com/repos/{owner}/{repo}/git/trees/HEAD?recursive=1"


def _requests_get(url: str, timeout: float) -> tuple[int, str]:
    import requests

    with requests.get(url, timeout=timeout, stream=True) as resp:
        body = resp.raw.read(_MAX_RESPONSE_BYTES, decode_content=True) or b""
        return resp.status_code, body.decode("utf-8", errors="replace")


def _safe(part: str) -> bool:
    return bool(_SAFE_PART.match(part)) and part not in (".", "..")


def _query_words(query: str) -> list[str]:
    return [w for w in re.findall(r"[a-z0-9]+", query.lower()) if len(w) >= 3]


class SkillMarket:
    """Search the market, download SKILL.md files, remember both."""

    def __init__(
        self,
        cache_dir: str,
        *,
        api_base: str = "https://skills.sh",
        min_installs: int = 100,
        timeout: float = 10.0,
        http_get: HttpGet | None = None,
    ) -> None:
        self.cache_dir = cache_dir
        self.api_base = api_base.rstrip("/")
        self.min_installs = int(min_installs)
        self.timeout = float(timeout)
        self._get = http_get or _requests_get
        self._lock = threading.Lock()
        self._searches: dict[str, list[dict[str, Any]]] | None = None

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------
    def _search_cache_path(self) -> str:
        return os.path.join(self.cache_dir, "_search_cache.json")

    def _load_searches(self) -> dict[str, list[dict[str, Any]]]:
        if self._searches is None:
            try:
                with open(self._search_cache_path(), encoding="utf-8") as f:
                    data = json.load(f)
                self._searches = data if isinstance(data, dict) else {}
            except (OSError, ValueError):
                self._searches = {}
        return self._searches

    def search(self, query: str, *, limit: int = 10) -> list[dict[str, Any]]:
        """Market entries for ``query`` (cached), unfiltered."""
        key = query.strip().lower()
        if not key:
            return []
        with self._lock:
            cached = self._load_searches().get(key)
        if cached is not None:
            return cached
        url = f"{self.api_base}/api/search?q={quote(key)}&limit={int(limit)}"
        status, text = self._get(url, self.timeout)
        if status != 200:
            _LOG.warning("skill market search %r answered %s", key, status)
            return []
        try:
            entries = [e for e in (json.loads(text).get("skills") or []) if isinstance(e, dict)]
        except (ValueError, AttributeError):
            return []
        with self._lock:
            searches = self._load_searches()
            searches[key] = entries
            os.makedirs(self.cache_dir, exist_ok=True)
            with open(self._search_cache_path(), "w", encoding="utf-8") as f:
                json.dump(searches, f, ensure_ascii=False, indent=1)
        return entries

    # ------------------------------------------------------------------
    # Fetch
    # ------------------------------------------------------------------
    @staticmethod
    def skill_id_for(entry: dict[str, Any]) -> str | None:
        """Local id for a market entry, or None when the entry looks unsafe."""
        source = str(entry.get("source") or "")
        name = str(entry.get("skillId") or "")
        owner, _, repo = source.partition("/")
        if not (_safe(owner) and _safe(repo) and _safe(name)):
            return None
        return f"{owner}__{repo}__{name}"

    def fetch(self, entry: dict[str, Any]) -> Skill | None:
        """The entry's skill, from the local copy or downloaded once."""
        skill_id = self.skill_id_for(entry)
        if skill_id is None:
            return None
        folder = os.path.join(self.cache_dir, skill_id)
        path = os.path.join(folder, "SKILL.md")
        if os.path.isfile(path):
            with open(path, encoding="utf-8") as f:
                return self._parse(skill_id, f.read())

        owner, _, repo = str(entry["source"]).partition("/")
        name = str(entry["skillId"])
        try:
            found = self._download(owner, repo, name)
        except Exception as exc:  # network trouble = no skill
            _LOG.warning("skill download failed %s/%s %s: %s", owner, repo, name, exc)
            return None
        if found is None:
            return None
        url, text = found
        text = text[:_MAX_SKILL_CHARS]
        os.makedirs(folder, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        with open(os.path.join(folder, "source.json"), "w", encoding="utf-8") as f:
            json.dump(
                {"url": url, "installs": entry.get("installs"), "fetched_at": time.time()},
                f,
                ensure_ascii=False,
            )
        return self._parse(skill_id, text)

    def _download(self, owner: str, repo: str, name: str) -> tuple[str, str] | None:
        """``(url, text)`` of the skill's SKILL.md on the default branch."""
        layouts = [f"skills/{name}/SKILL.md", f"{name}/SKILL.md"]
        if name == repo:
            layouts.append("SKILL.md")
        for layout in layouts:
            url = f"{_RAW_BASE}/{owner}/{repo}/HEAD/{layout}"
            status, text = self._get(url, self.timeout)
            if status == 200 and text.strip():
                return url, text
        # Unusual layout (plugins/…, guides/<topic>/…): ask the repo's tree.
        status, text = self._get(_TREE_API.format(owner=owner, repo=repo), self.timeout)
        if status != 200:
            return None
        try:
            tree = json.loads(text).get("tree") or []
        except (ValueError, AttributeError):
            return None
        suffix = f"{name}/SKILL.md"
        paths = sorted(
            (str(item.get("path") or "") for item in tree if isinstance(item, dict)),
            key=len,
        )
        for candidate in paths:
            if candidate == suffix or candidate.endswith(f"/{suffix}"):
                if any(not _safe(part) for part in candidate.split("/")):
                    return None
                url = f"{_RAW_BASE}/{owner}/{repo}/HEAD/{candidate}"
                status, text = self._get(url, self.timeout)
                return (url, text) if status == 200 and text.strip() else None
        return None

    @staticmethod
    def _parse(skill_id: str, text: str) -> Skill:
        skill = parse_skill_markdown(skill_id, text)
        # A folded YAML description (``description: >-``) is not read by
        # the flat parser; fall back to the first paragraph of the body.
        if not skill.description or skill.description[:1] in (">", "|"):
            paragraphs = [p.strip() for p in skill.body.split("\n\n") if p.strip()]
            prose = [p for p in paragraphs if not p.startswith("#")]
            skill.description = (prose[0] if prose else "")[:200]
        skill.origin = "market"
        return skill

    # ------------------------------------------------------------------
    def find(self, query: str, *, limit: int = 2, exclude_ids: Sequence[str] = ()) -> list[Skill]:
        """Up to ``limit`` relevant, popular-enough skills for ``query``."""
        words = _query_words(query)
        need = min(2, len(words))
        out: list[Skill] = []
        for entry in self.search(query):
            if len(out) >= limit:
                break
            if int(entry.get("installs") or 0) < self.min_installs:
                continue
            skill_id = self.skill_id_for(entry)
            if skill_id is None or skill_id in exclude_ids:
                continue
            skill = self.fetch(entry)
            if skill is None:
                continue
            surface = f"{skill.name} {skill.description}".lower()
            if sum(w in surface for w in words) < need:
                continue
            if any(s.name == skill.name for s in out):  # a fork of one already picked
                continue
            out.append(skill)
        return out


__all__ = ["HttpGet", "SkillMarket"]
