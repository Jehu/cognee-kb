# Modeltest: openrouter/mistralai/mistral-small-2603

Dataset: `mt-mistral`

**Ingest** (2 Quellen): 107 s

## Was ist das Agent-Skills-Pattern und wie ist ein Skill strukturell aufgebaut?

_(2.4 s)_

Das **Agent-Skills-Pattern** ist ein strukturierter Ansatz, bei dem wiederverwendbare Prozesse als Pakete (Ordner) mit einer **Skill-Hauptdatei (`SKILL.md`)** und mehreren **Referenzdateien** implementiert werden. Ein Agent lädt diese Skills, um spezifische Workflows ohne ad-hoc-Anpassungen auszuführen. 

Ein **Skill** besteht aus:
1. **`SKILL.md`** (Hauptdatei) – Enthält den Hauptprozess, sequenzielle Schritte (z. B. Fetch → Filter → Format → Output → Notify) und Anweisungen.
2. **Referenzdateien** – Personalisierte Konfigurationsdateien (z. B. `radar_sources.xml`, `training.md`, `voice.md`), die Details aus der Hauptlogik ausgliedern, um die Skills generisch zu halten.

Beispielaufbau eines Skills im Ordner `skills/content-radar-scan/`:
- `SKILL.md` (Hauptprozess)
- `radar_sources.xml` (RSS-Feed-Konfiguration)
- `training.md` (Themen, Ton, Interessen)
- `voice.md` (Schreibstil-Richtlinien)

## Wie hängen Agent-Autonomie und Enforcement über Hooks zusammen — wo braucht es harte technische Grenzen statt Vertrauen in den Agenten?

_(2.0 s)_

Agent-Autonomie und Enforcement über Hooks hängen eng zusammen: Hooks fangen den Moment ab, wenn ein Agent von Planung zu Ausführung wechselt. Harte technische Grenzen sind nötig bei **Sicherheitskomponenten** (z. B. Credential-Scan, Injection-Prävention) und **Systemstabilität** (z. B. Anti-Spiral-Erkennung, Context-Drift-Monitoring), da hier ein Vertrauensfehler zu irreversiblen Schäden führen kann. Bei Komfort- oder Qualitätsregeln (z. B. CHANGELOG-Attribution) reichen initiale Warnungen über den Agenten, da er durch Prompt-Feedback korrigierbar ist.
