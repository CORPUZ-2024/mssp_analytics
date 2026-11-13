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

## Architecture

All CMS access happens at build time, when a maintainer runs `src/build_site.py`
locally. It resolves the current dataset endpoints from the CMS DCAT catalog, fetches and
reshapes the vintages, enforces a set of quality gates, and writes the result as static
JSON under `docs/data/` for the maintainer to commit. The
published page fetches only those committed files, so an upstream outage, URL change or
schema change can fail a build but cannot blank the dashboard — it keeps serving the last
payload that passed the gates.

**There is no automatic data pull.** Per the project's scope, the dashboard is a
point-in-time analysis of the committed payload; the data changes only when a maintainer
rebuilds and commits it (see [Refreshing the data](#refreshing-the-data)).

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
| `src/build_site.py` | build-time ETL that writes `docs/data/*.json` (run manually to refresh the data) |
| `docs/` | the published static site — `index.html`, `app.js`, `data/` |
| `src/app.py` | the Streamlit app, kept as a local exploration tool |
| `src/cli.py` | standalone ETL CLI (`ingest`) for local CSV work |
| `maintenance/` | operational and design notes (see [`maintenance/architecture.md`](maintenance/architecture.md)) |
| `.github/workflows/` | `pages.yml` (deploy only; there is no data-refresh workflow) |

The committed payload carries provenance — build timestamp, catalog source, and the
exact dataset UUIDs and vintage labels used — in `docs/data/manifest.json`, and the
dashboard renders it in a banner above the tabs.

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

## Refreshing the data

Data pulls are manual: no workflow or schedule queries the CMS Data API. (The legacy
`src/app.py` exploration app is the one exception — it calls the API live when opened —
and it does not feed the dashboard.) To move the dashboard to a newer CMS release:

```bash
python -m src.build_site --check-only   # confirm upstream passes the quality gates
python -m src.build_site                # rebuild docs/data/ and data/cms_catalog.json
git add docs/data data/cms_catalog.json
git commit -m "Refresh CMS payload (PYxxxx)"
git push origin main                    # then bring master in line with main
```

Because the commit is user-authored and touches `docs/`, the push triggers `pages.yml`
and the refreshed payload goes live. If a gate fails, `docs/data/` is left untouched and
the dashboard keeps serving the previous payload.

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
| `pages.yml` | a push to `master` / `main` touching `docs/**` or the workflow file; or manual dispatch | Verifies the payload files exist, parse, and are not thin (`>= 8,000` county rows) **before** deploying. A bad payload fails the job instead of publishing. |

`pages.yml` filters on `branches: [master, main]`, so the branch a payload is pushed to
is the branch that deploys. `pages.yml` uses `concurrency: group: pages, cancel-in-progress:
true`, so overlapping pushes collapse to the latest.

### Branches

`master` and `main` are kept in sync and either can deploy. `feature/*` branches do not
deploy; `streamlit-version` is the frozen pre-migration archive.

---

## Caveats

**Data / freshness**

- **The data is a snapshot.** There is no automatic refresh, so the dashboard shows the
  last payload a maintainer built and committed, even after CMS publishes a newer
  release. The provenance banner (built-at date, vintage labels) indicates how current
  that is.
- **YoY deltas need two `FINAL` years** in the catalog. **OC-stability needs operational
  cuts** published for the latest year; if none exist that panel is empty (the manifest
  records `oc_stability_available: false`).
- **County/enrollment coverage varies by year.** Small cells are sparse, and
  `person_years` is the weight by which a row's reliability should be judged.

**Deployment**

- The `github-pages` environment's **deployment-branch rule** can silently block a deploy
  from `main` even when the workflow trigger is correct — see configuration above.

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
