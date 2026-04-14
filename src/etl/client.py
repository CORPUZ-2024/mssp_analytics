from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlencode

import requests
import pandas as pd

logger = logging.getLogger(__name__)

# CMS MSSP County-Level Aggregate Expenditure & Risk Score PUF
# https://data.cms.gov/medicare-shared-savings-program/
#   county-level-aggregate-expenditure-and-risk-score-data-on-assignable-beneficiaries
DEFAULT_DATASET_ID = "7c34-eaqd"
_SODA_BASE = "https://data.cms.gov/resource"
_DEFAULT_PAGE_SIZE = 1_000
_REQUEST_TIMEOUT = 30


class CMSSodaClient:
    """Thin client for the CMS SODA API (data.cms.gov).

    Supports paginated fetches, filter push-down, and direct conversion to
    a pandas DataFrame.  The default dataset is the MSSP county-level PUF.

    Example::

        client = CMSSodaClient()
        df = client.fetch_to_dataframe(year="2023", enrollment_type="Aged Non-Dual")
    """

    def __init__(
        self,
        dataset_id: str = DEFAULT_DATASET_ID,
        app_token: str | None = None,
        base_url: str = _SODA_BASE,
    ) -> None:
        self.dataset_id = dataset_id
        self.app_token = app_token
        self.base_url = base_url.rstrip("/")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def fetch_page(
        self,
        limit: int = _DEFAULT_PAGE_SIZE,
        offset: int = 0,
        **filters: Any,
    ) -> list[dict[str, Any]]:
        """Fetch a single page of records from the SODA endpoint.

        Args:
            limit:   Number of rows to return (SODA ``$limit``).
            offset:  Row offset (SODA ``$offset``).
            **filters: Field equality filters translated to SODA ``$where`` clauses.
        """
        params: dict[str, Any] = {"$limit": limit, "$offset": offset}
        if filters:
            where_clauses = [
                f"{k}='{v}'" if isinstance(v, str) else f"{k}={v}"
                for k, v in filters.items()
            ]
            params["$where"] = " AND ".join(where_clauses)

        url = f"{self.base_url}/{self.dataset_id}.json"
        headers: dict[str, str] = {}
        if self.app_token:
            headers["X-App-Token"] = self.app_token

        logger.debug("SODA request: %s?%s", url, urlencode(params))
        response = requests.get(url, params=params, headers=headers, timeout=_REQUEST_TIMEOUT)
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
        **filters: Any,
    ) -> list[dict[str, Any]]:
        """Paginate through the full dataset and return all matching records.

        Iterates until a page shorter than *page_size* is returned, which
        signals the last page.
        """
        all_records: list[dict[str, Any]] = []
        offset = 0
        while True:
            page = self.fetch_page(limit=page_size, offset=offset, **filters)
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
        **filters: Any,
    ) -> pd.DataFrame:
        """Return all matching records as a pandas DataFrame.

        The returned frame includes a ``dataset_id`` column stamped with
        ``self.dataset_id`` so downstream deduplication can distinguish rows
        from different API sources.
        """
        records = self.fetch_all(page_size=page_size, **filters)
        df = pd.DataFrame(records)
        if not df.empty:
            df["dataset_id"] = self.dataset_id
        return df

    def row_count(self, **filters: Any) -> int:
        """Return the total record count without fetching data."""
        params: dict[str, Any] = {"$select": "count(*)", "$limit": 1}
        if filters:
            where_clauses = [
                f"{k}='{v}'" if isinstance(v, str) else f"{k}={v}"
                for k, v in filters.items()
            ]
            params["$where"] = " AND ".join(where_clauses)
        url = f"{self.base_url}/{self.dataset_id}.json"
        headers: dict[str, str] = {"X-App-Token": self.app_token} if self.app_token else {}
        response = requests.get(url, params=params, headers=headers, timeout=_REQUEST_TIMEOUT)
        response.raise_for_status()
        result = response.json()
        return int(result[0].get("count", 0))
