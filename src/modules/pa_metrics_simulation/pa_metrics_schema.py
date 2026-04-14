from __future__ import annotations

from dataclasses import dataclass


@dataclass
class PriorAuthMetricRecord:
    county_id: str
    state_id: str
    enrollment_type: str
    year: str
    total_requests: int
    approved_requests: int
    denied_requests: int
    appeals_overturned: int
    expedited_requests: int
    expedited_approved: int
    expedited_denied: int


@dataclass
class PriorAuthMetric:
    metric_name: str
    value: float
    unit: str
    note: str | None = None
