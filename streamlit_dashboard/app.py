"""MSSP county-level analytics - Streamlit edition of the GitHub Pages dashboard.

A line-for-line port of docs/index.html + docs/app.js. Like the Pages site, it
talks to no API: it reads the JSON payload committed under docs/data/, which
`python -m src.build_site` produces and the "Refresh CMS data" workflow keeps
current. A CMS endpoint change can fail a build, but it cannot blank this app.

Derived measures (V28 exposure index, RADV composite, benchmarks, shared
savings, MSR) are recomputed on the filtered subset exactly as app.js does, so
every sidebar control stays live.

Run from the repository root:
    py -m pip install -r streamlit_dashboard/requirements.txt
    py -m streamlit run streamlit_dashboard/app.py
"""
from __future__ import annotations

import hashlib
import html
import inspect
import json
import math
import os
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

DATA_DIR = Path(__file__).resolve().parent.parent / "docs" / "data"
PAYLOAD_FILES = ("counties", "oc_stability", "reference", "manifest")

# Where the payload comes from. "main" (default) reads docs/data/ from the main
# branch on GitHub - the exact files the Pages site is built from - pinned to a
# single commit so the four files always belong to the same build. "local"
# reads the copy committed on this branch (offline use). MSSP_DATA_SOURCE and
# MSSP_DATA_REF can also be set as Streamlit Community Cloud secrets.
REPO = "CORPUZ-2024/mssp_analytics"


def _setting(name: str, default: str) -> str:
    try:
        if name in st.secrets:
            return str(st.secrets[name])
    except Exception:  # noqa: BLE001 - no secrets.toml is the normal local case
        pass
    return os.environ.get(name, default)

ENROLLMENT_TYPES = ["ESRD", "Disabled", "Aged Dual", "Aged Non-Dual"]

st.set_page_config(
    page_title="CMS MSSP County-Level Analytics",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------------
# Design tokens - the light set from docs/index.html
# ---------------------------------------------------------------------------

T = dict(
    surface="#fcfcfb", plane="#f9f9f7",
    ink="#0b0b0b", ink2="#52514e", muted="#898781",
    grid="#e1e0d9", axis="#c3c2b7",
    s1="#2a78d6", s2="#eb6834", s3="#1baf7a", s4="#eda100",
    ord=["#86b6ef", "#3987e5", "#184f95"],
    div_neg=["#86b6ef", "#2a78d6", "#1c5cab"],
    div_mid="#c3c2b7",
    div_pos=["#e99392", "#e34948", "#b02f2f", "#7d1f1f"],
    ok="#0ca30c", warn="#fab219", crit="#d03b3b",
)

st.markdown(
    f"""
<style>
.block-container {{ padding-top: 2.5rem !important; }}
.masthead {{ display:flex; align-items:flex-start; justify-content:space-between; gap:16px;
  flex-wrap:wrap; padding:4px 0 14px; border-bottom:1px solid rgba(11,11,11,0.10); margin-bottom:16px; }}
.masthead h1 {{ font-size:18px; font-weight:600; margin:0; padding:0; }}
.masthead .sub {{ font-size:12px; color:{T['muted']}; margin-top:3px; }}
.pill {{ font-size:11px; font-weight:500; padding:2px 10px; border-radius:99px;
  border:1px solid rgba(11,11,11,0.10); color:{T['ink2']}; white-space:nowrap; text-decoration:none; }}
.pill-row {{ display:flex; gap:6px; align-items:center; flex-wrap:wrap; }}

.sb-head {{ font-size:10px; font-weight:600; letter-spacing:.06em; text-transform:uppercase;
  color:{T['muted']}; margin:14px 0 6px; }}
.kpi {{ border:1px solid rgba(11,11,11,0.10); border-radius:8px; padding:8px 10px;
  margin-bottom:8px; background:rgba(11,11,11,0.035); }}
.kpi .k-label {{ font-size:10px; color:{T['muted']}; }}
.kpi .k-val {{ font-size:22px; font-weight:500; line-height:1.2; color:{T['ink']}; }}
.kpi .k-sub {{ font-size:10px; color:{T['muted']}; }}

.provenance {{ border:1px solid rgba(11,11,11,0.10); border-left:3px solid {T['s3']};
  border-radius:0 8px 8px 0; background:{T['surface']}; padding:10px 14px; margin-bottom:14px;
  font-size:12px; color:{T['ink2']}; }}
.provenance.stale {{ border-left-color:{T['warn']}; }}
.provenance.error {{ border-left-color:{T['crit']}; }}
.provenance b {{ color:{T['ink']}; }}
.provenance summary {{ cursor:pointer; color:{T['muted']}; font-size:11px; margin-top:6px; }}

.card-h {{ font-size:14px; font-weight:600; margin:6px 0 2px; color:{T['ink']}; }}
.cap {{ font-size:11.5px; color:{T['muted']}; margin:0 0 6px; }}
.foot {{ font-size:11px; color:{T['muted']}; margin:-6px 0 14px; }}

.formula {{ font-family:ui-monospace,"SF Mono","Cascadia Mono",monospace; font-size:12px;
  background:rgba(11,11,11,0.035); border:1px solid rgba(11,11,11,0.10); border-radius:6px;
  padding:9px 12px; margin-bottom:10px; line-height:1.7; }}
.formula .note {{ font-family:inherit; font-size:11px; color:{T['muted']}; }}

.insight {{ border-left:3px solid {T['s1']}; background:rgba(11,11,11,0.035);
  border-radius:0 8px 8px 0; padding:10px 14px; margin:8px 0 12px; }}
.insight.green {{ border-left-color:{T['s3']}; }}
.insight.amber {{ border-left-color:{T['s2']}; }}
.insight .lbl {{ font-size:10px; font-weight:600; color:{T['muted']}; text-transform:uppercase;
  letter-spacing:.05em; margin-bottom:4px; }}
.insight p {{ font-size:12.5px; line-height:1.65; margin:0; color:{T['ink2']}; }}

.tw {{ overflow-x:auto; padding-bottom:4px; }}
.tw table {{ border-collapse:collapse; width:100%; font-size:12px; }}
.tw th, .tw td {{ text-align:left; padding:6px 9px; border:none; border-bottom:1px solid {T['grid']};
  white-space:nowrap; }}
.tw th {{ color:{T['muted']}; font-weight:600; font-size:10.5px; text-transform:uppercase;
  letter-spacing:.04em; }}
.tw td.num {{ text-align:right; font-variant-numeric:tabular-nums; }}
.tw td.wrap {{ white-space:normal; }}
.tw tbody tr:hover {{ background:rgba(11,11,11,0.035); }}
.tw th[data-tip] {{ position:relative; cursor:help; text-decoration:underline dotted; }}
.tw th[data-tip]:hover::after {{ content:attr(data-tip); position:absolute; top:100%; left:0;
  margin-top:6px; z-index:30; width:max-content; max-width:260px; white-space:normal;
  font-size:11px; font-weight:400; text-transform:none; letter-spacing:normal; line-height:1.5;
  color:{T['ink']}; background:{T['surface']}; border:1px solid rgba(11,11,11,0.10);
  border-radius:6px; padding:8px 10px; box-shadow:0 4px 16px rgba(0,0,0,0.18); }}
.tw th[data-tip]:nth-last-child(-n+3):hover::after {{ left:auto; right:0; }}

.badge {{ display:inline-block; font-size:9.5px; font-weight:600; padding:1px 7px;
  border-radius:99px; margin-left:4px; border:1px solid rgba(11,11,11,0.10); color:{T['ink2']}; }}
.badge.derived {{ border-color:{T['s3']}; color:{T['s3']}; }}
.badge.external {{ border-color:{T['s2']}; color:{T['s2']}; }}
.badge.constant {{ border-color:{T['s1']}; color:{T['s1']}; }}
.dot {{ display:inline-block; width:8px; height:8px; border-radius:50%; margin-right:6px; vertical-align:-1px; }}
.legend-inline {{ display:flex; gap:14px; flex-wrap:wrap; font-size:11.5px; color:{T['ink2']}; margin-bottom:6px; }}
.empty {{ font-size:12.5px; color:{T['muted']}; padding:24px 0; text-align:center; }}
</style>
""",
    unsafe_allow_html=True,
)


def md(markup: str) -> None:
    st.markdown(markup, unsafe_allow_html=True)


esc = html.escape

# ---------------------------------------------------------------------------
# Formatting helpers (mirror fmtPct / fmtUsd / fmtInt in app.js)
# ---------------------------------------------------------------------------


def _missing(v) -> bool:
    return v is None or (isinstance(v, float) and math.isnan(v))


def fmt_pct(v, d: int = 1) -> str:
    return "—" if _missing(v) else f"{'+' if v >= 0 else ''}{v * 100:.{d}f}%"


def fmt_pct_plain(v, d: int = 1) -> str:
    return "—" if _missing(v) else f"{v * 100:.{d}f}%"


def fmt_usd(v, d: int = 0) -> str:
    return "—" if _missing(v) else f"${v:,.{d}f}"


def fmt_int(v) -> str:
    return "—" if _missing(v) else f"{int(round(v)):,}"


def nanmean(s) -> float:
    s = pd.Series(s, dtype="float64").dropna()
    return float(s.mean()) if len(s) else float("nan")


def quantile(s, q: float) -> float:
    """Linear-interpolated quantile (pandas default, same as app.js)."""
    s = pd.Series(s, dtype="float64").dropna()
    return float(s.quantile(q)) if len(s) else float("nan")


def thin(df: pd.DataFrame, cap: int) -> pd.DataFrame:
    """Deterministic thinning - reproducible across reruns, unlike a random sample."""
    if len(df) <= cap:
        return df
    stride = len(df) / cap
    return df.iloc[[int(math.floor(i * stride)) for i in range(cap)]]


def bin_counts(values: pd.Series, edges: list, labels: list) -> list[int]:
    """Counts per right-closed interval, i.e. pd.cut(right=True)."""
    cut = pd.cut(values.dropna(), bins=edges, labels=labels, right=True)
    return [int(c) for c in cut.value_counts().reindex(labels, fill_value=0)]


# ---------------------------------------------------------------------------
# Plotly helpers
# ---------------------------------------------------------------------------

_PLOTLY_PARAMS = inspect.signature(st.plotly_chart).parameters


def _axis(**extra) -> dict:
    base = dict(gridcolor=T["grid"], zeroline=False, linecolor=T["axis"],
                tickfont=dict(color=T["muted"]))
    base.update(extra)
    return base


def layout(**extra) -> dict:
    base = dict(
        template="none",
        height=300,
        margin=dict(l=58, r=16, t=16, b=44),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(size=11, color=T["ink2"], family='system-ui, -apple-system, "Segoe UI", sans-serif'),
        hoverlabel=dict(bgcolor=T["surface"], bordercolor=T["axis"], font=dict(color=T["ink"], size=11)),
        xaxis=_axis(),
        yaxis=_axis(),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1, font=dict(size=10)),
        bargap=0.28,
    )
    base.update(extra)
    return base


