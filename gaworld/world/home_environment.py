"""Home environment design (P5 layer of the world/physical stack).

Every agent gets a deterministic procedural home: rooms (living room, bedroom,
dining room, kitchen, study, bathroom, balcony), furniture per room, an
ambiance (lighting + sound + smell + temperature + tidiness) that drifts with
day/weather and the agent's own habits, and a small ``at_home_activities``
table that the home mode projects onto the perception prompt when the agent is
actually at home. The same table decides **which room the agent is in**: the
activity they are doing picks the room (sleeping → bedroom, eating → dining
room, cooking → kitchen), so the agent really moves around inside their flat
instead of standing in one place.

Two design goals drive the shape of this module:

1. **Deterministic by default.** ``design_home(agent, seed)`` is pure — given
   the same agent id and seed, you get the same home — so a run with
   ``stateful=True`` can persist and reload the result without an LLM call.
2. **Optional LLM enrichment.** When ``home.llm_enrich`` is on, the procedural
   home gets passed through an LLM that polishes names (``"a worn reading
   armchair"`` instead of ``armchair``) and writes a one-line ``vibe``. Without
   LLM, the names stay generic but the structure is still useful — the prompt
   text only needs the structure, not the names.

The observation side is here too: :func:`home_observation` answers the
question "this tick the agent is at home, what does the home look like?",
returning a structured snapshot (current room + per-room activity intensity +
ambiance) that the plugin stuffs into ``perception.compose`` and records into
``output/home/agent_<id>.jsonl`` for downstream analysis.
"""

from __future__ import annotations

import hashlib
import json
import random
import re
from typing import Any

from gaworld.logging_setup import get_logger

_LOG = get_logger("gaworld.world.home_environment")


# ---------------------------------------------------------------------------
# Room templates.
# ---------------------------------------------------------------------------

# Each entry is a room with (display name, furniture pool, common activities,
# typical ambiance bias). Pools are deliberately small — the LLM polisher
# expands them when on; without LLM we still cover the everyday verbs.
ROOM_TEMPLATES: list[dict[str, Any]] = [
    {
        "key": "living_room",
        "name": "客厅",
        "furniture": ["沙发", "茶几", "电视柜", "电视", "地毯", "落地灯", "书架", "抱枕"],
        "activities": ["看电视", "刷手机", "接待客人", "看书", "喝茶", "听音乐", "做拉伸", "发呆", "吃零食"],
        "ambiance_bias": "social",
    },
    {
        "key": "bedroom",
        "name": "卧室",
        "furniture": ["床", "床头柜", "衣柜", "梳妆台", "台灯", "窗帘", "床头灯"],
        "activities": ["睡觉", "午休", "换衣服", "整理床铺", "敷面膜", "看手机", "听白噪音"],
        "ambiance_bias": "private",
    },
    {
        "key": "dining_room",
        "name": "餐厅",
        "furniture": ["餐桌", "餐椅", "碗柜", "餐边柜", "电饭煲", "花瓶"],
        "activities": [
            "吃早饭",
            "吃午饭",
            "吃晚饭",
            "吃饭",
            "早饭",
            "午饭",
            "晚饭",
            "吃夜宵",
            "家庭聚餐",
            "收拾餐桌",
        ],
        "ambiance_bias": "social",
    },
    {
        "key": "kitchen",
        "name": "厨房",
        "furniture": ["灶台", "抽油烟机", "冰箱", "微波炉", "电饭煲", "砧板", "调料架"],
        "activities": [
            "做饭",
            "做早餐",
            "做午餐",
            "做晚餐",
            "烧水",
            "泡茶",
            "泡咖啡",
            "洗菜",
            "洗碗",
            "热剩饭",
            "收拾厨房",
        ],
        "ambiance_bias": "active",
    },
    {
        "key": "study",
        "name": "书房",
        "furniture": ["书桌", "椅子", "电脑", "台灯", "书柜", "打印机", "显示器", "耳机"],
        "activities": [
            "加班",
            "写文档",
            "上网课",
            "看资料",
            "视频会议",
            "整理桌面",
            "剪视频",
            "学习",
            "写作业",
        ],
        "ambiance_bias": "focus",
    },
    {
        "key": "bathroom",
        "name": "卫生间",
        "furniture": ["马桶", "淋浴", "洗手台", "镜子", "洗衣机", "毛巾架", "吹风机"],
        "activities": ["洗澡", "刷牙", "洗脸", "上厕所", "吹头发", "洗衣服"],
        "ambiance_bias": "private",
    },
    {
        "key": "balcony",
        "name": "阳台",
        "furniture": ["晾衣架", "花盆", "藤椅", "小茶几", "遮阳伞"],
        "activities": ["晾衣服", "浇花", "看风景", "抽烟", "晒太阳", "发呆", "做操"],
        "ambiance_bias": "outdoor",
    },
]


