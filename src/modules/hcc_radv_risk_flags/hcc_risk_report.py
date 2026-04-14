from __future__ import annotations

import pandas as pd

from .hcc_mapper import estimate_hcc_concentration_proxy
from .radv_proxy_flags import compute_radv_exposure_score
from .risk_score_variance import compute_risk_score_yoy_delta


def build_hcc_risk_flag_summary(
    df: pd.DataFrame,
    top_n: int = 25,
) -> pd.DataFrame:
    """Produce a ranked table of county-level RADV-style risk exposure indicators.

    This helper uses year-over-year risk score changes, expenditure efficiency, and
    a proxy HCC concentration signal to approximate counties with RADV exposure patterns.
    """
    df = df.copy()
    df = compute_risk_score_yoy_delta(df)
    if "hcc_concentration_index" not in df.columns:
        df["hcc_concentration_index"] = estimate_hcc_concentration_proxy(df)

    if "expenditure_efficiency_ratio" not in df.columns and "avg_risk_score" in df.columns:
        df["expenditure_efficiency_ratio"] = (
            df["per_capita_exp"] / df["avg_risk_score"].replace({0: pd.NA})
        )

    if "radv_exposure_score" not in df.columns:
        df = compute_radv_exposure_score(df)

    df["efficiency_outlier_flag"] = False
    if "expenditure_efficiency_ratio" in df.columns:
        efficiency_mean = df["expenditure_efficiency_ratio"].mean()
        efficiency_std = df["expenditure_efficiency_ratio"].std(ddof=0)
        df["efficiency_outlier_flag"] = (
            df["expenditure_efficiency_ratio"] > efficiency_mean + efficiency_std
        )

    if "data_cut" in df.columns:
        data_cut_counts = (
            df.groupby(["year", "state_id", "county_id", "enrollment_type"])["data_cut"]
            .nunique()
            .rename("distinct_data_cuts")
        )
        df = df.merge(data_cut_counts, on=["year", "state_id", "county_id", "enrollment_type"], how="left")
        df["single_source_hcc_proxy_flag"] = df["distinct_data_cuts"].fillna(0) < 3

    summary_columns = [
        "year",
        "state_id",
        "county_id",
        "enrollment_type",
        "avg_risk_score",
        "risk_score_yoy_delta",
        "per_capita_exp",
        "expenditure_efficiency_ratio",
        "hcc_concentration_index",
        "efficiency_outlier_flag",
        "single_source_hcc_proxy_flag",
        "radv_exposure_score",
        "radv_exposure_flag",
    ]
    summary_columns = [col for col in summary_columns if col in df.columns]
    summary = df.sort_values(
        by=[col for col in ["radv_exposure_score", "risk_score_yoy_delta"] if col in df.columns],
        ascending=False,
    )
    return summary.loc[:, summary_columns].head(top_n)
