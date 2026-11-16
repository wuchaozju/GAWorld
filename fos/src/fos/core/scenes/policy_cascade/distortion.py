from __future__ import annotations

import hashlib
import re
from typing import Dict, List

from fos.core.agent import Agent

from .constants import AGENT_SIGNAL_MARKERS, POLICY_LINE_MARKERS


class PolicyCascadeDistortionMixin:
    def _deterministic_score(self, *parts: str) -> float:
        text = "|".join(str(part or "") for part in parts)
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:8]
        return int(digest, 16) / 0xFFFFFFFF

    def _clamp01(self, value: float) -> float:
        return max(0.0, min(1.0, float(value)))

    def _keyword_score(self, text: str, keywords: List[str]) -> float:
        if not text:
            return 0.0
        hits = [keyword for keyword in keywords if keyword in text]
        return self._clamp01(len(hits) / max(1, len(keywords)))

    def _agent_signal_text(self, agent: Agent) -> str:
        parts = [
            str(agent.name or ""),
            str(getattr(agent, "role_prompt", "") or ""),
            str(getattr(agent, "user_profile", "") or ""),
        ]
        properties = getattr(agent, "properties", {}) or {}
        for key, value in properties.items():
            if key == "tier":
                continue
            parts.append(f"{key}:{value}")
        return "\n".join(parts)

    def _agent_signal_profile(self, agent: Agent) -> Dict[str, float]:
        text = self._agent_signal_text(agent)
        return {
            key: self._keyword_score(text, keywords)
            for key, keywords in AGENT_SIGNAL_MARKERS.items()
        }

    def _policy_signal_profile(self) -> Dict[str, float]:
        text = "\n".join([
            str(self.state.get("source_policy", "") or ""),
            str(self.state.get("relayed_policy", "") or ""),
            str(self.state.get("latest_notice", "") or ""),
        ])
        profile = {
            key: self._keyword_score(text, keywords)
            for key, keywords in POLICY_LINE_MARKERS.items()
        }
        profile["burden"] = self._clamp01(
            profile["execution"] * 0.35
            + profile["report"] * 0.35
            + profile["accountability"] * 0.2
            + profile["invariant"] * 0.1
        )
        profile["resource_gap"] = self._clamp01(
            profile["execution"] * 0.4
            + profile["report"] * 0.25
            + profile["accountability"] * 0.2
            - profile["resource"] * 0.45
        )
        resource_shortage = self._condition_value("resource_shortage")
        assessment_cycle = self._condition_value("assessment_cycle")
        public_opinion_pressure = self._condition_value("public_opinion_pressure")
        inspection_pressure = self._condition_value("inspection_pressure")
        profile["burden"] = self._clamp01(profile["burden"] + resource_shortage * 0.25 + assessment_cycle * 0.1)
        profile["resource_gap"] = self._clamp01(profile["resource_gap"] + resource_shortage * 0.45)
        profile["accountability"] = self._clamp01(profile["accountability"] + inspection_pressure * 0.35 + assessment_cycle * 0.15)
        profile["report"] = self._clamp01(profile["report"] + assessment_cycle * 0.3 + inspection_pressure * 0.1)
        profile["goal"] = self._clamp01(profile["goal"] + public_opinion_pressure * 0.1)
        return profile

    def _block_tendency(self, agent: Agent, tier: str) -> float:
        pressure = self._conflict_pressure(agent, tier)
        seed = self._deterministic_score(
            "block",
            agent.name,
            tier,
            self.state.get("source_policy", ""),
            self.state.get("relayed_policy", ""),
            self.state.get("latest_notice", ""),
        )
        activation = self._clamp01(
            0.1
            + self._distortion_strength() * 0.55
            + self._conflict_sensitivity() * 0.35
        )
        return self._clamp01(
            self._block_probability()
            + pressure * activation * 0.55
            + seed * 0.05
        )

    def _distortion_reason(self, agent: Agent, tier: str) -> str:
        agent_profile = self._agent_signal_profile(agent)
        policy_profile = self._policy_signal_profile()
        scored = [
            ("基层执行负担高", policy_profile["burden"] * (0.35 + agent_profile["burden"] * 0.35)),
            ("资源保障与任务要求不匹配", policy_profile["resource_gap"] * (0.2 + agent_profile["resource"] * 0.3)),
            ("考核问责压力触发本层自保", policy_profile["accountability"] * (0.15 + agent_profile["autonomy"] * 0.2)),
            ("报送链条过重导致转述弱化", policy_profile["report"] * (0.1 + agent_profile["burden"] * 0.15)),
        ]
        top_reasons = [label for label, score in sorted(scored, key=lambda item: item[1], reverse=True)[:2] if score > 0.08]
        if not top_reasons:
            top_reasons = ["本层判断需要重新筛选政策重点"]

        role_kind = self._tier_role_kind(tier)
        if role_kind == "top":
            role_note = "高层优先保留统筹、问责和重点指标。"
        elif role_kind == "mid":
            role_note = "中层优先保留可操作任务，压缩跨部门协调成本。"
        else:
            role_note = "基层优先保留最低可执行动作，降低一线负担。"

        return "；".join(top_reasons + [role_note])

    def _emit_distortion_event(self, simulator, agent: Agent, tier: str, input_policy: str, agent_draft: str, final_action: str, final_message: str) -> None:
        pressure = self._conflict_pressure(agent, tier)
        tendency = self._block_tendency(agent, tier)
        original_norm = " ".join(str(input_policy or "").split())
        final_norm = " ".join(str(final_message or "").split())
        changed = final_action == "yield" or original_norm != final_norm
        simulator.emit_event(
            "cascade_distortion",
            {
                "agent": agent.name,
                "tier": tier,
                "mode": self._cascade_mode(),
                "blocked": final_action == "yield",
                "changed": changed,
                "original_message": input_policy,
                "agent_draft_message": agent_draft,
                "final_message": final_message,
                "reason": self._distortion_reason(agent, tier),
                "pressure": round(pressure, 4),
                "block_tendency": round(tendency, 4),
                "distortion_strength": round(self._distortion_strength(), 4),
                "conflict_sensitivity": round(self._conflict_sensitivity(), 4),
                "block_probability": round(self._block_probability(), 4),
            },
        )

    def _split_policy_line(self, line: str) -> tuple[str, str]:
        parts = re.split(r"[:：]", line, maxsplit=1)
        if len(parts) == 2:
            return parts[0].strip(), parts[1].strip()
        return "", line.strip()

    def _line_kind(self, line: str) -> str:
        normalized = re.sub(r'^\s*(?:\d+[\.、]\s*)?', '', str(line or '').strip())
        if normalized == "原文：":
            return "meta"
        if ("通知" in normalized or "公告" in normalized) and (
            normalized.startswith("关于")
            or "关于" in normalized
            or normalized.startswith("「")
            or normalized.startswith("【")
        ):
            return "title"
        header, _ = self._split_policy_line(normalized)
        if header:
            for kind, markers in POLICY_LINE_MARKERS.items():
                if any(marker in header for marker in markers):
                    return kind
        for kind, markers in POLICY_LINE_MARKERS.items():
            if any(marker in normalized for marker in markers):
                return kind
        return "general"

    def _policy_lines_for_distortion(self, message: str) -> List[tuple[str, str]]:
        source = str(self.state.get("source_policy", "") or "").strip()
        if not source:
            source = self._sanitize_message(message)
        if not source:
            source = str(self.state.get("relayed_policy", "") or self.state.get("latest_policy", "") or "")
        lines = [line.rstrip() for line in source.splitlines() if line.strip()]
        result: List[tuple[str, str]] = []
        current_kind = "general"
        for raw_line in lines:
            stripped = raw_line.strip()
            kind = self._line_kind(stripped)
            if stripped.startswith("*") or stripped.startswith("•") or stripped.startswith("-"):
                kind = current_kind
            elif current_kind == "invariant" and stripped.startswith(("“", '"', "'", "‘")):
                kind = "invariant"
            elif kind == "general" and current_kind in {"report", "execution"} and stripped.startswith(("（", "(", "附", "其中", "包括")):
                kind = current_kind
            elif kind not in {"general", "meta", "title"}:
                current_kind = kind
            result.append((kind, stripped))
        return result

    def _clean_policy_body(self, text: str) -> str:
        return str(text or "").strip().rstrip("。；;，,:：")

    def _soften_body(self, body: str, strength: float) -> str:
        softened = str(body or "").strip()
        replacements = [
            ("必须", "优先"),
            ("立即", "尽快"),
            ("全部", "重点"),
            ("统一", "先行"),
            ("问责", "跟踪"),
            ("督办", "协调"),
        ]
        if strength >= 0.35:
            for old, new in replacements:
                softened = softened.replace(old, new)
        if strength >= 0.65:
            softened = re.sub(r"(\d+小时内|当天|本周内|周五18点前|立即)", "条件具备后再统一推进", softened)
        return softened

    def _rewrite_line_for_distortion(self, kind: str, tier: str, line: str, strength: float, pressure: float) -> str:
        role_kind = self._tier_role_kind(tier)
        header, body = self._split_policy_line(line)
        softened = self._clean_policy_body(self._soften_body(body, strength))
        clean_body = self._clean_policy_body(body)
        if kind == "title":
            return line
        if kind == "meta":
            return line
        if strength < 0.35:
            return line
        elif strength <= 0.55:
            if kind == "goal":
                return f"政策目标：{softened or clean_body}。"
            if kind == "scope":
                return f"适用范围仍按原文执行：{softened or clean_body}。"
            if kind == "standard":
                return f"调整标准原则上保持不变：{softened or clean_body}。"
            if kind == "support":
                return f"配套安排继续同步说明：{softened or clean_body}。"
            if kind == "execution":
                return f"执行时继续按原要求推进：{softened or clean_body}。"
            if kind == "report":
                return f"报告要求继续保留：{softened or clean_body}。"
            if kind == "resource":
                return f"资源支持继续保留原则安排：{softened or clean_body}。"
            if kind == "accountability":
                return f"责任链条继续明确：{softened or clean_body}。"
            if kind == "invariant":
                return line
            return line
        if kind == "goal":
            if role_kind == "top":
                return f"阶段目标：继续围绕{softened or clean_body}推进，但先突出最核心指标。"
            if role_kind == "mid":
                return f"当前先按阶段性目标处理：{softened or clean_body}，其余部分分批推进。"
            return f"一线仅保留最低目标：{softened or clean_body}。"
        if kind == "scope":
            if role_kind == "top":
                return f"适用范围暂按原口径掌握：{softened or clean_body}。"
            if role_kind == "mid":
                return f"当前执行范围先收敛为：{softened or clean_body}。"
            return f"一线当前仅按以下范围理解：{softened or clean_body}。"
        if kind == "standard":
            if role_kind == "top":
                return f"调整标准先保留关键口径：{softened or clean_body}。"
            if role_kind == "mid":
                return f"本层只下传最核心的调整标准：{softened or clean_body}。"
            return f"基层仅掌握与执行直接相关的标准：{softened or clean_body}。"
        if kind == "support":
            if role_kind == "top":
                return f"配套安排原则上保留：{softened or clean_body}。"
            if role_kind == "mid":
                return f"配套安排先保留必要部分：{softened or clean_body}。"
            return f"一线仅保留必要配套说明：{softened or clean_body}。"
        if kind == "execution":
            if role_kind == "top":
                return f"执行重点：各单位先围绕{softened or clean_body}落实，细项后续再补。"
            if role_kind == "mid":
                return f"现阶段执行安排调整为：优先处理{softened or clean_body}。"
            return f"基层先完成最小动作：{softened or clean_body}。"
        if kind == "report":
            if strength >= 0.75:
                return "报送要求调整为：先内部掌握情况，后续视条件统一汇总。"
            if role_kind == "low":
                return f"报送部分先简化为现场记录：{softened or clean_body}。"
            return f"报送安排改为部门内部先汇总：{softened or clean_body}。"
        if kind == "resource":
            if role_kind == "top":
                return f"资源保障部分暂保留原则性表述：{softened or clean_body}。"
            return "资源支持暂按现有条件消化，新增保障后续再协调。"
        if kind == "accountability":
            if role_kind == "top":
                return f"考核问责仍然保留，但先聚焦关键事项：{softened or clean_body}。"
            if pressure >= 0.6:
                return "考核要求暂不向下展开，先看本轮执行反馈。"
            return f"跟踪要求调整为阶段性检查：{softened or clean_body}。"
        if kind == "invariant":
            return line
        if kind == "title":
            return line
        if kind == "meta":
            return line
        if role_kind == "top":
            return f"本层转述：{softened or clean_body or header}。"
        if role_kind == "mid":
            return f"结合本层压力，改写为：{softened or clean_body or header}。"
        return f"一线暂按以下方式理解：{softened or clean_body or header}。"

    def _line_priority(self, kind: str, tier: str) -> int:
        role_kind = self._tier_role_kind(tier)
        if role_kind == "top":
            order = ["goal", "scope", "standard", "support", "resource", "report", "accountability", "execution", "invariant", "general"]
        elif role_kind == "mid":
            order = ["standard", "execution", "scope", "support", "report", "goal", "accountability", "resource", "invariant", "general"]
        else:
            order = ["execution", "support", "report", "standard", "scope", "goal", "general", "resource", "accountability", "invariant"]
        return order.index(kind) if kind in order else len(order)

    def _must_keep_line(self, kind: str, line: str, strength: float, tier: str) -> bool:
        if kind in {"title", "meta"}:
            return True
        if kind == "invariant":
            return True
        if strength <= 0.55:
            return kind in {"goal", "scope", "standard", "support", "report", "resource", "accountability"}
        if self._tier_role_kind(tier) == "top":
            return kind in {"goal", "standard", "resource", "report"}
        return kind in {"standard", "execution", "report"}

    def _conflict_pressure(self, agent: Agent, tier: str) -> float:
        role_kind = self._tier_role_kind(tier)
        tier_base = 0.18 if role_kind == "top" else 0.42 if role_kind == "mid" else 0.68
        agent_profile = self._agent_signal_profile(agent)
        policy_profile = self._policy_signal_profile()
        semantic_conflict = (
            policy_profile["burden"] * (0.35 + agent_profile["burden"] * 0.35)
            + policy_profile["resource_gap"] * (0.2 + agent_profile["resource"] * 0.3)
            + policy_profile["accountability"] * (0.15 + agent_profile["autonomy"] * 0.2)
            + policy_profile["report"] * (0.1 + agent_profile["burden"] * 0.15)
        )
        semantic_conflict -= agent_profile["control"] * policy_profile["accountability"] * 0.25
        semantic_conflict -= agent_profile["stability"] * policy_profile["goal"] * 0.1
        if role_kind == "top":
            semantic_conflict -= 0.08
        elif role_kind == "low":
            semantic_conflict += 0.08
        semantic_conflict += self._condition_value("resource_shortage") * 0.12
        semantic_conflict += self._condition_value("assessment_cycle") * 0.08
        semantic_conflict += self._condition_value("inspection_pressure") * 0.1
        semantic_conflict += self._condition_value("public_opinion_pressure") * 0.06
        semantic_conflict = self._clamp01(semantic_conflict)
        sensitivity = self._conflict_sensitivity()
        return self._clamp01(tier_base * (1 - sensitivity) + semantic_conflict * sensitivity)

    def _should_block(self, agent: Agent, tier: str) -> bool:
        return self._block_tendency(agent, tier) >= 0.5

    def _distort_message(self, agent: Agent, tier: str, message: str) -> str:
        normalized = self._sanitize_message(message)
        if not normalized:
            return normalized
        strength = self._distortion_strength()
        if strength <= 0:
            return normalized

        lines = self._policy_lines_for_distortion(normalized)
        if not lines:
            return normalized

        content_lines = [item for item in lines if item[0] not in {"title", "meta"}]
        if content_lines:
            lines = content_lines

        prefix = self._distortion_intro(tier, strength)

        pressure = self._conflict_pressure(agent, tier)
        keep_count = max(1, min(len(lines), self._distortion_anchor_limit(tier, strength)))
        ranked = sorted(lines, key=lambda item: self._line_priority(item[0], tier))
        required: List[tuple[str, str]] = []
        for item in ranked:
            if self._must_keep_line(item[0], item[1], strength, tier) and item not in required:
                required.append(item)
        selected: List[tuple[str, str]] = list(required)
        for item in ranked:
            if len(selected) >= keep_count:
                break
            if item not in selected:
                selected.append(item)
        if len(required) > keep_count:
            keep_count = len(required)
        selected = selected[:keep_count]
        rewritten = [
            self._rewrite_line_for_distortion(kind, tier, line, strength, pressure)
            for kind, line in selected
        ]
        if not rewritten:
            return normalized

        parts = [prefix, normalized, self._distortion_constraint_label(tier, strength)]
        parts.extend(rewritten)
        if pressure >= 0.75:
            parts.append("其余内容待条件成熟后再决定是否继续下传。")
        return "\n".join(part for part in parts if part)
