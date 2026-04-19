from __future__ import annotations

import pandas as pd


def simulate_pa_metrics(
    df: pd.DataFrame,
    utilization_col: str = "specialty_utilization_rate",
    urgent_rate_col: str = "urgent_utilization_rate",
) -> pd.DataFrame:
    """Generate a synthetic prior authorization metric report using MSSP utilization proxies.

    Source type annotations (per v5 / CMS-0057-F schema):
        derived   — computed from MSSP PUF proxy columns (weak proxy; see schema notes)
        external  — national benchmark constant from literature (KFF, CMS FFS stats)
        constant  — CMS regulatory parameter
        simulated — modeled estimate with no direct data source

    CRITICAL implementation notes:
        - Field 4 (appeal overturn rate) denominator = denied_requests, NOT total.
          Dividing by total understates the rate by ~12x.
        - Fields 2+3 must sum to exactly 100% (enforced via _enforce_sum).
        - Fields 6+7 must sum to exactly 100% (enforced via _enforce_sum).
        - Field 5 (extended review) has no public benchmark — label as 'assumed constant'.
    """
    df = df.copy()
    if utilization_col not in df.columns:
        if "per_capita_exp" in df.columns:
            max_exp = df["per_capita_exp"].max()
            df[utilization_col] = (
                df["per_capita_exp"].fillna(0) / max_exp if max_exp else 0.1
            )
        else:
            raise ValueError(f"Missing required column: {utilization_col}")

    util = df[utilization_col].fillna(0)
    util_mean = util.mean()

    # --- Fields 2+3: standard approval / denial (source: derived) ----------
    approved_rate = (0.923 + (util - util_mean) * 0.05).clip(0.70, 0.99)
    # Enforce F2+F3 = 1.0 at float level before rounding
    denied_rate = (1.0 - approved_rate).round(6)
    approved_rate = (1.0 - denied_rate).round(6)

    df["total_requests"]    = (util * 1000).round().astype(int)
    df["standard_requests"] = (df["total_requests"] * 0.88).round().astype(int)
    df["approved_rate"]     = approved_rate   # Field 2 — source: derived
    df["denied_rate"]       = denied_rate     # Field 3 — source: derived (inverse of F2)

    df["approved_requests"] = (df["total_requests"] * approved_rate).round().astype(int)
    df["denied_requests"]   = df["total_requests"] - df["approved_requests"]

    # --- Field 4: appeal overturn rate (source: external) ------------------
    # National benchmark constant applied uniformly — NOT a county-level simulation.
    # Denominator = denied_requests. Using 61% (lower KFF band for ACO populations).
    # KFF MA 2024: >80% overturned; ACO-adjacent: more defensible initial denials.
    df["appeal_overturn_rate"] = 0.612  # external benchmark constant, uniform
    df["appeals_overturned"]   = (df["denied_requests"] * df["appeal_overturn_rate"]).round().astype(int)

    # --- Field 5: extended review then approved (source: simulated) --------
    # Assumed constant — no public benchmark. Modeled at 4% from UM literature.
    df["extended_review_rate"]     = 0.040   # simulated constant
    df["extended_review_requests"] = (df["total_requests"] * df["extended_review_rate"]).round().astype(int)

    # --- Fields 6+7: expedited approval / denial (source: derived) ---------
    if urgent_rate_col in df.columns:
        df["expedited_requests"] = (
            df[urgent_rate_col].fillna(0) * df["total_requests"]
        ).round().astype(int)
    else:
        df["expedited_requests"] = (df["total_requests"] * 0.05).round().astype(int)

    # Enforce F6+F7 = 1.0: compute approved first, derive denied from it
    expedited_approved_rate = pd.Series(0.891, index=df.index)  # FFS FY2024 reference
    df["expedited_approved"] = (
        df["expedited_requests"] * expedited_approved_rate
    ).round().astype(int)
    df["expedited_denied"]   = df["expedited_requests"] - df["expedited_approved"]

    output_cols = [
        "year", "state_id", "county_id", "enrollment_type",
        "total_requests", "standard_requests", "expedited_requests",
        "approved_requests", "denied_requests",
        "appeals_overturned", "extended_review_requests",
        "expedited_approved", "expedited_denied",
        "approved_rate", "denied_rate",
        "appeal_overturn_rate", "extended_review_rate",
    ]
    available = [c for c in output_cols if c in df.columns]
    return df[available]
