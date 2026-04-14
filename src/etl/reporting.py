from __future__ import annotations

import csv
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_REPORT_FILENAME = "api_call_report.csv"
_REPORT_FIELDS = (
    "timestamp",
    "dataset_id",
    "raw_observations",
    "deduplicated_rows",
    "rows_dropped",
)


class PipelineReporter:
    """Generate pipeline execution reports for audit and QA traceability.

    The ``api_call_report.csv`` records pre-dedup and post-dedup row counts
    per pipeline run so downstream consumers can verify observation counts
    against expected county totals (e.g. 7c34-eaqd returned 27 obs vs. 25
    expected after dedup).
    """

    def write_api_call_report(
        self,
        raw_count: int,
        dedup_count: int,
        dataset_id: str | None,
        output_dir: str | Path,
    ) -> Path:
        """Append one row to ``api_call_report.csv`` in *output_dir*.

        Args:
            raw_count:   Pre-deduplication row count (total source observations).
            dedup_count: Post-deduplication row count (rows in cleaned output).
            dataset_id:  CMS SODA dataset identifier, if available.
            output_dir:  Directory to write or append the report CSV.

        Returns:
            Absolute path to the report file.
        """
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        report_path = output_dir / _REPORT_FILENAME

        row: dict[str, Any] = {
            "timestamp": datetime.now(tz=timezone.utc).isoformat(),
            "dataset_id": dataset_id or "",
            "raw_observations": raw_count,
            "deduplicated_rows": dedup_count,
            "rows_dropped": raw_count - dedup_count,
        }

        write_header = not report_path.exists()
        with report_path.open("a", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(_REPORT_FIELDS))
            if write_header:
                writer.writeheader()
            writer.writerow(row)

        logger.info(
            "api_call_report.csv updated → raw=%d, dedup=%d, dropped=%d (%s).",
            raw_count,
            dedup_count,
            raw_count - dedup_count,
            report_path,
        )
        return report_path

    def read_report(self, output_dir: str | Path) -> list[dict[str, Any]]:
        """Return all rows from ``api_call_report.csv`` as a list of dicts."""
        path = Path(output_dir) / _REPORT_FILENAME
        if not path.exists():
            return []
        with path.open(encoding="utf-8") as fh:
            return list(csv.DictReader(fh))
