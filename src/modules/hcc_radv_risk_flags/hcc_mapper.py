from __future__ import annotations

import pandas as pd

# ---------------------------------------------------------------------------
# ICD-10 → CMS-HCC category mapping
# Source: CMS-HCC Risk Adjustment Model V24 / V28 crosswalk.
# This is a representative subset covering the HCC groupings most relevant
# to RADV audit targeting (high-RAF conditions, frequently miscoded codes,
# and DM+CHF / CHF+CKD combinations flagged in CMS 2019 RADV methods doc).
# Full crosswalk: cms.gov → Medicare Advantage → Risk Adjustment Data Validation
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# V24 / V28 coefficient delta reference table
# Source: CMS 2024 Announcement Table VIII-1 (V28 coefficients)
#         CMS 2020 Announcement Table VI-1 (V24 baseline)
# Delta = V24_coefficient - V28_coefficient
# Positive = V28 compresses this HCC relative to V24
# Negative = V28 rewards this HCC (e.g., CKD specificity for ESRD counties)
# NOTE: Illustrative coefficients derived from CMS directional documentation —
# precise per-HCC coefficients require CMS Announcement Table files.
# ---------------------------------------------------------------------------
HCC_V24_V28_COEFFICIENT_DELTA: dict[str, dict[str, object]] = {
    "HCC9": {
        "description": "Lung and Other Severe Cancers",
        "v24_coeff": 2.448, "v28_coeff": 2.448,
        "delta": 0.000, "direction": "neutral",
        "note": "Malignancies stable across V24/V28",
    },
    "HCC12": {
        "description": "Breast, Prostate, Colorectal Cancers",
        "v24_coeff": 0.670, "v28_coeff": 0.640,
        "delta": 0.030, "direction": "compression",
        "note": "Modest V28 compression for common cancers",
    },
    "HCC18": {
        "description": "Diabetes with Chronic Complications",
        "v24_coeff": 0.318, "v28_coeff": 0.240,
        "delta": 0.078, "direction": "compression",
        "note": "V28 constrains diabetic coefficients to prevent double-counting; Aged Dual impact",
    },
    "HCC19": {
        "description": "Diabetes without Complications",
        "v24_coeff": 0.118, "v28_coeff": 0.079,
        "delta": 0.039, "direction": "compression",
        "note": "Modest V28 compression",
    },
    "HCC52": {
        "description": "Dementia with or without Complications",
        "v24_coeff": 0.346, "v28_coeff": 0.298,
        "delta": 0.048, "direction": "compression",
        "note": "Moderate neurological compression in V28",
    },
    "HCC57": {
        "description": "Schizophrenia",
        "v24_coeff": 0.421, "v28_coeff": 0.310,
        "delta": 0.111, "direction": "compression",
        "note": "Significant psychiatric compression; Disabled enrollment type most affected",
    },
    "HCC59": {
        "description": "Major Depressive Disorder",
        "v24_coeff": 0.344, "v28_coeff": 0.255,
        "delta": 0.089, "direction": "compression",
        "note": "V28 downweights depression HCC; Disabled cluster primary impact",
    },
    "HCC85": {
        "description": "Congestive Heart Failure",
        "v24_coeff": 0.331, "v28_coeff": 0.272,
        "delta": 0.059, "direction": "compression",
        "note": "Moderate CHF compression; largest impact on CHF+CKD county combinations",
    },
    "HCC86": {
        "description": "Coronary Artery Disease",
        "v24_coeff": 0.288, "v28_coeff": 0.110,
        "delta": 0.178, "direction": "compression",
        "note": "LARGE V28 removal — CAD HCC significantly downweighted; Aged Non-Dual primary loser",
    },
    "HCC100": {
        "description": "Ischemic Stroke",
        "v24_coeff": 0.379, "v28_coeff": 0.340,
        "delta": 0.039, "direction": "compression",
        "note": "Modest stroke compression",
    },
    "HCC108": {
        "description": "Vascular Disease",
        "v24_coeff": 0.299, "v28_coeff": 0.079,
        "delta": 0.220, "direction": "compression",
        "note": "LARGEST V28 removal — vascular disease HCC substantially reduced; Aged Non-Dual most exposed",
    },
    "HCC111": {
        "description": "Chronic Obstructive Pulmonary Disease",
        "v24_coeff": 0.335, "v28_coeff": 0.265,
        "delta": 0.070, "direction": "compression",
        "note": "Moderate COPD compression across enrollment types",
    },
    "HCC134": {
        "description": "Dialysis Status",
        "v24_coeff": 0.539, "v28_coeff": 0.590,
        "delta": -0.051, "direction": "reward",
        "note": "V28 BENEFIT — dialysis status coefficient increased; ESRD counties gain under V28",
    },
    "HCC136": {
        "description": "Chronic Kidney Disease, Stage 4/5",
        "v24_coeff": 0.289, "v28_coeff": 0.378,
        "delta": -0.089, "direction": "reward",
        "note": "V28 BENEFIT — CKD Stage 4/5 specificity rewarded; ESRD counties with complete coding gain",
    },
    "HCC137": {
        "description": "Chronic Kidney Disease, Stage 3",
        "v24_coeff": 0.100, "v28_coeff": 0.143,
        "delta": -0.043, "direction": "reward",
        "note": "Modest V28 CKD Stage 3 reward; less than Stage 4/5",
    },
}

