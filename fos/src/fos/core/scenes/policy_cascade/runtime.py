from __future__ import annotations

import re
from typing import List

from fos.core.actions.base_actions import SendMessageAction, YieldAction
from fos.core.actions.policy_feedback_actions import (
    AnnouncePolicyAdjustmentAction,
    ConsultPeerAction,
    EscalateComplaintAction,
    NotifySubordinateAction,
    ReportUpwardAction,
)
from fos.core.agent import Agent
from fos.core.event import PublicEvent

from .constants import _parse_tier_order
from fos.i18n import T


class PolicyCascadeRuntimeMixin:
    def get_scene_actions(self, agent: Agent):
        actions = [SendMessageAction(), YieldAction()]
        effective_mode = self._effective_task_mode_for(agent)
        if effective_mode not in {"follow_up", "follow_up_thread"}:
            return actions
        tier = self._tier_map.get(agent.name) or self._extract_tier(agent)
        private_event = self._private_event_for(agent.name)
        current_thread = self._thread_for_id(str(private_event.get("thread_id") or "")) if effective_mode == "follow_up_thread" else {}
        follow_up_actions = []
        thread_kind = str(current_thread.get("kind") or "") if effective_mode == "follow_up_thread" else ""
        if thread_kind != "upward_feedback":
            follow_up_actions.append(ReportUpwardAction())
        if thread_kind != "escalation":
            follow_up_actions.append(EscalateComplaintAction())
        if thread_kind != "peer_consult":
            follow_up_actions.append(ConsultPeerAction())
        if thread_kind != "subordinate_notice":
            follow_up_actions.append(NotifySubordinateAction())
        if self._can_announce_policy_adjustment(agent, tier, current_thread):
            follow_up_actions.append(AnnouncePolicyAdjustmentAction())
        return actions + follow_up_actions

    def parse_and_handle_action(self, action_data, agent: Agent, simulator):
        payload = action_data
        original_payload = dict(action_data)
        raw_action = action_data.get("action")
        if type(raw_action) is dict:
            action_name = raw_action.get("name") or raw_action.get("action")
            merged = {k: v for k, v in raw_action.items() if k != "name"}
            for k, v in action_data.items():
                if k != "action":
                    merged[k] = v
            merged["action"] = action_name
            payload = merged
        action_name = payload.get("action")
        tier = self._tier_map.get(agent.name) or self._extract_tier(agent)
        private_event = self._private_event_for(agent.name)
        effective_task_mode = self._effective_task_mode_for(agent)
        thread = self._thread_for_id(str(private_event.get("thread_id") or "")) if effective_task_mode == "follow_up_thread" else {}
        special_actions = {
            "report_upward",
            "escalate_complaint",
            "consult_peer",
            "notify_subordinate",
            "announce_policy_adjustment",
        }
        defer_thread_reply = (
            effective_task_mode == "follow_up"
            and bool(private_event)
            and str(private_event.get("task_mode") or "") == "follow_up_thread"
            and agent.name not in self._follow_up_public_done_agents()
        )
        known_actions = {"send_message", "yield", *special_actions}
        source_policy = str(
            private_event.get("source_policy")
            or self.state.get("source_policy", "")
            or private_event.get("relayed_policy")
            or private_event.get("latest_policy")
            or self.state.get("relayed_policy", "")
            or self.state.get("latest_policy", "")
            or ""
        ).strip()

        normalized_action = str(action_name or "").strip()
        no_action_signal = effective_task_mode in {"follow_up", "follow_up_thread"} and self._follow_up_no_action_signal(payload)
        if no_action_signal:
            action_name = "send_message"
            payload["action"] = "send_message"
            payload["message"] = self._follow_up_no_action_message(agent)
        elif normalized_action not in known_actions:
            fallback_message = self._payload_message_text(payload)
            if fallback_message:
                action_name = "send_message"
                payload["action"] = "send_message"
                payload["message"] = fallback_message

        if (
            effective_task_mode == "follow_up"
            and no_action_signal
            and not self.should_skip_turn(agent, simulator)
        ):
            payload = {"action": "send_message", "message": self._follow_up_no_action_message(agent)}
            self._record_follow_up_message_state(agent.name, payload["message"], effective_task_mode)
            self._record_branch_interpretation(agent, tier, payload["message"], effective_task_mode)
            self._write_final_debug(agent, effective_task_mode, original_payload, payload)
            success, result, summary, meta, _ = super().parse_and_handle_action(payload, agent, simulator)
            if success and defer_thread_reply:
                self._mark_follow_up_public_done(agent.name)
                return success, result, summary, meta, False
            return success, result, summary, meta, True

        if effective_task_mode == "cascade" and self._must_complete_current_cascade():
            normalized_action = str(action_name or "").strip()
            allowed_cascade_actions = {"send_message", "yield", *special_actions}
            if normalized_action not in allowed_cascade_actions:
                action_name = "send_message"
                payload["action"] = "send_message"
                payload["message"] = self._payload_message_text(payload)

        if effective_task_mode == "cascade" and self._must_complete_current_cascade() and action_name == "yield":
            policy = str(
                private_event.get("relayed_policy")
                or private_event.get("latest_policy")
                or self.state.get("relayed_policy", "")
                or self.state.get("latest_policy", "")
                or ""
            ).strip()
            if policy:
                action_name = "send_message"
                payload["action"] = "send_message"
                payload["message"] = f"{policy}\n{self._cascade_suffix(tier)}"

        if effective_task_mode in {"follow_up", "follow_up_thread"} and action_name == "yield" and no_action_signal:
            action_name = "send_message"
            payload["action"] = "send_message"
            payload["message"] = self._follow_up_no_action_message(agent)

        if effective_task_mode == "follow_up" and action_name == "yield":
            action_name = "send_message"
            payload["action"] = "send_message"
            payload["message"] = self._normalize_follow_up_message(agent, tier, self._payload_message_text(payload), None)

        if effective_task_mode == "follow_up_thread":
            if action_name == "send_message" and not self.should_skip_turn(agent, simulator):
                raw_message = self._payload_message_text(payload)
                message = self._sanitize_message(raw_message)
                if (
                    not message
                    or self._follow_up_replays_policy(message, self._private_event_for(agent.name))
                ):
                    message = self._normalize_follow_up_message(agent, tier, raw_message, thread)
                if no_action_signal:
                    message = self._follow_up_no_action_message(agent)
                self._record_follow_up_message_state(agent.name, message, effective_task_mode)
                self._reply_to_thread(thread, agent, message, simulator)
                self._consume_thread_event(agent.name)
                self._write_final_debug(agent, effective_task_mode, original_payload, {"action": "send_message", "message": message})
                return True, {"message": message}, f"{agent.name} 私下回复了线程", {}, True
            if action_name == "yield" and not self.should_skip_turn(agent, simulator):
                self._ignore_thread(thread, agent, simulator)
                self._consume_thread_event(agent.name)
                return True, {}, f"{agent.name} 暂未处理线程", {}, True
            if action_name in special_actions and not self.should_skip_turn(agent, simulator):
                if action_name != "announce_policy_adjustment" and not str(payload.get("target") or payload.get("to") or "").strip():
                    error = "Provide 'target'."
                    agent.add_env_feedback(error)
                    return False, {"error": error}, error, {}, True
                success, result, summary, meta, pass_control = self.handle_policy_special_action(action_name, payload, agent, simulator)
                if success:
                    self._consume_thread_event(agent.name)
                return success, result, summary, meta, pass_control

        if action_name in special_actions and not self.should_skip_turn(agent, simulator):
            if action_name != "announce_policy_adjustment" and not str(payload.get("target") or payload.get("to") or "").strip():
                inferred_target = self._infer_special_action_target(action_name, payload, agent, effective_task_mode)
                if inferred_target:
                    payload["target"] = inferred_target
                elif effective_task_mode in {"follow_up", "follow_up_thread"}:
                    payload["action"] = "send_message"
                    payload["message"] = self._normalize_follow_up_message(agent, tier, self._payload_message_text(payload), thread if effective_task_mode == "follow_up_thread" else None)
                    action_name = "send_message"
            if action_name == "send_message":
                payload["message"] = self._normalize_follow_up_message(agent, tier, self._payload_message_text(payload), thread if effective_task_mode == "follow_up_thread" else None)
            else:
                success, result, summary, meta, pass_control = self.handle_policy_special_action(action_name, payload, agent, simulator)
                if success and defer_thread_reply:
                    self._mark_follow_up_public_done(agent.name)
                    return success, result, summary, meta, False
                return success, result, summary, meta, pass_control

        if effective_task_mode == "notice" and action_name == "send_message" and not self.should_skip_turn(agent, simulator):
            message = self._payload_message_text(payload)
            if private_event:
                payload["message"] = message
            else:
                payload["message"] = self._normalize_notice_message(tier, message)

        if effective_task_mode == "cascade" and action_name == "send_message" and not self.should_skip_turn(agent, simulator):
            policy = str(private_event.get("relayed_policy") or private_event.get("latest_policy") or self.state.get("relayed_policy", "") or self.state.get("latest_policy", "") or "").strip()
            source_policy = str(private_event.get("source_policy") or self.state.get("source_policy", "") or policy).strip()
            message = self._payload_message_text(payload)
            if not policy:
                raise ValueError(T("latest policy missing for cascade"))

            if private_event:
                self.state["latest_notice"] = str(private_event.get("latest_notice") or self.state.get("latest_notice") or "")
                self.state["latest_policy"] = policy
                self.state["source_policy"] = source_policy
                self.state["relayed_policy"] = policy
                self.state["task_mode"] = "cascade"
                self.state["notice_kind"] = "execution"

            if self._cascade_mode() == "distortion_cascade":
                if not self._must_complete_current_cascade() and self._should_block(agent, tier):
                    payload["action"] = "yield"
                    payload.pop("message", None)
                else:
                    distorted = self._agent_led_distortion(agent, tier, policy, message)
                    payload["message"] = distorted or message
                self._emit_distortion_event(
                    simulator,
                    agent,
                    tier,
                    policy,
                    message,
                    str(payload.get("action") or ""),
                    str(payload.get("message") or ""),
                )
            else:
                def _norm(text: str) -> str:
                    return " ".join(text.split())

                policy_norm = _norm(policy)
                message_norm = _norm(message)
                invariants = re.findall(r"“([^”]+)”", policy)

                matches_policy = policy_norm and policy_norm in message_norm
                matches_invariants = bool(invariants) and all(inv in message for inv in invariants)
                head = policy_norm[:120]
                matches_head = head and head in message_norm

                if not matches_policy and not matches_invariants and not matches_head:
                    payload["message"] = f"{policy}\n{self._cascade_suffix(tier)}"
                elif not any(word in message for word in ["态度：", "补充："]):
                    payload["message"] = f"{message}\n{self._cascade_suffix(tier)}"
                elif self._message_has_tier_drift(tier, message.replace(policy, "", 1)):
                    payload["message"] = f"{policy}\n{self._cascade_suffix(tier)}"
                else:
                    payload["message"] = message

            if str(payload.get("action") or "") == "send_message":
                payload["message"] = self._normalize_cascade_message(
                    agent,
                    tier,
                    policy,
                    str(payload.get("message", "") or ""),
                )

            if str(payload.get("action") or "") == "send_message":
                relay_policy = self._relay_policy_text(str(payload.get("message") or policy), source_policy)
                self.state["latest_policy"] = str(payload.get("message") or policy)
                self.state["relayed_policy"] = relay_policy
                self.state["source_policy"] = source_policy
                self.state["task_mode"] = "cascade"
                self.state["notice_kind"] = "execution"

        if private_event and effective_task_mode == "cascade":
            private_events = self.state.get("private_events") or {}
            private_events.pop(agent.name, None)
            self.state["private_events"] = private_events

            self.state["latest_notice"] = str(private_event.get("latest_notice") or "")
            self.state["latest_policy"] = str(payload.get("message") or private_event.get("relayed_policy") or private_event.get("latest_policy") or "")
            self.state["source_policy"] = source_policy
            self.state["relayed_policy"] = self._relay_policy_text(
                str(payload.get("message") or private_event.get("relayed_policy") or private_event.get("latest_policy") or ""),
                source_policy,
            )
            self.state["task_mode"] = "cascade"
            self.state["notice_kind"] = "execution"

        if str(payload.get("action") or action_name) == "send_message":
            payload["message"] = self._payload_message_text(payload)
            if effective_task_mode in {"follow_up", "follow_up_thread"} and no_action_signal:
                payload["message"] = self._follow_up_no_action_message(agent)
            elif effective_task_mode in {"follow_up", "follow_up_thread"}:
                payload["message"] = self._normalize_follow_up_message(agent, tier, payload["message"], thread if effective_task_mode == "follow_up_thread" else None)
            self._record_follow_up_message_state(agent.name, payload["message"], effective_task_mode)
            self._record_branch_interpretation(agent, tier, payload["message"], effective_task_mode)
            self._write_final_debug(agent, effective_task_mode, original_payload, payload)

        success, result, summary, meta, _ = super().parse_and_handle_action(payload, agent, simulator)
        if success and defer_thread_reply:
            self._mark_follow_up_public_done(agent.name)
            return success, result, summary, meta, False
        return success, result, summary, meta, True

    def handle_policy_special_action(self, action_name: str, action_data: dict, agent: Agent, simulator):
        target = str(action_data.get("target") or action_data.get("to") or "").strip()
        message = self._sanitize_message(str(action_data.get("message") or ""))
        tier = self._tier_map.get(agent.name) or self._extract_tier(agent)
        current_thread_event = self._private_event_for(agent.name)
        current_thread = self._thread_for_id(str(current_thread_event.get("thread_id") or "")) if current_thread_event else {}

        if action_name == "announce_policy_adjustment":
            if tier == self.tier_order[-1]:
                error = self._tr("prompts.policy_cascade.runtime.low_cannot_announce", agent)
                agent.add_env_feedback(error)
                return False, {"error": error}, error, {}, True
            if not self._can_announce_policy_adjustment(agent, tier, current_thread):
                error = self._tr("prompts.policy_cascade.runtime.strict_announce_only", agent)
                agent.add_env_feedback(error)
                return False, {"error": error}, error, {}, True
            if not message:
                error = "Missing message."
                agent.add_env_feedback(error)
                return False, {"error": error}, error, {}, True
            text = self._tr("prompts.policy_cascade.runtime.policy_adjustment_prefix", agent, message=message)
            if tier == self.tier_order[0]:
                simulator.broadcast(PublicEvent(text, prefix="Policy Update"))
                recipients = [name for name in simulator.agents.keys() if name != agent.name]
                downstream = self._entire_next_tier_targets(agent)
                self._queue_private_cascade_targets(downstream, agent, text, text)
                tier_transmitted = self.state.get("tier_transmitted") or {t: False for t in self.tier_order}
                tier_transmitted[tier] = True
                self.state["tier_transmitted"] = tier_transmitted
            else:
                recipients = self._branch_descendants(agent)
                simulator.broadcast(PublicEvent(text, prefix="Policy Update"), receivers=recipients)
            simulator.emit_event(
                "policy_adjustment_issued",
                {
                    "sender": agent.name,
                    "tier": tier,
                    "message": text,
                    "recipients": recipients,
                },
            )
            self._clear_follow_up_no_action_agents()
            self._write_final_debug(agent, "follow_up", action_data, {"action": action_name, "message": text})
            return True, {"message": text, "recipients": recipients}, self._tr("prompts.policy_cascade.runtime.summary_announce", agent, agent=agent.name), {}, True

        if not target:
            error = "Provide 'target'."
            agent.add_env_feedback(error)
            return False, {"error": error}, error, {}, True
        if target not in simulator.agents:
            error = f"No such person: {target}."
            agent.add_env_feedback(error)
            return False, {"error": error}, error, {}, True
        if not message:
            error = "Missing message."
            agent.add_env_feedback(error)
            return False, {"error": error}, error, {}, True

        if action_name == "report_upward":
            allowed = self._upstream_targets(agent, 1)
            if target not in allowed:
                error = self._tr("prompts.policy_cascade.runtime.invalid_report_target", agent, target=target)
                agent.add_env_feedback(error)
                return False, {"error": error}, error, {}, True
            metadata = {
                "tier": tier,
                "issues": self._thread_issue_candidates(agent, tier),
                "source_thread": current_thread.get("id") if current_thread else "",
            }
            thread = self._open_thread("upward_feedback", agent, target, message, simulator, metadata)
            if current_thread:
                current_thread["status"] = "forwarded"
                self._replace_thread(current_thread["id"], current_thread)
            self._write_final_debug(agent, "follow_up", action_data, {"action": action_name, "target": target, "message": message})
            return True, {"thread_id": thread["id"], "target": target, "message": message}, self._tr("prompts.policy_cascade.runtime.summary_report", agent, agent=agent.name, target=target), {}, True

        if action_name == "escalate_complaint":
            allowed = self._upstream_targets(agent, 2)
            if target not in allowed:
                error = self._tr("prompts.policy_cascade.runtime.invalid_escalate_target", agent, target=target)
                agent.add_env_feedback(error)
                return False, {"error": error}, error, {}, True
            metadata = {
                "tier": tier,
                "issues": self._thread_issue_candidates(agent, tier),
                "source_thread": current_thread.get("id") if current_thread else "",
                "escalated": True,
            }
            thread = self._open_thread("escalation", agent, target, message, simulator, metadata)
            if current_thread:
                current_thread["status"] = "escalated"
                self._replace_thread(current_thread["id"], current_thread)
            self._write_final_debug(agent, "follow_up", action_data, {"action": action_name, "target": target, "message": message})
            return True, {"thread_id": thread["id"], "target": target, "message": message}, self._tr("prompts.policy_cascade.runtime.summary_escalate", agent, agent=agent.name, target=target), {}, True

        if action_name == "consult_peer":
            allowed = self._peer_targets(agent)
            if target not in allowed:
                error = self._tr("prompts.policy_cascade.runtime.invalid_peer_target", agent, target=target)
                agent.add_env_feedback(error)
                return False, {"error": error}, error, {}, True
            metadata = {
                "tier": tier,
                "issues": self._thread_issue_candidates(agent, tier),
                "source_thread": current_thread.get("id") if current_thread else "",
                "informal": True,
            }
            thread = self._open_thread("peer_consult", agent, target, message, simulator, metadata)
            self._write_final_debug(agent, "follow_up", action_data, {"action": action_name, "target": target, "message": message})
            return True, {"thread_id": thread["id"], "target": target, "message": message}, self._tr("prompts.policy_cascade.runtime.summary_peer", agent, agent=agent.name, target=target), {}, True

        if action_name == "notify_subordinate":
            allowed = self._notify_targets(agent)
            if target not in allowed:
                error = self._tr("prompts.policy_cascade.runtime.invalid_notify_target", agent, target=target)
                agent.add_env_feedback(error)
                return False, {"error": error}, error, {}, True
            metadata = {
                "tier": tier,
                "source_thread": current_thread.get("id") if current_thread else "",
                "notified_by": agent.name,
            }
            thread = self._open_thread("subordinate_notice", agent, target, message, simulator, metadata)
            if current_thread:
                current_thread["status"] = "redirected"
                self._replace_thread(current_thread["id"], current_thread)
            self._write_final_debug(agent, "follow_up", action_data, {"action": action_name, "target": target, "message": message})
            return True, {"thread_id": thread["id"], "target": target, "message": message}, self._tr("prompts.policy_cascade.runtime.summary_notify", agent, agent=agent.name, target=target), {}, True

        error = f"Unknown special action: {action_name}"
        agent.add_env_feedback(error)
        return False, {"error": error}, error, {}, True

    def deliver_message(self, event, sender: Agent, simulator):
        event.code = "scene_chat"
        event.params = {"sender": sender.name, "message": event.message}

        formatted = event.to_string(self.state.get("time"))
        sender.add_env_feedback(formatted)

        tier = self._tier_map.get(sender.name) or self._extract_tier(sender)
        self.state.setdefault("tier_transmitted", {t: False for t in self.tier_order})
        self.state["tier_transmitted"][tier] = True
        recipients: List[str] = []
        tier_idx = self.tier_order.index(tier) if tier in self.tier_order else 0

        if self.state.get("task_mode") == "notice":
            recipients = [a.name for a in simulator.agents.values() if a.name != sender.name]
        elif self.state.get("task_mode") == "follow_up":
            recipients = self._follow_up_visible_targets(sender.name)
        elif tier_idx < len(self.tier_order) - 1:
            recipients = self._downstream_targets(sender)
            self._queue_private_cascade_targets(
                recipients,
                sender,
                event.message,
                str(self.state.get("source_policy") or self.state.get("latest_policy") or event.message or ""),
            )
        elif tier_idx == len(self.tier_order) - 1:
            recipients = []
        else:
            recipients = [a.name for a in simulator.agents.values() if a.name != sender.name]

        for name in recipients:
            agent = simulator.agents.get(name)
            if agent:
                agent.add_env_feedback(formatted)

        simulator.emit_event_later(
            "system_broadcast",
            {
                "time": self.state.get("time"),
                "type": event.__class__.__name__,
                "sender": sender.name,
                "recipients": recipients,
                "text": event.to_string(),
                "code": event.code,
                "params": {"sender": sender.name, "message": event.message, "recipients": recipients},
            },
        )

    def should_skip_turn(self, agent: Agent, simulator) -> bool:
        if self.state.get("complete"):
            return True
        mode = str(self.state.get("task_mode") or "notice")
        if mode == "follow_up":
            private_event = self._private_event_for(agent.name)
            if self._follow_up_requires_tier_order():
                tier = self._tier_map.get(agent.name) or self._extract_tier(agent)
                if tier != self._active_tier():
                    return True
            if agent.name in self._follow_up_no_action_agents() and not private_event:
                return True
            return False
        tier = self._tier_map.get(agent.name) or self._extract_tier(agent)
        active = self._active_tier()
        if tier != active:
            return True
        active_targets = self._active_targets_for_tier(active)
        if active_targets:
            return agent.name not in active_targets
        private_recipients = self._private_recipient_names()
        if private_recipients:
            private_tier = self.tier_order[self._private_active_tier_idx()]
            if private_tier == active:
                return agent.name not in private_recipients
        return False

    def post_turn(self, agent: Agent, simulator) -> None:
        super().post_turn(agent, simulator)
        self._clear_follow_up_public_done(agent.name)

        if str(self.state.get("task_mode") or "") == "follow_up":
            if self._follow_up_requires_tier_order():
                tier = self._tier_map.get(agent.name) or self._extract_tier(agent)
                active = self._active_tier()
                if tier != active:
                    return

                seen = self.state.get("tier_seen", {})
                if active not in seen:
                    seen[active] = []
                if agent.name not in seen[active]:
                    seen[active].append(agent.name)

                expected_agents = self._agents_by_tier.get(active, [])
                if expected_agents and all(name in seen[active] for name in expected_agents):
                    next_idx = self.tier_order.index(active) + 1
                    if next_idx < len(self.tier_order):
                        self.state["current_tier_idx"] = next_idx
                    else:
                        self.state["follow_up_force_tier_order"] = False
                        self.state["current_tier_idx"] = 0
                        if not self._private_recipient_names():
                            self._auto_seed_follow_up_threads()
                    self.state["tier_seen"] = {t: [] for t in self.tier_order}
                    self._normalize_active_tier()
                self._activate_next_thread(agent.name)
                return
            self._activate_next_thread(agent.name)
            return

        tier = self._tier_map.get(agent.name) or self._extract_tier(agent)
        active = self._active_tier()
        if tier != active:
            return

        seen = self.state.get("tier_seen", {})
        if tier not in seen:
            seen[tier] = []
        if agent.name not in seen[tier]:
            seen[tier].append(agent.name)

        expected_agents = self._active_targets_for_tier(tier) or self._agents_by_tier.get(tier, [])
        if expected_agents and all(name in seen[tier] for name in expected_agents):
            active_targets = self.state.get("active_tier_targets") or {}
            active_targets.pop(tier, None)
            self.state["active_tier_targets"] = active_targets
            transmitted = bool((self.state.get("tier_transmitted") or {}).get(tier, False))
            if (
                self.state.get("task_mode") == "cascade"
                and self._cascade_mode() == "distortion_cascade"
                and not self._must_complete_current_cascade()
                and not transmitted
            ):
                self.state["current_tier_idx"] = len(self.tier_order)
                self.state["complete"] = True
                self.state["processed_policy_version"] = int(self.state.get("policy_version", 0) or 0)
                self._set_force_complete_current_cascade(False)
                self.state["tier_seen"] = {t: [] for t in self.tier_order}
                self._normalize_active_tier()
                return
            next_idx = self.tier_order.index(tier) + 1
            if next_idx < len(self.tier_order):
                self.state["current_tier_idx"] = next_idx
                if (
                    self.state.get("task_mode") == "cascade"
                    and (self.state.get("social_network") or {})
                    and not self._active_targets_for_tier(self.tier_order[next_idx])
                    and not self._private_recipient_names()
                ):
                    simulator.emit_event(
                        "cascade_network_dead_end",
                        self._cascade_dead_end_data(agent),
                    )
                    self.state["current_tier_idx"] = len(self.tier_order)
                    self.state["complete"] = True
                    self.state["processed_policy_version"] = int(self.state.get("policy_version", 0) or 0)
                    self._set_force_complete_current_cascade(False)
            else:
                self.state["current_tier_idx"] = len(self.tier_order)
                self.state["complete"] = True
                self.state["processed_policy_version"] = int(self.state.get("policy_version", 0) or 0)
                self._set_force_complete_current_cascade(False)
            self.state["tier_seen"] = {t: [] for t in self.tier_order}
            self._normalize_active_tier()

    def is_complete(self):
        if str(self.state.get("task_mode") or "") == "follow_up":
            return False
        return bool(self.state.get("complete"))

    def serialize_config(self) -> dict:
        return {
            "tier_order": list(self.tier_order),
            "cascade_mode": self._cascade_mode(),
            "distortion_strength": self._distortion_strength(),
            "conflict_sensitivity": self._conflict_sensitivity(),
            "block_probability": self._block_probability(),
        }

    @classmethod
    def deserialize_config(cls, config: dict) -> dict:
        params = config.get("parameters") or {}
        return {
            "tier_order": _parse_tier_order(config.get("tier_order") or params.get("tier_order")),
            "cascade_mode": str(config.get("cascade_mode") or params.get("cascade_mode") or "strict_cascade"),
            "distortion_strength": float(config.get("distortion_strength") or params.get("distortion_strength") or 0.6),
            "conflict_sensitivity": float(config.get("conflict_sensitivity") or params.get("conflict_sensitivity") or 0.5),
            "block_probability": float(config.get("block_probability") or params.get("block_probability") or 0.25),
        }
