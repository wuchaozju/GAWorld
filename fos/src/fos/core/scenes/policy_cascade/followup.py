from __future__ import annotations

from typing import List

from fos.core.agent import Agent


class PolicyCascadeFollowUpMixin:
    def _branch_interpretations(self) -> dict:
        interpretations = self.state.get("branch_interpretations") or {}
        if type(interpretations) is not dict:
            interpretations = {}
        self.state["branch_interpretations"] = interpretations
        return interpretations

    def _record_branch_interpretation(self, agent: Agent, tier: str, message: str, mode: str) -> None:
        if not str(message or "").strip():
            return
        interpretations = self._branch_interpretations()
        interpretations[agent.name] = {
            "agent": agent.name,
            "tier": tier,
            "message": str(message),
            "mode": mode,
            "policy_version": int(self.state.get("policy_version", 0) or 0),
            "turn": int(getattr(self.simulator, "turns", 0) or 0),
        }
        self.state["branch_interpretations"] = interpretations

    def _competing_interpretations_for(self, agent: Agent) -> List[dict]:
        current_version = int(self.state.get("policy_version", 0) or 0)
        candidates = []
        seen = set()
        for name in self._reverse_connections_for(agent.name) + self._peer_targets(agent):
            if name in seen:
                continue
            seen.add(name)
            item = dict((self._branch_interpretations().get(name) or {}))
            if not item:
                continue
            if int(item.get("policy_version", -1) or -1) != current_version:
                continue
            candidates.append(item)
        return candidates

    def _thread_history_excerpt(self, history: List[dict], limit: int = 6) -> str:
        items = list(history or [])
        if not items:
            return ""
        excerpt = items[-limit:]
        lines = []
        for idx, item in enumerate(excerpt, start=max(1, len(items) - len(excerpt) + 1)):
            sender = str(item.get("sender") or self._tr("prompts.policy_cascade.shared.unknown"))
            recipient = str(item.get("recipient") or self._tr("prompts.policy_cascade.shared.unknown"))
            message = self._sanitize_message(str(item.get("message") or "")).replace("\n", " ").strip()
            if len(message) > 90:
                message = message[:90] + "..."
            lines.append(self._tr("prompts.policy_cascade.followup.thread_history_item", round=idx, sender=sender, recipient=recipient, message=message))
        return "\n".join(lines)

    def _thread_focus_summary(self, thread: dict) -> str:
        metadata = dict(thread.get("metadata") or {})
        issues = [str(item).strip() for item in list(metadata.get("issues") or []) if str(item).strip()]
        if issues:
            return "、".join(issues[:3])
        history = list(thread.get("history") or [])
        if history:
            text = self._sanitize_message(str(history[0].get("message") or "")).replace("\n", " ").strip()
            return text[:90] + "..." if len(text) > 90 else text
        text = self._sanitize_message(str(thread.get("last_message") or "")).replace("\n", " ").strip()
        return text[:90] + "..." if len(text) > 90 else text

    def _thread_target_guidance(self, agent: Agent) -> str:
        direct_up = self._upstream_targets(agent, 1)
        skip_up = self._upstream_targets(agent, 2)
        peers = self._peer_targets(agent)
        down = self._notify_targets(agent)
        parts = [self._tr("prompts.policy_cascade.followup.target_guidance_intro", agent)]
        if direct_up:
            parts.append(self._tr("prompts.policy_cascade.followup.target_guidance_report", agent, targets="、".join(direct_up)))
        if skip_up:
            parts.append(self._tr("prompts.policy_cascade.followup.target_guidance_escalate", agent, targets="、".join(skip_up)))
        if peers:
            parts.append(self._tr("prompts.policy_cascade.followup.target_guidance_peer", agent, targets="、".join(peers)))
        if down:
            parts.append(self._tr("prompts.policy_cascade.followup.target_guidance_notify", agent, targets="、".join(down)))
        return "".join(parts)

    def _payload_message_text(self, payload: dict) -> str:
        message = self._sanitize_message(str(payload.get("message") or ""))
        if message:
            return message
        content = self._sanitize_message(str(payload.get("content") or payload.get("text") or ""))
        if content:
            return content
        context = self._sanitize_message(str(payload.get("context") or ""))
        if context:
            return context
        response = self._sanitize_message(str(payload.get("response") or ""))
        return response

    def _follow_up_reference_text(self, private_event: dict) -> str:
        return str(
            private_event.get("latest_notice")
            or self.state.get("latest_notice")
            or private_event.get("relayed_policy")
            or private_event.get("source_policy")
            or self.state.get("relayed_policy")
            or self.state.get("source_policy")
            or self.state.get("latest_policy")
            or ""
        ).strip()

    def _follow_up_replays_policy(self, message: str, private_event: dict) -> bool:
        normalized = self._clean_policy_text(message)
        if not normalized:
            return False
        reference = self._clean_policy_text(self._follow_up_reference_text(private_event))
        if not reference:
            return False
        if "原文：" in normalized and len(normalized.splitlines()) >= 8:
            return True
        if len(reference) >= 80 and reference[:80] in normalized:
            return True
        invariants = self._policy_invariants()
        if len(normalized.splitlines()) >= 8 and invariants and all(item in normalized for item in invariants):
            return True
        return False

    def _follow_up_is_generic(self, tier: str, message: str, issues: List[str], current_thread: dict | None = None) -> bool:
        normalized = self._sanitize_message(message)
        if not normalized:
            return True
        if len(normalized) < 28:
            return True
        evasive_fragments = [
            "无需继续推进",
            "无需继续回复",
            "无需继续推进或回复",
            "无需进一步行动",
            "无需进一步操作",
            "当前未收到新请求",
            "维持既有立场",
            "等待上级先处理",
            "等待 mid 层先处理",
            "等待 top 层先处理",
        ]
        if any(fragment in normalized for fragment in evasive_fragments):
            return True
        feedback_signal = self._public_feedback_signal(self._current_follow_up_notice())
        if feedback_signal == "positive":
            positive_markers = ["满意", "缓和", "收缩", "转入常态", "减少", "下调", "抽查", "保留", "维持", "优化"]
            if not any(marker in normalized for marker in positive_markers):
                return True
        thread_focus = self._sanitize_message(self._thread_focus_summary(current_thread or {}))
        concrete_markers = issues + self._tier_keywords(tier) + ["24小时", "48小时", "5个工作日", "今天", "本周", "预算", "台账", "清单", "证据", "数据", "负责人"]
        if thread_focus:
            concrete_markers.append(thread_focus[:12])
        latest_message = self._sanitize_message(str((current_thread or {}).get("last_message") or ""))
        if latest_message:
            concrete_markers.extend(
                fragment
                for fragment in ["两个环节", "支持量", "资源缺口", "执行成本", "冲突节点", "保留项", "暂缓项", "责任人", "时点", "量化标准"]
                if fragment in latest_message
            )
        if any(marker and marker in normalized for marker in concrete_markers):
            if "已确保" in normalized and not any(fragment in normalized for fragment in ["负责人", "时点", "支持量", "两个环节", "台账", "清单", "证据", "24小时", "48小时", "今天"]):
                return True
            return False
        generic_fragments = [
            "确保信息传递的透明性",
            "确保信息传递的透明性和实效性",
            "结合基层实际需求",
            "明确调整范围和实施标准",
            "优化执行策略",
            "确保政策落地",
            "降低潜在冲突",
            "请确认具体调整方案",
            "继续推进协调",
            "根据系统公告内容",
            "已确保",
        ]
        if any(fragment in normalized for fragment in generic_fragments):
            return True
        return not any(keyword in normalized for keyword in self._tier_keywords(tier))

    def _current_follow_up_notice(self) -> str:
        return str(self.state.get("latest_environment_notice") or self.state.get("latest_notice") or "").strip()

    def _public_feedback_signal(self, text: str) -> str:
        notice = str(text or "").strip()
        if not notice:
            return ""
        if any(marker in notice for marker in ["抗议", "游行", "示威", "舆情", "媒体曝光", "热搜", "举报"]):
            return "negative"
        if any(marker in notice for marker in ["很满意", "表示满意", "普遍满意", "群众满意", "高度认可", "普遍支持", "积极评价", "一致好评", "欢迎这一政策", "拥护该政策", "反响良好"]):
            return "positive"
        return ""

    def _build_follow_up_message(self, agent: Agent, tier: str, current_thread: dict | None = None) -> str:
        current_thread = current_thread or {}
        issues = self._thread_issue_candidates(agent, tier)
        issue_text = "、".join(issues) if issues else "执行口径和资源安排"
        policy_summary = self._policy_prompt_excerpt(self._follow_up_reference_text(self._private_event_for(agent.name)))
        focus = self._sanitize_message(self._thread_focus_summary(current_thread))
        role_kind = self._tier_role_kind(tier)
        feedback_signal = self._public_feedback_signal(self._current_follow_up_notice())
        if current_thread:
            if role_kind == "top":
                return self._sanitize_message(
                    f"关于你反馈的{focus or issue_text}，我先做两项调整：第一，24小时内由牵头负责人补齐资源缺口和成本测算，明确哪些岗位必须保留、哪些环节可以延后；第二，48小时内统一解释口径，只保留{policy_summary or '当前政策硬约束'}，避免继续层层加码。你收到后请按新口径回传一版可执行清单。"
                )
            if role_kind == "mid":
                return self._sanitize_message(
                    f"针对你提到的{focus or issue_text}，我先按两步处理：今天内把资源缺口、执行成本和冲突节点汇总成一张台账，明早前给出保留项、暂缓项和责任人；同时保留{policy_summary or '当前政策硬约束'}，不再重复整段公告。你先补充最卡的两个环节和所需支持量。"
                )
            return self._sanitize_message(
                f"针对当前的{focus or issue_text}，我这边先按现场可执行口径处理：先把最耗资源的两项任务单独列出，今天内补齐证据和影响范围；对无法在时限内完成的部分同步上报，不再空泛复述公告。若你同意，我就按这个清单继续反馈。"
            )
        if feedback_signal == "positive":
            if role_kind == "top":
                return self._sanitize_message(
                    f"既然公众反馈已明显转向正面，我将把前一轮高压处置调整为稳态跟踪：保留{policy_summary or '当前政策硬约束'}，但把新增督办频次下调为每周复盘一次，同时收缩临时资源投放，只保留对关键岗位和申诉渠道的保障。"
                )
            if role_kind == "mid":
                return self._sanitize_message(
                    "既然当前反馈趋于正面，我会把任务重排为“继续保留”“可转入常态跟踪”“可暂停追加资源”三类，今天内更新台账并同步负责人；对上只汇报保留项和收缩项，对下直接下发简化后的执行步骤。"
                )
            return self._sanitize_message(
                "既然一线反馈已转向正面，我会把原先高频排查改为按清单抽查，保留申诉渠道和值班记录，对已稳定环节停止重复加码；若再出现异常，再按原上报链路补充证据和时间点。"
            )
        if role_kind == "top":
            return self._sanitize_message(
                f"针对当前暴露出的{issue_text}，我不会直接结束讨论。下一步由高层先核定资源缺口和容错边界，24小时内明确哪些要求继续硬执行、哪些环节允许分批推进；同时统一下发一版只保留{policy_summary or '核心硬约束'}的解释口径，避免继续层层放大执行成本。"
            )
        if role_kind == "mid":
            return self._sanitize_message(
                f"围绕当前的{issue_text}，我将先把任务拆成“必须立即执行”“可顺延一周”“需追加资源”三类，今天内更新台账并回传负责人和时间表；对上只保留{policy_summary or '当前政策核心要求'}，对下不再复述整段公告，而是直接给出可执行步骤。"
            )
        return self._sanitize_message(
            f"结合一线目前的{issue_text}，我会先按现场流程核对最耗时的两个环节，补充证据、责任人和预计完成时点；对无法按时完成或资源明显不足的部分立即上报，不再重复政策原文，而是给出具体卡点和所需支持。"
        )

    def _normalize_follow_up_message(self, agent: Agent, tier: str, message: str, current_thread: dict | None = None) -> str:
        normalized = self._sanitize_message(message)
        issues = self._thread_issue_candidates(agent, tier)
        private_event = self._private_event_for(agent.name)
        if self._follow_up_replays_policy(normalized, private_event):
            normalized = ""
        if normalized and self._follow_up_is_generic(tier, normalized, issues, current_thread):
            normalized = ""
        if not normalized:
            normalized = self._build_follow_up_message(agent, tier, current_thread)
        if self._message_has_tier_drift(tier, normalized):
            normalized = self._build_follow_up_message(agent, tier, current_thread)
        return self._sanitize_message(normalized)

    def _special_action_allowed_targets(self, action_name: str, agent: Agent) -> List[str]:
        if action_name == "report_upward":
            return self._upstream_targets(agent, 1)
        if action_name == "escalate_complaint":
            return self._upstream_targets(agent, 2)
        if action_name == "consult_peer":
            return self._peer_targets(agent)
        if action_name == "notify_subordinate":
            return self._notify_targets(agent)
        return []

    def _mentioned_target_name(self, text: str, candidates: List[str]) -> str:
        content = str(text or "")
        if not content:
            return ""
        ordered = sorted([name for name in candidates if name], key=len, reverse=True)
        for name in ordered:
            if name in content:
                return name
        return ""

    def _infer_special_action_target(self, action_name: str, payload: dict, agent: Agent, effective_task_mode: str) -> str:
        if effective_task_mode == "follow_up_thread":
            return ""
        candidates = self._special_action_allowed_targets(action_name, agent)
        if not candidates:
            return ""
        if len(candidates) == 1:
            return candidates[0]
        text = "\n".join(
            part
            for part in [
                self._payload_message_text(payload),
                self._sanitize_message(str(payload.get("thoughts") or "")),
                self._sanitize_message(str(payload.get("response") or "")),
            ]
            if part
        )
        return self._mentioned_target_name(text, candidates)

    def _thread_shock_guidance(self, notice: str, issue_candidates: List[str]) -> str:
        text = str(notice or "").strip()
        if not text:
            return ""
        if any(marker in text for marker in ["抗议", "游行", "示威", "舆情", "媒体曝光", "热搜", "举报"]):
            extra = self._tr("prompts.policy_cascade.followup.shock_negative_extra", issues="、".join(issue_candidates)) if issue_candidates else ""
            return self._tr("prompts.policy_cascade.followup.shock_negative", extra=extra)
        if any(marker in text for marker in ["很满意", "表示满意", "普遍支持", "反响良好", "一致好评"]):
            return self._tr("prompts.policy_cascade.followup.shock_positive")
        return ""

    def _queue_thread_event(self, recipient: str, thread: dict, reply_target: str, notice: str = "") -> None:
        private_events = self.state.get("private_events") or {}
        inboxes = self.state.get("thread_inboxes") or {}
        history = list(thread.get("history") or [])
        payload = {
            "task_mode": "follow_up_thread",
            "latest_notice": str(self.state.get("latest_notice") or notice or ""),
            "latest_environment_notice": str(self.state.get("latest_environment_notice") or ""),
            "latest_policy": str(self.state.get("latest_policy") or ""),
            "source_policy": str(self.state.get("source_policy") or ""),
            "relayed_policy": str(self.state.get("relayed_policy") or self.state.get("latest_policy") or ""),
            "notice_kind": "execution",
            "thread_id": thread["id"],
            "thread_kind": thread["kind"],
            "thread_sender": thread.get("last_sender") or thread.get("sender"),
            "reply_target": reply_target,
            "thread_message": thread.get("last_message") or thread.get("message") or "",
            "thread_status": thread.get("status") or "open",
            "conversation_history": history,
            "thread_round_count": len(history),
            "thread_history_excerpt": self._thread_history_excerpt(history),
            "thread_focus": self._thread_focus_summary(thread),
            "thread_root_sender": thread.get("root_sender") or thread.get("sender"),
            "thread_notice": notice,
        }
        existing = private_events.get(recipient) or {}
        if existing:
            queued = list(inboxes.get(recipient) or [])
            queued.append(thread["id"])
            inboxes[recipient] = queued
        else:
            private_events[recipient] = payload
        self.state["private_events"] = private_events
        self.state["thread_inboxes"] = inboxes
        self._mark_follow_up_public_done(recipient)

    def _activate_next_thread(self, recipient: str) -> None:
        private_events = self.state.get("private_events") or {}
        if private_events.get(recipient):
            return
        inboxes = self.state.get("thread_inboxes") or {}
        queued = list(inboxes.get(recipient) or [])
        if not queued:
            return
        thread_id = queued.pop(0)
        inboxes[recipient] = queued
        self.state["thread_inboxes"] = inboxes
        thread = self._thread_for_id(thread_id)
        if not thread:
            return
        reply_target = str(thread.get("last_sender") or thread.get("sender") or "")
        self._queue_thread_event(recipient, thread, reply_target)

    def _consume_thread_event(self, recipient: str) -> None:
        private_events = self.state.get("private_events") or {}
        private_events.pop(recipient, None)
        self.state["private_events"] = private_events
        self._activate_next_thread(recipient)

    def _open_thread(self, kind: str, sender: Agent, recipient: str, message: str, simulator, metadata: dict | None = None) -> dict:
        thread_id = self._next_thread_id()
        history = [
            {
                "sender": sender.name,
                "recipient": recipient,
                "message": message,
                "kind": kind,
                "turn": int(simulator.turns),
            }
        ]
        thread = {
            "id": thread_id,
            "kind": kind,
            "sender": sender.name,
            "root_sender": sender.name,
            "root_recipient": recipient,
            "last_sender": sender.name,
            "last_recipient": recipient,
            "last_message": message,
            "status": "open",
            "created_turn": int(simulator.turns),
            "history": history,
            "metadata": metadata or {},
        }
        self._replace_thread(thread_id, thread)
        self._queue_thread_event(recipient, thread, sender.name)
        simulator.emit_event(
            "policy_thread_opened",
            {
                "thread_id": thread_id,
                "kind": kind,
                "sender": sender.name,
                "recipient": recipient,
                "message": message,
                "metadata": metadata or {},
            },
        )
        return thread

    def _reply_to_thread(self, thread: dict, agent: Agent, message: str, simulator) -> None:
        reply_target = str(thread.get("last_sender") or thread.get("sender") or "")
        history = list(thread.get("history") or [])
        history.append(
            {
                "sender": agent.name,
                "recipient": reply_target,
                "message": message,
                "kind": "reply",
                "turn": int(simulator.turns),
            }
        )
        thread["history"] = history
        thread["last_sender"] = agent.name
        thread["last_recipient"] = reply_target
        thread["last_message"] = message
        thread["status"] = "responded"
        thread["reply_count"] = int(thread.get("reply_count", 0) or 0) + 1
        self._replace_thread(thread["id"], thread)
        self._queue_thread_event(reply_target, thread, agent.name)
        simulator.emit_event(
            "policy_thread_reply",
            {
                "thread_id": thread["id"],
                "kind": thread.get("kind"),
                "sender": agent.name,
                "recipient": reply_target,
                "message": message,
            },
        )

    def _ignore_thread(self, thread: dict, agent: Agent, simulator) -> None:
        thread["status"] = "ignored"
        self._replace_thread(thread["id"], thread)
        last_sender = str(thread.get("last_sender") or thread.get("sender") or "")
        notice = self._tr("prompts.policy_cascade.followup.ignore_notice", agent, agent=agent.name)
        if last_sender and last_sender != agent.name:
            thread["last_sender"] = agent.name
            thread["last_recipient"] = last_sender
            thread["last_message"] = notice
            self._replace_thread(thread["id"], thread)
            self._queue_thread_event(last_sender, thread, agent.name, notice=notice)
        simulator.emit_event(
            "policy_thread_ignored",
            {
                "thread_id": thread["id"],
                "kind": thread.get("kind"),
                "agent": agent.name,
                "notice": notice,
            },
        )

    def _follow_up_visible_targets(self, agent_name: str) -> List[str]:
        visible = []
        for name in self._network_connections_for(agent_name):
            if name not in visible:
                visible.append(name)
        for name in self._reverse_connections_for(agent_name):
            if name not in visible:
                visible.append(name)
        for name in (self._informal_network().get(agent_name) or []):
            if name in self.simulator.agents and name != agent_name and name not in visible:
                visible.append(name)
        if visible:
            return visible
        return [name for name in self.simulator.agents.keys() if name != agent_name]

    def _network_connections_for(self, agent_name: str) -> List[str]:
        social_network = self.state.get("social_network") or {}
        if type(social_network) is not dict or not social_network:
            return []
        raw_connections = social_network.get(agent_name) or []
        if type(raw_connections) is not list:
            return []
        return [name for name in raw_connections if name in self.simulator.agents and name != agent_name]

    def _active_targets_for_tier(self, tier: str) -> List[str]:
        active_targets = self.state.get("active_tier_targets") or {}
        targets = list(active_targets.get(tier) or [])
        return [name for name in targets if (self._tier_map.get(name) or self._extract_tier(self.simulator.agents[name])) == tier]

    def _upstream_merge_message(self, recipient: str, upstream_messages: List[dict]) -> str:
        if len(upstream_messages) == 1:
            return str(upstream_messages[0].get("message") or "")
        lines = [self._tr("prompts.policy_cascade.followup.upstream_merge_intro")]
        for idx, item in enumerate(upstream_messages, start=1):
            sender = str(item.get("sender") or self._tr("prompts.policy_cascade.followup.upstream_node", index=idx))
            message = str(item.get("message") or "").strip()
            lines.append(self._tr("prompts.policy_cascade.followup.upstream_merge_item", index=idx, sender=sender, message=message))
        lines.append(self._tr("prompts.policy_cascade.followup.upstream_merge_outro"))
        return "\n\n".join(lines)

    def _queue_private_cascade_targets(self, recipients: List[str], sender: Agent, relayed_message: str, source_policy: str) -> None:
        if not recipients:
            return
        private_events = self.state.get("private_events") or {}
        active_targets = self.state.get("active_tier_targets") or {}
        notice = str(self.state.get("latest_notice") or source_policy or relayed_message or "")
        relay_policy = self._relay_policy_text(relayed_message, source_policy)
        for recipient in recipients:
            existing = dict(private_events.get(recipient) or {})
            upstream_messages = list(existing.get("upstream_messages") or [])
            candidate = {"sender": sender.name, "message": relay_policy}
            if candidate not in upstream_messages:
                upstream_messages.append(candidate)
            merged_message = self._upstream_merge_message(recipient, upstream_messages)
            private_events[recipient] = {
                "latest_notice": notice,
                "latest_environment_notice": str(self.state.get("latest_environment_notice") or ""),
                "latest_policy": merged_message,
                "source_policy": source_policy,
                "relayed_policy": merged_message,
                "task_mode": "cascade",
                "notice_kind": "execution",
                "upstream_messages": upstream_messages,
            }
            tier = self._tier_map.get(recipient) or ""
            if tier:
                current = list(active_targets.get(tier) or [])
                if recipient not in current:
                    current.append(recipient)
                active_targets[tier] = current
        self.state["private_events"] = private_events
        self.state["active_tier_targets"] = active_targets

    def _downstream_targets(self, agent: Agent) -> List[str]:
        tier = self._tier_map.get(agent.name) or self._extract_tier(agent)
        idx = self.tier_order.index(tier) if tier in self.tier_order else 0
        if idx + 1 >= len(self.tier_order):
            return []
        next_tier = self.tier_order[idx + 1]
        candidates = self._agents_by_tier.get(next_tier, [])
        social_connections = self._network_connections_for(agent.name)
        if not social_connections:
            return candidates
        return [name for name in candidates if name in social_connections]

    def _next_tier_candidates(self, tier: str) -> List[str]:
        idx = self.tier_order.index(tier) if tier in self.tier_order else 0
        if idx + 1 >= len(self.tier_order):
            return []
        next_tier = self.tier_order[idx + 1]
        return list(self._agents_by_tier.get(next_tier, []))

    def _cascade_dead_end_data(self, agent: Agent) -> dict:
        tier = self._tier_map.get(agent.name) or self._extract_tier(agent)
        idx = self.tier_order.index(tier) if tier in self.tier_order else 0
        next_tier = self.tier_order[idx + 1] if idx + 1 < len(self.tier_order) else ""
        direct_connections = self._network_connections_for(agent.name)
        next_tier_candidates = self._next_tier_candidates(tier)
        next_tier_connections = [name for name in direct_connections if name in next_tier_candidates]
        return {
            "agent": agent.name,
            "tier": tier,
            "next_tier": next_tier,
            "direct_connections": direct_connections,
            "next_tier_candidates": next_tier_candidates,
            "next_tier_connections": next_tier_connections,
        }

    def _entire_next_tier_targets(self, agent: Agent) -> List[str]:
        tier = self._tier_map.get(agent.name) or self._extract_tier(agent)
        idx = self.tier_order.index(tier) if tier in self.tier_order else 0
        if idx + 1 >= len(self.tier_order):
            return []
        next_tier = self.tier_order[idx + 1]
        return list(self._agents_by_tier.get(next_tier, []))
