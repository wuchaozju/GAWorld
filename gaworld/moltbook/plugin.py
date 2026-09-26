"""MoltbookPlugin — a connected resident's simulated day becomes a Moltbook post.

Hooks:

- ``on_simulation_start`` (observe): open one client per connected agent and
  ask Moltbook whether the account has been claimed. An unclaimed account is
  logged once and then left alone — Moltbook refuses its posts.
- ``on_agent_post_step`` (observe): collect the step (activity, action,
  reflection, place) into the agent's day buffer.
- ``on_day_end`` (observe): turn the buffer into one post — written in the
  resident's voice by the model when one is available, a plain digest
  otherwise — spaced by wall-clock time to respect Moltbook's
  one-post-per-30-minutes rule. Simulated days pass far faster than that, so a
  day that cannot post yet keeps its buffer and joins the next allowed post
  rather than being dropped. After posting, the resident reads the feed, so
  the record shows what it saw as well as what it said.

Every call that reaches Moltbook, and every refusal, lands in
``output/moltbook/agent_<id>/actions.jsonl`` (what the workbench shows) and
in the recorder's ``moltbook.actions`` table (the cross-plugin timeline).

The switch itself is not here: it lives in ``data/moltbook_accounts.json`` and
is flipped from Agent Studio. This plugin only reads it, once, at start.
"""

from __future__ import annotations

import json
import re
import time

from gaworld.kernel import Plugin
from gaworld.logging_setup import get_logger
from gaworld.moltbook import accounts
from gaworld.moltbook import log as action_log
from gaworld.moltbook.client import (
    DEFAULT_BASE_URL,
    MoltbookClient,
    MoltbookError,
    numeric_answer,
    post_id_of,
    verification_challenge,
)

_LOG = get_logger("gaworld.moltbook.plugin")

#: Steps kept per agent between posts — two days of half-hour ticks.
_BUFFER_LIMIT = 96
#: How much of a step's reflection goes into the digest / prompt.
_REFLECTION_CHARS = 120
#: Stay well under Moltbook's body cap.
_CONTENT_CHARS = 1800
_TITLE_CHARS = 120

_JSON_RE = re.compile(r"\{.*\}", re.S)


def _default_client_factory(base_url, api_key, timeout):
    return MoltbookClient(base_url=base_url, api_key=api_key, timeout=timeout)


def _agent_id(agent):
    try:
        return int((agent or {}).get("id"))
    except (TypeError, ValueError):
        return None


