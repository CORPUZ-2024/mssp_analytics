from umlkit import Box, Diagram


def make():
    d = Diagram(1560, 1180, "src.etl — class diagram",
                "Classes in the ETL package. + public, − private. Upstream access is used only by src/build_site.py (and the legacy src/app.py).")

    # ---------------- upstream access frame -------------------------------
    vint = Box("Vintage", "«dataclass» frozen", [
        (None, ["+year: int", "+data_cut: str", "+dataset_id: str", "+label: str",
                "+api_url: str", "+csv_url: str | None"]),
        (None, ["+key(): tuple[int, str]"])], kind="data")
    cat = Box("CMSCatalog", None, [
        (None, ["+fetched_at: str", "+source: str  # \"live\" | \"cache\""]),
        (None, ["+load(cache_path, allow_network): CMSCatalog",
                "+from_network(title): CMSCatalog",
                "+from_cache(path): CMSCatalog",
                "+save(path)",
                "+vintage(year, data_cut=\"FINAL\"): Vintage | None",
                "+years(): list[int]",
                "+latest_years(n=2, data_cut): list[int]",
                "+cuts_for_year(year): list[str]"])])
    client = Box("CMSDataClient", None, [
        (None, ["+dataset_id: str", "+expected_year: int", "+data_cut: str",
                "+app_token: str | None", "+base_url: str"]),
        (None, ["+for_vintage(vintage, app_token): CMSDataClient",
                "+fetch_page(limit, offset): list[dict]",
                "+fetch_all(page_size): list[dict]",
                "+fetch_to_dataframe(page_size): DataFrame",
                "−_assert_expected_year(rows)",
                "−_reshape_wide_to_long(df): DataFrame"])])
    fv = Box("client.fetch_vintages", "«function»", [
        (None, ["fetch_vintages(catalog, requests_,",
                "    app_token=None, required=False)",
                "    : DataFrame"])], kind="module")
    caterr = Box("CatalogError", "«exception» RuntimeError", [], kind="exc")
    uperr = Box("UpstreamDataError", "«exception» RuntimeError", [], kind="exc")
    soda = Box("CMSSodaClient", "«deprecated alias»", [
        (None, ["+__init__(dataset_id=None, **kw)"])])

    top_y = 120
    vint.at(50, top_y + 40)
    cat.at(vint.right + 70, top_y + 20)
    client.at(cat.right + 70, top_y + 20)
    fv.at(client.right + 60, top_y + 20)
    caterr.at(cat.x + 70, cat.bottom + 50)
    soda.at(client.x + 40, client.bottom + 50)
    uperr.at(fv.x + 10, fv.bottom + 70)
    fx2 = max(fv.right, uperr.right) + 30
    fb = max(caterr.bottom, soda.bottom, uperr.bottom) + 30
    d.frame(30, top_y - 10, fx2 - 30, fb - top_y + 10, "Upstream access  (catalog.py · client.py)")
    d.add(vint, cat, client, fv, caterr, uperr, soda)

    d.edge([cat.l(0.25), (vint.right, cat.l(0.25)[1])], "comp")
    d.label((cat.x - 6, cat.l(0.25)[1] - 6), "vintages 1..*", "end")
    uy = cat.bottom + 22
    d.edge([client.b(0.12), (client.b(0.12)[0], uy), (vint.cx, uy), (vint.cx, vint.bottom)], "dep",
           "«use» for_vintage(vintage)", (vint.right + 20, uy - 6), "start")
    d.edge([fv.l(0.5), (client.right, fv.l(0.5)[1])], "dep", "«create»", ((fv.x + client.right) / 2, fv.l(0.5)[1] - 7))
    ty = top_y + 4
    d.edge([fv.t(0.5), (fv.cx, ty), (cat.x + cat.w * 0.75, ty), cat.t(0.75)], "dep",
           "«use» catalog.vintage(year, cut)", ((fv.cx + cat.x + cat.w * 0.75) / 2, ty - 6))
    d.edge([caterr.t(0.5), (caterr.cx, cat.bottom)], "dep", "«raises»", (caterr.cx + 8, cat.bottom + 42), "start")
    d.edge([fv.b(0.5), (fv.cx, uperr.y)], "dep", "«raises»", (fv.cx + 8, fv.bottom + 38), "start")
    d.edge([soda.t(0.5), (soda.cx, client.bottom)], "inherit")

    # ---------------- normalisation frame ---------------------------------
    y0 = fb + 60
    pipe = Box("DataIngestionPipeline", None, [
        (None, ["+ingestor: DataIngestor", "+enricher: DataEnricher", "+validator: DataValidator",
                "+cleaner: DataCleaner", "+reporter: PipelineReporter"]),
        (None, ["+run(source_path, output_path, qa_path,", "    dataset_id=None): DataFrame",
                "+preview(source_path, n=10): DataFrame"])])
    ing = Box("DataIngestor", None, [
        (None, ["+csv_kwargs: dict"]),
        (None, ["+load(path): DataFrame", "+process_dataframe(df): DataFrame",
                "−_read(path)", "−_normalize_columns(df)", "−_coerce_dtypes(df)",
                "−_add_raw_observations(df)"])])
    enr = Box("DataEnricher", None, [
        (None, []),
        (None, ["+enrich(df): DataFrame", "−_normalize_strings(df)", "−_flag_state_membership(df)",
                "−_add_pilot_flags(df)", "−_team_hash_proxy(df)", "−_add_efficiency_ratio(df)"])])
    val = Box("DataValidator", None, [
        (None, []),
        (None, ["+validate(df)", "+validate_schema(df)", "+validate_dtypes(df)",
                "+validate_ranges(df)", "+validate_key_columns(df)"])])
    cln = Box("DataCleaner", None, [
        (None, []),
        (None, ["+mark_conflicts(df): DataFrame", "+deduplicate(df): DataFrame",
                "+generate_qa_artifacts(...)", "−_effective_dedup_subset(df)"])])
    rep = Box("PipelineReporter", None, [
        (None, []),
        (None, ["+write_api_call_report(...)", "+read_report(output_dir)", "    : list[dict]"])])
    verr = Box("ValidationError", "«exception» Exception", [], kind="exc")
    cfg = Box("config / constants", "«module»", [
        (None, ["REQUIRED_COLUMNS", "NUMERIC_COLUMNS", "STRING_COLUMNS", "ALLOWED_DATA_CUTS",
                "DEDUP_SUBSET", "AHEAD/TEAM/WISER_STATE_NAMES", "RAW_OBSERVATIONS_COLUMN"]),
        ("read by", ["DataIngestor, DataEnricher,", "DataValidator, DataCleaner"])], kind="module")
    disc = Box("DisclosureIngestor", None, [
        (None, ["+records: list[PriorAuthMetricRecord]"]),
        (None, ["+ingest_directory(dir_path): DataFrame", "+ingest_file(file_path)",
                "+to_dataframe(): DataFrame", "−_detect_payer(...)", "−_detect_year(...)",
                "−_extract_metrics(...)"])])
    parec = Box("PriorAuthMetricRecord", "«dataclass» src.modules.pa_metrics_simulation", [
        (None, ["+county_id, state_id: str", "+enrollment_type, year: str",
                "+total/approved/denied_requests: int", "+appeals_overturned: int",
                "+expedited_requests/approved/denied: int"]),
        (None, ["+standard_approval_rate(): float", "+standard_denial_rate(): float",
                "+appeal_overturn_rate(): float", "…"])], kind="data")

    row = [ing, enr, val, cln, rep]
    gap = 26
    total = sum(b.w for b in row) + gap * (len(row) - 1)
    x = 50
    pipe.at(x + total / 2 - pipe.w / 2, y0 + 40)
    bus = pipe.bottom + 34
    ry = bus + 34
    for b in row:
        b.at(x, ry)
        x = b.right + gap
    verr.at(val.x + val.w / 2 - 80, max(b.bottom for b in row) + 50)
    cfg.at(rep.right + 50, y0 + 40)
    disc.at(rep.right + 50, cfg.bottom + 50)
    parec.at(disc.x, disc.bottom + 60)
    nx2 = max(cfg.right, disc.right, parec.right) + 30
    nb = max(verr.bottom, parec.bottom) + 30
    d.frame(30, y0, nx2 - 30, nb - y0, "Normalise · validate · report  (ingest, enrich, validate, cleaning, reporting, pipeline, disclosures)")
    d.add(pipe, *row, verr, cfg, disc, parec)

    d.edge([pipe.b(0.5), (pipe.cx, bus)], "comp")
    d.raw(f'<path class="edge" d="M{ing.cx:.1f},{bus} L{rep.cx:.1f},{bus}"/>', "edges")
    for b in row:
        d.edge([(b.cx, bus), (b.cx, b.y)], "assoc")
    d.label((pipe.cx + 8, bus - 12), "1", "start")
    d.edge([verr.t(0.5), (verr.cx, val.bottom)], "dep", "«raises»", (verr.cx + 8, val.bottom + 28), "start")
    d.edge([disc.b(0.5), (disc.cx, parec.y)], "dep", "«create»", (disc.cx + 8, disc.bottom + 34), "start")

    d.note(50, nb - 120, [
        "src/build_site.py.transform() reuses DataIngestor.process_dataframe()",
        "and DataEnricher.enrich() on the CMS API frames; the full",
        "DataIngestionPipeline is driven by src/cli.py for local CSV files."])
    d.h = int(nb + 30)
    d.w = int(max(fx2, nx2) + 30)
    return d
