from __future__ import annotations

"""Resolve CMS MSSP PUF dataset endpoints from the DCAT catalog.

Why this module exists
----------------------
The previous implementation hard-coded CMS Data API dataset UUIDs::

    DATASET_IDS_BY_YEAR = {2024: "5f9f1216-...", 2023: "ebd74cd0-...", ...}

That broke in production (see ``plan/issues/api_call.png``) for two reasons:

1. The year-specific UUIDs were **retired** by CMS and now return HTTP 404
   ("Access denied to the requested data").
2. The "portal default" UUID is an **alias for the newest vintage**, not for a
   fixed year.  When CMS published PY2025 the same UUID silently started
   serving ``YEAR=2025``, so a ``start_year=2024, end_year=2024`` filter
   returned zero rows -- the "No records returned" banner in the screenshot.

The fix is to stop treating UUIDs as stable identifiers.  CMS publishes a
DCAT-US catalog at ``https://data.cms.gov/data.json`` in which the **dataset
title is the stable key** and each vintage (performance year x operational cut)
is a ``distribution`` carrying its own current UUID.  We resolve titles -> UUIDs
at build time, so a CMS-side UUID rotation is absorbed by the resolver instead
of surfacing as a broken dashboard.

A resolved catalog is cached to disk and committed to the repo, so a CMS
outage during a build degrades to "use the last known-good endpoint map"
rather than to a hard failure.
"""

import json
import logging
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import requests

logger = logging.getLogger(__name__)

CATALOG_URL = "https://data.cms.gov/data.json"

# Stable key: the dataset *title* on data.cms.gov. Matched case-insensitively
# on a prefix so CMS punctuation tweaks do not break resolution.
MSSP_COUNTY_PUF_TITLE = (
    "County-level Aggregate Expenditure and Risk Score Data on Assignable Beneficiaries"
)

DEFAULT_CACHE_PATH = Path(__file__).resolve().parents[2] / "data" / "cms_catalog.json"

_REQUEST_TIMEOUT = 120

# Distribution titles look like "... : 2025-01-02oc1" or "... : 2024-01-04".
# The leading 4-digit group is the performance year; the optional oc<N> suffix
# is the operational cut.
_VINTAGE_RE = re.compile(r"(?P<year>\d{4})-\d{2}-\d{2}\s*(?P<cut>oc\d)?\s*$", re.IGNORECASE)


@dataclass(frozen=True)
class Vintage:
    """One published vintage of the PUF: a performance year at a given cut."""

    year: int
    data_cut: str          # "FINAL", "OC1", "OC2", "OC3"
    dataset_id: str        # current CMS Data API UUID -- treated as volatile
    label: str             # raw CMS vintage label, e.g. "2025-01-02oc1"
    api_url: str
    csv_url: str | None = None

    @property
    def key(self) -> str:
        return f"{self.year}:{self.data_cut}"


class CatalogError(RuntimeError):
    """Raised when the catalog cannot be resolved and no cache is usable."""


