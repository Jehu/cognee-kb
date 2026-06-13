# kb — Multi-Vault Knowledge System

Persönliches Knowledge System auf Basis von Cognee: zwei Instanzen
(privat = lokal via Ollama, business = OpenRouter), drei Vaults
(privat, business-ki, business-mwe), serielle Ingest-Queue (SQLite).
Details: `docs/` (PRD, Architektur, Phasenpläne).

## Setup

```sh
uv sync
cp .env.privat.template .env.privat      # anpassen
cp .env.business.template .env.business  # API-Key eintragen
```

## CLI

```sh
uv run kb ingest <vault> <url-oder-text-oder-datei>   # in Queue legen
uv run kb worker <instanz>                            # Queue abarbeiten
uv run kb query <vault> "Frage"                       # GRAPH_COMPLETION
```

## Phase 2 — Gateway + PWA

Architektur: Gateway (Port 8800, Bearer-Token, ohne cognee) nimmt Ingest
entgegen und proxyt Queries an die Instance Services privat :8801 /
business :8802 (nur 127.0.0.1).

Token-Setup (einmalig):

```sh
cp .env.gateway.template .env.gateway   # KB_API_TOKEN setzen (.env.gateway ist gitignored)
```

PWA bauen (liefert das Gateway aus `web/dist/` aus):

```sh
cd web && npm install && npm run build
```

Starten (drei Terminals):

```sh
uv run kb serve-instance privat
uv run kb serve-instance business
uv run kb serve-gateway
```

Zugriff von unterwegs über Tailscale (kein offener Port nötig);
iOS-Teilen-Sheet → Knowledge Base: siehe `ops/ios-kurzbefehl.md`.

## Phase 3 — MCP (Agent-Zugriff)

Pro Instanz ein eigener dünner stdio-MCP-Server (`kb/mcp_server.py`) statt des
offiziellen `cognee-mcp`: Letzterer öffnet eine eigene Kuzu-RW-Instanz, und Kuzu
ist strikt single-writer — neben dem laufenden Instance Service führt das zum
Lock-Crash oder zu divergierenden Daten. Der eigene Server bleibt cognee-frei,
proxyt Queries per httpx an den Instance Service und schreibt Ingest direkt in
die Queue. Tools werden dynamisch aus den Vaults der Instanz registriert
(privat: `search_privat`; business: `search_business_ki`, `search_business_mwe`,
`search_all`; je `ingest` + `job_status`).

```sh
uv run kb serve-mcp privat     # bzw. business — Instance Service muss laufen
```

Registrierung in Claude Code (project-scope, Isolations-Regeln, Verifikation):
siehe `ops/mcp-setup.md`. Kopiervorlagen: `ops/mcp/privat.mcp.json` und
`ops/mcp/business.mcp.json`.
