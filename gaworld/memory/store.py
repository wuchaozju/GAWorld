import atexit
import json
import math
import os
import re
import sqlite3
import threading
import time
import zlib
from collections import OrderedDict, deque

import numpy as np

from gaworld.settings import CONFIG
from gaworld.logging_setup import get_logger

_LOG = get_logger("gaworld.memory.store")

# Paths and parameters for memory/logs + vector store.
MEMORY_DIR = CONFIG["memory_dir"]
LOG_DIR = CONFIG["log_dir"]
VECTOR_DB_PATH = CONFIG.get("vector_db_path", os.path.join(MEMORY_DIR, "vector_db.sqlite"))
VECTOR_DB_DIM = int(CONFIG.get("vector_db_dim", 256))
VECTOR_DB_TOP_K = int(CONFIG.get("vector_db_top_k", 3))
VECTOR_DB_MAX_CHARS = int(CONFIG.get("vector_db_max_chars", 2000))
LOG_CACHE_MAX_BLOCKS = int(CONFIG.get("log_cache_max_blocks", 24))
LOG_CACHE_MAX_ACTIONS = int(CONFIG.get("log_cache_max_actions", 32))

#: One sqlite connection **per thread**, not one shared connection.
#:
#: The main loop runs its per-agent stages through
#: ``gaworld.core.runner.parallel_map`` when ``CONFIG["concurrency"]`` is on,
#: and daily-routine generation recalls memories, so this module is entered
#: from worker threads. A single shared connection fails there twice over: it
#: raises ``ProgrammingError`` (thread-bound) without ``check_same_thread``,
#: and ``InterfaceError: bad parameter or other API misuse`` with it, because
#: concurrent statements trample one connection's cursor state. Per-thread
#: connections also make ``with conn:`` mean what it reads like — it commits
#: that thread's transaction and nobody else's. WAL is what lets them share
#: the file. (Congestion proposal §16.7.)
_VECTOR_DB_LOCAL = threading.local()
#: Every connection handed out, so teardown can close them all.
_VECTOR_DB_CONNS: list = []
_VECTOR_DB_CONNS_LOCK = threading.Lock()
_VECTOR_DB_READY = False
_LOG_CACHE = {}


# =========================================================
# File-backed memory & log helpers
# =========================================================

def _memory_path(agent_id):
    return os.path.join(MEMORY_DIR, f"agent_{agent_id}.json")


def _schedule_path(agent_id):
    return os.path.join(MEMORY_DIR, f"agent_{agent_id}_schedule.json")


def _actions_path(agent_id):
    return os.path.join(MEMORY_DIR, f"agent_{agent_id}_actions.json")


def _location_path(agent_id):
    return os.path.join(MEMORY_DIR, f"agent_{agent_id}_locations.json")


def _location_action_bias_path(agent_id):
    return os.path.join(MEMORY_DIR, f"agent_{agent_id}_location_action_bias.json")


def _log_path(agent_id):
    return os.path.join(LOG_DIR, f"agent_{agent_id}.log")


def _sim_state_path():
    return os.path.join(MEMORY_DIR, "sim_state.json")


def _new_log_cache_entry():
    return {
        "blocks": deque(maxlen=max(2, LOG_CACHE_MAX_BLOCKS)),
        "current_block": [],
        "actions": deque(maxlen=max(6, LOG_CACHE_MAX_ACTIONS)),
    }


def _finalize_log_block(entry):
    block = "\n".join(entry.get("current_block", [])).strip()
    entry["current_block"] = []
    if block:
        entry["blocks"].append(block)


def _ingest_log_line(entry, line):
    clean_line = line.rstrip("\n")
    if clean_line.startswith("[") and entry["current_block"]:
        _finalize_log_block(entry)
    if clean_line or entry["current_block"]:
        entry["current_block"].append(clean_line)
    if clean_line.startswith("Action:"):
        action = clean_line.split("Action:", 1)[-1].strip()
        if action:
            entry["actions"].append(action)


