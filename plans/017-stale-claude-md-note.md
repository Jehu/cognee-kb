# Plan 017: Remove the now-stale name-drift note in CLAUDE.md

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 5c096b7..HEAD -- CLAUDE.md README.md`
> If either changed since this plan was written, compare excerpts to live code; on mismatch, STOP.

## Status

- **Priority**: P3 | **Effort**: S | **Risk**: LOW | **Depends on**: none
- **Category**: docs | **Planned at**: commit `5c096b7`, 2026-06-19

## Why this matters

`CLAUDE.md:115-117` warns that the README still uses old wall names
(`privat`/`business`, `.env.privat`). The current README is correct: walls are
`local`/`cloud`, vaults are `privat`/`allgemein`/`business-ki`/`business-mwe`,
and `.env.privat` does not appear. The pointer meant to protect against name
drift has itself become the drift — a contributor will "fix" an already-correct
README, or learn to distrust the doc.

## Current state

`CLAUDE.md:115-117`:
```
> **Hinweis:** Walls heißen im Code `local`/`cloud`. Das README nennt an einigen
> Stellen noch ältere Namen (`privat`/`business`, `.env.privat`) — `kb.toml` und
> `config.py` sind maßgeblich.
```

README verified current (uses `local`/`cloud` for walls, the four vault names,
no `.env.privat`).

## Scope

**In scope**: `CLAUDE.md` only.
**Out of scope**: README, code.

## Steps

1. Replace the three-line note with a correct, forward-pointing statement, e.g.:
   ```
   > **Hinweis:** Walls heißen `local`/`cloud`; `kb.toml` und `config.py` sind
   > maßgeblich für die Topologie. README und Code nutzen dieselben Namen.
   ```
2. Grep to confirm no other stale references: `grep -nE "privat.*business|\.env\.privat" CLAUDE.md README.md`
   → should return nothing (vault `privat` alone is fine; the pattern catches the old wall pairing).

## Commands you will need

| Purpose | Command | Expected |
|--------|---------|----------|
| Verify | `grep -nE "\.env\.privat|privat.*business" CLAUDE.md README.md` | no matches |

## Done criteria

- [ ] The stale note at `CLAUDE.md:115-117` is corrected
- [ ] No stale `privat`/`business` wall-pairing or `.env.privat` references remain
- [ ] Only `CLAUDE.md` modified
- [ ] `plans/README.md` status row updated

## STOP conditions

- The README at HEAD actually still contains the old names — then fix the
  README instead (the audit's premise would be wrong); STOP and report.

## Maintenance notes

- This is a one-line doc fix; keep it honest as topology names evolve.
