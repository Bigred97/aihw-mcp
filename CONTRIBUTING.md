# Contributing to aihw-mcp

Thanks for considering a contribution. This is an indie open-source project — every PR is read.

## Quick start

```bash
git clone https://github.com/Bigred97/aihw-mcp.git
cd aihw-mcp
uv sync --extra dev
uv pip install -e .

# Unit tests (no network)
uv run pytest

# Live integration tests (hits data.gov.au)
uv run pytest -m live
```

## What kind of contribution helps?

| Most welcome | Be cautious |
|---|---|
| Bug fixes (with a regression test) | Adding new tools to the MCP surface |
| New curated datasets (one YAML per dataset in `src/aihw_mcp/data/curated/`) | Refactors that touch >3 modules |
| Better error messages with actionable hints | Changes that break the public response shape |
| Docs / README improvements | Pulling in new dependencies |
| Performance fixes (with a benchmark) | Changes to the YAML schema |

## Adding a curated dataset

1. Find the dataset on [data.gov.au](https://data.gov.au/data/organization/aihw). Note the dataset slug (e.g. `grim-books`) and the specific resource name (e.g. `GRIM`).
2. Fetch the resource metadata via CKAN: `curl https://data.gov.au/data/api/3/action/package_show?id={slug} | jq` and find the resource's `url` field.
3. Download a copy and inspect headers:
   ```python
   import pandas as pd
   df = pd.read_csv("file.csv", encoding="utf-8-sig", nrows=20)
   print(df.columns.tolist())
   print(df.head())
   ```
   Identify the column names, layout (wide vs transposed), and which columns are dimensions vs measures.
4. Hand-write the YAML under `src/aihw_mcp/data/curated/{ID}.yaml`. `GRIM_DEATHS.yaml` is the simplest reference (a long-format CSV with clear dimensions and measures); `MORT_GEOGRAPHY.yaml` covers the multi-measure case; `PUBLIC_HOSPITALS.yaml` covers a register-style table with many dimensions and one numeric measure.
5. Add a `discovery:` block so new yearly releases land without a YAML edit:
   ```yaml
   discovery:
     package_id: my-aihw-dataset      # the CKAN slug
     resource_name: My Resource Name  # exact match against resource["name"]
   ```
6. Run the smoke test to confirm column mappings match:
   ```bash
   PYTHONPATH=src uv run python -c "
   from pathlib import Path
   from aihw_mcp import curated, parsing
   cd = curated.get('YOUR_ID')
   df = parsing.read_csv(Path('/path/to/file.csv').read_bytes())
   missing = [c.source_column for c in cd.columns.values() if c.source_column not in df.columns]
   print('missing:' if missing else 'all columns match', missing)
   "
   ```
7. Add a test fixture in `tests/fixtures/` and write a test in `tests/test_curated.py`.
8. Run `uv run pytest -m live` and confirm green.

## PR checklist

- [ ] All tests pass (`uv run pytest -m "not live"` minimum; `uv run pytest -m live` if you touched curation or the network path)
- [ ] New code has tests
- [ ] No new dependencies (or they're justified in the PR body)
- [ ] CHANGELOG.md updated under the Unreleased section
- [ ] If you changed default behaviour, the README "Example queries" still produces the documented values
- [ ] CC-BY 3.0 AU attribution still surfaces in `DataResponse.attribution`

## Style

- Python 3.11+, `from __future__ import annotations` at file top
- Pydantic v2 models — use `Field(default_factory=...)` for mutable defaults
- Docstrings in module-level summary; functions only when non-obvious
- No comments restating the code; comments explain *why*

## Filing bugs

Use the bug-report issue template. Bugs filed via the template get triaged within a week; freeform issues may sit longer.

## Discussions vs Issues

- **Issue**: bug, feature request, security report
- **Discussion**: question, idea you're not sure about, sharing how you're using the package

## Code of conduct

This project follows the [Contributor Covenant](CODE_OF_CONDUCT.md). Be kind.

## Releasing (maintainers)

Releases publish to PyPI via [Trusted Publishing](https://docs.pypi.org/trusted-publishers/) — no long-lived API token in the repo. PyPI verifies the GitHub OIDC claim against the publisher registered at [pypi.org/manage/project/aihw-mcp/settings/publishing/](https://pypi.org/manage/project/aihw-mcp/settings/publishing/) (workflow `publish.yml`, environment `pypi`).

To cut a release:

```bash
# 1. Bump version
#    - pyproject.toml: version = "X.Y.Z"
#    - CHANGELOG.md: new section under [Unreleased]
git add pyproject.toml CHANGELOG.md
git commit -m "Bump to X.Y.Z"
git push origin main

# 2. Tag and push
git tag -a vX.Y.Z -m "vX.Y.Z — short summary"
git push origin vX.Y.Z

# 3. Watch .github/workflows/publish.yml run.
#    It will:
#    - Verify the tag matches pyproject version
#    - uv build
#    - Smoke-test the wheel
#    - Publish to PyPI via OIDC
```

If the publish workflow fails because the tag doesn't match `pyproject.toml`'s version, delete the tag locally + remotely, fix the version, and re-tag:

```bash
git tag -d vX.Y.Z
git push origin :refs/tags/vX.Y.Z
# edit pyproject.toml + CHANGELOG.md, commit
git tag -a vX.Y.Z -m "..."
git push origin vX.Y.Z
```
