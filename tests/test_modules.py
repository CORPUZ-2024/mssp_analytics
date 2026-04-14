"""Module-level unit tests for all four analytical modules."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.modules.hcc_radv_risk_flags.hcc_mapper import (
    estimate_hcc_concentration_proxy,
    map_icd10_to_hcc,
    hcc_to_category,
)
from src.modules.hcc_radv_risk_flags.risk_score_variance import compute_risk_score_yoy_delta
from src.modules.hcc_radv_risk_flags.radv_proxy_flags import compute_radv_exposure_score
from src.modules.hcc_radv_risk_flags.hcc_risk_report import build_hcc_risk_flag_summary

from src.modules.shared_savings_model.benchmark_constructor import build_benchmark
from src.modules.shared_savings_model.shared_savings_calc import (
    calculate_shared_savings,
    calculate_msr_threshold,
    TRACK_PARAMS,
)
from src.modules.shared_savings_model.reconciliation import build_reconciliation

from src.modules.pa_metrics_simulation.pa_metrics_simulation import simulate_pa_metrics
from src.modules.pa_metrics_simulation.pa_metrics_report import build_pa_metrics_report

from src.modules.fhir_data_bridge.puf_to_fhir_mapper import (
    map_puf_row_to_fhir,
    FHIR_FIELD_MAP,
    PUF_FIELD_CATALOG,
)
from src.modules.fhir_data_bridge.mapping_report import (
    build_fhir_mapping_table,
    build_api_coverage_summary,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _multi_year_df(n_counties: int = 10, years: list[str] | None = None) -> pd.DataFrame:
    if years is None:
        years = ["2022", "2023", "2024"]
    rng = np.random.default_rng(0)
    rows = []
    for i in range(n_counties):
        base_raf = rng.uniform(0.85, 1.40)
        base_exp = rng.uniform(9_000, 15_000)
        for yr in years:
            rows.append({
                "year":             yr,
                "state_id":         f"{(i % 5) + 1:02d}",
                "county_id":        f"{i + 1:03d}",
                "enrollment_type":  "Aged Non-Dual",
                "avg_risk_score":   round(base_raf * (1.01 ** years.index(yr)) + rng.normal(0, 0.02), 4),
                "per_capita_exp":   round(base_exp * (1.02 ** years.index(yr)) + rng.normal(0, 200), 2),
                "person_years":     int(rng.integers(300, 5_000)),
                "team_model_flag":  False,
                "dataset_id":       "7c34-eaqd",
            })
    df = pd.DataFrame(rows)
    df["expenditure_efficiency_ratio"] = df["per_capita_exp"] / df["avg_risk_score"]
    return df


# ---------------------------------------------------------------------------
# Module A — HCC / RADV Risk Flags
# ---------------------------------------------------------------------------

class TestHCCMapper:
    def test_map_known_icd10(self):
        result = map_icd10_to_hcc("E1165")
        assert result is not None
        hcc_code, description = result
        assert hcc_code == "HCC18"
        assert "Diabetes" in description

    def test_map_unknown_icd10_returns_none(self):
        assert map_icd10_to_hcc("ZZZZZ") is None

    def test_map_strips_dot_notation(self):
        # E11.65 should normalise to E1165
        assert map_icd10_to_hcc("E11.65") == map_icd10_to_hcc("E1165")

    def test_hcc_to_category_known(self):
        assert hcc_to_category("HCC85") == "Cardiovascular — CHF"

    def test_hcc_to_category_unknown(self):
        assert hcc_to_category("HCC999") == "Other"

    def test_concentration_proxy_returns_series_in_range(self):
        df = _multi_year_df()
        proxy = estimate_hcc_concentration_proxy(df)
        assert (proxy >= 0).all() and (proxy <= 1).all()
        assert len(proxy) == len(df)

    def test_concentration_proxy_handles_missing_columns(self):
        proxy = estimate_hcc_concentration_proxy(pd.DataFrame({"x": [1, 2]}))
        assert (proxy == 0.0).all()


class TestRiskScoreVariance:
    def test_yoy_delta_computed(self):
        df = _multi_year_df()
        result = compute_risk_score_yoy_delta(df)
        assert "risk_score_yoy_delta" in result.columns
        # First year per group must be NaN (no prior year)
        first_year_rows = result[result["year"] == "2022"]
        assert first_year_rows["risk_score_yoy_delta"].isna().all()

    def test_yoy_delta_positive_for_increasing_risk(self):
        df = pd.DataFrame([
            {"year": "2022", "state_id": "01", "county_id": "001", "enrollment_type": "A", "avg_risk_score": 1.00},
            {"year": "2023", "state_id": "01", "county_id": "001", "enrollment_type": "A", "avg_risk_score": 1.10},
        ])
        result = compute_risk_score_yoy_delta(df)
        delta_2023 = result.loc[result["year"] == "2023", "risk_score_yoy_delta"].iloc[0]
        assert delta_2023 == pytest.approx(0.10, rel=1e-4)

    def test_raises_on_missing_required_column(self):
        with pytest.raises(ValueError):
            compute_risk_score_yoy_delta(pd.DataFrame({"year": ["2023"]}))


class TestRADVProxyFlags:
    def test_exposure_score_columns_created(self):
        df = _multi_year_df()
        df = compute_risk_score_yoy_delta(df)
        result = compute_radv_exposure_score(df)
        assert "radv_exposure_score" in result.columns
        assert "radv_exposure_flag" in result.columns

    def test_exposure_flag_is_top_10_pct(self):
        df = _multi_year_df(n_counties=50)
        df = compute_risk_score_yoy_delta(df)
        result = compute_radv_exposure_score(df)
        flag_rate = result["radv_exposure_flag"].mean()
        assert 0.08 <= flag_rate <= 0.12  # should be ~10%

    def test_raises_on_missing_required_column(self):
        with pytest.raises(ValueError):
            compute_radv_exposure_score(pd.DataFrame({"x": [1]}))


class TestHCCRiskReport:
    def test_returns_dataframe(self):
        df = _multi_year_df(n_counties=15)
        result = build_hcc_risk_flag_summary(df)
        assert isinstance(result, pd.DataFrame)

    def test_top_n_respected(self):
        df = _multi_year_df(n_counties=30)
        result = build_hcc_risk_flag_summary(df, top_n=10)
        assert len(result) <= 10


# ---------------------------------------------------------------------------
# Module B — Shared Savings Model
# ---------------------------------------------------------------------------

class TestBenchmarkConstructor:
    def test_benchmark_columns_created(self):
        df = _multi_year_df()
        result = build_benchmark(df)
        assert "benchmark_v24_per_capita_exp" in result.columns
        assert "benchmark_v28_per_capita_exp" in result.columns
        assert "benchmark_per_capita_exp" in result.columns

    def test_benchmark_uses_v28_as_default(self):
        df = _multi_year_df()
        result = build_benchmark(df)
        pd.testing.assert_series_equal(
            result["benchmark_per_capita_exp"],
            result["benchmark_v28_per_capita_exp"],
            check_names=False,
        )

    def test_raises_on_missing_columns(self):
        with pytest.raises(ValueError):
            build_benchmark(pd.DataFrame({"x": [1]}))


class TestSharedSavingsCalc:
    def test_msr_threshold_sliding_scale(self):
        py = pd.Series([1_000, 30_000, 90_000])
        thresholds = calculate_msr_threshold(py)
        assert thresholds.iloc[0] == pytest.approx(0.035)
        assert 0.020 < thresholds.iloc[1] < 0.035
        assert thresholds.iloc[2] == pytest.approx(0.020)

    def test_shared_savings_status_labels(self):
        df = pd.DataFrame([
            {"per_capita_exp": 9_000, "benchmark_per_capita_exp": 10_000, "person_years": 1_000},  # savings > MSR
            {"per_capita_exp": 9_900, "benchmark_per_capita_exp": 10_000, "person_years": 1_000},  # savings < MSR
            {"per_capita_exp": 11_000, "benchmark_per_capita_exp": 10_000, "person_years": 1_000}, # loss
        ])
        result = calculate_shared_savings(df)
        assert result["shared_savings_status"].iloc[0] == "qualified_savings"
        assert result["shared_savings_status"].iloc[1] == "savings_below_msr"
        assert result["shared_savings_status"].iloc[2] in {"loss_not_shared", "shared_loss"}

    def test_track_params_all_present(self):
        for track in ("A", "B", "ENHANCED"):
            assert track in TRACK_PARAMS
            assert "sharing_rate" in TRACK_PARAMS[track]
            assert "two_sided" in TRACK_PARAMS[track]

    def test_track_b_is_two_sided(self):
        assert TRACK_PARAMS["B"]["two_sided"] is True

    def test_track_a_is_one_sided(self):
        assert TRACK_PARAMS["A"]["two_sided"] is False


class TestReconciliation:
    def test_reconciliation_returns_dataframe(self):
        df = _multi_year_df()
        result = build_reconciliation(df, track_type="A")
        assert isinstance(result, pd.DataFrame)
        assert "shared_savings_status" in result.columns
        assert "benchmark_version_skew" in result.columns

    def test_reconciliation_track_column_set(self):
        df = _multi_year_df()
        result = build_reconciliation(df, track_type="B")
        assert (result["mssp_track"] == "B").all()


# ---------------------------------------------------------------------------
# Module C — PA Metrics Simulation
# ---------------------------------------------------------------------------

class TestPAMetricsSimulation:
    def _pa_df(self) -> pd.DataFrame:
        rng = np.random.default_rng(1)
        n = 30
        df = pd.DataFrame({
            "year":             ["2024"] * n,
            "state_id":         [f"{i % 5 + 1:02d}" for i in range(n)],
            "county_id":        [f"{i + 1:03d}" for i in range(n)],
            "enrollment_type":  ["Aged Non-Dual"] * n,
            "per_capita_exp":   rng.uniform(9_000, 16_000, n).round(2),
        })
        df["specialty_utilization_rate"] = df["per_capita_exp"] / df["per_capita_exp"].max()
        return df

    def test_simulate_returns_required_columns(self):
        result = simulate_pa_metrics(self._pa_df())
        for col in ("approved_requests", "denied_requests", "appeals_overturned",
                    "expedited_approved", "expedited_denied"):
            assert col in result.columns

    def test_approval_rate_within_realistic_range(self):
        result = simulate_pa_metrics(self._pa_df())
        approval_rates = result["approved_requests"] / result["total_requests"].replace({0: np.nan})
        assert approval_rates.dropna().between(0.70, 0.99).all()

    def test_build_report_adds_rate_columns(self):
        df = self._pa_df()
        report = build_pa_metrics_report(df)
        assert "standard_approval_rate" in report.columns
        assert "expedited_approval_rate" in report.columns


# ---------------------------------------------------------------------------
# Module D — FHIR Data Bridge
# ---------------------------------------------------------------------------

class TestFHIRMapper:
    def test_fhir_field_map_has_expected_keys(self):
        expected = {"avg_risk_score", "per_capita_exp", "enrollment_type",
                    "year", "state_id", "county_id"}
        assert expected.issubset(set(FHIR_FIELD_MAP.keys()))

    def test_gap_fields_in_catalog_but_not_map(self):
        gap_fields = {e["puf_field"] for e in PUF_FIELD_CATALOG if e["gap"]}
        assert len(gap_fields) >= 2
        for gf in gap_fields:
            assert gf not in FHIR_FIELD_MAP, f"Gap field {gf!r} should not be in FHIR_FIELD_MAP"

    def test_sav_rate_is_gap(self):
        gaps = {e["puf_field"]: e for e in PUF_FIELD_CATALOG if e["gap"]}
        assert "sav_rate" in gaps

    def test_map_puf_row_to_fhir_excludes_gap_fields(self):
        row = {"avg_risk_score": 1.2, "sav_rate": 0.023, "year": "2024"}
        result = map_puf_row_to_fhir(row)
        # sav_rate has no FHIR path — should not appear in output
        assert not any("sav_rate" in str(k) for k in result.keys())

    def test_map_puf_row_includes_mapped_fields(self):
        row = {"avg_risk_score": 1.2, "per_capita_exp": 12_000.0, "year": "2024"}
        result = map_puf_row_to_fhir(row)
        assert "RiskAssessment.prediction[0].probabilityDecimal" in result
        assert result["RiskAssessment.prediction[0].probabilityDecimal"] == 1.2


class TestFHIRMappingReport:
    def test_mapping_table_has_all_catalog_fields(self):
        table = build_fhir_mapping_table(pd.DataFrame())
        catalog_fields = {e["puf_field"] for e in PUF_FIELD_CATALOG}
        report_fields = set(table["puf_field"].tolist())
        assert catalog_fields == report_fields

    def test_api_coverage_summary_returns_dataframe(self):
        table = build_fhir_mapping_table(pd.DataFrame())
        summary = build_api_coverage_summary(table)
        assert isinstance(summary, pd.DataFrame)
        assert "field_count" in summary.columns

    def test_gap_fields_flagged_in_report(self):
        table = build_fhir_mapping_table(pd.DataFrame())
        gap_rows = table[table["gap"] == True]
        assert len(gap_rows) >= 2
        assert "sav_rate" in gap_rows["puf_field"].values
