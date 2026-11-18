from umlkit import Box, Diagram


def make():
    d = Diagram(1640, 1080, "Dashboard programs — class diagram",
                "The three front ends, shown as «module» classifiers with their functions grouped by role, and where each one gets its data.")

    js = Box("docs/app.js", "«program» GitHub Pages dashboard (browser)", [
        ("state", ["S: {tab, state, enrollment, threshold,", "   track, raf, v28, service, moduleC}",
                   "DATA: {counties, oc, ref, manifest}", "ALL_ROWS: rows[]"]),
        ("load", ["async boot()", "decodeCounties(payload): rows[]", "showBootError(headline, detail)"]),
        ("derive  (mirror src.modules)", ["addV28Index(rows)", "addRadvScore(rows)", "addSavings(rows, track)",
                                          "msrThreshold(personYears, base, floor, …)",
                                          "categorise(value, msr, twoSided)", "rafBand(risk)"]),
        ("render", ["render()", "renderProvenance()", "renderKpis(rows)", "renderModuleA(rows)",
                    "renderOcChart(rows)", "renderRankedTable(rows, hasYoy)", "renderModuleB(rows)",
                    "renderModuleC(rows)", "renderFieldTable(records, keys, …)"]),
        ("UI + helpers", ["bind() · selectTab(tab) · selection()", "layout() · draw(id, traces) · tokens()",
                          "fmtPct · fmtUsd · fmtInt · quantile · thin"])],
        kind="prog", icon="component")
    st = Box("streamlit_dashboard/app.py", "«program» Streamlit edition (port of app.js)", [
        ("settings", ["MSSP_DATA_SOURCE = \"main\" | \"local\"", "MSSP_DATA_REF = \"main\"",
                      "PAYLOAD_FILES = counties, oc_stability,", "  reference, manifest"]),
        ("load  (@cache = st.cache_data)", ["load_payload(): (payload, source)",
                  "resolve_commit(ref): {sha, date, url}  @cache(ttl=900)",
                  "fetch_payload(sha): dict  @cache", "read_local(mtimes): dict  @cache",
                  "decode_payload(raw): dict  @cache"]),
        ("derive  (mirror src.modules)", ["add_v28_index(df, raw)", "add_radv_score(df)",
                                          "add_savings(df, ref, track)", "msr_threshold(py, base, floor, …)",
                                          "raf_band(risk): Series"]),
        ("render", ["selection(): DataFrame", "render_kpis(rows)", "render_module_a(rows)",
                    "render_oc_chart(rows)", "render_ranked_table(rows, has_yoy)", "render_module_b(rows)",
                    "render_module_c()", "render_field_table(records, keys, …)"]),
        ("helpers", ["md() · draw(traces) · layout() · insight() · kpi()",
                     "fmt_pct · fmt_usd · fmt_int · quantile · thin"])],
        kind="prog", icon="component")
    payload = Box("docs/data/", "«artifact» committed JSON payload", [
        ("counties.json", ["columns[10], states[], counties[]", "enrollment_types[], rows[][]"]),
        ("oc_stability.json", ["available, cuts[], series[], national[]"]),
        ("reference.json", ["v28_skew, v28_raw_exposure, track_params,", "benchmark, disclosures, pa_fields, …"]),
        ("manifest.json", ["built_at, catalog_source, latest_year,", "county_rows, states, vintages[]"])],
        kind="art", icon="artifact")
    gh = Box("GitHub", "«external system»", [(None, ["api.github.com  /commits?path=docs/data",
                                                      "raw.githubusercontent.com/{sha}/docs/data"])],
             kind="ext", icon="component")
    legacy = Box("src/app.py", "«program» legacy Streamlit app (live API)", [
        ("load  @cache_data(ttl=3600)", ["fetch_puf_data(): DataFrame", "fetch_hcc_multi_year_data(): DataFrame"]),
        ("render", ["main()", "render_sidebar(df, active_tab)", "render_hcc_tab(df, filters)",
                    "render_shared_savings_tab(df, filters)", "render_pa_metrics_tab(df, filters)"])],
        kind="prog", icon="component")
    cms = Box("data.cms.gov", "«external system»", [(None, ["Data API v1"])], kind="ext", icon="component")
    pk = Box("src.etl · src.modules", "«package»", [(None, ["CMSCatalog, fetch_vintages,", "DataIngestor, DataEnricher,",
                                                           "report builders"])], kind="pkg", icon="component")

    js.at(40, 90)
    payload.at(js.right + 170, 120)
    st.at(payload.right + 170, 90)
    gh.at(payload.cx - gh.w / 2 - 30, payload.bottom + 110)
    legacy.at(payload.right + 170, st.bottom + 60)
    cms.at(legacy.x - cms.w - 120, legacy.y + 10)
    pk.at(legacy.x - pk.w - 120, cms.bottom + 40)
    d.add(js, payload, st, gh, legacy, cms, pk)

    yy = payload.y + 40
    d.edge([(js.right, yy), (payload.x, yy)], "dep", "boot(): fetch ./data/*.json\n(cache: no-cache)",
           ((js.right + payload.x) / 2, yy - 22))
    y2 = payload.y + 100
    d.edge([(st.x, y2), (payload.right, y2)], "dep", "read_local()\nfallback / local mode",
           ((st.x + payload.right) / 2, y2 - 22))
    gy = gh.cy
    sx = st.x - 30
    d.edge([(st.x, st.y + st.h * 0.3), (sx, st.y + st.h * 0.3), (sx, gy), (gh.right, gy)], "dep",
           "resolve_commit(ref)\n→ fetch_payload(sha)", (gh.right + 8, gy - 22), "start")
    d.edge([gh.t(0.5), (gh.cx, payload.bottom)], "dep", "serves main's\ndocs/data/ at one commit",
           (gh.cx + 8, payload.bottom + 40), "start")
    d.edge([legacy.l(0.25), (cms.right, legacy.l(0.25)[1])], "dep", "«HTTP» on load",
           ((legacy.x + cms.right) / 2, legacy.l(0.25)[1] - 7))
    ly = pk.cy
    d.edge([(legacy.x, ly), (pk.right, ly)], "use", "«use»", ((legacy.x + pk.right) / 2, ly - 7))

    # port relation between app.js and the Streamlit edition (over the top)
    ty = 74
    d.edge([js.t(0.7), (js.t(0.7)[0], ty), (st.t(0.3)[0], ty), st.t(0.3)], "dep",
           "«port» line-for-line: same tabs, filters, charts, KPIs", (payload.cx, ty - 6))

    d.note(40, js.bottom + 20, [
        "app.js and streamlit_dashboard/app.py never call data.cms.gov: a CMS",
        "outage or URL change cannot blank them. Their derive functions",
        "re-implement src.modules formulas (compute_v28_exposure_index,",
        "compute_radv_exposure_score, calculate_shared_savings) on the",
        "filtered selection. Only the legacy src/app.py calls CMS directly."])
    d.w = int(max(st.right, legacy.right) + 40)
    d.h = int(max(js.bottom + 120, legacy.bottom, pk.bottom) + 40)
    return d
