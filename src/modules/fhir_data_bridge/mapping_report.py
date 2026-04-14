from __future__ import annotations

import pandas as pd

from .puf_to_fhir_mapper import FHIR_FIELD_MAP, PUF_FIELD_CATALOG, map_puf_row_to_fhir


def build_fhir_mapping_table(df: pd.DataFrame, sample_rows: int = 3) -> pd.DataFrame:
    """Return a full PUF-to-FHIR mapping table including gap fields.

    Each row describes one PUF field: its FHIR target path (if any), the
    CMS-0057-F API scope, support status, gap flag, explanatory note, and
    sample values drawn from *df*.

    Gap fields (``gap=True``) are included with empty fhir_path values so
    the dashboard can highlight interoperability holes explicitly.
    """
    sample = df.head(sample_rows)
    rows = []
    for entry in PUF_FIELD_CATALOG:
        puf_field = str(entry["puf_field"])
        col_data = sample.get(puf_field, pd.Series([None] * len(sample)))
        samples = col_data.astype(str).tolist()
        rows.append(
            {
                "puf_field":      puf_field,
                "fhir_path":      entry["fhir_path"] or "—",
                "fhir_resource":  entry["fhir_resource"] or "—",
                "cms_0057f_api":  entry["cms_0057f_api"],
                "support_status": entry["support_status"],
                "gap":            entry["gap"],
                "note":           entry["note"],
                "sample_values":  "; ".join(str(s) for s in samples),
            }
        )
    return pd.DataFrame(rows)


def build_api_coverage_summary(mapping_df: pd.DataFrame) -> pd.DataFrame:
    """Summarise field counts per CMS API, broken out by support status.

    Used by the FHIR tab to render the API coverage bar chart.
    """
    if mapping_df.empty or "cms_0057f_api" not in mapping_df.columns:
        return pd.DataFrame()

    summary = (
        mapping_df.groupby(["cms_0057f_api", "support_status"])
        .size()
        .reset_index(name="field_count")
        .sort_values(["cms_0057f_api", "support_status"])
    )
    return summary
