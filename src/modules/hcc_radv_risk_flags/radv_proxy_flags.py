from __future__ import annotations

import pandas as pd


def compute_radv_exposure_score(
    df: pd.DataFrame,
    risk_score_col: str = "avg_risk_score",
    per_capita_col: str = "per_capita_exp",
    yoy_col: str = "risk_score_yoy_delta",
    hcc_concentration_col: str = "hcc_concentration_index",
    efficiency_col: str = "expenditure_efficiency_ratio",
) -> pd.DataFrame:
    """Compute a proxy RADV exposure score from risk, cost, and concentration patterns."""
    required_columns = {risk_score_col, per_capita_col, yoy_col}
    if not required_columns.issubset(df.columns):
        raise ValueError("Required columns are missing for RADV exposure scoring")

    df = df.copy()
    df["risk_normalized"] = (df[risk_score_col] - df[risk_score_col].mean()) / df[risk_score_col].std(ddof=0)
    df["exp_normalized"] = (df[per_capita_col] - df[per_capita_col].mean()) / df[per_capita_col].std(ddof=0)
    df["efficiency_normalized"] = (
        (df[efficiency_col] - df[efficiency_col].mean()) / df[efficiency_col].std(ddof=0)
        if efficiency_col in df.columns
        else 0
    )
    df[hcc_concentration_col] = df.get(hcc_concentration_col, pd.Series(0.0, index=df.index)).fillna(0)

    df["radv_exposure_score"] = (
        df["risk_normalized"].fillna(0) * 0.30
        + df["exp_normalized"].fillna(0) * 0.20
        + df[yoy_col].fillna(0) * 0.20
        + df["efficiency_normalized"].fillna(0) * 0.15
        + df[hcc_concentration_col].fillna(0) * 0.15
    )
    threshold = df["radv_exposure_score"].quantile(0.90)
    df["radv_exposure_flag"] = df["radv_exposure_score"] > threshold
    df["radv_exposure_level"] = pd.cut(
        df["radv_exposure_score"].fillna(0),
        bins=[-float("inf"), threshold, float("inf")],
        labels=["normal", "high"],
    )
    return df
