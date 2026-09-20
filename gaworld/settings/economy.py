"""Economy module defaults."""

from __future__ import annotations

from typing import Any


def economy_settings() -> dict[str, Any]:
    return {
        # Economy module – realistic personal finance with tax, social insurance,
        # Engel-coefficient spending, investment, and macro-economic cycles.
        "economy": {
            "enabled": True,
            "currency": "CNY",
            "output_dir": "output/economy",
            "hours_per_step": 1.0,
            "work_days_per_month": 22,
            "work_hours_per_day": 8,
            # --- Initial assets ---
            "initial_savings_months_min": 1.0,
            "initial_savings_months_max": 6.0,
            "inheritance_enabled": True,
            "inheritance_base_probability": 0.28,
            "inheritance_age_peak_low": 30,
            "inheritance_age_peak_high": 55,
            "inheritance_ratio_min": 0.25,
            "inheritance_ratio_max": 2.0,
            "inheritance_hukou_bonus": {
                "urban": 0.04,
                "city": 0.04,
                "town": 0.02,
                "rural": -0.03,
                "village": -0.03,
            },
            # --- Tax (China 2024 progressive individual income tax) ---
            "tax": {
                "enabled": True,
                "monthly_exemption": 5000.0,
                "default_special_deduction": 1500.0,
                "brackets": [
                    (3000, 0.03, 0),
                    (12000, 0.10, 210),
                    (25000, 0.20, 1410),
                    (35000, 0.25, 2660),
                    (55000, 0.30, 4410),
                    (80000, 0.35, 7160),
                    (float("inf"), 0.45, 15160),
                ],
            },
            # --- Social insurance (individual contribution rates) ---
            "social_insurance": {
                "enabled": True,
                "pension_rate": 0.08,
                "medical_rate": 0.02,
                "unemployment_rate": 0.005,
                "work_injury_rate": 0.0,
                "maternity_rate": 0.0,
                "housing_fund_rate": 0.08,
                "housing_fund_employer_rate": 0.08,
                "base_cap": 36000.0,
                "base_floor": 4462.0,
            },
            # --- Spending (Engel coefficient curve) ---
            "spending": {
                "engel_curve": [
                    (4000, 0.48, 0.05),
                    (7000, 0.38, 0.15),
                    (12000, 0.30, 0.25),
                    (20000, 0.22, 0.32),
                    (float("inf"), 0.15, 0.40),
                ],
                "budget_template": {
                    "food": 0.30,
                    "housing": 0.25,
                    "transport": 0.10,
                    "clothing": 0.06,
                    "leisure": 0.10,
                    "education": 0.08,
                    "healthcare": 0.06,
                    "misc": 0.05,
                },
                "income_elasticity": {
                    "food": 0.5,
                    "housing": 0.8,
                    "transport": 0.7,
                    "clothing": 1.2,
                    "leisure": 1.5,
                    "education": 1.1,
                    "healthcare": 0.6,
                    "misc": 1.0,
                },
                "daily_variance": 0.25,
            },
            # --- Investment & savings ---
            "investment": {
                "enabled": True,
                "asset_returns": {
                    "deposits": (0.025, 0.005),
                    "funds": (0.06, 0.08),
                    "stocks": (0.08, 0.22),
                },
                "portfolio_profiles": {
                    "conservative": {"deposits": 0.70, "funds": 0.25, "stocks": 0.05},
                    "moderate": {"deposits": 0.40, "funds": 0.40, "stocks": 0.20},
                    "aggressive": {"deposits": 0.15, "funds": 0.35, "stocks": 0.50},
                },
                "auto_save_enabled": True,
                "checking_buffer_months": 2.0,
                "market_correlation": 0.7,
            },
            # --- Credit & cash constraint ---
            "credit": {
                "enabled": True,
                "credit_limit_months": 2.0,
                "annual_interest_rate": 0.18,
                "hardship_liquidity_months": 1.0,
                "min_spend_factor": 0.25,
            },
            # --- Macro-economic cycle ---
            "macro": {
                "enabled": True,
                "initial_inflation_rate": 0.025,
                "initial_unemployment_rate": 0.052,
                "cycle_phase_duration_days": (60, 180),
                "phases": ["expansion", "peak", "contraction", "trough"],
                "phase_effects": {
                    "expansion": {
                        "income_mult": 1.05,
                        "expense_mult": 1.02,
                        "layoff_risk": 0.002,
                        "raise_chance": 0.03,
                    },
                    "peak": {
                        "income_mult": 1.08,
                        "expense_mult": 1.06,
                        "layoff_risk": 0.005,
                        "raise_chance": 0.02,
                    },
                    "contraction": {
                        "income_mult": 0.95,
                        "expense_mult": 1.04,
                        "layoff_risk": 0.015,
                        "raise_chance": 0.005,
                    },
                    "trough": {
                        "income_mult": 0.90,
                        "expense_mult": 0.98,
                        "layoff_risk": 0.025,
                        "raise_chance": 0.002,
                    },
                },
                "industry_conditions": {
                    "tech": 1.0,
                    "finance": 1.0,
                    "medical": 1.0,
                    "education": 1.0,
                    "service": 1.0,
                    "trade": 1.0,
                    "default": 1.0,
                },
            },
            # --- Shock events ---
            "shocks": {
                "enabled": True,
                "layoff_base_prob": 0.001,
                "raise_base_prob": 0.008,
                "medical_emergency_prob": 0.0005,
                "medical_cost_range": (2000.0, 50000.0),
                "year_end_bonus_enabled": True,
                "year_end_bonus_months": 1.0,
            },
            # --- Payment routing to agents (P3) ---
            "routing": {
                "enabled": True,
                "merchant_labor_share": 0.35,
                "landlord_share": 1.0,
                "landlord_keywords": ["房东", "包租", "出租"],
            },
            # --- Friend loans over the social network (P3) ---
            "friend_loans": {
                "enabled": True,
                "max_outstanding_months": 1.0,
                "lender_buffer_months": 2.0,
                "willingness_factor": 0.5,
            },
            # --- Sector pools (closed-loop money flows) ---
            "sectors": {
                "initial_firms_balance": 0.0,
                "initial_government_balance": 0.0,
                "initial_bank_balance": 0.0,
            },
            # --- Backward-compat behavior triggers ---
            "rent_income_ratio": 0.22,
            "daily_utilities_cost": 12.0,
            "base_living_cost_per_hour": 6.0,
            "min_hourly_income": 8.0,
            "income_volatility": 0.25,
            "target_work_hours_per_day": 7.0,
            "asset_safety_days": 18.0,
            "income_seek_threshold": 0.56,
            "income_seek_probability_scale": 0.9,
            "income_seek_activities": ["工作", "兼职", "接单", "技能提升"],
            "expense_ranges": {
                "food": [8.0, 26.0],
                "clothing": [18.0, 120.0],
                "transport": [3.0, 28.0],
                "housing": [0.0, 0.0],
                "leisure": [8.0, 70.0],
                "education": [10.0, 60.0],
                "healthcare": [12.0, 90.0],
                "misc": [4.0, 22.0],
            },
        },
    }
