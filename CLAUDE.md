# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Was das ist

Persönliches Multi-Vault-Knowledge-System auf Basis von **Cognee 1.2.2**. Zwei
strikt getrennte Verarbeitungs-Instanzen ("Walls") mit eigenem Prozess und
eigenem LLM, mehrere thematische Vaults darin, serielle Ingest-Queue (SQLite).
Datenfluss: Input → klassifizieren → Queue → Worker fetcht & schreibt Rohschicht
→ cognee `add` + `cognify` → später `query` (GRAPH_COMPLETION). Detaildokumente
in `docs/` (PRD, Architektur, Phasenpläne).

## Befehle

```sh
uv sync                                    # Deps installieren
uv run pytest                              # alle Tests
uv run pytest tests/test_worker.py         # eine Datei
uv run pytest tests/test_worker.py::test_process_one_snippet_full_chain  # ein Test
uv run pytest -k worker                    # nach Namen filtern

uv run kb ingest <vault> <url|text|datei>  # in Queue legen
uv run kb import <vault> <dir|datei>       # .md/.txt-Bestand migrieren (--dry-run, --node-set)
uv run kb worker <instance>                # Standalone-Worker (local | cloud)
uv run kb query <vault> "Frage"            # direkter Query (lädt cognee)
uv run kb serve-instance <instance>        # Instance Service (127.0.0.1:8801/8802)
uv run kb serve-gateway                    # Gateway + PWA (0.0.0.0:8800)
uv run kb serve-mcp <instance>             # stdio-MCP-Server der Instanz

cd web && npm install && npm run build     # PWA bauen → web/dist/ (vom Gateway ausgeliefert)
cd web && npm test                    # PWA-Tests (node --test)
```

Es gibt keine Lint-Konfiguration und keine `[tool.pytest]`-Section; pytest läuft
mit Defaults (`pytest-asyncio` ist installiert, Async-Tests werden manuell mit
`asyncio.run`/`AsyncMock` gefahren — kein `asyncio_mode=auto`).

## Architektur — die tragenden Konzepte

**`kb.toml` ist die Single Source of Truth für die Topologie.** `config.py` lädt
sie beim Import und leitet alles per Konvention aus den Namen ab — Umbenennen
oder Hinzufügen von Walls/Vaults passiert **nur hier**, nie im Code:
- Wall `<name>` → Env-File `.env.<name>`, Datenpfad `var/<name>`, Port aus TOML.
- Vault `<name>` → Cognee-Dataset `<name>`, Rohschicht `raw/<name>`.
- `INSTANCES`/`VAULTS` sind beim Import gebaute, frozen Dicts. Tests, die andere
  Vaults brauchen, konstruieren `Vault(...)`/`Instance(...)` direkt.

**Die Privacy-Wand ist das zentrale Sicherheitskonzept.** Wall-`mode` bestimmt
die erlaubten LLM-Provider (`MODE_PROVIDERS` in `config.py`):
`local` → nur `ollama` (Inhalte verlassen den Rechner nie), `cloud` → `custom`
(OpenAI-kompatibler Cloud-Endpoint). `guard.assert_instance_env` erzwingt das vor
**jedem** cognee-Call und prüft zusätzlich `EMBEDDING_PROVIDER == fastembed` hart
— ein Embedding-Wechsel würde still alle bestehenden Vektoren invalidieren.

**Nur `cognee_io.py` importiert cognee.** Alle anderen Module bleiben cognee-frei.
Gateway, MCP-Server und Worker-Schleife des Instance Service erreichen cognee nur
indirekt (HTTP-Proxy bzw. Queue). cognee-Imports sind überall **lazy** (erst nach
`load_instance_env`, weil cognee Env beim Import liest). `cognee_io` ist gegen
1.2.2 verifiziert; `_render` behandelt sowohl `SearchResult`-Objekte als auch
dicts (ACL-Modus).