# Ambiance dimensions: each has a small vocabulary and a default. The runtime
# state stores one record per dimension; the prompt builder concatenates them into
# a single "家的氛围：" line.
AMBIANCE_DIMS: list[str] = ["lighting", "sound", "smell", "temperature", "tidiness"]


# Default ambiance values, used when the home has never been touched.
DEFAULT_AMBIANCE: dict[str, str] = {
    "lighting": "自然光",
    "sound": "安静",
    "smell": "无明显气味",
    "temperature": "室温舒适",
    "tidiness": "基本整洁",
}


# Persona-driven bias on which rooms are present and how big each room is.
# Income is the strongest signal (a tiny apartment has fewer rooms); family
# shape adds the study / extra bedroom.
_INCOME_TIER = [
    # (max monthly income CNY, room_keys, room_size_range, ambiance_quality)
    (3000, ["bedroom", "kitchen", "bathroom", "living_room"], (4, 7), "minimal"),
    (7000, ["bedroom", "kitchen", "bathroom", "living_room", "dining_room"], (6, 10), "basic"),
    (
        15000,
        ["bedroom", "kitchen", "bathroom", "living_room", "dining_room", "study"],
        (8, 14),
        "comfortable",
    ),
    (
        40000,
        ["bedroom", "kitchen", "bathroom", "living_room", "dining_room", "study", "balcony"],
        (12, 22),
        "comfortable",
    ),
    (
        float("inf"),
        [
            "bedroom",
            "kitchen",
            "bathroom",
            "living_room",
            "dining_room",
            "study",
            "balcony",
            "bedroom_2",
        ],
        (18, 40),
        "premium",
    ),
]


def _home_id(agent: dict[str, Any]) -> str:
    """Stable id for an agent's home (used as the persistence filename)."""
    aid = agent.get("id")
    return f"agent_{aid}"


def _income_tier(monthly_income: float | int | None) -> tuple[list[str], tuple[int, int], str]:
    """Pick a tier from monthly income; default to the second tier if unknown."""
    income = float(monthly_income or 0.0)
    for cap, rooms, size_range, quality in _INCOME_TIER:
        if income <= cap:
            return rooms, size_range, quality
    return _INCOME_TIER[-1][1], _INCOME_TIER[-1][2], _INCOME_TIER[-1][3]


def _has_partner(agent: dict[str, Any]) -> bool:
    """Best-effort check for an in-household partner/spouse.

    Uses the family-assignment hook if present, else falls back to the agent's
    own ``marital_status``. ``False`` is a safe default."""
    fam = agent.get("household") if isinstance(agent, dict) else None
    if isinstance(fam, dict):
        size = len(fam.get("agent_ids") or [])
        if size >= 2:
            return True
    status = str(agent.get("marital_status", ""))
    return status in {"married", "同居"}


def _has_child(agent: dict[str, Any]) -> bool:
    fam = agent.get("household") if isinstance(agent, dict) else None
    if isinstance(fam, dict):
        for member in fam.get("members") or []:
            if isinstance(member, dict) and member.get("relation") in {"child", "子女"}:
                return True
    # Heuristic fallback: a 30-50 agent with a married status is plausible,
    # but we only set the flag when the family layer explicitly says so.
    return False


