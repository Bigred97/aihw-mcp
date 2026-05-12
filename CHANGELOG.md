# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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

### Known limitations
- v0.1 ships only wide-layout (one-row-per-entity) datasets. The transposed
  code path is preserved for future AIHW reports (e.g. mental-health data
  tables, which use XLSX with metric-rows × year-columns layouts).
- `PUBLIC_HOSPITALS` is a 2016-17 snapshot — AIHW does not currently
  publish a refreshed register on data.gov.au. The discovery layer will
  pick up a new release automatically when one appears.
