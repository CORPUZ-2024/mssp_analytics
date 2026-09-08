from __future__ import annotations

"""Build the static GitHub Pages payload for the MSSP analytics dashboard.

Design contract
---------------
The published page must never talk to data.cms.gov.  All CMS access happens
here, at build time, in CI.  The build writes versioned JSON into ``docs/data/``
which is committed to the repository and served by GitHub Pages.  Consequences:

* A CMS URL change, UUID rotation, schema change or outage can fail *the build*.
  It cannot break the published page, which keeps serving the last good payload.
* Every payload carries provenance (which dataset UUIDs, which vintages, when),
  so a stale page is visibly stale rather than quietly wrong.

The build is transactional: data is staged to a temporary directory, run through
quality gates, and only then swapped into ``docs/data/``.  A failed gate leaves
the previous payload untouched and exits non-zero so CI reports the failure.

Usage::

    python -m src.build_site                 # normal build
    python -m src.build_site --check-only    # gates only, no publish
    python -m src.build_site --offline       # use the cached catalog
"""

import argparse
import json
import logging
import math
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.etl.catalog import CMSCatalog, CatalogError  # noqa: E402
from src.etl.client import UpstreamDataError, fetch_vintages  # noqa: E402
from src.etl.enrich import DataEnricher  # noqa: E402
from src.etl.ingest import DataIngestor  # noqa: E402
from src.modules.hcc_radv_risk_flags.v28_exposure_index import (  # noqa: E402
    ENROLLMENT_HCC_WEIGHTS,
    HCC_V28_DELTA,
)
from src.modules.pa_metrics_simulation.pa_metrics_report import (  # noqa: E402
    build_cms_field_table,
    build_cms_field_table_from_disclosures,
    build_pa_metrics_report,
)
from src.modules.shared_savings_model.benchmark_version_skew import (  # noqa: E402
    build_enrollment_type_skew_summary,
)
from src.modules.shared_savings_model.shared_savings_calc import TRACK_PARAMS  # noqa: E402

logger = logging.getLogger("build_site")

REPO_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = REPO_ROOT / "docs" / "data"
DISCLOSURES_CSV = REPO_ROOT / "disclosures_metrics.csv"

# Quality gates. A build that trips one of these does not get published --
# publishing a degraded payload over a good one is worse than staying stale.
MIN_COUNTY_ROWS = 8_000        # ~3,200 counties x 4 enrollment types, with slack
MIN_STATES = 45
MIN_NON_NULL_SHARE = 0.75      # of avg_risk_score / per_capita_exp on the latest year
MIN_YOY_COVERAGE = 0.50        # share of latest-year rows that got a YoY delta

ENROLLMENT_TYPES = ["ESRD", "Disabled", "Aged Dual", "Aged Non-Dual"]


class BuildError(RuntimeError):
    """Raised when the build cannot produce a payload worth publishing."""


# ---------------------------------------------------------------------------
# Extract
# ---------------------------------------------------------------------------

def resolve_plan(catalog: CMSCatalog) -> dict[str, Any]:
    """Decide which vintages to pull, from the catalog rather than from constants.

    The years are *discovered*, never hard-coded: the previous build pinned 2024
    and silently returned nothing once CMS moved on to 2025.
    """
    final_years = catalog.latest_years(2, data_cut="FINAL")
    if not final_years:
        raise BuildError("Catalog exposes no FINAL vintage for any year.")

    latest = final_years[0]
    prior = final_years[1] if len(final_years) > 1 else None

    # Operational cuts for the latest year drive the OC-stability analysis.
    oc_cuts = [c for c in catalog.cuts_for_year(latest) if c.startswith("OC")]

    return {
        "latest_year": latest,
        "prior_year": prior,
        "final_years": final_years,
        "oc_cuts": oc_cuts,
        "required": [(y, "FINAL") for y in final_years],
        "optional": [(latest, c) for c in oc_cuts],
    }


