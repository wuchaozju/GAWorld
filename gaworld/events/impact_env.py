"""环境事件的客观影响规则表。

环境事件此前是纯描述的：暴雨、涨价、场所停业出现在提示词里，却从不真正改写
任何状态。这张表把"描述"翻译成"后果"。

匹配方式是关键词 + 标签 + 严重度门槛，与仓库里既有的
``_suggest_activity_for_event`` 同一套路——中文关键词匹配粗糙，但透明、可测、
不需要模型。

**金额单位**：``params["amount"]`` 是严重度 1.0 时的标准量。实际扣账时再乘以
事件的客观严重度与主体预估系数，因此一场 0.5 严重度的小雨只扣半份车费。
"""

from __future__ import annotations

from typing import Any

from gaworld.events.impact import Impact, normalize_impacts

#: 规则表。每条规则：
#: ``key`` 规则标识；``keywords`` 命中任意一个即匹配（对名称/描述/主题）；
#: ``tags_any`` 事件须带其中任意一个 ``impact_tags``（为空则不要求）；
#: ``min_severity`` 低于此严重度不触发（避免每个 tick 的小波动都扣钱）；
#: ``impacts`` 命中后产生的客观影响池。
ENV_IMPACT_RULES: tuple[dict[str, Any], ...] = (
    {
        "key": "storm",
        "keywords": [
            "暴雨",
            "大雨",
            "台风",
            "雷阵雨",
            "雷暴",
            "冰雹",
            "暴雪",
            "大雪",
            "积雪",
            "大风",
            "风暴",
            "降水",
            "雨",
            "雪",
        ],
        "tags_any": [],
        "min_severity": 0.45,
        "impacts": [
            {
                "domain": "environment",
                "kind": "condition",
                "params": {"key": "traffic_slow", "label": "天气恶劣，路面湿滑，出行整体变慢"},
                "note": "出行环境变差",
            },
            {
                "domain": "schedule",
                "kind": "activity_replace",
                "params": {
                    "targets": ["通勤", "外出", "散步", "运动", "购物", "买菜", "拜访", "会面"],
                    "replacement": "调整出行",
                    "window_minutes": 240,
                },
                "note": "通勤改道或推迟，户外安排往后挪",
            },
            {
                "domain": "economy",
                "kind": "expense",
                "params": {"category": "transport", "amount": 30.0},
                "note": "打车或额外交通支出",
            },
        ],
    },
    {
        "key": "heat",
        "keywords": ["高温", "酷暑", "热浪", "暴晒", "桑拿"],
        "tags_any": [],
        "min_severity": 0.5,
        "impacts": [
            {
                "domain": "environment",
                "kind": "condition",
                "params": {"key": "heat", "label": "高温天气，白天需要避开户外"},
                "note": "高温环境",
            },
            {
                "domain": "schedule",
                "kind": "activity_replace",
                "params": {
                    "targets": ["运动", "跑步", "散步", "户外", "买菜", "通勤"],
                    "replacement": "室内活动",
                    "window_minutes": 360,
                },
                "note": "户外活动改到室内或傍晚",
            },
        ],
    },
    {
        "key": "cold",
        "keywords": ["寒潮", "低温", "冰冻", "严寒", "霜冻"],
        "tags_any": [],
        "min_severity": 0.5,
        "impacts": [
            {
                "domain": "environment",
                "kind": "condition",
                "params": {"key": "cold", "label": "低温天气，室外待不住"},
                "note": "低温环境",
            },
            {
                "domain": "schedule",
                "kind": "activity_replace",
                "params": {
                    "targets": ["通勤", "外出", "散步", "运动", "买菜"],
                    "replacement": "调整出行",
                    "window_minutes": 240,
                },
                "note": "出行时间与方式调整",
            },
            {
                "domain": "economy",
                "kind": "expense",
                "params": {"category": "transport", "amount": 20.0},
                "note": "保暖与额外交通支出",
            },
        ],
    },
    {
        "key": "price",
        "keywords": ["涨价", "物价", "价格", "通胀", "成本上涨", "上涨", "紧缺"],
        "tags_any": [],
        "min_severity": 0.45,
        "impacts": [
            {
                "domain": "economy",
                "kind": "expense",
                "params": {"category": "food", "amount": 120.0},
                "note": "日常食品与生活成本上升",
            },
            {
                "domain": "economy",
                "kind": "income_loss",
                "params": {"fraction": 0.03, "days": 7},
                "note": "实际收入被物价吃掉一部分",
            },
        ],
    },
    {
        "key": "closure",
        "keywords": ["停业", "关闭", "停运", "检修", "封锁", "施工", "搬迁", "拆除"],
        "tags_any": [],
        "min_severity": 0.45,
        "impacts": [
            {
                "domain": "environment",
                "kind": "condition",
                "params": {"key": "closure", "label": "周边部分场所临时关闭或搬迁"},
                "note": "可去处减少",
            },
            {
                "domain": "schedule",
                "kind": "activity_replace",
                "params": {
                    "targets": ["购物", "买菜", "办事", "就医", "锻炼", "理发"],
                    "replacement": "另找去处",
                    "window_minutes": 240,
                },
                "note": "原本要去的地方去不了",
            },
        ],
    },
    {
        "key": "air",
        "keywords": ["空气质量", "雾霾", "污染", "pm2.5", "沙尘"],
        "tags_any": [],
        "min_severity": 0.5,
        "impacts": [
            {
                "domain": "environment",
                "kind": "condition",
                "params": {"key": "air", "label": "空气质量差，户外活动受限"},
                "note": "空气环境变差",
            },
            {
                "domain": "schedule",
                "kind": "activity_replace",
                "params": {
                    "targets": ["运动", "跑步", "散步", "户外"],
                    "replacement": "室内活动",
                    "window_minutes": 300,
                },
                "note": "户外锻炼改到室内",
            },
        ],
    },
    {
        "key": "congestion",
        "keywords": ["拥堵", "堵车", "交通缓慢", "路况", "车流"],
        "tags_any": [],
        "min_severity": 0.45,
        "impacts": [
            {
                "domain": "environment",
                "kind": "condition",
                "params": {"key": "traffic_slow", "label": "路况拥堵，通勤时间明显变长"},
                "note": "交通变差",
            },
            {
                "domain": "schedule",
                "kind": "activity_replace",
                "params": {
                    "targets": ["通勤", "前往", "会面", "拜访"],
                    "replacement": "调整出行",
                    "window_minutes": 180,
                },
                "note": "通勤改道或提前出门",
            },
            {
                "domain": "economy",
                "kind": "expense",
                "params": {"category": "transport", "amount": 15.0},
                "note": "改乘更贵的交通方式",
            },
        ],
    },
    {
        "key": "market_shock",
        "keywords": ["市场波动", "大宗商品", "消费情绪", "股市", "暴跌", "涨停", "经济下行"],
        "tags_any": ["econ_security", "risk_preference"],
        "min_severity": 0.5,
        "impacts": [
            {
                "domain": "economy",
                "kind": "income_loss",
                "params": {"fraction": 0.05, "days": 5},
                "note": "市场波动带来的短期收入损失",
            },
        ],
    },
    {
        "key": "policy_notice",
        "keywords": ["监管提示", "治理通告", "新规", "政策", "通知", "公示"],
        "tags_any": [],
        "min_severity": 0.5,
        "impacts": [
            {
                "domain": "schedule",
                "kind": "activity_add",
                "params": {"activity": "查看通知", "minutes": 30},
                "note": "需要专门去了解新规定",
            },
        ],
    },
)