def _warm_log_cache(agent_id):
    cache_key = int(agent_id)
    if cache_key in _LOG_CACHE:
        return _LOG_CACHE[cache_key]
    entry = _new_log_cache_entry()
    path = _log_path(cache_key)
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                for raw in f:
                    _ingest_log_line(entry, raw)
        except OSError as exc:
            # Best-effort: fall back to whatever lines were already ingested.
            # Don't crash, but leave a breadcrumb when log files are unreadable.
            _LOG.debug("log cache warm failed for agent %s: %s", cache_key, exc)
    _LOG_CACHE[cache_key] = entry
    return entry


def _append_text_to_log_cache(agent_id, text):
    entry = _warm_log_cache(agent_id)
    for raw_line in str(text).splitlines():
        _ingest_log_line(entry, raw_line)


def _cached_log_blocks(agent_id):
    entry = _warm_log_cache(agent_id)
    blocks = list(entry["blocks"])
    current = "\n".join(entry.get("current_block", [])).strip()
    if current:
        blocks.append(current)
    return blocks


def load_agent_memory(agent_id):
    path = _memory_path(agent_id)
    if not os.path.exists(path):
        return []
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return []
    return data if isinstance(data, list) else []


def known_agent_ids():
    """Agent ids that have memory persisted in ``MEMORY_DIR`` — i.e. have run."""
    try:
        names = os.listdir(MEMORY_DIR)
    except OSError:
        return []
    ids = []
    for name in names:
        match = re.fullmatch(r"agent_(\d+)\.json", name)
        if match:
            ids.append(int(match.group(1)))
    return sorted(ids)


def save_agent_memory(agent):
    os.makedirs(MEMORY_DIR, exist_ok=True)
    with open(_memory_path(agent["id"]), "w", encoding="utf-8") as f:
        json.dump(agent["memory"], f, ensure_ascii=False, indent=2)


def load_agent_schedule(agent_id):
    path = _schedule_path(agent_id)
    if not os.path.exists(path):
        return []
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return []
    if not isinstance(data, list):
        return []
    cleaned = []
    for item in data:
        if isinstance(item, (list, tuple)) and len(item) == 2:
            time_str, activity = item
        elif isinstance(item, dict) and "time" in item and "activity" in item:
            time_str, activity = item["time"], item["activity"]
        else:
            continue
        time_str = str(time_str).strip()
        activity = str(activity).strip()
        if re.match(r"^\d{2}:\d{2}$", time_str) and activity:
            cleaned.append((time_str, activity))
    return cleaned


def save_agent_schedule(agent_id, schedule):
    os.makedirs(MEMORY_DIR, exist_ok=True)
    payload = []
    for time_str, activity in schedule:
        payload.append({"time": time_str, "activity": activity})
    with open(_schedule_path(agent_id), "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def load_agent_actions(agent_id):
    path = _actions_path(agent_id)
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}
    if not isinstance(data, dict):
        return {}
    cleaned = {}
    for k, v in data.items():
        if isinstance(v, list):
            cleaned[k] = [str(a).strip() for a in v if str(a).strip()]
    return cleaned


def save_agent_actions(agent_id, action_space):
    os.makedirs(MEMORY_DIR, exist_ok=True)
    with open(_actions_path(agent_id), "w", encoding="utf-8") as f:
        json.dump(action_space, f, ensure_ascii=False, indent=2)


def load_agent_locations(agent_id):
    path = _location_path(agent_id)
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def save_agent_locations(agent_id, locations):
    os.makedirs(MEMORY_DIR, exist_ok=True)
    with open(_location_path(agent_id), "w", encoding="utf-8") as f:
        json.dump(locations, f, ensure_ascii=False, indent=2)


def load_agent_location_action_bias(agent_id):
    path = _location_action_bias_path(agent_id)
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def save_agent_location_action_bias(agent_id, bias_map):
    os.makedirs(MEMORY_DIR, exist_ok=True)
    with open(_location_action_bias_path(agent_id), "w", encoding="utf-8") as f:
        json.dump(bias_map, f, ensure_ascii=False, indent=2)


def reset_agent_memory(agent_id):
    os.makedirs(MEMORY_DIR, exist_ok=True)
    with open(_memory_path(agent_id), "w", encoding="utf-8") as f:
        json.dump([], f, ensure_ascii=False, indent=2)
    vector_db_delete_agent(agent_id)


def append_agent_log(agent, text):
    os.makedirs(LOG_DIR, exist_ok=True)
    agent_id = int(agent["id"])
    _warm_log_cache(agent_id)
    with open(_log_path(agent["id"]), "a", encoding="utf-8") as f:
        f.write(text)
    _append_text_to_log_cache(agent_id, text)