def extract(catalog: CMSCatalog, plan: dict[str, Any]) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Fetch the required FINAL cuts and the optional OC cuts.

    FINAL vintages are required -- without them there is no dashboard.  OC
    vintages are optional: losing one degrades a single chart, so the build
    continues and records the gap in the manifest.
    """
    final_raw = fetch_vintages(catalog, plan["required"], required=True)

    oc_raw = pd.DataFrame()
    if plan["optional"]:
        try:
            oc_raw = fetch_vintages(catalog, plan["optional"], required=False)
        except UpstreamDataError as exc:
            logger.warning("No OC vintages available (%s); OC-stability chart will be empty.", exc)

    return final_raw, oc_raw


# ---------------------------------------------------------------------------
# Transform
# ---------------------------------------------------------------------------

def transform(raw: pd.DataFrame) -> pd.DataFrame:
    """Run the existing ETL: normalise columns, coerce dtypes, add pilot flags."""
    df = DataIngestor().process_dataframe(raw)
    df = DataEnricher().enrich(df)
    for col in ("avg_risk_score", "per_capita_exp", "person_years", "avg_demog_score"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def add_yoy_columns(final_df: pd.DataFrame, latest_year: int) -> pd.DataFrame:
    """Attach YoY risk and expenditure deltas to the latest-year rows.

    Computed by an explicit prior-year join rather than a ``groupby().shift()``:
    with several operational cuts in the frame a positional shift can pair a
    FINAL row with an OC row of the same year and silently invent a delta.
    """
    keys = ["state_id", "county_id", "enrollment_type"]
    latest = final_df[final_df["year"].astype(str) == str(latest_year)].copy()

    prior_years = sorted(
        {int(y) for y in final_df["year"].astype(int).unique() if int(y) < latest_year},
        reverse=True,
    )
    if not prior_years:
        latest["risk_score_yoy_delta"] = pd.NA
        latest["exp_growth_ratio"] = pd.NA
        return latest

    prior = final_df[final_df["year"].astype(int) == prior_years[0]]
    prior = prior[keys + ["avg_risk_score", "per_capita_exp"]].rename(
        columns={"avg_risk_score": "prev_risk_score", "per_capita_exp": "prev_per_capita_exp"}
    )
    prior = prior.drop_duplicates(subset=keys)

    merged = latest.merge(prior, on=keys, how="left")
    merged["risk_score_yoy_delta"] = (
        merged["avg_risk_score"] - merged["prev_risk_score"]
    ) / merged["prev_risk_score"].replace({0: pd.NA})
    merged["exp_growth_ratio"] = (
        merged["per_capita_exp"] - merged["prev_per_capita_exp"]
    ) / merged["prev_per_capita_exp"].replace({0: pd.NA})
    return merged


def add_oc_delta(latest_df: pd.DataFrame, oc_df: pd.DataFrame) -> pd.DataFrame:
    """Attach the earliest-OC -> FINAL risk-score movement to each latest-year row.

    Feeds the "OC stability" column of the ranked table, which the Streamlit
    build could only ever render as a dash: it fetched one cut, so the
    ``data_cut`` column never existed.
    """
    latest_df = latest_df.copy()
    if oc_df.empty:
        latest_df["oc_delta"] = pd.NA
        return latest_df

    keys = ["state_id", "county_id", "enrollment_type"]
    first_cut = sorted(oc_df["data_cut"].unique())[0]
    base = (
        oc_df[oc_df["data_cut"] == first_cut][keys + ["avg_risk_score"]]
        .rename(columns={"avg_risk_score": "_oc_base"})
        .drop_duplicates(subset=keys)
    )
    merged = latest_df.merge(base, on=keys, how="left")
    merged["oc_delta"] = (
        merged["avg_risk_score"] - merged["_oc_base"]
    ) / merged["_oc_base"].replace({0: pd.NA})
    return merged.drop(columns=["_oc_base"])


def build_oc_stability(oc_df: pd.DataFrame, final_latest: pd.DataFrame) -> dict[str, Any]:
    """OC1 -> FINAL risk-score movement per county, from real vintages.

    The Streamlit build could never populate this chart -- it fetched a single
    cut, so ``data_cut`` never existed and the panel fell back to a hard-coded
    illustration.  Resolving cuts from the catalog makes it real data.
    """
    if oc_df.empty:
        return {"available": False, "cuts": [], "series": [], "national": []}

    keys = ["state_id", "county_id", "enrollment_type"]
    final_slice = final_latest[keys + ["avg_risk_score", "state_name", "county_name"]].rename(
        columns={"avg_risk_score": "FINAL"}
    )

    frames = [final_slice]
    cuts = sorted(oc_df["data_cut"].unique())
    for cut in cuts:
        slice_ = (
            oc_df[oc_df["data_cut"] == cut][keys + ["avg_risk_score"]]
            .rename(columns={"avg_risk_score": cut})
            .drop_duplicates(subset=keys)
        )
        frames.append(slice_)

    wide = frames[0]
    for frame in frames[1:]:
        wide = wide.merge(frame, on=keys, how="inner")

    cut_order = cuts + ["FINAL"]
    first_cut = cut_order[0]
    wide = wide.dropna(subset=cut_order)
    if wide.empty:
        return {"available": False, "cuts": [], "series": [], "national": []}

    wide["oc_delta"] = (wide["FINAL"] - wide[first_cut]) / wide[first_cut].replace({0: pd.NA})

    # National mean trajectory per cut, plus the largest movers, which is what
    # the "late coding" read actually depends on.
    national = [float(wide[c].mean()) for c in cut_order]
    movers = wide.reindex(wide["oc_delta"].abs().sort_values(ascending=False).index).head(6)

    series = [
        {
            "label": f"{str(row['county_name']).title()}, {str(row['state_name']).title()}"
            f" ({row['enrollment_type']})",
            "values": [_num(row[c]) for c in cut_order],
            "delta": _num(row["oc_delta"]),
        }
        for _, row in movers.iterrows()
    ]

    return {
        "available": True,
        "cuts": cut_order,
        "series": series,
        "national": [_num(v) for v in national],
        "n_counties": int(len(wide)),
        "stable_high_count": int(
            ((wide["oc_delta"].abs() < 0.02) & (wide["FINAL"] > wide["FINAL"].mean() + wide["FINAL"].std(ddof=0))).sum()
        ),
    }


# ---------------------------------------------------------------------------
# Payload assembly
# ---------------------------------------------------------------------------

def build_county_payload(df: pd.DataFrame) -> dict[str, Any]:
    """Encode county rows as parallel index arrays, not objects.

    Repeating twelve JSON keys across ~13,000 rows roughly triples the payload
    for no benefit.  State and county names are interned into lookup tables and
    referenced by index.
    """
    df = df.copy()
    df["state_name"] = df["state_name"].astype(str).str.strip().str.title()
    df["county_name"] = df["county_name"].astype(str).str.strip().str.title()

    states = sorted(df["state_name"].unique())
    state_index = {name: i for i, name in enumerate(states)}

    county_keys = (
        df[["state_name", "county_name", "state_id", "county_id"]]
        .drop_duplicates()
        .sort_values(["state_name", "county_name"])
        .reset_index(drop=True)
    )
    county_index = {
        (row.state_id, row.county_id): i for i, row in county_keys.iterrows()
    }
    counties = [
        [state_index[row.state_name], row.county_name, str(row.state_id), str(row.county_id)]
        for _, row in county_keys.iterrows()
    ]

    enroll_index = {name: i for i, name in enumerate(ENROLLMENT_TYPES)}

    rows: list[list[Any]] = []
    for row in df.itertuples(index=False):
        key = (row.state_id, row.county_id)
        if key not in county_index:
            continue
        rows.append(
            [
                county_index[key],
                enroll_index.get(row.enrollment_type, 0),
                _num(row.avg_risk_score, 5),
                _num(row.per_capita_exp, 2),
                _num(row.avg_demog_score, 5),
                _num(row.person_years, 2),
                _num(getattr(row, "risk_score_yoy_delta", None), 6),
                _num(getattr(row, "exp_growth_ratio", None), 6),
                _num(getattr(row, "oc_delta", None), 6),
                1 if bool(getattr(row, "composite_confounded", False)) else 0,
            ]
        )

    return {
        "columns": [
            "county", "enrollment", "risk", "exp", "demog",
            "person_years", "yoy_delta", "exp_growth", "oc_delta", "confounded",
        ],
        "states": states,
        "counties": counties,
        "enrollment_types": ENROLLMENT_TYPES,
        "rows": rows,
    }


def add_confound_flags(df: pd.DataFrame, latest_year: int) -> pd.DataFrame:
    """Reproduce the v5 confound flags, which do not depend on user filters."""
    df = df.copy()
    df["team_county_flag"] = df.get("team_model_flag", pd.Series(False, index=df.index)).astype(bool)
    df["v28_transition_year_flag"] = df["year"].astype(str).str.strip() == "2024"
    df["enrollment_type_shift_flag"] = df["enrollment_type"].astype(str).str.strip().isin(
        {"ESRD", "Disabled"}
    )
    df["composite_confounded"] = (
        df["team_county_flag"] | df["v28_transition_year_flag"] | df["enrollment_type_shift_flag"]
    )
    return df


def build_reference_payload(latest_df: pd.DataFrame) -> dict[str, Any]:
    """Constants, regulatory parameters and the Module C tables.

    These are recomputed in the browser from the same numbers the Streamlit app
    used, so the client stays a pure function of this payload.
    """
    skew = build_enrollment_type_skew_summary()

    # Per-enrollment-type V28 raw exposure score, single-sourced from the Python
    # constants so the JS never re-encodes the HCC weight tables.
    v28_raw = {
        etype: round(
            sum(HCC_V28_DELTA.get(hcc, 0.0) * weight for hcc, weight in weights.items()), 6
        )
        for etype, weights in ENROLLMENT_HCC_WEIGHTS.items()
    }

    disclosures: list[dict[str, Any]] = []
    disclosure_fields: list[dict[str, Any]] = []
    if DISCLOSURES_CSV.exists():
        disclosures_df = pd.read_csv(DISCLOSURES_CSV)
        disclosures = json.loads(disclosures_df.to_json(orient="records"))
        table = build_cms_field_table_from_disclosures(disclosures_df)
        if not table.empty:
            disclosure_fields = json.loads(table.to_json(orient="records"))

    pa_working = latest_df.copy()
    max_exp = pa_working["per_capita_exp"].max()
    pa_working["specialty_utilization_rate"] = (
        pa_working["per_capita_exp"].fillna(0) / max_exp if max_exp else 0.1
    )
    pa_report = build_pa_metrics_report(pa_working)
    pa_fields = (
        json.loads(build_cms_field_table(pa_report).to_json(orient="records"))
        if not pa_report.empty
        else []
    )

    pa_summary: dict[str, Any] = {}
    if not pa_report.empty:
        pa_summary = {
            "approved_rate": _num(pa_report["approved_rate"].mean(), 6),
            "denied_rate": _num(pa_report["denied_rate"].mean(), 6),
            "appeal_overturn_rate": _num(pa_report["appeal_overturn_rate"].mean(), 6),
            "extended_review_rate": _num(pa_report["extended_review_rate"].mean(), 6),
        }

    pa_burden: list[dict[str, Any]] = []
    if not pa_report.empty and {"total_requests", "county_id"}.issubset(pa_report.columns):
        burden = pa_report.copy()
        burden["admin_hrs_per_1k"] = (
            burden["denied_rate"].fillna(0) * burden["total_requests"].fillna(0) * 0.013
        ).round(1)
        top = burden.groupby("county_id")["admin_hrs_per_1k"].mean().nlargest(8).reset_index()
        pa_burden = [
            {"county": str(r.county_id), "hours": _num(r.admin_hrs_per_1k, 1)}
            for r in top.itertuples(index=False)
        ]

    return {
        "v28_skew": json.loads(skew.to_json(orient="records")),
        "v28_raw_exposure": v28_raw,
        "track_params": {
            key: {k: v for k, v in params.items() if k != "description"}
            for key, params in TRACK_PARAMS.items()
        },
        "benchmark": {"trend_factor": 1.02, "v24_factor": 1.03, "v28_factor": 0.97},
        "disclosures": disclosures,
        "disclosure_fields": disclosure_fields,
        "pa_fields": pa_fields,
        "pa_summary": pa_summary,
        "pa_burden": pa_burden,
    }


# ---------------------------------------------------------------------------
# Quality gates
# ---------------------------------------------------------------------------

def run_quality_gates(county_payload: dict[str, Any], latest_df: pd.DataFrame) -> list[str]:
    """Assert the payload is worth publishing. Returns a list of failures."""
    failures: list[str] = []

    n_rows = len(county_payload["rows"])
    if n_rows < MIN_COUNTY_ROWS:
        failures.append(f"Only {n_rows:,} county rows (expected >= {MIN_COUNTY_ROWS:,}).")

    n_states = len(county_payload["states"])
    if n_states < MIN_STATES:
        failures.append(f"Only {n_states} states present (expected >= {MIN_STATES}).")

    for col in ("avg_risk_score", "per_capita_exp"):
        share = float(latest_df[col].notna().mean()) if col in latest_df.columns else 0.0
        if share < MIN_NON_NULL_SHARE:
            failures.append(
                f"Column {col} is only {share:.1%} populated (expected >= {MIN_NON_NULL_SHARE:.0%})."
            )

    if "risk_score_yoy_delta" in latest_df.columns:
        coverage = float(latest_df["risk_score_yoy_delta"].notna().mean())
        if coverage < MIN_YOY_COVERAGE:
            failures.append(
                f"YoY delta covers only {coverage:.1%} of rows (expected >= {MIN_YOY_COVERAGE:.0%})."
            )

    missing = set(ENROLLMENT_TYPES) - set(latest_df["enrollment_type"].unique())
    if missing:
        failures.append(f"Missing enrollment types: {sorted(missing)}.")

    return failures


# ---------------------------------------------------------------------------
# Publish
# ---------------------------------------------------------------------------

def publish(staged: Path, destination: Path) -> None:
    """Swap a validated staging directory into place.

    Written as replace-after-validate so a partial or failed build never leaves
    ``docs/data`` half-updated: the page either serves the new payload in full
    or keeps serving the previous one.
    """
    destination.parent.mkdir(parents=True, exist_ok=True)
    backup = destination.with_name(destination.name + ".prev")
    if backup.exists():
        shutil.rmtree(backup)
    if destination.exists():
        destination.rename(backup)
    try:
        shutil.copytree(staged, destination)
    except Exception:
        if backup.exists() and not destination.exists():
            backup.rename(destination)
        raise
    if backup.exists():
        shutil.rmtree(backup)


def _num(value: Any, places: int = 6) -> float | None:
    """JSON-safe rounded float. NaN and inf become null rather than invalid JSON."""
    if value is None:
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(out) or math.isinf(out):
        return None
    return round(out, places)


def _write(path: Path, payload: Any) -> int:
    path.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
    return path.stat().st_size


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def build(check_only: bool = False, offline: bool = False) -> dict[str, Any]:
    catalog = CMSCatalog.load(allow_network=not offline)
    plan = resolve_plan(catalog)
    logger.info(
        "Plan: FINAL %s, OC cuts %s for %s (catalog source: %s)",
        plan["final_years"],
        plan["oc_cuts"] or "none",
        plan["latest_year"],
        catalog.source,
    )

    final_raw, oc_raw = extract(catalog, plan)
    final_df = transform(final_raw)
    oc_df = transform(oc_raw) if not oc_raw.empty else pd.DataFrame()

    latest_df = add_yoy_columns(final_df, plan["latest_year"])
    latest_df = add_confound_flags(latest_df, plan["latest_year"])
    latest_df = add_oc_delta(latest_df, oc_df)

    county_payload = build_county_payload(latest_df)
    failures = run_quality_gates(county_payload, latest_df)
    if failures:
        raise BuildError("Quality gates failed:\n  - " + "\n  - ".join(failures))

    oc_payload = build_oc_stability(oc_df, latest_df)
    reference_payload = build_reference_payload(latest_df)

    vintages_used = [
        {
            "year": v.year,
            "data_cut": v.data_cut,
            "dataset_id": v.dataset_id,
            "label": v.label,
            "api_url": v.api_url,
        }
        for year, cut in plan["required"] + plan["optional"]
        if (v := catalog.vintage(year, cut)) is not None
    ]

    manifest = {
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "catalog_source": catalog.source,
        "catalog_fetched_at": catalog.fetched_at,
        "latest_year": plan["latest_year"],
        "prior_year": plan["prior_year"],
        "oc_cuts": plan["oc_cuts"],
        "oc_stability_available": oc_payload["available"],
        "county_rows": len(county_payload["rows"]),
        "states": len(county_payload["states"]),
        "counties": len(county_payload["counties"]),
        "vintages": vintages_used,
        "quality_gates": "passed",
    }

    if check_only:
        logger.info("Check-only run passed. Manifest: %s", json.dumps(manifest, indent=2))
        return manifest

    with tempfile.TemporaryDirectory() as tmp:
        staging = Path(tmp) / "data"
        staging.mkdir(parents=True)
        sizes = {
            "counties.json": _write(staging / "counties.json", county_payload),
            "oc_stability.json": _write(staging / "oc_stability.json", oc_payload),
            "reference.json": _write(staging / "reference.json", reference_payload),
        }
        manifest["payload_bytes"] = sizes
        _write(staging / "manifest.json", manifest)
        publish(staging, OUTPUT_DIR)

    logger.info(
        "Published %s: %d county rows, %d states. Payload %.1f KB.",
        OUTPUT_DIR,
        manifest["county_rows"],
        manifest["states"],
        sum(sizes.values()) / 1024,
    )
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the static MSSP dashboard payload.")
    parser.add_argument("--check-only", action="store_true", help="Validate without publishing.")
    parser.add_argument("--offline", action="store_true", help="Use the cached catalog only.")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)-8s %(name)s: %(message)s",
    )

    try:
        build(check_only=args.check_only, offline=args.offline)
    except (BuildError, CatalogError, UpstreamDataError) as exc:
        logger.error("Build failed: %s", exc)
        logger.error(
            "docs/data was left untouched -- the published page keeps serving the "
            "previous payload."
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
