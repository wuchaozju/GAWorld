"""The Legislative Council's own record of its members.

Why this source exists alongside the search engines: for the eighth-term
roster, the open web is close to useless. Only 17 of the 90 members have a
usable Chinese Wikipedia article (8 substantial, 9 stubs), and the scraped
engines answer a query like "蘇紹聰 香港立法會議員 簡歷" with flash-game
portals and video sites. The Council publishes the same六 fields for every
member — constituency, party, occupation, qualifications, service period —
which is both authoritative (members supply it themselves) and uniform, so a
backbencher with no press coverage is documented exactly as well as the
President.

Two endpoints, both public:

``/bi/data/members/term-08/members-details.json``  the roster: name → LASS id
``app4…/mapi/tc/api/LASS/getMember?member_id=N``   one member's record

Everything is cached under ``output/legco/`` — ninety members is ninety
requests, and a re-run during authoring should not repeat them.

TLS note: ``www.legco.gov.hk`` serves its leaf certificate without the
intermediate, so every call here goes through :mod:`gaworld.io.legco_ca`,
which completes the chain rather than turning verification off.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import requests

from gaworld.io.legco_ca import bundle_path
from gaworld.logging_setup import get_logger

_LOG = get_logger("gaworld.io.legco_roster")

ROSTER_URL = "https://www.legco.gov.hk/bi/data/members/term-08/members-details.json"
MEMBER_URL = "https://app4.legco.gov.hk/mapi/tc/api/LASS/getMember?member_id={member_id}"

_CACHE = Path(__file__).resolve().parents[2] / "output" / "legco"

#: Monthly remuneration for the eighth term, from the Council's own
#: 《議員酬金及工作開支償還款額最高限額》 (立法會秘書處, 2026年1月). Stated as
#: a constant because it is a published schedule, not a per-person fact: the
#: tier follows from the office held, and the figure is what makes
#: "目前没有工资性收入" — the line every one of these residents used to carry —
#: demonstrably false.
REMUNERATION_HKD = {
    "president": 217_580,
    "deputy": 163_190,
    "member": 108_790,
    "exco_member": 72_530,
}
MEDICAL_ALLOWANCE_HKD = 37_890  # per year

#: HKD → CNY, for the one place the two have to meet: ``agents_loader`` reads
#: the income a profile states about itself, and the economy
#: (``settings.economy``, ``economy.finance``) denominates everything in CNY.
#: Writing the Council's HKD figure into a field the simulator treats as yuan
#: would overstate these residents' income by about 9%. The rate is an
#: approximation of the 2026 level and is stated here so a reader can see which
#: number was used and change it, rather than finding 108,790 in a profile and
#: having no way to tell which currency it is.
HKD_TO_CNY = 0.92


def monthly_income_cny(monthly_hkd: int) -> int:
    """The Council's monthly remuneration in the currency the economy uses."""
    return int(round(monthly_hkd * HKD_TO_CNY))

#: Traditional-character variants that differ between the city roster and the
#: Council's spelling of the same person. Kept explicit rather than solved with
#: a conversion library: it is a three-entry problem, and a converter would
#: silently merge two genuinely different members if one ever appeared.
NAME_ALIASES = {
    "伍煥傑": "伍煥杰",
    "李慧瓊": "李慧琼",
    "陳祖恆": "陳祖恒",
}


#: Hosts that serve ``*.legco.gov.hk`` certificates without the intermediate.
_LEGCO_HOSTS = ("www.legco.gov.hk", "legco.gov.hk", "app.legco.gov.hk", "app4.legco.gov.hk")


def install_ca_bundle() -> bool:
    """Teach :mod:`gaworld.io.http_guard` how to verify the LegCo hosts.

    Worth doing beyond this module's own calls: once the search facets start
    returning real Council press releases (they do, as soon as the relevance
    filter stops burying them), ``fetch_news_excerpt`` hits the same missing
    intermediate and drops the best evidence on the floor.
    """
    bundle = bundle_path()
    if bundle is None:
        return False
    from gaworld.io.http_guard import register_ca_bundle

    for host in _LEGCO_HOSTS:
        register_ca_bundle(host, bundle)
    return True


