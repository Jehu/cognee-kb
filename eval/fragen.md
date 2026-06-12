# Phase-0-Fragen (fixiert VOR dem ersten Cognee-Ingest — nicht mehr ändern!)

Bewertung: Blind-Vergleich. Antworten von Cognee (`uv run kb eval --vault business-ki`)
und json-GraphRAG ohne Label nebeneinander, pro Frage Gewinner markieren.
Cognee muss >= 5/8 gewinnen.

Quellen-Cluster: AI-Agenten (Skills, Memory, Autonomie, Hooks, PM-Automatisierung)
— siehe eval/quellen.txt. Fragen 1–3 sind Einzelquellen-Fragen, 4–8 verlangen
Synthese über mehrere Quellen.

- Was ist das Agent-Skills-Pattern und wie ist ein Skill strukturell aufgebaut?
- Welche Ansätze zur persistenten Speicherung von Agenten-Gedächtnis werden beschrieben und welche Trade-offs haben sie?
- Was empfiehlt Boris Cherny für den Claude-Code-Workflow?
- Wie hängen Agent-Autonomie und Enforcement über Hooks zusammen — wo braucht es harte technische Grenzen statt Vertrauen in den Agenten?
- Welche Rolle spielen Skills, Memory und Hooks im Zusammenspiel, wenn ein Agenten-System sich selbst verbessern soll?
- Was bedeutet agent-native Infrastruktur und welche Anforderungen ergeben sich daraus für bestehende Tools und Workflows?
- Wie kann eine kleine Agentur ihr Projektmanagement mit AI-Agenten und n8n automatisieren — welche konkreten Workflows werden vorgeschlagen und welche Voraussetzungen brauchen sie?
- Welche wiederkehrenden Risiken und Grenzen von Agenten-Automatisierung nennen die Quellen, und welche Gegenmaßnahmen werden empfohlen?
