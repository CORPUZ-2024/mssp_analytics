from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st

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
# Data loading
# ---------------------------------------------------------------------------

def load_puf_data(uploaded_file) -> pd.DataFrame | None:
    if uploaded_file is None:
        return None
    try:
        df = DataIngestor().load(uploaded_file)
        return df
    except Exception as exc:
        st.error(f"Unable to load dataset: {exc}")
        return None


# ---------------------------------------------------------------------------
# Sidebar filters
# ---------------------------------------------------------------------------

def filter_data(df: pd.DataFrame) -> pd.DataFrame:
    def _options(col: str) -> list:
        return sorted(df[col].dropna().unique().tolist()) if col in df.columns else []

    selected_year       = st.sidebar.selectbox("Year",            ["All"] + _options("year"))
    selected_enrollment = st.sidebar.selectbox("Enrollment type", ["All"] + _options("enrollment_type"))
    selected_data_cut   = st.sidebar.selectbox("Data cut",        ["All"] + _options("data_cut"))
    selected_state      = st.sidebar.selectbox("State",           ["All"] + _options("state_name"))

    out = df.copy()
    if selected_year != "All":
        out = out[out["year"] == selected_year]
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
        "concentration signal are combined to identify counties with elevated RADV-style "
        "exposure patterns. This is a county-level audit risk proxy, not an actual RADV "
        "determination."
    )

    # Sliders — guard against zero or missing range to prevent Streamlit error
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
        st.warning(
            "Not enough data to compute HCC risk flags. "
            "Ensure the dataset contains year, state_id, county_id, and avg_risk_score."
        )
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
        "DM+CHF and CHF+CKD county combinations are RADV audit priority code pairs per CMS 2019 "
        "RADV methods documentation."
    )


def render_shared_savings_tab(df: pd.DataFrame) -> None:
    st.header("Shared Savings Reconciliation Model")
    st.markdown(
        "Simulates the MSSP-style risk-adjusted benchmark and estimates shared savings or loss "
        "relative to that benchmark. Track selection affects the ACO sharing rate and MSR threshold."
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
        ]
        if c in reconciliation.columns
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
            labels={
                "shared_savings_ratio":  "Shared Savings Ratio",
                "shared_savings_status": "Status",
            },
            color_discrete_map={
                "qualified_savings":  "#2ca02c",
                "savings_below_msr":  "#98df8a",
                "break_even":         "#aec7e8",
                "loss_not_shared":    "#d62728",
                "shared_loss":        "#9467bd",
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
            st.metric("Median V24/V28 benchmark version skew", f"{median_skew:.2%}" if pd.notna(median_skew) else "—")

    st.info(
        "**Key finding:** Counties with risk scores above 1.20 systematically exceed benchmark under "
        "Track A parameters — a structural underweighting of severity for high-complexity populations. "
        "The benchmark version skew metric isolates the V24/V28 methodology contribution to apparent "
        "savings, which is methodological, not clinical."
    )


def render_pa_metrics_tab(df: pd.DataFrame) -> None:
    st.header("Prior Authorization Metrics Simulation")
    st.markdown(
        "Simulates the seven CMS-0057-F required PA metrics using MSSP utilization proxy fields. "
        "All outputs are synthetic estimates demonstrating how a compliance reporting workflow would "
        "be structured. Reporting deadline: March 31 annually."
    )

    working = df.copy()
    if "specialty_utilization_rate" not in working.columns:
        st.caption(
            "No `specialty_utilization_rate` column found — using per-capita expenditure as proxy."
        )
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

    st.subheader("Simulated PA Metrics — Top 25 Counties")
    display_cols = [
        c for c in [
            "year", "state_id", "county_id", "enrollment_type",
            "total_requests", "standard_requests", "approved_requests",
            "denied_requests", "appeals_overturned", "expedited_requests",
            "expedited_approved", "standard_approval_rate", "expedited_approval_rate",
        ]
        if c in report.columns
    ]
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
        fig.add_vline(
            x=0.077, line_dash="dash", line_color="black",
            annotation_text="FFS benchmark (7.7%)", annotation_position="top right",
        )
        st.plotly_chart(fig, use_container_width=True)

    st.info(
        "**Key finding:** MSSP-aligned populations show slightly elevated simulated denial rates "
        "relative to the Medicare FFS benchmark (7.7%), consistent with higher specialty utilization "
        "in ACO populations. The appeal overturn rate pattern is consistent with more defensible "
        "initial denials or lower appeal propensity relative to MA plan populations (KFF 2024)."
    )


def render_fhir_tab(df: pd.DataFrame) -> None:
    st.header("FHIR Data Bridge — PUF vs. FHIR Mapping")
    st.markdown(
        "Maps MSSP PUF data elements to their FHIR R4 equivalents and surfaces the "
        "interoperability gaps in CMS-0057-F API coverage. Gap fields are highlighted in red."
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

    # API coverage bar chart
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
            labels={
                "cms_0057f_api":  "CMS API",
                "field_count":    "PUF fields",
                "support_status": "FHIR Support",
            },
            color_discrete_map={
                "Yes":         "#2ca02c",
                "Partial":     "#ff7f0e",
                "No mapping":  "#d62728",
            },
        )
        st.plotly_chart(fig, use_container_width=True)

    # Sample FHIR mapping for the first row of the uploaded dataset
    if not df.empty:
        st.subheader("Sample FHIR-Mapped Output (first row)")
        fhir_example = map_puf_row_to_fhir(df.iloc[0].to_dict())
        st.json(fhir_example)

    gap_count = int(mapping_table["gap"].sum())
    st.info(
        f"**Key finding:** {gap_count} MSSP PUF fields — including `sav_rate` (shared savings rate) "
        "and enrollment-type-stratified expenditure — have no direct FHIR R4 equivalent in any "
        "CMS-0057-F required API. CMS publishes these metrics only in flat-file PUF format. "
        "This is a genuine interoperability gap: ACO financial performance is not expressible "
        "through the standard FHIR resource model without custom extensions."
    )


# ---------------------------------------------------------------------------
# App entry point
# ---------------------------------------------------------------------------

def main() -> None:
    st.set_page_config(page_title="MSSP County-Level Analytics", layout="wide")
    st.title("MSSP County-Level Analytics Dashboard")
    st.caption(
        "Data source: CMS MSSP County-Level Aggregate Expenditure and Risk Score PUF — "
        "[data.cms.gov](https://data.cms.gov/medicare-shared-savings-program/"
        "county-level-aggregate-expenditure-and-risk-score-data-on-assignable-beneficiaries)"
    )

    with st.sidebar:
        st.header("Data")
        upload = st.file_uploader(
            "Upload MSSP PUF (CSV or Excel)",
            type=["csv", "xlsx", "xls"],
        )
        st.divider()
        st.header("Filters")

    df = load_puf_data(upload)
    if df is None:
        st.info("Upload a PUF dataset using the sidebar to begin.")
        st.stop()

    working_df = filter_data(df)

    with st.sidebar:
        st.divider()
        st.metric("Rows loaded", f"{len(df):,}")
        st.metric("Rows after filters", f"{len(working_df):,}")

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