def _session_get(url: str, timeout: int = 30) -> requests.Response:
    bundle = bundle_path()
    if bundle is None:
        raise RuntimeError("legco CA bundle unavailable — cannot verify www.legco.gov.hk")
    response = requests.get(url, timeout=timeout, verify=bundle)
    response.raise_for_status()
    return response


def _cached(name: str, loader) -> Any:
    path = _CACHE / name
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    data = loader()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    return data


def roster(refresh: bool = False) -> dict[str, str]:
    """``{member name: LASS id}`` for the whole eighth-term Council."""
    if refresh:
        (_CACHE / "roster.json").unlink(missing_ok=True)

    def load() -> dict[str, str]:
        payload = _session_get(ROSTER_URL).json()
        rows = payload.get("Members") if isinstance(payload, dict) else payload
        out: dict[str, str] = {}
        for row in rows if isinstance(rows, list) else []:
            label = str(row.get("Name_TC") or "")
            match = re.match(r"^(.+?)議員", label)
            lass = str(row.get("LASS_ID") or "").strip()
            if match and lass:
                out[match.group(1).strip()] = lass
        _LOG.info("legco roster: %d members", len(out))
        return out

    return _cached("roster.json", load)


def member_record(member_id: str) -> dict[str, Any]:
    """One member's published record, cached."""

    def load() -> dict[str, Any]:
        payload = _session_get(MEMBER_URL.format(member_id=member_id)).json()
        return payload.get("data") or {}

    return _cached(f"member-{member_id}.json", load)


def _listed(value: Any) -> list[str]:
    items = value if isinstance(value, list) else [value]
    return [text for text in (str(i or "").strip() for i in items) if text and text != "-"]


def _salary_tier(record: dict[str, Any], name: str) -> tuple[str, int]:
    honour = f"{record.get('title') or ''}{record.get('salute_name') or ''}"
    if "主席" in honour or name in ("李慧琼", "李慧瓊"):
        return "立法會主席", REMUNERATION_HKD["president"]
    return "議員（非行政會議成員）", REMUNERATION_HKD["member"]


def brief_for(name: str) -> tuple[str, str] | None:
    """``(title, prose)`` describing *name*, or ``None`` if not a member.

    The prose is written for a model to read, not a page to render: labelled
    lines, no markup, and the remuneration spelled out in full so the
    distillation has an income figure to state instead of inferring one.
    """
    table = roster()
    key = name if name in table else NAME_ALIASES.get(name, "")
    if key not in table:
        _LOG.info("legco roster has no entry for %r", name)
        return None
    record = member_record(table[key])
    if not record:
        return None

    tier, monthly = _salary_tier(record, key)
    lines = [
        f"姓名：{record.get('name') or key}",
        f"身份：香港特別行政區第八屆立法會議員（任期自2026年1月1日起）",
        f"選舉組別：{record.get('constituency_type') or '未列'}"
        + (f"／{record.get('constituency')}" if record.get("constituency") else ""),
        f"所屬政治團體：{'、'.join(_listed(record.get('party'))) or '無黨派'}",
        f"職業：{'、'.join(_listed(record.get('occupation'))) or '未列'}",
        f"學歷及專業資格：{'；'.join(_listed(record.get('qualification'))) or '未列'}",
        f"公開帳號：{'、'.join(_listed(record.get('homepage'))) or '未列'}",
        f"酬金級別：{tier}",
        f"每月酬金：港幣 {monthly:,} 元（立法會秘書處《議員酬金及工作開支償還款額最高限額》，2026年1月）",
        f"醫療津貼：每年港幣 {MEDICAL_ALLOWANCE_HKD:,} 元；任滿酬金為任內酬金總額的 15%。",
        "議員設立法會綜合大樓辦事處及地區辦事處，須出席立法會會議、委員會會議並處理選區／界別事務。",
    ]
    return f"{record.get('name') or key} · 立法會議員資料（立法會官方網站）", "\n".join(lines)
