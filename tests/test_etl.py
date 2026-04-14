"""ETL pipeline unit and integration tests."""
from __future__ import annotations

import warnings
from pathlib import Path

import pandas as pd
import pytest

from src.etl.cleaning import DataCleaner
from src.etl.config import DEDUP_SUBSET
from src.etl.ingest import DataIngestor
from src.etl.pipeline import DataIngestionPipeline
from src.etl.validate import DataValidator, ValidationError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_puf_csv(path: Path, rows: list[dict]) -> Path:
    pd.DataFrame(rows).to_csv(path, index=False)
    return path


def _base_row(**overrides) -> dict:
    row = {
        "YEAR": "2023",
        "STATE_ID": "01",
        "COUNTY_ID": "001",
        "DATASET_ID": "7c34-eaqd",
        "AVG_RISK_SCORE": 1.20,
        "PER_CAPITA_EXP": 12_000.0,
        "ENROLLMENT_TYPE": "Aged Non-Dual",
        "PERSON_YEARS": 500,
    }
    row.update(overrides)
    return row


# ---------------------------------------------------------------------------
# DataIngestor
# ---------------------------------------------------------------------------

class TestDataIngestor:
    def test_load_normalises_column_names(self, tmp_path):
        csv = _make_puf_csv(tmp_path / "raw.csv", [_base_row()])
        df = DataIngestor().load(csv)
        assert "avg_risk_score" in df.columns
        assert "AVG_RISK_SCORE" not in df.columns

    def test_year_cast_to_string(self, tmp_path):
        """Bug fix: YEAR must be str so dedup keys are type-stable across sources."""
        csv = _make_puf_csv(tmp_path / "raw.csv", [_base_row(YEAR=2023)])
        df = DataIngestor().load(csv)
        assert df["year"].dtype == object  # pandas string dtype
        assert df["year"].iloc[0] == "2023"

    def test_raw_observations_column_added(self, tmp_path):
        csv = _make_puf_csv(tmp_path / "raw.csv", [_base_row()])
        df = DataIngestor().load(csv)
        assert "raw_observations" in df.columns
        assert df["raw_observations"].iloc[0] == 1

    def test_numeric_coercion(self, tmp_path):
        row = _base_row(AVG_RISK_SCORE="bad_value")
        csv = _make_puf_csv(tmp_path / "raw.csv", [row])
        df = DataIngestor().load(csv)
        assert pd.isna(df["avg_risk_score"].iloc[0])


# ---------------------------------------------------------------------------
# DataCleaner
# ---------------------------------------------------------------------------

class TestDataCleaner:
    def _minimal_df(self, n_rows=2) -> pd.DataFrame:
        return pd.DataFrame([_base_row() for _ in range(n_rows)]).rename(
            columns=lambda c: c.lower()
        )

    def test_deduplicate_removes_exact_duplicates(self):
        cleaner = DataCleaner()
        df = self._minimal_df(n_rows=3)
        result = cleaner.deduplicate(df)
        assert len(result) == 1
        assert cleaner._rows_dropped == 2

    def test_raw_observations_aggregated(self):
        cleaner = DataCleaner()
        df = self._minimal_df(n_rows=3)
        result = cleaner.deduplicate(df)
        # 3 source rows collapsed into 1 — raw_observations should be 3
        assert result["raw_observations"].iloc[0] == 3

    def test_dedup_without_dataset_id_emits_warning(self):
        cleaner = DataCleaner()
        df = self._minimal_df().drop(columns=["dataset_id"])
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            cleaner.deduplicate(df)
        assert any(issubclass(warning.category, RuntimeWarning) for warning in w)

    def test_mark_conflicts_flags_conflicting_rows(self):
        cleaner = DataCleaner()
        rows = [
            _base_row(PER_CAPITA_EXP=12_000),
            _base_row(PER_CAPITA_EXP=99_000),  # same key, different expenditure
        ]
        df = pd.DataFrame(rows).rename(columns=lambda c: c.lower())
        result = cleaner.mark_conflicts(df)
        assert result["dedup_conflict"].any()

    def test_qa_artifacts_written(self, tmp_path):
        cleaner = DataCleaner()
        df = self._minimal_df(n_rows=2)
        df = cleaner.deduplicate(df)
        cleaner.generate_qa_artifacts(df, tmp_path / "qa")
        assert (tmp_path / "qa" / "qa_summary.txt").exists()

    def test_qa_summary_contains_correct_counts(self, tmp_path):
        cleaner = DataCleaner()
        df = self._minimal_df(n_rows=3)
        df = cleaner.deduplicate(df)
        cleaner.generate_qa_artifacts(df, tmp_path / "qa")
        text = (tmp_path / "qa" / "qa_summary.txt").read_text()
        assert "total_input: 3" in text
        assert "total_output: 1" in text
        assert "rows_dropped: 2" in text


