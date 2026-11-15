# Entscheidungen

Hier stehen alle Entscheidungen, die der Auftrag offen ließ, jeweils mit Begründung.

## Phase 0: Netzwerk (15.11.2026)

- **api.themoviedb.org: erreichbar.** `GET /3/configuration` ohne eigenen Auth-Header liefert
  HTTP 401 („Invalid API key“). Der Host antwortet also, aber in dieser Cloud-Umgebung ist kein
  Proxy-Secret für TMDB hinterlegt, und `TMDB_READ_TOKEN` ist nicht gesetzt. Folge: Der
  TMDB-Teil von Phase 3 kann hier nicht laufen und ist im Bericht als offen markiert.
- **files.grouplens.org: erreichbar, aber mit Zertifikatsproblem.** Der Server liefert eine Kette
  bis „emSign Root CA - G1“ (eMudhra). Dieses Root-Zertifikat ist im aktuellen
  certifi-Bundle (2026.10.18) und im System-Store des Containers nicht mehr enthalten, deshalb
  schlägt die TLS-Prüfung fehl. Ältere certifi-Versionen (z. B. 2024.8.30) enthalten es noch.
  Für den Download hier habe ich ein zusätzliches CA-Bundle aus System-Store plus diesem einen
  Root-Zertifikat (aus dem certifi-2024.8.30-Wheel von PyPI) gebaut. Die TLS-Prüfung blieb
  dabei aktiv, zusätzlich stimmt die MD5-Summe (`d472be332d4daa821edc399621853b57`).
  - Konsequenz für die App: `filmzwilling setup` versucht zuerst die normale Prüfung, dann den
    System-Store des Betriebssystems, dann eine über `FILMZWILLING_CA_BUNDLE` angegebene Datei.
    Klappt nichts, erscheint eine deutsche Anleitung: ZIP im Browser herunterladen, nach
    `data/raw/ml-32m.zip` legen und `setup` erneut starten (oder `setup --zip PFAD`).
  - Die MD5-Summe ist zusätzlich im Code hinterlegt, falls die `.md5`-Datei nicht geladen werden
    kann (manueller Download). Die TLS-Prüfung wird nie abgeschaltet.
