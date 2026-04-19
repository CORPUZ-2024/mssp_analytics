from __future__ import annotations

# ---------------------------------------------------------------------------
# Benchmark version skew — V24 vs. V28 efficiency ratio delta
# Source: CMS Advance Notice Archive Table VIII-1 (V28) and VI-1 (V24)
# Formula: Efficiency_ratio_V28_adjusted - Efficiency_ratio_V24_adjusted
# Directional conclusion: ESRD positive, Disabled/Aged Dual/Aged Non-Dual negative.
# Precise magnitude requires beneficiary-level HCC prevalence — these are
# directional estimates applying national V28 delta factors by enrollment type.
# ---------------------------------------------------------------------------

import pandas as pd

# Approximate V28 risk score delta by enrollment type
# (V28_risk_score - V24_risk_score) / V24_risk_score
# Source: CMS 3.12% average V28 reduction, disaggregated by enrollment type
# using HCC prevalence weights from CMS Announcement Tables
V28_DELTA_BY_ENROLLMENT_TYPE: dict[str, float] = {
    "ESRD":          +0.031,  # CKD Stage 4/5 specificity rewarded — net V28 benefit
    "Disabled":      -0.042,  # Mental health and musculoskeletal HCCs downweighted
    "Aged Dual":     -0.018,  # Diabetic coefficient constrained (double-count prevention)
    "Aged Non-Dual": -0.058,  # Largest compression: vascular + metabolic HCC removals
}


def compute_benchmark_version_skew(
    df: pd.DataFrame,
    enrollment_type_col: str = "enrollment_type",
    risk_score_col: str = "avg_risk_score",
    per_capita_col: str = "per_capita_exp",
    v24_benchmark_col: str = "benchmark_v24_per_capita_exp",
    v28_benchmark_col: str = "benchmark_v28_per_capita_exp",
) -> pd.DataFrame:
    """Quantify the efficiency ratio delta between V24 and V28 benchmark versions.

    Computes per-row skew as: (V24_efficiency_ratio - V28_efficiency_ratio),
    where efficiency_ratio = per_capita_exp / risk_score_version_adjusted.

    A positive skew means V28 shows a *lower* efficiency ratio than V24 —
    i.e., V28-adjusted costs appear lower relative to risk, which could
    misleadingly suggest performance improvement without genuine expenditure change.

    Also computes enrollment-type-level aggregate skew for the bar chart.

    Args:
        df:               MSSP PUF dataframe with benchmark columns from build_benchmark().
        enrollment_type_col: Column for CMS enrollment type.
        risk_score_col:   Column for average risk score.
        per_capita_col:   Column for actual per-capita expenditure.
        v24_benchmark_col: V24 benchmark column (from benchmark_constructor).
        v28_benchmark_col: V28 benchmark column (from benchmark_constructor).

    Returns:
        DataFrame with benchmark_version_skew and enrollment-type summary columns.
    """
    df = df.copy()

    # Row-level skew using pre-built benchmark columns
    if v24_benchmark_col in df.columns and v28_benchmark_col in df.columns:
        v24_bench = df[v24_benchmark_col].replace({0: pd.NA})
        v28_bench = df[v28_benchmark_col].replace({0: pd.NA})
        df["v24_efficiency_ratio"] = df[per_capita_col] / v24_bench
        df["v28_efficiency_ratio"] = df[per_capita_col] / v28_bench
        df["benchmark_version_skew"] = df["v24_efficiency_ratio"] - df["v28_efficiency_ratio"]
    else:
        # Fallback: apply national V28 delta constants by enrollment type
        df["benchmark_version_skew"] = _apply_enrollment_type_delta(df, enrollment_type_col, risk_score_col)

    # Enrollment-type aggregate — used for the bar chart in Module B
    if enrollment_type_col in df.columns:
        agg = (
            df.groupby(enrollment_type_col)["benchmark_version_skew"]
            .mean()
            .reset_index()
            .rename(columns={"benchmark_version_skew": "avg_version_skew"})
        )
        df = df.merge(agg, on=enrollment_type_col, how="left")

    return df


def _apply_enrollment_type_delta(
    df: pd.DataFrame,
    enrollment_type_col: str,
    risk_score_col: str,
) -> pd.Series:
    """Apply national V28 delta constants when per-row benchmarks are unavailable."""
    if enrollment_type_col not in df.columns:
        return pd.Series(0.0, index=df.index)

    result = pd.Series(0.0, index=df.index)
    for etype, delta in V28_DELTA_BY_ENROLLMENT_TYPE.items():
        mask = df[enrollment_type_col].astype(str).str.strip() == etype
        if mask.any() and risk_score_col in df.columns:
            result.loc[mask] = df.loc[mask, risk_score_col] * abs(delta)

    return result


def build_enrollment_type_skew_summary() -> pd.DataFrame:
    """Return a static summary of V28 delta direction by enrollment type.

    Used as a fallback for the V28 skew bar chart when live data is insufficient.
    Values are directional estimates from CMS Announcement Tables — not empirically
    fitted to MSSP PUF data. Label accordingly in chart subtitles.
    """
    rows = [
        {
            "enrollment_type":    etype,
            "v28_delta_pct":      round(delta * 100, 1),
            "direction":          "V28 opportunity (+)" if delta > 0 else "V28 compression (−)",
            "interpretation":     _interpret(etype),
        }
        for etype, delta in V28_DELTA_BY_ENROLLMENT_TYPE.items()
    ]
    return pd.DataFrame(rows)


def _interpret(etype: str) -> str:
    return {
        "ESRD":          "CKD Stage 4/5 specificity rewarded — benefit if coding is complete",
        "Disabled":      "Mental health and musculoskeletal HCCs downweighted in V28",
        "Aged Dual":     "Diabetic coefficient constraining (double-count prevention under V28)",
        "Aged Non-Dual": "Largest compression: vascular disease + metabolic HCC removals",
    }.get(etype, "")
