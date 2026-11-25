# Filmzwilling

Filmzwilling ist eine persönliche Film-Empfehlungs-App, die lokal auf dem eigenen Rechner läuft.
Die Empfehlungen kommen von „Geschmackszwillingen“: Menschen aus dem MovieLens-32M-Datensatz, die
Filme ähnlich bewertet haben wie du. Was sie mochten und du noch nicht kennst, landet oben auf der
Liste. Die Liste lässt sich nach deinen Streamingdiensten, Gratisangeboten (Joyn, Mediatheken) und
Genres filtern.

So läuft es ab:

1. Sehverläufe von Netflix, Prime Video und Disney+ importieren (mit mehreren Profilen, falls das
   Konto mit der Familie geteilt wird).
2. Auf einer schnellen Bewertungsseite rund 1000 Filme mit 0 bis 10 bewerten oder als „nicht
   gesehen“ markieren. Die Tastatur reicht dafür, eine Hand bleibt am Ziffernblock.
3. Die Empfehlungen ansehen, sortiert nach der vorhergesagten Note und gefiltert nach Anbietern,
   Genres, Jahr und Laufzeit.

## Installation

Voraussetzungen: Python 3.11 oder neuer, etwa 1,5 GB freier Platz für MovieLens und 4 GB
Arbeitsspeicher für die einmalige Aufbereitung (8 GB im Rechner reichen).

```bash
git clone <repo-url> filmzwilling
cd filmzwilling
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

Danach gibt es den Befehl `filmzwilling`. Ausprobieren ohne Netz und ohne Token:

```bash
filmzwilling demo --open
```

Das startet die App mit erfundenen Filmen und Platzhalter-Postern in einem temporären Ordner.

## TMDB-Token

Titel auf Deutsch, Poster, Laufzeiten und die Streaming-Anbieter kommen von The Movie Database
(TMDB). Dafür brauchst du einen kostenlosen Lesezugriffstoken:

1. Konto auf https://www.themoviedb.org anlegen.
2. In den Kontoeinstellungen unter „API“ einen API-Zugang beantragen (persönliche Nutzung).
3. Den „API-Lesezugriffstoken“ (der lange Token, nicht der kurze API-Schlüssel) kopieren.

Dann im Projektordner die Vorlage kopieren und den Token eintragen:

```bash
cp .env.example .env
```

```ini
TMDB_READ_TOKEN=eyJhbGciOi...
# FILMZWILLING_DATA_DIR=./data
# FILMZWILLING_CA_BUNDLE=
```

Fehlt der Token, schickt die App die Anfragen ohne Anmeldung ab (in manchen Umgebungen hängt ein
Proxy den Token an). Antwortet TMDB mit 401, erscheint „TMDB-Token fehlt oder ist ungültig, siehe
README“. Die `.env` steht in `.gitignore` und wird nie committet.

## Erster Start

```bash
filmzwilling setup                                   # MovieLens laden, prüfen, aufbereiten
filmzwilling import netflix ~/Downloads/netflix-export
filmzwilling import prime ~/Downloads/PrimeVideo.ViewingHistory.csv
filmzwilling import csv ~/Downloads/disney.csv
filmzwilling tmdb-sync                               # Zuordnung, Metadaten, Anbieter
filmzwilling serve --open
```

`setup` lädt einmalig 239 MB von grouplens.org, prüft die MD5-Summe und bereitet die Daten auf
(auf einem Rechner mit 4 Kernen gut 10 Sekunden, Spitze etwa 2,5 GB Arbeitsspeicher). Ein zweiter Aufruf erkennt das und überspringt die Arbeit. `tmdb-sync` holt
die Anbieterliste für Deutschland, ordnet importierte Titel Filmen zu und lädt Metadaten für die
Warteschlange. Ohne `--limit` sind das gut 1000 Filme, bei 20 Anfragen pro Sekunde dauert das
etwa eine Minute. Die Daten werden 30 Tage (Anbieter 7 Tage) zwischengespeichert.

Beim Start von `serve` legt die App ein Backup deiner Bewertungen unter
`data/backups/ratings-JJJJ-MM-TT.csv` an und behält die letzten 14.

Danach in den Einstellungen festlegen, welche importierten Profile deine sind. Die übrigen gelten
als Familienprofile und kommen in der Warteschlange später dran.

## Sehverläufe anfordern und importieren

Die Wege zu den Exporten ändern die Anbieter gelegentlich. Stand beim Schreiben dieser Anleitung:

**Netflix, vollständiger Datenexport.** Im Browser unter Konto, „Sicherheit und Datenschutz“,
„Persönliche Daten herunterladen“ (https://www.netflix.com/account/getmyinfo) anfordern. Netflix
schickt nach einigen Tagen eine Mail mit einem ZIP. Entpacken und den ganzen Ordner importieren:

```bash
filmzwilling import netflix ~/Downloads/netflix-report
```

Gelesen werden `CONTENT_INTERACTION/ViewingActivity.csv` (alle Profile, mit Dauer und Position)
und, falls vorhanden, `Ratings.csv` (Daumen-Bewertungen als Hinweis auf der Bewertungskarte).
Trailer, Vorschauen, Serienfolgen und kurz angespielte Titel (unter 2 Minuten) fallen weg.

**Netflix, einfacher Titelverlauf.** Im Profil unter „Titelverlauf“
(https://www.netflix.com/viewingactivity) ganz unten „Alle herunterladen“. Die Datei
`NetflixViewingHistory.csv` enthält nur Titel und Datum eines Profils, deshalb den Profilnamen
angeben:

```bash
filmzwilling import netflix NetflixViewingHistory.csv --profile Florian
```

**Amazon Prime Video.** Bei Amazon unter Konto, Datenschutz, „Ihre Daten anfordern“ die
Kategorie Prime Video anfordern. Im ZIP liegen Ordner wie `PrimeVideo.ViewingHistory` und
`PrimeVideo.WatchEvent` mit CSV-Dateien. Das genaue Format ist nicht dokumentiert, deshalb erkennt
der Importer die Spalten an ihren Namen. Erst nachsehen, was er erkennt:

```bash
filmzwilling import inspect PrimeVideo.ViewingHistory.csv
filmzwilling import prime PrimeVideo.ViewingHistory.csv
```

Liegt `inspect` daneben, eine Datei `mapping.toml` anlegen und mitgeben (die Spaltennamen hier
sind nur ein Beispiel, maßgeblich ist die Ausgabe von `inspect`):

```toml
[columns]
title = "Title"
date = "Playback Start Datetime (UTC)"
profile = "Profile Name"
duration = "Playback Duration"
position = "Playback Offset"

