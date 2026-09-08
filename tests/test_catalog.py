"""Tests for CMS catalog resolution and the build-time guards.

These cover the failure that took the dashboard down (plan/issues/api_call.png):
a hard-coded dataset UUID that CMS retired, plus a "portal default" UUID that
silently began serving a different performance year.
"""
from __future__ import annotations

import json

import pandas as pd
import pytest

from src.etl.catalog import CMSCatalog, CatalogError, _parse_distributions
from src.etl.client import CMSDataClient, UpstreamDataError


def _dist(title: str, fmt: str, url: str) -> dict:
    return {"title": title, "format": fmt, "accessURL": url}


API = "https://data.cms.gov/data-api/v1/dataset/{}/data"
TITLE = "County-level Aggregate Expenditure and Risk Score Data on Assignable Beneficiaries"


@pytest.fixture
def distributions() -> list[dict]:
    """Shaped like the real data.json entry, alias UUID included."""
    return [
        # The parent/portal UUID is aliased onto the newest vintage.
        _dist(f"{TITLE} : 2025-01-02oc1", "API", API.format("alias-parent-uuid")),
        _dist(f"{TITLE} : 2025-01-02oc1", "CSV", "https://data.cms.gov/files/oc1.csv"),
        _dist(f"{TITLE} : 2025-01-02oc1", "API", API.format("vintage-2025-oc1")),
        _dist(f"{TITLE} : 2025-01-01", "API", API.format("vintage-2025-final")),
        _dist(f"{TITLE} : 2024-01-04", "API", API.format("vintage-2024-final")),
        _dist(f"{TITLE} : 2022-12-12oc2", "API", API.format("vintage-2022-oc2")),
    ]


class TestDistributionParsing:
    def test_year_and_cut_are_read_from_the_vintage_label(self, distributions):
        vintages = {v.key: v for v in _parse_distributions(distributions)}
        assert set(vintages) == {
            "2025:OC1", "2025:FINAL", "2024:FINAL", "2022:OC2",
        }
        assert vintages["2025:FINAL"].dataset_id == "vintage-2025-final"
        assert vintages["2022:OC2"].data_cut == "OC2"

    def test_alias_uuid_is_not_used_for_the_newest_vintage(self, distributions):
        """The alias follows "whatever is newest" and must never be pinned.

        This is the exact trap in the original outage: the alias kept working
        while the year behind it changed.
        """
        newest = next(v for v in _parse_distributions(distributions) if v.key == "2025:OC1")
        assert newest.dataset_id == "vintage-2025-oc1"

    def test_csv_distribution_is_paired_with_its_api_vintage(self, distributions):
        oc1 = next(v for v in _parse_distributions(distributions) if v.key == "2025:OC1")
        assert oc1.csv_url == "https://data.cms.gov/files/oc1.csv"

    def test_unparseable_titles_are_skipped(self):
        assert _parse_distributions([_dist("Some other dataset", "API", API.format("x"))]) == []


class TestCatalogLookup:
    @pytest.fixture
    def catalog(self, distributions) -> CMSCatalog:
        return CMSCatalog(_parse_distributions(distributions), "2026-01-01T00:00:00+00:00", "test")

    def test_latest_years_discovers_years_instead_of_hard_coding_them(self, catalog):
        assert catalog.latest_years(2) == [2025, 2024]

    def test_latest_years_filters_by_cut(self, catalog):
        # 2022 publishes OC2 but 2025/2024 do not, so an OC2 query sees only 2022.
        assert catalog.latest_years(2, data_cut="OC2") == [2022]

    def test_cuts_for_year_is_ordered_oc_then_final(self, catalog):
        assert catalog.cuts_for_year(2025) == ["OC1", "FINAL"]

    def test_missing_vintage_returns_none_rather_than_raising(self, catalog):
        assert catalog.vintage(1999, "FINAL") is None


class TestCacheFallback:
    def test_cache_round_trips(self, tmp_path, distributions):
        original = CMSCatalog(_parse_distributions(distributions), "2026-01-01T00:00:00+00:00", "live")
        path = tmp_path / "cms_catalog.json"
        original.save(path)

        restored = CMSCatalog.from_cache(path)
        assert restored.source == "cache"
        assert {v.key for v in restored.vintages} == {v.key for v in original.vintages}

    def test_load_falls_back_to_cache_when_the_network_is_unavailable(
        self, tmp_path, distributions, monkeypatch
    ):
        path = tmp_path / "cms_catalog.json"
        CMSCatalog(_parse_distributions(distributions), "2026-01-01T00:00:00+00:00", "live").save(path)

        def explode(*_args, **_kwargs):
            raise ConnectionError("data.cms.gov unreachable")

        monkeypatch.setattr(CMSCatalog, "from_network", classmethod(explode))
        catalog = CMSCatalog.load(cache_path=path)
        assert catalog.source == "cache"
        assert catalog.latest_years(1) == [2025]

    def test_load_raises_only_when_there_is_no_network_and_no_cache(self, tmp_path, monkeypatch):
        def explode(*_args, **_kwargs):
            raise ConnectionError("data.cms.gov unreachable")

        monkeypatch.setattr(CMSCatalog, "from_network", classmethod(explode))
        with pytest.raises(CatalogError):
            CMSCatalog.load(cache_path=tmp_path / "absent.json")


