# iOS-Kurzbefehl „An KB senden"

Schickt URLs oder Text aus dem iOS-Teilen-Sheet direkt in die Ingest-Queue
des Gateways (`POST /api/ingest`).

## Voraussetzungen

- Tailscale-App auf dem iPhone installiert und verbunden (gleiches Tailnet
  wie der Rechner, auf dem das Gateway läuft).
- Gateway läuft (`uv run kb serve-gateway`, Port 8800).
- Token aus `.env.gateway` (Wert von `KB_API_TOKEN`) zur Hand.
- Tailscale-Name oder -IP des Gateway-Rechners (Tailscale-App → Geräteliste).

## Kurzbefehl anlegen

Kurzbefehle-App → neuer Kurzbefehl, Name **„An KB senden"**:

1. **Eingaben empfangen:** In den Kurzbefehl-Details „Im Teilen-Sheet
   anzeigen" aktivieren und als Eingabetypen **URLs** und **Text** wählen.
   (Erste Aktion ist dann automatisch „Empfange Eingaben vom Teilen-Sheet".)
2. **Aktion „Inhalt von URL abrufen":**
   - URL: `http://<tailscale-name-oder-ip>:8800/api/ingest`
   - Methode: **POST**
   - Header:
     - `Authorization`: `Bearer <TOKEN>` (Token aus `.env.gateway`)
     - `Content-Type`: `application/json`
   - Request-Body: **JSON** mit zwei Feldern:
     - `vault` → Text: `business-ki`
     - `content` → Variable **Kurzbefehl-Eingabe**
   - Entspricht: `{"vault": "business-ki", "content": <Kurzbefehl-Eingabe>}`
3. **Optional — Aktion „Benachrichtigung zeigen":** Als Inhalt das Feld
   `job_id` aus der Antwort wählen (Variable „Inhalt von URL" → über
   „Wörterbuchwert abrufen" den Schlüssel `job_id` herausziehen), z. B.
   „KB-Job <job_id> angelegt".

## Variante: Vault-Auswahl per Menü

Zweiter Kurzbefehl, z. B. **„An KB senden (Vault wählen)"**: Vor der
URL-Aktion eine **„Menü"**-Aktion mit den Einträgen `privat`,
`business-ki`, `business-mwe` einfügen. In jedem Menüzweig die gleiche
„Inhalt von URL abrufen"-Aktion wie oben, nur mit dem jeweiligen
Vault-Namen im Feld `vault`.

## Hinweise

- Die Antwort kommt in unter 5 Sekunden (HTTP 202) — der eigentliche
  Ingest-Job läuft asynchron im Instance Service.
- Job-Status ist in der PWA unter **Ingest** sichtbar (oder per
  `GET /api/jobs/<vault>/<job_id>`).
- Bei `401`: Token im Header prüfen; bei Timeout: Tailscale-Verbindung
  und laufendes Gateway prüfen.
