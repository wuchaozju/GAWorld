from __future__ import annotations

import re
from typing import List

from .constants import get_follow_up_no_action_message


class PolicyCascadeStateMixin:
    def _rebuild_tiers(self) -> None:
        self._tier_map = {}
        names = list(self.simulator.agents.keys())
        for name, agent in self.simulator.agents.items():
            self._tier_map[name] = self._extract_tier(agent)

        present = {t for t in self._tier_map.values() if t in self.tier_order}
        if len(present) < len(self.tier_order) and names:
            for idx, name in enumerate(names):
                tier = self._tier_map.get(name)
                if tier not in self.tier_order:
                    forced = self.tier_order[min(idx, len(self.tier_order) - 1)]
                    self._tier_map[name] = forced
                    present.add(forced)

        self._agents_by_tier = {t: [] for t in self.tier_order}
        for name, tier in self._tier_map.items():
            if tier in self.tier_order:
                self._agents_by_tier[tier].append(name)

    def _normalize_active_tier(self) -> None:
        idx = int(self.state.get("current_tier_idx", 0))
        while idx < len(self.tier_order):
            tier = self.tier_order[idx]
            if self._agents_by_tier.get(tier):
                break
            idx += 1
        self.state["current_tier_idx"] = min(idx, len(self.tier_order) - 1)

    def _active_tier(self) -> str:
        self._normalize_active_tier()
        idx = int(self.state.get("current_tier_idx", 0))
        return self.tier_order[min(max(idx, 0), len(self.tier_order) - 1)]

    def _private_event_for(self, agent_name: str) -> dict:
        private_events = self.state.get("private_events") or {}
        return private_events.get(agent_name) or {}

    def _private_recipient_names(self) -> List[str]:
        private_events = self.state.get("private_events") or {}
        return [name for name in private_events.keys() if name]

    def _private_active_tier_idx(self) -> int:
        names = self._private_recipient_names()
        tiers = [self._tier_map.get(name) for name in names if self._tier_map.get(name)]
        if not tiers:
            return 0
        return min(self.tier_order.index(tier) for tier in tiers)

    def _follow_up_no_action_agents(self) -> List[str]:
        names = self.state.get("follow_up_no_action_agents") or []
        return [name for name in names if name in self.simulator.agents]

    def _follow_up_public_done_agents(self) -> List[str]:
        names = self.state.get("follow_up_public_done_agents") or []
        return [name for name in names if name in self.simulator.agents]

    def _follow_up_requires_tier_order(self) -> bool:
        return bool(self.state.get("follow_up_force_tier_order")) and str(self.state.get("task_mode") or "") == "follow_up"

    def _clear_follow_up_no_action_agents(self) -> None:
        self.state["follow_up_no_action_agents"] = []

    def _clear_follow_up_public_done_agents(self) -> None:
        self.state["follow_up_public_done_agents"] = []

    def _mark_follow_up_public_done(self, agent_name: str) -> None:
        current = [name for name in self._follow_up_public_done_agents() if name != agent_name]
        current.append(agent_name)
        self.state["follow_up_public_done_agents"] = current

    def _clear_follow_up_public_done(self, agent_name: str) -> None:
        self.state["follow_up_public_done_agents"] = [
            name for name in self._follow_up_public_done_agents() if name != agent_name
        ]

    def _is_follow_up_no_action_message(self, message: str) -> bool:
        normalized = self._sanitize_message(str(message or ""))
        if not normalized:
            return False
        return normalized in {
            self._follow_up_no_action_message(),
            get_follow_up_no_action_message("zh"),
            get_follow_up_no_action_message("en"),
        }

    def _record_follow_up_message_state(self, agent_name: str, message: str, mode: str) -> None:
        if mode not in {"follow_up", "follow_up_thread"}:
            return
        current = [name for name in self._follow_up_no_action_agents() if name != agent_name]
        if self._is_follow_up_no_action_message(message):
            current.append(agent_name)
        self.state["follow_up_no_action_agents"] = current

    def _follow_up_no_action_signal(self, payload: dict) -> bool:
        action_field = payload.get("action")
        if type(action_field) is dict:
            action_name = str(action_field.get("name") or action_field.get("action") or action_field.get("type") or "").strip().lower()
        else:
            action_name = str(action_field or payload.get("type") or "").strip().lower()
        if action_name in {"none", "no_action"}:
            return True
        primary = self._sanitize_message(
            str(
                payload.get("message")
                or payload.get("content")
                or payload.get("text")
                or payload.get("context")
                or payload.get("reason")
                or ""
            )
        )
        if primary and not self._is_follow_up_no_action_message(primary):
            return False
        texts = [
            primary,
            str(payload.get("response") or ""),
            str(payload.get("thoughts") or ""),
            str(payload.get("status") or ""),
            str(payload.get("reason") or ""),
            str((payload.get("metadata") or {}).get("status") or ""),
            str((payload.get("metadata") or {}).get("notes") or ""),
            str((payload.get("metadata") or {}).get("reason") or ""),
        ]
        combined = "\n".join(texts)
        if self._is_follow_up_no_action_message(combined):
            return True
        return (
            any(marker in combined for marker in ["无动作倾向", "no remaining action tendency", "no further action tendency"])
            and any(marker in combined for marker in ["建议注入新的环境事件或发布新的政策", "inject a new environment event or release a new policy"])
        )

    def _reopen_public_follow_up_after_environment(self) -> None:
        self.state["task_mode"] = "follow_up"
        self.state["private_events"] = {}
        self.state["conversation_threads"] = {}
        self.state["thread_inboxes"] = {}
        self.state["active_tier_targets"] = {}
        self.state["follow_up_no_action_agents"] = []
        self.state["follow_up_public_done_agents"] = []
        self.state["follow_up_force_tier_order"] = True
        self.state["tier_seen"] = {t: [] for t in self.tier_order}
        self.state["tier_transmitted"] = {t: False for t in self.tier_order}
        self.state["complete"] = False
        self.state["current_tier_idx"] = 0
        self._normalize_active_tier()

    def _persistent_conditions(self) -> dict:
        conditions = self.state.get("persistent_conditions") or {}
        return conditions if type(conditions) is dict else {}

    def _pending_follow_up_conditions(self) -> dict:
        conditions = self.state.get("pending_follow_up_conditions") or {}
        return conditions if type(conditions) is dict else {}

    def _apply_pending_follow_up_conditions(self) -> None:
        pending = self._pending_follow_up_conditions()
        if not pending:
            return
        merged = dict(self._persistent_conditions())
        for key, value in pending.items():
            merged[key] = self._clamp01(float(value))
        self.state["persistent_conditions"] = merged
        self.state["pending_follow_up_conditions"] = {}

    def _follow_up_thread_seeds(self) -> List[dict]:
        seeds = self.state.get("follow_up_thread_seeds") or []
        return seeds if type(seeds) is list else []

    def _materialize_seeded_threads(self) -> None:
        seeds = list(self._follow_up_thread_seeds())
        if not seeds:
            return
        self.state["follow_up_thread_seeds"] = []
        self.state["task_mode"] = "follow_up"
        for seed in seeds:
            sender_name = str(seed.get("sender") or "").strip()
            recipient_name = str(seed.get("recipient") or "").strip()
            kind = str(seed.get("kind") or "peer_consult").strip() or "peer_consult"
            message = self._sanitize_message(str(seed.get("message") or ""))
            metadata = dict(seed.get("metadata") or {})
            notice = str(seed.get("notice") or "").strip()
            if notice:
                self.state["latest_notice"] = notice
            sender = self.simulator.agents[sender_name]
            self._open_thread(kind, sender, recipient_name, message, self.simulator, metadata)

    def _condition_value(self, *keys: str) -> float:
        conditions = self._persistent_conditions()
        for key in keys:
            if key in conditions:
                return self._clamp01(float(conditions.get(key) or 0.0))
        return 0.0

    def _parse_persistent_condition_payload(self, raw_text: str) -> dict:
        text = str(raw_text or "").strip()
        if not text:
            return {}
        cleaned = text.replace("；", ",").replace("\n", ",")
        pairs = [part.strip() for part in re.split(r"[,，]+", cleaned) if part.strip()]
        result = {}
        aliases = {
            "resource_shortage": "resource_shortage",
            "长期资源短缺": "resource_shortage",
            "assessment_cycle": "assessment_cycle",
            "考核周期": "assessment_cycle",
            "public_opinion_pressure": "public_opinion_pressure",
            "舆论高压": "public_opinion_pressure",
            "inspection_pressure": "inspection_pressure",
            "监察强化": "inspection_pressure",
        }
        for pair in pairs:
            if ":" in pair:
                key, value = pair.split(":", 1)
            elif "=" in pair:
                key, value = pair.split("=", 1)
            else:
                continue
            normalized = aliases.get(key.strip(), key.strip())
            result[normalized] = self._clamp01(float(value.strip()))
        return result

    def _infer_notice_condition_updates(self, raw_text: str) -> dict:
        text = str(raw_text or "").strip()
        if not text:
            return {}

        updates = {}
        if any(marker in text for marker in ["抗议", "游行", "示威", "群体事件", "群体性事件", "舆情", "舆论", "媒体曝光", "热搜", "举报"]):
            updates["public_opinion_pressure"] = {"value": 0.75, "mode": "raise"}
        positive_public_feedback = any(marker in text for marker in ["很满意", "表示满意", "普遍满意", "群众满意", "高度认可", "普遍支持", "积极评价", "一致好评", "欢迎这一政策", "拥护该政策", "反响良好"])
        blocking_negative_feedback = any(marker in text for marker in ["不满意", "不支持", "质疑", "反对", "投诉", "抱怨", "批评", "担忧", "焦虑", "抗议", "游行", "示威", "举报", "曝光"])
        if positive_public_feedback and not blocking_negative_feedback:
            updates["public_opinion_pressure"] = {"value": 0.15, "mode": "lower"}
        if any(marker in text for marker in ["督查", "巡视", "巡察", "约谈", "问责", "通报", "监察", "督办", "审计"]):
            updates["inspection_pressure"] = {"value": 0.7, "mode": "raise"}
        if any(marker in text for marker in ["月底", "月末", "周内", "本周内", "48小时", "24小时", "限期", "截止", "考核", "周报", "台账", "报送"]):
            updates["assessment_cycle"] = {"value": 0.65, "mode": "raise"}
        if any(marker in text for marker in ["资金紧张", "预算不足", "经费不足", "资源不足", "人手不足", "人员短缺", "无法保障", "缺编", "缩减预算"]):
            updates["resource_shortage"] = {"value": 0.7, "mode": "raise"}
        return updates

    def _apply_notice_condition_updates(self, sim, source: str, raw_text: str) -> None:
        updates = self._infer_notice_condition_updates(raw_text)
        if not updates:
            return
        merged = dict(self._persistent_conditions())
        changed = False
        for key, payload in updates.items():
            current = self._clamp01(float(merged.get(key) or 0.0))
            value = self._clamp01(float(payload["value"]))
            mode = str(payload["mode"])
            next_value = self._clamp01(max(current, value)) if mode == "raise" else self._clamp01(min(current, value))
            if next_value != current:
                merged[key] = next_value
                changed = True
        if not changed:
            return
        self.state["persistent_conditions"] = merged
        sim.emit_event(
            "persistent_conditions_updated",
            {
                "conditions": merged,
                "source": source,
            },
        )

    def _apply_persistent_condition_event(self, sim, event_type: str, data: dict) -> bool:
        if event_type != "environment":
            return False
        env_type = str(data.get("event_type") or "").strip().lower()
        if env_type not in {"persistent_condition", "institutional_condition", "system_condition"}:
            return False
        updates = self._parse_persistent_condition_payload(str(data.get("description") or ""))
        if not updates:
            return True
        merged = dict(self._persistent_conditions())
        for key, value in updates.items():
            merged[key] = self._clamp01(value)
        self.state["persistent_conditions"] = merged
        sim.emit_event(
            "persistent_conditions_updated",
            {
                "conditions": merged,
                "source": env_type,
            },
        )
        return True

    def _formal_network(self) -> dict:
        social_network = self.state.get("social_network") or {}
        return social_network if type(social_network) is dict else {}

    def _informal_network(self) -> dict:
        informal_network = self.state.get("informal_network") or {}
        return informal_network if type(informal_network) is dict else {}

    def _reverse_connections_for(self, agent_name: str) -> List[str]:
        result = []
        for sender, targets in self._formal_network().items():
            if type(targets) is not list:
                continue
            if agent_name in targets and sender in self.simulator.agents:
                result.append(sender)
        return result

    def _peer_targets(self, agent) -> List[str]:
        tier = self._tier_map.get(agent.name) or self._extract_tier(agent)
        same_tier = [name for name in self._agents_by_tier.get(tier, []) if name != agent.name]
        connected = []
        informal = self._informal_network().get(agent.name) or []
        formal = self._formal_network().get(agent.name) or []
        for name in same_tier:
            if name in informal or name in formal:
                connected.append(name)
        if connected:
            return connected
        return same_tier

    def _upstream_targets(self, agent, skip_levels: int = 1) -> List[str]:
        tier = self._tier_map.get(agent.name) or self._extract_tier(agent)
        idx = self.tier_order.index(tier) if tier in self.tier_order else 0
        target_idx = idx - skip_levels
        if target_idx < 0:
            return []
        target_tier = self.tier_order[target_idx]
        reverse = self._reverse_connections_for(agent.name)
        candidates = [name for name in reverse if (self._tier_map.get(name) or self._extract_tier(self.simulator.agents[name])) == target_tier]
        if candidates:
            return candidates
        return list(self._agents_by_tier.get(target_tier, []))

    def _notify_targets(self, agent) -> List[str]:
        tier = self._tier_map.get(agent.name) or self._extract_tier(agent)
        idx = self.tier_order.index(tier) if tier in self.tier_order else 0
        if idx + 1 >= len(self.tier_order):
            return []
        next_tier = self.tier_order[idx + 1]
        direct = self._network_connections_for(agent.name)
        candidates = [name for name in direct if (self._tier_map.get(name) or self._extract_tier(self.simulator.agents[name])) == next_tier]
        if candidates:
            return candidates
        return list(self._agents_by_tier.get(next_tier, []))

    def _branch_descendants(self, sender) -> List[str]:
        seen = set()
        queue = list(self._network_connections_for(sender.name) or [])
        while queue:
            name = queue.pop(0)
            if name in seen:
                continue
            seen.add(name)
            queue.extend(self._network_connections_for(name))
        return [name for name in seen if name in self.simulator.agents]

    def _policy_follow_up_ready(self) -> bool:
        latest_policy = str(self.state.get("latest_policy") or "").strip()
        if not latest_policy:
            return False
        policy_version = int(self.state.get("policy_version", 0) or 0)
        processed = int(self.state.get("processed_policy_version", -1) or -1)
        return policy_version <= processed

    def _follow_up_has_pending_threads(self) -> bool:
        if self._private_recipient_names():
            return any(
                str((self._private_event_for(name).get("task_mode") or "")) == "follow_up_thread"
                for name in self._private_recipient_names()
            )
        inboxes = self.state.get("thread_inboxes") or {}
        return any(list(items or []) for items in inboxes.values())
