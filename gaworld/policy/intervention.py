import csv
import os
import re


INTERVENTION_METRICS = [
    "stance_score",
    "toxicity_score",
    "misinformation_risk",
    "cross_viewpoint_exposure",
    "intervention_reward",
]


DEFAULT_CONFIG = {
    "enabled": True,
    "output_dir": "output/intervention",
    "recommendation": {
        "max_items": 5,
        "source_weights": {
            "relational": 1.0,
            "personalized": 0.85,
            "headline": 0.75,
        },
    },
    "exposure_control": {
        "enabled": True,
        "toxicity_threshold": 0.45,
        "misinformation_threshold": 0.35,
        "suppression_factor": 0.25,
    },
    "stance": {
        "alpha": 0.8,
        "positive_keywords": [
            "支持",
            "赞成",
            "改善",
            "安心",
            "信任",
            "机会",
            "合作",
            "透明",
            "保护",
        ],
        "negative_keywords": [
            "反对",
            "担心",
            "不满",
            "风险",
            "冲突",
            "失望",
            "质疑",
            "压力",
            "限制",
        ],
    },
    "toxicity_keywords": [
        "辱骂",
        "攻击",
        "仇恨",
        "歧视",
        "极端",
        "滚",
        "骗子",
        "垃圾",
    ],
    "misinformation_keywords": [
        "谣言",
        "假消息",
        "未经证实",
        "阴谋",
        "伪造",
        "骗局",
        "造假",
        "不实",
    ],
    "objectives": {
        "cross_viewpoint_weight": 0.55,
        "engagement_weight": 0.20,
        "toxicity_penalty_weight": 0.15,
        "misinformation_penalty_weight": 0.10,
    },
}


