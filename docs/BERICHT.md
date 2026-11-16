# Bericht: Filmzwilling, Stand 16.11.2026

## Was fertig ist

Die App ist vollständig nach Auftrag gebaut, Tests zuerst (Commit `test: add full test suite
(red)`, danach Implementierung Modul für Modul).

- MovieLens 32M: Download mit MD5-Prüfung, idempotente Aufbereitung nach `data/processed/`
  (Parquet, CSR-Matrix mit zentrierten Bewertungen, Nutzer-Mittelwerte, Anzahl, Mittelwert und
  Popularitätsrang pro Film).
- Kernlogik: Skala 0 bis 10, angepasste Kosinus-Ähnlichkeit mit Signifikanzgewichtung,
  filmspezifische k-Nachbarschaft, Schrumpfung zum Filmdurchschnitt, Begründungstext, Selbsttest
  mit 5-facher Kreuzvalidierung. Alles vektorisiert mit scipy.sparse.
- Importe: Netflix (Datenexport mit ViewingActivity und Ratings, einfacher Titelverlauf), Prime
  Video (heuristisch, `import inspect`, TOML-Mapping, Exporter-Skript als CSV und JSON),
  generische CSV. Serienerkennung, Sitzungen zusammenfassen, Autoplay-Filter, Idempotenz.
- Zuordnung zu TMDB mit rapidfuzz, Jahreszahl und Popularität; schwache Treffer auf der Seite
  „Zuordnung“.
- TMDB-Client: Bearer-Token optional, 20 Requests pro Sekunde, Retry-After und Backoff,
  deutsche Fehlermeldung bei 401, Cache in SQLite (30 Tage Metadaten, 7 Tage Anbieter),
  Anbieterliste, Discover für Neuerscheinungen.
- Weboberfläche (FastAPI, Jinja2, Vanilla-JS ohne Build, dunkles Design): Bewerten mit
  Tastatur und Touch, optimistischem UI, Retry-Queue, Vorladen der nächsten 5 Poster; Empfehlungen
  mit allen Filtern in der URL; Meine Bewertungen mit Suche und CSV-Export; Zuordnung; Zwillinge;
  Einstellungen mit Selbsttest.
- CLI mit allen Befehlen aus dem Auftrag, Backup beim Start von `serve` (14 Stück).
- `filmzwilling demo`: synthetische Daten in einem temporären Ordner, ohne Netz und ohne Token.
- Doku: `README.md`, `CLAUDE.md`, `docs/ENTSCHEIDUNGEN.md`, dieser Bericht.

## Testergebnisse

| Lauf | Ergebnis |
|---|---|
| `pytest` (Standardlauf) | 429 bestanden, 6 abgewählt (slow, e2e, real_data) |
| `pytest -m slow` | 1 bestanden: 20.000 Nutzer × 3.000 Filme (1,8 Mio. Bewertungen) in 0,04 s, Grenze 5 s |
| `pytest -m e2e` | 1 bestanden (Chromium über Playwright für Node) |
| `FILMZWILLING_REAL_DATA=1 pytest -m real_data` | 4 bestanden |
| `node --test tests/js/` | 17 bestanden |
| `ruff check`, `ruff format --check` | keine Befunde |
| `mypy src` (strict für scale, similarity, recommender) | keine Befunde in 31 Dateien |
| Coverage `src/filmzwilling` | 96 % (3609 Anweisungen, Zweige mitgezählt) |

Alle Läufe wurden zusätzlich in einem frischen Klon mit neuer virtueller Umgebung wiederholt
(`pip install -e ".[dev]"`), mit demselben Ergebnis. `filmzwilling demo` lief dort mit
blockiertem Netz (Proxy auf einen toten Port gesetzt).

Qualitätsschranke auf synthetischen Daten (300 Nutzer in 3 Geschmacksclustern, 200 Filme, ein
neuer Nutzer mit 120 Bewertungen): Hold-out 20 % ergibt RMSE 0,72 gegen 1,04 beim
Filmdurchschnitt (31 % besser, verlangt waren 15 %), Spearman 0,90 gegen 0,75. Die
Lieblingsfilme des eigenen Clusters stehen für jeden der drei Cluster in den Top 10 (mindestens
8 von 10).

