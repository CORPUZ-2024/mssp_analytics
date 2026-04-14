from __future__ import annotations

import logging
import warnings
from pathlib import Path

import pandas as pd

from .config import DEDUP_SUBSET
from .constants import DEDUP_CONFLICT_FLAG, RAW_OBSERVATIONS_COLUMN

logger = logging.getLogger(__name__)


class DataCleaner:
    """Deduplication and QA artifact generation for MSSP PUF data.

    Instance attributes track pipeline-run metadata so QA reports reflect
    pre-dedup counts without polluting the output dataframe with scalar
    metadata repeated on every row.
    """

    def __init__(self) -> None:
        self._raw_count: int = 0
        self._rows_dropped: int = 0
        self._conflict_count: int = 0
        self._duplicate_rows: pd.DataFrame | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def mark_conflicts(self, df: pd.DataFrame) -> pd.DataFrame:
        """Flag rows that share a dedup key but carry different expenditure values.

        Emits a RuntimeWarning (not just a log line) when ``dataset_id`` is
        absent so callers can surface the issue without silently dropping data.
        """
        subset = self._effective_dedup_subset(df, context="conflict detection")
        subset_list = list(subset)
        grouped = df.groupby(subset_list, dropna=False)
        agg = grouped.agg(lambda x: x.nunique(dropna=False)).reset_index()
        value_cols = [c for c in agg.columns if c not in subset_list]
        agg["conflict"] = agg[value_cols].gt(1).any(axis=1)
        conflict_keys = agg.loc[agg["conflict"], subset_list]

        df = df.copy()
        df[DEDUP_CONFLICT_FLAG] = False
        if not conflict_keys.empty:
            n = len(conflict_keys)
            logger.warning("Found %d duplicate groups with conflicting values.", n)
            key_index = conflict_keys.set_index(subset_list).index
            row_index = df.set_index(subset_list).index
            df.loc[row_index.isin(key_index), DEDUP_CONFLICT_FLAG] = True

        self._conflict_count = int(df[DEDUP_CONFLICT_FLAG].sum())
        return df

    def deduplicate(self, df: pd.DataFrame) -> pd.DataFrame:
        """Deduplicate on the canonical key set; keep=first after stable sort.

        Aggregates ``raw_observations`` so each surviving row records how many
        source rows it represents.  Emits a RuntimeWarning when ``dataset_id``
        is absent, per bug-fix spec.
        """
        df = df.copy()
        subset = self._effective_dedup_subset(df, context="deduplication")
        subset_list = list(subset)

        if RAW_OBSERVATIONS_COLUMN not in df.columns:
            df[RAW_OBSERVATIONS_COLUMN] = 1

        # Aggregate observation counts before dropping rows so the surviving
        # row carries the total for its key group.
        df[RAW_OBSERVATIONS_COLUMN] = (
            df.groupby(subset_list)[RAW_OBSERVATIONS_COLUMN].transform("sum")
        )

        sort_cols = subset_list + (
            ["dataset_id"] if "dataset_id" in df.columns else []
        )
        self._raw_count = len(df)
        df = df.sort_values(sort_cols).drop_duplicates(subset=subset_list, keep="first")
        self._rows_dropped = self._raw_count - len(df)

        if self._rows_dropped:
            logger.info(
                "Deduplicated %d → %d rows (%d removed).",
                self._raw_count,
                len(df),
                self._rows_dropped,
            )
        return df

    def generate_qa_artifacts(self, df: pd.DataFrame, qa_dir: str | Path) -> None:
        """Write QA summary and conflict/dropped-row CSVs to *qa_dir*."""
        qa_dir = Path(qa_dir)
        qa_dir.mkdir(parents=True, exist_ok=True)

        summary = {
            "total_input": self._raw_count,
            "total_output": len(df),
            "rows_dropped": self._rows_dropped,
            "conflict_rows": self._conflict_count,
        }
        summary_path = qa_dir / "qa_summary.txt"
        summary_path.write_text(
            "\n".join(f"{k}: {v}" for k, v in summary.items()),
            encoding="utf-8",
        )
        logger.info("Written QA summary → %s", summary_path)

        if self._duplicate_rows is not None and not self._duplicate_rows.empty:
            conflicts_path = qa_dir / "dedup_conflicts.csv"
            self._duplicate_rows.to_csv(conflicts_path, index=False)
            logger.info("Written conflict rows → %s", conflicts_path)

        if self._rows_dropped > 0:
            dropped_path = qa_dir / "deduplicated_rows_removed.csv"
            if self._duplicate_rows is not None and not self._duplicate_rows.empty:
                self._duplicate_rows.to_csv(dropped_path, index=False)
            else:
                pd.DataFrame([summary]).to_csv(dropped_path, index=False)
            logger.info("Written dropped-row record → %s", dropped_path)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _effective_dedup_subset(
        self, df: pd.DataFrame, *, context: str
    ) -> tuple[str, ...]:
        """Return the dedup key tuple, falling back and warning if dataset_id absent."""
        if "dataset_id" not in df.columns or df["dataset_id"].isna().all():
            warnings.warn(
                f"dataset_id is absent during {context}. "
                "Falling back to (year, state_id, county_id). "
                "Cross-dataset deduplication will be skipped — verify source completeness.",
                RuntimeWarning,
                stacklevel=3,
            )
            return tuple(c for c in DEDUP_SUBSET if c != "dataset_id")
        return DEDUP_SUBSET