def _deep_merge(base, override):
    merged = dict(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def normalize_config(config=None):
    return _deep_merge(DEFAULT_CONFIG, config if isinstance(config, dict) else {})


def clamp(value, low=0.0, high=1.0):
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = 0.0
    return max(low, min(high, number))


def _keyword_score(text, keywords):
    blob = str(text or "").lower()
    if not blob:
        return 0.0
    hits = 0
    for keyword in keywords or []:
        key = str(keyword or "").strip().lower()
        if key and key in blob:
            hits += 1
    if hits <= 0:
        return 0.0
    denominator = max(1.0, min(3.0, float(len(keywords or []) or 1)))
    return clamp(hits / denominator)


def toxicity_score(text, config=None):
    cfg = normalize_config(config)
    return _keyword_score(text, cfg.get("toxicity_keywords", []))


def misinformation_risk(text, config=None):
    cfg = normalize_config(config)
    return _keyword_score(text, cfg.get("misinformation_keywords", []))


def stance_from_text(text, config=None):
    cfg = normalize_config(config)
    stance_cfg = cfg.get("stance", {})
    positive = _keyword_score(text, stance_cfg.get("positive_keywords", []))
    negative = _keyword_score(text, stance_cfg.get("negative_keywords", []))
    return max(-1.0, min(1.0, positive - negative))


def initialize_agent_intervention_state(agent, config=None):
    state = agent.setdefault("state", {})
    for metric in INTERVENTION_METRICS:
        state.setdefault(metric, 0.0)
    agent.setdefault("_intervention_last_feed", {})
    return state


def _agent_profile_text(agent):
    return " ".join(
        str(agent.get(key, ""))
        for key in ("name", "job", "personality", "daily_life", "values", "work_style")
    )


def _make_candidate(source, text, weight, sender_id=None, metadata=None, config=None):
    clean_text = re.sub(r"\s+", " ", str(text or "")).strip()
    if not clean_text:
        return None
    tox = toxicity_score(clean_text, config)
    mis = misinformation_risk(clean_text, config)
    exposure = normalize_config(config).get("exposure_control", {})
    adjusted = float(weight)
    if exposure.get("enabled", True):
        threshold_t = float(exposure.get("toxicity_threshold", 0.45))
        threshold_m = float(exposure.get("misinformation_threshold", 0.35))
        factor = clamp(exposure.get("suppression_factor", 0.25), 0.0, 1.0)
        if tox >= threshold_t or mis >= threshold_m:
            adjusted *= factor
    return {
        "source": source,
        "text": clean_text,
        "sender_id": sender_id,
        "base_weight": float(weight),
        "score": adjusted,
        "toxicity_score": tox,
        "misinformation_risk": mis,
        "stance_score": stance_from_text(clean_text, config),
        "metadata": metadata or {},
    }


def _headline_candidates(env_events, policy_event, news_items, weights, config):
    candidates = []
    for event in env_events or []:
        if not isinstance(event, dict):
            continue
        text = event.get("description") or event.get("name") or event.get("topic")
        item = _make_candidate(
            "headline",
            text,
            weights.get("headline", 0.75),
            metadata={"kind": event.get("type", "event")},
            config=config,
        )
        if item:
            candidates.append(item)
    if policy_event:
        policy_text = policy_event.get("description") if isinstance(policy_event, dict) else str(policy_event)
        item = _make_candidate(
            "headline",
            policy_text,
            weights.get("headline", 0.75) + 0.1,
            metadata={"kind": "policy"},
            config=config,
        )
        if item:
            candidates.append(item)
    for news in news_items or []:
        if isinstance(news, dict):
            text = news.get("title") or news.get("summary") or news.get("content")
        else:
            text = str(news)
        item = _make_candidate("headline", text, weights.get("headline", 0.75), metadata={"kind": "news"}, config=config)
        if item:
            candidates.append(item)
    return candidates


def _relational_candidates(agent, agents_by_id, weights, config):
    candidates = []
    neighbor_ids = list(agent.get("social_neighbors", []) or [])
    recent_ids = list(agent.get("_recent_social_partners", []) or [])
    for neighbor_id in recent_ids + [n for n in neighbor_ids if n not in recent_ids]:
        neighbor = agents_by_id.get(neighbor_id, {}) if isinstance(agents_by_id, dict) else {}
        if not neighbor:
            continue
        parts = [
            neighbor.get("last_activity", ""),
            neighbor.get("last_action", ""),
            neighbor.get("last_reflection", ""),
        ]
        text = "；".join(str(p).strip() for p in parts if str(p).strip())
        if not text:
            text = f"{neighbor.get('name', neighbor_id)} 最近的状态值得留意"
        rel_weight = weights.get("relational", 1.0)
        relationships = agent.get("relationships", {})
        if isinstance(relationships, dict):
            rel = relationships.get(str(neighbor_id), {})
            if isinstance(rel, dict):
                rel_weight *= 0.75 + clamp(rel.get("closeness", 0.5)) * 0.5
        item = _make_candidate("relational", text, rel_weight, sender_id=neighbor_id, config=config)
        if item:
            candidates.append(item)
    return candidates


def _personalized_candidates(agent, env_events, policy_event, weights, config):
    profile = _agent_profile_text(agent)
    profile_stance = stance_from_text(profile, config)
    candidates = []
    source_texts = []
    for event in env_events or []:
        if isinstance(event, dict):
            source_texts.append(event.get("description") or event.get("name") or "")
    if policy_event:
        source_texts.append(policy_event.get("description") if isinstance(policy_event, dict) else str(policy_event))
    if not source_texts:
        source_texts.append(profile)
    for text in source_texts:
        if not str(text).strip():
            continue
        item = _make_candidate(
            "personalized",
            f"与你的关注点相关：{text}",
            weights.get("personalized", 0.85) + abs(profile_stance) * 0.1,
            metadata={"profile_stance": profile_stance},
            config=config,
        )
        if item:
            candidates.append(item)
    return candidates


def build_intervention_feed(
    agent,
    agents_by_id=None,
    day=None,
    time_str="",
    env_events=None,
    policy_event=None,
    news_items=None,
    config=None,
):
    cfg = normalize_config(config)
    initialize_agent_intervention_state(agent, cfg)
    rec = cfg.get("recommendation", {})
    weights = rec.get("source_weights", {})
    max_items = max(1, int(rec.get("max_items", 5)))
    candidates = []
    candidates.extend(_relational_candidates(agent, agents_by_id or {}, weights, cfg))
    candidates.extend(_personalized_candidates(agent, env_events, policy_event, weights, cfg))
    candidates.extend(_headline_candidates(env_events, policy_event, news_items, weights, cfg))
    candidates.sort(key=lambda item: item.get("score", 0.0), reverse=True)
    selected = candidates[:max_items]
    by_source = {}
    for item in selected:
        by_source[item["source"]] = by_source.get(item["source"], 0) + 1
    context_text = format_feed_context(selected)
    feed = {
        "day": day,
        "time": time_str,
        "items": selected,
        "source_counts": by_source,
        "context_text": context_text,
    }
    agent["_intervention_last_feed"] = feed
    return feed


def format_feed_context(items):
    if not items:
        return ""
    fragments = []
    labels = {
        "relational": "关系动态",
        "personalized": "个性化推荐",
        "headline": "公共议题",
    }
    for item in items:
        label = labels.get(item.get("source"), item.get("source", "推荐"))
        text = str(item.get("text", "")).strip()
        if len(text) > 90:
            text = text[:87].rstrip() + "..."
        fragments.append(f"{label}: {text}")
    return "；".join(fragments)


def _engagement_score(action, reflection):
    text = f"{action} {reflection}"
    if any(k in text for k in ["回复", "联系", "沟通", "讨论", "分享", "转发", "评论", "表达", "参与"]):
        return 1.0
    if any(k in text for k in ["查看", "了解", "留意", "阅读", "确认"]):
        return 0.65
    if any(k in text for k in ["忽略", "不理", "跳过"]):
        return 0.15
    return 0.35


def _cross_viewpoint_exposure(agent, feed, agents_by_id=None):
    items = (feed or {}).get("items", []) if isinstance(feed, dict) else []
    if not items:
        return 0.0
    own_stance = float(agent.get("state", {}).get("stance_score", 0.0))
    diffs = []
    for item in items:
        sender_id = item.get("sender_id")
        sender_stance = None
        if sender_id is not None and isinstance(agents_by_id, dict):
            sender = agents_by_id.get(sender_id, {})
            sender_stance = sender.get("state", {}).get("stance_score") if isinstance(sender, dict) else None
        if sender_stance is None:
            sender_stance = item.get("stance_score", 0.0)
        diffs.append(abs(own_stance - float(sender_stance)) / 2.0)
    return clamp(sum(diffs) / len(diffs))


def update_agent_intervention_metrics(agent, feed=None, action="", outcome="", reflection="", agents_by_id=None, config=None):
    cfg = normalize_config(config)
    state = initialize_agent_intervention_state(agent, cfg)
    feed = feed if isinstance(feed, dict) else agent.get("_intervention_last_feed", {})
    item_text = " ".join(str(item.get("text", "")) for item in feed.get("items", []) if isinstance(item, dict))
    combined = " ".join([item_text, str(action or ""), str(outcome or ""), str(reflection or "")]).strip()
    raw_stance = stance_from_text(combined, cfg)
    alpha = clamp(cfg.get("stance", {}).get("alpha", 0.8), 0.0, 1.0)
    prev_stance = float(state.get("stance_score", 0.0))
    stance = alpha * prev_stance + (1.0 - alpha) * raw_stance
    tox = toxicity_score(combined, cfg)
    mis = misinformation_risk(combined, cfg)
    cross = _cross_viewpoint_exposure(agent, feed, agents_by_id=agents_by_id)
    engagement = _engagement_score(action, reflection)
    objective = cfg.get("objectives", {})
    reward = (
        float(objective.get("cross_viewpoint_weight", 0.55)) * cross
        + float(objective.get("engagement_weight", 0.20)) * engagement
        + float(objective.get("toxicity_penalty_weight", 0.15)) * (1.0 - tox)
        + float(objective.get("misinformation_penalty_weight", 0.10)) * (1.0 - mis)
    )
    metrics = {
        "stance_score": max(-1.0, min(1.0, stance)),
        "toxicity_score": clamp(tox),
        "misinformation_risk": clamp(mis),
        "cross_viewpoint_exposure": clamp(cross),
        "intervention_reward": clamp(reward),
    }
    state.update(metrics)
    return metrics


def append_intervention_metrics(output_dir, row):
    os.makedirs(output_dir, exist_ok=True)
    path = os.path.join(output_dir, "intervention_metrics.csv")
    fieldnames = [
        "day",
        "time",
        "agent_id",
        "feed_items",
        "relational_items",
        "personalized_items",
        "headline_items",
    ] + INTERVENTION_METRICS
    write_header = not os.path.exists(path)
    clean = {key: row.get(key, "") for key in fieldnames}
    with open(path, "a", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if write_header:
            writer.writeheader()
        writer.writerow(clean)
    return path