def load_sim_state():
    path = _sim_state_path()
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def save_sim_state(state):
    os.makedirs(MEMORY_DIR, exist_ok=True)
    with open(_sim_state_path(), "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def _split_log_blocks(log_text):
    if not log_text:
        return []
    blocks = []
    current = []
    for line in log_text.splitlines():
        if line.startswith("[") and current:
            blocks.append("\n".join(current).strip())
            current = [line]
        else:
            current.append(line)
    if current:
        blocks.append("\n".join(current).strip())
    return [b for b in blocks if b]


def load_recent_log_blocks(agent_id, max_blocks=2, max_chars=500):
    blocks = _cached_log_blocks(agent_id)
    if not blocks:
        return []
    tail = blocks[-max_blocks:]
    trimmed = []
    for block in tail:
        if len(block) > max_chars:
            trimmed.append(block[-max_chars:])
        else:
            trimmed.append(block)
    return trimmed


def load_recent_actions(agent_id, max_items=6):
    entry = _warm_log_cache(agent_id)
    return list(entry["actions"])[-max_items:]


# =========================================================
# Vector store utilities (hashed bag-of-words embeddings)
# =========================================================

def _extract_keywords(text):
    if not text:
        return []
    tokens = re.findall(r"[\u4e00-\u9fff]{2,}|[A-Za-z0-9]{3,}", text)
    return [t.lower() for t in tokens]


_POSITIVE_MEMORY_HINTS = (
    "顺利",
    "满意",
    "开心",
    "轻松",
    "完成",
    "进展",
    "收获",
    "支持",
    "认可",
    "放松",
)

_NEGATIVE_MEMORY_HINTS = (
    "失败",
    "挫败",
    "焦虑",
    "压力",
    "冲突",
    "不满",
    "拖延",
    "疲惫",
    "后悔",
    "麻烦",
)


def _recent_unique(items, max_items):
    if not items:
        return []
    seen = set()
    recent = []
    for item in reversed(items):
        if item in seen:
            continue
        seen.add(item)
        recent.append(item)
        if len(recent) >= max_items:
            break
    return list(reversed(recent))


def _normalize_memory(memory):
    cleaned = []
    for item in memory:
        text = ""
        if isinstance(item, str):
            text = item.strip()
        elif isinstance(item, dict):
            for key in ("memory", "text", "summary", "content"):
                value = item.get(key)
                if isinstance(value, str) and value.strip():
                    text = value.strip()
                    break
            if not text:
                text = str(item).strip()
        else:
            text = str(item).strip()
        if text:
            cleaned.append(text)
    return cleaned


def _sanitize_memory_text(text, max_chars=VECTOR_DB_MAX_CHARS):
    if not text:
        return ""
    cleaned = re.sub(r"\s+", " ", str(text)).strip()
    if len(cleaned) > max_chars:
        return cleaned[:max_chars]
    return cleaned


def _vector_db_connect():
    """The calling thread's connection, opened on first use."""
    conn = getattr(_VECTOR_DB_LOCAL, "conn", None)
    if conn is not None and getattr(_VECTOR_DB_LOCAL, "path", None) == VECTOR_DB_PATH:
        return conn
    dir_path = os.path.dirname(VECTOR_DB_PATH)
    if dir_path:
        os.makedirs(dir_path, exist_ok=True)
    conn = sqlite3.connect(VECTOR_DB_PATH, timeout=30)
    # Concurrency / durability tuning:
    # - WAL allows readers to proceed during writes, eliminating most
    #   "database is locked" errors when several agents flush at once.
    # - synchronous=NORMAL is the recommended pairing with WAL for
    #   workloads where the simulator can replay from logs after a
    #   crash; full fsync on every commit is unnecessary.
    # PRAGMAs are best-effort: if the disk doesn't support WAL (e.g.
    # network mounts), we keep the default journaling mode rather than
    # crash the simulator.
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA temp_store=MEMORY")
    except sqlite3.Error:
        # Pragmas are advisory; carry on with defaults.
        pass
    _VECTOR_DB_LOCAL.conn = conn
    _VECTOR_DB_LOCAL.path = VECTOR_DB_PATH
    with _VECTOR_DB_CONNS_LOCK:
        _VECTOR_DB_CONNS.append(conn)
    return conn


def _close_vector_db():
    """Close every connection handed out, from whichever thread calls.

    Tests repoint ``VECTOR_DB_PATH`` at a fresh temp file between cases, so a
    worker thread's connection to the previous file must not survive.
    """
    global _VECTOR_DB_READY
    with _VECTOR_DB_CONNS_LOCK:
        conns, _VECTOR_DB_CONNS[:] = list(_VECTOR_DB_CONNS), []
    for conn in conns:
        try:
            conn.close()
        except sqlite3.Error as exc:
            # Connection is being torn down anyway; just leave a breadcrumb.
            _LOG.debug("vector db close failed: %s", exc)
    _VECTOR_DB_LOCAL.conn = None
    _VECTOR_DB_LOCAL.path = None
    _VECTOR_DB_READY = False


def _init_vector_db():
    global _VECTOR_DB_READY
    if _VECTOR_DB_READY:
        return
    conn = _vector_db_connect()
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA temp_store=MEMORY")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS memory_entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            agent_id INTEGER NOT NULL,
            entry_type TEXT NOT NULL,
            text TEXT NOT NULL,
            sim_day INTEGER,
            sim_time TEXT,
            created_at REAL NOT NULL,
            embedding TEXT NOT NULL
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_memory_entries_agent ON memory_entries(agent_id)"
    )
    # Idempotent schema migration for RAG-enhancement fields. SQLite
    # has no `ADD COLUMN IF NOT EXISTS`, so we probe via PRAGMA first.
    # Each column has a safe default so legacy rows behave like the
    # neutral middle of the new scoring space.
    existing_cols = {row[1] for row in conn.execute("PRAGMA table_info(memory_entries)")}
    for col_name, col_decl in (
        ("salience", "REAL DEFAULT 0.5"),
        ("emotion", "REAL DEFAULT 0.0"),
        ("recall_count", "INTEGER DEFAULT 0"),
        ("last_recall_at", "REAL DEFAULT 0.0"),
    ):
        if col_name not in existing_cols:
            conn.execute(f"ALTER TABLE memory_entries ADD COLUMN {col_name} {col_decl}")
    conn.commit()
    _VECTOR_DB_READY = True


