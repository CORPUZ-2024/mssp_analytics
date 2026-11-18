from umlkit import Box, Diagram


def make():
    d = Diagram(1500, 960, "MSSP Analytics — component diagram",
                "How the programs, packages and data files connect. Data is pulled from CMS only when a maintainer runs the build.")

    ext = d.add(Box("data.cms.gov", "«external system»",
                    [(None, ["DCAT catalog   /data.json",
                             "Data API v1    /data-api/v1/dataset/{uuid}/data"])],
                    kind="ext", icon="component").at(40, 100))
    cache = d.add(Box("data/cms_catalog.json", "«file» catalog cache",
                      [(None, ["last known-good dataset UUIDs"])], kind="art", icon="artifact").at(40, 540))
    disc = d.add(Box("disclosures_metrics.csv", "«file»",
                     [(None, ["public payer PA disclosures", "(Module C)"])], kind="art", icon="artifact").at(40, 660))
    cli = d.add(Box("src/cli.py", "«program»",
                    [(None, ["ingest: local CSV → clean CSV + QA"])], kind="prog", icon="component").at(40, 800))

    build = d.add(Box("src/build_site.py", "«program» run manually",
                      [(None, ["build(check_only, offline)",
                               "resolve_plan → extract → transform",
                               "quality gates → atomic publish"])],
                      kind="prog", icon="component", minw=300).at(440, 300))
    etl = d.add(Box("src.etl", "«package»",
                    [(None, ["catalog · client · ingest", "enrich · cleaning · validate",
                             "pipeline · reporting", "disclosures"])],
                    kind="pkg", icon="component").at(440, 600))
    mods = d.add(Box("src.modules", "«package»",
                     [(None, ["hcc_radv_risk_flags", "shared_savings_model",
                              "pa_metrics_simulation", "fhir_data_bridge (standalone)"])],
                     kind="pkg", icon="component").at(720, 600))

    payload = d.add(Box("docs/data/", "«artifact» committed payload",
                        [(None, ["counties.json", "oc_stability.json",
                                 "reference.json", "manifest.json"])],
                        kind="art", icon="artifact", minw=210))
    payload.at(860, build.cy - payload.h / 2 + 10)
    wf = d.add(Box(".github/workflows/pages.yml", "«workflow» GitHub Actions",
                   [(None, ["on push to main/master touching docs/**",
                            "verify payload (≥ 8,000 rows) → deploy"])],
                   kind="wf").at(800, 470))

    pages = d.add(Box("GitHub Pages dashboard", "«program» docs/index.html + docs/app.js",
                      [(None, ["static site; reads ./data/*.json only"])],
                      kind="prog", icon="component", minw=300).at(1160, 110))
    st = d.add(Box("Streamlit edition", "«program» streamlit_dashboard/app.py",
                   [(None, ["branch streamlit-version", "reads docs/data from main",
                            "(fallback: this branch's copy)"])],
                   kind="prog", icon="component", minw=300))
    st.at(1160, payload.y + payload.h / 2 - st.h / 2)
    legacy = d.add(Box("Legacy Streamlit app", "«program» src/app.py",
                       [(None, ["calls the CMS API live on load", "local exploration tool"])],
                       kind="prog", icon="component", minw=300))
    legacy.at(1160, mods.cy - legacy.h / 2)

    ya = build.y + 34
    d.actor(150, ya - 23, "Maintainer")

    # maintainer runs the build
    d.edge([(172, ya), (build.x, ya)], "flow", "runs python -m src.build_site", (306, ya - 8))
    # build -> CMS
    bx = build.t(0.2)[0]
    d.edge([build.t(0.2), (bx, ext.r(0.6)[1]), ext.r(0.6)], "dep", "«HTTP» catalog + vintages",
           (bx + 8, ext.r(0.6)[1] + 70), "start")
    # build -> cache / disclosures
    y1, y2 = build.l(0.78)[1], build.l(0.93)[1]
    d.edge([build.l(0.78), (400, y1), (400, cache.cy), cache.r()], "bidep", "read / refresh", (396, cache.cy - 8), "end")
    d.edge([build.l(0.93), (375, y2), (375, disc.cy), disc.r()], "dep", "«read»", (370, disc.cy - 8), "end")
    # build -> packages
    d.edge([build.b(0.25), (build.b(0.25)[0], etl.y)], "use", "«use»", (build.b(0.25)[0] + 8, etl.y - 40), "start")
    d.edge([build.b(0.9), (build.b(0.9)[0], mods.y)], "use", "«use»", (build.b(0.9)[0] + 8, mods.y - 40), "start")
    d.edge([etl.r(0.35), mods.l(0.35)], "use", "«use»", ((etl.right + mods.x) / 2, etl.r(0.35)[1] - 7))
    # build -> payload
    d.edge([build.r(0.55), (payload.x, build.r(0.55)[1])], "flow", "«write»\natomic publish",
           ((build.right + payload.x) / 2, build.r(0.55)[1] - 20))
    # workflow
    d.edge([(wf.cx, wf.y), (wf.cx, payload.bottom)], "dep", "«deploys»", (wf.cx + 8, (wf.y + payload.bottom) / 2 + 4), "start")
    wx = 1145
    d.edge([wf.r(0.5), (wx, wf.r(0.5)[1]), (wx, pages.r(1)[1] - 14), (pages.x, pages.r(1)[1] - 14)], "flow",
           "publishes", (wx + 6, 470), "start")
    # readers of the payload
    d.edge([pages.l(0.45), (payload.cx, pages.l(0.45)[1]), (payload.cx, payload.y)], "dep",
           "fetch ./data/*.json", (payload.cx - 70, pages.l(0.45)[1] - 7))
    d.edge([st.l(0.5), (payload.right, st.l(0.5)[1])], "dep", "via GitHub\n@ main",
           ((st.x + payload.right) / 2 - 14, st.l(0.5)[1] + 18))
    # legacy app
    lx = 1470
    d.edge([legacy.r(0.3), (lx, legacy.r(0.3)[1]), (lx, 78), (ext.cx, 78), ext.t()], "dep",
           "«HTTP» live CMS API on every load (not used by the dashboards)", (900, 72))
    d.edge([legacy.l(0.5), mods.r(legacy.l(0.5)[1] and (legacy.cy - mods.y) / mods.h)], "use", "«use»",
           ((legacy.x + mods.right) / 2, legacy.cy - 7))
    ly = 900
    d.edge([legacy.b(0.2), (legacy.b(0.2)[0], ly), (etl.x + etl.w * 0.7, ly), etl.b(0.7)], "use", "«use»",
           (1000, ly - 6))
    cy_ = cli.cy
    d.edge([cli.r(), (etl.x + etl.w * 0.3, cy_), etl.b(0.3)], "use", "«use» pipeline, disclosures",
           (cli.right + 8, cy_ - 7), "start")

    d.note(440, 462, ["No schedule or workflow pulls data. To refresh,",
                      "the maintainer runs the build, then commits",
                      "and pushes docs/data/, which triggers pages.yml."])
    return d
