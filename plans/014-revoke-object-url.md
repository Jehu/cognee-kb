# Plan 014: Revoke the object URL in `openSourceRaw` and handle blocked popups

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 5c096b7..HEAD -- web/src/lib/api.js web/test/`
> If `api.js` changed since this plan was written, compare excerpts to live code; on mismatch, STOP.

## Status

- **Priority**: P3 | **Effort**: S | **Risk**: LOW | **Depends on**: none
- **Category**: bug | **Planned at**: commit `5c096b7`, 2026-06-19

## Why this matters

`openSourceRaw` calls `URL.createObjectURL(blob)` then `window.open(u, ...)` and
never calls `URL.revokeObjectURL(u)` — each source-chip click leaks a blob URL
until the document unloads. Worse, if the browser blocks the popup (common on
iOS Safari outside a user gesture), the blob is created and orphaned with **no
user feedback** — the chip appears dead.

## Current state

`web/src/lib/api.js:102-104`:

```js
102:  const blob = await res.blob();
103:  const u = URL.createObjectURL(blob);
104:  window.open(u, '_blank');
```

## Scope

**In scope**: `web/src/lib/api.js`, `web/test/` (a unit test).
**Out of scope**: other pages, the gateway.

## Steps

1. Replace lines 102-104 with popup-detection + cleanup:
   ```js
   const blob = await res.blob();
   const u = URL.createObjectURL(blob);
   const win = window.open(u, '_blank');
   // Blob nach kurzer Frist freigeben (Leak über lange Sessions), und
   // blockierten Popup-Öffner bemerken (iOS Safari außerhalb User-Gesture).
   setTimeout(() => URL.revokeObjectURL(u), 60_000);
   if (!win) alert('Popup wurde blockiert — bitte Popups für diese Seite erlauben.');
   ```
2. Extract the logic into a testable `openBlobInNewTab(blob)` helper (export
   from `api.js`) so `web/test/` can mock `window.open`/`URL` and assert:
   (a) `revokeObjectURL` is eventually called, (b) a blocked `window.open`
   (returns `null`) triggers the alert path.

## Commands you will need

| Purpose   | Command              | Expected |
|-----------|----------------------|----------|
| Web tests | `cd web && npm test` | all pass |

## Done criteria

- [ ] `cd web && npm test` exits 0; new test passes
- [ ] `revokeObjectURL` is called; blocked popup is surfaced
- [ ] Only `api.js`/`web/test/` modified
- [ ] `plans/README.md` status row updated

## STOP conditions

- The 60s revoke window turns out too short for large raw files on slow
  devices — if so, lengthen or revoke on `win.addEventListener('load')`; do
  not remove the revoke.

## Maintenance notes

- Reviewers: confirm the test mocks `window.open` returning `null` and asserts
  the alert path.
