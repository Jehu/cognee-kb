# Plan 005: Confine raw-source endpoint to `raw_dir` (read-side path traversal)

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 5c096b7..HEAD -- kb/gateway.py tests/test_gateway.py`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: security
- **Planned at**: commit `5c096b7`, 2026-06-19

## Why this matters

`GET /api/source/{vault}/{source_id}/raw` serves the file at whatever path is
stored in the `raw_md_path` column — taken verbatim from the DB row and handed
to `FileResponse` with no check that it resolves under the vault's `raw_dir`.
Today this is safe only as an emergent property of `rawstore.slugify` cleaning
every *write*. The moment any future code path, an MCP-side insert, a migration
script, or a manual DB edit stores an absolute or `..`-laden path, the
endpoint becomes an authenticated arbitrary-file-read (`.env.gateway`,
`var/<wall>/cognee_data/…`, SSH keys, etc.) — including for the `privat`
vault. Read-side confinement is a one-line fix; relying on every writer
forever is a latent hole.

## Current state

`kb/gateway.py:115-129`:

```python
115:    @api.get("/source/{vault}/{source_id}/raw")
116:    def source_raw(vault: str, source_id: str):
117:        v = _resolve_vault(vault)
120:        store = SourceStore(sources_path(v.instance))
121:        rec = store.get(source_id)
124:        if rec is None or rec.vault != v.name:
125:            raise HTTPException(404, "Unbekannte Quelle")
126:        p = Path(rec.raw_md_path)
127:        if not p.is_file():
128:            raise HTTPException(404, "Rohdatei nicht gefunden")
129:        return FileResponse(p, media_type="text/markdown")
```

`Vault.raw_dir` is `ROOT / "raw" / name` (`config.py:81-82`). `Path.resolve()`
+ parent-check is the standard confinement idiom. `tests/test_gateway.py` has
a `test_source_raw_returns_markdown` test that stores an arbitrary
`raw_md_path` (a file under `tmp_path`, NOT under a `raw_dir`) — that test
will need its fixture moved under a fake `raw_dir`.

## Repo conventions to match

- German comments explaining the why (see `gateway.py:122-123` style — the
  existing vault-scope comment is the model).
- 404 (not 403) on the failure to avoid confirming whether a file exists
  outside the vault (matches the existing "Unbekannte Quelle" 404 pattern).

## Commands you will need

| Purpose    | Command                                | Expected on success |
|------------|----------------------------------------|---------------------|
| Tests      | `uv run pytest tests/test_gateway.py`  | all pass            |
| Full suite | `uv run pytest` (or `make test`)       | all pass            |

## Scope

**In scope**:
- `kb/gateway.py` (add confinement check at line 126)
- `tests/test_gateway.py` (update the existing raw test fixture; add a
  traversal regression test)

**Out of scope**:
- Do NOT change `rawstore.slugify` (write-side safety stays).
- Do NOT add confinement elsewhere (the only `raw_md_path` reader is this
  endpoint).

## Git workflow

- Branch: `advisor/005-raw-source-confinement`
- Commit style: `Confine raw-source endpoint to vault raw_dir`

## Steps

### Step 1: Add the confinement check

In `kb/gateway.py` `source_raw`, replace lines 126-128 with a resolved-path
parent check against the vault's `raw_dir`:

```python
        raw_dir = v.raw_dir.resolve()
        p = Path(rec.raw_md_path).resolve()
        if raw_dir != p.parent and raw_dir not in p.parents:
            raise HTTPException(404, "Unbekannte Quelle")
        if not p.is_file():
            raise HTTPException(404, "Rohdatei nicht gefunden")
        return FileResponse(p, media_type="text/markdown")
```

Add a one-line German comment explaining why (Confinement gegen
Pfad-Traversal: `raw_md_path` darf nie außerhalb von `raw_dir` zeigen).

**Verify**: `uv run pytest tests/test_gateway.py` → the existing
`test_source_raw_returns_markdown` may now FAIL because its fixture path is
not under a `raw_dir`; that is expected and fixed in Step 2.

### Step 2: Fix the existing test fixture + add a traversal regression test

- In `tests/test_gateway.py`, update `test_source_raw_returns_markdown` so the
  stored `raw_md_path` points to a file written UNDER a fake `raw_dir` derived
  from the test's vault (e.g. create `<tmp>/raw/<vault>/<file>.md` and either
  monkeypatch the vault's `raw_dir` or construct the record so the path is
  inside it). The test should still assert a 200 + markdown body.
- Add `test_source_raw_rejects_traversal`: store a `raw_md_path` that escapes
  (e.g. `str(tmp_path / "../../etc/evil.md")` or an absolute path outside
  `raw_dir`) and assert the endpoint returns 404 and does NOT attempt to read
  the file.

**Verify**: `uv run pytest tests/test_gateway.py` → all pass, including the
new traversal test.

### Step 3: Full suite

**Verify**: `uv run pytest` (or `make test`) → all pass.

## Test plan

- Updated `test_source_raw_returns_markdown` (path under a fake `raw_dir`).
- New `test_source_raw_rejects_traversal` (escaped path → 404, no read).
- Pattern: existing `tests/test_gateway.py` tests for how the FastAPI
  `TestClient` + `JobQueue`/`SourceStore` fixtures are wired.
- Verification: `uv run pytest tests/test_gateway.py` → all pass.

## Done criteria

- [ ] `uv run pytest` exits 0
- [ ] `gateway.py` resolves `raw_md_path` and rejects anything not under
      `v.raw_dir`
- [ ] `test_source_raw_rejects_traversal` exists and passes
- [ ] The existing happy-path raw test passes with its fixture under `raw_dir`
- [ ] No files outside the in-scope list are modified
- [ ] `plans/README.md` status row updated

## STOP conditions

- `Vault.raw_dir` is not a `Path` or is computed differently at HEAD — STOP
  (confirm `config.py:81-82` still builds `ROOT / "raw" / name`).
- A legitimate `raw_md_path` is stored as a relative path that does not
  resolve under `raw_dir` today (it should not — `rawstore.write_raw` writes
  absolute paths via `raw_dir / ...`). If relative paths exist in the wild,
  STOP and report.

## Maintenance notes

- If relative `raw_md_path` storage is ever introduced (e.g. for portability
  across hosts), the resolve-and-parent check still holds as long as paths
  are relative to `raw_dir` — but revisit the anchoring.
- Reviewers: confirm the traversal test stores a path that would otherwise be
  served (i.e. the file exists outside `raw_dir`), so the 404 is provably from
  the confinement check, not the `is_file()` check.
