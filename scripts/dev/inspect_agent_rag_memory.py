import argparse
import json
import os
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from gaworld.settings import CONFIG


def _memory_path(memory_dir, agent_id):
    return os.path.join(memory_dir, f"agent_{agent_id}.json")


def _load_memory_items(memory_dir, agent_id):
    path = _memory_path(memory_dir, agent_id)
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, list):
        return []
    items = []
    for idx, item in enumerate(data):
        text = ""
        if isinstance(item, str):
            text = item.strip()
        elif isinstance(item, dict):
            for key in ("text", "memory", "summary", "content"):
                val = item.get(key)
                if isinstance(val, str) and val.strip():
                    text = val.strip()
                    break
            if not text:
                text = str(item).strip()
        else:
            text = str(item).strip()
        if text:
            items.append({"index": idx, "text": text})
    return items


def _load_rag_entries(vector_db_path, agent_id):
    if not vector_db_path or not os.path.exists(vector_db_path):
        return []
    conn = sqlite3.connect(vector_db_path)
    try:
        rows = conn.execute(
            """
            SELECT id, entry_type, text, sim_day, sim_time, created_at
            FROM memory_entries
            WHERE agent_id = ?
            ORDER BY created_at DESC
            """,
            (int(agent_id),),
        ).fetchall()
    finally:
        conn.close()
    entries = []
    for row in rows:
        entries.append(
            {
                "id": int(row[0]),
                "entry_type": str(row[1]),
                "text": str(row[2] or "").strip(),
                "sim_day": row[3],
                "sim_time": str(row[4] or "").strip(),
                "created_at": float(row[5]) if row[5] is not None else 0.0,
            }
        )
    return entries


def _shorten(text, width=120):
    s = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(s) <= width:
        return s
    return s[: max(0, width - 3)] + "..."


def _render_bar(label, count, max_count, width=30):
    if max_count <= 0:
        filled = 0
    else:
        filled = int(round((count / max_count) * width))
    bar = "#" * filled + "." * (width - filled)
    return f"{label:<16} |{bar}| {count}"


def _guess_memory_tag(text):
    if text.startswith("[额外信息"):
        return "external_info(mem)"
    if text.startswith("[InfoSeek"):
        return "info_seek(mem)"
    if text.startswith("[WebSearch"):
        return "web_search(mem)"
    if text.startswith("[NewsRead"):
        return "news(mem)"
    if text.startswith("[Day"):
        return "daily(mem)"
    return "general(mem)"


def _extract_keywords(text, max_items=6):
    tokens = re.findall(r"[\u4e00-\u9fff]{2,}|[A-Za-z0-9]{3,}", text or "")
    counts = Counter(t.lower() for t in tokens if t.strip())
    return [k for k, _ in counts.most_common(max_items)]


