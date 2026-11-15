# Entscheidungen

Hier steht alles, was der Auftrag offen ließ, mit der jeweiligen Begründung. Die Reihenfolge folgt
grob den Phasen.

## Netzwerk (Phase 0, 15.11.2026)

**api.themoviedb.org ist erreichbar.** `GET /3/configuration` ohne eigenen Auth-Header liefert
HTTP 401 („Invalid API key“). Der Host antwortet also, aber in dieser Cloud-Umgebung ist kein
Proxy-Secret für TMDB hinterlegt und `TMDB_READ_TOKEN` ist nicht gesetzt. Der TMDB-Teil von
Phase 3 konnte deshalb nicht laufen und ist im Bericht als offen markiert.

**files.grouplens.org ist erreichbar, hat aber ein Zertifikatsproblem.** Der Server liefert eine
Kette bis „emSign Root CA - G1“ (eMudhra). Dieses Root-Zertifikat fehlt im aktuellen
certifi-Bundle (2026.10.18) und im System-Store des Containers, ältere certifi-Versionen
(2024.8.30) enthalten es noch. Für den Download hier habe ich ein CA-Bundle aus System-Store plus
diesem einen Root-Zertifikat (aus dem certifi-Wheel von PyPI) gebaut. Die TLS-Prüfung blieb aktiv,
die MD5-Summe stimmt (`d472be332d4daa821edc399621853b57`).

Folgen für die App:

- `filmzwilling setup` probiert nacheinander eine Datei aus `FILMZWILLING_CA_BUNDLE`, das
  certifi-Bundle und den Zertifikatsspeicher des Betriebssystems. Klappt nichts, erscheint eine
  deutsche Anleitung: ZIP im Browser laden, als `data/raw/ml-32m.zip` ablegen oder mit
  `setup --zip PFAD` angeben. Die TLS-Prüfung wird nie abgeschaltet.
- Die MD5-Summe steht zusätzlich im Code. Sie wird benutzt, wenn die `.md5`-Datei selbst nicht
  geladen werden kann (gleiches Zertifikatsproblem). Mit `--md5` lässt sie sich überschreiben.

## Tests

- `test_missing_metadata_and_offers` erwartete, dass auch ein Film ohne tmdbId als „Metadaten
  fehlen“ gemeldet wird. Für so einen Film kann TMDB nichts liefern, und die Funktion bestimmt
  genau die abzufragenden Filme. Der Test prüft jetzt nur Filme mit tmdbId. Das war die einzige
  Testkorrektur.
- `node --test tests/js/` mit einem Ordner als Argument versteht Node 22 nicht (es erwartet
  Dateien oder Glob-Muster). Damit der Befehl aus dem Auftrag trotzdem funktioniert, liegen in
  `tests/js/` eine `package.json` mit `"main": "index.js"` und eine `index.js`, die alle
  Testdateien importiert. Die `package.json` im Projektordner setzt `"type": "module"` und hat
  keine Abhängigkeiten.
- Der E2E-Test braucht Playwright für Node (nicht für Python). Ist es nicht installiert, wird der
  Test übersprungen.
- `mypy src` muss mit dem mypy aus der Projektumgebung laufen. Ein global installiertes mypy (zum
  Beispiel als uv-Tool) sieht die Pakete nicht und meldet Folgefehler. Im Zweifel
  `python -m mypy src`.

## MovieLens

- Filme ohne eine einzige Bewertung bleiben als Spalte in der Matrix (Anzahl 0, Rang ganz hinten).
  So bleiben die Spaltenindizes stabil.
- Kommt eine tmdbId in `links.csv` mehrfach vor, behält sie nur der Film mit den meisten
  Bewertungen. In der App-Datenbank ist die tmdbId eindeutig.
- Der Popularitätsrang sortiert nach Anzahl Bewertungen absteigend, bei Gleichstand nach movieId.
- `ratings.csv` ist nach userId sortiert. Dann baut die Aufbereitung die CSR-Matrix direkt aus den
  Zeilenzeigern, ohne Umweg über COO. Das hält den Speicherbedarf bei etwa 2,5 GB.
- Nach der Aufbereitung werden die entpackten CSV-Dateien gelöscht, das ZIP bleibt liegen.

## Empfehlungen

- Die Formeln und Standardwerte stammen unverändert aus dem Auftrag (min_overlap 10,
  shrinkage 25, k 50, min_support 5, prior_weight 3) und stehen in `RecommenderConfig`.
