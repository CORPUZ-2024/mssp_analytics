from __future__ import annotations

import pandas as pd


def build_benchmark(
    df: pd.DataFrame,
    trend_factor: float = 1.02,
    risk_score_col: str = "avg_risk_score",
    per_capita_col: str = "per_capita_exp",
    version_factors: dict[str, float] | None = None,
) -> pd.DataFrame:
    """Build a simplified MSSP-style benchmark estimate for each county/enrollment group."""
    if risk_score_col not in df.columns or per_capita_col not in df.columns:
        raise ValueError("Required columns are missing for benchmark construction")

    if version_factors is None:
        version_factors = {"v24": 1.03, "v28": 0.97}

    df = df.copy()
    national_avg_risk = df[risk_score_col].mean()
    for version, factor in version_factors.items():
        column_name = f"benchmark_{version}_per_capita_exp"
        df[column_name] = (
            df[per_capita_col].fillna(0)
            * trend_factor
            * factor
            * (df[risk_score_col].fillna(national_avg_risk) / national_avg_risk)
        )

    df["benchmark_per_capita_exp"] = df["benchmark_v28_per_capita_exp"]
    return df
