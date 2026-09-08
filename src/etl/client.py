from __future__ import annotations

"""HTTP client for the CMS Data API v1 (data.cms.gov).

Dataset UUIDs are **not** hard-coded here any more.  They are resolved at call
time from the DCAT catalog (see ``src/etl/catalog.py``), because CMS retires and
re-points UUIDs between publications.  Two guards are layered on top:

* **Retry with backoff** for transient 5xx / connection errors.
* **Year assertion** -- every fetch verifies that the rows CMS returned actually
  carry the performance year that was asked for.  The original outage was a
  *silent* content swap (a UUID that used to serve PY2024 began serving PY2025),
  which no HTTP status code would have caught.
"""

import logging
import time
from typing import Any

import pandas as pd
import requests

from .catalog import CMSCatalog, Vintage

logger = logging.getLogger(__name__)

_API_BASE = "https://data.cms.gov/data-api/v1/dataset"
_DEFAULT_PAGE_SIZE = 5_000
_REQUEST_TIMEOUT = 90
_MAX_RETRIES = 4
_BACKOFF_BASE = 1.5

# Wide-format suffix -> enrollment_type label
_ENROLLMENT_SUFFIX_MAP: dict[str, str] = {
    "ESRD": "ESRD",
    "DIS": "Disabled",
    "AGDU": "Aged Dual",
    "AGND": "Aged Non-Dual",
}

# Columns identifying a county/year combination (not per-enrollment-type)
_ID_COLS = ["YEAR", "STATE_NAME", "COUNTY_NAME", "STATE_ID", "COUNTY_ID"]

# Metric column prefixes in the wide format
_METRIC_PREFIXES = ["PER_CAPITA_EXP", "AVG_RISK_SCORE", "AVG_DEMOG_SCORE", "PERSON_YEARS"]


class UpstreamDataError(RuntimeError):
    """Raised when CMS responds successfully but with unusable content."""


class CMSDataClient:
    """Client for one resolved vintage of the CMS MSSP county-level PUF.

    The CMS Data API v1 returns **wide** rows (one per county, with
    per-enrollment-type metrics as separate columns).  ``fetch_to_dataframe``
    reshapes to **long** format so downstream code sees one row per
    county x enrollment-type, and stamps ``year`` / ``data_cut`` / ``dataset_id``
    provenance columns onto every row.

    Example::

        catalog = CMSCatalog.load()
        client  = CMSDataClient.for_vintage(catalog.vintage(2025, "FINAL"))
        df      = client.fetch_to_dataframe()
    """

    def __init__(
        self,
        dataset_id: str,
        expected_year: int | None = None,
        data_cut: str = "FINAL",
        app_token: str | None = None,
        base_url: str = _API_BASE,
    ) -> None:
        self.dataset_id = dataset_id
        self.expected_year = expected_year
        self.data_cut = data_cut.upper()
        self.app_token = app_token
        self.base_url = base_url.rstrip("/")

    @classmethod
    def for_vintage(cls, vintage: Vintage, app_token: str | None = None) -> "CMSDataClient":
        return cls(
            dataset_id=vintage.dataset_id,
            expected_year=vintage.year,
            data_cut=vintage.data_cut,
            app_token=app_token,
        )

    @property
    def _endpoint(self) -> str:
        return f"{self.base_url}/{self.dataset_id}/data"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def fetch_page(self, limit: int = _DEFAULT_PAGE_SIZE, offset: int = 0) -> list[dict[str, Any]]:
        """Fetch one page of raw wide-format records, retrying transient failures."""
        params: dict[str, Any] = {"size": limit, "offset": offset}
        headers: dict[str, str] = {}
        if self.app_token:
            headers["X-App-Token"] = self.app_token

        last_error: Exception | None = None
        for attempt in range(_MAX_RETRIES):
            try:
                response = requests.get(
                    self._endpoint, params=params, headers=headers, timeout=_REQUEST_TIMEOUT
                )
                # 4xx means the dataset id is wrong or retired -- retrying cannot
                # help, and the caller needs to re-resolve the catalog.
                if 400 <= response.status_code < 500:
                    response.raise_for_status()
                response.raise_for_status()
                return response.json()
            except requests.HTTPError as exc:
                status = exc.response.status_code if exc.response is not None else 0
                if 400 <= status < 500:
                    raise
                last_error = exc
            except (requests.ConnectionError, requests.Timeout, ValueError) as exc:
                last_error = exc

            sleep_for = _BACKOFF_BASE ** attempt
            logger.warning(
                "CMS API request failed (attempt %d/%d): %s. Retrying in %.1fs.",
                attempt + 1,
                _MAX_RETRIES,
                last_error,
                sleep_for,
            )
            time.sleep(sleep_for)

        raise UpstreamDataError(
            f"CMS API request to {self._endpoint} failed after {_MAX_RETRIES} attempts: {last_error}"
        )

    def fetch_all(self, page_size: int = _DEFAULT_PAGE_SIZE) -> list[dict[str, Any]]:
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
            "Fetched %d records for %s cut %s (dataset %s).",
            len(all_records),
            self.expected_year,
            self.data_cut,
            self.dataset_id,
        )
        return all_records

    def fetch_to_dataframe(self, page_size: int = _DEFAULT_PAGE_SIZE) -> pd.DataFrame:
        """Return the vintage as a long-format dataframe with provenance columns."""
        records = self.fetch_all(page_size=page_size)
        df = pd.DataFrame(records)
        if df.empty:
            raise UpstreamDataError(
                f"CMS returned zero rows for dataset {self.dataset_id} "
                f"({self.expected_year} {self.data_cut})."
            )

        self._assert_expected_year(df)

        long_df = self._reshape_wide_to_long(df)
        long_df["dataset_id"] = self.dataset_id
        long_df["data_cut"] = self.data_cut
        return long_df.reset_index(drop=True)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _assert_expected_year(self, df: pd.DataFrame) -> None:
        """Fail loudly when CMS serves a different performance year than requested.

        This is the guard that turns the original silent failure into a build
        error: a UUID that quietly starts serving a different year is caught
        here rather than producing an empty dashboard.
        """
        if self.expected_year is None or "YEAR" not in df.columns:
            return
        years = set(df["YEAR"].astype(str).str.strip().unique())
        expected = str(self.expected_year)
        if years != {expected}:
            raise UpstreamDataError(
                f"Dataset {self.dataset_id} was resolved as performance year "
                f"{expected} ({self.data_cut}) but returned year(s) {sorted(years)}. "
                "The CMS catalog mapping has changed -- re-resolve before trusting this build."
            )

    @staticmethod
    def _reshape_wide_to_long(df: pd.DataFrame) -> pd.DataFrame:
        """Reshape the wide CMS response into one row per county x enrollment type.

        Input:  one row per county, with per-enrollment-type metric columns
                (PER_CAPITA_EXP_ESRD, AVG_RISK_SCORE_DIS, ...).
        Output: four rows per county with standard metric columns
                (per_capita_exp, avg_risk_score, avg_demog_score, person_years).
        """
        id_cols = [c for c in _ID_COLS if c in df.columns]
        frames: list[pd.DataFrame] = []

        for suffix, label in _ENROLLMENT_SUFFIX_MAP.items():
            sub = df[id_cols].copy()
            sub["enrollment_type"] = label
            for prefix in _METRIC_PREFIXES:
                src = f"{prefix}_{suffix}"
                if src in df.columns:
                    sub[prefix.lower()] = df[src].values
            frames.append(sub)

        return pd.concat(frames, ignore_index=True)


