from __future__ import annotations

import logging
from typing import Any

import pandas as pd
import requests

logger = logging.getLogger(__name__)

# CMS MSSP County-Level Aggregate Expenditure & Risk Score PUF
# New CMS Data API v1 (replaces retired Socrata endpoint 7c34-eaqd)
# https://data.cms.gov/medicare-shared-savings-program/
#   county-level-aggregate-expenditure-and-risk-score-data-on-assignable-beneficiaries
DEFAULT_DATASET_ID = "5f9f1216-6fd9-455d-bfbc-0efade687a4e"
_API_BASE = "https://data.cms.gov/data-api/v1/dataset"
_DEFAULT_PAGE_SIZE = 1_000
_REQUEST_TIMEOUT = 60

# Wide-format suffix → enrollment_type label
_ENROLLMENT_SUFFIX_MAP: dict[str, str] = {
    "ESRD": "ESRD",
    "DIS": "Disabled",
    "AGDU": "Aged Dual",
    "AGND": "Aged Non-Dual",
}

# Columns that identify a county/year combination (not per-enrollment-type)
_ID_COLS = ["YEAR", "STATE_NAME", "COUNTY_NAME", "STATE_ID", "COUNTY_ID"]

# Metric column prefixes in the wide format
_METRIC_PREFIXES = ["PER_CAPITA_EXP", "AVG_RISK_SCORE", "AVG_DEMOG_SCORE", "PERSON_YEARS"]


class CMSSodaClient:
    """Client for the CMS Data API v1 (data.cms.gov).

    The default dataset is the MSSP county-level PUF.  The CMS Data API v1
    returns data in **wide format** (one row per county, with per-enrollment-type
    metrics as separate columns). ``fetch_to_dataframe`` automatically reshapes
    the response to **long format** so downstream code sees one row per
    county × enrollment-type combination — matching the expected schema.

    Example::

        client = CMSSodaClient()
        df = client.fetch_to_dataframe(start_year=2024, end_year=2024)
    """

    def __init__(
        self,
        dataset_id: str = DEFAULT_DATASET_ID,
        app_token: str | None = None,
        base_url: str = _API_BASE,
    ) -> None:
        self.dataset_id = dataset_id
        self.app_token = app_token
        self.base_url = base_url.rstrip("/")

    @property
    def _endpoint(self) -> str:
        return f"{self.base_url}/{self.dataset_id}/data"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def fetch_page(
        self,
        limit: int = _DEFAULT_PAGE_SIZE,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Fetch a single page of raw (wide-format) records."""
        params: dict[str, Any] = {"size": limit, "offset": offset}
        headers: dict[str, str] = {}
        if self.app_token:
            headers["X-App-Token"] = self.app_token

        logger.debug("CMS API request: %s  params=%s", self._endpoint, params)
        response = requests.get(
            self._endpoint, params=params, headers=headers, timeout=_REQUEST_TIMEOUT
        )
        response.raise_for_status()
        records: list[dict[str, Any]] = response.json()
        logger.info(
            "Fetched %d records from dataset %s (offset=%d).",
            len(records),
            self.dataset_id,
            offset,
        )
        return records

    def fetch_all(
        self,
        page_size: int = _DEFAULT_PAGE_SIZE,
    ) -> list[dict[str, Any]]:
        """Paginate through the full dataset and return all raw wide-format records."""
        all_records: list[dict[str, Any]] = []
        offset = 0
        while True:
            page = self.fetch_page(limit=page_size, offset=offset)
            all_records.extend(page)
            if len(page) < page_size:
                break
            offset += page_size
        logger.info(
            "Completed full fetch: %d total records from dataset %s.",
            len(all_records),
            self.dataset_id,
        )
        return all_records

    def fetch_to_dataframe(
        self,
        page_size: int = _DEFAULT_PAGE_SIZE,
        start_year: int | str | None = None,
        end_year: int | str | None = None,
        # Legacy SODA-style parameters accepted but ignored (API no longer SODA)
        where: str | None = None,
        **filters: Any,
    ) -> pd.DataFrame:
        """Return all matching records as a long-format pandas DataFrame.

        Fetches all data from the API, reshapes from wide to long format
        (one row per county × enrollment-type), then applies optional year
        range filtering in Python.

        Args:
            start_year: Earliest performance year to include (inclusive).
            end_year:   Latest performance year to include (inclusive).
            where:      Ignored — accepted for backward compatibility only.
            **filters:  Ignored — accepted for backward compatibility only.
        """
        records = self.fetch_all(page_size=page_size)
        df = pd.DataFrame(records)
        if df.empty:
            return df

        df = self._reshape_wide_to_long(df)
        df["dataset_id"] = self.dataset_id

        # Year range filter applied in Python (API does not support server-side filtering)
        if "YEAR" in df.columns:
            yr = df["YEAR"].astype(str)
            if start_year is not None:
                df = df[yr >= str(start_year)]
            if end_year is not None:
                df = df[yr <= str(end_year)]

        return df.reset_index(drop=True)

    def row_count(self, **filters: Any) -> int:
        """Return -1 (count endpoint not available on CMS Data API v1)."""
        logger.warning("row_count() is not supported on CMS Data API v1; returning -1.")
        return -1

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _reshape_wide_to_long(df: pd.DataFrame) -> pd.DataFrame:
        """Reshape the wide CMS API response to long format.

        Input:  one row per county, with per-enrollment-type metric columns
                (e.g. PER_CAPITA_EXP_ESRD, AVG_RISK_SCORE_DIS, …).
        Output: four rows per county (one per enrollment type) with standard
                metric columns: per_capita_exp, avg_risk_score, avg_demog_score,
                person_years.
        """
        id_cols = [c for c in _ID_COLS if c in df.columns]
        frames: list[pd.DataFrame] = []

        for suffix, label in _ENROLLMENT_SUFFIX_MAP.items():
            sub = df[id_cols].copy()
            sub["enrollment_type"] = label
            for prefix in _METRIC_PREFIXES:
                src = f"{prefix}_{suffix}"
                dst = prefix.lower()
                if src in df.columns:
                    sub[dst] = df[src].values
            frames.append(sub)

        return pd.concat(frames, ignore_index=True)
