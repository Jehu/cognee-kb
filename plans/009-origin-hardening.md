# Plan 009: Harden the PWA origin (security headers + CSP + source-URL scheme)

> Covers findings #9 (no CSP/security headers) and #16 (source-chip `href`
> accepts any URL scheme). One issue will be created for this combined theme;
> both findings map to this plan in `plans/README.md`.
>
> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 5c096b7..HEAD -- kb/gateway.py web/src/pages/chat.astro tests/test_gateway.py`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: security
- **Planned at**: commit `5c096b7`, 2026-06-19
- **Issue**: #9 — https://github.com/Jehu/cognee-kb/issues/9

## Why this matters

The bearer token lives in `localStorage` (`api.js:18-20`). Today there is no
XSS sink (all chat/source rendering uses `textContent`), so the token is safe.
But the entire posture rests on "no one ever adds an `innerHTML`/`set:html`".
A single future regression rendering LLM output or an ingested title as HTML
becomes immediate token theft, with nothing slowing it down. A CSP converts
that from catastrophic to contained. Separately, source chips set
`chip.href = src.url` (`chat.astro:145`) with no scheme check — safe today
because `classify` enforces https on ingest, but a `javascript:`/`data:` URL
in the column (DB edit, a future writer) is a click-driven XSS in the PWA
origin. Both are cheap defense-in-depth fixes; neither changes any current
behavior.

## Current state

- `kb/gateway.py:166-169` — PWA mounted via `StaticFiles`, no header
  middleware; `grep content-security|x-frame|add_middleware` → none.
- `web/src/layouts/Base.astro:14-22` — `<head>` has no CSP meta.
- `web/src/pages/chat.astro:141-150` — `chip.href = src.url; chip.target =
  '_blank'` with no scheme validation.
- Astro bundles page `<script>` blocks into external same-origin assets and
  inlines `<style is:global>` into the document `<head>` (confirmed: pages use
  `<script>` + `<style is:global>`, no inline event handlers, no remote CDNs).
  So `script-src 'self'` is viable; `style-src` needs `'unsafe-inline'` (or
  hashes) because Astro inlines styles.
- The source-raw feature opens a `blob:` URL in a new tab (`api.js:102-104`);
  avoid a CSP directive that blocks top-level blob navigations (do not set
  `navigate-to`).

## Repo conventions to match

- German comments explaining the why (defense-in-depth for the localStorage
  token).
- Gateway middleware pattern: add via `@app.middleware("http")` inside
  `create_app` (FastAPI/Starlette), matching the app-construction style at
  `gateway.py:78-80`.

## Commands you will need

| Purpose    | Command                                  | Expected on success |
|------------|------------------------------------------|---------------------|
| Tests      | `uv run pytest tests/test_gateway.py`    | all pass            |
| Web tests  | `cd web && npm test`                      | all pass            |
| Web build  | `cd web && npm run build`                | exit 0              |
| Full suite | `make test`                              | all pass            |

## Scope

**In scope**:
- `kb/gateway.py` (header middleware)
- `web/src/pages/chat.astro` (scheme guard on source-chip href)
- `tests/test_gateway.py` (assert headers present)

**Out of scope**:
- Do NOT move scripts/styles to external files (Astro already bundles scripts;
  style `'unsafe-inline'` is acceptable as a pragmatic first step).
- Do NOT change the token storage model (localStorage is a documented
  single-user tradeoff).
- Do NOT touch the service worker.

## Git workflow

- Branch: `advisor/009-origin-hardening`
- Commit style: `Add security headers + CSP and validate source-chip URL scheme`

## Steps

### Step 1: Add a header middleware to the gateway

In `kb/gateway.py` `create_app`, before `app.include_router(api)` (so it covers
both API and the PWA mount), add:

```python
    @app.middleware("http")
    async def security_headers(request, call_next):
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = (
            "default-src 'self';"
            "connect-src 'self';"
            "script-src 'self';"
            "style-src 'self' 'unsafe-inline';"
            "img-src 'self' data:;"
            "object-src 'none';"
            "base-uri 'none';"
            "frame-ancestors 'none';"
            "manifest-src 'self';"
            "worker-src 'self';"
            "form-action 'self'"
        )
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        return response
```

Rationale comment (German): defense-in-depth — der Token liegt in localStorage;
ein künftiges innerHTML/set:html würde ohne CSP sofort den Token exfiltrieren.

**Verify**: `uv run pytest tests/test_gateway.py` → existing tests pass (the
middleware is additive; if any test asserts an exact header set, update it).

### Step 2: Validate the source-chip URL scheme

In `web/src/pages/chat.astro`, where the `<a>` chip is built (~line 141-150),
only assign `href` for http(s); otherwise fall back to the button path
(tokengeschützter Raw-Download) or render as plain text. Concretely, guard
with a scheme check:

```js
const SAFE_URL = /^https?:\/\//i;
// ...
if (src.url && SAFE_URL.test(src.url)) {
  // bestehender <a>-Zweig
} else {
  // bestehender Button-Zweig (openSourceRaw) — gilt dann auch für URLs mit
  // fremdem Schema, statt chip.href blind zu vertrauen
}
```

**Verify**: `cd web && npm run build` → exit 0.

### Step 3: Tests

- `tests/test_gateway.py`: add a test hitting any route (e.g. `/api/health`)
  that asserts the response carries `Content-Security-Policy`,
  `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`,
  `X-Frame-Options: DENY`.
- `web/test/`: add a small unit test for a `safeSourceHref(url)` helper
  (extract the check into a tiny exported function in `api.js` or a new
  `web/src/lib/safe.js` so it is testable) returning the URL only for
  `^https?://`, else `null`. Assert `javascript:alert(1)`, `data:text/html,...`
  → null; `https://x` → the URL.