def title(text: str) -> dict:
    return dict(text=text, font=dict(size=10))


def draw(traces: list, **extra) -> None:
    fig = go.Figure(data=traces, layout=layout(**extra))
    kwargs = dict(config={"displayModeBar": False, "responsive": True})
    if "theme" in _PLOTLY_PARAMS:
        kwargs["theme"] = None  # keep our tokens; don't let Streamlit repaint the series
    if "width" not in _PLOTLY_PARAMS:
        kwargs["use_container_width"] = True
    st.plotly_chart(fig, **kwargs)


def heading(text: str, cap: str | None = None) -> None:
    md(f'<div class="card-h">{esc(text)}</div>' + (f'<p class="cap">{esc(cap)}</p>' if cap else ""))


def foot(text: str) -> None:
    if text:
        md(f'<p class="foot">{esc(text)}</p>')


def insight(text: str, variant: str = "") -> None:
    md(f'<div class="insight {variant}"><div class="lbl">Key finding</div><p>{text}</p></div>')


def kpi(label: str, value: str, sub: str) -> str:
    return (f'<div class="kpi"><div class="k-label">{label}</div>'
            f'<div class="k-val">{value}</div><div class="k-sub">{sub}</div></div>')


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

_cache = getattr(st, "cache_data", None) or st.experimental_memo  # type: ignore[attr-defined]


def _get(url: str, timeout: float = 15) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "mssp-analytics-streamlit"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - fixed https hosts
        return resp.read()


@_cache(ttl=900, show_spinner=False)
def resolve_commit(ref: str) -> dict:
    """Latest commit on `ref` that touched docs/data/ - i.e. the payload build."""
    url = f"https://api.github.com/repos/{REPO}/commits?sha={ref}&path=docs/data&per_page=1"
    c = json.loads(_get(url))[0]
    return {"sha": c["sha"], "date": c["commit"]["committer"]["date"], "url": c["html_url"]}


@_cache(show_spinner="Loading payload…")
def fetch_payload(sha: str) -> dict:
    """Raw bytes of the four payload files at one commit (immutable, so cached forever)."""
    return {n: _get(f"https://raw.githubusercontent.com/{REPO}/{sha}/docs/data/{n}.json")
            for n in PAYLOAD_FILES}


@_cache(show_spinner=False)
def read_local(mtimes: tuple) -> dict:
    """Raw bytes of the copy on this branch. `mtimes` busts the cache on change."""
    return {n: (DATA_DIR / f"{n}.json").read_bytes() for n in PAYLOAD_FILES}


@_cache(show_spinner=False)
def decode_payload(raw: dict) -> dict:
    out = {n: json.loads(b) for n, b in raw.items()}
    out["fingerprint"] = hashlib.sha256(raw["counties"]).hexdigest()[:12]
    p = out["counties"]
    counties = p["counties"]
    rows = p["rows"]
    df = pd.DataFrame(rows, columns=["c", "e", "risk", "exp", "demog", "personYears",
                                     "yoy", "expGrowth", "ocDelta", "confounded"])
    df["countyName"] = [counties[i][1] for i in df["c"]]
    df["stateName"] = [p["states"][counties[i][0]] for i in df["c"]]
    df["enrollment"] = [p["enrollment_types"][i] for i in df["e"]]
    df["confounded"] = df["confounded"] == 1
    for col in ("risk", "exp", "demog", "personYears", "yoy", "expGrowth", "ocDelta"):
        df[col] = pd.to_numeric(df[col], errors="coerce").astype("float64")
    out["rows"] = df.drop(columns=["c", "e"])
    return out


