# Plan 013: Fix node-set autosuggest race on rapid vault switching

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 5c096b7..HEAD -- web/src/pages/index.astro web/test/`
> If `index.astro` changed since this plan was written, compare excerpts to live code; on mismatch, STOP.

## Status

- **Priority**: P3 | **Effort**: S | **Risk**: LOW | **Depends on**: none
- **Category**: bug | **Planned at**: commit `5c096b7`, 2026-06-19
- **Issue**: #13 — https://github.com/Jehu/cognee-kb/issues/13

## Why this matters

Switching vault A→B quickly fires two concurrent `loadNodeSets` requests.
If A resolves last, its node-sets are appended into the `<datalist>` while
vault B is selected — the user can then pick a node-set that does not belong
to B, mistagging the ingest (`node_set` is sent in the ingest body and drives
Cognee `node_set` scoping). Low frequency on desktop, more plausible on mobile
where `change` fires per tap.

## Current state

`web/src/pages/index.astro:92-105`:

```js
92:    async function refreshNodeSetSuggestions() {
93:      nodeSetSuggestions.replaceChildren();
94:      if (!vaultSel.value) return;
95:      try {
96:        const nodeSets = await loadNodeSets(vaultSel.value);
97:        for (const nodeSet of nodeSets) { ... nodeSetSuggestions.appendChild(option); }
```

Called on every vault `change` (`index.astro:58-61`). The awaited response is
appended without confirming the still-selected vault matches the request.

## Scope

**In scope**: `web/src/pages/index.astro`, `web/test/` (a race test).
**Out of scope**: `api.js` (`loadNodeSets` stays), other pages.

## Steps

1. Capture the vault at call time; ignore the response if it changed:
   ```js
   async function refreshNodeSetSuggestions() {
     nodeSetSuggestions.replaceChildren();
     const requested = vaultSel.value;
     if (!requested) return;
     try {
       const nodeSets = await loadNodeSets(requested);
       if (vaultSel.value !== requested) return;   // überholter Request
       for (const nodeSet of nodeSets) { ... appendChild ... }
     } catch { /* Komfort-Feature */ }
   }
   ```
2. Add a `web/test/` test that mocks two `loadNodeSets` calls resolving in
   reverse order and asserts only the selected vault's node-sets end up in the
   sink. (Reuse the injectable-sink approach from plan 006 if that landed; else
   extract a tiny `renderSuggestions(list)` helper for testability.)

## Commands you will need

| Purpose    | Command              | Expected |
|------------|----------------------|----------|
| Web tests  | `cd web && npm test` | all pass |
| Build      | `cd web && npm run build` | exit 0 |

## Done criteria

- [ ] `cd web && npm test` exits 0; new race test passes
- [ ] Stale responses are dropped when the selected vault differs
- [ ] No files outside `index.astro`/`web/test/` modified
- [ ] `plans/README.md` status row updated

## STOP conditions

- `index.astro` already guards against stale responses — STOP, bug gone.
- Plan 006 introduced a shared suggestion-sink — reconcile to avoid divergence.

## Maintenance notes

- Reviewers: confirm the test resolves the A request AFTER B and asserts A's
  items are NOT rendered.
