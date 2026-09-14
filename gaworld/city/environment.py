"""Derive a city's environment config from its geocoded place record.

``EnvironmentSystem`` reads two blocks: the legacy ``environment`` (fixed pools
of natural / social events it samples from) and ``external_environment`` (whose
``generator.description`` is the prompt context an LLM uses to invent events).
Both are place-specific — a coastal subtropical town should get typhoons and a
continental one should get blizzards — so we derive them from the latitude and
scale that geocoding already gave us instead of shipping one global default.
"""

from __future__ import annotations

from typing import Any

from gaworld.city.geocode import Place

#: |latitude| upper bound → climate key. Ordered; first match wins.
CLIMATE_BANDS = (
    (23.5, "tropical"),
    (35.0, "subtropical"),
    (50.0, "temperate"),
    (66.5, "continental"),
    (90.0, "polar"),
)

CLIMATE_LABEL_ZH = {
    "tropical": "热带",
    "subtropical": "亚热带",
    "temperate": "温带",
    "continental": "大陆性寒冷",
    "polar": "极地",
}

NATURAL_EVENTS: dict[str, list[str]] = {
    "tropical": [
        "午后雷阵雨，短时强降水",
        "台风外围环流影响，风力加大",
        "持续高温高湿，体感闷热",
        "空气质量转差，能见度下降",
        "连续晴热，用电负荷升高",
    ],
    "subtropical": [
        "午后有小雨，路面湿滑",
        "冷空气到达，气温明显下降",
        "清晨有大雾，能见度低",
        "高温橙色预警",
        "梅雨持续，空气潮湿",
    ],
    "temperate": [
        "阴雨天气，气温偏低",
        "强冷空气南下，降温明显",
        "早晨霜冻，道路结冰",
        "大风降温，体感寒冷",
        "空气质量良好，适宜出行",
    ],
    "continental": [
        "降雪天气，道路积雪",
        "寒潮来袭，气温骤降",
        "暴风雪预警，出行受阻",
        "极端低温，供暖负荷升高",
        "冰冻天气，路面湿滑",
    ],
    "polar": [
        "极寒天气，户外活动受限",
        "暴风雪，能见度极低",
        "长时间极夜，日照不足",
        "道路封闭，物资运输延迟",
        "低温持续，供暖压力大",
    ],
}

#: Social events scale with the city: a village has no metro to delay.
SOCIAL_EVENTS: dict[str, list[str]] = {
    "small": [
        "集市开集，镇中心人流增加",
        "村口道路施工，绕行通行",
        "社区义诊活动",
        "农产品收购价格波动",
        "乡镇文化演出",
    ],
    "medium": [
        "主干道交通拥堵",
        "公交线路临时调整",
        "社区市集活动",
        "学校放假，家庭出行增加",
        "本地商圈促销活动",
    ],
    "large": [
        "主干道交通拥堵",
        "地铁运营延误",
        "城市马拉松导致道路封闭",
        "大型演出，周边人流密集",
        "商圈促销活动，客流激增",
    ],
}

#: scale → the SOCIAL_EVENTS bucket to use.
SCALE_TO_SOCIAL = {
    "tiny": "small",
    "small": "small",
    "medium": "medium",
    "large": "large",
    "metro": "large",
}

SCALE_LABEL_ZH = {
    "tiny": "村庄",
    "small": "小镇",
    "medium": "中等城市",
    "large": "大城市",
    "metro": "超大城市",
}


def climate_of(lat: float) -> str:
    """Climate key for a latitude (northern/southern hemisphere symmetric)."""
    magnitude = abs(float(lat))
    for bound, key in CLIMATE_BANDS:
        if magnitude < bound:
            return key
    return "polar"


def describe(place: Place) -> str:
    """The prompt context an LLM uses to invent plausible events here."""
    climate = CLIMATE_LABEL_ZH[climate_of(place.lat)]
    scale = SCALE_LABEL_ZH.get(place.scale, "城市")
    where = f"{place.country}的" if place.country else ""
    population = f"常住人口约 {place.population:,} 人；" if place.population else ""
    return (
        f"{where}{place.name}，{scale}，{climate}气候，季节性天气变化明显；{population}"
        f"当地经济与就业结构随规模而定，居民对物价、就业与公共服务变化敏感。"
    )


def background_for(place: Place) -> str:
    """The simulation ``background`` prompt for this city.

    Without this every new city inherits the default Hangzhou background and
    its agents reason about the wrong place entirely.
    """
    climate = CLIMATE_LABEL_ZH[climate_of(place.lat)]
    scale = SCALE_LABEL_ZH.get(place.scale, "城市")
    where = f"{place.country}·{place.name}" if place.country else place.name
    return (
        f"{where}。{scale}，{climate}气候。"
        f"当地经济与就业结构与其规模相称，居民对物价、就业与公共服务的变化较为敏感；"
        f"社会秩序稳定。"
    )


def build_environment(place: Place, *, enabled: bool = True, seed: int | None = None) -> dict[str, Any]:
    """The ``environment.json`` fragment for a city bundle.

    Shaped as a partial config: the keys merge over ``data/environment_config.json``
    so a bundle only overrides what is genuinely place-specific.
    """
    climate = climate_of(place.lat)
    social_bucket = SCALE_TO_SOCIAL.get(place.scale, "medium")
    return {
        "city": place.name,
        "climate": climate,
        "background": background_for(place),
        "environment": {
            "enabled": bool(enabled),
            "event_chance": 0.6,
            "max_events_per_tick": 2,
            "natural_events": list(NATURAL_EVENTS[climate]),
            "social_events": list(SOCIAL_EVENTS[social_bucket]),
        },
        "external_environment": {
            "enabled": bool(enabled),
            "seed": seed,
            "max_events_per_tick": 3,
            "generator": {
                "mode": "llm",
                "history_days": 3,
                "description": describe(place),
            },
        },
    }


__all__ = [
    "CLIMATE_BANDS",
    "NATURAL_EVENTS",
    "SOCIAL_EVENTS",
    "background_for",
    "build_environment",
    "climate_of",
    "describe",
]
