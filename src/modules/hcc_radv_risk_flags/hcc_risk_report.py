from __future__ import annotations

import pandas as pd

from .hcc_mapper import estimate_hcc_concentration_proxy
from .radv_proxy_flags import compute_radv_exposure_score
from .risk_score_variance import compute_oc_stability, compute_risk_score_yoy_delta
from .v28_exposure_index import compute_v28_exposure_index


def build_hcc_risk_flag_summary(
    df: pd.DataFrame,
    top_n: int = 25,
) -> pd.DataFrame:
    """Produce a ranked table of county-level RADV-style risk exposure indicators.

    Uses year-over-year risk score changes, expenditure efficiency, V28 coding
    exposure index (replacing HCC concentration index), OC-cut stability, and
    confound flags to approximate counties with RADV exposure patterns.

    V5 changes:
    - HCC concentration index replaced with V28 coding exposure index
    - Composite formula: (YoY delta × 0.4) + (Exp growth ratio × 0.4) + (V28 index × 0.2)
    - Three confound flags added: TEAM county, V28 transition year, enrollment type shift
    - OC stability added via compute_oc_stability()
    """
    df = df.copy()

    # ---- YoY risk score delta ---------------------------------------------
    df = compute_risk_score_yoy_delta(df)

    # ---- V28 coding exposure index (replaces HCC concentration index) -----
    if "v28_exposure_index" not in df.columns:
        df["v28_exposure_index"] = compute_v28_exposure_index(df)

    # ---- Expenditure efficiency ratio -------------------------------------
    if "expenditure_efficiency_ratio" not in df.columns and "avg_risk_score" in df.columns:
        df["expenditure_efficiency_ratio"] = (
            df["per_capita_exp"] / df["avg_risk_score"].replace({0: pd.NA})
        )

    # ---- RADV composite score (v5 formula) --------------------------------
    df = compute_radv_exposure_score(df)

    # ---- OC-cut stability -------------------------------------------------
    df = compute_oc_stability(df)

    # ---- Efficiency outlier flag ------------------------------------------
    df["efficiency_outlier_flag"] = False
    if "expenditure_efficiency_ratio" in df.columns:
        eff_mean = df["expenditure_efficiency_ratio"].mean()
        eff_std  = df["expenditure_efficiency_ratio"].std(ddof=0)
        df["efficiency_outlier_flag"] = (
            df["expenditure_efficiency_ratio"] > eff_mean + eff_std
        )

    summary_columns = [
        "year",
        "state_id",
        "state_name",
        "county_id",
        "county_name",
        "enrollment_type",
        "avg_risk_score",
        "person_years",
        "risk_score_yoy_delta",
        "per_capita_exp",
        "exp_growth_ratio",
        "expenditure_efficiency_ratio",
        "v28_exposure_index",
        "oc_stability_flag",
        "oc_delta",
        "efficiency_outlier_flag",
        "radv_exposure_score",
        "radv_exposure_flag",
        "radv_exposure_level",
        "composite_confounded",
        "team_county_flag",
        "v28_transition_year_flag",
        "enrollment_type_shift_flag",
    ]
    summary_columns = [col for col in summary_columns if col in df.columns]

    sort_by = [c for c in ("radv_exposure_score", "risk_score_yoy_delta") if c in df.columns]
    summary = df.sort_values(by=sort_by, ascending=False)
    return summary.loc[:, summary_columns].head(top_n)
