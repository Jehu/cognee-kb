# Ideen aus BeeMind für die KB

Stand: 2026-06-13 · Quelle: [beemind.app](https://beemind.app/) (Read-it-Later-App
mit KI, von den Machern von Elephas; nativ macOS/iOS). Recherche-Notiz +
abgeleitete Ideen für unser Cognee-Knowledge-System. **Keine** dieser Ideen ist
beschlossen — Backlog zum Bewerten.

## Was BeeMind macht

Kerngedanke: nicht ganze Artikel für „irgendwann" wegspeichern, sondern **kleine,
entscheidende Snippets** (Zitate, Gedanken, Entscheidungen, Links) in Sekunden
erfassen und dafür sorgen, dass man sie wiederfindet und behält.

- **Instant Capture** aus jeder App (iOS Share Sheet, macOS Services). Quellen:
  YouTube, X/Twitter, LinkedIn, Web-Artikel, PDFs, Code-Snippets.
- **Automatisches Linking / Knowledge Graph** — KI taggt und verbindet verwandte
  Fragmente selbst, ohne Ordner oder manuelle Tags.
- **Chat & Suche mit Quellenangaben** — natürlichsprachliche Frage an die eigene
  Bibliothek, jede Antwort rückverweist auf das gespeicherte Snippet.
- **Spaced Repetition (SM-2)** — gespeicherte Snippets werden automatisch zur
  Wiederholung eingeplant. Der eigentliche Twist: Capture **plus** aktives Behalten.
- **Content Creation** — Snippets in Artikel/Essays umwandeln.
- **Privacy** — eingebautes Modell, eigener API-Key (Claude/GPT-4/Gemini) **oder
  100 % lokal** für Chat und Indexing.

Überschneidung mit uns ist hoch: Privacy-Wand ↔ „100 % lokal", Auto-Linking ↔
Cognee-Graph, Chat-mit-Quellen ↔ `GRAPH_COMPLETION`.

## Abgeleitete Ideen

### 1. Source-Attribution im Query-Output

**Status:** umgesetzt.

BeeMind verkauft „jede Antwort rückverweisbar zum Snippet" als Kernversprechen.
Die Daten-Brücke wird inzwischen im Query-Pfad überquert:

- `query_with_sources()` in [`cognee_io.py`](../kb/cognee_io.py) kombiniert
  `GRAPH_COMPLETION` für die Antwort mit einem begleitenden `CHUNKS`-Lauf.
- `_extract_source_ids()` liest `source_id` aus den Chunk-Strings defensiv über
  mehrere mögliche cognee-Rückgabeformen.
- `instance_service.py` löst diese IDs über `SourceStore` zu Quellen-Chips auf.
- `gateway.py` reicht die Quellen durch und bietet den token-geschützten
  Raw-Endpoint `/api/source/{vault}/{source_id}/raw`.
- Die PWA zeigt Quellen-Chips im Chat und öffnet lokale Rohtexte über einen
  Bearer-geschützten Fetch statt per Token in der URL.

### 2. Spaced Repetition (SM-2) als optionaler Retrieval-Layer

**Status:** offen, nicht prioritär, vorgemerkt für Lernen/Erinnern.
(MuninnDB-Engram `01KV0W4YVHMR554N8FB0WEBNGD`.)

Unsere KB ist heute reines **Pull** (Query on demand). BeeMind dreht das um: SM-2
**pusht** Snippets aktiv zurück. Für uns: ein `next_review`/`ease`-Feld (Frontmatter
oder eigene `review`-Tabelle neben der Queue), Gateway/PWA zeigt eine „Heute
fällig"-Ansicht. Passt sauber, weil `raw/<vault>/` schon versionierte Markdown-
Snippets mit Frontmatter sind.

### 3. Content-Creation-Modus

**Status:** offen, Anregung, unbewertet.

Aus mehreren Vault-Treffern einen Entwurf generieren — ein zweiter Query-Modus
neben der direkten Antwort.

### 4. Multi-Source-Connectoren erweitern

**Status:** offen, Anregung, teilweise vorhanden.

BeeMind zieht aus YouTube/X/LinkedIn/PDF. Wir haben YouTube
([`fetch_youtube.py`](../kb/fetch_youtube.py)) und Web
([`fetch_web.py`](../kb/fetch_web.py)); X-Thread / PDF / LinkedIn wären
Erweiterungen des Klassifizierers ([`classify.py`](../kb/classify.py)).

## Korrektur einer früheren Fehlannahme

Ein erster Vorschlag „Snippet-First statt Document-First" beruhte auf einer
Vermutung über unsere `cognify`-Granularität — **falsch**. Der Snippet-Pfad
existiert bereits vollständig: `classify()` stuft alles ohne URL als `snippet` ein
([`classify.py:22`](../kb/classify.py)), `SourceRecord.type` kennt
`youtube | web | snippet | file` ([`sources.py:42`](../kb/sources.py)), und pro
Quelle wird genau eine `.md` geschrieben ([`rawstore.py:18`](../kb/rawstore.py)).
Capture-Granularität = eine Markdown-Datei pro Quelle; Cognee chunkt intern beim
`cognify`. Kein Handlungsbedarf.
