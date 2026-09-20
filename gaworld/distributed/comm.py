import os
import random
import re
import socket
import time
from threading import RLock

import requests


def _to_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def _to_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _clamp(value, low, high):
    return max(low, min(high, value))


def _normalize_text(text, max_chars=160):
    cleaned = re.sub(r"\s+", " ", str(text or "")).strip()
    if max_chars > 0 and len(cleaned) > max_chars:
        cleaned = cleaned[:max_chars].rstrip()
    return cleaned


def _emotion_label(value):
    score = _clamp(_to_float(value, 0.5), 0.0, 1.0)
    if score >= 0.72:
        return "积极"
    if score >= 0.56:
        return "平稳"
    if score >= 0.38:
        return "谨慎"
    return "低落"


def _infer_topic(activity, outcome):
    blob = f"{activity} {outcome}"
    rules = [
        (("工作", "项目", "任务", "加班"), "工作进展"),
        (("通勤", "出行", "路上", "移动"), "出行安排"),
        (("学习", "备课", "研究", "面试"), "学习成长"),
        (("家", "休息", "睡前", "个人时间"), "个人生活"),
        (("朋友", "聊天", "社交", "消息"), "社交互动"),
    ]
    for needles, topic in rules:
        if any(token in blob for token in needles):
            return topic
    return "近况更新"


def _infer_intent(activity, reflection, outcome):
    blob = f"{activity} {reflection} {outcome}"
    if any(token in blob for token in ("请教", "建议", "怎么看", "想听听")):
        return "advice_request"
    if any(token in blob for token in ("帮助", "协作", "配合")):
        return "collaboration"
    if any(token in blob for token in ("消息", "回复", "联系")):
        return "conversation"
    if any(token in blob for token in ("比较", "选择", "what-if", "反事实")):
        return "what_if_share"
    return "status_update"


def _build_public_profile(agent):
    if not isinstance(agent, dict):
        return {}
    tags = []
    for raw in (agent.get("job", ""), agent.get("personality", ""), agent.get("values", "")):
        text = _normalize_text(raw, max_chars=24)
        if text and text not in tags:
            tags.append(text)
    summary_source = agent.get("daily_life") or agent.get("background_summary") or agent.get("personality", "")
    return {
        "summary": _normalize_text(summary_source, max_chars=180),
        "status": "",
        "focus": _normalize_text(agent.get("job", ""), max_chars=64),
        "tags": tags[:3],
    }


def _build_public_state(agent, activity="", reflection=""):
    state = (agent or {}).get("state", {})
    if not isinstance(state, dict):
        state = {}
    public_state = {}
    for key in ("emotion", "stress", "social_need", "energy", "econ_security"):
        value = state.get(key)
        try:
            public_state[key] = round(float(value), 4)
        except (TypeError, ValueError):
            continue
    public_state["status"] = _normalize_text(reflection or activity, max_chars=80)
    return public_state


def _build_social_summary(agent, activity, reflection, outcome, max_chars=160):
    refl = _normalize_text(reflection, max_chars=max_chars)
    out = _normalize_text(outcome, max_chars=max_chars)
    summary_text = refl or out or "完成了一个时间片行动。"
    state = (agent or {}).get("state", {})
    if not isinstance(state, dict):
        state = {}
    return {
        "summary": summary_text,
        "topic": _infer_topic(activity, outcome),
        "status": _normalize_text(activity or outcome, max_chars=72),
        "emotion": _emotion_label(state.get("emotion", 0.5)),
        "ask": "",
    }


def _coerce_agent_ids(values):
    if values is None:
        return []
    if not isinstance(values, (list, tuple, set)):
        values = [values]
    ids = []
    seen = set()
    for raw in values:
        aid = _to_int(raw, 0)
        if aid <= 0 or aid in seen:
            continue
        seen.add(aid)
        ids.append(aid)
    return ids


def extract_sender_agent_ids(messages):
    ids = []
    seen = set()
    for msg in messages or []:
        if not isinstance(msg, dict):
            continue
        aid = _to_int(msg.get("from_agent"), 0)
        if aid <= 0 or aid in seen:
            continue
        seen.add(aid)
        ids.append(aid)
    return ids


def format_inbox_context(messages, max_items=3):
    if not messages:
        return ""
    chunks = []
    for msg in list(messages)[: max(1, int(max_items))]:
        if not isinstance(msg, dict):
            continue
        sender = str(msg.get("from_name", "")).strip()
        sender_id = _to_int(msg.get("from_agent"), 0)
        text = _normalize_text(msg.get("text", ""), max_chars=80)
        social_summary = msg.get("social_summary", {}) if isinstance(msg.get("social_summary"), dict) else {}
        topic = _normalize_text(social_summary.get("topic", ""), max_chars=24)
        status = _normalize_text(social_summary.get("status", ""), max_chars=40)
        ask = _normalize_text(social_summary.get("ask", ""), max_chars=40)
        if not text:
            continue
        sender_tag = sender if sender else (f"Agent {sender_id}" if sender_id > 0 else "远端智能体")
        details = []
        if topic:
            details.append(f"主题{topic}")
        if status:
            details.append(f"状态{status}")
        if ask:
            details.append(f"想法{ask}")
        if details:
            chunks.append(f"{sender_tag}说：{text}（{'，'.join(details)}）")
        else:
            chunks.append(f"{sender_tag}说：{text}")
    if not chunks:
        return ""
    return "跨机器通信消息：" + "；".join(chunks)


