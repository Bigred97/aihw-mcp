# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.4.4] - 2026-05-16

### Added — defensive long-text-field cap (portfolio sister-MCP playbook, item 5)

`shaping.truncate_text()` caps dimension-string values above 500 chars
with a `...[N more chars, include_full_text=true]` marker and runs over
every dim value emitted from `shape_wide` / `shape_transposed`.

**Audit finding**: in every observed AIHW dataset (GRIM, MORT, ACIM,
HEXP, YOUTH_JUSTICE, PUBLIC_HOSPITALS), the longest dimension string is
~70 chars (a PUBLIC_HOSPITALS peer-group name). The 500-char cap is
therefore a no-op for current data — the field-cap path is defensive
plumbing that protects the response payload tightness contract against
a future AIHW release introducing a long descriptor (e.g. extended
cancer-type definitions, hospital service descriptions, free-text
methodology notes attached to a region label).

4 new unit tests in `tests/test_shaping.py`:
- `test_long_text_field_is_truncated_by_default` — synthetic 800-char
  `cause_of_death` value carries the truncation marker
- `test_short_text_field_is_not_truncated` — real <100-char AIHW values
  pass through unchanged (the common case)
- `test_truncate_text_helper_threshold` — helper is configurable; default
  cap lives between 100 and 5000 chars
- `test_truncate_text_handles_non_string` — `None` / `int` / empty string
  pass through, so the helper is safe to call on every dim slot

### Backward compatibility

No behaviour change for any existing AIHW dataset — every real
dimension value is well under the cap.

## [0.4.3] - 2026-05-16

### Changed — sanitize user-facing error messages (portfolio sister-MCP playbook, item 3)

Strip internal references from `ValueError` strings surfaced to MCP clients:

- **Unknown filter / unknown filter value / unknown measure**: replace the
  trailing `Try describe_dataset('<id>') for the full list.` hint with an
  inline `Valid filters: ...` / `Valid values: ...` / `Valid measures: ...`
  list. The error already enumerates the valid options; the second pointer
  to a sister-tool was redundant and leaked the MCP tool name to non-MCP
  callers.
- **measures validation errors** (`top_n` measure required, list-of-int,
  empty string, bad type): same — drop the trailing `describe_dataset(<id>)`
  pointer; the inline example already shows the expected shape.
- **AIHWAPIError messages from `client.py`**: stop echoing the full CKAN
  resource URL in error text. The status code (or exception class) plus the
  service name (`data.gov.au`) is the right amount of context — the URL
  itself is an implementation detail that leaks to MCP clients via the
  wrapped `ValueError` in `_fetch_and_parse`.
- **`stale_reason`** (surfaced verbatim in `DataResponse.stale_reason`):
  drop the URL from the human-readable reason for the same reason.

10 new unit tests in `tests/test_server_validation.py` and
`tests/test_resilience.py` pin the user-facing surface so this never
regresses. 2 existing tests updated to match the new phrasing
(`Try one of` → `Valid values`).

### Backward compatibility

No behaviour change. Inputs that previously raised still raise with the
same `ValueError` class; the message body is cleaner. Cache, response
envelope, and tool signatures are unchanged.

## [0.4.2] - 2026-05-16

### Fixed — JSON-string `filters` parameter (portfolio-wide)

The MCP protocol JSON-encodes dict parameters before they reach the
server. `_validate_filters` was checking `isinstance(filters, dict)`
before parsing the JSON string, so every call of the form
`get_data(filters={"sex":"male"})` from a real MCP client was rejected.
Fix: decode JSON-string filters before the type check. Coordinated
patch across the portfolio (abs, ato, apra, asic, aihw, wgea, aemo).

## [0.4.1] - 2026-05-16

### Changed — stale dataset flagged in description

