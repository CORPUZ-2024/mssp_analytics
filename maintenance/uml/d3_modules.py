from umlkit import Box, Diagram


def M(name, lines, kind="module", stereo="«module»"):
    return Box(name, stereo, [(None, lines)], kind=kind)


def package(d, x, y, title, top, row, deps, gap=24, row2=None):
    """Lay out a facade module on top and its helpers in a row beneath; returns frame rect."""
    rows = [row] + ([row2] if row2 else [])
    width = max(sum(b.w for b in r) + gap * (len(r) - 1) for r in rows)
    inner_x = x + 20
    top.at(inner_x + width / 2 - top.w / 2, y + 24)
    ry = top.bottom + 60
    for r in rows:
        rw = sum(b.w for b in r) + gap * (len(r) - 1)
        cx = inner_x + (width - rw) / 2
        for b in r:
            b.at(cx, ry)
            cx = b.right + gap
        ry = max(b.bottom for b in r) + 40
    allb = [top] + [b for r in rows for b in r]
    w = width + 40
    h = max(b.bottom for b in allb) - y + 22
    d.frame(x, y, w, h, title)
    d.add(*allb)
    bus = top.bottom + 28
    targets = [b for b in row if b in deps]
    if targets:
        d.edge([top.b(0.5), (top.cx, bus)], "line")
        xs = [b.cx for b in targets] + [top.cx]
        d.raw(f'<path class="edge dash" d="M{min(xs):.1f},{bus} L{max(xs):.1f},{bus}"/>', "edges")
        for b in targets:
            d.edge([(b.cx, bus), (b.cx, b.y)], "dep")
        d.label((top.cx + 8, bus - 8), "«import»", "start")
    return (x, y, w, h)


def make():
    d = Diagram(1700, 1200, "src.modules — package diagram",
                "The four analysis packages, their internal imports, and which programs import them.")

    # Module A ---------------------------------------------------------------
    a_top = M("hcc_risk_report", ["build_hcc_risk_flag_summary(df, top_n): DataFrame"])
    v28 = M("v28_exposure_index", ["HCC_V28_DELTA: dict", "ENROLLMENT_HCC_WEIGHTS: dict",
                                   "compute_v28_exposure_index(df, …)", "  : Series"])
    radv = M("radv_proxy_flags", ["CONFOUND_FLAG_COL", "compute_radv_exposure_score(", "  df, …): DataFrame"])
    rsv = M("risk_score_variance", ["compute_risk_score_yoy_delta(", "  df, …): DataFrame",
                                    "compute_oc_stability(", "  df, …): DataFrame"])
    hm = M("hcc_mapper", ["HCC_TO_CATEGORY, RADV_PRIORITY_PAIRS", "map_icd10_to_hcc(code)",
                          "hcc_to_category(hcc)", "estimate_hcc_concentration_proxy(", "  df, …): Series"])
    fa = package(d, 30, 100, "hcc_radv_risk_flags  (Module A)", a_top, [v28, radv, rsv, hm], {v28, radv, rsv, hm})
    d.edge([radv.l(0.7), (v28.right, radv.l(0.7)[1])], "dep")

    # Module B ---------------------------------------------------------------
    b_top = M("reconciliation", ["build_reconciliation(df, track_type)", "  : DataFrame"])
    bc = M("benchmark_constructor", ["build_benchmark(df, trend_factor,", "  …, version_factors)"])
    bvs = M("benchmark_version_skew", ["compute_benchmark_version_skew(df, …)",
                                       "build_enrollment_type_skew_summary()", "  : DataFrame"])
    ssc = M("shared_savings_calc", ["TRACK_PARAMS: dict", "calculate_msr_threshold(py, …)",
                                    "calculate_shared_savings(df, …,", "  track): DataFrame"])
    tep = M("team_episode_proxy", ["build_team_episode_proxy(df, …)", "  : DataFrame"])
    return _finish(d, fa, b_top, bc, bvs, ssc, tep)


