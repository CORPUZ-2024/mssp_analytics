from umlkit import Box, Diagram, t


def make():
    parts = [("Maintainer", None, "actor"),
             (":build_site", "«program» src/build_site.py", "prog"),
             (":CMSCatalog", "src.etl.catalog", "class"),
             ("fetch_vintages / :CMSDataClient", "src.etl.client", "class"),
             ("data.cms.gov", "«external system»", "ext"),
             (":DataIngestor · :DataEnricher", "src.etl", "class"),
             ("src.modules", "«package»", "module"),
             ("docs/data/", "«artifact»", "art")]
    xs = [90, 300, 520, 745, 975, 1185, 1395, 1570]
    d = Diagram(1700, 1500, "src/build_site.py — sequence diagram",
                "One manual run of  python -m src.build_site [--check-only] [--offline].  Nothing schedules this; the maintainer runs it and commits the result.")
    top = 80
    heads = {}
    for (name, st, kind), x in zip(parts, xs):
        if kind == "actor":
            d.actor(x, top, name)
            heads[x] = top + 72
        else:
            b = Box(name, st, [], kind=kind)
            b.at(x - b.w / 2, top + 8)
            d.add(b)
            heads[x] = b.bottom
    X = dict(zip(["M", "B", "C", "F", "W", "I", "S", "D"], xs))

    y = top + 110
    msgs = []          # drawn into d.top after fragments so they sit above

    def call(a, b, text, ret=False, dy=36):
        nonlocal y
        xa, xb = X[a], X[b]
        off = 6 if a == "B" and not ret else 0
        offb = 6 if b == "B" else 0
        sx = xa + (off if xb > xa else -off)
        ex = xb - (offb if xb > xa else -offb)
        d.edge([(sx, y), (ex, y)], "ret" if ret else "flow")
        anchor = "start" if xb > xa else "end"
        d.label((sx + (8 if xb > xa else -8), y - 6), text, anchor)
        y += dy

    def self_(a, text, dy=44):
        nonlocal y
        x = X[a] + (6 if a == "B" else 0)
        d.edge([(x, y), (x + 34, y), (x + 34, y + 16), (x + 2, y + 16)], "flow")
        for i, ln in enumerate(text.split("\n")):
            d.label((x + 42, y + 12 + i * 13), ln, "start")
        y += dy + 13 * (text.count("\n"))

    frames = []

    def frag(op, guard, x1, x2, y1, y2, elses=()):
        frames.append((op, guard, x1, x2, y1, y2, elses))

    call("M", "B", "python -m src.build_site [--check-only] [--offline]")
    act_start = y - 40
    self_("B", "main(argv) → build(check_only, offline)")
    call("B", "C", "CMSCatalog.load(allow_network = not offline)")
    a0 = y - 14
    y += 28
    call("C", "W", "GET /data.json  (DCAT catalog)")
    call("W", "C", "dataset distributions by title", ret=True)
    self_("C", "save(data/cms_catalog.json)")
    else_y = y - 10
    y += 26
    self_("C", "from_cache(data/cms_catalog.json)")
    frag("alt", "[network allowed and catalog reachable]", X["C"] - 40, X["W"] + 70, a0, y - 14,
         [(else_y, "[offline, or live resolution failed]")])
    y += 6
    call("C", "B", "catalog  (source = \"live\" | \"cache\")", ret=True)
    self_("B", "resolve_plan(catalog)\nlatest_years(2) · cuts_for_year(latest)")
    call("B", "F", "extract(): fetch_vintages(catalog, FINAL years, required=True)")
    l0 = y - 14
    y += 28
    call("F", "C", "vintage(year, cut)")
    call("C", "F", "Vintage(dataset_id, api_url, …)", ret=True)
    call("F", "W", "GET /data-api/v1/dataset/{uuid}/data?size&offset  (paged)")
    call("W", "F", "rows", ret=True)
    self_("F", "_assert_expected_year() · _reshape_wide_to_long()")
    frag("loop", "[each (year, cut) requested]", X["C"] - 40, X["W"] + 70, l0, y - 10)
    y += 6
    call("F", "B", "final_raw  (+ oc_raw: optional OC cuts, required=False)", ret=True)
    call("B", "I", "transform(raw): process_dataframe(raw) → enrich(df)")
    call("I", "B", "normalised frames", ret=True)
    self_("B", "add_yoy_columns · add_confound_flags · add_oc_delta\nbuild_county_payload(latest_df)")
    self_("B", "run_quality_gates(county_payload, latest_df)")
    g0 = y - 14
    y += 28
    call("B", "M", "raise BuildError — docs/data/ left untouched, exit 1", ret=True)
    frag("alt", "[any gate fails]", X["M"] - 50, X["B"] + 120, g0, y - 12)
    y += 10
    self_("B", "build_oc_stability(oc_df, latest_df)")
    call("B", "S", "build_reference_payload(): build_enrollment_type_skew_summary(),")
    d.label((X["B"] + 14, y - 20), "build_pa_metrics_report(), build_cms_field_table(), TRACK_PARAMS, HCC_V28_DELTA", "start")
    y += 6
    call("S", "B", "reference tables", ret=True)
    self_("B", "manifest = {built_at, catalog_source, latest_year, vintages, …}")
    o0 = y - 14
    y += 28
    call("B", "M", "return manifest  (nothing written)", ret=True)
    frag("opt", "[--check-only]", X["M"] - 50, X["B"] + 120, o0, y - 12)
    y += 10
    call("B", "D", "_write() 4 JSON files to temp staging  →  publish(staging, docs/data)")
    d.label((X["B"] + 14, y - 22), "atomic swap: old payload moved to docs/data.prev, restored if the copy fails, then removed", "start")
    y += 28
    call("B", "M", "exit 0 · log summary", ret=True)
    act_end = y - 30
    y += 10

    n = d.note(X["M"] - 60, y, [
        "Then, by hand: git add docs/data data/cms_catalog.json,",
        "git commit, git push origin main (then bring master in line).",
        "The push touches docs/**, so .github/workflows/pages.yml verifies",
        "and deploys the new payload. No workflow runs this build."])
    end = y + n[3] + 30

    # lifelines + activation, behind everything
    for x in xs:
        d.raw(f'<line class="life" x1="{x}" y1="{heads[x]}" x2="{x}" y2="{end - 10}"/>', "frames")
    d.raw(f'<rect class="act" x="{X["B"] - 6}" y="{act_start}" width="12" height="{act_end - act_start}"/>', "frames")
    for op, guard, x1, x2, y1, y2, elses in frames:
        tw = len(op) * 8 + 18
        d.raw(f'<rect class="frag" x="{x1}" y="{y1}" width="{x2 - x1}" height="{y2 - y1}"/>'
              f'<path class="fragtab" d="M{x1},{y1} h{tw} v12 l-7,7 h{-(tw - 7)} z"/>'
              + t(x1 + 6, y1 + 14, op, "fragtxt") + t(x1 + tw + 8, y1 + 14, guard, "guard"), "frames")
        for ey, eg in elses:
            d.raw(f'<line class="frag" x1="{x1}" y1="{ey}" x2="{x2}" y2="{ey}" stroke-dasharray="6 4"/>'
                  + t(x1 + 8, ey + 14, eg, "guard"), "frames")
    d.h = int(end)
    return d
