from __future__ import annotations

import pandas as pd

# ---------------------------------------------------------------------------
# MSSP track parameters
# Source: CMS MSSP Participation Agreement + MSSP final rule (42 CFR § 425)
# ---------------------------------------------------------------------------

TRACK_PARAMS: dict[str, dict[str, object]] = {
    "A": {
        "sharing_rate": 0.50,        # 50% of savings shared with ACO
        "loss_sharing_rate": 0.0,    # Track A: one-sided (savings only)
        "msr_base": 0.0350,          # 3.5% for ≤5K beneficiaries
        "msr_floor": 0.0200,         # scales to 2% at ≥60K
        "two_sided": False,
        "description": "Track A — one-sided, 50% shared savings",
    },
    "B": {
        "sharing_rate": 0.60,
        "loss_sharing_rate": 0.60,   # Track B: two-sided, symmetrical
        "msr_base": 0.0200,          # Lower MSR because ACO bears downside
        "msr_floor": 0.0200,
        "two_sided": True,
        "description": "Track B — two-sided, 60% shared savings / loss",
    },
    "ENHANCED": {
        "sharing_rate": 0.75,
        "loss_sharing_rate": 0.75,
        "msr_base": 0.0200,
        "msr_floor": 0.0200,
        "two_sided": True,
        "description": "ENHANCED — two-sided, 75% shared savings / loss",
    },
}


def calculate_msr_threshold(
    person_years: pd.Series,
    msr_base: float = 0.035,
    msr_floor: float = 0.020,
    size_lower: float = 5_000,
    size_upper: float = 60_000,
) -> pd.Series:
    """Scale MSR from *msr_base* for small ACOs down to *msr_floor* for large ones.

    Linear interpolation between *size_lower* and *size_upper* person-years.
    Mirrors the CMS MSSP Participation Agreement sliding MSR table.
    """
    py = person_years.fillna(0)
    span = size_upper - size_lower
    rate = (msr_base - msr_floor) / span

    thresholds = pd.Series(msr_base, index=py.index)
    in_range = (py > size_lower) & (py < size_upper)
    thresholds.loc[in_range] = msr_base - (py.loc[in_range] - size_lower) * rate
    thresholds.loc[py >= size_upper] = msr_floor
    return thresholds


def calculate_shared_savings(
    df: pd.DataFrame,
    actual_col: str = "per_capita_exp",
    benchmark_col: str = "benchmark_per_capita_exp",
    person_years_col: str = "person_years",
    track: str = "A",
) -> pd.DataFrame:
    """Calculate shared savings/loss and assign status labels.

    Adds columns:
    - ``shared_savings_ratio``: (benchmark − actual) / benchmark
    - ``net_aco_savings_ratio``: share of savings retained by the ACO after
      applying the track sharing rate
    - ``msr_threshold``: minimum savings rate required to qualify
    - ``shared_savings_status``: categorical label

    Args:
        df:             Input dataframe with expenditure and benchmark columns.
        actual_col:     Column with actual per-capita expenditure.
        benchmark_col:  Column with risk-adjusted benchmark.
        person_years_col: Used to size-adjust the MSR threshold.
        track:          MSSP track — ``"A"``, ``"B"``, or ``"ENHANCED"``.
    """
    if actual_col not in df.columns or benchmark_col not in df.columns:
        raise ValueError(
            f"Required columns missing for shared savings calculation: "
            f"{actual_col!r}, {benchmark_col!r}"
        )

    params = TRACK_PARAMS.get(track.upper(), TRACK_PARAMS["A"])
    sharing_rate: float = float(params["sharing_rate"])
    loss_sharing_rate: float = float(params["loss_sharing_rate"])
    msr_base: float = float(params["msr_base"])
    msr_floor: float = float(params["msr_floor"])
    two_sided: bool = bool(params["two_sided"])

    df = df.copy()
    benchmark = df[benchmark_col].replace({0: pd.NA})
    df["shared_savings_ratio"] = (df[benchmark_col] - df[actual_col]) / benchmark
    df["net_aco_savings_ratio"] = df["shared_savings_ratio"].apply(
        lambda v: v * sharing_rate if (pd.notna(v) and v >= 0)
        else (v * loss_sharing_rate if (pd.notna(v) and two_sided)
              else 0.0)
    )

    if person_years_col in df.columns:
        df["msr_threshold"] = calculate_msr_threshold(
            df[person_years_col], msr_base=msr_base, msr_floor=msr_floor
        )
    else:
        df["msr_threshold"] = msr_base

    df["shared_savings_status"] = [
        _categorize(ratio, msr, two_sided)
        for ratio, msr in zip(df["shared_savings_ratio"], df["msr_threshold"])
    ]
    df["mssp_track"] = track.upper()
    return df


def _categorize(value: float | None, msr: float, two_sided: bool) -> str:
    if pd.isna(value):
        return "unknown"
    if value >= msr:
        return "qualified_savings"
    if 0 < value < msr:
        return "savings_below_msr"
    if value == 0:
        return "break_even"
    # Negative (loss)
    if two_sided:
        return "shared_loss"
    return "loss_not_shared"
