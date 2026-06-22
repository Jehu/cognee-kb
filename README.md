# kb — Multi-Vault Knowledge System

Persönliches Knowledge System auf Basis von Cognee. Zwei Instanzen ("Walls"):
`local` (lokal via Ollama, Inhalte verlassen den Rechner nie) und `cloud`
(Cloud-LLM via OpenRouter/DeepSeek). Vier Vaults — `privat` (Wall `local`),
`allgemein`, `business-ki` und `business-mwe` (Wall `cloud`) — plus serielle
Ingest-Queue (SQLite). Topologie ist in `kb.toml` definiert (Single Source of Truth).
Details: `docs/` (PRD, Architektur, Phasenpläne).

## Setup

```sh
uv sync
cp .env.local.template .env.local      # anpassen (Ollama)
cp .env.cloud.template .env.cloud      # API-Key eintragen (Cloud-LLM)
```

## Tests

```sh
uv run pytest              # Python-Backend
cd web && npm test         # PWA (node --test)
make test                  # beides zusammen
```

## CLI

```sh
uv run kb ingest <vault> <url-oder-text-oder-datei>   # in Queue legen
uv run kb import <vault> <dir-oder-datei>             # .md/.txt-Bestand migrieren (--exclude, --only-newer-than, --limit, --dry-run)
uv run kb worker <instance>                           # Queue abarbeiten (local | cloud)
uv run kb query <vault> "Frage"                       # GRAPH_COMPLETION
```

## Phase 2 — Gateway + PWA

Architektur: Gateway (Port 8800, Bearer-Token, ohne cognee) nimmt Ingest
entgegen und proxyt Queries an die Instance Services local :8801 /
cloud :8802 (nur 127.0.0.1).

Token-Setup (einmalig):

```sh
cp .env.gateway.template .env.gateway   # KB_API_TOKEN setzen (.env.gateway ist gitignored)
```

PWA bauen (liefert das Gateway aus `web/dist/` aus):

```sh
cd web && npm install && npm run build
```

In der PWA wird der Bearer-Token lokal in den Einstellungen hinterlegt. Ohne
gültigen Token lädt die App keine Vault-Liste aus dem Gateway und sperrt
Vault-Auswahl sowie Ingest-/Chat-Aktionen; die Einstellungen zeigen zusätzlich
Gateway-, Instanz- und Authentifizierungsstatus. Vault-Auswahlen zeigen die
zugehörige Wall (`local`/`cloud`) gruppiert und im Optionstext an.
Der Ingest-Screen ist als schneller Capture-Flow aufgebaut (Metadaten einklappbar,
Node-Set-Autosuggest aus bestehenden Jobs, Job-Fortschritt sichtbar); der Chat
zeigt im leeren Zustand Beispiel-Fragen und als verwandte Quelle nur den besten
Chunk-Treffer zur Frage. Die Einstellungen bieten Token-Anzeige sowie einen
Verbindungstest.

Starten (ein Befehl, idempotent):

```sh
uv run kb up                    # alle Dienste detached (local + cloud + gateway)
uv run kb up local              # nur eine Wall oder 'gateway'
uv run kb status                # Lauf-Status aller Dienste (Port + PID)
uv run kb logs gateway          # Live-Logs (tail -f), Strg-C bricht ab
uv run kb down                  # alle stoppen
```

Dienste laufen detached (überleben das Terminal). Logs landen in
`var/gateway.log` bzw. `var/<wall>/logs/serve.log`. Nach `kb.toml`-Änderungen
greifen diese erst nach Neustart der betroffenen Prozesse: `kb restart all`.

Zugriff von unterwegs über Tailscale (kein offener Port nötig);
iOS-Teilen-Sheet → Knowledge Base: siehe `ops/ios-kurzbefehl.md`.

## Topologie ändern (kb.toml)

`kb.toml` ist die Single Source of Truth (Walls, Vaults, Ports). `config.py` lädt
sie **beim Import** und friert sie als Schnappschuss ein — Änderungen greifen
deshalb erst nach Neustart der betroffenen Prozesse:

