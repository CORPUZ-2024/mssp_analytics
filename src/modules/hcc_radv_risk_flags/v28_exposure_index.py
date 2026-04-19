from __future__ import annotations

# ---------------------------------------------------------------------------
# V28 coding exposure index
# Source: CMS 2024 Announcement Table VIII-1 (V28 coefficients)
#         CMS 2020 Announcement Table VI-1 (V24 baseline)
# Formula: sum_i( HCC_prevalence_weight_i * (V24_coefficient_i - V28_coefficient_i) )
#          normalized by county avg_risk_score
# Result:  estimated % of risk score exposed to V28 compression per enrollment type
# ---------------------------------------------------------------------------
# Illustrative weights — pending empirical validation against RADV audit outcome data.
# Directional estimates derived from CMS Advance Notice Archive Table VIII-1 (V28)
# and Table VI-1 (V24). Precise magnitude requires beneficiary-level HCC prevalence data.
# ---------------------------------------------------------------------------

import pandas as pd

# HCC coefficient delta: V24_coeff - V28_coeff (positive = V28 compresses this HCC)
# Negative delta means V28 rewards this HCC (e.g., CKD specificity for ESRD).
# Source: CMS 2024 Announcement Tables VIII-1 and VI-1
HCC_V28_DELTA: dict[str, float] = {
    # Diabetes — V28 added constraints on double-counting for Aged Dual
    "HCC18": 0.08,   # Diabetes w/ Chronic Complications — slight compression
    "HCC19": 0.04,   # Diabetes w/o Complications — modest compression
    # Cardiovascular / vascular — V28 removed / downweighted
    "HCC85": 0.06,   # Congestive Heart Failure — moderate compression
    "HCC86": 0.18,   # Coronary Artery Disease — significant V28 removal
    "HCC108": 0.22,  # Vascular Disease — large V28 removal (major V28 loser)
    # Renal — V28 rewards CKD specificity (negative = V28 benefit)
    "HCC134": -0.05, # Dialysis Status — V28 rewards, ESRD benefit
    "HCC136": -0.09, # CKD Stage 4/5 — V28 specificity reward (ESRD positive delta)
    "HCC137": -0.04, # CKD Stage 3 — modest V28 reward
    # Respiratory
    "HCC111": 0.07,  # COPD — modest compression
    # Malignancy — relatively stable across V24/V28
    "HCC9":  0.02,
    "HCC12": 0.03,
    # Neurological / psychiatric — mental health downweighted in V28 (Disabled impact)
    "HCC52": 0.05,   # Dementia
    "HCC57": 0.11,   # Schizophrenia — moderate compression (Disabled cluster)
    "HCC59": 0.09,   # Major Depressive Disorder — moderate compression (Disabled cluster)
    "HCC100": 0.04,  # Ischemic Stroke
}

# Enrollment-type HCC prevalence weights
# Approximate share of county risk score attributable to each HCC grouping
# by enrollment type. Derived from CMS MA Landscape and MSSP methodology docs.
# These are directional weights, not empirically fitted coefficients.
ENROLLMENT_HCC_WEIGHTS: dict[str, dict[str, float]] = {
    "ESRD": {
        "HCC134": 0.40,  # Dialysis Status — dominant for ESRD
        "HCC136": 0.30,  # CKD Stage 4/5 — high prevalence
        "HCC137": 0.10,  # CKD Stage 3
        "HCC85":  0.08,  # CHF comorbidity
        "HCC18":  0.05,  # Diabetes comorbidity
        "HCC108": 0.04,  # Vascular
        "HCC111": 0.03,  # COPD
    },
    "Disabled": {
        "HCC57":  0.18,  # Schizophrenia — elevated in Disabled
        "HCC59":  0.22,  # Major Depression — elevated in Disabled
        "HCC52":  0.10,  # Dementia
        "HCC108": 0.15,  # Vascular / musculoskeletal proxy
        "HCC85":  0.08,
        "HCC111": 0.10,
        "HCC18":  0.08,
        "HCC86":  0.09,
    },
    "Aged Dual": {
        "HCC18":  0.20,  # Diabetes — diabetic coefficient constrained in V28
        "HCC85":  0.15,  # CHF
        "HCC19":  0.10,  # Diabetes uncomplicated
        "HCC86":  0.12,  # CAD
        "HCC108": 0.13,  # Vascular
        "HCC111": 0.10,
        "HCC52":  0.08,
        "HCC59":  0.07,
        "HCC9":   0.05,
    },
    "Aged Non-Dual": {
        "HCC86":  0.20,  # CAD — major V28 loser
        "HCC108": 0.18,  # Vascular — largest V28 removal
        "HCC85":  0.12,
        "HCC18":  0.12,
        "HCC111": 0.10,
        "HCC19":  0.08,
        "HCC52":  0.08,
        "HCC9":   0.06,
        "HCC12":  0.06,
    },
}

# Expected V28 net delta direction by enrollment type (for validation)
# Negative = V28 compresses; Positive = V28 rewards
EXPECTED_V28_DIRECTION: dict[str, str] = {
    "ESRD":          "positive",   # CKD specificity rewarded
    "Disabled":      "negative",   # Mental health downweighted
    "Aged Dual":     "negative",   # Diabetic coefficient constrained
    "Aged Non-Dual": "negative",   # Largest compression: vascular + metabolic removals
}


def compute_v28_exposure_index(
    df: pd.DataFrame,
    enrollment_type_col: str = "enrollment_type",
    risk_score_col: str = "avg_risk_score",
) -> pd.Series:
    """Compute county-level V28 coding exposure index per enrollment type.

    Formula: weighted sum of (V24_coeff - V28_coeff) across HCC groupings
    for the county's enrollment type, normalized by avg_risk_score.

    A positive value = net V28 compression (risk score likely falls under V28).
    A negative value = net V28 benefit (risk score likely rises under V28 — ESRD/CKD).

    Illustrative weights — pending empirical validation against RADV audit outcome data.

    Args:
        df:                  MSSP PUF dataframe with enrollment_type and avg_risk_score.
        enrollment_type_col: Column identifying the CMS enrollment type.
        risk_score_col:      Column with average risk score.

    Returns:
        pd.Series of float — V28 coding exposure index per row.
    """
    if enrollment_type_col not in df.columns:
        return pd.Series(0.0, index=df.index)

    result = pd.Series(0.0, index=df.index)

    for etype, hcc_weights in ENROLLMENT_HCC_WEIGHTS.items():
        mask = df[enrollment_type_col].astype(str).str.strip() == etype
        if not mask.any():
            continue

        raw_score = sum(
            HCC_V28_DELTA.get(hcc, 0.0) * weight
            for hcc, weight in hcc_weights.items()
        )

        # Normalize by avg_risk_score — counties with higher RAF have larger absolute
        # exposure but lower relative exposure as a share of total score
        if risk_score_col in df.columns:
            national_avg = df.loc[mask, risk_score_col].mean()
            county_scores = df.loc[mask, risk_score_col].replace({0: national_avg})
            normalized = raw_score / county_scores.clip(lower=0.01)
        else:
            normalized = pd.Series(raw_score, index=df.index[mask])

        result.loc[mask] = normalized

    return result
