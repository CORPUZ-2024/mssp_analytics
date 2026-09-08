# MSSP Analytics

County-level analytics on the CMS **Medicare Shared Savings Program (MSSP)** public use
file: a build-time ETL that resolves, validates and reshapes the CMS data, three
analytical modules layered on top of it, and a static dashboard published to GitHub
Pages.

- **Dashboard:** https://corpuz-2024.github.io/mssp_analytics/
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

## Architecture: the published page makes no API calls

The dashboard used to query the CMS Data API from the browser on every page load, which
made a third-party API a hard runtime dependency of the page. It failed in two ways at
once, and only one of them showed an error:

![CMS API failure](plan/issues/api_call.png)

1. **Retired UUIDs.** Year-specific dataset UUIDs were hard-coded. CMS retired them, so
   requests returned `404 Access denied to the requested data`.
2. **A silent content swap.** The "portal default" UUID is an *alias for the newest
   vintage*, not a fixed year. When CMS published PY2025 that UUID began serving
   `YEAR=2025`, so a `start_year=2024, end_year=2024` filter matched nothing — no HTTP
   error, just an empty dashboard.

The fix moves all CMS access to **build time, in CI**, and commits the result:

```
data.cms.gov/data.json ──▶ src/etl/catalog.py   title ──▶ current dataset UUIDs
data.cms.gov/data-api  ──▶ src/etl/client.py    fetch, paginate, wide──▶long, verify year
                           src/etl/{ingest,enrich}.py   normalise, coerce, flag
                           src/build_site.py    YoY + OC deltas, quality gates, atomic publish
                                  │
                                  ▼  (committed to git by CI)
                           docs/data/*.json   counties · oc_stability · reference · manifest
                                  │
                                  ▼  (static fetch, no API)
                           docs/index.html + docs/app.js  ──▶  GitHub Pages
```

**The published page reads committed JSON and nothing else.** A CMS outage, URL change
or schema change can fail a *build*; it cannot blank the page, which keeps serving the
last payload that passed the quality gates.

### The guards that make that safe

| Guard | Where | What it prevents |
|---|---|---|
| Title-keyed catalog resolution | `src/etl/catalog.py` | UUID rotation. The dataset **title** in `data.cms.gov/data.json` is the stable key; UUIDs are read from it per build. |
| Year discovery | `catalog.latest_years()` | Pinned years going stale — years come from the catalog, never a constant. |
| Year assertion | `client._assert_expected_year()` | The *silent* swap. If CMS serves a different year than was resolved, the build fails loudly instead of returning zero rows. |
| Quality gates + atomic publish | `build_site.run_quality_gates()`, `publish()` | Publishing a degraded payload over a good one. Data is staged to a temp dir, validated, then swapped in; a failed gate leaves `docs/data/` untouched. |
| Committed catalog cache | `data/cms_catalog.json` | A CMS outage *during* a build — the resolver falls back to the last known-good endpoint map instead of failing. |

Quality gates (in `src/build_site.py`): `>= 8,000` county rows, `>= 45` states,
`>= 75%` non-null `avg_risk_score` / `per_capita_exp` on the latest year, `>= 50%` YoY
delta coverage, and all four enrollment types present.

### What resolving vintages from the catalog bought

The catalog exposes the operational cuts (`OC1`/`OC2`/`OC3`) next to each `FINAL`
vintage. The **OC-stability panel** — early-cut → `FINAL` risk-score movement per county,
a read on late diagnosis coding — is now real data. The Streamlit version could only
draw it as a hard-coded illustration because it fetched a single cut.

---

## Repository layout

| Path | Purpose |
|---|---|
| `src/etl/catalog.py` | CMS DCAT catalog resolver (dataset title &rarr; current UUIDs, with a committed cache) |
| `src/etl/client.py` | CMS Data API v1 client: ret/backoff, pagination, wide&rarr;long reshape, year assertion |
| `src/etl/{ingest,cleaning,enrich,validate,pipeline}.py` | normalise, clean, enrich, validate |
| `src/etl/disclosures.py` | Module C payer-disclosure ingestion |
| `src/modules/hcc_radv_risk_flags/` | V28 / RADV exposure index and flags |
| `src/modules/shared_savings_model/` | benchmark-version skew, shared-savings calculator |
| `src/modules/pa_metrics_simulation/` | CMS-0057-F prior authorization metrics report |
| `src/build_site.py` | build-time ETL that writes `docs/data/*.json` (the entry point CI runs) |
| `docs/` | the published static site — `index.html`, `app.js`, `data/` |
| `src/app.py` | the Streamlit app, kept as a local exploration tool |
| `src/cli.py` | standalone ETL CLI (`ingest`) for local CSV work |
| `.github/workflows/` | `refresh-data.yml` (data) and `pages.yml` (deploy) |