def load_payload() -> tuple[dict, dict]:
    """Returns (payload, source). Falls back to the local copy if GitHub fails."""
    mode = _setting("MSSP_DATA_SOURCE", "main").lower()
    ref = _setting("MSSP_DATA_REF", "main")
    fallback_reason = None
    if mode != "local":
        try:
            commit = resolve_commit(ref)
            data = decode_payload(fetch_payload(commit["sha"]))
            return data, dict(kind="github", ref=ref, **commit)
        except Exception as err:  # noqa: BLE001 - any network/API problem -> local copy
            fallback_reason = f"{type(err).__name__}: {err}"
    mtimes = tuple((DATA_DIR / f"{n}.json").stat().st_mtime for n in PAYLOAD_FILES)
    return decode_payload(read_local(mtimes)), dict(kind="local", reason=fallback_reason)


def add_v28_index(df: pd.DataFrame, raw: dict) -> None:
    """Mirrors compute_v28_exposure_index() / addV28Index()."""
    df["v28Index"] = 0.0
    for etype in ENROLLMENT_TYPES:
        mask = df["enrollment"] == etype
        if not mask.any():
            continue
        risk = df.loc[mask, "risk"]
        national_avg = nanmean(risk)
        score = risk.where(risk.notna() & (risk != 0), national_avg)
        df.loc[mask, "v28Index"] = raw.get(etype, 0) / score.clip(lower=0.01)


def add_radv_score(df: pd.DataFrame) -> None:
    """Mirrors compute_radv_exposure_score() / addRadvScore()."""
    def norm(col):
        v = df[col].fillna(0).abs()
        lo, hi = v.min(), v.max()
        return v * 0 if hi == lo else (v - lo) / (hi - lo)

    df["radvScore"] = norm("yoy") * 0.4 + norm("expGrowth") * 0.4 + norm("v28Index") * 0.2
    ok = df["risk"].notna() & (df["risk"] != 0) & df["exp"].notna()
    df["efficiency"] = np.where(ok, df["exp"] / df["risk"].where(ok, 1), np.nan)

    # Exposure level is banded on relative terciles of the composite within the
    # current selection, not fixed cut points (see app.js for the rationale).
    q67, q33 = quantile(df["radvScore"], 0.67), quantile(df["radvScore"], 0.33)
    df["radvLevel"] = np.where(df["radvScore"] >= q67, "High",
                               np.where(df["radvScore"] >= q33, "Medium", "Low"))

    # The v5 "flagged" indicator: top decile of unconfounded rows.
    cutoff = quantile(df.loc[~df["confounded"], "radvScore"], 0.90)
    df["radvFlag"] = ~df["confounded"] & (df["radvScore"] > cutoff)


def msr_threshold(py: pd.Series, base: float, floor: float, lower=5000, upper=60000) -> pd.Series:
    """Sliding MSR: base at <=5k person-years, easing to floor at >=60k."""
    mid = base - (py - lower) * ((base - floor) / (upper - lower))
    return pd.Series(np.where(py >= upper, floor, np.where(py <= lower, base, mid)), index=py.index)


def add_savings(df: pd.DataFrame, ref: dict, track: str) -> None:
    """Mirrors build_benchmark() + calculate_shared_savings() / addSavings()."""
    p = ref["track_params"].get(track, ref["track_params"]["A"])
    b = ref["benchmark"]
    national_avg_risk = nanmean(df["risk"])
    exp0 = df["exp"].fillna(0)
    risk = df["risk"].fillna(national_avg_risk)
    scale = b["trend_factor"] * (risk / national_avg_risk)
    df["benchV24"] = exp0 * scale * b["v24_factor"]
    df["benchV28"] = exp0 * scale * b["v28_factor"]
    df["benchmark"] = df["benchV28"]

    bench = df["benchmark"]
    valid = bench.notna() & (bench != 0)
    df["savingsRatio"] = np.where(valid, (bench - df["exp"]) / bench.where(valid, 1), np.nan)
    df["msr"] = msr_threshold(df["personYears"].fillna(0), p["msr_base"], p["msr_floor"])

    r, m = df["savingsRatio"], df["msr"]
    df["savingsStatus"] = np.select(
        [r.isna(), r >= m, r > 0, r == 0],
        ["unknown", "qualified_savings", "savings_below_msr", "break_even"],
        default="shared_loss" if p["two_sided"] else "loss_not_shared",
    )


RAF_BANDS = [
    ("0.70–0.85", 0, 0.85),
    ("0.86–1.00", 0.85, 1.00),
    ("1.01–1.20", 1.00, 1.20),
    ("1.21–1.50", 1.20, 1.50),
    ("1.51+", 1.50, math.inf),
]


def raf_band(risk: pd.Series) -> pd.Series:
    out = pd.Series([None] * len(risk), index=risk.index, dtype="object")
    for label, lo, hi in reversed(RAF_BANDS):
        out[(risk > lo) & (risk <= hi)] = label
    return out


# ---------------------------------------------------------------------------
# Load
# ---------------------------------------------------------------------------

try:
    DATA, SOURCE = load_payload()
except Exception as err:  # noqa: BLE001 - surface any payload problem as the Pages site does
    md(f'<div class="provenance error"><b>Could not load the committed data payload.</b> '
       f'{esc(str(err))}. The payload lives in docs/data/ and is regenerated by '
       f'<code>python -m src.build_site</code> or the Refresh CMS data workflow.</div>')
    st.stop()

REF, MANIFEST, OC = DATA["reference"], DATA["manifest"], DATA["oc_stability"]
ALL_ROWS: pd.DataFrame = DATA["rows"]

# ---------------------------------------------------------------------------
# Masthead + tabs (tab is chosen first so the sidebar can follow it)
# ---------------------------------------------------------------------------

_year_pill = f"PY{MANIFEST['latest_year']}" + (f" vs. PY{MANIFEST['prior_year']}" if MANIFEST.get("prior_year") else "")
md(f"""
<div class="masthead">
  <div>
    <h1>CORPUZ-2024 / mssp_analytics</h1>
    <div class="sub">CMS MSSP County-Level Analytics &middot; v5 spec &middot; Modules A &middot; B &middot; C</div>
  </div>
  <div class="pill-row">
    <span class="pill">{_year_pill}</span>
    <a class="pill" href="https://github.com/CORPUZ-2024/mssp_analytics" target="_blank">github</a>
    <a class="pill" href="https://corpuz-2024.github.io/mssp_analytics/" target="_blank">pages</a>
  </div>
</div>
""")

