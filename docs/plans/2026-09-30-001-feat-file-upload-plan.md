---
title: PWA File Upload - Plan
type: feat
date: 2026-09-30
artifact_contract: ce-unified-plan/v1
product_contract_source: ce-plan-bootstrap
execution: code
---

# PWA File Upload - Plan

## Goal Capsule

- **Objective:** A user can select a local PDF (and the already-supported plain-text formats) in the PWA, choose a vault and collections, submit it, and see its ingest job finish without using the CLI or making the file publicly reachable.
- **Means:** An authenticated multipart upload endpoint stages a bounded file under the selected wall's private `var/` tree, enqueues a reference in that wall's existing SQLite queue, and lets its single worker extract and ingest through the existing raw Markdown and Cognee pipeline.
- **Authority:** This plan scopes the requested file-upload feature following the PDF gap; `kb.toml` and the existing wall isolation, token, queue, and collection contracts remain authoritative.
- **Stop conditions:** Do not ship a path that copies private bytes into the cloud wall by default, accepts a browser-supplied filesystem path, retains unbounded uploads, or loses queued files on gateway/worker restart.

## Product Contract

### Requirements

- **R1 — Capture:** The PWA lets the user choose exactly one `.pdf`, `.md`, or `.txt` file instead of entering a URL/note. The selected vault and up to ten selected collections apply unchanged; the wall hint remains visible. Existing text/URL capture stays intact. The default selected vault must not change silently when switching modes.
- **R2 — Upload:** A valid authenticated upload returns the existing `202` job response (`job_id`, `vault`, `kind`), then the existing job status reports pending/running/done/failed. For unsupported, empty, oversized, invalid, or unreadable files, show an actionable error; a textless/scanned PDF reports that no text could be extracted (OCR is out of scope).
- **R3 — Limits and privacy:** Accept one file, at most 20 MiB, with strict server-side format validation: PDF magic plus parseable PDF for PDFs; UTF-8 decoding for `.md`/`.txt`. Keep bytes on the chosen wall's local disk, not in the request URL, logs, SQLite job payload, browser localStorage, or another wall. Reject invalid token/vault/collection without creating a job or retaining a file.
- **R4 — Lifecycle:** Queue-owned staged bytes survive process restarts until the job consumes them. After success, dedup skip, or failure, discard them; reclaim interrupted/unreferenced files safely without deleting files still needed by pending/running jobs. Preserve the canonical `raw/<vault>/` Markdown and SourceRecord as the durable output, not the original upload.
- **R5 — Compatibility:** PDF URL capture, snippets, CLI local-file ingest, queue status, dedup by extracted body within a vault, and collection reindex remain unchanged. Do not expose staged absolute paths as a source locator or a public download.

### Scope decisions

- The initial picker supports `.pdf`, `.md`, and `.txt`; these map to the currently existing PDF extraction and plain-text worker paths. Other binary formats, multi-file batch upload, image OCR, and preserving the original binary for later download are out of scope.
- The 20 MiB cap bounds single uploads; the interface names the cap before submission. This is an implementation default, not an observed current system limit. Extracted PDF text can still be large; bound processing if practical without changing PDF URL semantics.

### Acceptance examples

1. With a valid token, upload a UTF-8 `.txt` or `.md` into `privat` with a chosen collection; receive a job ID, observe `done`, and see one source in the selected vault/collection. Another wall does not receive that source or the staged file.
2. Upload a text-bearing `.pdf` to `allgemein`; the worker extracts text, creates the raw Markdown source, and completes the job. Uploading the same extracted body again returns a job that finishes without a duplicate source.
3. Submit a scanned PDF with no extractable text: the job fails with a useful message; no source/raw file or staged binary remains.
4. Reject an expired token, unknown vault, foreign/archived collection, `.exe` disguised as `.pdf`, invalid UTF-8 `.txt`, zero-byte file, and a file over 20 MiB without enqueueing or retaining bytes. Reject a multipart request with more than one file.
5. Stop and restart the gateway and worker while a job is pending: the staged file remains available and the recovered worker completes it. An orphan from a failed enqueue/aborted request is reclaimed without touching referenced pending jobs.

## Planning Contract