The committed payload carries provenance — build timestamp, catalog source, and the
exact dataset UUIDs and vintage labels used — in `docs/data/manifest.json`, and the
dashboard renders it in a banner above the tabs.

---

## Working with it

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

Standalone ETL CLI, unchanged:

```bash
python -m src.cli ingest --input raw/mssp_puf.csv --output clean/mssp_puf_clean.csv --qa reports/qa.txt
```

### Streamlit app

Still runnable locally, and now resolves years and endpoints through the same catalog:

```bash
py -m streamlit run src/app.py
```

It is no longer the published surface — GitHub Pages is. The archived pre-migration
version lives on the `streamlit-version` branch.

---

## Workflow &amp; deployment

### GitHub Pages one-time setup

1. **Settings &rarr; Pages &rarr; Source: GitHub Actions** (not "Deploy from a branch").
2. **Settings &rarr; Environments &rarr; `github-pages` &rarr; Deployment branches:** allow
   both `master` and `main` (or "All branches"). A deploy from a branch the environment
   does not list is rejected even if the workflow runs.

### The two workflows

| Workflow | Triggers | On failure |
|---|---|---|
| `refresh-data.yml` | weekly cron, manual dispatch, or a push to `master` / `main` touching `src/etl/**`, `src/build_site.py`, `src/modules/**`, `disclosures_metrics.csv`, or the workflow file | Leaves `docs/data/` untouched, fails the run, and opens (once) a `data-refresh` issue. The page stays up on the previous payload. |
| `pages.yml` | a push to `master` / `main` touching `docs/**` or the workflow file; or manual dispatch | Verifies the payload files exist, parse, and are not thin (`>= 8,000` county rows) **before** deploying. A bad payload fails the job instead of publishing. |

Both filter on `branches: [master, main]`, so the branch you push a payload to is the
one that deploys. `pages.yml` uses `concurrency: group: pages, cancel-in-progress: true`,
so overlapping pushes collapse to the latest.

### How a data refresh reaches the page

`refresh-data.yml` rebuilds `docs/data/` and commits it with the built-in `GITHUB_TOKEN`.
GitHub's anti-recursion rule means **that bot commit does not trigger `pages.yml`**. The
deploy fires on the next *user-authored* commit under `docs/` (or a manual
`workflow_dispatch` of "Deploy Pages"). Keep this in mind after an automated refresh: the
data is in git but not yet live until something pushes it.

### Branches

`master` and `main` are kept in sync and either can deploy. `feature/*` branches don't
deploy; `streamlit-version` is the frozen pre-migration archive.

---

## Caveats

**Data / freshness**

- **A stale page looks identical to a fresh one.** The dashboard renders whatever passed
  the gates last; check the provenance banner (built-at date, vintage labels) to see how
  current it is.
- **YoY deltas need two `FINAL` years** in the catalog. **OC-stability needs operational
  cuts** published for the latest year; if none exist that panel is empty (the manifest
  records `oc_stability_available: false`).
- **County/enrollment coverage varies by year.** Small cells are sparse; `person_years`
  is the weight to judge a row's reliability by.

**Deployment**

- The `github-pages` environment's **deployment-branch rule** can silently block a
  deploy from `main` even after the workflow trigger is correct — see setup above.
- After an automated data refresh, the page is **not live until a user-authored push**
  under `docs/` (anti-recursion rule above).

**Modelling assumptions**

- **Provenance badges** mark every figure as `derived`, `external`, `constant` or
  `simulated`. Module C mixes real payer disclosures (`disclosures_metrics.csv`) with
  modelled estimates; the badges are how you tell them apart.
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

The CMS PUF is a U.S. Government work in the public domain; cite CMS as the source.
Derived figures and modelled estimates in this repo are the authors' and are not
endorsed by CMS.