# Provenance banner
_built = datetime.fromisoformat(MANIFEST["built_at"])
_age_days = (datetime.now(timezone.utc) - _built).total_seconds() / 86400
_stale = _age_days > 45 or MANIFEST.get("catalog_source") == "cache"
_vintage_rows = "".join(
    f"<tr><td>PY{v['year']}</td><td>{esc(v['data_cut'])}</td><td>{esc(v['label'])}</td>"
    f"<td><a href=\"{esc(v['api_url'])}\" target=\"_blank\">{esc(v['dataset_id'])}</a></td></tr>"
    for v in MANIFEST["vintages"]
)
_catalog_note = (
    "Endpoints came from the <b>cached</b> CMS catalog — live resolution failed on the last build."
    if MANIFEST.get("catalog_source") == "cache"
    else "Endpoints resolved live from the CMS DCAT catalog."
)
if SOURCE["kind"] == "github":
    _source_note = (
        f'Payload read from <code>docs/data/</code> on <b>{esc(SOURCE["ref"])}</b> at commit '
        f'<a href="{esc(SOURCE["url"])}" target="_blank"><code>{SOURCE["sha"][:7]}</code></a> '
        f'({SOURCE["date"][:10]}) &mdash; the same files the GitHub Pages site is built from.'
    )
else:
    _source_note = "Payload read from the copy of <code>docs/data/</code> committed on this branch" + (
        f' &mdash; <b>GitHub was unreachable</b> ({esc(SOURCE["reason"])}), so it may lag <code>main</code>.'
        if SOURCE.get("reason") else " (MSSP_DATA_SOURCE=local).")
    _stale = _stale or bool(SOURCE.get("reason"))
_source_note += f' Payload fingerprint <code>{DATA["fingerprint"]}</code> (SHA-256 of counties.json).'

md(f"""
<div class="provenance{' stale' if _stale else ''}">
  <b>Data as published by CMS for PY{MANIFEST['latest_year']}.</b>
  Built {_built.date().isoformat()} ({round(_age_days)} d ago) from
  {MANIFEST['county_rows']:,} county &times; enrollment rows across
  {MANIFEST['counties']:,} counties and {MANIFEST['states']} states.
  {_catalog_note}
  {_source_note}
  It makes no request to data.cms.gov, so a CMS endpoint change cannot break it.
  <details>
    <summary>Source vintages and dataset identifiers</summary>
    <div class="tw"><table>
      <thead><tr><th>Year</th><th>Cut</th><th>CMS vintage</th><th>Dataset UUID (volatile)</th></tr></thead>
      <tbody>{_vintage_rows}</tbody>
    </table></div>
  </details>
</div>
""")

TABS = {
    "a": "A — HCC & RADV risk flags",
    "b": "B — Shared savings model",
    "c": "C — PA metrics (CMS-0057-F)",
}
# Options are the visible labels (not keys + format_func) so AppTest can drive them.
_radio_kwargs = dict(horizontal=True)
if "label_visibility" in inspect.signature(st.radio).parameters:
    _radio_kwargs["label_visibility"] = "collapsed"
_tab_label = st.radio("Module", list(TABS.values()), **_radio_kwargs)
TAB = next(k for k, v in TABS.items() if v == _tab_label)

# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

with st.sidebar:
    md('<div class="sb-head">Modules</div>')
    MODULE_C = st.checkbox("Enable Module C — PA metrics", value=False)

    md('<div class="sb-head">Filters</div>')
    STATE = st.selectbox("State", ["All states"] + DATA["counties"]["states"])
    ENROLL = st.selectbox("Enrollment type", ["All types"] + ENROLLMENT_TYPES)

    THRESHOLD, TRACK, RAF, V28, SERVICE = 0, "A", "All bands", "Show both", "All services"
    if TAB == "a":
        THRESHOLD = st.slider("Min YoY delta threshold (%)", 0, 20, 0, 1)
    elif TAB == "b":
        _tracks = {"A": "Track A (upside only)", "B": "Track B", "ENHANCED": "ENHANCED"}
        _track_label = st.selectbox("MSSP track", list(_tracks.values()))
        TRACK = next(k for k, v in _tracks.items() if v == _track_label)
        RAF = st.selectbox("RAF band", ["All bands"] + [b[0] for b in RAF_BANDS])
        V28 = st.selectbox("V28 adjustment", ["Show both", "V24 only", "V28 adjusted"])
    else:
        SERVICE = st.selectbox("Service type", ["All services", "Cardiology", "Ortho", "Oncology",
                                                "Neurology", "Behavioral", "Post-acute", "DME"])

    md('<div class="sb-head">Summary</div>')
    KPI_SLOT = st.empty()


def selection() -> pd.DataFrame:
    df = ALL_ROWS
    if STATE != "All states":
        df = df[df["stateName"] == STATE]
    if ENROLL != "All types":
        df = df[df["enrollment"] == ENROLL]
    df = df.reset_index(drop=True).copy()
    if df.empty:
        return df
    add_v28_index(df, REF["v28_raw_exposure"])
    add_radv_score(df)
    add_savings(df, REF, TRACK)
    return df


ROWS = selection()

# ---------------------------------------------------------------------------
# Sidebar KPIs
# ---------------------------------------------------------------------------


def render_kpis(rows: pd.DataFrame) -> None:
    n = len(rows)
    if TAB == "a":
        flagged = int(rows["radvFlag"].sum()) if n else 0
        high = int((rows["radvLevel"] == "High").sum()) if n else 0
        med_eff = float(rows["efficiency"].median()) if n else float("nan")
        body = (kpi("Counties flagged", fmt_int(flagged), f"of {n:,} · top decile, unconfounded")
                + kpi("High exposure tercile", fmt_int(high), "top third of composite in view")
                + kpi("Median efficiency ratio", fmt_usd(med_eff), "PER_CAPITA_EXP / AVG_RISK_SCORE"))
    elif TAB == "b":
        with_savings = int((rows["savingsRatio"].fillna(-1) > 0).sum()) if n else 0
        qualified = int((rows["savingsStatus"] == "qualified_savings").sum()) if n else 0
        avg_rate = nanmean(rows["savingsRatio"]) if n else float("nan")
        body = (kpi("Counties w/ savings", fmt_int(with_savings), f"Track {TRACK}")
                + kpi("Qualify after MSR", fmt_int(qualified), f"{fmt_int(max(with_savings - qualified, 0))} lost below MSR")
                + kpi("Avg savings rate", fmt_pct(avg_rate), "national MSSP avg 1–3%"))
    else:
        s = REF.get("pa_summary") or {}
        body = (kpi("Simulated denial rate", fmt_pct_plain(s.get("denied_rate")), "vs. 7.7% FFS reference")
                + kpi("Appeal overturn rate", fmt_pct_plain(s.get("appeal_overturn_rate")), "vs. &gt;80% KFF MA data")
                + kpi("Extended review est.", fmt_pct_plain(s.get("extended_review_rate")), "modeled · no FFS equivalent"))
    body += kpi("Records in view", f"{n:,}", "county &times; enrollment rows")
    KPI_SLOT.markdown(body, unsafe_allow_html=True)


render_kpis(ROWS)

if ROWS.empty:
    md('<p class="empty">No counties match the current filters.</p>')
    st.stop()