- Die Nachbarschaft eines Films sind die k ähnlichsten Zwillinge, die ihn bewertet haben. Dafür
  werden die Zeilen aller Zwillinge in Ähnlichkeitsreihenfolge als CSC-Matrix abgelegt, und pro
  Spalte zählen die ersten k Einträge. Es gibt keine Python-Schleife über Nutzer oder Filme.
- Filme mit support unter min_support erscheinen nicht in der Liste. Beim Selbsttest bekommen sie
  trotzdem eine Vorhersage, nämlich den Prior (eigener Mittelwert plus Filmabweichung). Die
  Abdeckung (Anteil mit genug Zwillingen) wird mit ausgegeben.
- „Die drei Filme mit der größten Übereinstimmung“ auf der Zwillingsseite sind die gemeinsamen
  Filme mit dem größten Produkt der zentrierten Noten. Das sind Filme, bei denen beide in dieselbe
  Richtung deutlich vom eigenen Schnitt abweichen. Diese Filme tragen am meisten zur Ähnlichkeit bei.
- Automatische Neuberechnung: Die erste startet im Hintergrund, sobald 30 eigene Bewertungen da
  sind, danach jeweils nach 25 neuen. Es läuft nie mehr als eine Berechnung gleichzeitig.
- Mit echten Daten landen oben auch wenig bekannte Filme mit 5 bis 9 Zwillingen (siehe Bericht).
  Die Standardwerte bleiben trotzdem wie vorgegeben. Wer das nicht will, setzt den Filter
  „Mindestens Zwillinge“ auf 20 oder 30.

## Anbieter und Filter

- Die Voreinstellung „meine Anbieter“ prüft lange Namen als Teilstring („Netflix basic with Ads“
  enthält „Netflix“). Kurze Namen müssen am Wortanfang stehen (`\bzdf`, `\barte\b`, `\b3sat\b`,
  `\bjoyn`), sonst würde zum Beispiel „Smartes Kino“ als Arte zählen. „Joyn Plus“ zählt als Joyn,
  so wie der Auftrag es verlangt.
- Ist noch keine Anbieterliste geladen (offline, vor dem ersten `tmdb-sync`), filtern die
  Empfehlungen standardmäßig nicht nach Anbietern. Sonst wäre die Liste leer.
- Wählt man in der URL ausdrücklich keinen Anbieter (`providers=`), passt kein Film. `providers=any`
  schaltet den Filter ab.
- Filme ohne Laufzeit oder Jahr fallen heraus, sobald ein Laufzeit- oder Jahresfilter gesetzt ist.
- Anbieterdaten holt die App für die besten 3000 Kandidaten: nach jeder Neuberechnung im
  Hintergrund nur die veralteten (älter als 7 Tage), mit dem Knopf „Verfügbarkeit aktualisieren“
  alle 3000.
- Der Abschnitt „Neu seit Ende 2023“ ist immer nach TMDB-Note sortiert, egal welche Sortierung
  gewählt ist. Mindest-Match und Mindestzahl Zwillinge gelten dort nicht, weil es keine Vorhersage
  gibt. Discover lädt 3 Seiten (bis zu 60 Filme).

## Warteschlange und Bewerten

- Sind in den Einstellungen keine eigenen Profile gewählt, gelten alle importierten Profile als
  eigene. Für einen einzelnen Nutzer ist das die naheliegende Annahme.
- Hat ein Film Ereignisse aus einem eigenen und einem Familienprofil, zählt das eigene Profil.
  Die Hinweis-Chips zeigen beide.
- Quelle 2 enthält neben „abgebrochen“ und „unklar“ auch „unbekannt“ (keine Laufzeit), sortiert
  nach letzter Sichtung. Quelle 3 ist ebenfalls nach letzter Sichtung sortiert.
- Importierte Filme ohne MovieLens-ID kommen in die Quellen 1 bis 3. Die Einschränkung auf Filme
  mit beiden IDs gilt laut Auftrag nur für Quelle 4. Für die Empfehlungen zählen sie nicht.
- Bewertete und als „nicht gesehen“ markierte Filme zählen zur festen Menge aus Quelle 4 (daraus
  ergibt sich der Fortschritt „412 bewertet · 380 nicht gesehen · 208 übrig“). Filme mit „Kein
  Interesse“ fallen ganz heraus, dafür rückt ein anderer Film nach.
