# AGENTS.md

Lies die `CLAUDE.md`, falls noch nicht geschehen.

## README aktuell halten

Die `README.md` muss **immer** auf dem neuesten Stand gehalten werden. Sobald
sich ein Feature ändert oder ein neues hinzukommt, ist die `README.md` im selben
Arbeitsschritt mit anzupassen — nicht später, nicht „auf Zuruf".

Konkret aktualisieren bei:

- neuen oder geänderten CLI-Befehlen / `kb`-Subcommands,
- neuen oder geänderten Diensten (Gateway, Instance Service, MCP-Server),
- geänderter Topologie (Walls/Vaults in `kb.toml`), Ports oder Env-Files,
- neuen oder geänderten Setup-/Build-Schritten,
- jeder Änderung am Datenfluss oder an der Architektur, die ein Nutzer kennen muss.

Vor dem Abschluss einer Aufgabe prüfen: Stimmt die `README.md` noch mit dem
tatsächlichen Verhalten überein? Falsche Namen, veraltete Befehle und nicht mehr
existierende Schritte aktiv korrigieren.