Phase 4 per HTTP: `filmzwilling demo` gestartet, alle sechs Seiten liefern 200 ohne
Template-Reste, 50 Bewertungen über `POST /api/rate`, danach liefert `/api/recommendations` 229
Empfehlungen (mit Standard-Anbieterfilter).

Tempo beim Bewerten: 40 Bewertungen per Tastatur im Demo-Modus, gemessen im Browser vom
Tastendruck bis zum neuen Titel: Median 0,7 ms, höchstens 2,1 ms. Alle 40 Bewertungen kamen beim
Server an. Auf echten Daten braucht der Server für `POST /api/rate` etwa 11 ms, das läuft im
Hintergrund und bremst die Anzeige nicht.

Ein Fund aus dem E2E-Test: Wer direkt nach dem Bewerten die Seite verlässt, verlor die noch nicht
gesendeten Aktionen. Behoben mit `client_id` pro Aktion, `keepalive` und einem
`sendBeacon`-Batch beim Verlassen (Details in `docs/ENTSCHEIDUNGEN.md`).

## Phase 3: echte Daten

**MovieLens.** Download (239 MB) und MD5-Prüfung ok. `filmzwilling setup` von Grund auf: 12,5 s
gesamt (Entpacken, Aufbereitung, 87.585 Filme in die SQLite-Datenbank), Spitze 2,5 GB
Arbeitsspeicher. Zweiter Aufruf: übersprungen nach 2,4 s (MD5 des ZIPs). Ergebnis: 32.000.204
Bewertungen, 200.948 Nutzer, 87.585 Filme, `data/processed` 340 MB. Laden der aufbereiteten
Daten: 0,3 s.

**Laufzeit der Empfehlungen** mit 400 eigenen Bewertungen: Ähnlichkeit und Vorhersage 1,0 bis
1,7 s (132.000 Zwillinge, 41.000 Kandidaten), inklusive Speichern in SQLite 1,8 s. Erster Aufruf
der Empfehlungsliste 1,1 s, danach mit Filtern 35 ms. `GET /api/queue` 12 ms, `POST /api/rate`
11 ms.

**Test-Florian.** 20 zufällige echte Nutzer mit mindestens 300 Bewertungen, jeweils auf 0 bis 10
umgerechnet, aus der Nachbarschaft entfernt, 20 % versteckt (Seed 1):

| Nutzer | Bewertungen | RMSE | RMSE Baseline | Spearman | Spearman Baseline |
|---|---|---|---|---|---|
| 171997 | 505 | 1,82 | 1,84 | 0,47 | 0,45 |
| 130656 | 313 | 1,91 | 2,32 | 0,36 | 0,03 |
| 140942 | 319 | 1,53 | 1,74 | 0,65 | 0,58 |
| 170702 | 357 | 2,23 | 2,48 | 0,56 | 0,55 |
| 158282 | 385 | 0,95 | 2,77 | 0,37 | 0,36 |
| 5517 | 369 | 1,49 | 1,10 | 0,62 | 0,55 |
| 59750 | 324 | 1,63 | 1,78 | 0,47 | 0,33 |
| 166653 | 613 | 1,45 | 1,62 | 0,31 | 0,27 |
| 74166 | 663 | 1,03 | 1,00 | 0,66 | 0,67 |
| 16359 | 477 | 1,81 | 1,97 | 0,64 | 0,57 |
| 93643 | 318 | 1,56 | 1,63 | 0,58 | 0,33 |
| 35684 | 889 | 1,69 | 2,42 | 0,62 | 0,56 |
| 144043 | 312 | 1,77 | 1,79 | 0,48 | 0,44 |
| 128702 | 424 | 1,72 | 2,03 | 0,60 | 0,61 |
| 71076 | 316 | 1,19 | 1,45 | 0,51 | 0,50 |
| 73198 | 431 | 1,77 | 2,31 | 0,45 | 0,21 |
| 35377 | 317 | 2,17 | 2,47 | 0,46 | 0,32 |
| 181243 | 362 | 1,70 | 1,67 | 0,45 | 0,33 |
| 20093 | 544 | 1,34 | 1,53 | 0,77 | 0,74 |
| 128099 | 2160 | 1,99 | 2,63 | 0,71 | 0,66 |