- Die Fortschrittsleiste zählt alle Bewertungen und alle „nicht gesehen“, „übrig“ bezieht sich auf
  die Warteschlange.
- Eine Bewertung entfernt die Markierung „nicht gesehen“.
- „Rückgängig“ gilt nur für Aktionen auf der Bewertungsseite. Bewertungen über die Kachel
  („Schon gesehen, bewerten“) oder auf „Meine Bewertungen“ landen nicht im Rückgängig-Stapel.
- Die Hinweis-Chips zeigen Quelle und Profil, Abbruch oder „unklar“ und Netflix-Daumen. „Zu Ende
  geschaut“ bekommt keinen eigenen Chip, um die Karte ruhig zu halten.
- Die Buttons 0 bis 4 werden hervorgehoben, wenn ein eigenes Profil abgebrochen hat und keines zu
  Ende geschaut hat.

**Keine verlorenen Aktionen.** Der E2E-Test hat gezeigt, dass Aktionen verloren gingen, wenn man
direkt nach dem Bewerten die Seite verlässt (die Retry-Queue lebte nur im Browser). Jetzt bekommt
jede Aktion eine `client_id`, die der Server nur einmal ausführt. Aktionen laufen serverseitig
nacheinander. Die Requests nutzen `keepalive`, und beim Verlassen oder Verstecken der Seite
schickt der Browser alle noch offenen Aktionen in Reihenfolge als einen Batch per `sendBeacon` an
`POST /api/actions`. Doppelte Zustellung schadet dank `client_id` nicht.

## Importe

**Serienfolgen.** Ein Titel wird an „: “ (Doppelpunkt mit Leerzeichen) in Abschnitte geteilt.

- Folge sicher: ein Abschnitt wie „Staffel 2“, „Season 1“, „Series 3“; Marker wie „Limitierte
  Serie“, „Miniserie“, „Limited Series“; ein Abschnitt, der mit „Folge 3“, „Episode 4“,
  „Kapitel eins“ beginnt; „S01E02“ oder „ - Staffel 1“ irgendwo im Titel.
- „Teil 1“, „Part 2“, „Volume 1“ gelten nur dann als Staffel, wenn danach noch ein Abschnitt
  folgt. So bleiben „Kill Bill: Volume 1“ und „Dune: Part Two“ Filme, „Haus des Geldes: Teil 1:
  Folge 1“ ist eine Folge.
- „Episode IV“ mit römischer Zahl ist kein Folgenmarker (Star Wars).
- Drei oder mehr Abschnitte ohne Marker gelten als „unklar“. Dann entscheidet TMDB: Ein
  Filmtreffer über der Schwelle gewinnt, sonst wird der Titel als Serie verworfen und taucht nicht
  auf der Seite „Zuordnung“ auf.

**Netflix.** `Bookmark` ist die Position am Ende einer Sitzung, `Latest Bookmark` wird ignoriert.
Die 120-Sekunden-Grenze gilt für die Summe aller Sitzungen eines Titels pro Profil. Enthält ein
Ordner sowohl den Datenexport als auch den einfachen Export, wird nur der Datenexport gelesen. Der
einfache Export ohne `--profile` bekommt das Profil „Netflix“.

**Netflix-Ratings.csv** (Format angenommen, nicht an einer echten Datei geprüft): Spalten werden
über den Namen erkannt (Profil: „Profile Name“ oder „Profile“, Titel: „Title Name“ oder „Title“,
Daumen: „Thumbs Value“). Werte: 1 = Daumen runter, 2 = Daumen hoch, 3 = zwei Daumen hoch, alles
andere wird ignoriert (auch alte Sternbewertungen). Gibt es zu einem Daumen keinen Sehverlauf,
entsteht ein Ereignis mit 0 Sitzungen, damit der Film trotzdem in die Warteschlange kommt.

**Prime Video** (Format unbekannt): Spalten werden über die Liste in `header_aliases.py` erkannt.
Exakte Treffer gehen vor Treffern am Wortanfang, diese vor Teilstrings, damit zum Beispiel
„Minutes Watched“ als Dauer und nicht als Datum zählt. Einheiten erkennt der Importer am Namen
(„ms“, „Millis“ = Millisekunden, „Minuten“/„min“ = Minuten, sonst Sekunden), `HH:MM:SS` geht
immer. Zeilen, deren Typ-Spalte „Episode“, „Series“, „Folge“ und ähnliches enthält oder deren
Folgentitel gefüllt ist, gelten als Serie. Die 120-Sekunden-Regel gilt wie bei Netflix. Ohne
Profilspalte heißt das Profil „Prime Video“.

