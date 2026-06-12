# Architektur: Multi-Vault Knowledge-System mit Cognee-Kern

*Bauvorlage, Stand 12. Juni 2026. Technische Aussagen zu Cognee sind mit Quellen belegt (siehe Ende). Offene Entscheidungen sind als konditionale WENN/DANN-Zweige mit Konfidenz und Falsifizierbarkeit markiert.*

---

## 1. Ziel & Aufgabenteilung

**Ziel:** Ein ingestion-first System. Du wirfst YouTube-/Weblinks, Wissensschnipsel und Transkripte rein; das System erfasst, strukturiert und legt rückverfolgbar ab. Primärer Konsument ist ein **KI-Agent**, der die KB befragt und daraus synthetisiert — nicht du beim manuellen Browsen.

**Aufgabenteilung (bewusste Schnittstelle):**

| Schicht | Wer | Inhalt |
|---|---|---|
| Wissens-Kern | **Cognee** (fertig) | `add()` → `cognify()` → `search()`: Entity-Extraktion, Graph, Embeddings, hybrider Abruf, Traceability, MCP-Server |
| Ingestion-UI + Worker | **Eigenbau** | Typ-Erkennung, YouTube-Transkript-Fetch, Provenance-Anreicherung, Vault-Routing |
| iOS-Zugriff | **Eigenbau** | PWA / iOS-Kurzbefehl „Teilen → an KB senden" |
| Rohschicht (Markdown) | **Eigenbau, optional** | Lange Rohtexte (Transkripte etc.) als `.md` als kanonische Kopie + Exit-Versicherung |

