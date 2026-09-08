/* ------------------------------------------------------------------------
 * MSSP county-level analytics - static dashboard.
 *
 * This file talks to no API. It reads the JSON payloads under ./data/, which
 * are produced at build time by `python -m src.build_site` and committed to
 * the repository. A CMS endpoint change can therefore fail a build, but it can
 * never blank this page: the last good payload keeps being served.
 *
 * Derived measures (V28 exposure index, RADV composite, benchmarks, shared
 * savings, MSR) are recomputed here on the filtered subset, matching what the
 * Streamlit app computed in pandas, so every sidebar control stays live.
 * ---------------------------------------------------------------------- */
"use strict";

const DATA = { counties: null, oc: null, ref: null, manifest: null };

const ENROLLMENT_TYPES = ["ESRD", "Disabled", "Aged Dual", "Aged Non-Dual"];

/* ---------------------------------------------------------------- tokens */

const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

function tokens() {
  return {
    surface: css("--surface-1"),
    ink: css("--text-primary"),
    ink2: css("--text-secondary"),
    muted: css("--text-muted"),
    grid: css("--grid"),
    axis: css("--axis"),
    s1: css("--series-1"), s2: css("--series-2"), s3: css("--series-3"), s4: css("--series-4"),
    ord: [css("--ord-1"), css("--ord-2"), css("--ord-3")],
    divNeg: [css("--div-neg-1"), css("--div-neg-2"), css("--div-neg-3")],
    divMid: css("--div-mid"),
    divPos: [css("--div-pos-1"), css("--div-pos-2"), css("--div-pos-3"), css("--div-pos-4")],
    warn: css("--warn"),
    crit: css("--crit")
  };
}

function layout(extra = {}) {
  const t = tokens();
  return Object.assign({
    margin: { l: 58, r: 16, t: 16, b: 44 },
    paper_bgcolor: "rgba(0,0,0,0)",
    plot_bgcolor: "rgba(0,0,0,0)",
    font: { size: 11, color: t.ink2, family: 'system-ui, -apple-system, "Segoe UI", sans-serif' },
    hoverlabel: { bgcolor: t.surface, bordercolor: t.axis, font: { color: t.ink, size: 11 } },
    xaxis: { gridcolor: t.grid, zeroline: false, linecolor: t.axis, tickfont: { color: t.muted } },
    yaxis: { gridcolor: t.grid, zeroline: false, linecolor: t.axis, tickfont: { color: t.muted } },
    legend: { orientation: "h", yanchor: "bottom", y: 1.02, xanchor: "right", x: 1, font: { size: 10 } },
    bargap: 0.28
  }, extra);
}

const PLOT_CONFIG = { displayModeBar: false, responsive: true };

function draw(id, traces, extra) {
  Plotly.react(document.getElementById(id), traces, layout(extra), PLOT_CONFIG);
}

/* ------------------------------------------------------------- utilities */

const fmtPct = (v, d = 1) => (v === null || v === undefined || Number.isNaN(v))
  ? "—" : `${v >= 0 ? "+" : ""}${(v * 100).toFixed(d)}%`;
const fmtPctPlain = (v, d = 1) => (v === null || v === undefined || Number.isNaN(v))
  ? "—" : `${(v * 100).toFixed(d)}%`;
const fmtUsd = (v, d = 0) => (v === null || v === undefined || Number.isNaN(v))
  ? "—" : `$${v.toLocaleString(undefined, { minimumFractionDigits: d, maximumFractionDigits: d })}`;
const fmtInt = (v) => (v === null || v === undefined || Number.isNaN(v))
  ? "—" : Math.round(v).toLocaleString();

