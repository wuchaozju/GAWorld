#!/usr/bin/env python3
"""OpenClaw ↔ GAWorld Bridge

This standalone script runs on a user's local machine alongside their
OpenClaw agent.  It translates between GAWorld's distributed relay
protocol and OpenClaw's Gateway (OpenResponses) HTTP API so that the
user's OpenClaw persona participates in the social simulation as if it
were a native GAWorld agent.

Typical usage
-------------
    # 1.  Start your OpenClaw agent (default gateway on :18789).
    # 2.  Run the bridge:
    python scripts/openclaw_bridge.py \
        --relay-url http://<relay-server>:8877 \
        --openclaw-url http://127.0.0.1:18789 \
        --soul-path ./examples/openclaw/SOUL.md \
        --name "李明" \
        --cluster default

The bridge will:
    1.  Parse SOUL.md to extract a GAWorld-compatible agent profile.
    2.  Register the agent with the relay server (auto-assigned ID ≥ 1001).
    3.  Enter a loop: poll messages → build a prompt → call OpenClaw → send reply.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import signal
import sys
import time
from typing import Any

import requests

# =====================================================================
# Defaults
# =====================================================================
_DEFAULT_RELAY_URL = "http://127.0.0.1:8877"
_DEFAULT_OPENCLAW_URL = "http://127.0.0.1:18789"
_DEFAULT_CLUSTER = "default"
_DEFAULT_POLL_INTERVAL = 5.0          # seconds between relay polls
_DEFAULT_OPENCLAW_TIMEOUT = 30        # seconds for OpenClaw API calls
_DEFAULT_RELAY_TIMEOUT = 5            # seconds for relay API calls
_DEFAULT_MAX_INBOUND = 5              # max messages per poll cycle
_DEFAULT_MESSAGE_MAX_CHARS = 300      # truncate outbound messages


def _normalize_text(value: Any, max_chars: int = 200) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if max_chars > 0 and len(text) > max_chars:
        text = text[:max_chars].rstrip()
    return text


def _build_public_profile(profile: dict[str, str]) -> dict[str, Any]:
    tags = []
    for raw in (profile.get("job", ""), profile.get("personality", ""), profile.get("values", "")):
        text = _normalize_text(raw, max_chars=24)
        if text and text not in tags:
            tags.append(text)
    return {
        "summary": _normalize_text(profile.get("background_summary", ""), max_chars=180),
        "status": "",
        "focus": _normalize_text(profile.get("job", ""), max_chars=64),
        "tags": tags[:3],
    }


def _build_social_summary(text: str, activity: str = "", ask: str = "") -> dict[str, str]:
    return {
        "summary": _normalize_text(text, max_chars=180),
        "topic": "跨节点交流",
        "status": _normalize_text(activity or "回复消息", max_chars=80),
        "emotion": "平稳",
        "ask": _normalize_text(ask, max_chars=120),
    }


# =====================================================================
# SOUL.md → agent profile
# =====================================================================

def parse_soul_file(path: str) -> dict[str, str]:
    """Extract a GAWorld-compatible profile dict from a SOUL.md file.

    Looks for common headings / YAML front-matter fields:
        name, age, gender, job/occupation, personality, values, background
    Returns a flat dict with those keys (empty string for missing fields).
    """
    if not path or not os.path.isfile(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()

    profile: dict[str, str] = {}

    # --- Try YAML front-matter first (between ---) ---
    fm_match = re.match(r"^---\s*\n(.*?)\n---", text, re.DOTALL)
    if fm_match:
        for line in fm_match.group(1).splitlines():
            if ":" in line:
                key, _, val = line.partition(":")
                profile[key.strip().lower()] = val.strip().strip('"').strip("'")

    # --- Scan markdown headings / bold labels ---
    label_map = {
        "name": "name", "名字": "name", "姓名": "name",
        "age": "age", "年龄": "age",
        "gender": "gender", "性别": "gender",
        "job": "job", "occupation": "job", "职业": "job", "工作": "job",
        "personality": "personality", "性格": "personality", "人格": "personality",
        "values": "values", "价值观": "values",
        "background": "background_summary", "背景": "background_summary",
        "bio": "background_summary", "简介": "background_summary",
    }
    for raw_key, mapped in label_map.items():
        if mapped in profile and profile[mapped]:
            continue
        # Match "## Key" or "**Key**:" patterns
        pattern = rf"(?:^#+\s*{re.escape(raw_key)}\s*$|^\*\*{re.escape(raw_key)}\*\*\s*[:：])"
        match = re.search(pattern, text, re.MULTILINE | re.IGNORECASE)
        if match:
            # Grab the next non-empty line(s) as the value.
            after = text[match.end():].strip()
            value_lines = []
            for ln in after.splitlines():
                ln_s = ln.strip()
                if not ln_s or ln_s.startswith("#"):
                    break
                value_lines.append(ln_s)
            if value_lines:
                profile[mapped] = " ".join(value_lines)[:400]

    # If no name found, use filename stem.
    if not profile.get("name"):
        profile["name"] = os.path.splitext(os.path.basename(path))[0]

    # Also store the full SOUL text as a background summary fallback.
    if not profile.get("background_summary"):
        profile["background_summary"] = text[:400].strip()

    return profile


# =====================================================================
# Relay client (thin wrapper)
# =====================================================================

class RelayClient:
    """Minimal HTTP client for the GAWorld distributed relay server."""

    def __init__(self, base_url: str, cluster: str, token: str = "",
                 timeout: float = _DEFAULT_RELAY_TIMEOUT):
        self.base_url = base_url.rstrip("/")
        self.cluster = cluster
        self.token = token
        self.timeout = timeout
        self.node_id = f"openclaw-{os.getpid()}"
        self.agent_id: int = 0
        self._last_seen: dict[str, int] = {}

    def _headers(self) -> dict[str, str]:
        h: dict[str, str] = {"Content-Type": "application/json"}
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        return h

    def _post(self, path: str, payload: dict) -> dict:
        url = f"{self.base_url}{path}"
        try:
            r = requests.post(url, json=payload, headers=self._headers(),
                              timeout=self.timeout)
            r.raise_for_status()
            return r.json()
        except (requests.RequestException, ValueError) as exc:
            print(f"[bridge] relay POST {path} error: {exc}", file=sys.stderr)
            return {}

    def _get(self, path: str, params: dict | None = None) -> dict:
        url = f"{self.base_url}{path}"
        try:
            r = requests.get(url, params=params, headers=self._headers(),
                             timeout=self.timeout)
            r.raise_for_status()
            return r.json()
        except (requests.RequestException, ValueError) as exc:
            print(f"[bridge] relay GET {path} error: {exc}", file=sys.stderr)
            return {}

    def register(self, profile: dict[str, str]) -> int:
        """Register with the relay.  Returns the assigned agent_id."""
        register_profile = dict(profile)
        register_profile["public_profile"] = _build_public_profile(profile)
        payload = {
            "cluster": self.cluster,
            "node_id": self.node_id,
            "agent_type": "openclaw",
            "token": self.token,
            "agents": [register_profile],
        }
        data = self._post("/register", payload)
        ids = data.get("assigned_ids", [])
        if ids:
            self.agent_id = int(ids[0])
        return self.agent_id

    def poll(self, max_items: int = _DEFAULT_MAX_INBOUND) -> list[dict]:
        if not self.agent_id:
            return []
        since = {str(self.agent_id): self._last_seen.get(str(self.agent_id), 0)}
        payload = {
            "cluster": self.cluster,
            "node_id": self.node_id,
            "recipient_ids": [self.agent_id],
            "since": since,
            "limit": max_items,
        }
        data = self._post("/message/poll", payload)
        messages = data.get("messages", [])
        next_since = data.get("next_since", {})
        if isinstance(next_since, dict):
            for k, v in next_since.items():
                cur = self._last_seen.get(k, 0)
                nv = int(v) if str(v).isdigit() else cur
                if nv > cur:
                    self._last_seen[k] = nv
        return messages if isinstance(messages, list) else []

    def send(
        self,
        to_agent: int,
        text: str,
        day: int = 0,
        time_str: str = "",
        activity: str = "",
        *,
        social_summary: dict[str, Any] | None = None,
        public_state: dict[str, Any] | None = None,
        intent: str = "conversation",
        conversation_id: str = "",
    ) -> bool:
        if not self.agent_id or not text:
            return False
        payload = {
            "cluster": self.cluster,
            "node_id": self.node_id,
            "message": {
                "from_agent": self.agent_id,
                "from_name": "",
                "to_agent": to_agent,
                "kind": "openclaw_reply",
                "text": text[:_DEFAULT_MESSAGE_MAX_CHARS],
                "day": day,
                "time": time_str,
                "activity": activity,
                "conversation_id": conversation_id,
                "intent": intent,
                "visibility": "direct",
                "private_level": "summary",
                "memory_policy": "social_summary",
                "social_summary": social_summary or _build_social_summary(text, activity=activity),
                "public_state": public_state or {"status": _normalize_text(activity or "回复消息", max_chars=80)},
            },
        }
        data = self._post("/message/send", payload)
        return bool(data.get("ok"))

    def get_tick(self) -> dict:
        return self._get("/tick")

    def get_directory(self) -> list[dict]:
        data = self._get("/directory", params={"cluster": self.cluster})
        return data.get("agents", [])


# =====================================================================
# OpenClaw Gateway client
# =====================================================================

class OpenClawClient:
    """Thin wrapper around the OpenClaw OpenResponses HTTP API."""

    def __init__(self, base_url: str, agent_id: str = "",
                 token: str = "", timeout: float = _DEFAULT_OPENCLAW_TIMEOUT):
        self.base_url = base_url.rstrip("/")
        self.agent_id = agent_id
        self.token = token
        self.timeout = timeout

    def send_message(self, text: str, session_key: str = "gaworld") -> str:
        """Send a user message and return the assistant's text reply."""
        url = f"{self.base_url}/v1/responses"
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        if self.agent_id:
            headers["x-openclaw-agent-id"] = self.agent_id
        headers["x-openclaw-session-key"] = session_key

        payload: dict[str, Any] = {
            "model": self.agent_id or "default",
            "input": text,
            "stream": False,
        }

        try:
            r = requests.post(url, json=payload, headers=headers,
                              timeout=self.timeout)
            r.raise_for_status()
            data = r.json()
        except (requests.RequestException, ValueError) as exc:
            print(f"[bridge] openclaw API error: {exc}", file=sys.stderr)
            return ""

        # Extract the text content from the OpenResponses format.
        output = data.get("output", [])
        if isinstance(output, list):
            for item in output:
                if isinstance(item, dict) and item.get("type") == "message":
                    content = item.get("content", [])
                    if isinstance(content, list):
                        parts = [c.get("text", "") for c in content
                                 if isinstance(c, dict) and c.get("type") == "output_text"]
                        if parts:
                            return " ".join(parts).strip()
        # Fallback: try top-level output_text.
        if isinstance(data.get("output_text"), str):
            return data["output_text"].strip()
        return str(data.get("output", "")).strip()


