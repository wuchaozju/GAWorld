"""Preview and append fictional tertiary students to the request's active world."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from gaworld.accounts import ownership
from gaworld.apps import residents, world_paths
from gaworld.population.locale import compose_name, normalize_locale
from gaworld.population.synth import derive_rng

STAGES = {
    "大专": (18, 21, "高中/中专"),
    "本科": (18, 22, "高中/中专"),
    "硕士": (22, 26, "本科"),
    "博士": (25, 30, "硕士及以上"),
}


def preview(payload: dict[str, Any]) -> dict[str, Any]:
    count = int(payload.get("count", 30))
    seed = int(payload.get("seed", 42))
    stage = str(payload.get("student_status") or "本科")
    if not 1 <= count <= 200 or not 0 <= seed <= 2**31 - 1 or stage not in STAGES:
        raise ValueError("人数应为 1–200，种子为非负整数，在读阶段应为大专、本科、硕士或博士")
    low, high, degree = STAGES[stage]
    rng = derive_rng(seed, "student_append")
    csv_path, md_path = Path(world_paths.state_csv_path()), Path(world_paths.profile_path())
    if not csv_path.exists() or not md_path.exists():
        raise ValueError("当前世界缺少人口文件，无法追加")
    locale_path = csv_path.parent / "locale.json"
    locale_data = json.loads(locale_path.read_text()) if locale_path.exists() else {}
    snapshot = [
        str(csv_path.resolve()),
        str(md_path.resolve()),
        csv_path.read_bytes().hex(),
        md_path.read_bytes().hex(),
        locale_data,
    ]
    token = hashlib.sha256(
        json.dumps([snapshot, count, seed, stage], ensure_ascii=False).encode()
    ).hexdigest()
    _, rows = residents.read_state_rows()
    next_id = max((residents.row_id(row) or 0 for row in rows), default=0) + 1
    names = {str(row.get("name") or "") for row in rows}
    locale = normalize_locale(locale_data)
    people = []
    for index in range(count):
        gender = "男" if rng.random() < 0.5 else "女"
        name = compose_name(locale, gender == "男", rng)
        for _attempt in range(1000):
            if name not in names:
                break
            name = compose_name(locale, gender == "男", rng)
        else:
            name = f"{name}{next_id + index}"
        names.add(name)
        job = f"{stage}学生" if stage in ("大专", "本科") else f"{stage}研究生（学生）"
        people.append(
            {
                "id": next_id + index,
                "name": name,
                "gender": gender,
                "age": int(rng.integers(low, high + 1)),
                "education": degree,
                "student_status": stage,
                "job": job,
                "hukou": "未知",
                "residence": "校园宿舍",
                "employment": "not_in_labor_force",
                "industry": "none",
                "monthly_income": 0,
                "education_income": f"{degree}学历，目前没有工资性收入，生活费来源未设定。",
                "daily_life": "日常围绕课程、自习、校园活动和同学交往安排。",
                "personality": "由独立种子设置初始状态，个人经历和偏好尚待补充。",
                "state": {key: round(float(rng.uniform(0.3, 0.7)), 2) for key in residents.STATE_VAR_KEYS},
            }
        )
    return {
        "count": count,
        "seed": seed,
        "student_status": stage,
        "people": people,
        "preview_token": token,
        "note": "虚构的补充研究样本，不代表所在城市的真实在校生比例；不会改写已有居民或实验记录。",
    }


def append(payload: dict[str, Any]) -> dict[str, Any]:
    with residents.SEED_LOCK:
        proposed = preview(payload)
        if payload.get("preview_token") != proposed["preview_token"]:
            raise ValueError("人口或配置已变化，请重新预览后再追加")
        paths = [Path(world_paths.state_csv_path()), Path(world_paths.profile_path())]
        original = [path.read_bytes() for path in paths]
        try:
            created = [residents.create_agent(person) for person in proposed["people"]]
        except Exception:
            for path, content in zip(paths, original, strict=True):
                path.write_bytes(content)
            raise
        return {"count": len(created), "agent_ids": [p["id"] for p in created], **ownership.stamp()}


def handle_post(path: str, payload: dict[str, Any]) -> tuple[dict[str, Any], int]:
    try:
        if path == "/api/population/students/preview":
            with residents.SEED_LOCK:
                return preview(payload), 200
        if path == "/api/population/students/append":
            return append(payload), 200
    except (TypeError, ValueError, OSError) as exc:
        return {"error": str(exc)}, 400
    return {"error": "Unknown endpoint"}, 404