def fetch_vintages(
    catalog: CMSCatalog,
    requests_: list[tuple[int, str]],
    app_token: str | None = None,
    required: bool = False,
) -> pd.DataFrame:
    """Fetch several (year, data_cut) vintages and concatenate them.

    Args:
        catalog:   Resolved CMS catalog.
        requests_: ``[(2025, "FINAL"), (2025, "OC1"), ...]``.
        app_token: Optional CMS API token.
        required:  When ``True`` any single failure aborts.  When ``False``
                   (the default) a failed vintage is logged and skipped, so an
                   optional cut going missing upstream degrades one chart
                   instead of the whole build.

    Returns:
        Long-format dataframe with ``year``/``data_cut``/``dataset_id`` columns.
    """
    frames: list[pd.DataFrame] = []
    for year, cut in requests_:
        vintage = catalog.vintage(year, cut)
        if vintage is None:
            message = f"No {cut} vintage published for {year}."
            if required:
                raise UpstreamDataError(message)
            logger.warning("%s Skipping.", message)
            continue
        try:
            frames.append(CMSDataClient.for_vintage(vintage, app_token).fetch_to_dataframe())
        except Exception as exc:  # noqa: BLE001 - one bad cut must not kill the build
            if required:
                raise
            logger.warning("Could not fetch %s %s (%s). Skipping.", year, cut, exc)

    if not frames:
        raise UpstreamDataError("No vintages could be fetched from CMS.")
    return pd.concat(frames, ignore_index=True)


# ---------------------------------------------------------------------------
# Backwards compatibility
# ---------------------------------------------------------------------------

class CMSSodaClient(CMSDataClient):
    """Deprecated alias kept so older callers keep importing successfully.

    The CMS endpoint has not been SODA since the Socrata retirement, and the
    class no longer accepts a hard-coded default dataset id -- resolve one from
    :class:`~src.etl.catalog.CMSCatalog` instead.
    """

    def __init__(self, dataset_id: str | None = None, **kwargs: Any) -> None:
        if dataset_id is None:
            catalog = CMSCatalog.load()
            latest = catalog.latest_years(1)
            if not latest:
                raise UpstreamDataError("Catalog contains no FINAL vintage.")
            vintage = catalog.vintage(latest[0], "FINAL")
            assert vintage is not None
            logger.warning(
                "CMSSodaClient instantiated without a dataset id; resolved latest "
                "FINAL vintage %s. Prefer CMSDataClient.for_vintage().",
                vintage.key,
            )
            dataset_id = vintage.dataset_id
            kwargs.setdefault("expected_year", vintage.year)
            kwargs.setdefault("data_cut", vintage.data_cut)
        kwargs.pop("base_url", None)
        super().__init__(dataset_id=dataset_id, **kwargs)