### Key Technical Decisions

- **KTD1 — Separate endpoint:** Add `POST /api/uploads` under the existing authenticated `/api` router, accepting multipart form fields `vault`, `file`, and `collection_ids` (repeated field or one documented JSON field). Retain JSON `/api/ingest` unchanged. This prevents applying a browser path to the text classifier and keeps client contracts distinct (`kb/gateway.py:59-72,163-181`).
- **KTD2 — Private wall-local staging:** Resolve the vault first, stream a bounded upload into a unique, server-generated filename under `var/<instance>/uploads/<vault>/` with private directory/file permissions. Stage atomically before enqueue; payload includes only a server-created reference and minimal metadata, not bytes or a client-supplied path. Do not derive a destination path from the user filename. Validate the resolved staged path remains under its vault/wall root when the worker consumes it. CLI path jobs remain allowed only on their existing CLI route (`kb/cli.py:205-233`, `kb/worker.py:18-33`).
- **KTD3 — Bounded and honest validation:** Check `Content-Length` as an early optimization, but enforce the 20 MiB limit while streaming chunks and rejecting overflow. Limit multipart fields and files (including malformed/aborted requests); do not rely on browser `accept` or MIME alone. Require `.pdf` plus `%PDF-` header and PDF parseability, or `.md`/`.txt` plus UTF-8 decode; reject empty files and unextractable PDFs as appropriate. If PDF parsing is deferred to the worker, return `202` then a failed job with a clear reason, rather than claiming synchronous validation.
- **KTD4 — Ownership and cleanup:** Record the upload's server-generated reference in a distinct upload job kind or explicit trusted-upload payload, rather than reinterpreting arbitrary `pdf/path` or `file/path` jobs. Worker removes the staged binary in `finally` across success, dedup, and failures. For crash recovery, reconcile only terminal-job or unreferenced staged files with a grace period; never TTL-delete bytes referenced by pending/running jobs. Failed enqueue and request cancellation remove staged bytes. Keep stale-running recovery (`kb/queue.py:94-100`) compatible.
- **KTD5 — Browser transport:** Update `web/src/lib/api.js` so `FormData` does not get an explicit JSON `Content-Type`; browser supplies the multipart boundary, helper still sends Bearer. Keep JSON requests unchanged. Extend `web/src/pages/index.astro` with a text/file mode or mutually exclusive controls and one-file picker, preserving collections and progress. Existing polling uses unauthenticated `fetch` (`index.astro:86-98`); use the authenticated API helper and cancel stale polls so uploaded jobs can actually reach a visible terminal state.
- **KTD6 — Source metadata:** Uploaded PDF/text source title comes from a safe display filename (or PDF metadata if appropriate). Do not retain the staging path in `SourceRecord.locator`; use a safe, non-path display name or no locator. Keep existing CLI source locators and URL sources unchanged.

### Dependencies and risks

- `python-multipart` is already version-overridden in `pyproject.toml:38-41`; add it as a direct dependency if FastAPI's multipart route requires a direct declared runtime dependency, update `uv.lock`, and do not loosen its security floor.
- FastAPI/Starlette's multipart parser may spool data before handler-level validation; choose framework/parser limits or an equivalent streaming strategy that actually bounds unauthenticated or oversized request impact, rather than assuming a loop around `UploadFile.read()` is a whole-request cap.
- A worker in the same wall reads the file after a different process enqueues it; do not unlink at HTTP response time. Guard against symlinks, traversal, upload-path tampering, and cross-vault references; staged names are not trust boundaries by themselves.
- Uploaded file names/metadata are untrusted UI text; render as text, not HTML. Uploaded content is private data; logging, error responses, source locators and telemetry must not reveal file bytes or internal paths.

## Implementation Units

### U1 — Gateway upload contract and bounded staging

