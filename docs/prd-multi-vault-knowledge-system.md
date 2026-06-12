# PRD: Multi-Vault Knowledge-System („KB")

*Stand 12. Juni 2026. Basis: [architektur-knowledge-system-cognee.md](architektur-knowledge-system-cognee.md) plus Recherche-Befunde zu Cognee-Constraints (Muninn-Engram `01KTXRGNXMCNRV77C2EKPWFE5N`).*

## 1. Problem & Ziel

Marco sammelt Wissen aus YouTube-Videos, Weblinks, Snippets und Transkripten. Heute: Obsidian-Vault mit Git-Sync-Schmerz auf iOS, manuelle Struktur, kein agententauglicher Abruf.

**Ziel:** Ein ingestion-first Knowledge-System. Links/Texte reinwerfen → System erfasst, strukturiert (Knowledge Graph + Embeddings via Cognee) und legt rückverfolgbar ab. Primärer Konsument ist ein **KI-Agent** (via MCP), nicht manuelles Browsen.

## 2. Nutzer & Use Cases

Single-User (Marco) + seine Agenten (Claude Code, Huginn).

1. **Ingest unterwegs:** YouTube-Video in iOS teilen → landet transkribiert im richtigen Vault.
2. **Ingest am Mac:** URL/Text/Datei per CLI oder PWA-Form einwerfen.
3. **Frage stellen:** Chat (PWA) oder Agent (MCP) fragt einen Vault, bekommt synthetisierte Antwort mit Quellenbezug.
4. **Quelle nachschlagen:** Von jeder Antwort zurück zur Original-URL/Timestamp/Rohdatei.

## 3. Anforderungen

### Funktional (MUSS)

- **F1 Quelltypen:** YouTube-Link (Transkript-Fetch), Weblink (Text-Extraktion), Snippet (Rohtext), Markdown-/Textdatei.
- **F2 Vaults:** `privat`, `business-ki`, `business-mwe`. Jeder Ingest geht explizit in genau einen Vault.
- **F3 Isolation:** Privat ist **physisch** getrennt (eigene Cognee-Instanz, eigener Prozess, eigene Datenpfade, eigener MCP-Server). Business-Vaults sind Datasets einer gemeinsamen Instanz mit `ENABLE_BACKEND_ACCESS_CONTROL=true` (ohne das Flag ignoriert Cognee Dataset-Filter!).
- **F4 Provenance:** Jede Quelle bekommt einen Source-Record (id, type, url, video_id, locator, fetched_at, raw_md_path) in eigener SQLite-Tabelle + als Frontmatter in der Rohtext-`.md`. Cognee bekommt `node_set`-Tags; Custom-Metadata existiert in Cognee nicht via REST/MCP.
- **F5 Rohschicht:** Jeder Ingest erzeugt eine kanonische `.md`-Kopie unter `raw/<vault>/` (Exit-Versicherung, Re-Ingest-Fähigkeit).
- **F6 LLM-Routing:** Privat-Instanz: Ollama für LLM **und** Embeddings (kein Cloud-Call, auch nicht query-seitig). Business-Instanz: Cloud-LLM (OpenRouter oder Infomaniak), Embeddings lokal via Ollama.
- **F7 Serielle Ingestion:** Pro Instanz genau ein Worker-Prozess, Jobs strikt seriell (Cognee-Config ist prozess-global; parallele cognify-Calls = Race Condition).
- **F8 Agent-Zugriff:** Ein `cognee-mcp`-Server pro Instanz. Der Privat-MCP wird nur in privaten Kontexten registriert.
- **F9 iOS-Ingest:** Kurzbefehl „Teilen → an KB" → `POST /ingest` (Gateway), erreichbar via Tailscale.

### Nicht-funktional

- **N1 Datenschutz:** Privat-Inhalte verlassen den Mac nie (LLM, Embeddings, Suche — alles lokal). Erzwungen durch Env-Guard im Worker (Abbruch bei falschem `LLM_PROVIDER`/`EMBEDDING_PROVIDER`).
- **N2 Einfachheit:** Single-User. SQLite statt Redis/Celery, Dateisystem statt Object Storage, keine Container-Pflicht.
- **N3 Exit-Fähigkeit:** `raw/` + Source-DB reichen, um in jedes andere System zu re-ingestieren.

### Nicht-Ziele

- Kein Multi-User, kein RBAC über die zwei Instanzen hinaus.
- Keine native iOS-App (PWA + Kurzbefehl genügen).
- Kein Vault-Sync aufs iPhone (der Vault bleibt auf dem Server).
- Kein Postgres (Abweichung von §6 des Architektur-Docs: ACL funktioniert out-of-the-box nur mit Kuzu + LanceDB; SQLite/Kuzu/LanceDB sind alle file-based und reichen für Single-User).