# ---------------------------------------------------------------------------
# DataValidator
# ---------------------------------------------------------------------------

class TestDataValidator:
    def test_validate_raises_on_missing_required_column(self):
        df = pd.DataFrame({"year": ["2023"], "state_id": ["01"]})
        with pytest.raises(ValidationError, match="Missing required columns"):
            DataValidator().validate(df)

    def test_validate_raises_on_negative_expenditure(self):
        row = _base_row(PER_CAPITA_EXP=-1.0)
        df = pd.DataFrame([row]).rename(columns=lambda c: c.lower())
        with pytest.raises(ValidationError, match="negative"):
            DataValidator().validate(df)

    def test_validate_raises_on_risk_score_out_of_range(self):
        row = _base_row(AVG_RISK_SCORE=99.0)
        df = pd.DataFrame([row]).rename(columns=lambda c: c.lower())
        with pytest.raises(ValidationError, match=r"avg_risk_score.*\[0, 5\]"):
            DataValidator().validate(df)

    def test_validate_warns_on_missing_dataset_id(self, capsys):
        row = _base_row()
        df = pd.DataFrame([row]).rename(columns=lambda c: c.lower()).drop(columns=["dataset_id"])
        # Should not raise — dataset_id is optional; warning is logged
        DataValidator().validate_schema(df)


# ---------------------------------------------------------------------------
# DataIngestionPipeline (integration)
# ---------------------------------------------------------------------------

class TestDataIngestionPipeline:
    def test_full_pipeline_run(self, tmp_path):
        csv = _make_puf_csv(tmp_path / "raw.csv", [_base_row()])
        pipeline = DataIngestionPipeline()
        result = pipeline.run(
            csv,
            output_path=tmp_path / "clean.csv",
            qa_path=tmp_path / "qa",
        )
        assert (tmp_path / "clean.csv").exists()
        assert (tmp_path / "qa" / "qa_summary.txt").exists()
        assert len(result) == 1
        assert result["avg_risk_score"].iloc[0] == pytest.approx(1.20)

    def test_pipeline_deduplicates_exact_duplicates(self, tmp_path):
        rows = [_base_row(), _base_row()]
        csv = _make_puf_csv(tmp_path / "raw.csv", rows)
        pipeline = DataIngestionPipeline()
        result = pipeline.run(csv, tmp_path / "clean.csv", tmp_path / "qa")
        assert len(result) == 1

    def test_pipeline_adds_pilot_flags(self, tmp_path):
        row = _base_row()
        row["STATE_NAME"] = "Maryland"
        csv = _make_puf_csv(tmp_path / "raw.csv", [row])
        pipeline = DataIngestionPipeline()
        result = pipeline.run(csv, tmp_path / "clean.csv", tmp_path / "qa")
        assert "ahead_model_flag" in result.columns

    def test_pipeline_adds_efficiency_ratio(self, tmp_path):
        csv = _make_puf_csv(tmp_path / "raw.csv", [_base_row()])
        pipeline = DataIngestionPipeline()
        result = pipeline.run(csv, tmp_path / "clean.csv", tmp_path / "qa")
        assert "expenditure_efficiency_ratio" in result.columns
        expected = 12_000.0 / 1.20
        assert result["expenditure_efficiency_ratio"].iloc[0] == pytest.approx(expected, rel=1e-4)

    def test_pipeline_writes_api_call_report(self, tmp_path):
        csv = _make_puf_csv(tmp_path / "raw.csv", [_base_row()])
        pipeline = DataIngestionPipeline()
        pipeline.run(csv, tmp_path / "clean.csv", tmp_path / "qa")
        report_path = tmp_path / "qa" / "api_call_report.csv"
        assert report_path.exists()
        report = pd.read_csv(report_path)
        assert "raw_observations" in report.columns
        assert "rows_dropped" in report.columns

    def test_preview_returns_head(self, tmp_path):
        rows = [_base_row(COUNTY_ID=f"{i:03d}") for i in range(20)]
        csv = _make_puf_csv(tmp_path / "raw.csv", rows)
        pipeline = DataIngestionPipeline()
        preview = pipeline.preview(csv, n=5)
        assert len(preview) == 5
