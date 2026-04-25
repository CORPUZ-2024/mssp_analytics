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
py -m streamlit run src/app.py
```

> **Windows note:** `streamlit` and `pip` are often not on the system PATH in cmd.exe.
> Use `py -m streamlit` and `py -m pip` as shown above — these always work regardless of PATH.
> To make the bare `streamlit` command available permanently, add Python's Scripts folder to PATH:
> ```
> setx PATH "%PATH%;C:\Users\<you>\AppData\Local\Programs\Python\Python39\Scripts"
> ```
> Then reopen the terminal.

### Share the app publicly

| Method | Best for | Cost | URL lifetime |
|---|---|---|---|
| [Streamlit Community Cloud](https://streamlit.io/cloud) | Permanent public link from GitHub | Free | Permanent |
| [ngrok](https://ngrok.com) | Quick demo share | Free tier | Session only |
| [Cloudflare Tunnel](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/) | Stable tunnel, no port forwarding | Free | Persistent |

**Fastest option for a non-technical audience:**
1. Push this repo to GitHub (public or private)
2. Go to [share.streamlit.io](https://share.streamlit.io) → New app → select repo → `src/app.py`
3. Share the generated `https://*.streamlit.app` URL — no install required for viewers

The dashboard includes four tabs aligned to the project plan:

- **HCC Risk Flags** — RADV-style exposure scoring and YoY risk score variance
- **Shared Savings Model** — benchmark construction and savings/loss ratio simulation
- **PA Metrics Simulation** — synthetic prior authorization metrics using utilization proxies

## Design highlights

- strict schema validation for CMS PUF ingest
- deduplication based on `year`, `state_id`, `county_id`, and `dataset_id`
- conflict detection and QA report generation
- module scaffolding aligned to the attached project plan

## Notes

This repository is intended to capture the data ingestion and validation workflow for the MSSP project plan. The analytic modules are designed to be extended with domain-specific logic for RADV, shared savings and PA metrics. 
