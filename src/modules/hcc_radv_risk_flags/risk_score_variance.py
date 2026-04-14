from __future__ import annotations

import pandas as pd


def compute_risk_score_yoy_delta(
    df: pd.DataFrame,
    group_cols: tuple[str, ...] = ("state_id", "county_id", "enrollment_type"),
    score_col: str = "avg_risk_score",
    year_col: str = "year",
) -> pd.DataFrame:
    """Compute year-over-year change in average risk score for each county/enrollment group."""
    if score_col not in df.columns or year_col not in df.columns:
        raise ValueError("Required columns are missing for risk score variance calculation")

    df = df.copy()
    df[year_col] = df[year_col].astype(str)
    df = df.sort_values(list(group_cols) + [year_col])
    df["prev_risk_score"] = df.groupby(list(group_cols))[score_col].shift(1)
    df["risk_score_yoy_delta"] = (df[score_col] - df["prev_risk_score"]) / df["prev_risk_score"].replace({0: pd.NA})
    return df