# ---------------------------------------------------------------------------
# Deterministic home design.
# ---------------------------------------------------------------------------


def _rng_for(agent: dict[str, Any], seed: Any) -> random.Random:
    base = f"{agent.get('id', '')}:{seed}"
    digest = hashlib.md5(base.encode("utf-8")).digest()
    return random.Random(int.from_bytes(digest[:8], "big"))


def design_home(agent: dict[str, Any], seed: Any = None) -> dict[str, Any]:
    """Build the procedural home for ``agent`` deterministically.

    Returned schema::

        {
            "home_id":        "agent_<id>",
            "home_node":      "Lakeview Tower",
            "rooms": {
                "living_room": {"name": "客厅", "size_sqm": 18, "furniture": [...]},
                ...
            },
            "ambiance_quality": "comfortable",
            "vibe": "采光不错，养了几盆绿植",
            "ambient_state": {"lighting": "...", ...},
            "at_home_activities": {
                "living_room": ["看电视", "刷手机", ...],
                ...
            },
        }
    """
    income = agent.get("monthly_income") or agent.get("income") or agent.get("salary") or 0
    room_keys, size_range, quality = _income_tier(income)
    rng = _rng_for(agent, seed)

    rooms: dict[str, dict[str, Any]] = {}
    activities: dict[str, list[str]] = {}
    for key in room_keys:
        template = _lookup_template(key)
        size = rng.randint(*size_range)
        furniture = sorted(
            set(
                rng.sample(
                    template["furniture"],
                    k=min(
                        len(template["furniture"]),
                        rng.randint(3, max(3, len(template["furniture"]) // 2 + 2)),
                    ),
                )
            )
        )
        rooms[key] = {
            "name": _room_name(key, template),
            "size_sqm": size,
            "furniture": furniture,
            "ambiance_bias": template["ambiance_bias"],
        }
        activities[key] = list(template["activities"])

    home_node = str((agent.get("locations") or {}).get("home", "") or "").strip()
    if not home_node:
        home_node = _home_id(agent)

    # Persona flavor: the determinism here is by agent id, so the same agent
    # always gets the same vibe.
    vibe_pool = [
        "采光不错，养了几盆绿植",
        "墙上挂着家人的照片",
        "书架上摆满了书",
        "角落里有一台小茶台",
        "厨房里飘着淡淡的饭菜香",
        "窗户望出去能看见小区花园",
        "沙发上盖着一条米色毯子",
        "整体偏简约风，留白比较多",
    ]
    vibe = rng.choice(vibe_pool)

    return {
        "home_id": _home_id(agent),
        "home_node": home_node,
        "rooms": rooms,
        "ambiance_quality": quality,
        "vibe": vibe,
        "ambient_state": dict(DEFAULT_AMBIANCE),
        "at_home_activities": activities,
    }


def _lookup_template(key: str) -> dict[str, Any]:
    if key == "bedroom_2":
        # A second bedroom (kid room / guest room) reuses the bedroom template
        # without the master-bedroom furniture bias.
        return next(t for t in ROOM_TEMPLATES if t["key"] == "bedroom")
    return next(t for t in ROOM_TEMPLATES if t["key"] == key)


def _room_name(key: str, template: dict[str, Any]) -> str:
    """The room's name. Two bedrooms need two names (the flat plan draws them
    as separate rooms, and one label per room has to stay unique)."""
    if key == "bedroom_2":
        return "次卧"
    return str(template["name"])


# ---------------------------------------------------------------------------
# Ambient state evolution.
# ---------------------------------------------------------------------------


_LIGHTING_BY_HOUR = [
    ((0, 5), "夜灯昏暗"),
    ((5, 7), "晨光初起"),
    ((7, 18), "自然光"),
    ((18, 20), "暖色吊灯"),
    ((20, 24), "台灯+落地灯"),
]


def _lighting_for(time_str: str, weather_state: str) -> str:
    """Pick a lighting label from time-of-day + weather."""
    try:
        hour = int(time_str.split(":")[0])
    except (AttributeError, ValueError):
        hour = 12
    label = "自然光"
    for (start, end), text in _LIGHTING_BY_HOUR:
        if start <= hour < end:
            label = text
            break
    if weather_state in {"rain", "snow"} and "自然光" in label:
        label = "窗外天色阴沉，开了主灯"
    if weather_state == "hot" and label == "自然光":
        label = "拉上了遮光帘，开空调"
    return label


def _sound_for(activity: str, home: dict[str, Any]) -> str:
    """A short sound line reflecting the current activity + ambient baseline."""
    if activity in {"睡觉", "午休", "敷面膜", "听白噪音"}:
        return "很安静"
    if activity in {"做饭", "做早餐", "做午餐", "做晚餐", "洗碗", "洗菜", "热剩饭", "收拾厨房"}:
        return "厨房传来锅碗声"
    if activity in {"吃早饭", "吃午饭", "吃晚饭", "吃饭", "家庭聚餐"}:
        return "碗筷轻碰的声音"
    if activity in {"看电视", "刷手机"}:
        return "电视/手机的低语"
    if activity in {"看资料", "加班", "写文档", "视频会议", "剪视频"}:
        return "键盘与纸页声"
    if activity in {"洗澡", "吹头发", "洗衣服"}:
        return "水流声"
    if activity in {"接待客人"}:
        return "聊天的笑声"
    if activity in {"浇花", "晾衣服", "看风景", "晒太阳"}:
        return "窗外小区里的人声"
    return "比较安静"


def _temperature_for(weather_state: str, ambiance_quality: str) -> str:
    base = {
        "hot": "开了空调，26℃",
        "cold": "开了暖气",
        "rain": "空气有点潮",
        "snow": "开了地暖",
        "clear": "室温舒适",
    }.get(weather_state, "室温舒适")
    if ambiance_quality == "minimal" and base == "室温舒适":
        return "有点闷热"
    return base


def _tidiness_for(activity: str, current_tidiness: str) -> str:
    """Living room drops a notch after cooking; cleaning lifts it back."""
    score = {
        "基本整洁": 2,
        "有点乱": 1,
        "比较乱": 0,
    }.get(current_tidiness, 2)
    if activity in {"做饭", "做早餐", "做午餐", "做晚餐", "洗碗", "洗菜"}:
        score = max(0, score - 1)
    if activity in {"整理床铺", "整理桌面", "收拾餐桌", "收拾厨房"}:
        score = min(2, score + 1)
    return ["比较乱", "有点乱", "基本整洁"][score]


def _smell_for(activity: str) -> str:
    if activity in {"做饭", "做早餐", "做午餐", "做晚餐", "吃早饭", "吃午饭", "吃晚饭", "热剩饭"}:
        return "饭菜香"
    if activity in {"泡茶", "泡咖啡"}:
        return "茶香/咖啡香"
    if activity in {"洗澡", "刷牙", "洗脸"}:
        return "沐浴露/牙膏味"
    return "无明显气味"


def update_ambiance(
    home: dict[str, Any],
    *,
    time_str: str,
    weather_state: str,
    activity: str = "",
) -> dict[str, str]:
    """Mutate ``home["ambient_state"]`` for the new tick and return it.

    Each call re-derives lighting/sound/smell/temperature from the new tick's
    context; tidiness is the only stateful one (the cleaning/cooking deltas
    accumulate over the day)."""
    state = home.setdefault("ambient_state", dict(DEFAULT_AMBIANCE))
    quality = home.get("ambiance_quality", "comfortable")
    state["lighting"] = _lighting_for(time_str, weather_state)
    state["temperature"] = _temperature_for(weather_state, quality)
    if activity:
        state["sound"] = _sound_for(activity, home)
        state["smell"] = _smell_for(activity)
        state["tidiness"] = _tidiness_for(activity, state.get("tidiness", "基本整洁"))
    return state


# ---------------------------------------------------------------------------
# Observation: what the agent sees of the home this tick.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Activity → room.
# ---------------------------------------------------------------------------

#: Keyword rules for the room an activity belongs to. The order matters — the
#: first match wins — so the specific ones come first (cooking before eating:
#: "做饭" contains "饭"; sleeping before resting: "睡前" is a bedroom thing).
ACTIVITY_ROOM_RULES: list[tuple[re.Pattern[str], str]] = [
    (
        re.compile(
            r"做[^，。！？\s]{0,3}(饭|菜|餐|夜宵)|烹饪|下厨|备菜|烧水|泡(茶|咖啡)|洗菜|洗碗|热剩饭|收拾厨房"
        ),
        "kitchen",
    ),
    (re.compile(r"睡|午休|午睡|躺|起床|换衣服|整理床铺|敷面膜|白噪音"), "bedroom"),
    (
        re.compile(
            r"学习|上课|作业|看书|阅读|办公|加班|工作|写文档|电脑|网课|视频会议|整理桌面|剪视频|论文|复习|备课|待办"
        ),
        "study",
    ),
    (re.compile(r"吃|用餐|早餐|午餐|晚餐|夜宵|聚餐|早饭|午饭|晚饭|饭"), "dining_room"),
    (re.compile(r"洗澡|淋浴|刷牙|洗脸|上厕所|如厕|卫生间|洗衣|吹头发"), "bathroom"),
    (
        re.compile(r"电视|手机|客人|聊天|喝茶|听音乐|拉伸|发呆|零食|接待|追剧|游戏|个人时间|刷|逗孩子"),
        "living_room",
    ),
    (re.compile(r"浇花|晾衣|晒太阳|看风景|抽烟|做操|通风|乘凉|看楼下|晨练"), "balcony"),
]


#: Where an activity lands when the home has no room of that kind (a small
#: flat has no dining room: the meal happens in the living room).
ROOM_FALLBACKS: dict[str, tuple[str, ...]] = {
    "dining_room": ("living_room", "kitchen"),
    "kitchen": ("dining_room", "living_room"),
    "study": ("living_room",),
    "bathroom": ("bedroom",),
    "balcony": ("living_room",),
}


def _room_key_for_activity(home: dict[str, Any], activity: str, time_str: str = "") -> str:
    """The room key an activity belongs to (without checking the home has it)."""
    activities = home.get("at_home_activities") or {}
    for room_key, options in activities.items():
        if activity and activity in options:
            return room_key
    for pattern, room_key in ACTIVITY_ROOM_RULES:
        if activity and pattern.search(activity):
            return room_key
    # Time-of-day fallback when the activity is too generic ("休息", "居家")
    try:
        hour = int((time_str or "12:00").split(":")[0])
    except (ValueError, AttributeError):
        hour = 12
    if hour >= 22 or hour < 6:
        return "bedroom"
    if hour < 9:
        return "kitchen"
    return "living_room"


def pick_room_for_activity(
    home: dict[str, Any],
    activity: str,
    time_str: str = "",
) -> tuple[str, str]:
    """Map the agent's current activity to a (room_key, room_name) inside the home.

    Three passes: the room's own activity list (an exact hit wins), then the
    keyword rules (so the daily routine's vocabulary — 午饭、睡前、个人时间 —
    lands in the right room), then the time of day. A room the home does not
    have falls back to the closest one it does have."""
    rooms = home.get("rooms") or {}
    key = _room_key_for_activity(home, activity, time_str)
    if key in rooms:
        return key, rooms[key].get("name", key)
    for alt in ROOM_FALLBACKS.get(key, ()):
        if alt in rooms:
            return alt, rooms[alt].get("name", alt)
    for alt in ("living_room", "bedroom", "kitchen"):
        if alt in rooms:
            return alt, rooms[alt].get("name", alt)
    if rooms:
        first = next(iter(rooms))
        return first, rooms[first].get("name", first)
    return "living_room", "客厅"


def home_observation(
    agent: dict[str, Any],
    home: dict[str, Any],
    *,
    activity: str = "",
    time_str: str = "",
) -> dict[str, Any]:
    """Return the per-tick home snapshot (current room + ambiance summary).

    Output schema::

        {
            "is_at_home": True,
            "home_node": "Lakeview Tower",
            "current_room": {"key": "kitchen", "name": "厨房", "size_sqm": 9,
                             "furniture": ["灶台", ...]},
            "ambiance": {"lighting": "...", "sound": "...", ...},
            "vibe": "采光不错，养了几盆绿植",
        }
    """
    if not home:
        return {"is_at_home": False}
    room_key, room_name = pick_room_for_activity(home, activity, time_str)
    rooms = home.get("rooms") or {}
    current_room = {
        "key": room_key,
        "name": room_name,
        "size_sqm": rooms.get(room_key, {}).get("size_sqm"),
        "furniture": rooms.get(room_key, {}).get("furniture", []),
    }
    return {
        "is_at_home": True,
        "home_node": home.get("home_node", ""),
        "current_room": current_room,
        "ambiance": dict(home.get("ambient_state") or DEFAULT_AMBIANCE),
        "vibe": home.get("vibe", ""),
    }


# ---------------------------------------------------------------------------
# Prompt text builder.
# ---------------------------------------------------------------------------


def _format_room_line(obs: dict[str, Any]) -> str:
    room = obs.get("current_room") or {}
    furniture = room.get("furniture") or []
    size = room.get("size_sqm")
    bits = [f"你正在家里的【{room.get('name', '')}】"]
    if size:
        bits.append(f"约{size}平米")
    if furniture:
        # Cap the furniture list so we don't blow up the prompt.
        bits.append("布置有：" + "、".join(furniture[:5]))
        if len(furniture) > 5:
            bits.append("等")
    return "，".join(bits) + "。"


def _format_ambiance_line(ambiance: dict[str, str]) -> str:
    if not ambiance:
        return ""
    parts = []
    for key in AMBIANCE_DIMS:
        value = ambiance.get(key)
        if value:
            parts.append(f"{key}：{value}")
    label_map = {
        "lighting": "光线",
        "sound": "声音",
        "smell": "气味",
        "temperature": "体感",
        "tidiness": "整洁度",
    }
    pretty = "，".join(
        label_map.get(key, key) + "「" + value + "」"
        for key, value in zip(AMBIANCE_DIMS, (ambiance.get(k, "") for k in AMBIANCE_DIMS), strict=False)
        if value
    )
    return f"此刻家里的氛围：{pretty}。"


def home_prompt_lines(obs: dict[str, Any]) -> list[str]:
    """Render the at-home snippet for the perception prompt.

    Returns an empty list when the agent isn't at home — the plugin only
    contributes when the snapshot says ``is_at_home``."""
    if not obs or not obs.get("is_at_home"):
        return []
    lines = []
    room_line = _format_room_line(obs)
    if room_line:
        lines.append(room_line)
    ambiance_line = _format_ambiance_line(obs.get("ambiance") or {})
    if ambiance_line:
        lines.append(ambiance_line)
    vibe = obs.get("vibe")
    if vibe:
        lines.append(f"家里的整体气质：{vibe}。")
    return lines


# ---------------------------------------------------------------------------
# Persistence.
# ---------------------------------------------------------------------------


_JSON_LINE_SEP = "\n"


def _safe_json(obj: Any) -> str:
    try:
        return json.dumps(obj, ensure_ascii=False, sort_keys=True)
    except (TypeError, ValueError):
        return json.dumps(str(obj), ensure_ascii=False)


def save_home(home_id: str, home: dict[str, Any], output_dir: Any) -> None:
    """Persist the designed home to ``<output_dir>/<home_id>.json``.

    Re-running with the same ``seed`` yields the same home, so this is the
    cache key for ``stateful=True`` runs."""
    if home is None or not output_dir:
        return
    try:
        from pathlib import Path

        path = Path(output_dir) / f"{home_id}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_safe_json(home), encoding="utf-8")
    except OSError as exc:
        _LOG.warning("save_home(%s) failed: %s", home_id, exc)


def load_home(home_id: str, output_dir: Any) -> dict[str, Any] | None:
    try:
        from pathlib import Path

        path = Path(output_dir) / f"{home_id}.json"
        if not path.exists():
            return None
        text = path.read_text(encoding="utf-8").strip()
        if not text:
            return None
        return json.loads(text)
    except (OSError, ValueError) as exc:
        _LOG.warning("load_home(%s) failed: %s", home_id, exc)
        return None


def append_observation(
    output_dir: Any,
    *,
    agent_id: Any,
    day: Any,
    time_str: str,
    obs: dict[str, Any],
) -> None:
    """Append one observation row to ``<output_dir>/agent_<id>.jsonl``.

    The Recorder is the canonical writer for plugin-shaped artifacts; this
    helper exists so tests and offline tooling can read the same rows."""
    if not output_dir or not obs:
        return
    try:
        from pathlib import Path

        path = Path(output_dir) / f"agent_{agent_id}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        row = {"day": day, "time": time_str, **obs}
        with path.open("a", encoding="utf-8") as f:
            f.write(_safe_json(row) + _JSON_LINE_SEP)
    except OSError as exc:
        _LOG.warning("append_observation(agent_%s) failed: %s", agent_id, exc)


# ---------------------------------------------------------------------------
# LLM polisher (optional, opt-in via home.llm_enrich).
# ---------------------------------------------------------------------------


_POLISH_PROMPT = """你是一位住宅软装编辑。请基于下面的家庭结构与房间清单，把每个房间的家具改写成更生活化的中文短语（保留语义，不要添加家电），并写一句整体气质。
要求：
1) 仅输出 JSON。
2) 键为房间 key（living_room/bedroom/dining_room/kitchen/study/bathroom/balcony/bedroom_2）。
3) 每个房间输出 `furniture`（4-7 个短语）和可选 `note`（一句该房间的描述，不超过 25 字）。
4) 最后输出 `vibe`：一句整体气质（不超过 25 字）。
"""


def _extract_json_block(text: str) -> str:
    match = re.search(r"\{.*\}", text or "", re.S)
    return match.group(0) if match else ""


def polish_home_with_llm(
    home: dict[str, Any],
    *,
    call_llm: Any,
    agent: dict[str, Any],
) -> dict[str, Any]:
    """Optionally enrich the procedural home via an LLM call.

    Returns ``home`` unchanged on parse failure — the procedural output is
    still useful, so a bad LLM response is logged, not raised."""
    if not home or not callable(call_llm):
        return home
    payload = json.dumps(
        {
            "rooms": {
                k: {"name": v["name"], "furniture": v["furniture"]}
                for k, v in (home.get("rooms") or {}).items()
            },
            "ambiance_quality": home.get("ambiance_quality", ""),
        },
        ensure_ascii=False,
        indent=2,
    )
    prompt = f"{_POLISH_PROMPT}\n家庭资料：{json.dumps({'name': agent.get('name', ''), 'age': agent.get('age', ''), 'job': agent.get('job', '')}, ensure_ascii=False)}\n{payload}"
    try:
        response = call_llm(prompt, task="home_polish", agent_id=agent.get("id"))
    except Exception as exc:
        _LOG.warning("home LLM polish failed for agent %s: %s", agent.get("id"), exc)
        return home
    raw = _extract_json_block(response or "")
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return home
    if not isinstance(parsed, dict):
        return home
    rooms = home.get("rooms") or {}
    for key, info in parsed.items():
        if not isinstance(info, dict) or key not in rooms:
            continue
        if isinstance(info.get("furniture"), list):
            new_furniture = [str(x).strip() for x in info["furniture"] if str(x).strip()]
            if new_furniture:
                rooms[key]["furniture"] = new_furniture[:8]
    if isinstance(parsed.get("vibe"), str) and parsed["vibe"].strip():
        home["vibe"] = parsed["vibe"].strip()[:50]
    return home
