from __future__ import annotations

import pandas as pd

from .pa_metrics_schema import PA_FIELD_SOURCE_TYPES
from .pa_metrics_simulation import simulate_pa_metrics


def build_pa_metrics_report(df: pd.DataFrame) -> pd.DataFrame:
    """Create a simulated prior authorization metric report from MSSP proxy fields.

    Adds source_type column for each row so the dashboard can render source badges
    (derived / external / constant / simulated) per v5 spec.
    """
    report = simulate_pa_metrics(df)
    if report.empty:
        return report

    metrics = report.copy()

    # Standard rates — enforce F2+F3 sum to exactly 100% at float level
    metrics["standard_approval_rate"] = (
        metrics["approved_requests"] / metrics["standard_requests"].replace({0: pd.NA})
    ).clip(0, 1)
    metrics["standard_denial_rate"] = (1.0 - metrics["standard_approval_rate"]).clip(0, 1)

    # Expedited rates — enforce F6+F7 sum to exactly 100% at float level
    metrics["expedited_approval_rate"] = (
        metrics["expedited_approved"] / metrics["expedited_requests"].replace({0: pd.NA})
    ).clip(0, 1)
    metrics["expedited_denial_rate"] = (1.0 - metrics["expedited_approval_rate"]).clip(0, 1)

    return metrics


def build_cms_field_table_from_disclosures(disclosures_df: pd.DataFrame) -> pd.DataFrame:
    """Build a comparison table using real disclosure data."""
    if disclosures_df.empty:
        return pd.DataFrame()
    
    # Average across all payers in the disclosure file
    agg = disclosures_df.agg({
        "total_requests": "sum",
        "approved_requests": "sum",
        "denied_requests": "sum",
        "appeals_overturned": "sum",
        "expedited_requests": "sum",
        "expedited_approved": "sum",
        "expedited_denied": "sum"
    })
    
    total_std = agg["total_requests"]
    app_std = agg["approved_requests"]
    den_std = agg["denied_requests"]
    overturned = agg["appeals_overturned"]
    total_exp = agg["expedited_requests"]
    app_exp = agg["expedited_approved"]
    den_exp = agg["expedited_denied"]
    
    std_approval = app_std / total_std if total_std > 0 else 0
    std_denial = den_std / total_std if total_std > 0 else 0
    app_overturn = overturned / den_std if den_std > 0 else 0
    exp_approval = app_exp / total_exp if total_exp > 0 else 0
    exp_denial = den_exp / total_exp if total_exp > 0 else 0

    rows = [
        {
            "field_num":   1,
            "cms_field":   PA_FIELD_SOURCE_TYPES[1]["name"],
            "source_type": "external",
            "value":       "Refer to Plan Disclosures",
            "ffs_ref":     "CMS PA list (Jan 2026)",
            "note":        "Real data from ingested PDF disclosures.",
        },
        {
            "field_num":   2,
            "cms_field":   PA_FIELD_SOURCE_TYPES[2]["name"],
            "source_type": "external",
            "value":       f"{std_approval:.1%}",
            "ffs_ref":     "92.3%",
            "note":        f"Based on {total_std:,} standard requests.",
        },
        {
            "field_num":   3,
            "cms_field":   PA_FIELD_SOURCE_TYPES[3]["name"],
            "source_type": "external",
            "value":       f"{std_denial:.1%}",
            "ffs_ref":     "7.7%",
            "note":        f"Based on {den_std:,} standard denials.",
        },
        {
            "field_num":   4,
            "cms_field":   PA_FIELD_SOURCE_TYPES[4]["name"],
            "source_type": "external",
            "value":       f"{app_overturn:.1%}",
            "ffs_ref":     "~6.4% appeal rate",
            "note":        f"Based on {overturned:,} overturned appeals.",
        },
        {
            "field_num":   6,
            "cms_field":   PA_FIELD_SOURCE_TYPES[6]["name"],
            "source_type": "external",
            "value":       f"{exp_approval:.1%}",
            "ffs_ref":     "89.1%",
            "note":        f"Based on {total_exp:,} expedited requests.",
        },
        {
            "field_num":   7,
            "cms_field":   PA_FIELD_SOURCE_TYPES[7]["name"],
            "source_type": "external",
            "value":       f"{exp_denial:.1%}",
            "ffs_ref":     "10.9%",
            "note":        f"Inverse of Field 6.",
        },
    ]
    return pd.DataFrame(rows)


