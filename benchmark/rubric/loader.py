"""Read GAWorld ``output/`` artifacts into plain dicts.

Stdlib only, mirroring benchmark/gaworld_bench.py. Every loader degrades to an
empty result when the artifact is missing -- absent data must surface as
``abstain`` downstream, never as a low score.
"""

import csv
import json
import re
from pathlib import Path

_AGENT_RE = re.compile(r"agent_(\d+)")


def _agent_id(path: Path) -> int | None:
    m = _AGENT_RE.search(path.name)
    return int(m.group(1)) if m else None


def _time_key(ep: dict) -> tuple:
    t = str(ep.get("time") or "")
    parts = t.split(":")
    try:
        return (int(ep.get("day") or 0), int(parts[0]), int(parts[1]))
    except (ValueError, IndexError):
        return (int(ep.get("day") or 0), 0, 0)


def load_episodes(output_dir: Path) -> dict[int, list[dict]]:
    """agent_id -> episodes sorted by (day, time)."""
    out: dict[int, list[dict]] = {}
    mem = Path(output_dir) / "memory"
    if not mem.is_dir():
        return out
    for path in sorted(mem.glob("agent_*_episodes.jsonl")):
        aid = _agent_id(path)
        if aid is None:
            continue
        eps = []
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                eps.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        if eps:
            out[aid] = sorted(eps, key=_time_key)
    return out


def load_growth(output_dir: Path) -> dict[int, dict]:
    out: dict[int, dict] = {}
    mem = Path(output_dir) / "memory"
    if not mem.is_dir():
        return out
    for path in sorted(mem.glob("agent_*_growth.json")):
        aid = _agent_id(path)
        if aid is None:
            continue
        try:
            out[aid] = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
    return out


def load_diaries(output_dir: Path) -> dict[int, dict[int, str]]:
    """agent_id -> {day: markdown}."""
    out: dict[int, dict[int, str]] = {}
    root = Path(output_dir) / "diaries"
    if not root.is_dir():
        return out
    for adir in sorted(root.iterdir()):
        aid = _agent_id(adir)
        if aid is None or not adir.is_dir():
            continue
        days: dict[int, str] = {}
        for f in sorted(adir.glob("day_*.md")):
            m = re.search(r"day_(\d+)", f.name)
            if m:
                days[int(m.group(1))] = f.read_text(encoding="utf-8")
        if days:
            out[aid] = days
    return out


def load_state_series(output_dir: Path) -> dict[int, dict[str, list[tuple[int, float]]]]:
    """agent_id -> metric -> [(step, value)], from the long-format history CSV."""
    out: dict[int, dict[str, list[tuple[int, float]]]] = {}
    path = Path(output_dir) / "state" / "agent_state_history.csv"
    if not path.is_file():
        return out
    with path.open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            try:
                aid = int(row["agent_id"])
                step = int(row["step"])
                val = float(row["value"])
            except (KeyError, TypeError, ValueError):
                continue
            out.setdefault(aid, {}).setdefault(row.get("metric", ""), []).append((step, val))
    for metrics in out.values():
        for series in metrics.values():
            series.sort()
    return out


def load_ledger(output_dir: Path) -> dict[tuple[int, int], dict]:
    """(day, agent_id) -> ledger row (numeric fields coerced to float)."""
    out: dict[tuple[int, int], dict] = {}
    path = Path(output_dir) / "economy" / "daily_ledger.csv"
    if not path.is_file():
        return out
    with path.open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            try:
                key = (int(row["day"]), int(row["agent_id"]))
            except (KeyError, TypeError, ValueError):
                continue
            parsed = {}
            for k, v in row.items():
                try:
                    parsed[k] = float(v)
                except (TypeError, ValueError):
                    parsed[k] = v
            out[key] = parsed
    return out


def load_conservation(output_dir: Path) -> dict[int, float]:
    """day -> drift."""
    out: dict[int, float] = {}
    path = Path(output_dir) / "economy" / "conservation_audit.csv"
    if not path.is_file():
        return out
    with path.open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            try:
                out[int(row["day"])] = float(row["drift"])
            except (KeyError, TypeError, ValueError):
                continue
    return out


def load_profiles(output_dir: Path) -> dict[int, str]:
    """agent_id -> profile text.

    Assumption: ``## Profile NN｜name`` sections are 1-indexed and NN maps to
    agent_id NN. Only feeds R1.3 (an LLM item); a wrong mapping shows up as a
    low R1.3 with mismatched evidence rather than a silent error, and a missing
    profile abstains.
    """
    out: dict[int, str] = {}
    root = Path(output_dir) / "population"
    if not root.is_dir():
        return out
    files = sorted(root.glob("*_profiles.md"))
    if not files:
        return out
    text = files[0].read_text(encoding="utf-8")
    chunks = re.split(r"^##\s*Profile\s*(\d+)", text, flags=re.MULTILINE)
    for i in range(1, len(chunks) - 1, 2):
        try:
            out[int(chunks[i])] = chunks[i + 1].strip()
        except ValueError:
            continue
    return out


def detect_run_mode(output_dir: Path) -> str:
    """``fast_forward`` | ``full`` | ``unknown``.

    Fast-forward steps log a ``[FastForward <Day|Month|Year> N]`` block instead
    of a per-tick trace, so the logs are the cheapest reliable marker. This
    matters because a fast-forward run writes no episodes and its diaries come
    from the deterministic fallback -- both change which rubric items are
    answerable. The marker prefix is unit-agnostic on purpose: a month/year
    run is fast-forward too, just coarser.
    """
    logs = Path(output_dir) / "logs"
    if not logs.is_dir():
        return "unknown"
    for path in sorted(logs.glob("*.log")):
        try:
            head = path.read_text(encoding="utf-8", errors="ignore")[:200_000]
        except OSError:
            continue
        if "[FastForward " in head:
            return "fast_forward"
        if "=== Day " in head or "===== Day" in head:
            return "full"
    return "unknown"


def capabilities(data: dict) -> dict[str, bool]:
    """Which data capabilities this run actually provides.

    Consumed by the runner to abstain on items whose inputs are missing,
    instead of scoring them 0 -- a missing artifact is not a modelling failure.
    """
    episodes = data.get("episodes") or {}
    has_social = any(
        _partner_list(ep.get("social_partners")) and ep.get("social_partners")
        for eps in episodes.values() for ep in eps
    )
    return {
        "episodes": bool(episodes),
        "series": bool(data.get("series")),
        "growth": bool(data.get("growth")),
        "ledger": bool(data.get("ledger")),
        "profiles": bool(data.get("profiles")),
        "daily_narrative": bool(data.get("diaries")),
        # Fast-forward diaries come from _fallback_daily_diary, i.e. a fixed
        # template -- judging "non-templated narrative" on them measures the
        # fallback, not the model.
        "authored_diary": bool(data.get("diaries")) and data.get("run_mode") != "fast_forward",
        "social_graph": has_social,
    }


def _partner_list(raw) -> bool:
    return bool(raw) and isinstance(raw, (list, tuple))


def load_all(output_dir: Path) -> dict:
    output_dir = Path(output_dir)
    data = {
        "output_dir": str(output_dir),
        "run_mode": detect_run_mode(output_dir),
        "episodes": load_episodes(output_dir),
        "growth": load_growth(output_dir),
        "diaries": load_diaries(output_dir),
        "series": load_state_series(output_dir),
        "ledger": load_ledger(output_dir),
        "conservation": load_conservation(output_dir),
        "profiles": load_profiles(output_dir),
    }
    data["capabilities"] = capabilities(data)
    return data