- **CLI** (`kb ingest/query/...`) liest `kb.toml` bei jedem Aufruf frisch → kein Neustart nötig.
- **Server** (Gateway, Instance Services, MCP) halten den Schnappschuss → Neustart nötig.

Helfer dafür (beendet den Prozess auf dem Port des Ziels sauber und startet ihn
detached neu — der Port ist der eindeutige Anker, kein Namens-Matching):

```sh
uv run kb restart local        # Instance Service einer Wall (local | cloud)
uv run kb restart gateway      # das Gateway
uv run kb restart all          # alle Instances + Gateway
```

Nach Änderungsart:

- **Vault zu bestehender Wall:** `kb restart <wall>` **und** `kb restart gateway`.
  `raw/<name>/` und das cognee-Dataset entstehen automatisch beim ersten Ingest;
  die PWA-Auswahl füllt sich aus `/api/vaults` (kein `npm run build` nötig).
- **Neue Wall:** zuerst `.env.<name>` anlegen (sonst scheitert der Start am Guard),
  dann `kb restart all`.
- **Port geändert:** betroffene Instance **und** Gateway neu starten.

Fallstricke: `kb.toml` ist validiert — bei kaputtem TOML, doppelten/Gateway-
kollidierenden Ports oder unbekannter Wall startet der Server gar nicht (lauter
`ConfigError`, kein stiller Halbzustand). Und **Umbenennen ≠ Daten mitnehmen**:
Dataset-Name und Pfade werden aus dem Namen abgeleitet, ein umbenannter Vault
startet leer (die alten cognee-Daten bleiben unter dem alten Namen liegen).

## Phase 3 — MCP (Agent-Zugriff)

Pro Instanz ein eigener dünner stdio-MCP-Server (`kb/mcp_server.py`) statt des
offiziellen `cognee-mcp`: Letzterer öffnet eine eigene Kuzu-RW-Instanz, und Kuzu
ist strikt single-writer — neben dem laufenden Instance Service führt das zum
Lock-Crash oder zu divergierenden Daten. Der eigene Server bleibt cognee-frei,
proxyt Queries per httpx an den Instance Service und schreibt Ingest direkt in
die Queue. Tools werden dynamisch aus den Vaults der Instanz registriert
(local: `search_privat`; cloud: `search_allgemein`, `search_business_ki`,
`search_business_mwe`, `search_all`; je `ingest` + `job_status`).

```sh
uv run kb serve-mcp local     # bzw. cloud — Instance Service muss laufen
```

Registrierung in Claude Code (project-scope, Isolations-Regeln, Verifikation):
siehe `ops/mcp-setup.md`. Kopiervorlagen: `ops/mcp/local.mcp.json` und
`ops/mcp/cloud.mcp.json`.

## Phase 4 — Docker (Deployment)

Ein-Container-Setup: `kb serve` startet alle Instance Services + Gateway als
eigene Subprozesse im Vordergrund (PID 1 = `dumb-init`, leitet SIGTERM weiter).
`kb.toml`, `.env.*` und die Daten-Volumes werden gemountet — ein
Topologie- oder Token-Wechsel braucht nur `docker compose restart`, kein Rebuild.

```sh
# .env.* aus Templates anlegen (wie lokal), dann:
docker compose up -d --build     # Build + Start
docker compose logs -f           # Live-Logs aller Dienste
docker compose restart           # kb.toml-Änderung greift nach Restart
docker compose down              # Stop (Daten-Volumes bleiben erhalten)
```

Port 8800 (Gateway) wird gepublished, die Instance Services bleiben intern.
Der Healthcheck (`/api/health`) wird von Docker automatisch überwacht.

Hinweis `local`-Wall: Ollama läuft nicht im Container. Auf dem VPS nur die
`cloud`-Walls in `kb.toml` definieren (oder Ollama zusätzlich als Service
 starten und `LLM_ENDPOINT` auf dessen Adresse setzen).
