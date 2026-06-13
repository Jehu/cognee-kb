# Quellen-Chip — Stufe 1 + Stufe 1.5 (Implementierungsplan)

> Ergebnis des Spezialisten-Disputs vom 2026-06-13. Stufe 2 (CYPHER-Fallback für
> Multi-Chunk-Docs) ist bewusst **nicht** Teil dieses Plans (YAGNI — heute kein
> reales Doc > 1 Chunk).

## Ziel

Jede Chat-Antwort liefert zusätzlich zum Antworttext eine Liste der **Quellen**,
die als klickbarer Chip unter der Antwort erscheinen. Die Herkunft wird
**graph-frei** gewonnen: der CHUNKS-Retriever gibt den rohen Chunk-Text inkl.
YAML-Frontmatter zurück; daraus wird die `source_id` per Regex extrahiert und
über den (cognee-freien) `SourceStore` zum vollen `SourceRecord` aufgelöst.

**Warum graph-frei (Disput-Befund, live verifiziert):**
- `raw_data_location` auf dem cognee-Graph-Node ist die interne Hash-Kopie
  (`var/<inst>/cognee_data/text_<hash>.txt`), **nicht** unser `raw_md_path` →
  jeder Pfad-Join über den Graphen ist tot.
- Kuzu hat nur eine `Node`- und eine `EDGE`-Tabelle (keine `:DocumentChunk`/
  `:is_part_of`-Labels) → der naive CYPHER matcht 0 Zeilen.
- Aber: `CHUNKS`-`payload['text']` trägt bei allen realen Docs das volle
  Frontmatter inkl. `source_id` (alle Docs sind Single-Chunk). Das ist der
  verlässliche, billige Weg.

**Ehrliche Grenze:** CHUNKS-Top-k ist die *vektor-ähnlichste* Chunk-Menge, nicht
beweisbar die von GRAPH_COMPLETION synthetisierte. Der Chip heißt darum
**„Quellen"**, nicht „zitiert".

## Fixe Kontrakte (alle Tasks bauen gegen diese)

1. **`cognee_io.query_with_sources(instance, question, datasets) -> tuple[str, list[str]]`**
   - Gibt `(answer, source_ids)` zurück. `answer` = GRAPH_COMPLETION-Text wie
     heute (`_render`). `source_ids` = deduplizierte, reihenfolge-erhaltende
     Liste der aus den CHUNKS-Treffern geparsten `source_id`s.
   - Bleibt **cognee-frei vom SourceStore** — gibt nur die rohen IDs zurück, der
     Aufrufer löst auf. Das bestehende `query()` (→ `str`) bleibt unverändert
     (CLI nutzt es weiter).

2. **`SourceRecord`** bekommt ein **letztes** Feld `title: str | None = None`.
   `SourceStore` migriert bestehende DBs (`ALTER TABLE … ADD COLUMN title`).

3. **Instance Service `POST /query`** liefert
   `{"answer": str, "sources": [{source_id, type, url, locator, raw_md_path, title}]}`.

4. **Gateway `POST /api/query`** reicht `sources` transparent durch:
   `{"vault", "answer", "sources": [...]}`. Zusätzlich neuer Endpoint
   **`GET /api/source/{vault}/{source_id}/raw`** (tokengeschützt, vault-gescoped,
   liefert die Rohdatei als `text/markdown`) — Privacy-Wand: Rohinhalte nie als
   `file://` oder ungeschützt raus.

5. **Frontend** rendert pro Quelle einen Chip: `url`-Quellen (web/youtube) als
   externer Link; `snippet`/`file` als tokengeschützter Abruf des raw-Endpoints
   (Blob → neuer Tab). Leeres `sources` → „Keine Quelle gefunden".

---

## Task 1 — Domain-Layer (Stufe 1 + Stufe 1.5)

**Dateien:** `kb/sources.py`, `kb/cognee_io.py`, `kb/worker.py` +
`tests/test_sources.py`, `tests/test_cognee_io.py`, `tests/test_worker.py`.

### 1a. `kb/sources.py` — `title`-Feld + Migration
- `SourceRecord`: neues **letztes** Feld `title: str | None = None` (Default
  nötig, damit bestehende `SourceRecord.new(...)`-Aufrufe ohne `title` weiter
  funktionieren; frozen-dataclass verlangt Felder mit Default zuletzt).
- `SCHEMA`: Spalte `title TEXT` (am Ende) ergänzen.
- `SourceStore.__init__`: nach `executescript(SCHEMA)` eine **Migration** für
  Bestands-DBs: `ALTER TABLE sources ADD COLUMN title TEXT`, in
  `try/except sqlite3.OperationalError` (Spalte existiert bei frischen/bereits
  migrierten DBs schon → Fehler schlucken). Kurzer Kommentar, *warum*.