ICD10_TO_HCC: dict[str, tuple[str, str]] = {
    # Diabetes with complications
    "E1165": ("HCC18", "Diabetes with Chronic Complications"),
    "E1169": ("HCC18", "Diabetes with Chronic Complications"),
    "E1140": ("HCC18", "Diabetes with Chronic Complications"),
    "E1100": ("HCC19", "Diabetes without Complications"),
    "E1190": ("HCC19", "Diabetes without Complications"),
    # Congestive heart failure
    "I5020": ("HCC85", "Congestive Heart Failure"),
    "I5021": ("HCC85", "Congestive Heart Failure"),
    "I5022": ("HCC85", "Congestive Heart Failure"),
    "I5030": ("HCC85", "Congestive Heart Failure"),
    "I5031": ("HCC85", "Congestive Heart Failure"),
    "I5032": ("HCC85", "Congestive Heart Failure"),
    "I5040": ("HCC85", "Congestive Heart Failure"),
    "I5041": ("HCC85", "Congestive Heart Failure"),
    "I5042": ("HCC85", "Congestive Heart Failure"),
    # Chronic kidney disease
    "N183":  ("HCC137", "Chronic Kidney Disease, Stage 3"),
    "N184":  ("HCC136", "Chronic Kidney Disease, Stage 4"),
    "N185":  ("HCC136", "Chronic Kidney Disease, Stage 4"),
    "N186":  ("HCC136", "Chronic Kidney Disease, Stage 4"),
    # End-stage renal disease / dialysis
    "N189":  ("HCC136", "Chronic Kidney Disease, Stage 4"),
    "Z9911": ("HCC134", "Dialysis Status"),
    "Z992":  ("HCC134", "Dialysis Status"),
    # Vascular disease (downweighted in V28)
    "I2510": ("HCC86", "Coronary Artery Disease"),
    "I2590": ("HCC86", "Coronary Artery Disease"),
    "I739":  ("HCC108", "Vascular Disease"),
    "I7389": ("HCC108", "Vascular Disease"),
    # COPD / respiratory
    "J449":  ("HCC111", "Chronic Obstructive Pulmonary Disease"),
    "J441":  ("HCC111", "Chronic Obstructive Pulmonary Disease"),
    "J440":  ("HCC111", "Chronic Obstructive Pulmonary Disease"),
    # Malignancies
    "C509":  ("HCC12", "Breast Cancer"),
    "C189":  ("HCC12", "Colorectal Cancer"),
    "C61":   ("HCC12", "Prostate Cancer"),
    "C349":  ("HCC9",  "Lung Cancer"),
    # Major depression / psychiatric
    "F3290": ("HCC59", "Major Depressive Disorder"),
    "F3289": ("HCC59", "Major Depressive Disorder"),
    "F3110": ("HCC57", "Schizophrenia"),
    # Stroke / neurological
    "I63319":("HCC100", "Ischemic Stroke"),
    "I6350": ("HCC100", "Ischemic Stroke"),
    "G309":  ("HCC52",  "Dementia"),
    "G3184": ("HCC52",  "Dementia"),
}