# =====================================================================
# Prompt builder
# =====================================================================

def build_prompt(messages: list[dict], tick: dict, profile: dict,
                 directory: list[dict]) -> str:
    """Build a Chinese-language prompt for the OpenClaw agent.

    Includes simulation context, sender identities, and the messages
    themselves, so that the OpenClaw agent can respond in-character.
    """
    tick_info = tick.get("tick", tick)
    day = tick_info.get("day", "?")
    sim_time = tick_info.get("time", "?")
    bg = tick_info.get("background", "")

    # Build a quick directory lookup.
    dir_map: dict[int, str] = {}
    for entry in directory:
        aid = entry.get("agent_id", 0)
        name = entry.get("name", f"Agent {aid}")
        if aid:
            dir_map[int(aid)] = name

    parts: list[str] = []
    parts.append("你正在参与一个城市社会模拟。请以你的人设身份自然地回应以下消息。")
    parts.append(f"当前模拟时间：第 {day} 天，{sim_time}。")
    if bg:
        parts.append(f"背景设定：{bg}")
    parts.append(f"你的身份：{profile.get('name', '未知')}，{profile.get('job', '')}。")
    parts.append("")
    parts.append("收到的消息：")
    for msg in messages:
        sender_id = msg.get("from_agent", 0)
        sender_name = msg.get("from_name") or dir_map.get(int(sender_id), f"Agent {sender_id}")
        text = msg.get("text", "")
        activity = msg.get("activity", "")
        social_summary = msg.get("social_summary", {}) if isinstance(msg.get("social_summary"), dict) else {}
        line = f"- {sender_name}"
        if activity:
            line += f"（正在{activity}）"
        line += f"：{text}"
        extras = []
        topic = _normalize_text(social_summary.get("topic", ""), max_chars=32)
        status = _normalize_text(social_summary.get("status", ""), max_chars=48)
        ask = _normalize_text(social_summary.get("ask", ""), max_chars=64)
        if topic:
            extras.append(f"主题：{topic}")
        if status:
            extras.append(f"状态：{status}")
        if ask:
            extras.append(f"期待：{ask}")
        if extras:
            line += f"（{'；'.join(extras)}）"
        parts.append(line)
    parts.append("")
    parts.append("请用简短的中文回复（1-3句话），保持你的人物性格，自然地参与对话。")
    return "\n".join(parts)


