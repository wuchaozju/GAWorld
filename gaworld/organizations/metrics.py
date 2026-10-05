"""Application distributions based on information frozen before each decision."""

from __future__ import annotations


def application_groups(applications):
    labels = {
        "age_band": ("under_35", "35_to_64", "65_plus", "unknown"),
        "gender": ("male", "female", "other", "unknown"),
        "employment": ("employed", "unemployed", "retired", "other", "unknown"),
    }

    def empty():
        return {
            "applications": 0,
            "eligible_applications": 0,
            "aid_paid_cents": 0,
            "paid_aid_applications": 0,
            "hires": 0,
            "rejections": 0,
            "waiting_days_sum": 0,
        }

    groups = {dimension: {label: empty() for label in values} for dimension, values in labels.items()}
    for application in applications:
        snapshot = application.get("frozen", {})
        age = snapshot.get("age")
        age_band = (
            "unknown" if age is None else "under_35" if age < 35 else "35_to_64" if age < 65 else "65_plus"
        )
        gender = snapshot.get("gender")
        gender = {
            "男": "male",
            "男性": "male",
            "male": "male",
            "女": "female",
            "女性": "female",
            "female": "female",
        }.get(str(gender).lower(), "other" if gender else "unknown")
        employment = snapshot.get("employment")
        employment = (
            employment
            if employment in {"employed", "unemployed", "retired"}
            else "other"
            if employment
            else "unknown"
        )
        for dimension, label in (("age_band", age_band), ("gender", gender), ("employment", employment)):
            row = groups[dimension][label]
            row["applications"] += 1
            row["eligible_applications"] += bool(application.get("eligible"))
            row["aid_paid_cents"] += application.get("paid_cents", 0) if application["kind"] == "aid" else 0
            row["paid_aid_applications"] += application["kind"] == "aid" and bool(
                application.get("paid_cents")
            )
            row["hires"] += application["status"] == "hired"
            row["rejections"] += application["status"] == "rejected"
            row["waiting_days_sum"] += application.get("waiting_days", 0)
    return groups