## 4. Technische Architektur (entschieden)

| Komponente | Technik |
|---|---|
| Sprache | Python 3.12 (Cognee ist Python-SDK; `DataPoint`/Provenance nur via SDK; yt-dlp/youtube-transcript-api) |
| Cognee | SDK in-process, **zwei Instanzen = zwei Worker-Prozesse** mit getrennten Env-Files und Datenpfaden |
| Stores | Cognee-Defaults: SQLite (relational), Kuzu (Graph), LanceDB (Vektor) — pro Instanz eigene Verzeichnisse |
| Embeddings | Ollama `nomic-embed-text` (768 dim) für **beide** Instanzen. ⚠️ Nach Ingest-Start nicht mehr wechselbar ohne Re-Ingest |
| Job-Queue | SQLite-Tabelle (WAL) pro Instanz |
| Gateway | FastAPI: `POST /ingest`, `POST /query` mit Vault-Routing |
| Frontend | Astro-PWA (Ingest-Form, Chat, Vault-Switcher) |
| Netz | Tailscale (kein offener Port) |
| Agent | `cognee-mcp` pro Instanz, Transport stdio/HTTP (SSE meiden, Bug cognee#2131) |

**Cross-Vault-Suche:** nur innerhalb der Business-Instanz (`datasets=["business-ki","business-mwe"]`, durch ACL erzwungen). Privat ist per Prozessgrenze nie Teil eines Cross-Vault-Scopes — härter als jedes Flag.

## 5. Phasen & Gates

- **Phase 0 — Validierung:** Privat-Instanz mit Ollama, ~10 echte Quellen, 5–10 **vorab festgeschriebene** Fragen, Blind-Vergleich gegen bestehendes json-GraphRAG. **Gate:** Cognee gewinnt den Blind-Vergleich mehrheitlich, und Ingest-Dauer/Quelle ist auf der Hardware tragbar. Wenn nein → Stack-Entscheidung falsifiziert, Stopp.
  - Zusätzlich verifizieren: Dataset-Scoping mit `ENABLE_BACKEND_ACCESS_CONTROL=true` funktioniert real (Bleed-Test wegen cognee#1023); Embedding-Qualität von `nomic-embed-text` reicht.
- **Phase 1 — Ingestion-Worker:** Queue, Fetcher (YouTube/Web/Snippet/Datei), Provenance, Rohschicht, CLI, Env-Guards. → Detailplan: [2026-06-12-kb-implementierungsplan.md](2026-06-12-kb-implementierungsplan.md)
- **Phase 2 — Gateway + PWA + iOS:** FastAPI-Endpoints, Astro-PWA, Kurzbefehl, Tailscale. (Eigener Plan nach Phase 1.)
- **Phase 3 — Agent-Integration + Migration:** MCP-Registrierung, bestehende Markdown-KB in Business-Vault migrieren. (Eigener Plan.)

## 6. Erfolgskriterien

1. iOS-Teilen → Antwort „ingested" in < 5 s (Verarbeitung asynchron).
2. Jede Antwort im Chat/Agent ist in ≤ 2 Schritten zur Originalquelle rückverfolgbar.
3. Kein einziger Cloud-Call mit Privat-Inhalten (verifizierbar via Env-Guard + Netzwerk-Log-Stichprobe).
4. Obsidian-Git-Sync auf iOS ist ersatzlos abgeschaltet.

## 7. Risiken

| Risiko | Gegenmaßnahme |
|---|---|
| Cognee-Synthese schlägt json-GraphRAG nicht | Phase-0-Gate mit Blind-Vergleich, vorab fixierte Fragen |
| Dataset-Bleed trotz ACL (cognee#1023) | expliziter Bleed-Test in Phase 0 |
| Ollama-cognify zu langsam | in Phase 0 messen; Fallback: kleineres Extraktionsmodell oder Business-LLM auch für Privat-*Ingest* bewusst entscheiden |
| Transkript nicht verfügbar (YouTube) | Job markiert `failed` mit Grund; manueller Fallback (yt-dlp Audio + lokale Transkription) als späteres Feature |
| Embedding-Modell-Reue | Entscheidung explizit in Phase 0 testen, danach eingefroren |
| Cognee-API-Drift (junge Library) | Version pinnen; Adapter-Schicht `cognee_io.py` kapselt alle SDK-Calls |
