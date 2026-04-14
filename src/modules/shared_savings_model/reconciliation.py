from __future__ import annotations

import pandas as pd

from .benchmark_constructor import build_benchmark
from .shared_savings_calc import calculate_shared_savings
from .team_episode_proxy import build_team_episode_proxy


def build_reconciliation(df: pd.DataFrame, track_type: str = "A") -> pd.DataFrame:
    """Assemble a full reconciliation dataset with benchmark and savings indicators.

    Steps:
    1. Build the V24 and V28 risk-adjusted benchmarks.
    2. Select the track-appropriate benchmark column.
    3. Calculate shared savings / loss ratios and MSR thresholds.
    4. Add TEAM episode proxy cost for flagged counties.
    5. Compute benchmark version skew (V24 vs. V28 methodology contribution).

    Args:
        df:         Cleaned MSSP PUF dataframe from the ETL pipeline.
        track_type: MSSP track — ``"A"``, ``"B"``, or ``"ENHANCED"``.
    """
    df = df.copy()
    df = build_benchmark(df)

    # Select track-appropriate benchmark (V28 base for all tracks; track
    # parameters affect sharing rate and MSR, not the benchmark value itself).
    df["benchmark_track_per_capita_exp"] = df["benchmark_per_capita_exp"]

    df = calculate_shared_savings(
        df,
        benchmark_col="benchmark_track_per_capita_exp",
        track=track_type,
    )
    df = build_team_episode_proxy(df)

    # Version skew: difference in simulated benchmark under V24 vs. V28
    if "benchmark_v24_per_capita_exp" in df.columns and "benchmark_v28_per_capita_exp" in df.columns:
        v28 = df["benchmark_v28_per_capita_exp"].replace({0: pd.NA})
        df["benchmark_version_skew"] = (
            (df["benchmark_v24_per_capita_exp"] - df["benchmark_v28_per_capita_exp"]) / v28
        )
    else:
        df["benchmark_version_skew"] = pd.NA

    return df
