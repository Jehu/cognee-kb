# Plan 006: Serialize ingest polling so concurrent jobs don't clobber status DOM

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 5c096b7..HEAD -- web/src/pages/index.astro web/test/`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none (optionally plan 001 so `npm test` is wired)
- **Category**: bug
- **Planned at**: commit `5c096b7`, 2026-06-19

## Why this matters

Submitting a second source within the ~2-minute poll window starts a second
`poll()` loop without stopping the first. Both loops write to the same
`#result` / `#job-steps` singletons, so status text interleaves and the
3-step indicator flips between jobs — the user loses track of which job
finished or failed. The form even invites this ("Verarbeitung läuft im
Hintergrund", and `finally` re-enables submit the moment the POST is
accepted, while the first poll is still running).

## Current state

`web/src/pages/index.astro`:

```js
133:    async function poll(vault, jobId) {
134:      const maxTries = 40; // 40 × 3 s ≈ 2 min
135:      for (let i = 0; i < maxTries; i++) {
136:        await new Promise((r) => setTimeout(r, 3000));
...
160:    form.addEventListener('submit', async (ev) => {
...
174:      try {
175:        const res = await api('/api/ingest', { method: 'POST', body: ... });
...
182:        poll(vault, res.job_id);      // fire-and-forget — NOT awaited
183:      } catch (e) {
184:        show(e.message, 'error');
185:      } finally {
186:        submit.disabled = false;       // submit re-enabled while poll runs
187:      }
```

Both `poll()` instances call `show(...)` (writes `#result`) and `setStep(...)`
(writes `#job-steps`). There is no notion of the "active" job.

## Repo conventions to match

- Vanilla JS, ES modules, no framework. Match the existing style in
  `index.astro` (`async function`, `document.getElementById`, template-less
  DOM via `replaceChildren`/`Object.assign(document.createElement(...), {...})`).
- Web tests use `node --test` (`web/test/*.test.mjs`); see `web/test/api.test.mjs`
  for the fetch-mocking pattern.

## Commands you will need

| Purpose    | Command                | Expected on success |
|------------|------------------------|---------------------|
| Web tests  | `cd web && npm test`   | all pass            |
| Full suite | `make test`            | all pass            |

## Scope

**In scope**:
- `web/src/pages/index.astro` (serialize/abort polling)
- `web/test/` (add a poll-behavior test)

**Out of scope**:
- `web/src/lib/api.js`, the chat/settings pages, the service worker.
- Changing the backend job/poll contract.

## Git workflow

- Branch: `advisor/006-concurrent-poll`
- Commit style: `Serialize ingest polling to avoid clobbering status DOM`

## Steps

### Step 1: Track the active poll and stop a prior one

In `index.astro`, introduce a module-level `let activePoll = null;` (an
`AbortController` or a `{ jobId, cancelled }` token). At the start of `poll`,
create the token; in the loop, bail out early if `token.cancelled` is true.
When a new submit starts, set the previous `activePoll.cancelled = true`
before launching the new poll. Pass the token into `poll(vault, jobId, token)`.

Concretely:
```js
let activePoll = null;

async function poll(vault, jobId, token) {
  const maxTries = 40;
  for (let i = 0; i < maxTries; i++) {
    await new Promise((r) => setTimeout(r, 3000));
    if (token.cancelled) return;          // ein neuerer Job hat übernommen
    try {
      const job = await api(`/api/jobs/${encodeURIComponent(vault)}/${jobId}`);
      if (token.cancelled) return;
      // ... bestehende done/failed/running-Äste unverändert ...
    } catch (e) {
      if (token.cancelled) return;
      show(`Job #${jobId}: Statusabfrage fehlgeschlagen — ${e.message}`, 'error');
      continue;
    }
  }
}

// im submit-handler, VOR dem neuen poll():
if (activePoll) activePoll.cancelled = true;
const token = { cancelled: false };
activePoll = token;
poll(vault, res.job_id, token);
```

Keep `finally { submit.disabled = false; }` as-is (re-enabling submit is fine
once polls are serialized).

**Verify**: `cd web && npm run build` → exit 0.

### Step 2: Add a behavior test

In `web/test/` add `poll.test.mjs` (model on `api.test.mjs`'s fetch mocking).
Test: start two polls for two job ids against a mocked `/api/jobs/...` that
returns `running` then `done`; assert that after the second poll starts, the
first no longer mutates a shared status sink. Because `poll` currently writes
directly to the DOM, extract the status-writing into a small injectable sink
(e.g. `poll(vault, jobId, token, sink)` where `sink.show`/`sink.setStep` default
to the DOM functions) so the test can observe calls per job id. Keep the DOM
default behavior identical.

**Verify**: `cd web && npm test` → new test passes; existing tests still pass.

### Step 3: Full suite

**Verify**: `make test` → all pass.

## Test plan

- New `web/test/poll.test.mjs`: two concurrent polls; the older one stops
  mutating the sink once the newer starts.
- Pattern: `web/test/api.test.mjs` (fetch mocking).
- Verification: `cd web && npm test` → all pass.

## Done criteria

- [ ] `cd web && npm test` exits 0
- [ ] `cd web && npm run build` exits 0
- [ ] A prior `poll()` stops updating the DOM when a newer submit starts
- [ ] No files outside the in-scope list are modified
- [ ] `plans/README.md` status row updated

## STOP conditions

- `index.astro` no longer uses a single shared `#result`/`#job-steps` (e.g.
  it was already reworked to per-job rows) — STOP, the bug may already be gone.
- Making `poll` injectable for tests requires changing the public API of
  `api.js` — STOP (out of scope); find a narrower seam.

## Maintenance notes

- If the UI moves to per-job status rows (planned direction), this
  token-based serialization can be dropped — each row owns its own sink.
- Reviewers: confirm the test actually proves the first poll stopped (assert
  zero further sink calls after cancellation), not just that the second ran.