Im Mittel RMSE 1,64 gegen 1,93 (15 % besser, Median 11 %), Spearman 0,54 gegen 0,45. Die RMSE
ist bei 17 von 20 Nutzern besser, Spearman bei 18 von 20. Der Test `test_real_data.py` prüft
drei feste Nutzer und verlangt, dass beide Werte die Baseline schlagen. Eine 5-fache
Kreuzvalidierung für Nutzer 171997 (505 Bewertungen): RMSE 1,87 gegen 1,95, Spearman 0,52 gegen
0,45, Dauer 5,7 s.

Einschränkung der Messung: Die Filmmittelwerte enthalten die Bewertungen des Test-Nutzers noch
(er ist nur aus der Nachbarschaft entfernt). Bei Filmen mit Tausenden Bewertungen ist das egal,
bei sehr seltenen Filmen hilft es der Baseline und dem Prior leicht.

**`filmzwilling check`** auf den echten Daten (ohne TMDB, also nur lokale Titelsuche):

```
$ filmzwilling check "The Godfather" --year 1972
„The Godfather“ (1972)
  In MovieLens: ja (movieId 858, tmdbId 238)
  Bewertungen: 66.440, im Schnitt 4,32 von 5 Sternen
  Popularitätsrang: 20 von 87.585
  Warteschlange: Platz 20 von 1000

$ filmzwilling check "Inception"
„Inception“ (2010)
  In MovieLens: ja (movieId 79132, tmdbId 27205)
  Bewertungen: 57.931, im Schnitt 4,16 von 5 Sternen
  Popularitätsrang: 27 von 87.585
  Warteschlange: Platz 27 von 1000

$ filmzwilling check "Das Leben der Anderen"
„The Lives of Others“ (2006)
  In MovieLens: ja (movieId 44555, tmdbId 582)
  Bewertungen: 12.273, im Schnitt 4,20 von 5 Sternen
  Popularitätsrang: 607 von 87.585
  Warteschlange: Platz 607 von 1000

$ filmzwilling check "Toni Erdmann"
„Toni Erdmann“ (2016)
  In MovieLens: ja (movieId 158972, tmdbId 374475)
  Bewertungen: 658, im Schnitt 3,72 von 5 Sternen
  Popularitätsrang: 5.483 von 87.585
  Warteschlange: nicht enthalten (nur die 1000 meistbewerteten Filme kommen hinein, Größe in den Einstellungen änderbar)

$ filmzwilling check "Manitou's Shoe"
„Manitou's Shoe“ (2001)
  In MovieLens: ja (movieId 173627, tmdbId 8366)
  Bewertungen: 57, im Schnitt 3,27 von 5 Sternen
  Popularitätsrang: 15.196 von 87.585
  Warteschlange: nicht enthalten (…)
```

Weitere Ergebnisse: „Lola rennt“ findet „Run Lola Run“ (Rang 245, Platz 245), „Das Boot“ (1981)
Rang 411, „Good Bye, Lenin!“ Rang 1.124, „Der Untergang“ findet „Downfall“ (Rang 1.066). Die
deutschen Titel „Der Pate“ und „Der Schuh des Manitu“ findet die lokale Suche nicht, weil
MovieLens sie nicht als Alternativtitel führt; mit TMDB klappt es (siehe unten). Die
Platzangaben gelten für eine leere Datenbank ohne Importe und Bewertungen.

`filmzwilling serve` mit den echten Daten: alle Seiten 200, die Warteschlange beginnt mit
„The Shawshank Redemption“ und „Forrest Gump“, das Backup wird angelegt.

**TMDB.** Anfangs gab es in der Cloud-Umgebung keinen Token (401). Am 16.11. kam der Token als
Netzwerk-Secret dazu; der Proxy hängt ihn an, die App sendet selbst keinen Header. Danach lief der
TMDB-Teil vollständig mit dem Client der App:

