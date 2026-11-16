from __future__ import annotations

import re
from typing import List

from fos.core.agent import Agent


class PolicyCascadeThreadMixin:
    def _next_thread_id(self) -> str:
        current = int(self.state.get("thread_counter", 0) or 0) + 1
        self.state["thread_counter"] = current
        return f"thread-{current}"

    def _thread_store(self) -> dict:
        threads = self.state.get("conversation_threads") or {}
        if type(threads) is not dict:
            threads = {}
        for thread_id, thread in list(threads.items()):
            if type(thread) is dict and "id" not in thread:
                normalized = dict(thread)
                normalized["id"] = thread_id
                threads[thread_id] = normalized
        self.state["conversation_threads"] = threads
        return threads

    def _thread_for_id(self, thread_id: str) -> dict:
        thread = dict((self._thread_store().get(thread_id) or {}))
        if thread and "id" not in thread:
            thread["id"] = thread_id
        return thread

    def _replace_thread(self, thread_id: str, thread: dict) -> None:
        threads = self._thread_store()
        threads[thread_id] = thread
        self.state["conversation_threads"] = threads

    def _thread_issue_candidates(self, agent: Agent, tier: str) -> List[str]:
        policy_profile = self._policy_signal_profile()
        issues = []
        if policy_profile["burden"] >= 0.45:
            issues.append("执行成本过高")
        if policy_profile["resource_gap"] >= 0.35 or self._condition_value("resource_shortage") >= 0.35:
            issues.append("资源不足")
        if self._conflict_pressure(agent, tier) >= 0.55:
            issues.append("目标冲突")
        if self._condition_value("public_opinion_pressure") >= 0.4:
            issues.append("群体反弹")
        if self._condition_value("assessment_cycle") >= 0.45 or policy_profile["report"] >= 0.45:
            issues.append("无法按时完成")
        return issues[:3]

    def _policy_invariants(self) -> List[str]:
        source_policy = str(self.state.get("source_policy") or self.state.get("latest_policy") or "")
        return re.findall(r"“([^”]+)”", source_policy)

    def _message_drops_invariants(self, message: str) -> bool:
        invariants = self._policy_invariants()
        if not invariants:
            return False
        normalized = str(message or "")
        return any(item not in normalized for item in invariants)

    def _thread_policy_version(self, thread: dict) -> int:
        metadata = thread.get("metadata") or {}
        return int(metadata.get("policy_version", self.state.get("policy_version", 0)) or 0)

    def _threads_for_sender(self, sender_name: str, kinds: List[str] | None = None, statuses: List[str] | None = None) -> List[dict]:
        current_version = int(self.state.get("policy_version", 0) or 0)
        result = []
        for thread in (self._thread_store().values() or []):
            if str(thread.get("root_sender") or thread.get("sender") or "") != sender_name:
                continue
            if self._thread_policy_version(thread) != current_version:
                continue
            if kinds and str(thread.get("kind") or "") not in kinds:
                continue
            if statuses and str(thread.get("status") or "") not in statuses:
                continue
            result.append(dict(thread))
        return result

    def _has_active_thread(self, sender_name: str, recipient_name: str, kinds: List[str]) -> bool:
        current_version = int(self.state.get("policy_version", 0) or 0)
        for thread in (self._thread_store().values() or []):
            if self._thread_policy_version(thread) != current_version:
                continue
            if str(thread.get("root_sender") or thread.get("sender") or "") != sender_name:
                continue
            if str(thread.get("root_recipient") or thread.get("last_recipient") or "") != recipient_name:
                continue
            if str(thread.get("kind") or "") not in kinds:
                continue
            if str(thread.get("status") or "") in {"ignored", "closed"}:
                continue
            return True
        return False

    def _ignored_feedback_count(self, sender_name: str) -> int:
        ignored = self._threads_for_sender(
            sender_name,
            kinds=["upward_feedback", "escalation", "skip_level_complaint"],
            statuses=["ignored"],
        )
        return len(ignored)

    def _dialogue_attempt_count(self, sender_name: str) -> int:
        threads = self._threads_for_sender(
            sender_name,
            kinds=["upward_feedback", "peer_consult", "escalation", "skip_level_complaint"],
        )
        attempts = 0
        for thread in threads:
            attempts += 1
            history = list(thread.get("history") or [])
            if len(history) > 1:
                attempts += len(history) - 1
            if str(thread.get("status") or "") == "ignored":
                attempts += 1
        return attempts

    def _direct_superior_interpretation(self, agent: Agent) -> str:
        direct = self._upstream_targets(agent, 1)
        if not direct:
            return ""
        item = dict((self._branch_interpretations().get(direct[0]) or {}))
        return str(item.get("message") or "")

    def _severe_skip_level_risk(self, agent: Agent, tier: str) -> bool:
        policy_profile = self._policy_signal_profile()
        superior_message = self._direct_superior_interpretation(agent)
        if self._message_drops_invariants(superior_message):
            return True
        if policy_profile["resource_gap"] >= 0.55 and policy_profile["report"] >= 0.45:
            return True
        if self._ignored_feedback_count(agent.name) >= 2:
            return True
        return False

    def _strict_adjustment_threshold_reached(self, agent: Agent, tier: str, current_thread: dict | None = None) -> bool:
        policy_profile = self._policy_signal_profile()
        current_thread = current_thread or {}
        thread_kind = str(current_thread.get("kind") or "")
        public_pressure = self._condition_value("public_opinion_pressure")
        inspection_pressure = self._condition_value("inspection_pressure")
        assessment_cycle = self._condition_value("assessment_cycle")
        resource_shortage = self._condition_value("resource_shortage")
        conflict_pressure = self._conflict_pressure(agent, tier)
        ignored_count = self._ignored_feedback_count(agent.name)
        severe = self._severe_skip_level_risk(agent, tier)

        if self._message_drops_invariants(self._direct_superior_interpretation(agent)):
            return True
        if tier == self.tier_order[0] and public_pressure >= 0.9 and inspection_pressure >= 0.8:
            return True
        if resource_shortage >= 0.9 and assessment_cycle >= 0.85 and conflict_pressure >= 0.8:
            return True
        if thread_kind in {"escalation", "skip_level_complaint"} and severe and (
            public_pressure >= 0.75 or resource_shortage >= 0.85 or inspection_pressure >= 0.75
        ):
            return True
        if ignored_count >= 2 and severe and policy_profile["report"] >= 0.7:
            return True
        return False

    def _distortion_adjustment_threshold_reached(self, agent: Agent, tier: str, current_thread: dict | None = None) -> bool:
        current_thread = current_thread or {}
        public_pressure = self._condition_value("public_opinion_pressure")
        inspection_pressure = self._condition_value("inspection_pressure")
        assessment_cycle = self._condition_value("assessment_cycle")
        resource_shortage = self._condition_value("resource_shortage")
        conflict_pressure = self._conflict_pressure(agent, tier)
        issues = self._thread_issue_candidates(agent, tier)
        ignored_count = self._ignored_feedback_count(agent.name)
        competing_count = len(self._competing_interpretations_for(agent))
        thread_kind = str(current_thread.get("kind") or "")

        if tier == self.tier_order[0]:
            if thread_kind in {"upward_feedback", "escalation", "skip_level_complaint"}:
                return (
                    public_pressure >= 0.75
                    or inspection_pressure >= 0.75
                    or resource_shortage >= 0.8
                    or (resource_shortage >= 0.7 and assessment_cycle >= 0.7)
                )
            if not self._follow_up_has_pending_threads():
                return False
            return (
                (public_pressure >= 0.85 and inspection_pressure >= 0.75)
                or (public_pressure >= 0.85 and resource_shortage >= 0.8)
                or (resource_shortage >= 0.85 and assessment_cycle >= 0.75)
            )

        if thread_kind in {"upward_feedback", "escalation", "skip_level_complaint"}:
            return True
        if public_pressure >= 0.6 or inspection_pressure >= 0.7:
            return True
        if resource_shortage >= 0.7 and assessment_cycle >= 0.6:
            return True
        if ignored_count >= 1 and (issues or conflict_pressure >= 0.55):
            return True
        if competing_count >= 2 and conflict_pressure >= 0.55:
            return True
        if issues and conflict_pressure >= 0.65:
            return True
        return False

    def _can_announce_policy_adjustment(self, agent: Agent, tier: str, current_thread: dict | None = None) -> bool:
        if tier == self.tier_order[-1]:
            return False
        if self._cascade_mode() == "strict_cascade":
            return self._strict_adjustment_threshold_reached(agent, tier, current_thread)
        return self._distortion_adjustment_threshold_reached(agent, tier, current_thread)

    def _strict_escalation_ready(self, agent: Agent, tier: str) -> bool:
        if self._cascade_mode() != "strict_cascade":
            return self._ignored_feedback_count(agent.name) >= 1
        severe = self._severe_skip_level_risk(agent, tier)
        ignored_count = self._ignored_feedback_count(agent.name)
        dialogue_attempts = self._dialogue_attempt_count(agent.name)
        return severe and ignored_count >= 2 and dialogue_attempts >= 4

    def _strict_skip_level_ready(self, agent: Agent, tier: str) -> bool:
        if self._cascade_mode() != "strict_cascade":
            return self._severe_skip_level_risk(agent, tier)
        severe = self._severe_skip_level_risk(agent, tier)
        ignored_count = self._ignored_feedback_count(agent.name)
        dialogue_attempts = self._dialogue_attempt_count(agent.name)
        return severe and ignored_count >= 3 and dialogue_attempts >= 6

    def _auto_upward_feedback_message(self, agent: Agent, target: str, issues: List[str]) -> str:
        issue_text = "、".join(issues) if issues else "执行困难"
        return self._tr("prompts.policy_cascade.threads.auto_upward", agent, target=target, issue_text=issue_text)

    def _auto_escalation_message(self, agent: Agent, target: str, issues: List[str]) -> str:
        issue_text = "、".join(issues) if issues else "执行风险"
        return self._tr("prompts.policy_cascade.threads.auto_escalation", agent, target=target, issue_text=issue_text)

    def _auto_skip_level_message(self, agent: Agent, target: str, issues: List[str]) -> str:
        issue_text = "、".join(issues) if issues else "重大执行风险"
        return self._tr("prompts.policy_cascade.threads.auto_skip_level", agent, target=target, issue_text=issue_text)

    def _auto_peer_consult_message(self, agent: Agent, target: str, issues: List[str]) -> str:
        issue_text = "、".join(issues) if issues else "口径分歧"
        return self._tr("prompts.policy_cascade.threads.auto_peer", agent, target=target, issue_text=issue_text)

    def get_skip_reason(self, agent: Agent, simulator) -> str:
        if self.state.get("complete"):
            return self._tr("prompts.policy_cascade.threads.skip_complete", agent, agent=agent.name)
        mode = str(self.state.get("task_mode") or "notice")
        private_event = self._private_event_for(agent.name)
        private_recipients = self._private_recipient_names()
        tier = self._tier_map.get(agent.name) or self._extract_tier(agent)
        if mode == "follow_up" and private_recipients:
            private_tier = self.tier_order[self._private_active_tier_idx()]
            if agent.name not in private_recipients or tier != private_tier:
                return self._tr("prompts.policy_cascade.threads.skip_wait_private_tier", agent, agent=agent.name, tier=private_tier)
            return self._tr("prompts.policy_cascade.threads.skip_private_turn", agent, agent=agent.name)
        if mode == "follow_up" and agent.name in self._follow_up_no_action_agents() and not private_event:
            return self._tr("prompts.policy_cascade.threads.skip_no_action", agent, agent=agent.name)
        active = self._active_tier()
        if tier != active:
            return self._tr("prompts.policy_cascade.threads.skip_wait_active_tier", agent, agent=agent.name, tier=active)
        active_targets = self._active_targets_for_tier(active)
        if active_targets and agent.name not in active_targets:
            return self._tr("prompts.policy_cascade.threads.skip_not_private_turn", agent, agent=agent.name)
        if private_recipients:
            private_tier = self.tier_order[self._private_active_tier_idx()]
            if private_tier == active and agent.name not in private_recipients:
                return self._tr("prompts.policy_cascade.threads.skip_not_private_turn", agent, agent=agent.name)
        return self._tr("prompts.policy_cascade.threads.skip_hold_position", agent, agent=agent.name)

    def _auto_seed_follow_up_threads(self) -> None:
        if not self._policy_follow_up_ready():
            return
        self.state["task_mode"] = "follow_up"
        opened = []
        ordered_agents = sorted(
            self.simulator.agents.values(),
            key=lambda agent: self.tier_order.index(self._tier_map.get(agent.name) or self._extract_tier(agent)),
            reverse=True,
        )
        current_version = int(self.state.get("policy_version", 0) or 0)

        for agent in ordered_agents:
            tier = self._tier_map.get(agent.name) or self._extract_tier(agent)
            if tier == self.tier_order[0]:
                continue

            issues = self._thread_issue_candidates(agent, tier)
            direct_targets = self._upstream_targets(agent, 1)
            skip_targets = self._upstream_targets(agent, 2)
            peer_targets = self._peer_targets(agent)
            consultation_needed = bool(peer_targets and (issues or self._competing_interpretations_for(agent)))

            if self._cascade_mode() == "strict_cascade":
                if consultation_needed:
                    peer = peer_targets[0]
                    if not self._has_active_thread(agent.name, peer, ["peer_consult"]):
                        thread = self._open_thread(
                            "peer_consult",
                            agent,
                            peer,
                            self._auto_peer_consult_message(agent, peer, issues),
                            self.simulator,
                            {"auto_generated": True, "policy_version": current_version, "issues": issues},
                        )
                        opened.append(thread["id"])
                        continue

                if skip_targets and self._strict_skip_level_ready(agent, tier):
                    target = skip_targets[0]
                    if not self._has_active_thread(agent.name, target, ["skip_level_complaint"]):
                        thread = self._open_thread(
                            "skip_level_complaint",
                            agent,
                            target,
                            self._auto_skip_level_message(agent, target, issues),
                            self.simulator,
                            {"auto_generated": True, "policy_version": current_version, "issues": issues},
                        )
                        opened.append(thread["id"])
                        continue

                if skip_targets and self._strict_escalation_ready(agent, tier):
                    target = skip_targets[0]
                    if not self._has_active_thread(agent.name, target, ["escalation"]):
                        thread = self._open_thread(
                            "escalation",
                            agent,
                            target,
                            self._auto_escalation_message(agent, target, issues),
                            self.simulator,
                            {"auto_generated": True, "policy_version": current_version, "issues": issues},
                        )
                        opened.append(thread["id"])
                        continue

                if direct_targets and issues:
                    target = direct_targets[0]
                    if not self._has_active_thread(agent.name, target, ["upward_feedback"]):
                        thread = self._open_thread(
                            "upward_feedback",
                            agent,
                            target,
                            self._auto_upward_feedback_message(agent, target, issues),
                            self.simulator,
                            {"auto_generated": True, "policy_version": current_version, "issues": issues},
                        )
                        opened.append(thread["id"])
                continue

            ignored_count = self._ignored_feedback_count(agent.name)
            severe = self._severe_skip_level_risk(agent, tier)

            if skip_targets and severe:
                target = skip_targets[0]
                if not self._has_active_thread(agent.name, target, ["skip_level_complaint"]):
                    thread = self._open_thread(
                        "skip_level_complaint",
                        agent,
                        target,
                        self._auto_skip_level_message(agent, target, issues),
                        self.simulator,
                        {"auto_generated": True, "policy_version": current_version, "issues": issues},
                    )
                    opened.append(thread["id"])
                    continue

            if skip_targets and ignored_count >= 1:
                target = skip_targets[0]
                if not self._has_active_thread(agent.name, target, ["escalation"]):
                    thread = self._open_thread(
                        "escalation",
                        agent,
                        target,
                        self._auto_escalation_message(agent, target, issues),
                        self.simulator,
                        {"auto_generated": True, "policy_version": current_version, "issues": issues},
                    )
                    opened.append(thread["id"])
                    continue

            if direct_targets and issues:
                target = direct_targets[0]
                if not self._has_active_thread(agent.name, target, ["upward_feedback"]):
                    thread = self._open_thread(
                        "upward_feedback",
                        agent,
                        target,
                        self._auto_upward_feedback_message(agent, target, issues),
                        self.simulator,
                        {"auto_generated": True, "policy_version": current_version, "issues": issues},
                    )
                    opened.append(thread["id"])

            if consultation_needed:
                peer = peer_targets[0]
                if not self._has_active_thread(agent.name, peer, ["peer_consult"]):
                    thread = self._open_thread(
                        "peer_consult",
                        agent,
                        peer,
                        self._auto_peer_consult_message(agent, peer, issues),
                        self.simulator,
                        {"auto_generated": True, "policy_version": current_version, "issues": issues},
                    )
                    opened.append(thread["id"])

        if opened:
            self.simulator.emit_event(
                "auto_follow_up_seeded",
                {
                    "threads": opened,
                    "policy_version": current_version,
                },
            )
