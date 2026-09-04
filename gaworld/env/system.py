import json
import random
import re

import requests

from gaworld.logging_setup import get_logger

_LOG = get_logger("gaworld.environment")


def _clip(value, lo=0.0, hi=1.0):
    return max(lo, min(hi, float(value)))


def _safe_float(value, default=0.0):
    """Convert a value to float safely, handling lists, None, and type errors."""
    if value is None:
        return default
    if isinstance(value, (list, tuple)):
        return _safe_float(value[0], default) if value else default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


class EnvironmentSystem:
    def __init__(self, config, llm_fn=None):
        config = config or {}
        legacy_cfg = config.get("environment", config)
        external_cfg = config.get("external_environment", {})
        has_external = "external_environment" in config or any(
            k in config for k in ("natural", "economic", "political", "technology", "intraday")
        )

        self.legacy_enabled = bool(legacy_cfg.get("enabled", True))
        self.event_chance = _safe_float(legacy_cfg.get("event_chance", 0.5))
        self.max_events_per_tick = int(legacy_cfg.get("max_events_per_tick", 1))
        self.natural_events = list(legacy_cfg.get("natural_events", []))
        self.social_events = list(legacy_cfg.get("social_events", []))

        self.external_cfg = external_cfg if isinstance(external_cfg, dict) else {}
        anomaly_cfg = config.get("anomaly", self.external_cfg.get("anomaly", {}))
        self.anomaly_cfg = anomaly_cfg if isinstance(anomaly_cfg, dict) else {}
        self.anomaly_enabled = bool(self.anomaly_cfg.get("enabled", False))
        self.anomaly_severity_threshold = _safe_float(self.anomaly_cfg.get("severity_threshold", 0.65), 0.65)
        self.anomaly_intraday_threshold = _safe_float(self.anomaly_cfg.get("intraday_threshold", 0.45), 0.45)
        self.external_enabled = bool(self.external_cfg.get("enabled", has_external))
        self.external_max_events_per_tick = int(self.external_cfg.get("max_events_per_tick", 3))
        generator_cfg = self.external_cfg.get("generator", {})
        if not isinstance(generator_cfg, dict):
            generator_cfg = {}
        self.generator_cfg = generator_cfg
        self.generator_mode = str(generator_cfg.get("mode", "llm")).strip().lower()
        self.generator_description = str(generator_cfg.get("description", "")).strip()
        self.generator_history_days = max(0, int(generator_cfg.get("history_days", 3)))
        seed = self.external_cfg.get("seed")
        self.rng = random.Random(seed) if seed is not None else random.Random()

        self.llm_fn = llm_fn
        self.enabled = self.legacy_enabled or self.external_enabled
        self._current_events = []
        self._day_events = []
        self._day_context = ""
        self._intraday_rules = {}
        self._recent_day_summaries = []
        self._weather_state = "clear"
        self._market_index = _safe_float(self.external_cfg.get("economic", {}).get("market_index_base", 100.0))

    def _extract_json_object(self, text):
        if not text:
            return {}
        block = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", str(text), re.S)
        if block:
            blob = block.group(1)
        else:
            inline = re.search(r"\{.*\}", str(text), re.S)
            blob = inline.group(0) if inline else ""
        if not blob:
            return {}
        try:
            data = json.loads(blob)
        except json.JSONDecodeError:
            return {}
        return data if isinstance(data, dict) else {}

    def _coerce_generated_event(self, raw, day, day_scope=True):
        if not isinstance(raw, dict):
            return None
        etype = str(raw.get("type", raw.get("domain", "event"))).strip().lower() or "event"
        topic = str(raw.get("topic", "")).strip() or "generated"
        name = str(raw.get("name", raw.get("title", raw.get("description", "外部事件")))).strip()
        description = str(raw.get("description", name)).strip()
        if not description:
            return None
        severity = _clip(raw.get("severity", 0.45))
        impact_tags = raw.get("impact_tags", [])
        if not isinstance(impact_tags, list):
            impact_tags = []
        start_time = str(raw.get("start_time", "")).strip()
        if not start_time:
            start_time = f"Day {day} 全天" if day_scope else f"Day {day}"
        return self._build_event(
            etype,
            topic,
            name or description[:18],
            description,
            severity=severity,
            impact_tags=[str(x).strip() for x in impact_tags if str(x).strip()],
            start_time=start_time,
            end_time=str(raw.get("end_time", "")).strip(),
            day=day,
        )

    def _llm_generate_day_environment(self, day, day_context):
        if not self.llm_fn or self.generator_mode != "llm":
            return None
        description = self.generator_description or "经济温和波动、天气多变、政策与技术持续调整的城市环境。"
        history = self._recent_day_summaries[-self.generator_history_days:] if self.generator_history_days > 0 else []
        history_text = "；".join(history) if history else "无历史摘要"
        prompt = f"""
你是城市模拟器的“外部环境生成器”。
请根据给定环境描述与近期演化历史，生成“今天”的外部环境与变化规则。

环境描述：
{description}

今天信息：
- day: {day}
- 日期: {day_context.get('sim_date', '')}
- 星期: {day_context.get('weekday_zh', '')}
- 日类型: {day_context.get('day_type_zh', '')}

近期历史摘要：
{history_text}

仅输出 JSON 对象，格式：
{{
  "day_summary": "一句话总结今天外部环境主线",
  "day_events": [
    {{
      "type": "natural|economic|political|technology",
      "topic": "weather/market/policy/adoption等",
      "name": "事件标题",
      "description": "事件描述",
      "severity": 0.0-1.0,
      "impact_tags": ["mobility","stress"]
    }}
  ],
  "intraday_rules": {{
    "natural_shock_chance": 0.0-1.0,
    "economic_shock_chance": 0.0-1.0,
    "political_shock_chance": 0.0-1.0,
    "technology_shock_chance": 0.0-1.0,
    "natural_shocks": ["..."],
    "economic_shocks": ["..."],
    "political_shocks": ["..."],
    "technology_shocks": ["..."]
  }}
}}
要求：
1) day_events 保持 1-4 条，覆盖你认为最重要的领域。
2) 不要编造具体数值统计来源；只描述趋势和情境。
3) 仅输出 JSON，不要其他文字。
"""
        try:
            resp = self.llm_fn(prompt, task="external_environment", agent_id=None)
        except (requests.RequestException, ValueError, RuntimeError) as exc:
            # LLM may fail with network errors, HTTP errors, or auth/config issues.
            _LOG.warning("LLM env generation failed: %s", exc)
            return None
        parsed = self._extract_json_object(resp)
        if not parsed:
            return None

        raw_events = parsed.get("day_events", [])
        day_events = []
        if isinstance(raw_events, list):
            for item in raw_events:
                ev = self._coerce_generated_event(item, day, day_scope=True)
                if ev:
                    day_events.append(ev)
        intraday_rules = parsed.get("intraday_rules", {})
        if not isinstance(intraday_rules, dict):
            intraday_rules = {}
        summary = str(parsed.get("day_summary", "")).strip()
        if not summary:
            summary = self._format_events(day_events) if day_events else "今日外部环境总体平稳。"
        return {
            "day_summary": summary,
            "day_events": day_events[:4],
            "intraday_rules": intraday_rules,
        }

    def _build_event(
        self,
        domain,
        topic,
        name,
        description,
        severity=0.3,
        scope="city",
        impact_tags=None,
        start_time=None,
        end_time=None,
        day=None,
        time_str=None,
    ):
        event_id = f"{domain}-{topic}-{day or ''}-{time_str or start_time or ''}-{abs(hash(description)) % 100000}"
        return {
            "id": event_id,
            "type": str(domain),
            "topic": str(topic),
            "name": str(name),
            "description": str(description),
            "severity": _clip(severity),
            "scope": str(scope),
            "start_time": str(start_time) if start_time else "",
            "end_time": str(end_time) if end_time else "",
            "impact_tags": list(impact_tags or []),
            "anomaly": False,
            "anomaly_score": 0.0,
        }

    def _annotate_anomaly(self, events):
        for event in events or []:
            if not isinstance(event, dict):
                continue
            event["anomaly"] = False
            event["anomaly_score"] = 0.0
            if not self.anomaly_enabled:
                continue
            severity = _clip(event.get("severity", 0.0))
            topic = str(event.get("topic", "")).strip().lower()
            domain = str(event.get("type", "")).strip().lower()
            is_intraday = topic == "intraday"
            threshold = self.anomaly_intraday_threshold if is_intraday else self.anomaly_severity_threshold
            threshold = max(0.01, float(threshold))
            score = severity / threshold
            keyword_bonus = 0.0
            if topic in {"extreme", "emergency", "shock", "intraday"}:
                keyword_bonus += 0.1
            if domain in {"natural", "economic", "political", "technology"} and is_intraday:
                keyword_bonus += 0.05
            score = _clip(score + keyword_bonus)
            if severity >= threshold:
                event["anomaly"] = True
                event["anomaly_score"] = round(score, 4)
        return events

    def _weighted_pick(self, choices, default_value):
        if not choices:
            return default_value
        labels = []
        weights = []
        for item in choices:
            if isinstance(item, dict):
                labels.append(item.get("name") or item.get("key") or default_value)
                weights.append(max(0.01, float(item.get("weight", 1.0))))
            else:
                labels.append(str(item))
                weights.append(1.0)
        return self.rng.choices(labels, weights=weights, k=1)[0]

    def _domain_cfg(self, key, defaults):
        domain_cfg = self.external_cfg.get(key, {})
        if not isinstance(domain_cfg, dict):
            domain_cfg = {}
        merged = dict(defaults)
        merged.update(domain_cfg)
        return merged

    def _generate_natural_day_event(self, day, day_context):
        cfg = self._domain_cfg(
            "natural",
            {
                "enabled": True,
                "daily_weather_chance": 0.95,
                "extreme_chance": 0.08,
                "weather_states": [
                    {"name": "晴朗", "weight": 0.28},
                    {"name": "多云", "weight": 0.24},
                    {"name": "小雨", "weight": 0.22},
                    {"name": "中雨", "weight": 0.12},
                    {"name": "高温", "weight": 0.08},
                    {"name": "寒潮", "weight": 0.06},
                ],
            },
        )
        if not cfg.get("enabled", True):
            return []
        events = []
        day_label = f"Day {day} 全天"
        if self.rng.random() < _safe_float(cfg.get("daily_weather_chance", 0.95)):
            weather_name = self._weighted_pick(cfg.get("weather_states", []), "多云")
            self._weather_state = weather_name
            desc = f"今日主要天气为{weather_name}，将影响出行与情绪。"
            sev = 0.2 if weather_name in ("晴朗", "多云") else 0.45
            if weather_name in ("高温", "寒潮"):
                sev = 0.55
            events.append(
                self._build_event(
                    "natural",
                    "weather",
                    f"天气：{weather_name}",
                    desc,
                    severity=sev,
                    impact_tags=["mobility", "emotion"],
                    start_time=day_label,
                    day=day,
                )
            )
        if self.rng.random() < _safe_float(cfg.get("extreme_chance", 0.08)):
            extreme_pool = list(cfg.get("extreme_events", [])) or ["短时强降雨预警", "空气质量恶化预警", "局地雷暴大风预警"]
            extreme = self.rng.choice(extreme_pool)
            events.append(
                self._build_event(
                    "natural",
                    "extreme",
                    extreme,
                    f"{extreme}，居民外出与公共活动受限。",
                    severity=0.72,
                    impact_tags=["mobility", "stress", "public_service"],
                    start_time=day_label,
                    day=day,
                )
            )
        return events

    def _generate_economic_day_event(self, day, day_context):
        cfg = self._domain_cfg(
            "economic",
            {
                "enabled": True,
                "daily_market_volatility": 0.012,
                "macro_event_chance": 0.12,
                "market_index_base": 100.0,
            },
        )
        if not cfg.get("enabled", True):
            return []
        events = []
        day_label = f"Day {day} 全天"
        vol = max(0.001, _safe_float(cfg.get("daily_market_volatility", 0.012)))
        drift = _safe_float(cfg.get("daily_market_drift", 0.0005))
        daily_ret = self.rng.gauss(drift, vol)
        self._market_index = max(40.0, self._market_index * (1.0 + daily_ret))
        pct = daily_ret * 100
        if abs(pct) >= _safe_float(cfg.get("market_news_threshold_pct", 0.6)):
            direction = "上涨" if pct > 0 else "下跌"
            sev = _clip(abs(pct) / 2.5, lo=0.2, hi=0.85)
            events.append(
                self._build_event(
                    "economic",
                    "market",
                    f"市场{direction}",
                    f"主要指数日内{direction}{abs(pct):.2f}%，市场风险偏好出现变化。",
                    severity=sev,
                    impact_tags=["econ_security", "risk_preference", "consumption"],
                    start_time=day_label,
                    day=day,
                )
            )
        if self.rng.random() < _safe_float(cfg.get("macro_event_chance", 0.12)):
            macro_pool = list(cfg.get("macro_events", [])) or [
                "社会消费数据走弱",
                "就业市场边际改善",
                "居民通胀预期上升",
                "制造业景气回落",
            ]
            macro = self.rng.choice(macro_pool)
            events.append(
                self._build_event(
                    "economic",
                    "macro",
                    macro,
                    f"{macro}，居民对收入与物价的预期发生调整。",
                    severity=0.58,
                    impact_tags=["econ_security", "stress"],
                    start_time=day_label,
                    day=day,
                )
            )
        return events

    def _generate_political_day_event(self, day, day_context):
        cfg = self._domain_cfg(
            "political",
            {
                "enabled": True,
                "daily_policy_chance": 0.10,
                "policy_events": [
                    "地方政府发布民生服务优化通知",
                    "就业促进政策细则更新",
                    "平台用工合规检查启动",
                ],
            },
        )
        if not cfg.get("enabled", True):
            return []
        if self.rng.random() >= _safe_float(cfg.get("daily_policy_chance", 0.10)):
            return []
        event_name = self.rng.choice(list(cfg.get("policy_events", [])) or ["政策沟通会议召开"])
        return [
            self._build_event(
                "political",
                "policy",
                event_name,
                f"{event_name}，公众对制度与规则变化的关注提升。",
                severity=0.5,
                impact_tags=["policy_sensitivity", "voice_propensity"],
                start_time=f"Day {day} 全天",
                day=day,
            )
        ]

    def _generate_technology_day_event(self, day, day_context):
        cfg = self._domain_cfg(
            "technology",
            {
                "enabled": True,
                "daily_tech_chance": 0.12,
                "tech_events": [
                    "主流平台推荐算法更新",
                    "本地智慧交通服务升级",
                    "新型办公工具在企业扩散",
                ],
            },
        )
        if not cfg.get("enabled", True):
            return []
        if self.rng.random() >= _safe_float(cfg.get("daily_tech_chance", 0.12)):
            return []
        event_name = self.rng.choice(list(cfg.get("tech_events", [])) or ["技术服务更新"])
        return [
            self._build_event(
                "technology",
                "adoption",
                event_name,
                f"{event_name}，工作与信息获取方式出现调整。",
                severity=0.46,
                impact_tags=["platform_dependence", "mobility_intent", "risk_preference"],
                start_time=f"Day {day} 全天",
                day=day,
            )
        ]

    def _generate_legacy_tick_events(self):
        events = []
        if not self.legacy_enabled:
            return events
        if self.rng.random() >= self.event_chance:
            return events
        candidates = []
        for name in self.natural_events:
            candidates.append(
                self._build_event(
                    "natural",
                    "legacy",
                    name,
                    name,
                    severity=0.35,
                    impact_tags=["mobility", "emotion"],
                )
            )
        for name in self.social_events:
            candidates.append(
                self._build_event(
                    "social",
                    "legacy",
                    name,
                    name,
                    severity=0.4,
                    impact_tags=["stress", "mobility"],
                )
            )
        if not candidates:
            return []
        k = min(self.max_events_per_tick, len(candidates))
        return self.rng.sample(candidates, k=k)

    def _generate_external_tick_events(self, day, time_str):
        if not self.external_enabled:
            return []
        cfg = self._domain_cfg(
            "intraday",
            {
                "enabled": True,
                "natural_shock_chance": 0.06,
                "economic_shock_chance": 0.05,
                "political_shock_chance": 0.03,
                "technology_shock_chance": 0.04,
            },
        )
        if isinstance(self._intraday_rules, dict):
            cfg.update(self._intraday_rules)
        if not cfg.get("enabled", True):
            return []
        events = []

        if self.rng.random() < _safe_float(cfg.get("natural_shock_chance", 0.06)):
            pool = list(cfg.get("natural_shocks", [])) or ["突发短时降雨", "局地交通受天气影响放缓", "空气质量短时恶化"]
            name = self.rng.choice(pool)
            events.append(
                self._build_event(
                    "natural",
                    "intraday",
                    name,
                    f"{name}（{time_str}）",
                    severity=0.48,
                    impact_tags=["mobility", "stress"],
                    start_time=f"Day {day} {time_str}",
                    day=day,
                    time_str=time_str,
                )
            )
        if self.rng.random() < _safe_float(cfg.get("economic_shock_chance", 0.05)):
            pool = list(cfg.get("economic_shocks", [])) or ["市场波动加剧", "大宗商品价格短时上行", "消费情绪短时走弱"]
            name = self.rng.choice(pool)
            events.append(
                self._build_event(
                    "economic",
                    "intraday",
                    name,
                    f"{name}（{time_str}）",
                    severity=0.52,
                    impact_tags=["econ_security", "risk_preference", "stress"],
                    start_time=f"Day {day} {time_str}",
                    day=day,
                    time_str=time_str,
                )
            )
        if self.rng.random() < _safe_float(cfg.get("political_shock_chance", 0.03)):
            pool = list(cfg.get("political_shocks", [])) or ["临时监管提示发布", "公共治理通告更新"]
            name = self.rng.choice(pool)
            events.append(
                self._build_event(
                    "political",
                    "intraday",
                    name,
                    f"{name}（{time_str}）",
                    severity=0.45,
                    impact_tags=["policy_sensitivity", "voice_propensity"],
                    start_time=f"Day {day} {time_str}",
                    day=day,
                    time_str=time_str,
                )
            )
        if self.rng.random() < _safe_float(cfg.get("technology_shock_chance", 0.04)):
            pool = list(cfg.get("technology_shocks", [])) or ["平台服务异常波动", "数字工具新功能灰度上线"]
            name = self.rng.choice(pool)
            events.append(
                self._build_event(
                    "technology",
                    "intraday",
                    name,
                    f"{name}（{time_str}）",
                    severity=0.42,
                    impact_tags=["platform_dependence", "mobility_intent"],
                    start_time=f"Day {day} {time_str}",
                    day=day,
                    time_str=time_str,
                )
            )
        return events

    def _format_events(self, events):
        if not events:
            return ""
        chunks = []
        for ev in events:
            severity = float(ev.get("severity", 0.0))
            topic = ev.get("topic", "")
            chunks.append(f"{ev.get('type', 'event')}/{topic}({severity:.2f}): {ev.get('description', '')}")
        return " ; ".join(chunks)

    def start_day(self, day, day_context=None, agents=None):
        if not self.enabled:
            self._day_events = []
            self._day_context = ""
            self._current_events = []
            return []
        events = []
        self._day_context = ""
        self._intraday_rules = {}
        generated = None
        if self.external_enabled and self.generator_mode == "llm":
            generated = self._llm_generate_day_environment(day, day_context or {})
        if generated:
            events.extend(generated.get("day_events", []))
            self._intraday_rules = generated.get("intraday_rules", {}) if isinstance(generated.get("intraday_rules", {}), dict) else {}
            self._day_context = str(generated.get("day_summary", "")).strip() or "今日外部环境总体平稳。"
        elif self.external_enabled:
            events.extend(self._generate_natural_day_event(day, day_context))
            events.extend(self._generate_economic_day_event(day, day_context))
            events.extend(self._generate_political_day_event(day, day_context))
            events.extend(self._generate_technology_day_event(day, day_context))
        self._annotate_anomaly(events)
        self._day_events = events
        if not self._day_context:
            summary = self._format_events(events)
            self._day_context = summary if summary else "今日外部环境总体平稳。"
        self._recent_day_summaries.append(self._day_context)
        if len(self._recent_day_summaries) > 30:
            self._recent_day_summaries = self._recent_day_summaries[-30:]
        self._current_events = []
        return list(self._day_events)

    def tick(self, day, time_str, agents=None):
        if not self.enabled:
            self._current_events = []
            return []
        events = []
        events.extend(self._generate_legacy_tick_events())
        events.extend(self._generate_external_tick_events(day, time_str))
        if len(events) > self.external_max_events_per_tick:
            events = self.rng.sample(events, k=self.external_max_events_per_tick)
        self._annotate_anomaly(events)
        self._current_events = events
        return list(events)

    def get_events(self):
        return list(self._current_events)

    def get_day_events(self):
        return list(self._day_events)

    def get_day_context_text(self):
        return self._day_context or "今日外部环境总体平稳。"

    def export_runtime_state(self):
        return {
            "weather_state": self._weather_state,
            "market_index": float(self._market_index),
            "recent_day_summaries": list(self._recent_day_summaries),
        }

    def import_runtime_state(self, state):
        if not isinstance(state, dict):
            return
        if "weather_state" in state:
            self._weather_state = str(state.get("weather_state") or self._weather_state)
        if "market_index" in state:
            try:
                self._market_index = float(state.get("market_index"))
            except (TypeError, ValueError):
                pass
        history = state.get("recent_day_summaries", [])
        if isinstance(history, list):
            self._recent_day_summaries = [str(x) for x in history if str(x).strip()][-30:]

    def get_context_text(self):
        tick_summary = self._format_events(self._current_events)
        day_summary = self.get_day_context_text()
        if tick_summary:
            return f"日级环境：{day_summary}；当前事件：{tick_summary}"
        return f"日级环境：{day_summary}"


