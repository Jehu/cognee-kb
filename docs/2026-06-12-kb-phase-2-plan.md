# Phase 2 — Gateway + PWA + iOS-Ingest

Stand: 2026-06-12 · Voraussetzung: Phase-0-Gate bestanden (Cognee 6/8), Phase 1 implementiert.

## Architekturentscheidung

Cognee-Config ist prozess-global (lru_cache-Singleton) und Kuzu erlaubt nur einen
Read-Write-Prozess pro Datenbank-Verzeichnis. Daraus folgt:

1. **Instance Service** (einer pro Instanz, `kb/instance_service.py`): FastAPI-App auf
   localhost, lädt beim Start die Instanz-Env + Guard, startet die Worker-Loop als
   asyncio-Background-Task und beantwortet `/query` — **alles im selben Event-Loop**
   (cognee cachet loop-gebundene Ressourcen; zwei Loops in einem Prozess riskieren
   „attached to a different loop").
2. **Gateway** (`kb/gateway.py`): separater Prozess **ohne cognee-Import**. Ingest =
   direktes Enqueue in die SQLite-Queue (WAL ist prozessübergreifend sicher), Query =
   HTTP-Proxy an den zuständigen Instance Service. Liefert zusätzlich die PWA aus.
3. **PWA** (`web/`): Astro, statischer Build, kein Framework-Island nötig.
4. **Netz/Auth:** Tailscale (kein offener Port) + Bearer-Token `KB_API_TOKEN` am
   Gateway (Defense in Depth). Instance Services binden nur an 127.0.0.1 — kein Token.

```
iOS-Kurzbefehl ─┐
PWA (Browser) ──┼─► Gateway :8800 ──► enqueue → var/<instanz>/queue.db
Agent/CLI ──────┘        │
                         ├─► Proxy /query ─► privat   :8801 (127.0.0.1, Ollama+fastembed)
                         └─► Proxy /query ─► business :8802 (127.0.0.1, OpenRouter+fastembed)
```

## Ports (in `kb/config.py`)

| Dienst | Port | Bind |
|---|---|---|
| Gateway | 8800 | 0.0.0.0 (Tailscale schirmt ab) |
| Instance privat | 8801 | 127.0.0.1 |
| Instance business | 8802 | 127.0.0.1 |

## API-Kontrakt

### Gateway (öffentlich, Bearer `KB_API_TOKEN`)

| Endpoint | Request | Response |
|---|---|---|
| `POST /api/ingest` | `{"vault": str, "content": str, "node_set": str\|null}` | `202 {"job_id": int, "vault": str, "kind": str}` |
| `POST /api/query` | `{"vault": str, "question": str}` | `200 {"vault": str, "answer": str}` |
| `GET /api/jobs/{vault}/{job_id}` | — | `{"id", "status", "kind", "error", "created_at"}` |
| `GET /api/vaults` | — | `[{"name": str, "instance": str}]` |
| `GET /api/health` | — | `{"gateway": "ok", "instances": {name: "ok"\|"down"}}` |
| `GET /` | — | PWA (statisch aus `web/dist/`, falls vorhanden) |

Fehler: unbekannter Vault → 404, fehlendes/falsches Token → 401, Instance Service
nicht erreichbar → 502 mit klarer Meldung. Ingest klassifiziert via `kb.classify`
(wie CLI), **kein** Datei-Pfad-Zweig (HTTP-Clients schicken keinen lokalen Pfad).

### Instance Service (intern, nur 127.0.0.1)

| Endpoint | Request | Response |
|---|---|---|
| `POST /query` | `{"question": str, "datasets": [str]}` | `{"answer": str}` |
| `GET /health` | — | `{"instance": str, "queue": {"pending": int, "running": int, "done": int, "failed": int}}` |

## Tasks

- **T1 Worker-Async-Refactor** (`kb/worker.py`): Kernlogik nach
  `async def process_one_async()` heben (`_fetch` via `asyncio.to_thread`,
  `await cognee_io.ingest`). `process_one`/`run_forever` bleiben als sync-Wrapper
  (CLI-kompatibel). Neu: `async def run_forever_async()` für den Instance Service
  (ohne Env-Load — macht der Service beim Start).
- **T2 Instance Service** (`kb/instance_service.py`): App-Factory, Lifespan lädt Env
  + `guard.assert_instance_env`, `recover_stale()`, startet Worker-Task; `/query`,
  `/health`. Hängt an T1.
- **T3 Gateway** (`kb/gateway.py`): Auth, Enqueue, Proxy (httpx), Static-Mount.
  `JobQueue` pro Request instanziieren (sqlite3-Thread-Bindung). `queue.py` bekommt
  `info(job_id)`. `queue.py::status()` bleibt unangetastet.
- **T4 PWA** (`web/`): Astro. Seiten: Ingest-Form (Vault-Switcher, URL/Text,
  node_set optional), Chat (Frage → Antwort, Verlauf client-seitig), Einstellungen
  (Token, in localStorage). Manifest + minimaler Service Worker (installierbar).
  Build nach `web/dist/`.
- **T5 Wiring + Docs**: CLI-Befehle `kb serve-gateway` / `kb serve-instance <name>`
  (uvicorn), `KB_API_TOKEN` in `.env.gateway` + Template, README-Update,
  `ops/ios-kurzbefehl.md` (Schritt-für-Schritt: Teilen-Sheet → POST /api/ingest).
- **T6 Integration + Review**: Gesamttestlauf, Code-Review, Smoke-Test.

## Deployment-Hinweis

Lokal nur Tests (`uv run kb serve-…`). Produktiv-Deployment auf VPS am Projektende
(systemd statt launchd) — eigener Ops-Schritt, nicht Teil von Phase 2.