- **Files:** `kb/gateway.py`, a small wall-local upload helper if warranted, `pyproject.toml`, `uv.lock`, `tests/test_gateway.py` (or the existing corresponding gateway test module).
- **Approach:** Add authenticated single-file multipart route. Validate vault and collections before writing, stage privately under the selected wall, enforce total/file/field bounds, validate supported formats and ensure cleanup on validation/enqueue failure. Return the existing 202 response, enqueue an upload-owned reference in the selected wall. Do not change JSON `/api/ingest`.
- **Tests:** Valid PDF/text request with token yields one queued job in selected wall; no bytes in queue payload. Bad token, foreign collection, unknown vault, duplicate file fields, empty/misnamed/oversized/invalid-UTF-8 files return expected 4xx and no retained staging/job. Simulated enqueue exception leaves no staged file; test limit when body is streamed without trusting `Content-Length`.

### U2 — Worker consumption and staged-file lifecycle

- **Files:** `kb/worker.py`, `kb/fetch_pdf.py` if filename handling needs adjustment, `kb/queue.py` only if reference-aware orphan cleanup needs queue inspection, `tests/test_worker.py`, targeted upload lifecycle tests.
- **Approach:** Resolve the server-owned reference within the job's vault wall, extract PDF/text through existing paths, preserve current dedup/source/collection/Cognee behavior; never expose staging path as locator. Remove staging in `finally`; reconcile old orphans at controlled startup/maintenance only after checking active queue references. Keep CLI paths unaffected.
- **Tests:** PDF/text source succeeds and collection state is correct; duplicate body skips source and removes file; scanned PDF, invalid/stale upload reference, and Cognee failure mark failed and remove only that job's staged file. Pending upload survives restart and `recover_stale`; orphan cleanup spares pending/running files and removes abandoned/terminal ones after grace. Cross-vault/cross-wall and traversal references are rejected.

### U3 — PWA capture and progress

- **Files:** `web/src/pages/index.astro`, `web/src/lib/api.js`, existing `web` test module(s) relevant to API/capture, styles only if needed.
- **Approach:** Add accessible file mode and picker with accepted formats/cap, preserve vault and collection selection, disable duplicate submit while uploading, send `FormData` through shared authenticated helper, show validation and network failures, clear file only after 202, and use token-authenticated job polling to show terminal status. Do not force multipart `Content-Type`.
- **Tests:** JSON capture still sends JSON; FormData sends Bearer and no explicit content type; selected file/vault/collections submitted once. Error leaves selection for retry; job pending→running→done/failed surfaces correctly; invalid type/oversize rejected before transfer as convenience while server remains authoritative.

### U4 — Documentation and real-flow verification

- **Files:** `README.md` (capture, supported formats, limit, PDF OCR limitation, CLI distinction), optionally `docs/` user-facing operations only if upload cleanup/backup procedures are documented there.
- **Approach:** Document browser upload versus PDF URL/CLI; document that original binaries are temporary, raw Markdown is canonical and the wall is selected by vault. Verify gateway+worker+PWA together with representative real files, not just mocked endpoints.
- **Tests:** No new permanent test for wording; browser smoke with a small text-bearing PDF and UTF-8 note plus error case. Confirm jobs reach terminal state and staging is gone; local vs cloud isolation is observed in the intended vault/source listing.

## Verification Contract

- Run focused gateway, worker, and web tests while implementing; finish with `uv run pytest` and `cd web && npm test && npm run build` (the repo has no lint command).
- Start the actual gateway and one instance service in an isolated test environment; submit real multipart requests with token and poll the authenticated job endpoint through a pending→terminal transition. Inspect only test wall `var/` staging and source records, never production private data.
- Open the built PWA in a browser, select PDF/text file, vault and collection, submit, observe accepted/running/done or actionable failure; confirm JSON snippet and PDF URL flows still work. Exercise a real failed scanned/textless PDF. If full Cognee runtime is unavailable, explicitly report that limit and still run a temporary gateway+worker smoke with real parsing and isolated persistence.
- Security checks: unauthorized and cross-vault attempts create neither job nor retained bytes; oversized chunked transfer is bounded; queue/restart/orphan reconciliation does not delete live input; no internal path appears in UI/job JSON.

## Definition of Done

- R1–R5 and their acceptance examples hold end-to-end. Every uploaded job's private bytes have a bounded, wall-local lifetime and no upload path is publicly reachable or logged.
- Existing JSON/CLI ingest and collections continue to work, status polling uses authentication, and the README describes the supported formats and limits. No temporary fixtures or staged artifacts remain from verification.