**Verify**: `uv run pytest tests/test_gateway.py` and `cd web && npm test` → all pass.

### Step 4: Smoke-test the PWA under CSP

Build and load: `cd web && npm run build`, then start the gateway and open the
PWA. Confirm: chat works, source chips open, no CSP violations in the browser
console. (If the SW registration or blob-open reports a CSP error, widen the
specific directive minimally — do NOT loosen `script-src`.)

**Verify**: no CSP violation console errors on `/`, `/chat/`, `/settings/`.

## Test plan

- `tests/test_gateway.py`: header bundle present on a response.
- `web/test/`: `safeSourceHref` scheme table.
- Verification: `make test` + manual CSP smoke (Step 4).

## Done criteria

- [ ] `uv run pytest` and `cd web && npm test` exit 0
- [ ] `cd web && npm run build` exits 0
- [ ] Gateway responses carry CSP, X-Content-Type-Options, Referrer-Policy,
      X-Frame-Options
- [ ] Source chips never assign a non-http(s) `href`
- [ ] No CSP console errors on the three PWA pages after build
- [ ] No files outside the in-scope list are modified
- [ ] `plans/README.md` status row updated

## STOP conditions

- A legitimate PWA feature breaks under the proposed CSP (e.g. an inline
  script Astro did NOT bundle) — STOP and report which directive needs
  widening rather than broadly loosening the policy.
- Astro does NOT hoist the page `<script>` to an external file in the current
  version (verify in the built `dist/`): if inline scripts remain, `script-src
  'self'` will break the app — switch to per-script hashes, do NOT use
  `'unsafe-inline'` for scripts without escalation.

## Maintenance notes

- When any page adds an inline event handler or `set:html`, revisit CSP
  (`script-src`) — that is exactly the regression CSP is meant to catch.
- If the source-raw blob-open ever moves into an `<iframe>`, add `blob:` to
  `frame-src`.
- Reviewers: confirm the built `dist/` has no inline `<script>` (only
  external + the style inline) before accepting `script-src 'self'`.