def _format_created_at(ts):
    if not ts:
        return ""
    try:
        return datetime.fromtimestamp(float(ts)).strftime("%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError, OSError):
        return ""


def _render_terminal(agent_id, memory_items, rag_entries, top_n):
    print(f"\n=== Agent {agent_id} RAG/Memory Report ===")
    print(f"memory_items: {len(memory_items)}")
    print(f"rag_entries : {len(rag_entries)}")

    rag_types = Counter(e["entry_type"] for e in rag_entries)
    mem_types = Counter(_guess_memory_tag(m["text"]) for m in memory_items)

    print("\n[Entry Type Distribution]")
    merged = defaultdict(int)
    for k, v in rag_types.items():
        merged[k] += v
    for k, v in mem_types.items():
        merged[k] += v
    if not merged:
        print("no data")
    else:
        max_count = max(merged.values())
        for label, count in sorted(merged.items(), key=lambda x: (-x[1], x[0])):
            print(_render_bar(label, count, max_count))

    print("\n[Top Keywords from recent RAG text]")
    keywords = Counter()
    for e in rag_entries[: max(20, top_n)]:
        keywords.update(_extract_keywords(e["text"], max_items=10))
    if keywords:
        for word, c in keywords.most_common(12):
            print(f"{word:<12} {c}")
    else:
        print("no keywords")

    print(f"\n[Recent RAG Entries Top {top_n}]")
    if not rag_entries:
        print("no rag entries")
    else:
        for i, e in enumerate(rag_entries[:top_n], start=1):
            stamp = _format_created_at(e["created_at"])
            meta = f"type={e['entry_type']} day={e['sim_day']} time={e['sim_time']} created={stamp}"
            print(f"{i:>2}. {meta}")
            print(f"    {_shorten(e['text'], 140)}")

    print(f"\n[Recent Memory Items Top {top_n}]")
    if not memory_items:
        print("no memory items")
    else:
        recent_memory = list(reversed(memory_items[-top_n:]))
        for i, m in enumerate(recent_memory, start=1):
            tag = _guess_memory_tag(m["text"])
            print(f"{i:>2}. idx={m['index']} tag={tag}")
            print(f"    {_shorten(m['text'], 140)}")


def _build_html(agent_id, memory_items, rag_entries, top_n):
    rag_types = Counter(e["entry_type"] for e in rag_entries)
    mem_types = Counter(_guess_memory_tag(m["text"]) for m in memory_items)
    merged = defaultdict(int)
    for k, v in rag_types.items():
        merged[k] += v
    for k, v in mem_types.items():
        merged[k] += v
    max_count = max(merged.values()) if merged else 1

    dist_rows = []
    for label, count in sorted(merged.items(), key=lambda x: (-x[1], x[0])):
        pct = int(round((count / max_count) * 100))
        dist_rows.append(
            "<tr>"
            f"<td>{label}</td>"
            f"<td>{count}</td>"
            f"<td><div class='bar'><span style='width:{pct}%'></span></div></td>"
            "</tr>"
        )

    rag_rows = []
    for e in rag_entries[:top_n]:
        rag_rows.append(
            "<tr>"
            f"<td>{e['entry_type']}</td>"
            f"<td>{e['sim_day']}</td>"
            f"<td>{e['sim_time']}</td>"
            f"<td>{_format_created_at(e['created_at'])}</td>"
            f"<td>{_shorten(e['text'], 220)}</td>"
            "</tr>"
        )

    memory_rows = []
    for m in list(reversed(memory_items[-top_n:])):
        memory_rows.append(
            "<tr>"
            f"<td>{m['index']}</td>"
            f"<td>{_guess_memory_tag(m['text'])}</td>"
            f"<td>{_shorten(m['text'], 220)}</td>"
            "</tr>"
        )

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Agent {agent_id} RAG Report</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; margin: 20px; color: #1f2937; }}
    h1, h2 {{ margin: 8px 0 12px; }}
    .meta {{ color: #4b5563; margin-bottom: 14px; }}
    table {{ width: 100%; border-collapse: collapse; margin-bottom: 18px; }}
    th, td {{ border: 1px solid #e5e7eb; padding: 8px; vertical-align: top; text-align: left; font-size: 13px; }}
    th {{ background: #f9fafb; }}
    .bar {{ width: 240px; height: 10px; background: #e5e7eb; border-radius: 8px; overflow: hidden; }}
    .bar span {{ display: block; height: 100%; background: #3b82f6; }}
  </style>
</head>
<body>
  <h1>Agent {agent_id} RAG / Memory Report</h1>
  <div class="meta">memory_items={len(memory_items)} | rag_entries={len(rag_entries)} | generated_at={datetime.now().strftime("%Y-%m-%d %H:%M:%S")}</div>

  <h2>Entry Type Distribution</h2>
  <table>
    <thead><tr><th>Type</th><th>Count</th><th>Visual</th></tr></thead>
    <tbody>
      {"".join(dist_rows) if dist_rows else "<tr><td colspan='3'>no data</td></tr>"}
    </tbody>
  </table>

  <h2>Recent RAG Entries (Top {top_n})</h2>
  <table>
    <thead><tr><th>type</th><th>sim_day</th><th>sim_time</th><th>created_at</th><th>text</th></tr></thead>
    <tbody>
      {"".join(rag_rows) if rag_rows else "<tr><td colspan='5'>no rag entries</td></tr>"}
    </tbody>
  </table>

  <h2>Recent Memory Items (Top {top_n})</h2>
  <table>
    <thead><tr><th>index</th><th>tag</th><th>text</th></tr></thead>
    <tbody>
      {"".join(memory_rows) if memory_rows else "<tr><td colspan='3'>no memory items</td></tr>"}
    </tbody>
  </table>
</body>
</html>
"""


def main():
    parser = argparse.ArgumentParser(description="Inspect one agent's RAG and memory with simple visualization.")
    parser.add_argument("--agent-id", type=int, required=True, help="Target agent id.")
    parser.add_argument("--top", type=int, default=12, help="How many recent items to show.")
    parser.add_argument("--memory-dir", default=CONFIG.get("memory_dir", "output/memory"), help="Memory directory.")
    parser.add_argument(
        "--vector-db",
        default=CONFIG.get("vector_db_path", os.path.join(CONFIG.get("memory_dir", "output/memory"), "vector_db.sqlite")),
        help="Vector DB sqlite file path.",
    )
    parser.add_argument("--html", default="", help="Optional HTML output file path.")
    args = parser.parse_args()

    memory_items = _load_memory_items(args.memory_dir, args.agent_id)
    rag_entries = _load_rag_entries(args.vector_db, args.agent_id)

    _render_terminal(args.agent_id, memory_items, rag_entries, max(1, int(args.top)))
    if args.html:
        directory = os.path.dirname(args.html)
        if directory:
            os.makedirs(directory, exist_ok=True)
        html = _build_html(args.agent_id, memory_items, rag_entries, max(1, int(args.top)))
        with open(args.html, "w", encoding="utf-8") as f:
            f.write(html)
        print(f"\nhtml_report: {args.html}")


if __name__ == "__main__":
    main()