| Film | deutscher Titel, Laufzeit | Poster | DE: Abo, gratis, mit Werbung (Auszug) |
|---|---|---|---|
| 238 | Der Pate, 175 Min. | ja | Paramount Plus, Joyn Plus, Magenta TV+ |
| 27205 | Inception, 148 Min. | ja | Amazon Prime Video (auch mit Werbung), RTL+, HBO Max |
| 582 | Das Leben der Anderen, 137 Min. | ja | HBO Max |
| 374475 | Toni Erdmann, 162 Min. | ja | nur Leihen und Kaufen |
| 8366 | Der Schuh des Manitu, 84 Min. | ja | HBO Max, CineMix+ Amazon Channel |
| 104 | Lola rennt, 79 Min. | ja | ARD Plus, Magenta TV+ |
| 338 | Good Bye, Lenin!, 121 Min. | ja | Disney Plus, Joyn Plus, HBO Max |
| 387 | Das Boot, 150 Min. | ja | Netflix (auch mit Werbung), gratis: filmfriend |
| 613 | Der Untergang, 156 Min. | ja | Paramount Plus, HBO Max |
| 276 | Die fetten Jahre sind vorbei, 127 Min. | ja | ARD Plus; mit Werbung: Rakuten TV |

Die zehn Abrufe dauerten zusammen 0,8 s. Die Anbieterliste für Deutschland hat 197 Einträge, die
Voreinstellung „meine Anbieter“ ergibt 13 (Netflix mit Kids und Werbevarianten, Amazon Prime Video
mit Werbevarianten, Disney Plus, Joyn, Joyn Plus, ARD Mediathek, ZDF, Arte, 3sat). Discover mit
diesen Anbietern ab 1.10.2023 und mindestens 100 Stimmen: 60 Filme in 0,3 s, an der Spitze
„Swapped – Getauscht“ (8,8) und „Der Astronaut – Project Hail Mary“ (8,6). Die Titelsuche ordnet
„Der Pate“ (1972), „Das Leben der Anderen“, „Der Schuh des Manitu“ und „Lola rennt“ mit
Ähnlichkeit 100 zu, „Planet der Affen“ mit Jahr 1968 dem Original (871) statt dem Remake.

`filmzwilling tmdb-sync` auf den echten Daten: 58,5 s für die ganze Warteschlange (999 von 1000
Filmen mit Metadaten, ein Film fehlt bei TMDB) und 60 Neuerscheinungen, Spitze 200 MB
Arbeitsspeicher. `check` mit deutschem Titel:

```
$ filmzwilling check "Der Pate"
„Der Pate“ (1972)
  Titel in MovieLens: The Godfather
  In MovieLens: ja (movieId 858, tmdbId 238)
  Bewertungen: 66.440, im Schnitt 4,32 von 5 Sternen
  Popularitätsrang: 20 von 87.585
  Warteschlange: Platz 20 von 1000
```

`check "Der Schuh des Manitu"` findet jetzt „Manitou's Shoe“ (movieId 173627, tmdbId 8366).

Mit einem echten MovieLens-Nutzer (400 Bewertungen) als Florian: Neuberechnung 1,9 s, danach
holt die App im Hintergrund Anbieter und Metadaten für die besten 3000 Kandidaten (2776 Abrufe,
151 s beim ersten Mal). Mit dem Standard-Anbieterfilter passen 600 Filme. Die ersten zehn: Der
Pate (8,4), The Dark Knight (8,4), Pink Floyd: Pulse (8,4, 11 Zwillinge, 3sat), Prinzessin
Mononoke (8,3, Netflix), Die letzten Glühwürmchen (8,3, Netflix), Der General (8,2), Zwei
glorreiche Halunken, Der Pate Teil II, Requiem for a Dream, Chihiros Reise ins Zauberland.

Die Live-Prüfung hat drei Fehler gezeigt, die jetzt behoben und getestet sind:

- Empfohlene Filme außerhalb der Warteschlange hatten weder Poster noch deutschen Titel, weil nur
  die Anbieter geholt wurden. Jetzt holt die Verfügbarkeitsabfrage für Kandidaten ohne Metadaten
  die vollständigen Details (ein Abruf liefert beides).