- `insert()`: auf **explizite Spalten** umstellen
  (`INSERT INTO sources (id,type,url,video_id,locator,fetched_at,vault,raw_md_path,title) VALUES (?,?,?,?,?,?,?,?,?)`),
  damit es unabhängig von der physischen Spalten-Reihenfolge nach `ALTER` korrekt
  ist.
- `get()`: `title` an **letzter** Stelle in `SELECT` ergänzen; `SourceRecord(*row)`
  bleibt positionsbasiert (passt, weil `title` letztes dataclass-Feld ist).
- `frontmatter()` braucht keine Änderung (`asdict` nimmt `title` automatisch mit).

### 1b. `kb/cognee_io.py` — `query_with_sources` + Extraktion
- Neue Funktion `query_with_sources(instance, question, datasets) -> tuple[str, list[str]]`:
  - `assert_instance_env(instance)`; lazy `import cognee` + `from cognee import SearchType`.
  - GRAPH_COMPLETION wie in `query()` → `answer = "\n".join(_render(r) for r in results)`.
  - Zusätzlich `await cognee.search(query_type=SearchType.CHUNKS, query_text=question, datasets=datasets)`.
  - `source_ids = _extract_source_ids(chunk_results)`; `return answer, source_ids`.
- `_extract_source_ids(results) -> list[str]`: regext `source_id:\s*([0-9a-f-]{36})`
  über den Roh-Text **jedes** Treffers, dedupliziert reihenfolge-erhaltend.
- **Robustheit (wichtig — Shape ist nur statisch belegt, end-to-end ungeprüft):**
  Die exakte Rückgabe-Form von `cognee.search(CHUNKS)` ist nicht 100% sicher
  (dict-`payload` mit `text`, `SearchResult`-Objekt, ACL-dict mit `search_result`,
  plain str). Darum ein defensiver Walker `_iter_strings(obj)`, der rekursiv alle
  String-Blätter sammelt (über dict-values, list-items und die Attribute
  `text`/`search_result`/`payload`), mit Tiefenlimit. `_extract_source_ids`
  regext über die gesammelten Strings. Stil analog zum bestehenden `_render`
  (Kommentar: *warum* defensiv — cognee-Shape je ACL-Modus).
- Kommentare deutsch, knapp, erklären das **Warum**.

### 1c. `kb/worker.py` — Stufe 1.5 (node_set) + title
- `node_set`-Default: `node_set = job.payload.get("node_set") or record.id`.
  `node_sets`-Ableitung vereinfacht sich zu `node_set if isinstance(node_set, list) else [node_set]`
  (node_set ist jetzt immer truthy). Kurzer Kommentar: Versicherung für den
  späteren Stufe-2-CYPHER-Fallback, ändert Stufe 1 nicht.
- `SourceRecord.new(...)`-Aufruf um `title=doc.title` erweitern (FetchedDoc trägt
  `title`).

### 1d. Tests
- `tests/test_sources.py`: Roundtrip-Test deckt `title` ab (z.B. `make_record`
  optional mit `title`; ein Test mit gesetztem `title`). Neuer Test:
  Bestands-DB-Migration (DB ohne `title`-Spalte anlegen → `SourceStore` öffnen →
  `insert`/`get` mit `title` funktioniert). Nicht die bestehende
  `_QuotingDumper`-Logik anfassen.
- `tests/test_cognee_io.py`: neue Tests für `_extract_source_ids` /
  `_iter_strings` über die bekannten Shapes (dict mit `text`-Frontmatter,
  `SearchResult`-Objekt mit `search_result`-Liste, ACL-dict, mehrere Chunks
  derselben Quelle → 1 dedupte ID, kein Treffer → leere Liste). `_render`-Tests
  bleiben.
- `tests/test_worker.py`: die drei `assert_awaited_once_with(..., node_sets=[])`
  müssen auf `node_sets=[<record_id>]` umgestellt werden — `record_id` aus der
  `sources`-Tabelle lesen (`SELECT id FROM sources`). `await_count`-Tests bleiben.

**Verifikation Task 1:** `uv run pytest tests/test_sources.py tests/test_cognee_io.py tests/test_worker.py tests/test_rawstore.py` grün.

---

## Task 2 — Service-Layer

**Dateien:** `kb/instance_service.py`, `kb/gateway.py` +
`tests/test_instance_service.py`, `tests/test_gateway.py`.

### 2a. `kb/instance_service.py` — `/query` mit Quellen
- Handler ruft `cognee_io.query_with_sources(app.state.inst, body.question, datasets=body.datasets)`.
- Auflösung über das bereits vorhandene `app.state.store` (SourceStore aus dem
  Lifespan — selber Loop/Thread, kein neuer Connection nötig): pro `source_id`
  `app.state.store.get(sid)`; `None` überspringen; zu dict
  `{source_id, type, url, locator, raw_md_path, title}` mappen.
