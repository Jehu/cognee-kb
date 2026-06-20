# Plan 024: [direction] Design — additional source connectors (PDF / X / LinkedIn)

> A **direction spike/design plan**, "offen, Anregung" in
> `docs/2026-06-13-ideen-beemind.md`. The fetcher interface is already
> established, so each connector is one classifier branch + one fetcher. PDF is
> the lowest-risk.
>
> **Executor instructions**: Investigate scope + dep cost per connector and
> produce a short design doc. Do NOT build the feature.
>
> **Drift check (run first)**: `git diff --stat 5c096b7..HEAD -- kb/classify.py kb/fetch_web.py kb/fetch_youtube.py kb/worker.py docs/2026-06-13-ideen-beemind.md`

## Status

- **Priority**: P3 (direction) | **Effort**: S per connector (coarse) | **Risk**: MED
- **Depends on**: none | **Category**: direction | **Planned at**: commit `5c096b7`, 2026-06-19
- **Issue**: #24 — https://github.com/Jehu/cognee-kb/issues/24

## Why this matters (grounding)

`docs/2026-06-13-ideen-beemind.md:66-73` — "Status: offen, Anregung, teilweise
vorhanden"; YouTube (`fetch_youtube.py`) and Web (`fetch_web.py`) exist;
"X-Thread / PDF / LinkedIn wären Erweiterungen des Klassifizierers
(`classify.py`)." The extension point is clean: `classify.py:15-22` returns a
`kind`, and `worker._fetch` (`worker.py:14-25`) dispatches on `kind`. Marco
captures from exactly these sources today (the BeeMind comparison exists
because of them).

## Investigation questions to resolve (per connector)

1. **PDF**: a text-extraction dep (pypdf is already a cognee transitive dep —
   check; else add one). `classify` detects `.pdf` URLs / file content →
   `fetch_pdf` extracts text → `.md`. Lowest risk, highest value.
2. **X / Twitter**: oEmbed or the official API (auth required). Scrape
   fragility + ToS risk. Is a thread fetcher worth the maintenance vs.
   paste-the-text-as-snippet?
3. **LinkedIn**: login-walled; scraping is brittle and ToS-hostile. Likely
   "reject" — confirm and record.
4. **Interface fit**: confirm each new `kind` slots into `build_payload`
   (`classify.py:55-66`) + `_fetch` (`worker.py:14-25`) without changing the
   job/payload contract, and that `SourceRecord.type` (`sources.py:44`)
   accommodates the new kinds.

## Scope of THIS plan (design only)

- Read `classify.py`, `fetch_web.py`, `fetch_youtube.py`, `worker.py`; check
  whether pypdf is importable from the cognee dep tree; produce a per-connector
  go/no-go.

## Done criteria

- [ ] Design doc gives a go/no-go per connector (PDF / X / LinkedIn) with dep
      cost + fragility + ToS notes
- [ ] At least PDF has a concrete shape (classify branch + `fetch_pdf` +
      extraction lib) ready to become a build plan
- [ ] `plans/README.md` status row updated

## STOP conditions

- A connector requires shipping long-lived platform credentials into the
  worker — flag the credential-handling design; don't ignore the privacy wall.
- Extraction quality can't be verified without the dep installed — note the
  verification gap rather than asserting quality.

## Maintenance notes

- PDF is the recommended first build; X/LinkedIn likely stay rejected (record
  why, so they're not re-proposed). Each connector that's built must respect
  plan 004's SSRF guard if it fetches by URL.

---

## Spike result (2026-06-20)

**GO für PDF, NO-GO für X/LinkedIn.**

**Befund (cognee):** cognee bringt ein natives `PdfDocument`-Modul
(`cognee/modules/data/processing/document_types/PdfDocument.py`) — `cognee.add()`
extrahiert PDF-Text selbst. kb muss also nur den Typ erkennen und den Pfad
durchreichen; keine eigene Extraction-Dep nötig.

**Pro-Connector:**
- **PDF — GO (klein):** `classify` erkennt `.pdf`-URL/Datei → `fetch_pdf` (oder
  direkt `cognee.add(pdf_path)`); SSRF-Guard (Plan 004) greift bei URL-Fetch.
  Höchster Nutzen, geringstes Risiko. → `028-pdf-connector.md`.
- **X/Twitter — NO-GO:** oEmbed/Scraper-Fragilität + ToS-Risiko + Auth-Aufwand.
  Workaround: Text manuell als Snippet erfassen (bereits möglich).
- **LinkedIn — NO-GO:** login-walled, scrape-feindlich, ToS-hostil. Snippet ist
  der realistische Pfad.

**Interface-Fit:** jeder Connector = ein `classify`-Zweig + ein Fetcher, dispatched
via `worker._fetch` — die Erweiterungsstelle ist sauber (`SourceRecord.type`
nimmt `pdf` auf). PDF baut auf Plan 004s SSRF-Guard auf, falls per URL gefetcht.
