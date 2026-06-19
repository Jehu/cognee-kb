# Plan 012: Refresh vulnerable deps + add a recurring audit gate

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 5c096b7..HEAD -- pyproject.toml uv.lock web/package.json web/package-lock.json .github/workflows/ci.yml`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: MED
- **Depends on**: plans/001-verification-baseline.md (CI exists), plans/010-ruff-mypy.md (recommended)
- **Category**: security
- **Planned at**: commit `5c096b7`, 2026-06-19

## Why this matters

`npm audit` in `web/` reports 4 XSS advisories + 1 prerender SSRF against
`astro <=7.0.0-alpha.1` (`web/package.json:9` pins `^5.0.0`), and `pip-audit`
against the live venv reports 27 advisories across `python-multipart`,
`pyjwt`, `pillow`, `pypdf`, `fastapi-users` (transitive via cognee).
Reachability is LOW–MED today: the gateway uses JSON bodies only (no
`Form()`/`File()`, so the multipart CVEs are dormant), and the PWA renders
chat via `textContent` (so the Astro XSS paths aren't exercised). The risk is
**deteriorating posture** — the next feature that adds a `Form` endpoint, a
`set:html`, or ingests a PDF makes these live — and there is NO automated
gate preventing the drift.

## Current state

- `pyproject.toml`: `cognee==0.3.*`, `fastapi>=0.136.3`, `trafilatura>=2.1.0`,
  etc.; `[tool.uv] constraint-dependencies = ["mistralai<2.0.0"]` (cognee/instructor
  conflict — do NOT remove).
- `uv.lock` resolves `python-multipart 0.0.20`, `pyjwt 2.10.1`, `pillow 11.3.0`,
  `pypdf 6.13.2`, `fastapi-users 14.0.2`.
- `web/package.json:9`: `"astro": "^5.0.0"` (only web dep besides scripts).
- `cognee==0.3.*` is a deliberate pin (verified against 0.3.9) — keep, but note
  the glob means `uv lock --upgrade` can advance past 0.3.9 silently.

## Repo conventions to match

- Hard-pinning with a German rationale comment is the established style
  (`pyproject.toml:9` fastembed, `:34` mistralai). Preserve those comments and
  the constraints.

## Commands you will need

| Purpose      | Command                              | Expected on success |
|--------------|--------------------------------------|---------------------|
| Upgrade py   | `uv lock --upgrade`                  | lock updated        |
| Tests        | `uv run pytest` (or `make test`)     | all pass            |
| Import smoke | `uv run python -c "import cognee"`   | exit 0              |
| Web upgrade  | `cd web && npm install astro@latest` | exit 0              |
| Web build    | `cd web && npm run build`            | exit 0              |
| Web audit    | `cd web && npm audit --omit=dev`     | 0 high/critical     |
| Py audit     | `uv run --with pip-audit pip-audit`  | 0 high/critical (reachable) |

## Scope

**In scope**:
- `pyproject.toml`, `uv.lock` (Python upgrades)
- `web/package.json`, `web/package-lock.json` (astro upgrade)
- `.github/workflows/ci.yml` (audit job)

**Out of scope**:
- Do NOT change `cognee==0.3.*` or the `mistralai<2` constraint.
- Do NOT change application source to satisfy a bumped API (unless trivial).

## Git workflow

- Branch: `advisor/012-deps-audit-gate`
- Commit style: `Refresh vulnerable deps and add audit CI gate`

## Steps

### Step 1: Upgrade Python transitive deps

Run `uv lock --upgrade`. Then `uv run pytest` and `uv run python -c "import
cognee; print(cognee.__version__)"`.

**Verify**: tests pass; cognee still imports; record the resolved cognee
version. If cognee advanced past 0.3.9 and `cognee_io.py` introspection breaks
(see its docstring), STOP.

### Step 2: Upgrade Astro

`cd web && npm install astro@latest && npm run build && npm test`. Astro 5→6
is breaking; smoke-test all three pages (`/`, `/chat/`, `/settings/`) and the
service worker registration after build.

**Verify**: `cd web && npm run build` exits 0; `npm test` passes; `npm audit
--omit=dev` shows 0 high/critical.

### Step 3: Add an audit CI gate

Add a `audit` job to `.github/workflows/ci.yml`:

```yaml
  audit:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.12" }
      - run: pip install uv && uv sync
      - run: uv run --with pip-audit pip-audit --strict --ignore-vuln GHSA-xxxx  # add real false-positives here
      - uses: actions/setup-node@v4
        with: { node-version: "20" }
      - run: npm install
        working-directory: web
      - run: npm audit --omit=dev --audit-level=high
        working-directory: web
```

Tune `--ignore-vuln` only for confirmed false positives (e.g. advisories in
deps not reachable at runtime); record each ignore with a one-line reason.

**Verify**: the audit job passes on the branch (run `pip-audit`/`npm audit`
locally first).

## Test plan

No new unit tests. Verification = existing `make test` + `npm run build` +
the audit commands all green after upgrade.

## Done criteria

- [ ] `uv run pytest` exits 0; `import cognee` works
- [ ] `cd web && npm run build` exits 0; all 3 pages + SW work after build
- [ ] `cd web && npm audit --omit=dev --audit-level=high` exits 0
- [ ] `pip-audit` shows 0 high/critical reachable (ignores documented)
- [ ] CI has an `audit` job
- [ ] `cognee==0.3.*` and `mistralai<2` constraints unchanged
- [ ] `plans/README.md` status row updated

## STOP conditions

- `uv lock --upgrade` advances cognee past 0.3.9 and `cognee_io.py` breaks
  (the module is verified against 0.3.9) — STOP; consider pinning `cognee==0.3.9`.
- Astro 6 requires source changes beyond config (e.g. removed APIs the PWA
  uses) — STOP and scope a dedicated migration plan; do not half-upgrade.
- `pip-audit`/`npm audit` flag a CVE that is genuinely reachable and not
  fixed by the upgrade — STOP and report.

## Maintenance notes

- The audit job runs on every CI build; triage new advisories against actual
  reachability (the gateway uses JSON, not multipart; the PWA uses
  textContent, not set:html) before ignoring.
- If `uv lock --upgrade` ever silently moves cognee, add a CI assertion on the
  installed cognee version (or pin `==0.3.9`) to protect the `cognee_io`
  verification.
- Reviewers: confirm the Astro 6 smoke test covered the service worker and
  source-chip flows, not just page load.
