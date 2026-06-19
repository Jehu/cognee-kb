# Plan 001: One-command verification baseline (Python + web)

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 5c096b7..HEAD -- README.md CLAUDE.md web/package.json Makefile scripts/ .github/`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none (this is the prerequisite for all other plans)
- **Category**: dx
- **Planned at**: commit `5c096b7`, 2026-06-19
- **Issue**: #1 — https://github.com/Jehu/cognee-kb/issues/1

## Why this matters

The repo has two test suites in two directories with no single command to run
both, and the web suite is invisible to a contributor: `README.md` never
mentions `npm test`, `CLAUDE.md` documents only `uv run pytest`. A clone +
`uv run pytest` looks green while the frontend (`web/src/lib/api.js`, the PWA's
auth/vault-loading logic) is effectively uncovered from a contributor's view.
This is the prerequisite that makes every other plan safe — without a
one-command green bar, refactors (plans 002, 008) can't be verified.

Note: `web/test/` is **already tracked** (committed in `b2d14c7`); the gap is
the missing harness + docs, not uncommitted files.

## Current state

- `web/package.json` scripts (verified at HEAD):
  ```json
  "scripts": { "dev": "astro dev", "test": "node --test", "build": "astro build", "preview": "astro preview" }
  ```
  `npm test` works today (`node --test` runs `web/test/*.test.mjs`).
- `web/test/api.test.mjs`, `web/test/ui-source.test.mjs` exist and are tracked.
- `README.md` mentions only `npm run build` (lines 41, 88); no `pytest`, no
  `npm test`.
- `CLAUDE.md:18-21` documents `uv run pytest` variants but never the web suite;
  line 33-35 states there is no lint config and no `[tool.pytest]` section.
- No `.github/workflows/`, no `Makefile`, no `scripts/` at repo root.

## Repo conventions to match

- README is bilingual-flavoured German prose; CLAUDE.md is German. Keep any new
  doc lines in the same German register, matching the existing `## Setup` /
  `## Befehle` sections.
- Commands in docs are shown as plain shell lines (see `CLAUDE.md:16-31`).

## Commands you will need

| Purpose          | Command                          | Expected on success |
|------------------|----------------------------------|---------------------|
| Install (py)     | `uv sync`                        | exit 0              |
| Python tests     | `uv run pytest`                  | all pass            |
| Web install      | `cd web && npm install`          | exit 0              |
| Web tests        | `cd web && npm test`             | 8 tests pass        |
| Web build        | `cd web && npm run build`        | exit 0, `dist/` written |

## Scope

**In scope**:
- `Makefile` (create, at repo root)
- `.github/workflows/ci.yml` (create)
- `README.md` (add test/setup section)
- `CLAUDE.md` (add web test command to `## Befehle`)

**Out of scope**:
- Do NOT change any source under `kb/` or `web/src/`.
- Do NOT add ruff/mypy here (that is plan 010).
- Do NOT touch `web/test/` content.

## Git workflow

- Branch: `advisor/001-verification-baseline`
- One commit per logical unit; message style (from `git log --oneline`):
  short English imperative, e.g. `Add Makefile + CI for unified test run`.

## Steps

### Step 1: Add a root `Makefile` that runs both suites

Create `Makefile`:

```makefile
.PHONY: test test-py test-web install build check

install:
	uv sync
	cd web && npm install

test-py:
	uv run pytest

test-web:
	cd web && npm test

test: test-py test-web

build:
	cd web && npm run build

## Schnellprüfung: Deps ok + beide Suites grün + PWA baut.
check: install test build
```

**Verify**: `make test` → both `uv run pytest` and `cd web && npm test` run and
all pass (expect "8 tests" from the web side plus the Python suite).

### Step 2: Add CI workflow

Create `.github/workflows/ci.yml`:

```yaml
name: CI
on:
  push:
    branches: [main]
  pull_request:
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.12" }
      - run: pip install uv
      - run: uv sync
      - run: uv run pytest
      - uses: actions/setup-node@v4
        with: { node-version: "20" }
      - run: npm install
        working-directory: web
      - run: npm test
        working-directory: web
      - run: npm run build
        working-directory: web
```

**Verify**: `uv run pytest` and `cd web && npm test` still pass locally (CI
runs on push; no local CI runner needed). Optionally `act` if installed —
otherwise skip.

### Step 3: Document both suites

- In `README.md`, add a short `## Tests` section under Setup stating:
  `uv run pytest` (Python) and `cd web && npm test` (web), plus `make test`
  for both. Match the German prose style of the existing Setup section.
- In `CLAUDE.md` `## Befehle`, add the web test line next to the Python ones,
  e.g. `cd web && npm test     # PWA-Tests (node --test)`.

**Verify**: `grep -nE 'npm test|make test' README.md CLAUDE.md` → matches in
both files.

## Test plan

No new tests. This plan wires up existing tests. Verification is the harness
itself: `make test` must run both suites green.

## Done criteria

- [ ] `make test` exits 0 and runs BOTH `uv run pytest` and `cd web && npm test`
- [ ] `cd web && npm run build` exits 0
- [ ] `.github/workflows/ci.yml` exists with the three steps (pytest, npm test, build)
- [ ] `grep -nE 'npm test|make test' README.md CLAUDE.md` returns matches in both
- [ ] No files outside the in-scope list are modified (`git status`)
- [ ] `plans/README.md` status row updated

## STOP conditions

- `make test` fails on `main` before any change (i.e. the suites are already
  red) — report the failing test instead of papering over it.
- `web/test/` is not present at HEAD (it must be; it was committed in `b2c...`).
  If absent, STOP.
- The CI YAML uses a Node/Python version not available — report rather than
  guessing versions.

## Maintenance notes

- When plan 010 (ruff/mypy) lands, add `make lint` and a lint job to CI.
- The Makefile is the single entry point contributors should reach for; keep
  its targets truthful as commands evolve.
