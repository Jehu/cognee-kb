# Plan 011: Test all `kb.toml` validation branches in `config.py`

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 5c096b7..HEAD -- kb/config.py tests/test_config.py`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: tests
- **Planned at**: commit `5c096b7`, 2026-06-19
- **Issue**: #11 — https://github.com/Jehu/cognee-kb/issues/11

## Why this matters

`config.py` is the single source of truth that routes content to the correct
wall/vault/dataset — a regression here silently mis-routes data (the worst
case: private content landing in the cloud wall, breaking the privacy
guarantee). It raises `ConfigError` at 8 sites, but `tests/test_config.py`
covers only 2 (TOML parse + unknown wall). The remaining 6 — bad `mode`,
missing `port`, no walls, incomplete vault entry, duplicate vault, no vaults,
duplicate/Gateway-colliding ports — are untested. A bad-port or
duplicate-vault check could be deleted with no signal.

## Current state

`kb/config.py` `ConfigError` sites (all in `_load`):
- `:49` missing file, `:51` bad TOML — covered by `test_config.py`
- `:57` wall `mode` not in `MODE_PROVIDERS`
- `:60` wall missing `port`
- `:70` no walls defined
- `:76` vault entry missing `name`/`wall`
- `:80` duplicate vault name
- `:84` no vaults defined
- `:89` duplicate or Gateway-colliding ports

`tests/test_config.py` already calls `_load(Path)` directly with a temp file
(see its existing tests for the pattern — it constructs TOML text, writes to
`tmp_path`, and asserts `pytest.raises(ConfigError)`). `_load` takes an
optional `path` arg, so tests bypass the module-level `INSTANCES/VAULTS =
_load()` import-time call.

## Repo conventions to match

- Use `pytest.mark.parametrize` for the malformed-TOML table (one row per
  `ConfigError` site). Match the existing `test_config.py` harness style.

## Commands you will need

| Purpose    | Command                            | Expected on success |
|------------|------------------------------------|---------------------|
| Tests      | `uv run pytest tests/test_config.py` | all pass          |
| Full suite | `uv run pytest` (or `make test`)   | all pass            |

## Scope

**In scope**:
- `tests/test_config.py` (add a parametrized validation test)

**Out of scope**:
- `kb/config.py` (no change).
- The happy-path / instance-construction tests (already present).

## Git workflow

- Branch: `advisor/011-config-validation-tests`
- Commit style: `Cover all kb.toml validation branches in config tests`

## Steps

### Step 1: Add a parametrized test

In `tests/test_config.py`, add a parametrized test that writes a malformed
TOML to `tmp_path` and asserts `_load(path)` raises `ConfigError`. One row per
untested site. Examples (adapt the TOML bodies to match the real `kb.toml`
shape):

```python
import pytest
from kb.config import ConfigError, _load

@pytest.mark.parametrize("toml", [
    # bad mode
    "[walls.local]\nmode = 'bogus'\nport = 8801\n",
    # missing port
    "[walls.local]\nmode = 'local'\n",
    # no walls
    "[[vaults]]\nname = 'privat'\nwall = 'local'\n",
    # vault missing name/wall
    "[walls.local]\nmode='local'\nport=8801\n[[vaults]]\nname='privat'\n",
    # duplicate vault
    "[walls.local]\nmode='local'\nport=8801\n[[vaults]]\nname='privat'\nwall='local'\n[[vaults]]\nname='privat'\nwall='local'\n",
    # no vaults
    "[walls.local]\nmode='local'\nport=8801\n",
    # port collides with gateway (8800)
    "[walls.local]\nmode='local'\nport=8800\n[[vaults]]\nname='privat'\nwall='local'\n",
    # duplicate ports across walls
    "[walls.local]\nmode='local'\nport=8801\n[walls.cloud]\nmode='cloud'\nport=8801\n[[vaults]]\nname='privat'\nwall='local'\n",
])
def test__load_rejects_bad_topology(tmp_path, toml):
    p = tmp_path / "kb.toml"
    p.write_text(toml)
    with pytest.raises(ConfigError):
        _load(p)
```

Adjust each TOML body so it actually triggers the intended branch (verify by
reading `config.py:54-89` — the order of checks matters; a TOML must pass all
earlier checks to reach the target branch).

**Verify**: `uv run pytest tests/test_config.py -k bad_topology` → all rows pass.

### Step 2: Full suite

**Verify**: `uv run pytest` → all pass.

## Test plan

The new parametrized test IS the test plan. Optionally add one positive row
that loads a valid minimal `kb.toml` and asserts no raise, if not already
covered.

## Done criteria

- [ ] `uv run pytest` exits 0
- [ ] At least 6 new parametrized rows exist, each targeting a distinct
      previously-untested `ConfigError` site
- [ ] No files outside the in-scope list are modified
- [ ] `plans/README.md` status row updated

## STOP conditions

- A TOML body does not trigger its intended branch (an earlier check fires
  first) — rework that row so it reaches the target; do not delete the row.
- `_load` no longer accepts a `path` arg at HEAD — STOP, the test harness
  premise has changed.

## Maintenance notes

- When a new validation branch is added to `config.py`, add a row here in the
  same change — keep coverage at 100% of `ConfigError` sites.
- Reviewers: confirm each row genuinely reaches its target check (temporarily
  comment out that check and see the row fail differently or the suite change).