class MoltbookPlugin(Plugin):
    id = "moltbook"

    def __init__(self, client_factory=None, now=None):
        # Both injectable so the tests never open a socket or wait 30 minutes.
        self._client_factory = client_factory or _default_client_factory
        self._now = now or time.time
        self._cfg = {}
        self._clients = {}
        self._last_post = {}

    # -- lifecycle -----------------------------------------------------------

    def setup(self, ctx):
        self._cfg = dict(ctx.config.get("moltbook", {}) or {})
        if not self._cfg.get("enabled", True):
            return
        ctx.bus.on("on_simulation_start", self._on_start)
        ctx.bus.on("on_agent_post_step", self._on_post_step)
        ctx.bus.on("on_day_end", self._on_day_end)

    def teardown(self, ctx):
        self._clients = {}

    def _opt(self, key, default):
        value = self._cfg.get(key)
        return default if value is None else value

    # -- hooks ---------------------------------------------------------------

    def _on_start(self, hook_ctx):
        sim = hook_ctx["sim"]
        connected = accounts.connected(self._opt("accounts_path", accounts.DEFAULT_PATH))
        if not connected:
            return
        for agent in hook_ctx.get("agents") or sim.agents:
            agent_id = _agent_id(agent)
            record = connected.get(agent_id)
            if record is None:
                continue
            client = self._client_factory(
                self._opt("base_url", DEFAULT_BASE_URL),
                record["api_key"],
                float(self._opt("timeout_seconds", 20)),
            )
            self._clients[agent_id] = client
            ext = sim.agent_ext(agent, self.id)
            ext["name"] = str(record.get("name") or "")
            ext["buffer"] = []
            try:
                status = client.status()["status"]
            except MoltbookError as exc:
                ext["status"] = "unknown"
                self._record(
                    sim, agent_id, kind="error", ok=False,
                    summary=f"查询账号状态失败：{exc}",
                    detail={"op": "status", "http_status": exc.status},
                )
                continue
            ext["status"] = status
            accounts.set_status(agent_id, status, path=self._opt("accounts_path", accounts.DEFAULT_PATH))
            if status == accounts.STATUS_CLAIMED:
                summary = f"账号 {ext['name']} 已认领，仿真期间会把每天写成帖子"
            else:
                summary = f"账号 {ext['name']} 状态为 {status}：认领之前 Moltbook 不接受发帖"
            self._record(sim, agent_id, kind="status", ok=True, summary=summary, detail={"status": status})

    def _on_post_step(self, hook_ctx):
        agent = hook_ctx.get("agent") or {}
        agent_id = _agent_id(agent)
        if agent_id not in self._clients:
            return
        step = hook_ctx.get("step") or {}
        buffer = hook_ctx["sim"].agent_ext(agent, self.id).setdefault("buffer", [])
        buffer.append(
            {
                "day": hook_ctx.get("day"),
                "time": str(hook_ctx.get("time_str") or ""),
                "activity": str(step.get("activity") or ""),
                "action": str(step.get("action") or ""),
                "reflection": str(step.get("reflection") or "")[:_REFLECTION_CHARS],
                "location": str(step.get("resolved_location") or step.get("location") or ""),
            }
        )
        del buffer[:-_BUFFER_LIMIT]

    def _on_day_end(self, hook_ctx):
        sim = hook_ctx["sim"]
        day = hook_ctx.get("day")
        daily_logs = hook_ctx.get("daily_logs") or {}
        for agent_id, client in list(self._clients.items()):
            agent = sim.agents_by_id.get(agent_id)
            if agent is None:
                continue
            ext = sim.agent_ext(agent, self.id)
            if ext.get("status") != accounts.STATUS_CLAIMED:
                continue
            buffer = list(ext.get("buffer") or [])
            brief = ""
            if not buffer:
                # Fast-forward / coarse runs never tick, so the day arrives as
                # one brief in daily_logs instead of a list of steps.
                brief = str(daily_logs.get(agent_id) or "").strip()
                if not brief:
                    continue
            now = self._now()
            last = self._last_post.get(agent_id)
            if last is not None and now - last < float(self._opt("min_post_interval_seconds", 1800)):
                continue
            title, content = self._compose(sim, agent, day, buffer, brief)
            # Set before the call: a refusal must not be retried ten seconds
            # later on the next simulated day.
            self._last_post[agent_id] = now
            submolt = str(self._opt("submolt", "general"))
            try:
                payload = client.create_post(submolt, title, content)
            except MoltbookError as exc:
                self._record(
                    sim, agent_id, kind="error", ok=False,
                    summary=f"发帖失败：{exc}",
                    detail={"op": "post", "title": title, "http_status": exc.status},
                    day=day,
                )
                continue
            ext["buffer"] = []
            self._record(
                sim, agent_id, kind="post", ok=True, summary=title,
                detail={"post_id": post_id_of(payload), "submolt": submolt, "content": content},
                day=day,
            )
            challenge = verification_challenge(payload)
            if challenge:
                self._answer_challenge(sim, agent_id, client, challenge, day)
            if self._opt("read_feed", True):
                self._read_feed(sim, agent_id, client, day)

    # -- pieces --------------------------------------------------------------

    def _read_feed(self, sim, agent_id, client, day):
        try:
            posts = client.feed(limit=int(self._opt("feed_limit", 5)))
        except MoltbookError as exc:
            self._record(
                sim, agent_id, kind="error", ok=False,
                summary=f"读取信息流失败：{exc}",
                detail={"op": "feed", "http_status": exc.status}, day=day,
            )
            return
        seen = []
        for post in posts:
            author = post.get("author") if isinstance(post.get("author"), dict) else {}
            submolt = post.get("submolt") if isinstance(post.get("submolt"), dict) else {}
            seen.append(
                {
                    "id": str(post.get("id") or ""),
                    "title": str(post.get("title") or "")[:_TITLE_CHARS],
                    "author": str(author.get("name") or post.get("author_name") or ""),
                    "submolt": str(submolt.get("name") or post.get("submolt_name") or post.get("submolt") or ""),
                }
            )
        titles = "；".join(item["title"] for item in seen if item["title"])
        self._record(
            sim, agent_id, kind="feed", ok=True,
            summary=f"浏览了信息流的 {len(seen)} 篇帖子" + (f"：{titles}" if titles else ""),
            detail={"posts": seen}, day=day,
        )

    def _answer_challenge(self, sim, agent_id, client, challenge, day):
        answer = None
        if sim.llm is not None:
            prompt = (
                "下面是一道验证题，请计算并只回答最终数字（保留两位小数），不要解释。\n"
                f"{challenge['challenge_text']}"
            )
            try:
                answer = numeric_answer(sim.llm(prompt, task="moltbook_verify", agent_id=agent_id))
            except Exception as exc:  # noqa: BLE001 - a model failure is a log row, not a crash
                _LOG.warning("moltbook: verification prompt failed for agent %s: %s", agent_id, exc)
        if answer is None:
            self._record(
                sim, agent_id, kind="error", ok=False,
                summary="发帖后的验证题没有作答（没有可用模型），帖子可能不会公开",
                detail={"op": "verify", "challenge": challenge["challenge_text"]}, day=day,
            )
            return
        try:
            client.verify(challenge["verification_code"], answer)
        except MoltbookError as exc:
            self._record(
                sim, agent_id, kind="error", ok=False,
                summary=f"验证题作答被拒绝：{exc}",
                detail={"op": "verify", "answer": answer, "http_status": exc.status}, day=day,
            )
            return
        self._record(
            sim, agent_id, kind="verify", ok=True,
            summary=f"通过了发帖验证（答案 {answer}）",
            detail={"answer": answer, "challenge": challenge["challenge_text"]}, day=day,
        )

    def _compose(self, sim, agent, day, buffer, brief):
        """``(title, content)`` for the day — model-written when possible."""
        name = str(agent.get("name") or f"agent {agent.get('id')}")
        city = str(sim.config.get("city") or agent.get("residence") or "")
        lines = []
        for step in buffer:
            line = f"{step['time']} {step['activity']}：{step['action']}".strip()
            if step.get("reflection"):
                line += f"——{step['reflection']}"
            lines.append(line)
        digest = "\n".join(lines) if lines else brief
        digest = digest[:_CONTENT_CHARS]
        title = f"第 {day} 天：{name} 在 {city} 的一天" if city else f"第 {day} 天：{name} 的一天"
        if sim.llm is None or not self._opt("compose_with_llm", True):
            return title, digest
        prompt = (
            f"你是{name}"
            + (f"，{agent.get('age')}岁" if agent.get("age") else "")
            + (f"，{agent.get('job')}" if agent.get("job") else "")
            + (f"，住在{city}" if city else "")
            + "。你在 Moltbook（一个 AI 智能体的社交网络）上有自己的账号。\n"
            f"下面是你今天（第 {day} 天）的经历：\n{digest}\n\n"
            "请以第一人称写一篇发到 Moltbook 的短帖：标题一句话（不超过 40 字），"
            "正文 3 到 6 句，讲今天最值得说的事和你的感受，不要逐条复述。\n"
            '只输出 JSON：{"title": "...", "content": "..."}'
        )
        try:
            parsed = _parse_post(sim.llm(prompt, task="moltbook_post", agent_id=agent.get("id")))
        except Exception as exc:  # noqa: BLE001 - fall back to the digest, never lose the day
            _LOG.warning("moltbook: model post for agent %s failed (%s); using the digest", agent.get("id"), exc)
            parsed = None
        if parsed is None:
            return title, digest
        return parsed

    def _record(self, sim, agent_id, *, kind, ok, summary, detail=None, day=None):
        row = {
            "kind": kind,
            "ok": bool(ok),
            "summary": str(summary),
            "detail": detail or {},
            "day": sim.clock.day if day is None else day,
            "time": sim.clock.time_str,
        }
        action_log.append(agent_id, row, root=self._opt("log_dir", action_log.DEFAULT_DIR))
        sim.recorder.record("moltbook.actions", {"agent_id": agent_id, **row})


def _parse_post(reply):
    """``(title, content)`` from a model reply, or ``None`` when it is unusable."""
    text = str(reply or "").strip()
    if not text:
        return None
    match = _JSON_RE.search(text)
    if match:
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError:
            data = None
        if isinstance(data, dict):
            title = str(data.get("title") or "").strip()
            content = str(data.get("content") or "").strip()
            if title and content:
                return title[:_TITLE_CHARS], content[:_CONTENT_CHARS]
    # Plain prose: first line is the title, the rest the body.
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) >= 2:
        return lines[0][:_TITLE_CHARS], "\n".join(lines[1:])[:_CONTENT_CHARS]
    return None
