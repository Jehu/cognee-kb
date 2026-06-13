# MCP-Setup — kb-Vaults in Claude Code

Pro Instanz läuft ein dünner stdio-MCP-Server (`kb serve-mcp <instance>`), der
OHNE cognee-Import auskommt: Queries proxyt er per httpx an den Instance Service,
Ingest schreibt er direkt in die SQLite-Queue. **Voraussetzung ist daher ein
laufender Instance Service** (local :8801 / cloud :8802) — sonst antworten
die `search_*`-Tools mit „Instance Service nicht erreichbar".

```sh
uv run kb serve-instance local     # bzw. cloud — muss laufen, bevor der MCP nützt
```

## Tools pro Instanz

### local

| Tool | Was es tut |
|---|---|
| `search_privat(question)` | Frage an den Vault `privat` (GRAPH_COMPLETION). |
| `ingest(vault, content, node_set?)` | Inhalt (URL/Text/YouTube) in die Queue eines Instanz-Vaults legen. |
| `job_status(vault, job_id)` | Status/Fehler eines Queue-Jobs nachschlagen. |

### cloud

| Tool | Was es tut |
|---|---|
| `search_business_ki(question)` | Frage an den Vault `business-ki`. |
| `search_business_mwe(question)` | Frage an den Vault `business-mwe`. |
| `search_all(question)` | Frage über alle Business-Vaults gleichzeitig (ACL-scoped). |
| `ingest(vault, content, node_set?)` | Inhalt in die Queue eines Business-Vaults legen. |
| `job_status(vault, job_id)` | Status/Fehler eines Queue-Jobs nachschlagen. |

`ingest` und `job_status` akzeptieren nur Vaults der jeweiligen Instanz; fremde
Vault-Namen werden mit einer Fehlermeldung abgewiesen.

## Registrierung — zwei Wege

Beide Wege registrieren **project-scope**: Die Konfiguration landet in der
`.mcp.json` im Projekt-Root und wird mit dem Repo geteilt.

### Weg A — Template kopieren

Template aus diesem Repo ins Root des Zielprojekts kopieren und in `.mcp.json`
umbenennen:

```sh
# in einem privaten Projekt:
cp /Users/marco/coding/kb/ops/mcp/local.mcp.json /pfad/zum/privaten/projekt/.mcp.json

# in einem Business-Projekt:
cp /Users/marco/coding/kb/ops/mcp/cloud.mcp.json /pfad/zum/business/projekt/.mcp.json
```

Existiert im Zielprojekt bereits eine `.mcp.json`, den `mcpServers`-Eintrag von
Hand einfügen statt die Datei zu überschreiben.

> **Pfad-Hinweis (VPS-Umzug):** Die Templates setzen `cwd` auf den absoluten Pfad
> `/Users/marco/coding/kb`. JSON erlaubt keine Kommentare, daher steht der Hinweis
> nur hier: Zieht das kb-Projekt auf den VPS um, muss `cwd` in der kopierten
> `.mcp.json` jedes Projekts auf den neuen Pfad angepasst werden. Der
> `KB_MCP_INSTANCE`-Eintrag im `env`-Block ist redundant (die Instanz steckt
> bereits in den `args`) und schadet nicht.

### Weg B — `claude mcp add`

```sh
# Business-Projekt:
claude mcp add --scope project --transport stdio kb-cloud -- uv run kb serve-mcp cloud

# Privates Projekt:
claude mcp add --scope project --transport stdio kb-local -- uv run kb serve-mcp local
```

Das schreibt denselben Eintrag in die `.mcp.json` des aktuellen Projekts. `cwd`
ergibt sich hier aus dem Projektverzeichnis — `uv run` findet das kb-Projekt nur,
wenn es von dort erreichbar ist; andernfalls Weg A mit explizitem `cwd` nutzen.

## ⚠️ Isolation — Privacy-Wand auf MCP-Ebene

**Der local-MCP darf NIEMALS user-scope (global) registriert werden.**

User-scope (`--scope user`) lädt einen MCP-Server in **jedem** Projekt auf der
Maschine. Würde der local-MCP so registriert, landeten private Inhalte in
Business- und fremden Kontexten — die Vault-Trennung wäre durchbrochen.

Regeln:

- **local-MCP** nur in die `.mcp.json` **privater** Projekte.
- **cloud-MCP** nur in die `.mcp.json` von **Business**-Projekten.
- **Nie `--scope user`** für einen kb-MCP. Immer `--scope project`.

project-scope verlangt beim ersten Start eine **einmalige Approval pro Projekt**
(Claude Code fragt, ob die projektlokalen MCP-Server vertraut werden). Diese
Entscheidungen lassen sich zurücksetzen:

```sh
claude mcp reset-project-choices
```

## Verifikation

Registrierte Server auflisten:

```sh
claude mcp list
```

In einer laufenden Claude-Code-Session zeigt das interaktive Panel `/mcp` die
verbundenen Server und ihre Tools an (interaktiver Slash-Befehl — nur in der
Session aufrufbar, nicht skriptbar).

Funktionstest: ein search-Tool aufrufen (z. B. `search_business_ki` mit einer
Testfrage). Voraussetzung bleibt der laufende Instance Service der Instanz —
ohne ihn meldet das Tool „Instance Service nicht erreichbar".
