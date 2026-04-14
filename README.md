# MSSP Analytics ETL

This repository implements a CMS MSSP County-Level Aggregate Expenditure and Risk Score ETL workflow with validation, deduplication, and analytic module scaffolding for:

- HCC / RADV risk flag analysis
- Shared savings and benchmark modeling
- Prior authorization simulation
- FHIR data bridge mapping

## What is included

- `src/etl/` — ingestion, cleaning, validation, and pipeline orchestration
- `src/modules/` — module scaffolding for the four analytical tracks described in the project plan
- `src/cli.py` — command-line ingestion entry point
- `pyproject.toml` — dependency metadata for Python packaging

## Running the ETL

Install dependencies:

```bash
python -m pip install -e .
```

Run the pipeline:

```bash
python -m src.cli ingest --input raw/mssp_puf.csv --output clean/mssp_puf_clean.csv --qa reports/qa.txt
```

## Streamlit dashboard

Launch the app with:

```bash
streamlit run src/app.py
```

The dashboard includes four tabs aligned to the project plan:

- **HCC Risk Flags** — RADV-style exposure scoring and YoY risk score variance
- **Shared Savings Model** — benchmark construction and savings/loss ratio simulation
- **PA Metrics Simulation** — synthetic prior authorization metrics using utilization proxies
- **FHIR Data Bridge** — PUF-to-FHIR mapping table and interoperability gap analysis

## Design highlights

- strict schema validation for CMS PUF ingest
- deduplication based on `year`, `state_id`, `county_id`, and `dataset_id`
- conflict detection and QA report generation
- module scaffolding aligned to the attached project plan

## Notes

This repository is intended to capture the data ingestion and validation workflow for the MSSP project plan. The analytic modules are designed to be extended with domain-specific logic for RADV, shared savings, PA metrics, and FHIR mapping.