- Rückgabe: `{"answer": answer, "sources": sources}`.

### 2b. `kb/gateway.py` — Durchreichen + raw-Endpoint
- `/api/query`: `body = r.json(); return {"vault": v.name, "answer": body["answer"], "sources": body.get("sources", [])}`.
- Neuer Endpoint im **token-geschützten** `api`-Router:
  `GET /api/source/{vault}/{source_id}/raw`:
  - Vault auflösen; `SourceStore(get_instance(v.instance).var_dir / "sources.db")`
    (frische Connection pro Request — wie `JobQueue`-Muster, sqlite thread-gebunden).
  - `rec = store.get(source_id)`; `if rec is None or rec.vault != v.name: 404`
    (Vault-Scope verhindert Cross-Vault-Leak).
  - `p = Path(rec.raw_md_path); if not p.is_file(): 404`; sonst
    `FileResponse(p, media_type="text/markdown")`.
  - Imports: `from kb.sources import SourceStore`, `from fastapi.responses import FileResponse`.

### 2c. Tests
- `tests/test_instance_service.py`: `test_query_calls_cognee_io` auf
  `query_with_sources` umstellen (mit `raising=False` mocken, da das Symbol
  ggf. parallel entsteht), Mock-Return `("Antwort!", [])`, Assert
  `{"answer": "Antwort!", "sources": []}`. Zusätzlich ein Test, der
  `query_with_sources` `("A", ["sid1"])` zurückgibt und über ein in `app.state`
  injiziertes/gemocktes Store-`get` einen Chip-dict erzeugt.
- `tests/test_gateway.py`: `test_query_proxies_to_instance` — `_FakeResponse`
  liefert nun auch `sources` (oder Default `[]` prüfen); Assertion auf
  `{"vault": ..., "answer": "42", "sources": [...]}`. Neuer Test für den
  raw-Endpoint: bekannte Quelle (Store mit Record) → 200 + Markdown; fremder
  Vault / unbekannte ID → 404; ohne Token → 401.

**Verifikation Task 2:** `uv run pytest tests/test_instance_service.py tests/test_gateway.py` grün.

---

## Task 3 — Frontend

**Dateien:** `web/src/pages/chat.astro`, `web/src/lib/api.js`.

- `render()` in `chat.astro`: für Assistant-Messages nach `.body` eine
  `.sources`-Zeile rendern, wenn `msg.sources` vorhanden. Pro Quelle ein Chip:
  - Anzeigetext = `title` || Stem von `raw_md_path` || `type`.
  - Optional `locator` anhängen, wenn `!= null`.
  - Icon/Präfix nach `type`.
  - `link`: bei `url` (web/youtube) → `<a href=url target="_blank" rel="noopener">`.
    Bei `snippet`/`file` → Button, der via tokengeschütztem Fetch
    (`/api/source/{vault}/{source_id}/raw`, `Authorization: Bearer`) den Text holt
    und als Blob in neuem Tab öffnet (Token bleibt im Header, nicht in der URL).
  - Leeres/fehlendes `sources` bei Assistant-Antwort → dezenter Hinweis
    „Keine Quelle gefunden".
  - Überschrift/Label „Quellen" (nicht „zitiert").
- `api.js`: Helfer `sourceRawUrl(vault, sourceId)` und/oder `fetchSourceRaw(...)`
  (Fetch mit Bearer-Token → `res.blob()` → `URL.createObjectURL` → `window.open`).
  `history`-Objekt um `sources` erweitern; im `submit`-Handler
  `history.push({ role: 'assistant', text: res.answer, sources: res.sources, vault })`.
- `msg.vault` für den raw-Link mitführen.

**Verifikation Task 3:** `cd web && npm run build` ohne Fehler.

---

## Gesamt-Verifikation (nach allen Tasks)

- `uv run pytest` komplett grün.
- `cd web && npm run build` grün.
- Optionaler Live-Smoke (Disput-Verifikationsschritt, Queue ist leer →
  Restart gefahrlos): `local`-Service neu starten, echte Frage gegen `privat`
  stellen, prüfen dass `sources` den Adler-`source_id` mit korrektem
  `raw_md_path` liefert. **Nur auf ausdrückliche Freigabe** (berührt den
  laufenden Dienst).

## Invarianten (gelten für alle Tasks)

- Nur `kb/cognee_io.py` importiert cognee.
- Keine Embedding-/Provider-Änderung; Privacy-Wand bleibt heil.
- Ein Loop pro Instanz, Kuzu single-writer — keine neuen cognee-Prozesse.
- Kommentare/Docstrings deutsch, knapp, erklären das **Warum**.
- Commit-Messages englisch, im Stil der Historie; keine Attribution.
