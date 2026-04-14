from __future__ import annotations

import sys
from pathlib import Path

# Ensure the project root is on sys.path so `src.*` imports resolve
# whether the app is launched via `streamlit run src/app.py` or from the root.
sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd
import plotly.express as px
import streamlit as st
from packaging.version import Version as _V

# Streamlit 1.18+ uses st.cache_data; 1.12 (Python 3.9.7 local) uses
# st.experimental_memo.  Both share the same signature for ttl/show_spinner.
if _V(st.__version__) >= _V("1.18"):
    _cache_data = st.cache_data
else:
    _cache_data = st.experimental_memo  # type: ignore[attr-defined]

from src.etl.client import CMSSodaClient
from src.etl.enrich import DataEnricher
from src.etl.ingest import DataIngestor
from src.modules.hcc_radv_risk_flags.hcc_risk_report import build_hcc_risk_flag_summary
from src.modules.hcc_radv_risk_flags.risk_score_variance import compute_risk_score_yoy_delta
from src.modules.shared_savings_model.reconciliation import build_reconciliation
from src.modules.pa_metrics_simulation.pa_metrics_report import build_pa_metrics_report
from src.modules.fhir_data_bridge.mapping_report import (
    build_fhir_mapping_table,
    build_api_coverage_summary,
)
from src.modules.fhir_data_bridge.puf_to_fhir_mapper import map_puf_row_to_fhir

# MSSP PUF available performance years via CMS Data API v1.
# The current dataset (5f9f1216-…) publishes benchmark data starting with
# performance year 2024.  Update _LAST_YEAR as CMS releases new vintages.
_FIRST_YEAR = 2024
_LAST_YEAR  = 2024
_ALL_YEARS  = list(range(_FIRST_YEAR, _LAST_YEAR + 1))


# ---------------------------------------------------------------------------
# Data fetching — cached by year range so filters don't re-trigger the API
# ---------------------------------------------------------------------------

@_cache_data(show_spinner=False, ttl=3_600)
def fetch_puf_data(start_year: int, end_year: int) -> pd.DataFrame:
    """Fetch CMS MSSP PUF from the SODA API for the given year range,
    normalise columns, coerce dtypes, and enrich with pilot-program flags."""
    client   = CMSSodaClient()
    ingestor = DataIngestor()
    enricher = DataEnricher()

    raw = client.fetch_to_dataframe(start_year=start_year, end_year=end_year)

    if raw.empty:
        return raw

    df = ingestor.process_dataframe(raw)
    df = enricher.enrich(df)
    return df


# ---------------------------------------------------------------------------
# Sidebar filters (applied after data is loaded)
# ---------------------------------------------------------------------------

def apply_filters(df: pd.DataFrame) -> pd.DataFrame:
    def _opts(col: str) -> list:
        return sorted(df[col].dropna().unique().tolist()) if col in df.columns else []

    selected_enrollment = st.sidebar.selectbox("Enrollment type", ["All"] + _opts("enrollment_type"))
    selected_data_cut   = st.sidebar.selectbox("Data cut",        ["All"] + _opts("data_cut"))
    selected_state      = st.sidebar.selectbox("State",           ["All"] + _opts("state_name"))

    out = df.copy()
    if selected_enrollment != "All":
        out = out[out["enrollment_type"] == selected_enrollment]
    if selected_data_cut != "All":
        out = out[out["data_cut"] == selected_data_cut]
    if selected_state != "All":
        out = out[out["state_name"] == selected_state]
    return out


# ---------------------------------------------------------------------------
# Tab renderers
# ---------------------------------------------------------------------------

