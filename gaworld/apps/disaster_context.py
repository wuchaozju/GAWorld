"""Read-only local scenarios and auditable, stage-delayed social messages."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from gaworld.apps.game_reactions import scale_integer

RELATIONS = {
    "sibling": "兄弟姐妹",
    "spouse": "配偶",
    "parent": "亲子",
    "child": "亲子",
    "grandparent": "祖孙",
    "grandchild": "祖孙",
    "friend": "朋友",
    "neighbor": "邻居",
    "coworker": "同事",
    "family": "家人",
}

PANIC_SCALE = "1=平静能安排事务；2=担心但能按计划行动；3=焦虑影响判断；4=强烈恐惧难以集中；5=极度恐慌无法有序行动。模型角色自报，非经验证的心理量表。"
METRIC_DEFINITIONS = {
    "n": "总反应人次=居民数×阶段数，包含失败尝试，不是去重人数。",
    "actions": "行动分布只统计有效主行动；次要行动不重复计数。",
    "help_rate": "家庭外互助率=help=true人次/有效help布尔回答人次；保护家人不计入此项，不代表互助已成功。",
    "avg_panic": "平均恐慌=有效1—5整数评分之和/有效评分人次。" + PANIC_SCALE,
    "missing": "无有效回答显示—；解析失败及缺失字段不补分、不视为不互助。",
}


def load_context(city: str, ids: list[int]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Read the selected world's seed and an existing region; never research."""
    from gaworld.apps import world_paths
    from gaworld.city.bundle import CityNotFoundError, resolve_city
    from gaworld.city.config import run_overrides
    from gaworld.city.region import load_region
    from gaworld.interview.roster import city_paths, recruitment_population

    active_city = str(world_paths.effective_config().get("city") or "")
    selected_city = city or active_city
    region: dict[str, Any] = {}
    if selected_city:
        try:
            region = load_region(resolve_city(selected_city)).to_dict()
        except (CityNotFoundError, OSError, ValueError):
            pass
    rows = [dict(p) for p in recruitment_population(city) if int(p["id"]) in ids]
    memory_dir = (
        Path(world_paths.memory_base_dir())
        if not city or city == active_city
        else Path(world_paths.REPO_ROOT) / run_overrides(selected_city)["memory_dir"]
    )
    seed = (
        Path(world_paths.state_csv_path())
        if not city or (world_paths.current_world() and city == active_city)
        else city_paths(city)[0]
    )
    raw_rows: dict[int, dict[str, Any]] = {}
    try:
        with seed.open(encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                aid = scale_integer(row.get("id"), 1, 2**53)
                if aid in ids:
                    raw_rows[aid] = row
    except (OSError, UnicodeError, csv.Error):
        pass
    for row in rows:
        raw = raw_rows.get(int(row["id"]), {}).get("relationships", "")
        try:
            relations = json.loads(raw) if isinstance(raw, str) and raw else {}
        except (ValueError, TypeError):
            relations = {}
        if not isinstance(relations, dict):
            relations = {}
        try:
            existing = json.loads(
                (memory_dir / f"agent_{int(row['id'])}_relationships.json").read_text(encoding="utf-8")
            )
        except (OSError, ValueError, UnicodeError):
            existing = {}
        if isinstance(existing, dict):
            relations.update(
                {
                    key: value
                    for key, value in existing.items()
                    if isinstance(value, dict) and value.get("kind", "agent") == "agent"
                }
            )
        row["relationships"] = {
            key: value
            for key, value in relations.items()
            if isinstance(value, dict) and value.get("kind", "agent") == "agent"
        }
    return region, relationship_edges(rows)


def relationship_edges(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Explicit seed ties first; infer only non-familial ties when absent."""
    edges = []
    for index, left in enumerate(rows):
        for right in rows[index + 1 :]:
            a, b = int(left["id"]), int(right["id"])
            ties = left.get("relationships") or {}
            back = right.get("relationships") or {}
            tie = ties.get(str(b), ties.get(b)) or back.get(str(a), back.get(a))
            same_home = bool(left.get("residence")) and left.get("residence") == right.get("residence")
            if isinstance(tie, dict):
                role = str(tie.get("relation") or tie.get("type") or tie.get("role") or "熟人")
                label, source = RELATIONS.get(role, role), "explicit"
            elif same_home:
                label, source = "邻居", "inferred"
            elif (
                left.get("job")
                and left.get("job") == right.get("job")
                and left["job"] not in ("退休", "无业", "学生")
            ):
                label, source = "同行", "inferred"
            elif left.get("age") and right.get("age") and abs(int(left["age"]) - int(right["age"])) <= 5:
                label, source = "同龄熟人", "inferred"
            else:
                continue
            edges.append(
                {
                    "a": a,
                    "b": b,
                    "label": label,
                    "source": source,
                    "channel": "face_to_face" if same_home else "remote",
                }
            )
    return edges


def local_scenario(disaster: dict[str, Any], region: dict[str, Any]) -> tuple[list[str], dict[str, Any]]:
    """Scenario assumptions derive from documented terrain, never city names."""
    original = list(disaster["stages"])
    dossier = "；".join(str(region.get(k) or "") for k in ("terrain", "water", "climate", "commuting"))
    kind = (
        "coastal"
        if any(k in dossier for k in ("沿海", "海岸", "海岛", "海滨"))
        else "mountain"
        if any(k in dossier for k in ("山区", "山地", "丘陵", "高山"))
        else "water_town"
        if any(k in dossier for k in ("水乡", "河网", "湖区", "水网"))
        else "generic"
    )
    context = {
        "kind": kind,
        "source": region.get("source", "missing"),
        "basis": {k: region[k] for k in ("terrain", "water", "climate", "commuting") if region.get(k)},
        "sources": region.get("sources", []),
        "note": "依据已有地域资料构造的假想情境，不是当地实际灾情。"
        if dossier.strip("；")
        else "缺少地域资料，使用通用假想情境。",
    }
    if disaster["id"] == "custom":
        context["note"] = "使用用户自定义情境，保留原文。"
        return original, context
    floods = {
        "mountain": [
            "连续暴雨36小时，山区沟谷发生山洪，坡面落石，出村山路局部中断。收到暴雨红色预警，需要判断家人位置与可用避险路线。",
            "第二天：山洪仍在，低处房屋进水，山路中断，小区断电断网。救援人员从可通行路段逐户联系。",
            "第五天：水退后山路仍有塌方风险，社区统计房屋与农具损失，居民要决定临时安置与修复顺序。",
        ],
        "coastal": [
            "连续暴雨36小时，沿海低洼地带排水受潮位顶托，局部倒灌。收到暴雨红色预警，居民需要判断沿海道路是否可通行。",
            "第二天：低洼房屋持续进水，部分沿海道路封闭，小区断电断网。救援人员从安全路线安排转移。",
            "第五天：积水消退，潮湿与污损影响电器、店铺和渔具，社区登记损失，排水设施仍需检查。",
        ],
        "water_town": [
            "连续暴雨36小时，水乡河网水位上涨，低桥与沿河巷道被淹。收到暴雨红色预警，一楼住户需要安排家人与物品转移。",
            "第二天：河网仍维持高水位，桥头通行受限，小区断电断网，救援小船沿安全水路联络住户。",
            "第五天：水退后沿河屋内满是淤泥，电器和临街店铺受损，社区按街巷登记损失。",
        ],
    }
    if disaster["id"] == "flood" and kind in floods:
        return floods[kind], context
    modifiers = {
        "mountain": "山路和分散住户限制面对面联络与物资运送。",
        "coastal": "沿海通道与港口相关生计影响撤离及物资安排。",
        "water_town": "河网、低桥及临水住户影响联络、通行与财产保护。",
    }
    addition = modifiers.get(kind, "")
    return [text + ("【地域条件】" + addition if addition else "") for text in original], context


def stage_messages(
    people: list[Any], edges: list[dict[str, Any]], stage: int, text: str
) -> tuple[dict[int, list[dict[str, Any]]], list[dict[str, Any]]]:
    """Only prior-stage messages cross edges, with explicit channel failures."""
    inbox: dict[int, list[dict[str, Any]]] = {p.agent_id: [] for p in people}
    blocked = []
    if not stage:
        return inbox, blocked
    by_id = {p.agent_id: p for p in people}
    outage = max(text.rfind(word) for word in ("断网", "全城停电", "小区断电", "信号一格一格"))
    restored = max(text.rfind(word) for word in ("网络恢复", "恢复网络", "通信恢复", "信号恢复"))
    offline = outage > restored
    for edge in edges:
        for sender, target in ((edge["a"], edge["b"]), (edge["b"], edge["a"])):
            if sender not in by_id or target not in by_id or sender == target:
                continue
            previous = by_id[sender].reactions[stage - 1]
            if previous.get("parse_status") == "invalid":
                continue
            event = {
                "from": sender,
                "to": target,
                "name": by_id[sender].name,
                "stage": stage,
                "source_stage": stage - 1,
                "label": edge.get("label", "熟人"),
                "source": edge.get("source", "provided"),
                "channel": edge.get("channel", "remote"),
                "action": previous["action"],
                "detail": previous["detail"],
                "say": previous["say"],
            }
            if offline and event["channel"] == "remote":
                blocked.append({**event, "reason": "本阶段停电或断网，远程消息未送达"})
            else:
                inbox[target].append(event)
    return inbox, blocked


def observation_line(events: list[dict[str, Any]]) -> str:
    if not events:
        return "本阶段没有收到参演熟人的消息；不能据此推测其他人都在做什么。"
    return "上一阶段熟人的行为与传话（不是全城统计）：\n" + "\n".join(
        f"#{e['from']} {e['name']}（{e['label']}，关系来源{e['source']}，渠道{e['channel']}）："
        f"{e['action']}，{e['detail']}；原话：{e['say']}"
        for e in events
    )