Für das Skript „watch-history-exporter-for-amazon-prime-video“ konnte ich die Ausgabe nicht
nachsehen (GitHub ist aus dieser Umgebung nicht erreichbar). Angenommen sind CSV-Spalten wie
`Date Watched, Type, Title, Episode Title, …` und JSON als Liste von Objekten mit Schlüsseln wie
`dateWatched`, `type`, `title`, `episodeTitle` oder als Objekt mit Listen (`movies`, `episodes`).
Listen, deren Name nach Serien klingt, gelten als Folgen. Passt das echte Format nicht, hilft
`import inspect` plus eine Mapping-Datei.

**Generische CSV.** Die Titelspalte muss `title` oder `Titel` heißen. `watched_fraction` versteht
0,85, 0.85, „85 %“ und 85 (Werte über 1 gelten als Prozent). Ohne Profil heißt das Profil
„Manuell“. Komma, Semikolon und Tabulator als Trennzeichen sowie UTF-8 mit und ohne BOM und
Windows-1252 werden erkannt.

**Zuordnung.** Bewertung eines TMDB-Treffers: höchste rapidfuzz-Ähnlichkeit (`ratio` oder
`token_sort_ratio`) von normalisiertem Titel oder Originaltitel, plus 5 Punkte bei gleichem Jahr,
2 bei einem Jahr Abstand, sonst bis zu 25 Punkte Abzug, plus höchstens 3 Punkte für viele Stimmen
auf TMDB. Ohne Jahresangabe dient das Jahr der letzten Sichtung als Obergrenze: Ein Film, der
erst danach erschienen ist, verliert 30 Punkte. Steht eine Jahreszahl in Klammern im Titel, wird
sie als Jahr benutzt. Findet die Suche mit Jahr nichts, sucht sie ohne Jahr. Zusätze wie „(OmU)“
oder „[4K UHD]“ werden vor der Suche entfernt. TMDB-Ergebnisse mit `media_type` „tv“ werden
übersprungen.

## TMDB

- Die rohen Antworten liegen in der Tabelle `tmdb_cache` (Metadaten und Suchen 30 Tage, Anbieter
  7 Tage). Die Tabelle `films` enthält die daraus gelesenen Felder. Sind nur die Anbieter veraltet,
  wird nur `/movie/{id}/watch/providers` abgefragt.
- Ein 404 für eine Film-ID wird ebenfalls 30 Tage gemerkt.
- Neben 429 werden auch 5xx-Antworten und Netzwerkfehler wiederholt (höchstens 5 Versuche,
  Backoff 0,5 s, 1 s, 2 s, 4 s). Das Rate-Limit ist ein gleitendes Fenster von 20 Requests pro
  Sekunde plus eine Semaphore mit 20 gleichzeitigen Requests.
- MovieLens-Genres werden auf die deutschen TMDB-Namen abgebildet (Children = Familie,
  Film-Noir = Krimi, IMAX entfällt), damit der Genrefilter für alle Filme dieselben Namen hat.

## Sonstiges

- `filmzwilling check` sucht zuerst über TMDB (deutscher Titel), dann lokal in den
  MovieLens-Titeln inklusive der Alternativtitel in Klammern. Deutsche Titel, die MovieLens nicht
  als Alternativtitel führt („Der Pate“, „Der Schuh des Manitu“), findet nur die TMDB-Suche.
- Ein Demo-Datenordner ist in der Datenbank als Demo markiert. Die App fragt für ihn nie TMDB an,
  auch wenn ein Token gesetzt ist, weil die tmdbIds der Demo erfunden sind.
- Das Backup beim Start von `serve` überschreibt eine Datei vom selben Tag. Andere Dateien im
  Backup-Ordner bleiben unberührt.
- Zeitstempel in der Datenbank sind UTC.
- Die Starlette-Warnung, dass der TestClient lieber das Paket `httpx2` hätte, ist in der
  pytest-Konfiguration ausgeblendet. Die App selbst nutzt `httpx`.