def render_hcc_tab(df: pd.DataFrame) -> None:
    st.header("HCC / RADV Risk Flag Analysis")
    st.markdown(
        "Year-over-year risk score variance, expenditure efficiency, and a proxy HCC "
        "concentration signal combined to identify counties with elevated RADV-style "
        "exposure patterns."
    )

    max_yoy = float(
        df["risk_score_yoy_delta"].abs().max()
        if "risk_score_yoy_delta" in df.columns and df["risk_score_yoy_delta"].notna().any()
        else 1.0
    ) or 1.0
    max_eer = float(
        df["expenditure_efficiency_ratio"].max()
        if "expenditure_efficiency_ratio" in df.columns and df["expenditure_efficiency_ratio"].notna().any()
        else 1.0
    ) or 1.0

    col1, col2 = st.columns(2)
    with col1:
        delta_threshold = st.slider("Min risk score YoY delta", 0.0, max_yoy, 0.0, max_yoy / 100)
    with col2:
        eer_threshold = st.slider("Min expenditure efficiency ratio", 0.0, max_eer, 0.0, max_eer / 100)

    summary = build_hcc_risk_flag_summary(df)
    if summary.empty:
        st.warning("Not enough data to compute HCC risk flags.")
        return

    filtered = summary.copy()
    if "risk_score_yoy_delta" in filtered.columns:
        filtered = filtered[filtered["risk_score_yoy_delta"].fillna(0) >= delta_threshold]
    if "expenditure_efficiency_ratio" in filtered.columns:
        filtered = filtered[filtered["expenditure_efficiency_ratio"].fillna(0) >= eer_threshold]

    st.subheader(f"Top RADV Exposure Counties ({len(filtered)} records)")
    st.dataframe(filtered.head(25), use_container_width=True)

    if (
        "risk_score_yoy_delta" in filtered.columns
        and "expenditure_efficiency_ratio" in filtered.columns
        and not filtered.empty
    ):
        st.subheader("Risk Score Growth vs. Expenditure Efficiency")
        fig = px.scatter(
            filtered,
            x="risk_score_yoy_delta",
            y="expenditure_efficiency_ratio",
            color="radv_exposure_flag",
            color_discrete_map={True: "#d62728", False: "#1f77b4"},
            size="hcc_concentration_index" if "hcc_concentration_index" in filtered.columns else None,
            size_max=14,
            hover_data=["state_id", "county_id", "enrollment_type"],
            title="RADV Exposure Proxy: YoY Risk Score Delta vs. Expenditure Efficiency",
            labels={
                "risk_score_yoy_delta":        "YoY Risk Score Delta",
                "expenditure_efficiency_ratio": "Expenditure Efficiency Ratio ($/RAF)",
                "radv_exposure_flag":           "High RADV Exposure",
            },
        )
        st.plotly_chart(fig, use_container_width=True)

    st.info(
        "**Key finding:** Counties with the highest RADV exposure scores combine above-average "
        "risk score increases, concentrated HCC patterns, and above-average expenditure efficiency. "
        "DM+CHF and CHF+CKD combinations are RADV audit priority code pairs per CMS 2019 "
        "RADV methods documentation."
    )


def render_shared_savings_tab(df: pd.DataFrame) -> None:
    st.header("Shared Savings Reconciliation Model")
    st.markdown(
        "Simulates the MSSP-style risk-adjusted benchmark and estimates shared savings or loss. "
        "Track selection affects the ACO sharing rate and MSR threshold."
    )

    col1, col2 = st.columns(2)
    with col1:
        track_type = st.selectbox("MSSP shared savings track", ["A", "B", "Enhanced"], index=0)
    with col2:
        enrollment_filter = st.selectbox(
            "Enrollment type filter",
            ["All"] + (sorted(df["enrollment_type"].dropna().unique().tolist()) if "enrollment_type" in df.columns else []),
        )

    plot_df = df.copy()
    if enrollment_filter != "All" and "enrollment_type" in plot_df.columns:
        plot_df = plot_df[plot_df["enrollment_type"] == enrollment_filter]

    reconciliation = build_reconciliation(plot_df, track_type=track_type)
    if reconciliation.empty:
        st.warning("No data available for shared savings reconciliation.")
        return

    display_cols = [
        c for c in [
            "year", "state_id", "county_id", "enrollment_type",
            "avg_risk_score", "per_capita_exp", "benchmark_track_per_capita_exp",
            "shared_savings_ratio", "msr_threshold", "shared_savings_status",
            "benchmark_version_skew",
        ] if c in reconciliation.columns
    ]
    st.subheader("Shared Savings Summary")
    st.dataframe(
        reconciliation[display_cols].sort_values("shared_savings_ratio", ascending=False).head(25),
        use_container_width=True,
    )

    if "shared_savings_ratio" in reconciliation.columns:
        fig = px.histogram(
            reconciliation.dropna(subset=["shared_savings_ratio"]),
            x="shared_savings_ratio",
            color="shared_savings_status",
            nbins=30,
            barmode="stack",
            title=f"Shared Savings Ratio Distribution — Track {track_type.upper()}",
            labels={"shared_savings_ratio": "Shared Savings Ratio", "shared_savings_status": "Status"},
            color_discrete_map={
                "qualified_savings": "#2ca02c",
                "savings_below_msr": "#98df8a",
                "break_even":        "#aec7e8",
                "loss_not_shared":   "#d62728",
                "shared_loss":       "#9467bd",
            },
        )
        fig.add_vline(x=0, line_dash="dash", line_color="black")
        st.plotly_chart(fig, use_container_width=True)

    col_a, col_b = st.columns(2)
    with col_a:
        median_savings = reconciliation["shared_savings_ratio"].median()
        st.metric("Median shared savings ratio", f"{median_savings:.2%}" if pd.notna(median_savings) else "—")
    with col_b:
        if "benchmark_version_skew" in reconciliation.columns:
            median_skew = reconciliation["benchmark_version_skew"].median()
            st.metric("Median V24/V28 version skew", f"{median_skew:.2%}" if pd.notna(median_skew) else "—")

    st.info(
        "**Key finding:** Counties with risk scores above 1.20 systematically exceed benchmark under "
        "Track A — a structural underweighting of severity for high-complexity populations."
    )


