from __future__ import annotations

import logging
from io import IOBase
from pathlib import Path
from typing import Any

import pandas as pd

from .config import ALLOWED_DATA_CUTS, NUMERIC_COLUMNS, REQUIRED_COLUMNS, STRING_COLUMNS
from .constants import RAW_OBSERVATIONS_COLUMN

logger = logging.getLogger(__name__)


class DataIngestor:
    """Load and normalise MSSP PUF data from CSV or Excel sources.

    Handles column normalisation, dtype coercion, and data-cut
    standardisation.  Deduplication is intentionally delegated to
    ``DataCleaner`` so QA metadata stays in one place.
    """

    def __init__(self, csv_kwargs: dict[str, Any] | None = None) -> None:
        self.csv_kwargs = csv_kwargs or {}

    def load(self, path: str | Path | IOBase) -> pd.DataFrame:
        """Load a CSV or Excel PUF file and return a normalised dataframe."""
        df = self._read(path)
        logger.info(
            "Loaded %d rows × %d columns from %s.",
            len(df),
            len(df.columns),
            getattr(path, "name", path),
        )
        df = self._normalize_columns(df)
        df = self._coerce_dtypes(df)
        df = self._add_raw_observations(df)
        return df

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _read(self, path: str | Path | IOBase) -> pd.DataFrame:
        if isinstance(path, (str, Path)):
            path = Path(path)
            if path.suffix.lower() in {".csv", ".txt"}:
                return pd.read_csv(path, **self.csv_kwargs)
            if path.suffix.lower() in {".xls", ".xlsx"}:
                return pd.read_excel(path)
            raise ValueError(f"Unsupported file type: {path.suffix}")

        # File-like object
        suffix = Path(getattr(path, "name", "")).suffix.lower()
        if suffix in {".csv", ".txt", ""}:
            return pd.read_csv(path, **self.csv_kwargs)
        if suffix in {".xls", ".xlsx"}:
            return pd.read_excel(path)
        raise ValueError(f"Unsupported file type for file-like object: {suffix!r}")

    def _normalize_columns(self, df: pd.DataFrame) -> pd.DataFrame:
        return df.rename(columns={c: self._clean_col(c) for c in df.columns})

    @staticmethod
    def _clean_col(name: str) -> str:
        cleaned = name.strip().lower().replace(" ", "_").replace("-", "_")
        cleaned = cleaned.replace("/", "_").replace("\\", "_")
        while "__" in cleaned:
            cleaned = cleaned.replace("__", "_")
        return cleaned

    def _coerce_dtypes(self, df: pd.DataFrame) -> pd.DataFrame:
        # String columns — strip whitespace
        for col in STRING_COLUMNS:
            if col in df.columns:
                df[col] = df[col].astype(str).str.strip()

        # Numeric columns — coerce silently; NaN on failure
        for col in NUMERIC_COLUMNS:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

        # YEAR must be str so dedup keys are type-stable across sources
        if "year" in df.columns:
            df["year"] = df["year"].astype(str).str.strip()

        # Standardise data_cut to uppercase with underscores
        if "data_cut" in df.columns:
            normalised = (
                df["data_cut"]
                .astype(str)
                .str.strip()
                .str.upper()
                .str.replace(r"\s+", "_", regex=True)
            )
            df["data_cut"] = normalised.where(
                normalised.isin(ALLOWED_DATA_CUTS), other=normalised
            )

        return df

    @staticmethod
    def _add_raw_observations(df: pd.DataFrame) -> pd.DataFrame:
        if RAW_OBSERVATIONS_COLUMN not in df.columns:
            df[RAW_OBSERVATIONS_COLUMN] = 1
        return df
