from __future__ import annotations

# ---------------------------------------------------------------------------
# MSSP PUF → FHIR R4 field mapping
# Source: US Core IG (hl7.org/fhir/us/core), CMS Blue Button 2.0,
#         CMS-0057-F required API specifications
# ---------------------------------------------------------------------------

# Fields that have a FHIR R4 equivalent path (complete or partial mapping).
# Gap fields (sav_rate, quality_score, etc.) are catalogued in PUF_FIELD_CATALOG
# but deliberately excluded from this map — there is no FHIR path to set.
FHIR_FIELD_MAP: dict[str, str] = {
    "avg_risk_score":    "RiskAssessment.prediction[0].probabilityDecimal",
    "per_capita_exp":    "ExplanationOfBenefit.total.amount.value",
    "enrollment_type":   "Coverage.type.coding.code",
    "year":              "ExplanationOfBenefit.billablePeriod.start",
    "state_id":          "Organization.address[0].state",
    "county_id":         "Organization.address[0].district",
    "n_ab_ben":          "Group.member.count",
    "quality_score":     "MeasureReport.group.measureScore",
}

# Complete field catalog including gap fields with no FHIR equivalent.
# This is the source of truth for the FHIR vs. PUF comparison analysis.
PUF_FIELD_CATALOG: list[dict[str, str | bool | None]] = [
    {
        "puf_field":      "avg_risk_score",
        "fhir_resource":  "RiskAssessment",
        "fhir_path":      "RiskAssessment.prediction[0].probabilityDecimal",
        "cms_0057f_api":  "Patient Access API",
        "support_status": "Partial",
        "gap":            False,
        "note": (
            "Risk prediction probability exists in FHIR R4, but CMS-HCC risk score "
            "semantics are not a direct match. V24/V28 blend methodology is not "
            "expressible in a standard RiskAssessment resource."
        ),
    },
    {
        "puf_field":      "per_capita_exp",
        "fhir_resource":  "ExplanationOfBenefit",
        "fhir_path":      "ExplanationOfBenefit.total.amount.value",
        "cms_0057f_api":  "Patient Access API",
        "support_status": "Yes",
        "gap":            False,
        "note": (
            "Expenditure totals are available in FHIR EOB resources. "
            "Enrollment-type breakdowns are not natively supported — "
            "require population-level aggregation outside the FHIR model."
        ),
    },
    {
        "puf_field":      "enrollment_type",
        "fhir_resource":  "Coverage",
        "fhir_path":      "Coverage.type.coding.code",
        "cms_0057f_api":  "Patient Access API",
        "support_status": "Partial",
        "gap":            False,
        "note": (
            "Patient coverage type exists in FHIR. MSSP enrollment categories "
            "(ESRD, Disabled, Aged Dual, Aged Non-Dual) require CMS-specific "
            "extensions not defined in US Core."
        ),
    },
    {
        "puf_field":      "year",
        "fhir_resource":  "ExplanationOfBenefit",
        "fhir_path":      "ExplanationOfBenefit.billablePeriod.start",
        "cms_0057f_api":  "Patient Access API",
        "support_status": "Yes",
        "gap":            False,
        "note":           "Claim billable period start maps cleanly to performance year.",
    },
    {
        "puf_field":      "state_id",
        "fhir_resource":  "Organization",
        "fhir_path":      "Organization.address[0].state",
        "cms_0057f_api":  "Provider Directory API",
        "support_status": "Yes",
        "gap":            False,
        "note":           "State from the FHIR Organization address; indirect for beneficiary attribution.",
    },
    {
        "puf_field":      "county_id",
        "fhir_resource":  "Organization",
        "fhir_path":      "Organization.address[0].district",
        "cms_0057f_api":  "Provider Directory API",
        "support_status": "Partial",
        "gap":            False,
        "note": (
            "District/county available in US Core Organization address. "
            "SSA county code to FHIR district value mapping is not standardised."
        ),
    },
    {
        "puf_field":      "n_ab_ben",
        "fhir_resource":  "Group",
        "fhir_path":      "Group.member.count",
        "cms_0057f_api":  "Provider Access API",
        "support_status": "Partial",
        "gap":            False,
        "note": (
            "FHIR Group resource can express member counts, but there is no "
            "US Core profile for enrollment-type-stratified beneficiary counts. "
            "CMS-specific extension required."
        ),
    },
    {
        "puf_field":      "quality_score",
        "fhir_resource":  "MeasureReport",
        "fhir_path":      "MeasureReport.group.measureScore",
        "cms_0057f_api":  "Patient Access API",
        "support_status": "Partial",
        "gap":            False,
        "note": (
            "HEDIS/CAHPS quality composites require custom FHIR Measure profiles. "
            "No standard US Core equivalent. CMS-0057-F does not mandate a "
            "quality composite resource — only individual measure reporting."
        ),
    },
    # --- GAP FIELDS: no FHIR R4 equivalent ---
    {
        "puf_field":      "sav_rate",
        "fhir_resource":  None,
        "fhir_path":      None,
        "cms_0057f_api":  "N/A",
        "support_status": "No mapping",
        "gap":            True,
        "note": (
            "Shared savings / loss rate has no FHIR R4 standard resource. "
            "CMS publishes this metric only in flat-file PUF format. "
            "This is a genuine interoperability gap: CMS-0057-F required APIs "
            "cannot express ACO financial performance without custom extensions."
        ),
    },
    {
        "puf_field":      "per_capita_exp_by_enrollment_type",
        "fhir_resource":  None,
        "fhir_path":      None,
        "cms_0057f_api":  "N/A",
        "support_status": "No mapping",
        "gap":            True,
        "note": (
            "Enrollment-type-stratified per-capita expenditure requires population-level "
            "aggregation that is not native to the FHIR resource model. "
            "ExplanationOfBenefit records are beneficiary-level; county-level "
            "enrollment-type aggregates must be computed outside FHIR."
        ),
    },
]


def map_puf_row_to_fhir(row: dict[str, object]) -> dict[str, object]:
    """Map a single PUF row to a simplified FHIR field dictionary.

    Only fields with a non-None FHIR path are included in the output.
    Gap fields are silently excluded — callers should reference
    ``PUF_FIELD_CATALOG`` to identify them.
    """
    return {
        fhir_path: row.get(puf_field)
        for puf_field, fhir_path in FHIR_FIELD_MAP.items()
    }