[units]
duration = "ms"        # seconds, ms, minutes oder auto (auto versteht auch HH:MM:SS)
position = "ms"

[defaults]
profile = "Prime Video"
```

```bash
filmzwilling import prime PrimeVideo.ViewingHistory.csv --mapping mapping.toml
```

Die CSV- und JSON-Ausgabe des Browser-Skripts „watch-history-exporter-for-amazon-prime-video“
(liest den Verlauf auf primevideo.com aus) versteht derselbe Befehl.

**Disney+ und alles andere.** Disney+ bietet keinen Download des Verlaufs an. Eine
DSGVO-Auskunft lässt sich beim Disney-Datenschutz anfordern, ihr Format ist unbekannt. Am
einfachsten ist eine eigene Liste, zum Beispiel in einer Tabellenkalkulation, gespeichert als CSV:

```csv
title,year,profile,watched_fraction
Soul,2020,Kinder,
Das Leben der Anderen,2006,Florian,1
Encanto,,,85%
```

Nur `title` ist Pflicht. `year` hilft bei Remakes, `profile` ordnet die Zeile einem Profil zu
(sonst „Manuell“), `watched_fraction` ist der gesehene Anteil (0,85, 0.85, „85 %“ oder 85).
Komma oder Semikolon als Trennzeichen gehen beide.

```bash
filmzwilling import csv disney.csv
```

Jeder Import ist wiederholbar: Dieselbe Datei ein zweites Mal erzeugt keine doppelten Einträge,
ein neuerer Export aktualisiert die vorhandenen.

**Zuordnung.** Titel, die keinem Film sicher zugeordnet werden konnten, stehen auf der Seite
„Zuordnung“. Dort den richtigen Film suchen oder „Ignorieren“ klicken.

## Bewerten

Die Startseite zeigt immer einen Film. Der nächste erscheint sofort, die Speicherung läuft im
Hintergrund. Klappt sie nicht (WLAN weg), bleiben die Aktionen in einer Warteschlange und werden
wiederholt. Beim Verlassen der Seite schickt der Browser offene Aktionen noch ab.

| Taste | Aktion |
|---|---|
| `0` bis `9` | Note 0 bis 9 |
| `+` (auch Ziffernblock) oder `Z` | Note 10 |
| Leertaste | nicht gesehen |
| `S` | später (ans Ende) |
| Backspace | rückgängig (auch mehrmals) |
| `T` | Trailer abspielen |

Die Tasten wirken nicht, solange ein Eingabefeld aktiv ist. Bei abgebrochenen Filmen steht auf
der Karte zum Beispiel „Abgebrochen bei 28 % (34 von 121 Min.), Profil Florian“, und die Buttons
0 bis 4 sind leicht hervorgehoben. Bewertet wird nie automatisch.

Reihenfolge der Warteschlange: zuerst Filme, die du zu Ende geschaut hast (neueste zuerst), dann
abgebrochene oder unklare, dann Filme aus Familienprofilen, dann die meistbewerteten Filme aus
MovieLens (Standard 1000, in den Einstellungen änderbar).

Bewerten auf dem Handy im WLAN:

```bash
filmzwilling serve --host 0.0.0.0
```

Dann auf dem Handy `http://<IP-des-Rechners>:8000` öffnen. Die App hat keine Anmeldung, also nur
im eigenen Heimnetz so starten.

