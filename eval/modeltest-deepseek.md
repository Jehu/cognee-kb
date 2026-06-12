# Modeltest: openrouter/deepseek/deepseek-v4-flash

Dataset: `mt-deepseek`

**Ingest** (2 Quellen): 123 s

## Was ist das Agent-Skills-Pattern und wie ist ein Skill strukturell aufgebaut?

_(3.7 s)_

Das Agent-Skills-Pattern definiert strukturierte, wiederholbare Prozesse, die als Ordner mit einer Hauptdatei (SKILL.md) und optionalen Referenzdateien verpackt werden. Ein Skill ist wie folgt aufgebaut: skills/<name>/SKILL.md (Hauptprozess + Instruktionen), plus Referenzdateien wie radar_sources.xml, training.md, voice.md zur Auslagerung personalisierter Konfiguration.

## Wie hängen Agent-Autonomie und Enforcement über Hooks zusammen — wo braucht es harte technische Grenzen statt Vertrauen in den Agenten?

_(21.8 s)_

Der Kern des Zusammenhangs: **Agent-Autonomie bedeutet, dass der LLM entscheiden kann, was und wie er tut, während Enforcement über Hooks** (Layer 1 — WHEN) **harte technische Grenzen an den Action Boundaries setzt.** Hooks unterbrechen den Agenten genau dort, wo er vom Denken zum Handeln wechselt (z. B. Tool-Ausführung, Datei-Edit). An dieser Stelle können **Validatoren** (Layer 2 — HOW) deterministisch prüfen, ob eine Aktion erlaubt ist, und durch **Guard YAMLs** (Layer 3 — WHAT) konfigurierbare Regeln durchsetzen.

**Wo braucht es harte technische Grenzen statt Vertrauen?** Überall dort, wo LLMs inhärent unzuverlässig sind:
- **Context-Compaction & Attention-Drift** (LLMs vergessen Markdown-Regeln um 20–40 %)
- **Security**: Injection, Credential-Leaks, Unicode-Angriffe — hier darf man sich nicht auf LLM-Judgment verlassen
- **Orchestration**: Anti-Spiral-Erkennung, Handoff-Validierung — Endlosschleifen verhindern
- **Compliance**: Strukturvorgaben wie UEAH-Attribution — durchsetzbar, nicht nur erinnerbar

Das System implementiert drei Phasen: `monitor → warn → enforce`. Erst ab `enforce` wird ein **Hard Block** (exit 2) gesetzt. Der Warn-Modus nutzt dagegen den RL-Catnip-Effekt: Der Agent erhält die Warnung als Prompt und kann sich selbst korrigieren — eine **vertrauensbasierte** Phase vor der harten Grenze. Diese Kombination aus graduellem Enforcement und Hook-basierter Unterbrechung ist der Schlüssel.
