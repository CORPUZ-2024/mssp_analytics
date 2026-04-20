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
    valid_group_cols = [c for c in group_cols if c in df.columns]
    df = df.sort_values(valid_group_cols + [year_col])
    df["prev_risk_score"] = df.groupby(valid_group_cols)[score_col].shift(1)
    df["risk_score_yoy_delta"] = (
        (df[score_col] - df["prev_risk_score"])
        / df["prev_risk_score"].replace({0: pd.NA})
    )
    return df


def compute_oc_stability(
    df: pd.DataFrame,
    group_cols: tuple[str, ...] = ("year", "state_id", "county_id", "enrollment_type"),
    score_col: str = "avg_risk_score",
    data_cut_col: str = "data_cut",
    oc1_label: str = "OC1",
    oc3_label: str = "OC3",
    stability_threshold: float = 0.02,
    high_risk_score_threshold: float | None = None,
) -> pd.DataFrame:
    """Flag counties where OC1→OC3 risk score delta is below threshold AND score is high.

    A county is flagged as OC-stable if:
        (AVG_RISK_SCORE_OC3 - AVG_RISK_SCORE_OC1) / AVG_RISK_SCORE_OC1 < stability_threshold
        AND AVG_RISK_SCORE_OC3 > 1 SD above national mean.

    This pattern — risk score already high at OC1 and unchanged by OC3 — is consistent
    with carry-forward or single-encounter coding (CMS RADV single-source HCC targeting).

    Requires data with a 'data_cut' column containing OC1 and OC3 rows for the same
    (year, state_id, county_id, enrollment_type) key. If OC vintages are absent,
    the column is set to NaN with a warning.

    Args:
        df:                        MSSP PUF dataframe with multiple data cuts.
        group_cols:                Key columns identifying a unique county/year/type.
        score_col:                 avg_risk_score column.
        data_cut_col:              data_cut column ('OC1', 'OC3', etc.).
        oc1_label:                 Label used for OC1 in data_cut_col.
        oc3_label:                 Label used for OC3 in data_cut_col.
        stability_threshold:       Max acceptable OC1→OC3 delta to be called stable.
        high_risk_score_threshold: If None, uses mean + 1 SD of OC3 scores.

    Returns:
        Original dataframe with 'oc_stability_flag' and 'oc_delta' columns added.
    """
    if data_cut_col not in df.columns:
        df = df.copy()
        df["oc_stability_flag"] = pd.NA
        df["oc_delta"] = pd.NA
        return df

    valid_group_cols = [c for c in group_cols if c in df.columns]

    oc1 = (
        df[df[data_cut_col].astype(str).str.upper() == oc1_label.upper()]
        .set_index(valid_group_cols)[score_col]
        .rename("oc1_score")
    )
    oc3 = (
        df[df[data_cut_col].astype(str).str.upper() == oc3_label.upper()]
        .set_index(valid_group_cols)[score_col]
        .rename("oc3_score")
    )

    if oc1.empty or oc3.empty:
        df = df.copy()
        df["oc_stability_flag"] = pd.NA
        df["oc_delta"] = pd.NA
        return df

    stability = oc1.to_frame().join(oc3, how="inner")
    stability["oc_delta"] = (
        (stability["oc3_score"] - stability["oc1_score"])
        / stability["oc1_score"].replace({0: pd.NA})
    )

    national_mean = stability["oc3_score"].mean()
    national_std  = stability["oc3_score"].std(ddof=0)
    threshold_score = (
        high_risk_score_threshold
        if high_risk_score_threshold is not None
        else national_mean + national_std
    )

    stability["oc_stability_flag"] = (
        stability["oc_delta"].abs() < stability_threshold
    ) & (stability["oc3_score"] > threshold_score)

    df = df.copy()
    df = df.merge(
        stability[["oc_delta", "oc_stability_flag"]].reset_index(),
        on=valid_group_cols,
        how="left",
        suffixes=("", "_oc"),
    )
    return df