# ---------------------------------------------------------------------------
# Module A
# ---------------------------------------------------------------------------

YOY_EDGES = [-math.inf, -0.05, 0, 0.02, 0.05, 0.10, 0.15, math.inf]
YOY_LABELS = ["<−5%", "−5–0%", "0–2%", "2–5%", "5–10%", "10–15%", ">15%"]
RISK_EDGES = [0, 0.70, 0.85, 1.00, 1.20, 1.50, math.inf]
RISK_LABELS = ["<0.70", "0.70–0.85", "0.86–1.00", "1.01–1.20", "1.21–1.50", "1.51+"]


def render_module_a(rows: pd.DataFrame) -> None:
    has_yoy = rows["yoy"].notna().any()

    # The threshold slider feeds every panel the same filtered population, falling
    # back to the full set rather than showing nothing.
    threshold_active = has_yoy and THRESHOLD > 0
    above = rows[rows["yoy"].fillna(0).abs() >= THRESHOLD / 100] if threshold_active else rows
    fell_back = threshold_active and above.empty
    view = rows if above.empty else above

    use_col = "yoy" if has_yoy else "risk"
    edges, labels = (YOY_EDGES, YOY_LABELS) if has_yoy else (RISK_EDGES, RISK_LABELS)
    colors = ([T["div_neg"][2], T["div_neg"][0], T["div_mid"], T["div_pos"][0], T["div_pos"][1],
               T["div_pos"][2], T["div_pos"][3]] if has_yoy else
              [T["div_neg"][2], T["div_neg"][1], T["div_neg"][0], T["div_mid"], T["div_pos"][1], T["div_pos"][3]])

    values = view[use_col].dropna()
    counts = bin_counts(values, edges, labels)

    threshold_note = ""
    if threshold_active:
        threshold_note = (f" · no counties clear the {THRESHOLD}% threshold — showing all counties instead"
                          if fell_back else f" · filtered to |YoY delta| ≥ {THRESHOLD}%")

    c1, c2 = st.columns(2)
    with c1:
        heading("Risk score YoY delta distribution" if has_yoy
                else f"Risk score distribution ({MANIFEST['latest_year']})",
                "AVG_RISK_SCORE delta by county · blue below zero, red above · source: derived" if has_yoy
                else "Year-over-year delta unavailable for this selection — showing absolute risk score · source: derived")
        draw([go.Bar(
            x=labels, y=counts,
            marker=dict(color=colors, line=dict(width=2, color=T["surface"])),
            text=[f"{c:,}" if c else "" for c in counts], textposition="outside",
            textfont=dict(color=T["ink2"], size=10), cliponaxis=False,
            hovertemplate="%{x}<br>%{y:,} counties<extra></extra>", showlegend=False,
        )], yaxis=_axis(title=title("Counties")),
            xaxis=_axis(title=title("YoY risk score delta" if has_yoy else "Risk score band")))
        foot((f"n={len(values):,} · mean {fmt_pct(nanmean(values))} · bars show county count per risk tier"
              if has_yoy else f"n={len(values):,} counties · bars show count per RAF band") + threshold_note)

    with c2:
        heading("Risk score growth vs. expenditure efficiency ratio",
                "X: YoY delta (%) · Y: PER_CAPITA_EXP / AVG_RISK_SCORE ($/unit) · source: derived")
        levels = [("Low", T["ord"][0], "circle"), ("Medium", T["ord"][1], "diamond"),
                  ("High", T["ord"][2], "triangle-up")]
        md('<div class="legend-inline">' + "".join(
            f'<span><span class="dot" style="background:{c}"></span>{n} RADV exposure</span>'
            for n, c, _ in levels) + "</div>")
        eligible = view[view["efficiency"].notna() & (view["personYears"].fillna(0) >= 10)]
        pts = thin(eligible[eligible[use_col].notna()], 600)
        traces = []
        for name, color, symbol in levels:
            sub = pts[pts["radvLevel"] == name]
            if sub.empty:
                continue
            traces.append(go.Scatter(
                mode="markers", name=name, x=sub[use_col], y=sub["efficiency"],
                customdata=np.stack([sub["countyName"] + ", " + sub["stateName"],
                                     sub["enrollment"], sub["radvScore"].round(3)], axis=-1),
                marker=dict(color=color, symbol=symbol, size=6.5, opacity=0.78,
                            line=dict(width=1, color=T["surface"])),
                hovertemplate="<b>%{customdata[0]}</b><br>%{customdata[1]}<br>"
                              + ("YoY delta %{x:+.2%}" if has_yoy else "Risk score %{x:.3f}")
                              + "<br>Efficiency $%{y:,.0f}<br>Composite %{customdata[2]}<extra></extra>",
            ))
        draw(traces, showlegend=False, margin=dict(l=70, r=16, t=16, b=54),
             xaxis=_axis(title=dict(text="YoY risk score delta" if has_yoy else "Risk score",
                                    font=dict(size=10), standoff=14),
                         tickformat=".0%" if has_yoy else ".2f"),
             yaxis=_axis(title=dict(text="Efficiency ratio ($/unit)", font=dict(size=10), standoff=14),
                         tickprefix="$", tickformat=",.0f"))
        foot(f"n={len(pts):,} county × enrollment rows shown · person_years ≥ 10 · "
             f"thinned deterministically from {len(eligible):,}{threshold_note}")

    render_oc_chart(view)
    render_ranked_table(view, has_yoy)
    insight("Counties with YoY risk score growth &gt;10% AND expenditure growth exceeding the national trend "
            "factor show HCC concentration patterns consistent with RADV audit targeting criteria. For ESRD "
            "enrollment type, a positive V28 delta signals CKD coding specificity opportunity &mdash; CHF+CKD "
            "combinations rewarded under V28 when documented at Stage 4/5. Aged Non-Dual counties showing negative "
            "V28 delta face vascular disease and metabolic HCC compression unrelated to actual health change.",
            "green")


