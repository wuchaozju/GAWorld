"""Render a run manifest as a single-file HTML report.

The report is deliberately self-contained: no external CSS, no JS
frameworks, no icon fonts. It opens with a double-click, prints
cleanly, and archives well next to the JSON manifest.

Design goals
------------
* Above-the-fold summary: outcome badge, duration, LLM call count,
  sim_days × agents.
* Config diff hint (via curated subset already stored in the manifest).
* LLM stats table (calls / failures / latency by task and provider).
* Environment strip (Python, hostname, git commit + dirty flag).
* Artefacts panel that names the largest per-subdir files, so a
  reviewer can spot missing outputs at a glance.

Everything else is intentionally excluded — the JSON manifest is the
source of truth if the reader wants the fine detail.
"""

from __future__ import annotations

import html
from typing import Any, Mapping


# ---------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------

def _e(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def _human_bytes(size: Any) -> str:
    try:
        n = float(size)
    except (TypeError, ValueError):
        return ""
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{int(n)} {unit}"
        n /= 1024
    return f"{n:.1f} GB"


def _human_duration(seconds: Any) -> str:
    try:
        n = float(seconds)
    except (TypeError, ValueError):
        return ""
    if n < 1:
        return f"{n * 1000:.0f} ms"
    if n < 60:
        return f"{n:.1f} s"
    minutes, s = divmod(n, 60)
    if minutes < 60:
        return f"{int(minutes)}m {int(s)}s"
    hours, minutes = divmod(minutes, 60)
    return f"{int(hours)}h {int(minutes)}m"


def _badge(outcome: str) -> str:
    palette = {
        "ok": ("#0d6b3f", "#e8f5ee"),
        "failed": ("#b32424", "#fce8e8"),
        "in_progress": ("#8a5a0b", "#fff5e0"),
    }
    fg, bg = palette.get(outcome, ("#333", "#eee"))
    return (
        f'<span class="badge" style="color:{fg};background:{bg}">'
        f"{_e(outcome or 'unknown')}</span>"
    )


# ---------------------------------------------------------------------
# Section renderers
# ---------------------------------------------------------------------

def _header(manifest: Mapping[str, Any]) -> str:
    run_line = manifest.get("run", {}) or {}
    llm_line = manifest.get("llm", {}) or {}
    duration = _human_duration(manifest.get("duration_s"))
    call_count = llm_line.get("call_count", 0)
    slug = manifest.get("slug", "")
    return f"""
<header>
  <h1>GAWorld run <span class="slug">{_e(slug)}</span></h1>
  <p class="lede">
    {_badge(str(manifest.get('outcome', 'unknown')))}
    &nbsp; started {_e(manifest.get('started_at', '') or '—')}
    &nbsp; · duration {_e(duration or '—')}
    &nbsp; · sim_days = {_e(run_line.get('sim_days', '—'))}
    &nbsp; · agents = {_e(len(run_line.get('agent_ids', []) or []))}
    &nbsp; · LLM calls = {_e(call_count)}
  </p>
</header>
"""


def _env_strip(manifest: Mapping[str, Any]) -> str:
    env = manifest.get("environment", {}) or {}
    git = manifest.get("git", {}) or {}
    dirty = " (dirty)" if git.get("dirty") else ""
    commit = _e((git.get("commit") or "")[:12])
    branch = _e(git.get("branch") or "")
    return f"""
<section class="strip">
  <div><span class="k">python</span>{_e(env.get('python', ''))}</div>
  <div><span class="k">platform</span>{_e(env.get('platform', ''))}</div>
  <div><span class="k">host</span>{_e(env.get('hostname', ''))}</div>
  <div><span class="k">git</span>{commit}{_e(dirty)}
     &nbsp;<em>{branch}</em></div>
</section>
"""


def _kv_table(title: str, mapping: Mapping[str, Any]) -> str:
    if not mapping:
        return f"<section><h2>{_e(title)}</h2><p class='empty'>—</p></section>"
    rows = "".join(
        f"<tr><th>{_e(k)}</th><td>{_e(v if not isinstance(v, (dict, list)) else _short_json(v))}</td></tr>"
        for k, v in mapping.items()
    )
    return f"""
<section>
  <h2>{_e(title)}</h2>
  <table class="kv"><tbody>{rows}</tbody></table>
</section>
"""


def _short_json(value: Any, limit: int = 120) -> str:
    import json as _json

    try:
        text = _json.dumps(value, ensure_ascii=False, sort_keys=True)
    except (TypeError, ValueError):
        text = str(value)
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _llm_section(manifest: Mapping[str, Any]) -> str:
    llm = manifest.get("llm", {}) or {}
    if not llm:
        return "<section><h2>LLM</h2><p class='empty'>no LLM stats recorded</p></section>"
    by_task = llm.get("by_task", {}) or {}
    by_provider = llm.get("by_provider", {}) or {}

    def _rows(name: str, stats: Mapping[str, Any]) -> str:
        entries = sorted(stats.items(), key=lambda kv: -int(kv[1].get("calls", 0)))
        rows = "".join(
            f"<tr><td>{_e(k)}</td>"
            f"<td class='num'>{_e(v.get('calls', 0))}</td>"
            f"<td class='num'>{_e(v.get('failures', 0))}</td>"
            f"<td class='num'>{_e(round(v.get('total_latency_ms', 0) / max(v.get('calls', 1), 1)))}</td>"
            f"</tr>"
            for k, v in entries
            if isinstance(v, Mapping)
        )
        return f"""
<h3>By {_e(name)}</h3>
<table class="stats">
  <thead><tr><th>{_e(name)}</th><th>calls</th><th>failures</th><th>avg latency ms</th></tr></thead>
  <tbody>{rows or '<tr><td colspan="4" class="empty">—</td></tr>'}</tbody>
</table>
"""

    call_count = _e(llm.get("call_count", 0))
    failure_count = _e(llm.get("failure_count", 0))
    return f"""
<section>
  <h2>LLM</h2>
  <p>Total calls: <strong>{call_count}</strong> · failures: <strong>{failure_count}</strong></p>
  {_rows('task', by_task)}
  {_rows('provider', by_provider)}
</section>
"""


def _artefacts_section(manifest: Mapping[str, Any]) -> str:
    art = manifest.get("artefacts", {}) or {}
    if not art:
        return "<section><h2>Artefacts</h2><p class='empty'>—</p></section>"
    parts = []
    for sub, entries in art.items():
        entries = list(entries or [])
        entries.sort(key=lambda e: -int(e.get("size", 0)))
        top = entries[:8]
        rows = "".join(
            f"<tr><td>{_e(e.get('path', ''))}</td>"
            f"<td class='num'>{_e(_human_bytes(e.get('size')))}</td></tr>"
            for e in top
        )
        if not rows:
            rows = "<tr><td colspan='2' class='empty'>—</td></tr>"
        parts.append(
            f"""<h3>{_e(sub)} <span class='muted'>({len(entries)} files)</span></h3>
<table class='files'>
  <thead><tr><th>path</th><th>size</th></tr></thead>
  <tbody>{rows}</tbody>
</table>"""
        )
    return "<section><h2>Artefacts</h2>" + "\n".join(parts) + "</section>"


def _config_section(manifest: Mapping[str, Any]) -> str:
    cfg = manifest.get("config", {}) or {}
    if not cfg:
        return ""
    scalars = {k: v for k, v in cfg.items() if not isinstance(v, (dict, list))}
    blocks = {k: v for k, v in cfg.items() if isinstance(v, dict)}
    scalar_html = _kv_table("Config (scalars)", scalars) if scalars else ""
    block_parts = []
    for name, block in blocks.items():
        block_parts.append(_kv_table(f"Config · {name}", block))
    return scalar_html + "\n".join(block_parts)


def _events_section(manifest: Mapping[str, Any]) -> str:
    events = manifest.get("events", []) or []
    if not events:
        return ""
    # Show the last 30 events — enough to eyeball day boundaries.
    rows = "".join(
        f"<tr><td class='muted'>{_e(e.get('ts', ''))}</td>"
        f"<td>{_e(e.get('kind', ''))}</td>"
        f"<td>{_e(_short_json(e.get('payload', {})))}</td></tr>"
        for e in events[-30:]
    )
    return f"""
<section>
  <h2>Recent events</h2>
  <table class='events'>
    <thead><tr><th>timestamp</th><th>kind</th><th>payload</th></tr></thead>
    <tbody>{rows}</tbody>
  </table>
</section>
"""


def _notes_section(manifest: Mapping[str, Any]) -> str:
    notes = manifest.get("notes", []) or []
    if not notes:
        return ""
    items = "".join(f"<li>{_e(n)}</li>" for n in notes)
    return f"<section><h2>Notes</h2><ul>{items}</ul></section>"


# ---------------------------------------------------------------------
# Top-level renderer
# ---------------------------------------------------------------------

_STYLE = """
* { box-sizing: border-box; }
body { font: 14px/1.5 -apple-system, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
       color: #222; margin: 0; padding: 32px; background: #fafafa; }
header h1 { margin: 0 0 8px 0; font-size: 22px; }
header .slug { color: #888; font-weight: normal; }
.lede { color: #555; margin: 0 0 24px 0; }
.badge { display:inline-block; padding: 2px 8px; border-radius: 4px;
         font-weight: 600; font-size: 12px; letter-spacing: 0.02em; }
section { background: white; border: 1px solid #e6e6e6; border-radius: 6px;
          padding: 20px 24px; margin: 0 0 20px 0; }
section h2 { margin: 0 0 12px 0; font-size: 16px; color: #113; }
section h3 { margin: 16px 0 6px 0; font-size: 13px; color: #333; text-transform: uppercase;
             letter-spacing: 0.04em; }
.strip { display: flex; flex-wrap: wrap; gap: 24px; padding: 12px 24px; }
.strip .k { display:inline-block; color:#888; margin-right:8px; text-transform:uppercase;
            font-size: 11px; letter-spacing: 0.04em; }
.strip em { color:#888; font-style: normal; }
table { border-collapse: collapse; width: 100%; }
th, td { text-align: left; padding: 6px 10px; border-bottom: 1px solid #eee; vertical-align: top; }
th { color: #666; font-weight: 500; font-size: 12px; text-transform: uppercase; letter-spacing: 0.03em; }
table.kv th { width: 30%; color: #444; font-weight: 600; text-transform: none; letter-spacing: 0; }
table.stats td.num, table.files td.num { text-align: right; font-variant-numeric: tabular-nums; }
.empty { color: #aaa; }
.muted { color: #888; font-size: 12px; }
footer { color: #999; font-size: 11px; margin-top: 16px; }
"""


def render_report(manifest: Mapping[str, Any]) -> str:
    """Return the full HTML report as a string."""
    body = "\n".join(
        [
            _header(manifest),
            _env_strip(manifest),
            _llm_section(manifest),
            _artefacts_section(manifest),
            _config_section(manifest),
            _events_section(manifest),
            _notes_section(manifest),
        ]
    )
    footer = (
        "<footer>generated by gaworld.core.run_report · schema "
        f"{_e(manifest.get('schema_version'))} · run_id "
        f"{_e(manifest.get('run_id', ''))}</footer>"
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>GAWorld run {_e(manifest.get('slug', ''))}</title>
  <style>{_STYLE}</style>
</head>
<body>
{body}
{footer}
</body>
</html>
"""


__all__ = ["render_report"]
