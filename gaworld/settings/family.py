"""Family / household module defaults.

Marital-status shares are age-band x gender categorical distributions rather
than a single "married rate", because the four statuses drive different
household shapes: ``divorced`` and ``widowed`` with children produce
single-parent households, which a scalar rate cannot express.

Numbers are ballpark urban-China figures skewed slightly later than the
national census to match Hangzhou's young migrant profile. They are config,
not constants — override ``CONFIG["family"]`` for a different city or for
policy experiments (e.g. halve ``fertility.p_any_child`` to study low
fertility).
"""

from __future__ import annotations

from typing import Any


def family_settings() -> dict[str, Any]:
    return {
        "family": {
            "enabled": True,
            "output_dir": "output/family",
            # Per-agent families pinned by hand in Agent Studio. Read while
            # assigning, so a pinned family survives the re-assignment that
            # happens at the start of every run.
            "overrides_path": "data/family_overrides.json",
            # Deterministic household assignment; combined with the agent id
            # so a given agent keeps its family across runs of the same seed.
            "seed": 20260813,
            # --- Marital status: age band -> gender -> shares -------------
            # Bands are (min_age, max_age) inclusive; shares are normalised,
            # so they do not have to sum to exactly 1.0.
            "marital_status_bands": [
                {"age": [0, 17], "male": {"never": 1.0}, "female": {"never": 1.0}},
                {"age": [18, 24],
                 "male": {"never": 0.96, "married": 0.04},
                 "female": {"never": 0.91, "married": 0.09}},
                {"age": [25, 29],
                 "male": {"never": 0.52, "married": 0.46, "divorced": 0.02},
                 "female": {"never": 0.40, "married": 0.58, "divorced": 0.02}},
                {"age": [30, 34],
                 "male": {"never": 0.22, "married": 0.74, "divorced": 0.04},
                 "female": {"never": 0.14, "married": 0.82, "divorced": 0.04}},
                {"age": [35, 39],
                 "male": {"never": 0.12, "married": 0.83, "divorced": 0.05},
                 "female": {"never": 0.08, "married": 0.87, "divorced": 0.05}},
                {"age": [40, 49],
                 "male": {"never": 0.07, "married": 0.87, "divorced": 0.055, "widowed": 0.005},
                 "female": {"never": 0.05, "married": 0.88, "divorced": 0.06, "widowed": 0.01}},
                {"age": [50, 59],
                 "male": {"never": 0.04, "married": 0.89, "divorced": 0.06, "widowed": 0.01},
                 "female": {"never": 0.03, "married": 0.87, "divorced": 0.06, "widowed": 0.04}},
                {"age": [60, 200],
                 "male": {"never": 0.02, "married": 0.85, "divorced": 0.04, "widowed": 0.09},
                 "female": {"never": 0.02, "married": 0.72, "divorced": 0.04, "widowed": 0.22}},
            ],
            # Share of never-married adults in this age range living with a
            # partner (未婚同居) — becomes a `partner` tie, not a `spouse`.
            "cohabitation": {
                "age_min": 24,
                "age_max": 38,
                "share": 0.10,
            },
            # --- Pairing -------------------------------------------------
            # Same-sex pairing is not modelled; an agent who finds no match
            # falls back to an off-screen spouse rather than being forced
            # back into being single.
            "pairing": {
                # Prefer marrying two in-sim agents to each other; only fall
                # back to an off-screen spouse when no partner fits.
                "prefer_in_sim": True,
                # Share of the partnered agents that get an *in-sim* partner
                # rather than an off-screen one. Two agents drawn from a
                # 12M-person city are in reality almost never married to each
                # other, so this is an explicit modelling choice bought for
                # in-sim family interaction — not a demographic fact. Lower it
                # towards 0 for a demographically pure run.
                "in_sim_pair_share": 0.6,
                "max_age_gap": 8,
                # Husband older by this much on average when the spouse is
                # off-screen (in-sim pairs use the real ages).
                "spouse_age_gap_mean": 2.0,
                # Extra match score for two agents living in the same district.
                "same_district_bonus": 2.0,
            },
            # --- Children -------------------------------------------------
            "fertility": {
                # P(at least one child) given ever-married, by parent age band.
                "p_any_child": [
                    {"age": [0, 26], "p": 0.10},
                    {"age": [27, 31], "p": 0.45},
                    {"age": [32, 37], "p": 0.72},
                    {"age": [38, 49], "p": 0.86},
                    {"age": [50, 200], "p": 0.92},
                ],
                # Given at least one child, share with a second / third.
                "p_second_child": 0.32,
                "p_third_child": 0.04,
                # Parent age minus child age, sampled uniformly in this range.
                "parent_age_at_first_birth": [27, 34],
                # A child older than this has left home (still kin, not
                # co-resident, no childcare duty).
                "coresident_child_max_age": 22,
            },
            # --- Co-residence --------------------------------------------
            "coresidence": {
                # Never-married adults living with their parents, by hukou.
                # Migrants overwhelmingly do not.
                "with_parents_local": 0.42,
                "with_parents_migrant": 0.04,
                # Never-married adults not with parents / partner: shared rental
                # vs living alone.
                "shared_rental_share": 0.45,
                # Married couples with a co-resident grandparent (三代同堂),
                # more likely when there is a young child.
                "multigen_base": 0.16,
                "multigen_with_young_child": 0.34,
                "young_child_max_age": 6,
                # Elderly agents (this age and up) living with an adult child.
                "elder_with_child_age": 70,
                "elder_with_child_share": 0.35,
            },
            # --- Daily family duties (P1) ---------------------------------
            "duties": {
                "enabled": True,
                # Max duty hints injected into one day's planning context.
                "max_per_day": 3,
                # Childcare (school run, homework) applies below this age.
                "school_age_max": 15,
                "preschool_age_max": 6,
                # Elder care applies to co-resident parents at/above this age.
                "elder_care_age": 75,
            },
            # --- Household finance (P2) ------------------------------------
            "finance": {
                "enabled": True,
                # Share of each earner's daily income pooled into the
                # household account before personal spending.
                "pooling_rate": 0.65,
                # Monthly per-child cost (childcare, schooling, extras), CNY.
                "child_cost_monthly": 2200.0,
                "preschool_extra_monthly": 1500.0,
                # Monthly support sent to a non-co-resident elderly parent,
                # and the age at which a parent starts needing it.
                "elder_support_monthly": 900.0,
                "elder_support_min_age": 65,
                # Co-resident elders cost less in cash but still cost.
                "coresident_elder_monthly": 600.0,
                # Rent is shared: a co-resident adult pays this share of what
                # they would pay alone.
                "shared_rent_discount": 0.62,
                # A spouse with a cash buffer covers the other's shortfall
                # before either resorts to credit.
                "spouse_bailout_enabled": True,
                # econ_security nudge per day from having a second earner.
                "dual_income_security_bonus": 0.004,
                "sole_earner_stress": 0.003,
            },
            # --- Family events & contagion (P3) ----------------------------
            "events": {
                "enabled": True,
                # Per-household per-day probability of any family event.
                "daily_probability": 0.14,
                # Emotion / stress contagion between co-resident members,
                # applied per tick in `state.effects`.
                "contagion_enabled": True,
                "contagion_weight": 0.035,
                # Ties that are not co-resident (adult child in another city,
                # ex-spouse) still transmit, but weakly.
                "remote_contagion_weight": 0.008,
            },
        },
    }
