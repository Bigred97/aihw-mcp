# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.1] — 2026-05-13

Code review pass — two real bugs fixed, one UX polish across every tool. No
breaking changes; v0.1.0 callers keep working unchanged.

### Bug fixes

- **`latest()` now actually returns the most recent observation** on
  wide-layout datasets. Previously it took the last row in source order,
  which incidentally worked for GRIM (year-sorted in source) but would
  silently regress if AIHW changed sort order — e.g. `latest("GRIM_DEATHS",
  filters={"cause_of_death": "Diabetes"})` could start returning a 1907 row.
  Fix: each time-series dataset now declares a `period_dimension` in its
  YAML (`year` / `YEAR` / `financial_year`); the shaping layer sorts by it
  ascending before the `last_n` trim so the most-recent period always wins.
- **`start_period` and `end_period` now filter wide datasets**. They were
  silently ignored before v0.1.1 — only transposed tables looked at them.
  Customer writing `get_data("GRIM_DEATHS", start_period="2000",
  end_period="2010")` got every year back. Fix: `_filter_wide_by_period`
  applies the same lenient `_period_in_range` parser that transposed tables
  use, so `YYYY`, `YYYY-MM`, and `YYYY-YY` financial-year strings all work
  out of the box.
- Datasets without a natural time axis (`PUBLIC_HOSPITALS`) leave
  `period_dimension` unset; period args are silently ignored, preserving
  the v0.1.0 behaviour for register-style queries.

### UX

- **Fuzzy "did you mean?" hints** on every "Unknown X" error path —
  unknown filter keys, unknown filter values, and unknown measures. Uses
  RapidFuzz (already a dep). Typo `sex="femal"` now answers with
  `Did you mean 'female'? Try one of: female, male, persons, ...`
  instead of just the alphabetised list. Tight WRatio cutoff of 70 avoids
  misleading suggestions on wildly-different input.

### Tests
- **264 total** (258 unit + 6 live) — up from 247 in v0.1.0
- 3 consecutive zero-flake full-suite runs before publish
- 17 new tests in `tests/test_period_axis.py` covering: every dataset's
  `period_dimension` declaration, latest-on-wide returns max-year row,
  latest survives shuffled source order, start/end_period filters work on
  both `YYYY` (GRIM) and `YYYY-YY` (HEALTH_EXPENDITURE) formats, period
  args silently ignored on register-style tables, three "did you mean"
  suggestion scenarios plus a no-spurious-suggestion guard.

## [0.1.0] — 2026-05-12

First public release. Six curated datasets, six MCP tools, end-to-end tested
against live data.gov.au.

### Added
- `search_datasets`, `describe_dataset`, `get_data`, `latest`, `top_n`, `list_curated`
  tools (FastMCP) — same surface as `abs-mcp`, `rba-mcp`, and `ato-mcp` so an
  agent that uses multiple servers gets a uniform shape.
- Curated datasets:
  - `GRIM_DEATHS` — General Record of Incidence of Mortality. Long-term national
    deaths by cause × year × sex × age group, 1907 onward. ~370k rows × 3 measures.
  - `MORT_GEOGRAPHY` — Mortality Over Regions and Time. Recent deaths by State,
    SA3, SA4, PHN, GCCSA, Remoteness, Socioeconomic group, with 15 measures
    including premature deaths, PYLL, and potentially avoidable deaths.
  - `CANCER_INCIDENCE_MORTALITY` — ACIM Combined Counts. Cancer incidence and
    mortality by year × sex × cancer type, with 19 age-band columns from 1968.
  - `HEALTH_EXPENDITURE` — Real (CPI-adjusted) health expenditure by financial
    year × state × area × broad/detailed source of funding from 1997-98.
  - `YOUTH_JUSTICE_DETENTION` — Quarterly average nightly youth detention
    population by state × sex × legal status × Indigenous status from 2008.
  - `PUBLIC_HOSPITALS` — Directory of every Australian public hospital with
    LHN, Medicare provider, peer group, remoteness, IHPA funding designation,
    and bed count (2016-17 reference year).
- HTTP fetcher with SQLite-backed disk cache (`~/.aihw-mcp/cache.db`); per-resource
  TTL tuned for AIHW's annual cadence.
- CSV + XLSX parsers with automatic header-padding normalisation.
- Auto-discovery layer (`discovery.py`): each curated YAML can declare a
  `discovery:` block so new yearly releases land without a wheel update.
  Discovery failures fall back silently to the YAML's hard-coded
  `download_url`.
- Discovery host pin: resolved CKAN URLs are accepted only when the host is
  `data.gov.au` (or a subdomain), as a defense-in-depth check against a
  compromised CKAN response.
- Parsed-DataFrame in-process LRU cache (8 entries) — warm `get_data` calls
  skip the pandas CSV re-parse and respond in tens of milliseconds.

### Tests
- **247 total** (241 unit + 6 live integration)
- 3 consecutive full-suite runs with zero flakes
- Test files: `test_curated`, `test_parsing`, `test_shaping`, `test_server_validation`,
  `test_cache`, `test_edge_inputs`, `test_edge_data`, `test_concurrency`,
  `test_customer_flows`, `test_resilience`, `test_discovery`, `test_df_cache`,
  `test_top_n`, `test_integration`
- Coverage: parsing (CSV/XLSX, BOM, Unicode, malformed bodies, blank-row
  trimming, header normalisation); shaping (alias rename, dtype coercion,
  filter resolution, CSV/series/records output formats, empty-result CSV);
  server-tool validation (every tool's rejected/accepted input); cache layer
  (TTL, corrupt-DB silent rebuild, 50-concurrent writes, 10MB roundtrip,
  binary-safe); adversarial edge inputs (Unicode, RTL, emoji, SQL/script
  injection, path traversal, 16KB strings, type confusion); data edge cases
  (NaN cells, `*`/`na` sentinels, mixed dtypes, trailing whitespace,
  numeric-ID float coercion); concurrency (50 parallel callers dedupe to
  one fetch, 6 parallel cross-dataset queries, cache-warm rapid sequential);
  realistic customer agent flows; resilience (404, 503, timeout, DNS
  failure, malformed CKAN JSON, non-http URLs, in-flight dedup); discovery
  (CKAN package_show, package_search-with-pattern, host pin against
  attacker.com, off-host suffix attacks, malformed URLs); parsed-DataFrame
  LRU cache (content-aware invalidation, no re-parse on warm hits); top_n
  (top/bottom direction, null-value skip, envelope preservation, cross-query
  caching); live integration smoke tests against real data.gov.au.

### Known limitations
- v0.1 ships only wide-layout (one-row-per-entity) datasets. The transposed
  code path is preserved for future AIHW reports (e.g. mental-health data
  tables, which use XLSX with metric-rows × year-columns layouts).
- `PUBLIC_HOSPITALS` is a 2016-17 snapshot — AIHW does not currently
  publish a refreshed register on data.gov.au. The discovery layer will
  pick up a new release automatically when one appears.