def _finish(d, fa, b_top, bc, bvs, ssc, tep):
    # Module B laid out by hand as a 2x2 grid under its facade (keeps the frame narrow).
    x0 = fa[0] + fa[2] + 40
    y0 = 100
    colw = max(bc.w, ssc.w), max(bvs.w, tep.w)
    gap = 30
    inner = colw[0] + colw[1] + gap
    b_top.at(x0 + 20 + inner / 2 - b_top.w / 2, y0 + 24)
    r1 = b_top.bottom + 60
    bc.at(x0 + 20, r1); bvs.at(x0 + 20 + colw[0] + gap, r1)
    r2 = max(bc.bottom, bvs.bottom) + 30
    ssc.at(x0 + 20, r2); tep.at(x0 + 20 + colw[0] + gap, r2)
    wB = inner + 40
    hB = max(fa[3], max(ssc.bottom, tep.bottom) - y0 + 22)
    d.frame(x0, y0, wB, hB, "shared_savings_model  (Module B)")
    d.add(b_top, bc, bvs, ssc, tep)
    bus = b_top.bottom + 28
    d.edge([b_top.b(0.5), (b_top.cx, bus)], "line")
    d.raw(f'<path class="edge dash" d="M{bc.cx - 60:.1f},{bus} L{bvs.cx + 60:.1f},{bus}"/>', "edges")
    d.edge([(bc.cx, bus), (bc.cx, bc.y)], "dep")
    d.edge([(bvs.cx, bus), (bvs.cx, bvs.y)], "dep")
    lx, rx = bc.x - 10, bvs.right + 10
    d.edge([(bc.cx - 60, bus), (lx, bus), (lx, ssc.cy), (ssc.x, ssc.cy)], "dep")
    d.edge([(bvs.cx + 60, bus), (rx, bus), (rx, tep.cy), (tep.right, tep.cy)], "dep")
    d.label((b_top.cx + 8, bus - 8), "«import»", "start")
    fb = (x0, y0, wB, hB)

    # consumers band -------------------------------------------------------
    band_y = max(fa[1] + fa[3], fb[1] + fb[3]) + 120
    bs = Box("src/build_site.py", "«program»", [(None, ["imports constants + report builders"])],
             kind="prog")
    app = Box("src/app.py", "«program» legacy live-API app", [(None, ["imports report builders"])], kind="prog")
    dis = Box("src/etl/disclosures.py", "«module»", [(None, ["DisclosureIngestor"])], kind="module")
    nb = Box("notebooks", "«ipynb»", [(None, ["hcc_risk_report.ipynb", "financial_model.ipynb",
                                             "pa_metrics_report.ipynb", "fhir_vs_puf_comparison.ipynb"])],
             kind="art")
    split = fb[0] - 20
    bs.at(split - bs.w / 2 - 10, band_y)
    app.at(fa[0] + 40, band_y)
    dis.at((app.right + bs.x) / 2 - dis.w / 2, band_y)
    nb.at(bs.right + 140, band_y)
    d.add(bs, app, dis, nb)

    yA, yB = fa[1] + fa[3], fb[1] + fb[3]
    d.edge([bs.t(0.15), (bs.t(0.15)[0], yA)], "dep")
    d.label((bs.t(0.15)[0] - 6, yA + 26), "HCC_V28_DELTA,\nENROLLMENT_HCC_WEIGHTS", "end")
    d.edge([bs.t(0.85), (bs.t(0.85)[0], yB)], "dep")
    d.label((bs.t(0.85)[0] + 8, band_y - 34), "TRACK_PARAMS,\nbuild_enrollment_type_skew_summary", "start")
    d.edge([app.t(0.5), (app.cx, yA)], "dep")
    d.label((app.cx + 8, yA + 26), "build_hcc_risk_flag_summary,\ncompute_risk_score_yoy_delta", "start")

    # bottom row: Modules C and D --------------------------------------------
    y2 = band_y + max(bs.h, app.h, dis.h, nb.h) + 90
    c_top = M("pa_metrics_report", ["build_pa_metrics_report(df)", "build_cms_field_table(report)",
                                    "build_cms_field_table_from_disclosures(", "  disclosures_df)"])
    sim = M("pa_metrics_simulation", ["simulate_pa_metrics(df,", "  utilization_col, urgent_rate_col)"])
    sch = Box("pa_metrics_schema", "«module»", [
        (None, ["PA_FIELD_SOURCE_TYPES: dict"]),
        ("«dataclass»", ["PriorAuthMetricRecord", "PriorAuthMetric"])], kind="module")
    fc = package(d, 30, y2, "pa_metrics_simulation  (Module C — CMS-0057-F)", c_top, [sim, sch], {sim, sch})

    d_top = M("mapping_report", ["build_fhir_mapping_table(df, sample_rows)", "build_api_coverage_summary(",
                                 "  mapping_df)"])
    pm = M("puf_to_fhir_mapper", ["FHIR_FIELD_MAP", "PUF_FIELD_CATALOG", "map_puf_row_to_fhir(row)"])
    bb = Box("BlueButton2SandboxClient", "«dataclass» bb2_sandbox_query", [
        (None, ["+base_url: str", "+access_token: str | None"]),
        (None, ["+fetch_explanation_of_benefit(...)"])])
    fd = package(d, fc[0] + fc[2] + 40, y2, "fhir_data_bridge  (standalone exploration)", d_top, [pm, bb], {pm})

    yC = fc[1]
    my = band_y + max(bs.h, app.h, dis.h) + 30
    by2 = my + 26
    ex = fc[0] + fc[2] - 14
    d.edge([bs.b(0.3), (bs.b(0.3)[0], by2), (ex, by2), (ex, yC)], "dep")
    d.label((bs.b(0.3)[0] + 8, bs.bottom + 22), "build_pa_metrics_report, build_cms_field_table,\nbuild_cms_field_table_from_disclosures", "start")
    d.edge([app.b(0.5), (app.cx, yC - 20)], "dep")
    d.label((app.cx - 8, app.bottom + 30), "pa_metrics_report\nbuilders", "end")
    d.edge([dis.b(0.5), (dis.cx, my), (sch.right - 30, my), (sch.right - 30, sch.y)], "dep")
    d.label((dis.cx + 8, dis.bottom + 18), "PriorAuthMetricRecord", "start")
    # Module B arrow from src/app.py routes above the band
    ay = band_y - 80
    d.edge([app.t(0.85), (app.t(0.85)[0], ay), (fb[0] + 40, ay), (fb[0] + 40, yB)], "dep")
    d.label((app.right + 30, ay - 6), "build_reconciliation, build_enrollment_type_skew_summary", "start")

    d.note(nb.x, nb.bottom + 14, ["Notebooks call the package facades", "directly; no program imports", "fhir_data_bridge."])
    d.w = int(max(fb[0] + fb[2], fd[0] + fd[2], nb.right) + 40)
    d.h = int(max(fc[1] + fc[3], fd[1] + fd[3]) + 40)
    return d