def render_oc_chart(rows: pd.DataFrame) -> None:
    """The earliest cut's risk score is recovered from FINAL and oc_delta, so the
    chart follows the sidebar filters rather than being a fixed picture."""
    heading("OC-cut stability — risk score across data cuts",
            "Operational cut → Final · a large cut-to-final delta is a late-coding pattern "
            "(single-source HCC proxy) · source: derived")
    cuts = OC["cuts"] if OC and OC.get("available") else None
    with_oc = rows[rows["ocDelta"].notna() & rows["risk"].notna() & (rows["risk"] != 0)].copy()
    if not cuts or with_oc.empty:
        md('<p class="empty">No operational-cut vintage was published for this performance year, '
           'so cut-to-final movement cannot be computed.</p>')
        return

    with_oc["ocBase"] = with_oc["risk"] / (1 + with_oc["ocDelta"])
    traces = [go.Scatter(
        mode="lines+markers", name="All counties in view (mean)", x=cuts,
        y=[with_oc["ocBase"].mean(), with_oc["risk"].mean()],
        line=dict(color=T["s1"], width=2.5),
        marker=dict(color=T["s1"], size=9, line=dict(width=2, color=T["surface"])),
        hovertemplate="%{x}<br>mean risk %{y:.4f}<extra>mean</extra>",
    )]
    movers = with_oc.assign(_abs=with_oc["ocDelta"].abs()) \
        .sort_values("_abs", ascending=False, kind="mergesort").head(3)
    for color, (_, r) in zip([T["s2"], T["s3"], T["s4"]], movers.iterrows()):
        traces.append(go.Scatter(
            mode="lines+markers+text", name=f"{r.countyName}, {r.stateName}", x=cuts,
            y=[r.ocBase, r.risk], line=dict(color=color, width=2),
            marker=dict(color=color, size=8, line=dict(width=2, color=T["surface"])),
            text=["", f"  {r.countyName} {fmt_pct(r.ocDelta)}"], textposition="middle right",
            textfont=dict(size=9.5, color=T["ink2"]), cliponaxis=False,
            hovertemplate=f"<b>{esc(r.countyName)}, {esc(r.stateName)}</b> ({esc(r.enrollment)})"
                          "<br>%{x}: %{y:.4f}<extra></extra>",
        ))
    draw(traces, margin=dict(l=58, r=150, t=16, b=40), hovermode="closest",
         yaxis=_axis(title=title("avg_risk_score")), xaxis=_axis(title=title("Data cut")))
    foot(f"{len(with_oc):,} county × enrollment rows have both a {cuts[0]} and a FINAL vintage. "
         f"Nationally {OC['stable_high_count']:,} rows are \"stable-high\" (|delta| < 2% and FINAL score "
         "more than 1 SD above the mean) — the carry-forward coding pattern CMS RADV targets. "
         "The three largest movers in the current selection are labelled.")


def render_ranked_table(rows: pd.DataFrame, has_yoy: bool) -> None:
    heading("Top flagged counties — RADV risk composite ranking")
    md('<div class="formula">Composite_score = <b>0.4</b> &times; YoY_delta + <b>0.4</b> &times; '
       'Exp_growth_ratio + <b>0.2</b> &times; V28_coding_exposure_index<br>'
       '<span class="note">Illustrative weights &mdash; pending empirical validation against RADV audit '
       'outcome data. Sensitivity: test 0.5/0.3/0.2 and 0.33/0.33/0.33 per v5 spec.</span></div>')

    top = rows.assign(_s=rows["radvScore"].fillna(0)) \
        .sort_values("_s", ascending=False, kind="mergesort").head(20)
    flag_color = {"Low": T["ord"][0], "Medium": T["ord"][1], "High": T["ord"][2]}

    head = ["County", "State", "Enroll type", "YoY risk Δ" if has_yoy else "Risk score",
            "Exp growth ratio", "V28 delta est.", "OC stability", "Composite", "RADV flag", "Confounded"]
    defs = [
        None, None, None,
        ("Year-over-year change in AVG_RISK_SCORE vs. the prior published performance year: "
         "(current − prior) / prior." if has_yoy else
         "AVG_RISK_SCORE for the current year. Shown instead of a YoY delta because no prior year "
         "is available for this selection."),
        "Year-over-year change in per-capita expenditure (PER_CAPITA_EXP), computed the same way as YoY risk Δ.",
        "Estimated net V28 coding-model exposure for this enrollment type, normalized by the county's risk "
        "score. Positive = net V28 compression (score likely falls under V28); negative = net V28 benefit "
        "(score likely rises). A directional estimate from CMS Announcement Tables, not fitted to this data.",
        "Whether AVG_RISK_SCORE moved less than 2% between the earliest operational cut and the FINAL vintage; "
        "the percentage shown is that cut-to-final delta. Large, stable-high movement can indicate "
        "carry-forward or single-encounter coding.",
        "RADV exposure composite: 0.4 × |YoY risk Δ| + 0.4 × |Exp growth ratio| + 0.2 × |V28 delta est.|, "
        "each normalized 0–1 within the current selection. Illustrative weights, pending empirical validation.",
        "Exposure tier (Low / Medium / High) by tercile of the Composite score within the current selection — "
        "not a fixed threshold.",
        "Whether a known confounder may distort the composite for this row: a TEAM bundled-payment county, "
        "the PY2024 V28 transition year, or an ESRD/Disabled enrollment share that shifted >5pp year over year.",
    ]
    ths = ""
    for i, h in enumerate(head):
        cls = ' class="num"' if 3 <= i <= 7 else ""
        tip = f' data-tip="{esc(defs[i])}"' if defs[i] else ""
        ths += f"<th{cls}{tip}>{h}</th>"

    body = []
    for _, r in top.iterrows():
        oc = r.ocDelta
        oc_text = "—" if _missing(oc) else ("Stable" if abs(oc) < 0.02 else "Unstable")
        if not _missing(oc):
            oc_text += f" ({fmt_pct(oc)})"
        v28 = r.v28Index
        body.append(
            f"<tr><td>{esc(r.countyName)}</td><td>{esc(r.stateName)}</td><td>{esc(r.enrollment)}</td>"
            f'<td class="num">{fmt_pct(r.yoy, 2) if has_yoy else ("—" if _missing(r.risk) else f"{r.risk:.3f}")}</td>'
            f'<td class="num">{fmt_pct(r.expGrowth, 2)}</td>'
            f'<td class="num">{"+" if v28 >= 0 else ""}{v28:.3f}</td>'
            f'<td class="num">{oc_text}</td>'
            f'<td class="num">{r.radvScore:.3f}</td>'
            f'<td><span class="dot" style="background:{flag_color[r.radvLevel]}"></span>{r.radvLevel}</td>'
            f'<td>{"Yes" if r.confounded else "No"}</td></tr>')
    tbody = "".join(body) or '<tr><td colspan="10" class="empty">No counties match the current filters.</td></tr>'
    md(f'<div class="tw"><table><thead><tr>{ths}</tr></thead><tbody>{tbody}</tbody></table></div>')


# ---------------------------------------------------------------------------
# Module B
# ---------------------------------------------------------------------------

SAV_EDGES = [-math.inf, -0.10, -0.05, -0.01, 0.01, 0.03, 0.05, math.inf]
SAV_LABELS = ["<−10%", "−5–10%", "−1–5%", "Break-even", "+1–3%", "+3–5%", ">+5%"]


