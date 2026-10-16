import argparse
import json
import math
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from gaworld.settings import CONFIG


def _to_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def _normalize_text(value, max_chars=280):
    text = str(value or "").strip()
    if max_chars > 0 and len(text) > max_chars:
        text = text[:max_chars].rstrip()
    return text


def _safe_dict(value):
    return value if isinstance(value, dict) else {}


def _safe_list(value):
    return value if isinstance(value, list) else []


def _normalize_choice(value, allowed, default):
    text = _normalize_text(value, max_chars=40).lower()
    return text if text in allowed else default


def _sanitize_public_profile(raw_profile):
    profile = _safe_dict(raw_profile)
    tags = profile.get("tags", [])
    if not isinstance(tags, list):
        tags = []
    clean_tags = []
    for tag in tags:
        text = _normalize_text(tag, max_chars=32)
        if text and text not in clean_tags:
            clean_tags.append(text)
    return {
        "summary": _normalize_text(
            profile.get("summary") or profile.get("public_summary") or profile.get("background_summary"),
            max_chars=220,
        ),
        "status": _normalize_text(profile.get("status") or profile.get("public_status"), max_chars=80),
        "focus": _normalize_text(profile.get("focus"), max_chars=80),
        "tags": clean_tags[:6],
    }


def _build_public_profile_from_agent(item):
    public_profile = _sanitize_public_profile(item.get("public_profile"))
    if not public_profile.get("summary"):
        public_profile["summary"] = _normalize_text(item.get("background_summary", ""), max_chars=220)
    if not public_profile.get("status"):
        public_profile["status"] = _normalize_text(item.get("public_status", ""), max_chars=80)
    if not public_profile.get("focus"):
        public_profile["focus"] = _normalize_text(item.get("job", ""), max_chars=80)
    if not public_profile.get("tags"):
        tags = []
        for raw in (item.get("job", ""), item.get("personality", ""), item.get("values", "")):
            text = _normalize_text(raw, max_chars=32)
            if text and text not in tags:
                tags.append(text)
        public_profile["tags"] = tags[:3]
    return public_profile


def _sanitize_social_summary(raw_summary, text=""):
    summary = _safe_dict(raw_summary)
    clean = {
        "summary": _normalize_text(summary.get("summary") or text, max_chars=180),
        "topic": _normalize_text(summary.get("topic"), max_chars=64),
        "status": _normalize_text(summary.get("status"), max_chars=80),
        "emotion": _normalize_text(summary.get("emotion"), max_chars=32),
        "ask": _normalize_text(summary.get("ask"), max_chars=120),
    }
    if not clean["summary"]:
        clean["summary"] = _normalize_text(text, max_chars=180)
    return clean


def _sanitize_public_state(raw_state):
    state = _safe_dict(raw_state)
    clean = {}
    for key in ("emotion", "stress", "social_need", "energy", "econ_security"):
        value = state.get(key)
        try:
            number = float(value)
            if math.isfinite(number):
                clean[key] = round(number, 4)
        except (TypeError, ValueError):
            continue
    status = _normalize_text(state.get("status"), max_chars=80)
    if status:
        clean["status"] = status
    return clean