# Process-local LRU for embeddings. Each entry is text-key → vec. We
# keep this small so a long-running simulator doesn't keep every
# memory's vector in RAM forever; the SQLite row is the durable copy.
_EMBED_CACHE_MAX = 2048
_EMBED_CACHE: "OrderedDict[tuple[str, str], list[float]]" = OrderedDict()


def _embed_cache_get(provider: str, text: str) -> list[float] | None:
    key = (provider, text)
    vec = _EMBED_CACHE.get(key)
    if vec is None:
        return None
    _EMBED_CACHE.move_to_end(key)
    return vec


def _embed_cache_put(provider: str, text: str, vec: list[float]) -> None:
    if not vec:
        return
    key = (provider, text)
    _EMBED_CACHE[key] = vec
    _EMBED_CACHE.move_to_end(key)
    while len(_EMBED_CACHE) > _EMBED_CACHE_MAX:
        _EMBED_CACHE.popitem(last=False)


def _hash_embed(text, dim=VECTOR_DB_DIM):
    # Hash tokens into a fixed-size vector for fast, dependency-free similarity.
    tokens = _extract_keywords(text)
    if not tokens:
        return [0.0] * dim
    vec = np.zeros(dim, dtype=np.float32)
    for token in tokens:
        idx = zlib.crc32(token.encode("utf-8")) % dim
        vec[idx] += 1.0
    norm = float(np.linalg.norm(vec))
    if norm > 0:
        vec /= norm
    return vec.tolist()


