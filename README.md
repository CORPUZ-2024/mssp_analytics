# MSSP Analytics

CMS MSSP County-Level Aggregate Expenditure and Risk Score analytics: ETL, validation,
and three analytical modules, published as a static dashboard on GitHub Pages.

- **Dashboard:** https://corpuz-2024.github.io/mssp_analytics/
- **Modules:** HCC / RADV risk flags &middot; shared savings and benchmark modelling &middot;
  CMS-0057-F prior authorization metrics

## Architecture: why the dashboard has no API calls

The dashboard used to query the CMS Data API from the browser on every page load. That
made a third-party API a hard runtime dependency of the page, and it failed exactly the
way you would expect:

![CMS API failure](plan/issues/api_call.png)

Two separate upstream changes caused that screenshot, and only one of them was visible
as an error:

1. **Retired UUIDs.** The year-specific dataset UUIDs were hard-coded. CMS retired them,
   so requests returned `404 Access denied to the requested data` — the yellow banner.
2. **A silent content swap.** The "portal default" UUID is an *alias for the newest
   vintage*, not a fixed year. When CMS published PY2025, that same UUID began serving
   `YEAR=2025`, so the app's `start_year=2024, end_year=2024` filter matched nothing —
   the "No records returned" banner. No HTTP error was involved.

The fix splits the two concerns that were tangled together:

```
data.cms.gov  ──▶  src/etl/catalog.py   resolve title ──▶ current UUIDs
                   src/etl/client.py    fetch + verify the year
                   src/build_site.py    transform, gate, publish
                          │
                          ▼  (committed to git, in CI)
                   docs/data/*.json
                          │
                          ▼  (static file read)
                   docs/index.html + docs/app.js   ──▶  GitHub Pages
```

**The published page reads committed JSON and nothing else.** A CMS outage, URL change or
schema change can fail a *build*; it cannot blank the page, which keeps serving the last
payload that passed the quality gates.

### The four guards

| Guard | Where | What it prevents |
|---|---|---|
| Title-keyed catalog resolution | `src/etl/catalog.py` | UUID rotation. The dataset *title* in `data.cms.gov/data.json` is the stable key; UUIDs are read from it per build. |
| Year discovery | `catalog.latest_years()` | Pinned years going stale. Years come from the catalog, never from a constant. |
| Year assertion | `client._assert_expected_year()` | The *silent* swap. If CMS serves a year other than the one resolved, the build fails loudly instead of returning zero rows. |
| Quality gates + atomic publish | `build_site.run_quality_gates()`, `publish()` | Publishing a degraded payload over a good one. Data is staged, validated, then swapped in; a failure leaves `docs/data/` untouched. |

The catalog is also cached to `data/cms_catalog.json` and committed, so a CMS outage
during a build degrades to "use the last known-good endpoint map" rather than a failure.

### What this bought beyond the fix

Resolving vintages from the catalog exposed the operational cuts (OC1/OC2/OC3) alongside
each FINAL vintage. The OC-stability panel — which the Streamlit version could only draw
as a hard-coded illustration, because it fetched a single cut — is now real data.

## Repository layout

| Path | Purpose |
|---|---|
| `src/etl/catalog.py` | CMS DCAT catalog resolver (title &rarr; current dataset UUIDs) |
| `src/etl/client.py` | CMS Data API client: retries, pagination, wide&rarr;long reshape, year assertion |
| `src/etl/` | ingestion, cleaning, validation, enrichment, pipeline |
| `src/modules/` | the three analytical modules |
| `src/build_site.py` | build-time ETL that writes `docs/data/*.json` |
| `docs/` | the published static site (`index.html`, `app.js`, `data/`) |
| `src/app.py` | the Streamlit app, kept as a local exploration tool |
| `.github/workflows/` | scheduled data refresh and Pages deploy |

## Working with it

```bash
python -m pip install -e .

# Rebuild the dashboard payload from CMS (writes docs/data/)
python -m src.build_site

# Validate upstream without publishing
python -m src.build_site --check-only

# Build from the cached catalog, no catalog request
python -m src.build_site --offline

# Preview the site locally
python -m http.server 8000 --directory docs   # then open http://localhost:8000

python -m pytest
```

The ETL CLI is unchanged:

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

## Automation

| Workflow | Trigger | Behaviour on failure |
|---|---|---|
| `refresh-data.yml` | weekly, manual, or a push touching the ETL | Leaves `docs/data/` untouched, fails the run, and opens a `data-refresh` issue. The page stays up on the previous payload. |
| `pages.yml` | a push touching `docs/` | Verifies the payload parses and is not thin before deploying. |

Because a stale-but-working page is the quiet failure mode, every payload carries
provenance — build timestamp, catalog source, and the exact dataset UUIDs used — and the
dashboard renders it in a banner above the tabs.

## Data notes

- **Provenance badges** mark every figure as `derived`, `external`, `constant` or
  `simulated`. Module C mixes real payer disclosures with modelled estimates; the badges
  are how you tell them apart.
- **The RADV composite uses illustrative weights** (0.4 / 0.4 / 0.2), pending empirical
  validation against RADV audit outcomes. Exposure tiers are relative terciles of the
  composite *within the current selection*, not absolute thresholds.
- **V28 skew figures are directional estimates** from CMS Announcement Tables VIII-1 and
  VI-1, not values fitted to the PUF.

## GitHub Pages setup

One-time, in **Settings &rarr; Pages**: set the source to **GitHub Actions**. The
`pages.yml` workflow handles the rest.
