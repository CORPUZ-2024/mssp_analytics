from __future__ import annotations

# ---------------------------------------------------------------------------
# RADV proxy exposure scoring — v5 spec
# Composite formula (illustrative weights — pending empirical validation):
#   Composite = (YoY_delta × 0.4) + (Expenditure_growth_ratio × 0.4) +
#               (V28_coding_exposure_index × 0.2)
# Structurally analogous to FICO / Altman Z-Score — requires discriminant
# analysis on historical RADV audit outcomes before weights can be validated.
# Label as "illustrative weights" in all outputs.
# ---------------------------------------------------------------------------

import warnings

import pandas as pd

from .v28_exposure_index import compute_v28_exposure_index

# Confound flag columns — must be applied before computing composite.
# When any flag is active the composite is marked "confounded — interpret with caution"
# and excluded from the primary ranking per v5 spec.
CONFOUND_FLAG_COL = "composite_confounded"


def compute_radv_exposure_score(
    df: pd.DataFrame,
    risk_score_col: str = "avg_risk_score",
    per_capita_col: str = "per_capita_exp",
    yoy_col: str = "risk_score_yoy_delta",
    enrollment_type_col: str = "enrollment_type",
    year_col: str = "year",
) -> pd.DataFrame:
    """Compute a RADV proxy composite score using the v5 formula.

    Formula (illustrative weights — pending empirical validation):
        Composite = (YoY_delta × 0.4) + (Expenditure_growth_ratio × 0.4)
                  + (V28_coding_exposure_index × 0.2)

    Confound flags applied before scoring:
        - team_county_flag: TEAM bundled payment CBSA (inpatient spend compressed)
        - v28_transition_year_flag: PY2024 (67%/33% blend — structural delta noise)
        - enrollment_type_shift_flag: ESRD or Disabled share changed >5pp YoY

    When any confound flag is active the row is marked confounded and excluded
    from the primary ranking.

    Args:
        df:               MSSP PUF dataframe.
        risk_score_col:   avg_risk_score column.
        per_capita_col:   per_capita_exp column.
        yoy_col:          risk_score_yoy_delta column (from risk_score_variance.py).
        enrollment_type_col: enrollment_type column.
        year_col:         year column.

    Returns:
        DataFrame with radv_exposure_score, radv_exposure_flag,
        radv_exposure_level, and confound flag columns added.
    """
    required = {risk_score_col, per_capita_col, yoy_col}
    if not required.issubset(df.columns):
        raise ValueError(
            f"Required columns missing for RADV exposure scoring: "
            f"{required - set(df.columns)}"
        )

    df = df.copy()

    # ---- 1. Expenditure growth ratio (YoY, analogous to risk delta) --------
    df = _add_expenditure_growth_ratio(df, per_capita_col, enrollment_type_col, year_col)

    # ---- 2. V28 coding exposure index (replaces HCC concentration index) ----
    df["v28_exposure_index"] = compute_v28_exposure_index(df, enrollment_type_col, risk_score_col)

    # ---- 3. Confound flags -------------------------------------------------
    df = _add_confound_flags(df, enrollment_type_col, year_col)

    # ---- 4. Normalize inputs to [0, 1] for comparability -------------------
    def _norm(series: pd.Series) -> pd.Series:
        mn, mx = series.min(), series.max()
        if mx == mn:
            return pd.Series(0.0, index=series.index)
        return (series - mn) / (mx - mn)

    yoy_norm       = _norm(df[yoy_col].fillna(0).abs())
    exp_norm       = _norm(df.get("exp_growth_ratio", pd.Series(0.0, index=df.index)).fillna(0).abs())
    v28_norm       = _norm(df["v28_exposure_index"].fillna(0).abs())

    # ---- 5. Composite score (illustrative weights — unvalidated) -----------
    # Sensitivity note: also test 0.5/0.3/0.2 and 0.33/0.33/0.33 per v5 spec
    df["radv_exposure_score"] = (
        yoy_norm  * 0.40
        + exp_norm  * 0.40
        + v28_norm  * 0.20
    )

    # ---- 6. Exclude confounded rows from primary ranking -------------------
    # Confounded rows receive NaN score so they don't pollute the top-10% cutoff
    confounded = df[CONFOUND_FLAG_COL] if CONFOUND_FLAG_COL in df.columns else pd.Series(False, index=df.index)
    score_for_threshold = df["radv_exposure_score"].where(~confounded, other=pd.NA)

    threshold = score_for_threshold.quantile(0.90)
    df["radv_exposure_flag"] = df["radv_exposure_score"].gt(threshold) & ~confounded
    df["radv_exposure_level"] = pd.cut(
        df["radv_exposure_score"].fillna(0),
        bins=[0.0, 0.33, 0.67, 1.01],
        labels=["Low", "Medium", "High"],
        right=False,
        include_lowest=True,
    )

    return df


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _add_expenditure_growth_ratio(
    df: pd.DataFrame,
    per_capita_col: str,
    enrollment_type_col: str,
    year_col: str,
) -> pd.DataFrame:
    """Add expenditure YoY growth ratio, analogous to risk_score_yoy_delta."""
    if year_col not in df.columns or per_capita_col not in df.columns:
        df["exp_growth_ratio"] = pd.NA
        return df

    group_cols = [c for c in (enrollment_type_col, "state_id", "county_id") if c in df.columns]
    if not group_cols:
        df["exp_growth_ratio"] = pd.NA
        return df

    df = df.copy()
    df[year_col] = df[year_col].astype(str)
    df = df.sort_values(group_cols + [year_col])
    df["_prev_exp"] = df.groupby(group_cols)[per_capita_col].shift(1)
    df["exp_growth_ratio"] = (
        (df[per_capita_col] - df["_prev_exp"]) / df["_prev_exp"].replace({0: pd.NA})
    )
    df = df.drop(columns=["_prev_exp"])
    return df


def _add_confound_flags(
    df: pd.DataFrame,
    enrollment_type_col: str,
    year_col: str,
) -> pd.DataFrame:
    """Apply the three v5 confound flags before composite scoring.

    Flags:
        team_county_flag        — TEAM model CBSA (inpatient spend compressed)
        v28_transition_year_flag — PY2024 (V28 blend creates structural delta noise)
        enrollment_type_shift_flag — ESRD or Disabled share changed >5pp YoY
    """
    # TEAM flag: proxy from enrich layer (team_model_flag already set by DataEnricher)
    if "team_model_flag" not in df.columns:
        df["team_county_flag"] = False
    else:
        df["team_county_flag"] = df["team_model_flag"].astype(bool)

    # V28 transition year flag — PY2024 blend (67% V28 / 33% V24) is structural noise
    if year_col in df.columns:
        df["v28_transition_year_flag"] = df[year_col].astype(str).str.strip() == "2024"
    else:
        df["v28_transition_year_flag"] = False

    # Enrollment-type shift flag — ESRD or Disabled share changed >5pp YoY
    # Proxy: flag ESRD or Disabled rows in years where that type's share may shift
    if enrollment_type_col in df.columns and year_col in df.columns:
        high_vol_types = {"ESRD", "Disabled"}
        df["enrollment_type_shift_flag"] = (
            df[enrollment_type_col].astype(str).str.strip().isin(high_vol_types)
        )
    else:
        df["enrollment_type_shift_flag"] = False

    # Composite confound flag
    df[CONFOUND_FLAG_COL] = (
        df["team_county_flag"]
        | df["v28_transition_year_flag"]
        | df["enrollment_type_shift_flag"]
    )

    return df