def _embed_text(text, dim=VECTOR_DB_DIM):
    """Embed ``text`` into a fixed-length list of floats.

    Strategy:

    * If ``vector_db_embedding_provider`` is ``"llm"`` and a provider
      with an ``embed()`` method is configured, use it. Vectors are
      cached in-process so the same text isn't re-embedded repeatedly.
    * Fall back to the legacy CRC32 hash bag-of-words embedding so the
      simulator stays usable when no embedding endpoint is reachable.

    The returned vector is always L2-normalised so cosine similarity
    reduces to a dot product.
    """
    if not isinstance(text, str) or not text.strip():
        return [0.0] * int(dim)

    mode = str(CONFIG.get("vector_db_embedding_provider", "hash")).lower()
    if mode == "llm":
        cached = _embed_cache_get("llm", text)
        if cached is not None:
            return cached
        try:
            # Late import to avoid a circular dependency at module load
            # (providers.py is constructed *after* config import).
            from gaworld.llm import providers as _llm_providers
            llm_vec = _llm_providers.embed_text(text, task="memory")
        except Exception as exc:
            _LOG.debug("LLM embed failed, falling back to hash: %s", exc)
            llm_vec = None
        if llm_vec:
            norm = math.sqrt(sum(v * v for v in llm_vec))
            if norm > 0:
                llm_vec = [float(v) / norm for v in llm_vec]
            _embed_cache_put("llm", text, llm_vec)
            return llm_vec
        # Fall through to hash on failure.

    return _hash_embed(text, dim=dim)