# =====================================================================
# Main loop
# =====================================================================

_running = True


def _handle_signal(sig, frame):
    global _running
    _running = False
    print("\n[bridge] shutting down…")


def run_bridge(args):
    global _running

    # --- Parse SOUL.md ---
    profile = parse_soul_file(args.soul_path)
    if args.name:
        profile["name"] = args.name
    if args.age:
        profile["age"] = args.age
    if args.gender:
        profile["gender"] = args.gender
    if args.job:
        profile["job"] = args.job

    agent_name = profile.get("name", "OpenClaw Agent")
    print(f"[bridge] agent profile: {agent_name}")
    print(f"[bridge] relay: {args.relay_url}  cluster: {args.cluster}")
    print(f"[bridge] openclaw: {args.openclaw_url}")

    # --- Init clients ---
    relay = RelayClient(
        base_url=args.relay_url,
        cluster=args.cluster,
        token=args.token,
        timeout=args.relay_timeout,
    )
    openclaw = OpenClawClient(
        base_url=args.openclaw_url,
        agent_id=args.openclaw_agent_id,
        token=args.openclaw_token,
        timeout=args.openclaw_timeout,
    )

    # --- Register ---
    assigned_id = relay.register(profile)
    if not assigned_id:
        print("[bridge] ERROR: registration failed — is the relay server running?",
              file=sys.stderr)
        sys.exit(1)
    print(f"[bridge] registered as agent #{assigned_id}")

    # Update from_name on the relay client for outbound messages.
    def _send_with_name(
        to_agent,
        text,
        day=0,
        time_str="",
        activity="",
        *,
        social_summary=None,
        public_state=None,
        intent="conversation",
        conversation_id="",
    ):
        if not relay.agent_id or not text:
            return False
        payload = {
            "cluster": relay.cluster,
            "node_id": relay.node_id,
            "message": {
                "from_agent": relay.agent_id,
                "from_name": agent_name,
                "to_agent": to_agent,
                "kind": "openclaw_reply",
                "text": text[:_DEFAULT_MESSAGE_MAX_CHARS],
                "day": day,
                "time": time_str,
                "activity": activity,
                "conversation_id": conversation_id,
                "intent": intent,
                "visibility": "direct",
                "private_level": "summary",
                "memory_policy": "social_summary",
                "social_summary": social_summary or _build_social_summary(text, activity=activity),
                "public_state": public_state or {"status": _normalize_text(activity or "回复消息", max_chars=80)},
            },
        }
        data = relay._post("/message/send", payload)
        return bool(data.get("ok"))

    relay.send = _send_with_name

    # --- Main loop ---
    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    cycle = 0
    while _running:
        cycle += 1
        try:
            # 1. Get current tick state.
            tick = relay.get_tick()

            # 2. Poll inbound messages.
            messages = relay.poll(max_items=args.max_inbound)

            if messages:
                tick_info = tick.get("tick", tick)
                day = tick_info.get("day", 0)
                sim_time = tick_info.get("time", "")

                # 3. Get directory for sender name resolution.
                directory = relay.get_directory()

                # 4. Build prompt and call OpenClaw.
                prompt = build_prompt(messages, tick, profile, directory)
                print(f"[bridge] cycle {cycle}: {len(messages)} message(s) → calling OpenClaw…")

                reply = openclaw.send_message(prompt, session_key=f"gaworld-{day}-{sim_time}")

                if reply:
                    print(f"[bridge] OpenClaw reply: {reply[:80]}…" if len(reply) > 80
                          else f"[bridge] OpenClaw reply: {reply}")

                    # 5. Send reply back to each sender.
                    replied_to: set[int] = set()
                    for msg in messages:
                        sender_id = int(msg.get("from_agent", 0))
                        if sender_id <= 0 or sender_id in replied_to:
                            continue
                        relay.send(
                            to_agent=sender_id,
                            text=reply,
                            day=day,
                            time_str=sim_time,
                            activity="回复消息",
                            social_summary=_build_social_summary(
                                reply,
                                activity="回复消息",
                                ask="继续保持交流",
                            ),
                            public_state={"status": "正在参与跨节点交流"},
                            intent="conversation",
                            conversation_id=_normalize_text(msg.get("conversation_id", ""), max_chars=64),
                        )
                        replied_to.add(sender_id)
                        print(f"[bridge]   → replied to agent #{sender_id}")
                else:
                    print(f"[bridge] cycle {cycle}: OpenClaw returned empty reply")
            else:
                if cycle % 12 == 1:  # Periodic heartbeat log.
                    print(f"[bridge] cycle {cycle}: no new messages, waiting…")

        except Exception as exc:
            print(f"[bridge] cycle {cycle} error: {exc}", file=sys.stderr)

        # 6. Wait for next poll cycle.
        time.sleep(args.poll_interval)

    print("[bridge] stopped.")