- Die Notenknöpfe auf den Kacheln waren immer sichtbar (CSS überschrieb das `hidden`-Attribut).
- Mit 197 Anbietern war der Filter unübersichtlich. Jetzt stehen „meine Anbieter“ oben, die
  übrigen hinter „Weitere Anbieter“. Kostenpflichtige Zusatzkanäle („ZDF Herzkino Amazon
  Channel“) zählen nicht mehr zur Voreinstellung.

## Nur synthetisch oder mit angenommenen Formaten getestet

- Prime Video: Das Format der Amazon-Datenauskunft ist unbekannt. Getestet sind zwei erfundene
  Header-Varianten (englisch mit Sekunden, deutsch mit Semikolon und `HH:MM:SS`) und das
  Mapping per TOML. Mit einer echten Datei zuerst `filmzwilling import inspect` laufen lassen.
- Ausgabe des Skripts „watch-history-exporter-for-amazon-prime-video“: Spaltennamen und
  JSON-Schlüssel sind angenommen (siehe ENTSCHEIDUNGEN).
- Netflix `Ratings.csv`: Spaltennamen und Bedeutung der Werte 1, 2, 3 sind angenommen.
- Netflix `ViewingActivity.csv` und der einfache Export folgen dem dokumentierten Format, die
  Testdatei ist aber selbst gebaut.
- Disney+: Es gibt keinen Export, daher nur die generische CSV.
- Die Qualitätsschranke von 15 % ist auf synthetischen Daten gemessen. Auf echten Daten liegt der
  Mittelwert bei 15 %, einzelne Nutzer liegen darunter.

## Bekannte Grenzen

- Oben in der Liste stehen mit den vorgegebenen Parametern auch wenig bekannte Filme mit 5 bis 9
  Zwillingen (in einem Test mit 400 Bewertungen: 31 % der Top 100). Mit dem Filter „Mindestens
  Zwillinge“ 20 verschwinden sie. Anbieterdaten gibt es nur für die besten 3000 Kandidaten, mit
  dem Standard-Anbieterfilter sieht man also nur Filme aus diesem Bereich.
- MovieLens reicht bis Oktober 2023. Neuere Filme erscheinen nur im Abschnitt „Neu seit Ende
  2023“, ohne persönliche Vorhersage.
- Der Download von files.grouplens.org scheitert mit aktuellen Zertifikatslisten (emSign-Root
  fehlt). Die App erklärt den manuellen Weg (`setup --zip`).
- Daumen-Bewertungen für Serien (Ratings.csv enthält auch Serientitel) erzeugen einen
  Importeintrag. Findet TMDB einen gleichnamigen Film, landet dieser in der Warteschlange.
- Die erste Verfügbarkeitsabfrage für 3000 Kandidaten dauert gut zwei Minuten. Bis sie fertig ist,
  zeigt der Standard-Anbieterfilter weniger Filme.
- Die App hat keine Anmeldung. `serve --host 0.0.0.0` nur im eigenen Netz benutzen.
- Die Liste der bereits verarbeiteten `client_id` liegt im Speicher. Nach einem Neustart des
  Servers wird eine noch einmal zugestellte Aktion erneut ausgeführt (praktisch nur, wenn der
  Server genau während des Bewertens neu startet).

## Sinnvolle nächste Schritte

1. Einen echten Prime-Export mit `import inspect` prüfen und die Aliasliste in
   `importers/header_aliases.py` um die echten Spaltennamen ergänzen.
2. Nach etwa 300 eigenen Bewertungen `filmzwilling evaluate` laufen lassen und mit anderen
   Werten für k, shrinkage und prior_weight vergleichen (alle in `RecommenderConfig`). Ein
   kleiner Parameter-Suchlauf über `cross_validate` wäre wenig Aufwand.
3. Für die Sortierung eine Variante anbieten, die unsichere Vorhersagen nach unten schiebt (zum
   Beispiel nach der Untergrenze eines Konfidenzintervalls statt nach dem Punktwert).
