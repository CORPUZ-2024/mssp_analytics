# Module C — Prior Authorization Metrics Simulation

**Track:** PA Metrics / Compliance Reporting  
**Path:** `src/modules/pa_metrics_simulation/`  
**Notebook:** `pa_metrics_report.ipynb`

---

## What this module does

MSSP ACOs interact with payers via prior authorization — their members' specialty referrals, procedures, and post-acute services flow through PA processes. This module simulates what a CMS-0057-F compliant PA metrics report would look like if the underlying encounter data were available.

It uses MSSP county encounter utilization fields as proxy inputs for service-level PA volume and denial rate estimation. The output demonstrates the seven CMS-required PA metric fields against Medicare FFS and MA plan benchmarks.

---

## CMS-0057-F context

CMS finalized the Interoperability and Prior Authorization rule (CMS-0057-F) in January 2024. Impacted payers (MA plans, Medicaid MCOs, CHIP plans, QHPs) must:

1. Implement HL7 FHIR APIs for PA requests (HL7 Da Vinci PAS IG)
2. **Report seven standardised PA metrics annually by March 31**
3. Send decision notifications within 1 business day

The seven required metrics are defined in the CMS PA API FAQ and the PA Metrics Reporting Template PDF.

---

## The 7 CMS-required PA metric fields

| CMS metric | Definition | Medicare FFS benchmark | MSSP PUF proxy |
|---|---|---|---|
| List of PA-required items | All medical items/services requiring PA | CMS Required PA List (Jan 2026) | MSSP specialty utilization categories |
| % standard requests approved | Approved standard / total standard × 100 | ~92.3% (FY2024 CMS Pre-Claim Review) | Specialty utilization rate |
| % standard requests denied | Denied standard / total standard × 100 | ~7.7% | Inverse of approval proxy |
| % approved after appeal | Reversed on appeal / total denied × 100 | >80% overturned (KFF 2024) | 82% simulation band |
| % extended review then approved | Extended TAT requests ultimately approved | 3–5% of standard (UM literature) | Low-urgency utilization + delay flag |
| % expedited requests approved | Approved expedited (72-hr) / total expedited × 100 | ~89.1% (FY2024) | Urgent/emergent utilization rate |
| % expedited requests denied | Denied expedited / total expedited × 100 | ~10.9% | Inverse of expedited approval |

---

## Files

| File | Purpose |
|------|---------|
| `pa_metrics_schema.py` | Python dataclasses for PA metric records and individual metrics |
| `pa_metrics_simulation.py` | Generates synthetic PA metrics from MSSP utilization proxy fields |
| `pa_metrics_report.py` | Assembles the full report with approval/denial rate calculations |
| `pa_metrics_report.ipynb` | Rendered output in CMS reporting template format |

---

## Simulation assumptions

- Baseline standard approval rate: 92.3% (Medicare FFS FY2024)
- Approval rate variance: ±5% based on specialty utilization deviation from county mean
- Appeal overturn rate: fixed at 82% (midpoint of KFF MA band 80–84%)
- Extended review rate: 3–10% of standard requests (UM literature range)
- Expedited approval rate: fixed at 89.1% (Medicare FFS FY2024)
- Total PA requests proxy: specialty_utilization_rate × 1,000 per county-year

These are simulation parameters, not actual CMS reporting outcomes. All outputs should be treated as proxy estimates for analytical demonstration.

---

## Key finding

MSSP-aligned populations show slightly elevated simulated denial rates relative to Medicare FFS, consistent with higher specialty utilization in ACO populations. The appeal overturn rate gap versus KFF MA data suggests ACO-adjacent populations face more defensible initial denials or lower appeal propensity — a pattern relevant to payer compliance teams conducting annual PA metric reporting under CMS-0057-F.

---

## CMS benchmark sources

| Source | What it validates |
|--------|------------------|
| [CMS PA API FAQ — 7 required metric fields](https://www.cms.gov/priorities/key-initiatives/burden-reduction/interoperability/policy-and-regulations/cms-interoperability-and-prior-authorization-final-rule-cms-0057-f) | Exact required metric fields and March 31 reporting cadence |
| [CMS PA Metrics Reporting Template PDF](https://www.cms.gov/priorities/key-initiatives/burden-reduction/interoperability) | Official template format payers must follow |
| [Medicare FFS PA & Pre-Claim Review Stats FY2024](https://www.cms.gov) | FFS approval/denial/appeal rates — primary reference range |
| [KFF MA Prior Authorization Data 2024](https://www.kff.org/medicare/issue-brief/medicare-advantage-in-2023-prior-authorization-and-clinical-criteria/) | MA denial rates (~7.7%), appeal overturn rates (~80%) |
