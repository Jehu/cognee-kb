# Phase 3 — MCP-Integration

> **Status 2026-06-14:** Umgesetzt. Offen aus der ursprünglichen Phase 3 bleibt
> nur die separate Migration bestehender Markdown-KB in den passenden Business-
> Vault; sie ist nicht Teil dieses MCP-Plans.

Stand: 2026-06-13 · Voraussetzung: Phase 1+2 fertig (Instance Services 8801/8802 laufen).
Scope dieses Plans: **nur MCP-Integration**. Migration der bestehenden Markdown-KB ist separat.

## Architekturentscheidung (recherche-belegt)

Der offizielle `cognee-mcp` öffnet im Default-Modus eine **eigene** Cognee-Instanz mit
eigenem Kuzu-RW-Lock. Kuzu ist strikt single-writer (`.lock`-File, kein RO-Bypass bei
gehaltenem Lock — kuzu#3295/#3872). Auf dasselbe DB-Verzeichnis wie ein laufender
Instance-Service zeigend → garantierter Lock-Crash; auf ein eigenes Verzeichnis zeigend →
dritter, divergierender Datenbestand. Beides unbrauchbar.

**Lösung: eigener dünner stdio-MCP-Server** (`kb/mcp_server.py`), analog zum Gateway:
- **kein cognee-Import** (Privacy-Wand bleibt; einziger Kuzu-RW-Prozess pro Vault bleibt
  der Instance-Service)
- **Query** → httpx an `http://127.0.0.1:{port}/query` des zuständigen Instance-Service
- **Ingest** → direkt in die SQLite-Queue (wie Gateway/CLI: `classify` + `JobQueue`),
  kein Token nötig (lokaler stdio-Prozess auf derselben Maschine)
- **Transport stdio** (umgeht SSE-Bug cognee#2131, simpelste Claude-Code-Integration)
- **ein Server-Prozess pro Instanz**, parametrisiert über Env `KB_MCP_INSTANCE`

```
Claude Code ──stdio──► kb serve-mcp local  ──httpx──► Instance local  :8801 ─► Kuzu (RW)
                                              └─enqueue─► var/local/queue.db
            ──stdio──► kb serve-mcp cloud  ──httpx──► Instance cloud  :8802 ─► Kuzu (RW)
                                              └─enqueue─► var/cloud/queue.db
```

## Tool-Design

Der Server liest `KB_MCP_INSTANCE`, ermittelt die Vaults dieser Instanz aus `config.VAULTS`
und registriert **dynamisch**:

| Tool | Instanz | Wirkung |
|---|---|---|
| `search_<vault>(question)` | je Vault der Instanz | POST `/query` {question, datasets:[dataset]} → Antwort-Text |
| `search_all(question)` | nur cloud (2+ Vaults) | datasets über alle Vaults der Instanz (ACL-scoped) |
| `ingest(vault, content, node_set?)` | je Instanz | classify + enqueue; `vault` auf Instanz-Vaults beschränkt (sonst Fehler) |
| `job_status(vault, job_id)` | je Instanz | Queue-Lookup → status/error |

Tool-Docstrings nennen den konkreten Vault-Namen, damit der Agent zielsicher routet.
Local-Instanz bekommt **kein** `search_all` (nur ein Vault) und ist per `.mcp.json`-Scoping
isoliert.

## Isolation (Privacy-Wand auf MCP-Ebene)

- **project-Scope `.mcp.json`**, niemals user-Scope. Der local-MCP wird nur im `.mcp.json`
  privater Projekte eingetragen, der cloud-MCP nur in Business-Projekten.
- Templates: `ops/mcp/local.mcp.json` + `ops/mcp/cloud.mcp.json` zum Kopieren.
- Doku stellt explizit klar: local-MCP nie user-scoped registrieren (würde überall laden).

## Tasks

- **T1 MCP-Server** (`kb/mcp_server.py` + CLI `kb serve-mcp <instance>`): FastMCP stdio,
  dynamische Tool-Registrierung aus `config`, httpx-Query, Queue-Ingest, kein cognee-Import.
  Dependency `mcp>=1.27`. Tests: Tool-Registrierung pro Instanz, Vault-Whitelist im ingest,
  Query-Proxy gemockt.
- **T2 Registrierung + Docs**: `ops/mcp/local.mcp.json` + `cloud.mcp.json`,
  `ops/mcp-setup.md` (claude mcp add / .mcp.json, project-scope-Begründung, Isolations-Warnung),
  README-Abschnitt „Phase 3 — MCP".
- **T3 Integration + Review + Smoke**: echter stdio-Handshake (`tools/list`), Code-Review,
  Gesamtsuite grün, Commit.

## Nicht in diesem Plan

Migration der kDrive-Markdown-KB in den Business-Vault — eigener Schritt nach der
MCP-Integration.