# HCC → clinical grouping (for concentration index calculation)
HCC_TO_CATEGORY: dict[str, str] = {
    "HCC9":   "Malignancy",
    "HCC12":  "Malignancy",
    "HCC18":  "Diabetes — Complicated",
    "HCC19":  "Diabetes — Uncomplicated",
    "HCC52":  "Neurological — Dementia",
    "HCC57":  "Psychiatric — Psychosis",
    "HCC59":  "Psychiatric — Depression",
    "HCC85":  "Cardiovascular — CHF",
    "HCC86":  "Cardiovascular — CAD",
    "HCC100": "Neurological — Stroke",
    "HCC108": "Vascular",
    "HCC111": "Respiratory — COPD",
    "HCC134": "ESRD — Dialysis",
    "HCC136": "Renal — CKD Stage 4",
    "HCC137": "Renal — CKD Stage 3",
}

# RADV priority HCC pairs: co-occurrence is a RADV audit risk signal
RADV_PRIORITY_PAIRS: frozenset[frozenset[str]] = frozenset(
    {
        frozenset({"HCC18", "HCC85"}),   # Diabetes + CHF
        frozenset({"HCC85", "HCC136"}),  # CHF + CKD Stage 4
        frozenset({"HCC85", "HCC137"}),  # CHF + CKD Stage 3
        frozenset({"HCC18", "HCC136"}),  # Diabetes + CKD Stage 4
        frozenset({"HCC9",  "HCC85"}),   # Malignancy + CHF
        frozenset({"HCC52", "HCC59"}),   # Dementia + Depression
    }
)


def map_icd10_to_hcc(icd10_code: str) -> tuple[str, str] | None:
    """Return the (hcc_code, description) for an ICD-10 code, or None.

    Strips dots and uppercases the code to handle common formatting variants.
    """
    normalised = icd10_code.strip().upper().replace(".", "")
    return ICD10_TO_HCC.get(normalised)


def hcc_to_category(hcc_code: str) -> str:
    """Map an HCC code string to its clinical grouping label."""
    return HCC_TO_CATEGORY.get(hcc_code.strip().upper(), "Other")


def estimate_hcc_concentration_proxy(
    df: pd.DataFrame,
    score_col: str = "avg_risk_score",
    expense_col: str = "per_capita_exp",
    person_years_col: str = "person_years",
) -> pd.Series:
    """Estimate a county-level HCC concentration proxy from PUF summary statistics.

    When ICD-10 encounter-level data is unavailable the proxy uses risk score
    and expenditure deviation from the county mean, weighted by person-years
    volume to down-weight volatile small-N counties.

    Returns a float in [0, 1] — higher means more concentrated risk pattern.
    """
    if score_col not in df.columns or expense_col not in df.columns:
        return pd.Series(0.0, index=df.index)

    risk_norm = (df[score_col] - df[score_col].mean()) / (df[score_col].std(ddof=0) or 1)
    exp_norm = (df[expense_col] - df[expense_col].mean()) / (df[expense_col].std(ddof=0) or 1)

    # Person-years weight: log-scale so large counties don't dominate completely
    if person_years_col in df.columns:
        py = df[person_years_col].fillna(0).clip(lower=1)
        weight = py.apply(lambda x: min(1.0, (x ** 0.3) / (py.max() ** 0.3 + 1e-9)))
    else:
        weight = pd.Series(1.0, index=df.index)

    proxy = 0.5 + 0.30 * risk_norm.fillna(0) + 0.20 * exp_norm.fillna(0)
    proxy = (proxy * weight).clip(0.0, 1.0)
    return proxy