def vector_db_add_entry(
    agent_id,
    entry_type,
    text,
    sim_day=None,
    sim_time=None,
    *,
    salience: float | None = None,
    emotion: float | None = None,
):
    """Insert one memory row.

    The original positional signature ``(agent_id, entry_type, text,
    sim_day, sim_time)`` is preserved so existing callers across the
    codebase keep working unchanged. New keyword-only parameters
    ``salience`` and ``emotion`` let callers tag entries that matter
    more (a strong emotional episode, a key bit of skill knowledge);
    when omitted, the DB defaults (0.5 / 0.0) apply.
    """
    cleaned = _sanitize_memory_text(text)
    if not cleaned:
        return
    _init_vector_db()
    embedding = _embed_text(cleaned)
    salience_val = 0.5 if salience is None else max(0.0, min(1.0, float(salience)))
    emotion_val = 0.0 if emotion is None else max(-1.0, min(1.0, float(emotion)))
    payload = (
        int(agent_id),
        str(entry_type),
        cleaned,
        int(sim_day) if sim_day is not None else None,
        str(sim_time) if sim_time is not None else None,
        time.time(),
        json.dumps(embedding, ensure_ascii=False),
        salience_val,
        emotion_val,
    )
    conn = _vector_db_connect()
    with conn:
        conn.execute(
            """
            INSERT INTO memory_entries
            (agent_id, entry_type, text, sim_day, sim_time, created_at,
             embedding, salience, emotion)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            payload,
        )


def vector_db_delete_agent(agent_id):
    if not os.path.exists(VECTOR_DB_PATH):
        return
    conn = _vector_db_connect()
    with conn:
        conn.execute("DELETE FROM memory_entries WHERE agent_id = ?", (int(agent_id),))


def _memory_scoring_config() -> dict:
    return CONFIG.get("memory", {}) or {}


def vector_db_search(agent_id, query, top_k=VECTOR_DB_TOP_K, entry_types=None):
    """Retrieve top-k memories for ``query``.

    Legacy mode (``memory.salience_weight = False``, default) keeps the
    original pure cosine ranking so the rest of the simulator behaves
    exactly as before.

    Enhanced mode (``memory.salience_weight = True``) re-ranks hits by:

        score = cos_sim
              * (0.5 + 0.5 * salience)
              * exp(-age_days / halflife)
              * (1 + 0.1 * ln(1 + recall_count))

    and bumps ``recall_count`` / ``last_recall_at`` for every returned
    row. This is what produces "memories that get used become easier
    to retrieve" — the cognitive feedback loop from the RAG plan (D1b).
    """
    cleaned_query = _sanitize_memory_text(query, max_chars=800)
    if not cleaned_query:
        return []
    if not os.path.exists(VECTOR_DB_PATH):
        return []
    qvec = np.array(_embed_text(cleaned_query), dtype=np.float32)
    if not np.any(qvec):
        return []
    _init_vector_db()
    filters = "agent_id = ?"
    params = [int(agent_id)]
    if entry_types:
        placeholders = ", ".join(["?"] * len(entry_types))
        filters += f" AND entry_type IN ({placeholders})"
        params.extend(entry_types)

    mem_cfg = _memory_scoring_config()
    weighted = bool(mem_cfg.get("salience_weight", False))
    halflife_days = max(1.0, float(mem_cfg.get("decay_halflife_days", 14)))
    now = time.time()

    if weighted:
        sql = f"""
            SELECT id, entry_type, text, sim_day, sim_time, embedding,
                   created_at, salience, recall_count
            FROM memory_entries
            WHERE {filters}
        """
    else:
        sql = f"""
            SELECT entry_type, text, sim_day, sim_time, embedding
            FROM memory_entries
            WHERE {filters}
        """
    conn = _vector_db_connect()
    rows = conn.execute(sql, params).fetchall()
    scored = []
    for row in rows:
        if weighted:
            (row_id, entry_type, text, sim_day, sim_time, embedding_blob,
             created_at, salience, recall_count) = row
        else:
            entry_type, text, sim_day, sim_time, embedding_blob = row
            row_id = None
            created_at = now
            salience = 0.5
            recall_count = 0
        try:
            vec = np.array(json.loads(embedding_blob), dtype=np.float32)
        except (TypeError, json.JSONDecodeError):
            continue
        if vec.shape != qvec.shape:
            continue
        cos_sim = float(np.dot(qvec, vec))
        if cos_sim <= 0:
            continue
        if weighted:
            age_days = max(0.0, (now - float(created_at or now)) / 86400.0)
            decay = math.exp(-age_days / halflife_days)
            salience_factor = 0.5 + 0.5 * max(0.0, min(1.0, float(salience or 0.5)))
            recall_boost = 1.0 + 0.1 * math.log1p(max(0, int(recall_count or 0)))
            score = cos_sim * salience_factor * decay * recall_boost
        else:
            score = cos_sim
        hit = {
            "score": score,
            "type": entry_type,
            "text": text,
            "sim_day": sim_day,
            "sim_time": sim_time,
        }
        if weighted:
            hit["row_id"] = row_id
        scored.append(hit)
    scored.sort(key=lambda x: x["score"], reverse=True)
    top = scored[:max(1, int(top_k))]
    if weighted and top:
        ids_to_bump = [int(h["row_id"]) for h in top if h.get("row_id") is not None]
        if ids_to_bump:
            try:
                placeholders = ", ".join(["?"] * len(ids_to_bump))
                with conn:
                    conn.execute(
                        f"UPDATE memory_entries SET recall_count = recall_count + 1, "
                        f"last_recall_at = ? WHERE id IN ({placeholders})",
                        [now, *ids_to_bump],
                    )
            except sqlite3.Error as exc:
                # Recall bookkeeping is best-effort — never break a
                # planning call because the bump failed.
                _LOG.debug("recall bookkeeping update failed: %s", exc)
    # Strip the internal row_id before handing back to callers.
    for h in top:
        h.pop("row_id", None)
    return top


def vector_db_count_entries(agent_id):
    if not os.path.exists(VECTOR_DB_PATH):
        return 0
    _init_vector_db()
    conn = _vector_db_connect()
    row = conn.execute(
        "SELECT COUNT(1) FROM memory_entries WHERE agent_id = ?",
        (int(agent_id),),
    ).fetchone()
    return int(row[0]) if row else 0


def seed_vector_db_from_memory(agent):
    if not isinstance(agent, dict):
        return
    memories = _normalize_memory(agent.get("memory", []))
    if not memories:
        return
    if vector_db_count_entries(agent["id"]) > 0:
        return
    for mem in memories:
        vector_db_add_entry(agent["id"], "memory", mem)


def _growth_boost_hits(agent, hits):
    """Re-rank ``hits`` to prefer memories tied to the agent's growth items.

    Only active when ``memory.growth_boost`` is on (default ON). Late-imports
    ``gaworld.interests`` so the memory store stays import-light, and is a
    no-op when the agent has no ``growth_profile`` attached — i.e. the
    rest of the simulator still works for runs where the growth bootstrap
    wasn't invoked.
    """
    if not isinstance(agent, dict) or not hits:
        return hits
    mem_cfg = CONFIG.get("memory", {}) or {}
    if not mem_cfg.get("growth_boost", True):
        return hits
    profile = agent.get("growth_profile")
    if not profile:
        return hits
    try:
        from gaworld.interests import GrowthProfile, match_growth_items
    except Exception:  # pragma: no cover - keep store import-safe
        return hits
    gp = profile if isinstance(profile, GrowthProfile) else GrowthProfile.from_dict(profile)
    if not gp.items:
        return hits
    strength = max(0.0, float(mem_cfg.get("growth_boost_strength", 0.15)))
    if strength <= 0:
        return hits
    boosted = []
    for hit in hits:
        text = hit.get("text") or ""
        matches = match_growth_items(gp, text)
        if matches:
            # Boost by the strongest matching item's priority. We look
            # priorities back up from the canonical profile so this
            # works whether `match_growth_items` returned dicts or not.
            top_priority = 0.0
            for m in matches:
                name = str(m.get("name", "")).strip()
                for item in gp.items:
                    if item.name == name and item.priority > top_priority:
                        top_priority = item.priority
            multiplier = 1.0 + strength * top_priority
            new_hit = dict(hit)
            new_hit["score"] = float(hit.get("score", 0.0)) * multiplier
            new_hit["growth_match"] = sorted({str(m.get("name", "")) for m in matches if m.get("name")})
            boosted.append(new_hit)
        else:
            boosted.append(hit)
    boosted.sort(key=lambda x: x.get("score", 0.0), reverse=True)
    return boosted


def retrieve_relevant_memories(agent, query, max_items=VECTOR_DB_TOP_K, entry_types=None):
    # Prefer vector DB; fall back to keyword scan of JSON memory when DB is empty.
    agent_id = agent["id"] if isinstance(agent, dict) else int(agent)
    hits = vector_db_search(agent_id, query, top_k=max_items, entry_types=entry_types)
    if hits:
        return _growth_boost_hits(agent, hits)
    if isinstance(agent, dict):
        fallback = relevant_memory(agent, context=query, max_items=max_items)
        return [{"type": "memory", "text": t, "score": 0.0} for t in fallback]
    return []


def _format_memory_hint(memories, max_chars=180):
    if not memories:
        return "暂无重要经验"
    lines = []
    for item in memories:
        text = item["text"] if isinstance(item, dict) else str(item)
        cleaned = _sanitize_memory_text(text, max_chars=max_chars)
        if cleaned:
            lines.append(cleaned)
    return "；".join(lines) if lines else "暂无重要经验"


def _memory_action_bias(action, memories):
    if not action or not memories:
        return 0.0
    act_tokens = set(_extract_keywords(action))
    if not act_tokens:
        return 0.0
    score = 0.0
    for item in memories:
        text = item["text"] if isinstance(item, dict) else str(item)
        mem_tokens = set(_extract_keywords(text))
        overlap = len(act_tokens & mem_tokens)
        if not overlap:
            action_text = str(action).strip()
            memory_text = str(text).strip()
            if action_text and action_text in memory_text:
                overlap = 1
        if not overlap:
            continue
        positive = sum(1 for hint in _POSITIVE_MEMORY_HINTS if hint in text)
        negative = sum(1 for hint in _NEGATIVE_MEMORY_HINTS if hint in text)
        bias = 0.10 * overlap
        if positive > negative:
            bias += 0.06 * overlap
        elif negative > positive:
            bias -= 0.55 * overlap
        score += bias
    return score


# =========================================================
# Fallback keyword retrieval for JSON memory lists
# =========================================================

def relevant_memory(agent, context=None, max_items=3):
    memory = _normalize_memory(agent.get("memory", []))
    if not memory:
        return []
    if context:
        tokens = _extract_keywords(context)
        if tokens:
            token_set = set(tokens)
            scored = []
            total = len(memory)
            for idx, item in enumerate(memory):
                mem_tokens = _extract_keywords(item)
                if not mem_tokens:
                    continue
                mem_set = set(mem_tokens)
                overlap = len(token_set & mem_set)
                if overlap == 0:
                    continue
                coverage = overlap / max(len(mem_set), 1)
                recency = idx / max(total - 1, 1)
                score = overlap * 3 + coverage + recency * 0.5
                scored.append((score, idx, item))
            if scored:
                scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
                top = scored[:max_items]
                top.sort(key=lambda x: x[1])
                return [item for _, _, item in top]
    return _recent_unique(memory, max_items)


atexit.register(_close_vector_db)