class TestYearAssertion:
    """The guard for a *silent* upstream content swap - no HTTP error involved."""

    def _client(self) -> CMSDataClient:
        return CMSDataClient(dataset_id="d", expected_year=2024, data_cut="FINAL")

    def test_matching_year_passes(self):
        self._client()._assert_expected_year(pd.DataFrame({"YEAR": ["2024", "2024"]}))

    def test_wrong_year_is_rejected(self):
        with pytest.raises(UpstreamDataError, match="returned year"):
            self._client()._assert_expected_year(pd.DataFrame({"YEAR": ["2025", "2025"]}))

    def test_mixed_years_are_rejected(self):
        with pytest.raises(UpstreamDataError):
            self._client()._assert_expected_year(pd.DataFrame({"YEAR": ["2024", "2025"]}))


class TestReshape:
    def test_wide_response_becomes_one_row_per_enrollment_type(self):
        wide = pd.DataFrame([{
            "YEAR": "2025", "STATE_NAME": "ALABAMA", "COUNTY_NAME": "AUTAUGA",
            "STATE_ID": "1", "COUNTY_ID": "0",
            "PER_CAPITA_EXP_ESRD": "1", "AVG_RISK_SCORE_ESRD": "0.9",
            "PER_CAPITA_EXP_DIS": "2", "AVG_RISK_SCORE_DIS": "0.8",
            "PER_CAPITA_EXP_AGDU": "3", "AVG_RISK_SCORE_AGDU": "0.7",
            "PER_CAPITA_EXP_AGND": "4", "AVG_RISK_SCORE_AGND": "0.6",
        }])
        long = CMSDataClient._reshape_wide_to_long(wide)
        assert len(long) == 4
        assert set(long["enrollment_type"]) == {"ESRD", "Disabled", "Aged Dual", "Aged Non-Dual"}
        assert long.loc[long["enrollment_type"] == "Aged Dual", "per_capita_exp"].iloc[0] == "3"


class TestBuildTransforms:
    def test_yoy_join_does_not_pair_a_final_row_with_an_oc_row(self):
        """A positional shift would; an explicit prior-year join must not."""
        from src.build_site import add_yoy_columns

        df = pd.DataFrame([
            {"year": "2024", "state_id": "1", "county_id": "0", "enrollment_type": "ESRD",
             "avg_risk_score": 1.00, "per_capita_exp": 100.0},
            {"year": "2025", "state_id": "1", "county_id": "0", "enrollment_type": "ESRD",
             "avg_risk_score": 1.10, "per_capita_exp": 110.0},
        ])
        out = add_yoy_columns(df, 2025)
        assert len(out) == 1
        assert out["risk_score_yoy_delta"].iloc[0] == pytest.approx(0.10)
        assert out["exp_growth_ratio"].iloc[0] == pytest.approx(0.10)

    def test_yoy_is_null_when_no_prior_year_is_published(self):
        from src.build_site import add_yoy_columns

        df = pd.DataFrame([
            {"year": "2025", "state_id": "1", "county_id": "0", "enrollment_type": "ESRD",
             "avg_risk_score": 1.10, "per_capita_exp": 110.0},
        ])
        out = add_yoy_columns(df, 2025)
        assert out["risk_score_yoy_delta"].isna().all()

    def test_quality_gates_reject_a_thin_payload(self):
        from src.build_site import run_quality_gates

        payload = {"rows": [[0] * 10], "states": ["Alabama"], "counties": [[0, "Autauga", "1", "0"]]}
        latest = pd.DataFrame({
            "avg_risk_score": [1.0], "per_capita_exp": [1.0],
            "enrollment_type": ["ESRD"], "risk_score_yoy_delta": [0.1],
        })
        failures = run_quality_gates(payload, latest)
        assert any("county rows" in f for f in failures)
        assert any("states" in f for f in failures)
        assert any("Missing enrollment types" in f for f in failures)


class TestPublishedPayload:
    """The committed payload is what the page actually serves - check its shape."""

    def test_payload_matches_the_manifest(self):
        from pathlib import Path

        data = Path(__file__).resolve().parents[1] / "docs" / "data"
        if not (data / "manifest.json").exists():
            pytest.skip("No payload built yet; run `python -m src.build_site`.")

        manifest = json.loads((data / "manifest.json").read_text(encoding="utf-8"))
        counties = json.loads((data / "counties.json").read_text(encoding="utf-8"))

        assert len(counties["rows"]) == manifest["county_rows"]
        assert len(counties["states"]) == manifest["states"]
        assert len(counties["counties"]) == manifest["counties"]
        assert len(counties["columns"]) == len(counties["rows"][0])
        # No NaN/Infinity leaked into the JSON - both are invalid JSON literals
        # that would make the page fail to parse the payload at all.
        assert "NaN" not in (data / "counties.json").read_text(encoding="utf-8")
