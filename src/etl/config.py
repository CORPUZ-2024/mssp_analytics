from __future__ import annotations

from typing import Final

REQUIRED_COLUMNS: Final[tuple[str, ...]] = (
    "year",
    "state_id",
    "county_id",
    "dataset_id",
    "avg_risk_score",
    "per_capita_exp",
    "enrollment_type",
    "person_years",
)

NUMERIC_COLUMNS: Final[tuple[str, ...]] = (
    "avg_risk_score",
    "per_capita_exp",
    "person_years",
    "total_beneficiaries",
    "total_assignable_beneficiaries",
    "total_expenditure",
)

STRING_COLUMNS: Final[tuple[str, ...]] = (
    "year",
    "state_id",
    "county_id",
    "dataset_id",
    "state_name",
    "county_name",
    "enrollment_type",
    "data_cut",
)

# Dedup key: year + SSA county identifier pair. STATE_NAME / COUNTY_NAME
# are excluded — whitespace/case variation causes missed duplicates.
DEDUP_SUBSET: Final[tuple[str, ...]] = (
    "year",
    "state_id",
    "county_id",
    "dataset_id",
)

ALLOWED_DATA_CUTS: Final[tuple[str, ...]] = (
    "OC1",
    "OC2",
    "OC3",
    "FINAL",
    "FINAL_COVID_ADJUSTED",
)

# AHEAD model states (MD, CT, HI, VT, RI — select NY counties are not
# identifiable at the state level in the PUF, so NY is excluded here).
AHEAD_STATE_NAMES: Final[set[str]] = {
    "MARYLAND",
    "CONNECTICUT",
    "HAWAII",
    "VERMONT",
    "RHODE ISLAND",
}

# WISeR model states (AI utilization reduction — regulatory, not organic).
WISER_STATE_NAMES: Final[set[str]] = {
    "ARIZONA",
    "NEW JERSEY",
    "OHIO",
    "OKLAHOMA",
    "TEXAS",
    "WASHINGTON",
}

# TEAM model operates across ~25% of US CBSAs selected randomly; there is no
# state-level designation in the PUF. The enrich layer uses a deterministic
# hash proxy when no explicit CBSA flag column is present.
TEAM_STATE_NAMES: Final[set[str]] = set()

VALIDATION_WARNINGS: Final[tuple[str, ...]] = (
    "missing_required_columns",
    "invalid_dtypes",
    "out_of_range_values",
    "duplicate_conflict",
    "missing_key_columns",
)
