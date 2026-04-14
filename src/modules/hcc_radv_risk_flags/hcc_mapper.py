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