# =====================================================================
# CLI
# =====================================================================

def main():
    parser = argparse.ArgumentParser(
        description="OpenClaw ↔ GAWorld Bridge — connect your OpenClaw agent to the social simulation",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Basic usage with a SOUL.md file:
  python scripts/openclaw_bridge.py --soul-path ./examples/openclaw/SOUL.md --name "李明"

  # Connect to a remote relay server with authentication:
  python scripts/openclaw_bridge.py \\
      --relay-url http://192.168.1.100:8877 \\
      --token my-secret-token \\
      --soul-path ./examples/openclaw/SOUL.md

  # Override profile fields directly:
  python scripts/openclaw_bridge.py \\
      --name "王芳" --age 28 --gender 女 --job "软件工程师"
""",
    )

    # Relay server options
    relay_group = parser.add_argument_group("Relay Server")
    relay_group.add_argument("--relay-url", default=_DEFAULT_RELAY_URL,
                             help=f"Relay server URL (default: {_DEFAULT_RELAY_URL})")
    relay_group.add_argument("--cluster", default=_DEFAULT_CLUSTER,
                             help=f"Cluster name (default: {_DEFAULT_CLUSTER})")
    relay_group.add_argument("--token", default=os.environ.get("GAWORLD_TOKEN", ""),
                             help="Auth token for relay server (or set GAWORLD_TOKEN env)")

    # OpenClaw options
    oc_group = parser.add_argument_group("OpenClaw")
    oc_group.add_argument("--openclaw-url", default=_DEFAULT_OPENCLAW_URL,
                          help=f"OpenClaw Gateway URL (default: {_DEFAULT_OPENCLAW_URL})")
    oc_group.add_argument("--openclaw-agent-id", default="",
                          help="OpenClaw agent ID header (x-openclaw-agent-id)")
    oc_group.add_argument("--openclaw-token", default=os.environ.get("OPENCLAW_TOKEN", ""),
                          help="OpenClaw Gateway bearer token (or set OPENCLAW_TOKEN env)")
    oc_group.add_argument("--openclaw-timeout", type=float, default=_DEFAULT_OPENCLAW_TIMEOUT,
                          help=f"OpenClaw API timeout in seconds (default: {_DEFAULT_OPENCLAW_TIMEOUT})")

    # Agent profile
    profile_group = parser.add_argument_group("Agent Profile")
    profile_group.add_argument("--soul-path", default="",
                               help="Path to SOUL.md file for profile extraction")
    profile_group.add_argument("--name", default="",
                               help="Agent display name (overrides SOUL.md)")
    profile_group.add_argument("--age", default="",
                               help="Agent age (overrides SOUL.md)")
    profile_group.add_argument("--gender", default="",
                               help="Agent gender (overrides SOUL.md)")
    profile_group.add_argument("--job", default="",
                               help="Agent job/occupation (overrides SOUL.md)")

    # Runtime
    runtime_group = parser.add_argument_group("Runtime")
    runtime_group.add_argument("--poll-interval", type=float, default=_DEFAULT_POLL_INTERVAL,
                               help=f"Seconds between relay polls (default: {_DEFAULT_POLL_INTERVAL})")
    runtime_group.add_argument("--max-inbound", type=int, default=_DEFAULT_MAX_INBOUND,
                               help=f"Max inbound messages per cycle (default: {_DEFAULT_MAX_INBOUND})")
    runtime_group.add_argument("--relay-timeout", type=float, default=_DEFAULT_RELAY_TIMEOUT,
                               help=f"Relay API timeout in seconds (default: {_DEFAULT_RELAY_TIMEOUT})")

    args = parser.parse_args()

    if not args.soul_path and not args.name:
        parser.error("至少需要提供 --soul-path 或 --name 参数")

    run_bridge(args)


if __name__ == "__main__":
    main()