def render_module_b(rows: pd.DataFrame) -> None:
    bands = raf_band(rows["risk"])
    scoped = rows[bands == RAF] if RAF != "All bands" else rows
    if scoped.empty:
        scoped = rows
    scoped_bands = raf_band(scoped["risk"])

    c1, c2 = st.columns(2)
    with c1:
        heading("ACO financial performance distribution",
                "Simulated shared savings / loss · MSR threshold marked · source: derived")
        ratios = scoped["savingsRatio"].dropna()
        counts = bin_counts(ratios, SAV_EDGES, SAV_LABELS)
        sav_colors = [T["div_pos"][3], T["div_pos"][2], T["div_pos"][0], T["div_mid"],
                      T["div_neg"][0], T["div_neg"][1], T["div_neg"][2]]
        msr_pct = nanmean(scoped["msr"])
        draw([go.Bar(
            x=SAV_LABELS, y=counts, marker=dict(color=sav_colors, line=dict(width=2, color=T["surface"])),
            text=[f"{c:,}" if c else "" for c in counts], textposition="outside", cliponaxis=False,
            textfont=dict(color=T["ink2"], size=10),
            hovertemplate="%{x}<br>%{y:,} counties<extra></extra>", showlegend=False,
        )], yaxis=_axis(title=title("Counties")),
            shapes=[dict(type="line", x0=3.5, x1=3.5, y0=0, y1=1, yref="paper",
                         line=dict(color=T["ink2"], width=1.5, dash="dot"))],
            annotations=[dict(x=3.5, y=1.06, yref="paper", showarrow=False,
                              text=f"mean MSR {fmt_pct_plain(msr_pct)}", font=dict(size=9.5, color=T["ink2"]))])
        qualified = int((scoped["savingsStatus"] == "qualified_savings").sum())
        foot(f"Track {TRACK} · n={len(ratios):,} · {qualified:,} clear their size-adjusted MSR; "
             "savings to the left of the marker do not qualify.")

    with c2:
        heading("Benchmark vs. actual · by RAF quartile",
                "Per-beneficiary · risk-adjusted · source: derived + constant ref")
        risk0 = scoped["risk"].fillna(0)
        q1, q2, q3 = (quantile(risk0, q) for q in (0.25, 0.5, 0.75))
        q_labels = ["Q1 (low RAF)", "Q2", "Q3", "Q4 (high RAF)"]
        q_idx = np.select([risk0 <= q1, risk0 <= q2, risk0 <= q3], [0, 1, 2], default=3)
        series = [("Actual", "exp", T["s1"]), ("Benchmark (V28 adj.)", "benchV28", T["s2"]),
                  ("Benchmark (V24)", "benchV24", T["s3"])]
        if V28 == "V28 adjusted":
            series = [s for s in series if s[1] != "benchV24"]
        elif V28 == "V24 only":
            series = [s for s in series if s[1] != "benchV28"]
        draw([go.Bar(
            name=name, x=q_labels,
            y=[nanmean(scoped.loc[q_idx == i, col]) for i in range(4)],
            marker=dict(color=color, line=dict(width=2, color=T["surface"])),
            hovertemplate=f"{name}<br>%{{x}}<br>$%{{y:,.0f}}<extra></extra>",
        ) for name, col, color in series],
            barmode="group", bargroupgap=0.08,
            yaxis=_axis(title=title("Per-capita ($)"), tickformat="$,.0f"))

    heading("Benchmark version skew — V24 vs. V28",
            "Methodology artifact vs. genuine performance change · per enrollment type · "
            "V28 full implementation CY2026 · source: external ref + constant")
    skew = REF["v28_skew"]
    draw([go.Bar(
        x=[s["enrollment_type"] for s in skew], y=[s["v28_delta_pct"] for s in skew],
        marker=dict(color=[T["div_neg"][1] if s["v28_delta_pct"] > 0 else T["div_pos"][1] for s in skew],
                    line=dict(width=2, color=T["surface"])),
        text=[f"{'+' if s['v28_delta_pct'] > 0 else ''}{s['v28_delta_pct']:.1f}%" for s in skew],
        textposition="outside", cliponaxis=False, textfont=dict(color=T["ink2"], size=10),
        customdata=[[s["direction"], s["interpretation"]] for s in skew],
        hovertemplate="<b>%{x}</b><br>%{y:+.1f}%<br>%{customdata[0]}<br>%{customdata[1]}<extra></extra>",
        showlegend=False,
    )], height=250, yaxis=_axis(title=title("V24–V28 delta (%)"), ticksuffix="%"),
        shapes=[dict(type="line", x0=-0.5, x1=3.5, y0=0, y1=0, line=dict(color=T["axis"], width=1))])
    foot("Directional estimates from CMS Announcement Tables VIII-1 / VI-1 — national V28 delta "
         "factors by enrollment type.")

    p = REF["track_params"][TRACK]
    heading("Shared savings by RAF band · with MSR filter",
            f"Track {TRACK} MSR: {fmt_pct_plain(p['msr_base'])} at ≤5K person-years → "
            f"{fmt_pct_plain(p['msr_floor'])} at >60K · sharing rate {fmt_pct_plain(p['sharing_rate'], 0)} · "
            '"At MSR" = saving but not qualifying for distribution')
    body = []
    for label, _, _ in RAF_BANDS:
        sub = scoped[scoped_bands == label]
        if sub.empty:
            continue
        rate = nanmean(sub["savingsRatio"])
        status = "—" if math.isnan(rate) else ("Savings" if rate > 0.005 else ("At MSR" if rate > 0 else "Loss"))
        body.append(
            f'<tr><td>{label}</td><td class="num">{fmt_int(len(sub))}</td>'
            f'<td class="num">{fmt_usd(nanmean(sub["benchmark"]))}</td>'
            f'<td class="num">{fmt_usd(nanmean(sub["exp"]))}</td>'
            f'<td class="num">{fmt_pct(rate)}</td>'
            f'<td class="num">{fmt_int(int((sub["savingsStatus"] == "qualified_savings").sum()))}</td>'
            f"<td>{status}</td></tr>")
    tbody = "".join(body) or '<tr><td colspan="7" class="empty">No counties in the selected RAF band.</td></tr>'
    md('<div class="tw"><table><thead><tr><th>RAF band</th><th class="num">Counties</th>'
       '<th class="num">Avg benchmark</th><th class="num">Avg actual</th><th class="num">Savings rate</th>'
       f'<th class="num">Clear MSR</th><th>Qualifies?</th></tr></thead><tbody>{tbody}</tbody></table></div>')

    insight("ACOs with RAF scores above 1.20 systematically exceed benchmark under Track A. The V28 adjustment "
            "column shows increasing negative skew at higher RAF bands &mdash; the version skew is largest exactly "
            "where financial pressure is already highest. The 0.86&ndash;1.00 band is the analytically interesting "
            "case: counties are generating savings but failing to clear MSR, meaning the benchmark methodology "
            "penalizes moderate-complexity populations. TEAM episode pricing will face the same dynamic for "
            "surgical patients with comorbidities in the 1.01&ndash;1.20 RAF range.", "amber")


# ---------------------------------------------------------------------------
# Module C
# ---------------------------------------------------------------------------

SERVICE_TYPES = ["Cardiology", "Ortho", "Oncology", "Neurology", "Behavioral", "Post-acute", "DME"]
SERVICE_ADJ = [0.00, -0.03, -0.05, -0.01, -0.08, -0.12, -0.06]


