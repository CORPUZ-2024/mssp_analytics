# MSSP Analytics

County-level analytics on the CMS **Medicare Shared Savings Program (MSSP)** public use
file: a build-time ETL that resolves, validates and reshapes the CMS data, three
analytical modules layered on top of it, and a static dashboard published to GitHub
Pages.

- **Dashboard:** https://corpuz-2024.github.io/mssp_analytics/
- **Local Streamlit edition** (this branch): the same dashboard as a Streamlit app — see
  [Run the dashboard locally (Streamlit)](#run-the-dashboard-locally-streamlit)
- **Modules:** HCC / RADV risk-exposure flags &middot; shared savings and benchmark
  modelling &middot; CMS-0057-F prior authorization metrics

---

## Data source

Everything downstream is derived from one CMS public use file:

> **County-level Aggregate Expenditure and Risk Score Data on Assignable Beneficiaries**
> Centers for Medicare &amp; Medicaid Services, Medicare Shared Savings Program.
> Landing page: <https://data.cms.gov/medicare-shared-savings-program/county-level-aggregate-expenditure-and-risk-score-data-on-assignable-beneficiaries>

The PUF reports, per **county** and per **Medicare enrollment type** (ESRD, Disabled,
Aged/Dual-eligible, Aged/Non-dual-eligible):

| Field | Meaning |
|---|---|
| `per_capita_exp` | Per-capita Parts A + B fee-for-service expenditure |
| `avg_risk_score` | Mean CMS-HCC prospective risk score |
| `avg_demog_score` | Mean demographic-only risk score |
| `person_years` | Assignable-beneficiary person-years (the denominator / weight) |

CMS publishes the file annually in the fall for the prior calendar year, and issues
earlier **operational cuts** (`OC1`, `OC2`, `OC3`) ahead of each `FINAL` vintage. The
build pulls the two most recent `FINAL` years plus whatever operational cuts exist for
the latest year.

- **Methodology:** <https://data.cms.gov/resources/county-level-aggregate-expenditure-and-risk-score-data-on-assignable-beneficiaries-methodology>
- **Data dictionary:** <https://data.cms.gov/resources/county-level-aggregate-expenditure-and-risk-score-data-on-assignable-beneficiaries-data-dictionary>
- **Program data hub:** <https://www.cms.gov/medicare/payment/fee-for-service-providers/shared-savings-program-ssp-acos/data>
- **DCAT catalog** the build reads: <https://data.cms.gov/data.json>

Module C additionally reads `disclosures_metrics.csv`, a small hand-maintained table of
public payer prior-authorization disclosures; the rest of that module is modelled (see
[Caveats](#caveats)).

---

## Architecture

All CMS access happens at build time, in CI. `src/build_site.py` resolves the current
dataset endpoints from the CMS DCAT catalog, fetches and reshapes the vintages, enforces
a set of quality gates, and commits the result as static JSON under `docs/data/`. The
published page fetches only those committed files, so an upstream outage, URL change or
schema change can fail a build but cannot blank the dashboard — it keeps serving the last
payload that passed the gates.

The full account — the original browser-side failure modes that motivated this design,
the data-flow diagram, the five upstream-failure guards, and the quality-gate
thresholds — is kept in [`maintenance/`](maintenance/), the folder for operational and
design notes that sit outside this README. See
[`maintenance/architecture.md`](maintenance/architecture.md).

---

## Repository layout

| Path | Purpose |
|---|---|
| `src/etl/catalog.py` | CMS DCAT catalog resolver (dataset title &rarr; current UUIDs, with a committed cache) |
| `src/etl/client.py` | CMS Data API v1 client: retry/backoff, pagination, wide&rarr;long reshape, year assertion |
| `src/etl/{ingest,cleaning,enrich,validate,pipeline}.py` | normalise, clean, enrich, validate |
| `src/etl/disclosures.py` | Module C payer-disclosure ingestion |
| `src/modules/hcc_radv_risk_flags/` | V28 / RADV exposure index and flags |
| `src/modules/shared_savings_model/` | benchmark-version skew, shared-savings calculator |
| `src/modules/pa_metrics_simulation/` | CMS-0057-F prior authorization metrics report |
| `src/build_site.py` | build-time ETL that writes `docs/data/*.json` (the entry point CI runs) |
| `docs/` | the published static site — `index.html`, `app.js`, `data/` |
| `streamlit_dashboard/` | Streamlit port of the Pages dashboard (`app.py`, `requirements.txt`) — reads `docs/data/*.json`; see [Run the dashboard locally](#run-the-dashboard-locally-streamlit) |
| `run.bat` | Windows launcher for the Streamlit dashboard |
| `src/app.py` | the original live-API Streamlit app, kept as a local exploration tool |
| `src/cli.py` | standalone ETL CLI (`ingest`) for local CSV work |
| `maintenance/` | operational and design notes (see [`maintenance/architecture.md`](maintenance/architecture.md)) |
| `.github/workflows/` | `refresh-data.yml` (data) and `pages.yml` (deploy) |

The committed payload carries provenance — build timestamp, catalog source, and the
exact dataset UUIDs and vintage labels used — in `docs/data/manifest.json`, and the
dashboard renders it in a banner above the tabs.

---

## Run the dashboard locally (Streamlit)

This branch (`streamlit-version`) carries everything on `main` plus a Streamlit edition
of the GitHub Pages dashboard that runs on your own machine.

### What it is

`streamlit_dashboard/app.py` is a port of the Pages dashboard (`docs/index.html` +
`docs/app.js`) to Streamlit. It has:

- **The same three module tabs:** A — HCC &amp; RADV risk flags, B — shared savings model,
  C — PA metrics (CMS-0057-F), with Module C off by default behind a sidebar toggle.
- **The same sidebar:** state and enrollment-type filters, plus per-tab controls (YoY
  delta threshold; MSSP track, RAF band and V28 adjustment; service type) and summary
  KPIs that follow the selected tab.
- **The same charts, tables and text:** every chart, the ranked RADV table with its
  column-definition tooltips, the RAF-band and PA-field tables, the key-finding panels,
  and the provenance banner with source vintages.
- **The same calculations:** the V28 exposure index, RADV composite and tiers, benchmarks,
  shared savings and sliding MSR are recomputed on the filtered selection exactly as
  `app.js` does. Its sidebar KPIs were checked against `app.js` on the same payload and
  match.

### Where its data comes from

By default the app reads `docs/data/` **from the `main` branch on GitHub** — the exact
files the Pages site is built from — pinned to the latest commit that touched
`docs/data/`, so all four payload files always come from the same build. When the weekly
refresh lands on `main`, the app picks it up within 15 minutes; this branch never needs a
merge to stay current. Like the Pages site, it makes no request to data.cms.gov.

If GitHub cannot be reached, the app falls back to the copy of `docs/data/` committed on
this branch and says so in an amber banner. Two optional settings (environment variables,
or Community Cloud secrets) change this:

| Setting | Default | Effect |
|---|---|---|
| `MSSP_DATA_SOURCE` | `main` | `local` reads this branch's `docs/data/` only (fully offline) |
| `MSSP_DATA_REF` | `main` | branch, tag or commit to read the payload from |

### Comparing it with the Pages site

The provenance banner at the top of both apps shows the build date, row, county and
state counts. The Streamlit banner also shows the `main` commit the payload came from and
a **payload fingerprint** (first 12 hex digits of the SHA-256 of `counties.json`). To
confirm both are on identical data:

```bash
git fetch origin
git show origin/main:docs/data/counties.json | sha256sum | cut -c1-12
```

With the same filters selected, the sidebar KPIs, charts and tables should then match
the Pages site exactly.

Differences from the Pages site: there is no theme button (the app is set to light in
`.streamlit/config.toml`, matching the Pages colours; use Streamlit's own settings menu to
switch), and the module tabs are a row of radio buttons at the top of the page.

### Files

| Path | Purpose |
|---|---|
| `streamlit_dashboard/app.py` | the Streamlit dashboard |
| `streamlit_dashboard/requirements.txt` | its dependencies — Streamlit **1.32.2** (pinned), pandas, numpy, Plotly |
| `.streamlit/config.toml` | light theme matching the Pages design tokens |
| `run.bat` | Windows launcher — uses `.venv` when present, otherwise the `py` launcher |
| `src/app.py` | the older live-API Streamlit app, unchanged |

### Setup (first time)

Requires Python 3.9+ **other than 3.9.7**: Streamlit excludes 3.9.7 from every release
after 1.12.0, so `pip` cannot install 1.32 on it. Python 3.11 is recommended. On Windows
it can be installed alongside an existing Python with:

```bash
winget install --id Python.Python.3.11 -e --scope user
```

Then, from the repository root:

```bash
git checkout streamlit-version
py -3.11 -m venv .venv
.venv\Scripts\python -m pip install -r streamlit_dashboard/requirements.txt
```

`.venv/` is git-ignored.

### Run

Double-click `run.bat`, or from the repository root:

```bash
.venv\Scripts\python -m streamlit run streamlit_dashboard/app.py
```

The app opens at <http://localhost:8501>. Use the venv's Python, not plain `py` — on a
machine whose default is 3.9.7, `py` still points at an old Streamlit.

### Public deployment (Streamlit Community Cloud)

Deployed from this branch at share.streamlit.io with:

| Setting | Value |
|---|---|
| Repository | `CORPUZ-2024/mssp_analytics` |
| Branch | `streamlit-version` |
| Main file path | `streamlit_dashboard/app.py` |
| Python version (Advanced settings) | 3.11 |

Community Cloud installs `streamlit_dashboard/requirements.txt` (it prefers the
requirements file next to the entry point over the root one) and reads the theme from
`.streamlit/config.toml`. No secrets are needed. The deployed app follows `main`'s
payload automatically, as described above; pushing to this branch redeploys the code.

---

## Local development

```bash
python -m pip install -e .

# Rebuild the dashboard payload from CMS (writes docs/data/)
python -m src.build_site

# Validate upstream without publishing (runs the quality gates only)
python -m src.build_site --check-only

# Build from the committed catalog cache, no catalog request
python -m src.build_site --offline

# Preview the built site locally
python -m http.server 8000 --directory docs   # then open http://localhost:8000

python -m pytest
```

Standalone ETL CLI for local CSV work:

```bash
python -m src.cli ingest --input raw/mssp_puf.csv --output clean/mssp_puf_clean.csv --qa reports/qa.txt
```

---

## Workflow &amp; deployment

### GitHub Pages configuration

1. **Settings &rarr; Pages &rarr; Source:** GitHub Actions (not "Deploy from a branch").
2. **Settings &rarr; Environments &rarr; `github-pages` &rarr; Deployment branches:** both
   `master` and `main` must be listed (or "All branches"). A deploy from an unlisted
   branch is rejected even when the workflow runs.

### Workflows

| Workflow | Triggers | On failure |
|---|---|---|
| `refresh-data.yml` | weekly cron, manual dispatch, or a push to `master` / `main` touching `src/etl/**`, `src/build_site.py`, `src/modules/**`, `disclosures_metrics.csv`, or the workflow file | Leaves `docs/data/` untouched, fails the run, and opens (once) a `data-refresh` issue. The page stays up on the previous payload. |
| `pages.yml` | a push to `master` / `main` touching `docs/**` or the workflow file; or manual dispatch | Verifies the payload files exist, parse, and are not thin (`>= 8,000` county rows) **before** deploying. A bad payload fails the job instead of publishing. |

Both filter on `branches: [master, main]`, so the branch a payload is pushed to is the
branch that deploys. `pages.yml` uses `concurrency: group: pages, cancel-in-progress:
true`, so overlapping pushes collapse to the latest.

### Data-refresh propagation

`refresh-data.yml` rebuilds `docs/data/` and commits it with the built-in `GITHUB_TOKEN`.
GitHub's anti-recursion rule means that bot commit does not trigger `pages.yml`. The
deploy fires on the next user-authored commit under `docs/`, or a manual
`workflow_dispatch` of "Deploy Pages". After an automated refresh the new data is
committed but not live until a subsequent push.

### Branches

`master` and `main` are kept in sync and either can deploy. `feature/*` branches do not
deploy; `streamlit-version` tracks `main` and adds the local Streamlit edition in
`streamlit_dashboard/`. Neither workflow runs on it, so pushing it publishes nothing, and
the Streamlit app reads its payload from `main` at runtime, so it tracks `main`'s data
without a merge.

---

## Caveats

**Data / freshness**

- **A stale page looks identical to a fresh one.** The dashboard renders whatever passed
  the gates last; the provenance banner (built-at date, vintage labels) indicates how
  current that is.
- **YoY deltas need two `FINAL` years** in the catalog. **OC-stability needs operational
  cuts** published for the latest year; if none exist that panel is empty (the manifest
  records `oc_stability_available: false`).
- **County/enrollment coverage varies by year.** Small cells are sparse, and
  `person_years` is the weight by which a row's reliability should be judged.

**Deployment**

- The `github-pages` environment's **deployment-branch rule** can silently block a deploy
  from `main` even when the workflow trigger is correct — see configuration above.
- After an automated data refresh, the page is **not live until a user-authored push**
  under `docs/` (anti-recursion rule above).

**Modelling assumptions**

- **Provenance badges** mark every figure as `derived`, `external`, `constant` or
  `simulated`. Module C mixes real payer disclosures (`disclosures_metrics.csv`) with
  modelled estimates; the badges distinguish the two.
- **The RADV composite uses illustrative weights** (0.4 / 0.4 / 0.2), pending empirical
  validation against RADV audit outcomes. Exposure tiers are relative terciles of the
  composite *within the current selection*, not absolute thresholds.
- **V28 skew figures are directional estimates** from CMS Announcement Tables VIII-1 and
  VI-1, not values fitted to the PUF.
- **CMS-0057-F prior-authorization metrics are a simulation** driven by PUF-derived
  utilization proxies, not observed PA decisions, except where a row is sourced from
  `disclosures_metrics.csv`.

---

## Licence &amp; attribution

The CMS PUF is a U.S. Government work in the public domain; CMS is the source to cite.
Derived figures and modelled estimates in this repository are the authors' and are not
endorsed by CMS.
