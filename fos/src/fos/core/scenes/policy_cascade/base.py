from __future__ import annotations

import re
from typing import Dict, List

from fos.core.agent import Agent
from fos.i18n import T

from .constants import DEFAULT_TIER_ORDER, get_follow_up_no_action_message, _has_meaningful_notice_content, _normalize_tier_token, _parse_tier_order


class PolicyCascadeBaseMixin:
    def __init__(
        self,
        name: str,
        initial_event: str,
        tier_order: List[str] | None = None,
        cascade_mode: str = "strict_cascade",
        distortion_strength: float = 0.6,
        conflict_sensitivity: float = 0.5,
        block_probability: float = 0.25,
    ):
        super().__init__(name, initial_event)
        self.tier_order = _parse_tier_order(tier_order or DEFAULT_TIER_ORDER)
        self.state["current_tier_idx"] = 0
        self.state["tier_seen"] = {t: [] for t in self.tier_order}
        self.state["tier_transmitted"] = {t: False for t in self.tier_order}
        self.state["tier_order"] = list(self.tier_order)
        self.state["latest_policy"] = ""
        self.state["source_policy"] = ""
        self.state["relayed_policy"] = ""
        self.state["latest_notice"] = str(initial_event or "")
        self.state["latest_environment_notice"] = ""
        self.state["task_mode"] = "notice"
        self.state["notice_kind"] = "execution"
        self.state["cascade_mode"] = cascade_mode
        self.state["distortion_strength"] = distortion_strength
        self.state["conflict_sensitivity"] = conflict_sensitivity
        self.state["block_probability"] = block_probability
        self.state["private_events"] = {}
        self.state["active_tier_targets"] = {}
        self.state["policy_version"] = 0
        self.state["processed_policy_version"] = -1
        self.state["conversation_threads"] = {}
        self.state["thread_inboxes"] = {}
        self.state["thread_counter"] = 0
        self.state["persistent_conditions"] = {}
        self.state["pending_follow_up_conditions"] = {}
        self.state["follow_up_thread_seeds"] = []
        self.state["follow_up_no_action_agents"] = []
        self.state["follow_up_public_done_agents"] = []
        self.state["follow_up_force_tier_order"] = False
        self.state["informal_network"] = {}
        self.state["branch_interpretations"] = {}
        self.state["force_complete_current_cascade"] = False
        self.state["complete"] = False
        self._tier_map: Dict[str, str] = {}
        self._agents_by_tier: Dict[str, List[str]] = {t: [] for t in self.tier_order}

    def _scene_locale(self, actor: Agent | None = None) -> str:
        locale = str(self.state.get("locale") or self.state.get("language") or "").strip()
        if locale:
            return locale
        agent_locale = str(getattr(actor, "language", "") or "").strip()
        if agent_locale and agent_locale != "en":
            return agent_locale
        return "zh"

    def _tr(self, key: str, actor: Agent | None = None, **kwargs) -> str:
        return T(key, locale=self._scene_locale(actor), **kwargs)

    def _follow_up_no_action_message(self, actor: Agent | None = None) -> str:
        return get_follow_up_no_action_message(self._scene_locale(actor))

    def configure_from_config(self, config: dict) -> None:
        params = config.get("parameters") or {}
        raw_order = params.get("tier_order") or config.get("tier_order")
        self.tier_order = _parse_tier_order(raw_order)
        cascade_mode = str(params.get("cascade_mode") or config.get("cascade_mode") or "strict_cascade").strip() or "strict_cascade"
        distortion_strength = float(params.get("distortion_strength") or config.get("distortion_strength") or 0.6)
        conflict_sensitivity = float(params.get("conflict_sensitivity") or config.get("conflict_sensitivity") or 0.5)
        block_probability = float(params.get("block_probability") or config.get("block_probability") or 0.25)
        self.state["tier_order"] = list(self.tier_order)
        self.state["tier_seen"] = {tier: [] for tier in self.tier_order}
        self.state["tier_transmitted"] = {tier: False for tier in self.tier_order}
        self.state["cascade_mode"] = cascade_mode
        self.state["distortion_strength"] = distortion_strength
        self.state["conflict_sensitivity"] = conflict_sensitivity
        self.state["block_probability"] = block_probability
        self.state["source_policy"] = ""
        self.state["relayed_policy"] = ""
        self.state.setdefault("latest_environment_notice", "")
        self.state["private_events"] = {}
        self.state["active_tier_targets"] = {}
        self.state.setdefault("policy_version", 0)
        self.state.setdefault("processed_policy_version", -1)
        self.state.setdefault("conversation_threads", {})
        self.state.setdefault("thread_inboxes", {})
        self.state.setdefault("thread_counter", 0)
        self.state.setdefault("persistent_conditions", {})
        self.state.setdefault("pending_follow_up_conditions", {})
        self.state.setdefault("follow_up_thread_seeds", [])
        self.state.setdefault("follow_up_no_action_agents", [])
        self.state.setdefault("follow_up_public_done_agents", [])
        self.state.setdefault("follow_up_force_tier_order", False)
        self.state.setdefault("informal_network", {})
        self.state.setdefault("branch_interpretations", {})
        self.state.setdefault("force_complete_current_cascade", False)
        self._agents_by_tier = {tier: [] for tier in self.tier_order}

    def _reset_agents_for_new_policy(self, simulator) -> None:
        for agent in simulator.agents.values():
            # Legacy Agent attributes — reset if present
            if hasattr(agent, "consecutive_llm_errors"):
                agent.consecutive_llm_errors = 0
            if hasattr(agent, "is_offline"):
                agent.is_offline = False
            # Legacy Agent: clean [Action] prefixes from short_memory
            if hasattr(agent, "short_memory") and hasattr(agent.short_memory, "history"):
                for entry in agent.short_memory.history:
                    if entry.get("role") != "assistant":
                        continue
                    lines = [
                        line
                        for line in str(entry.get("content") or "").splitlines()
                        if not line.startswith("[Action]")
                    ]
                    entry["content"] = "\n".join(lines).strip()
            # ExperimentAgent: clear feedback buffer for new policy
            if hasattr(agent, "clear_feedback_buffer"):
                agent.clear_feedback_buffer()

    def _relay_policy_text(self, message: str, fallback_policy: str) -> str:
        cleaned = self._clean_policy_text(str(message or ""))
        if not cleaned:
            return self._clean_policy_text(str(fallback_policy or ""))

        kept_lines = []
        for line in cleaned.splitlines():
            stripped = line.strip()
            if stripped.startswith("态度：") or stripped.startswith("补充："):
                break
            kept_lines.append(line)

        relay = self._clean_policy_text("\n".join(kept_lines))
        if relay:
            return relay
        return self._clean_policy_text(str(fallback_policy or ""))

    def _set_force_complete_current_cascade(self, enabled: bool) -> None:
        self.state["force_complete_current_cascade"] = bool(enabled)

    def should_extend_run(self, turns_completed: int, max_turns: int) -> bool:
        task_mode = str(self.state.get("task_mode") or "")
        if task_mode == "follow_up" and self._follow_up_requires_tier_order():
            active_tier = self._active_tier()
            expected_agents = self._agents_by_tier.get(active_tier, [])
            if not expected_agents:
                return False
            seen = list((self.state.get("tier_seen", {}) or {}).get(active_tier, []) or [])
            return any(name not in seen for name in expected_agents)

        if task_mode != "cascade" or bool(self.state.get("complete")):
            return False
        if bool(self.state.get("force_complete_current_cascade")):
            return True
        active_tier = self._active_tier()
        expected_agents = self._active_targets_for_tier(active_tier) or self._agents_by_tier.get(active_tier, [])
        if not expected_agents:
            return False
        seen = list((self.state.get("tier_seen", {}) or {}).get(active_tier, []) or [])
        return any(name not in seen for name in expected_agents)

    def set_simulator(self, simulator):
        self.simulator = simulator
        self._rebuild_tiers()
        self._normalize_active_tier()

    def reset_for_run(self):
        self.state["complete"] = False
        self._set_force_complete_current_cascade(False)
        self.state["tier_seen"] = {t: [] for t in self.tier_order}
        self.state["tier_transmitted"] = {t: False for t in self.tier_order}
        self.state["active_tier_targets"] = {}
        self._rebuild_tiers()
        self._apply_pending_follow_up_conditions()
        self._materialize_seeded_threads()
        if not self._private_recipient_names() and not self._follow_up_requires_tier_order():
            self._auto_seed_follow_up_threads()
        self._clear_follow_up_public_done_agents()
        if self._follow_up_has_pending_threads():
            self.state["task_mode"] = "follow_up"
        elif self._policy_follow_up_ready() and not self._private_recipient_names():
            self.state["task_mode"] = "follow_up"
        if self._private_recipient_names():
            self.state["current_tier_idx"] = self._private_active_tier_idx()
        else:
            self.state["current_tier_idx"] = 0
        self._normalize_active_tier()

    def on_event(self, sim, event_type: str, data):
        if event_type in {"environment", "broadcast"}:
            self._clear_follow_up_no_action_agents()
            self._clear_follow_up_public_done_agents()
            if self._apply_persistent_condition_event(sim, event_type, data):
                return None

            if event_type == "environment" or bool(data.get("notice_only")):
                desc = data.get("description") or data.get("content") or data.get("message") or ""
                cleaned_desc = self._clean_policy_text(str(desc))
                if not _has_meaningful_notice_content(cleaned_desc):
                    return None
                self.state["latest_notice"] = cleaned_desc
                self.state["latest_environment_notice"] = cleaned_desc
                self.state["notice_kind"] = self._detect_notice_kind(cleaned_desc)
                self._apply_notice_condition_updates(sim, "environment_notice", cleaned_desc)
                sim.emit_event(
                    "environment_notice_received",
                    {
                        "event_type": event_type,
                        "content": cleaned_desc,
                        "mode": self._cascade_mode(),
                    },
                )
                if self._policy_follow_up_ready():
                    self._reopen_public_follow_up_after_environment()
                return None

            self.state["current_tier_idx"] = 0
            self.state["tier_seen"] = {t: [] for t in self.tier_order}
            self.state["tier_transmitted"] = {t: False for t in self.tier_order}
            self.state["private_events"] = {}
            self.state["active_tier_targets"] = {}
            self.state["conversation_threads"] = {}
            self.state["thread_inboxes"] = {}
            self.state["branch_interpretations"] = {}
            desc = data.get("description") or data.get("content") or data.get("message") or ""
            cleaned_desc = self._clean_policy_text(str(desc))
            if not _has_meaningful_notice_content(cleaned_desc):
                return None
            self.state["latest_notice"] = cleaned_desc
            self.state["latest_environment_notice"] = ""
            self.state["policy_version"] = int(self.state.get("policy_version", 0) or 0) + 1
            self.state["latest_policy"] = cleaned_desc
            self.state["source_policy"] = cleaned_desc
            self.state["relayed_policy"] = cleaned_desc
            self.state["task_mode"] = "cascade"
            self.state["notice_kind"] = "execution"
            self._set_force_complete_current_cascade(True)
            self._reset_agents_for_new_policy(sim)
            if self._cascade_mode() == "distortion_cascade":
                sim.emit_event(
                    "cascade_input_classified",
                    {
                        "event_type": event_type,
                        "content": cleaned_desc,
                        "entered_distortion_chain": True,
                        "mode": self._cascade_mode(),
                    },
                )
            self.state["complete"] = False
            self._rebuild_tiers()
            self._normalize_active_tier()
        return None

    def on_private_event(self, sim, event_type: str, data, recipients: List[str]):
        if event_type not in {"environment", "broadcast"}:
            return None

        self._clear_follow_up_no_action_agents()

        if self._apply_persistent_condition_event(sim, event_type, data):
            return None

        if event_type == "environment" or bool(data.get("notice_only")):
            desc = data.get("description") or data.get("content") or data.get("message") or ""
            cleaned_desc = self._clean_policy_text(str(desc))
            if not _has_meaningful_notice_content(cleaned_desc):
                return None
            self.state["latest_notice"] = cleaned_desc
            self.state["latest_environment_notice"] = cleaned_desc
            self.state["notice_kind"] = self._detect_notice_kind(cleaned_desc)
            self._apply_notice_condition_updates(sim, "environment_private_notice", cleaned_desc)
            sim.emit_event(
                "environment_private_notice_received",
                {
                    "event_type": event_type,
                    "content": cleaned_desc,
                    "recipients": recipients,
                },
            )
            return None

        desc = data.get("description") or data.get("content") or data.get("message") or ""
        cleaned_desc = self._clean_policy_text(str(desc))
        if not _has_meaningful_notice_content(cleaned_desc):
            return None
        private_payload = {
            "latest_notice": cleaned_desc,
            "latest_environment_notice": cleaned_desc,
            "latest_policy": cleaned_desc,
            "source_policy": cleaned_desc,
            "relayed_policy": cleaned_desc,
            "task_mode": "cascade",
            "notice_kind": "execution",
        }

        private_events = self.state.get("private_events") or {}
        for name in recipients:
            private_events[name] = dict(private_payload)
        self.state["private_events"] = private_events
        active_targets = self.state.get("active_tier_targets") or {}
        for name in recipients:
            tier = self._tier_map.get(name) or ""
            if not tier:
                continue
            current = list(active_targets.get(tier) or [])
            if name not in current:
                current.append(name)
            active_targets[tier] = current
        self.state["active_tier_targets"] = active_targets

        for visible_to in recipients:
            visible_tier = self._tier_map.get(visible_to) or ""
            sim.emit_event(
                "private_cascade_input",
                {
                    "event_type": event_type,
                    "content": cleaned_desc,
                    "visible_to": visible_to,
                    "visible_tier": visible_tier,
                    "recipients": list(recipients),
                },
            )

        self.state["complete"] = False
        self.state["tier_seen"] = {t: [] for t in self.tier_order}
        self.state["tier_transmitted"] = {t: False for t in self.tier_order}
        self.state["conversation_threads"] = {}
        self.state["thread_inboxes"] = {}
        self.state["branch_interpretations"] = {}
        self.state["task_mode"] = "cascade"
        self.state["notice_kind"] = "execution"
        self.state["latest_notice"] = cleaned_desc
        self.state["latest_policy"] = cleaned_desc
        self.state["source_policy"] = cleaned_desc
        self.state["relayed_policy"] = cleaned_desc
        self._rebuild_tiers()

        recipient_tiers = [self._tier_map.get(name) for name in recipients if self._tier_map.get(name)]
        if recipient_tiers:
            first_tier = min(self.tier_order.index(tier) for tier in recipient_tiers)
            self.state["current_tier_idx"] = first_tier
        else:
            self.state["current_tier_idx"] = 0
        self.state["policy_version"] = int(self.state.get("policy_version", 0) or 0) + 1
        self._set_force_complete_current_cascade(True)
        self._reset_agents_for_new_policy(sim)
        self._normalize_active_tier()
        return None

    def _normalize_allowed_tier(self, value: str) -> str:
        text = str(value or "").strip()
        if not text:
            return ""

        for tier in self.tier_order:
            if text.lower() == tier.lower():
                return tier

        legacy = _normalize_tier_token(text)
        if legacy:
            for tier in self.tier_order:
                if _normalize_tier_token(tier) == legacy:
                    return tier

        compact = re.sub(r"[\s_-]+", "", text).lower()
        for tier in self.tier_order:
            tier_compact = re.sub(r"[\s_-]+", "", tier).lower()
            if compact == tier_compact or compact in tier_compact or tier_compact in compact:
                return tier

        return ""

    def _extract_tier(self, agent: Agent) -> str:
        properties = getattr(agent, "properties", {}) or {}
        tier = self._normalize_allowed_tier(str(properties.get("tier", "")))
        if tier:
            return tier

        tier_level = self._normalize_allowed_tier(str(properties.get("tier_level", "")))
        if tier_level:
            return tier_level

        profile_tier = self._normalize_allowed_tier(str(properties.get("政治职位层级", "")))
        if profile_tier:
            return profile_tier

        text = " ".join([
            str(getattr(agent, "role_prompt", "")),
            str(getattr(agent, "user_profile", "")),
        ])
        match = re.search(r"政治职位层级[:：]\s*([^|\n]+)", text)
        if match:
            matched = self._normalize_allowed_tier(match.group(1))
            if matched:
                return matched

        inferred = self._normalize_allowed_tier(text)
        if inferred:
            return inferred

        return self.tier_order[min(1, len(self.tier_order) - 1)]

    def _tier_role_kind(self, tier: str) -> str:
        idx = self.tier_order.index(tier) if tier in self.tier_order else 0
        if idx <= 0:
            return "top"
        if idx >= len(self.tier_order) - 1:
            return "low"
        return "mid"

    def _cascade_mode(self) -> str:
        mode = str(self.state.get("cascade_mode", "strict_cascade") or "strict_cascade")
        if mode not in {"strict_cascade", "distortion_cascade"}:
            return "strict_cascade"
        return mode

    def _distortion_strength(self) -> float:
        return float(self.state.get("distortion_strength", 0.6) or 0.0)

    def _conflict_sensitivity(self) -> float:
        return float(self.state.get("conflict_sensitivity", 0.5) or 0.0)

    def _block_probability(self) -> float:
        return float(self.state.get("block_probability", 0.25) or 0.0)