def build_cms_field_table(report: pd.DataFrame) -> pd.DataFrame:
    """Build the 7-field CMS-0057-F table with source type badges and benchmarks.

    Used by the dashboard to render the all-fields table per v5 spec.
    Each field gets a source_type badge (derived / external / constant / simulated).

    Field 4 denominator note: overturn rate uses denied_requests as denominator,
    per v5 spec — dividing by total understates the rate by ~12x.
    """
    if report.empty:
        return pd.DataFrame()

    agg = report.agg({
        "approved_rate":       "mean",
        "denied_rate":         "mean",
        "appeal_overturn_rate":"mean",
        "extended_review_rate":"mean",
    })

    std_approval = float(agg.get("approved_rate",        0.914))
    std_denial   = float(agg.get("denied_rate",           0.086))
    app_overturn = float(agg.get("appeal_overturn_rate",  0.612))
    ext_review   = float(agg.get("extended_review_rate",  0.040))
    exp_approval = 0.891   # FFS FY2024 — applied uniformly
    exp_denial   = 1.0 - exp_approval

    rows = [
        {
            "field_num":   1,
            "cms_field":   PA_FIELD_SOURCE_TYPES[1]["name"],
            "source_type": PA_FIELD_SOURCE_TYPES[1]["source_type"],
            "simulated":   "18 service types",
            "ffs_ref":     "CMS PA list (Jan 2026)",
            "ma_ref":      "Plan-specific",
            "variance":    "—",
            "flag":        "Reference",
            "note":        PA_FIELD_SOURCE_TYPES[1]["note"],
        },
        {
            "field_num":   2,
            "cms_field":   PA_FIELD_SOURCE_TYPES[2]["name"],
            "source_type": PA_FIELD_SOURCE_TYPES[2]["source_type"],
            "simulated":   f"{std_approval:.1%}",
            "ffs_ref":     "92.3%",
            "ma_ref":      "92.3%",
            "variance":    f"{(std_approval - 0.923)*100:+.1f} pp",
            "flag":        "Normal",
            "note":        PA_FIELD_SOURCE_TYPES[2]["note"],
        },
        {
            "field_num":   3,
            "cms_field":   PA_FIELD_SOURCE_TYPES[3]["name"],
            "source_type": PA_FIELD_SOURCE_TYPES[3]["source_type"],
            "simulated":   f"{std_denial:.1%}",
            "ffs_ref":     "7.7%",
            "ma_ref":      "7.7%",
            "variance":    f"{(std_denial - 0.077)*100:+.1f} pp",
            "flag":        "Outlier" if std_denial > 0.10 else "Normal",
            "note":        PA_FIELD_SOURCE_TYPES[3]["note"],
        },
        {
            "field_num":   4,
            "cms_field":   PA_FIELD_SOURCE_TYPES[4]["name"],
            "source_type": PA_FIELD_SOURCE_TYPES[4]["source_type"],
            "simulated":   f"{app_overturn:.1%}",
            "ffs_ref":     "~6.4% appeal rate (FFS 2022)",
            "ma_ref":      ">80% overturned (KFF 2024)",
            "variance":    f"{(app_overturn - 0.80)*100:+.1f} pp vs. MA",
            "flag":        "Investigate",
            "note":        PA_FIELD_SOURCE_TYPES[4]["note"],
        },
        {
            "field_num":   5,
            "cms_field":   PA_FIELD_SOURCE_TYPES[5]["name"],
            "source_type": PA_FIELD_SOURCE_TYPES[5]["source_type"],
            "simulated":   f"{ext_review:.1%}",
            "ffs_ref":     "N/A (FFS)",
            "ma_ref":      "N/A (not reported)",
            "variance":    "—",
            "flag":        "Modeled",
            "note":        PA_FIELD_SOURCE_TYPES[5]["note"],
        },
        {
            "field_num":   6,
            "cms_field":   PA_FIELD_SOURCE_TYPES[6]["name"],
            "source_type": PA_FIELD_SOURCE_TYPES[6]["source_type"],
            "simulated":   f"{exp_approval:.1%}",
            "ffs_ref":     "89.1%",
            "ma_ref":      "N/A",
            "variance":    f"{(exp_approval - 0.891)*100:+.1f} pp",
            "flag":        "Normal",
            "note":        PA_FIELD_SOURCE_TYPES[6]["note"],
        },
        {
            "field_num":   7,
            "cms_field":   PA_FIELD_SOURCE_TYPES[7]["name"],
            "source_type": PA_FIELD_SOURCE_TYPES[7]["source_type"],
            "simulated":   f"{exp_denial:.1%}",
            "ffs_ref":     "10.9%",
            "ma_ref":      "N/A",
            "variance":    f"{(exp_denial - 0.109)*100:+.1f} pp",
            "flag":        "Outlier" if exp_denial > 0.15 else "Normal",
            "note":        PA_FIELD_SOURCE_TYPES[7]["note"],
        },
    ]
    return pd.DataFrame(rows)
