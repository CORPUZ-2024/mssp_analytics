from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from .cleaning import DataCleaner
from .enrich import DataEnricher
from .ingest import DataIngestor
from .reporting import PipelineReporter
from .validate import DataValidator, ValidationError

logger = logging.getLogger(__name__)


class DataIngestionPipeline:
    """Orchestrates load → enrich → validate → deduplicate → report → save."""

    def __init__(self, csv_kwargs: dict[str, object] | None = None) -> None:
        self.ingestor = DataIngestor(csv_kwargs=csv_kwargs)
        self.enricher = DataEnricher()
        self.validator = DataValidator()
        self.cleaner = DataCleaner()
        self.reporter = PipelineReporter()

    def run(
        self,
        source_path: str | Path,
        output_path: str | Path,
        qa_path: str | Path,
        dataset_id: str | None = None,
    ) -> pd.DataFrame:
        """Run the full ingestion pipeline and return the cleaned dataframe.

        Args:
            source_path: Raw CSV or Excel input file.
            output_path: Destination path for the cleaned output CSV.
            qa_path:     Directory (or file path whose parent is used) for QA
                         artefacts including ``qa_summary.txt`` and conflict CSVs.
            dataset_id:  Optional CMS SODA dataset identifier stamped on each row.
                         Required for cross-dataset deduplication.  Omitting it
                         triggers a RuntimeWarning in the cleaning step.
        """
        df = self.ingestor.load(source_path)

        if dataset_id is not None and "dataset_id" not in df.columns:
            df["dataset_id"] = dataset_id

        df = self.enricher.enrich(df)
        self.validator.validate(df)
        df = self.cleaner.mark_conflicts(df)
        df = self.cleaner.deduplicate(df)

        qa_dir = Path(qa_path) if Path(qa_path).suffix == "" else Path(qa_path).parent
        self.cleaner.generate_qa_artifacts(df, qa_dir)
        self.reporter.write_api_call_report(
            raw_count=self.cleaner._raw_count,
            dedup_count=len(df),
            dataset_id=dataset_id or df.get("dataset_id", pd.Series()).iloc[0]
            if "dataset_id" in df.columns
            else None,
            output_dir=qa_dir,
        )

        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(output_path, index=False)
        logger.info("Saved cleaned dataset → %s", output_path)
        return df

    def preview(self, source_path: str | Path, n: int = 10) -> pd.DataFrame:
        """Return the first *n* rows of the source file without full processing."""
        return self.ingestor.load(source_path).head(n)
