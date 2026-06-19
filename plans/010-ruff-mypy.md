# Plan 010: Add ruff + mypy (the code already assumes they exist)

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 5c096b7..HEAD -- pyproject.toml Makefile .github/workflows/ci.yml kb/`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: S (ruff) / M (with mypy)
- **Risk**: LOW
- **Depends on**: plans/001-verification-baseline.md (uses the `Makefile`/CI
  from 001)
- **Category**: dx
- **Planned at**: commit `5c096b7`, 2026-06-19

## Why this matters

The code carries `# noqa: BLE001` directives (`worker.py:61`,
`instance_service.py:62`, `fetch_youtube.py:34`) and uses full PEP 604 type
hints throughout — but there is NO `[tool.ruff]`/`[tool.mypy]`/`.pre-commit`
(verified). The suppressions are unverifiable faith claims: nothing enforces
that ruff was ever run, or that the broad-except blocks are still warranted.
Adding ruff (lint+format) and mypy gives cheap, near-zero-config guardrails
that catch import drift, unused vars, and the `.get` vs `[]` inconsistencies
behind plan 008.

## Current state

- `pyproject.toml` has no `[tool.ruff]`/`[tool.mypy]`/`[tool.black]` sections.
- dev deps: `pytest>=9.0.3`, `pytest-asyncio>=1.4.0` only.
- `# noqa: BLE001` present at the three sites above.
- Full type hints already in use (frozen dataclasses, `X | None`, etc.).
- Plan 001 adds a `Makefile` (with `make test`) and `.github/workflows/ci.yml`
  — this plan adds `make lint` and a lint CI job.

## Repo conventions to match

- Keep all existing `# noqa` comments (they document deliberate broad-except
  for the worker-must-not-die invariant). After running ruff, if a noqa is no
  longer needed, leave a note but do not delete rationale comments.
- German comments elsewhere; config-file comments can be German or English.

## Commands you will need

| Purpose    | Command                | Expected on success |
|------------|------------------------|---------------------|
| Lint       | `uv run ruff check kb tests` | exit 0        |
| Format chk | `uv run ruff format --check kb tests` | exit 0 |
| Types      | `uv run mypy kb`       | exit 0             |
| Tests      | `make test`            | all pass           |

## Scope

**In scope**:
- `pyproject.toml` (dev deps + `[tool.ruff]` + `[tool.mypy]`)
- `Makefile` (add `lint` target — from plan 001)
- `.github/workflows/ci.yml` (add lint job — from plan 001)
- `kb/*.py`, `tests/*.py` (only auto-format whitespace + any noqa fixups ruff
  flags; NO logic changes)

**Out of scope**:
- Do NOT change runtime logic to satisfy the type checker beyond trivial,
  obvious fixes (e.g. a missing `| None`). If mypy flags a real design issue,
  STOP and report.
- Do NOT add type stubs for third-party libs unless mypy blocks on them.

## Git workflow

- Branch: `advisor/010-ruff-mypy`
- Commit style: `Add ruff + mypy config and lint CI`

## Steps

### Step 1: Add tooling

`uv add --dev ruff mypy`. Add to `pyproject.toml`:

```toml
[tool.ruff]
line-length = 100
target-version = "py312"

[tool.ruff.lint]
# BLE ausgeblendet ist Absicht (Worker darf nie sterben); noqa-Kommentare
# bleiben gelten. Selections konservativ, um das bestehende Idiom nicht
# umzuschreiben.
select = ["E", "F", "I", "UP", "B"]
# BLE001 wird gezielt per noqa an den drei Worker-/Service-Stellen erlaubt.
ignore = []

[tool.ruff.format]
quote-style = "double"

[tool.mypy]
python_version = "3.12"
strict = true
# cognee ist lazily importiert und ungetypt; keine Stub-Noise propagieren.
ignore_missing_imports = true
files = ["kb"]
```

### Step 2: Run and fix trivially

- `uv run ruff check kb tests` → fix import-order/unused-import findings
  (mechanical). Re-run until clean.
- `uv run ruff format kb tests` → apply formatting. Re-run `--check` until
  clean.
- `uv run mypy kb` → fix trivial type gaps. For each NON-trivial error, STOP
  per the maintenance note rather than weakening strictness.

**Verify**: all three commands exit 0; `uv run pytest` still green.

### Step 3: Wire into Makefile + CI

- `Makefile`: add `lint: \n\tuv run ruff check kb tests\n\tuv run ruff format --check kb tests\n\tuv run mypy kb` and add `lint` as a dependency of `check`.
- `.github/workflows/ci.yml`: add a `lint` job running `uv run ruff check`, `uv
  run ruff format --check`, `uv run mypy kb`.

**Verify**: `make lint` → exit 0.

## Test plan

No new tests. The tooling IS the verification. Ensure `make test` still green
after formatting.

## Done criteria

- [ ] `uv run ruff check kb tests` exits 0
- [ ] `uv run ruff format --check kb tests` exits 0
- [ ] `uv run mypy kb` exits 0
- [ ] `make test` exits 0
- [ ] `Makefile` has `lint`, CI has a lint job
- [ ] No runtime logic changed (diff should be formatting/config/noqa only)
- [ ] `plans/README.md` status row updated

## STOP conditions

- mypy reports an error whose fix requires a logic/contract change — STOP and
  report (do not sprinkle `# type: ignore` or weaken `strict`).
- ruff flags the deliberate `# noqa: BLE001` blocks as removable — keep them;
  the broad-except is load-bearing (worker must not die).

## Maintenance notes

- New code should pass `make lint` locally before commit; CI enforces it.
- If a future dep lacks stubs and causes noise, prefer per-module
  `ignore_missing_imports` over global weakening.
- Reviewers: confirm the diff contains NO logic changes, only formatting +
  config.
