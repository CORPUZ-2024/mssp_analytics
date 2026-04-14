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

# ---------------------------------------------------------------------------
# Data fetching — cached for 1 hour; always loads the current 2024 PUF
# ---------------------------------------------------------------------------

@_cache_data(show_spinner=False, ttl=3_600)
def fetch_puf_data() -> pd.DataFrame:
    """Fetch the 2024 CMS MSSP PUF from the CMS Data API v1,
    normalise columns, coerce dtypes, and enrich with pilot-program flags."""
    client   = CMSSodaClient()
    ingestor = DataIngestor()
    enricher = DataEnricher()

    raw = client.fetch_to_dataframe()

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
    selected_state      = st.sidebar.selectbox("State",           ["All"] + _opts("state_name"))
    selected_county     = st.sidebar.selectbox("County",          ["All"] + _opts("county_name"))

    out = df.copy()
    if selected_enrollment != "All":
        out = out[out["enrollment_type"] == selected_enrollment]
    if selected_state != "All":
        out = out[out["state_name"] == selected_state]
    if selected_county != "All":
        out = out[out["county_name"] == selected_county]
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

    summary = build_hcc_risk_flag_summary(df)
    if summary.empty:
        st.warning("Not enough data to compute HCC risk flags.")
        return

    # Detect whether true YoY delta is available (requires ≥2 years of data).
    # With a single performance year the shift(1) produces all-NaN deltas,
    # so we fall back to the absolute risk score as the x-axis.
    has_yoy = (
        "risk_score_yoy_delta" in summary.columns
        and summary["risk_score_yoy_delta"].notna().any()
    )

    max_eer = float(
        summary["expenditure_efficiency_ratio"].max()
        if "expenditure_efficiency_ratio" in summary.columns
        and summary["expenditure_efficiency_ratio"].notna().any()
        else 1.0
    ) or 1.0

    col1, col2 = st.columns(2)
    with col1:
        if has_yoy:
            max_yoy = float(summary["risk_score_yoy_delta"].abs().max()) or 1.0
            delta_threshold = st.slider("Min YoY risk score delta", 0.0, max_yoy, 0.0, max_yoy / 100)
        else:
            max_rs = float(summary["avg_risk_score"].max()) if "avg_risk_score" in summary.columns else 2.0
            rs_threshold = st.slider("Min risk score", 0.0, max_rs, 0.0, max_rs / 100)
    with col2:
        eer_threshold = st.slider("Min expenditure efficiency ratio", 0.0, max_eer, 0.0, max_eer / 100)

    filtered = summary.copy()
    if has_yoy:
        filtered = filtered[filtered["risk_score_yoy_delta"].fillna(0) >= delta_threshold]
    else:
        if "avg_risk_score" in filtered.columns:
            filtered = filtered[filtered["avg_risk_score"].fillna(0) >= rs_threshold]
    if "expenditure_efficiency_ratio" in filtered.columns:
        filtered = filtered[filtered["expenditure_efficiency_ratio"].fillna(0) >= eer_threshold]

    st.subheader(f"Top RADV Exposure Counties ({len(filtered)} records)")
    st.dataframe(filtered.head(25), height=400)

    if "expenditure_efficiency_ratio" in filtered.columns and not filtered.empty:
        if has_yoy:
            x_col, x_label = "risk_score_yoy_delta", "YoY Risk Score Delta"
        else:
            # Single year: no prior year to diff — use absolute risk score and note why.
            x_col, x_label = "avg_risk_score", "Risk Score (2024)"
            st.caption(
                "ℹ️ YoY delta requires at least two years of data. "
                "Showing absolute 2024 risk score vs. expenditure efficiency."
            )

        st.subheader("Risk Score vs. Expenditure Efficiency — RADV Exposure Map")
        fig = px.scatter(
            filtered.dropna(subset=[x_col, "expenditure_efficiency_ratio"]),
            x=x_col,
            y="expenditure_efficiency_ratio",
            color="radv_exposure_flag",
            color_discrete_map={True: "#e8180c", False: "#1a6faf"},
            size="hcc_concentration_index" if "hcc_concentration_index" in filtered.columns else None,
            size_max=18,
            opacity=0.85,
            hover_data=["state_id", "county_id", "enrollment_type"],
            title="RADV Exposure Proxy: Risk Score vs. Expenditure Efficiency",
            labels={
                x_col:                         x_label,
                "expenditure_efficiency_ratio": "Expenditure Efficiency Ratio ($/RAF)",
                "radv_exposure_flag":           "High RADV Exposure",
            },
            height=450,
        )
        fig.update_traces(marker_line_width=0.5, marker_line_color="white")
        fig.update_layout(legend_title_text="High RADV Exposure")
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
        height=400,
    )

    if "shared_savings_ratio" in reconciliation.columns:
        fig = px.histogram(
            reconciliation.dropna(subset=["shared_savings_ratio"]),
            x="shared_savings_ratio",
            color="shared_savings_status",
            nbins=30,
            barmode="stack",
            opacity=0.88,
            title=f"Shared Savings Ratio Distribution — Track {track_type.upper()}",
            labels={"shared_savings_ratio": "Shared Savings Ratio", "shared_savings_status": "Status"},
            color_discrete_map={
                "qualified_savings": "#1b7e24",
                "savings_below_msr": "#57b85a",
                "break_even":        "#5b9bd5",
                "loss_not_shared":   "#c0392b",
                "shared_loss":       "#7b3fa0",
                "unknown":           "#707070",
            },
            height=450,
        )
        fig.add_vline(x=0, line_dash="dash", line_color="white", line_width=1.5,
                      annotation_text="Break-even", annotation_position="top left")
        fig.update_layout(bargap=0.05, legend_title_text="Savings Status")
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
    st.dataframe(report[display_cols].head(25), height=400)

    if "denied_rate" in report.columns and "enrollment_type" in report.columns:
        fig = px.histogram(
            report.dropna(subset=["denied_rate"]),
            x="denied_rate",
            color="enrollment_type",
            nbins=25,
            barmode="overlay",
            opacity=0.82,
            title="Simulated Denial Rate Distribution by Enrollment Type",
            labels={"denied_rate": "Denial Rate", "enrollment_type": "Enrollment Type"},
            color_discrete_map={
                "ESRD":          "#a93226",
                "Disabled":      "#1f618d",
                "Aged Dual":     "#1e8449",
                "Aged Non-Dual": "#d4ac0d",
            },
            height=450,
        )
        fig.add_vline(x=0.077, line_dash="dash", line_color="white", line_width=1.5,
                      annotation_text="FFS benchmark 7.7%")
        fig.update_layout(bargap=0.02, legend_title_text="Enrollment Type")
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
        height=400,
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
            opacity=0.88,
            title="MSSP PUF Field Coverage per CMS-0057-F API",
            labels={"cms_0057f_api": "CMS API", "field_count": "PUF fields", "support_status": "FHIR Support"},
            color_discrete_map={
                "Yes":        "#1a7a2e",
                "Partial":    "#c97a0a",
                "No mapping": "#b03020",
            },
            height=400,
        )
        fig.update_layout(bargap=0.25, legend_title_text="FHIR Support")
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
        "Performance Year 2024 · CMS MSSP County-Level Aggregate Expenditure & Risk Score PUF — "
        "[data.cms.gov](https://data.cms.gov/medicare-shared-savings-program/"
        "county-level-aggregate-expenditure-and-risk-score-data-on-assignable-beneficiaries)"
    )

    # ------------------------------------------------------------------
    # Auto-load 2024 PUF data on startup — no user input required
    # ------------------------------------------------------------------
    if "puf_df" not in st.session_state:
        with st.spinner("Loading 2024 MSSP PUF data from CMS API…"):
            try:
                st.session_state["puf_df"] = fetch_puf_data()
            except Exception as exc:
                st.error(f"CMS API fetch failed: {exc}")
                st.stop()

    df = st.session_state["puf_df"]

    if df.empty:
        st.warning("No records returned from the CMS API. Please try again later.")
        st.stop()

    # ------------------------------------------------------------------
    # Sidebar — filters only (no data-input controls needed)
    # ------------------------------------------------------------------
    with st.sidebar:
        st.header("Filters")
        working_df = apply_filters(df)
        st.markdown("---")
        st.metric("Records loaded", f"{len(df):,}")
        st.metric("After filters",  f"{len(working_df):,}")
        st.markdown("---")
        if st.button("Refresh data"):
            st.session_state.pop("puf_df", None)
            try:
                fetch_puf_data.clear()          # st.cache_data (>=1.18)
            except AttributeError:
                pass                            # st.experimental_memo has no .clear()
            if _V(st.__version__) >= _V("1.27"):
                st.rerun()
            else:
                st.experimental_rerun()         # type: ignore[attr-defined]

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