class RemoteEnvironmentClient:
    def __init__(self, config):
        config = config or {}
        self.enabled = bool(config.get("enabled", False))
        self.base_url = str(config.get("base_url", "http://127.0.0.1:8765")).rstrip("/")
        self.timeout = float(config.get("timeout", 6))
        self.fallback_to_empty = bool(config.get("fallback_to_empty", True))
        self._current_events = []
        self._day_events = []
        self._day_context = "今日外部环境总体平稳。"

    def _post(self, path, payload):
        url = f"{self.base_url}{path}"
        try:
            resp = requests.post(url, json=payload, timeout=self.timeout)
            resp.raise_for_status()
            data = resp.json()
            return data if isinstance(data, dict) else {}
        except (requests.RequestException, ValueError) as exc:
            # ValueError covers JSONDecodeError; remote service may be down.
            _LOG.warning("Remote env POST %s failed: %s", url, exc)
            return {}

    def start_day(self, day, day_context=None, agents=None):
        if not self.enabled:
            self._day_events = []
            self._day_context = "今日外部环境总体平稳。"
            self._current_events = []
            return []
        payload = {"day": int(day), "day_context": day_context or {}}
        data = self._post("/day/start", payload)
        if not data:
            if self.fallback_to_empty:
                self._day_events = []
                self._day_context = "今日外部环境总体平稳。"
                self._current_events = []
                return []
            raise RuntimeError("remote environment server unavailable")
        self._day_events = list(data.get("events", []))
        self._day_context = str(data.get("context", "今日外部环境总体平稳。"))
        self._current_events = []
        return list(self._day_events)

    def tick(self, day, time_str, agents=None):
        if not self.enabled:
            self._current_events = []
            return []
        payload = {"day": int(day), "time": str(time_str)}
        data = self._post("/tick", payload)
        if not data:
            if self.fallback_to_empty:
                self._current_events = []
                return []
            raise RuntimeError("remote environment server unavailable")
        self._current_events = list(data.get("events", []))
        if data.get("context"):
            self._day_context = str(data.get("context"))
        return list(self._current_events)

    def get_events(self):
        return list(self._current_events)

    def get_day_events(self):
        return list(self._day_events)

    def get_day_context_text(self):
        return self._day_context or "今日外部环境总体平稳。"

    def get_context_text(self):
        tick_summary = []
        for ev in self._current_events:
            et = str(ev.get("type", "event"))
            topic = str(ev.get("topic", "")).strip()
            sev = float(ev.get("severity", 0.0))
            desc = str(ev.get("description", ev.get("name", "")))
            tick_summary.append(f"{et}/{topic}({sev:.2f}): {desc}")
        if tick_summary:
            return f"日级环境：{self.get_day_context_text()}；当前事件：{' ; '.join(tick_summary)}"
        return f"日级环境：{self.get_day_context_text()}"
