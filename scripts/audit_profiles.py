"""Check the shipped resident profiles for internal contradictions.

A profile card states a resident's age, job, income and household. Those
fields have to agree with each other: a fourteen-year-old student who reads
"与配偶及子女同住" is not a rich character, it is a broken generator — and
it makes the whole population look fabricated.

Run it after changing anything under ``gaworld/population`` or after
regenerating a city bundle::

    python scripts/audit_profiles.py                # every city
    python scripts/audit_profiles.py 拉斯维加斯        # one city

Exit code is 1 when any contradiction is found, so it can gate a commit.
"""

from __future__ import annotations

import csv
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CITY_DIR = ROOT / "data" / "cities"

BLOCK = re.compile(r"## Profile (\d+)｜(.+?)\n(.*?)(?=\n---)", re.S)
AGE = re.compile(r"\*\*基础信息\*\*：(.+?)，(\d+)岁")
JOB = re.compile(r"\*\*职业与工作节奏\*\*：(.+)")
EDU = re.compile(r"\*\*教育与收入背景\*\*：(.+?)(?:学历|，)")
SOCIAL = re.compile(r"\*\*社交网络情况\*\*：(.+?)。")

#: Household wording a minor can never be the subject of.
ADULT_ONLY = ("与配偶", "与子女", "与伴侣", "独居", "与室友合租")
#: Household wording a minor should always carry.
MINOR_SAYS = ("父母", "单亲家长", "家人")
TERTIARY = ("大专", "本科", "硕士及以上", "研究生", "大学")


def _rows(path: Path) -> dict[int, dict[str, str]]:
    if not path.exists():
        return {}
    with path.open(encoding="utf-8-sig") as fh:
        return {int(row["id"]): row for row in csv.DictReader(fh)}


def audit_city(city: Path) -> list[str]:
    """Every contradiction found in one city bundle."""
    md = city / "profiles.md"
    if not md.exists():
        return []
    rows = _rows(city / "agents.csv")
    problems: list[str] = []
    text = md.read_text(encoding="utf-8")

    for match in BLOCK.finditer(text):
        agent_id = int(match.group(1))
        body = match.group(3)
        age_match = AGE.search(body)
        if not age_match:
            problems.append(f"#{agent_id} {match.group(2)}：基础信息无法解析")
            continue
        gender, age = age_match.group(1), int(age_match.group(2))
        job = JOB.search(body)
        edu = EDU.search(body)
        social = SOCIAL.search(body)
        job_text = job.group(1).strip() if job else ""
        edu_text = edu.group(1).strip() if edu else ""
        social_text = social.group(1).strip() if social else ""
        row = rows.get(agent_id, {})
        employment = row.get("employment", "")
        income = (row.get("monthly_income") or "").strip()
        where = f"#{agent_id} {match.group(2)}（{gender} {age}岁）"

        if age <= 17:
            for label in ADULT_ONLY:
                if label in social_text:
                    problems.append(f"[未成年人套用成人家庭描述] {where}：{social_text}")
                    break
            if not any(word in social_text for word in MINOR_SAYS):
                problems.append(f"[未成年人未说明与谁同住] {where}：{social_text}")
            if job_text and job_text != "学生":
                problems.append(f"[未成年却有工作] {where}：职业={job_text}")
            if income and income != "0":
                problems.append(f"[未成年却有工资收入] {where}：收入={income}")
            if edu_text and edu_text in TERTIARY:
                problems.append(f"[未成年学历过高] {where}：{edu_text}")
        if job_text == "学生" and age >= 22:
            problems.append(f"[成年仍是学生] {where}")
        if age >= 65 and job_text == "学生":
            problems.append(f"[老人是学生] {where}")
        if employment == "employed" and income == "0":
            problems.append(f"[在职但无收入] {where}：职业={job_text}")
    return problems


def main(argv: list[str]) -> int:
    targets = argv[1:] or sorted(p.name for p in CITY_DIR.iterdir() if p.is_dir())
    total = 0
    for slug in targets:
        city = CITY_DIR / slug
        if not city.is_dir():
            print(f"{slug}: 找不到城市目录 {city}")
            total += 1
            continue
        problems = audit_city(city)
        if not problems:
            continue
        print(f"=== {slug}（{len(problems)} 处）")
        for problem in problems:
            print("  " + problem)
        total += len(problems)
    print(f"合计 {total} 处矛盾")
    return 1 if total else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
