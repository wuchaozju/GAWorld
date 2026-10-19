"""Public sector defaults: which government runs the city, and its policies."""

from __future__ import annotations

from typing import Any


def _policies(**overrides: Any) -> dict[str, Any]:
    # Neutral values: a lever left here changes nothing about the economy.
    policies: dict[str, Any] = {
        "income_tax_exemption": None,
        "income_tax_rate_scale": 1.0,
        "social_insurance_rate_scale": 1.0,
        "medical_reimbursement": None,
        "min_hourly_wage": None,
        "unemployment_benefit_daily": 0.0,
        "pension_daily": 0.0,
        "basic_income_daily": 0.0,
    }
    policies.update(overrides)
    return policies


def public_sector_settings() -> dict[str, Any]:
    return {
        # Public sector: the government in office and the policies it runs.
        # Off by default; while off nothing here touches a run.
        "public_sector": {
            "enabled": False,
            # Key into `governments` below.
            "government": "baseline",
            # Each resident's first perception of the day carries a one-line
            # brief of the government and the policies that touch them.
            "announce": True,
            # Changes of government during a run: [{"day": 30, "government":
            # "welfare", "note": "换届"}]. Applied at that day's start.
            "schedule": [],
            "governments": {
                "baseline": {
                    "name": "现行体制",
                    "description": "沿用经济系统里的税率、社保和最低时薪，不额外发放任何补贴。",
                    "policies": _policies(),
                },
                "welfare": {
                    "name": "福利型政府",
                    "description": "高税收、高福利：提高起征点和报销比例，给失业者和老人按天发钱，钱来自更高的税和社保。",
                    "policies": _policies(
                        income_tax_exemption=6000.0,
                        income_tax_rate_scale=1.3,
                        social_insurance_rate_scale=1.2,
                        medical_reimbursement=[0.70, 0.95],
                        min_hourly_wage=12.0,
                        unemployment_benefit_daily=80.0,
                        pension_daily=120.0,
                    ),
                },
                "minimal": {
                    "name": "小政府",
                    "description": "低税负、少干预：税和社保都减，医保报销少，不设失业救济和养老金，市场自己解决。",
                    "policies": _policies(
                        income_tax_exemption=5000.0,
                        income_tax_rate_scale=0.6,
                        social_insurance_rate_scale=0.6,
                        medical_reimbursement=[0.20, 0.50],
                        min_hourly_wage=5.0,
                    ),
                },
                "developmental": {
                    "name": "发展型政府",
                    "description": "稳就业、保底线：税负不变，最低时薪上调，失业有救济、老人有基本养老金。",
                    "policies": _policies(
                        min_hourly_wage=10.0,
                        unemployment_benefit_daily=40.0,
                        pension_daily=60.0,
                    ),
                },
                "austerity": {
                    "name": "紧缩型政府",
                    "description": "财政吃紧：加税、提社保缴费，压低报销比例，救济和养老金只保最低水平。",
                    "policies": _policies(
                        income_tax_exemption=4000.0,
                        income_tax_rate_scale=1.15,
                        social_insurance_rate_scale=1.1,
                        medical_reimbursement=[0.40, 0.70],
                        unemployment_benefit_daily=20.0,
                        pension_daily=50.0,
                    ),
                },
                "basic_income": {
                    "name": "基本收入试点",
                    "description": "每位居民每天无条件领一笔基本收入，用更高的所得税来付。",
                    "policies": _policies(
                        income_tax_rate_scale=1.4,
                        basic_income_daily=50.0,
                    ),
                },
            },
        },
    }
