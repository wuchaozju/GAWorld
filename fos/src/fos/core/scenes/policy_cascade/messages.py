from __future__ import annotations

import re

from fos.core.agent import Agent
from fos.core.agent.parsing import strip_thinking_tokens

from .constants import NOTICE_ANALYSIS_MARKERS, NOTICE_EXECUTION_MARKERS, POLICY_MARKERS, get_scene_debug_file


class PolicyCascadeMessageMixin:
    def _is_policy_announcement(self, text: str) -> bool:
        return any(marker in text for marker in POLICY_MARKERS)

    def _should_enter_cascade(self, text: str, event_type: str) -> bool:
        cleaned = str(text or "").strip()
        if not cleaned:
            return False

        initial_text = self._clean_policy_text(str(getattr(self.initial_event, "content", "") or ""))
        if event_type == "broadcast" and cleaned == initial_text and not str(self.state.get("relayed_policy", "") or self.state.get("latest_policy", "") or "").strip():
            return False

        if self._cascade_mode() != "distortion_cascade":
            return self._is_policy_announcement(text)

        return True

    def _extract_min_chars(self, text: str) -> int:
        match = re.search(r"不少于\s*(\d+)\s*字|至少\s*(\d+)\s*字", text)
        if not match:
            return 0
        value = match.group(1) or match.group(2) or "0"
        return int(value)

    def _detect_notice_kind(self, text: str) -> str:
        if any(marker in text for marker in NOTICE_ANALYSIS_MARKERS):
            return "analysis"
        if any(marker in text for marker in NOTICE_EXECUTION_MARKERS):
            return "execution"
        return "execution"

    def _gov_meeting_terms(self, tier: str) -> list[str]:
        role_kind = self._tier_role_kind(tier)
        if role_kind == "top":
            return [
                "传达学习", "会议精神", "统筹推进", "统一部署", "压实责任", "狠抓落实",
                "督促检查", "跟踪问效", "问责机制", "组织领导", "决策部署", "牵头负责",
            ]
        if role_kind == "mid":
            return [
                "细化举措", "分解任务", "对标对表", "协同推进", "专班推进", "建立台账",
                "清单化管理", "节点推进", "定期调度", "周报机制", "协调联动", "督办落实",
            ]
        return [
            "现场核验", "逐项排查", "问题整改", "及时上报", "一线落实", "闭环管理",
            "销号管理", "复查复核", "反馈情况", "责任到人", "逐条落实", "应改尽改",
        ]

    def _analysis_structure_keywords(self, tier: str) -> list[str]:
        shared = ["优点", "缺点", "建议", "风险", "合理性"]
        return shared + self._gov_meeting_terms(tier)

    def _tier_keywords(self, tier: str) -> list[str]:
        role_kind = self._tier_role_kind(tier)
        if role_kind == "top":
            return ["统筹", "资源", "考核", "问责", "部署", "督办", "压实责任", "跟踪问效"] + self._gov_meeting_terms(tier)
        if role_kind == "mid":
            return ["拆解", "协调", "时间表", "周报", "台账", "分解任务", "协同推进", "定期调度"] + self._gov_meeting_terms(tier)
        return ["排查", "上报", "反馈", "核验", "整改", "闭环", "复查", "销号"] + self._gov_meeting_terms(tier)

    def _cross_tier_words(self, tier: str) -> list[str]:
        role_kind = self._tier_role_kind(tier)
        if role_kind == "top":
            return [
                "基层执行", "基层落实", "中层协调", "中层执行", "现场核验", "逐项排查", "复查复核", "销号管理",
                "任务拆解", "周报台账", "跨部门协调", "排查步骤", "问题整改", "上报反馈",
            ]
        if role_kind == "mid":
            return [
                "高层统筹", "高层问责", "基层执行", "基层落实", "组织领导", "决策部署", "现场核验", "逐项排查",
                "总体目标", "资源调配", "督促检查", "责任落实", "问题整改", "上报反馈", "闭环",
            ]
        return [
            "高层统筹", "高层部署", "中层协调", "中层执行", "组织领导", "决策部署", "周报机制", "专班推进",
            "总体目标", "资源调配", "督促检查", "跨层级协同治理", "任务拆解", "跨部门协调", "台账机制",
        ]

    def _policy_focus(self) -> list[str]:
        policy = str(self.state.get("source_policy", "") or self.state.get("relayed_policy", "") or self.state.get("latest_policy", "") or "")
        lines = [line.strip(" *") for line in policy.splitlines() if line.strip()]
        picks = []
        for line in lines:
            if "目标" in line or "报告要求" in line or "执行要求" in line or "责任分工" in line:
                picks.append(line)
        return picks[:3]

    def _policy_prompt_excerpt(self, text: str) -> str:
        cleaned = self._clean_policy_text(text)
        if not cleaned:
            return ""
        lines = [line.strip() for line in cleaned.splitlines() if line.strip()]
        picked: list[str] = []
        seen = set()
        for line in lines:
            normalized = line.strip(" *")
            kind = self._line_kind(normalized)
            summary = ""
            if kind == "goal":
                if "6 个月内" in normalized and "岗位稳定" in normalized:
                    summary = "目标：6个月内完成成本优化与岗位稳定"
                else:
                    _, body = self._split_policy_line(normalized)
                    summary = f"目标：{body[:24]}" if body else "目标：保持政策目标不变"
            elif kind == "scope":
                if "中层及以下" in normalized and ("暂不纳入" in normalized or "关键" in normalized):
                    summary = "范围：中层及以下，关键岗位原则上暂不纳入"
                else:
                    summary = "范围：保持原适用范围"
            elif kind == "standard":
                if "10%" in normalized and "阶段性下调" in normalized:
                    summary = "标准：10%阶段性下调"
                else:
                    summary = "标准：保持原调整标准"
            elif kind == "support":
                summary = "配套：同步说明稳岗安排、心理支持与申诉渠道"
            elif kind == "report":
                if "5 个工作日" in normalized or "5个工作日" in normalized:
                    summary = "报告：5个工作日内提交落实情况"
                else:
                    summary = "报告：保留落实情况报送要求"
            elif kind == "resource":
                summary = "资源：可申请沟通、人力和缓冲预算支持"
            elif kind == "accountability":
                if "不得跳级" in normalized:
                    summary = "责任：逐级传达，不得跳级通知"
                else:
                    summary = "责任：明确负责人对接与责任链条"
            elif kind == "invariant":
                summary = "硬约束：保留不可改写条款"
            elif kind == "title" and not picked:
                summary = normalized[:24]
            if summary and summary not in seen:
                picked.append(summary)
                seen.add(summary)
        if not picked:
            picked = ["按当前政策版本执行"]
        return "；".join(picked[:4])

    def _sanitize_message(self, message: str) -> str:
        sanitized = strip_thinking_tokens(str(message or "")).strip()
        sanitized = re.sub(r'(^|\n)\s*/(?:think|reasoning|analysis)\b.*?(?=\n|\Z)', '\\1', sanitized, flags=re.IGNORECASE | re.DOTALL)
        sanitized = re.sub(r'(?i)(?:^|(?<=\s))/(?:think|reasoning|analysis)\b[^\S\r\n]*$', '', sanitized, flags=re.MULTILINE)
        sanitized = re.sub(r'\s*/(?:think|reasoning|analysis)\b', '', sanitized, flags=re.IGNORECASE)
        sanitized = re.sub(r'<[^>]+>', '', sanitized)
        sanitized = re.sub(r'\n{3,}', '\n\n', sanitized)
        return sanitized.strip()

    def _cascade_tier_detail(self, tier: str) -> str:
        role_kind = self._tier_role_kind(tier)
        if role_kind == "top":
            return "补充：本层只补充高层统筹、资源批准和督办问责安排。"
        if role_kind == "mid":
            return "补充：本层只补充任务拆解、跨部门协调和周报台账安排。"
        return "补充：本层只补充逐项排查、现场核验、整改复查和上报反馈。"

    def _normalize_cascade_message(self, agent: Agent, tier: str, policy: str, message: str) -> str:
        normalized = self._sanitize_message(message)
        if not normalized:
            if self._cascade_mode() == "distortion_cascade":
                normalized = self._distort_message(agent, tier, policy)
            else:
                normalized = f"{policy}\n{self._cascade_suffix(tier)}"

        if not self._message_has_tier_drift(tier, normalized):
            return self._sanitize_message(normalized)

        detail = self._cascade_tier_detail(tier)
        if detail not in normalized:
            normalized = f"{normalized}\n{detail}".strip()

        if not self._message_has_tier_drift(tier, normalized):
            return self._sanitize_message(normalized)

        if self._cascade_mode() == "distortion_cascade":
            distorted = self._distort_message(agent, tier, policy)
            normalized = distorted or normalized
            if detail not in normalized:
                normalized = f"{normalized}\n{detail}".strip()
            return self._sanitize_message(normalized)

        return self._sanitize_message(f"{policy}\n{self._cascade_suffix(tier)}")

    def _agent_led_distortion(self, agent: Agent, tier: str, policy: str, draft: str) -> str:
        normalized = self._sanitize_message(draft)
        if not normalized:
            return self._distort_message(agent, tier, policy)

        policy_norm = " ".join(str(policy or "").split())
        draft_norm = " ".join(normalized.split())
        if draft_norm == policy_norm:
            return self._distort_message(agent, tier, policy)

        strength = self._distortion_strength()
        pressure = self._conflict_pressure(agent, tier)
        if self._message_has_tier_drift(tier, normalized):
            detail = self._cascade_tier_detail(tier)
            if detail not in normalized:
                normalized = f"{normalized}\n{detail}".strip()

        if strength >= 0.45 and pressure >= 0.5:
            issues = self._thread_issue_candidates(agent, tier)
            if issues:
                issue_line = "本层当前最担心：" + "、".join(issues) + "。"
                if issue_line not in normalized:
                    normalized = f"{normalized}\n{issue_line}".strip()

        if strength >= 0.65 and not any(marker in normalized for marker in ["暂缓", "分批", "优先", "内部掌握", "条件具备后"]):
            normalized = f"{normalized}\n后续其余部分视资源与反馈情况分批推进。".strip()

        return self._sanitize_message(normalized)

    def _clean_policy_text(self, text: str) -> str:
        cleaned = self._sanitize_message(text)
        lines = []
        for raw_line in cleaned.splitlines():
            line = raw_line.rstrip()
            line = re.sub(r'^\s*\*\s*\*\s*', '', line)
            line = re.sub(r'^\s*\*\s+(?=(?:标题|原文|传达要求|资源支持|责任分工|报告要求|执行要求|目标|不可改写条款))', '', line)
            line = re.sub(r'^\s*\*\s+(?=\d+\.)', '', line)
            line = re.sub(r'^\s*\*\s+(?=[“"])', '', line)
            line = re.sub(r'^\s{2,}\*\s+', '    * ', line)
            line = re.sub(r'\*\s*\*', '', line)
            lines.append(line)

        normalized = "\n".join(lines)
        normalized = re.sub(r'\n{3,}', '\n\n', normalized)
        normalized = re.sub(r'[ \t]+\n', '\n', normalized)
        return normalized.strip()

    def _distortion_anchor_limit(self, tier: str, strength: float) -> int:
        role_kind = self._tier_role_kind(tier)
        if strength <= 0.55:
            return 3 if role_kind == "top" else 4
        if strength < 0.75:
            return 3 if role_kind != "low" else 2
        return 2

    def _distortion_constraint_label(self, tier: str, strength: float) -> str:
        role_kind = self._tier_role_kind(tier)
        if strength <= 0.55:
            if role_kind == "top":
                return self._tr("prompts.policy_cascade.messages.constraint_top_soft")
            if role_kind == "mid":
                return self._tr("prompts.policy_cascade.messages.constraint_mid_soft")
            return self._tr("prompts.policy_cascade.messages.constraint_low_soft")
        if role_kind == "top":
            return self._tr("prompts.policy_cascade.messages.constraint_top_strong")
        if role_kind == "mid":
            return self._tr("prompts.policy_cascade.messages.constraint_mid_strong")
        return self._tr("prompts.policy_cascade.messages.constraint_low_strong")

    def _distortion_intro(self, tier: str, strength: float) -> str:
        role_kind = self._tier_role_kind(tier)
        if role_kind == "top":
            return self._tr("prompts.policy_cascade.messages.intro_top_soft" if strength <= 0.55 else "prompts.policy_cascade.messages.intro_top_strong")
        if role_kind == "mid":
            return self._tr("prompts.policy_cascade.messages.intro_mid_soft" if strength <= 0.55 else "prompts.policy_cascade.messages.intro_mid_strong")
        return self._tr("prompts.policy_cascade.messages.intro_low_soft" if strength <= 0.55 else "prompts.policy_cascade.messages.intro_low_strong")

    def _build_analysis_message(self, tier: str) -> str:
        notice = str(self.state.get("latest_notice", "") or "").strip()
        role_kind = self._tier_role_kind(tier)
        if role_kind == "top":
            return self._tr("prompts.policy_cascade.messages.analysis_top", notice=notice)
        if role_kind == "mid":
            return self._tr("prompts.policy_cascade.messages.analysis_mid", notice=notice)
        return self._tr("prompts.policy_cascade.messages.analysis_low", notice=notice)

    def _notice_expansion(self, tier: str) -> list[str]:
        notice = str(self.state.get("latest_notice", "") or "").strip()
        role_kind = self._tier_role_kind(tier)
        if self.state.get("notice_kind") == "analysis":
            if role_kind == "top":
                return [
                    self._tr("prompts.policy_cascade.messages.expansion_analysis_top_1", notice=notice),
                    self._tr("prompts.policy_cascade.messages.expansion_analysis_top_2"),
                    self._tr("prompts.policy_cascade.messages.expansion_analysis_top_3"),
                ]
            if role_kind == "mid":
                return [
                    self._tr("prompts.policy_cascade.messages.expansion_analysis_mid_1", notice=notice),
                    self._tr("prompts.policy_cascade.messages.expansion_analysis_mid_2"),
                    self._tr("prompts.policy_cascade.messages.expansion_analysis_mid_3"),
                ]
            return [
                self._tr("prompts.policy_cascade.messages.expansion_analysis_low_1", notice=notice),
                self._tr("prompts.policy_cascade.messages.expansion_analysis_low_2"),
                self._tr("prompts.policy_cascade.messages.expansion_analysis_low_3"),
            ]
        if role_kind == "top":
            return [
                self._tr("prompts.policy_cascade.messages.expansion_exec_top_1", notice=notice),
                self._tr("prompts.policy_cascade.messages.expansion_exec_top_2"),
                self._tr("prompts.policy_cascade.messages.expansion_exec_top_3"),
            ]
        if role_kind == "mid":
            return [
                self._tr("prompts.policy_cascade.messages.expansion_exec_mid_1", notice=notice),
                self._tr("prompts.policy_cascade.messages.expansion_exec_mid_2"),
                self._tr("prompts.policy_cascade.messages.expansion_exec_mid_3"),
            ]
        return [
            self._tr("prompts.policy_cascade.messages.expansion_exec_low_1", notice=notice),
            self._tr("prompts.policy_cascade.messages.expansion_exec_low_2"),
            self._tr("prompts.policy_cascade.messages.expansion_exec_low_3"),
        ]

    def _enforce_min_chars(self, tier: str, message: str) -> str:
        normalized = str(message or "").strip()
        min_chars = self._extract_min_chars(str(self.state.get("latest_notice", "") or ""))
        if not min_chars:
            return normalized
        expansions = self._notice_expansion(tier)
        idx = 0
        while len(normalized) < min_chars:
            normalized = f"{normalized}\n{expansions[idx % len(expansions)]}".strip()
            idx += 1
        return normalized

    def _message_has_tier_drift(self, tier: str, message: str) -> bool:
        if any(word in message for word in self._cross_tier_words(tier)):
            return True
        return not any(word in message for word in self._tier_keywords(tier))

    def _message_matches_notice_kind(self, tier: str, message: str) -> bool:
        if self.state.get("notice_kind") != "analysis":
            return True
        return all(keyword in message for keyword in ["优点", "缺点", "建议"]) and any(
            keyword in message for keyword in self._analysis_structure_keywords(tier)
        )

    def _build_notice_message(self, tier: str) -> str:
        if self.state.get("notice_kind") == "analysis":
            return self._build_analysis_message(tier)
        notice = str(self.state.get("latest_notice", "") or "").strip()
        focus = self._policy_focus()
        role_kind = self._tier_role_kind(tier)
        if role_kind == "top":
            message = (
                f"作为高层，我对“{notice}”的执行方案如下：第一，我将把政策目标纳入本阶段总任务，"
                "以月度例会统一督办，并明确问责口径；第二，我将优先审批数据合规专项预算和人力补充，"
                "确保重点单位具备整改资源；第三，我会建立按月考核机制，要求各单位围绕关键指标提交结果说明。"
            )
        elif role_kind == "mid":
            message = (
                f"作为中层，我对“{notice}”的执行方案如下：第一，我将在48小时内把任务拆解到具体部门和责任人，"
                "形成分工表与时间表；第二，我将组织跨部门协调会，统一口径、收集资源缺口并建立周报台账；"
                "第三，我会对上汇总进度、对下跟踪节点，确保每项任务都有明确交付物和截止时间。"
            )
        else:
            message = (
                f"作为基层执行人员，我对“{notice}”的执行方案如下：第一，我将按清单逐项排查当前业务与流程，"
                "记录问题点、责任人和完成时限；第二，我会把现场核验结果当天汇总，并对异常情况在24小时内上报；"
                "第三，我将持续跟踪整改反馈，确保形成核验、上报、复查的闭环。"
            )
        if focus:
            message += "重点依据包括：" + "；".join(focus) + "。"
        return message

    def _normalize_notice_message(self, tier: str, message: str) -> str:
        normalized = self._sanitize_message(message)
        min_chars = self._extract_min_chars(str(self.state.get("latest_notice", "") or ""))
        if not normalized:
            normalized = self._build_notice_message(tier)

        if self._message_has_tier_drift(tier, normalized):
            normalized = self._build_notice_message(tier)

        if not self._message_matches_notice_kind(tier, normalized):
            normalized = self._build_notice_message(tier)

        if self.state.get("notice_kind") == "analysis" and min_chars and len(normalized) < min_chars:
            normalized = self._build_notice_message(tier)

        normalized = self._enforce_min_chars(tier, normalized)

        if self._message_has_tier_drift(tier, normalized):
            normalized = self._enforce_min_chars(tier, self._build_notice_message(tier))

        if not self._message_matches_notice_kind(tier, normalized):
            normalized = self._enforce_min_chars(tier, self._build_notice_message(tier))

        return normalized

    def _write_final_debug(self, agent: Agent, mode: str, original_payload: dict, final_payload: dict) -> None:
        try:
            with open(get_scene_debug_file(), "a", encoding="utf-8") as f:
                tier = self._tier_map.get(agent.name) or self._extract_tier(agent)
                f.write(f"\n{'=' * 80}\n")
                f.write(f"[FINAL ACTION] {agent.name}\n")
                f.write(f"tier={tier}\n")
                f.write(f"mode={mode} notice_kind={self.state.get('notice_kind', '')}\n")
                f.write(f"source_policy={self.state.get('source_policy', '')}\n")
                f.write(f"relayed_policy={self.state.get('relayed_policy', '')}\n")
                if mode == "cascade":
                    f.write(f"formal_connections={self._network_connections_for(agent.name)}\n")
                    f.write(f"downstream_targets={self._downstream_targets(agent)}\n")
                f.write("--- ORIGINAL PAYLOAD ---\n")
                f.write(f"{original_payload}\n")
                f.write("--- FINAL PAYLOAD ---\n")
                f.write(f"{final_payload}\n")
                f.write("--- FINAL MESSAGE ---\n")
                f.write(f"{final_payload.get('message', '')}\n")
                f.write("--- END FINAL ACTION ---\n")
        except Exception:
            return None

    def _cascade_suffix(self, tier: str) -> str:
        role_kind = self._tier_role_kind(tier)
        if role_kind == "top":
            return "态度：完全支持并按原文执行。\n补充：由我批准专项预算并建立月度问责机制。"
        if role_kind == "mid":
            return "态度：完全支持并按原文执行。\n补充：我将在48小时内拆解任务到各部门并建立周报台账。"
        return "态度：完全支持并按原文执行。\n补充：我将按排查清单逐项核验，并在发现异常后24小时内上报。"