## Trailer

Auf der Bewertungsseite, in den Empfehlungen (Kachel oder Detailansicht) und unter „Meine
Bewertungen“ startet „Trailer“ den Film-Trailer direkt in der App. Die Trailer kommen über TMDB
(deutsche zuerst, dann englische), der Stream kommt von YouTube (eingebettet über
youtube-nocookie.com, ohne YouTube-Bedienelemente). Gibt es mehrere, wechselst du oben im Player.

| Taste | Aktion im Player |
|---|---|
| Leertaste oder `K` | Abspielen/Pause |
| `←` `→` oder `J` `L` | 10 Sekunden zurück/vor |
| `↑` `↓` | Lautstärke |
| `M` | Ton an/aus |
| `F` | Vollbild |
| `N` | nächster Trailer |
| Esc | schließen |

Ohne Netz (oder im Demo-Modus) gibt es keine Trailer. Manche Studios verbieten das Einbetten;
dann springt der Player zum nächsten Trailer oder bietet als letzten Ausweg den Link zu YouTube an.

## Controller

Ein Gamepad (Xbox, PlayStation, Switch Pro, alles mit Standard-Belegung im Browser) wird
erkannt, sobald du im Browserfenster eine Taste drückst. Oben rechts erscheint dann ein
Controller-Symbol.

| Taste | Aktion |
|---|---|
| Steuerkreuz oder linker Stick | Auswahl bewegen (auf der Bewertungsseite startet sie bei Note 5) |
| A (Kreuz) | auswählen, bewerten |
| B (Kreis) | zurück, schließen; beim Bewerten rückgängig |
| X (Quadrat) | nicht gesehen |
| Y (Dreieck) | Trailer |
| RT | später |
| LB / RB | vorherige / nächste Seite |
| Start | Filter öffnen/schließen (Empfehlungen), X setzt sie zurück |
| rechter Stick | scrollen |
| Select / View | Hilfe mit der Belegung |

Im Trailer: A oder Start Pause, links/rechts 10 Sekunden, LT/RT 30 Sekunden, hoch/runter
Lautstärke, X Ton, Y Vollbild, LB/RB Trailer wechseln, B schließen.

## Empfehlungen

Ab 30 eigenen Bewertungen erscheint eine Liste. Neu berechnet wird per Knopf, mit
`filmzwilling recommend` und automatisch im Hintergrund nach je 25 neuen Bewertungen. Die
Berechnung dauert mit dem vollen Datensatz etwa 2 Sekunden.

Oben laufen die fünf besten Empfehlungen als großes Banner durch. Jede Kachel zeigt das Poster
mit der vorhergesagten Note (zum Beispiel „8,7“) und den Anbietern, darunter Titel, Jahr,
Laufzeit und wie viele Zwillinge den Film bewertet haben. Ein Klick öffnet die Detailansicht mit
Handlung, Trailer, Bewerten und „Kein Interesse“. Die Filter öffnest du mit „Filter“ (am Controller mit Start). Anbieter, Genres und Sortierung sind
große Schaltflächen zum Antippen, die Zahlenfilter haben −/+ Knöpfe (leer heißt „egal“, der erste
Druck springt auf einen sinnvollen Startwert, unter dem Minimum wird das Feld wieder leer). Filter (Anbieter, Genres mit
ODER oder UND, Mindest-Match, Mindestzahl Zwillinge, Jahr, Laufzeit, Leihen und Kaufen) stehen in
der URL, ein Lesezeichen behält sie. Ein Tipp: Mit „Mindestens Zwillinge“ 20 verschwinden
Exoten, die nur wenige Leute gesehen haben.

Unter „Zwillinge“ führt jede Karte zur Seite dieses Zwillings: alle seine MovieLens-Bewertungen
als Poster-Raster (seine Note oben links, deine oben rechts, falls du den Film bewertet hast), mit
Notenverteilung, Auswahl „Alle / Neu für dich / Gemeinsam“ und Sortierung. „Neu für dich“ mit
„Beste zuerst“ ist eine gute Fundgrube. Ein Film öffnet die Detailansicht mit Trailer und Bewerten,
am Controller spielt Y den Trailer und B führt zurück zur Übersicht.