def render_pa_metrics_tab(df: pd.DataFrame) -> None:
    st.header("Prior Authorization Metrics Simulation")
    st.markdown(
        "Simulates the seven CMS-0057-F required PA metrics using MSSP utilization proxy fields. "
        "All outputs are synthetic estimates. Reporting deadline: March 31 annually."
    )

    working = df.copy()
    if "specialty_utilization_rate" not in working.columns:
        st.caption("No specialty utilization column found — using per-capita expenditure as proxy.")
        if "per_capita_exp" in working.columns:
            max_exp = working["per_capita_exp"].max()
            working["specialty_utilization_rate"] = (
                working["per_capita_exp"].fillna(0) / max_exp if max_exp else 0.1
            )
        else:
            working["specialty_utilization_rate"] = 0.1

    report = build_pa_metrics_report(working)
    if report.empty:
        st.warning("PA metrics simulation produced no output.")
        return

    display_cols = [
        c for c in [
            "year", "state_id", "county_id", "enrollment_type",
            "total_requests", "standard_requests", "approved_requests",
            "denied_requests", "appeals_overturned", "expedited_requests",
            "expedited_approved", "standard_approval_rate", "expedited_approval_rate",
        ] if c in report.columns
    ]
    st.subheader("Simulated PA Metrics — Top 25 Counties")
    st.dataframe(report[display_cols].head(25), use_container_width=True)

    if "denied_rate" in report.columns and "enrollment_type" in report.columns:
        fig = px.histogram(
            report.dropna(subset=["denied_rate"]),
            x="denied_rate",
            color="enrollment_type",
            nbins=25,
            barmode="overlay",
            opacity=0.75,
            title="Simulated Denial Rate Distribution by Enrollment Type",
            labels={"denied_rate": "Denial Rate", "enrollment_type": "Enrollment Type"},
        )
        fig.add_vline(x=0.077, line_dash="dash", line_color="black",
                      annotation_text="FFS benchmark (7.7%)", annotation_position="top right")
        st.plotly_chart(fig, use_container_width=True)

    st.info(
        "**Key finding:** MSSP-aligned populations show slightly elevated simulated denial rates "
        "relative to the Medicare FFS benchmark (7.7%), consistent with higher specialty utilization "
        "in ACO populations."
    )


