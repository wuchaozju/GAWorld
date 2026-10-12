from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import List

from fos.i18n import T
from fos.core.runtime_paths import get_runtime_debug_dir


DEFAULT_TIER_ORDER = ["top", "mid", "low"]
POLICY_MARKERS = ["原文", "不可改写条款", "报告要求", "执行要求", "目标："]
POLICY_LINE_MARKERS = {
    "goal": ["政策目标", "目标", "总体要求", "工作要求"],
    "scope": ["调整范围", "适用范围", "覆盖范围"],
    "standard": ["调整标准", "下调", "比例", "薪酬标准", "固定薪酬"],
    "support": ["配套要求", "稳岗安排", "心理支持", "申诉反馈渠道"],
    "execution": ["执行要求", "落实", "整改", "排查", "培训", "核验", "完成"],
    "report": ["报告要求", "报送", "汇总", "周报", "台账", "上报", "签到表", "填报"],
    "resource": ["资源", "预算", "经费", "人员", "保障", "技术支持", "专项"],
    "accountability": ["责任分工", "问责", "考核", "督办", "责任", "压实责任", "跟踪问效"],
    "invariant": ["不可改写条款", "严禁", "不得", "必须", "一律"],
}
AGENT_SIGNAL_MARKERS = {
    "burden": ["负担", "压力", "成本", "加班", "重复", "繁琐", "一线", "基层", "执行难"],
    "autonomy": ["灵活", "自主", "因地制宜", "协调", "平衡", "裁量", "缓行", "试点"],
    "control": ["问责", "纪律", "考核", "刚性", "统一部署", "压实责任", "督办", "从严"],
    "resource": ["预算", "人手", "资源", "经费", "设备", "支持", "保障", "条件"],
    "stability": ["稳定", "风险", "舆情", "安全", "秩序", "审慎", "稳妥"],
}
NOTICE_ANALYSIS_MARKERS = [
    "解读", "评估", "合理性", "优点", "缺点", "优缺点", "利弊", "优势", "不足",
    "问题", "建议", "看法", "分析", "研判", "评论", "谈谈", "怎么看", "是否可行",
]
NOTICE_EXECUTION_MARKERS = [
    "贯彻", "落实", "执行", "推进", "部署", "传达", "整改", "排查", "督办", "落实情况",
]
_scene_debug_file: Path | None = None


def get_follow_up_no_action_message(locale: str | None = None) -> str:
    return T("prompts.policy_cascade.shared.follow_up_no_action", locale=locale or "zh")


def get_scene_debug_file() -> Path:
    global _scene_debug_file
    if _scene_debug_file is None:
        scene_debug_dir = get_runtime_debug_dir("policy_cascade")
        _scene_debug_file = scene_debug_dir / f"policy_cascade_final_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    return _scene_debug_file


def _normalize_tier_token(value: str) -> str:
    normalized = value.strip().lower().replace("_", "-").replace(" ", "-")
    if normalized in {"top", "top-tier", "high", "high-tier"} or "高层" in value:
        return "top"
    if normalized in {"mid", "mid-tier", "middle", "middle-tier"} or "中层" in value:
        return "mid"
    if normalized in {"low", "low-tier", "base", "base-tier"} or "基层" in value:
        return "low"
    return ""


def _parse_tier_order(raw_value) -> List[str]:
    if type(raw_value) is list:
        values = [str(item).strip() for item in raw_value]
    else:
        values = re.split(r"[,，\n]+", str(raw_value or ""))
        values = [value.strip() for value in values]

    cleaned: List[str] = []
    seen = set()
    for value in values:
        if not value:
            continue
        key = value.lower()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(value)
    return cleaned or list(DEFAULT_TIER_ORDER)


def _has_meaningful_notice_content(text: str) -> bool:
    return bool(re.search(r"[A-Za-z0-9\u4e00-\u9fff]", str(text or "")))
