# Plan 015: Strip surrounding quotes in the `.env` parsers

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 5c096b7..HEAD -- kb/cognee_io.py kb/cli.py tests/test_cognee_io.py`
> If either parser changed since this plan was written, compare excerpts to live code; on mismatch, STOP.

## Status

- **Priority**: P3 | **Effort**: S | **Risk**: LOW | **Depends on**: none
- **Category**: bug | **Planned at**: commit `5c096b7`, 2026-06-19

## Why this matters

The `.env` loaders parse `KEY=value` with a bare `partition("=")` + `.strip()`
and never strip surrounding quotes — a divergence from the dotenv convention
`.env` authors expect. If anyone writes `LLM_API_KEY="sk-..."` (a common
habit), cognee receives the value WITH literal quotes → silent auth failure
with a hard-to-diagnose key-mismatch error. The tracked templates
(`.env.local.template`, `.env.cloud.template`) are unquoted today, so this is
latent — but the parser should not be a trap.

## Current state

`kb/cognee_io.py:28-33`:
```python
28:    for line in path.read_text().splitlines():
29:        line = line.strip()
30:        if not line or line.startswith("#") or "=" not in line:
31:            continue
32:        key, _, value = line.partition("=")
33:        os.environ[key.strip()] = value.strip()
```

`kb/cli.py` has a parallel `_load_env_file` with the identical pattern (read
`cli._load_env_file` before editing; it is used only for the gateway which
never imports cognee, but should still be consistent).

## Scope

**In scope**: `kb/cognee_io.py`, `kb/cli.py`, `tests/test_cognee_io.py`.
**Out of scope**: the templates (leave unquoted), any other env handling.

## Steps

1. Add a small helper that strips ONE matching pair of surrounding `"` or `'`:
   ```python
   def _strip_quotes(value: str) -> str:
       v = value.strip()
       if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
           return v[1:-1]
       return v
   ```
   Apply it where the value is assigned in both parsers (`cognee_io.load_instance_env`
   and `cli._load_env_file`).
2. Add tests in `tests/test_cognee_io.py` (and the cli test file if one exists;
   else add to `test_cognee_io.py` with a direct call) asserting:
   `KEY="value"` → env value is `value` (no quotes); `KEY=value` unchanged;
   `KEY='value'` → `value`; `KEY=a"b` unchanged (mismatched quotes).

## Commands you will need

| Purpose    | Command                            | Expected |
|------------|------------------------------------|----------|
| Tests      | `uv run pytest tests/test_cognee_io.py` | all pass |
| Full       | `uv run pytest` (or `make test`)   | all pass |

## Done criteria

- [ ] `uv run pytest` exits 0; new quote-stripping tests pass
- [ ] Both `cognee_io.load_instance_env` and `cli._load_env_file` strip quotes
- [ ] Only the in-scope files modified
- [ ] `plans/README.md` status row updated

## STOP conditions

- A tracked template legitimately relies on preserving surrounding quotes
  (none do today) — STOP.
- `cli._load_env_file` is gone or relocated at HEAD — reconcile before editing.

## Maintenance notes

- If a real dotenv lib (`python-dotenv`) is ever adopted, delete these helpers.
- Reviewers: confirm mismatched-quote and unquoted cases are preserved verbatim.