def render_fhir_tab(df: pd.DataFrame) -> None:
    st.header("FHIR Data Bridge — PUF vs. FHIR Mapping")
    st.markdown(
        "Maps MSSP PUF data elements to their FHIR R4 equivalents and surfaces the "
        "interoperability gaps in CMS-0057-F API coverage."
    )

    mapping_table = build_fhir_mapping_table(df)
    support_options = sorted(mapping_table["support_status"].dropna().unique().tolist())

    col1, col2 = st.columns(2)
    with col1:
        selected_support = st.selectbox("Filter by FHIR support status", ["All"] + support_options)
    with col2:
        show_gaps_only = st.checkbox("Show gap fields only", value=False)

    display_table = mapping_table.copy()
    if selected_support != "All":
        display_table = display_table[display_table["support_status"] == selected_support]
    if show_gaps_only:
        display_table = display_table[display_table["gap"] == True]

    st.subheader("PUF-to-FHIR Field Mapping")
    st.dataframe(
        display_table[["puf_field", "fhir_path", "cms_0057f_api", "support_status", "gap", "note"]],
        use_container_width=True,
    )

    st.subheader("API Coverage by CMS-0057-F API")
    coverage = build_api_coverage_summary(mapping_table)
    if not coverage.empty:
        fig = px.bar(
            coverage,
            x="cms_0057f_api",
            y="field_count",
            color="support_status",
            barmode="stack",
            title="MSSP PUF Field Coverage per CMS-0057-F API",
            labels={"cms_0057f_api": "CMS API", "field_count": "PUF fields", "support_status": "FHIR Support"},
            color_discrete_map={"Yes": "#2ca02c", "Partial": "#ff7f0e", "No mapping": "#d62728"},
        )
        st.plotly_chart(fig, use_container_width=True)

    if not df.empty:
        st.subheader("Sample FHIR-Mapped Output (first row)")
        st.json(map_puf_row_to_fhir(df.iloc[0].to_dict()))

    gap_count = int(mapping_table["gap"].sum())
    st.info(
        f"**Key finding:** {gap_count} MSSP PUF fields — including `sav_rate` and enrollment-type "
        "stratified expenditure — have no FHIR R4 equivalent in any CMS-0057-F required API."
    )


# ---------------------------------------------------------------------------
# App entry point
# ---------------------------------------------------------------------------

def main() -> None:
    st.set_page_config(page_title="MSSP County-Level Analytics", layout="wide")
    st.title("MSSP County-Level Analytics Dashboard")
    st.caption(
        "Data: CMS MSSP County-Level Aggregate Expenditure & Risk Score PUF — "
        "[data.cms.gov](https://data.cms.gov/medicare-shared-savings-program/"
        "county-level-aggregate-expenditure-and-risk-score-data-on-assignable-beneficiaries)"
    )

    # ------------------------------------------------------------------
    # Sidebar — year range selection
    # ------------------------------------------------------------------
    with st.sidebar:
        st.header("Performance Year Range")
        start_year = st.selectbox("Start year", _ALL_YEARS, index=_ALL_YEARS.index(2022))
        end_year   = st.selectbox("End year",   _ALL_YEARS, index=_ALL_YEARS.index(_LAST_YEAR))

        if start_year > end_year:
            st.error("Start year must be ≤ end year.")
            st.stop()

        if _V(st.__version__) >= _V("1.14"):
            load = st.button("Load Data", type="primary", use_container_width=True)
        else:
            load = st.button("Load Data")
        st.markdown("---")

    # ------------------------------------------------------------------
    # Fetch data on button press (or if already cached)
    # ------------------------------------------------------------------
    cache_key = (start_year, end_year)

    if load or "puf_df" in st.session_state:
        if load or st.session_state.get("loaded_range") != cache_key:
            with st.spinner(f"Fetching PUF data for {start_year}–{end_year} from CMS SODA API…"):
                try:
                    df = fetch_puf_data(start_year, end_year)
                    st.session_state["puf_df"]      = df
                    st.session_state["loaded_range"] = cache_key
                except Exception as exc:
                    st.error(f"API fetch failed: {exc}")
                    st.stop()
        else:
            df = st.session_state["puf_df"]
    else:
        st.info(
            "Select a performance year range and click **Load Data** to begin.\n\n"
            "Data is fetched directly from the CMS SODA API — no file upload needed."
        )
        st.stop()

    if df.empty:
        st.warning(f"No records returned for {start_year}–{end_year}. Try a different year range.")
        st.stop()

    # ------------------------------------------------------------------
    # Sidebar — filters (shown after data loads)
    # ------------------------------------------------------------------
    with st.sidebar:
        st.header("Filters")
        working_df = apply_filters(df)
        st.markdown("---")
        st.metric("Records loaded", f"{len(df):,}")
        st.metric("After filters",  f"{len(working_df):,}")

    # ------------------------------------------------------------------
    # Tabs
    # ------------------------------------------------------------------
    tab1, tab2, tab3, tab4 = st.tabs([
        "HCC Risk Flags",
        "Shared Savings Model",
        "PA Metrics Simulation",
        "FHIR Data Bridge",
    ])

    with tab1:
        render_hcc_tab(working_df)
    with tab2:
        render_shared_savings_tab(working_df)
    with tab3:
        render_pa_metrics_tab(working_df)
    with tab4:
        render_fhir_tab(working_df)


if __name__ == "__main__":
    main()
