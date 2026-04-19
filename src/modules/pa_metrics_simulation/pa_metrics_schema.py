from __future__ import annotations

from dataclasses import dataclass, field


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

    def __post_init__(self) -> None:
        """Validate CMS-0057-F schema constraints per v5 spec.

        Fields 2+3 (standard approved + denied) must sum to total_requests.
        Fields 6+7 (expedited approved + denied) must sum to expedited_requests.
        Field 4 denominator is denied_requests (NOT total_requests) — common
        implementation error is dividing by total, which understates overturn rate ~12x.
        """
        # Fields 2+3 must account for all standard requests
        standard_total = self.approved_requests + self.denied_requests
        if self.total_requests > 0 and standard_total != self.total_requests:
            raise ValueError(
                f"Fields 2+3 sum mismatch: approved ({self.approved_requests}) + "
                f"denied ({self.denied_requests}) = {standard_total} "
                f"!= total_requests ({self.total_requests}). "
                "Standard approval + denial rates must sum to 100%."
            )

        # Fields 6+7 must account for all expedited requests
        if self.expedited_requests > 0:
            exp_total = self.expedited_approved + self.expedited_denied
            if exp_total != self.expedited_requests:
                raise ValueError(
                    f"Fields 6+7 sum mismatch: expedited_approved ({self.expedited_approved}) + "
                    f"expedited_denied ({self.expedited_denied}) = {exp_total} "
                    f"!= expedited_requests ({self.expedited_requests}). "
                    "Expedited approval + denial rates must sum to 100%."
                )

    @property
    def standard_approval_rate(self) -> float:
        """Field 2 — % standard requests approved."""
        if self.total_requests == 0:
            return 0.0
        return self.approved_requests / self.total_requests

    @property
    def standard_denial_rate(self) -> float:
        """Field 3 — % standard requests denied. Enforces F2+F3 = 100%."""
        return 1.0 - self.standard_approval_rate

    def appeal_overturn_rate(self, appeals_overturn_count: int) -> float:
        """Field 4 — % approved after appeal.

        CRITICAL: denominator is denied_requests, NOT total_requests.
        Dividing by total understates the overturn rate by approximately 12x
        (since ~7.7% of requests are denied on average).
        """
        if self.denied_requests == 0:
            return 0.0
        return appeals_overturn_count / self.denied_requests

    @property
    def expedited_approval_rate(self) -> float:
        """Field 6 — % expedited requests approved."""
        if self.expedited_requests == 0:
            return 0.0
        return self.expedited_approved / self.expedited_requests

    @property
    def expedited_denial_rate(self) -> float:
        """Field 7 — % expedited requests denied. Enforces F6+F7 = 100%."""
        return 1.0 - self.expedited_approval_rate


@dataclass
class PriorAuthMetric:
    metric_name: str
    value: float
    unit: str
    source_type: str = "derived"  # derived | external | constant | simulated
    note: str | None = None

    VALID_SOURCE_TYPES = frozenset({"derived", "external", "constant", "simulated"})

    def __post_init__(self) -> None:
        if self.source_type not in self.VALID_SOURCE_TYPES:
            raise ValueError(
                f"source_type must be one of {sorted(self.VALID_SOURCE_TYPES)}, "
                f"got {self.source_type!r}"
            )


# ---------------------------------------------------------------------------
# Source type definitions per v5 spec
# ---------------------------------------------------------------------------
PA_FIELD_SOURCE_TYPES: dict[int, dict[str, str]] = {
    1: {
        "name":        "List of PA-required items and services",
        "source_type": "constant",
        "note":        "CMS DMEPOS Required Prior Authorization List (updated Jan 2026). Drugs excluded per CMS-0057-F.",
    },
    2: {
        "name":        "% standard requests approved",
        "source_type": "derived",
        "note":        "MSSP specialty utilization rate as weak proxy. PUF captures aggregate expenditure, not authorization event counts — proxy relationship unvalidated.",
    },
    3: {
        "name":        "% standard requests denied",
        "source_type": "derived",
        "note":        "Inverse of Field 2. Fields 2+3 must sum to 100%. Validated in pa_metrics_schema.py.",
    },
    4: {
        "name":        "% approved after appeal",
        "source_type": "external",
        "note":        "National benchmark constant applied uniformly — not a county-level simulation. Denominator is denied decisions, not total decisions. KFF MA 2024: >80% overturned. Using 61–80% band for ACO-adjacent populations.",
    },
    5: {
        "name":        "% extended review then approved",
        "source_type": "simulated",
        "note":        "Assumed constant — no public benchmark. Modeled at 4% (range 2–6%) from UM literature. No FFS equivalent. No validation possible — included for schema completeness only.",
    },
    6: {
        "name":        "% expedited requests approved",
        "source_type": "derived",
        "note":        "MSSP urgent utilization rate proxy. 72-hour TAT required per CMS-0057-F effective Jan 1, 2026.",
    },
    7: {
        "name":        "% expedited requests denied",
        "source_type": "derived",
        "note":        "Inverse of Field 6. Fields 6+7 must sum to 100%. Higher expedited denial signals CMS-0057-F audit scrutiny.",
    },
}
