from __future__ import annotations

from fos.core.agent import Agent

class PolicyCascadePromptMixin:
    def get_behavior_guidelines(self):
        state_mode = str(self.state.get("task_mode") or "notice")
        if state_mode == "cascade":
            effective_mode = "cascade"
            effective_notice_kind = str(self.state.get("notice_kind") or "execution")
        else:
            private_recipients = self._private_recipient_names()
            private_event = self._private_event_for(private_recipients[0]) if private_recipients else {}
            effective_mode = str(private_event.get("task_mode") or state_mode or "notice")
            effective_notice_kind = str(private_event.get("notice_kind") or self.state.get("notice_kind") or "execution")

        if effective_mode == "notice":
            if effective_notice_kind == "analysis":
                return self._tr("prompts.policy_cascade.guidelines.notice_analysis")
            return self._tr("prompts.policy_cascade.guidelines.notice_execution")
        if effective_mode == "follow_up_thread":
            adjustment_rule = self._tr(
                "prompts.policy_cascade.guidelines.follow_up_thread_adjustment_strict"
                if self._cascade_mode() == "strict_cascade"
                else "prompts.policy_cascade.guidelines.follow_up_thread_adjustment_relaxed"
            )
            return self._tr(
                "prompts.policy_cascade.guidelines.follow_up_thread",
                adjustment_rule=adjustment_rule,
                no_action=self._follow_up_no_action_message(),
            )
        if effective_mode == "follow_up":
            adjustment_rule = self._tr(
                "prompts.policy_cascade.guidelines.follow_up_adjustment_strict"
                if self._cascade_mode() == "strict_cascade"
                else "prompts.policy_cascade.guidelines.follow_up_adjustment_relaxed"
            )
            return self._tr(
                "prompts.policy_cascade.guidelines.follow_up",
                adjustment_rule=adjustment_rule,
                no_action=self._follow_up_no_action_message(),
            )
        if self._cascade_mode() == "distortion_cascade":
            return self._tr(
                "prompts.policy_cascade.guidelines.distortion_cascade",
                distortion_strength=f"{self._distortion_strength():.2f}",
                conflict_sensitivity=f"{self._conflict_sensitivity():.2f}",
                block_probability=f"{self._block_probability():.2f}",
            )
        return self._tr("prompts.policy_cascade.guidelines.default_cascade")

    def _active_private_event_for(self, agent_name: str) -> dict:
        private_event = self._private_event_for(agent_name)
        state_mode = str(self.state.get("task_mode") or "notice")
        if state_mode == "cascade" and str(private_event.get("task_mode") or "") != "cascade":
            return {}
        return private_event

    def get_agent_status_prompt(self, agent: Agent) -> str:
        private_event = self._active_private_event_for(agent.name)
        notice = str(private_event.get("latest_notice") or self.state.get("latest_notice", "") or "").strip()
        environment_notice = str(private_event.get("latest_environment_notice") or self.state.get("latest_environment_notice", "") or "").strip()
        source_policy = str(private_event.get("source_policy") or self.state.get("source_policy", "") or "").strip()
        relayed_policy = str(private_event.get("relayed_policy") or self.state.get("relayed_policy", "") or private_event.get("latest_policy") or self.state.get("latest_policy", "") or "").strip()
        parts = []
        mode = self._effective_task_mode_for(agent)
        tier = self._tier_map.get(agent.name) or self._extract_tier(agent)
        role_kind = self._tier_role_kind(tier)
        issue_candidates = self._thread_issue_candidates(agent, tier)
        if mode == "notice":
            notice_kind = str(private_event.get("notice_kind") or self.state.get("notice_kind") or "execution")
            if notice_kind == "analysis":
                parts.append(self._tr("prompts.policy_cascade.status.notice_analysis", agent))
            else:
                parts.append(self._tr("prompts.policy_cascade.status.notice_execution", agent))
            if role_kind == "top":
                parts.append(self._tr("prompts.policy_cascade.status.notice_top_scope", agent))
                parts.append(self._tr("prompts.policy_cascade.status.notice_top_drift", agent))
            elif role_kind == "mid":
                parts.append(self._tr("prompts.policy_cascade.status.notice_mid_scope", agent))
                parts.append(self._tr("prompts.policy_cascade.status.notice_mid_drift", agent))
            else:
                parts.append(self._tr("prompts.policy_cascade.status.notice_low_scope", agent))
                parts.append(self._tr("prompts.policy_cascade.status.notice_low_drift", agent))
        elif mode == "cascade":
            parts.append(self._tr("prompts.policy_cascade.status.cascade_intro", agent))
            if self._cascade_mode() == "distortion_cascade":
                parts.append(self._tr("prompts.policy_cascade.status.cascade_distortion", agent))
                parts.append(self._tr("prompts.policy_cascade.status.cascade_distortion_yield", agent))
                parts.append(
                    self._tr(
                        "prompts.policy_cascade.status.cascade_params",
                        agent,
                        distortion_strength=f"{self._distortion_strength():.2f}",
                        conflict_sensitivity=f"{self._conflict_sensitivity():.2f}",
                        block_probability=f"{self._block_probability():.2f}",
                    )
                )
            if role_kind == "top":
                parts.append(self._tr("prompts.policy_cascade.status.cascade_top_scope", agent))
            elif role_kind == "mid":
                parts.append(self._tr("prompts.policy_cascade.status.cascade_mid_scope", agent))
            else:
                parts.append(self._tr("prompts.policy_cascade.status.cascade_low_scope", agent))
        elif mode == "follow_up_thread":
            thread_kind = str(private_event.get("thread_kind") or "thread")
            thread_sender = str(private_event.get("thread_sender") or "")
            thread_message = str(private_event.get("thread_message") or "")
            reply_target = str(private_event.get("reply_target") or thread_sender)
            thread_notice = str(private_event.get("thread_notice") or "")
            thread_focus = str(private_event.get("thread_focus") or "")
            thread_round_count = int(private_event.get("thread_round_count") or 0)
            thread_history_excerpt = str(private_event.get("thread_history_excerpt") or "")
            parts.append(self._tr("prompts.policy_cascade.status.follow_up_thread_intro", agent))
            if thread_notice:
                parts.append(self._tr("prompts.policy_cascade.status.thread_notice", agent, notice=thread_notice))
            parts.append(
                self._tr(
                    "prompts.policy_cascade.status.thread_meta",
                    agent,
                    thread_kind=thread_kind,
                    sender=thread_sender or self._tr("prompts.policy_cascade.shared.unknown", agent),
                    reply_target=reply_target or self._tr("prompts.policy_cascade.shared.unknown", agent),
                )
            )
            if thread_focus:
                parts.append(self._tr("prompts.policy_cascade.status.thread_focus", agent, focus=thread_focus))
            if thread_message:
                parts.append(self._tr("prompts.policy_cascade.status.thread_message", agent, message=thread_message))
            if thread_round_count > 1 and thread_history_excerpt:
                parts.append(
                    self._tr(
                        "prompts.policy_cascade.status.thread_history",
                        agent,
                        rounds=min(thread_round_count, 6),
                        history=thread_history_excerpt,
                    )
                )
                parts.append(self._tr("prompts.policy_cascade.status.thread_continue", agent))
                parts.append(self._tr("prompts.policy_cascade.status.thread_reply_requirements", agent))
            parts.append(self._tr("prompts.policy_cascade.status.thread_ban_generic", agent))
            parts.append(self._tr("prompts.policy_cascade.status.thread_no_action", agent, no_action=self._follow_up_no_action_message(agent)))
            parts.append(self._thread_target_guidance(agent))
            shock_guidance = self._thread_shock_guidance(notice, issue_candidates)
            if shock_guidance:
                parts.append(shock_guidance)
            if thread_kind in {"upward_feedback", "escalation"}:
                parts.append(self._tr("prompts.policy_cascade.status.thread_upward_options", agent))
        else:
            parts.append(self._tr("prompts.policy_cascade.status.follow_up_intro", agent))
            if private_event and str(private_event.get("task_mode") or "") == "follow_up_thread":
                parts.append(self._tr("prompts.policy_cascade.status.follow_up_public_then_private", agent))
                pending_sender = str(private_event.get("thread_sender") or private_event.get("reply_target") or "")
                pending_message = str(private_event.get("thread_message") or "")
                if pending_sender:
                    parts.append(self._tr("prompts.policy_cascade.status.pending_sender", agent, sender=pending_sender))
                if pending_message:
                    parts.append(self._tr("prompts.policy_cascade.status.pending_message", agent, message=pending_message))
            if issue_candidates:
                parts.append(self._tr("prompts.policy_cascade.status.issue_candidates", agent, issues="、".join(issue_candidates)))
            if environment_notice:
                parts.append(self._tr("prompts.policy_cascade.status.environment_notice", agent, notice=environment_notice))
                shock_guidance = self._thread_shock_guidance(environment_notice, issue_candidates)
                if shock_guidance:
                    parts.append(shock_guidance)
                else:
                    parts.append(self._tr("prompts.policy_cascade.status.environment_changed", agent))
            if notice:
                parts.append(self._tr("prompts.policy_cascade.status.latest_notice_priority", agent))
                shock_guidance = self._thread_shock_guidance(environment_notice or notice, issue_candidates)
                if shock_guidance:
                    parts.append(shock_guidance)
                else:
                    parts.append(self._tr("prompts.policy_cascade.status.external_changed", agent))
            direct_up = self._upstream_targets(agent, 1)
            skip_up = self._upstream_targets(agent, 2)
            peers = self._peer_targets(agent)
            down = self._notify_targets(agent)
            if direct_up:
                parts.append(self._tr("prompts.policy_cascade.status.direct_up", agent, targets="、".join(direct_up)))
            if skip_up:
                parts.append(self._tr("prompts.policy_cascade.status.skip_up", agent, targets="、".join(skip_up)))
            if peers:
                parts.append(self._tr("prompts.policy_cascade.status.peers", agent, targets="、".join(peers)))
            if down:
                parts.append(self._tr("prompts.policy_cascade.status.down", agent, targets="、".join(down)))
            if role_kind != "low":
                parts.append(self._tr("prompts.policy_cascade.status.announce_adjustment", agent))
            no_action_agents = self._follow_up_no_action_agents()
            if no_action_agents:
                parts.append(self._tr("prompts.policy_cascade.status.no_action_agents", agent, agents="、".join(no_action_agents)))
            parts.append(self._tr("prompts.policy_cascade.status.follow_up_continue", agent, no_action=self._follow_up_no_action_message(agent)))
        parts.append(self._tr("prompts.policy_cascade.status.no_repeat", agent))
        if notice:
            parts.append(self._tr("prompts.policy_cascade.status.latest_notice", agent, notice=notice))
            min_chars = self._extract_min_chars(notice)
            if min_chars:
                parts.append(self._tr("prompts.policy_cascade.status.min_chars", agent, min_chars=min_chars))
        if environment_notice and environment_notice != notice:
            parts.append(self._tr("prompts.policy_cascade.status.environment_full", agent, notice=environment_notice))
        if relayed_policy and relayed_policy != notice:
            prefix = self._tr(
                "prompts.policy_cascade.status.relayed_policy_bg_prefix" if mode in {"follow_up", "follow_up_thread"} and notice else "prompts.policy_cascade.status.relayed_policy_prefix",
                agent,
            )
            parts.append(f"{prefix}{self._policy_prompt_excerpt(relayed_policy)}")
        if private_event and source_policy and source_policy != relayed_policy:
            prefix = self._tr(
                "prompts.policy_cascade.status.source_policy_bg_prefix" if mode in {"follow_up", "follow_up_thread"} and notice else "prompts.policy_cascade.status.source_policy_prefix",
                agent,
            )
            parts.append(f"{prefix}{self._policy_prompt_excerpt(source_policy)}")
        conditions = self._persistent_conditions()
        if conditions:
            rendered = "、".join(f"{key}={value:.2f}" for key, value in conditions.items())
            parts.append(self._tr("prompts.policy_cascade.status.conditions", agent, conditions=rendered))
        competing = self._competing_interpretations_for(agent)
        if mode in {"follow_up", "follow_up_thread"} and competing:
            summary = "；".join(
                f"{item.get('agent')}({item.get('tier')})：{self._policy_prompt_excerpt(str(item.get('message') or ''))}"
                for item in competing[:3]
            )
            parts.append(self._tr("prompts.policy_cascade.status.competing", agent, summary=summary))
        upstream_messages = list(private_event.get("upstream_messages") or [])
        if len(upstream_messages) > 1:
            senders = "、".join(str(item.get("sender") or "上层节点") for item in upstream_messages)
            parts.append(self._tr("prompts.policy_cascade.status.multiple_upstream", agent, senders=senders))
        return "\n".join(parts)

    def _effective_task_mode_for(self, agent: Agent) -> str:
        state_mode = str(self.state.get("task_mode", "notice") or "notice")
        if state_mode == "cascade":
            return "cascade"
        private_event = self._active_private_event_for(agent.name)
        if (
            state_mode == "follow_up"
            and private_event
            and str(private_event.get("task_mode") or "") == "follow_up_thread"
            and agent.name not in self._follow_up_public_done_agents()
        ):
            return "follow_up"
        return str(private_event.get("task_mode") or state_mode or "notice")

    def _must_complete_current_cascade(self) -> bool:
        return bool(self.state.get("force_complete_current_cascade")) and str(self.state.get("task_mode") or "") == "cascade"