**Ein Event-Loop pro Instanz — niemals einer pro Job.** cognee cachet
loop-gebundene Ressourcen; ein frischer Loop pro Frage/Job löst
`attached to a different loop`-Fehler aus. Deshalb:
- `worker.run_forever` baut **einen** Loop und fährt alle Jobs darüber.
- Der Instance Service läuft den Worker als asyncio-Background-Task im **selben**
  Loop wie die FastAPI-Handler (kein Thread, kein neuer Loop).
- `cli.eval` beantwortet alle Fragen sequenziell im selben Loop (`_answer_all`).

**Cognee/Ladybug bleibt in `kb` single-writer.** Genau ein Worker pro Instanz.
Deshalb gibt es **keinen** offiziellen `cognee-mcp`; stattdessen proxyt/enqueued
der eigene dünne `mcp_server.py` wie das Gateway. `recover_stale()` setzt
verwaiste `running`-Jobs gefahrlos zurück, weil es nur einen Schreiber gibt.

**SQLite-Connections sind thread-/loop-gebunden.** Gateway und MCP-Server bauen
pro Request eine frische `JobQueue`/`SourceStore`. Queue läuft im WAL-Modus;
`claim_next` nutzt atomares `UPDATE ... RETURNING`.

## Prozess-Topologie (Phase 2/3)

```
PWA / iOS-Shortcut / Agent
        │ Bearer-Token (KB_API_TOKEN)
        ▼
   Gateway :8800 (0.0.0.0, cognee-frei)
   ├─ POST /api/ingest  → schreibt direkt in queue.db
   ├─ POST /api/query   → httpx-Proxy an Instance Service
   └─ liefert PWA aus web/dist/
        │ 127.0.0.1 (kein Token)
        ▼
   Instance Service :8801/:8802  ── Worker-Task (selber Loop) ──> cognee
        ▲
        │ httpx
   MCP-Server (stdio, pro Instanz, cognee-frei)
```

MCP-Tools werden dynamisch aus den Vaults der Instanz registriert
(`search_<vault>`, bei >1 Vault zusätzlich `search_all`, je `ingest`+`job_status`).
**Isolations-Regel:** kb-MCPs nie `--scope user` registrieren — local-MCP nur in
private, cloud-MCP nur in Business-Projekte (`ops/mcp-setup.md`). Sonst bricht die
Vault-Trennung.

## Env-Files & Pfade

Pro Wall ein gitignored `.env.<name>` (`.env.local`, `.env.cloud`) mit
`LLM_PROVIDER`/`EMBEDDING_PROVIDER` etc.; `.env.gateway` enthält nur
`KB_API_TOKEN`. `load_instance_env` setzt zusätzlich die cognee-Verzeichnisse
(`DATA_ROOT_DIRECTORY` etc.) auf `var/<name>/cognee_*` — bewusst relativ statt
absolut, damit ein VPS-Umzug ohne Env-Edits funktioniert. Alle Laufzeitdaten
(Queue-DB, Source-DB, cognee-Roots, Logs) liegen unter `var/<instance>/` und sind
gitignored. `raw/<vault>/` hält die versionierbare Markdown-Rohschicht mit
YAML-Frontmatter (`sources.py` quotet Strings mit Doppelpunkt bewusst — nicht zu
`safe_dump` vereinfachen).

> **Hinweis:** Walls heißen `local`/`cloud`; `kb.toml` und `config.py` sind
> maßgeblich für die Topologie. README und Code nutzen dieselben Namen.

## Konventionen

- Kommentare und Doc-Strings auf Deutsch, knapp, erklären das **Warum** (oft
  cognee-/Ladybug-/asyncio-Fallstricke). Dieser Stil ist beim Anfassen beizubehalten.
- Dependencies sind teils hart gepinnt mit Begründung im Kommentar
  (`cognee==1.2.2`; `fastembed==0.6.0` wegen Pooling-Wechsel) — nicht ohne Grund anheben.
- Git: Commit-Messages auf Englisch, im Stil der bestehenden Historie.
