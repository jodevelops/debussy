# AGENTS.md

## Purpose
Debussy is an AI-assisted curation workbench for GLAM collection data.
It supports ingest, structural analysis, NER, EDTF normalization, enrichment,
image analysis, OCR, export, and integration workflows.

## Stack
- Python >= 3.10
- FastAPI web app
- Local run via `python -m kwb.api.app`
- Tests via `pytest`
- Lint via `ruff`

## Local setup
Create and activate a virtual environment, then install all extras:

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -U pip
pip install -e .[all]
```

## Run locally

```bash
python -m kwb.api.app
```

Default local URL:
- http://localhost:8765

## Required checks before opening a PR
Run all of the following unless the task explicitly does not touch code:

```bash
ruff check .
pytest
```

If the change affects the web UI, API flows, upload handling, export, or analysis flows:
- start the app locally
- verify the affected flow on localhost
- include manual verification notes in the PR
- if E2E tests exist for the affected area, run them too

## Change policy
- Never commit directly to `main`
- Always work on a feature or fix branch
- Prefer minimal, targeted changes
- Do not mix unrelated refactors into a bugfix PR
- Keep public behavior stable unless the issue explicitly changes it

## Testing policy
For every bugfix:
- first reproduce the bug
- then add or update an automated test that fails before the fix, if feasible
- implement the minimal fix
- rerun lint and tests

For new features:
- add happy-path tests
- add at least one edge-case test where feasible

Use deterministic tests whenever possible:
- prefer mocks over live external dependencies
- prefer fixture data over ad hoc samples
- prefer the mock provider for AI-related tests unless real integration is explicitly required

## Fixtures and sample data
When adding or changing workflows that depend on sample data:
- use versioned fixtures in `tests/fixtures/`
- keep fixtures small, realistic, and non-sensitive
- document new fixtures briefly in the PR

## PR expectations
Each PR should explain:
- what problem was solved
- root cause
- files changed
- tests added or updated
- manual verification performed
- remaining risks or follow-up work

## Code style
- Follow existing project structure and naming conventions
- Preserve modularity
- Avoid unnecessary abstraction
- Avoid introducing hidden global state
- Keep error messages actionable
- Prefer explicit behavior over clever shortcuts

## Safety and resilience
When touching external integrations, uploads, parsing, or HTML output:
- think about malformed input
- think about empty input
- think about encoding issues
- think about security regressions
- do not weaken existing protections without explicit reason

## If blocked
If you cannot complete a task fully:
- state exactly what is blocked
- leave the repo in a runnable state
- summarize partial progress and next steps in the PR or issue comment