class DistributedRelayClient:
    def __init__(self, config):
        cfg = dict(config or {})
        relay_cfg = cfg.get("relay", {}) if isinstance(cfg.get("relay"), dict) else {}
        self.enabled = bool(cfg.get("enabled", False))
        self.cluster = str(cfg.get("cluster", "default")).strip() or "default"
        self.node_id = str(cfg.get("node_id", "")).strip() or self._default_node_id()
        self.base_url = str(relay_cfg.get("base_url", "http://127.0.0.1:8877")).rstrip("/")
        self.timeout = max(0.5, _to_float(relay_cfg.get("timeout", 3), 3.0))
        self.send_probability = _clamp(_to_float(cfg.get("send_probability", 0.18), 0.18), 0.0, 1.0)
        self.max_inbound_per_step = max(1, _to_int(cfg.get("max_inbound_per_step", 3), 3))
        self.max_outbound_per_step = max(0, _to_int(cfg.get("max_outbound_per_step", 1), 1))
        self.message_max_chars = max(20, _to_int(cfg.get("message_max_chars", 160), 160))
        self.fail_fast = bool(cfg.get("fail_fast", False))
        self.peer_agent_ids = _coerce_agent_ids(cfg.get("peer_agent_ids", []))
        twin_cfg = cfg.get("personal_twin", {}) if isinstance(cfg.get("personal_twin"), dict) else {}
        self.personal_twin_enabled = bool(twin_cfg.get("enabled", False))
        self._lock = RLock()
        self._last_seen = {}
        self._directory = {}
        self._local_agent_ids = set()
        self.last_error = ""

    def _default_node_id(self):
        host = socket.gethostname() or "node"
        return f"{host}-{os.getpid()}"

    def _request_json(self, method, path, payload=None, params=None):
        url = f"{self.base_url}{path}"
        try:
            response = requests.request(
                method=method.upper(),
                url=url,
                json=payload,
                params=params,
                timeout=self.timeout,
            )
            response.raise_for_status()
            data = response.json()
            if isinstance(data, dict):
                self.last_error = ""
                return data
            self.last_error = f"invalid json payload from {url}"
        except (requests.RequestException, ValueError) as exc:
            # ValueError covers JSONDecodeError raised by response.json().
            self.last_error = str(exc)
            if self.fail_fast:
                raise
        return {}

    def _update_directory(self, agents):
        if not isinstance(agents, list):
            return
        with self._lock:
            merged = {}
            for item in agents:
                if not isinstance(item, dict):
                    continue
                aid = _to_int(item.get("agent_id", item.get("id")), 0)
                if aid <= 0:
                    continue
                merged[aid] = dict(item)
            self._directory = merged

    def register_agents(self, agents):
        if not self.enabled:
            return False
        register_items = []
        local_ids = []
        agent_type = "personal_twin" if self.personal_twin_enabled else "native"
        for agent in agents or []:
            if not isinstance(agent, dict):
                continue
            aid = _to_int(agent.get("id"), 0)
            if aid <= 0:
                continue
            local_ids.append(aid)
            register_items.append({
                "id": aid,
                "name": str(agent.get("name", aid)),
                "age": _normalize_text(agent.get("age", ""), max_chars=8),
                "gender": _normalize_text(agent.get("gender", ""), max_chars=8),
                "job": _normalize_text(agent.get("job", ""), max_chars=64),
                "personality": _normalize_text(agent.get("personality", ""), max_chars=200),
                "values": _normalize_text(agent.get("values", ""), max_chars=200),
                "background_summary": _normalize_text(
                    agent.get("daily_life") or agent.get("background_summary", ""),
                    max_chars=400,
                ),
                "public_profile": _build_public_profile(agent),
                "public_state": _build_public_state(agent),
            })
        with self._lock:
            self._local_agent_ids = set(local_ids)
        payload = {
            "cluster": self.cluster,
            "node_id": self.node_id,
            "agent_type": agent_type,
            "agents": register_items,
            "timestamp": time.time(),
        }
        data = self._request_json("POST", "/register", payload=payload)
        self._update_directory(data.get("directory", []))
        return bool(data.get("ok"))

    def refresh_directory(self):
        if not self.enabled:
            return {}
        data = self._request_json("GET", "/directory", params={"cluster": self.cluster})
        self._update_directory(data.get("agents", []))
        return self.directory_snapshot()

    def directory_snapshot(self):
        with self._lock:
            return {int(k): dict(v) for k, v in self._directory.items()}

    def available_remote_agent_ids(self, exclude=None):
        exclude_set = set(_coerce_agent_ids(exclude))
        with self._lock:
            local = set(self._local_agent_ids)
        if self.peer_agent_ids:
            return [aid for aid in self.peer_agent_ids if aid not in local and aid not in exclude_set]
        directory = self.directory_snapshot()
        return sorted(
            aid for aid in directory.keys()
            if aid not in local and aid not in exclude_set
        )

    def poll_messages(self, local_agent_ids, day=None, time_str=""):
        grouped = {aid: [] for aid in _coerce_agent_ids(local_agent_ids)}
        if not self.enabled or not grouped:
            return grouped
        with self._lock:
            since = {
                str(aid): _to_int(self._last_seen.get(str(aid), 0), 0)
                for aid in grouped.keys()
            }
        payload = {
            "cluster": self.cluster,
            "node_id": self.node_id,
            "day": _to_int(day, 0),
            "time": str(time_str or ""),
            "recipient_ids": list(grouped.keys()),
            "since": since,
            "limit": max(10, self.max_inbound_per_step * max(1, len(grouped))),
        }
        data = self._request_json("POST", "/message/poll", payload=payload)
        messages = data.get("messages", [])
        next_since = data.get("next_since", {})
        if isinstance(next_since, dict):
            with self._lock:
                for key, value in next_since.items():
                    aid = _to_int(key, 0)
                    if aid <= 0:
                        continue
                    cur = _to_int(self._last_seen.get(str(aid), 0), 0)
                    nxt = _to_int(value, cur)
                    if nxt > cur:
                        self._last_seen[str(aid)] = nxt
        per_agent_count = {aid: 0 for aid in grouped}
        for msg in messages if isinstance(messages, list) else []:
            if not isinstance(msg, dict):
                continue
            aid = _to_int(msg.get("to_agent"), 0)
            if aid not in grouped:
                continue
            if per_agent_count[aid] >= self.max_inbound_per_step:
                continue
            grouped[aid].append(msg)
            per_agent_count[aid] += 1
        return grouped

    def update_tick(self, day, time_str, background=""):
        if not self.enabled:
            return {}
        payload = {
            "day": _to_int(day, 0),
            "time": str(time_str or ""),
            "background": _normalize_text(background, max_chars=600),
        }
        return self._request_json("POST", "/tick", payload=payload)

    def _build_message_text(self, activity, reflection, outcome):
        parts = []
        act = _normalize_text(activity, max_chars=36)
        if act:
            parts.append(f"我在{act}")
        refl = _normalize_text(reflection, max_chars=self.message_max_chars)
        out = _normalize_text(outcome, max_chars=self.message_max_chars)
        if refl:
            parts.append(f"感受是：{refl}")
        elif out:
            parts.append(f"结果是：{out}")
        text = "；".join(parts)
        if not text:
            text = "我完成了一个时间片行动。"
        return _normalize_text(text, max_chars=self.message_max_chars)

    def send_agent_messages(self, agent, day, time_str, activity, reflection, outcome):
        if not self.enabled or self.max_outbound_per_step <= 0:
            return []
        if random.random() > self.send_probability:
            return []
        sender_id = _to_int((agent or {}).get("id"), 0)
        if sender_id <= 0:
            return []
        targets = self.available_remote_agent_ids(exclude=[sender_id])
        if not targets:
            return []
        random.shuffle(targets)
        selected = targets[: self.max_outbound_per_step]
        text = self._build_message_text(activity, reflection, outcome)
        social_summary = _build_social_summary(
            agent,
            activity=activity,
            reflection=reflection,
            outcome=outcome,
            max_chars=self.message_max_chars,
        )
        public_profile = dict(_build_public_profile(agent))
        if isinstance((agent or {}).get("public_profile"), dict):
            public_profile.update((agent or {}).get("public_profile"))
        public_state = _build_public_state(agent, activity=activity, reflection=reflection)
        intent = _infer_intent(activity, reflection, outcome)
        sender_name = str((agent or {}).get("name", sender_id))
        sent = []
        for target_id in selected:
            payload = {
                "cluster": self.cluster,
                "node_id": self.node_id,
                "message": {
                    "from_agent": sender_id,
                    "from_name": sender_name,
                    "to_agent": int(target_id),
                    "kind": "agent_update",
                    "text": text,
                    "day": _to_int(day, 0),
                    "time": str(time_str),
                    "activity": _normalize_text(activity, max_chars=48),
                    "conversation_id": f"{self.cluster}:{min(sender_id, int(target_id))}:{max(sender_id, int(target_id))}:d{_to_int(day, 0)}",
                    "intent": intent,
                    "visibility": "direct",
                    "private_level": "summary",
                    "memory_policy": "social_summary",
                    "social_summary": social_summary,
                    "public_profile": public_profile,
                    "public_state": public_state,
                },
            }
            data = self._request_json("POST", "/message/send", payload=payload)
            msg = data.get("message")
            if isinstance(msg, dict):
                sent.append(msg)
        return sent