- `PUBLIC_HOSPITALS` description now prominently warns the data is the
  AIHW 2016-17 reference release and has not been refreshed. The dataset
  remains queryable for trend / peer-group analysis but the description
  now clearly flags it should NOT be used as a current registration
  source. Hospital openings, closures, name changes, and LHN
  reorganisations since 2017 are not reflected.
- `period_coverage` updated to "2016-17 reference year (historical —
  not refreshed)" to make this surface in `describe_dataset`.

No data, code, or test changes. Description-only update.

## [0.4.0] - 2026-05-15

### Added

- **DataResponse.source_url**: canonical click-through URL field, populated
  alongside the legacy `aihw_url` alias. Cross-sister consumers can now read
  `.source_url` uniformly across the portfolio. `aihw_url` remains populated
  with the same value for backward compatibility.

## [0.3.0] — 2026-05-15

### Added — Wave 1 portfolio interoperability fix (int-year coercion)

Cross-sister consistency pass on input handling identified in the portfolio
interoperability audit.

- **Int-year coercion in period validation.** `start_period=2024` (a bare
  JSON int) now coerces to `"2024"` instead of raising a TypeError-style
  message. LLM clients routinely send JSON ints; this removes a confusing
  failure mode that surfaced as `must be a string, got int`. Out-of-range
  ints (e.g. `12345`, `1800`) still raise — with a hint pointing at the
  canonical `'YYYY'` / `'YYYY-MM'` / `'YYYY-YY'` (AIHW FY) forms. `bool` is
  explicitly rejected (it's a subclass of int) to avoid silent coercion.
- **Type signature broadened** on `get_data`'s `start_period` /
  `end_period` to `str | int | None` so the tool's published schema
  reflects the new coercion behaviour.

3 new unit tests in `tests/test_server_validation.py` cover the coercion
boundary, the out-of-range hint, and the bool-subclass-of-int guard.

### Backward compatibility

No breaking changes. Inputs that previously raised a type error on bare
int years now succeed; every other input still validates as before.

## [0.2.0] — 2026-05-15

### Added — aus-identity integration

The cross-source compatibility moat for the AU public-data MCP stack.
The `state` filter on every location-aware AIHW dataset
(HEALTH_EXPENDITURE, PUBLIC_HOSPITALS, YOUTH_JUSTICE_DETENTION, etc.)
now accepts the full canonical menu:

- Canonical short codes (`NSW`, `VIC`, `QLD`, `SA`, `WA`, `TAS`, `NT`, `ACT`)
- Case-insensitive variants (`nsw`, `Nsw`)
- Full names (`New South Wales`, `Queensland`, `Tasmania`)
- ISO 3166-2 (`AU-NSW`, `AU-VIC`)
- Common aliases (`Tassie`)
- 4-digit postcodes (`2000` → NSW, `2600` → ACT, `3000` → VIC, `0800` → NT)

Powered by [`aus-identity`](https://pypi.org/project/aus-identity/). An LLM
agent that's already fetched a postcode from another sister MCP (ato-mcp,
asic-mcp) can pass it straight to aihw-mcp without manual conversion.

- **`aus-identity>=0.1.0`** added as a new top-level dependency.
- **`curated.translate_filter_value`** runs state-shaped dim values through
  `aus_identity.normalize_state` (state codes, full names, aliases) and
  `aus_identity.postcode_to_state` (numeric postcodes) before the existing
  alias / canonical lookup. Existing aliases (`nsw` → `NSW`) and canonical
  values (`NSW` → `NSW`) still resolve unchanged.
- **7 new unit tests** in `tests/test_curated.py` covering full name,
  lowercase full name, ISO 3166-2, common alias, postcode routing,
  ACT-postcode boundary, and a second dataset (PUBLIC_HOSPITALS).

### Backward compatibility

No breaking changes — every input that worked in 0.1.3 still works.

## [0.1.3] — 2026-05-15

Error-message sweep — rejection messages now suggest the correction, not just
describe the rejection. No behavioural changes; same exception types, same
inputs accepted, same inputs rejected.

### Changed
- **Every `ValueError` carries an actionable hint.** Per the Quality Dimension
  #5 contract: every rejection message now says either "Did you mean X?"
  (fuzzy match on the rejected token), "Valid options: a, b, c" (capped at
  10 for token economy), or a worked example, plus a pointer at
  `describe_dataset`, `list_curated`, or `search_datasets` so the agent
  knows the next call to make. Affected paths:
  - **Unknown dataset_id** (describe_dataset / get_data / latest / top_n) —
    surfaces a `'Did you mean X?'` hint via fuzzy match against the curated
    ID list, plus the truncated list and a `list_curated()` pointer.
  - **Bad period format** (start_period / end_period) — adds a concrete
    worked example: `start_period='2020'` or `'2020-07'` for financial-year
    ranges, alongside the existing YYYY / YYYY-MM / YYYY-YY guidance.
  - **Bad format value** (get_data / latest format=) — adds a fuzzy
    `'Did you mean'` for typos like `'recordz'` → `'records'`.
  - **end_period before start_period** — now shows the swapped values
    inline: `Try swapping them: start_period='2020', end_period='2024'`.
  - **measures list with empty string / wrong type** — adds an
    `Example: measures='deaths'` and a `describe_dataset` pointer.
  - **search_datasets limit too small / too big** — explicit valid range
    `1-50` and a default-value hint.
  - **top_n n / direction errors** — adds valid-range hint and a fuzzy
    `'Did you mean'` for direction typos.
  - **Unknown filter / unknown value / unknown measure** — list now capped
    at 10 with a `(N total)` count and a `describe_dataset(<id>)` pointer
    instead of unbounded enumeration.

### Tests
- **266 total** (260 unit + 6 live) — up from 262 in v0.1.2.
- 10 consecutive zero-flake full-suite runs before tagging.
- 4 new regression tests in `tests/test_server_validation.py` covering the
  rewritten paths: dataset-id `'Did you mean'` typo correction, valid-
  options enumeration when no close match exists, period worked example,
  and format `'Did you mean'` typo correction.

## [0.1.2] — 2026-05-15

Reliability pass — graceful degradation when data.gov.au is unreachable.
No breaking changes; v0.1.1 callers keep working unchanged.

### Added
- **Stale-cache fallback.** When data.gov.au returns 5xx or the connection
  fails (timeout, DNS, connection refused, etc.), `fetch_resource()` /
  `fetch_package()` now fall back to the most-recent cached payload —
  regardless of its TTL — instead of raising. The agent's chain of
  reasoning keeps moving forward; the user sees the data with a
  `stale=True` flag and a human-readable reason. Mirrors the abs-mcp
  0.2.13 pattern. Behaviour when there is no cache to fall back to is
  unchanged: `AIHWAPIError` propagates as before.
- **`DataResponse.stale`** (bool), **`DataResponse.stale_reason`** (str | None),
  and **`DataResponse.truncated_at`** (int | None) fields. `stale_reason`
  format: `"AIHW API returned 503 for <url>; serving cached payload from
  ~12 minute(s) ago"`. `truncated_at` is reserved for future register-style
  caps and currently always `None`.
- `Cache.get_stale(key)` returns `(payload, cached_at_epoch)` regardless
  of TTL — the building block of the fallback path.
- `client.reset_stale_signal()` / `client.get_stale_signal()` —
  ContextVar-scoped so concurrent MCP tool calls each see their own state.
  `_get_data_impl` resets at the start of each call and propagates to the
  response at the end.

### Tests
- **262 total** (256 unit + 6 live) — up from 258 unit in v0.1.1.
- 3 consecutive zero-flake full-suite runs before publish.
- 4 new tests in `tests/test_client.py`: 5xx fallback serves cached payload
  and sets stale signal, RequestError (DNS / connect) fallback, empty
  cache still raises, `Cache.get_stale` round-trip with TTL miss.

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