const mean = (xs) => {
  const v = xs.filter((x) => x !== null && x !== undefined && !Number.isNaN(x));
  return v.length ? v.reduce((a, b) => a + b, 0) / v.length : NaN;
};
const std = (xs) => {
  const v = xs.filter((x) => x !== null && !Number.isNaN(x));
  if (!v.length) return NaN;
  const m = v.reduce((a, b) => a + b, 0) / v.length;
  return Math.sqrt(v.reduce((a, b) => a + (b - m) ** 2, 0) / v.length);
};
const median = (xs) => {
  const v = xs.filter((x) => x !== null && !Number.isNaN(x)).sort((a, b) => a - b);
  if (!v.length) return NaN;
  const mid = v.length >> 1;
  return v.length % 2 ? v[mid] : (v[mid - 1] + v[mid]) / 2;
};
/** Linear-interpolated quantile, matching pandas' default. */
function quantile(sorted, q) {
  if (!sorted.length) return NaN;
  const pos = (sorted.length - 1) * q;
  const lo = Math.floor(pos), hi = Math.ceil(pos);
  return lo === hi ? sorted[lo] : sorted[lo] + (sorted[hi] - sorted[lo]) * (pos - lo);
}
/** Bin index for right-closed intervals, i.e. pandas' pd.cut(right=True). */
function binIndex(value, edges) {
  for (let i = 0; i < edges.length - 1; i++) {
    if (value > edges[i] && value <= edges[i + 1]) return i;
  }
  return -1;
}
/** Deterministic thinning - reproducible across reloads, unlike a random sample. */
function thin(rows, cap) {
  if (rows.length <= cap) return rows;
  const stride = rows.length / cap;
  const out = [];
  for (let i = 0; i < cap; i++) out.push(rows[Math.floor(i * stride)]);
  return out;
}
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => (
  { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

/* ------------------------------------------------------------ data model */

/** Decode the column-indexed payload into objects once, at load. */
function decodeCounties(payload) {
  const { states, counties, rows } = payload;
  return rows.map((r) => {
    const c = counties[r[0]];
    return {
      countyName: c[1],
      stateName: states[c[0]],
      stateId: c[2],
      countyId: c[3],
      enrollment: payload.enrollment_types[r[1]],
      risk: r[2],
      exp: r[3],
      demog: r[4],
      personYears: r[5],
      yoy: r[6],
      expGrowth: r[7],
      ocDelta: r[8],
      confounded: r[9] === 1
    };
  });
}

/* ------------------------------------------------------- derived measures */

/**
 * V28 coding exposure index, mirroring compute_v28_exposure_index().
 * raw score per enrollment type comes from the Python constants via
 * reference.json, so the HCC weight tables live in one place only.
 */
function addV28Index(rows) {
  const raw = DATA.ref.v28_raw_exposure;
  for (const type of ENROLLMENT_TYPES) {
    const subset = rows.filter((r) => r.enrollment === type);
    if (!subset.length) continue;
    const nationalAvg = mean(subset.map((r) => r.risk));
    const rawScore = raw[type] ?? 0;
    for (const r of subset) {
      const score = (r.risk === 0 || r.risk === null) ? nationalAvg : r.risk;
      r.v28Index = rawScore / Math.max(score, 0.01);
    }
  }
  for (const r of rows) if (r.v28Index === undefined) r.v28Index = 0;
}

/**
 * RADV proxy composite, mirroring compute_radv_exposure_score():
 * min-max normalise |YoY|, |exp growth| and |V28 index| over the current
 * selection, then weight 0.4 / 0.4 / 0.2.
 */
function addRadvScore(rows) {
  const norm = (get) => {
    const vals = rows.map((r) => Math.abs(get(r) ?? 0));
    const lo = Math.min(...vals), hi = Math.max(...vals);
    return hi === lo ? vals.map(() => 0) : vals.map((v) => (v - lo) / (hi - lo));
  };
  const y = norm((r) => r.yoy);
  const e = norm((r) => r.expGrowth);
  const v = norm((r) => r.v28Index);

  rows.forEach((r, i) => {
    r.radvScore = y[i] * 0.4 + e[i] * 0.4 + v[i] * 0.2;
    r.efficiency = (r.risk && r.exp !== null) ? r.exp / r.risk : null;
  });

  // Exposure level is banded on *relative terciles* of the composite within the
  // current selection, not on fixed 0.33/0.67 cut points. Min-max normalisation
  // is dominated by a handful of tiny-denominator counties with extreme
  // expenditure swings, which compresses almost every row below 0.33 - fixed
  // bands would paint the whole map "Low" and the encoding would carry nothing.
  const ranked = rows.map((r) => r.radvScore).sort((a, b) => a - b);
  const q67 = quantile(ranked, 0.67), q33 = quantile(ranked, 0.33);
  for (const r of rows) {
    r.radvLevel = r.radvScore >= q67 ? "High" : (r.radvScore >= q33 ? "Medium" : "Low");
  }

  // Separately, the v5 "flagged" indicator stays the top decile of unconfounded
  // rows, so confounded outliers cannot drag the cutoff.
  const clean = rows.filter((r) => !r.confounded).map((r) => r.radvScore).sort((a, b) => a - b);
  const cutoff = quantile(clean, 0.90);
  for (const r of rows) r.radvFlag = !r.confounded && r.radvScore > cutoff;
}

/**
 * Benchmarks + shared savings, mirroring build_benchmark() and
 * calculate_shared_savings(). National average risk is taken over the
 * *filtered* selection, exactly as the Streamlit app did.
 */
function addSavings(rows, track) {
  const p = DATA.ref.track_params[track] || DATA.ref.track_params.A;
  const b = DATA.ref.benchmark;
  const nationalAvgRisk = mean(rows.map((r) => r.risk));

  for (const r of rows) {
    const exp = r.exp ?? 0;
    const risk = (r.risk === null || r.risk === undefined) ? nationalAvgRisk : r.risk;
    const scale = b.trend_factor * (risk / nationalAvgRisk);
    r.benchV24 = exp * scale * b.v24_factor;
    r.benchV28 = exp * scale * b.v28_factor;
    r.benchmark = r.benchV28;

    r.savingsRatio = r.benchmark ? (r.benchmark - r.exp) / r.benchmark : null;
    r.msr = msrThreshold(r.personYears ?? 0, p.msr_base, p.msr_floor);
    r.savingsStatus = categorise(r.savingsRatio, r.msr, p.two_sided);
    r.netAcoRatio = r.savingsRatio === null ? 0
      : (r.savingsRatio >= 0 ? r.savingsRatio * p.sharing_rate
        : (p.two_sided ? r.savingsRatio * p.loss_sharing_rate : 0));
  }
}

/** Sliding MSR: msr_base at <=5k person-years, easing to msr_floor at >=60k. */
function msrThreshold(personYears, base, floor, lower = 5000, upper = 60000) {
  if (personYears >= upper) return floor;
  if (personYears <= lower) return base;
  return base - (personYears - lower) * ((base - floor) / (upper - lower));
}

function categorise(value, msr, twoSided) {
  if (value === null || Number.isNaN(value)) return "unknown";
  if (value >= msr) return "qualified_savings";
  if (value > 0) return "savings_below_msr";
  if (value === 0) return "break_even";
  return twoSided ? "shared_loss" : "loss_not_shared";
}

const RAF_BANDS = [
  { label: "0.70–0.85", lo: 0, hi: 0.85 },
  { label: "0.86–1.00", lo: 0.85, hi: 1.00 },
  { label: "1.01–1.20", lo: 1.00, hi: 1.20 },
  { label: "1.21–1.50", lo: 1.20, hi: 1.50 },
  { label: "1.51+", lo: 1.50, hi: Infinity }
];
const rafBand = (risk) => (risk === null || risk === undefined) ? null
  : (RAF_BANDS.find((b) => risk > b.lo && risk <= b.hi)?.label ?? null);

/* ------------------------------------------------------------------ state */

const S = {
  tab: "a",
  state: "All states",
  enrollment: "All types",
  threshold: 0,
  track: "A",
  raf: "All bands",
  v28: "Show both",
  service: "All services",
  moduleC: false
};

let ALL_ROWS = [];

function selection() {
  let rows = ALL_ROWS;
  if (S.state !== "All states") rows = rows.filter((r) => r.stateName === S.state);
  if (S.enrollment !== "All types") rows = rows.filter((r) => r.enrollment === S.enrollment);
  rows = rows.map((r) => Object.assign({}, r));
  addV28Index(rows);
  addRadvScore(rows);
  addSavings(rows, S.track);
  return rows;
}

/* ------------------------------------------------------------- Module A */

const YOY_EDGES = [-Infinity, -0.05, 0, 0.02, 0.05, 0.10, 0.15, Infinity];
const YOY_LABELS = ["<−5%", "−5–0%", "0–2%", "2–5%", "5–10%", "10–15%", ">15%"];
const RISK_EDGES = [0, 0.70, 0.85, 1.00, 1.20, 1.50, Infinity];
const RISK_LABELS = ["<0.70", "0.70–0.85", "0.86–1.00", "1.01–1.20", "1.21–1.50", "1.51+"];

function renderModuleA(rows) {
  const t = tokens();
  const hasYoy = rows.some((r) => r.yoy !== null && r.yoy !== undefined);

  // The "Min YoY delta threshold" slider used to be read only inside
  // renderRankedTable(), so moving it updated the table underneath while the
  // histogram, scatter and OC chart above stayed on the unfiltered set --
  // the whole tab looked unresponsive except for the one panel that changed.
  // Apply it once here and feed every panel the same filtered population, with
  // the same "fall back to the full set rather than show nothing" behaviour
  // the table already had.
  const thresholdActive = hasYoy && S.threshold > 0;
  const aboveThreshold = thresholdActive
    ? rows.filter((r) => Math.abs(r.yoy ?? 0) >= S.threshold / 100)
    : rows;
  const thresholdFellBack = thresholdActive && aboveThreshold.length === 0;
  const viewRows = aboveThreshold.length ? aboveThreshold : rows;

  /* --- Histogram: YoY delta, or absolute risk when no prior year exists --- */
  const useCol = hasYoy ? "yoy" : "risk";
  const edges = hasYoy ? YOY_EDGES : RISK_EDGES;
  const labels = hasYoy ? YOY_LABELS : RISK_LABELS;
  // Diverging: blue arm below zero, neutral at no-change, red arm above.
  const colors = hasYoy
    ? [t.divNeg[2], t.divNeg[0], t.divMid, t.divPos[0], t.divPos[1], t.divPos[2], t.divPos[3]]
    : [t.divNeg[2], t.divNeg[1], t.divNeg[0], t.divMid, t.divPos[1], t.divPos[3]];

  const values = viewRows.map((r) => r[useCol]).filter((v) => v !== null && v !== undefined);
  const counts = new Array(labels.length).fill(0);
  for (const v of values) {
    const i = binIndex(v, edges);
    if (i >= 0) counts[i]++;
  }

  document.getElementById("a-hist-title").textContent = hasYoy
    ? "Risk score YoY delta distribution"
    : `Risk score distribution (${DATA.manifest.latest_year})`;
  document.getElementById("a-hist-cap").textContent = hasYoy
    ? "AVG_RISK_SCORE delta by county · blue below zero, red above · source: derived"
    : "Year-over-year delta unavailable for this selection — showing absolute risk score · source: derived";

  draw("chart-a-hist", [{
    type: "bar", x: labels, y: counts,
    marker: { color: colors, line: { width: 2, color: t.surface } },
    text: counts.map((c) => c ? c.toLocaleString() : ""), textposition: "outside",
    textfont: { color: t.ink2, size: 10 },
    hovertemplate: "%{x}<br>%{y:,} counties<extra></extra>",
    showlegend: false
  }], {
    yaxis: Object.assign(layout().yaxis, { title: { text: "Counties", font: { size: 10 } } }),
    xaxis: Object.assign(layout().xaxis, {
      title: { text: hasYoy ? "YoY risk score delta" : "Risk score band", font: { size: 10 } }
    })
  });

  const thresholdNote = thresholdActive
    ? (thresholdFellBack
        ? ` · no counties clear the ${S.threshold}% threshold — showing all counties instead`
        : ` · filtered to |YoY delta| ≥ ${S.threshold}%`)
    : "";
  document.getElementById("a-hist-foot").textContent = (hasYoy
    ? `n=${values.length.toLocaleString()} · mean ${fmtPct(mean(values))} · bars show county count per risk tier`
    : `n=${values.length.toLocaleString()} counties · bars show count per RAF band`) + thresholdNote;

  /* --- Scatter: YoY delta vs. efficiency ratio, coloured by RADV level --- */
  const LEVELS = [
    { name: "Low", color: t.ord[0], symbol: "circle" },
    { name: "Medium", color: t.ord[1], symbol: "diamond" },
    { name: "High", color: t.ord[2], symbol: "triangle-up" }
  ];
  let pts = viewRows.filter((r) =>
    r.efficiency !== null && r[useCol] !== null && (r.personYears ?? 0) >= 10);
  pts = thin(pts, 600);

  const scatterTraces = LEVELS.map((lvl) => {
    const sub = pts.filter((r) => r.radvLevel === lvl.name);
    return {
      type: "scatter", mode: "markers", name: lvl.name,
      x: sub.map((r) => r[useCol]),
      y: sub.map((r) => r.efficiency),
      customdata: sub.map((r) => [`${r.countyName}, ${r.stateName}`, r.enrollment, r.radvScore]),
      marker: {
        color: lvl.color, symbol: lvl.symbol, size: 6.5, opacity: 0.78,
        line: { width: 1, color: t.surface }
      },
      hovertemplate: "<b>%{customdata[0]}</b><br>%{customdata[1]}<br>"
        + (hasYoy ? "YoY delta %{x:+.2%}" : "Risk score %{x:.3f}")
        + "<br>Efficiency $%{y:,.0f}<br>Composite %{customdata[2]:.3f}<extra></extra>"
    };
  }).filter((tr) => tr.x.length);

  document.getElementById("a-scatter-legend").innerHTML = LEVELS.map((l) =>
    `<span><span class="dot" style="background:${l.color}"></span>${l.name} RADV exposure</span>`).join("");

  draw("chart-a-scatter", scatterTraces, {
    showlegend: false,
    // Wider margins than the shared default: dollar-formatted y ticks (e.g.
    // "$150,000") and percent-formatted x ticks both need real clearance
    // from their axis titles, which the default 58/44 margins didn't leave --
    // titles were sitting right against the tick labels.
    margin: { l: 70, r: 16, t: 16, b: 54 },
    xaxis: Object.assign(layout().xaxis, {
      title: { text: hasYoy ? "YoY risk score delta" : "Risk score", font: { size: 10 }, standoff: 14 },
      tickformat: hasYoy ? ".0%" : ".2f"
    }),
    yaxis: Object.assign(layout().yaxis, {
      title: { text: "Efficiency ratio ($/unit)", font: { size: 10 }, standoff: 14 },
      tickprefix: "$", tickformat: ",.0f"
    })
  });
  document.getElementById("a-scatter-foot").textContent =
    `n=${pts.length.toLocaleString()} county × enrollment rows shown · person_years ≥ 10 · `
    + `thinned deterministically from ${viewRows.filter((r) => r.efficiency !== null && (r.personYears ?? 0) >= 10).length.toLocaleString()}`
    + thresholdNote;

  renderOcChart(viewRows);
  renderRankedTable(viewRows, hasYoy);
}

/**
 * OC-cut stability. The earliest operational cut's risk score is recovered
 * from the FINAL score and the stored oc_delta, so the chart responds to the
 * sidebar filters instead of being a fixed precomputed picture.
 */
function renderOcChart(rows) {
  const t = tokens();
  const cuts = (DATA.oc && DATA.oc.available) ? DATA.oc.cuts : null;
  const foot = document.getElementById("a-oc-foot");

  const withOc = rows.filter((r) => r.ocDelta !== null && r.ocDelta !== undefined && r.risk);
  if (!cuts || !withOc.length) {
    draw("chart-a-oc", [], {});
    document.getElementById("chart-a-oc").innerHTML =
      '<p class="empty">No operational-cut vintage was published for this performance year, '
      + 'so cut-to-final movement cannot be computed.</p>';
    foot.textContent = "";
    return;
  }

  for (const r of withOc) r.ocBase = r.risk / (1 + r.ocDelta);

  const nationalSeries = {
    type: "scatter", mode: "lines+markers", name: "All counties in view (mean)",
    x: cuts, y: [mean(withOc.map((r) => r.ocBase)), mean(withOc.map((r) => r.risk))],
    line: { color: t.s1, width: 2.5 },
    marker: { color: t.s1, size: 9, line: { width: 2, color: t.surface } },
    hovertemplate: "%{x}<br>mean risk %{y:.4f}<extra>mean</extra>"
  };

  const movers = withOc.slice()
    .sort((a, b) => Math.abs(b.ocDelta) - Math.abs(a.ocDelta))
    .slice(0, 3);
  const moverColors = [t.s2, t.s3, t.s4];
  const moverTraces = movers.map((r, i) => ({
    type: "scatter", mode: "lines+markers+text", name: `${r.countyName}, ${r.stateName}`,
    x: cuts, y: [r.ocBase, r.risk],
    line: { color: moverColors[i], width: 2 },
    marker: { color: moverColors[i], size: 8, line: { width: 2, color: t.surface } },
    text: ["", `  ${r.countyName} ${fmtPct(r.ocDelta)}`],
    textposition: "middle right", textfont: { size: 9.5, color: t.ink2 }, cliponaxis: false,
    hovertemplate: `<b>${esc(r.countyName)}, ${esc(r.stateName)}</b> (${esc(r.enrollment)})`
      + "<br>%{x}: %{y:.4f}<extra></extra>"
  }));

  draw("chart-a-oc", [nationalSeries, ...moverTraces], {
    margin: { l: 58, r: 150, t: 16, b: 40 },
    yaxis: Object.assign(layout().yaxis, { title: { text: "avg_risk_score", font: { size: 10 } } }),
    xaxis: Object.assign(layout().xaxis, { title: { text: "Data cut", font: { size: 10 } } }),
    hovermode: "closest"
  });

  const stableHigh = DATA.oc.stable_high_count;
  foot.textContent =
    `${withOc.length.toLocaleString()} county × enrollment rows have both a ${cuts[0]} and a FINAL vintage. `
    + `Nationally ${stableHigh.toLocaleString()} rows are "stable-high" (|delta| < 2% and FINAL score more than `
    + "1 SD above the mean) — the carry-forward coding pattern CMS RADV targets. "
    + "The three largest movers in the current selection are labelled.";
}

function renderRankedTable(rows, hasYoy) {
  // rows is already threshold-filtered by renderModuleA(), same as the
  // histogram, scatter and OC chart -- this used to re-filter independently,
  // which is exactly why the table changed with the slider and nothing else did.
  const t = tokens();
  const ranked = rows.slice().sort((a, b) => (b.radvScore ?? 0) - (a.radvScore ?? 0));
  const top = ranked.slice(0, 20);

  const flagColor = { Low: t.ord[0], Medium: t.ord[1], High: t.ord[2] };

  const head = ["County", "State", "Enroll type", hasYoy ? "YoY risk Δ" : "Risk score",
    "Exp growth ratio", "V28 delta est.", "OC stability", "Composite", "RADV flag", "Confounded"];

  // Column definitions, matched to what each figure actually is computed from
  // (addRadvScore / addV28Index / renderOcChart) -- shown as a native tooltip
  // on hover so the abbreviated header text isn't the only explanation.
  const defs = [
    null, null, null,
    hasYoy
      ? "Year-over-year change in AVG_RISK_SCORE vs. the prior published performance "
        + "year: (current − prior) / prior."
      : "AVG_RISK_SCORE for the current year. Shown instead of a YoY delta because no "
        + "prior year is available for this selection.",
    "Year-over-year change in per-capita expenditure (PER_CAPITA_EXP), computed the "
      + "same way as YoY risk Δ.",
    "Estimated net V28 coding-model exposure for this enrollment type, normalized by "
      + "the county's risk score. Positive = net V28 compression (score likely falls "
      + "under V28); negative = net V28 benefit (score likely rises). A directional "
      + "estimate from CMS Announcement Tables, not fitted to this data.",
    "Whether AVG_RISK_SCORE moved less than 2% between the earliest operational cut "
      + "and the FINAL vintage; the percentage shown is that cut-to-final delta. Large, "
      + "stable-high movement can indicate carry-forward or single-encounter coding.",
    "RADV exposure composite: 0.4 × |YoY risk Δ| + 0.4 × |Exp growth ratio| + "
      + "0.2 × |V28 delta est.|, each normalized 0–1 within the current selection. "
      + "Illustrative weights, pending empirical validation.",
    "Exposure tier (Low / Medium / High) by tercile of the Composite score within the "
      + "current selection — not a fixed threshold.",
    "Whether a known confounder may distort the composite for this row: a TEAM "
      + "bundled-payment county, the PY2024 V28 transition year, or an ESRD/Disabled "
      + "enrollment share that shifted >5pp year over year.",
  ];

  document.querySelector("#table-a thead").innerHTML = `<tr>${head.map((h, i) => {
    const classAttr = i >= 3 && i <= 7 ? ' class="num"' : "";
    // title="" is kept for screen readers and as a native fallback; the
    // visible tooltip itself is the data-tip CSS popover (see index.html) --
    // it appears immediately on hover/focus, where title has a real delay
    // and no touch support at all.
    const tipAttrs = defs[i] ? ` title="${esc(defs[i])}" data-tip="${esc(defs[i])}" tabindex="0"` : "";
    return `<th${classAttr}${tipAttrs}>${h}</th>`;
  }).join("")}</tr>`;

  document.querySelector("#table-a tbody").innerHTML = top.map((r) => {
    const flag = r.radvLevel;
    const ocText = (r.ocDelta === null || r.ocDelta === undefined) ? "—"
      : (Math.abs(r.ocDelta) < 0.02 ? "Stable" : "Unstable");
    return `<tr>
      <td>${esc(r.countyName)}</td>
      <td>${esc(r.stateName)}</td>
      <td>${esc(r.enrollment)}</td>
      <td class="num">${hasYoy ? fmtPct(r.yoy, 2) : (r.risk?.toFixed(3) ?? "—")}</td>
      <td class="num">${fmtPct(r.expGrowth, 2)}</td>
      <td class="num">${r.v28Index !== undefined ? (r.v28Index >= 0 ? "+" : "") + r.v28Index.toFixed(3) : "—"}</td>
      <td class="num">${ocText}${r.ocDelta !== null && r.ocDelta !== undefined ? ` (${fmtPct(r.ocDelta)})` : ""}</td>
      <td class="num">${r.radvScore.toFixed(3)}</td>
      <td><span class="dot" style="background:${flagColor[flag]}"></span>${flag}</td>
      <td>${r.confounded ? "Yes" : "No"}</td>
    </tr>`;
  }).join("") || '<tr><td colspan="10" class="empty">No counties match the current filters.</td></tr>';
}

/* ------------------------------------------------------------- Module B */

const SAV_EDGES = [-Infinity, -0.10, -0.05, -0.01, 0.01, 0.03, 0.05, Infinity];
const SAV_LABELS = ["<−10%", "−5–10%", "−1–5%", "Break-even", "+1–3%", "+3–5%", ">+5%"];

function renderModuleB(rows) {
  const t = tokens();
  let scoped = rows;
  if (S.raf !== "All bands") scoped = scoped.filter((r) => rafBand(r.risk) === S.raf);
  if (!scoped.length) scoped = rows;

  /* --- Savings distribution: loss (red) <- break-even -> savings (blue) --- */
  const ratios = scoped.map((r) => r.savingsRatio).filter((v) => v !== null && !Number.isNaN(v));
  const counts = new Array(SAV_LABELS.length).fill(0);
  for (const v of ratios) {
    const i = binIndex(v, SAV_EDGES);
    if (i >= 0) counts[i]++;
  }
  const savColors = [t.divPos[3], t.divPos[2], t.divPos[0], t.divMid,
    t.divNeg[0], t.divNeg[1], t.divNeg[2]];

  const msrPct = mean(scoped.map((r) => r.msr));
  draw("chart-b-hist", [{
    type: "bar", x: SAV_LABELS, y: counts,
    marker: { color: savColors, line: { width: 2, color: t.surface } },
    text: counts.map((c) => c ? c.toLocaleString() : ""), textposition: "outside",
    textfont: { color: t.ink2, size: 10 },
    hovertemplate: "%{x}<br>%{y:,} counties<extra></extra>", showlegend: false
  }], {
    yaxis: Object.assign(layout().yaxis, { title: { text: "Counties", font: { size: 10 } } }),
    shapes: [{
      type: "line", x0: 3.5, x1: 3.5, y0: 0, y1: 1, yref: "paper",
      line: { color: t.ink2, width: 1.5, dash: "dot" }
    }],
    annotations: [{
      x: 3.5, y: 1.06, yref: "paper", showarrow: false,
      text: `mean MSR ${fmtPctPlain(msrPct)}`, font: { size: 9.5, color: t.ink2 }
    }]
  });
  const qualified = scoped.filter((r) => r.savingsStatus === "qualified_savings").length;
  document.getElementById("b-hist-foot").textContent =
    `Track ${S.track} · n=${ratios.length.toLocaleString()} · `
    + `${qualified.toLocaleString()} clear their size-adjusted MSR; savings to the left of the marker do not qualify.`;

  /* --- Benchmark vs. actual by RAF quartile --- */
  const sortedRisk = scoped.map((r) => r.risk ?? 0).sort((a, b) => a - b);
  const cuts = [0.25, 0.5, 0.75].map((q) => quantile(sortedRisk, q));
  const qLabels = ["Q1 (low RAF)", "Q2", "Q3", "Q4 (high RAF)"];
  const qIndex = (risk) => {
    const v = risk ?? 0;
    if (v <= cuts[0]) return 0;
    if (v <= cuts[1]) return 1;
    if (v <= cuts[2]) return 2;
    return 3;
  };
  const buckets = qLabels.map(() => ({ actual: [], v28: [], v24: [] }));
  for (const r of scoped) {
    const b = buckets[qIndex(r.risk)];
    b.actual.push(r.exp); b.v28.push(r.benchV28); b.v24.push(r.benchV24);
  }

  // Colour follows the entity: Actual is always slot 1, V28 slot 2, V24 slot 3,
  // so hiding V24 never repaints the other two.
  const series = [
    { name: "Actual", key: "actual", color: t.s1 },
    { name: "Benchmark (V28 adj.)", key: "v28", color: t.s2 },
    { name: "Benchmark (V24)", key: "v24", color: t.s3 }
  ].filter((s) => {
    if (S.v28 === "V28 adjusted") return s.key !== "v24";
    if (S.v28 === "V24 only") return s.key !== "v28";
    return true;
  });

  draw("chart-b-quartile", series.map((s) => ({
    type: "bar", name: s.name, x: qLabels,
    y: buckets.map((b) => mean(b[s.key])),
    marker: { color: s.color, line: { width: 2, color: t.surface } },
    hovertemplate: `${s.name}<br>%{x}<br>$%{y:,.0f}<extra></extra>`
  })), {
    barmode: "group", bargroupgap: 0.08,
    yaxis: Object.assign(layout().yaxis, {
      title: { text: "Per-capita ($)", font: { size: 10 } }, tickformat: "$,.0f"
    })
  });

  /* --- V28 version skew by enrollment type --- */
  const skew = DATA.ref.v28_skew;
  draw("chart-b-skew", [{
    type: "bar",
    x: skew.map((s) => s.enrollment_type),
    y: skew.map((s) => s.v28_delta_pct),
    marker: {
      color: skew.map((s) => (s.v28_delta_pct > 0 ? t.divNeg[1] : t.divPos[1])),
      line: { width: 2, color: t.surface }
    },
    text: skew.map((s) => `${s.v28_delta_pct > 0 ? "+" : ""}${s.v28_delta_pct.toFixed(1)}%`),
    textposition: "outside", textfont: { color: t.ink2, size: 10 },
    customdata: skew.map((s) => [s.direction, s.interpretation]),
    hovertemplate: "<b>%{x}</b><br>%{y:+.1f}%<br>%{customdata[0]}<br>%{customdata[1]}<extra></extra>",
    showlegend: false
  }], {
    yaxis: Object.assign(layout().yaxis, {
      title: { text: "V24–V28 delta (%)", font: { size: 10 } }, ticksuffix: "%"
    }),
    shapes: [{ type: "line", x0: -0.5, x1: 3.5, y0: 0, y1: 0, line: { color: t.axis, width: 1 } }]
  });

  /* --- RAF band table --- */
  const p = DATA.ref.track_params[S.track];
  document.getElementById("b-raf-cap").textContent =
    `Track ${S.track} MSR: ${fmtPctPlain(p.msr_base)} at ≤5K person-years → `
    + `${fmtPctPlain(p.msr_floor)} at >60K · sharing rate ${fmtPctPlain(p.sharing_rate, 0)} · `
    + '"At MSR" = saving but not qualifying for distribution';

  const bandRows = RAF_BANDS.map((band) => {
    const sub = scoped.filter((r) => rafBand(r.risk) === band.label);
    if (!sub.length) return null;
    const rate = mean(sub.map((r) => r.savingsRatio));
    const status = Number.isNaN(rate) ? "—"
      : (rate > 0.005 ? "Savings" : (rate > 0 ? "At MSR" : "Loss"));
    return {
      label: band.label, n: sub.length,
      bench: mean(sub.map((r) => r.benchmark)),
      actual: mean(sub.map((r) => r.exp)),
      rate, status,
      qualified: sub.filter((r) => r.savingsStatus === "qualified_savings").length
    };
  }).filter(Boolean);

  document.querySelector("#table-b thead").innerHTML =
    '<tr><th>RAF band</th><th class="num">Counties</th><th class="num">Avg benchmark</th>'
    + '<th class="num">Avg actual</th><th class="num">Savings rate</th>'
    + '<th class="num">Clear MSR</th><th>Qualifies?</th></tr>';
  document.querySelector("#table-b tbody").innerHTML = bandRows.map((b) => `<tr>
      <td>${b.label}</td>
      <td class="num">${fmtInt(b.n)}</td>
      <td class="num">${fmtUsd(b.bench)}</td>
      <td class="num">${fmtUsd(b.actual)}</td>
      <td class="num">${fmtPct(b.rate)}</td>
      <td class="num">${fmtInt(b.qualified)}</td>
      <td>${b.status}</td>
    </tr>`).join("") || '<tr><td colspan="7" class="empty">No counties in the selected RAF band.</td></tr>';
}

/* ------------------------------------------------------------- Module C */

const SERVICE_TYPES = ["Cardiology", "Ortho", "Oncology", "Neurology", "Behavioral", "Post-acute", "DME"];
const SERVICE_ADJ = [0.00, -0.03, -0.05, -0.01, -0.08, -0.12, -0.06];

function renderModuleC(rows) {
  const t = tokens();
  const disclosures = DATA.ref.disclosures || [];
  const hasDisclosures = disclosures.length > 0;

  const leftTitle = document.getElementById("c-left-title");
  const leftCap = document.getElementById("c-left-cap");
  const rightTitle = document.getElementById("c-right-title");
  const rightCap = document.getElementById("c-right-cap");

  if (hasDisclosures) {
    // Some filings report expedited volume only. Plotting those as a 0% approval
    // bar reads as "this payer approves nothing" rather than "this payer did not
    // report standard requests", so they are dropped from the rate chart and
    // named underneath it. They still appear in the volume chart.
    const rated = disclosures.filter((d) => d.total_requests > 0);
    const unrated = disclosures.filter((d) => !(d.total_requests > 0));

    leftTitle.textContent = "Real payer disclosure metrics";
    leftCap.textContent = "Approval vs. denial rates from ingested disclosures · source: external";

    const payers = rated.map((d) => d.enrollment_type);
    const approval = rated.map((d) => (d.approved_requests / d.total_requests) * 100);
    const denial = rated.map((d) => (d.denied_requests / d.total_requests) * 100);

    draw("chart-c-left", [
      {
        type: "bar", name: "Approval rate", x: payers, y: approval,
        marker: { color: t.s1, line: { width: 2, color: t.surface } },
        hovertemplate: "%{x}<br>Approval %{y:.1f}%<extra></extra>"
      },
      {
        type: "bar", name: "Denial rate", x: payers, y: denial,
        marker: { color: t.s2, line: { width: 2, color: t.surface } },
        hovertemplate: "%{x}<br>Denial %{y:.1f}%<extra></extra>"
      }
    ], {
      barmode: "stack",
      yaxis: Object.assign(layout().yaxis, {
        title: { text: "Share of requests (%)", font: { size: 10 } }, range: [0, 100], ticksuffix: "%"
      })
    });

    if (unrated.length) {
      leftCap.textContent += ` · ${unrated.map((d) => d.enrollment_type).join(", ")} `
        + `reported expedited volume only and ${unrated.length > 1 ? "are" : "is"} excluded here`;
    }

    rightTitle.textContent = "Expedited vs. total request volume";
    rightCap.textContent = "Total request volume from ingested disclosures · source: external";
    draw("chart-c-right", [
      {
        type: "bar", name: "Total requests", x: payers,
        y: disclosures.map((d) => d.total_requests),
        marker: { color: t.s1, line: { width: 2, color: t.surface } },
        hovertemplate: "%{x}<br>%{y:,} total<extra></extra>"
      },
      {
        type: "bar", name: "Expedited requests", x: payers,
        y: disclosures.map((d) => d.expedited_requests),
        marker: { color: t.s3, line: { width: 2, color: t.surface } },
        hovertemplate: "%{x}<br>%{y:,} expedited<extra></extra>"
      }
    ], {
      barmode: "group", bargroupgap: 0.08,
      yaxis: Object.assign(layout().yaxis, {
        title: { text: "Requests", font: { size: 10 } }, tickformat: "~s"
      })
    });

    renderFieldTable(DATA.ref.disclosure_fields,
      ["field_num", "cms_field", "value", "ffs_ref", "note"],
      ["#", "CMS metric field", "Actual (aggregate)", "FFS reference", "Note"],
      "Real payer disclosure metrics vs. CMS benchmarks",
      "Aggregated from ingested disclosure PDFs · source: external (actual payer reported)");
  } else {
    const base = DATA.ref.pa_summary.approved_rate ?? 0.914;
    let svc = SERVICE_TYPES.map((name, i) => {
      const approval = Math.min(0.99, Math.max(0.50, base + SERVICE_ADJ[i]));
      return { name, approval: +(approval * 100).toFixed(1), denial: +(100 - approval * 100).toFixed(1) };
    });
    if (S.service !== "All services") svc = svc.filter((s) => s.name === S.service);

    leftTitle.textContent = "Simulated PA approval / denial · by service type";
    leftCap.textContent = "Stacked 100% bar · fields 2+3 · MSSP specialty utilization proxy · source: derived";
    draw("chart-c-left", [
      {
        type: "bar", name: "Approval rate", x: svc.map((s) => s.name), y: svc.map((s) => s.approval),
        marker: { color: t.s1, line: { width: 2, color: t.surface } },
        hovertemplate: "%{x}<br>Approval %{y:.1f}%<extra></extra>"
      },
      {
        type: "bar", name: "Denial rate", x: svc.map((s) => s.name), y: svc.map((s) => s.denial),
        marker: { color: t.s2, line: { width: 2, color: t.surface } },
        hovertemplate: "%{x}<br>Denial %{y:.1f}%<extra></extra>"
      }
    ], {
      barmode: "stack",
      yaxis: Object.assign(layout().yaxis, { range: [0, 100], ticksuffix: "%" })
    });

    const burden = DATA.ref.pa_burden || [];
    rightTitle.textContent = "Estimated PA burden · admin hours per 1,000 beneficiaries";
    rightCap.textContent = "AMA 13 hr/physician/week benchmark × specialty utilization rate · source: external ref";
    draw("chart-c-right", [{
      type: "bar", x: burden.map((b) => b.county), y: burden.map((b) => b.hours),
      marker: { color: t.s1, line: { width: 2, color: t.surface } },
      hovertemplate: "County %{x}<br>%{y:.1f} hrs / 1k<extra></extra>", showlegend: false
    }], {
      yaxis: Object.assign(layout().yaxis, {
        title: { text: "Est. admin hrs / 1,000 ben", font: { size: 10 } }
      })
    });

    renderFieldTable(DATA.ref.pa_fields,
      ["field_num", "cms_field", "simulated", "ffs_ref", "ma_ref", "variance", "flag"],
      ["#", "CMS metric field", "Simulated", "FFS reference", "MA benchmark", "Variance vs. FFS", "Flag"],
      "All 7 CMS-required PA metric fields — simulated vs. benchmark",
      "CMS-0057-F public reporting schema · payers must post annually by March 31 · "
      + "drugs excluded per rule · field 4 denominator = denied decisions (not total)");
  }
}

function renderFieldTable(records, keys, headers, title, caption) {
  document.getElementById("c-table-title").textContent = title;
  document.getElementById("c-table-cap").textContent = caption;
  document.querySelector("#table-c thead").innerHTML =
    `<tr>${headers.map((h) => `<th>${esc(h)}</th>`).join("")}</tr>`;
  document.querySelector("#table-c tbody").innerHTML = (records || []).map((row) => {
    const cells = keys.map((k) => {
      if (k === "cms_field") {
        const type = row.source_type || "simulated";
        return `<td style="white-space:normal">${esc(row[k])}<span class="badge ${esc(type)}">${esc(type)}</span></td>`;
      }
      if (k === "note") return `<td style="white-space:normal">${esc(row[k] ?? "")}</td>`;
      return `<td>${esc(row[k] ?? "—")}</td>`;
    });
    return `<tr>${cells.join("")}</tr>`;
  }).join("") || `<tr><td colspan="${headers.length}" class="empty">No field data available.</td></tr>`;
}

/* ------------------------------------------------------------ sidebar KPIs */

function renderKpis(rows) {
  const el = document.getElementById("sidebar-kpis");
  const kpi = (label, value, sub) =>
    `<div class="kpi"><div class="k-label">${label}</div><div class="k-val">${value}</div>
     <div class="k-sub">${sub}</div></div>`;

  if (S.tab === "a") {
    const flagged = rows.filter((r) => r.radvFlag).length;
    const high = rows.filter((r) => r.radvLevel === "High").length;
    const medEff = median(rows.map((r) => r.efficiency));
    el.innerHTML = kpi("Counties flagged", fmtInt(flagged), `of ${rows.length.toLocaleString()} · top decile, unconfounded`)
      + kpi("High exposure tercile", fmtInt(high), "top third of composite in view")
      + kpi("Median efficiency ratio", fmtUsd(medEff), "PER_CAPITA_EXP / AVG_RISK_SCORE");
  } else if (S.tab === "b") {
    const withSavings = rows.filter((r) => (r.savingsRatio ?? -1) > 0).length;
    const qualified = rows.filter((r) => r.savingsStatus === "qualified_savings").length;
    const avgRate = mean(rows.map((r) => r.savingsRatio));
    el.innerHTML = kpi("Counties w/ savings", fmtInt(withSavings), `Track ${S.track}`)
      + kpi("Qualify after MSR", fmtInt(qualified), `${fmtInt(Math.max(withSavings - qualified, 0))} lost below MSR`)
      + kpi("Avg savings rate", fmtPct(avgRate), "national MSSP avg 1–3%");
  } else {
    const s = DATA.ref.pa_summary || {};
    el.innerHTML = kpi("Simulated denial rate", fmtPctPlain(s.denied_rate), "vs. 7.7% FFS reference")
      + kpi("Appeal overturn rate", fmtPctPlain(s.appeal_overturn_rate), "vs. >80% KFF MA data")
      + kpi("Extended review est.", fmtPctPlain(s.extended_review_rate), "modeled · no FFS equivalent");
  }
  document.getElementById("kpi-records").textContent = rows.length.toLocaleString();
}

/* --------------------------------------------------------------- render */

function render() {
  const rows = selection();
  renderKpis(rows);
  if (S.tab === "a") renderModuleA(rows);
  else if (S.tab === "b") renderModuleB(rows);
  else if (S.moduleC) renderModuleC(rows);
}

/* ---------------------------------------------------------- provenance */

function renderProvenance() {
  const m = DATA.manifest;
  const el = document.getElementById("provenance");
  const built = new Date(m.built_at);
  const ageDays = (Date.now() - built.getTime()) / 86400000;

  document.getElementById("pill-year").textContent =
    `PY${m.latest_year}${m.prior_year ? ` vs. PY${m.prior_year}` : ""}`;

  const stale = ageDays > 45 || m.catalog_source === "cache";
  el.className = "provenance" + (stale ? " stale" : "");

  const vintageRows = m.vintages.map((v) => `<tr>
      <td>PY${v.year}</td><td>${esc(v.data_cut)}</td><td>${esc(v.label)}</td>
      <td><a href="${esc(v.api_url)}" rel="noopener">${esc(v.dataset_id)}</a></td>
    </tr>`).join("");

  el.innerHTML = `
    <b>Data as published by CMS for PY${m.latest_year}.</b>
    Built ${built.toISOString().slice(0, 10)} (${Math.round(ageDays)} d ago) from
    ${m.county_rows.toLocaleString()} county × enrollment rows across
    ${m.counties.toLocaleString()} counties and ${m.states} states.
    ${m.catalog_source === "cache"
      ? "Endpoints came from the <b>cached</b> CMS catalog — live resolution failed on the last build."
      : "Endpoints resolved live from the CMS DCAT catalog."}
    This page reads committed JSON only; it makes no request to data.cms.gov, so a CMS
    endpoint change cannot break it.
    <details>
      <summary>Source vintages and dataset identifiers</summary>
      <div class="tw"><table>
        <thead><tr><th>Year</th><th>Cut</th><th>CMS vintage</th><th>Dataset UUID (volatile)</th></tr></thead>
        <tbody>${vintageRows}</tbody>
      </table></div>
    </details>`;
}

/* ---------------------------------------------------------------- wiring */

function selectTab(tab) {
  S.tab = tab;
  for (const key of ["a", "b", "c"]) {
    document.getElementById(`tab-${key}`).setAttribute("aria-selected", String(key === tab));
    document.getElementById(`panel-${key}`).hidden = key !== tab;
  }
  document.getElementById("filters-a").hidden = tab !== "a";
  document.getElementById("filters-b").hidden = tab !== "b";
  document.getElementById("filters-c").hidden = tab !== "c";
  render();
}

function bind() {
  const stateSel = document.getElementById("f-state");
  stateSel.innerHTML = ['<option>All states</option>']
    .concat(DATA.counties.states.map((s) => `<option>${esc(s)}</option>`)).join("");
  document.getElementById("f-enroll").innerHTML = ['<option>All types</option>']
    .concat(ENROLLMENT_TYPES.map((e) => `<option>${esc(e)}</option>`)).join("");

  const on = (id, key, transform = (v) => v) =>
    document.getElementById(id).addEventListener("change", (e) => {
      S[key] = transform(e.target.value); render();
    });

  on("f-state", "state");
  on("f-enroll", "enrollment");
  on("f-track", "track");
  on("f-raf", "raf");
  on("f-v28", "v28");
  on("f-service", "service");

  const slider = document.getElementById("f-threshold");
  slider.addEventListener("input", (e) => {
    S.threshold = Number(e.target.value);
    document.getElementById("f-threshold-val").textContent = `${S.threshold}%`;
    render();
  });

  document.getElementById("f-module-c").addEventListener("change", (e) => {
    S.moduleC = e.target.checked;
    document.getElementById("panel-c-disabled").hidden = S.moduleC;
    document.getElementById("panel-c-body").hidden = !S.moduleC;
    if (S.tab === "c") render();
  });

  for (const key of ["a", "b", "c"]) {
    document.getElementById(`tab-${key}`).addEventListener("click", () => selectTab(key));
  }

  document.getElementById("theme-toggle").addEventListener("click", () => {
    const root = document.documentElement;
    const dark = root.getAttribute("data-theme") === "dark"
      || (!root.hasAttribute("data-theme") && matchMedia("(prefers-color-scheme: dark)").matches);
    root.setAttribute("data-theme", dark ? "light" : "dark");
    render();
  });

  matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => {
    if (!document.documentElement.hasAttribute("data-theme")) render();
  });
  addEventListener("resize", () => {
    for (const el of document.querySelectorAll(".chart")) {
      if (el.data) Plotly.Plots.resize(el);
    }
  });
}

function showBootError(headline, detail) {
  const el = document.getElementById("provenance");
  el.className = "provenance error";
  el.innerHTML = `<b>${esc(headline)}</b> ${esc(detail)}`;
}

async function boot() {
  // Checked first and outside the data try/catch below, so a blocked or
  // missing chart library reports as what it is instead of surfacing as a
  // "could not load the payload" message when the payload loaded fine.
  // Real cause seen in production: a CDN version pin that 404s silently
  // leaves `Plotly` undefined, and the first Plotly.react() call inside
  // render() would otherwise throw from deep inside the data try block.
  if (typeof Plotly === "undefined") {
    showBootError(
      "Chart library failed to load.",
      "The page could not load Plotly from cdnjs.cloudflare.com. This is usually an ad "
      + "blocker, browser extension, or network policy blocking the CDN — not a data "
      + "problem. Try disabling content blockers for this site or a different network, "
      + "then reload.");
    return;
  }

  let payload;
  try {
    const [counties, oc, ref, manifest] = await Promise.all(
      ["counties", "oc_stability", "reference", "manifest"].map((name) =>
        fetch(`./data/${name}.json`, { cache: "no-cache" }).then((r) => {
          if (!r.ok) throw new Error(`${name}.json: HTTP ${r.status}`);
          return r.json();
        })));
    payload = { counties, oc, ref, manifest };
  } catch (err) {
    showBootError(
      "Could not load the committed data payload.",
      `${err.message}. The payload lives in docs/data/ and is regenerated by the `
      + "Refresh CMS data workflow.");
    return;
  }

  // A failure from here on is a rendering bug against a payload that DID
  // load correctly, so it gets its own message rather than being folded
  // into the data-load error above.
  try {
    DATA.counties = payload.counties;
    DATA.oc = payload.oc;
    DATA.ref = payload.ref;
    DATA.manifest = payload.manifest;
    ALL_ROWS = decodeCounties(payload.counties);

    renderProvenance();
    bind();
    selectTab("a");
  } catch (err) {
    showBootError(
      "The data payload loaded, but rendering it failed.",
      `${err.message}. This is a page bug, not a data problem — please report it.`);
  }
}

boot();
