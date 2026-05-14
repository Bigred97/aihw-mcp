# aihw-mcp

[![PyPI](https://img.shields.io/pypi/v/aihw-mcp.svg)](https://pypi.org/project/aihw-mcp/)
[![Python](https://img.shields.io/pypi/pyversions/aihw-mcp.svg)](https://pypi.org/project/aihw-mcp/)
[![License](https://img.shields.io/pypi/l/aihw-mcp.svg)](https://github.com/Bigred97/aihw-mcp/blob/main/LICENSE)
[![Tests](https://github.com/Bigred97/aihw-mcp/actions/workflows/test.yml/badge.svg)](https://github.com/Bigred97/aihw-mcp/actions/workflows/test.yml)
[![CodeQL](https://github.com/Bigred97/aihw-mcp/actions/workflows/codeql.yml/badge.svg)](https://github.com/Bigred97/aihw-mcp/actions/workflows/codeql.yml)
[![Glama MCP server quality](https://glama.ai/mcp/servers/Bigred97/aihw-mcp/badges/score.svg)](https://glama.ai/mcp/servers/Bigred97/aihw-mcp)

**MCP server for Australian Institute of Health and Welfare statistics.** Plain-English access to long-term mortality (GRIM), regional mortality (MORT), cancer incidence and mortality (ACIM), national health expenditure, youth justice detention, and the public hospitals register — all from a single `uvx` command.

```text
"How have diabetes deaths changed since 1980?"
"What's the age-standardised mortality rate in the Sydney - Inner West SA3?"
"Show me breast cancer incidence in women aged 50–54 over time."
"How much did Australia spend on public hospitals in 2022-23?"
"How many young people are in detention in NSW vs VIC?"
"List all Principal referral hospitals in Queensland."
"Top 5 causes of death in 2023."
```

Sister to [abs-mcp](https://github.com/Bigred97/abs-mcp) (Australian Bureau of Statistics), [rba-mcp](https://github.com/Bigred97/rba-mcp) (Reserve Bank of Australia), [ato-mcp](https://github.com/Bigred97/ato-mcp) (Australian Taxation Office), and [au-weather-mcp](https://github.com/Bigred97/au-weather-mcp) (Australian weather). The five together cover the macro / regulator / tax / health / climate layer of Australian official data.

---

## Install

```bash
# Run on demand via uvx (recommended)
uvx --upgrade aihw-mcp

# Or install permanently
pip install aihw-mcp
```

### Claude Desktop

Add to `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "aihw": { "command": "uvx", "args": ["--upgrade", "aihw-mcp"] }
  }
}
```

> **Why `--upgrade`?** `uvx aihw-mcp` (without the flag) uses whatever wheel is cached and never adopts new PyPI releases on its own. `--upgrade` makes uvx check PyPI on each launch and pull a newer release if one exists. To verify which version is currently serving you, look at the `server_version` field on any `DataResponse`.

### Claude Code / Cursor

```bash
claude mcp add aihw --command uvx --args -- --upgrade aihw-mcp
```

## Auto-updating data

Beyond the wheel-level `--upgrade`, the server has a second auto-update path **inside** the data layer: when AIHW refreshes GRIM with another year of deaths data or publishes a new MORT release, aihw-mcp resolves the new resource URL via [data.gov.au's CKAN API](https://data.gov.au/data/api/3/action/package_show) at fetch time and uses the freshest match. Hard-coded YAML URLs are the safe fallback if discovery fails. You do **not** need to wait for a new wheel release to get new yearly data — just delete `~/.aihw-mcp/cache.db` to force a refresh, or wait for the 7-day TTL to expire.

---

## What it exposes

Six tools, all plain-English in, structured out:

| Tool                | Purpose                                                       |
|---------------------|---------------------------------------------------------------|
| `search_datasets`   | Fuzzy-search the curated catalog by keyword                   |
| `describe_dataset`  | List a dataset's filterable dimensions and returnable measures |
| `get_data`          | Query with `filters`, `measures`, period range, output format |
| `latest`            | Last observation per measure (shortcut)                       |
| `top_n`             | Rank rows by a measure, return top (or bottom) N              |
| `list_curated`      | Enumerate the curated dataset IDs                             |

Every response is the same shape — `dataset_id`, `dataset_name`, `query`, `period`, `unit`, `row_count`, `records`, `aihw_url`, `attribution`, `server_version` — across every curated dataset.

Time-series datasets (GRIM, MORT, ACIM, Health Expenditure, Youth Justice) accept `start_period` and `end_period` on `get_data` — e.g. `start_period="2000", end_period="2010"` narrows GRIM to that decade. `latest()` returns the most-recent observation per measure, sorted by the dataset's declared period dimension (not by source row order). Error messages include fuzzy "did you mean?" suggestions when you typo a filter or measure name.

---

## Curated datasets (6 in v0.1)

| ID                          | What it is                                                                              | Period             | Coverage                  |
|-----------------------------|-----------------------------------------------------------------------------------------|--------------------|---------------------------|
| `GRIM_DEATHS`               | National long-term mortality: deaths × cause × year × sex × age band                    | 1907 → present     | ~370k rows, 3 measures    |
| `MORT_GEOGRAPHY`            | Regional mortality: deaths + premature/avoidable deaths × State / SA3 / SA4 / PHN       | 2019 → present     | ~15k rows, 15 measures    |
| `CANCER_INCIDENCE_MORTALITY`| Cancer incidence + mortality counts × year × sex × type × 5-year age band               | 1968 → present     | ~9k rows, 19 age columns  |
| `HEALTH_EXPENDITURE`        | Real expenditure by financial year × state × area × source (Government / non-Govt)      | 1997-98 → present  | ~7k rows, AUD millions    |
| `YOUTH_JUSTICE_DETENTION`   | Avg nightly youth-detention pop × quarter × state × sex × Indigenous × legal status     | 2008 → present     | ~42k rows                 |
| `PUBLIC_HOSPITALS`          | Directory of every public hospital × state × peer group × remoteness × LHN              | 2016-17 reference  | ~700 hospitals            |

Adding a new dataset is a single YAML drop into `src/aihw_mcp/data/curated/` — see [CONTRIBUTING.md](CONTRIBUTING.md).

---

## Example queries (paste into Claude)

**Public-health research**: *"For GRIM_DEATHS, give me the deaths and age-standardised rate for 'Diabetes' for Persons every year from 1980 to the latest, so I can chart the trajectory."*

**Health-tech / regional analysis**: *"Using MORT_GEOGRAPHY, list the 10 SA3 regions with the highest age-standardised mortality rate for Persons in the most recent year."*

**Oncology**: *"From CANCER_INCIDENCE_MORTALITY, give me Breast cancer incidence in Females across the 50–54 age band for every available year, plus the same age band's mortality."*

**Health-policy**: *"From HEALTH_EXPENDITURE, what was the real spend on 'Public hospitals' in NSW in 2022-23, broken down by broad source (Government vs Non-government)?"*

**Criminal-justice tech**: *"Using YOUTH_JUSTICE_DETENTION, compare the average nightly youth-detention population in NSW vs VIC in 'Jun qtr 2017', for both Indigenous and Total."*

**Hospital-tech / market intel**: *"From PUBLIC_HOSPITALS, list every 'Principal referral' hospital with their state and Local Hospital Network. Then count how many there are per state."*

Each prompt resolves to one or two `get_data` / `top_n` calls. The response includes the source URL so the agent can cite it back.

---

## Architecture

Same shape as the sister packages — `client → cache → parsing → shaping → server`:

- **`client.py`** wraps `httpx` with a SQLite-backed disk cache (per-resource TTL).
- **`parsing.py`** reads CSV (via `pandas`) and XLSX (via `openpyxl`/`pandas`). Header rows + sheet names live in the curated YAML so future format quirks are a YAML edit, not a code change.
- **`curated.py`** loads dataset specs from `data/curated/*.yaml` — each one declares its dimensions, measures, dimension value enums, source/download URLs, format, and parse layout.
- **`shaping.py`** transforms the parsed DataFrame into `DataResponse` (records / series / csv).
- **`server.py`** is the FastMCP entrypoint — six tools, full input validation with helpful "Try X" hints on error.

Cache lives under `~/.aihw-mcp/cache.db`. Most AIHW datasets refresh once a year; the TTLs are tuned for that cadence.

---

## Attribution

Data sourced from the Australian Institute of Health and Welfare (AIHW) via [data.gov.au](https://data.gov.au/). Licensed under [Creative Commons Attribution 3.0 Australia (CC BY 3.0 AU)](https://creativecommons.org/licenses/by/3.0/au/). The MCP server is MIT-licensed; the data carries the upstream CC-BY 3.0 AU licence, which is echoed in every response's `attribution` field.

---

## Sister MCPs (Australian Public Data portfolio)

- [abs-mcp](https://pypi.org/project/abs-mcp/) — Australian Bureau of Statistics (CPI, unemployment, ERP, building approvals)
- [rba-mcp](https://pypi.org/project/rba-mcp/) — Reserve Bank of Australia (cash rate, lending stats, exchange rates)
- [ato-mcp](https://pypi.org/project/ato-mcp/) — Australian Taxation Office (tax stats, ACNC charities)
- [apra-mcp](https://pypi.org/project/apra-mcp/) — Australian Prudential Regulation Authority (banking, insurance, super)
- **aihw-mcp** — this one. National mortality, regional health, cancer, expenditure, youth justice, hospitals.
- [asic-mcp](https://pypi.org/project/asic-mcp/) — Australian Securities and Investments Commission (company registers)
- [aemo-mcp](https://pypi.org/project/aemo-mcp/) — Australian Energy Market Operator (NEM dispatch, spot prices, generation)
- [au-weather-mcp](https://pypi.org/project/au-weather-mcp/) — Open-Meteo (Bureau of Meteorology aggregator)
- [wgea-mcp](https://pypi.org/project/wgea-mcp/) — Workplace Gender Equality Agency
- [aus-identity](https://pypi.org/project/aus-identity/) — Postcode / state / ABN normalisation helper used by all sisters

The portfolio is designed to compose: an agent can ask for "unemployment + cash rate + median income + mortality + climate" for postcode 2000 and one shot fans out across multiple MCPs.

---

## Roadmap (next iterations)

- v0.2: MORT_TABLE_2 (deaths by leading cause × region); intercountry adoptions; AIHW mental-health data tables (XLSX path)
- v0.3: hosted version with [x402](https://x402.org/) per-call paywall; programmatic SEO pages
- v0.4: listing on MCPay + Apify; paid tier for high-volume agent users

[CHANGELOG](CHANGELOG.md) tracks every release.

---

## Development

```bash
git clone https://github.com/Bigred97/aihw-mcp.git
cd aihw-mcp
uv venv
uv pip install -e ".[dev]"
pytest                  # unit tests, no network
pytest -m live          # integration tests against data.gov.au
```

Issues, ideas, and contributions welcome: [github.com/Bigred97/aihw-mcp/issues](https://github.com/Bigred97/aihw-mcp/issues).
