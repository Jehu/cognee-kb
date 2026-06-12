# Modeltest: openrouter/anthropic/claude-haiku-4.5

Dataset: `mt-haiku`

**Ingest** (2 Quellen): 60 s

## Was ist das Agent-Skills-Pattern und wie ist ein Skill strukturell aufgebaut?

_(4.9 s)_

Das Agent-Skills-Pattern ist eine strukturierte Methodik für wiederholbare Prozesse, die als Ordner mit einer Skill-Hauptdatei und Referenzdateien verpackt werden. Agenten laden einen Skill und haben damit alles Notwendige für spezifische Workflows – ohne Ad-hoc-Instruktionen.

**Struktureller Aufbau eines Skills:**

```
skills/
  <skill-name>/
    SKILL.md              # Hauptprozess + Instruktionen
    radar_sources.xml     # Konfigurationsdateien (z.B. RSS-Feed-URLs)
    training.md           # Personalisierte Inhalte (Themen, Ton)
    voice.md              # Schreibstil-Guidelines
```

**Kernmerkmale:**
- **SKILL.md**: Enthält sequenzielle Prozessschritte (Fetch → Filter → Format → Output → Notify)
- **Referenzdateien**: Lagern Konfiguration und Personalisierung aus der Skill-Logik aus
- **Generisch vs. personalisiert**: Skills bleiben generisch, Referenzdateien sind personalisiert
- **Output-Format**: Klar definiert (Dateiname-Schema, Markdown-Struktur, Benachrichtigungskanal)
- **Automation**: Cron-Scheduling für automatische Ausführung möglich

## Wie hängen Agent-Autonomie und Enforcement über Hooks zusammen — wo braucht es harte technische Grenzen statt Vertrauen in den Agenten?

_(7.2 s)_

Agent-Autonomie und Hook-basiertes Enforcement sind eng verknüpft: Markdown-Regeln allein sind unzureichend (LLMs vergessen sie zu 20-40%). Harte technische Grenzen werden an **Action Boundaries** notwendig — den Momenten, wo Agenten vom Denken zum Handeln wechseln.

**Wo Vertrauen nicht reicht:**

1. **Security**: Credential-Leaks, Injection-Attacks, Prompt-Injection — erfordern präventive Hook-Blöcke (exit 2), nicht nachträgliche Audits
2. **Compliance**: Attribution-Pflicht, strukturelle Vorgaben (UEAH-Tags) — Agenten unterschlagen diese konsistent, brauchen erzwungene Validierung
3. **Orchestration**: Recursive Spirals, Context-Drift — automatische Erkennung und Hard-Termination statt manualer Intervention

**Das 3-Layer-System setzt technische Grenzen:**
- **Layer 1 (Hooks)**: Plattformspezifische Trigger an kritischen Punkten
- **Layer 2 (Validators)**: Deterministisches Python-Regelchecking
- **Layer 3 (Guard YAMLs)**: Konfigurierbare Policies ohne Code-Änderung

**Rollout ohne totale Kontrolle**: `monitor` → `warn` → `enforce` — graduelles Einführen statt Alles-oder-Nichts. Der Warn-Payload wird vom Agenten als Prompt aufgenommen (RL-Effekt), führt zu Selbstkorrektur.

**Resultat**: 100% Attribution-Compliance, 0 Credential-Leaks, automatische Spiral-Termination. Autonomie bleibt erhalten, aber innerhalb verifizierbarer Grenzen.
