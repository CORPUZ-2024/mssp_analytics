# Module D — FHIR API Schema Reference

**Track:** Interoperability / FHIR Operations  
**Path:** `src/modules/fhir_data_bridge/`  
**Notebook:** `fhir_vs_puf_comparison.ipynb`

---

## CMS-0057-F: Five required APIs

CMS finalized five mandatory FHIR R4 APIs under the CMS Interoperability and Patient Access final rule and its successor rules (CMS-0057-F). The table below maps each API to the MSSP PUF fields it can or cannot express.

| CMS-0057-F API | FHIR resources | MSSP PUF fields covered | Coverage |
|---|---|---|---|
| **Patient Access API** | ExplanationOfBenefit, Coverage, MeasureReport | per_capita_exp, enrollment_type, year, quality_score (partial) | Partial |
| **Provider Directory API** | Organization, Practitioner, Location | state_id, county_id | Partial |
| **Provider Access API** | Group, CareTeam | n_ab_ben | Partial |
| **Prior Authorization API** | Claim, ClaimResponse | PA metrics (Module C proxy fields) | Partial |
| **Drug Formulary API** | MedicationKnowledge | No MSSP PUF overlap | None |

---

## PUF-to-FHIR field mapping

| PUF field | FHIR R4 resource | FHIR element path | CMS-0057-F API | Support | Gap |
|---|---|---|---|---|---|
| avg_risk_score | RiskAssessment | `prediction[0].probabilityDecimal` | Patient Access | Partial | No |
| per_capita_exp | ExplanationOfBenefit | `total.amount.value` | Patient Access | Yes | No |
| enrollment_type | Coverage | `type.coding.code` | Patient Access | Partial | No |
| year | ExplanationOfBenefit | `billablePeriod.start` | Patient Access | Yes | No |
| state_id | Organization | `address[0].state` | Provider Directory | Yes | No |
| county_id | Organization | `address[0].district` | Provider Directory | Partial | No |
| n_ab_ben | Group | `member.count` | Provider Access | Partial | No |
| quality_score | MeasureReport | `group.measureScore` | Patient Access | Partial | No |
| **sav_rate** | — | — | — | **No mapping** | **YES** |
| **per_capita_exp_by_enrollment_type** | — | — | — | **No mapping** | **YES** |

---

## Gap analysis

### sav_rate — no FHIR R4 equivalent

Shared savings / loss rate has no standard FHIR R4 resource. Financial performance metrics are not expressible through any CMS-0057-F required API without custom extensions. CMS publishes ACO financial results exclusively in flat-file PUF format. This is a genuine regulatory gap: the FHIR interoperability framework does not cover VBC financial performance reporting.

### per_capita_exp by enrollment type — no native FHIR aggregation

ExplanationOfBenefit records are beneficiary-level. County-level per-capita expenditure stratified by enrollment type (ESRD, Disabled, Aged Dual, Aged Non-Dual) requires population-level aggregation that is not native to the FHIR resource model. No US Core profile defines this aggregation.

### quality_score — custom profiles required

HEDIS and CAHPS quality composite scores require custom FHIR Measure profiles not defined in US Core. CMS-0057-F requires access to quality measures, but the mapping from MSSP-specific composite scores to standard FHIR MeasureReport resources is not standardised.

---

## CMS Blue Button 2.0 sandbox

Live FHIR R4 API for synthetic Medicare data. Used in `bb2_sandbox_query.py` to validate field-by-field mapping against actual API responses.

- **Sandbox registration:** https://bluebutton.cms.gov/developers/
- **FHIR base URL:** `https://sandbox.bluebutton.cms.gov/v1/fhir`
- **Key resources:** ExplanationOfBenefit, Patient, Coverage
- **Auth:** OAuth 2.0 with sandbox credentials

---

## FHIR compliance testing

CMS references the **Inferno FHIR Testing Tool** (ONC) for US Core and CMS-0057-F compliance validation.

- **Inferno:** https://inferno.healthit.gov
- Test suites: US Core v3.1.1, CMS Patient Access API, Da Vinci PAS

---

## Key finding

Four MSSP PUF fields — including shared savings rate and enrollment-type-stratified expenditure — have no direct FHIR R4 equivalent in any CMS-0057-F required API. CMS publishes these metrics in flat-file format, but they are not expressible through the standard FHIR resource model without custom extensions. This interoperability gap affects ACO operators, analytics vendors, and MA plans that rely on FHIR APIs for data exchange.

---

## Source references

| Source | URL |
|--------|-----|
| US Core Implementation Guide (HL7) | https://hl7.org/fhir/us/core/ |
| CMS APIs and required standards | https://www.cms.gov/priorities/key-initiatives/burden-reduction/interoperability/policy-and-regulations |
| CMS Blue Button 2.0 developer portal | https://bluebutton.cms.gov/developers/ |
| Inferno FHIR testing tool | https://inferno.healthit.gov |
| CMS-0057-F final rule | https://www.federalregister.gov/documents/2024/02/08/2024-00895 |
