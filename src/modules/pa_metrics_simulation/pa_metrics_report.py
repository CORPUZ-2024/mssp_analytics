from __future__ import annotations

import pandas as pd

from .pa_metrics_simulation import simulate_pa_metrics


def build_pa_metrics_report(df: pd.DataFrame) -> pd.DataFrame:
    """Create a simulated prior authorization metric report from MSSP proxy fields."""
    report = simulate_pa_metrics(df)
    if report.empty:
        return report

    metrics = report.copy()
    metrics["standard_approval_rate"] = (metrics["approved_requests"] / metrics["standard_requests"].replace({0: pd.NA})).clip(0, 1)
    metrics["expedited_approval_rate"] = (metrics["expedited_approved"] / metrics["expedited_requests"].replace({0: pd.NA})).clip(0, 1)
    return metrics
