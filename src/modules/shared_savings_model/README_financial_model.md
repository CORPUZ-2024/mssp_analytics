# Module B — Shared Savings Reconciliation Model

**Track:** VBC Financial Modeling  
**Path:** `src/modules/shared_savings_model/`  
**Notebook:** `financial_model.ipynb`

---

## What this module does

This module builds a simplified MSSP-style risk-adjusted benchmark for each county–enrollment-type pair and estimates shared savings or loss relative to that benchmark. It extends the core Expenditure Efficiency Ratio from the ETL pipeline into a full financial reconciliation layer.

It also constructs a TEAM episode cost analog using per-capita expenditure fields as a surgical episode proxy for TEAM-designated counties.

---

## Files

| File | Purpose |
|------|---------|
| `benchmark_constructor.py` | V24 and V28 risk-adjusted benchmark per county/enrollment type |
| `shared_savings_calc.py` | Track A / B / ENHANCED shared savings and loss reconciliation |
| `team_episode_proxy.py` | Post-acute spend as episode cost analog for TEAM counties |
| `reconciliation.py` | Orchestrator — assembles benchmark + savings + TEAM + version skew |
| `financial_model.ipynb` | Interactive reconciliation output and ACO performance distribution |

---

## MSSP financial methodology (simplified)

**Benchmark construction:**

```
Benchmark = Prior_Benchmark × National_Trend_Factor × (County_RAF / National_Avg_RAF)
```

This module uses a simplified version where:
- `National_Trend_Factor` = 1.02 (approximate CMS default; actual values published annually in MSSP Final Rule)
- V24 and V28 risk score factors reflect the 2024 transition blend (67% V24 / 33% V28 for MA; MSSP uses V24 through 2023, V28 for 2024+)

**Shared savings formula:**

```
Shared_Savings_Ratio = (Benchmark − Actual_Spend) / Benchmark
```

Positive ratio = ACO generated savings. Only ratios exceeding the MSR qualify for shared savings distribution.

**Minimum Savings Rate (MSR) — Track A:**

| Assigned beneficiaries | MSR |
|---|---|
| ≤ 5,000 | 3.5% |
| 5,001–60,000 | Scales linearly from 3.5% → 2.0% |
| ≥ 60,000 | 2.0% |

**Track parameters:**

| Track | Sharing rate | Loss sharing | MSR |
|---|---|---|---|
| A | 50% | None (one-sided) | Sliding 3.5%–2.0% |
| B | 60% | 60% | 2.0% |
| ENHANCED | 75% | 75% | 2.0% |

---

## TEAM episode proxy

The TEAM Model targets ~25% of US CBSAs for five mandatory surgical episodes. This module uses a hash-based CBSA proxy (see `enrich.py`) and estimates episode cost as a share of total per-capita expenditure. TEAM counties should show inpatient spend compression relative to pre-TEAM trend.

---

## Key finding

ACOs with risk scores above 1.20 systematically exceed benchmark under Track A parameters. This is a structural underweighting problem: the benchmark construction formula underweights severity for high-complexity populations, and the minimum savings rate does not adjust for population acuity. TEAM episode target pricing faces the same structural issue for surgical patients with comorbidities.

---

## CMS benchmark sources

| Source | What it validates |
|--------|------------------|
| [MSSP PY Financial & Quality Results PUF](https://data.cms.gov/medicare-shared-savings-program) | Ground truth ACO savings/loss by performance year |
| [CMMI TEAM Model specification](https://innovation.cms.gov/innovation-models/team) | Episode target prices for 5 surgical procedures |
| [FY2026 IPPS Final Rule — TEAM section](https://www.cms.gov/medicare/payment/prospective-payment-systems/acute-inpatient-pps) | Regulatory basis for TEAM financial methodology |
| MSSP Participation Agreement — Financial Methodology Appendix | MSR sliding scale, shared savings rate by track |