class CMSCatalog:
    """Title-keyed resolver for CMS Data API dataset endpoints.

    Example::

        cat = CMSCatalog.load()               # network, falling back to cache
        v   = cat.vintage(2025, "FINAL")      # -> Vintage(dataset_id=...)
        cat.latest_years(2)                   # -> [2025, 2024]
    """

    def __init__(self, vintages: Iterable[Vintage], fetched_at: str, source: str) -> None:
        self.vintages: list[Vintage] = sorted(
            vintages, key=lambda v: (v.year, v.data_cut), reverse=True
        )
        self.fetched_at = fetched_at
        self.source = source  # "live" | "cache"

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    @classmethod
    def load(
        cls,
        cache_path: Path | str | None = DEFAULT_CACHE_PATH,
        allow_network: bool = True,
    ) -> "CMSCatalog":
        """Resolve the catalog, preferring live data and falling back to cache.

        Never raises on a network failure alone -- that is the whole point.  It
        raises ``CatalogError`` only when live resolution fails *and* no cache
        is available, because at that point there is genuinely nothing to build
        from.
        """
        cache_path = Path(cache_path) if cache_path else None

        if allow_network:
            try:
                catalog = cls.from_network()
                if cache_path:
                    catalog.save(cache_path)
                return catalog
            except Exception as exc:  # noqa: BLE001 - degrade, do not crash
                logger.warning("Live CMS catalog resolution failed (%s); trying cache.", exc)

        if cache_path and cache_path.exists():
            catalog = cls.from_cache(cache_path)
            logger.warning(
                "Using cached CMS catalog from %s (%d vintages). Endpoints may be stale.",
                catalog.fetched_at,
                len(catalog.vintages),
            )
            return catalog

        raise CatalogError(
            "Could not resolve the CMS catalog from the network and no cache is "
            f"available at {cache_path}."
        )

    @classmethod
    def from_network(cls, title: str = MSSP_COUNTY_PUF_TITLE) -> "CMSCatalog":
        response = requests.get(CATALOG_URL, timeout=_REQUEST_TIMEOUT)
        response.raise_for_status()
        payload = response.json()

        entry = _find_dataset(payload.get("dataset", []), title)
        if entry is None:
            raise CatalogError(f"Dataset titled {title!r} not present in {CATALOG_URL}.")

        vintages = _parse_distributions(entry.get("distribution", []))
        if not vintages:
            raise CatalogError(f"No parseable API distributions for dataset {title!r}.")

        return cls(
            vintages=vintages,
            fetched_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            source="live",
        )

    @classmethod
    def from_cache(cls, path: Path | str) -> "CMSCatalog":
        blob = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(
            vintages=[Vintage(**v) for v in blob["vintages"]],
            fetched_at=blob.get("fetched_at", "unknown"),
            source="cache",
        )

    def save(self, path: Path | str) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "catalog_url": CATALOG_URL,
            "dataset_title": MSSP_COUNTY_PUF_TITLE,
            "fetched_at": self.fetched_at,
            "vintages": [asdict(v) for v in self.vintages],
        }
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    # ------------------------------------------------------------------
    # Lookup
    # ------------------------------------------------------------------

    def vintage(self, year: int, data_cut: str = "FINAL") -> Vintage | None:
        cut = data_cut.upper()
        for v in self.vintages:
            if v.year == year and v.data_cut == cut:
                return v
        return None

    def years(self) -> list[int]:
        """All performance years present, newest first."""
        return sorted({v.year for v in self.vintages}, reverse=True)

    def latest_years(self, n: int = 2, data_cut: str = "FINAL") -> list[int]:
        """The *n* most recent years publishing the requested cut, newest first.

        Callers should use this instead of hard-coding a year.  Hard-coded years
        were the second half of the original outage: the endpoint moved *and*
        the year filter no longer matched what the endpoint served.
        """
        cut = data_cut.upper()
        available = sorted({v.year for v in self.vintages if v.data_cut == cut}, reverse=True)
        return available[:n]

    def cuts_for_year(self, year: int) -> list[str]:
        order = {"OC1": 0, "OC2": 1, "OC3": 2, "FINAL": 3}
        cuts = {v.data_cut for v in self.vintages if v.year == year}
        return sorted(cuts, key=lambda c: order.get(c, 99))


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _find_dataset(datasets: list[dict[str, Any]], title: str) -> dict[str, Any] | None:
    needle = title.strip().lower()
    for entry in datasets:
        if entry.get("title", "").strip().lower().startswith(needle):
            return entry
    return None


def _parse_distributions(distributions: list[dict[str, Any]]) -> list[Vintage]:
    """Turn DCAT distributions into Vintage records, pairing API and CSV URLs.

    CMS emits one distribution per format per vintage.  The parent dataset's own
    UUID also appears as an API distribution aliased to the newest vintage; it is
    dropped in favour of the vintage-specific UUID so nothing silently follows
    "whatever is newest".
    """
    api_by_label: dict[str, list[str]] = {}
    csv_by_label: dict[str, str] = {}

    for dist in distributions:
        label = _vintage_label(dist.get("title", ""))
        if not label:
            continue
        url = dist.get("accessURL") or dist.get("downloadURL") or ""
        fmt = (dist.get("format") or "").upper()
        if fmt == "API" and "/data-api/v1/dataset/" in url:
            api_by_label.setdefault(label, []).append(url)
        elif fmt == "CSV" and url:
            csv_by_label.setdefault(label, url)

    newest_label = max(api_by_label, key=_label_sort_key, default=None)
    vintages: list[Vintage] = []

    for label, urls in api_by_label.items():
        parsed = _VINTAGE_RE.search(label)
        if not parsed:
            continue
        # The alias UUID and the vintage UUID both appear on the newest label.
        # data.json lists the alias first, so prefer the last entry there.
        url = urls[-1] if (label == newest_label and len(urls) > 1) else urls[0]
        dataset_id = url.rstrip("/").split("/dataset/")[-1].split("/")[0]
        cut = (parsed.group("cut") or "FINAL").upper()
        vintages.append(
            Vintage(
                year=int(parsed.group("year")),
                data_cut=cut,
                dataset_id=dataset_id,
                label=label,
                api_url=url,
                csv_url=csv_by_label.get(label),
            )
        )

    return vintages


def _vintage_label(title: str) -> str | None:
    """Extract "2025-01-02oc1" from a full distribution title."""
    tail = title.rsplit(":", 1)[-1].strip()
    return tail if _VINTAGE_RE.search(tail) else None


def _label_sort_key(label: str) -> tuple[int, str]:
    match = _VINTAGE_RE.search(label)
    return (int(match.group("year")) if match else 0, label)