def render_field_table(records, keys, headers, table_title, caption) -> None:
    heading(table_title, caption)
    rows = []
    for row in records or []:
        cells = []
        for k in keys:
            if k == "cms_field":
                typ = row.get("source_type") or "simulated"
                cells.append(f'<td class="wrap">{esc(str(row.get(k, "")))}'
                             f'<span class="badge {esc(typ)}">{esc(typ)}</span></td>')
            elif k == "note":
                cells.append(f'<td class="wrap">{esc(str(row.get(k) or ""))}</td>')
            else:
                v = row.get(k)
                cells.append(f"<td>{esc('—' if v is None else str(v))}</td>")
        rows.append(f"<tr>{''.join(cells)}</tr>")
    tbody = "".join(rows) or f'<tr><td colspan="{len(headers)}" class="empty">No field data available.</td></tr>'
    ths = "".join(f"<th>{esc(h)}</th>" for h in headers)
    md(f'<div class="tw"><table><thead><tr>{ths}</tr></thead><tbody>{tbody}</tbody></table></div>')


def render_module_c() -> None:
    if not MODULE_C:
        md('<p class="empty">Module C is disabled. Enable it with the toggle in the sidebar '
           '(<b>Modules &rarr; Enable Module C &mdash; PA metrics</b>).</p>')
        return

    md('<div class="legend-inline">'
       '<span><span class="badge derived">derived</span> MSSP PUF proxy</span>'
       '<span><span class="badge external">external</span> payer disclosure (real)</span>'
       '<span><span class="badge constant">constant</span> CMS regulatory parameter</span>'
       '<span><span class="badge">simulated</span> modeled estimate</span></div>')

    disclosures = REF.get("disclosures") or []
    c1, c2 = st.columns(2)
    if disclosures:
        # Expedited-only filings would read as a 0% approval bar, so they are
        # dropped from the rate chart and named underneath it.
        rated = [d for d in disclosures if (d.get("total_requests") or 0) > 0]
        unrated = [d for d in disclosures if not (d.get("total_requests") or 0) > 0]
        payers = [d["enrollment_type"] for d in rated]
        cap = "Approval vs. denial rates from ingested disclosures · source: external"
        if unrated:
            cap += (f" · {', '.join(d['enrollment_type'] for d in unrated)} reported expedited volume only "
                    f"and {'are' if len(unrated) > 1 else 'is'} excluded here")
        with c1:
            heading("Real payer disclosure metrics", cap)
            draw([
                go.Bar(name="Approval rate", x=payers,
                       y=[d["approved_requests"] / d["total_requests"] * 100 for d in rated],
                       marker=dict(color=T["s1"], line=dict(width=2, color=T["surface"])),
                       hovertemplate="%{x}<br>Approval %{y:.1f}%<extra></extra>"),
                go.Bar(name="Denial rate", x=payers,
                       y=[d["denied_requests"] / d["total_requests"] * 100 for d in rated],
                       marker=dict(color=T["s2"], line=dict(width=2, color=T["surface"])),
                       hovertemplate="%{x}<br>Denial %{y:.1f}%<extra></extra>"),
            ], barmode="stack",
                yaxis=_axis(title=title("Share of requests (%)"), range=[0, 100], ticksuffix="%"))
        with c2:
            heading("Expedited vs. total request volume",
                    "Total request volume from ingested disclosures · source: external")
            all_payers = [d["enrollment_type"] for d in disclosures]
            draw([
                go.Bar(name="Total requests", x=all_payers, y=[d["total_requests"] for d in disclosures],
                       marker=dict(color=T["s1"], line=dict(width=2, color=T["surface"])),
                       hovertemplate="%{x}<br>%{y:,} total<extra></extra>"),
                go.Bar(name="Expedited requests", x=all_payers, y=[d["expedited_requests"] for d in disclosures],
                       marker=dict(color=T["s3"], line=dict(width=2, color=T["surface"])),
                       hovertemplate="%{x}<br>%{y:,} expedited<extra></extra>"),
            ], barmode="group", bargroupgap=0.08, yaxis=_axis(title=title("Requests"), tickformat="~s"))
        render_field_table(REF.get("disclosure_fields"),
                           ["field_num", "cms_field", "value", "ffs_ref", "note"],
                           ["#", "CMS metric field", "Actual (aggregate)", "FFS reference", "Note"],
                           "Real payer disclosure metrics vs. CMS benchmarks",
                           "Aggregated from ingested disclosure PDFs · source: external (actual payer reported)")
    else:
        base = (REF.get("pa_summary") or {}).get("approved_rate") or 0.914
        svc = []
        for name, adj in zip(SERVICE_TYPES, SERVICE_ADJ):
            approval = min(0.99, max(0.50, base + adj))
            svc.append((name, round(approval * 100, 1), round(100 - approval * 100, 1)))
        if SERVICE != "All services":
            svc = [s for s in svc if s[0] == SERVICE]
        with c1:
            heading("Simulated PA approval / denial · by service type",
                    "Stacked 100% bar · fields 2+3 · MSSP specialty utilization proxy · source: derived")
            draw([
                go.Bar(name="Approval rate", x=[s[0] for s in svc], y=[s[1] for s in svc],
                       marker=dict(color=T["s1"], line=dict(width=2, color=T["surface"])),
                       hovertemplate="%{x}<br>Approval %{y:.1f}%<extra></extra>"),
                go.Bar(name="Denial rate", x=[s[0] for s in svc], y=[s[2] for s in svc],
                       marker=dict(color=T["s2"], line=dict(width=2, color=T["surface"])),
                       hovertemplate="%{x}<br>Denial %{y:.1f}%<extra></extra>"),
            ], barmode="stack", yaxis=_axis(range=[0, 100], ticksuffix="%"))
        with c2:
            burden = REF.get("pa_burden") or []
            heading("Estimated PA burden · admin hours per 1,000 beneficiaries",
                    "AMA 13 hr/physician/week benchmark × specialty utilization rate · source: external ref")
            draw([go.Bar(x=[b["county"] for b in burden], y=[b["hours"] for b in burden],
                         marker=dict(color=T["s1"], line=dict(width=2, color=T["surface"])),
                         hovertemplate="County %{x}<br>%{y:.1f} hrs / 1k<extra></extra>", showlegend=False)],
                 xaxis=_axis(type="category"), yaxis=_axis(title=title("Est. admin hrs / 1,000 ben")))
        render_field_table(REF.get("pa_fields"),
                           ["field_num", "cms_field", "simulated", "ffs_ref", "ma_ref", "variance", "flag"],
                           ["#", "CMS metric field", "Simulated", "FFS reference", "MA benchmark",
                            "Variance vs. FFS", "Flag"],
                           "All 7 CMS-required PA metric fields — simulated vs. benchmark",
                           "CMS-0057-F public reporting schema · payers must post annually by March 31 · "
                           "drugs excluded per rule · field 4 denominator = denied decisions (not total)")

    insight("MSSP-aligned populations show slightly elevated simulated denial rates vs. Medicare FFS, "
            "consistent with higher specialty utilization in ACO populations. Field 4 (appeal approval rate) "
            "shows the largest gap vs. MA benchmarks &mdash; suggesting ACO-adjacent populations face more "
            "defensible initial denials, or lower propensity to appeal. Field 5 (extended review) has no public "
            "benchmark &mdash; an analytical gap in the CMS-0057-F public reporting schema itself, not a data "
            "limitation of this simulation.")


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------

if TAB == "a":
    render_module_a(ROWS)
elif TAB == "b":
    render_module_b(ROWS)
else:
    render_module_c()
