"""Governments and their policies, as pure functions over config.

A government is ``{"name", "description", "policies"}``. Its policies are
levers on rules the economy already runs (income tax, social insurance,
medical reimbursement, minimum wage) plus three transfers the public sector
pays itself (unemployment benefit, pension, basic income). Everything here is
deterministic and touches no simulation state, so the plugin and the
dashboard read the same answer.

The economy is always re-derived from the *base* economy config — the one the
run started with — rather than from whatever the previous government left, so
switching welfare → minimal → welfare lands exactly where the first welfare
term did.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

#: Insurance rates the scale applies to. The housing fund is the resident's
#: own savings, not a levy, so it stays out.
SCALED_SI_RATES = ("pension_rate", "medical_rate", "unemployment_rate")

#: Upper bound on a rate scale: at 2x the top bracket is 90%.
MAX_RATE_SCALE = 2.0

#: Transfer policy key -> (recipients, label shown to residents).
TRANSFERS: dict[str, tuple[str, str]] = {
    "unemployment_benefit_daily": ("unemployed", "失业救济"),
    "pension_daily": ("retired", "养老金"),
    "basic_income_daily": ("everyone", "基本收入"),
}


def _num(value: Any, default: float | None = None) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if number == number else default


def _clip(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def governments(config: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Every configured government, keyed by id."""
    section = config.get("public_sector") or {}
    table = section.get("governments") if isinstance(section, dict) else None
    return {str(k): v for k, v in (table or {}).items() if isinstance(v, dict)}


def resolve(config: dict[str, Any], government_id: str | None = None) -> tuple[str, dict[str, Any]]:
    """``(id, government)`` for ``government_id`` or the configured one.

    Raises ``KeyError`` for an id that is not configured: silently falling
    back to another government would run the wrong experiment.
    """
    section = config.get("public_sector") or {}
    gid = str(government_id or section.get("government") or "baseline")
    table = governments(config)
    if gid not in table:
        raise KeyError(gid)
    return gid, table[gid]


def policies_of(government: dict[str, Any]) -> dict[str, Any]:
    policies = government.get("policies")
    return policies if isinstance(policies, dict) else {}


def _scaled_brackets(brackets: list[Any], scale: float) -> list[list[float]]:
    # tax = taxable * rate - quick_deduction within each bracket, so scaling
    # rate and quick deduction together scales the tax owed by exactly `scale`.
    return [
        [upper, round(float(rate) * scale, 4), round(float(quick) * scale, 2)]
        for upper, rate, quick in brackets
    ]


def derive_economy(base_economy: dict[str, Any], policies: dict[str, Any]) -> dict[str, Any]:
    """The economy config a government's policies produce from ``base_economy``."""
    from gaworld.economy.finance import DEFAULT_ECONOMY_CONFIG

    economy = deepcopy(base_economy) if isinstance(base_economy, dict) else {}

    tax = economy.setdefault("tax", {})
    exemption = _num(policies.get("income_tax_exemption"))
    if exemption is not None:
        tax["monthly_exemption"] = max(0.0, exemption)
    tax_scale = _clip(_num(policies.get("income_tax_rate_scale"), 1.0) or 0.0, 0.0, MAX_RATE_SCALE)
    if tax_scale != 1.0:
        brackets = tax.get("brackets") or DEFAULT_ECONOMY_CONFIG["tax"]["brackets"]
        tax["brackets"] = _scaled_brackets(brackets, tax_scale)

    si = economy.setdefault("social_insurance", {})
    si_scale = _clip(_num(policies.get("social_insurance_rate_scale"), 1.0) or 0.0, 0.0, MAX_RATE_SCALE)
    if si_scale != 1.0:
        defaults = DEFAULT_ECONOMY_CONFIG["social_insurance"]
        for key in SCALED_SI_RATES:
            base = _num(si.get(key), _num(defaults.get(key), 0.0)) or 0.0
            si[key] = round(base * si_scale, 5)
    reimbursement = policies.get("medical_reimbursement")
    if isinstance(reimbursement, (list, tuple)) and len(reimbursement) == 2:
        low, high = (_num(v) for v in reimbursement)
        if low is not None and high is not None:
            low, high = sorted((_clip(low, 0.0, 1.0), _clip(high, 0.0, 1.0)))
            si["medical_reimbursement_range"] = [low, high]

    wage = _num(policies.get("min_hourly_wage"))
    if wage is not None:
        economy["min_hourly_income"] = max(0.0, wage)
    return economy


