from __future__ import annotations

import pandas as pd


def simulate_pa_metrics(
    df: pd.DataFrame,
    utilization_col: str = "specialty_utilization_rate",
    urgent_rate_col: str = "urgent_utilization_rate",
) -> pd.DataFrame:
    """Generate a synthetic prior authorization metric report using MSSP utilization proxies."""
    df = df.copy()
    if utilization_col not in df.columns:
        if "per_capita_exp" in df.columns:
            df[utilization_col] = df["per_capita_exp"].fillna(0) / df["per_capita_exp"].max() if df["per_capita_exp"].max() else 0
        else:
            raise ValueError(f"Missing required column: {utilization_col}")

    df["total_requests"] = (df[utilization_col].fillna(0) * 1000).round().astype(int)
    df["standard_requests"] = (df["total_requests"] * 0.88).round().astype(int)
    df["expedited_requests"] = (df[urgent_rate_col].fillna(0) * df["total_requests"]).round().astype(int) if urgent_rate_col in df.columns else 0
    df["approved_rate"] = 0.923 + (df[utilization_col].fillna(0) - df[utilization_col].mean()) * 0.05
    df["approved_rate"] = df["approved_rate"].clip(0.70, 0.99)
    df["denied_rate"] = 1 - df["approved_rate"]
    df["approved_requests"] = (df["total_requests"] * df["approved_rate"]).round().astype(int)
    df["denied_requests"] = df["total_requests"] - df["approved_requests"]
    df["appeal_overturn_rate"] = 0.82
    df["appeals_overturned"] = (df["denied_requests"] * df["appeal_overturn_rate"]).round().astype(int)
    df["extended_review_rate"] = (0.04 + (df[utilization_col].fillna(0) - df[utilization_col].mean()) * 0.01).clip(0.03, 0.10)
    df["extended_review_requests"] = (df["total_requests"] * df["extended_review_rate"]).round().astype(int)
    df["expedited_approved"] = (df["expedited_requests"] * 0.89).round().astype(int)
    df["expedited_denied"] = df["expedited_requests"] - df["expedited_approved"]

    return df[
        [
            "year",
            "state_id",
            "county_id",
            "enrollment_type",
            "total_requests",
            "standard_requests",
            "expedited_requests",
            "approved_requests",
            "denied_requests",
            "appeals_overturned",
            "extended_review_requests",
            "expedited_approved",
            "expedited_denied",
            "approved_rate",
            "denied_rate",
            "appeal_overturn_rate",
            "extended_review_rate",
        ]
    ]