class DistributedRelayBackend:
    def __init__(self, state_path="", max_messages=20000):
        self.state_path = state_path
        self.max_messages = max(100, _to_int(max_messages, 20000))
        self.max_social_events = max(200, min(self.max_messages, 4000))
        self.lock = threading.RLock()
        self.next_message_id = 1
        self.messages = []
        self.directory = {}
        self.interaction_edges = {}
        self.recent_social_events = []
        # --- OpenClaw extension ---
        # Profiles for externally-registered agents (keyed by cluster→agent_id).
        self.agent_profiles = {}
        # Simple token auth for OpenClaw bridges (cluster → set of valid tokens).
        self.auth_tokens = {}
        # Simulation tick state broadcast by the sim engine so bridges can sync.
        self.tick_state = {"day": 0, "time": "00:00", "background": "", "updated_at": 0.0}
        # Next auto-assigned ID for OpenClaw agents (1001+).
        self._next_openclaw_id = 1001
        self._load()

    def _persist(self):
        if not self.state_path:
            return
        directory = os.path.dirname(self.state_path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        payload = {
            "next_message_id": int(self.next_message_id),
            "messages": self.messages,
            "directory": self.directory,
            "interaction_edges": self.interaction_edges,
            "recent_social_events": self.recent_social_events,
            "agent_profiles": self.agent_profiles,
            "auth_tokens": self.auth_tokens,
            "tick_state": self.tick_state,
            "_next_openclaw_id": self._next_openclaw_id,
            "max_messages": int(self.max_messages),
            "updated_at": time.time(),
        }
        with open(self.state_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)

    def _load(self):
        if not self.state_path or not os.path.exists(self.state_path):
            return
        try:
            with open(self.state_path, encoding="utf-8") as f:
                payload = json.load(f)
        except (OSError, json.JSONDecodeError):
            return
        if not isinstance(payload, dict):
            return
        self.next_message_id = max(1, _to_int(payload.get("next_message_id", 1), 1))
        raw_messages = payload.get("messages", [])
        self.messages = raw_messages if isinstance(raw_messages, list) else []
        raw_dir = payload.get("directory", {})
        self.directory = raw_dir if isinstance(raw_dir, dict) else {}
        raw_edges = payload.get("interaction_edges", {})
        self.interaction_edges = raw_edges if isinstance(raw_edges, dict) else {}
        raw_events = payload.get("recent_social_events", [])
        self.recent_social_events = raw_events if isinstance(raw_events, list) else []
        if self.messages:
            max_id = max(_to_int(msg.get("id"), 0) for msg in self.messages if isinstance(msg, dict))
            self.next_message_id = max(self.next_message_id, max_id + 1)
        # Restore OpenClaw extension state.
        raw_profiles = payload.get("agent_profiles", {})
        self.agent_profiles = raw_profiles if isinstance(raw_profiles, dict) else {}
        raw_tokens = payload.get("auth_tokens", {})
        self.auth_tokens = raw_tokens if isinstance(raw_tokens, dict) else {}
        raw_tick = payload.get("tick_state")
        if isinstance(raw_tick, dict):
            self.tick_state = raw_tick
        self._next_openclaw_id = max(1001, _to_int(payload.get("_next_openclaw_id", 1001), 1001))

        # Dev persisted messages but not the derived social indexes.
        if "interaction_edges" not in payload:
            for message in self.messages:
                if not isinstance(message, dict):
                    continue
                cluster = str(message.get("cluster") or "default")
                sender = self._touch_agent_entry(cluster, message.get("from_agent"), direction="outbound")
                recipient = self._touch_agent_entry(cluster, message.get("to_agent"), direction="inbound")
                self._append_recent_partner(sender, message.get("to_agent"))
                self._append_recent_partner(recipient, message.get("from_agent"))
                self._record_social_event(cluster, message)

    def _cluster_directory(self, cluster):
        cluster = str(cluster or "default")
        cluster_map = self.directory.setdefault(cluster, {})
        return cluster_map if isinstance(cluster_map, dict) else {}

    def _cluster_profiles(self, cluster):
        cluster = str(cluster or "default")
        profile_map = self.agent_profiles.setdefault(cluster, {})
        return profile_map if isinstance(profile_map, dict) else {}

    def _cluster_edges(self, cluster):
        cluster = str(cluster or "default")
        edge_map = self.interaction_edges.setdefault(cluster, {})
        return edge_map if isinstance(edge_map, dict) else {}

    def _touch_agent_entry(
        self,
        cluster,
        agent_id,
        *,
        name="",
        node_id="",
        agent_type="",
        public_profile=None,
        public_state=None,
        direction="",
        timestamp=None,
    ):
        aid = _to_int(agent_id, 0)
        if aid <= 0:
            return None
        now = float(timestamp if timestamp is not None else time.time())
        cluster_map = self._cluster_directory(cluster)
        key = str(aid)
        entry = cluster_map.get(key)
        if not isinstance(entry, dict):
            entry = {
                "agent_id": aid,
                "name": "",
                "node_id": "",
                "agent_type": "native",
                "updated_at": now,
                "registered_at": now,
                "last_seen_at": now,
                "message_counts": {"inbound": 0, "outbound": 0},
                "recent_partners": [],
                "public_profile": {},
                "public_state": {},
            }
            cluster_map[key] = entry
        entry["agent_id"] = aid
        if name:
            entry["name"] = _normalize_text(name, max_chars=64)
        elif not entry.get("name"):
            entry["name"] = f"Agent {aid}"
        if node_id:
            entry["node_id"] = _normalize_text(node_id, max_chars=64)
        entry["agent_type"] = (
            _normalize_text(
                agent_type if agent_type else entry.get("agent_type", "native"),
                max_chars=24,
            )
            or "native"
        )
        entry["updated_at"] = now
        entry["last_seen_at"] = now
        if not entry.get("registered_at"):
            entry["registered_at"] = now
        public_profile = _sanitize_public_profile(public_profile)
        if any(public_profile.values()):
            entry["public_profile"] = public_profile
        elif not isinstance(entry.get("public_profile"), dict):
            entry["public_profile"] = {}
        public_state = _sanitize_public_state(public_state)
        if public_state:
            entry["public_state"] = public_state
        elif not isinstance(entry.get("public_state"), dict):
            entry["public_state"] = {}
        counts = entry.get("message_counts")
        if not isinstance(counts, dict):
            counts = {}
            entry["message_counts"] = counts
        counts.setdefault("inbound", 0)
        counts.setdefault("outbound", 0)
        if direction == "outbound":
            counts["outbound"] = _to_int(counts.get("outbound", 0), 0) + 1
            entry["last_outbound_at"] = now
        elif direction == "inbound":
            counts["inbound"] = _to_int(counts.get("inbound", 0), 0) + 1
            entry["last_inbound_at"] = now
        return entry

    def _append_recent_partner(self, entry, partner_id):
        if not isinstance(entry, dict):
            return
        pid = _to_int(partner_id, 0)
        if pid <= 0:
            return
        current = entry.get("recent_partners", [])
        if not isinstance(current, list):
            current = []
        current = [int(x) for x in current if _to_int(x, 0) > 0 and _to_int(x, 0) != pid]
        current.insert(0, pid)
        entry["recent_partners"] = current[:8]

    def _record_social_event(self, cluster, message):
        cluster = str(cluster or "default")
        msg = _safe_dict(message)
        if not msg:
            return
        sender = _to_int(msg.get("from_agent"), 0)
        recipient = _to_int(msg.get("to_agent"), 0)
        if sender <= 0 or recipient <= 0:
            return
        cluster_map = self._cluster_directory(cluster)
        sender_entry = _safe_dict(cluster_map.get(str(sender)))
        recipient_entry = _safe_dict(cluster_map.get(str(recipient)))
        # Never expose raw direct-message text or private metadata in a snapshot.
        summary = _sanitize_social_summary(msg.get("social_summary"))
        if msg.get("private_level") == "private" or msg.get("memory_policy") == "ephemeral":
            summary = _sanitize_social_summary({})
        event = {
            "id": _to_int(msg.get("id"), 0),
            "message_id": _to_int(msg.get("id"), 0),
            "cluster": cluster,
            "from_agent": sender,
            "from_name": _normalize_text(
                msg.get("from_name") or sender_entry.get("name", f"Agent {sender}"),
                max_chars=64,
            ),
            "to_agent": recipient,
            "to_name": _normalize_text(
                recipient_entry.get("name", f"Agent {recipient}"),
                max_chars=64,
            ),
            "conversation_id": _normalize_text(msg.get("conversation_id"), max_chars=64),
            "intent": _normalize_text(msg.get("intent"), max_chars=40),
            "visibility": _normalize_text(msg.get("visibility"), max_chars=24),
            "private_level": _normalize_text(msg.get("private_level"), max_chars=24),
            "activity": _normalize_text(msg.get("activity"), max_chars=64),
            "day": _to_int(msg.get("day"), 0),
            "time": _normalize_text(msg.get("time"), max_chars=16),
            "preview": summary.get("summary", ""),
            "text": summary.get("summary", ""),
            "social_summary": summary,
            "kind": _normalize_text(msg.get("kind", ""), max_chars=40),
            "topic": summary.get("topic", ""),
            "status": summary.get("status", ""),
            "emotion": summary.get("emotion", ""),
            "ask": summary.get("ask", ""),
            "created_at": float(msg.get("created_at", time.time())),
        }
        self.recent_social_events.append(event)
        overflow = len(self.recent_social_events) - self.max_social_events
        if overflow > 0:
            self.recent_social_events = self.recent_social_events[overflow:]

        a_id, b_id = sorted((sender, recipient))
        edge_key = f"{a_id}:{b_id}"
        edge_map = self._cluster_edges(cluster)
        edge = edge_map.get(edge_key)
        if not isinstance(edge, dict):
            edge = {
                "agent_a": a_id,
                "agent_b": b_id,
                "source": a_id,
                "target": b_id,
                "interaction_count": 0,
                "message_ids": [],
            }
            edge_map[edge_key] = edge
        edge["interaction_count"] = _to_int(edge.get("interaction_count", 0), 0) + 1
        edge["last_message_id"] = event["message_id"]
        edge["last_day"] = event["day"]
        edge["last_time"] = event["time"]
        edge["last_intent"] = event["intent"]
        edge["last_visibility"] = event["visibility"]
        edge["last_preview"] = event["preview"]
        edge["last_created_at"] = event["created_at"]
        edge["last_from_agent"] = sender
        edge["last_to_agent"] = recipient
        ids = edge.get("message_ids", [])
        if not isinstance(ids, list):
            ids = []
        ids.append(event["message_id"])
        edge["message_ids"] = ids[-12:]

    # ------------------------------------------------------------------
    # Auth helpers
    # ------------------------------------------------------------------
    def add_auth_token(self, cluster, token):
        """Register a bearer token that OpenClaw bridges must present."""
        cluster = str(cluster or "default")
        with self.lock:
            tokens = self.auth_tokens.setdefault(cluster, [])
            if token and token not in tokens:
                tokens.append(str(token))
            self._persist()

    def verify_token(self, cluster, token):
        """Return True if *token* is valid for *cluster*, or if no tokens are configured."""
        cluster = str(cluster or "default")
        with self.lock:
            tokens = self.auth_tokens.get(cluster, [])
        if not tokens:
            return True  # open cluster
        return str(token) in tokens

    # ------------------------------------------------------------------
    # Registration (extended for OpenClaw agents)
    # ------------------------------------------------------------------
    def register_agents(self, cluster, node_id, agents, agent_type="native"):
        cluster = str(cluster or "default")
        node_id = str(node_id or "node")
        agent_type = str(agent_type or "native")
        now = time.time()
        with self.lock:
            cluster_map = self._cluster_directory(cluster)
            profile_map = self._cluster_profiles(cluster)
            count = 0
            assigned_ids = []
            for item in agents if isinstance(agents, list) else []:
                if not isinstance(item, dict):
                    continue
                aid = _to_int(item.get("id"), 0)
                # OpenClaw agents may omit id — auto-assign from 1001+.
                if aid <= 0 and agent_type == "openclaw":
                    aid = self._next_openclaw_id
                    self._next_openclaw_id += 1
                if aid <= 0:
                    continue
                public_profile = _build_public_profile_from_agent(item)
                public_state = _sanitize_public_state(item.get("public_state"))
                entry = self._touch_agent_entry(
                    cluster,
                    aid,
                    name=item.get("name", ""),
                    node_id=node_id,
                    agent_type=agent_type,
                    public_profile=public_profile,
                    public_state=public_state,
                    timestamp=now,
                )
                if isinstance(entry, dict):
                    entry["registered_at"] = now
                # Store extended profile for OpenClaw agents.
                if agent_type in {"openclaw", "personal_twin"}:
                    profile_map[str(aid)] = {
                        "agent_id": aid,
                        "name": _normalize_text(item.get("name", ""), max_chars=64),
                        "age": _normalize_text(item.get("age", ""), max_chars=8),
                        "gender": _normalize_text(item.get("gender", ""), max_chars=8),
                        "job": _normalize_text(item.get("job", ""), max_chars=64),
                        "personality": _normalize_text(item.get("personality", ""), max_chars=200),
                        "values": _normalize_text(item.get("values", ""), max_chars=200),
                        "background_summary": _normalize_text(
                            item.get("background_summary", ""), max_chars=400
                        ),
                        "public_profile": public_profile,
                        "public_state": public_state,
                        "agent_type": agent_type,
                        "node_id": node_id,
                        "updated_at": now,
                    }
                assigned_ids.append(aid)
                count += 1
            self._persist()
            agents_list = list(cluster_map.values())
        agents_list.sort(key=lambda x: _to_int(x.get("agent_id"), 0))
        return {"ok": True, "registered": count, "assigned_ids": assigned_ids, "directory": agents_list}

    def get_directory(self, cluster):
        cluster = str(cluster or "default")
        with self.lock:
            cluster_map = _safe_dict(self.directory.get(cluster))
            agents_list = list(cluster_map.values())
        agents_list.sort(key=lambda x: _to_int(x.get("agent_id"), 0))
        return {"ok": True, "cluster": cluster, "agents": agents_list}

    def send_message(self, cluster, node_id, message):
        cluster = str(cluster or "default")
        node_id = str(node_id or "node")
        payload = _safe_dict(message)
        from_agent = _to_int(payload.get("from_agent"), 0)
        to_agent = _to_int(payload.get("to_agent"), 0)
        text = _normalize_text(payload.get("text", ""), max_chars=400)
        if from_agent <= 0 or to_agent <= 0 or not text:
            return {"ok": False, "error": "invalid message payload"}
        intent = _normalize_text(payload.get("intent", "status_update"), max_chars=40) or "status_update"
        visibility = _normalize_choice(
            payload.get("visibility"),
            {"direct", "friends", "public", "network"},
            "direct",
        )
        private_level = _normalize_choice(
            payload.get("private_level"),
            {"public", "summary", "private"},
            "summary",
        )
        memory_policy = _normalize_choice(
            payload.get("memory_policy"),
            {"social_summary", "retain", "ephemeral"},
            "social_summary",
        )
        conversation_id = _normalize_text(payload.get("conversation_id"), max_chars=64)
        social_summary = _sanitize_social_summary(payload.get("social_summary"))
        public_state = _sanitize_public_state(payload.get("public_state"))
        public_profile = _build_public_profile_from_agent(payload)
        msg = {
            "id": 0,
            "cluster": cluster,
            "node_id": node_id,
            "from_agent": from_agent,
            "from_name": _normalize_text(payload.get("from_name", ""), max_chars=64),
            "to_agent": to_agent,
            "kind": _normalize_text(payload.get("kind", "agent_update"), max_chars=40) or "agent_update",
            "text": text,
            "day": _to_int(payload.get("day"), 0),
            "time": _normalize_text(payload.get("time", ""), max_chars=16),
            "activity": _normalize_text(payload.get("activity", ""), max_chars=64),
            "conversation_id": conversation_id
            or f"{cluster}:{min(from_agent, to_agent)}:{max(from_agent, to_agent)}",
            "reply_to": _to_int(payload.get("reply_to"), 0),
            "intent": intent,
            "visibility": visibility,
            "private_level": private_level,
            "memory_policy": memory_policy,
            "social_summary": social_summary,
            "public_state": public_state,
            "meta": _safe_dict(payload.get("meta")),
            "created_at": time.time(),
        }
        with self.lock:
            sender_entry = self._touch_agent_entry(
                cluster,
                from_agent,
                name=msg.get("from_name", ""),
                node_id=node_id,
                public_profile=public_profile,
                public_state=public_state,
                direction="outbound",
                timestamp=msg["created_at"],
            )
            if isinstance(sender_entry, dict) and social_summary.get("status"):
                profile = _safe_dict(sender_entry.get("public_profile"))
                profile["status"] = social_summary.get("status", "")
                sender_entry["public_profile"] = profile
            recipient_entry = self._touch_agent_entry(
                cluster,
                to_agent,
                name="",
                direction="inbound",
                timestamp=msg["created_at"],
            )
            self._append_recent_partner(sender_entry, to_agent)
            self._append_recent_partner(recipient_entry, from_agent)
            msg["id"] = int(self.next_message_id)
            self.next_message_id += 1
            self.messages.append(msg)
            overflow = len(self.messages) - self.max_messages
            if overflow > 0:
                self.messages = self.messages[overflow:]
            self._record_social_event(cluster, msg)
            self._persist()
        return {"ok": True, "message": msg}

    def poll_messages(self, cluster, recipient_ids, since_map, limit):
        cluster = str(cluster or "default")
        ids = []
        for raw in recipient_ids if isinstance(recipient_ids, list) else []:
            aid = _to_int(raw, 0)
            if aid > 0:
                ids.append(aid)
        unique_ids = sorted(set(ids))
        since_obj = _safe_dict(since_map)
        effective_limit = max(1, min(500, _to_int(limit, 100)))
        if not unique_ids:
            return {"ok": True, "messages": [], "next_since": {}}

        id_set = set(unique_ids)
        next_since = {str(aid): _to_int(since_obj.get(str(aid), 0), 0) for aid in unique_ids}
        selected = []
        with self.lock:
            for msg in self.messages:
                if not isinstance(msg, dict):
                    continue
                if str(msg.get("cluster", "")) != cluster:
                    continue
                to_agent = _to_int(msg.get("to_agent"), 0)
                if to_agent not in id_set:
                    continue
                msg_id = _to_int(msg.get("id"), 0)
                if msg_id <= next_since.get(str(to_agent), 0):
                    continue
                selected.append(msg)
                next_since[str(to_agent)] = max(next_since.get(str(to_agent), 0), msg_id)
                if len(selected) >= effective_limit:
                    break
        return {"ok": True, "messages": selected, "next_since": next_since}

    # ------------------------------------------------------------------
    # Tick state (sim engine pushes; bridges pull)
    # ------------------------------------------------------------------
    def update_tick(self, day, time_str, background=""):
        with self.lock:
            self.tick_state = {
                "day": _to_int(day, 0),
                "time": _normalize_text(time_str, max_chars=16),
                "background": _normalize_text(background, max_chars=600),
                "updated_at": time.time(),
            }
            self._persist()
        return {"ok": True, "tick": self.tick_state}

    def get_tick(self):
        with self.lock:
            return {"ok": True, "tick": dict(self.tick_state)}

    # ------------------------------------------------------------------
    # Agent profiles (for cross-node identity resolution)
    # ------------------------------------------------------------------
    def get_agent_profile(self, cluster, agent_id):
        cluster = str(cluster or "default")
        aid = _to_int(agent_id, 0)
        with self.lock:
            profile_map = _safe_dict(self.agent_profiles.get(cluster))
            profile = profile_map.get(str(aid))
        if profile:
            return {"ok": True, "profile": profile}
        # Fallback: return directory entry for native agents.
        with self.lock:
            cluster_map = _safe_dict(self.directory.get(cluster))
            entry = cluster_map.get(str(aid))
        if entry:
            return {"ok": True, "profile": entry}
        return {"ok": False, "error": f"agent {aid} not found"}

    def list_agent_profiles(self, cluster):
        cluster = str(cluster or "default")
        with self.lock:
            profile_map = _safe_dict(self.agent_profiles.get(cluster))
            profiles = list(profile_map.values())
        profiles.sort(key=lambda x: _to_int(x.get("agent_id"), 0))
        return {"ok": True, "profiles": profiles}

    def list_social_agents(self, cluster):
        cluster = str(cluster or "default")
        with self.lock:
            cluster_map = _safe_dict(self.directory.get(cluster))
            agents = []
            for entry in cluster_map.values():
                if not isinstance(entry, dict):
                    continue
                agent = dict(entry)
                counts = _safe_dict(agent.get("message_counts"))
                agent["message_counts"] = {
                    "inbound": _to_int(counts.get("inbound", 0), 0),
                    "outbound": _to_int(counts.get("outbound", 0), 0),
                }
                agent["public_profile"] = _sanitize_public_profile(agent.get("public_profile"))
                agent["public_state"] = _sanitize_public_state(agent.get("public_state"))
                agents.append(agent)
        agents.sort(
            key=lambda item: (
                -_to_int(_safe_dict(item.get("message_counts")).get("inbound", 0), 0)
                - _to_int(_safe_dict(item.get("message_counts")).get("outbound", 0), 0),
                _to_int(item.get("agent_id"), 0),
            )
        )
        return {"ok": True, "cluster": cluster, "agents": agents}

    def list_social_edges(self, cluster):
        cluster = str(cluster or "default")
        with self.lock:
            edge_map = _safe_dict(self.interaction_edges.get(cluster))
            edges = [dict(edge) for edge in edge_map.values() if isinstance(edge, dict)]
        edges.sort(
            key=lambda item: (
                -_to_int(item.get("interaction_count", 0), 0),
                -_to_int(item.get("last_message_id", 0), 0),
            )
        )
        return {"ok": True, "cluster": cluster, "edges": edges}

    def list_recent_social_messages(self, cluster, limit=20):
        cluster = str(cluster or "default")
        limit = max(1, min(200, _to_int(limit, 20)))
        with self.lock:
            events = [
                dict(item)
                for item in self.recent_social_events
                if isinstance(item, dict) and str(item.get("cluster", "")) == cluster
            ]
        return {"ok": True, "cluster": cluster, "messages": list(reversed(events[-limit:]))}

    def social_snapshot(self, cluster, recent_limit=20):
        cluster = str(cluster or "default")
        recent_limit = max(1, min(200, _to_int(recent_limit, 20)))
        agents_payload = self.list_social_agents(cluster)
        edges_payload = self.list_social_edges(cluster)
        recent_payload = self.list_recent_social_messages(cluster, limit=recent_limit)
        agents = agents_payload.get("agents", [])
        edges = edges_payload.get("edges", [])
        recent = recent_payload.get("messages", [])
        active_agent_count = sum(
            1 for item in agents if isinstance(item, dict) and float(item.get("last_seen_at", 0.0)) > 0.0
        )
        return {
            "ok": True,
            "cluster": cluster,
            "tick": dict(self.tick_state),
            "stats": {
                "agent_count": len(agents),
                "active_agent_count": active_agent_count,
                "edge_count": len(edges),
                "recent_message_count": len(recent),
                "total_message_count": len(
                    [
                        msg
                        for msg in self.messages
                        if isinstance(msg, dict) and str(msg.get("cluster", "")) == cluster
                    ]
                ),
            },
            "agents": agents,
            "edges": edges,
            "recent_messages": recent,
        }

    def snapshot(self):
        with self.lock:
            cluster_count = len(self.directory)
            agent_count = sum(len(_safe_dict(v)) for v in self.directory.values())
            message_count = len(self.messages)
            latest_id = _to_int(self.messages[-1].get("id"), 0) if self.messages else 0
        return {
            "ok": True,
            "cluster_count": cluster_count,
            "registered_agent_count": agent_count,
            "message_count": message_count,
            "latest_message_id": latest_id,
            "max_messages": int(self.max_messages),
        }


class DistributedRelayRequestHandler(BaseHTTPRequestHandler):
    backend = None

    def _read_json(self):
        raw_len = self.headers.get("Content-Length", "0")
        size = _to_int(raw_len, 0)
        if size <= 0:
            return {}
        raw = self.rfile.read(size)
        if not raw:
            return {}
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return {}
        return payload if isinstance(payload, dict) else {}

    def _write_json(self, code, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _extract_token(self):
        """Extract bearer token from Authorization header."""
        auth = self.headers.get("Authorization", "")
        if auth.lower().startswith("bearer "):
            return auth[7:].strip()
        return auth.strip()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)
        if path == "/health":
            self._write_json(200, {"ok": True})
            return
        if path == "/snapshot":
            self._write_json(200, self.backend.snapshot())
            return
        if path == "/directory":
            cluster = (query.get("cluster") or ["default"])[0]
            self._write_json(200, self.backend.get_directory(cluster))
            return
        if path == "/tick":
            self._write_json(200, self.backend.get_tick())
            return
        if path == "/agents/profiles":
            cluster = (query.get("cluster") or ["default"])[0]
            self._write_json(200, self.backend.list_agent_profiles(cluster))
            return
        if path == "/social/snapshot":
            cluster = (query.get("cluster") or ["default"])[0]
            limit = (query.get("limit") or ["20"])[0]
            self._write_json(200, self.backend.social_snapshot(cluster, recent_limit=limit))
            return
        if path == "/social/agents":
            cluster = (query.get("cluster") or ["default"])[0]
            self._write_json(200, self.backend.list_social_agents(cluster))
            return
        if path == "/social/edges":
            cluster = (query.get("cluster") or ["default"])[0]
            self._write_json(200, self.backend.list_social_edges(cluster))
            return
        if path == "/social/messages/recent":
            cluster = (query.get("cluster") or ["default"])[0]
            limit = (query.get("limit") or ["20"])[0]
            self._write_json(200, self.backend.list_recent_social_messages(cluster, limit=limit))
            return
        if path.startswith("/agents/profile/"):
            aid_str = path.rsplit("/", 1)[-1]
            cluster = (query.get("cluster") or ["default"])[0]
            self._write_json(200, self.backend.get_agent_profile(cluster, aid_str))
            return
        self._write_json(404, {"ok": False, "error": "not found"})

    def do_POST(self):
        if self.path == "/register":
            payload = self._read_json()
            agent_type = str(payload.get("agent_type", "native"))
            # Token auth required for OpenClaw registrations.
            if agent_type == "openclaw":
                cluster = str(payload.get("cluster", "default"))
                token = payload.get("token") or self._extract_token()
                if not self.backend.verify_token(cluster, token):
                    self._write_json(403, {"ok": False, "error": "invalid token"})
                    return
            data = self.backend.register_agents(
                cluster=payload.get("cluster", "default"),
                node_id=payload.get("node_id", "node"),
                agents=payload.get("agents", []),
                agent_type=agent_type,
            )
            self._write_json(200, data)
            return
        if self.path == "/tick":
            payload = self._read_json()
            data = self.backend.update_tick(
                day=payload.get("day", 0),
                time_str=payload.get("time", "00:00"),
                background=payload.get("background", ""),
            )
            self._write_json(200, data)
            return
        if self.path == "/auth/token":
            payload = self._read_json()
            token = str(payload.get("token", "")).strip()
            cluster = str(payload.get("cluster", "default"))
            if not token:
                self._write_json(400, {"ok": False, "error": "token required"})
                return
            self.backend.add_auth_token(cluster, token)
            self._write_json(200, {"ok": True})
            return
        if self.path == "/message/send":
            payload = self._read_json()
            data = self.backend.send_message(
                cluster=payload.get("cluster", "default"),
                node_id=payload.get("node_id", "node"),
                message=payload.get("message", {}),
            )
            status = 200 if data.get("ok") else 400
            self._write_json(status, data)
            return
        if self.path == "/message/poll":
            payload = self._read_json()
            data = self.backend.poll_messages(
                cluster=payload.get("cluster", "default"),
                recipient_ids=payload.get("recipient_ids", []),
                since_map=payload.get("since", {}),
                limit=payload.get("limit", 100),
            )
            self._write_json(200, data)
            return
        self._write_json(404, {"ok": False, "error": "not found"})


def run_server(host, port, state_path, max_messages):
    backend = DistributedRelayBackend(state_path=state_path, max_messages=max_messages)
    DistributedRelayRequestHandler.backend = backend
    server = ThreadingHTTPServer((host, int(port)), DistributedRelayRequestHandler)
    print(f"[distributed-relay] listening on http://{host}:{int(port)}")
    print(f"[distributed-relay] state path: {state_path}")
    print(f"[distributed-relay] max messages: {int(max_messages)}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def _build_arg_parser():
    parser = argparse.ArgumentParser(description="Distributed communication relay server")
    distributed_cfg = CONFIG.get("distributed", {})
    server_cfg = distributed_cfg.get("server", {}) if isinstance(distributed_cfg.get("server"), dict) else {}
    parser.add_argument("--host", default=server_cfg.get("host", "0.0.0.0"), help="Bind host")
    parser.add_argument(
        "--port", type=int, default=_to_int(server_cfg.get("port", 8877), 8877), help="Bind port"
    )
    parser.add_argument(
        "--state-path",
        default=server_cfg.get("state_path", "output/distributed/relay_state.json"),
        help="State persistence path",
    )
    parser.add_argument(
        "--max-messages",
        type=int,
        default=_to_int(server_cfg.get("max_messages", 20000), 20000),
        help="Max retained messages",
    )
    return parser


def main():
    parser = _build_arg_parser()
    args = parser.parse_args()
    run_server(
        host=args.host,
        port=args.port,
        state_path=args.state_path,
        max_messages=args.max_messages,
    )


if __name__ == "__main__":
    main()