Cognee läuft self-hosted und **100 % lokal mit Ollama** möglich — passt zu deinem vorhandenen Ollama-/Infomaniak-Setup ([dev.to: cognee + Ollama](https://dev.to/chinmay_bhosale_9ceed796b/cognee-with-ollama-3pp8)).

---

## 2. Multi-Vault-Mapping (Privat ↔ Business trennen)

Cognee bietet drei Isolations-Ebenen ([Permissions-Doku](https://docs.cognee.ai/core-concepts/multi-user-mode/permissions-system/overview), [Multi-Tenant-Ankündigung](https://www.cognee.ai/blog/cognee-news/product-announcement-user-management)):

- **Dataset** — self-contained Einheit aus Dokumenten + Metadaten + Graph/Vektor-Repräsentation. Suche ist pro Dataset skopierbar.
- **Tenant** — breiter Container für isolierte Umgebungen (gedacht für Agenturen/mehrere Kunden).
- **Node Set** — feinere logische Gruppierung (Thema/Projekt), die Suche/Abruf eingrenzt.
- **`ENABLE_BACKEND_ACCESS_CONTROL=true`** erzwingt Daten-Isolation auf User+Dataset-Ebene für Graph *und* Vektor-Store (Auth wird Pflicht).

**Mapping deiner Vaults** (Business KI-Beratung, Business MWE, Privat):

- WENN Single-User, einfache Trennung genügt → **Vault = Dataset**. Cross-Vault-Suche = Query über mehrere Datasets; Privat bleibt per Default ausgeschlossen. (Empfehlung für Start, Konfidenz ~70 %)
- WENN du *harte* Wände willst (Privat: Philosophie/Medien/Propaganda strikt weg von Beruflichem) ODER Business MWE später für Kunden teilen möchtest → **Vault = Tenant** + Access Control aktivieren. (Konfidenz ~60 %)
- Innerhalb eines Vaults: **Node Sets** je Thema (z. B. im Business-KI-Vault: `n8n`, `mcp`, `seo`).

*Falsifizierung:* Wenn ein Cross-Vault-Synthese-Bedarf entsteht, der Privat+Business mischen müsste, ist die harte Tenant-Trennung hinderlich → dann Dataset-Modell. Vor Festlegung: 2–3 reale Abfragen durchspielen, ob je Cross-Vault nötig ist.

> **Entscheidung (getroffen): Vault = Dataset.** Begründung: Cross-Vault-Suche soll möglich sein, aber **optional** — das spricht gegen harte Tenant-Wände, weil eine Query über mehrere Datasets technisch einfach ist, eine über getrennte Tenants dagegen umständlich. Konkret:
> - Jeder Vault ist ein eigenes Dataset; Default-Abfrage ist **immer single-vault** (isoliert).
> - Cross-Vault ist ein **bewusst gesetztes Flag** in der Query (z. B. `scope=["business-ki", "business-mwe"]`).
> - **Privat ist per Default aus jedem Cross-Vault-Scope ausgeschlossen** und nur explizit einzeln abfragbar. WENN für Privat später doch eine *harte* Wand nötig wird (kein versehentliches Mischen) → diesen einen Vault zusätzlich über Access Control / separaten Tenant absichern, Business-Vaults bleiben Datasets.

---

## 3. Ingestion-Flows pro Quelltyp

Alle Flows enden in `cognee.add(data, dataset_name=<vault>)` → `cognee.cognify(dataset=<vault>)`. `add()` nimmt Weblink-URLs und Dateien (.md/.txt/.pdf/.docx/.pptx/.csv/Bilder/.mp3/.wav/Code …) nativ ([add()-Doku](https://docs.cognee.ai/python-api/add)).

| Quelltyp | Vorverarbeitung (Eigenbau-Worker) | An Cognee | Provenance |
|---|---|---|---|
| **YouTube-Link** | Transkript holen (`youtube-transcript-api` / `yt-dlp`) → `.md` mit Video-URL + Zeitmarken | `add(md_path, dataset)` | Video-URL, Video-ID, Timestamps |
| **Weblink** | Tavily *oder* Cognee-eigene Web-Extraktion (BeautifulSoup, CSS/XPath) → `.md` | `add(url, dataset)` *oder* `add(md_path)` | Original-URL, `fetched_at` |
| **Snippet** | direkt als Text | `add(text, dataset, node_set=…)` | Quelle = „manual", optional Notiz |
| **Datei / Meeting-Transkript** | als `.md` ablegen | `add(md_path, dataset)` | Dateiname, Datum, Teilnehmer (Metadata) |

Cognee unterstützt Web-Extraktion direkt (BeautifulSoup-Regeln, optional Tavily) — d. h. Weblinks kannst du auch ganz ohne eigenen Extraktor an `add()` geben; eigener Worker lohnt nur, wo du Provenance/Format kontrollieren willst. **YouTube hat Cognee nicht nativ** → der Transkript-Schritt ist der Kern deines Eigenbaus.

---

## 4. Provenance-Modell („woher kam das?")

Deine Anforderung — strukturiertes Wissen *plus* Rückverweis auf Originalquelle — ist datenbanktechnisch ein Standard-Pattern und mit Cognee abbildbar (Cognee ist traceable und speichert Metadaten):

- Jede Quelle bekommt einen **Source-Record**: `{id, type: youtube|web|snippet|file, url, video_id, locator (z. B. timestamp/Seite), fetched_at, raw_md_path}`.
- Beim `add()` wird dieser Record als **Metadata/Node-Set** mitgegeben → extrahierte Entities/Fakten bleiben im Graph mit der Quelle verknüpft.
- Die **Rohtext-`.md`** bleibt als kanonische Kopie auf Platte (dein „besseres Gefühl" + Git-Versionierung + Exit-Option, falls du Cognee je verlässt). Der Pfad steht im Source-Record.

Damit gilt: Markdown ist nicht mehr *Source of Truth für die Struktur* (das ist der Graph), aber **Source of Truth für die Rohtexte** — genau die Aufteilung, die du beschrieben hast.

---

## 5. iOS-Zugriff (löst dein Obsidian-Sync-Problem)

Der Obsidian-Git-Sync-Schmerz entfällt, weil der **Vault gar nicht mehr aufs iPhone muss**. Auf iOS brauchst du nur zwei Dinge:

- **Ingest:** ein iOS-Kurzbefehl mit „Teilen"-Ziel → `POST /ingest {url|text, vault}` an deinen Server. Aus YouTube-App, Safari, jeder App heraus.
- **Fragen:** dieselbe Web-/PWA-Oberfläche (Chat über Cognee `search`).

Erreichbarkeit des self-hosted Servers von unterwegs: **Tailscale** (privates Netz, kein offenes Port-Forwarding) — datenschutzfreundlich, gerade für den Privat-Vault.

---

## 6. Tech-Stack-Vorschlag (konditional)

- **Cognee:** self-host via Docker; Storage Postgres; LLM-Provider **pro Vault konfigurierbar** — Ollama (lokal), Infomaniak und OpenRouter. OpenRouter und Infomaniak sind OpenAI-API-kompatibel und damit über `LLM_PROVIDER`/`LLM_ENDPOINT`/`LLM_API_KEY` (bzw. `base_url`) einbindbar; Ollama wird von Cognee nativ unterstützt. *Hinweis:* Cognee setzt LLM-Konfiguration primär global/per-Instanz — Per-Vault-Routing löst du sauber über den Ingestion-Worker (er wählt je Ziel-Vault Provider + Modell, bevor er `cognify` anstößt). Konfidenz, dass das so trägt: ~70 %; falsifizierbar, falls Cognee in deiner Version nur eine globale LLM-Config zulässt → dann pro Vault eine eigene Cognee-Konfiguration/Instanz.
- **Ingestion-Worker:** Python (passt zu Cognee-SDK + `youtube-transcript-api`/`yt-dlp`).
- **Frontend/PWA:** Astro (dein Stack) als installierbare PWA mit Ingest-Form + Chat + Vault-Switcher.
- **Agent-Zugriff:** Cognee-**MCP-Server** → Claude Code & andere Agenten fragen nativ ([cognee-mcp](https://glama.ai/mcp/servers/topoteretes/cognee)).
- **Netz:** Tailscale für Mac+iOS.

**LLM-Routing pro Vault (getroffen):** Jeder Vault bekommt eine eigene Provider+Modell-Zuordnung. Verfügbar: **Ollama (lokal), Infomaniak, OpenRouter.** Empfehlung als Default-Belegung (anpassbar):

| Vault | Default-Provider | Begründung |
|---|---|---|
| Privat | Ollama (lokal) | Datenschutz hart → keine Cloud-Calls bei Philosophie/Medien/Propaganda |
| Business KI-Beratung | OpenRouter *oder* Infomaniak | Qualität/Modell-Auswahl; Geschäftsdaten weniger sensibel als Privat |
| Business MWE | Infomaniak *oder* OpenRouter | wie oben; ggf. Schweiz-Hosting via Infomaniak bevorzugen |

Das Routing implementiert der Ingestion-Worker (Provider-Auswahl je Ziel-Vault); siehe §6.

---

## 7. Phasenplan (mit eingebautem Test-Gate)

- **Phase 0 — Validierung (vor Vollausbau):** Cognee lokal + Ollama, 1 Dataset, ~10 echte Quellen manuell rein. Dann 5–10 echte Geschäfts-/Synthese-Fragen stellen. *Gate:* Liefert Cognees Synthese spürbar bessere Antworten als dein heutiges json-GraphRAG? WENN nein → Annahme „Cognee lohnt" ist falsifiziert, Stack überdenken.
- **Phase 1 — Ingestion-Worker:** Web + YouTube + Snippet + Provenance, Routing in den richtigen Vault.
- **Phase 2 — Oberfläche:** Astro-PWA (Ingest-Form + Chat + Vault-Switcher) + iOS-Kurzbefehl.
- **Phase 3 — Multi-Vault-Härtung:** Tenant/Access-Control je nach §2-Entscheidung; optionale Migration deiner bestehenden `raw/`-Markdown-KB in den Business-Vault.

---

## 8. Entscheidungen

**Getroffen:**

1. **Isolations-Modell:** Vault = **Dataset** (siehe §2). Default-Abfrage single-vault.
2. **Cross-Vault-Suche:** **erlaubt, aber optional** — nur per explizitem Scope-Flag; Privat per Default ausgeschlossen (§2).
3. **LLM-Routing:** **pro Vault konfigurierbar** über Ollama / Infomaniak / OpenRouter; Default-Belegung in §6.

**Noch offen:**

- **Provider-Feinwahl je Business-Vault:** OpenRouter (Modell-Vielfalt) vs. Infomaniak (CH-Hosting) für KI-Beratung bzw. MWE — entscheidbar in Phase 0 anhand von Antwortqualität + Tempo.
- **Harte Wand für Privat:** ob das Dataset-Modell reicht oder Privat zusätzlich Access-Control/Tenant bekommt (§2) — abhängig davon, wie kritisch versehentliches Mischen wäre.

---

## 9. Risiken, Bias & Unsicherheit

- **Ingest-Kosten/Latenz:** `cognify()` macht LLM-Aufrufe pro Quelle; lokal mit Ollama langsamer. *Fehlende Daten:* unbekannt für deine Hardware → in Phase 0 messen.
- **YouTube-Lücke:** nicht nativ → Eigenbau-Abhängigkeit von Transkript-Verfügbarkeit (manche Videos haben keine).
- **Lock-in:** Wissensstruktur lebt in Cognee. *Gegenmaßnahme:* Rohtext-Markdown als kanonische Kopie behalten → jederzeit re-ingestierbar in ein anderes System.
- **Bias-Hinweis:** „Cognee klingt super" + frische Beschäftigung mit 7 Frameworks = Neuheits-/Anker-Risiko. Das Phase-0-Gate ist genau dafür da — entscheide an echten Antworten, nicht am README. Cognee-Benchmark-/Marketing-Aussagen sind anbieterseitig (Selektionsbias).

---

## Quellen

- Cognee (Repo): [github.com/topoteretes/cognee](https://github.com/topoteretes/cognee)
- Cognee `add()` (Formate/Weblinks): [docs.cognee.ai/python-api/add](https://docs.cognee.ai/python-api/add)
- Cognee Permissions / Multi-User: [docs.cognee.ai/core-concepts/multi-user-mode/permissions-system/overview](https://docs.cognee.ai/core-concepts/multi-user-mode/permissions-system/overview)
- Cognee Multi-Tenant-Ankündigung (RBAC, Dataset-Sharing): [cognee.ai/blog/cognee-news/product-announcement-user-management](https://www.cognee.ai/blog/cognee-news/product-announcement-user-management)
- Cognee + Ollama (100 % lokal): [dev.to/.../cognee-with-ollama](https://dev.to/chinmay_bhosale_9ceed796b/cognee-with-ollama-3pp8)
- Cognee MCP-Server: [glama.ai/mcp/servers/topoteretes/cognee](https://glama.ai/mcp/servers/topoteretes/cognee)
- Karpathy LLM Wiki (Ausgangspattern): [gist.github.com/karpathy/442a6bf…](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f)