def transfer_amounts(policies: dict[str, Any]) -> dict[str, float]:
    """Daily amount per transfer policy, zero for the ones not paid."""
    return {key: max(0.0, _num(policies.get(key), 0.0) or 0.0) for key in TRANSFERS}


def _pct(value: float) -> str:
    return f"{value * 100:.0f}%"


def policy_lines(policies: dict[str, Any]) -> list[str]:
    """Plain-language statements of every policy that departs from neutral."""
    lines: list[str] = []
    exemption = _num(policies.get("income_tax_exemption"))
    if exemption is not None:
        lines.append(f"个税起征点 {exemption:.0f} 元/月")
    tax_scale = _num(policies.get("income_tax_rate_scale"), 1.0)
    if tax_scale is not None and tax_scale != 1.0:
        lines.append(f"个税税负为基准的 {_pct(tax_scale)}")
    si_scale = _num(policies.get("social_insurance_rate_scale"), 1.0)
    if si_scale is not None and si_scale != 1.0:
        lines.append(f"社保个人缴费为基准的 {_pct(si_scale)}")
    reimbursement = policies.get("medical_reimbursement")
    if isinstance(reimbursement, (list, tuple)) and len(reimbursement) == 2:
        low, high = (_num(v) for v in reimbursement)
        if low is not None and high is not None:
            lines.append(f"医保报销 {_pct(min(low, high))}–{_pct(max(low, high))}")
    wage = _num(policies.get("min_hourly_wage"))
    if wage is not None:
        lines.append(f"最低时薪 {wage:g} 元")
    for key, amount in transfer_amounts(policies).items():
        if amount > 0:
            lines.append(f"{TRANSFERS[key][1]} {amount:g} 元/天")
    return lines


def brief(government: dict[str, Any]) -> str:
    """One paragraph a resident reads: who governs, what they do, the rules."""
    name = str(government.get("name") or "本市政府")
    text = f"本市现任政府：{name}"
    description = str(government.get("description") or "").strip().rstrip("。.")
    if description:
        text += f"——{description}"
    lines = policy_lines(policies_of(government))
    if lines:
        text += "。现行政策：" + "；".join(lines)
    return text + "。"


def validate_config(config: dict[str, Any]) -> None:
    """Refuse to start a run whose government or schedule names nothing.

    Falling back to some other government would quietly run a different
    experiment from the one configured.
    """
    section = config.get("public_sector") or {}
    if not isinstance(section, dict) or not section.get("enabled", False):
        return
    table = governments(config)
    wanted = [str(section.get("government") or "baseline")]
    schedule = section.get("schedule") or []
    if not isinstance(schedule, list):
        raise ValueError("public_sector.schedule must be a list")
    for entry in schedule:
        if not isinstance(entry, dict) or "day" not in entry:
            raise ValueError("public_sector.schedule entries need a `day` and a `government`")
        wanted.append(str(entry.get("government") or ""))
    unknown = sorted({gid for gid in wanted if gid not in table})
    if unknown:
        raise ValueError(f"public_sector names unknown governments: {', '.join(unknown)}")


__all__ = [
    "TRANSFERS",
    "brief",
    "derive_economy",
    "governments",
    "policies_of",
    "policy_lines",
    "resolve",
    "transfer_amounts",
    "validate_config",
]