Der Abschnitt „Neu seit Ende 2023“ zeigt Filme, die nach dem Stand von MovieLens erschienen sind.
Für sie gibt es keine Zwillingsdaten, sie sind nach TMDB-Note sortiert.

„So gut kennt dich die App“ in den Einstellungen (oder `filmzwilling evaluate`) versteckt
reihum ein Fünftel deiner Bewertungen, sagt sie vorher und vergleicht mit dem einfachen
Filmdurchschnitt.

## Befehle

| Befehl | Zweck |
|---|---|
| `filmzwilling setup [--zip DATEI] [--md5 SUMME]` | MovieLens laden, prüfen, aufbereiten |
| `filmzwilling tmdb-sync [--limit N]` | Zuordnung, Metadaten, Anbieter, Neuerscheinungen |
| `filmzwilling import netflix PFAD [--profile NAME]` | Netflix-Export importieren |
| `filmzwilling import prime PFAD [--mapping DATEI]` | Prime-Video-Verlauf importieren |
| `filmzwilling import csv PFAD` | eigene Liste importieren |
| `filmzwilling import inspect PFAD [--mapping DATEI]` | erkannte Spalten anzeigen |
| `filmzwilling serve [--host H] [--port P] [--open]` | Weboberfläche starten |
| `filmzwilling recommend` | berechnen und Top 20 zeigen |
| `filmzwilling evaluate` | Selbsttest |
| `filmzwilling check "Titel" [--year J]` | Film in MovieLens? Rang? In der Warteschlange? |
| `filmzwilling export-ratings DATEI` | Bewertungen als CSV |
| `filmzwilling demo [--no-serve]` | Demo mit synthetischen Daten |

Alle Befehle nehmen `--data-dir`. Standard ist `./data` oder `FILMZWILLING_DATA_DIR`.

## Fehlerbehebung

**Zertifikatsfehler beim MovieLens-Download.** Der Server files.grouplens.org nutzt ein
Root-Zertifikat (emSign Root CA - G1), das neuere Zertifikatslisten nicht mehr enthalten. Dann
bricht `setup` mit einer Anleitung ab. Lösung: https://files.grouplens.org/datasets/movielens/ml-32m.zip
im Browser laden und

```bash
filmzwilling setup --zip ~/Downloads/ml-32m.zip
```

aufrufen. Die MD5-Summe wird trotzdem geprüft. Alternativ eine CA-Datei mit dem fehlenden
Zertifikat über `FILMZWILLING_CA_BUNDLE` angeben.

**„TMDB-Token fehlt oder ist ungültig“.** Den Lesezugriffstoken (nicht den API-Schlüssel) in die
`.env` eintragen, siehe oben.

**Offline arbeiten.** Mit `FILMZWILLING_OFFLINE=1` fragt die App TMDB nie an.

## Daten und Lizenzen

Alles liegt in `./data/` (MovieLens, Datenbank, Backups) und steht in `.gitignore`. MovieLens-Dateien,
Datenbanken, Exporte und Tokens gehören nicht ins Repository.

**MovieLens 32M** (GroupLens Research, University of Minnesota) darf nur für persönliche, nicht
kommerzielle Zwecke genutzt und nicht weitergegeben werden. Quelle: F. Maxwell Harper und Joseph
A. Konstan, „The MovieLens Datasets: History and Context“, ACM Transactions on Interactive
Intelligent Systems 5(4), 2015.

**TMDB:** Diese App nutzt die TMDB-API, wird aber nicht von TMDB unterstützt oder zertifiziert.
Es gelten die Nutzungsbedingungen der TMDB-API.

**JustWatch:** Die Streaming-Verfügbarkeit liefert TMDB, die Daten stammen von JustWatch.

## Entwicklung

```bash
pytest                                     # Standardlauf
pytest -m slow                             # Performance (20.000 Nutzer × 3.000 Filme)
pytest -m e2e                              # Browser-Test, braucht Playwright für Node
FILMZWILLING_REAL_DATA=1 pytest -m real_data -s   # echte Daten in ./data
node --test tests/js/
ruff check . && ruff format --check .
mypy src
pytest --cov=filmzwilling --cov-report=term-missing
```

Aufbau und Konventionen stehen in `CLAUDE.md`, getroffene Entscheidungen in
`docs/ENTSCHEIDUNGEN.md`, der Stand in `docs/BERICHT.md`.