def _event_text(event: dict[str, Any]) -> str:
    parts = [
        str(event.get("name", "") or ""),
        str(event.get("description", "") or ""),
        str(event.get("topic", "") or ""),
        str(event.get("type", "") or ""),
    ]
    return " ".join(parts).lower()


def match_env_impacts(event: Any) -> list[Impact]:
    """The objective impact pool of an environment event.

    Empty when nothing matches — most environment events (a passing cloud, a
    market wobble below the floor) are not supposed to change anything.
    """
    if not isinstance(event, dict):
        return []
    try:
        severity = float(event.get("severity", 0.0) or 0.0)
    except (TypeError, ValueError):
        severity = 0.0
    text = _event_text(event)
    tags = {str(t).strip().lower() for t in (event.get("impact_tags") or []) if str(t).strip()}

    for rule in ENV_IMPACT_RULES:
        min_severity = float(rule.get("min_severity", 0.0))
        if severity < min_severity:
            continue
        keywords = [str(k).lower() for k in rule.get("keywords", [])]
        if not any(k in text for k in keywords):
            continue
        tags_any = [str(t).lower() for t in rule.get("tags_any", [])]
        if tags_any and not any(t in tags for t in tags_any):
            continue
        impacts = normalize_impacts(rule.get("impacts"))
        if impacts:
            return impacts
    return []


__all__ = ["ENV_IMPACT_RULES", "match_env_impacts"]
