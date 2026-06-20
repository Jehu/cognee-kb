# Plan 023: [direction] Design — Spaced-Repetition (SM-2) retrieval layer

> A **direction spike/design plan**, explicitly "offen, vorgemerkt" in
> `docs/2026-06-13-ideen-beemind.md`. Goal: decide scope + whether to build now.
>
> **Executor instructions**: Investigate and produce a short design doc. Do NOT
> build the feature.
>
> **Drift check (run first)**: `git diff --stat 5c096b7..HEAD -- kb/sources.py kb/gateway.py docs/2026-06-13-ideen-beemind.md`

## Status

- **Priority**: P3 (direction) | **Effort**: M–L (coarse) | **Risk**: MED
- **Depends on**: none | **Category**: direction | **Planned at**: commit `5c096b7`, 2026-06-19
- **Issue**: #23 — https://github.com/Jehu/cognee-kb/issues/23

## Why this matters (grounding)

`docs/2026-06-13-ideen-beemind.md:48-57` — "Status: offen … vorgemerkt für
Lernen/Erinnern" (MuninnDB engram `01KV0W4YVHMR554N8FB0WEBNGD`). The KB is
today pure **pull** (query on demand). SM-2 **pushes** snippets back for
review. The storage shape already supports it: `raw/<vault>/` holds
frontmattered `.md` snippets (`sources.py` `frontmatter()`) — a
`next_review`/`ease`/`interval` field lands cleanly, and a Gateway/PWA "Heute
fällig" view is one endpoint + page away.

## Investigation questions to resolve

1. **Storage**: add review fields to the source frontmatter + a `review` table
   (or columns on `sources`), vs a separate SQLite DB. Which fits the existing
   `SourceStore` pattern (`sources.py`) without a heavy migration?
2. **Scheduler**: a review-push needs a scheduler. The serial-worker invariant
   (one writer per wall) and the privacy wall (no cloud calls for `local`)
   constrain where scheduling runs. Confirm a single in-process scheduler per
   instance is acceptable, or whether review is purely on-demand (PWA polls
   "due today").
3. **Scope of review item**: review whole sources, or individual
   chunks/snippets? BeeMind reviews small snippets; Cognee chunks internally —
   decide the unit.
4. **SM-2 UX**: rate-on-review (again/hard/good/easy) → ease/interval update.
   Keep the algorithm minimal and well-tested (SM-2 is small but easy to get
   wrong).

## Scope of THIS plan (design only)

- Read `kb/sources.py`, `kb/rawstore.py`, `docs/2026-06-13-ideen-beemind.md`;
  produce a design doc answering the 4 questions + a go/no-go.

## Done criteria

- [ ] Design doc records storage choice, scheduler placement (respecting the
      privacy wall + serial worker), review unit, and SM-2 scope
- [ ] A go/no-go with the deciding trade-off (the pull→push inversion is the
      real cost)
- [ ] `plans/README.md` status row updated

## STOP conditions

- The scheduler would force cloud calls for the `local` wall — reject that
  design; review scheduling must stay local-only.
- SM-2 correctness can't be locked with a small test set — propose the test
  cases rather than skipping them.

## Maintenance notes

- This inverts the KB's pull model; treat as a product decision for Marco, not
  an obvious win. The doc's job is to make the trade-off visible.

---

## Spike result (2026-06-20)

**DEFERRED (Produktentscheidung von Marco) — Design ist solide, aber Pull→Push-Inversion ist der echte Kostenpunkt.**

**Antworten:**
1. **Storage:** Spalten auf `sources` (`next_review`, `ease`, `interval`,
   `last_review_at`) statt separater Tabelle — passt zur bestehenden
   `SourceStore`-Migration (wie `title`/`content_hash`) und hält alles in einer
   DB. Frontmatter-Felder同步 via `frontmatter()`.
2. **Scheduler:** **on-demand** (PWA fragt „Heute fällig" per
   `GET /api/sources/{vault}?due=today`), **kein** Hintergrund-Scheduler.
   Begründung: ein Scheduler müsste für die `local`-Wall 100 % lokal bleiben
   (Privacy-Wand) und single-instance sein — das on-demand-Modell umgeht beides
   und reicht für Single-User.
3. **Review-Einheit:** ganze Quelle (ein `.md`), nicht einzelne Chunks — passt
   zu kb's Granularität (eine Quelle = eine Rohdatei). Chunk-Level wäre
   over-engineering.
4. **SM-2:** klein und gut testbar (Algo ist ~15 Zeilen); Testset aus
   known SM-2-Vektoren sperren.

**Empfehlung:** erst angehen, wenn Marco aktives Behalten wirklich will —
invertert das aktuelle Pull-Modell. Kein Follow-up-Stub, bis Go kommt.
