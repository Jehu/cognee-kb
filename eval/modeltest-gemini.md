# Modeltest: openrouter/google/gemini-3-flash-preview

Dataset: `mt-gemini`

**Ingest** (2 Quellen): 39 s

## Was ist das Agent-Skills-Pattern und wie ist ein Skill strukturell aufgebaut?

_(5.7 s)_

Das Agent-Skills-Pattern ist ein Framework für modulare, wiederholbare AI-Automatisierungs-Workflows, bei denen Prozesse als Ordner verpackt werden. Ein Skill besteht strukturell aus einer Hauptdatei (SKILL.md) für Instruktionen und Logik sowie personalisierten Referenzdateien (z. B. training.md, voice.md, Datenquellen), um die Skill-Logik von der Konfiguration zu trennen.

## Wie hängen Agent-Autonomie und Enforcement über Hooks zusammen — wo braucht es harte technische Grenzen statt Vertrauen in den Agenten?

_(2.3 s)_

Agenten-Autonomie endet an 'Action Boundaries' (Uebergang vom Denken zum Handeln), an denen Hooks deterministisches Enforcement ermöglichen. Harte technische Grenzen (Hard Blocks via Exit-Code 2) sind dort notwendig, wo Markdown-Regeln versagen, da LLMs diese durch Context-Compaction und Attention-Drift um 20-40 % ignorieren. Dies betrifft besonders Compliance, Security (Injection/Credential-Exposures) und die Verhinderung von Endlosschleifen (Anti-Spiral-Detection).
